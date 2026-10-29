"""Host HeAP integer-limit audit guards, not FPGA/HDL tests."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools/cmac')]
import audit_shared_heap_attempt_limit as audit


class HeapAttemptLimitControls(unittest.TestCase):
    def test_only_exact_source_expression(self):
        source = audit.SOURCE.read_text()
        self.assertEqual(audit.expression(source), audit.EXPRESSION)
        for changed in (source.replace(audit.EXPRESSION, '10000'), source + '\n' + source,
                        source.replace('"placerHeap/cellPlacementTimeout", 8', '"placerHeap/cellPlacementTimeout", 1')):
            with self.assertRaises(AssertionError):
                audit.expression(changed)

    def test_fixture_executes_unmodified_expression_not_widened_repair(self):
        text = audit.fixture(audit.SOURCE.read_text())
        self.assertEqual(text.count(audit.EXPRESSION), 1)
        self.assertIn('std::numeric_limits<int>::digits == 31', text)
        self.assertNotIn('int64_t', text)

    def test_in_range_controls_require_exact_success(self):
        for n in (7, 46340):
            text = f'count={n} timeout={max(10000,n*n//8)}\n'
            audit.validate_arithmetic(text, 0, n)
            for bad, code in ((text, 1), (text + 'other output\n', 0), (text.replace('timeout=', 'changed='), 0)):
                with self.assertRaises(AssertionError):
                    audit.validate_arithmetic(bad, code, n)

    def test_ubsan_negative_requires_actual_count_and_finite_overflow(self):
        for n in (46341, 523410):
            text = f"fixture.cc: runtime error: signed integer overflow: {n} * {n} cannot be represented in type 'int'\n"
            audit.validate_arithmetic(text, 1, n)
            for bad, code in ((text, 0), (text.replace(str(n), '1'), 1), ('timeout\n', 1),
                              (text + 'timeout=10000\n', 1)):
                with self.assertRaises(AssertionError):
                    audit.validate_arithmetic(bad, code, n)


if __name__ == '__main__':
    unittest.main()
