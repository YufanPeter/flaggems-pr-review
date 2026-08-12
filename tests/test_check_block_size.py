#!/usr/bin/env python3.11
"""Unit tests for check_block_size.py"""

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
    return any(v['line'] == line and v['value'] == value for v in vs)


# --- tests: should be flagged ---

def test_hardcoded_1024_in_launcher():
    src = '''\
def _my_kernel_launcher(x):
    N = x.numel()
    BLOCK_SIZE = 1024
    grid = (N // BLOCK_SIZE,)
    my_kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert has_violation(src, line=3, value=1024)


def test_hardcoded_512_in_launcher():
    src = '''\
def _launch(x):
    N = x.numel()
    BLOCK_SIZE = 512
    grid = (N // BLOCK_SIZE,)
    kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert has_violation(src, line=3, value=512)


def test_hardcoded_at_module_level():
    src = '''\
import triton

BLOCK_SIZE = 1024

def launcher(x):
    kernel[x.numel() // BLOCK_SIZE](x, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert has_violation(src, line=3, value=1024)


def test_hardcoded_256_in_launcher():
    src = '''\
def launch_op(x):
    n = x.numel()
    BLOCK_SIZE = 256
    my_kernel[(n // BLOCK_SIZE,)](x, n, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert has_violation(src, line=3, value=256)


def test_hardcoded_4096_in_launcher():
    src = '''\
def _dist_p2(x):
    N = x.numel()
    BLOCK_SIZE = 4096
    grid = (triton.cdiv(N, BLOCK_SIZE),)
    dist_kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert has_violation(src, line=3, value=4096)


# --- tests: should NOT be flagged ---

def test_dynamic_next_power_of_2():
    src = '''\
import triton

def launcher(x):
    N = x.numel()
    BLOCK_SIZE = triton.next_power_of_2(N)
    grid = (triton.cdiv(N, BLOCK_SIZE),)
    kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_dynamic_min_next_power_of_2():
    src = '''\
import triton

def launcher(x):
    N = x.numel()
    BLOCK_SIZE = min(1024, triton.next_power_of_2(N))
    grid = (triton.cdiv(N, BLOCK_SIZE),)
    kernel[grid](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_edge_case_block_size_1_allowed():
    # BLOCK_SIZE = 1 is a legitimate guard for empty / tiny data
    src = '''\
def launcher(x):
    N = x.numel()
    BLOCK_SIZE = triton.next_power_of_2(N)
    if BLOCK_SIZE == 0:
        BLOCK_SIZE = 1
    kernel[(triton.cdiv(N, BLOCK_SIZE),)](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_constexpr_inside_triton_kernel_ignored():
    # Declarations inside @triton.jit are compile-time constants, not hardcoding
    src = '''\
import triton
import triton.language as tl

@triton.jit
def my_kernel(x_ptr, n, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offsets = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    tl.store(x_ptr + offsets, tl.load(x_ptr + offsets))

def launcher(x):
    N = x.numel()
    BLOCK_SIZE = min(1024, triton.next_power_of_2(N))
    my_kernel[(triton.cdiv(N, BLOCK_SIZE),)](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_dynamic_variable_assignment():
    # BLOCK_SIZE = n (variable) is fine
    src = '''\
def launcher(x, block):
    BLOCK_SIZE = block
    kernel[(x.numel() // BLOCK_SIZE,)](x, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


def test_multiple_violations_detected():
    src = '''\
MODULE_BLOCK_SIZE = 512

def launcher_a(x):
    N = x.numel()
    BLOCK_SIZE = 1024
    kernel_a[(N // BLOCK_SIZE,)](x, N, BLOCK_SIZE=BLOCK_SIZE)

def launcher_b(x):
    N = x.numel()
    BLOCK_SIZE = 256
    kernel_b[(N // BLOCK_SIZE,)](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    vs = violations_at(src)
    values = {v['value'] for v in vs}
    assert 512 in values
    assert 1024 in values
    assert 256 in values


def test_sqrt_based_dynamic_allowed():
    src = '''\
import math
import triton

def launcher(x):
    N = x.numel()
    BLOCK_SIZE = triton.next_power_of_2(math.ceil(math.sqrt(N)))
    mid = triton.cdiv(N, BLOCK_SIZE)
    kernel[(mid,)](x, N, BLOCK_SIZE=BLOCK_SIZE)
'''
    assert no_violations(src)


# --- run ---

if __name__ == '__main__':
    tests = [
        test_hardcoded_1024_in_launcher,
        test_hardcoded_512_in_launcher,
        test_hardcoded_at_module_level,
        test_hardcoded_256_in_launcher,
        test_hardcoded_4096_in_launcher,
        test_dynamic_next_power_of_2,
        test_dynamic_min_next_power_of_2,
        test_edge_case_block_size_1_allowed,
        test_constexpr_inside_triton_kernel_ignored,
        test_dynamic_variable_assignment,
        test_multiple_violations_detected,
        test_sqrt_based_dynamic_allowed,
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
