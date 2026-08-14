---
name: review-flaggems-pr
description: 对 FlagGems PR 运行所有相关的可编程检查（is_cuda、排序、block_size、skipif、code-style、python-op），诊断问题后提出修复方案，经用户 review 确认后执行修复
---

# Review FlagGems PR

对指定的 FlagGems PR 运行所有相关的可编程检查，根据 PR 的实际改动智能选择检查项。发现问题后提出修复方案并标注风险等级，经用户 review 确认后再执行 —— 任何改动执行前都需人工确认，无例外。

## 工作流程

1. **获取 PR 信息**
   ```bash
   gh pr view <PR> --repo flagos-ai/FlagGems --json files,number,headRefName
   ```
   获取改动的文件列表，判断需要运行哪些检查。

2. **智能选择检查项**
   根据改动的文件类型自动决定：
   - 改了 `src/flag_gems/ops/` 或 `src/flag_gems/fused/` 的 `.py` → `is_cuda` 检查 + `block_size` 检查
   - 改了 `tests/` 下的 `.py` → `skipif` 检查
   - 改了 `__init__.py` → `init_registration` 检查
   - 改了 `operators.yaml` → `operators_yaml` 检查
   - 改了任何 `.py` 文件 → `code_style` 检查

3. **并行执行检查**
   所有适用的检查可以并行运行，加速流程。

4. **处理结果并修复**
   **所有**检查发现的问题都走同一个流程，没有例外 —— 任何改动执行前都必须先经用户确认：
   - **诊断**：Agent 读取相关源码，分析每个问题的根因
   - **提出方案 + 标注风险**：向用户展示每处改动和理由，并给出**风险等级**：
     - 🟢 **无风险**：幂等、确定性的机械改动（排序、black/isort 格式化）
     - 🟡 **低风险**：局部逻辑改动（删除 skipif、补 import、改测试断言）
     - 🔴 **高风险**：影响算子实现语义、跨芯片行为的改动
   - **等待 human review**：用户 review 方案后才执行，**不做无声 auto-fix，也没有"零风险直接改"的例外**
   - **执行 + 验证**：修复后重跑对应检查确认清零

5. **生成报告**
   清晰汇总哪些通过、哪些方案待用户确认、确认后哪些已修复。

## 可用的检查工具

所有工具位于 `/Users/yufan.shi/Desktop/PR-Review/scripts/`：

### 1. is_cuda 滥用检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_is_cuda.py <PR> --json
```
- **检查内容**：算子代码中是否使用了 `is_cuda`（违反跨芯片兼容原则）
- **适用条件**：改动了 `src/flag_gems/ops/` 或 `src/flag_gems/fused/` 下的算子
- **修复流程**：Agent 诊断 → 提出方案 → 用户确认 → 执行
- **退出码**：0=clean, 1=has_violations
- **输出格式**：JSON（`--json`）或人类可读

**为什么重要**：FlagGems 目标是跨芯片兼容（NVIDIA + 国产芯片），`is_cuda` 把代码限制在 NVIDIA，maintainer 明确表示 "is_cuda is invalid for non NV chips"。

### 2. __init__.py 注册顺序检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_init_registration.py <PR> --json
```
- **检查内容**：`__all__` 列表是否按字母序排列
- **适用条件**：改动了 `__init__.py` 文件
- **修复流程**：排序改动（🟢 无风险）→ 提出方案标注风险 → 用户确认 → 执行
- **退出码**：0=clean, 1=needs_fix

**修复方法**：
```python
# 读取 __init__.py
# 找到 __all__ = [...] 
# 提取列表内容，按字母序排序（大小写敏感）
# 写回文件，保持原格式（单行/多行）
```

### 3. operators.yaml 排序检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_operators_yaml.py <PR> --json
```
- **检查内容**：算子 ID 是否按字母序排列
- **适用条件**：改动了 `operators.yaml`
- **修复流程**：排序改动（🟢 无风险）→ 提出方案标注风险 → 用户确认 → 执行
- **退出码**：0=clean, 1=needs_fix

**修复方法**：
```python
# 用 PyYAML 读取
# 按 key（算子 ID）排序
# 写回，保持格式
```

### 4. Code-style 检查和修复（两阶段模式）

**Phase 1: 计算修复方案（dry-run）**
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/fix_code_style_v2.py dry-run <PR> --json
```
- **检查内容**：black、isort、flake8、mypy
- **适用条件**：改动了任何 `.py` 文件
- **输出**：JSON 格式包含
  - `status`: 'clean' | 'fixable' | 'needs_human'
  - `mechanical_diff`: 机械修复的 diff（black/isort/eof）
  - `agent_diff`: Agent 修复的 diff（flake8/mypy）
  - `risk_levels`: 每个文件的风险等级（'green' | 'yellow'）
  - `state_file`: 状态文件路径，用于 phase 2

**Phase 2: 应用修复（apply）**
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/fix_code_style_v2.py apply <state_file>
```
- **输入**：Phase 1 生成的状态文件
- **行为**：在临时 clone 里 commit 修复（不自动 push）
- **输出**：commit SHA 列表 + push 指令

**修复流程（遵循统一原则）**：
1. **Phase 1 (propose)**: dry-run 计算修复，输出 diff + 风险标注
2. **Human review**: Agent 向用户展示修复方案并标注风险
   - 🟢 **无风险**: black/isort/eof 机械格式化
   - 🟡 **低风险**: flake8/mypy Agent 修复（删 import、断行、补类型）
3. **Phase 2 (fix)**: 用户确认后，apply 执行 commit
4. **Verify**: 重跑 pre-commit 确认清零

**退出码**：0=clean/fixable, 1=needs_human, 2=error

**关键**: 此检查现在完全遵循统一原则 **detect → propose → approve → fix → verify**，与其他检查一致。

### 5. BLOCK_SIZE 硬编码检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_block_size.py <PR> --json
```
- **检查内容**：`@triton.jit` kernel **函数体内** `tl.arange(0, <整数字面量>)` 硬编码，且该 kernel 声明了名称含 BLOCK/SIZE/TILE 的 `tl.constexpr` 参数
- **适用条件**：改动了 `src/flag_gems/ops/` 或 `src/flag_gems/fused/` 下的算子
- **修复流程**：Agent 诊断（确认 kernel 声明了哪个 constexpr 参数）→ 提出方案 → 用户确认 → 执行
- **退出码**：0=clean, 1=has_violations
- **输出格式**：JSON（`--json`）或人类可读

**为什么重要**：`@triton.jit` 标记的是 GPU kernel 本身。kernel 声明 `BLOCK_SIZE: tl.constexpr` 是为了让 Triton 针对不同 tile 尺寸编译多个特化版本。如果 kernel 体内用 `tl.arange(0, 1024)` 写死字面量，就绕过了这个机制，constexpr 参数形同虚设，Triton 只能编译单一版本。

**⚠️ 检查范围（重要）**：
- ❌ **只查 `@triton.jit` kernel 函数体内的字面量** —— 这是真问题
- ✅ **launcher / host 代码里 `BLOCK_SIZE = 1024` 是合法的** —— 它只是决定调用哪个已特化的 kernel variant，不报
- ✅ **模块级常量 `BLOCK_SIZE = 1024` 合法** —— 同理，不报
- ✅ **kernel 没有 constexpr 参数时** —— 字面量合理，不报

**问题模式**：
```python
# ❌ kernel 体内写死，忽略了声明的 constexpr 参数
@triton.jit
def my_kernel(x_ptr, out_ptr, n_elements, BLOCK_SIZE: tl.constexpr):
    offsets = tl.arange(0, 1024)  # ← 应该用 BLOCK_SIZE
```

**正确模式**：
```python
# ✅ kernel 体内使用声明的 constexpr 参数
@triton.jit
def my_kernel(x_ptr, out_ptr, n_elements, BLOCK_SIZE: tl.constexpr):
    offsets = tl.arange(0, BLOCK_SIZE)

# ✅ launcher 里 hardcode 完全允许（host 代码，决定调哪个特化版本）
def launcher(x, out):
    BLOCK_SIZE = 1024
    grid = (triton.cdiv(x.numel(), BLOCK_SIZE),)
    my_kernel[grid](x, out, x.numel(), BLOCK_SIZE=BLOCK_SIZE)
```

### 6. pytest.mark.skipif 检查

```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_skipif.py <PR> --json
```
- **检查内容**：测试中新增的 `@pytest.mark.skipif` 装饰器
- **适用条件**：改动了 `tests/` 下的测试文件
- **能否自动修复**：❌ 需 Agent 分析和人工确认
- **退出码**：0=clean, 1=has_violations
- **输出格式**：JSON（`--json`）或人类可读

**为什么重要**：AI 写测试时可能偷懒加 `skipif` 跳过失败的测试，而不是修复真正的问题。特别是 vendor-specific skipif 违反 FlagGems 跨芯片兼容目标。

**问题分类**：
```python
# 🔴 CRITICAL - vendor-specific skipif
@pytest.mark.skipif(flag_gems.vendor_name == "metax", reason="not working")
# → 违反跨芯片兼容原则，应修复算子实现而不是跳过测试

# 🔴 CRITICAL - CUDA-specific skipif
@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
# → 硬编码 CUDA 依赖，应使用 flag_gems.device

# 🟡 WARNING - lazy skipif
@pytest.mark.skipif(True, reason="TODO: fix later")
# → 永远跳过测试 = 测试无意义，应直接删除

# 🟢 INFO - reasonable (可能合理，需人工确认)
@pytest.mark.skipif(TE_OP is None, reason="TransformerEngine not installed")
# → 依赖检查，可能是合理的前提条件
```

#### 核心原则：reason 是「主张」，不是「证据」

skipif 的分类只分两步（脚本已按此实现）：
1. **没有 reason** → 明确错误，直接删除。
2. **有 reason** → 标记为 `needs_verification`，**必须验证 reason 是否真的成立**，不能因为写了 reason 就放过。

脚本会为每个带 reason 的 skipif 输出：
- `issue_ref` / `operator`：从 reason 提取的 issue 号、从文件名推导的算子名
- `verification_checklist`：逐条要核对的点
- `timeline`：**自动**拉取 issue 与 PR 的创建时间做对比，给出 `verdict`
  （`reason_invalid` / `timeline_ok` / `unknown`）

#### 验证 reason 的三个校验点（按此顺序逐条排查）

1. **算子名匹配**：issue 是否真的把这个算子列为不支持？
   近似名不算匹配。
   > 校准案例 **PR #5399**：reason 引用 Issue #5254，但该 issue 列的是
   > `special_chebyshev_polynomial_**w**`，PR 是 `_**t**` 变体 —— 名称对不上，reason 不成立。

2. **时间线（机械可判定，脚本已自动完成）**：issue 创建时间是否早于 PR？
   **早于 PR 的 issue 不可能描述本 PR 新增的实现 —— 因果倒置，reason 不成立。**
   看脚本输出的 `timeline.verdict`：
   - `reason_invalid` → 因果倒置，判错
   - `timeline_ok` → 时间上可能覆盖，继续核对算子名与 issue 内容
   - `unknown` → 时间戳拉取失败，人工核对
   > 校准案例 **PR #5290**：reason 引用 Issue #4131（2026-06 创建，基于更早的
   > PR #3782 旧 backend），PR 是 2026-08 才新增的 convolution Triton kernel。
   > 一个 6 月的 issue 覆盖不了 8 月的新实现 —— 判错。

3. **issue 质量与状态**：issue 描述是否清晰、是否被维护者质疑、state 是否仍 OPEN、
   是否只是测试基准问题（如标题 "failed without --ref cpu" 其实是 `--ref` 配置问题，
   而非算子真的不支持）。描述含糊或问题性质对不上，不足以支撑跳过整个测试。

**结论逻辑**：三点中任何一点不成立 → reason 不成立 → 删除 skipif。
三点全部成立才可保留，且需在报告中注明「保留但需跟踪 issue 修复进度」。

#### 终判分流：哪些不用 agent 看，哪些必须看

脚本的 `auto_verdict` / `needs_agent_verification` 只决定 **agent 要不要额外读 issue 去验证**，
**不决定要不要汇报和是否直接改**。无论哪种结论，所有 skipif 的删除动作都统一走
「汇总 → 向用户展示方案和理由 → 等用户确认 → 执行 → 重跑验证」，不做无声 auto-fix。

| auto_verdict | needs_agent_verification | 含义 | agent 的验证工作量 |
|---|---|---|---|
| `confirmed_error` | `false` | 无 reason，或时间线倒置（issue 早于 PR） | **无需读 issue**，脚本已给出足够依据，直接把「建议删除」写进待确认方案 |
| `pending` | `true` | 时间线未证伪（issue 晚于/接近 PR，或无 issue 号，或时间戳拉取失败） | **需读 issue**，核对算子名 + issue 内容/状态，得出结论后再写进待确认方案 |

- **时间线倒置 = 逻辑硬事实**：issue 比 PR 还早，代码那时都不存在，issue 不可能在描述本 PR 的新实现 → 脚本可直接给出「确认错误」的依据，agent 不用再花力气读 issue 正文。
- **其余的仍需 agent 验证**：脚本只能判时间线，算子名语义匹配、issue 描述质量/状态这些要读内容才能定，交给 agent。
- **两种结论都要汇报**：`confirmed_error` 省掉的是 agent 的验证成本，不是用户的知情权和确认权。方案里如实标注每个 skipif 是「脚本已确认」还是「agent 核对后确认」，最终都由用户拍板。

`summary` 里也有汇总：`confirmed_error`（已定案的错误数）和 `needs_agent_verification`（还需 agent 核对的数量），供组织报告用。

### 7. python-op CI 检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_python_op.py <PR> --json
```
- **检查内容**：PR 的 CI 中 `python-op` job 是否失败，并提取完整失败日志
- **适用条件**：始终运行（不依赖改动文件类型）
- **能否自动修复**：❌ 需 Agent 分析日志 + 读 PR 代码后提出方案，人工确认
- **退出码**：0=passed/skipped, 1=failed
- **输出格式**：JSON（`--json`）或人类可读

**工作流程**：
1. **脚本职责（detect）**：
   - 判断 python-op job 是否失败
   - 提取每个失败测试的完整日志上下文（error message + traceback + 周围输出）
   - 输出 JSON 包含 `failures` 数组，每项有 `file`、`test`、`error_type`、`error_message`、`log_context`

2. **Agent 职责（propose）**：
   - 读取脚本输出的 `log_context`（完整日志，不依赖预分类）
   - 读取 PR 改动的代码，定位根因
   - 综合日志 + 代码 + 外部上下文（如 reviewer 意图），提出具体修复方案

3. **人工确认（approve）**：
   - Agent 向用户展示方案 + 理由
   - 用户确认后再执行

**过期日志处理**：CI 日志在 Azure Blob 上保存约 90 天。若日志已过期，输出 `logs_unavailable: true` 并附上 Job URL 供人工查看。

## 执行策略

### Step 1: 读取 PR 信息
```bash
gh pr view <PR> --repo flagos-ai/FlagGems --json files,headRefName,headRepository
```

提取：
- 改动的文件列表
- head 分支名
- 是否是 fork

### Step 2: 判断需要的检查
```python
checks_needed = []

for file in changed_files:
    if file.startswith("src/flag_gems/ops/") or file.startswith("src/flag_gems/fused/"):
        if file.endswith(".py"):
            checks_needed.append("is_cuda")
            checks_needed.append("block_size")
    
    if file.startswith("tests/") and file.endswith(".py"):
        checks_needed.append("skipif")
    
    if file.endswith("__init__.py"):
        checks_needed.append("init_registration")
    
    if file == "operators.yaml":
        checks_needed.append("operators_yaml")
    
    if file.endswith(".py"):
        checks_needed.append("code_style")

# python-op CI 检查（始终运行，不依赖改动文件类型）
checks_needed.append("python_op")

checks_needed = list(set(checks_needed))  # 去重
```

### Step 3: 并行运行检查
如果有多个检查，可以并行执行节省时间：
```bash
# 示例：同时跑 is_cuda、block_size 和 init_registration
python3.11 check_is_cuda.py <PR> --json &
python3.11 check_block_size.py <PR> --json &
python3.11 check_init_registration.py <PR> --json &
wait
```

### Step 4: 处理结果

#### is_cuda 违规
1. 读取违规的算子文件，理解上下文
2. 提出修复方案（例：移除 `is_cuda` 检查，或改用 `x.device.type == runtime.device.name`）
3. 向用户说明每处改动的理由，**等用户确认后再执行**
4. 执行修复，重跑 `check_is_cuda.py` 验证清零

#### block_size 硬编码（kernel 体内）
1. 读取违规文件，确认 kernel 声明了哪个 `tl.constexpr` 参数（BLOCK_SIZE / TILE 等）
2. 提出修复方案：把 kernel 体内 `tl.arange(0, <字面量>)` 改用对应的 constexpr 参数（例：`tl.arange(0, BLOCK_SIZE)`）
3. 向用户说明每处改动，**等用户确认后再执行**
4. 执行修复，重跑 `check_block_size.py` 验证清零

> 注意：launcher / 模块级的 `BLOCK_SIZE = <literal>` 不是违规，脚本不会报，也不需要改。

#### skipif 问题
1. 汇总所有 skipif 问题（按 critical/warning/info 分组）
2. 读取相关算子代码，分析每个 skipif 的根因
3. 提出修复方案（例：critical 的 vendor_specific → 删除 skipif + 修复算子实现；lazy → 直接删除装饰器）
4. 向用户展示完整方案，**等用户确认后再执行**
5. 执行修复，重跑 `check_skipif.py` 验证清零

#### python-op CI 失败
1. **读取脚本输出**：check_python_op.py 提取了完整的 `log_context`（error message + traceback + 周围输出）
2. **Agent 分析日志**：读 `log_context`，判断错误类型（ImportError/NameError/AssertionError/shape_mismatch 等）
3. **读取 PR 代码**：定位 PR 改动的相关文件，结合日志理解根因
4. **提出修复方案**：基于日志 + 代码分析，给出具体修复步骤（例：补 import、修函数定义对齐、修算子实现、修测试断言）
5. **向用户展示方案**，标注风险等级，**等用户确认后再执行**
6. 执行修复，提示重新触发 CI 验证
7. `logs_unavailable` 时：告知日志已过期，提供 Job URL，让用户手动确认失败类型后再走上述流程

#### 排序问题（__init__.py 或 operators.yaml）
1. Clone PR 仓库到临时目录，读取文件算出排序后的结果
2. **向用户展示 diff，标注 🟢 无风险（幂等排序），等确认**
3. 确认后：写回 → 重跑检查脚本验证（退出码应为 0）
4. 生成 commit（但不自动 push）

#### code-style 问题（两阶段模式）
1. **Phase 1 (dry-run)**: 调用 `fix_code_style_v2.py dry-run <PR> --json` 计算修复方案
2. **展示方案**: 向用户展示 mechanical_diff 和 agent_diff，标注风险等级（机械 🟢 / Agent 🟡）
3. **Phase 2 (apply)**: 用户确认后，调用 `fix_code_style_v2.py apply <state_file>` 执行 commit
4. **验证**: 脚本自动重跑 pre-commit 验证清零

根据 Phase 1 返回状态：
  - `clean`：首次运行全绿，无需修复
  - `fixable`：有修复方案，按上述流程走
  - `needs_human`：无法自动修，报告阻塞的 hooks

### Step 5: 生成 Review 阶段报告

在完成所有检查、分析问题、提出修复方案后，生成待确认方案报告：

```bash
# 准备检查结果 JSON
cat > checks-result.json << 'EOF'
{
  "_meta": {"pr": "5395", "repo": "flagos-ai/FlagGems", "branch": "fix/add-convolution"},
  "is_cuda": {"status": "passed", "violations": []},
  "skipif": {"status": "failed", "violations": [...]},
  "code_style": {"status": "fixable", "mechanical_files": [...], "agent_files": [...]}
}
EOF

# 生成报告
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/generate_report.py \
  single-review 5395 \
  --repo flagos-ai/FlagGems \
  --branch fix/add-convolution \
  --checks checks-result.json \
  --output reports/PR-5395-review.md
```

**报告内容**（示例）：
```markdown
# PR #5395 待修复方案

检查结果表格（通过/需修复/问题数）
待确认修复方案（按风险等级分组）
无法自动修复的问题
确认执行？ [yes/no]
```

向用户展示报告内容并等待确认。

### Step 6: 执行修复并生成最终总结

用户确认后：
1. 执行所有修复（在临时目录）
2. 验证修复（重跑检查全绿）
3. 生成 commits
4. 生成最终总结报告

```bash
# 准备修复结果 JSON
cat > fixes-result.json << 'EOF'
{
  "applied": [
    {"name": "skipif 违规修复", "files": ["tests/test_copy.py"]},
    {"name": "code-style 修复", "files": ["tests/test_add.py", "src/flag_gems/ops/add.py"]}
  ],
  "commits": [
    "abc123d: fix: remove vendor-specific skipif",
    "def456a: style: apply formatting"
  ],
  "needs_human": ["tests/test_add.py:15 undefined name"],
  "clone_dir": "/tmp/pr-fix-5395-xyz/repo"
}
EOF

# 生成最终总结
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/generate_report.py \
  single-final 5395 \
  --repo flagos-ai/FlagGems \
  --branch fix/add-convolution \
  --checks checks-result.json \
  --fixes fixes-result.json \
  --output reports/PR-5395-final.md
```

**报告内容**（示例）：
```markdown
# PR #5395 Review 总结

6 项检查，2 项通过，4 项已修复

修改内容
- skipif 违规修复: tests/test_copy.py
- code-style 修复: tests/test_add.py, src/flag_gems/ops/add.py

Commits: 2 个
验证: 全部通过

总结
- 已修复: 4 项
- 需人工处理: 1 项
- 下一步: cd /tmp/pr-fix-5395-xyz/repo && git push origin HEAD:fix/add-convolution
```

向用户展示最终报告，告知下一步操作。

### Step 7: 批量场景

如果同时审查多个 PR，使用批量报告模式：

```bash
# 假设已完成多个 PR 的检查，每个生成了 checks JSON
# checks/
#   PR-5395-checks.json
#   PR-5390-checks.json
#   PR-5388-checks.json

python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/generate_report.py \
  batch \
  --prs 5395 5390 5388 5387 \
  --checks-dir ./checks/ \
  --output reports/batch-2026-08-13.md
```

**报告内容**（示例）：
```markdown
# FlagGems PR 批量 Review 报告

总览表格（PR、分支、状态、问题数、风险等级）

统计
- 全部通过: 1 个
- 需修复: 3 个（其中高风险 1 个）
- 总问题数: 15 项

需关注的 PR
- 高风险: #5387（is_cuda 违规 3 处）
- 中风险: #5395（skipif 2 处）
- 低风险: #5388, #5390
```

批量报告提供聚合视图，高风险 PR 详细列出，低风险 PR 只列编号，避免信息过载。

## 安全边界

1. **只读操作**：
   - 所有检查都是只读的
   - 不修改用户的本地仓库

2. **隔离修复**：
   - 所有修复在临时 clone 里进行（`/tmp/flaggems-pr-<PR>-<random>`）
   - 不影响用户的工作目录

3. **人工确认（两道）**：
   - **改动前**：任何修复（含排序、机械 code-style 等零风险改动）落盘前，都先展示方案 + 风险等级，等用户 review 确认 —— 无例外
   - **push 前**：默认不自动 push，打印修改内容和 push 命令，用户确认后手动 push

4. **fail-closed**：
   - 修复后必须重跑检查全绿才生成 commit
   - 测试失败（如果启用）则放弃修复

5. **重试限制**：
   - Agent 修复每个文件最多 3 次
   - 失败后标记 `needs_human`，不强行修复

## 使用示例

### 单个 PR 审查流程

```bash
/review-flaggems-pr 5395

# Agent 会：
# 1. 读取 PR 5395 的文件列表
# 2. 判断需要跑哪些检查
# 3. 并行执行检查
# 4. 对所有问题（排序、code-style、is_cuda、block_size、skipif、python-op）
#    诊断根因、提出修复方案并标注风险等级
# 5. 生成 Review 阶段报告（待确认方案）
# 6. 等用户 review 确认后再执行修复，重跑检查验证清零
# 7. 生成最终总结报告
```

### 批量 PR 审查流程

```bash
/review-flaggems-pr --batch 5395 5390 5388 5387

# Agent 会：
# 1. 对每个 PR 并行执行所有检查
# 2. 生成批量聚合报告（总览表 + 风险分级）
# 3. 高风险 PR 详细展示，低风险 PR 只列编号
# 4. 根据用户选择，逐个或批量处理修复
# 5. 每个 PR 修复后生成独立的最终总结
```

## 注意事项

1. **首次运行慢**：`fix_code_style_v2.py` 首次运行会安装 pre-commit hooks（1-3 分钟），后续使用缓存。

2. **网络依赖**：需要克隆 PR 仓库，网络慢时可能耗时较长。

3. **Python 版本**：必须用 Python 3.11，确保与 FlagGems CI 一致。

4. **临时目录清理**：修复成功后保留临时目录供用户确认，失败或 clean 时自动清理。

5. **跨仓库 PR**：如果 PR 来自 fork，会克隆 fork 仓库（可能更慢）。

6. **报告文件**：
   - Review 阶段报告：`reports/PR-{number}-review.md`（待确认方案）
   - 最终总结报告：`reports/PR-{number}-final.md`（执行结果）
   - 批量报告：`reports/batch-{timestamp}.md`（聚合视图）
   - 所有报告文件保存在 `/Users/yufan.shi/Desktop/PR-Review/reports/`

## 扩展性

新增检查只需：
1. 在 `/Users/yufan.shi/Desktop/PR-Review/scripts/` 添加脚本
2. 更新本 skill 的"可用的检查工具"部分
3. 更新"判断需要的检查"逻辑
