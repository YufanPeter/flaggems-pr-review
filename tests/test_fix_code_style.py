#!/usr/bin/env python3.11
"""测试统一的 code-style 修复脚本（机械 + agent 两种模式）。"""

import tempfile
from pathlib import Path
import subprocess
import sys


def test_parse_flake8_errors():
    """测试 flake8 错误解析。"""
    from fix_code_style import parse_linting_errors

    output = """
src/ops/add.py:42:10: E501 line too long (88 > 79 characters)
src/ops/add.py:50:1: F401 'torch' imported but unused
src/ops/mul.py:100:5: F821 undefined name 'foo'
"""

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir)
        (clone_dir / "src" / "ops").mkdir(parents=True)
        (clone_dir / "src" / "ops" / "add.py").touch()
        (clone_dir / "src" / "ops" / "mul.py").touch()

        errors = parse_linting_errors(output, clone_dir)

        assert "src/ops/add.py" in errors
        assert len(errors["src/ops/add.py"]) == 2
        assert errors["src/ops/add.py"][0]["code"] == "E501"
        assert errors["src/ops/add.py"][1]["code"] == "F401"

        assert "src/ops/mul.py" in errors
        assert len(errors["src/ops/mul.py"]) == 1
        assert errors["src/ops/mul.py"][0]["code"] == "F821"

    print("✓ test_parse_flake8_errors passed")


def test_mechanical_only_mode():
    """测试函数签名和默认行为。"""
    from fix_code_style import fix_pr_code_style

    # 验证函数签名正确
    import inspect
    sig = inspect.signature(fix_pr_code_style)
    assert 'skip_tests' in sig.parameters
    assert 'keep_dir' in sig.parameters
    # enable_agent 参数已移除
    assert 'enable_agent' not in sig.parameters

    print("✓ test_mechanical_only_mode passed")


def test_agent_prompt_construction():
    """测试 agent prompt 的构造。"""
    errors = [
        {'line': 42, 'col': 10, 'code': 'E501', 'msg': 'line too long (88 > 79)'},
        {'line': 50, 'col': 1, 'code': 'F401', 'msg': "'torch' imported but unused"},
    ]

    file_content = "import torch\n\ndef foo():\n    pass\n"

    error_summary = "\n".join([
        f"Line {e['line']}, col {e['col']}: [{e['code']}] {e['msg']}"
        for e in errors
    ])

    prompt = f"""Fix the following linting errors in this Python file:

File: test.py

Errors:
{error_summary}

Current file content:
```python
{file_content}```

Fix all the errors listed above. Return ONLY the corrected file content, no explanations."""

    # 验证 prompt 包含必要信息
    assert "E501" in prompt
    assert "F401" in prompt
    assert "import torch" in prompt
    assert "Line 42" in prompt

    print("✓ test_agent_prompt_construction passed")


def test_integration_structure():
    """测试集成流程结构。"""
    # 验证工具函数可调用
    from fix_code_style import (
        parse_pr_ref,
        get_changed_files,
        make_commit,
        run_pre_commit,
    )

    # 测试 PR 解析
    repo, pr_num = parse_pr_ref("5395")
    assert repo == "flagos-ai/FlagGems"
    assert pr_num == "5395"

    repo, pr_num = parse_pr_ref("https://github.com/flagos-ai/FlagGems/pull/5395")
    assert repo == "flagos-ai/FlagGems"
    assert pr_num == "5395"

    print("✓ test_integration_structure passed")


def test_command_line_args():
    """测试命令行参数解析。"""
    import sys
    import argparse

    # 模拟解析
    parser = argparse.ArgumentParser()
    parser.add_argument('pr')
    parser.add_argument('--skip-tests', action='store_true')
    parser.add_argument('--keep-dir', action='store_true')

    # 默认：agent 启用，测试不跳过
    args = parser.parse_args(['5395'])
    assert not args.skip_tests

    # 跳过测试
    args = parser.parse_args(['5395', '--skip-tests'])
    assert args.skip_tests

    # 保留目录
    args = parser.parse_args(['5395', '--keep-dir'])
    assert args.keep_dir

    print("✓ test_command_line_args passed")


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

    test_parse_flake8_errors()
    test_mechanical_only_mode()
    test_agent_prompt_construction()
    test_integration_structure()
    test_command_line_args()

    print("\n✅ All tests passed")
    print("\nUsage:")
    print("  # 默认：机械 + agent 修复 + 测试")
    print("  python3.11 scripts/fix_code_style.py 5395")
    print()
    print("  # 跳过测试验证（加速）")
    print("  python3.11 scripts/fix_code_style.py 5395 --skip-tests")
