#!/usr/bin/env python3.11
"""
测试改进后的 check_is_cuda：路径过滤 + 注释/字符串处理
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from check_is_cuda import should_check_file, remove_comments_and_strings, check_is_cuda_abuse


class TestShouldCheckFile(unittest.TestCase):
    """测试文件路径过滤"""

    def test_check_ops_files(self):
        """算子实现文件应该检查"""
        files = [
            'flag_gems/ops/special_bessel_j1.py',
            'src/flag_gems/ops/special_bessel_j1.py',
            'flag_gems/fused/cross_entropy.py',
            'src/flag_gems/fused/attention.py',
        ]
        for f in files:
            self.assertTrue(should_check_file(f), f"应该检查: {f}")

    def test_skip_test_files(self):
        """测试文件应该跳过"""
        files = [
            'tests/test_special_bessel_j1.py',
            'test/test_ops.py',
            'flag_gems/test_utils.py',
            'test_foo.py',
        ]
        for f in files:
            self.assertFalse(should_check_file(f), f"应该跳过: {f}")

    def test_skip_benchmark_files(self):
        """benchmark 文件应该跳过"""
        files = [
            'benchmark/test_special_bessel_j1.py',
            'benchmarks/perf_test.py',
        ]
        for f in files:
            self.assertFalse(should_check_file(f), f"应该跳过: {f}")

    def test_skip_config_and_docs(self):
        """配置和文档应该跳过"""
        files = [
            'conf/operators.yaml',
            'docs/setup.py',
            'scripts/helper.py',
            'tools/codegen.py',
        ]
        for f in files:
            self.assertFalse(should_check_file(f), f"应该跳过: {f}")

    def test_skip_non_python(self):
        """非 Python 文件应该跳过"""
        files = [
            'README.md',
            'config.yaml',
            'setup.sh',
        ]
        for f in files:
            self.assertFalse(should_check_file(f), f"应该跳过: {f}")


class TestRemoveCommentsAndStrings(unittest.TestCase):
    """测试注释和字符串移除"""

    def test_remove_line_end_comment(self):
        """移除行尾注释"""
        line = '    if x.is_cuda:  # TODO: fix this'
        result = remove_comments_and_strings(line)
        self.assertIn('is_cuda', result)
        self.assertNotIn('TODO', result)
        self.assertNotIn('fix', result)

    def test_remove_single_quote_string(self):
        """移除单引号字符串"""
        line = "    error = 'is_cuda not supported'"
        result = remove_comments_and_strings(line)
        self.assertNotIn('is_cuda', result)
        self.assertIn('error', result)

    def test_remove_double_quote_string(self):
        """移除双引号字符串"""
        line = '    msg = "torch.cuda is deprecated"'
        result = remove_comments_and_strings(line)
        self.assertNotIn('torch.cuda', result)
        self.assertIn('msg', result)

    def test_preserve_code(self):
        """保留实际代码"""
        line = '    if x.is_cuda:'
        result = remove_comments_and_strings(line)
        self.assertIn('is_cuda', result)

    def test_mixed_code_and_comment(self):
        """混合代码和注释"""
        line = '    device = torch.cuda.current_device()  # get device'
        result = remove_comments_and_strings(line)
        self.assertIn('torch.cuda', result)
        self.assertNotIn('get device', result)

    def test_comment_only_line(self):
        """纯注释行"""
        line = '    # This is about is_cuda'
        result = remove_comments_and_strings(line)
        self.assertNotIn('is_cuda', result)
        # 应该只剩空白
        self.assertEqual(result.strip(), '')


class TestCheckIsCudaAbuseImproved(unittest.TestCase):
    """测试改进后的 is_cuda 检测"""

    def test_skip_comment_in_ops_file(self):
        """算子文件中的注释应该被跳过"""
        files = {
            'flag_gems/ops/test.py': [
                (10, '    # TODO: check is_cuda here'),
                (11, '    if x.is_valid:  # is_cuda not used'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 0, "注释中的 is_cuda 不应该报错")

    def test_detect_real_is_cuda_in_ops(self):
        """算子文件中的真实 is_cuda 应该检测到"""
        files = {
            'flag_gems/ops/test.py': [
                (20, '    if x.is_cuda:'),
                (21, '        return True'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]['line'], 20)

    def test_skip_string_literal(self):
        """字符串字面量中的 is_cuda 应该被跳过"""
        files = {
            'flag_gems/ops/test.py': [
                (10, '    error_msg = "is_cuda check failed"'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 0, "字符串中的 is_cuda 不应该报错")

    def test_skip_test_file_entirely(self):
        """测试文件应该完全跳过，即使有 is_cuda"""
        files = {
            'tests/test_ops.py': [
                (10, '    if x.is_cuda:'),
                (11, '        device = torch.cuda.current_device()'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 0, "测试文件应该被跳过")

    def test_skip_benchmark_file(self):
        """benchmark 文件应该跳过"""
        files = {
            'benchmark/test_perf.py': [
                (10, '    if torch.cuda.is_available():'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 0, "benchmark 文件应该被跳过")

    def test_detect_in_fused_ops(self):
        """fused 算子中的 is_cuda 应该检测到"""
        files = {
            'flag_gems/fused/attention.py': [
                (30, '    if x.is_cuda:'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        self.assertEqual(len(violations), 1)

    def test_mixed_violations_with_comments(self):
        """混合真实违规和注释"""
        files = {
            'flag_gems/ops/test.py': [
                (10, '    # This is a comment about is_cuda'),
                (20, '    if x.is_cuda:  # real violation'),
                (30, '    msg = "is_cuda deprecated"'),
                (40, '    device = torch.cuda.current_device()'),
            ]
        }
        violations = check_is_cuda_abuse(files)
        # 应该只检测到 2 处真实违规（行 20 和 40）
        self.assertEqual(len(violations), 2)
        violation_lines = [v['line'] for v in violations]
        self.assertIn(20, violation_lines)
        self.assertIn(40, violation_lines)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestShouldCheckFile))
    suite.addTests(loader.loadTestsFromTestCase(TestRemoveCommentsAndStrings))
    suite.addTests(loader.loadTestsFromTestCase(TestCheckIsCudaAbuseImproved))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(run_tests())
