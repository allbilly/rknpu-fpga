"""Admission/log controls only; successful native execution is separate."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from qualify_strict_search_candidate import (QUALIFIED, COMMANDS, FLAGS, NATIVE, verify_metadata,
                                            check_strict_log, small_argv)
from qualify_static_exp_candidate import check_log
from build_strict_search_candidate import BUILT, COMMANDS as BUILD_COMMANDS, FLAGS as BUILD_FLAGS, verify_build_metadata
from strict_search_candidate import PRECISION_SOURCE, PRECISION_OBJECT


def report():
    return dict(status=QUALIFIED, stage='complete', finished_utc='synthetic', part='xc7k480tffg1156-2',
        full_parallel_products=512, native_positive_placements=3, lut_output_comparisons=1024,
        illegal_pair_rejected_before_postPlace=True, small_native_PNR_FASM_executed=True,
        native_control_cell_counts={'DSP48E1_DSP48E1': 4, 'RAMB36E1_RAMB36E1': 6},
        DSP_feature_comparison={str(i): {} for i in range(4)}, BRAM_feature_comparison={str(i): {} for i in range(6)},
        production_source_before='same', production_source_after='same', **{k: False for k in FLAGS},
        commands=[dict(label=n, returncode=125 if n == 'invalid-forced' else 0,
            expected_returncode=125 if n == 'invalid-forced' else 0,
            status='PASS_EXPECTED_REJECTION_ONLY' if n == 'invalid-forced' else 'PASS_TOOL_EXECUTION_ONLY') for n in COMMANDS])


def build():
    return dict(status=BUILT, stage='complete', finished_utc='synthetic', part='xc7k480tffg1156-2',
        full_parallel_products=512, corrected_parent_relink_byte_identical=True,
        changed_objects_relative_to_corrected_DSP_encoder=1, changed_search_upper_bounds=2,
        search_rng_trajectory_changed=True, actual_original_source=str(PRECISION_SOURCE), actual_original_object=str(PRECISION_OBJECT),
        production_source_before='same', production_source_after='same', **{k: False for k in BUILD_FLAGS},
        commands=[dict(label=n, returncode=0, status='PASS_TOOL_EXECUTION_ONLY') for n in BUILD_COMMANDS])


LOG_LINE = ('seconds=1.0 queue={queue} pops=49 committed=49 samples=200 outside={outside} empty=10 '
            'plain_checks=80 plain_rejects=10 cluster_checks=4 cluster_rejects=0 cell=- radius=0 ripup_radius=2 validity={validity}')
GOOD_LOG = '\n'.join('Info: RKNPU strict search: ' + phase + ' ' + LOG_LINE.format(queue=q, outside=0, validity=1)
    for phase, q in [('begin', 49), ('complete', 0)])


class StrictSearchQualification(unittest.TestCase):
    def test_only_completed_small_qualification_admitted(self): verify_metadata(report())

    def test_no_full_physical_wrong_target_or_missing_native_evidence(self):
        for key, value in [(k, True) for k in FLAGS] + [('status', 'RUNNING'), ('status', 'FAIL'), ('stage', 'native_legality_controls'),
                ('part', 'xc7k480tffg1156-1'), ('full_parallel_products', 32), ('native_positive_placements', 2),
                ('lut_output_comparisons', 0), ('illegal_pair_rejected_before_postPlace', False), ('small_native_PNR_FASM_executed', False)]:
            r = report(); r[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_metadata(r)
        for n in range(len(COMMANDS)):
            r = report(); r['commands'][n]['returncode'] = -9
            with self.assertRaises(AssertionError): verify_metadata(r)
        r = report(); r['commands'].pop()
        with self.assertRaises(AssertionError): verify_metadata(r)

    def test_isolated_build_never_grants_native_or_physical_acceptance(self):
        verify_build_metadata(build())
        for key, value in [(k, True) for k in BUILD_FLAGS] + [('search_rng_trajectory_changed', False),
                ('changed_objects_relative_to_corrected_DSP_encoder', 2), ('changed_search_upper_bounds', 0),
                ('corrected_parent_relink_byte_identical', False)]:
            r = build(); r[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_build_metadata(r)

    def test_actual_native_markers_required_with_all_counters_and_empty_queue(self):
        check_strict_log(GOOD_LOG)
        for broken in (GOOD_LOG.replace('complete', 'searching'), GOOD_LOG + '\n' + GOOD_LOG,
                       GOOD_LOG.replace('queue=0', 'queue=1'), GOOD_LOG.replace('validity=1', 'validity=0'),
                       GOOD_LOG.replace('outside=0', 'outside=1'), GOOD_LOG.replace('plain_rejects=10 ', '')):
            with self.assertRaises(AssertionError): check_strict_log(broken)

    def test_old_warning_and_negative_expectations_not_changed(self):
        negative = 'ERROR: post-placement validity check failed\nERROR: Static refinement failed; aborting placement before postPlace.'
        check_log(125, GOOD_LOG + '\n' + negative, 125)
        for code in (0, -6, 1):
            with self.assertRaises(AssertionError): check_log(code, GOOD_LOG + '\n' + negative, 125)

    def test_actual_small_input_clock_seed_and_normal_checks_unchanged(self):
        q = json.loads(NATIVE.read_text()); old = next(c['argv'] for c in q['commands'] if c['label'] == 'small_native_PNR_FASM')
        changed = small_argv('isolated', q, Path('/fresh'))
        self.assertEqual(changed[0], 'isolated')
        for option in ('--json', '--device', '--chipdb', '--top', '--seed', '--freq', '--placer', '--router'):
            self.assertEqual(changed[changed.index(option) + 1], old[old.index(option) + 1])
        self.assertIn('--Werror', changed)
        self.assertEqual(changed[changed.index('--write') + 1], '/fresh/routed.json')
        self.assertIn('fasm=/fresh/control.fasm', changed); self.assertIn('placement=/fresh/placement.json', changed)
        broken = deepcopy(q); next(c for c in broken['commands'] if c['label'] == 'small_native_PNR_FASM')['argv'].append('--timing-allow-fail')
        with self.assertRaises(AssertionError): small_argv('isolated', broken, Path('/fresh'))


if __name__ == '__main__': unittest.main()
