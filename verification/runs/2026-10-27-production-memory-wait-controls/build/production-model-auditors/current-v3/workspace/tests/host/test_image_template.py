"""Mock native image-emission gates. No Vivado, device or programmable image."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile
import unittest

from tools.host.image_template import render
from tools.hardware.sample_ew import tcl_literal


MOCK = r'''
proc current_design {} {return design}
proc open_checkpoint {path} {}
proc get_waivers {} {if {$::scenario eq "waiver"} {return waiver0};return {}}
proc report_route_status {args} {
    if {[lindex $args end] eq "ROUTED_FULLY"} {return [expr {$::scenario ne "unrouted"}]}
    return [expr {$::scenario eq "route_error"}]
}
proc get_ports {args} {
    if {[llength $args] == 0} {
        set ports {SYS_CLK led_3bits_tri_o[0] led_3bits_tri_o[1] led_3bits_tri_o[2]}
        if {$::scenario eq "ports"} {lappend ports R28}
        return $ports
    }
    return [lindex $args end]
}
proc get_clocks {args} {
    if {[lindex $args end] eq "sys_clk"} {return sys_clk}
    if {$::scenario eq "clock_count"} {return sys_clk}
    return {sys_clk jtag_tck}
}
proc get_pins {args} {return {}}
proc get_nets {args} {return {}}
proc get_property {key object} {
    set f $::scenario
    if {$key eq "NAME"} {if {$object eq "sys_clk" && $f eq "clock_name"} {return other};return $object}
    switch -- $key {
        JTAG_CHAIN {if {$f eq "bscan_chain"} {return 1};return 2}
        INIT {if {$f eq "init"} {return "1'b1"};return "1'b0"}
        REF_NAME {return FDRE}
        PART {if {$f eq "part"} {return xc7k325tffg900-2};return xc7k480tffg1156-2}
        TOP {if {$f eq "top"} {return ypcb_ew_startup_top};return ypcb_jtag_ew_top}
        CONFIG_VOLTAGE {if {$f eq "voltage"} {return 3.3};return 1.8}
        CFGBVS {if {$f eq "cfgbvs"} {return VCCO};return GND}
        PERIOD {if {$f eq "period"} {return 40.0};return 20.0}
        WAVEFORM {if {$f eq "waveform"} {return {0.000 5.000}};return {0.000 10.000}}
        PACKAGE_PIN {
            if {$f eq "pin"} {return R28}
            return [dict get [dict create SYS_CLK AA28 {led_3bits_tri_o[0]} P30 {led_3bits_tri_o[1]} M30 {led_3bits_tri_o[2]} N30] $object]
        }
        IOSTANDARD {if {$f eq "standard"} {return LVCMOS33};return LVCMOS18}
        DIRECTION {if {$f eq "direction"} {return INOUT};if {$object eq "SYS_CLK"} {return IN};return OUT}
        SLACK {if {$f eq "nan"} {return NaN};if {$f eq "negative_slack"} {return -0.001};return 0.057}
        SEVERITY {if {$f eq "drc_error" || ($f eq "bitstream_error" && $::deck eq "bitstream_checks")} {return Error};return Warning}
    }
    error "Unexpected property $key"
}
proc get_timing_paths {args} {if {$::scenario eq "missing_timing"} {return {}};return path0}
proc check_timing {args} {
    set check [lindex $args 1]
    if {$::scenario eq "internal_missing"} {return "checking $check (0)"}
    if {$::scenario eq "internal"} {return "checking $check (1)\n There are 1 pins that are not constrained"}
    return "checking $check (0)\n There are 0 pins that are not constrained"
}
proc report_pulse_width {args} {
    if {$::scenario eq "pulse_missing"} {return "No clock pulse checks"}
    set slack [expr {$::scenario eq "pulse" ? -0.1 : 9.6}]
    return "Min Period n/a RAMB36/CLK n/a 2.095 20.0 17.905 site pin\nLow Pulse Width Slow FDRE/C n/a 0.4 10.0 $slack site pin\nHigh Pulse Width Slow FDRE/C n/a 0.35 10.0 9.65 site pin"
}
proc get_cells {args} {
    set filter [lindex $args end]
    set n 1
    if {[string first "RAMB" $filter]>=0} {set n 256}
    if {[string first "startup/" $filter]>=0} {set n 65}
    if {$::scenario eq "reduced" && $n==256} {incr n -1}
    if {$::scenario eq "startup_count" && $n==65} {incr n -1}
    if {$::scenario eq "bscan_count" && [string first "BSCANE2" $filter]>=0} {set n 0}
    set result {};for {set i 0} {$i<$n} {incr i} {lappend result cell$i};return $result
}
proc report_drc {args} {set ::deck [lindex $args 1]}
proc get_drc_violations {} {
    set f $::scenario
    if {$::deck eq "bitstream_checks"} {
        if {$f eq "bitstream_error"} {return {NSTD-1#1}}
        if {$f eq "bitstream_warning_new"} {return {REQP-1839#1}}
        return {}
    }
    set result {}
    foreach {rule count} {DPIP-1 2 DPOP-1 1 DPOP-2 1} {
        for {set i 1} {$i<=$count} {incr i} {lappend result $rule#$i}
    }
    if {$f eq "drc_new"} {lappend result REQP-1839#1}
    if {$f eq "drc_missing"} {set result [lrange $result 1 end]}
    return $result
}
proc set_property {key value object} {
    if {$key ne "BITSTREAM.CONFIG.USR_ACCESS" || $value ne "0x3a0ef75f"} {error "Forbidden implementation/property mutation"}
}
proc write_checkpoint {path} {set f [open $path w];puts $f SYNTHETIC_NOT_A_CHECKPOINT;close $f}
proc write_bitstream {path} {set f [open $path w];puts $f SYNTHETIC_NOT_A_BITSTREAM;close $f}
'''


@unittest.skipUnless(shutil.which('tclsh') and shutil.which('sha256sum'), 'Mocked Tcl and SHA utility required')
class HostImageTemplateTests(unittest.TestCase):
    def invoke(self, scenario):
        with tempfile.TemporaryDirectory(prefix='image {;} control ') as directory:
            root = Path(directory)
            item = root/'qualified {input}; backslash\\ newline\n.txt'
            item.write_text('synthetic qualified-input fixture\n')
            expected = hashlib.sha256(item.read_bytes()).hexdigest()
            target = root/'image output'
            cdc = root/'cdc.tcl'
            cdc.write_text('proc rk_host_one {items label} {if {[llength $items]!=1} {error count};return [lindex $items 0]}\n'
                           'proc rk_host_cdc_audit {out} {if {$::scenario eq "cdc"} {error "CDC rejected"}}\n')
            body = render(root/'synthetic.dcp', target, {str(item): expected}, cdc, '3a0ef75f')
            if scenario == 'input_changed':
                item.write_bytes(item.read_bytes()+b'\n')
            if scenario == 'output_exists':
                target.mkdir()
            script = root/'mock.tcl'
            script.write_text('set ::scenario '+tcl_literal(scenario)+'\n'+MOCK+'\n'+body)
            result = subprocess.run([shutil.which('tclsh'), str(script)], text=True, capture_output=True, timeout=15)
            return result, (target/'host-user2-ew.bit').exists()

    def test_exact_profile_emits_only_synthetic_files(self):
        result, bit = self.invoke('good')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertIn('PASS_SOURCE_REVIEWED_USER2_EW_BITSTREAM_EMISSION', result.stdout)
        self.assertTrue(bit)

    def test_every_failed_native_gate_blocks_emission(self):
        for scenario in ['part', 'top', 'voltage', 'cfgbvs', 'ports', 'pin', 'standard', 'direction',
                         'clock_count', 'clock_name', 'period', 'waveform', 'negative_slack', 'nan',
                         'missing_timing', 'pulse', 'pulse_missing', 'internal', 'internal_missing',
                         'unrouted', 'route_error', 'waiver', 'reduced', 'bscan_count', 'bscan_chain', 'startup_count', 'init', 'cdc', 'drc_error',
                         'drc_new', 'drc_missing', 'bitstream_error', 'bitstream_warning_new',
                         'input_changed', 'output_exists']:
            with self.subTest(scenario=scenario):
                result, bit = self.invoke(scenario)
                self.assertNotEqual(result.returncode, 0, scenario)
                self.assertFalse(bit, scenario)
                self.assertNotIn('PASS_SOURCE_REVIEWED_USER2_EW_BITSTREAM_EMISSION', result.stdout)

    def test_no_hardware_route_or_severity_mutation_commands(self):
        text = render('synthetic.dcp', 'synthetic-output', {'fixture': 'a'*64}, 'cdc.tcl', '3a0ef75f')
        for forbidden in ['open_hw_manager', 'program_hw', 'route_design', 'place_design', 'synth_design',
                          'set_false_path', 'set_max_delay', 'set_property SEVERITY']:
            self.assertNotIn(forbidden, text)

    def test_empty_or_malformed_hashes_reject(self):
        for inputs in [{}, {'fixture': 'bad'}, {'fixture': 'a'*63}]:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                render('synthetic.dcp', 'output', inputs, 'cdc.tcl', '3a0ef75f')


if __name__ == '__main__':
    unittest.main()
