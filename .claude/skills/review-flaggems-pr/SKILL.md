---
name: review-flaggems-pr
description: 审查 FlagGems 仓库的 PR 时使用。对指定 PR 运行可编程检查（is_cuda 跨芯片兼容、block_size 硬编码、skipif 合理性、__init__/operators.yaml 排序、code-style、python-op CI），诊断根因后提出修复方案并标注风险，经用户确认后在临时 clone 里执行修复。支持单 PR 和批量模式。
---

# Review FlagGems PR

对指定的 FlagGems PR 运行所有相关的可编程检查，根据 PR 的实际改动智能选择检查项。发现问题后提出修复方案并标注风险等级，经用户 review 确认后再执行 —— 任何改动执行前都需人工确认，无例外。

## 前置：定位仓库根目录

本 skill 的脚本位于仓库的 `scripts/`。所有命令都假设已 `cd` 到**仓库根目录**（即本 SKILL.md 上溯三级：`.claude/skills/review-flaggems-pr/SKILL.md` → 仓库根）。执行任何脚本前先：

```bash
# 从 skill 目录定位仓库根（SKILL.md 在 <repo>/.claude/skills/review-flaggems-pr/ 下）
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo <仓库根路径>)"
```

后文所有 `python3.11 scripts/xxx.py` 均以仓库根为工作目录。

## 统一原则

所有检查发现的问题都走同一条流水线，没有例外：

**detect → propose → approve → fix → verify**

- **detect**：脚本检测问题，输出 JSON
- **propose**：agent 读源码诊断根因，提出方案并标注风险等级
  - 🟢 **无风险**：幂等确定性机械改动（排序、black/isort 格式化）
  - 🟡 **低风险**：局部逻辑改动（删 skipif、补 import、改测试断言）
  - 🔴 **高风险**：影响算子语义、跨芯片行为的改动
- **approve**：**等待 human review**，用户确认后才执行 —— 不做无声 auto-fix，也没有「零风险直接改」的例外
- **fix**：在临时 clone 里执行修复
- **verify**：重跑对应检查确认清零，全绿才生成 commit

## 执行流程

### Step 1：读取 PR 信息

```bash
gh pr view <PR> --repo flagos-ai/FlagGems --json files,number,headRefName,headRepository
```

提取改动的文件列表、head 分支名、是否是 fork。

### Step 2：智能选择检查项

```python
checks_needed = []
for file in changed_files:
    if (file.startswith("src/flag_gems/ops/") or file.startswith("src/flag_gems/fused/")) and file.endswith(".py"):
        checks_needed += ["is_cuda", "block_size"]
    if file.startswith("tests/") and file.endswith(".py"):
        checks_needed.append("skipif")
    if file.endswith("__init__.py"):
        checks_needed.append("init_registration")
    if file == "operators.yaml":
        checks_needed.append("operators_yaml")
    if file.endswith(".py"):
        checks_needed.append("code_style")

checks_needed.append("python_op")   # 始终运行，不依赖改动文件类型
checks_needed = list(set(checks_needed))
```

### Step 3：并行运行检查

多个检查可并行执行节省时间：

```bash
python3.11 scripts/check_is_cuda.py <PR> --json &
python3.11 scripts/check_block_size.py <PR> --json &
python3.11 scripts/check_init_registration.py <PR> --json &
wait
```

### Step 4：诊断、提方案、修复

按检查类型处理（每类都走统一原则，approve 后才执行）：

- **is_cuda 违规**：读违规算子文件 → 提方案（移除 `is_cuda` 检查，或改用 `x.device.type == runtime.device.name`）→ 确认 → 执行 → 重跑验证
- **block_size 硬编码**：确认 kernel 声明了哪个 constexpr 参数 → 把体内 `tl.arange(0, <字面量>)` 改用该参数 → 确认 → 执行 → 重跑验证。（launcher/模块级 hardcode 不报，不改）
- **skipif 问题**：按 critical/warning/info 分组，逐个验证 reason 是否成立 → 提方案 → 确认 → 执行 → 重跑验证。验证方法见 `reference/skipif-verification.md`
- **python-op CI 失败**：读脚本输出的 `log_context` + PR 代码定位根因 → 提方案 → 确认 → 执行 → 提示重触发 CI
- **排序问题**（__init__.py / operators.yaml）：算出排序结果 → 展示 diff 标 🟢 → 确认 → 写回 → 重跑验证
- **code-style**：见下方两阶段模式

**code-style 两阶段**：
```bash
python3.11 scripts/fix_code_style_v2.py dry-run <PR> --json   # Phase 1: 计算方案
# 展示 mechanical_diff(🟢)/agent_diff(🟡)，等用户确认
python3.11 scripts/fix_code_style_v2.py apply <state_file>     # Phase 2: commit
```
按 Phase 1 状态分流：`clean`（无需修复）/ `fixable`（走流程）/ `needs_human`（报告阻塞的 hooks）。

### Step 5：生成报告

- 提方案阶段：`single-review` 模式生成待确认方案报告
- 用户确认执行后：`single-final` 模式生成最终总结
- 批量场景：`batch` 模式生成聚合视图

三种模式的完整命令和 JSON 格式见 `reference/report-generation.md`。

## 检查工具速查

所有脚本在仓库 `scripts/` 下，均支持 `--json`，退出码 0=clean。

| 脚本 | 检查内容 | 适用条件 |
|---|---|---|
| `check_is_cuda.py` | `is_cuda` 滥用（违反跨芯片兼容） | 改动 `ops/`、`fused/` 算子 |
| `check_block_size.py` | kernel 体内 `tl.arange(0,字面量)` 硬编码 | 改动 `ops/`、`fused/` 算子 |
| `check_skipif.py` | `@pytest.mark.skipif` 合理性 | 改动 `tests/` |
| `check_init_registration.py` | `__all__` 字母序 | 改动 `__init__.py` |
| `check_operators_yaml.py` | 算子 ID 字母序 | 改动 `operators.yaml` |
| `check_python_op.py` | python-op CI 失败日志提取 | 始终运行 |
| `fix_code_style_v2.py` | black/isort/flake8/mypy 两阶段修复 | 改动任何 `.py` |
| `generate_report.py` | 报告生成 | 结尾汇总 |

### is_cuda —— 为什么重要

FlagGems 目标是跨芯片兼容（NVIDIA + 天数/沐曦/昇腾/海光/昆仑芯），`is_cuda` 把代码限制在 NVIDIA，maintainer 明确表示 "is_cuda is invalid for non NV chips"。

### block_size —— 检查范围（重要）

`@triton.jit` 标记的是 GPU kernel 本身。kernel 声明 `BLOCK_SIZE: tl.constexpr` 是为了让 Triton 针对不同 tile 尺寸编译多个特化版本。体内写死字面量会绕过该机制。

- ❌ **只查 `@triton.jit` kernel 函数体内的字面量**（且 kernel 声明了名称含 BLOCK/SIZE/TILE 的 constexpr 参数）—— 这是真问题
- ✅ launcher / host 代码里 `BLOCK_SIZE = 1024` 合法 —— 只是决定调哪个特化版本
- ✅ 模块级常量合法
- ✅ kernel 没有 constexpr 参数时字面量合理

```python
# ❌ kernel 体内写死，忽略了声明的 constexpr 参数
@triton.jit
def my_kernel(x_ptr, out_ptr, n_elements, BLOCK_SIZE: tl.constexpr):
    offsets = tl.arange(0, 1024)      # ← 应该用 BLOCK_SIZE

# ✅ 体内使用声明的 constexpr 参数
    offsets = tl.arange(0, BLOCK_SIZE)

# ✅ launcher 里 hardcode 完全允许
def launcher(x, out):
    BLOCK_SIZE = 1024
    my_kernel[(triton.cdiv(x.numel(), BLOCK_SIZE),)](x, out, x.numel(), BLOCK_SIZE=BLOCK_SIZE)
```

### skipif —— 为什么重要

AI 写测试时可能偷懒加 `skipif` 跳过失败的测试，而不是修复问题。vendor-specific skipif 违反跨芯片兼容目标。**reason 是「主张」不是「证据」**，必须验证。详细分类、三点校验法、终判分流表见 `reference/skipif-verification.md`。

### python-op —— 过期日志

CI 日志在 Azure Blob 上保存约 90 天。若已过期，脚本输出 `logs_unavailable: true` 并附 Job URL 供人工查看，告知用户手动确认失败类型后再走流程。

## 使用示例

```bash
/review-flaggems-pr 5395              # 单 PR：读文件 → 选检查 → 并行跑 → 提方案 → 确认 → 修复 → 报告
/review-flaggems-pr --batch 5395 5390 5388 5387   # 批量：并行检查 → 聚合报告 → 逐个/批量修复
```

## 安全边界

1. **只读检查**：所有检查只读，不改用户本地仓库
2. **隔离修复**：修复在临时 clone 里进行（`/tmp/flaggems-pr-<PR>-<random>`），不影响工作目录
3. **人工确认两道**：
   - 改动前：任何修复（含排序、机械 code-style 等零风险）落盘前先展示方案 + 风险等级，等确认 —— 无例外
   - push 前：默认不自动 push，打印修改内容和 push 命令，用户确认后手动 push
4. **fail-closed**：修复后必须重跑检查全绿才生成 commit
5. **重试限制**：Agent 修复每个文件最多 3 次，失败标记 `needs_human`，不强行修复

## 注意事项

1. **首次运行慢**：`fix_code_style_v2.py` 首次会安装 pre-commit hooks（1-3 分钟），后续用缓存
2. **网络依赖**：需克隆 PR 仓库，网络慢时耗时较长；fork PR 克隆 fork 仓库可能更慢
3. **Python 版本**：必须用 Python 3.11，与 FlagGems CI 一致
4. **临时目录清理**：修复成功后保留临时目录供确认，失败或 clean 时自动清理

## 扩展性

新增检查只需：在 `scripts/` 添加脚本 → 更新本 SKILL.md 的「检查工具速查」表 → 更新 Step 2 的选择逻辑。
