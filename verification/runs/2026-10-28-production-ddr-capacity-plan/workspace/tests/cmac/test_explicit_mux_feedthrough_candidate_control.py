"""Preserve all original candidate gates plus the explicit test-bench boundary."""
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools'), str(Path(__file__).parent)]
import build_explicit_mux_feedthrough_candidate as explicit
from test_mux_feedthrough_candidate_control import MuxCandidateControls


class ExplicitMuxBenchControls(unittest.TestCase):
    def test_same_build_procedure_and_all_native_source_guards(self):
        text = explicit.MAIN_SOURCE
        for old, new in reversed(explicit.REPLACEMENTS):
            self.assertEqual(text.count(new), 1)
            text = text.replace(new, old)
        self.assertEqual(text, inspect.getsource(explicit.original.main))
        for name in ('verify_metadata', 'packed_probe', 'candidate_source', 'verify_source_transition'):
            self.assertIs(explicit.NAMESPACE[name], getattr(explicit.original, name))
        self.assertEqual(explicit.NAMESPACE['MODELS'], explicit.original.MODELS)

    def test_original_exhaustive_expectations_and_negative_byte_identical(self):
        old = explicit.original.BENCH.read_text()
        new = explicit.BENCH.read_text()
        marker = '\n  initial begin\n'
        self.assertEqual(old[old.index(marker):], new[new.index(marker):])
        start, end = '  function automatic four_state', '\n  for (genvar i'
        self.assertEqual(old[old.index(start):old.index(end)], new[new.index(start):new.index(end)])
        first, last = '  for (genvar i', '  for (genvar j'
        self.assertEqual(old[old.index(first):old.index(last)],
                         new[new.index(first):new.index('  MUXF7 wrapper_left_floating')])
        self.assertNotIn('genvar j', new)
        for suffix, value, index in (('floating', "1'bz", 0), ('ground', "1'b0", 1)):
            for side in ('left', 'right'):
                expected = ('MUXF7 wrapper_' + side + '_' + suffix + ' (.I0(buffered_' + side + '), .I1(' +
                            value + "), .S(1'b0), .O(wrapped_" + side + '[' + str(index) + ']));')
                self.assertIn(expected, new)
            self.assertIn('MUXF8 candidate_root_' + suffix, new)


if __name__ == '__main__':
    unittest.main()
