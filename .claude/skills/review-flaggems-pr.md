---
name: review-flaggems-pr
description: 对 FlagGems PR 运行所有相关的可编程检查（is_cuda、排序、block_size、skipif、code-style、python-op），诊断问题后提出修复方案，经用户 review 确认后执行修复
---

# Review FlagGems PR

对指定的 FlagGems PR 运行所有相关的可编程检查，根据 PR 的实际改动智能选择检查项，发现问题后尝试自动修复。

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
   所有检查发现的问题都需要修复，统一走同一个流程：
   - **诊断**：Agent 读取相关源码，分析每个问题的根因
   - **提出方案**：向用户展示每处改动和理由
   - **等待确认**：用户 review 后再执行（不做无声 auto-fix）
   - **执行 + 验证**：修复后重跑对应检查确认清零
   
   唯一例外：排序（`init_registration`、`operators_yaml`）和机械 code-style（black/isort）是幂等、零风险的确定性改动，可直接修复后一并报告。

5. **生成报告**
   清晰汇总哪些通过、哪些已修复、哪些方案待用户确认。

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
- **修复流程**：确定性改动（排序），可直接修复后报告
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
- **修复流程**：确定性改动（排序），可直接修复后报告
- **退出码**：0=clean, 1=needs_fix

**修复方法**：
```python
# 用 PyYAML 读取
# 按 key（算子 ID）排序
# 写回，保持格式
```

### 4. Code-style 检查和修复
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/fix_code_style.py <PR> [--skip-tests]
```
- **检查内容**：black、isort、flake8、mypy
- **适用条件**：改动了任何 `.py` 文件
- **能否自动修复**：✅ 大部分可以
  - 机械修复：black、isort、end-of-file-fixer（幂等、零风险）
  - Agent 修复：flake8 未使用 import/变量、行太长、mypy 类型标注
- **退出码**：0=clean/fixed, 1=needs_human
- **输出状态**：
  - `clean`：首次运行全绿，无需修复
  - `auto_fixable`：已修复并生成 commit（未 push）
  - `needs_human`：仍有无法自动修的问题

**修复流程**：
1. Clone PR head 到临时目录
2. 只对 PR 改动的文件运行 pre-commit（对齐 CI）
3. 机械修复（black/isort）
4. Agent 修复（flake8/mypy），每个文件最多 3 次重试
5. 跑 PR 相关测试验证（可用 `--skip-tests` 跳过加速）
6. 重跑 pre-commit 验证全绿（fail-closed）
7. 生成 commit（但不自动 push）

### 5. BLOCK_SIZE 硬编码检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_block_size.py <PR> --json
```
- **检查内容**：Triton kernel launcher 里的 `BLOCK_SIZE = <literal>` 硬编码
- **适用条件**：改动了 `src/flag_gems/ops/` 或 `src/flag_gems/fused/` 下的算子
- **修复流程**：Agent 诊断（读上下文、看 N 来源）→ 提出方案 → 用户确认 → 执行
- **退出码**：0=clean, 1=has_violations
- **输出格式**：JSON（`--json`）或人类可读

**为什么重要**：硬编码的 `BLOCK_SIZE` 让 Triton 只编译一个固定的 kernel 版本，无法根据实际数据量（N）动态选择最优的 block size。小数据浪费资源，大数据缺少优化。

**问题模式**：
```python
# ❌ 硬编码
N = x.numel()
BLOCK_SIZE = 1024  # 无论 N 是 100 还是 100万
kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
```

**正确模式**：
```python
# ✅ 动态调整
N = x.numel()
BLOCK_SIZE = min(1024, triton.next_power_of_2(N))
kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
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

### 7. python-op CI 检查
```bash
python3.11 /Users/yufan.shi/Desktop/PR-Review/scripts/check_python_op.py <PR> --json
```
- **检查内容**：PR 的 CI 中 `python-op` job 是否失败，并解析失败原因
- **适用条件**：始终运行（不依赖改动文件类型）
- **能否自动修复**：❌ 需 Agent 分析根因后人工确认
- **退出码**：0=passed/skipped, 1=failed/error
- **输出格式**：JSON（`--json`）或人类可读

**失败类型分类**：
| 类型 | 严重度 | 含义 |
|------|--------|------|
| `missing_import` | critical | `NameError` / `ImportError`：缺少 import 语句 |
| `import_error` | critical | `ModuleNotFoundError`：模块不存在 |
| `assertion` | high | `AssertionError`：断言失败，结果不符合预期 |
| `shape_mismatch` | high | 输出 tensor shape 与期望不符 |
| `dtype_mismatch` | high | 输出 dtype 与期望不符 |
| `numerical_error` | medium | 精度不足或数值错误 |
| `signature_mismatch` | high | 函数签名不兼容 |
| `type_error` | medium | `TypeError`：类型不匹配 |
| `attribute_error` | medium | `AttributeError`：属性访问失败 |
| `cuda_error` | high | CUDA runtime 错误 |
| `runtime_error` | high | 其他运行时错误 |

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

#### block_size 硬编码
1. 读取违规文件，查看上下文（launcher 函数、N 的来源）
2. 提出修复方案（例：`BLOCK_SIZE = min(1024, triton.next_power_of_2(N))`）
3. 向用户说明每处改动，**等用户确认后再执行**
4. 执行修复，重跑 `check_block_size.py` 验证清零

#### skipif 问题
1. 汇总所有 skipif 问题（按 critical/warning/info 分组）
2. 读取相关算子代码，分析每个 skipif 的根因
3. 提出修复方案（例：critical 的 vendor_specific → 删除 skipif + 修复算子实现；lazy → 直接删除装饰器）
4. 向用户展示完整方案，**等用户确认后再执行**
5. 执行修复，重跑 `check_skipif.py` 验证清零

#### python-op CI 失败
1. 解析日志里的失败类型和位置
2. 读取相关源文件，定位根因
3. 提出修复方案（例：补 import、修算子实现、修测试断言）
4. 向用户展示方案，**等用户确认后再执行**
5. 执行修复，提示重新触发 CI 验证
6. `logs_unavailable` 时：告知日志已过期，提供 Job URL，让用户手动确认失败类型后再走上述流程

#### 排序问题（__init__.py 或 operators.yaml）
- **自动修复**
- Clone PR 仓库到临时目录
- 读取文件 → 排序 → 写回
- 验证：重跑检查脚本，退出码应为 0
- 生成 commit（但不自动 push）

#### code-style 问题
- **调用 fix_code_style.py**
- 根据返回状态：
  - `clean`：无需处理
  - `auto_fixable`：修复成功，已生成 commit
  - `needs_human`：报告无法自动修的问题

### Step 5: 生成最终报告

```
==================== PR #5395 Review 报告 ====================

✅ is_cuda: 无违规
✅ block_size: 无硬编码
🔴 skipif: 发现 2 个 vendor-specific skipif（需修复）
  - tests/test_copy.py:114: flag_gems.vendor_name == "metax"
  - tests/test_copy.py:171: flag_gems.vendor_name == "metax"
✅ __init__.py: 已自动修复（1 个文件）
  - src/flag_gems/__init__.py: __all__ 列表已按字母序排序
✅ code-style: 已自动修复（2 个文件）
  - src/flag_gems/ops/add.py: black + 移除未使用的 import
  - tests/test_add.py: isort

⚠️  需要人工处理：
  - tests/test_add.py:15: flake8 F821 - undefined name 'foo'

==================== 修复的文件 ====================
已生成 commit（未 push）：
  M src/flag_gems/__init__.py
  M src/flag_gems/ops/add.py
  M tests/test_add.py

临时目录：/tmp/flaggems-pr-5395-xyz

下一步：
cd /tmp/flaggems-pr-5395-xyz
git diff HEAD~1  # 查看修改
git push origin HEAD  # 确认后推送
```

## 安全边界

1. **只读操作**：
   - 所有检查都是只读的
   - 不修改用户的本地仓库

2. **隔离修复**：
   - 所有修复在临时 clone 里进行（`/tmp/flaggems-pr-<PR>-<random>`）
   - 不影响用户的工作目录

3. **人工确认**：
   - 默认不自动 push
   - 打印修改内容和 push 命令
   - 用户确认后手动 push

4. **fail-closed**：
   - 修复后必须重跑检查全绿才生成 commit
   - 测试失败（如果启用）则放弃修复

5. **重试限制**：
   - Agent 修复每个文件最多 3 次
   - 失败后标记 `needs_human`，不强行修复

## 使用示例

```bash
# 基本用法
/review-flaggems-pr 5395

# Agent 会：
# 1. 读取 PR 5395 的文件列表
# 2. 判断需要跑哪些检查
# 3. 并行执行检查
# 4. 直接修复确定性问题（排序、机械 code-style）
# 5. 对 is_cuda / block_size / skipif / python-op 诊断根因、提出方案、等用户确认后修复
# 6. 生成最终报告
```

## 注意事项

1. **首次运行慢**：`fix_code_style.py` 首次运行会安装 pre-commit hooks（1-3 分钟），后续使用缓存。

2. **网络依赖**：需要克隆 PR 仓库，网络慢时可能耗时较长。

3. **Python 版本**：必须用 Python 3.11，确保与 FlagGems CI 一致。

4. **临时目录清理**：修复成功后保留临时目录供用户确认，失败或 clean 时自动清理。

5. **跨仓库 PR**：如果 PR 来自 fork，会克隆 fork 仓库（可能更慢）。

## 扩展性

新增检查只需：
1. 在 `/Users/yufan.shi/Desktop/PR-Review/scripts/` 添加脚本
2. 更新本 skill 的"可用的检查工具"部分
3. 更新"判断需要的检查"逻辑
