#!/usr/bin/env python3.11
"""
真实场景测试：模拟一个完整 PR 的 diff
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from check_is_cuda import parse_diff_files, check_is_cuda_abuse


def test_realistic_pr():
    """模拟真实 PR：混合了算子实现、测试、benchmark"""

    diff = """diff --git a/flag_gems/ops/special_bessel_j1.py b/flag_gems/ops/special_bessel_j1.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/flag_gems/ops/special_bessel_j1.py
@@ -0,0 +1,15 @@
+import torch
+from flag_gems.runtime import torch_device_fn
+
+def special_bessel_j1(x):
+    # This function computes bessel j1
+    # TODO: optimize for is_cuda devices
+    if x.is_cuda:
+        return cuda_kernel(x)
+    return cpu_fallback(x)
+
diff --git a/tests/test_special_bessel_j1.py b/tests/test_special_bessel_j1.py
new file mode 100644
index 0000000..abcdefg
--- /dev/null
+++ b/tests/test_special_bessel_j1.py
@@ -0,0 +1,10 @@
+import torch
+
+def test_special_bessel_j1():
+    x = torch.randn(10)
+    if x.is_cuda:
+        device = torch.cuda.current_device()
+        print(f"Testing on CUDA device {device}")
+
diff --git a/benchmark/test_special_bessel_j1.py b/benchmark/test_special_bessel_j1.py
new file mode 100644
index 0000000..xyz1234
--- /dev/null
+++ b/benchmark/test_special_bessel_j1.py
@@ -0,0 +1,8 @@
+import torch
+
+def benchmark():
+    if torch.cuda.is_available():
+        device = "cuda"
+    else:
+        device = "cpu"
"""

    print("=" * 70)
    print("真实场景测试：一个 PR 包含算子实现 + 测试 + benchmark")
    print("=" * 70)
    print()

    files = parse_diff_files(diff)
    violations = check_is_cuda_abuse(files)

    print(f"📋 解析的文件：")
    for file_path in files.keys():
        print(f"   - {file_path}")
    print()

    if violations:
        print(f"❌ 发现 {len(violations)} 处违规（只在算子实现中）：\n")
        for v in violations:
            print(f"📁 {v['file']}:{v['line']}")
            print(f"   内容: {v['content']}")
            print(f"   问题: {v['description']}")
            print(f"   建议: {v['suggestion']}")
            print()
    else:
        print("✅ 未发现违规")

    print("=" * 70)
    print("预期结果：")
    print("  ✅ flag_gems/ops/special_bessel_j1.py 第 7 行应该被检测到")
    print("  ✅ 注释中的 'is_cuda' 应该被忽略（第 6 行）")
    print("  ✅ tests/test_special_bessel_j1.py 应该完全跳过")
    print("  ✅ benchmark/test_special_bessel_j1.py 应该完全跳过")
    print("=" * 70)
    print()

    # 验证结果
    assert len(violations) == 1, f"应该只有 1 处违规，实际：{len(violations)}"
    assert violations[0]['line'] == 7, f"违规应该在第 7 行，实际：{violations[0]['line']}"
    assert 'flag_gems/ops' in violations[0]['file'], "违规应该在 ops 文件中"

    print("✅ 所有断言通过！检测引擎工作正常。")


if __name__ == '__main__':
    test_realistic_pr()
