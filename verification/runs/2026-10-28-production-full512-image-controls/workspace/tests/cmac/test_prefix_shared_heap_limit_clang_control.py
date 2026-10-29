"""Compiler-selection-only continuation guards, not placement evidence."""
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools/cmac'), str(Path(__file__).parent)]
import continue_shared_heap_attempt_limit as continuation
import test_prefix_shared_heap_limit_control as existing

ExistingArithmeticControls = existing.HeapAttemptLimitControls


class CompilerSelectionControls(unittest.TestCase):
    def test_exact_reversible_compiler_and_binding_changes_only(self):
        text = continuation.MAIN_SOURCE
        for old, new in reversed(continuation.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, inspect.getsource(continuation.previous.main))
        self.assertEqual(continuation.NAMESPACE['validate_arithmetic'], continuation.previous.validate_arithmetic)
        self.assertEqual(continuation.NAMESPACE['fixture'], continuation.previous.fixture)

    def test_original_link_failure_preserved_and_runtime_bound(self):
        manifest = continuation.admit_failure()
        self.assertIn(str(continuation.AUDIT_FAILED), manifest)
        self.assertIn(str(Path(continuation.previous.__file__).resolve()), manifest)
        for name in ('libclang_rt.ubsan_standalone-x86_64.a', 'libclang_rt.ubsan_standalone_cxx-x86_64.a'):
            self.assertIn(str((continuation.RUNTIME / name).resolve(strict=True)), manifest)


if __name__ == '__main__':
    unittest.main()
