"""Host source/sampler controls; not native P&R, RTL or hardware validation."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from strict_search_candidate import (PRECISION_SOURCE, PRECISION_OBJECT, candidate_source,
                                     verify_source_transition, compile_argv)


class StrictSearchCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = PRECISION_SOURCE.read_text()
        cls.candidate = candidate_source(cls.original)

    def test_exact_transition_and_unchanged_assertions_rng_and_objective(self):
        verify_source_transition(self.original, self.candidate)
        start = self.original.index('    void legalise_placement_strict(bool require_validity = true)\n')
        end = self.original.index('\n  public:\n', start)
        self.assertEqual(self.original[:start], self.candidate[:start])
        self.assertEqual(self.original[end:], self.candidate[self.candidate.index('\n  public:\n', start):])
        self.assertEqual(self.original.count('NPNR_ASSERT'), self.candidate.count('NPNR_ASSERT'))
        self.assertEqual(self.original.count('ctx->rng('), self.candidate.count('ctx->rng('))
        for name in ('emin', 'emax'):
            self.assertIn(f'std::exp(static_cast<double>({name}))', self.candidate)

    def test_native_plain_and_cluster_validity_region_and_ripup_guards_retained(self):
        for guard in ('require_validity && !ctx->isBelLocationValid(sz)', '!ctx->isBelLocationValid(sm.first)',
                      '!ci->testRegion(sz)', '!target.first->testRegion(target.second)',
                      'bound->cluster != ClusterId() || bound->belStrength > STRENGTH_WEAK',
                      'total_iters_noreset > std::max(5000, 8 * int(ctx->cells.size()))'):
            self.assertEqual(self.candidate.count(guard), 1)

    def test_changed_guard_objective_rng_or_refinement_cannot_pass_exact_transition(self):
        for old, new in [('!ctx->isBelLocationValid(sz)', 'false'), ('!ci->testRegion(sz)', 'false'),
                         ('ctx->rng(20000)', 'ctx->rng(2)'), ('8 * int(ctx->cells.size())', '80 * int(ctx->cells.size())'),
                         ('std::exp(static_cast<double>(emin))', 'std::exp(emin)')]:
            with self.subTest(old=old), self.assertRaises(AssertionError):
                verify_source_transition(self.original, self.candidate.replace(old, new))

    def test_source_anchor_drift_fails(self):
        for old, new in [('int x1 = cx + rx;', 'int x1 = cx + 2 * rx;'),
                         ('int ripup_radius = 2;', 'int ripup_radius = 3;')]:
            with self.subTest(old=old), self.assertRaises(AssertionError):
                candidate_source(self.original.replace(old, new))

    def test_clamp_keeps_all_possible_legal_coordinates_including_region_intersection(self):
        # The candidate's two emitted expressions are explicitly checked above;
        # this host enumeration establishes their support, not native success.
        self.assertIn('int x1 = std::min(cx + rx, bel_width - 1);', self.candidate)
        self.assertIn('int y1 = std::min(cy + ry, bel_height - 1);', self.candidate)
        for width in range(1, 9):
            for centre in range(width):
                for radius in range(width + 3):
                    for region in (None, (0, width - 1), (0, 0), (width - 1, width - 1),
                                   (-3, -1), (width, width + 2), (1, width - 2)):
                        if region and region[0] > region[1]: continue
                        def support(clamped):
                            lo, hi = max(centre - radius, 0), centre + radius
                            if clamped: hi = min(hi, width - 1)
                            if region:
                                lo, hi = max(lo, region[0]), min(hi, region[1])
                                if lo > hi: lo, hi = hi, lo
                            return {x for x in range(lo, hi + 1) if 0 <= x < width and
                                    (region is None or region[0] <= x <= region[1])}
                        self.assertEqual(support(False), support(True), (width, centre, radius, region))

    def test_max_radius_removes_physical_rectangle_misses_without_claiming_speed(self):
        width, height, cx, cy, radius = 10, 6, 9, 5, 11
        old = (cx + radius + 1) * (cy + radius + 1)
        new = min(cx + radius + 1, width) * min(cy + radius + 1, height)
        self.assertEqual((old, new), (357, 60))
        self.assertLess(new, old)

    def test_telemetry_does_not_change_randomness_or_select_bels(self):
        body = self.candidate.split('auto progress =', 1)[1].split('progress("begin"', 1)[0]
        for forbidden in ('rng(', 'bindBel(', 'unbindBel(', 'enqueue_legalise(', 'log_error('):
            self.assertNotIn(forbidden, body)
        for marker in ('progress("begin"', 'progress("searching"', 'progress("complete"',
                       'search_samples & 4095ULL', 'std::chrono::seconds(30)'):
            self.assertIn(marker, self.candidate)

    def test_compile_only_replaces_source_object_and_dependency_output(self):
        old = ['c++', '-Wall', '-O3', '-MD', '-MF', str(PRECISION_OBJECT) + '.d',
               '-c', str(PRECISION_SOURCE), '-o', str(PRECISION_OBJECT)]
        self.assertEqual(compile_argv(old, Path('/candidate/source.cc'), Path('/candidate/object.o')),
            ['c++', '-Wall', '-O3', '-MD', '-MF', '/candidate/object.o.d',
             '-c', '/candidate/source.cc', '-o', '/candidate/object.o'])
        for broken in (old + [str(PRECISION_OBJECT)], old[:-1], old + [str(PRECISION_SOURCE)]):
            with self.assertRaises(AssertionError): compile_argv(broken, Path('/s'), Path('/o'))


if __name__ == '__main__': unittest.main()
