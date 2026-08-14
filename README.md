# FlagGems PR Review Automation

面向 FlagGems 项目的自动化 PR review 工具集。对 PR 运行一组可编程检查（跨芯片兼容、Triton kernel 质量、排序规范、测试质量、CI 失败分析、代码风格），诊断问题后提出修复方案并标注风险，经人工确认后在临时 clone 里执行修复。

## 检查工具

所有脚本在 `scripts/` 下，统一用法 `python3.11 scripts/<脚本> <PR编号> [--json]`，退出码 0=clean。

| 脚本 | 检查内容 |
|---|---|
| `check_is_cuda.py` | `is_cuda` 滥用（违反跨芯片兼容） |
| `check_block_size.py` | `@triton.jit` kernel 体内 `tl.arange(0, 字面量)` 硬编码 |
| `check_skipif.py` | `@pytest.mark.skipif` 合理性（reason 是否成立） |
| `check_init_registration.py` | `__init__.py` 的 `__all__` 字母序 |
| `check_operators_yaml.py` | `operators.yaml` 算子 ID 字母序 |
| `check_python_op.py` | python-op CI 失败日志提取和根因定位 |
| `fix_code_style_v2.py` | black/isort/flake8/mypy 两阶段修复（`dry-run` → `apply`） |
| `generate_report.py` | 报告生成（`single-review` / `single-final` / `batch`） |

检查规则的原理和细节见 [docs/](docs/)；报告生成参数见 [docs/generate_report_usage.md](docs/generate_report_usage.md)。

## 快速开始

```bash
# 前置：gh CLI 已登录，Python 3.11
# 对单个 PR 跑某项检查
python3.11 scripts/check_is_cuda.py 5172 --json

# code-style 两阶段修复
python3.11 scripts/fix_code_style_v2.py dry-run 5395 --json   # 计算方案，不 commit
python3.11 scripts/fix_code_style_v2.py apply <state_file>    # 确认后应用
```

## 推荐用法：review-flaggems-pr skill

完整工作流封装在 skill 里，会根据 PR 改动智能选检查、并行执行、诊断提方案、人工确认后修复、重跑验证、生成报告。

```bash
/review-flaggems-pr 5395                          # 单 PR
/review-flaggems-pr --batch 5395 5390 5388        # 批量
```

统一原则 **detect → propose → approve → fix → verify**：任何改动执行前都需人工确认，修复在临时 clone 里进行，重跑检查全绿才生成 commit。细节见 [.claude/skills/review-flaggems-pr/SKILL.md](.claude/skills/review-flaggems-pr/SKILL.md)。

## 测试

```bash
for test in tests/test_*.py; do python3.11 "$test" || exit 1; done
```

## 项目结构

```
scripts/    8 个检查/修复/报告脚本
tests/      单元测试
docs/       检查规则说明 + 确认的真问题清单（docs/issues/）
reports/    报告输出目录
.claude/skills/review-flaggems-pr/   PR review 工作流 skill
```

## License

MIT
