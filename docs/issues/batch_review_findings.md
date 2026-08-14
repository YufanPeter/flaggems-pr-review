# 批量 Review 发现的问题

> **检查标准更新（2026-08-14）**：block_size 检查逻辑已修正。
> 旧逻辑把 launcher/模块级的 `BLOCK_SIZE = <int>` 当违规，方向是反的。
> 经 mentor 确认，正确标准为：
> - ✅ **launcher / host 代码里 hardcode 允许** —— 只是决定调用哪个已特化的 kernel variant
> - ❌ **`@triton.jit` kernel 函数体内 hardcode 才是问题** —— 声明了 `tl.constexpr` 分块参数却在 `tl.arange(0, <字面量>)` 里写死，导致 Triton 只能编译单一 tile 尺寸
>
> 详见 PR：`fix/block-size-check-kernel-scope`（脚本 `scripts/check_block_size.py`）

## ✅ 已验证问题（5 PRs，8 初筛项 → 2 真问题）

| PR | 链接 | 问题位置 | 问题 | 验证结果 | 置信度 | 修复建议 |
|----|------|----------|------|----------|--------|----------|
| **#5172** Add replication_pad2d | [链接](https://github.com/flagos-ai/FlagGems/pull/5172) | replication_pad2d.py:133 | 使用 `if not input.is_cuda` 检查（违反跨芯片兼容） | ✅ **真问题** | 高 | 删除检查或改用 `device.type != flag_gems.device`；同系列 `replication_pad1d.py` 无此检查 |
| **#5160** Add _cudnn_attention_forward | [链接](https://github.com/flagos-ai/FlagGems/pull/5160) | test_cudnn_attention_forward.py:52 | skipif 硬编码 `not torch.cuda.is_available()` | ✅ **真问题** | 高 | 改用 `cfg.TO_CPU`；算子是通用 Triton FlashAttention-2，与 `_flash_attention_forward` 一致 |

### 按新标准正确放过的 block_size 初筛项

以下 4 项在**旧逻辑**下被误报，**新逻辑**下正确放过 —— 它们的 hardcode 都在 launcher / 模块级（host 代码），不在 kernel 函数体内，属于合法用法。

| PR | 问题位置 | 初筛内容 | 新标准结论 |
|----|----------|----------|-----------|
| #5440 Add addr_ | addr_.py:77-78 | launcher `BLOCK_SIZE_M/N = 32`，作为 tl.constexpr 传入 kernel | ✅ 正确放过（launcher hardcode 合法） |
| #5172 Add replication_pad2d | replication_pad2d.py:145 | launcher `BLOCK_SIZE = 1024` | ✅ 正确放过（launcher hardcode 合法） |
| #5163 Move arccosh to ops | arccosh.py:26 | 模块级 `BLOCK_SIZE = 1024` | ✅ 正确放过（模块级常量，非 kernel 内） |
| #5152 Add _fused_rms_norm | _fused_rms_norm.py:440-441 | launcher `ROW_BLOCK_SIZE=16 / COL_BLOCK_SIZE=256` | ✅ 正确放过（launcher hardcode 合法） |

> 说明：这些 PR 是否要进一步加 `@triton.autotune` 提升性能，属于**独立的性能优化机会**，不是本次代码规范检查要拦的缺陷。是否优化由算子作者按需决定。

## 📋 待验证问题（2 PRs）

| PR | 链接 | 问题位置 | 问题 | 备注 |
|----|------|----------|------|------|
| #5393 Add slice operator | https://github.com/flagos-ai/FlagGems/pull/5393 | src/flag_gems/ops/slice.py:254,272 | launcher `BLOCK_SIZE = 1024`（host 代码） | 按新标准应放过，需确认 kernel 体内是否用了 constexpr |
| #5399 Add special_chebyshev_polynomial_t | https://github.com/flagos-ai/FlagGems/pull/5399 | tests/test_special_chebyshev_polynomial_t.py:25,46 | vendor-specific skipif（cambricon）。reason 引用 issue #5254，但该 issue 列的是 `_w` 算子（本 PR 是 `_t`，名称不匹配），且 issue 早于 PR（时间线倒置） | 确认错误，建议删除 skipif |

---

## 统计

- **批量扫描范围**：40 个 KernelGen PRs
- **初筛发现**：8 个违规项（5 PRs）
- **按新 block_size 标准复核后**：
  - ✅ 真问题（需修复）：2 项 —— #5172 `is_cuda`、#5160 `skipif`（均为跨芯片兼容问题）
  - ✅ 正确放过：4 项 —— 全部为 launcher / 模块级 hardcode（旧逻辑误报，新逻辑已修正）
  - 📋 待验证：2 项 —— #5393、#5399
- **关键结论**：旧 block_size 检查方向错误导致大量误报；修正后 block_size 类误报归零，真问题聚焦在跨芯片兼容（`is_cuda` / CUDA-specific skipif）。
