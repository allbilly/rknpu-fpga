"""Prefix reviewed-checkpoint controls; all Vivado operations are MOCKED."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
sys.path.insert(0, str(ROOT / 'tests/cmac'))
import emit_dsp_prefix_bitstream as emitter
import test_emit_array_bitstream as original
import test_vivado_dsp_prefix_array_control as prefix_controls


class PrefixEmissionControl(original.EmissionControl):
    SOURCE_PROFILE = emitter.PROFILE
    CELLS = prefix_controls.EXTRA.split('proc get_property {name object} {')[0]
    CALLS = original.HARNESS.replace('set ::properties {}',
        CELLS + '\nset ::mock_routed 0\nset ::properties {}')
    CALLS = CALLS.replace('proc get_property {name object} {',
        'proc get_property {name object} {\n    if {$name eq "NAME"} {return $object}')

    def run_emit(self, settings=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        env.update(RK_CONFIRM_BOARD='YPCB_00338_1P1', RK_EMIT_BITSTREAM='1', RK_ARRAY_REVIEW_SHA='a' * 64)
        env.update(settings or {})
        with TemporaryDirectory(prefix='rk-prefix-emission-mocks-') as directory:
            dest = Path(directory); script = dest / 'emit.tcl'
            script.write_text(emitter.render(dest / 'mock.dcp', dest,
                {'configuration_voltage': '1.8', 'cfgbvs': 'GND'}, 'a' * 64, self.SOURCE_PROFILE))
            env['RK_TEST_BUILD_SCRIPT'] = str(script)
            result = subprocess.run([self.tclsh], input=self.CALLS, env=env, cwd=directory,
                text=True, capture_output=True, timeout=10)
            self.assertFalse(list(dest.rglob('*.bit')), 'Mocks must never write bitstreams')
        return result

    def test_full_prefix_dsp_guard_before_emission_not_shell_counts(self):
        result = self.run_emit({'MOCK_SHELL_DSPS': '7'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix'), 1)
        self.assertLess(result.stdout.index('ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix'),
                        result.stdout.index('EVENT write_bitstream'))
        for settings, message in [({'MOCK_KERNELS': '15'}, 'sixteen full C32'),
            ({'MOCK_KERNEL_ZERO_DSPS': '31'}, '32 DSP48E1'),
            ({'MOCK_KERNEL_ZERO_DSPS': '33'}, '32 DSP48E1'),
            ({'MOCK_DUPLICATE_KERNEL': '1'}, 'duplicate CMAC')]:
            self.blocked(settings, message)

    def test_exact_reversible_guard_only_no_physical_template_changes(self):
        args = (ROOT / 'MOCK/checkpoint', ROOT / 'MOCK/out',
            {'configuration_voltage': '1.8', 'cfgbvs': 'GND'}, 'a' * 64)
        plain = emitter.common.render(*args)
        actual = emitter.render(*args)
        inserted = emitter.prefix.GUARD + '\nwrite_bitstream $bitstream'
        self.assertEqual(actual.count(inserted), 1)
        self.assertEqual(actual.replace(inserted, 'write_bitstream $bitstream'), plain)
        for profile in ('baseline-c32k16', 'fixed-fp16-c32k16',
                        'dsp-compensated-c32k16', 'unverified'):
            with self.subTest(profile=profile), self.assertRaisesRegex(AssertionError, 'Unknown prefix'):
                emitter.render(*args, source_profile=profile)


def routed_mock():
    return dict(source_profile=emitter.PROFILE, status=emitter.prefix.ROUTED,
        action='run', finished_utc='MOCK_ONLY_NOT_ROUTED', channels=32, kernels=16,
        parallel_products=512, bitstream_emitted=False, hardware_programmed=False,
        commands=[dict(log='MOCK/' + label + '.log', status='PASS', returncode=0)
            for label in ('rom_check', 'version', 'implementation')],
        tool_version='Vivado v2026.1 (MOCK_ONLY_NOT_EXECUTED)',
        variant_evidence={n: {'MOCK_ONLY': n} for n in ('area', 'native', 'board', 'mapped')})


class PrefixReviewBinding(original.ReviewBinding):
    """Keep shared review controls, and test this profile's distinct admission."""
    def test_incomplete_and_cross_profile_reports_rejected_before_dispatch(self):
        parent = routed_mock()
        for profile in ('baseline-c32k16', 'fixed-fp16-c32k16', 'dsp-compensated-c32k16', None):
            bad = dict(parent, source_profile=profile)
            with self.subTest(profile=profile), self.assertRaisesRegex(AssertionError, 'Wrong prefix'):
                emitter.implementation_inputs(bad, ROOT / 'MOCK/report.json')
        for status in ('RUNNING', 'FAIL', 'PREPARED_DSP_PREFIX_ARRAY_VIVADO_ONLY',
            'ROUTED_DSP_ARRAY_CHECKPOINT_REVIEW_REQUIRED',
            'ROUTED_ARRAY_CHECKPOINT_REVIEW_REQUIRED', 'ROUTED_FIXED_ARRAY_CHECKPOINT_REVIEW_REQUIRED'):
            with self.subTest(status=status), self.assertRaisesRegex(AssertionError, 'Completed routed prefix'):
                emitter.implementation_inputs(dict(parent, status=status), ROOT / 'MOCK/report.json')

    def test_prefix_dispatch_revalidates_all_four_own_parents(self):
        parent = routed_mock(); report_path = ROOT / 'MOCK/report.json'
        with patch.object(emitter.prefix, 'inputs', return_value=({'MOCK': 'prefix spec'}, [])) as source, \
             patch.object(emitter.prefix, 'validate_evidence', return_value=parent['variant_evidence']) as evidence:
            self.assertEqual(emitter.implementation_inputs(parent, report_path), ({'MOCK': 'prefix spec'}, []))
            source.assert_called_once_with(report_path.parent)
            evidence.assert_called_once_with(report_path.parent)
            self.assertIs(emitter.implementation_board(parent), parent['variant_evidence']['board'])
            for banner in ('vivado v2026.1 (64-bit)', 'Vivado v2026.1 (64-bit)', 'VIVADO v2026.1.1 (64-bit)'):
                with self.subTest(banner=banner):
                    self.assertEqual(emitter.implementation_inputs(dict(parent, tool_version=banner), report_path),
                                     ({'MOCK': 'prefix spec'}, []))
            for name in parent['variant_evidence']:
                bad = copy.deepcopy(parent); bad['variant_evidence'][name] = {'MOCK_ONLY': 'different'}
                with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'Prefix implementation evidence differs'):
                    emitter.implementation_inputs(bad, report_path)
            evidence.side_effect = AssertionError('Incomplete own prefix numerical parents')
            with self.assertRaisesRegex(AssertionError, 'Incomplete own prefix'):
                emitter.implementation_inputs(parent, report_path)

    def test_completed_commands_dimensions_and_exact_flags_required(self):
        parent = routed_mock()
        changes = [('action', 'prepare'), ('finished_utc', ''), ('channels', 16),
            ('kernels', 8), ('parallel_products', 256), ('bitstream_emitted', 0),
            ('hardware_programmed', 0), ('bitstream_emitted', True),
            ('hardware_programmed', True), ('tool_version', 'Vivado Lab MOCK'),
            ('tool_version', 'vivado v'), ('tool_version', 'Vivado MOCK_ONLY'),
            ('tool_version', 'vivado v2026.1\nvivado lab v2026.1')]
        for key, value in changes:
            with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                emitter.implementation_inputs(dict(parent, **{key: value}), ROOT / 'MOCK/report.json')
        for change in ('missing', 'duplicate', 'live', 'nonzero', 'boolean_code', 'missing_code'):
            bad = copy.deepcopy(parent)
            if change == 'missing': bad['commands'].pop()
            elif change == 'duplicate': bad['commands'].append(bad['commands'][-1])
            elif change == 'live': bad['commands'][-1]['status'] = 'RUNNING'
            elif change == 'nonzero': bad['commands'][-1]['returncode'] = 1
            elif change == 'boolean_code': bad['commands'][-1]['returncode'] = False
            else: bad['commands'][-1].pop('returncode')
            with self.subTest(change=change), self.assertRaises((AssertionError, KeyError)):
                emitter.implementation_inputs(bad, ROOT / 'MOCK/report.json')

    def test_emission_source_binds_helpers_checkpoint_and_all_reviewed_reports(self):
        report = ROOT / 'MOCK/report.json'; review = ROOT / 'MOCK/review.json'
        built = [ROOT / 'fpga/cmac/ypcb_cmac_array_top.sv']
        paths = emitter.emission_inputs(built, report, review)
        self.assertEqual(paths, sorted(set(paths)))
        self.assertTrue(set(built + [report, review, emitter.TEMPLATE,
            Path(emitter.__file__).resolve(), Path(emitter.common.__file__).resolve(),
            Path(emitter.prefix.__file__).resolve(), ROOT / 'tools/evidence.py',
            *[report.parent / name for name in emitter.REPORTS + ('routed.dcp', 'build.tcl')]]) <= set(paths))

    def test_prepared_cli_rejected_before_output_or_tool_creation(self):
        with TemporaryDirectory(prefix='prefix-emitter-admission-control-', dir=ROOT / 'build') as name:
            directory = Path(name); report = directory / 'prepared.json'
            report.write_text(json.dumps(dict(source_profile=emitter.PROFILE,
                status='PREPARED_DSP_PREFIX_ARRAY_VIVADO_ONLY')))
            with patch.object(emitter, 'ROOT', directory), \
                 patch.object(sys, 'argv', ['emitter', 'review-template', '--implementation-report', str(report)]), \
                 patch.object(emitter.shutil, 'which') as which:
                with self.assertRaisesRegex(AssertionError, 'Completed routed prefix'):
                    emitter.main()
                which.assert_not_called()
            self.assertEqual(sorted(p.name for p in directory.iterdir()), ['prepared.json'])


if __name__ == '__main__':
    unittest.main()
