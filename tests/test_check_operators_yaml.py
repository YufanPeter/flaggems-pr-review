#!/usr/bin/env python3.11
"""
测试 check_operators_yaml.py 的基本功能。
"""

import sys
from pathlib import Path

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from check_operators_yaml import (
    extract_operator_ids,
    check_alphabetical_order,
    should_check_file
)


def test_should_check_file():
    """测试文件路径过滤"""
    assert should_check_file('operators.yaml')
    assert should_check_file('conf/operators.yaml')
    assert should_check_file('src/operators.yaml')
    assert not should_check_file('operators.py')
    # operators.yaml 任何路径都应该检查
    # assert not should_check_file('test_operators.yaml')
    print("✅ test_should_check_file 通过")


def test_extract_operator_ids():
    """测试算子 ID 提取"""
    lines = [
        (10, '  - id: abs'),
        (20, '  - id: add'),
        (30, '    description: Add two tensors'),
        (40, '  - id: mul'),
    ]
    result = extract_operator_ids(lines)
    assert len(result) == 3, f"期望 3 个算子，得到 {len(result)}"
    assert result[0] == (10, 'abs')
    assert result[1] == (20, 'add')
    assert result[2] == (40, 'mul')
    print("✅ test_extract_operator_ids 通过")


def test_extract_operator_ids_with_spaces():
    """测试带空格的算子 ID"""
    lines = [
        (10, '  - id:   abs  '),
        (20, '  - id: add'),
    ]
    result = extract_operator_ids(lines)
    assert len(result) == 2
    assert result[0] == (10, 'abs')
    assert result[1] == (20, 'add')
    print("✅ test_extract_operator_ids_with_spaces 通过")


def test_check_alphabetical_order_correct():
    """测试正确的字母序"""
    operators = [
        (10, 'abs'),
        (20, 'add'),
        (30, 'mul'),
        (40, 'sub'),
    ]
    violations = check_alphabetical_order(operators)
    assert len(violations) == 0, f"期望 0 个违规，得到 {len(violations)}"
    print("✅ test_check_alphabetical_order_correct 通过")


def test_check_alphabetical_order_wrong():
    """测试错误的字母序"""
    operators = [
        (10, 'add'),
        (20, 'sub'),
        (30, 'mul'),  # sub > mul，顺序错误
    ]
    violations = check_alphabetical_order(operators)
    assert len(violations) == 1, f"期望 1 个违规，得到 {len(violations)}"
    assert violations[0]['current'] == 'sub'
    assert violations[0]['next'] == 'mul'
    assert violations[0]['line'] == 20
    print("✅ test_check_alphabetical_order_wrong 通过")


def test_check_alphabetical_order_multiple_errors():
    """测试多个排序错误"""
    operators = [
        (10, 'sub'),
        (20, 'add'),  # sub > add
        (30, 'mul'),
        (40, 'abs'),  # mul > abs
    ]
    violations = check_alphabetical_order(operators)
    assert len(violations) >= 2, f"期望至少 2 个违规，得到 {len(violations)}"
    print(f"✅ test_check_alphabetical_order_multiple_errors 通过（发现 {len(violations)} 个错误）")


def test_underscore_prefix():
    """测试下划线前缀排序"""
    operators = [
        (10, '_add'),
        (20, '_sub'),
        (30, 'add'),
        (40, 'sub'),
    ]
    violations = check_alphabetical_order(operators)
    assert len(violations) == 0, f"期望 0 个违规，得到 {len(violations)}"
    print("✅ test_underscore_prefix 通过")


def test_real_operators():
    """测试真实的算子名称"""
    operators = [
        (10, '_reshape_alias'),
        (20, 'abs'),
        (30, 'abs_'),
        (40, 'absolute'),
        (50, 'acos'),
        (60, 'add'),
        (70, 'add_'),
    ]
    violations = check_alphabetical_order(operators)
    assert len(violations) == 0, f"期望 0 个违规，得到 {len(violations)}"
    print("✅ test_real_operators 通过")


def main():
    """运行所有测试"""
    print("🧪 开始测试 check_operators_yaml.py\n")

    tests = [
        test_should_check_file,
        test_extract_operator_ids,
        test_extract_operator_ids_with_spaces,
        test_check_alphabetical_order_correct,
        test_check_alphabetical_order_wrong,
        test_check_alphabetical_order_multiple_errors,
        test_underscore_prefix,
        test_real_operators,
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
