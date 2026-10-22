"""HeAP limit source/host arithmetic controls, not native or HDL acceptance."""
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/openxc7'), str(ROOT / 'tools/cmac')]
import heap_attempt_limit_candidate as candidate
from build_dsp_constant_candidate import link_argv


class HeapLimitCandidateControls(unittest.TestCase):
    def test_only_one_reversible_expression_changes(self):
        original = candidate.SOURCE.read_text()
        modified = candidate.candidate_source(original)
        candidate.verify_source_transition(original, modified)
        self.assertEqual(modified.replace(candidate.EXPRESSION, candidate.audit.EXPRESSION), original)
        for changed in (original, modified + '\n', modified.replace('ctx->rng(', 'other_rng('),
                        modified.replace('!ctx->isBelLocationValid(sz)', 'false')):
            with self.assertRaises(AssertionError):
                candidate.verify_source_transition(original, changed)

    def test_source_anchors_cannot_be_changed_or_duplicated(self):
        original = candidate.SOURCE.read_text()
        for bad in (original.replace(candidate.audit.EXPRESSION, '10000'), original + original,
                    original.replace('"placerHeap/cellPlacementTimeout", 8', '"placerHeap/cellPlacementTimeout", 0')):
            with self.assertRaises(AssertionError):
                candidate.candidate_source(bad)

    def test_finite_limit_reserves_counter_rejection_boundary(self):
        for n in (46341, 523410, 538118, 2**31-1, 2**64-1):
            actual = candidate.limit(n, 8)
            self.assertLessEqual(actual + 1, 2**31 - 1)
            self.assertEqual(actual, min(2**31 - 2, max(10000, n*n//8)))
        self.assertEqual(candidate.limit(523410, 8), 2147483646)
        self.assertEqual(candidate.limit(46340, 8), 268424450)

    def test_count_clamp_matches_saturated_mathematical_contract(self):
        rng = random.Random(3588)
        for _ in range(5000):
            count, divisor = rng.getrandbits(64), rng.randint(1, 2**31 - 1)
            clamped = min(count, 2**31 - 1)
            result = min(2**31 - 2, max(10000, clamped*clamped//divisor))
            self.assertEqual(result, candidate.limit(count, divisor))

    def test_nonpositive_divisor_semantics_and_domains_preserved(self):
        for divisor in (0, -1, -(2**31)):
            self.assertEqual(candidate.limit(523410, divisor), 0)
        for count, divisor in ((-1, 8), (2**64, 8), (1, 2**31), (True, 8), (1, False)):
            with self.assertRaises(AssertionError):
                candidate.limit(count, divisor)

    def test_actual_recipe_preserves_original_flags_and_quote_headers(self):
        flags, recipe = (candidate.CMAKE / n for n in ('flags.make', 'build.make'))
        argv = candidate.compile_argv(Path('/test/placer_heap.cc'), Path('/test/placer_heap.cc.o'),
                                      flags.read_text(), recipe.read_text())
        self.assertEqual(argv[0], '/usr/bin/c++')
        self.assertEqual(argv[argv.index('-iquote')+1], str(candidate.SOURCE.parent))
        self.assertEqual(argv[argv.index('-c')+1], '/test/placer_heap.cc')
        self.assertEqual(argv[argv.index('-MF')+1], '/test/placer_heap.cc.o.d')
        self.assertIn('-O3', argv)
        for bad in (recipe.read_text() + recipe.read_text(), recipe.read_text().replace(str(candidate.SOURCE), '/wrong.cc')):
            with self.assertRaises(AssertionError):
                candidate.compile_argv('/test/source', '/test/object', flags.read_text(), bad)

    def test_link_changes_only_one_object_and_owned_output(self):
        old = ['/usr/bin/c++', '-O3', '-Wl,--dependency-file=/old/executable.d', str(candidate.OBJECT),
               '/other/object.o', '-o', '/old/executable', '/other/library.a']
        result = link_argv(old, '/new/executable', {candidate.OBJECT: Path('/new/placer_heap.cc.o')})
        self.assertEqual(result, ['/usr/bin/c++', '-O3', '-Wl,--dependency-file=/new/executable.d',
            '/new/placer_heap.cc.o', '/other/object.o', '-o', '/new/executable', '/other/library.a'])

    def test_fixture_requires_sanitizer_clean_exact_counter_results(self):
        self.assertEqual(candidate.fixture().count(candidate.EXPRESSION), 1)
        self.assertIn('++attempts;', candidate.fixture())
        for n, divisor in ((7, 8), (523410, 8), (2**64-1, 2**31-1), (523410, 0)):
            value = candidate.limit(n, divisor)
            text = f'count={n} divisor={divisor} timeout={value} next={value+1} rejected={int(value > 0)}\n'
            candidate.validate_result(text, 0, n, divisor)
            for bad, code in ((text, 1), (text + 'runtime error: overflow\n', 0), (text.replace('rejected=', 'wrong='), 0)):
                with self.assertRaises(AssertionError):
                    candidate.validate_result(bad, code, n, divisor)


if __name__ == '__main__':
    unittest.main()
