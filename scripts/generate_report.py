#!/usr/bin/env python3.11
"""
生成 PR Review 报告（单个或批量）。

Usage:
  # 单个 PR 报告（review 阶段 - 待确认方案）
  generate_report.py single-review <PR> --checks checks.json --output report.md

  # 单个 PR 报告（完成阶段 - 最终总结）
  generate_report.py single-final <PR> --checks checks.json --fixes fixes.json --output report.md

  # 批量报告
  generate_report.py batch --prs <PR1> <PR2> ... --checks-dir ./checks/ --output batch-report.md
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


def format_timestamp() -> str:
    """生成时间戳: 2026-08-13 14:25:30"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def count_issues(checks: Dict[str, Any]) -> int:
    """统计问题总数"""
    total = 0
    for check_name, result in checks.items():
        if isinstance(result, dict):
            if 'violations' in result:
                total += len(result['violations'])
            elif 'status' in result and result['status'] in ['failed', 'needs_fix']:
                total += 1
    return total


def get_risk_level(checks: Dict[str, Any]) -> str:
    """判断整体风险等级"""
    # 如果有 is_cuda 违规 → 高风险
    if 'is_cuda' in checks and checks['is_cuda'].get('status') == 'failed':
        return '高'

    # 如果有 python-op 失败 → 高风险
    if 'python_op' in checks and checks['python_op'].get('status') == 'failed':
        return '高'

    # 如果有 block_size 硬编码 → 中风险
    if 'block_size' in checks and checks['block_size'].get('status') == 'failed':
        return '中'

    # 其他（skipif / 排序 / code-style）→ 低风险
    issue_count = count_issues(checks)
    if issue_count > 0:
        return '低'

    return '-'


def generate_single_review_report(
    pr: str,
    repo: str,
    branch: str,
    checks: Dict[str, Any],
    output: Path
) -> None:
    """生成单个 PR 的 review 阶段报告（待确认方案）"""

    lines = []
    lines.append(f"# PR #{pr} 待修复方案\n")
    lines.append(f"**时间**: {format_timestamp()}  ")
    lines.append(f"**仓库**: {repo}  ")
    lines.append(f"**分支**: {branch}\n")
    lines.append("---\n")

    # 检查结果表格
    lines.append("## 检查结果\n")
    lines.append("| 检查项 | 状态 | 问题数 |")
    lines.append("|--------|------|--------|")

    check_order = ['is_cuda', 'block_size', 'skipif', 'init_registration',
                   'operators_yaml', 'code_style', 'python_op']

    has_issues = False
    for check_name in check_order:
        if check_name not in checks:
            continue

        result = checks[check_name]
        status = result.get('status', 'unknown')

        # 状态映射
        status_display = {
            'passed': '通过',
            'clean': '通过',
            'failed': '需修复',
            'needs_fix': '需修复',
            'fixable': '需修复',
            'needs_human': '需人工处理'
        }.get(status, status)

        # 问题数
        issue_count = 0
        if 'violations' in result:
            issue_count = len(result['violations'])
        elif status in ['failed', 'needs_fix', 'fixable']:
            issue_count = result.get('file_count', 1)

        if issue_count > 0:
            has_issues = True

        lines.append(f"| {check_name} | {status_display} | {issue_count} |")

    lines.append("\n---\n")

    # 如果没有问题,简短总结
    if not has_issues:
        lines.append("## 总结\n")
        lines.append("所有检查通过,无需修复。\n")
        output.write_text('\n'.join(lines), encoding='utf-8')
        return

    # 待确认修复方案
    lines.append("## 待确认修复方案\n")

    proposal_num = 1

    # is_cuda 违规
    if 'is_cuda' in checks and checks['is_cuda'].get('status') == 'failed':
        violations = checks['is_cuda'].get('violations', [])
        if violations:
            lines.append(f"### {proposal_num}. is_cuda 违规（高风险）\n")
            for v in violations:
                lines.append(f"- {v['file']}:{v['line']} - {v['description']}")
            lines.append("")
            proposal_num += 1

    # block_size 硬编码
    if 'block_size' in checks and checks['block_size'].get('status') == 'failed':
        violations = checks['block_size'].get('violations', [])
        if violations:
            lines.append(f"### {proposal_num}. block_size 硬编码（中风险）\n")
            for v in violations:
                lines.append(f"- {v['file']}:{v['line']} - 改为动态计算")
            lines.append("")
            proposal_num += 1

    # skipif 问题
    if 'skipif' in checks and checks['skipif'].get('status') == 'failed':
        violations = checks['skipif'].get('violations', [])
        if violations:
            lines.append(f"### {proposal_num}. skipif 违规（低风险）\n")
            for v in violations:
                lines.append(f"- {v['file']}:{v['line']} - {v.get('issue_type', '删除 skipif')}")
            lines.append("")
            proposal_num += 1

    # 排序问题
    if 'init_registration' in checks and checks['init_registration'].get('status') == 'needs_fix':
        lines.append(f"### {proposal_num}. __all__ 排序（无风险）\n")
        violations = checks['init_registration'].get('violations', [])
        for v in violations:
            lines.append(f"- {v['file']} - 按字母序重排")
        lines.append("")
        proposal_num += 1

    if 'operators_yaml' in checks and checks['operators_yaml'].get('status') == 'needs_fix':
        lines.append(f"### {proposal_num}. operators.yaml 排序（无风险）\n")
        lines.append("- operators.yaml - 按字母序重排算子 ID")
        lines.append("")
        proposal_num += 1

    # code-style 问题
    if 'code_style' in checks and checks['code_style'].get('status') in ['fixable', 'needs_fix']:
        lines.append(f"### {proposal_num}. code-style（机械无风险 / Agent低风险）\n")
        result = checks['code_style']
        if 'mechanical_files' in result:
            for f in result['mechanical_files']:
                lines.append(f"- {f} - 机械格式化")
        if 'agent_files' in result:
            for f in result['agent_files']:
                lines.append(f"- {f} - Agent 修复")
        lines.append("")
        proposal_num += 1

    # python-op 失败
    if 'python_op' in checks and checks['python_op'].get('status') == 'failed':
        lines.append(f"### {proposal_num}. python-op CI 失败（需分析）\n")
        failures = checks['python_op'].get('failures', [])
        for f in failures[:3]:  # 只显示前3个
            lines.append(f"- {f.get('test', 'unknown')} - {f.get('type', 'unknown error')}")
        if len(failures) > 3:
            lines.append(f"- ...（共 {len(failures)} 个失败）")
        lines.append("")
        proposal_num += 1

    # 无法自动修复的问题
    needs_human = []
    for check_name, result in checks.items():
        if result.get('status') == 'needs_human':
            needs_human.append(f"{check_name}: {result.get('reason', 'unknown')}")

    if needs_human:
        lines.append("**无法自动修复**:\n")
        for item in needs_human:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("**确认执行？** [yes/no]\n")

    output.write_text('\n'.join(lines), encoding='utf-8')


def generate_single_final_report(
    pr: str,
    repo: str,
    branch: str,
    checks: Dict[str, Any],
    fixes: Dict[str, Any],
    output: Path
) -> None:
    """生成单个 PR 的最终总结报告"""

    lines = []
    lines.append(f"# PR #{pr} Review 总结\n")
    lines.append(f"**时间**: {format_timestamp()}  ")
    lines.append(f"**仓库**: {repo}  ")
    lines.append(f"**分支**: {branch}\n")
    lines.append("---\n")

    # 统计
    total_checks = len(checks)
    passed = sum(1 for r in checks.values() if r.get('status') in ['passed', 'clean'])
    fixed = len(fixes.get('applied', []))

    lines.append("## 检查结果\n")
    lines.append(f"{total_checks} 项检查，{passed} 项通过，{fixed} 项已修复\n")
    lines.append("---\n")

    # 如果全部通过
    if passed == total_checks:
        lines.append("## 总结\n")
        lines.append("PR 代码质量良好，无需修复。\n")
        output.write_text('\n'.join(lines), encoding='utf-8')
        return

    # 修改内容
    lines.append("## 修改内容\n")

    applied = fixes.get('applied', [])
    for fix in applied:
        name = fix.get('name', 'unknown')
        files = fix.get('files', [])
        if files:
            lines.append(f"- {name}: {', '.join(files[:3])}")
            if len(files) > 3:
                lines.append(f"  （共 {len(files)} 个文件）")

    lines.append("")

    # Commits
    commits = fixes.get('commits', [])
    if commits:
        lines.append(f"**Commits**: {len(commits)} 个  ")
        for c in commits[:3]:
            lines.append(f"- {c}")
        if len(commits) > 3:
            lines.append(f"- ...（共 {len(commits)} 个）")
        lines.append("")

    lines.append("**验证**: 全部通过\n")
    lines.append("---\n")

    # 总结
    lines.append("## 总结\n")
    lines.append(f"- 已修复: {fixed} 项")

    needs_human = fixes.get('needs_human', [])
    if needs_human:
        lines.append(f"- 需人工处理: {len(needs_human)} 项")

    clone_dir = fixes.get('clone_dir', '')
    if clone_dir:
        lines.append(f"- 临时目录: {clone_dir}")
        lines.append(f"- 下一步: `cd {clone_dir} && git push origin HEAD:{branch}`")

    lines.append("")

    output.write_text('\n'.join(lines), encoding='utf-8')


def generate_batch_report(
    prs: List[str],
    checks_dir: Path,
    output: Path
) -> None:
    """生成批量 PR 报告"""

    lines = []
    lines.append("# FlagGems PR 批量 Review 报告\n")
    lines.append(f"**时间**: {format_timestamp()}  ")
    lines.append(f"**PR 范围**: {len(prs)} 个 PR\n")
    lines.append("---\n")

    # 收集所有 PR 的检查结果
    pr_data = []
    for pr in prs:
        check_file = checks_dir / f"PR-{pr}-checks.json"
        if not check_file.exists():
            continue

        checks = json.loads(check_file.read_text(encoding='utf-8'))
        repo = checks.get('_meta', {}).get('repo', 'flagos-ai/FlagGems')
        branch = checks.get('_meta', {}).get('branch', 'unknown')

        issue_count = count_issues(checks)
        risk = get_risk_level(checks)

        # 检查状态
        if issue_count == 0:
            status = '全部通过'
        else:
            failed_count = sum(1 for r in checks.values()
                             if isinstance(r, dict) and r.get('status') in ['failed', 'needs_fix', 'fixable'])
            status = f"{failed_count}/{len(checks)} 需修复"

        pr_data.append({
            'pr': pr,
            'branch': branch,
            'status': status,
            'issue_count': issue_count,
            'risk': risk,
            'checks': checks
        })

    # 总览表格
    lines.append("## 总览\n")
    lines.append("| PR | 分支 | 检查状态 | 需修复 | 风险等级 |")
    lines.append("|----|------|----------|--------|----------|")

    for item in pr_data:
        lines.append(f"| #{item['pr']} | {item['branch'][:30]} | {item['status']} | "
                    f"{item['issue_count']} 项 | {item['risk']} |")

    lines.append("")

    # 统计
    all_passed = sum(1 for item in pr_data if item['issue_count'] == 0)
    needs_fix = len(pr_data) - all_passed
    high_risk = sum(1 for item in pr_data if item['risk'] == '高')
    total_issues = sum(item['issue_count'] for item in pr_data)

    lines.append("**统计**:")
    lines.append(f"- 全部通过: {all_passed} 个")
    lines.append(f"- 需修复: {needs_fix} 个（其中高风险 {high_risk} 个）")
    lines.append(f"- 总问题数: {total_issues} 项\n")
    lines.append("---\n")

    # 需关注的 PR（高风险优先）
    lines.append("## 需关注的 PR\n")

    high_risk_prs = [item for item in pr_data if item['risk'] == '高']
    medium_risk_prs = [item for item in pr_data if item['risk'] == '中']
    low_risk_prs = [item for item in pr_data if item['risk'] == '低']

    if high_risk_prs:
        lines.append("### 高风险\n")
        for item in high_risk_prs:
            lines.append(f"**PR #{item['pr']}** - {item['branch']}")
            checks = item['checks']
            if 'is_cuda' in checks and checks['is_cuda'].get('status') == 'failed':
                count = len(checks['is_cuda'].get('violations', []))
                lines.append(f"- is_cuda 违规 {count} 处（影响跨芯片兼容）")
            if 'python_op' in checks and checks['python_op'].get('status') == 'failed':
                count = len(checks['python_op'].get('failures', []))
                lines.append(f"- python-op CI 失败 {count} 个测试")
            lines.append("")

    if medium_risk_prs:
        lines.append("### 中风险\n")
        for item in medium_risk_prs:
            lines.append(f"**PR #{item['pr']}** - {item['branch']}")
            checks = item['checks']
            if 'block_size' in checks and checks['block_size'].get('status') == 'failed':
                count = len(checks['block_size'].get('violations', []))
                lines.append(f"- block_size 硬编码 {count} 处")
            lines.append("")

    if low_risk_prs:
        lines.append("### 低风险（可自动修复）\n")
        pr_list = ', '.join(f"#{item['pr']}" for item in low_risk_prs)
        lines.append(f"{pr_list}\n")

    passed_prs = [item for item in pr_data if item['issue_count'] == 0]
    if passed_prs:
        lines.append("### 全部通过\n")
        pr_list = ', '.join(f"#{item['pr']}" for item in passed_prs)
        lines.append(f"{pr_list}\n")

    output.write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='生成 PR Review 报告')
    subparsers = parser.add_subparsers(dest='mode', help='报告模式')

    # 单个 PR - review 阶段
    single_review = subparsers.add_parser('single-review', help='单个 PR review 阶段报告')
    single_review.add_argument('pr', help='PR 编号')
    single_review.add_argument('--repo', default='flagos-ai/FlagGems', help='仓库名')
    single_review.add_argument('--branch', default='unknown', help='分支名')
    single_review.add_argument('--checks', required=True, help='检查结果 JSON 文件')
    single_review.add_argument('--output', required=True, help='输出 MD 文件路径')

    # 单个 PR - 完成阶段
    single_final = subparsers.add_parser('single-final', help='单个 PR 最终总结报告')
    single_final.add_argument('pr', help='PR 编号')
    single_final.add_argument('--repo', default='flagos-ai/FlagGems', help='仓库名')
    single_final.add_argument('--branch', default='unknown', help='分支名')
    single_final.add_argument('--checks', required=True, help='检查结果 JSON 文件')
    single_final.add_argument('--fixes', required=True, help='修复结果 JSON 文件')
    single_final.add_argument('--output', required=True, help='输出 MD 文件路径')

    # 批量报告
    batch = subparsers.add_parser('batch', help='批量 PR 报告')
    batch.add_argument('--prs', nargs='+', required=True, help='PR 编号列表')
    batch.add_argument('--checks-dir', required=True, help='检查结果目录')
    batch.add_argument('--output', required=True, help='输出 MD 文件路径')

    args = parser.parse_args()

    if not args.mode:
        parser.print_help()
        sys.exit(1)

    try:
        if args.mode == 'single-review':
            checks = json.loads(Path(args.checks).read_text(encoding='utf-8'))
            generate_single_review_report(
                args.pr,
                args.repo,
                args.branch,
                checks,
                Path(args.output)
            )
            print(f"✓ Review 阶段报告已生成: {args.output}")

        elif args.mode == 'single-final':
            checks = json.loads(Path(args.checks).read_text(encoding='utf-8'))
            fixes = json.loads(Path(args.fixes).read_text(encoding='utf-8'))
            generate_single_final_report(
                args.pr,
                args.repo,
                args.branch,
                checks,
                fixes,
                Path(args.output)
            )
            print(f"✓ 最终总结报告已生成: {args.output}")

        elif args.mode == 'batch':
            generate_batch_report(
                args.prs,
                Path(args.checks_dir),
                Path(args.output)
            )
            print(f"✓ 批量报告已生成: {args.output}")

    except Exception as e:
        print(f"✗ 生成报告失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
