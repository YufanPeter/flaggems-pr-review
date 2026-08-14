# 批量 Review — 真正有问题的 PR

> 扫描范围：40 个 KernelGen PRs。本文档只保留经复核确认（或待验证）**真正有问题**的 PR。
> block_size 类初筛项按修正后的标准（launcher / 模块级 hardcode 合法，只查 kernel 体内忽略 constexpr 的 `tl.arange` 字面量）全部放过，已从本文档移除。

## ✅ 确认真问题（需修复）

| PR | 链接 | 问题位置 | 问题 | 置信度 | 修复方案 |
|----|------|----------|------|--------|----------|
| **#5172** Add replication_pad2d | [链接](https://github.com/flagos-ai/FlagGems/pull/5172) | replication_pad2d.py:133 | `if not input.is_cuda or not out.is_cuda:` 把算子钉死在 NVIDIA 上，违反跨芯片兼容 | 高 | 删除该检查（对齐同系列 `replication_pad1d.py`），或改用 `input.device.type != flag_gems.device`。`contiguous` 检查保留 |
| **#5160** Add _cudnn_attention_forward | [链接](https://github.com/flagos-ai/FlagGems/pull/5160) | tests/test_cudnn_attention_forward.py:52<br>benchmark/test_cudnn_attention_forward.py:187 | skipif 硬编码 `not torch.cuda.is_available()`。算子实现是通用 Triton FlashAttention-2，无 CUDA 专属代码 | 高 | 两处都改用 `@pytest.mark.skipif(cfg.TO_CPU, reason="Unsupported in CPU mode")`，对齐 `test_flash_attention.py` |
| **#5399** Add special_chebyshev_polynomial_t | [链接](https://github.com/flagos-ai/FlagGems/pull/5399) | tests/test_special_chebyshev_polynomial_t.py:25,46 | vendor-specific skipif（cambricon），reason 引用 Issue #5254。已验证 reason 不成立：① 算子名对不上——issue 清单第 11 项是 `test_special_chebyshev_polynomial_**w**.py`，本 PR 是 `_**t**` 变体，不在清单内；② 时间线倒置——issue 建于 2026-08-05，PR 建于 2026-08-11，早于 PR 的 issue 无法描述本 PR 新增的实现 | 高 | 删除两处 skipif（第 25、46 行）。若 `_t` 在 cambricon 上确有失败，应另开 issue 并修复算子实现，而非借用 `_w` 的 issue 跳过 |
| **#5283** Split xor/ixor operators and register ixor | [链接](https://github.com/flagos-ai/FlagGems/pull/5283) | conf/operators.yaml:10923 | operators.yaml 字母序错误：`"xor"` 排在 `"ixor"` 之前，但 `i < x`，`ixor` 应在前。新增 `ixor` 时插错位置（PR 已 merged，错误顺序已进 main）| 中（🟢 纯排序，无运行时风险）| 将 `"xor"` 移到 `"ixor"` 之后的正确位置 |
| **#5484** Add grid_sampler_2d_backward | [链接](https://github.com/flagos-ai/FlagGems/pull/5484) | src/flag_gems/ops/grid_sampler_2d_backward.py:272 | `with torch.cuda.device(grad_output.device):` 直接用 `torch.cuda` 模块，把算子锁死 NVIDIA，违反跨芯片兼容 | 高 | 改用 `flag_gems.runtime.torch_device_fn`（设备无关的 device guard），不能硬编码 `torch.cuda`。注意是上下文管理器，需换等价 API 而非直接删 |
| **#5485** Add blackman_window | [链接](https://github.com/flagos-ai/FlagGems/pull/5485) | src/flag_gems/ops/blackman_window.py（tests/test_blackman_window.py::test_blackman_window[dtype0-256]）| python-op CI FAIL：数值精度不达标（`Tensor-likes are not close!`），256 窗口下 Triton 实现偏离参考值超容差 | 高（🔴 触及算子语义/精度）| 需 root-cause 算子数学/精度实现，对齐 torch 参考后再修 |
| **#5486** Add binomial | [链接](https://github.com/flagos-ai/FlagGems/pull/5486) | tests/test_binomial.py（test_binomial_edge_probs / test_binomial_zero_count）| python-op CI FAIL（quick-cpu 模式）：测试直接用 `torch.zeros_like(count)`（建在 `flag_gems.device`/CUDA）传给 `gems_assert_equal`，而 `to_cpu` 要求 ref 在 CPU → 断言失败。测试写法 bug，非算子实现问题 | 中 | 参考同文件其他测试，将 ref 走 `to_reference(...)` 做 CPU 转换后再传入 `gems_assert_equal` |

---

## 统计

- **批量扫描范围**：80 个 KernelGen PRs（首批 40 + 后续三批 20 / 10 / 10）
- **确认真问题**：7 项 —— #5172 `is_cuda`、#5160 CUDA-specific `skipif`、#5399 vendor-specific `skipif`（issue 引用无效）、#5283 operators.yaml 排序、#5484 `is_cuda`（`torch.cuda`）、#5485 python-op 精度、#5486 python-op 测试写法 bug
- **待验证**：0 项
- **后续四批扫描**：第二批 20 个全 PASS；第三批 10 个中 9 PASS、1 FAIL（#5283）；第四批 10 个中 7 PASS、3 FAIL（#5484 / #5485 / #5486）；第五批进行中。
- **#5362 非真问题**：PR 已 CLOSED，python-op CI 失败发生在 `actions/checkout` 阶段（`couldn't find remote ref refs/pull/5362/merge`），测试从未运行 —— CI 基础设施/PR 状态问题，非代码缺陷，不计入真问题。（注：曾有一份 subagent 报告把它误报为 "gcd 算子正确性失败"，经 `gh pr view` 核实为幻觉/串号，已撤回。）
- **#5370 非活跃**：PR 已 CLOSED（view_as_complex）。记录在案的 python-op CI 为 fail，根因与 #5486 同类（测试在 quick-cpu 模式下未走 `to_reference`，ref 仍在 CUDA → 断言失败）。因 PR 已关闭不列入待修。（注：subagent 曾声称"分支 tip 已推进到 9576e561 且 CI 全绿"，但 `gh pr view` 显示 PR headRefOid 仍是失败 SHA `37588073f6`、python-op 仍 fail，该"已修复"说法无法证实，不采信。）
- **关键结论**：修正 block_size 检查方向后，block_size 类误报归零。真问题分布：跨芯片兼容（`is_cuda` / `torch.cuda` / CUDA-specific skipif）、skipif 引用规范、operators.yaml 字母序、python-op CI（算子精度与测试写法）。
- **check_is_cuda 能力确认**：`torch.cuda.device()` 这类 `torch.cuda` 模块直接调用也能被 is_cuda 检查捕获（#5484）。
- **厂商后端算子**：直接传文件路径时，`runtime/backend/<vendor>/ops/` 下的算子仍会被 is_cuda/block_size 扫描（#5445 _mthreads、#5381 _ascend 均已实测通过）；#5324 提到的"盲区"仅是 skill 自动路由 glob 未覆盖，非脚本本身限制。
- **脚本待修**：check_is_cuda / check_operators_yaml / check_init_registration 内硬编码默认 repo 仍是旧的 `FlagOpen/FlagGems`，应改为 `flagos-ai/FlagGems`（显式传参不受影响，但默认值该修）。
