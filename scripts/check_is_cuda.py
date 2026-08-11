#!/usr/bin/env python3.11
"""
检查 FlagGems PR 中是否滥用 is_cuda，违反跨芯片兼容红线。

根据 flaggems-domain.md §1 和 §2.7：
- is_cuda 把代码钉死在 NVIDIA 上，是红线
- 应该使用 x.device.type == runtime.device.name
- 应该使用 flag_gems.runtime.torch_device_fn 而不是 torch.cuda
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any


def get_pr_diff(pr_url_or_number: str) -> str:
    """获取 PR 的 diff 内容"""
    # 从 URL 或纯数字解析 owner/repo 和 PR 编号
    if pr_url_or_number.isdigit():
        # 纯数字，需要指定 repo（默认 FlagOpen/FlagGems）
        pr_number = pr_url_or_number
        repo = "FlagOpen/FlagGems"
    else:
        # 从 URL 提取 owner/repo 和编号
        match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', pr_url_or_number)
        if not match:
            raise ValueError(f"无法解析 PR URL: {pr_url_or_number}")
        owner, repo_name, pr_number = match.groups()
        repo = f"{owner}/{repo_name}"

    # 使用 gh CLI 获取 diff，指定 repo
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
        # 新文件标记
        if line.startswith('+++ b/'):
            current_file = line[6:]  # 去掉 '+++ b/'
            files[current_file] = []
            continue

        # 行号标记 @@ -old +new @@
        if line.startswith('@@'):
            match = re.search(r'\+(\d+)', line)
            if match:
                current_line_number = int(match.group(1))
            continue

        # 只检查新增行（以 + 开头，但不是 +++）
        if line.startswith('+') and not line.startswith('+++'):
            if current_file:
                files[current_file].append((current_line_number, line[1:]))  # 去掉开头的 +
                current_line_number += 1
        elif not line.startswith('-'):
            # 上下文行（不是删除行）
            current_line_number += 1

    return files


def should_check_file(file_path: str) -> bool:
    """
    判断文件是否需要检查 is_cuda 滥用。

    只检查算子实现文件，跳过测试/benchmark/配置/文档。
    """
    # 跳过非 Python 文件
    if not file_path.endswith('.py'):
        return False

    # 跳过路径（测试、benchmark、配置、文档、脚本）
    skip_patterns = [
        r'^tests/',
        r'^test/',
        r'^benchmark/',
        r'^conf/',
        r'^docs/',
        r'^scripts/',
        r'^tools/',
        r'test_.*\.py$',  # 测试文件
    ]

    for pattern in skip_patterns:
        if re.search(pattern, file_path):
            return False

    # 只检查算子实现路径
    check_patterns = [
        r'flag_gems/ops/',
        r'flag_gems/fused/',
        r'src/flag_gems/ops/',
        r'src/flag_gems/fused/',
    ]

    for pattern in check_patterns:
        if re.search(pattern, file_path):
            return True

    # 默认不检查（保守策略）
    return False


def remove_comments_and_strings(line: str) -> str:
    """
    移除行中的注释和字符串，只保留实际代码。

    简化处理：
    - 移除 # 后的所有内容（行尾注释）
    - 移除引号内的内容
    """
    # 先处理字符串（简化：假设没有转义引号）
    # 移除单引号字符串
    line = re.sub(r"'[^']*'", '""', line)
    # 移除双引号字符串
    line = re.sub(r'"[^"]*"', '""', line)

    # 移除注释（# 后的所有内容）
    if '#' in line:
        line = line[:line.index('#')]

    return line


def check_is_cuda_abuse(files: Dict[str, List[tuple]]) -> List[Dict[str, Any]]:
    """
    检查是否滥用 is_cuda。

    检查模式:
    1. .is_cuda 属性访问
    2. torch.cuda 模块使用（应该用 torch_device_fn）
    3. 硬编码 "cuda" 字符串（在设备判断上下文中）

    只检查算子实现文件（flag_gems/ops, flag_gems/fused），
    跳过测试、benchmark、配置、文档。
    """
    violations = []

    # 检查模式
    patterns = [
        {
            'regex': re.compile(r'\.is_cuda\b'),
            'description': '使用了 .is_cuda 属性（违反跨芯片兼容）',
            'suggestion': '移除显式检查，依赖 kernel launch 自然错误；或改用 x.device.type == runtime.device.name',
            'reference': 'PR #3726: "is_cuda is invalid for non NV chips"'
        },
        {
            'regex': re.compile(r'\btorch\.cuda\b(?!nn)'),  # 排除 torch.cudnn
            'description': '直接使用 torch.cuda 模块',
            'suggestion': '使用 flag_gems.runtime.torch_device_fn',
            'reference': 'flaggems-domain.md §2.7'
        },
        {
            'regex': re.compile(r'device\.type\s*==\s*["\']cuda["\']'),
            'description': '硬编码 "cuda" 字符串',
            'suggestion': '使用 runtime.device.name',
            'reference': 'flaggems-domain.md §2.7'
        }
    ]

    for file_path, lines in files.items():
        # 只检查特定路径的文件
        if not should_check_file(file_path):
            continue

        for line_num, content in lines:
            # 移除注释和字符串后再检查
            code_only = remove_comments_and_strings(content)

            # 如果移除后是空的，跳过
            if not code_only.strip():
                continue

            # 检查每个模式
            for pattern in patterns:
                match = pattern['regex'].search(code_only)
                if match:
                    violation = {
                        'file': file_path,
                        'line': line_num,
                        'content': content.strip(),
                        'matched': match.group(0),
                        'description': pattern['description'],
                        'suggestion': pattern['suggestion']
                    }
                    if 'reference' in pattern:
                        violation['reference'] = pattern['reference']
                    violations.append(violation)

    return violations


def main():
    parser = argparse.ArgumentParser(
        description='检查 FlagGems PR 中的 is_cuda 滥用（跨芯片兼容红线）'
    )
    parser.add_argument(
        'pr',
        help='PR URL 或编号'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='以 JSON 格式输出'
    )

    args = parser.parse_args()

    try:
        # 获取 PR diff
        diff_content = get_pr_diff(args.pr)

        # 解析文件和新增行
        files = parse_diff_files(diff_content)

        # 检查 is_cuda 滥用
        violations = check_is_cuda_abuse(files)

        # 输出结果
        if args.json:
            result = {
                'check': 'is_cuda_abuse',
                'status': 'failed' if violations else 'passed',
                'violations': violations
            }
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            if not violations:
                print("✅ 未发现 is_cuda 滥用")
                sys.exit(0)

            print(f"❌ 发现 {len(violations)} 处 is_cuda 滥用（违反跨芯片兼容红线）\n")
            for v in violations:
                print(f"📁 {v['file']}:{v['line']}")
                print(f"   内容: {v['content']}")
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
