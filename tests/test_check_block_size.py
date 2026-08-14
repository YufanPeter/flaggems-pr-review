#!/usr/bin/env python3.11
"""Unit tests for check_block_size.py

检查标准（导师确认）：只有 @triton.jit kernel **函数体内** 的
`tl.arange(0, <整数字面量>)`、且该 kernel 声明了名称含 BLOCK/SIZE/TILE 的
tl.constexpr 参数时，才算违规 —— 字面量绕过了 constexpr 特化机制。

launcher / host 代码 / 模块级的 `BLOCK_SIZE = 1024` 都是合法的，不报。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from check_block_size import find_hardcoded_block_sizes

# --- helpers ---

def violations_at(source: str):
    return find_hardcoded_block_sizes(source, 'test.py')


def no_violations(source: str):
    return violations_at(source) == []


def has_violation(source: str, *, line: int, value: int):
    vs = violations_at(source)
    return any(v['line'] == line and v['literal'] == value for v in vs)


# --- tests: should be flagged (kernel body literal, kernel declares constexpr) ---

def test_hardcoded_arange_1024_in_kernel():
    src = '''\
import triton
import triton.language as tl

@triton.jit
def my_kernel(x_ptr, n, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offsets = pid * BLOCK_SIZE + tl.arange(0, 1024)
    tl.store(x_ptr + offsets, tl.load(x_ptr + offsets))
'''
    assert has_violation(src, line=7, value=1024)


def test_hardcoded_arange_512_in_kernel():
    src = '''\
import triton
import triton.language as tl

@triton.jit
def kernel(x_ptr, n, BLOCK_SIZE: tl.constexpr):
    offsets = tl.arange(0, 512)
    tl.store(x_ptr + offsets, 0.0)
'''
    assert has_violation(src, line=6, value=512)


def test_hardcoded_arange_with_block_m_n_params():
    # constexpr 参数名是 BLOCK_SIZE_M / BLOCK_SIZE_N，仍应识别
    src = '''\
import triton
import triton.language as tl

@triton.jit
def matmul_kernel(a_ptr, b_ptr, BLOCK_SIZE_M: tl.constexpr, BLOCK_SIZE_N: tl.constexpr):
    offs_m = tl.arange(0, 128)
    offs_n = tl.arange(0, BLOCK_SIZE_N)
'''
    assert has_violation(src, line=6, value=128)


def test_multiple_violations_detected():
    # 同一 kernel / 跨 kernel 的多处体内字面量都应被检出
    src = '''\
import triton
import triton.language as tl

@triton.jit
def kernel_a(x_ptr, BLOCK_SIZE: tl.constexpr):
    offsets = tl.arange(0, 1024)
    tl.store(x_ptr + offsets, 0.0)

@triton.jit
def kernel_b(x_ptr, BLOCK_SIZE: tl.constexpr):
    offsets = tl.arange(0, 256)
    tl.store(x_ptr + offsets, 0.0)
'''
    vs = violations_at(src)
    values = {v['literal'] for v in vs}
    assert 1024 in values
    assert 256 in values


# --- tests: should NOT be flagged ---

def test_hardcoded_in_launcher_is_allowed():
    # launcher / host 代码里写死 BLOCK_SIZE 合法 —— 只决定调哪个特化版本
    src = '''\
def _my_kernel_launcher(x):
    N = x.numel()
    BLOCK_SIZE = 1024
    grid = (N // BLOCK_SIZE,)
    my_kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_hardcoded_at_module_level_is_allowed():
    src = '''\
import triton

BLOCK_SIZE = 1024

def launcher(x):
    kernel[x.numel() // BLOCK_SIZE](x, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_kernel_uses_constexpr_param_correctly():
    # 体内正确使用声明的 constexpr 参数，不报
    src = '''\
import triton
import triton.language as tl

@triton.jit
def my_kernel(x_ptr, n, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offsets = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    tl.store(x_ptr + offsets, tl.load(x_ptr + offsets))
'''
    assert no_violations(src)


def test_kernel_without_constexpr_param_ignored():
    # kernel 没声明 BLOCK/SIZE/TILE constexpr 参数时，字面量合理，不报
    src = '''\
import triton
import triton.language as tl

@triton.jit
def my_kernel(x_ptr, n):
    offsets = tl.arange(0, 128)
    tl.store(x_ptr + offsets, 0.0)
'''
    assert no_violations(src)


def test_arange_literal_0_or_1_ignored():
    # 0 / 1 是中性值，与 block size 无关，不报
    src = '''\
import triton
import triton.language as tl

@triton.jit
def my_kernel(x_ptr, BLOCK_SIZE: tl.constexpr):
    a = tl.arange(0, 1)
    b = tl.arange(0, BLOCK_SIZE)
'''
    assert no_violations(src)


def test_dynamic_block_size_in_launcher_allowed():
    src = '''\
import triton

def launcher(x):
    N = x.numel()
    BLOCK_SIZE = triton.next_power_of_2(N)
    grid = (triton.cdiv(N, BLOCK_SIZE),)
    kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


# --- run ---

if __name__ == '__main__':
    tests = [
        test_hardcoded_arange_1024_in_kernel,
        test_hardcoded_arange_512_in_kernel,
        test_hardcoded_arange_with_block_m_n_params,
        test_multiple_violations_detected,
        test_hardcoded_in_launcher_is_allowed,
        test_hardcoded_at_module_level_is_allowed,
        test_kernel_uses_constexpr_param_correctly,
        test_kernel_without_constexpr_param_ignored,
        test_arange_literal_0_or_1_ignored,
        test_dynamic_block_size_in_launcher_allowed,
    ]

    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
            passed += 1
        except AssertionError as e:
            print(f'  FAIL  {t.__name__}: {e}')
            failed += 1

    print(f'\n{passed}/{passed + failed} tests passed')
    sys.exit(0 if failed == 0 else 1)
