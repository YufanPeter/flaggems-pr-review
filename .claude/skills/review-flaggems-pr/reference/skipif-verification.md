# skipif reason 验证详解

`check_skipif.py` 检测测试中新增的 `@pytest.mark.skipif` 装饰器。本文档说明如何验证 reason 是否成立、如何分流。

## 问题分类

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

# 🟢 INFO - reasonable（可能合理，需人工确认）
@pytest.mark.skipif(TE_OP is None, reason="TransformerEngine not installed")
# → 依赖检查，可能是合理的前提条件
```

## 核心原则：reason 是「主张」，不是「证据」

skipif 的分类只分两步（脚本已按此实现）：

1. **没有 reason** → 明确错误，直接删除。
2. **有 reason** → 标记为 `needs_verification`，**必须验证 reason 是否真的成立**，不能因为写了 reason 就放过。

脚本会为每个带 reason 的 skipif 输出：
- `issue_ref` / `operator`：从 reason 提取的 issue 号、从文件名推导的算子名
- `verification_checklist`：逐条要核对的点
- `timeline`：**自动**拉取 issue 与 PR 的创建时间做对比，给出 `verdict`
  （`reason_invalid` / `timeline_ok` / `unknown`）

## 验证 reason 的三个校验点（按此顺序逐条排查）

### 1. 算子名匹配

issue 是否真的把这个算子列为不支持？近似名不算匹配。

> 校准案例 **PR #5399**：reason 引用 Issue #5254，但该 issue 列的是
> `special_chebyshev_polynomial_**w**`，PR 是 `_**t**` 变体 —— 名称对不上，reason 不成立。

### 2. 时间线（机械可判定，脚本已自动完成）

issue 创建时间是否早于 PR？
**早于 PR 的 issue 不可能描述本 PR 新增的实现 —— 因果倒置，reason 不成立。**

看脚本输出的 `timeline.verdict`：
- `reason_invalid` → 因果倒置，判错
- `timeline_ok` → 时间上可能覆盖，继续核对算子名与 issue 内容
- `unknown` → 时间戳拉取失败，人工核对

> 校准案例 **PR #5290**：reason 引用 Issue #4131（2026-06 创建，基于更早的
> PR #3782 旧 backend），PR 是 2026-08 才新增的 convolution Triton kernel。
> 一个 6 月的 issue 覆盖不了 8 月的新实现 —— 判错。

### 3. issue 质量与状态

issue 描述是否清晰、是否被维护者质疑、state 是否仍 OPEN、是否只是测试基准问题
（如标题 "failed without --ref cpu" 其实是 `--ref` 配置问题，而非算子真的不支持）。
描述含糊或问题性质对不上，不足以支撑跳过整个测试。

**结论逻辑**：三点中任何一点不成立 → reason 不成立 → 删除 skipif。
三点全部成立才可保留，且需在报告中注明「保留但需跟踪 issue 修复进度」。

## 终判分流：哪些不用 agent 看，哪些必须看

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
