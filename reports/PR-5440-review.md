# PR #5440 待修复方案

**时间**: 2026-08-13 16:25:30  
**仓库**: flagos-ai/FlagGems  
**分支**: kernelgen/addr_

---

## 检查结果

| 检查项 | 状态 | 问题数 |
|--------|------|--------|
| is_cuda | 通过 | 0 |
| block_size | 需修复 | 2 |
| skipif | 通过 | 0 |
| init_registration | 通过 | 0 |
| operators_yaml | 通过 | 0 |
| python-op | 通过 | 0 |

---

## 待确认修复方案

### block_size 硬编码（中风险）

**src/flag_gems/ops/addr_.py:77-78**

当前代码：
```python
BLOCK_SIZE_M = 32  # Tile size for rows
BLOCK_SIZE_N = 32  # Tile size for columns
```

**问题**：
- BLOCK_SIZE_M 和 BLOCK_SIZE_N 硬编码为 32
- 违反 FlagGems 最佳实践：动态 block size 让 Triton JIT 编译器为不同工作负载优化

**建议修复**：
```python
BLOCK_SIZE_M = min(32, triton.next_power_of_2(M))
BLOCK_SIZE_N = min(32, triton.next_power_of_2(N))
```

**风险等级**: 中风险
- 改动影响性能，但不改变语义
- 对小矩阵可能改变实际使用的 block size
- 需要测试验证性能无回退

**确认执行？** [yes/no]
