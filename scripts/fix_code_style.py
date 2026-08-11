#!/usr/bin/env python3.11
"""
自动修复 FlagGems PR 的 code-style 失败。

本脚本走「验证 → 修复 → 提交」闭环：
1. 把 PR head 精确 clone/checkout 到独立临时目录（不污染工作区）
2. 第一轮：机械修复（black/isort/eof 就地改文件）
3. 第二轮：解析 flake8/mypy 错误，用 agent 修复
4. 第三轮：整体验证 + 测试（如果 --skip-tests 未设置）
5. fail-closed 门禁：只有所有检查通过才生成 commit
6. 默认只在临时目录里 commit 并打印将要 push 的内容，不自动 push
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
MAX_RETRIES_PER_FILE = 3  # Agent 修复每个文件最多重试次数


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
    """获取 PR head 的精确信息：分支名、head SHA、fork 仓库、改动文件列表。"""
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


def clone_pr_head(repo: str, head: Dict[str, str], workdir: Path) -> Path:
    """把 PR head 精确 checkout 到 workdir，返回 clone 目录。"""
    clone_dir = workdir / "repo"
    subprocess.run(
        ['gh', 'repo', 'clone', head['fork'], str(clone_dir), '--',
         '--branch', head['branch'], '--depth', '1'],
        capture_output=True, text=True, check=True,
    )
    actual = subprocess.run(
        ['git', '-C', str(clone_dir), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if actual != head['sha']:
        subprocess.run(
            ['git', '-C', str(clone_dir), 'fetch', '--depth', '1', 'origin', head['sha']],
            capture_output=True, text=True, check=True,
        )
        subprocess.run(
            ['git', '-C', str(clone_dir), 'checkout', head['sha']],
            capture_output=True, text=True, check=True,
        )
    return clone_dir


def run_pre_commit(clone_dir: Path, files: List[str]) -> Dict[str, Any]:
    """在 clone 目录里对指定文件跑 pre-commit，返回结构化结果。"""
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
    """从 pre-commit 输出解析每个 hook 的 Passed/Failed 状态。"""
    hooks: Dict[str, str] = {}
    for line in output.splitlines():
        m = re.match(r'^(.+?)\.{3,}(Passed|Failed|Skipped|.*\(no files to check\).*)', line)
        if m:
            name = m.group(1).strip()
            status = 'Passed' if 'Passed' in m.group(2) else (
                'Failed' if 'Failed' in m.group(2) else 'Skipped')
            hooks[name] = status
    return hooks


def parse_linting_errors(output: str, clone_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """从 pre-commit 输出中解析 flake8/mypy 等错误，按文件分组。

    返回: {file_path: [{'line': int, 'col': int, 'code': str, 'msg': str}, ...]}
    """
    errors_by_file: Dict[str, List[Dict[str, Any]]] = {}

    # flake8 格式: path/to/file.py:42:10: E501 line too long (88 > 79 characters)
    # mypy 格式: path/to/file.py:42: error: Name 'foo' is not defined
    pattern = r'^(.+?):(\d+):(?:(\d+):)?\s*(?:error:|warning:)?\s*([A-Z]\d+)?\s*(.+)$'

    for line in output.splitlines():
        m = re.match(pattern, line.strip())
        if m:
            file_path = m.group(1)
            line_no = int(m.group(2))
            col = int(m.group(3)) if m.group(3) else 0
            code = m.group(4) or 'unknown'
            msg = m.group(5).strip()

            # 转换为相对路径
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


def fix_file_with_agent(clone_dir: Path, file_path: str,
                       errors: List[Dict[str, Any]]) -> bool:
    """使用 agent 修复文件中的错误。

    返回: True 如果修复成功，False 如果需要人工
    """
    abs_path = clone_dir / file_path
    if not abs_path.is_file():
        return False

    # 读取文件内容
    content = abs_path.read_text()

    # 构造错误摘要
    error_summary = "\n".join([
        f"Line {e['line']}, col {e['col']}: [{e['code']}] {e['msg']}"
        for e in errors
    ])

    # 构造 prompt
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

    # 调用 Claude
    try:
        result = subprocess.run(
            ['claude', '--model', 'claude-sonnet-4-20250514', '--no-cache'],
            input=prompt, capture_output=True, text=True, check=True,
        )
        fixed_content = result.stdout.strip()

        # 提取代码块（如果 Claude 用了 ```python 包裹）
        if '```python' in fixed_content:
            match = re.search(r'```python\n(.*?)```', fixed_content, re.DOTALL)
            if match:
                fixed_content = match.group(1)
        elif '```' in fixed_content:
            match = re.search(r'```\n(.*?)```', fixed_content, re.DOTALL)
            if match:
                fixed_content = match.group(1)

        # 写回文件
        abs_path.write_text(fixed_content)
        return True

    except subprocess.CalledProcessError as e:
        print(f"    ⚠️  Agent 调用失败: {e.stderr}", file=sys.stderr)
        return False


def run_tests(clone_dir: Path) -> bool:
    """跑与 PR 相关的测试。

    简化版：只跑 pytest，如果仓库有测试的话。
    返回: True 如果测试通过或无测试，False 如果测试失败
    """
    test_dir = clone_dir / "tests"
    if not test_dir.is_dir():
        return True  # 无测试目录，跳过

    # 尝试跑 pytest
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', '-xvs', '--tb=short'],
        cwd=str(clone_dir), capture_output=True, text=True, timeout=300,
    )

    if result.returncode == 0:
        return True

    # 测试失败，打印输出
    print("  ⚠️  测试失败:")
    print(result.stdout[-2000:])  # 只打印最后 2000 字符
    return False


def get_changed_files(clone_dir: Path) -> List[str]:
    """返回被 git 改动的文件列表。"""
    result = subprocess.run(
        ['git', '-C', str(clone_dir), 'diff', '--name-only'],
        capture_output=True, text=True, check=True,
    )
    return [f for f in result.stdout.splitlines() if f.strip()]


def make_commit(clone_dir: Path, changed_files: List[str], msg: str) -> str:
    """把改动的文件 commit（只在临时 clone 里），返回 commit SHA。"""
    subprocess.run(
        ['git', '-C', str(clone_dir), 'add'] + changed_files,
        capture_output=True, text=True, check=True,
    )
    subprocess.run(
        ['git', '-C', str(clone_dir), 'commit', '-m', msg, '--no-verify'],
        capture_output=True, text=True, check=True,
    )
    return subprocess.run(
        ['git', '-C', str(clone_dir), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def get_commit_diffstat(clone_dir: Path) -> str:
    """返回刚生成的 commit 的 diffstat，供人工确认将要 push 的内容。"""
    return subprocess.run(
        ['git', '-C', str(clone_dir), 'show', '--stat', '--oneline', 'HEAD'],
        capture_output=True, text=True, check=True,
    ).stdout


def fix_pr_code_style(pr_ref: str, skip_tests: bool = False, keep_dir: bool = False) -> Dict[str, Any]:
    """对单个 PR 跑完整的 验证→修复→提交 闭环。"""
    repo, pr_number = parse_pr_ref(pr_ref)
    head = get_pr_head(repo, pr_number)

    tmp = tempfile.mkdtemp(prefix=f"pr-fix-{pr_number}-")
    workdir = Path(tmp)
    keep = keep_dir

    try:
        print(f"→ PR #{pr_number} @ {repo}")
        print(f"  head: {head['fork']}@{head['branch']} ({head['sha'][:10]})")

        clone_dir = clone_pr_head(repo, head, workdir)
        pr_files = [f for f in head['changed_files'] if (clone_dir / f).is_file()]
        print(f"  clone 完成，PR 改动 {len(head['changed_files'])} 文件"
              f"（现存 {len(pr_files)}）")

        # ===== 第一轮：机械修复 =====
        print(f"  [1/3] 机械修复（black/isort/eof）...")
        first = run_pre_commit(clone_dir, pr_files)

        if first['exit_code'] == 0:
            print("  ✅ 首次即全绿，无需修复")
            return {'status': 'clean', 'pr': pr_number}

        # 格式化 hook 已就地修改文件
        mechanical_changes = get_changed_files(clone_dir)
        if mechanical_changes:
            print(f"  机械修复改动了 {len(mechanical_changes)} 个文件")
            make_commit(clone_dir, mechanical_changes,
                       "style: apply mechanical formatting (black/isort/eof)")

        # ===== 第二轮：Agent 修复 =====
        print("  [2/3] Agent 修复（flake8/mypy）...")
        second = run_pre_commit(clone_dir, pr_files)

        if second['exit_code'] == 0:
            print("  ✅ 机械修复后即全绿")
            keep = True
            print(f"  临时目录：{clone_dir}")
            print(f"  如确认无误，手动 push：")
            print(f"    git -C {clone_dir} push origin HEAD:{head['branch']}")
            return {
                'status': 'auto_fixable',
                'pr': pr_number,
                'clone_dir': str(clone_dir),
                'mechanical_only': True,
            }

        # 解析剩余错误
        errors_by_file = parse_linting_errors(second['output'], clone_dir)
        if not errors_by_file:
            print("  ⚠️  pre-commit 仍失败，但无法解析错误信息")
            failed_hooks = [name for name, st in second['hooks'].items() if st == 'Failed']
            return {
                'status': 'needs_human',
                'pr': pr_number,
                'blocking_hooks': failed_hooks,
            }

        print(f"  发现 {len(errors_by_file)} 个文件有 linting 错误，开始 agent 修复...")

        # 对每个文件尝试修复
        fixed_files = []
        failed_files = []

        for file_path, errors in errors_by_file.items():
            print(f"    修复 {file_path} ({len(errors)} 个错误)...")

            for attempt in range(MAX_RETRIES_PER_FILE):
                success = fix_file_with_agent(clone_dir, file_path, errors)
                if not success:
                    failed_files.append(file_path)
                    break

                # 验证修复
                verify = run_pre_commit(clone_dir, [file_path])
                if verify['exit_code'] == 0:
                    print(f"      ✅ 修复成功（第 {attempt + 1} 次尝试）")
                    fixed_files.append(file_path)
                    break

                # 仍有错误，解析并重试
                remaining = parse_linting_errors(verify['output'], clone_dir)
                if file_path not in remaining or not remaining[file_path]:
                    print(f"      ✅ 修复成功")
                    fixed_files.append(file_path)
                    break

                errors = remaining[file_path]
                print(f"      仍有 {len(errors)} 个错误，重试...")
            else:
                print(f"      ❌ 达到最大重试次数，放弃")
                failed_files.append(file_path)

        # Commit agent 修复
        agent_changes = get_changed_files(clone_dir)
        if agent_changes:
            make_commit(clone_dir, agent_changes,
                       "fix: resolve linting errors (agent-assisted)")

        # ===== 第三轮：整体验证 + 测试 =====
        print("  [3/3] 整体验证...")
        final = run_pre_commit(clone_dir, pr_files)

        if final['exit_code'] != 0:
            print("  ⚠️  仍有错误无法自动修复")
            failed_hooks = [name for name, st in final['hooks'].items() if st == 'Failed']
            return {
                'status': 'needs_human',
                'pr': pr_number,
                'blocking_hooks': failed_hooks,
                'failed_files': failed_files,
            }

        print("  ✅ 所有 linting 检查通过")

        # 跑测试
        if not skip_tests:
            print("  跑测试...")
            if not run_tests(clone_dir):
                print("  ⚠️  测试失败，需人工检查")
                return {
                    'status': 'needs_human',
                    'pr': pr_number,
                    'reason': 'tests_failed',
                }

        print("  ✅ 修复完成，所有检查通过")
        print("  ── 将要 push 的内容 ──")
        print(get_commit_diffstat(clone_dir))
        print(f"  如确认无误，手动 push：")
        print(f"    git -C {clone_dir} push origin HEAD:{head['branch']}")
        keep = True
        print(f"  临时目录已保留：{clone_dir}")

        return {
            'status': 'auto_fixable',
            'pr': pr_number,
            'clone_dir': str(clone_dir),
            'fixed_files': fixed_files,
            'failed_files': failed_files,
        }

    finally:
        if not keep:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="自动修复 FlagGems PR 的 code-style 失败（机械 + agent）")
    parser.add_argument('pr', help='PR 编号或完整 URL')
    parser.add_argument('--skip-tests', action='store_true',
                       help='跳过测试验证')
    parser.add_argument('--keep-dir', action='store_true',
                       help='保留临时 clone 目录')
    args = parser.parse_args()

    try:
        result = fix_pr_code_style(
            args.pr,
            skip_tests=args.skip_tests,
            keep_dir=args.keep_dir,
        )
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e}\n{e.stderr}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)

    sys.exit(0 if result['status'] in ('clean', 'auto_fixable') else 1)


if __name__ == '__main__':
    main()
