#!/usr/bin/env python3.11
"""
检查 FlagGems PR 中 operators.yaml 的算子 ID 是否按字母序排列。

高频问题：新增算子时容易插入到错误位置。
"""

import argparse
import json
import re
import subprocess
import sys
from typing import List, Dict, Any, Optional


def get_pr_diff(pr_url_or_number: str) -> str:
    """获取 PR 的 diff 内容"""
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
    return result.stdout


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
    """判断是否需要检查 operators.yaml"""
    return file_path.endswith('operators.yaml')


def extract_operator_ids(lines: List[tuple]) -> List[tuple]:
    """
    从新增行中提取算子 ID。

    返回: [(行号, operator_id), ...]
    """
    operators = []

    for line_num, content in lines:
        # 匹配 "  - id: <operator_name>"
        match = re.match(r'^  - id:\s+(\S+)', content)
        if match:
            op_id = match.group(1)
            operators.append((line_num, op_id))

    return operators


def check_alphabetical_order(operators: List[tuple]) -> List[Dict[str, Any]]:
    """
    检查算子 ID 是否按字母序排列。

    operators: [(行号, operator_id), ...]
    返回: 违规列表
    """
    violations = []

    for i in range(len(operators) - 1):
        current_line, current_id = operators[i]
        next_line, next_id = operators[i + 1]

        # 字母序比较
        if current_id > next_id:
            violations.append({
                'line': current_line,
                'current': current_id,
                'next': next_id,
                'description': f'"{current_id}" 应该排在 "{next_id}" 之后',
                'suggestion': f'将 "{current_id}" 移到正确位置'
            })

    return violations


def check_operators_yaml(files: Dict[str, List[tuple]]) -> List[Dict[str, Any]]:
    """
    检查 operators.yaml 的排序。

    返回: 违规列表
    """
    all_violations = []

    for file_path, lines in files.items():
        if not should_check_file(file_path):
            continue

        # 提取新增的算子 ID
        operators = extract_operator_ids(lines)
        if not operators:
            continue

        # 检查字母序
        violations = check_alphabetical_order(operators)

        for v in violations:
            all_violations.append({
                'file': file_path,
                'line': v['line'],
                'current': v['current'],
                'next': v['next'],
                'description': v['description'],
                'suggestion': v['suggestion']
            })

    return all_violations


def main():
    parser = argparse.ArgumentParser(
        description='检查 FlagGems PR 中 operators.yaml 的排序'
    )
    parser.add_argument('pr', help='PR URL 或编号')
    parser.add_argument('--json', action='store_true', help='以 JSON 格式输出')

    args = parser.parse_args()

    try:
        # 获取 PR diff
        diff_content = get_pr_diff(args.pr)

        # 解析文件和新增行
        files = parse_diff_files(diff_content)

        # 检查排序
        violations = check_operators_yaml(files)

        # 输出结果
        if args.json:
            result = {
                'check': 'operators_yaml_order',
                'status': 'failed' if violations else 'passed',
                'violations': violations
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if not violations:
                print("✅ operators.yaml 排序正确")
                sys.exit(0)

            print(f"❌ 发现 {len(violations)} 处排序错误\n")
            for v in violations:
                print(f"📁 {v['file']}:{v['line']}")
                print(f"   问题: {v['description']}")
                print(f"   建议: {v['suggestion']}")
                print()
            sys.exit(1)

    except subprocess.CalledProcessError as e:
        print(f"❌ 获取 PR diff 失败: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
