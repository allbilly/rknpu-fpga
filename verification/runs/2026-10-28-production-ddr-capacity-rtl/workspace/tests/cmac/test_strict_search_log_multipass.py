"""Controls for the source-defined two-pass native strict-search log parser."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from qualify_strict_search_candidate import check_strict_log as check_single_pass
from qualify_strict_search_rounds import check_strict_log as check_two_passes


def line(phase, **changes):
    values = dict(seconds='0.000' if phase == 'begin' else '1.000',
        queue=10 if phase == 'begin' else 0, pops=0 if phase == 'begin' else 10,
        committed=0 if phase == 'begin' else 8, samples=0 if phase == 'begin' else 100,
        outside=0, empty=0 if phase == 'begin' else 40,
        plain_checks=0 if phase == 'begin' else 80,
        plain_rejects=0 if phase == 'begin' else 30,
        cluster_checks=0 if phase == 'begin' else 20,
        cluster_rejects=0 if phase == 'begin' else 2,
        cell='-' if phase != 'searching' else 'active-cell', radius=0,
        ripup_radius=2, validity=1)
    values.update(changes)
    return 'Info: RKNPU strict search: ' + phase + ' ' + ' '.join(
        f'{key}={value}' for key, value in values.items())


GOOD = '\n'.join((line('begin'), line('complete'), line('begin'), line('complete')))


class StrictSearchLogMultipass(unittest.TestCase):
    def test_two_source_defined_passes_are_individually_complete_and_valid(self):
        report = check_two_passes(GOOD)
        self.assertEqual(report['source_defined_rounds'], 2)
        self.assertEqual([item['initial_queue'] for item in report['rounds']], [10, 10])
        self.assertTrue(report['native_validity_enabled_in_every_marker'])
        with self.assertRaises(AssertionError):
            check_single_pass(GOOD)

    def test_search_heartbeat_remains_ordered_and_counters_monotonic(self):
        text = '\n'.join((line('begin'), line('searching', seconds='0.500', queue=4,
            pops=5, committed=3, samples=50, empty=20, plain_checks=40,
            plain_rejects=10, cluster_checks=10, cluster_rejects=1),
            line('complete'), line('begin'), line('complete')))
        self.assertEqual(len(check_two_passes(text)['rounds'][0]['heartbeats']), 1)
        broken = text.replace('pops=10 committed=8 samples=100',
                               'pops=4 committed=8 samples=100', 1)
        with self.assertRaises(AssertionError):
            check_two_passes(broken)

    def test_incomplete_nested_extra_or_invalid_pass_is_rejected(self):
        malformed = (
            '\n'.join((line('begin'), line('complete'), line('begin'))),
            GOOD + '\n' + '\n'.join((line('begin'), line('complete'))),
            '\n'.join((line('begin'), line('begin'), line('complete'), line('complete'))),
            GOOD.replace('validity=1', 'validity=0', 1),
            GOOD.replace('outside=0', 'outside=1', 1),
            GOOD.replace('queue=0', 'queue=1', 1),
        )
        for text in malformed:
            with self.subTest(text=text), self.assertRaises(AssertionError):
                check_two_passes(text)


if __name__ == '__main__':
    unittest.main()
