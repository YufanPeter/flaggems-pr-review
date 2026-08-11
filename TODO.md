# TODO - 明天的工作

## 1. skipif 检查
- **问题**：测试用例中可能有不合理的 `@pytest.mark.skipif` 装饰器
- **检查内容**：
  - 是否有过于宽泛的 skip 条件
  - skip 理由是否清晰
  - 是否有应该修复而非 skip 的情况
- **工具位置**：`scripts/check_skipif.py`（待实现）
- **能否自动修复**：部分可以（比如补充清晰的 reason）

## 2. block_size 检查
- **问题**：CUDA kernel 的 block_size 设置可能不合理
- **检查内容**：
  - block_size 是否为 2 的幂
  - 是否超出硬件限制（通常最大 1024）
  - 是否有硬编码的 block_size（应该从配置读取）
- **工具位置**：`scripts/check_block_size.py`（待实现）
- **能否自动修复**：❌ 需要性能测试验证

## 3. python-op 检查
- **问题**：Python 算子实现可能有问题（这是 CI 第二大失败源，5/120 PRs）
- **检查内容**：
  - 算子参数签名是否与 PyTorch 一致
  - 是否缺少必需的参数
  - 返回类型是否正确
  - 是否缺少测试覆盖
- **工具位置**：`scripts/check_python_op.py`（待实现）
- **能否自动修复**：部分可以（比如补全缺少的参数、添加类型标注）

## 当前进度

### ✅ 已完成（今天）
1. `check_is_cuda.py` - is_cuda 滥用检查
2. `check_init_registration.py` - __init__.py 排序检查
3. `check_operators_yaml.py` - operators.yaml 排序检查
4. `fix_code_style.py` - code-style 自动修复（机械 + agent）

### 🔄 进行中
- Agent-driven skill 设计（让 agent 智能调用所有检查）

### ⏳ 明天做
1. 实现 skipif 检查
2. 实现 block_size 检查
3. 实现 python-op 检查
4. 完善 agent-driven review skill

## 相关数据

从 120 个 PR 的 CI 失败统计：
- code-style: 16 次（已解决）
- **python-op: 5 次**（明天重点）
- backend-tests: 9 次（后续）

## 参考
- PR-Review 仓库：`/Users/yufan.shi/Desktop/PR-Review`
- 上游仓库：`flagos-ai/FlagGems`
