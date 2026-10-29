"""Fixed-source build/evidence controls. All Vivado calls are MOCKED."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
sys.path.insert(0, str(ROOT / 'tests/cmac'))
import test_array_build as baseline
import test_fixed_array_board_control as board_controls
import vivado_fixed_array as fixed
from evidence import fingerprint


class FixedArrayBuildControl(baseline.ArrayBuildControl):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory = tempfile.TemporaryDirectory(prefix='fixed-build-controls-', dir=ROOT / 'build')
        out = Path(cls.directory.name)
        (out / Path(fixed.JOIN).name).write_text(fixed.fixed_join((ROOT / fixed.JOIN).read_text()))
        cls.spec, _ = fixed.inputs(out)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_incomplete_board_evidence_rejected(self):
        for status in ('RUNNING', 'FAIL', 'PASS_RAW_ARRAY_BOARD_FULL_RTL_ONLY',
                       'PASS_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_ONLY',
                       'PASS_FIXED_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_EXPERIMENT_ONLY'):
            with self.assertRaisesRegex(AssertionError, 'own completed nine-mode'):
                fixed.verify_board({'status': status}, {'MOCK': 'native'})


class FixedEvidenceControl(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='fixed-evidence-controls-', dir=ROOT / 'build')
        self.out = Path(self.directory.name)
        self.join = self.out / Path(fixed.JOIN).name
        self.join.write_text(fixed.fixed_join((ROOT / fixed.JOIN).read_text()))
        self.native = {'MOCK': 'Not HDL evidence; run separately requires a verified full native report'}
        self.snapshot = self.out / 'fixed_report_snapshot.json'
        self.snapshot.write_text(json.dumps(self.native))
        spec = json.loads(fixed.SPEC.read_text())
        sources = fixed.simulation_sources(spec, self.join)
        self.tracked = sources + [ROOT / name for name in (spec['bench'], spec['rom'], spec['constraints'], str(fixed.SPEC.relative_to(ROOT)), fixed.JOIN)] + [self.snapshot]
        log = self.out / 'MOCK.log'; log.write_text('Synthetic control fixture; no HDL tools executed\n')
        self.report = dict(status='PASS_FIXED_RAW_ARRAY_BOARD_FOUR_STATE_RTL_EXPERIMENT_ONLY', suite='fixed-iverilog',
                           tool_version='Icarus Verilog MOCK', channels=32, kernels=16, parallel_products=512,
                           row_formal_status_at_start=fixed.ROW_FORMAL, four_state_mode_not_run=None,
                           bitstream_emitted=False, hardware_programmed=False,
                           tests=[dict(mode=mode, status='PASS', result=board_controls.result(mode)) for mode in range(9)],
                           commands=[dict(status='PASS', returncode=0, log=name + '.log') for name in
                                     ('rom_check', 'version', 'runtime_version', 'compile', *('mode' + str(mode) for mode in range(9)))],
                           simulation_sources=[str(path.relative_to(ROOT)) for path in sources],
                           source=fingerprint(self.tracked), artifacts=fingerprint([log]))

    def tearDown(self):
        self.directory.cleanup()

    def test_complete_metadata_fixture_only(self):
        self.assertIs(fixed.verify_board(self.report, self.native), self.report)

    def test_all_nine_modes_required(self):
        for tests in (self.report['tests'][:-1], self.report['tests'] + self.report['tests'][:1],
                      self.report['tests'][:-1] + self.report['tests'][:1]):
            with self.assertRaisesRegex(AssertionError, 'All nine'):
                fixed.verify_board(dict(self.report, tests=tests), self.native)

    def test_shape_tool_and_proof_gates(self):
        for key, value in (('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('suite', 'two-state'), ('tool_version', 'Verilator MOCK'),
                           ('row_formal_status_at_start', 'RUNNING'), ('four_state_mode_not_run', 7),
                           ('bitstream_emitted', True), ('hardware_programmed', True)):
            with self.assertRaises(AssertionError, msg=key):
                fixed.verify_board(dict(self.report, **{key: value}), self.native)

    def test_counts_and_command_completion_gates(self):
        for changes in ({'result': board_controls.result(0).replace('check=4096', 'check=4095')}, {'status': 'RUNNING'}):
            tests = copy.deepcopy(self.report['tests']); tests[0].update(changes)
            with self.assertRaises(AssertionError):
                fixed.verify_board(dict(self.report, tests=tests), self.native)
        for commands in ([], self.report['commands'][:-1], [dict(self.report['commands'][0], returncode=1)]):
            with self.assertRaises(AssertionError):
                fixed.verify_board(dict(self.report, commands=commands), self.native)

    def test_every_build_input_covered(self):
        for name in ('tests/cmac/tb_cmac_array_bram_demo.sv', 'tests/cmac/array_data/board_rom.hex',
                     'fpga/ypcb.xdc', str(fixed.SPEC.relative_to(ROOT)), fixed.JOIN):
            source = fingerprint([path for path in self.tracked if str(path.relative_to(ROOT)) != name])
            with self.assertRaisesRegex(AssertionError, 'Untested fixed build'):
                fixed.verify_board(dict(self.report, source=source), self.native)
        with self.assertRaisesRegex(AssertionError, 'Tested source list'):
            fixed.verify_board(dict(self.report, simulation_sources=self.report['simulation_sources'][:-1]), self.native)

    def test_only_one_audited_wrapper_substitution(self):
        self.join.write_text(self.join.read_text().replace('assign in_ready=group_ready&&!error;', 'assign in_ready=group_ready;'))
        altered = dict(self.report, source=fingerprint(self.tracked))
        with self.assertRaisesRegex(AssertionError, 'Tested fixed wrapper changed'):
            fixed.verify_board(altered, self.native)
        with self.assertRaisesRegex(AssertionError, 'single audited substitution'):
            fixed.inputs(self.out)

    def test_native_snapshot_binding(self):
        self.snapshot.write_text(json.dumps({'MOCK': 'different native parent'}))
        with self.assertRaisesRegex(AssertionError, 'did not use this completed'):
            fixed.verify_board(dict(self.report, source=fingerprint(self.tracked)), self.native)

    def test_profile_evidence_paths_fail_closed(self):
        for name in ('/etc/passwd', '../outside', 'build/missing-control-evidence.json'):
            with self.assertRaises(AssertionError):
                fixed.inside(name)
        metadata = self.out / 'profile_evidence.json'; metadata.write_text(json.dumps({'unexpected': 'ignored?'}))
        with self.assertRaises(AssertionError):
            fixed.inputs(self.out)

    def test_synthesis_profile_not_baseline(self):
        spec, tracked = fixed.inputs(self.out)
        self.assertEqual(spec['source_profile'], fixed.PROFILE)
        self.assertEqual((spec['part'], spec['clock_period_ns']), ('xc7k480tffg1156-2', 20))
        self.assertIn(str(self.join.relative_to(ROOT)), spec['synthesis'])
        for name in (fixed.ROWS, fixed.CELL, fixed.ARRAY):
            self.assertIn(name, spec['synthesis'])
        for name in ('rtl/cmac/rk_cmac_fp16_cell.sv', 'rtl/cmac/rk_cmac_fp16_array.sv', fixed.JOIN):
            self.assertNotIn(name, spec['synthesis'])
            self.assertIn(ROOT / name, tracked)  # comparison provenance, not synthesized
        script = baseline.render(spec, self.out, 'a' * 64)
        for name in spec['synthesis']:
            self.assertIn('read_verilog -sv {' + str(ROOT / name) + '}', script)
        self.assertNotIn('write_bitstream', script)


if __name__ == '__main__':
    unittest.main()
