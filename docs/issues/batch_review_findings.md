# 批量 Review — 真正有问题的 PR

> 扫描范围：40 个 KernelGen PRs。本文档只保留经复核确认（或待验证）**真正有问题**的 PR。
> block_size 类初筛项按修正后的标准（launcher / 模块级 hardcode 合法，只查 kernel 体内忽略 constexpr 的 `tl.arange` 字面量）全部放过，已从本文档移除。

## ✅ 确认真问题（需修复）

| PR | 链接 | 问题位置 | 问题 | 置信度 | 修复方案 |
|----|------|----------|------|--------|----------|
| **#5172** Add replication_pad2d | [链接](https://github.com/flagos-ai/FlagGems/pull/5172) | replication_pad2d.py:133 | `if not input.is_cuda or not out.is_cuda:` 把算子钉死在 NVIDIA 上，违反跨芯片兼容 | 高 | 删除该检查（对齐同系列 `replication_pad1d.py`），或改用 `input.device.type != flag_gems.device`。`contiguous` 检查保留 |
| **#5160** Add _cudnn_attention_forward | [链接](https://github.com/flagos-ai/FlagGems/pull/5160) | tests/test_cudnn_attention_forward.py:52<br>benchmark/test_cudnn_attention_forward.py:187 | skipif 硬编码 `not torch.cuda.is_available()`。算子实现是通用 Triton FlashAttention-2，无 CUDA 专属代码 | 高 | 两处都改用 `@pytest.mark.skipif(cfg.TO_CPU, reason="Unsupported in CPU mode")`，对齐 `test_flash_attention.py` |

## 📋 待验证真问题

| PR | 链接 | 问题位置 | 问题 | 备注 |
|----|------|----------|------|------|
| #5399 Add special_chebyshev_polynomial_t | [链接](https://github.com/flagos-ai/FlagGems/pull/5399) | tests/test_special_chebyshev_polynomial_t.py:25,46 | vendor-specific skipif（cambricon）。reason 引用 issue #5254，但该 issue 列的是 `_w` 算子（本 PR 是 `_t`，名称不匹配），且 issue 早于 PR（时间线倒置） | 需验证 issue 引用是否确实错误，若是则建议删除或修正 skipif |

---

## 统计

- **批量扫描范围**：40 个 KernelGen PRs
- **确认真问题**：2 项（均为跨芯片兼容）—— #5172 `is_cuda`、#5160 `skipif`
- **待验证**：1 项 —— #5399 skipif issue 引用错误
- **关键结论**：修正 block_size 检查方向后，block_size 类误报归零；真问题集中在跨芯片兼容（`is_cuda` / CUDA-specific skipif）与 skipif 引用规范。
