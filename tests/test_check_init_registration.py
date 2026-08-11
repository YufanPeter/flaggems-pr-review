#!/usr/bin/env python3.11
"""
测试 check_init_registration.py 的基本功能。
"""

import sys
from pathlib import Path

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from check_init_registration import (
    extract_all_list,
    check_alphabetical_order,
    should_check_file
)


def test_should_check_file():
    """测试文件路径过滤"""
    assert should_check_file('flag_gems/ops/__init__.py')
    assert should_check_file('src/flag_gems/ops/__init__.py')
    assert should_check_file('flag_gems/fused/__init__.py')
    assert not should_check_file('tests/test_ops.py')
    assert not should_check_file('flag_gems/runtime/__init__.py')
    print("✅ test_should_check_file 通过")


def test_extract_all_list_single_line():
    """测试单行 __all__ 提取"""
    lines = [
        (1, '__all__ = ["add", "sub"]'),
    ]
    result = extract_all_list(lines)
    assert result == ["add", "sub"], f"期望 ['add', 'sub']，得到 {result}"
    print("✅ test_extract_all_list_single_line 通过")


def test_extract_all_list_multi_line():
    """测试多行 __all__ 提取"""
    lines = [
        (1, '__all__ = ['),
        (2, '    "add",'),
        (3, '    "mul",'),
        (4, '    "sub",'),
        (5, ']'),
    ]
    result = extract_all_list(lines)
    assert result == ["add", "mul", "sub"], f"期望 ['add', 'mul', 'sub']，得到 {result}"
    print("✅ test_extract_all_list_multi_line 通过")


def test_extract_all_list_mixed():
    """测试混合格式"""
    lines = [
        (1, '__all__ = ['),
        (2, '    "add",'),
        (3, '    "sub",'),
        (4, ']'),
    ]
    result = extract_all_list(lines)
    assert result == ["add", "sub"], f"期望 ['add', 'sub']，得到 {result}"
    print("✅ test_extract_all_list_mixed 通过")


def test_check_alphabetical_order_correct():
    """测试正确的字母序"""
    entries = ["abs", "add", "mul", "sub"]
    violations = check_alphabetical_order(entries)
    assert len(violations) == 0, f"期望 0 个违规，得到 {len(violations)}"
    print("✅ test_check_alphabetical_order_correct 通过")


def test_check_alphabetical_order_wrong():
    """测试错误的字母序"""
    entries = ["add", "sub", "mul"]  # sub 和 mul 顺序错误
    violations = check_alphabetical_order(entries)
    assert len(violations) == 1, f"期望 1 个违规，得到 {len(violations)}"
    assert violations[0]['current'] == 'sub'
    assert violations[0]['next'] == 'mul'
    print("✅ test_check_alphabetical_order_wrong 通过")


def test_check_alphabetical_order_multiple_errors():
    """测试多个排序错误"""
    entries = ["sub", "add", "mul", "abs"]  # 完全乱序
    violations = check_alphabetical_order(entries)
    assert len(violations) >= 1, f"期望至少 1 个违规，得到 {len(violations)}"
    print(f"✅ test_check_alphabetical_order_multiple_errors 通过（发现 {len(violations)} 个错误）")


def test_case_sensitive():
    """测试大小写敏感"""
    entries = ["Add", "add"]  # 大写 A 在小写 a 之前（ASCII 顺序）
    violations = check_alphabetical_order(entries)
    assert len(violations) == 0, f"期望 0 个违规（大写在前），得到 {len(violations)}"

    entries = ["add", "Add"]  # 小写 a 在大写 A 之后
    violations = check_alphabetical_order(entries)
    assert len(violations) == 1, f"期望 1 个违规，得到 {len(violations)}"
    print("✅ test_case_sensitive 通过")


def test_underscore_prefix():
    """测试下划线前缀排序"""
    entries = ["_add", "_sub", "add", "sub"]
    violations = check_alphabetical_order(entries)
    assert len(violations) == 0, f"期望 0 个违规，得到 {len(violations)}"
    print("✅ test_underscore_prefix 通过")


def main():
    """运行所有测试"""
    print("🧪 开始测试 check_init_registration.py\n")

    tests = [
        test_should_check_file,
        test_extract_all_list_single_line,
        test_extract_all_list_multi_line,
        test_extract_all_list_mixed,
        test_check_alphabetical_order_correct,
        test_check_alphabetical_order_wrong,
        test_check_alphabetical_order_multiple_errors,
        test_case_sensitive,
        test_underscore_prefix,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"❌ {test.__name__} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} 出错: {e}")
            failed += 1

    print(f"\n{'='*50}")
    if failed == 0:
        print(f"✅ 所有 {len(tests)} 个测试通过")
        sys.exit(0)
    else:
        print(f"❌ {failed}/{len(tests)} 个测试失败")
        sys.exit(1)


if __name__ == '__main__':
    main()
