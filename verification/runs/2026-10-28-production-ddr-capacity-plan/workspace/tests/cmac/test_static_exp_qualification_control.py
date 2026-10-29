"""Software admission controls, not native execution or physical acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/openxc7'))
from qualify_static_exp_candidate import BUILT, verify_build_metadata, probe_argv, check_log


def build():
    return dict(status=BUILT, stage='complete', finished_utc='synthetic control',
        part='xc7k480tffg1156-2', parent_relink_byte_identical=True, exact_changed_calls=2,
        **{k: False for k in ('assertion_removal', 'objective_or_coefficient_changed', 'FPGA_clock_or_geometry_changed',
            'native_requalification_executed', 'native_placement_executed', 'physical_fit_verified', 'timing_signoff',
            'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed')},
        commands=[dict(label=n, returncode=0, status='PASS_TOOL_EXECUTION_ONLY') for n in
            ('compiler_version', 'relink_parent_identity', 'compile_static_precision', 'link_precision_candidate', 'native_version')])


POSITIVE = '\n'.join(('Running Static placer...', 'Running simulated annealing placer for refinement.',
    'Running post-placement legalisation...', 'Program finished normally.'))
NEGATIVE = 'ERROR: post-placement validity check failed\nERROR: Static refinement failed; aborting placement before postPlace.'


class StaticExpQualificationControl(unittest.TestCase):
    def test_complete_isolated_build_only(self):
        verify_build_metadata(build())

    def test_build_failure_wrong_part_source_and_acceptance_rejected(self):
        for key, value in [('status', 'RUNNING'), ('status', 'FAIL'), ('stage', 'build'),
                ('finished_utc', ''), ('part', 'xc7k480tffg1156-1'), ('parent_relink_byte_identical', False),
                ('exact_changed_calls', 1)] + [(k, True) for k, v in build().items() if v is False]:
            report = build()
            report[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError): verify_build_metadata(report)
        for kind in ('wrong_rc', 'missing', 'status'):
            report = build()
            if kind == 'wrong_rc': report['commands'][0]['returncode'] = 1
            elif kind == 'missing': report['commands'].pop()
            else: report['commands'][0]['status'] = 'RUNNING'
            with self.assertRaises(AssertionError): verify_build_metadata(report)

    def test_native_argv_keeps_exact_target_clock_and_normal_refinement(self):
        argv = probe_argv('native', 'original-fixture', 'literal.xdc', 'placed')
        for key, value in (('--device', 'xc7k480tffg1156-2'), ('--freq', '50'), ('--seed', '12350'),
                           ('--placer', 'static'), ('--json', 'original-fixture')):
            self.assertEqual(argv[argv.index(key) + 1], value)
        for key in ('--Werror', '--no-route'): self.assertIn(key, argv)
        for key in ('--force', '--timing-allow-fail', '--no-pack', '--no-place', '--fasm',
                    '--placer-static-refine-max-iterations'): self.assertNotIn(key, argv)

    def test_positive_requires_all_completion_markers_and_no_warnings(self):
        check_log(0, POSITIVE, 0)
        for text in (POSITIVE.replace('Running post-placement legalisation...', ''), POSITIVE + '\nWARNING: ignored',
                     POSITIVE + '\nERROR: failed', POSITIVE + '\nStatic refinement iteration limit: 1.'):
            with self.assertRaises(AssertionError): check_log(0, text, 0)
        with self.assertRaises(AssertionError): check_log(-6, POSITIVE, 0)

    def test_negative_exact_rejection_not_abort_or_continued_execution(self):
        check_log(125, NEGATIVE, 125)
        for text in (NEGATIVE.replace('post-placement validity check failed', 'different failure'),
                     NEGATIVE + '\nAssertion failure', NEGATIVE + '\nProgram finished normally.',
                     NEGATIVE + '\nRunning post-placement legalisation...', NEGATIVE + '\nWARNING: ignored'):
            with self.assertRaises(AssertionError): check_log(125, text, 125)
        for code in (0, -6, 1):
            with self.assertRaises(AssertionError): check_log(code, NEGATIVE, 125)


if __name__ == '__main__': unittest.main()
