#!/usr/bin/env python3.11
"""
自动修复 FlagGems PR 的 code-style 失败 - 两阶段模式。

遵循统一原则: detect → propose → approve → fix → verify

Phase 1 (--dry-run, 默认):
  1. clone PR 到临时目录
  2. 机械修复（black/isort/eof）→ 算 diff（不 commit）
  3. Agent 修复（flake8/mypy）→ 算 diff（不 commit）
  4. 验证所有检查是否通过
  5. 输出 JSON: {status, diffs, risk_levels, state_file}

Phase 2 (--apply <state_file>):
  1. 读取 phase1 的状态文件
  2. 重新应用修复（从 state_file 的 clone_dir）
  3. commit 改动
  4. 输出 push 指令

退出码:
  0 = 成功（clean 或 fixable）
  1 = 需要人工（无法自动修复）
  2 = 错误（执行失败）
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


DEFAULT_REPO = "flagos-ai/FlagGems"
MAX_RETRIES_PER_FILE = 3


def parse_pr_ref(pr_url_or_number: str) -> Tuple[str, str]:
    """解析 PR 引用，返回 (repo, pr_number)。"""
    if pr_url_or_number.isdigit():
        return DEFAULT_REPO, pr_url_or_number

    match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_url_or_number)
    if not match:
        raise ValueError(f"无法解析 PR URL: {pr_url_or_number}")
    owner, repo_name, pr_number = match.groups()
    return f"{owner}/{repo_name}", pr_number


def get_pr_head(repo: str, pr_number: str) -> Dict[str, Any]:
    """获取 PR head 的精确信息。"""
    result = subprocess.run(
        ['gh', 'pr', 'view', pr_number, '--repo', repo,
         '--json', 'headRefName,headRefOid,headRepositoryOwner,headRepository,files'],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    owner = (data.get('headRepositoryOwner') or {}).get('login', '')
    repo_name = (data.get('headRepository') or {}).get('name', '')
    changed_files = [
        entry['path'] for entry in (data.get('files') or [])
        if isinstance(entry, dict) and entry.get('path')
    ]
    return {
        'branch': data['headRefName'],
        'sha': data['headRefOid'],
        'fork': f"{owner}/{repo_name}" if owner and repo_name else repo,
        'changed_files': changed_files,
    }


def check_push_permission(fork_repo: str) -> bool:
    """检测用户是否有 push 权限。"""
    try:
        result = subprocess.run(
            ['gh', 'api', f'repos/{fork_repo}', '--jq', '.permissions.push'],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return result.stdout.strip() == 'true'
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def clone_pr_head(repo: str, pr_number: str, head: Dict[str, str], workdir: Path) -> Tuple[Path, str]:
    """Clone PR head 到 workdir，返回 (clone_dir, mode)。"""
    clone_dir = workdir / "repo"
    can_push = check_push_permission(head['fork'])

    if can_push:
        try:
            subprocess.run(
                ['gh', 'repo', 'clone', head['fork'], str(clone_dir), '--',
                 '--branch', head['branch'], '--depth', '1'],
                capture_output=True, text=True, check=True,
            )
            return clone_dir, 'writable'
        except subprocess.CalledProcessError:
            pass

    # Fallback: fetch PR ref from main repo
    subprocess.run(
        ['git', 'clone', '--depth', '1', f'https://github.com/{repo}.git', str(clone_dir)],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ['git', '-C', str(clone_dir), 'fetch', 'origin', f'pull/{pr_number}/head'],
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ['git', '-C', str(clone_dir), 'checkout', 'FETCH_HEAD'],
        capture_output=True, text=True, check=True,
    )

    # Verify SHA
    actual = subprocess.run(
        ['git', '-C', str(clone_dir), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if actual != head['sha']:
        raise RuntimeError(f"SHA mismatch: expected {head['sha']}, got {actual}")

    return clone_dir, 'readonly'


def run_pre_commit(clone_dir: Path, files: List[str]) -> Dict[str, Any]:
    """运行 pre-commit，返回结果。"""
    if not files:
        return {'exit_code': 0, 'hooks': {}, 'output': ''}
    result = subprocess.run(
        [sys.executable, '-m', 'pre_commit', 'run',
         '--files', *files, '--color', 'never'],
        cwd=str(clone_dir), capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    hooks = _parse_hook_results(output)
    return {
        'exit_code': result.returncode,
        'hooks': hooks,
        'output': output,
    }


def _parse_hook_results(output: str) -> Dict[str, str]:
    """解析 pre-commit 输出。"""
    hooks: Dict[str, str] = {}
    for line in output.splitlines():
        m = re.match(r'^(.+?)\.{3,}(Passed|Failed|Skipped)', line)
        if m:
            hooks[m.group(1).strip()] = m.group(2)
    return hooks


def get_diff(clone_dir: Path) -> str:
    """获取当前 working tree 的 diff。"""
    result = subprocess.run(
        ['git', '-C', str(clone_dir), 'diff'],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def get_changed_files(clone_dir: Path) -> List[str]:
    """获取被改动的文件列表。"""
    result = subprocess.run(
        ['git', '-C', str(clone_dir), 'diff', '--name-only'],
        capture_output=True, text=True, check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def parse_linting_errors(output: str, clone_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """解析 flake8/mypy 错误。"""
    errors_by_file: Dict[str, List[Dict[str, Any]]] = {}
    pattern = r'^(.+?):(\d+):(?:(\d+):)?\s*(?:error:|warning:)?\s*([A-Z]\d+)?\s*(.+)$'

    for line in output.splitlines():
        m = re.match(pattern, line.strip())
        if m:
            file_path = m.group(1)
            line_no = int(m.group(2))
            col = int(m.group(3)) if m.group(3) else 0
            code = m.group(4) or 'unknown'
            msg = m.group(5).strip()

            try:
                abs_path = (clone_dir / file_path).resolve()
                rel_path = str(abs_path.relative_to(clone_dir.resolve()))
            except (ValueError, OSError):
                rel_path = file_path

            if rel_path not in errors_by_file:
                errors_by_file[rel_path] = []
            errors_by_file[rel_path].append({
                'line': line_no,
                'col': col,
                'code': code,
                'msg': msg,
            })

    return errors_by_file


def fix_file_with_agent(clone_dir: Path, file_path: str, errors: List[Dict[str, Any]]) -> bool:
    """使用 agent 修复文件。"""
    abs_path = clone_dir / file_path
    if not abs_path.is_file():
        return False

    content = abs_path.read_text()
    error_summary = "\n".join([
        f"Line {e['line']}, col {e['col']}: [{e['code']}] {e['msg']}"
        for e in errors
    ])

    prompt = f"""Fix the following linting errors in this Python file:

File: {file_path}

Errors:
{error_summary}

Current file content:
```python
{content}
```

Fix all the errors listed above. Return ONLY the corrected file content, no explanations.
Common fixes:
- Remove unused imports/variables
- Add missing type hints for mypy
- Fix line length (break long lines)
- Add missing blank lines
- Fix undefined names

Output the complete corrected file."""

    try:
        result = subprocess.run(
            ['claude', '--model', 'claude-sonnet-4-20250514'],
            input=prompt, capture_output=True, text=True, check=True,
        )
        fixed_content = result.stdout.strip()

        # Extract code block
        if '```python' in fixed_content:
            match = re.search(r'```python\n(.*?)```', fixed_content, re.DOTALL)
            if match:
                fixed_content = match.group(1)
        elif '```' in fixed_content:
            match = re.search(r'```\n(.*?)```', fixed_content, re.DOTALL)
            if match:
                fixed_content = match.group(1)

        abs_path.write_text(fixed_content)
        return True

    except subprocess.CalledProcessError:
        return False


# ===== PHASE 1: DRY-RUN =====

def dry_run_fix(pr_ref: str, skip_tests: bool = False) -> Dict[str, Any]:
    """Phase 1: 计算修复方案，不 commit。

    返回: {
        'status': 'clean' | 'fixable' | 'needs_human',
        'pr': pr_number,
        'repo': repo,
        'mechanical_diff': str,
        'agent_diff': str,
        'risk_levels': {file: 'green' | 'yellow'},
        'state_file': path,
        'verification': {...}
    }
    """
    repo, pr_number = parse_pr_ref(pr_ref)
    head = get_pr_head(repo, pr_number)

    tmp = tempfile.mkdtemp(prefix=f"pr-fix-{pr_number}-")
    workdir = Path(tmp)

    print(f"→ PR #{pr_number} @ {repo}", file=sys.stderr)
    print(f"  head: {head['fork']}@{head['branch']} ({head['sha'][:10]})", file=sys.stderr)

    clone_dir, mode = clone_pr_head(repo, pr_number, head, workdir)
    pr_files = [f for f in head['changed_files'] if (clone_dir / f).is_file()]
    print(f"  clone 完成，PR 改动 {len(pr_files)} 文件", file=sys.stderr)

    result = {
        'status': 'unknown',
        'pr': pr_number,
        'repo': repo,
        'head': head,
        'clone_dir': str(clone_dir),
        'mode': mode,
        'pr_files': pr_files,
        'mechanical_diff': '',
        'agent_diff': '',
        'risk_levels': {},
        'verification': {},
    }

    # ===== Step 1: 机械修复 =====
    print("  [1/3] 机械修复（black/isort/eof）...", file=sys.stderr)
    first = run_pre_commit(clone_dir, pr_files)

    if first['exit_code'] == 0:
        print("  ✅ 首次即全绿，无需修复", file=sys.stderr)
        result['status'] = 'clean'
        state_file = workdir / "state.json"
        state_file.write_text(json.dumps(result, indent=2))
        result['state_file'] = str(state_file)
        return result

    # 机械修复改动了文件
    mechanical_files = get_changed_files(clone_dir)
    if mechanical_files:
        result['mechanical_diff'] = get_diff(clone_dir)
        result['risk_levels'].update({f: 'green' for f in mechanical_files})
        print(f"  机械修复改动了 {len(mechanical_files)} 文件", file=sys.stderr)

    # ===== Step 2: Agent 修复 =====
    print("  [2/3] Agent 修复（flake8/mypy）...", file=sys.stderr)
    second = run_pre_commit(clone_dir, pr_files)

    if second['exit_code'] == 0:
        print("  ✅ 机械修复后即全绿", file=sys.stderr)
        result['status'] = 'fixable'
        result['verification'] = {'pre_commit_passed': True}
        state_file = workdir / "state.json"
        state_file.write_text(json.dumps(result, indent=2))
        result['state_file'] = str(state_file)
        return result

    # 解析剩余错误
    errors_by_file = parse_linting_errors(second['output'], clone_dir)
    if not errors_by_file:
        print("  ⚠️  pre-commit 仍失败，但无法解析错误", file=sys.stderr)
        result['status'] = 'needs_human'
        result['verification'] = {
            'pre_commit_passed': False,
            'blocking_hooks': [n for n, s in second['hooks'].items() if s == 'Failed']
        }
        state_file = workdir / "state.json"
        state_file.write_text(json.dumps(result, indent=2))
        result['state_file'] = str(state_file)
        return result

    print(f"  发现 {len(errors_by_file)} 个文件有 linting 错误，开始 agent 修复...", file=sys.stderr)

    # 保存机械修复的 diff（在 agent 修复前）
    if not result['mechanical_diff'] and mechanical_files:
        result['mechanical_diff'] = get_diff(clone_dir)

    # Agent 修复
    fixed_files = []
    failed_files = []

    for file_path, errors in errors_by_file.items():
        print(f"    修复 {file_path} ({len(errors)} 个错误)...", file=sys.stderr)

        for attempt in range(MAX_RETRIES_PER_FILE):
            success = fix_file_with_agent(clone_dir, file_path, errors)
            if not success:
                failed_files.append(file_path)
                break

            verify = run_pre_commit(clone_dir, [file_path])
            if verify['exit_code'] == 0:
                print(f"      ✅ 修复成功（第 {attempt + 1} 次）", file=sys.stderr)
                fixed_files.append(file_path)
                result['risk_levels'][file_path] = 'yellow'
                break

            remaining = parse_linting_errors(verify['output'], clone_dir)
            if file_path not in remaining or not remaining[file_path]:
                print(f"      ✅ 修复成功", file=sys.stderr)
                fixed_files.append(file_path)
                result['risk_levels'][file_path] = 'yellow'
                break

            errors = remaining[file_path]
            print(f"      仍有 {len(errors)} 个错误，重试...", file=sys.stderr)
        else:
            print(f"      ❌ 达到最大重试次数", file=sys.stderr)
            failed_files.append(file_path)

    # 获取 agent 修复的 diff（相对于机械修复后）
    agent_files = [f for f in get_changed_files(clone_dir) if f not in mechanical_files]
    if agent_files:
        result['agent_diff'] = get_diff(clone_dir)

    # ===== Step 3: 整体验证 =====
    print("  [3/3] 整体验证...", file=sys.stderr)
    final = run_pre_commit(clone_dir, pr_files)

    if final['exit_code'] != 0:
        print("  ⚠️  仍有错误无法自动修复", file=sys.stderr)
        result['status'] = 'needs_human'
        result['verification'] = {
            'pre_commit_passed': False,
            'blocking_hooks': [n for n, s in final['hooks'].items() if s == 'Failed'],
            'failed_files': failed_files,
        }
        state_file = workdir / "state.json"
        state_file.write_text(json.dumps(result, indent=2))
        result['state_file'] = str(state_file)
        return result

    print("  ✅ 所有 linting 检查通过", file=sys.stderr)
    result['status'] = 'fixable'
    result['verification'] = {
        'pre_commit_passed': True,
        'fixed_files': fixed_files,
    }

    # 保存状态文件
    state_file = workdir / "state.json"
    state_file.write_text(json.dumps(result, indent=2))
    result['state_file'] = str(state_file)

    return result


# ===== PHASE 2: APPLY =====

def apply_fix(state_file_path: str) -> Dict[str, Any]:
    """Phase 2: 从状态文件应用修复，commit。

    返回: {
        'status': 'applied' | 'error',
        'pr': pr_number,
        'commits': [sha1, sha2],
        'clone_dir': path,
        'mode': 'writable' | 'readonly'
    }
    """
    state_file = Path(state_file_path)
    if not state_file.is_file():
        raise ValueError(f"状态文件不存在: {state_file_path}")

    state = json.loads(state_file.read_text())

    if state['status'] not in ('fixable', 'clean'):
        raise ValueError(f"状态不可应用: {state['status']}")

    clone_dir = Path(state['clone_dir'])
    if not clone_dir.is_dir():
        raise ValueError(f"clone 目录不存在: {clone_dir}")

    pr_number = state['pr']
    head = state['head']
    mode = state['mode']

    print(f"→ 应用修复 PR #{pr_number}", file=sys.stderr)
    print(f"  clone_dir: {clone_dir}", file=sys.stderr)

    commits = []

    # 检查是否有改动
    changed = get_changed_files(clone_dir)
    if not changed:
        print("  ℹ️  没有改动需要 commit", file=sys.stderr)
        return {
            'status': 'applied',
            'pr': pr_number,
            'commits': [],
            'clone_dir': str(clone_dir),
            'mode': mode,
        }

    # 分两次 commit: mechanical + agent
    mechanical_files = [f for f, risk in state['risk_levels'].items() if risk == 'green']
    agent_files = [f for f, risk in state['risk_levels'].items() if risk == 'yellow']

    # Commit mechanical
    if mechanical_files:
        mech_changed = [f for f in mechanical_files if f in changed]
        if mech_changed:
            subprocess.run(
                ['git', '-C', str(clone_dir), 'add'] + mech_changed,
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ['git', '-C', str(clone_dir), 'commit', '-m',
                 'style: apply mechanical formatting (black/isort/eof)',
                 '--no-verify'],
                capture_output=True, text=True, check=True,
            )
            sha = subprocess.run(
                ['git', '-C', str(clone_dir), 'rev-parse', 'HEAD'],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            commits.append(sha)
            print(f"  ✅ Mechanical commit: {sha[:10]}", file=sys.stderr)

    # Commit agent
    if agent_files:
        agent_changed = [f for f in agent_files if f in changed]
        if agent_changed:
            subprocess.run(
                ['git', '-C', str(clone_dir), 'add'] + agent_changed,
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ['git', '-C', str(clone_dir), 'commit', '-m',
                 'fix: resolve linting errors (agent-assisted)',
                 '--no-verify'],
                capture_output=True, text=True, check=True,
            )
            sha = subprocess.run(
                ['git', '-C', str(clone_dir), 'rev-parse', 'HEAD'],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            commits.append(sha)
            print(f"  ✅ Agent commit: {sha[:10]}", file=sys.stderr)

    # 打印下一步
    print("\n  ✅ 修复已应用", file=sys.stderr)
    _print_diffstat(clone_dir)

    if mode == 'writable':
        print(f"\n  下一步（你有 push 权限）：", file=sys.stderr)
        print(f"    cd {clone_dir}", file=sys.stderr)
        print(f"    git push origin HEAD:{head['branch']}", file=sys.stderr)
    else:
        patch_file = clone_dir.parent / f"pr-{pr_number}.patch"
        _generate_patch(clone_dir, len(commits), patch_file)
        print(f"\n  下一步（只读模式，已生成 patch）：", file=sys.stderr)
        print(f"    patch 文件: {patch_file}", file=sys.stderr)

    return {
        'status': 'applied',
        'pr': pr_number,
        'commits': commits,
        'clone_dir': str(clone_dir),
        'mode': mode,
    }


def _print_diffstat(clone_dir: Path) -> None:
    """打印 commit 的 diffstat。"""
    result = subprocess.run(
        ['git', '-C', str(clone_dir), 'diff', '--stat', 'HEAD~1'],
        capture_output=True, text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        print("  ── diffstat ──", file=sys.stderr)
        for line in result.stdout.splitlines()[:10]:
            print(f"    {line}", file=sys.stderr)


def _generate_patch(clone_dir: Path, num_commits: int, output_file: Path) -> None:
    """生成 patch 文件。"""
    result = subprocess.run(
        ['git', '-C', str(clone_dir), 'format-patch', '--stdout', f'HEAD~{num_commits}'],
        capture_output=True, text=True, check=True,
    )
    output_file.write_text(result.stdout)


# ===== MAIN =====

def main():
    parser = argparse.ArgumentParser(
        description="自动修复 FlagGems PR 的 code-style（两阶段模式）"
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Phase 1: dry-run
    dry_run_parser = subparsers.add_parser(
        'dry-run',
        help='Phase 1: 计算修复方案（不 commit）'
    )
    dry_run_parser.add_argument('pr', help='PR 编号或 URL')
    dry_run_parser.add_argument('--skip-tests', action='store_true',
                               help='跳过测试验证')
    dry_run_parser.add_argument('--json', action='store_true',
                               help='以 JSON 格式输出')

    # Phase 2: apply
    apply_parser = subparsers.add_parser(
        'apply',
        help='Phase 2: 应用修复并 commit'
    )
    apply_parser.add_argument('state_file', help='Phase 1 生成的状态文件')
    apply_parser.add_argument('--json', action='store_true',
                             help='以 JSON 格式输出')

    args = parser.parse_args()

    try:
        if args.command == 'dry-run':
            result = dry_run_fix(args.pr, skip_tests=args.skip_tests)

            if args.json:
                # JSON 输出（给 agent 解析）
                output = {
                    'check': 'code_style_fix',
                    'pr': result['pr'],
                    'repo': result['repo'],
                    'status': result['status'],
                    'state_file': result.get('state_file', ''),
                    'mechanical_diff': result.get('mechanical_diff', ''),
                    'agent_diff': result.get('agent_diff', ''),
                    'risk_levels': result.get('risk_levels', {}),
                    'verification': result.get('verification', {}),
                }
                print(json.dumps(output, indent=2, ensure_ascii=False))
            else:
                # 人类可读输出
                print(f"\n状态: {result['status']}")
                if result['status'] == 'fixable':
                    print(f"状态文件: {result['state_file']}")
                    print(f"\n机械修复: {len([f for f in result['risk_levels'] if result['risk_levels'][f] == 'green'])} 文件 🟢")
                    print(f"Agent修复: {len([f for f in result['risk_levels'] if result['risk_levels'][f] == 'yellow'])} 文件 🟡")
                    print(f"\n下一步: fix_code_style_v2.py apply {result['state_file']}")
                elif result['status'] == 'needs_human':
                    print("需要人工修复")
                    if 'blocking_hooks' in result['verification']:
                        print(f"阻塞的 hooks: {result['verification']['blocking_hooks']}")

            sys.exit(0 if result['status'] in ('clean', 'fixable') else 1)

        elif args.command == 'apply':
            result = apply_fix(args.state_file)

            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(f"\n✅ 应用完成")
                print(f"Commits: {len(result['commits'])}")

            sys.exit(0)

    except subprocess.CalledProcessError as e:
        print(f"❌ 命令执行失败: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
