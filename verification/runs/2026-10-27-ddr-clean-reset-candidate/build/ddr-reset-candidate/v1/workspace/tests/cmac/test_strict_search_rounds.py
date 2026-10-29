"""New two-round log controls plus every unchanged original admission control."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from qualify_strict_search_rounds import FAILED, OLD_PARSE, check_strict_log, verify_failed_metadata
from test_strict_search_qualification import StrictSearchQualification


def line(phase, **changes):
    values = dict(seconds='0.000' if phase == 'begin' else '30.000', queue=10 if phase == 'begin' else 0,
        pops=0 if phase == 'begin' else 10, committed=0 if phase == 'begin' else 8,
        samples=0 if phase == 'begin' else 100, outside=0, empty=0 if phase == 'begin' else 40,
        plain_checks=0 if phase == 'begin' else 80, plain_rejects=0 if phase == 'begin' else 30,
        cluster_checks=0 if phase == 'begin' else 20, cluster_rejects=0 if phase == 'begin' else 2,
        cell='-', radius=0, ripup_radius=2, validity=1)
    values.update(changes)
    return 'Info: RKNPU strict search: ' + phase + ' ' + ' '.join(f'{k}={v}' for k, v in values.items())


GOOD = '\n'.join([line('begin'), line('complete'), line('begin'), line('complete')])


class StrictSearchRounds(unittest.TestCase):
    def test_actual_failed_native_negative_has_two_completed_valid_rounds(self):
        r = json.loads(FAILED.read_text()); verify_failed_metadata(r)
        text = Path(r['commands'][-1]['log']).read_text()
        result = check_strict_log(text)
        self.assertEqual(result['source_defined_rounds'], 2)
        self.assertEqual(result['rounds'][0]['final_counters']['pops'], 13)
        self.assertEqual(result['rounds'][1]['final_counters']['pops'], 28)
        with self.assertRaises(AssertionError): OLD_PARSE(text)

    def test_exact_two_rounds_without_nested_or_extra_or_missing_completion(self):
        check_strict_log(GOOD)
        for text in (GOOD.splitlines()[0], '\n'.join(GOOD.splitlines()[:2]), GOOD + '\n' + GOOD,
                     '\n'.join([line('begin'), line('begin'), line('complete'), line('complete')]),
                     GOOD.replace('complete', 'searching'), GOOD.replace('begin', 'complete')):
            with self.assertRaises(AssertionError): check_strict_log(text)

    def test_valid_heartbeat_and_per_round_monotonic_counters(self):
        text = '\n'.join([line('begin'), line('searching', seconds='10.000', queue=4, pops=5, committed=3,
            samples=50, empty=20, plain_checks=40, plain_rejects=10, cluster_checks=10, cluster_rejects=1, cell='actual-cell'),
            line('complete'), line('begin'), line('complete')])
        self.assertEqual(len(check_strict_log(text)['rounds'][0]['heartbeats']), 1)
        for old, new in [('pops=10', 'pops=4'), ('samples=100', 'samples=49'), ('seconds=30.000', 'seconds=9.000'),
                         ('plain_checks=80', 'plain_checks=39')]:
            with self.assertRaises(AssertionError): check_strict_log(text.replace(old, new))

    def test_disabled_validity_outside_nonempty_or_impossible_counters_rejected(self):
        for old, new in [('validity=1', 'validity=0'), ('outside=0', 'outside=1'), ('queue=0', 'queue=1'),
                         ('plain_rejects=30', 'plain_rejects=81'), ('cluster_rejects=2', 'cluster_rejects=21'),
                         ('pops=10', 'pops=7'), ('committed=8', 'committed=11')]:
            with self.subTest(old=old), self.assertRaises(AssertionError): check_strict_log(GOOD.replace(old, new))

    def test_unknown_malformed_missing_markers_counters_or_cells_rejected(self):
        for old, new in [('complete', 'ignored'), ('seconds=30.000', 'seconds=nan'),
                         ('plain_checks=80 ', ''), ('cell=-', 'cell=bad name'), ('begin', 'searching')]:
            with self.subTest(old=old), self.assertRaises(AssertionError): check_strict_log(GOOD.replace(old, new))

    def test_source_defined_call_order_exists_in_actual_frozen_native_source(self):
        from strict_search_candidate import PRECISION_SOURCE
        source = PRECISION_SOURCE.read_text()
        self.assertEqual(source.count('legalise_step(true);'), 1)
        self.assertEqual(source.count('legalise_step(false);'), 1)
        self.assertLess(source.index('legalise_step(true);'), source.index('legalise_step(false);'))
        self.assertIn('legalise_placement_strict(true);', source)

    def test_old_failure_wrong_native_outcome_or_physical_acceptance_rejected(self):
        original = json.loads(FAILED.read_text())
        for key, value in [('status', 'RUNNING'), ('status', 'PASS'), ('stage', 'complete'),
                           ('error', 'different error'), ('full_parallel_products', 32), ('physical_fit_verified', True)]:
            r = deepcopy(original); r[key] = value
            with self.assertRaises(AssertionError): verify_failed_metadata(r)
        for key, value in [('returncode', 0), ('expected_returncode', 1), ('status', 'PASS_EXPECTED_REJECTION_ONLY')]:
            r = deepcopy(original); r['commands'][-1][key] = value
            with self.assertRaises(AssertionError): verify_failed_metadata(r)


if __name__ == '__main__': unittest.main()
