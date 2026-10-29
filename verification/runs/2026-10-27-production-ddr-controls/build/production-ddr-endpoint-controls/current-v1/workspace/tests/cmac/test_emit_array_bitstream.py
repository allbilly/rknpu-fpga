"""Reviewed-checkpoint emission control MOCKS; no actual FPGA/tool validation."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
sys.path.insert(0, str(ROOT / 'tests'))
import emit_array_bitstream as emitter
from test_fpga_build import HARNESS

EXTRA = r'''
proc open_checkpoint {args} {event open_checkpoint {*}$args}
proc get_clocks {args} {if {[mock MOCK_NO_CLOCK 0]} {return {}}; return sys_clk}
'''
HARNESS = HARNESS.replace('proc get_property {name object} {', r'''
proc get_property {name object} {
    switch -- $name {
        PART {return [mock MOCK_PART xc7k480tffg1156-2]}
        CFGBVS {return [mock MOCK_CFGBVS GND]}
        CONFIG_VOLTAGE {return [mock MOCK_VOLTAGE 1.8]}
        PERIOD {return [mock MOCK_PERIOD 20.000]}
    }
''').replace('set ::properties {}', EXTRA + '\nset ::properties {}')


class EmissionControl(unittest.TestCase):
    SOURCE_PROFILE = 'baseline-c32k16'
    CALLS = HARNESS
    @classmethod
    def setUpClass(cls):
        cls.tclsh = shutil.which(os.environ.get('RK_TEST_TCLSH', 'tclsh'))
        if cls.tclsh is None:
            raise RuntimeError('UNAVAILABLE: Tcl interpreter')
        version = subprocess.run([cls.tclsh], input='puts [info patchlevel]\n', text=True,
                                 capture_output=True, check=True).stdout.strip()
        print(f'Emission tests: Tcl {version}; all Vivado calls MOCKED', flush=True)

    def run_emit(self, settings=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        env.update(RK_CONFIRM_BOARD='YPCB_00338_1P1', RK_EMIT_BITSTREAM='1', RK_ARRAY_REVIEW_SHA='a' * 64)
        env.update(settings or {})
        with tempfile.TemporaryDirectory(prefix='rk-emission-mocks-') as directory:
            dest = Path(directory)
            script = dest / 'emit.tcl'
            script.write_text(emitter.render(dest / 'mock.dcp', dest,
                              {'configuration_voltage': '1.8', 'cfgbvs': 'GND'}, 'a' * 64,
                              self.SOURCE_PROFILE))
            env['RK_TEST_BUILD_SCRIPT'] = str(script)
            result = subprocess.run([self.tclsh], input=self.CALLS, env=env, cwd=directory,
                                    text=True, capture_output=True, timeout=10)
            self.assertFalse(list(dest.rglob('*.bit')), 'Mocks must never write bitstreams')
        return result

    def blocked(self, settings, message):
        result = self.run_emit(settings)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertNotIn('EVENT write_bitstream', result.stdout)

    def test_mocked_emission_order_and_no_mutation(self):
        result = self.run_emit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('EVENT write_bitstream '), 1)
        self.assertLess(result.stdout.index('EVENT open_checkpoint'), result.stdout.index('EVENT report_drc'))
        self.assertLess(result.stdout.index('EVENT report_drc'), result.stdout.index('EVENT write_bitstream'))
        for forbidden in ('EVENT set_property', 'EVENT program_hw', 'EVENT open_hw', 'EVENT route_design'):
            self.assertNotIn(forbidden, result.stdout)

    def test_explicit_authority(self):
        for key, value in (('RK_CONFIRM_BOARD', ''), ('RK_EMIT_BITSTREAM', '0'), ('RK_EMIT_BITSTREAM', 'yes')):
            self.blocked({key: value}, 'Explicit board confirmation')
        self.blocked({'RK_ARRAY_REVIEW_SHA': ''}, 'source-bound reviewed-checkpoint')

    def test_checkpoint_identity_and_electrical_values(self):
        self.blocked({'MOCK_PART': 'xc7k325tffg900-2'}, 'part mismatch')
        self.blocked({'MOCK_CFGBVS': 'VCCO'}, 'CFGBVS mismatch')
        for value in ('', 'NaN', 'Inf', 'unknown', '3.3'):
            self.blocked({'MOCK_VOLTAGE': value}, 'voltage mismatch')

    def test_clock_and_memory(self):
        self.blocked({'MOCK_NO_CLOCK': '1'}, 'exactly one sys_clk')
        self.blocked({'MOCK_NO_BRAM': '1'}, 'No inferred block RAM')
        for value in ('', 'NaN', 'Inf', '40', 'unknown'):
            self.blocked({'MOCK_PERIOD': value}, 'clock period mismatch')

    def test_setup_hold_rejections(self):
        for kind in ('MAX', 'MIN'):
            self.blocked({'MOCK_EMPTY_' + kind: '1'}, 'No ' + kind.lower() + ' timing')
            for value in ('', 'NaN', 'Inf', '-Inf', '1e9999', '-0.001', 'N/A'):
                self.blocked({'MOCK_SLACK_' + kind: value}, 'Invalid or negative')

    def test_drc_rejections(self):
        for value in ('Error', 'Critical Warning', 'Fatal', '', 'unknown'):
            self.blocked({'MOCK_DRC_SEVERITY': value}, 'Blocking DRC violation')


class DspEmissionControl(EmissionControl):
    """Repeat every unchanged emission gate, plus the full DSP resource guard."""
    SOURCE_PROFILE = emitter.DSP_PROFILE
    import test_vivado_dsp_array_control as dsp_controls
    CELLS = dsp_controls.EXTRA.split('proc get_property {name object} {')[0]
    CALLS = HARNESS.replace('set ::properties {}', CELLS + '\nset ::mock_routed 0\nset ::properties {}')
    CALLS = CALLS.replace('proc get_property {name object} {',
        'proc get_property {name object} {\n    if {$name eq "NAME"} {return $object}')

    def test_dsp_checkpoint_requires_16_times_32_products_before_emission(self):
        result = self.run_emit({'MOCK_SHELL_DSPS': '7'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('EVENT write_bitstream '), 1)
        for settings, message in [({'MOCK_KERNELS': '15'}, 'sixteen full C32'),
            ({'MOCK_KERNEL_ZERO_DSPS': '31'}, '32 DSP48E1'),
            ({'MOCK_DUPLICATE_KERNEL': '1'}, 'duplicate CMAC')]:
            self.blocked(settings, message)

    def test_only_one_reversible_template_addition_and_unknown_profile_rejected(self):
        import vivado_dsp_array as dsp
        args = (ROOT / 'MOCK/checkpoint', ROOT / 'MOCK/out',
            {'configuration_voltage': '1.8', 'cfgbvs': 'GND'}, 'a' * 64)
        plain = emitter.render(*args)
        actual = emitter.render(*args, dsp.PROFILE)
        inserted = dsp.GUARD + '\nwrite_bitstream $bitstream'
        self.assertEqual(actual.count(inserted), 1)
        self.assertEqual(actual.replace(inserted, 'write_bitstream $bitstream'), plain)
        with self.assertRaisesRegex(AssertionError, 'Unknown emission'):
            emitter.render(*args, 'unverified-source-profile')


class ReviewBinding(unittest.TestCase):
    def test_prepared_and_cross_profile_reports_rejected(self):
        for profile, statuses in (
                ('baseline-c32k16', ('RUNNING', 'FAIL', 'PREPARED_ARRAY_VIVADO_ONLY', 'ROUTED_FIXED_ARRAY_CHECKPOINT_REVIEW_REQUIRED')),
                ('fixed-fp16-c32k16', ('RUNNING', 'FAIL', 'PREPARED_FIXED_ARRAY_VIVADO_ONLY', 'ROUTED_ARRAY_CHECKPOINT_REVIEW_REQUIRED')),
                (emitter.DSP_PROFILE, ('RUNNING', 'FAIL', 'PREPARED_DSP_ARRAY_VIVADO_ONLY',
                    'ROUTED_ARRAY_CHECKPOINT_REVIEW_REQUIRED', 'ROUTED_FIXED_ARRAY_CHECKPOINT_REVIEW_REQUIRED'))):
            for status in statuses:
                with self.assertRaisesRegex(AssertionError, 'Completed routed'):
                    emitter.implementation_inputs({'source_profile': profile, 'status': status}, ROOT / 'MOCK-report.json')
        with self.assertRaisesRegex(AssertionError, 'Unknown implementation'):
            emitter.implementation_inputs({'source_profile': 'unreviewed'}, ROOT / 'MOCK-report.json')

    def test_fixed_profile_dispatch_revalidates_both_parents(self):
        import vivado_fixed_array as fixed
        native, board = {'MOCK': 'native'}, {'MOCK': 'board'}
        parent = dict(source_profile=fixed.PROFILE, status=fixed.ROUTED, fixed_native_report=native, board_report=board)
        with patch.object(fixed, 'inputs', return_value=({'MOCK': 'spec'}, [])) as source_gate, \
                patch.object(fixed, 'validate_evidence', return_value=(native, board)) as evidence_gate:
            self.assertEqual(emitter.implementation_inputs(parent, ROOT / 'MOCK/report.json'), ({'MOCK': 'spec'}, []))
            source_gate.assert_called_once_with(ROOT / 'MOCK')
            evidence_gate.assert_called_once_with(ROOT / 'MOCK')
            for key in ('fixed_native_report', 'board_report'):
                invalid = dict(parent, **{key: {'MOCK': 'different evidence'}})
                with self.assertRaisesRegex(AssertionError, 'evidence differs'):
                    emitter.implementation_inputs(invalid, ROOT / 'MOCK/report.json')

    def test_dsp_profile_dispatch_revalidates_all_four_exact_parents(self):
        import vivado_dsp_array as dsp
        parents = {n: {'MOCK_ONLY': n} for n in ('area', 'native', 'board', 'mapped')}
        parent = dict(source_profile=dsp.PROFILE, status=dsp.ROUTED, variant_evidence=parents)
        with patch.object(dsp, 'inputs', return_value=({'MOCK_ONLY': 'DSP spec'}, [])) as source_gate, \
             patch.object(dsp, 'validate_evidence', return_value=parents) as evidence_gate:
            self.assertEqual(emitter.implementation_inputs(parent, ROOT / 'MOCK/report.json'), ({'MOCK_ONLY': 'DSP spec'}, []))
            source_gate.assert_called_once_with(ROOT / 'MOCK')
            evidence_gate.assert_called_once_with(ROOT / 'MOCK')
            self.assertIs(emitter.implementation_board(parent), parents['board'])
            for name in parents:
                bad = copy.deepcopy(parent); bad['variant_evidence'][name] = {'MOCK_ONLY': 'different'}
                with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'DSP implementation evidence differs'):
                    emitter.implementation_inputs(bad, ROOT / 'MOCK/report.json')
            evidence_gate.side_effect = AssertionError('Incomplete actual DSP evidence')
            with self.assertRaisesRegex(AssertionError, 'Incomplete actual DSP evidence'):
                emitter.implementation_inputs(parent, ROOT / 'MOCK/report.json')

    def test_existing_profiles_keep_their_original_board_binding(self):
        for profile in ('baseline-c32k16', 'fixed-fp16-c32k16'):
            board = {'MOCK_ONLY': profile}
            self.assertIs(emitter.implementation_board({'source_profile': profile, 'board_report': board}), board)

    def fixture(self, directory):
        dest = Path(directory)
        report_path = dest / 'implementation.json'
        report_path.write_text('MOCK implementation, not hardware evidence\n')
        for name in emitter.REPORTS + ('routed.dcp', 'build.tcl'):
            (dest / name).write_text('MOCK ' + name + '\n')
        artifacts = {name: emitter.digest(dest / name) for name in emitter.REPORTS + ('routed.dcp', 'build.tcl')}
        parent = {'implementation_settings': {'RK_CONFIRM_BOARD': 'YPCB_00338_1P1', 'RK_CONFIG_VOLTAGE': '1.8',
                                              'RK_CFGBVS': 'GND', 'RK_LED_ACTIVE_LOW': None},
                  'artifacts': {'files': artifacts}}
        review = {'schema': 1, 'implementation_report_sha256': emitter.digest(report_path),
                  'board': 'YPCB_00338_1P1', 'part': 'xc7k480tffg1156-2', 'reviewer': 'MOCK reviewer',
                  'physical_board_evidence': 'MOCK physical assertion, not established',
                  'configuration_voltage': '1.8', 'cfgbvs': 'GND', 'led_active_low': 0,
                  'checks': {key: True for key in emitter.CHECKS}, 'reviewed_artifacts': artifacts}
        return report_path, parent, review

    def test_all_explicit_acceptances_required(self):
        with tempfile.TemporaryDirectory(prefix='rk-review-mocks-') as directory, patch.object(emitter, 'ROOT', Path(directory)):
            report_path, parent, review = self.fixture(directory)
            emitter.validate_review(review, report_path, parent)
            for key in emitter.CHECKS:
                for value in (False, 1, 'true', None):
                    invalid = copy.deepcopy(review)
                    invalid['checks'][key] = value
                    with self.assertRaisesRegex(AssertionError, 'Incomplete explicit'):
                        emitter.validate_review(invalid, report_path, parent)
            for key in ('reviewer', 'physical_board_evidence'):
                invalid = copy.deepcopy(review)
                invalid[key] = ''
                with self.assertRaises(AssertionError):
                    emitter.validate_review(invalid, report_path, parent)

    def test_review_and_checkpoint_hashes_required(self):
        with tempfile.TemporaryDirectory(prefix='rk-review-mocks-') as directory, patch.object(emitter, 'ROOT', Path(directory)):
            report_path, parent, review = self.fixture(directory)
            invalid = copy.deepcopy(review)
            invalid['implementation_report_sha256'] = '0' * 64
            with self.assertRaisesRegex(AssertionError, 'Wrong implementation'):
                emitter.validate_review(invalid, report_path, parent)
            (Path(directory) / 'routed.dcp').write_text('MODIFIED MOCK checkpoint')
            with self.assertRaisesRegex(AssertionError, 'bind every required'):
                emitter.validate_review(review, report_path, parent)

    def test_settings_and_rendering_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='rk-review-mocks-') as directory, patch.object(emitter, 'ROOT', Path(directory)):
            report_path, parent, review = self.fixture(directory)
            for updates in ({'configuration_voltage': '3.3', 'cfgbvs': 'GND'}, {'led_active_low': True},
                            {'configuration_voltage': '2.5', 'cfgbvs': 'VCCO'}, {'led_active_low': 1}):
                invalid = copy.deepcopy(review)
                invalid.update(updates)
                with self.assertRaises(AssertionError):
                    emitter.validate_review(invalid, report_path, parent)
        with self.assertRaises(AssertionError):
            emitter.render(Path('checkpoint'), Path('out'), {'configuration_voltage': '1.8', 'cfgbvs': 'VCCO'}, 'a' * 64)
        with self.assertRaises(ValueError):
            emitter.render(Path('bad{path'), Path('out'), {'configuration_voltage': '1.8', 'cfgbvs': 'GND'}, 'a' * 64)


if __name__ == '__main__':
    unittest.main()
