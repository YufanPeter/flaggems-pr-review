#!/usr/bin/env python3.11
"""Unit tests for check_skipif.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
from check_skipif import find_skipif_decorators, classify_skipif


# --- Test skipif detection ---

def test_vendor_specific_skipif_detected():
    src = '''\
import pytest
import flag_gems

@pytest.mark.skipif(flag_gems.vendor_name == "metax", reason="not working")
def test_add():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 1
    assert skipifs[0]['line'] == 4
    assert 'vendor_name' in skipifs[0]['condition']
    assert skipifs[0]['reason'] == 'not working'


def test_cuda_specific_skipif_detected():
    src = '''\
import pytest
import torch

@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")
def test_kernel():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 1
    assert 'cuda' in skipifs[0]['condition'].lower()


def test_lazy_skipif_detected():
    src = '''\
import pytest

@pytest.mark.skipif(True, reason="TODO: fix later")
def test_broken():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 1
    assert 'True' in skipifs[0]['condition']
    assert 'TODO' in skipifs[0]['reason']


def test_reasonable_skipif_detected():
    src = '''\
import pytest

TE_OP = None

@pytest.mark.skipif(TE_OP is None, reason="TransformerEngine not installed")
def test_transformer():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 1
    assert 'None' in skipifs[0]['condition']


def test_multiline_skipif_detected():
    src = '''\
import pytest

@pytest.mark.skipif(
    flag_gems.vendor_name == "metax",
    reason="Issue #2849: Not working"
)
def test_something():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 1
    assert skipifs[0]['line'] == 3
    assert 'vendor_name' in skipifs[0]['condition']


def test_multiple_skipif_detected():
    src = '''\
import pytest

@pytest.mark.skipif(flag_gems.vendor_name == "metax", reason="Issue #2849")
@pytest.mark.skipif(flag_gems.vendor_name == "hygon", reason="Issue #2849")
def test_multi():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 2
    assert skipifs[0]['line'] == 3
    assert skipifs[1]['line'] == 4


# --- Test classification ---

def test_vendor_skipif_classified_as_critical():
    skipif = {
        'condition': 'flag_gems.vendor_name == "metax"',
        'reason': 'not working',
        'decorator': '@pytest.mark.skipif(flag_gems.vendor_name == "metax", reason="not working")',
    }
    severity, category, message, suggestion = classify_skipif(skipif)
    assert severity == 'critical'
    assert category == 'vendor_specific'
    assert '跨芯片兼容' in message


def test_cuda_skipif_classified_as_critical():
    skipif = {
        'condition': 'not torch.cuda.is_available()',
        'reason': 'CUDA required',
        'decorator': '@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")',
    }
    severity, category, message, suggestion = classify_skipif(skipif)
    assert severity == 'critical'
    assert category == 'cuda_specific'
    assert 'CUDA' in message


def test_lazy_skipif_classified_as_warning():
    skipif = {
        'condition': 'True',
        'reason': 'TODO: fix later',
        'decorator': '@pytest.mark.skipif(True, reason="TODO: fix later")',
    }
    severity, category, message, suggestion = classify_skipif(skipif)
    assert severity == 'warning'
    assert category == 'lazy'
    assert '偷懒' in message


def test_vague_reason_classified_as_warning():
    skipif = {
        'condition': 'some_condition',
        'reason': 'not working',
        'decorator': '@pytest.mark.skipif(some_condition, reason="not working")',
    }
    severity, category, message, suggestion = classify_skipif(skipif)
    assert severity == 'warning'
    assert category == 'vague_reason'
    assert '模糊' in message


def test_reasonable_skipif_classified_as_info():
    skipif = {
        'condition': 'TE_OP is None',
        'reason': 'TransformerEngine not installed',
        'decorator': '@pytest.mark.skipif(TE_OP is None, reason="TransformerEngine not installed")',
    }
    severity, category, message, suggestion = classify_skipif(skipif)
    assert severity == 'info'
    assert category == 'reasonable'


def test_version_check_classified_as_info():
    skipif = {
        'condition': 'torch.__version__ < "2.5"',
        'reason': 'Low Pytorch Version',
        'decorator': '@pytest.mark.skipif(torch.__version__ < "2.5", reason="Low Pytorch Version")',
    }
    severity, category, message, suggestion = classify_skipif(skipif)
    assert severity == 'info'
    assert category == 'reasonable'


# --- Edge cases ---

def test_no_skipif_returns_empty():
    src = '''\
import pytest

def test_normal():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert skipifs == []


def test_skipif_with_no_reason():
    # Some skipif might not have reason (though pytest requires it)
    src = '''\
import pytest

@pytest.mark.skipif(True)
def test_no_reason():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert len(skipifs) == 1
    assert skipifs[0]['reason'] == ''


def test_other_pytest_marks_ignored():
    src = '''\
import pytest

@pytest.mark.parametrize("x", [1, 2, 3])
@pytest.mark.slow
def test_with_marks():
    pass
'''
    skipifs = find_skipif_decorators(src, 'test.py')
    assert skipifs == []


# --- Run ---

if __name__ == '__main__':
    tests = [
        test_vendor_specific_skipif_detected,
        test_cuda_specific_skipif_detected,
        test_lazy_skipif_detected,
        test_reasonable_skipif_detected,
        test_multiline_skipif_detected,
        test_multiple_skipif_detected,
        test_vendor_skipif_classified_as_critical,
        test_cuda_skipif_classified_as_critical,
        test_lazy_skipif_classified_as_warning,
        test_vague_reason_classified_as_warning,
        test_reasonable_skipif_classified_as_info,
        test_version_check_classified_as_info,
        test_no_skipif_returns_empty,
        test_skipif_with_no_reason,
        test_other_pytest_marks_ignored,
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
