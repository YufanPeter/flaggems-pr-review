#!/usr/bin/env python3.11
"""
检查 FlagGems PR 中 __init__.py 的 __all__ 注册是否按字母序排列。

高频问题（6+ PRs）：新增算子时容易插入到错误位置。
"""

import argparse
import json
import re
import subprocess
import sys
from typing import List, Dict, Any, Optional


def get_pr_diff(pr_url_or_number: str) -> tuple:
    """获取 PR 的 diff 内容，返回 (diff_content, pr_number, repo)"""
    if pr_url_or_number.isdigit():
        pr_number = pr_url_or_number
        repo = "FlagOpen/FlagGems"
    else:
        match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_url_or_number)
        if not match:
            raise ValueError(f"无法解析 PR URL: {pr_url_or_number}")
        owner, repo_name, pr_number = match.groups()
        repo = f"{owner}/{repo_name}"

    result = subprocess.run(
        ['gh', 'pr', 'diff', pr_number, '--repo', repo],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout, pr_number, repo


def parse_diff_files(diff_content: str) -> Dict[str, List[tuple]]:
    """
    解析 diff，提取每个文件的新增行。

    返回: {文件路径: [(行号, 内容), ...]}
    """
    files = {}
    current_file = None
    current_line_number = 0

    for line in diff_content.split('\n'):
        if line.startswith('+++ b/'):
            current_file = line[6:]
            files[current_file] = []
            continue

        if line.startswith('@@'):
            match = re.search(r'\+(\d+)', line)
            if match:
                current_line_number = int(match.group(1))
            continue

        if line.startswith('+') and not line.startswith('+++'):
            if current_file:
                files[current_file].append((current_line_number, line[1:]))
                current_line_number += 1
        elif not line.startswith('-'):
            current_line_number += 1

    return files


def should_check_file(file_path: str) -> bool:
    """判断是否需要检查 __all__ 排序"""
    # 只检查算子 __init__.py
    patterns = [
        r'flag_gems/ops/__init__\.py$',
        r'flag_gems/fused/__init__\.py$',
        r'src/flag_gems/ops/__init__\.py$',
        r'src/flag_gems/fused/__init__\.py$',
    ]

    return any(re.search(pattern, file_path) for pattern in patterns)


def extract_all_list(lines: List[tuple]) -> Optional[List[str]]:
    """
    从新增行中提取 __all__ 列表的条目。

    支持两种场景：
    1. 完整的 __all__ = [...] 块（包含 __all__ = [ 行）
    2. 中间插入（只有新增的条目行，通过启发式检测）

    返回: 新增的条目列表，如果没有修改 __all__ 则返回 None
    """
    entries = []
    in_all_block = False

    for line_num, content in lines:
        # 场景1：检测 __all__ 开始
        if '__all__' in content and '[' in content:
            in_all_block = True
            # 可能在同一行就有条目
            if '"' in content or "'" in content:
                matches = re.findall(r'["\']([^"\']+)["\']', content)
                entries.extend(matches)
            continue

        # 在 __all__ 块中
        if in_all_block:
            # 检测结束
            if ']' in content:
                # 最后一行可能还有条目
                if '"' in content or "'" in content:
                    matches = re.findall(r'["\']([^"\']+)["\']', content)
                    entries.extend(matches)
                break

            # 提取条目
            if '"' in content or "'" in content:
                matches = re.findall(r'["\']([^"\']+)["\']', content)
                entries.extend(matches)

    # 场景2：启发式检测 - 如果没有找到 __all__ = [，
    # 但有看起来像列表条目的行（引号包裹的字符串，带逗号）
    if not entries:
        # 检查是否有至少2行连续的字符串字面量模式，避免误判单个字符串
        string_literal_lines = []
        for line_num, content in lines:
            # 匹配模式：    "identifier",
            if re.match(r'^\s*["\'][^"\']+["\']\s*,?\s*$', content.strip()):
                string_literal_lines.append((line_num, content))

        # 只有连续2行以上的字符串字面量才认为是 __all__ 条目
        if len(string_literal_lines) >= 2:
            for line_num, content in string_literal_lines:
                matches = re.findall(r'["\']([^"\']+)["\']', content)
                entries.extend(matches)

    return entries if entries else None


def check_alphabetical_order(entries: List[str]) -> List[Dict[str, Any]]:
    """
    检查条目是否按字母序排列。

    返回: 违规列表
    """
    violations = []

    for i in range(len(entries) - 1):
        current = entries[i]
        next_item = entries[i + 1]

        # 字母序比较（case-sensitive，因为 Python 标识符区分大小写）
        if current > next_item:
            violations.append({
                'current': current,
                'next': next_item,
                'position': i,
                'description': f'"{current}" 应该排在 "{next_item}" 之后',
                'suggestion': f'将 "{current}" 移到正确位置'
            })

    return violations


def check_init_registration(files: Dict[str, List[tuple]]) -> List[Dict[str, Any]]:
    """
    检查 __init__.py 的 __all__ 注册排序。

    返回: 违规列表
    """
    all_violations = []

    for file_path, lines in files.items():
        if not should_check_file(file_path):
            continue

        # 提取新增的 __all__ 条目
        entries = extract_all_list(lines)
        if not entries:
            continue

        # 检查字母序
        violations = check_alphabetical_order(entries)

        for v in violations:
            all_violations.append({
                'file': file_path,
                'current': v['current'],
                'next': v['next'],
                'description': v['description'],
                'suggestion': v['suggestion']
            })

    return all_violations


def main():
    parser = argparse.ArgumentParser(
        description='检查 FlagGems PR 中 __init__.py 的 __all__ 注册排序'
    )
    parser.add_argument('pr', help='PR URL 或编号')
    parser.add_argument('--json', action='store_true', help='以 JSON 格式输出')

    args = parser.parse_args()

    try:
        # 获取 PR diff
        diff_content, pr_number, repo = get_pr_diff(args.pr)

        # 解析文件和新增行
        files = parse_diff_files(diff_content)

        # 检查 __all__ 排序
        violations = check_init_registration(files)

        # 输出结果
        if args.json:
            result = {
                'check': 'init_registration_order',
                'pr': pr_number,
                'repo': repo,
                'status': 'failed' if violations else 'passed',
                'violations': violations
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if not violations:
                print("✅ __init__.py 的 __all__ 注册排序正确")
                sys.exit(0)

            print(f"❌ 发现 {len(violations)} 处 __all__ 排序错误\n")
            for v in violations:
                print(f"📁 {v['file']}")
                print(f"   问题: {v['description']}")
                print(f"   建议: {v['suggestion']}")
                print()
            sys.exit(1)

    except subprocess.CalledProcessError as e:
        print(f"❌ 获取 PR diff 失败: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
