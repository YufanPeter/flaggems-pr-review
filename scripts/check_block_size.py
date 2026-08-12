#!/usr/bin/env python3.11
"""
Check for hardcoded BLOCK_SIZE in FlagGems PRs.

Problem: Writing BLOCK_SIZE = 1024 as a fixed constant in a launcher function
means Triton's JIT compiles only one kernel variant and cannot pick an optimal
size based on the actual workload.

Correct pattern:
    BLOCK_SIZE = min(1024, triton.next_power_of_2(N))
    BLOCK_SIZE = triton.next_power_of_2(math.ceil(math.sqrt(N)))

Detection rule:
    1. Inside a launcher function (not a @triton.jit kernel)
    2. BLOCK_SIZE = <integer literal> (e.g. 1024, 512, 256)
    3. That value is passed directly to the kernel as a constexpr param
    4. Without any dynamic adjustment via triton.next_power_of_2() / min()
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


# --- AST analysis ---

def is_triton_kernel(node: ast.FunctionDef) -> bool:
    """Return True if this function is decorated with @triton.jit."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Attribute) and dec.attr == 'jit':
            return True
        if isinstance(dec, ast.Name) and dec.id == 'jit':
            return True
    return False


def find_hardcoded_block_sizes(source: str, filepath: str) -> List[Dict[str, Any]]:
    """
    Find BLOCK_SIZE = <literal int> assignments in launcher functions and
    at module level.

    Allowed (dynamic, not reported):
      - triton.next_power_of_2(...)
      - min(N, ...)
      - any non-literal right-hand side
      - BLOCK_SIZE = 1  (edge-case handling for empty/tiny data)

    Not allowed (hardcoded, reported):
      - BLOCK_SIZE = 1024  (or any other literal > 1 in a launcher/module scope)
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    violations = []

    def check_assign(node: ast.Assign, in_kernel: bool,
                     func_name: str, is_module_level: bool) -> None:
        # Only check BLOCK_SIZE-named variables
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            var = target.id
            if 'BLOCK_SIZE' not in var.upper():
                continue

            # Skip declarations inside @triton.jit kernels (they're constexpr params,
            # not the kind of hardcoding we care about)
            if in_kernel:
                continue

            value = node.value
            # Only flag literal integer assignments
            if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
                continue

            literal_val = value.value

            # BLOCK_SIZE = 1 is a legitimate edge-case guard
            if literal_val == 1:
                continue

            lineno = node.lineno
            line_content = lines[lineno - 1].strip() if lineno <= len(lines) else ''

            location = 'module level' if is_module_level else f'launcher `{func_name}`'
            violations.append({
                'file': filepath,
                'line': lineno,
                'variable': var,
                'value': literal_val,
                'code': line_content,
                'location': location,
                'message': (
                    f"`{var} = {literal_val}` is hardcoded in {location}. "
                    f"Use a dynamic expression such as "
                    f"`min({literal_val}, triton.next_power_of_2(N))` so Triton "
                    f"can JIT-compile the optimal kernel size for each workload."
                ),
            })

    # Check module-level assignments
    for stmt in ast.iter_child_nodes(tree):
        if isinstance(stmt, ast.Assign):
            check_assign(stmt, in_kernel=False, func_name='', is_module_level=True)

    # Check inside each function
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        in_kernel = is_triton_kernel(node)
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                check_assign(stmt, in_kernel=in_kernel,
                             func_name=node.name, is_module_level=False)

    return violations


def added_lines_from_patch(patch: str) -> set:
    """Return the set of new line numbers introduced by this patch hunk."""
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


def analyze_file(patch: str, filepath: str, full_source: str) -> List[Dict[str, Any]]:
    """Return only violations on lines newly introduced by this PR."""
    new_lines = added_lines_from_patch(patch)
    all_violations = find_hardcoded_block_sizes(full_source, filepath)
    return [v for v in all_violations if v['line'] in new_lines]


# --- Main check ---

def check_pr(pr_ref: str, json_output: bool = False) -> Dict[str, Any]:
    repo, pr_number = parse_pr_ref(pr_ref)
    files = get_pr_files(repo, pr_number)
    head_sha = get_pr_head_sha(repo, pr_number)

    violations: List[Dict[str, Any]] = []

    for f in files:
        filepath = f['filename']
        patch = f.get('patch', '')

        # Only scan operator and fused kernel files
        if not (filepath.startswith('src/flag_gems/ops/')
                or filepath.startswith('src/flag_gems/fused/')):
            continue
        if not filepath.endswith('.py') or not patch:
            continue

        content = get_file_content(repo, head_sha, filepath)
        if content is None:
            continue

        violations.extend(analyze_file(patch, filepath, content))

    result = {
        'check': 'block_size_hardcoded',
        'pr': pr_number,
        'repo': repo,
        'status': 'passed' if not violations else 'failed',
        'violations': violations,
    }

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    return result


def _print_human(result: Dict[str, Any]) -> None:
    pr = result['pr']
    violations = result['violations']

    if not violations:
        print(f"OK  PR #{pr}: no hardcoded BLOCK_SIZE found")
        return

    print(f"FAIL  PR #{pr}: {len(violations)} hardcoded BLOCK_SIZE issue(s)\n")
    for v in violations:
        print(f"  {v['file']}:{v['line']}")
        print(f"    code : {v['code']}")
        print(f"    issue: {v['message']}")
        print()

    print(
        "Note: a hardcoded BLOCK_SIZE forces Triton to compile a single fixed\n"
        "      kernel variant and prevents workload-adaptive optimisation.\n"
        "      Replace with: BLOCK_SIZE = min(1024, triton.next_power_of_2(N))"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Check FlagGems PR for hardcoded BLOCK_SIZE")
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
