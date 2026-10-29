"""DSP admission and Tcl controls. Vivado calls are MOCKED, not implementation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
sys.path.insert(0, str(ROOT / 'tests/cmac'))
import test_array_build as baseline
import vivado_dsp_array as dsp


EXTRA = r'''
proc get_cells {args} {
    event get_cells {*}$args
    set filter [lindex $args [expr {[lsearch -exact $args -filter] + 1}]]
    if {[string first "ORIG_REF_NAME" $filter] >= 0} {
        set kernels {}
        for {set k 0} {$k < [mock MOCK_KERNELS 16]} {incr k} {
            lappend kernels [format {dut/g_kernel[%d]/cell} $k]
        }
        if {[mock MOCK_DUPLICATE_KERNEL 0]} { lset kernels 15 [lindex $kernels 0] }
        return $kernels
    }
    if {$filter eq "REF_NAME == DSP48E1"} {
        set cells {}
        for {set k 0} {$k < 16} {incr k} {
            set count 32
            if {$k == 0} {set count [mock MOCK_KERNEL_ZERO_DSPS 32]}
            if {$::mock_routed && $k == 15} {set count [mock MOCK_ROUTED_LAST_DSPS 32]}
            for {set i 0} {$i < $count} {incr i} {
                lappend cells [format {dut/g_kernel[%d]/cell/lane[%d]/product} $k $i]
            }
        }
        # Extra shell DSPs must not be mistaken for the 512 CMAC products.
        for {set i 0} {$i < [mock MOCK_SHELL_DSPS 2]} {incr i} {
            lappend cells [format {dut/shell/dsp[%d]} $i]
        }
        return $cells
    }
    if {$filter eq "REF_NAME == RAMB18E1 || REF_NAME == RAMB36E1"} {
        if {[mock MOCK_NO_BRAM 0]} {return {}}
        return ram
    }
    error "Unexpected DSP-profile cell query: $args"
}
proc get_property {name object} {
    if {$name eq "NAME"} { return $object }
    if {$name eq "PERIOD"} { return [mock MOCK_PERIOD 20.000] }
    if {$name eq "SLACK" && $object in {path_max path_min}} {
        return [mock MOCK_SLACK_[string toupper [string range $object 5 end]] 0.100]
    }
    if {$name eq "SEVERITY" && $object eq "violation"} {
        return [mock MOCK_DRC_SEVERITY Error]
    }
    error "Unexpected DSP-profile property query: $name $object"
}
proc route_design {args} {set ::mock_routed 1; event route_design {*}$args}
set ::mock_routed 0
'''
HARNESS = baseline.HARNESS.replace('set ::properties {}', EXTRA + '\nset ::properties {}')


def mapped_report():
    return dict(status='PASS_FULL_C32K16_DSP_ARRAY_MAPPED_BINARY_FIXTURES_ONLY', stage='complete',
        finished_utc='MOCK_CONTROL_NOT_EXECUTED', channels=32, kernels=16, parallel_products=512,
        frames=208, expected_outputs=3328, seed='0x35883216',
        numerical_netlist_binary_fixture_acceptance=True,
        expected_result=dsp.mapped.EXPECTED, result=dsp.mapped.EXPECTED,
        kernel_cells={'DSP48E1': 32, 'LUT1': 1}, library_operations=['combo_update', 'create'],
        export_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
        commands=[dict(log='MOCK/' + label + '.log', status='PASS',
            returncode=-6 if label == 'negative_test' else 0) for label in dsp.LABELS],
        **{name: False for name in ('four_state_x_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')})


class DspBuildControls(baseline.ArrayBuildControl):
    """Rerun every original physical-control gate on the DSP-rendered Tcl."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory = TemporaryDirectory(prefix='dsp-vivado-controls-', dir=ROOT / 'build')
        out = Path(cls.directory.name)
        join = out / Path(dsp.gates.replay.preparation.JOIN).name
        join.write_text(dsp.gates.replay.preparation.dsp_join((ROOT / dsp.gates.replay.preparation.JOIN).read_text()))
        cls.spec, cls.tracked = dsp.inputs(out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_build(self, settings=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        env.update(RK_CONFIRM_BOARD='YPCB_00338_1P1', RK_ARRAY_SOURCE_SHA='a' * 64)
        env.update(settings or {})
        with TemporaryDirectory(prefix='dsp-vivado-tcl-control-') as directory:
            out = Path(directory); script = out / 'build.tcl'
            script.write_text(dsp.render(self.spec, out / 'out', 'a' * 64))
            env['RK_TEST_BUILD_SCRIPT'] = str(script)
            result = subprocess.run([self.tclsh], input=HARNESS, env=env, cwd=directory,
                text=True, capture_output=True, timeout=10)
            self.assertFalse(list(out.rglob('*.bit')))
            self.assertFalse(list(out.rglob('*.dcp')))
        self.assertNotIn('EVENT write_bitstream', result.stdout)
        return result

    def test_incomplete_board_evidence_rejected(self):
        for status in ('RUNNING', 'FAIL', 'PREPARED_COMPILED_FULL_C32K16_DSP_RAW_BOARD_ONLY',
            'PASS_FIXED_RAW_ARRAY_BOARD_FOUR_STATE_RTL_EXPERIMENT_ONLY'):
            with self.assertRaises(AssertionError):
                dsp.gates.validate_board_metadata({'status': status})

    def test_exact_512_products_and_literal_generate_names(self):
        result = self.run_build({'MOCK_SHELL_DSPS': '7'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('ORIG_REF_NAME == rk_cmac_fp16_cell_dsp'), 2)
        self.assertIn('-flatten_hierarchy none', result.stdout)
        for settings, message in [({'MOCK_KERNELS': '15'}, 'sixteen full C32'),
            ({'MOCK_KERNEL_ZERO_DSPS': '31'}, '32 DSP48E1'),
            ({'MOCK_KERNEL_ZERO_DSPS': '33'}, '32 DSP48E1'),
            ({'MOCK_DUPLICATE_KERNEL': '1'}, 'duplicate CMAC')]:
            blocked = self.run_build(settings)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn(message, blocked.stderr)
            self.assertNotIn('EVENT write_checkpoint', blocked.stdout)

    def test_recheck_after_route_before_routed_checkpoint(self):
        result = self.run_build({'MOCK_ROUTED_LAST_DSPS': '31'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('32 DSP48E1', result.stderr)
        self.assertIn('EVENT route_design', result.stdout)
        self.assertEqual(result.stdout.count('EVENT write_checkpoint'), 1)

    def test_only_three_reversible_physical_template_changes(self):
        out = ROOT / 'build/CONTROL_ONLY'; original = baseline.render(self.spec, out, 'a' * 64)
        text = dsp.render(self.spec, out, 'a' * 64)
        changes = [(' -generic LED_ACTIVE_LOW=$active_low',
            ' -generic LED_ACTIVE_LOW=$active_low -flatten_hierarchy none'),
            ('write_checkpoint -force [file join $out post_synth.dcp]',
             dsp.GUARD + '\nwrite_checkpoint -force [file join $out post_synth.dcp]'),
            ('\nroute_design\n', '\nroute_design\nrequire_full_dsp_cmac\n')]
        for before, after in reversed(changes):
            self.assertEqual(text.count(after), 1)
            text = text.replace(after, before)
        self.assertEqual(text, original)

    def test_profile_keeps_original_transport_and_only_changes_cmac_join(self):
        original, _ = dsp.original_inputs()
        self.assertEqual((self.spec['part'], self.spec['clock_period_ns'], self.spec['constraints'],
            self.spec['rom']), (original['part'], 20, original['constraints'], original['rom']))
        self.assertEqual(self.spec['source_profile'], dsp.PROFILE)
        preparation = dsp.gates.replay.preparation
        excluded = {preparation.ORIGINAL_ARRAY, preparation.ORIGINAL_CELL, preparation.JOIN}
        self.assertTrue(set(original['synthesis']) - excluded <= set(self.spec['synthesis']))
        self.assertFalse(excluded & set(self.spec['synthesis']))
        self.assertTrue({str(p.relative_to(ROOT)) for p in
            (preparation.ROWS, preparation.LANE, dsp.gates.array.DSP_CELL, dsp.gates.array.DSP_ARRAY)}
            <= set(self.spec['synthesis']))
        self.assertNotIn(str(dsp.gates.array.FIXED_ARRAY.relative_to(ROOT)), self.spec['synthesis'])
        for path in self.spec['synthesis']:
            self.assertIn(ROOT / path, self.tracked)


class DspEvidenceControls(unittest.TestCase):
    def test_caller_only_module_does_not_change_build_dependency_set(self):
        with TemporaryDirectory(prefix='dsp-vivado-import-control-', dir=ROOT / 'build') as name:
            out = Path(name); join = out / Path(dsp.gates.replay.preparation.JOIN).name
            join.write_text(dsp.gates.replay.preparation.dsp_join((ROOT / dsp.gates.replay.preparation.JOIN).read_text()))
            spec, before = dsp.inputs(out)
            caller_only = ModuleType('unrelated_caller_control')
            caller_only.__file__ = str(ROOT / 'tools/capture_current_backend.py')
            self.assertNotIn(Path(caller_only.__file__), before)
            with patch.dict(sys.modules, {'unrelated_caller_control': caller_only}):
                actual_spec, after = dsp.inputs(out)
            self.assertEqual(actual_spec, spec)
            self.assertEqual(after, before, 'Caller-only imports are not DSP synthesis dependencies')

    def test_full_mapped_binary_metadata_required(self):
        value = mapped_report(); dsp.validate_mapped_metadata(value)
        for key, replacement in [('status', 'RUNNING'), ('stage', 'simulation'), ('finished_utc', ''),
            ('channels', 16), ('kernels', 8), ('parallel_products', 256), ('frames', 207),
            ('expected_outputs', 3312), ('seed', '0'), ('numerical_netlist_binary_fixture_acceptance', False),
            ('expected_result', 'PASS smaller'), ('result', 'PASS smaller'),
            ('kernel_cells', {'DSP48E1': 31}), ('kernel_cells', {'DSP48E1': 32, 'FDCE': 1}),
            ('library_operations', ['create', 'seq_update']), ('export_circuit_identity', 'COUNTS_ONLY'),
            *[(name, True) for name in ('four_state_x_acceptance', 'raw_board_numerical_acceptance',
                'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed')]]:
            bad = deepcopy(value); bad[key] = replacement
            with self.subTest(key=key), self.assertRaises(AssertionError): dsp.validate_mapped_metadata(bad)

    def test_fresh_negative_and_every_completed_command_required(self):
        value = mapped_report()
        for code in (1, -6, 134):
            good = deepcopy(value); good['commands'][-2]['returncode'] = code
            dsp.validate_mapped_metadata(good)
        for code in (None, False, 'nonzero'):
            bad = deepcopy(value); bad['commands'][-2]['returncode'] = code
            with self.subTest(code=code), self.assertRaises(AssertionError): dsp.validate_mapped_metadata(bad)
        for change in ('missing', 'duplicate', 'live', 'negative_zero', 'positive_nonzero'):
            bad = deepcopy(value)
            if change == 'missing': bad['commands'].pop()
            elif change == 'duplicate': bad['commands'].append(bad['commands'][-1])
            elif change == 'live': bad['commands'][-1]['status'] = 'RUNNING'
            elif change == 'negative_zero': bad['commands'][-2]['returncode'] = 0
            else: bad['commands'][-1]['returncode'] = 1
            with self.subTest(change=change), self.assertRaises(AssertionError): dsp.validate_mapped_metadata(bad)

    def test_exact_variant_parent_dispatch_and_snapshot_binding(self):
        with TemporaryDirectory(prefix='dsp-vivado-parent-control-', dir=ROOT / 'build') as name:
            out = Path(name)
            parents = {n: {'MOCK_ONLY': n, 'source': {'sha256': n}} for n in ('area', 'native', 'board', 'mapped')}
            paths = {n: out / (n + '_report.json') for n in parents}
            for n, path in paths.items():
                path.write_text(json.dumps(parents[n]))
                (out / (n + '_snapshot.json')).write_bytes(path.read_bytes())
            (out / 'profile_evidence.json').write_text(json.dumps({n: str(p.relative_to(ROOT)) for n, p in paths.items()}))
            with patch.object(dsp.gates, 'verify_area', return_value=(parents['area'], {}, None)) as area, \
                 patch.object(dsp.gates.replay, 'verify_native', return_value=parents['native']) as native, \
                 patch.object(dsp.gates, 'verify_board', return_value=(parents['board'], {'native': paths['native']}, [])) as board, \
                 patch.object(dsp, 'verify_mapped', return_value=parents['mapped']) as mapped:
                self.assertEqual(dsp.validate_evidence(out), parents)
                area.assert_called_with(paths['area']); native.assert_called_with(paths['native'])
                self.assertEqual(board.call_args.args[0], paths['board'])
                mapped.assert_called_with(paths['mapped'], paths['area'], paths['native'], parents['area'], parents['native'])
                board.return_value = (parents['board'], {'native': paths['mapped']}, [])
                with self.assertRaisesRegex(AssertionError, 'different native'): dsp.validate_evidence(out)
                board.return_value = (parents['board'], {'native': paths['native']}, [])
                (out / 'mapped_snapshot.json').write_text('{}')
                with self.assertRaisesRegex(AssertionError, 'Changed parent'): dsp.validate_evidence(out)

    def test_metadata_paths_and_generated_join_are_fail_closed(self):
        with TemporaryDirectory(prefix='dsp-vivado-source-control-', dir=ROOT / 'build') as name:
            out = Path(name); join = out / Path(dsp.gates.replay.preparation.JOIN).name
            text = dsp.gates.replay.preparation.dsp_join((ROOT / dsp.gates.replay.preparation.JOIN).read_text())
            join.write_text(text + '\n// Extra unreviewed wrapper change\n')
            with self.assertRaises(AssertionError): dsp.inputs(out)
            join.write_text(text)
            (out / 'profile_evidence.json').write_text(json.dumps({'unknown': 'ignored?'}))
            with self.assertRaises(AssertionError): dsp.inputs(out)
        for path in ('/etc/passwd', '../outside', 'build/missing-DSP-variant-report.json'):
            with self.assertRaises(AssertionError): dsp.gates.replay.workspace_path(path)


if __name__ == '__main__': unittest.main()
