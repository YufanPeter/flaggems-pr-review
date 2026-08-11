#!/usr/bin/env python3.11
"""
手动测试 check_is_cuda.py 的检测能力

创建 mock diff 来验证各种违规场景
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from check_is_cuda import parse_diff_files, check_is_cuda_abuse


def test_case_1_is_cuda_property():
    """测试案例 1：使用 .is_cuda 属性"""
    print("=" * 60)
    print("测试案例 1：检测 .is_cuda 属性")
    print("=" * 60)

    diff = """diff --git a/src/ops/special_bessel_j1.py b/src/ops/special_bessel_j1.py
+++ b/src/ops/special_bessel_j1.py
@@ -10,3 +10,5 @@ def special_bessel_j1(x):
+    if x.is_cuda:
+        return cuda_kernel(x)
+    else:
+        return cpu_fallback(x)
"""

    files = parse_diff_files(diff)
    violations = check_is_cuda_abuse(files)

    print(f"\n发现 {len(violations)} 处违规：\n")
    for v in violations:
        print(f"📁 {v['file']}:{v['line']}")
        print(f"   内容: {v['content']}")
        print(f"   问题: {v['description']}")
        print(f"   建议: {v['suggestion']}\n")


def test_case_2_torch_cuda_module():
    """测试案例 2：使用 torch.cuda 模块"""
    print("=" * 60)
    print("测试案例 2：检测 torch.cuda 模块使用")
    print("=" * 60)

    diff = """diff --git a/src/ops/cuda_helper.py b/src/ops/cuda_helper.py
+++ b/src/ops/cuda_helper.py
@@ -5,2 +5,4 @@ import torch
+
+def get_device():
+    return torch.cuda.current_device()
"""

    files = parse_diff_files(diff)
    violations = check_is_cuda_abuse(files)

    print(f"\n发现 {len(violations)} 处违规：\n")
    for v in violations:
        print(f"📁 {v['file']}:{v['line']}")
        print(f"   内容: {v['content']}")
        print(f"   问题: {v['description']}")
        print(f"   建议: {v['suggestion']}\n")


def test_case_3_hardcoded_cuda_string():
    """测试案例 3：硬编码 "cuda" 字符串"""
    print("=" * 60)
    print("测试案例 3：检测硬编码 'cuda' 字符串")
    print("=" * 60)

    diff = """diff --git a/src/ops/device_check.py b/src/ops/device_check.py
+++ b/src/ops/device_check.py
@@ -10,2 +10,3 @@ def check_device(x):
+    if x.device.type == "cuda":
+        print("Running on CUDA")
"""

    files = parse_diff_files(diff)
    violations = check_is_cuda_abuse(files)

    print(f"\n发现 {len(violations)} 处违规：\n")
    for v in violations:
        print(f"📁 {v['file']}:{v['line']}")
        print(f"   内容: {v['content']}")
        print(f"   问题: {v['description']}")
        print(f"   建议: {v['suggestion']}\n")


def test_case_4_correct_usage():
    """测试案例 4：正确的用法（不应该报错）"""
    print("=" * 60)
    print("测试案例 4：正确的用法（应该通过）")
    print("=" * 60)

    diff = """diff --git a/src/ops/correct_impl.py b/src/ops/correct_impl.py
+++ b/src/ops/correct_impl.py
@@ -5,3 +5,6 @@ from flag_gems.runtime import torch_device_fn, device
+
+def check_device(x):
+    if x.device.type == runtime.device.name:
+        return torch_device_fn().current_device()
"""

    files = parse_diff_files(diff)
    violations = check_is_cuda_abuse(files)

    if violations:
        print(f"\n❌ 误报！发现 {len(violations)} 处违规：\n")
        for v in violations:
            print(f"📁 {v['file']}:{v['line']}")
            print(f"   内容: {v['content']}")
    else:
        print("\n✅ 正确！未检测到违规\n")


def test_case_5_mixed_violations():
    """测试案例 5：混合多种违规"""
    print("=" * 60)
    print("测试案例 5：混合多种违规")
    print("=" * 60)

    diff = """diff --git a/src/ops/bad_impl.py b/src/ops/bad_impl.py
+++ b/src/ops/bad_impl.py
@@ -10,5 +10,8 @@ import torch
+
+def bad_function(x):
+    if x.is_cuda and torch.cuda.is_available():
+        device = torch.cuda.current_device()
+        if x.device.type == "cuda":
+            return True
"""

    files = parse_diff_files(diff)
    violations = check_is_cuda_abuse(files)

    print(f"\n发现 {len(violations)} 处违规：\n")
    for v in violations:
        print(f"📁 {v['file']}:{v['line']}")
        print(f"   内容: {v['content']}")
        print(f"   匹配: {v['matched']}")
        print(f"   问题: {v['description']}")
        print(f"   建议: {v['suggestion']}\n")


if __name__ == '__main__':
    test_case_1_is_cuda_property()
    test_case_2_torch_cuda_module()
    test_case_3_hardcoded_cuda_string()
    test_case_4_correct_usage()
    test_case_5_mixed_violations()

    print("=" * 60)
    print("✅ 所有手动测试完成")
    print("=" * 60)
