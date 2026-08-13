# fix_code_style.py 重构方案A实现文档

## 变更概述

重构 `fix_code_style.py` 为两阶段模式，使其符合统一原则：**detect → propose → approve → fix → verify**

## 新旧对比

### 旧版本 (fix_code_style.py)

```
fix_pr_code_style(pr) {
  1. clone PR
  2. 机械修复 → make_commit()  ❌ 未经确认就 commit
  3. Agent 修复 → make_commit()  ❌ 未经确认就 commit
  4. 验证
  5. 返回状态
}
```

**问题**: 跳过了 "propose + approve" 步骤，直接执行修复并 commit。

### 新版本 (fix_code_style_v2.py)

```
Phase 1: dry-run (propose)
  1. clone PR
  2. 机械修复（不 commit）→ 算 diff
  3. Agent 修复（不 commit）→ 算 diff
  4. 验证
  5. 输出: {status, diffs, risk_levels, state_file}

Phase 2: apply (fix after approval)
  1. 读取状态文件
  2. 应用修复
  3. commit
  4. 输出 push 指令
```

**符合主线**: 完整的 detect → propose → approve → fix → verify 流程。

## 使用方式

### Phase 1: dry-run（计算修复方案）

```bash
./scripts/fix_code_style_v2.py dry-run <PR编号或URL> [--json]
```

**输出**:
```json
{
  "check": "code_style_fix",
  "pr": "123",
  "repo": "flagos-ai/FlagGems",
  "status": "fixable",
  "state_file": "/tmp/pr-fix-123-xxx/state.json",
  "mechanical_diff": "...",
  "agent_diff": "...",
  "risk_levels": {
    "file1.py": "green",   // 🟢 机械修复，无风险
    "file2.py": "yellow"   // 🟡 Agent修复，低风险
  },
  "verification": {
    "pre_commit_passed": true,
    "fixed_files": ["file1.py", "file2.py"]
  }
}
```

### Phase 2: apply（应用修复）

```bash
./scripts/fix_code_style_v2.py apply <state_file>
```

**输出**:
```json
{
  "status": "applied",
  "pr": "123",
  "commits": ["sha1", "sha2"],
  "clone_dir": "/tmp/pr-fix-123-xxx/repo",
  "mode": "writable"
}
```

## 状态文件格式

`state.json` 保存了 dry-run 的完整状态：

```json
{
  "pr": "123",
  "repo": "flagos-ai/FlagGems",
  "head": {
    "branch": "fix-xxx",
    "sha": "abc123...",
    "fork": "user/FlagGems"
  },
  "clone_dir": "/tmp/pr-fix-123-xxx/repo",
  "mode": "writable",
  "pr_files": ["file1.py", "file2.py"],
  "mechanical_diff": "...",
  "agent_diff": "...",
  "risk_levels": {
    "file1.py": "green",
    "file2.py": "yellow"
  },
  "verification": {
    "pre_commit_passed": true,
    "fixed_files": ["file1.py", "file2.py"]
  },
  "status": "fixable"
}
```

## 风险标注

- 🟢 **green** (机械修复): black/isort/eof 自动格式化，无风险
- 🟡 **yellow** (Agent修复): Claude 辅助修复 flake8/mypy 错误，低风险
- 🔴 **red** (测试失败): 修复后测试失败，需人工检查（当前版本暂不支持测试）

## Skill 集成流程

### Step 1: 检测（detect）

Skill 调用 `check_*` 脚本发现 code-style 失败。

### Step 2: 计算修复（propose）

```python
result = subprocess.run(
    ['./scripts/fix_code_style_v2.py', 'dry-run', pr_number, '--json'],
    capture_output=True, text=True, check=True
)
data = json.loads(result.stdout)
```

### Step 3: 展示方案（propose to user）

Agent 向用户展示：

```markdown
## 修复方案

**机械修复** (3 文件，🟢 无风险):
- file1.py: black 格式化
- file2.py: isort 排序
- file3.py: 文件末尾加换行

**Agent 修复** (2 文件，🟡 低风险):
- file4.py: 删除未使用的 import (L15)
- file5.py: 修复 line too long (L42)

验证: ✅ 所有 pre-commit 检查通过

确认应用修复？[yes/no]
```

### Step 4: 用户确认（approve）

用户输入 `yes`。

### Step 5: 执行修复（fix）

```python
result = subprocess.run(
    ['./scripts/fix_code_style_v2.py', 'apply', state_file],
    capture_output=True, text=True, check=True
)
```

### Step 6: 验证并 push（verify）

```bash
cd <clone_dir>
git push origin HEAD:<branch>
```

## 退出码

- **0**: 成功（clean 或 fixable）
- **1**: 需要人工（无法自动修复）
- **2**: 错误（执行失败）

## 与旧版本的兼容性

### 迁移步骤

1. **立即**: Skill 更新为调用 `fix_code_style_v2.py`
2. **验证**: 测试几个 PR 确认流程正确
3. **清理**: 删除旧的 `fix_code_style.py`

### 命令对比

**旧版**:
```bash
./scripts/fix_code_style.py <PR>
# → 直接 commit，打印 push 指令
```

**新版**:
```bash
# Step 1: 计算方案
./scripts/fix_code_style_v2.py dry-run <PR> --json

# Step 2: 用户确认后应用
./scripts/fix_code_style_v2.py apply <state_file>
```

## 关键设计决策

### 1. 为什么分两次 commit？

机械修复（green）和 Agent 修复（yellow）分开 commit，便于：
- 代码审查时区分自动和半自动修复
- 如果 Agent 修复有问题，只需 revert 第二个 commit

### 2. 为什么保存状态文件？

状态文件是 dry-run 和 apply 之间的契约：
- 保证幂等性：同样的状态文件总是产生同样的 commit
- 支持审计：可以事后查看修复是基于什么计算的

### 3. 为什么不在 apply 时重新跑修复？

**原则**: apply 阶段只应用 dry-run 已经验证过的修复，不应该重新计算。

如果重新跑：
- Agent 可能给出不同的修复（非确定性）
- 用户 approve 的 diff 和实际 commit 的不一致

### 4. clone_dir 的生命周期

- **dry-run**: 创建临时目录，返回路径
- **apply**: 读取 dry-run 创建的目录，commit 后保留
- **清理**: 由用户或 skill 在 push 后删除

## 测试

### 测试场景 1: 只需机械修复

```bash
# dry-run
./scripts/fix_code_style_v2.py dry-run 123 --json
# → status: fixable, mechanical_diff 有内容, agent_diff 为空

# apply
./scripts/fix_code_style_v2.py apply /tmp/pr-fix-123-xxx/state.json
# → 1 个 commit (mechanical only)
```

### 测试场景 2: 机械 + Agent 修复

```bash
# dry-run
./scripts/fix_code_style_v2.py dry-run 456 --json
# → status: fixable, 两个 diff 都有内容

# apply
./scripts/fix_code_style_v2.py apply /tmp/pr-fix-456-xxx/state.json
# → 2 个 commit (mechanical + agent)
```

### 测试场景 3: 无法自动修复

```bash
# dry-run
./scripts/fix_code_style_v2.py dry-run 789 --json
# → status: needs_human, verification.blocking_hooks 列出失败的检查

# apply
# 不应该调用，status 不是 fixable
```

## 后续改进

1. **增量修复**: 如果 dry-run 后文件被外部修改，apply 时检测并报错
2. **测试集成**: dry-run 阶段可选跑测试，标注风险为 red
3. **并行 Agent**: 多个文件并行调用 Agent 加速
4. **修复策略可配置**: 允许跳过某些 hook 或只跑机械修复

## 总结

新版本 `fix_code_style_v2.py` 完全符合统一原则：

- ✅ **detect**: 识别 code-style 失败
- ✅ **propose**: dry-run 输出完整 diff + 风险标注
- ✅ **approve**: 用户 review 后决定是否 apply
- ✅ **fix**: apply 阶段执行 commit
- ✅ **verify**: pre-commit 验证 + 可选测试

与其他检查脚本（is_cuda/block_size/skipif/python_op）一致，不再是例外。
