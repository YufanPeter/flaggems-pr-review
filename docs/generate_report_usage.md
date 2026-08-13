# generate_report.py 使用说明

生成 PR Review 报告的工具脚本。

## 使用场景

### 1. 单个 PR - Review 阶段（待确认方案）

在完成所有检查、提出修复方案后，生成待用户确认的报告。

```bash
python3.11 scripts/generate_report.py single-review <PR> \
  --repo flagos-ai/FlagGems \
  --branch fix/add-convolution \
  --checks checks-result.json \
  --output reports/PR-5395-review.md
```

**输出示例**:
```markdown
# PR #5395 待修复方案

检查结果表格
待确认修复方案（按风险等级分组）
确认执行？ [yes/no]
```

### 2. 单个 PR - 完成阶段（最终总结）

在用户确认并执行完所有修复后，生成最终总结。

```bash
python3.11 scripts/generate_report.py single-final <PR> \
  --repo flagos-ai/FlagGems \
  --branch fix/add-convolution \
  --checks checks-result.json \
  --fixes fixes-result.json \
  --output reports/PR-5395-final.md
```

**输出示例**:
```markdown
# PR #5395 Review 总结

6 项检查，2 项通过，4 项已修复

修改内容
Commits 列表
验证状态
下一步操作
```

### 3. 批量 PR 报告

批量测试多个 PR 后，生成聚合报告。

```bash
python3.11 scripts/generate_report.py batch \
  --prs 5395 5390 5388 5387 \
  --checks-dir ./checks/ \
  --output reports/batch-2026-08-13.md
```

**checks-dir 结构**:
```
checks/
  PR-5395-checks.json
  PR-5390-checks.json
  PR-5388-checks.json
  PR-5387-checks.json
```

**输出示例**:
```markdown
# FlagGems PR 批量 Review 报告

总览表格（按风险排序）
统计信息
需关注的 PR（高/中/低风险分组）
```

## JSON 格式规范

### checks-result.json

```json
{
  "_meta": {
    "pr": "5395",
    "repo": "flagos-ai/FlagGems",
    "branch": "fix/add-convolution"
  },
  "is_cuda": {
    "status": "passed",
    "violations": []
  },
  "skipif": {
    "status": "failed",
    "violations": [
      {
        "file": "tests/test_copy.py",
        "line": 114,
        "description": "vendor-specific skipif",
        "issue_type": "CRITICAL"
      }
    ]
  },
  "code_style": {
    "status": "fixable",
    "mechanical_files": ["tests/test_add.py"],
    "agent_files": ["src/flag_gems/ops/add.py"]
  }
}
```

### fixes-result.json

```json
{
  "applied": [
    {
      "name": "skipif 违规修复",
      "files": ["tests/test_copy.py"]
    },
    {
      "name": "code-style 修复",
      "files": ["tests/test_add.py", "src/flag_gems/ops/add.py"]
    }
  ],
  "commits": [
    "abc123d: fix: remove vendor-specific skipif",
    "def456a: style: apply formatting"
  ],
  "needs_human": [],
  "clone_dir": "/tmp/pr-fix-5395-xyz/repo"
}
```

## 报告输出特点

### 单个 PR - Review 阶段
- 完整的检查结果表格
- 按风险等级分组的修复方案
- 如果全部通过，报告极简（3 行）

### 单个 PR - 完成阶段
- 简洁的统计（X 项检查，Y 项通过，Z 项已修复）
- 修改内容列表
- Commits 记录
- 下一步操作指令
- 如果全部通过，报告极简（2 行）

### 批量报告
- 总览表格（PR、分支、状态、问题数、风险等级）
- 统计信息（通过/需修复/高风险数量）
- 分级展示需关注的 PR（高风险详细列出，低风险只列编号）

## 设计原则

1. **简洁优先**: 没有问题时报告极短
2. **风险驱动**: 高风险问题突出显示
3. **可操作**: 包含具体的下一步指令
4. **可审计**: 记录完整的检查和修复过程
5. **批量友好**: 聚合报告避免信息过载
