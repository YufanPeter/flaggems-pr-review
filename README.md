# FlagGems PR Review Automation

面向 FlagGems 项目的自动化 PR review 工具集，专注于可编程检查项：排序、代码风格、命名规范。

## 🎯 项目目标

**从小范围入手**，先实现高频、可编程、零歧义的检查项，而不是一次性处理所有 review comments。

### 为什么不做通用的 comment 解析？

- ❌ 自然语言 comments 需要 NLP，增加复杂度
- ❌ 同一个问题，reviewer 表述方式不同
- ✅ 直接检查代码，规则明确，准确率高
- ✅ 可以作为 **pre-review 工具**（PR 提交前检查）

## ✅ 已完成检查

### 1. `is_cuda` 滥用检查（P0）

检测违反跨芯片兼容的 `is_cuda` 使用。

**为什么重要**：
- FlagGems 的核心目标是跨芯片兼容（NVIDIA + 天数/沐曦/昇腾/海光/昆仑芯）
- `is_cuda` 把代码限制在 NVIDIA CUDA
- Maintainer 明确表示："is_cuda is invalid for non NV chips" (PR #3726)

**使用方法**：
```bash
# 检查单个 PR
python3.11 scripts/check_is_cuda.py <PR编号>
python3.11 scripts/check_is_cuda.py https://github.com/FlagOpen/FlagGems/pull/3698

# JSON 输出
python3.11 scripts/check_is_cuda.py 3698 --json
```

**测试覆盖**：
- ✅ 31 个单元测试
- ✅ 8 个真实 PR 验证
- ✅ 准确率 100%

**真实案例**：成功检测到 PR #3698 的违规

### 2. `__init__.py` 注册顺序检查（P0）

检测 `__all__` 列表是否按字母序排列。

**为什么重要**：
- 高频问题（6+ PRs）
- 手动维护容易出错
- isort 只管 import，不管 `__all__`

**使用方法**：
```bash
# 检查单个 PR
python3.11 scripts/check_init_registration.py <PR编号>
python3.11 scripts/check_init_registration.py 3698

# JSON 输出
python3.11 scripts/check_init_registration.py 3698 --json
```

**测试覆盖**：
- ✅ 9 个单元测试
- ✅ 覆盖单行/多行/混合格式
- ✅ 大小写敏感测试

### 3. `operators.yaml` 排序检查（P0）

检测算子 ID 是否按字母序排列。

**为什么重要**：
- 高频问题
- 新增算子时容易插入到错误位置
- 没有工具自动检查

**使用方法**：
```bash
# 检查单个 PR
python3.11 scripts/check_operators_yaml.py <PR编号>
python3.11 scripts/check_operators_yaml.py 3698

# JSON 输出
python3.11 scripts/check_operators_yaml.py 3698 --json
```

**测试覆盖**：
- ✅ 8 个单元测试
- ✅ 真实算子名称测试
- ✅ 下划线前缀测试

## 📋 计划中的检查（按优先级）

### P1（中频且可编程）
- [ ] Co-Authored-By trailer 检查
- [ ] snake_case 命名检查
- [ ] Logger 命名规范检查

### P2（低频或需要上下文）
- [ ] 测试维度覆盖检查
- [ ] 测试命名规范检查

## 🏗️ 项目结构

```
PR-Review/
├── scripts/
│   ├── check_is_cuda.py                # is_cuda 滥用检查
│   ├── check_init_registration.py      # __init__.py 注册检查
│   ├── check_operators_yaml.py         # operators.yaml 排序检查
│   └── fetch_pr_diff.py                # PR diff 获取工具
├── tests/
│   ├── test_check_is_cuda.py           # is_cuda 测试
│   ├── test_improved_check_is_cuda.py  # is_cuda 改进测试
│   ├── test_realistic_scenario.py      # is_cuda 真实场景测试
│   ├── manual_test_check_is_cuda.py    # is_cuda 手动测试
│   ├── test_check_init_registration.py # __init__.py 测试
│   └── test_check_operators_yaml.py    # operators.yaml 测试
├── docs/
│   ├── is_cuda-check-summary.md        # is_cuda 检查总结
│   └── real-pr-validation-report.md    # 真实 PR 验证报告
├── diagnosis.md                        # Pre-commit 调查结果
└── README.md                           # 本文档
```

## 🧪 运行测试

```bash
# 运行所有测试
for test in tests/test_*.py; do python3.11 "$test" || exit 1; done

# 运行单个测试
python3.11 tests/test_check_is_cuda.py
python3.11 tests/test_check_init_registration.py
python3.11 tests/test_check_operators_yaml.py
```

## 📚 设计原则

1. **小步快跑**：每次实现一个检查，验证后再继续
2. **可编程优先**：只做规则明确、无歧义的检查
3. **真实验证**：每个检查都在真实 PR 上验证
4. **准确性第一**：宁可保守（少报），不要误报

## 🎓 关键学习

### `is_cuda` 案例

**初始理解**（错误）：
- ❌ "防御性检查不应该存在"

**正确理解**（基于 PR #3726）：
- ✅ 防御性设备检查是必要的
- ✅ 但 `is_cuda` 把检查限制在 NVIDIA
- ✅ 正确做法：
  1. 移除显式 `is_cuda` 检查，依赖 kernel launch 的自然错误
  2. 或改用 `x.device.type == runtime.device.name`

**Maintainer 原话**：
> "is_cuda is invalid for non NV chips"

**修复方式**：
```python
# ❌ 修复前
assert x.is_cuda and out.is_cuda, "Inputs must be CUDA tensors"

# ✅ 修复后
# 移除显式检查
# "The same-device validation and kernel launch provide sufficient 
# guards across all backends (Nvidia, Metax, Ascend, Hygon, etc.)"
```

## 🚀 下一步

1. ✅ `is_cuda` 检查 - 已完成
2. ✅ `__init__.py` 注册检查 - 已完成
3. ✅ `operators.yaml` 排序检查 - 已完成
4. ⏳ Co-Authored-By trailer 检查 - 下一步

## 📖 参考

- [FlagGems 仓库](https://github.com/FlagOpen/FlagGems)
- [PR #3726](https://github.com/FlagOpen/FlagGems/pull/3726) - is_cuda 真实案例
- [PR #3698](https://github.com/FlagOpen/FlagGems/pull/3698) - 验证案例

## 🤝 贡献

这是一个学习项目（一周时间内完成 MVP）。欢迎反馈和建议！

## 📄 License

MIT
