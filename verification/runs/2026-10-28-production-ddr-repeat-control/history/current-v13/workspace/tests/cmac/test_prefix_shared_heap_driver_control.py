"""Explicit C++ driver replay guards, not placement or HDL acceptance."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools/cmac'), str(Path(__file__).parent)]
import replay_shared_heap_arithmetic as replay
import test_prefix_shared_heap_limit_control as existing

ExistingArithmeticControls = existing.HeapAttemptLimitControls


class ExplicitDriverControls(unittest.TestCase):
    def test_only_driver_and_output_path_change(self):
        old = ['/test/clang-22', '-std=c++17', '-O0', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=signed-integer-overflow', '-fno-sanitize-recover=all', '/test/input.cc', '-o', '/test/old']
        changed = replay.compile_argv(old, '/test/new')
        self.assertEqual(changed[0], old[0])
        self.assertEqual(changed.pop(1), '--driver-mode=g++')
        changed[-1] = '/test/old'
        self.assertEqual(changed, old)
        self.assertEqual(replay.audit.validate_arithmetic, existing.audit.validate_arithmetic)

    def test_missing_sanitizer_warning_guard_or_wrong_driver_refused(self):
        old = ['/test/clang-22', '-std=c++17', '-Werror', '-fsanitize=signed-integer-overflow',
               '-fno-sanitize-recover=all', '/test/input.cc', '-o', '/test/old']
        for flag in ('-Werror', '-fsanitize=signed-integer-overflow', '-fno-sanitize-recover=all', '-std=c++17'):
            changed = list(old)
            changed.remove(flag)
            with self.assertRaises(AssertionError):
                replay.compile_argv(changed, '/test/new')
        for changed in ([*old, '-o', '/test/other'], ['/test/other', *old[1:]],
                        [old[0], '--driver-mode=g++', *old[1:]]):
            with self.assertRaises(AssertionError):
                replay.compile_argv(changed, '/test/new')


if __name__ == '__main__':
    unittest.main()
