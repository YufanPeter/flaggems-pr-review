#!/usr/bin/env python3.11
"""
Check for hardcoded BLOCK_SIZE in FlagGems PRs.

Problem: Writing hardcoded integers in tl.arange() inside @triton.jit kernels
bypasses the tl.constexpr parameterization mechanism, forcing Triton to compile
only one kernel variant.

Correct pattern (kernel declares BLOCK_SIZE: tl.constexpr and uses it):
    @triton.jit
    def my_kernel(..., BLOCK_SIZE: tl.constexpr):
        offsets = tl.arange(0, BLOCK_SIZE)  # ✅ uses the constexpr param

Wrong pattern (kernel declares constexpr but ignores it):
    @triton.jit
    def my_kernel(..., BLOCK_SIZE: tl.constexpr):
        offsets = tl.arange(0, 128)  # ❌ hardcoded, ignores BLOCK_SIZE

Detection rule:
    1. Inside @triton.jit kernel functions
    2. tl.arange(start, stop) where stop is an integer literal > 1
    3. The kernel has a tl.constexpr parameter with a name containing BLOCK/SIZE/TILE
    4. That suggests the literal should use the constexpr parameter instead

Note: Hardcoded values in launcher functions (host code) are allowed —
they decide which specialized kernel variant to invoke.
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


def has_constexpr_block_param(func_def: ast.FunctionDef) -> List[str]:
    """
    Return list of parameter names that are tl.constexpr and contain BLOCK/SIZE/TILE.

    Example:
        def kernel(..., BLOCK_SIZE_M: tl.constexpr, BLOCK_SIZE_N: tl.constexpr):
    Returns: ['BLOCK_SIZE_M', 'BLOCK_SIZE_N']
    """
    constexpr_params = []
    for arg in func_def.args.args:
        if arg.annotation is None:
            continue
        # Check if annotation is tl.constexpr
        is_constexpr = False
        ann = arg.annotation
        if isinstance(ann, ast.Attribute) and ann.attr == 'constexpr':
            is_constexpr = True
        elif isinstance(ann, ast.Name) and ann.id == 'constexpr':
            is_constexpr = True

        if is_constexpr:
            param_name = arg.arg
            # Only track block/size/tile related params
            if any(kw in param_name.upper() for kw in ['BLOCK', 'SIZE', 'TILE']):
                constexpr_params.append(param_name)

    return constexpr_params


def find_hardcoded_block_sizes(source: str, filepath: str) -> List[Dict[str, Any]]:
    """
    Find hardcoded integer literals in tl.arange() calls inside @triton.jit kernels
    that should use tl.constexpr parameters instead.

    Checks:
      - tl.arange(start, LITERAL) where LITERAL is int > 1
      - The kernel has BLOCK_SIZE*/TILE_* constexpr parameters
      - Suggests the literal should use the constexpr param

    Does NOT check:
      - Launcher functions (host code) — hardcoded values are OK there
      - Module-level constants — those decide which kernel variant to call
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    lines = source.splitlines()
    violations = []

    # Find all @triton.jit kernels
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not is_triton_kernel(node):
            continue

        # Check if kernel has constexpr block params
        constexpr_params = has_constexpr_block_param(node)
        if not constexpr_params:
            # No constexpr params declared, nothing to check
            continue

        # Scan kernel body for tl.arange(...) calls with literal stop
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue

            # Match tl.arange or triton.language.arange
            func = child.func
            is_arange = False
            if isinstance(func, ast.Attribute) and func.attr == 'arange':
                is_arange = True
            elif isinstance(func, ast.Name) and func.id == 'arange':
                is_arange = True

            if not is_arange or len(child.args) < 2:
                continue

            # Check if stop (2nd arg) is a literal int > 1
            stop_arg = child.args[1]
            if not isinstance(stop_arg, ast.Constant):
                continue
            if not isinstance(stop_arg.value, int):
                continue

            literal_val = stop_arg.value
            if literal_val <= 1:
                # 0 or 1 are neutral, not block size related
                continue

            lineno = child.lineno
            line_content = lines[lineno - 1].strip() if lineno <= len(lines) else ''

            violations.append({
                'file': filepath,
                'line': lineno,
                'literal': literal_val,
                'code': line_content,
                'kernel': node.name,
                'constexpr_params': constexpr_params,
                'message': (
                    f"Hardcoded literal {literal_val} in tl.arange() inside kernel `{node.name}`. "
                    f"The kernel declares constexpr params {constexpr_params} but does not use them. "
                    f"Replace the literal with the appropriate constexpr parameter so Triton can "
                    f"JIT-compile different tile sizes."
                ),
            })

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
        print(f"OK  PR #{pr}: no hardcoded literals in @triton.jit kernels")
        return

    print(f"FAIL  PR #{pr}: {len(violations)} hardcoded literal(s) in @triton.jit kernels\n")
    for v in violations:
        print(f"  {v['file']}:{v['line']} (kernel `{v['kernel']}`)")
        print(f"    code    : {v['code']}")
        print(f"    literal : {v['literal']}")
        print(f"    constexpr params: {', '.join(v['constexpr_params'])}")
        print(f"    issue   : {v['message']}")
        print()

    print(
        "Note: Hardcoded literals in tl.arange() inside @triton.jit kernels prevent\n"
        "      Triton from compiling different tile-size variants. Use the declared\n"
        "      tl.constexpr parameters instead: tl.arange(0, BLOCK_SIZE)"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Check FlagGems PR for hardcoded literals in @triton.jit kernels")
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
