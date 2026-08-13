#!/usr/bin/env python3.11
"""Unit tests for check_skipif.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import check_skipif
from check_skipif import find_skipif_decorators, classify_skipif, check_timeline, resolve_verdict


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
        'file': 'tests/test_add.py',
        'condition': 'flag_gems.vendor_name == "metax"',
        'reason': 'not working',
        'decorator': '@pytest.mark.skipif(flag_gems.vendor_name == "metax", reason="not working")',
    }
    result = classify_skipif(skipif)
    assert result['severity'] == 'critical'
    assert result['category'] == 'vendor_specific'
    assert '跨芯片兼容' in result['message']
    assert result['has_reason'] == True
    assert result['needs_verification'] == True


def test_cuda_skipif_classified_as_critical():
    skipif = {
        'file': 'tests/test_kernel.py',
        'condition': 'not torch.cuda.is_available()',
        'reason': 'CUDA required',
        'decorator': '@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA required")',
    }
    result = classify_skipif(skipif)
    assert result['severity'] == 'critical'
    assert result['category'] == 'cuda_specific'
    assert 'CUDA' in result['message']
    assert result['has_reason'] == True
    assert result['needs_verification'] == True


def test_lazy_skipif_classified_as_warning():
    skipif = {
        'file': 'tests/test_broken.py',
        'condition': 'True',
        'reason': 'TODO: fix later',
        'decorator': '@pytest.mark.skipif(True, reason="TODO: fix later")',
    }
    result = classify_skipif(skipif)
    assert result['severity'] == 'warning'
    assert result['category'] == 'lazy'
    assert '偷懒' in result['message']
    assert result['has_reason'] == True
    assert result['needs_verification'] == True


def test_vague_reason_classified_as_warning():
    skipif = {
        'file': 'tests/test_something.py',
        'condition': 'some_condition',
        'reason': 'not working',
        'decorator': '@pytest.mark.skipif(some_condition, reason="not working")',
    }
    result = classify_skipif(skipif)
    assert result['severity'] == 'warning'
    assert result['category'] == 'vague_reason'
    assert '模糊' in result['message']
    assert result['has_reason'] == True
    assert result['needs_verification'] == True


def test_reasonable_skipif_classified_as_info():
    skipif = {
        'file': 'tests/test_transformer.py',
        'condition': 'TE_OP is None',
        'reason': 'TransformerEngine not installed',
        'decorator': '@pytest.mark.skipif(TE_OP is None, reason="TransformerEngine not installed")',
    }
    result = classify_skipif(skipif)
    assert result['severity'] == 'info'
    assert result['category'] == 'reasonable'
    assert result['has_reason'] == True
    assert result['needs_verification'] == True


def test_version_check_classified_as_info():
    skipif = {
        'file': 'tests/test_version.py',
        'condition': 'torch.__version__ < "2.5"',
        'reason': 'Low Pytorch Version',
        'decorator': '@pytest.mark.skipif(torch.__version__ < "2.5", reason="Low Pytorch Version")',
    }
    result = classify_skipif(skipif)
    assert result['severity'] == 'info'
    assert result['category'] == 'reasonable'
    assert result['has_reason'] == True
    assert result['needs_verification'] == True


# --- Test reason verification metadata ---

def test_issue_reason_has_checklist():
    skipif = {
        'file': 'tests/test_convolution.py',
        'condition': 'flag_gems.vendor_name == "tsingmicro"',
        'reason': 'Issue #4131: not working',
        'decorator': '@pytest.mark.skipif(flag_gems.vendor_name == "tsingmicro", reason="Issue #4131: not working")',
    }
    result = classify_skipif(skipif)
    assert result['issue_ref'] == '4131'
    assert result['operator'] == 'convolution'
    checklist = result['verification_checklist']
    assert any('算子名' in c for c in checklist)
    assert any('时间线' in c for c in checklist)


# --- Test timeline comparison (stub out gh calls) ---

def _stub_created_at(mapping):
    """Return a fake _gh_created_at that maps a command to a timestamp."""
    def fake(cmd):
        # PR view -> 'pr', issue view -> 'issue'
        kind = 'pr' if 'pr' in cmd else 'issue'
        return mapping.get(kind, '')
    return fake


def test_timeline_issue_predates_pr_is_invalid():
    orig = check_skipif._gh_created_at
    check_skipif._gh_created_at = _stub_created_at({
        'issue': '2026-06-17T06:04:29Z',
        'pr': '2026-08-06T08:18:34Z',
    })
    try:
        tl = check_timeline('flagos-ai/FlagGems', '5290', '4131')
    finally:
        check_skipif._gh_created_at = orig
    assert tl['issue_predates_pr'] is True
    assert tl['verdict'] == 'reason_invalid'


def test_timeline_issue_after_pr_is_ok():
    orig = check_skipif._gh_created_at
    check_skipif._gh_created_at = _stub_created_at({
        'issue': '2026-09-01T00:00:00Z',
        'pr': '2026-08-06T08:18:34Z',
    })
    try:
        tl = check_timeline('flagos-ai/FlagGems', '9999', '9998')
    finally:
        check_skipif._gh_created_at = orig
    assert tl['issue_predates_pr'] is False
    assert tl['verdict'] == 'timeline_ok'


def test_timeline_missing_timestamp_is_unknown():
    orig = check_skipif._gh_created_at
    check_skipif._gh_created_at = _stub_created_at({'issue': '', 'pr': ''})
    try:
        tl = check_timeline('flagos-ai/FlagGems', '1', '2')
    finally:
        check_skipif._gh_created_at = orig
    assert tl['verdict'] == 'unknown'


# --- Test verdict routing ---

def test_verdict_no_reason_is_confirmed_error():
    v = {'has_reason': False}
    out = resolve_verdict(v)
    assert out['auto_verdict'] == 'confirmed_error'
    assert out['needs_agent_verification'] is False


def test_verdict_timeline_invalid_is_confirmed_error():
    v = {'has_reason': True, 'timeline': {'verdict': 'reason_invalid'}}
    out = resolve_verdict(v)
    assert out['auto_verdict'] == 'confirmed_error'
    assert out['needs_agent_verification'] is False


def test_verdict_timeline_ok_needs_agent():
    v = {'has_reason': True, 'timeline': {'verdict': 'timeline_ok'}}
    out = resolve_verdict(v)
    assert out['auto_verdict'] == 'pending'
    assert out['needs_agent_verification'] is True


def test_verdict_timeline_unknown_needs_agent():
    v = {'has_reason': True, 'timeline': {'verdict': 'unknown'}}
    out = resolve_verdict(v)
    assert out['needs_agent_verification'] is True


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
        test_issue_reason_has_checklist,
        test_timeline_issue_predates_pr_is_invalid,
        test_timeline_issue_after_pr_is_ok,
        test_timeline_missing_timestamp_is_unknown,
        test_verdict_no_reason_is_confirmed_error,
        test_verdict_timeline_invalid_is_confirmed_error,
        test_verdict_timeline_ok_needs_agent,
        test_verdict_timeline_unknown_needs_agent,
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
