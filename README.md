# FlagGems PR Review Automation

面向 FlagGems 项目的自动化 PR review 工具集，通过 6 项可编程检查 + code-style 修复 + 统一报告生成，覆盖跨芯片兼容、排序规范、测试质量、代码风格等维度。

## 🎯 核心特性

- **跨芯片兼容检查**：`is_cuda` 滥用、CUDA-specific skipif、vendor-specific skipif
- **Triton kernel 质量**：BLOCK_SIZE 硬编码检查（kernel 体内 `tl.arange` 字面量）
- **排序规范**：`__init__.py` 的 `__all__`、`operators.yaml` 算子 ID
- **测试质量**：skipif 合理性验证（issue 引用、时间线、算子名匹配）
- **CI 失败分析**：python-op CI 失败日志提取和根因定位
- **Code-style 修复**：black/isort/flake8/mypy 两阶段修复（dry-run → apply）
- **统一报告生成**：单 PR review 报告、批量聚合报告、最终修复总结

## 📁 项目结构

```
PR-Review/
├── scripts/
│   ├── check_is_cuda.py               # is_cuda 滥用检查
│   ├── check_block_size.py            # BLOCK_SIZE 硬编码检查（kernel 体内）
│   ├── check_skipif.py                # pytest.mark.skipif 合理性验证
│   ├── check_init_registration.py     # __init__.py 注册顺序检查
│   ├── check_operators_yaml.py        # operators.yaml 排序检查
│   ├── check_python_op.py             # python-op CI 失败分析
│   ├── fix_code_style_v2.py           # Code-style 修复（两阶段）
│   └── generate_report.py             # 报告生成（single-review/single-final/batch）
├── tests/
│   ├── test_check_is_cuda.py
│   ├── test_check_init_registration.py
│   └── test_check_operators_yaml.py
├── docs/
│   ├── is_cuda-check-summary.md       # is_cuda 检查规则说明
│   ├── sorting-checks-summary.md      # 排序检查规则说明
│   ├── generate_report_usage.md       # generate_report.py 使用文档
│   └── issues/
│       └── batch_review_findings.md   # 批量扫描确认的真问题清单
├── reports/                            # 报告输出目录
│   └── README.md                      # 报告文件说明
├── .claude/
│   └── skills/
│       └── review-flaggems-pr.md      # PR review 完整工作流 skill
└── README.md                           # 本文档
```

## 🛠️ 检查工具详解

### 1. `is_cuda` 滥用检查

检测违反跨芯片兼容的 `is_cuda` 使用。

**为什么重要**：
- FlagGems 目标是跨芯片兼容（NVIDIA + 天数/沐曦/昇腾/海光/昆仑芯）
- `is_cuda` 把代码限制在 NVIDIA CUDA
- Maintainer 明确表示："is_cuda is invalid for non NV chips"

**使用**：
```bash
python3.11 scripts/check_is_cuda.py <PR编号> [--json]
```

**输出**：违规位置、代码行、修复建议

---

### 2. BLOCK_SIZE 硬编码检查

检测 `@triton.jit` kernel **函数体内** `tl.arange(0, <整数字面量>)` 硬编码。

**检查范围**（重要）：
- ✅ **只查 `@triton.jit` kernel 函数体内的字面量** —— kernel 声明了 `BLOCK_SIZE: tl.constexpr` 参数但体内用字面量，Triton 无法编译多个特化版本
- ❌ **launcher / host 代码里 `BLOCK_SIZE = 1024` 是合法的** —— 它只是决定调用哪个已特化的 kernel variant
- ❌ **模块级常量合法**
- ❌ **kernel 没有 constexpr 参数时字面量合理**

**使用**：
```bash
python3.11 scripts/check_block_size.py <PR编号> [--json]
```

---

### 3. skipif 合理性检查

检测测试中新增的 `@pytest.mark.skipif` 装饰器，验证 reason 是否成立。

**检查内容**：
- 🔴 **CRITICAL**: vendor-specific skipif（违反跨芯片兼容）
- 🔴 **CRITICAL**: CUDA-specific skipif（应使用 `cfg.TO_CPU`）
- 🟡 **WARNING**: lazy skipif（`skipif(True, reason="TODO")`）
- 🟢 **INFO**: 需验证 reason（issue 引用、时间线、算子名匹配）

**验证 reason 的三个校验点**（按此顺序）：
1. **算子名匹配**：issue 是否真的把这个算子列为不支持？
2. **时间线**：issue 创建时间是否早于 PR？（早于 PR 的 issue 无法描述本 PR 新增的实现）
3. **issue 质量**：描述是否清晰、state 是否仍 OPEN、是否被维护者质疑

**使用**：
```bash
python3.11 scripts/check_skipif.py <PR编号> [--json]
```

---

### 4. `__init__.py` 注册顺序检查

检测 `__all__` 列表是否按字母序排列（大小写敏感）。

**使用**：
```bash
python3.11 scripts/check_init_registration.py <PR编号> [--json]
```

---

### 5. `operators.yaml` 排序检查

检测算子 ID 是否按字母序排列。

**使用**：
```bash
python3.11 scripts/check_operators_yaml.py <PR编号> [--json]
```

---

### 6. python-op CI 失败分析

检测 PR 的 CI 中 `python-op` job 是否失败，提取完整失败日志（error message + traceback + 周围输出）。

**使用**：
```bash
python3.11 scripts/check_python_op.py <PR编号> [--json]
```

**输出**：
- `status`: "passed" | "failed" | "skipped"
- `failures`: 数组，每项包含 `file`、`test`、`error_type`、`error_message`、`log_context`
- `logs_unavailable`: CI 日志过期时为 true（约 90 天）

---

### 7. Code-style 修复（两阶段）

**Phase 1: dry-run**（计算修复方案，不 commit）
```bash
python3.11 scripts/fix_code_style_v2.py dry-run <PR编号> [--json]
```

**输出**：
- `status`: "clean" | "fixable" | "needs_human"
- `mechanical_diff`: black/isort/eof 机械修复的 diff
- `agent_diff`: flake8/mypy Agent 修复的 diff
- `risk_levels`: 每个文件的风险等级（"green" | "yellow"）
- `state_file`: 状态文件路径（用于 Phase 2）

**Phase 2: apply**（应用修复并 commit）
```bash
python3.11 scripts/fix_code_style_v2.py apply <state_file>
```

**输出**：commit SHA 列表 + push 指令

---

### 8. 报告生成

**单 PR review 报告**（待确认方案）：
```bash
python3.11 scripts/generate_report.py single-review <PR编号> \
  --repo flagos-ai/FlagGems \
  --branch <分支名> \
  --checks <checks-result.json> \
  --output reports/PR-<编号>-review.md
```

**单 PR 最终总结**（执行结果）：
```bash
python3.11 scripts/generate_report.py single-final <PR编号> \
  --repo flagos-ai/FlagGems \
  --branch <分支名> \
  --checks <checks-result.json> \
  --fixes <fixes-result.json> \
  --output reports/PR-<编号>-final.md
```

**批量聚合报告**：
```bash
python3.11 scripts/generate_report.py batch \
  --prs <PR编号列表> \
  --checks-dir <checks目录> \
  --output reports/batch-<timestamp>.md
```

详见 [docs/generate_report_usage.md](docs/generate_report_usage.md)

## 🎯 集成使用：review-flaggems-pr skill

完整的 PR review 工作流封装在 `.claude/skills/review-flaggems-pr.md`，自动执行：

1. **智能选择检查项**（根据 PR 改动文件类型）
2. **并行执行检查**
3. **诊断根因 + 提出修复方案 + 标注风险等级**
4. **等待 human review 确认后执行修复**
5. **重跑检查验证清零**
6. **生成报告**

**统一原则**：detect → propose → approve → fix → verify

**使用**：
```bash
# Claude Code CLI
/review-flaggems-pr <PR编号>

# 批量模式
/review-flaggems-pr --batch <PR编号列表>
```

所有改动（含排序、机械 code-style 等零风险改动）都需先展示方案 + 风险等级，等用户 review 确认后再执行。

## 🧪 测试

```bash
# 运行所有测试
for test in tests/test_*.py; do python3.11 "$test" || exit 1; done

# 运行单个测试
python3.11 tests/test_check_is_cuda.py
python3.11 tests/test_check_init_registration.py
python3.11 tests/test_check_operators_yaml.py
```

## 📚 核心设计原则

1. **可编程优先**：只做规则明确、无歧义的检查
2. **准确性第一**：宁可保守（少报），不要误报
3. **真实验证**：每个检查都在真实 PR 上验证（已扫描 80+ PRs）
4. **人工确认**：任何改动执行前都需 human review，无例外
5. **fail-closed**：修复后重跑检查全绿才生成 commit

## 🔍 已验证真问题

详见 [docs/issues/batch_review_findings.md](docs/issues/batch_review_findings.md)

**统计**（扫描范围：80 个 KernelGen PRs）：
- 确认真问题：7 项
  - #5172 `is_cuda` 硬编码
  - #5160 CUDA-specific skipif
  - #5399 vendor-specific skipif（issue 引用无效）
  - #5283 operators.yaml 排序
  - #5484 `torch.cuda.device()` 硬编码
  - #5485 python-op 精度失败
  - #5486 python-op 测试写法 bug

## 📖 参考

- [FlagGems 仓库](https://github.com/flagos-ai/FlagGems)
- [is_cuda 检查规则](docs/is_cuda-check-summary.md)
- [排序检查规则](docs/sorting-checks-summary.md)
- [报告生成使用](docs/generate_report_usage.md)

## 📄 License

MIT
