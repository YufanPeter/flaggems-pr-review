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


def _gh_created_at(cmd: List[str]) -> str:
    """Run a gh command that returns {'createdAt': ...}; return '' on any failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout).get('createdAt', '') or ''
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return ''


def check_timeline(repo: str, pr_number: str, issue_ref: str) -> Dict[str, Any]:
    """Compare the referenced issue's creation time against the PR's.

    This is a mechanical fact, not a judgment: if the cited issue predates the
    PR, the issue cannot describe *this* PR's newly-added implementation — the
    reason is causally inverted and the skip does not hold. (See PR #5290: a
    June issue was cited to skip an August implementation.)
    """
    pr_created = _gh_created_at(
        ['gh', 'pr', 'view', pr_number, '--repo', repo, '--json', 'createdAt'])
    issue_created = _gh_created_at(
        ['gh', 'issue', 'view', issue_ref, '--repo', repo, '--json', 'createdAt'])

    out = {
        'issue_ref': issue_ref,
        'issue_created_at': issue_created,
        'pr_created_at': pr_created,
        'issue_predates_pr': None,
        'verdict': 'unknown',
        'note': '',
    }
    if not pr_created or not issue_created:
        out['note'] = '无法获取时间戳（网络失败或字段缺失），需人工核对时间线。'
        return out

    predates = issue_created < pr_created
    out['issue_predates_pr'] = predates
    if predates:
        out['verdict'] = 'reason_invalid'
        out['note'] = (
            f'因果倒置：issue #{issue_ref} 创建于 {issue_created}，早于本 PR 的 {pr_created}。'
            f'早于 PR 的 issue 无法描述本 PR 新增的实现，reason 不成立，skip 应删除。'
        )
    else:
        out['verdict'] = 'timeline_ok'
        out['note'] = (
            f'时间线合理：issue #{issue_ref}（{issue_created}）晚于/接近本 PR（{pr_created}），'
            f'时间上可能覆盖本 PR，但仍需核对算子名与 issue 内容。'
        )
    return out


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


def _reason_verification(skipif: Dict[str, Any]) -> Dict[str, Any]:
    """Build verification metadata for a skipif that DOES have a reason.

    The reason itself is not proof — it must be verified. This extracts the
    issue reference (if any) and the operator/test name derived from the file,
    so the agent can cross-check whether the reason actually holds (e.g. the
    referenced issue may not even list this operator — see PR #5399 where the
    reason cited Issue #5254 but that issue lists `_w`, not the `_t` operator).
    """
    reason = skipif['reason']
    issue_match = re.search(r'#(\d{3,})', reason)
    issue_ref = issue_match.group(1) if issue_match else None

    # Derive the operator/test name from the test filename:
    # tests/test_special_chebyshev_polynomial_t.py -> special_chebyshev_polynomial_t
    fname = skipif['file'].rsplit('/', 1)[-1]
    op_name = fname[len('test_'):-len('.py')] if fname.startswith('test_') and fname.endswith('.py') else fname

    if issue_ref:
        hint = (
            f'reason 引用了 issue #{issue_ref}，需核对该 issue 是否真的把算子 '
            f'"{op_name}" 列为不支持。若 issue 未提及该算子（名称对不上），则 reason 不成立，skip 需删除。'
        )
        verify_cmd = f'gh issue view {issue_ref} --repo flagos-ai/FlagGems'
        # 已知的两类错误模式，逐条核对（见 skill 中的校准案例 PR #5399 / #5290）
        checklist = [
            f'算子名匹配：issue 是否真的把 "{op_name}" 列为不支持？'
            f'注意近似名（如 _t vs _w）不算匹配 —— 名称对不上则 reason 不成立。',
            f'时间线：issue #{issue_ref} 的创建时间是否早于本 PR？'
            f'若 issue 更早，它描述的是旧实现状态，无法覆盖本 PR 的新实现 —— 因果倒置，reason 不成立。',
            f'issue 质量与状态：issue 描述是否清晰、是否被维护者质疑、当前 state 是否仍 OPEN？'
            f'描述含糊或只是测试基准问题（如 "failed without --ref cpu"）不足以支撑跳过整个测试。',
        ]
    else:
        hint = (
            f'reason 未引用任何 issue 编号，无法追踪。需人工确认 "{op_name}" 是否真的在该芯片上无法支持，'
            f'否则 skip 需删除。'
        )
        verify_cmd = None
        checklist = [
            f'reason 未引用可追踪的 issue，无法验证 "{op_name}" 是否真的不支持 —— 默认视为需删除，'
            f'除非能补充可验证的依据。',
        ]

    return {
        'has_reason': True,
        'needs_verification': True,
        'issue_ref': issue_ref,
        'operator': op_name,
        'verification_hint': hint,
        'verification_cmd': verify_cmd,
        'verification_checklist': checklist,
    }


def classify_skipif(skipif: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify a skipif decorator.

    Returns a dict with:
    - severity: 'critical' | 'warning' | 'info'
    - category: 'no_reason' | 'vendor_specific' | 'cuda_specific' | 'lazy' | ...
    - message: description of the issue
    - suggestion: how to fix it
    - has_reason / needs_verification / issue_ref / operator / verification_* :
      present when the skipif carries a reason that must be verified

    Classification principle:
      1. No reason at all  -> definite error, must delete (no verification needed).
      2. Has a reason      -> Mark it and VERIFY the reason (it is a claim, not proof).
    """
    condition = skipif['condition'].lower()
    reason_raw = skipif['reason']
    reason = reason_raw.lower()
    has_reason = bool(reason_raw.strip())

    def result(severity, category, message, suggestion):
        out = {
            'severity': severity,
            'category': category,
            'message': message,
            'suggestion': suggestion,
            'has_reason': has_reason,
            'needs_verification': False,
        }
        # Any skipif carrying a reason gets verification metadata attached,
        # because a reason is a claim to be checked, not an accepted excuse.
        if has_reason:
            out.update(_reason_verification(skipif))
        return out

    # CRITICAL: skipif with NO reason at all -> definite error, must delete
    if not has_reason:
        return result(
            'critical',
            'no_reason',
            'skipif 没有任何 reason：无法判断跳过依据，属于明确错误',
            '删除 skipif；若测试确需跳过，必须补充可验证的 reason（引用 issue 说明原因）'
        )

    # CRITICAL: vendor-specific skipif (reason present -> must be verified)
    if 'vendor_name' in condition:
        return result(
            'critical',
            'vendor_specific',
            'vendor-specific skipif 违反跨芯片兼容原则：不应该因芯片类型跳过测试（reason 需验证）',
            '核对 reason 是否成立；若不成立则删除 skipif，如测试在某芯片上失败应修复算子实现'
        )

    # CRITICAL: CUDA-specific skipif
    if 'cuda' in condition or 'is_cuda' in skipif['condition']:
        return result(
            'critical',
            'cuda_specific',
            'CUDA-specific skipif 违反跨芯片兼容原则：硬编码 CUDA 依赖（reason 需验证）',
            '核对 reason 是否成立；移除 CUDA 检查，使用 flag_gems.device 以支持多种芯片'
        )

    # WARNING: lazy skipif with True condition
    if condition.strip().lower() in ['true', '1'] or 'skipif(true' in skipif['decorator'].lower():
        lazy_keywords = ['todo', 'fix later', 'not working', 'broken', 'skip for now']
        if any(kw in reason for kw in lazy_keywords):
            return result(
                'warning',
                'lazy',
                f'偷懒的 skipif：永远跳过测试（condition=True）且理由模糊（"{reason_raw}"）',
                '直接删除这个 skipif，修复测试或算子实现'
            )

    # WARNING: vague reason without issue number
    vague_keywords = ['not working', 'error', 'broken', 'fails']
    has_issue = re.search(r'#\d{3,}', reason_raw)
    if any(kw in reason for kw in vague_keywords) and not has_issue:
        return result(
            'warning',
            'vague_reason',
            f'模糊的 skipif 理由："{reason_raw}" 缺少 issue 编号或详细说明',
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
        return result(
            'info',
            'reasonable',
            f'依赖或版本检查：可能合理（{reason_raw}）',
            '人工确认这是否是必要的前提条件'
        )

    # Default: WARNING - needs review
    return result(
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
            classification = classify_skipif(skipif)
            violation = {
                'file': skipif['file'],
                'line': skipif['line'],
                'test_function': skipif['test_function'],
                'decorator': skipif['decorator'],
                'condition': skipif['condition'],
                'reason': skipif['reason'],
            }
            violation.update(classification)
            violations.append(violation)

    return violations


# --- Verdict routing ---

def resolve_verdict(violation: Dict[str, Any]) -> Dict[str, Any]:
    """Route a violation to a verdict.

    This flag only controls whether the agent must additionally READ the issue
    to verify the reason. It does NOT authorize a silent fix: every skipif
    deletion, regardless of verdict, must still be reported to the user and
    confirmed before it is applied (detect -> propose -> approve -> fix).

    Two shortcuts skip the agent's issue-reading step (mechanical facts):
      - no_reason            -> confirmed_error (nothing to verify)
      - timeline reason_invalid -> confirmed_error (issue predates PR: causally
        impossible for the issue to describe this PR's new implementation)

    Everything else with a reason still needs an agent to read the issue and
    check operator-name match and issue quality -> needs_agent_verification.
    """
    # skipif with no reason at all: already a definite error.
    if not violation.get('has_reason'):
        return {
            'auto_verdict': 'confirmed_error',
            'needs_agent_verification': False,
            'verdict_reason': 'skipif 无 reason，属明确错误，直接删除。',
        }

    timeline = violation.get('timeline') or {}
    if timeline.get('verdict') == 'reason_invalid':
        return {
            'auto_verdict': 'confirmed_error',
            'needs_agent_verification': False,
            'verdict_reason': (
                '时间线倒置：引用的 issue 早于本 PR，不可能描述本 PR 新增的实现，'
                'reason 无效，直接删除（无需人工读 issue 内容）。'
            ),
        }

    # Timeline OK or unknown, or no issue reference at all: an agent must verify.
    return {
        'auto_verdict': 'pending',
        'needs_agent_verification': True,
        'verdict_reason': (
            '时间线未证伪，需 agent 读 issue 核对：算子名是否匹配、issue 内容/状态是否成立。'
        ),
    }


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

    # Resolve the timeline check for every violation that cites an issue,
    # then route each violation to a verdict. Cache by issue_ref so we don't
    # re-query the same issue for sibling skipifs.
    timeline_cache: Dict[str, Dict[str, Any]] = {}
    for v in violations:
        issue_ref = v.get('issue_ref')
        if issue_ref:
            if issue_ref not in timeline_cache:
                timeline_cache[issue_ref] = check_timeline(repo, pr_number, issue_ref)
            v['timeline'] = timeline_cache[issue_ref]
        v.update(resolve_verdict(v))

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
            'confirmed_error': sum(1 for v in violations if v.get('auto_verdict') == 'confirmed_error'),
            'needs_agent_verification': sum(1 for v in violations if v.get('needs_agent_verification')),
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
