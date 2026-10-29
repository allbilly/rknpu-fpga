"""Mocked checkpoint-build control tests. No HDL or Vivado execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
sys.path.insert(0, str(ROOT / 'tests'))
from vivado_array import inputs, render, tcl_path, verify_full_board
from test_fpga_build import HARNESS

EXTRA = r'''
proc current_fileset {} { return sources_1 }
proc get_parts {args} { if {[mock MOCK_NO_PART 0]} {return {}}; return xc7k480tffg1156-2 }
proc get_clocks {args} { if {[mock MOCK_NO_CLOCK 0]} {return {}}; return sys_clk }
proc report_pulse_width {args} { event report_pulse_width {*}$args }
'''
HARNESS = HARNESS.replace('proc get_property {name object} {',
    'proc get_property {name object} {\n    if {$name eq "PERIOD"} { return [mock MOCK_PERIOD 20.000] }')
HARNESS = HARNESS.replace('set ::properties {}', EXTRA+'\nset ::properties {}')

class ArrayBuildControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tclsh = shutil.which(os.environ.get('RK_TEST_TCLSH', 'tclsh'))
        if cls.tclsh is None:
            raise RuntimeError('UNAVAILABLE: Tcl interpreter')
        cls.spec, _ = inputs()
        version = subprocess.run([cls.tclsh], input='puts [info patchlevel]\n', text=True, capture_output=True, check=True).stdout.strip()
        print(f'C32 array build-control tests: Tcl {version}; all Vivado calls MOCKED', flush=True)

    def run_build(self, settings=None):
        env = {k:v for k,v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        env.update(RK_CONFIRM_BOARD='YPCB_00338_1P1', RK_ARRAY_SOURCE_SHA='a'*64)
        env.update(settings or {})
        with tempfile.TemporaryDirectory(prefix='rk-array-build-control-') as directory:
            dest = Path(directory)
            script = dest / 'build.tcl'
            script.write_text(render(self.spec, dest / 'out', 'a'*64))
            env['RK_TEST_BUILD_SCRIPT'] = str(script)
            result = subprocess.run([self.tclsh], input=HARNESS, env=env, cwd=directory,
                                    text=True, capture_output=True, timeout=10)
            self.assertFalse(list(dest.rglob('*.bit')))
            self.assertFalse(list(dest.rglob('*.dcp')))
        self.assertNotIn('EVENT write_bitstream', result.stdout)
        return result

    def blocked(self, settings, message, early=False):
        result = self.run_build(settings)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        if early:
            self.assertNotIn('EVENT create_project', result.stdout)

    def test_checkpoint_sources_and_no_programming(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        for path in self.spec['synthesis']:
            self.assertIn('EVENT read_verilog -sv '+str(ROOT / path), result.stdout)
        self.assertEqual(result.stdout.count('EVENT read_verilog '), len(self.spec['synthesis']))
        self.assertIn('synth_design -top ypcb_cmac_array_top -part xc7k480tffg1156-2', result.stdout)
        self.assertIn('EVENT report_pulse_width ', result.stdout)
        self.assertIn('EVENT route_design', result.stdout)
        self.assertNotIn('EVENT set_property CONFIG_VOLTAGE', result.stdout)

    def test_gates_before_project(self):
        for settings, message in [({'RK_ARRAY_SOURCE_SHA':'wrong'}, 'completed matching'),
                                  ({'RK_CONFIRM_BOARD':''}, 'RK_CONFIRM_BOARD'),
                                  ({'RK_EMIT_BITSTREAM':'1'}, 'disabled'),
                                  ({'MOCK_NO_PART':'1'}, 'support is unavailable')]:
            self.blocked(settings, message, True)

    def test_boolean_validation(self):
        for key in ('RK_LED_ACTIVE_LOW', 'RK_EMIT_BITSTREAM'):
            for value in ('', 'yes', '2', '-1'):
                self.blocked({key:value}, key+' must be 0 or 1', True)

    def test_electrical_pairs(self):
        for settings in ({'RK_CONFIG_VOLTAGE':'1.8'}, {'RK_CFGBVS':'GND'}):
            self.blocked(settings, 'Supply both board-verified', True)
        for voltage, strap in (('1.8','VCCO'), ('3.3','GND')):
            self.blocked({'RK_CONFIG_VOLTAGE':voltage,'RK_CFGBVS':strap}, 'Incompatible', True)
        for voltage, strap in (('1.5','GND'),('1.8','GND'),('2.5','VCCO'),('3.3','VCCO')):
            result = self.run_build({'RK_CONFIG_VOLTAGE':voltage,'RK_CFGBVS':strap})
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('CONFIG_VOLTAGE', 'CFGBVS'):
                assignment = result.stdout.index('EVENT set_property '+name)
                self.assertLess(assignment, result.stdout.index('EVENT write_checkpoint'))
                self.assertLess(assignment, result.stdout.index('EVENT report_drc'))

    def test_clock_and_bram(self):
        self.blocked({'MOCK_NO_CLOCK':'1'}, 'exactly one sys_clk')
        self.blocked({'MOCK_NO_BRAM':'1'}, 'No block RAM inferred')
        for value in ('10', '40', 'NaN', 'Inf', '', 'unknown'):
            self.blocked({'MOCK_PERIOD':value}, '20.000 ns')
        for value in ('20', '20.0', '20.000'):
            result = self.run_build({'MOCK_PERIOD':value})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_timing_fails_closed(self):
        for kind in ('MAX','MIN'):
            self.blocked({'MOCK_EMPTY_'+kind:'1'}, 'No '+kind.lower()+' timing paths')
            self.blocked({'MOCK_SLACK_'+kind:'-0.001'}, 'Negative '+kind.lower()+' slack')
            for value in ('', 'NaN', 'Inf', '-Inf', '1e9999', 'N/A'):
                self.blocked({'MOCK_SLACK_'+kind:value}, 'Invalid '+kind.lower()+' slack')

    def test_drc_fails_closed(self):
        for value in ('Error','Critical Warning','Fatal','','unknown'):
            self.blocked({'MOCK_DRC_SEVERITY':value}, 'Blocking DRC violation')
        for value in ('Warning','Advisory','Info'):
            result = self.run_build({'MOCK_DRC_SEVERITY':value})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_tcl_paths(self):
        self.assertEqual(tcl_path('/path with spaces/$name'), '{/path with spaces/$name}')
        for value in ('bad{path', 'bad}path', 'bad\\path', 'bad\npath'):
            with self.assertRaises(ValueError):
                tcl_path(value)

    def test_incomplete_board_evidence_rejected(self):
        with tempfile.TemporaryDirectory(prefix='rk-array-evidence-gate-') as directory:
            path = Path(directory) / 'mock.json'
            for status in ('RUNNING','FAIL','PASS_RAW_ARRAY_BOARD_SMOKE_RTL_ONLY','PASS_RAW_ARRAY_CORE_FULL_ONLY',
                           'PASS_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_ONLY'):
                path.write_text(json.dumps({'status':status}))
                with self.assertRaisesRegex(AssertionError, 'FULL board'):
                    verify_full_board(path, self.spec)

if __name__ == '__main__':
    unittest.main()
