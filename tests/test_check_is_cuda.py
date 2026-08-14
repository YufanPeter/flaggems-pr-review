#!/usr/bin/env python3.11
"""
check_is_cuda.py 的单元测试

不依赖真实 GitHub PR，使用 mock diff 数据测试核心逻辑。
"""

import unittest
import sys
from pathlib import Path

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from check_is_cuda import parse_diff_files, check_is_cuda_abuse


class TestParseDiffFiles(unittest.TestCase):
    """测试 diff 解析逻辑"""

    def test_parse_simple_diff(self):
        """测试解析简单的 diff"""
        diff = """diff --git a/src/flag_gems/ops/example.py b/src/flag_gems/ops/example.py
index 1234567..abcdefg 100644
--- a/src/flag_gems/ops/example.py
+++ b/src/flag_gems/ops/example.py
@@ -10,3 +10,5 @@ def foo():
     pass
+
+def bar():
+    if x.is_cuda:
+        return True
"""
        files = parse_diff_files(diff)
        self.assertIn('src/flag_gems/ops/example.py', files)
        lines = files['src/flag_gems/ops/example.py']
        # 应该有 4 行新增：空行、def bar()、if x.is_cuda、return True
        self.assertEqual(len(lines), 4)
        # 检查 is_cuda 那行
        is_cuda_line = [l for l in lines if 'is_cuda' in l[1]]
        self.assertEqual(len(is_cuda_line), 1)

    def test_skip_deleted_lines(self):
        """测试跳过删除的行"""
        diff = """diff --git a/test.py b/test.py
--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 def foo():
-    old_line
+    new_line
"""
        files = parse_diff_files(diff)
        lines = files['test.py']
        # 只应该有 1 行新增
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0][1].strip(), 'new_line')


class TestCheckIsCudaAbuse(unittest.TestCase):
    """测试 is_cuda 滥用检测逻辑"""

    def test_detect_is_cuda_property(self):
        """测试检测 .is_cuda 属性"""
        files = {
            'src/flag_gems/ops/example.py': [
                (42, '    if x.is_cuda:'),
                (43, '        return True')
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]['file'], 'src/flag_gems/ops/example.py')
        self.assertEqual(violations[0]['line'], 42)
        self.assertIn('is_cuda', violations[0]['matched'])

    def test_detect_torch_cuda_module(self):
        """测试检测 torch.cuda 模块使用"""
        files = {
            'src/flag_gems/ops/example.py': [
                (10, 'import torch.cuda'),
                (20, 'device = torch.cuda.current_device()'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        # 应该检测到 2 处
        self.assertEqual(len(violations), 2)

    def test_detect_hardcoded_cuda_string(self):
        """测试检测硬编码 'cuda' 字符串"""
        files = {
            'src/flag_gems/ops/example.py': [
                (30, '    if device.type == "cuda":'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 1)
        self.assertIn('硬编码', violations[0]['description'])

    def test_skip_comments(self):
        """测试跳过注释行"""
        files = {
            'src/flag_gems/ops/example.py': [
                (10, '# This is a comment about is_cuda'),
                (11, '    # Another comment with torch.cuda'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        # 注释应该被跳过
        self.assertEqual(len(violations), 0)

    def test_skip_non_python_files(self):
        """测试跳过非 Python 文件"""
        files = {
            'README.md': [
                (1, 'Some text about is_cuda'),
            ],
            'config.yaml': [
                (5, 'device: cuda'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        # 非 .py 文件应该被跳过
        self.assertEqual(len(violations), 0)

    def test_no_violations(self):
        """测试正确的代码（无违规）"""
        files = {
            'src/flag_gems/ops/example.py': [
                (10, 'from flag_gems.runtime import torch_device_fn'),
                (20, '    if x.device.type == runtime.device.name:'),
                (30, '        device_fn = torch_device_fn()'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 0)

    def test_allow_torch_cudnn(self):
        """测试允许 torch.cudnn（不是 torch.cuda）"""
        files = {
            'src/flag_gems/ops/example.py': [
                (10, 'import torch.cudnn as cudnn'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        # torch.cudnn 应该被允许
        self.assertEqual(len(violations), 0)


class TestEdgeCases(unittest.TestCase):
    """测试边界情况"""

    def test_empty_diff(self):
        """测试空 diff"""
        files = parse_diff_files("")
        self.assertEqual(len(files), 0)

    def test_empty_files(self):
        """测试空文件列表"""
        violations = check_is_cuda_abuse({})
        self.assertEqual(len(violations), 0)

    def test_multiple_violations_same_line(self):
        """测试同一行有多个违规"""
        files = {
            'src/flag_gems/ops/example.py': [
                (10, '    if x.is_cuda and torch.cuda.is_available():'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        # 应该检测到至少 2 处违规（is_cuda 和 torch.cuda）
        self.assertGreaterEqual(len(violations), 2)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestParseDiffFiles))
    suite.addTests(loader.loadTestsFromTestCase(TestCheckIsCudaAbuse))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
