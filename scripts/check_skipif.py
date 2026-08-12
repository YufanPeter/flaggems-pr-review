#!/usr/bin/env python3.11
"""
Check for pytest.mark.skipif usage in FlagGems PRs.

Problem: AI-written tests may add skipif decorators to skip failing tests
instead of fixing the actual issues. This is particularly problematic for
vendor-specific skipif that violates FlagGems' cross-chip compatibility goal.

Detection categories:
    1. CRITICAL - vendor-specific skipif (e.g. flag_gems.vendor_name == "metax")
    2. CRITICAL - CUDA-specific skipif (e.g. not torch.cuda.is_available())
    3. WARNING - lazy skipif (e.g. skipif(True, reason="TODO"))
    4. INFO - reasonable dependency checks (e.g. library not installed, version requirement)

All new skipif decorators in a PR are reported for human review.
"""

import argparse
import ast
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_REPO = "flagos-ai/FlagGems"


# --- GitHub helpers ---

def parse_pr_ref(pr_url_or_number: str) -> Tuple[str, str]:
    if pr_url_or_number.isdigit():
        return DEFAULT_REPO, pr_url_or_number
    match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_url_or_number)
    if not match:
        raise ValueError(f"Cannot parse PR ref: {pr_url_or_number}")
    owner, repo_name, pr_number = match.groups()
    return f"{owner}/{repo_name}", pr_number


def get_pr_files(repo: str, pr_number: str) -> List[Dict[str, Any]]:
    result = subprocess.run(
        ['gh', 'api', f'repos/{repo}/pulls/{pr_number}/files',
         '--paginate', '--jq', '.[]'],
        capture_output=True, text=True, check=True,
    )
    files = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            try:
                files.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return files


def get_pr_head_sha(repo: str, pr_number: str) -> str:
    result = subprocess.run(
        ['gh', 'pr', 'view', pr_number, '--repo', repo, '--json', 'headRefOid'],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)['headRefOid']


def get_file_content(repo: str, sha: str, path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/{repo}/contents/{path}?ref={sha}',
             '--jq', '.content'],
            capture_output=True, text=True, check=True,
        )
        return base64.b64decode(result.stdout.strip()).decode('utf-8', errors='replace')
    except subprocess.CalledProcessError:
        return None


# --- Skipif analysis ---

def added_lines_from_patch(patch: str) -> set:
    """Return the set of new line numbers introduced by this patch."""
    added: set = set()
    current = 0
    for line in patch.splitlines():
        if line.startswith('@@'):
            m = re.search(r'\+(\d+)', line)
            if m:
                current = int(m.group(1)) - 1
        elif line.startswith('+') and not line.startswith('+++'):
            current += 1
            added.add(current)
        elif not line.startswith('-'):
            current += 1
    return added


def find_skipif_decorators(source: str, filepath: str) -> List[Dict[str, Any]]:
    """
    Find all @pytest.mark.skipif decorators in the source.

    Returns a list of skipif info dicts with:
    - line: line number
    - decorator: full decorator text
    - condition: skipif condition (extracted)
    - reason: reason string (extracted)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    skipifs = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue

        for dec in node.decorator_list:
            # Check if this is @pytest.mark.skipif
            is_skipif = False
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Attribute):
                    # @pytest.mark.skipif(...)
                    if (isinstance(dec.func.value, ast.Attribute) and
                        dec.func.value.attr == 'mark' and
                        dec.func.attr == 'skipif'):
                        is_skipif = True
                # Also handle @mark.skipif(...) if pytest.mark is imported as mark
                elif isinstance(dec.func, ast.Attribute) and dec.func.attr == 'skipif':
                    is_skipif = True

            if not is_skipif:
                continue

            # Extract condition and reason
            condition_str = ""
            reason_str = ""

            if isinstance(dec, ast.Call):
                # First positional arg is condition
                if dec.args:
                    condition_str = ast.unparse(dec.args[0])

                # reason is a keyword argument
                for kw in dec.keywords:
                    if kw.arg == 'reason':
                        if isinstance(kw.value, ast.Constant):
                            reason_str = kw.value.value

            # Get the decorator line from source
            lineno = dec.lineno
            decorator_lines = []
            # Decorators can span multiple lines
            i = lineno - 1
            while i < len(lines):
                line = lines[i].strip()
                decorator_lines.append(lines[i])
                if ')' in line:
                    break
                i += 1

            decorator_text = '\n'.join(decorator_lines)

            skipifs.append({
                'file': filepath,
                'line': lineno,
                'test_function': node.name,
                'decorator': decorator_text,
                'condition': condition_str,
                'reason': reason_str,
            })

    return skipifs


def classify_skipif(skipif: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """
    Classify a skipif decorator.

    Returns: (severity, category, message, suggestion)
    - severity: 'critical' | 'warning' | 'info'
    - category: 'vendor_specific' | 'cuda_specific' | 'lazy' | 'reasonable'
    - message: description of the issue
    - suggestion: how to fix it
    """
    condition = skipif['condition'].lower()
    reason = skipif['reason'].lower()

    # CRITICAL: vendor-specific skipif
    if 'vendor_name' in condition:
        return (
            'critical',
            'vendor_specific',
            'vendor-specific skipif 违反跨芯片兼容原则：不应该因芯片类型跳过测试',
            '删除 skipif 装饰器，如果测试在某芯片上失败，应修复算子实现而不是跳过测试'
        )

    # CRITICAL: CUDA-specific skipif
    if 'cuda' in condition or 'is_cuda' in skipif['condition']:
        return (
            'critical',
            'cuda_specific',
            'CUDA-specific skipif 违反跨芯片兼容原则：硬编码 CUDA 依赖',
            '移除 CUDA 检查，使用 flag_gems.device 以支持多种芯片'
        )

    # WARNING: lazy skipif with True condition
    if condition.strip() in ['true', '1'] or 'skipif(true' in skipif['decorator'].lower():
        lazy_keywords = ['todo', 'fix later', 'not working', 'broken', 'skip for now']
        if any(kw in reason for kw in lazy_keywords):
            return (
                'warning',
                'lazy',
                f'偷懒的 skipif：永远跳过测试（condition=True）且理由模糊（"{skipif["reason"]}"）',
                '直接删除这个 skipif，修复测试或算子实现'
            )

    # WARNING: vague reason without issue number
    vague_keywords = ['not working', 'error', 'broken', 'fails']
    has_issue = re.search(r'#\d{4}', skipif['reason'])
    if any(kw in reason for kw in vague_keywords) and not has_issue:
        return (
            'warning',
            'vague_reason',
            f'模糊的 skipif 理由："{skipif["reason"]}" 缺少 issue 编号或详细说明',
            '添加 issue 编号（如 "Issue #1234: ..."）或详细描述失败原因'
        )

    # INFO: reasonable dependency checks
    reasonable_patterns = [
        'is none',  # library not installed
        '__version__',  # version requirement
        'not installed',
        'module' in condition and 'none' in condition,
    ]

    if any(p if isinstance(p, bool) else p in condition for p in reasonable_patterns):
        return (
            'info',
            'reasonable',
            f'依赖或版本检查：可能合理（{skipif["reason"]}）',
            '人工确认这是否是必要的前提条件'
        )

    # Default: WARNING - needs review
    return (
        'warning',
        'needs_review',
        f'新增 skipif：需要人工审查是否必要',
        '确认是否有正当理由跳过此测试'
    )


def analyze_file(patch: str, filepath: str, full_source: str) -> List[Dict[str, Any]]:
    """Return only skipif decorators on lines newly introduced by this PR."""
    new_lines = added_lines_from_patch(patch)
    all_skipifs = find_skipif_decorators(full_source, filepath)

    violations = []
    for skipif in all_skipifs:
        # Check if this skipif's line is in the added lines
        if skipif['line'] in new_lines:
            severity, category, message, suggestion = classify_skipif(skipif)
            violations.append({
                'file': skipif['file'],
                'line': skipif['line'],
                'test_function': skipif['test_function'],
                'decorator': skipif['decorator'],
                'condition': skipif['condition'],
                'reason': skipif['reason'],
                'severity': severity,
                'category': category,
                'message': message,
                'suggestion': suggestion,
            })

    return violations


# --- Main check ---

def check_pr(pr_ref: str, json_output: bool = False) -> Dict[str, Any]:
    repo, pr_number = parse_pr_ref(pr_ref)
    files = get_pr_files(repo, pr_number)
    head_sha = get_pr_head_sha(repo, pr_number)

    violations: List[Dict[str, Any]] = []

    for f in files:
        filepath = f['filename']
        patch = f.get('patch', '')

        # Only scan test files
        if not (filepath.startswith('tests/') and filepath.endswith('.py')):
            continue
        if not patch:
            continue

        content = get_file_content(repo, head_sha, filepath)
        if content is None:
            continue

        violations.extend(analyze_file(patch, filepath, content))

    # Sort by severity: critical > warning > info
    severity_order = {'critical': 0, 'warning': 1, 'info': 2}
    violations.sort(key=lambda v: (severity_order[v['severity']], v['file'], v['line']))

    result = {
        'check': 'skipif',
        'pr': pr_number,
        'repo': repo,
        'status': 'passed' if not violations else 'failed',
        'violations': violations,
        'summary': {
            'total': len(violations),
            'critical': sum(1 for v in violations if v['severity'] == 'critical'),
            'warning': sum(1 for v in violations if v['severity'] == 'warning'),
            'info': sum(1 for v in violations if v['severity'] == 'info'),
        }
    }

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    return result


def _print_human(result: Dict[str, Any]) -> None:
    pr = result['pr']
    violations = result['violations']
    summary = result['summary']

    if not violations:
        print(f"OK  PR #{pr}: no problematic skipif found")
        return

    print(f"FAIL  PR #{pr}: {summary['total']} skipif issue(s) found\n")
    print(f"  🔴 Critical: {summary['critical']}")
    print(f"  🟡 Warning:  {summary['warning']}")
    print(f"  🔵 Info:     {summary['info']}\n")

    # Group by severity
    by_severity = {}
    for v in violations:
        by_severity.setdefault(v['severity'], []).append(v)

    for severity in ['critical', 'warning', 'info']:
        if severity not in by_severity:
            continue

        icon = {'critical': '🔴', 'warning': '🟡', 'info': '🔵'}[severity]
        label = severity.upper()
        print(f"{icon} {label} ({len(by_severity[severity])} issue(s)):\n")

        for v in by_severity[severity]:
            print(f"  {v['file']}:{v['line']} (test: {v['test_function']})")
            print(f"    decorator : {v['decorator'][:80]}...")
            print(f"    condition : {v['condition']}")
            print(f"    reason    : {v['reason']}")
            print(f"    问题      : {v['message']}")
            print(f"    建议      : {v['suggestion']}")
            print()

    print(
        "Note: vendor-specific skipif 违反 FlagGems 跨芯片兼容目标。\n"
        "      应修复算子实现而不是跳过测试。"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Check FlagGems PR for problematic pytest.mark.skipif usage")
    parser.add_argument('pr', help='PR number or full URL')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()

    try:
        result = check_pr(args.pr, json_output=args.json)
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}\n{e.stderr}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)

    sys.exit(0 if result['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
