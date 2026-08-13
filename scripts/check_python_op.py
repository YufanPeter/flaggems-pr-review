#!/usr/bin/env python3.11
"""
Check python-op CI job status for FlagGems PRs.

The python-op job runs pytest on changed test files. This script:
1. Fetches the PR's CI runs via GitHub API
2. Finds the python-op job
3. If failed, downloads logs and extracts full failure context
4. Agent analyzes logs and proposes fixes (no pre-categorization)
"""

import argparse
import json
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_REPO = "flagos-ai/FlagGems"


# --- GitHub API helpers ---

def parse_pr_ref(pr_url_or_number: str) -> Tuple[str, str]:
    if pr_url_or_number.isdigit():
        return DEFAULT_REPO, pr_url_or_number
    match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_url_or_number)
    if not match:
        raise ValueError(f"Cannot parse PR ref: {pr_url_or_number}")
    owner, repo_name, pr_number = match.groups()
    return f"{owner}/{repo_name}", pr_number


def get_pr_head_sha(repo: str, pr_number: str) -> str:
    result = subprocess.run(
        ['gh', 'pr', 'view', pr_number, '--repo', repo, '--json', 'headRefOid'],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)['headRefOid']


def get_python_op_check_via_pr(repo: str, pr_number: str) -> Optional[Dict[str, Any]]:
    """
    Faster method: use PR's statusCheckRollup to find python-op directly.
    """
    result = subprocess.run(
        ['gh', 'pr', 'view', pr_number, '--repo', repo, '--json',
         'statusCheckRollup,headRefOid'],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)

    # Find python-op check
    for check in data.get('statusCheckRollup', []):
        if check.get('name') == 'python-op':
            return {
                'name': check['name'],
                'status': check['status'],
                'conclusion': check.get('conclusion'),
                'html_url': check.get('detailsUrl'),
                'id': None,  # We'll extract this from detailsUrl if needed
            }
    return None


def get_run_jobs(repo: str, run_id: int) -> List[Dict[str, Any]]:
    """Get all jobs for a workflow run."""
    result = subprocess.run(
        ['gh', 'api', f'repos/{repo}/actions/runs/{run_id}/jobs',
         '--jq', '.jobs[]'],
        capture_output=True, text=True, check=True,
    )

    jobs = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            try:
                jobs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return jobs


def get_job_logs(repo: str, job_id: int) -> str:
    """Download logs for a specific job."""
    result = subprocess.run(
        ['gh', 'api', f'repos/{repo}/actions/jobs/{job_id}/logs',
         '--allow-escape-sequences'],
        capture_output=True, text=True, check=True,
    )
    # Strip ANSI escape sequences
    clean = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', result.stdout)
    # Strip GitHub Actions timestamps
    clean = re.sub(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ', '', clean, flags=re.MULTILINE)
    return clean


# --- Log parsing ---

def parse_pytest_failures(logs: str) -> List[Dict[str, Any]]:
    """
    Parse pytest output to extract failure information.

    Handles two kinds of failures:

    1. Normal test failures (short test summary):
        FAILED tests/test_add.py::test_add - AssertionError: ...

    2. Collection errors / ImportErrors before tests run:
        ImportError while loading conftest '...conftest.py'.
        ...
        E   NameError: name 'libtuner' is not defined
    """
    failures = []
    seen = set()

    # ── Pattern 1: FAILED lines in short test summary ──────────────────────
    failed_pattern = r'FAILED\s+([^\s:]+)::([^\s]+)\s+-\s+(.+)'
    for match in re.finditer(failed_pattern, logs):
        file_path = match.group(1)
        test_name = match.group(2)
        error_info = match.group(3).strip()

        key = (file_path, test_name)
        if key in seen:
            continue
        seen.add(key)

        error_type_match = re.match(r'([A-Za-z]+Error|Failed)', error_info)
        error_type = error_type_match.group(1) if error_type_match else 'Unknown'

        context = extract_failure_context(logs, file_path, test_name)

        failures.append({
            'file': file_path,
            'test': test_name,
            'error_type': error_type,
            'error_message': error_info,
            'context': context,
        })

    # ── Pattern 2: ImportError / collection error before tests run ──────────
    # Detect "ImportError while loading conftest ..." or "ERROR collecting ..."
    import_err_pattern = r'(ImportError while loading conftest|ERROR collecting)\s+[\'"]?([^\'">\s]+)[\'"]?'
    for match in re.finditer(import_err_pattern, logs):
        trigger = match.group(1)
        file_path = match.group(2)

        # Strip leading path prefix to get relative path
        file_path = re.sub(r'^.*/(?=tests/|src/)', '', file_path)

        # Find the actual error line (starts with "E   ")
        # Look forward from this match position
        remaining = logs[match.start():]
        error_line = ''
        error_type = 'ImportError'
        for line in remaining.splitlines():
            e_match = re.match(r'^E\s+([A-Za-z]+Error|NameError|AttributeError|SyntaxError)[:\s](.+)', line)
            if e_match:
                error_type = e_match.group(1)
                error_line = e_match.group(2).strip()
                break

        # Find the import chain (traceback lines before E line)
        chain_lines = []
        in_tb = False
        for line in remaining.splitlines()[:30]:
            if re.match(r'\s+\S.*:\s*in\s+\S', line) or re.match(r'\s+from\s+|import\s+', line):
                in_tb = True
                chain_lines.append(line.strip())
            elif line.startswith('E '):
                break

        context = '\n'.join(chain_lines[:5]) if chain_lines else None

        key = (file_path, 'collection')
        if key not in seen:
            seen.add(key)
            failures.append({
                'file': file_path,
                'test': '<collection>',
                'error_type': error_type,
                'error_message': f'{error_type}: {error_line}' if error_line else f'{trigger}',
                'context': context,
            })

    return failures


def extract_failure_context(logs: str, file_path: str, test_name: str) -> Optional[str]:
    """
    Extract more detailed context for a failure from the full logs.

    Looks for the test function output section in pytest logs.
    """
    # Find the section for this test
    pattern = rf'_{re.escape(file_path)}::{re.escape(test_name)}_+\s+(.*?)\s+(?:_+|FAILED)'
    match = re.search(pattern, logs, re.DOTALL)

    if match:
        context = match.group(1).strip()
        # Limit context to first 500 characters
        if len(context) > 500:
            context = context[:500] + '...'
        return context

    return None


def extract_detailed_log_context(logs: str, failure: Dict[str, Any]) -> str:
    """
    Extract the full error context around this failure for agent analysis.

    Returns the complete traceback and surrounding output so the agent can
    analyze root cause without needing pre-categorization.
    """
    file_path = failure['file']
    test_name = failure['test']

    # For collection errors, return the import chain we already extracted
    if test_name == '<collection>':
        context_lines = []
        if failure.get('context'):
            context_lines.append("Import traceback:")
            context_lines.append(failure['context'])
        context_lines.append(f"\nError: {failure['error_message']}")
        return '\n'.join(context_lines)

    # For normal test failures, find the full output section
    # pytest formats test output as:
    # _____ test_file.py::test_name _____
    # ... output ...
    # ... traceback ...
    # FAILED

    pattern = rf'_{re.escape(file_path)}::{re.escape(test_name)}_+\s+(.*?)\s+(?:FAILED|PASSED|ERROR)'
    match = re.search(pattern, logs, re.DOTALL)

    if match:
        full_output = match.group(1).strip()
        # Limit to last 100 lines to avoid overwhelming the agent
        lines = full_output.splitlines()
        if len(lines) > 100:
            lines = ['... (output truncated) ...'] + lines[-100:]
        return '\n'.join(lines)

    # Fallback: return what we have
    parts = [f"Error: {failure['error_message']}"]
    if failure.get('context'):
        parts.append(f"Context:\n{failure['context']}")
    return '\n'.join(parts)


# --- Main check ---

def check_pr(pr_ref: str, json_output: bool = False) -> Dict[str, Any]:
    repo, pr_number = parse_pr_ref(pr_ref)

    # Fast path: use PR's statusCheckRollup
    python_op_check = get_python_op_check_via_pr(repo, pr_number)

    if not python_op_check:
        result = {
            'check': 'python_op',
            'pr': pr_number,
            'repo': repo,
            'status': 'no_python_op_job',
            'message': 'python-op job not found in CI runs',
        }
        if json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"SKIP  PR #{pr_number}: python-op job not found")
        return result

    # Check job status
    job_status = python_op_check['conclusion']
    job_url = python_op_check['html_url']

    if job_status == 'SUCCESS' or job_status == 'success':
        result = {
            'check': 'python_op',
            'pr': pr_number,
            'repo': repo,
            'status': 'passed',
            'job_url': job_url,
        }
        if json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"OK  PR #{pr_number}: python-op tests passed")
        return result

    if job_status in ('SKIPPED', 'skipped'):
        result = {
            'check': 'python_op',
            'pr': pr_number,
            'repo': repo,
            'status': 'skipped',
            'message': 'python-op job was skipped (no tests label or no test files changed)',
            'job_url': job_url,
        }
        if json_output:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"SKIP  PR #{pr_number}: python-op job was skipped")
        return result

    # Job failed — extract job ID from detailsUrl and download logs
    # detailsUrl format: https://github.com/.../actions/runs/<run_id>/job/<job_id>
    job_id = None
    if job_url:
        m = re.search(r'/job[s]?/(\d+)$', job_url)
        if m:
            job_id = int(m.group(1))

    failures = []
    logs_unavailable = False
    raw_logs = ''
    if job_id:
        try:
            raw_logs = get_job_logs(repo, job_id)
            # Azure Blob 404 or empty response means logs expired
            if 'BlobNotFound' in raw_logs or not raw_logs.strip():
                logs_unavailable = True
            else:
                failures = parse_pytest_failures(raw_logs)
                # Extract detailed context for each failure
                for failure in failures:
                    failure['log_context'] = extract_detailed_log_context(raw_logs, failure)
        except subprocess.CalledProcessError:
            logs_unavailable = True

    result = {
        'check': 'python_op',
        'pr': pr_number,
        'repo': repo,
        'status': 'failed',
        'job_url': job_url,
        'job_conclusion': job_status,
        'logs_unavailable': logs_unavailable,
        'failures': failures,
        'summary': {
            'total': len(failures),
        },
    }

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    return result


def _print_human(result: Dict[str, Any]) -> None:
    pr = result['pr']
    failures = result['failures']

    print(f"FAIL  PR #{pr}: python-op tests failed\n")
    print(f"Job URL: {result['job_url']}\n")

    if result.get('logs_unavailable'):
        print("⚠️  CI 日志已过期，无法获取具体失败原因")
        print(f"   请直接查看 Job URL 了解详情")
        return

    if not failures:
        print("⚠️  Job 失败但未找到具体的测试失败记录")
        print("   可能是 checkout 失败、网络问题或其他 infra 故障")
        print(f"   请直接查看 Job URL 了解详情")
        return

    print(f"共 {len(failures)} 个失败：\n")
    for i, failure in enumerate(failures, 1):
        print(f"{i}. {failure['file']}::{failure['test']}")
        print(f"   错误类型: {failure['error_type']}")
        print(f"   错误信息: {failure['error_message']}")
        if failure.get('log_context'):
            # Truncate context for terminal display
            context_lines = failure['log_context'].splitlines()
            if len(context_lines) > 20:
                preview = '\n'.join(context_lines[:20])
                print(f"   日志片段:\n{preview}\n   ... (完整日志见 JSON 输出)")
            else:
                print(f"   日志片段:\n{failure['log_context']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Check python-op CI job for FlagGems PRs")
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

    # Exit code: 0 = passed/no job, 1 = failed, 2 = error
    if result['status'] == 'failed':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
