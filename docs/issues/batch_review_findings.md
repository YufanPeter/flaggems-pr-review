# 批量 Review 发现的问题

| PR | 链接 | 问题位置 | 问题 | 备注 |
|----|------|----------|------|------|
| #5440 Add addr_ operator | https://github.com/flagos-ai/FlagGems/pull/5440 | src/flag_gems/ops/addr_.py:77-78 | launcher 硬编码 `BLOCK_SIZE_M = 32` / `BLOCK_SIZE_N = 32`，未随 M/N 动态调整。kernel 参数本身是 `tl.constexpr` 动态的 | block_size 检查是否过严待讨论 |
| #5393 Add slice operator | https://github.com/flagos-ai/FlagGems/pull/5393 | src/flag_gems/ops/slice.py:254,272 | launcher 硬编码 `BLOCK_SIZE = 1024`，未随 N 动态调整 | block_size 检查是否过严待讨论 |
| #5399 Add special_chebyshev_polynomial_t | https://github.com/flagos-ai/FlagGems/pull/5399 | tests/test_special_chebyshev_polynomial_t.py:25,46 | vendor-specific skipif（cambricon）。reason 引用 issue #5254，但该 issue 列的是 `_w` 算子（本 PR 是 `_t`，名称不匹配），且 issue 早于 PR（时间线倒置） | 确认错误，建议删除 skipif |
