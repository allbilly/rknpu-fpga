"""Emission admission failures, with synthetic files and mocked native APIs."""
from pathlib import Path
import hashlib
import runpy
import shutil
import subprocess
import tempfile
import unittest

from tools.hardware.sample_ew import tcl_literal
from tools.tinystories.image_template import render

ROOT = Path(__file__).resolve().parents[2]
MOCK = runpy.run_path(str(ROOT/'tests/host/test_image_template.py'))['MOCK']
MOCK = MOCK.replace('return ypcb_jtag_ew_top', 'return ypcb_tinystories_top')
MOCK = MOCK.replace('0x3a0ef75f', '0x1e01179c')
MOCK = MOCK.replace('set n 1\n', 'set n 1\n    if {[string first "DSP48E1" $filter]>=0} {set n 516}\n')
MOCK = MOCK.replace('DPIP-1 2 DPOP-1 1 DPOP-2 1', 'DPIP-1 1032 DPOP-1 516 DPOP-2 516')
MOCK += r'''
rename get_cells original_get_cells
proc get_cells {args} {
    if {[string first "child_release_reg" [lindex $args end]]>=0} {return child}
    if {[string first "rst_n_reg" [lindex $args end]]>=0} {return global}
    return [original_get_cells {*}$args]
}
rename get_property original_get_property
proc get_property {key object} {
    if {$key eq "INIT" && $object eq "child"} {
        return [expr {$::scenario eq "child_init" ? "1'b0" : "1'b1"}]
    }
    if {$key eq "INIT" && $object eq "global" && $::scenario eq "global_init"} {return "1'b1"}
    return [original_get_property $key $object]
}
'''


@unittest.skipUnless(shutil.which('tclsh') and shutil.which('sha256sum'), 'Tcl/SHA utility required')
class DualImageTests(unittest.TestCase):
    def invoke(self, scenario):
        with tempfile.TemporaryDirectory(prefix='dual image {;} ') as directory:
            root = Path(directory)
            item = root/'input newline\n\\.txt'
            item.write_bytes(b'qualified synthetic input')
            digest = hashlib.sha256(item.read_bytes()).hexdigest()
            cdc = root/'cdc.tcl'
            cdc.write_text('proc rk_host_one {items label} {return [lindex $items 0]}\n'
                           'proc rk_host_cdc_audit {out} {if {$::scenario eq "cdc"} {error CDC}}\n')
            # Actual geometry/reset/pulse implementations have independent
            # negative controls in test_fpga_checks.py. Verify they are called.
            checks = root/'checks.tcl'
            checks.write_text('''
proc rk_dual_full512 {} {if {$::scenario eq "geometry"} {error geometry}}
proc rk_dual_registered_reset {out stage} {if {$::scenario eq "reset_cone"} {error reset}}
proc rk_dual_pulse_gate {text} {if {$::scenario in {pulse pulse_missing}} {error pulse}}
''')
            target = root/'image'
            body = render(root/'synthetic.dcp', target, {str(item): digest}, cdc, checks, '1e01179c')
            if scenario == 'input_changed':
                item.write_bytes(b'changed')
            if scenario == 'output_exists':
                target.mkdir()
            script = root/'mock.tcl'
            script.write_text('set ::scenario '+tcl_literal(scenario)+'\n'+MOCK+'\n'+body)
            result = subprocess.run([shutil.which('tclsh'), str(script)], capture_output=True, text=True, timeout=15)
            return result, (target/'tinystories-full512-dual.bit').exists()

    def test_exact_mock_profile_and_all_failed_gates(self):
        result, bit = self.invoke('good')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue(bit)
        for scenario in ('part', 'top', 'voltage', 'cfgbvs', 'ports', 'pin', 'standard', 'direction',
                         'clock_count', 'clock_name', 'period', 'waveform', 'negative_slack', 'nan',
                         'missing_timing', 'pulse', 'pulse_missing', 'internal', 'internal_missing',
                         'unrouted', 'route_error', 'waiver', 'reduced', 'bscan_count', 'bscan_chain',
                         'startup_count', 'init', 'child_init', 'global_init', 'cdc', 'geometry', 'reset_cone',
                         'drc_error', 'drc_new', 'drc_missing', 'bitstream_error', 'bitstream_warning_new',
                         'input_changed', 'output_exists'):
            with self.subTest(scenario=scenario):
                result, bit = self.invoke(scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertFalse(bit)

    def test_no_implementation_hardware_or_severity_mutation(self):
        text = render('in.dcp', 'out', {'fixture': 'a'*64}, 'cdc.tcl', 'checks.tcl', '1e01179c')
        for command in ('open_hw_manager', 'program_hw', 'route_design', 'place_design', 'synth_design',
                        'set_false_path', 'set_max_delay', 'set_property SEVERITY'):
            self.assertNotIn(command, text)


if __name__ == '__main__':
    unittest.main()
