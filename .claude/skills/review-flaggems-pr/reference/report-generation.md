# 报告生成详解

`generate_report.py` 提供三种报告模式。所有命令均假设已 `cd` 到仓库根目录。

## 模式 1：single-review（待确认方案报告）

在完成所有检查、分析问题、提出修复方案后，生成待确认方案报告：

```bash
# 准备检查结果 JSON
cat > checks-result.json << 'EOF'
{
  "_meta": {"pr": "5395", "repo": "flagos-ai/FlagGems", "branch": "fix/add-convolution"},
  "is_cuda": {"status": "passed", "violations": []},
  "skipif": {"status": "failed", "violations": [...]},
  "code_style": {"status": "fixable", "mechanical_files": [...], "agent_files": [...]}
}
EOF

# 生成报告
python3.11 scripts/generate_report.py \
  single-review 5395 \
  --repo flagos-ai/FlagGems \
  --branch fix/add-convolution \
  --checks checks-result.json \
  --output reports/PR-5395-review.md
```

**报告内容**（示例）：
```markdown
# PR #5395 待修复方案

检查结果表格（通过/需修复/问题数）
待确认修复方案（按风险等级分组）
无法自动修复的问题
确认执行？ [yes/no]
```

向用户展示报告内容并等待确认。

## 模式 2：single-final（最终总结报告）

用户确认后执行修复，然后生成最终总结：

```bash
# 准备修复结果 JSON
cat > fixes-result.json << 'EOF'
{
  "applied": [
    {"name": "skipif 违规修复", "files": ["tests/test_copy.py"]},
    {"name": "code-style 修复", "files": ["tests/test_add.py", "src/flag_gems/ops/add.py"]}
  ],
  "commits": [
    "abc123d: fix: remove vendor-specific skipif",
    "def456a: style: apply formatting"
  ],
  "needs_human": ["tests/test_add.py:15 undefined name"],
  "clone_dir": "/tmp/pr-fix-5395-xyz/repo"
}
EOF

# 生成最终总结
python3.11 scripts/generate_report.py \
  single-final 5395 \
  --repo flagos-ai/FlagGems \
  --branch fix/add-convolution \
  --checks checks-result.json \
  --fixes fixes-result.json \
  --output reports/PR-5395-final.md
```

**报告内容**（示例）：
```markdown
# PR #5395 Review 总结

6 项检查，2 项通过，4 项已修复

修改内容
- skipif 违规修复: tests/test_copy.py
- code-style 修复: tests/test_add.py, src/flag_gems/ops/add.py

Commits: 2 个
验证: 全部通过

总结
- 已修复: 4 项
- 需人工处理: 1 项
- 下一步: cd /tmp/pr-fix-5395-xyz/repo && git push origin HEAD:fix/add-convolution
```

向用户展示最终报告，告知下一步操作。

## 模式 3：batch（批量聚合报告）

同时审查多个 PR 时使用：

```bash
# 假设已完成多个 PR 的检查，每个生成了 checks JSON
# checks/
#   PR-5395-checks.json
#   PR-5390-checks.json
#   PR-5388-checks.json

python3.11 scripts/generate_report.py \
  batch \
  --prs 5395 5390 5388 5387 \
  --checks-dir ./checks/ \
  --output reports/batch-2026-08-13.md
```

**报告内容**（示例）：
```markdown
# FlagGems PR 批量 Review 报告

总览表格（PR、分支、状态、问题数、风险等级）

统计
- 全部通过: 1 个
- 需修复: 3 个（其中高风险 1 个）
- 总问题数: 15 项

需关注的 PR
- 高风险: #5387（is_cuda 违规 3 处）
- 中风险: #5395（skipif 2 处）
- 低风险: #5388, #5390
```

批量报告提供聚合视图，高风险 PR 详细列出，低风险 PR 只列编号，避免信息过载。

## 报告文件约定

- Review 阶段报告：`reports/PR-{number}-review.md`（待确认方案）
- 最终总结报告：`reports/PR-{number}-final.md`（执行结果）
- 批量报告：`reports/batch-{timestamp}.md`（聚合视图）
- 所有报告文件保存在仓库的 `reports/` 目录
