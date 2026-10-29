"""Mock Tcl admission failures; these controls never invoke Vivado/hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tools.hardware.sample_ew import tcl_literal

ROOT=Path(__file__).resolve().parents[2]
MOCK=r'''
proc get_cells {args} {
    set filter [lindex $args end]
    if {[string first "ORIG_REF_NAME" $filter]>=0} {
        set count [expr {$::scenario eq "kernels" ? 15 : 16}]
        set result {};for {set i 0} {$i<$count} {incr i} {lappend result k$i};return $result
    }
    if {[string first "DSP48E1" $filter]>=0} {
        set result {}
        for {set k 0} {$k<16} {incr k} {for {set i 0} {$i<32} {incr i} {
            if {$::scenario eq "missing_dsp" && $k==0 && $i==0} {continue}
            lappend result k$k/d$i
        }}
        return $result
    }
    if {[string first "RAMB" $filter]>=0} {
        set count [expr {$::scenario eq "ram_missing" ? 255 : 256}]
        set result {};for {set i 0} {$i<$count} {incr i} {lappend result ram$i};return $result
    }
    if {[string first "child_release_reg" $filter]>=0} {
        if {$::scenario eq "missing_child"} {return {}}
        return child_release_reg
    }
    if {[string first "rst_n_reg" $filter]>=0} {return global_release_reg}
    if {[string first "startup/*" $filter]>=0} {
        set count [expr {$::scenario eq "startup_count" ? 64 : 65}]
        set result {};for {set i 0} {$i<$count} {incr i} {lappend result startup$i};return $result
    }
    error "Unexpected cell query $filter"
}
proc get_property {key object} {
    switch -- $key {
        NAME {return $object}
        REF_NAME {
            if {[string first ram $object]==0} {return [expr {$::scenario eq "ram_half_capacity" ? "RAMB18E1" : "RAMB36E1"}]}
            if {$::scenario eq "reset_latch"} {return LDCE}
            return FDRE
        }
        INIT {return [expr {$::scenario eq "startup_init" ? "1'b1" : "1'b0"}]}
    }
    error "Unexpected property $key"
}
proc get_pins {args} {return [lindex $args end]}
proc get_clocks {args} {
    if {[lindex $args 0] eq "-of_objects"} {return [expr {$::scenario eq "reset_clock" ? "jtag_tck" : "sys_clk"}]}
    return [lindex $args end]
}
proc all_fanin {args} {
    if {$::scenario eq "state_decode"} {return {state_reg/C global_release_reg/C}}
    if {$::scenario eq "child_not_driving"} {return global_release_reg/C}
    if {$::scenario eq "empty_cone"} {return {}}
    return {child_release_reg/C global_release_reg/C}
}
set pulse {Clock Name:         jtag_tck
Min Period        n/a BUFG/I n/a 1.408 166.666 165.258 site pin
Low Pulse Width   Slow FDRE/C n/a 0.400 83.333 82.933 site pin
High Pulse Width  Slow FDRE/C n/a 0.350 83.333 82.983 site pin
Clock Name:         sys_clk
Min Period        n/a RAMB36/CLK n/a 2.340 20.000 17.660 site pin
Low Pulse Width   Slow FDRE/C n/a 0.400 10.000 9.600 site pin
High Pulse Width  Slow FDRE/C n/a 0.350 10.000 9.650 site pin
}
switch -- $::scenario {
    pulse_negative {set pulse [string map {9.600 -0.001} $pulse]}
    pulse_nan {set pulse [string map {9.600 NaN} $pulse]}
    pulse_missing {set pulse [string map {{High Pulse Width  Slow FDRE/C n/a 0.350 10.000 9.650 site pin} {}} $pulse]}
    pulse_duplicate {append pulse "High Pulse Width  Slow FDRE/C n/a 0.350 10.000 9.650 site pin\n"}
    pulse_clock {set pulse [string map {sys_clk other_clk} $pulse]}
}
'''


@unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter required')
class FpgaCheckTests(unittest.TestCase):
    def invoke(self,scenario):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'checks.tcl'
            text='set ::scenario '+tcl_literal(scenario)+'\n'+MOCK+'\n'
            text+='source '+tcl_literal(ROOT/'fpga/host/mailbox_cdc.tcl')+'\n'
            text+='source '+tcl_literal(ROOT/'fpga/tinystories/checks.tcl')+'\n'
            text+='rk_dual_full512\nrk_dual_registered_reset '+tcl_literal(directory)+' mock\n'
            text+='rk_dual_pulse_gate $pulse\nputs PASS_MOCK_DUAL_NATIVE_CHECKS\n'
            path.write_text(text)
            return subprocess.run([shutil.which('tclsh'),str(path)],capture_output=True,text=True,timeout=15)

    def test_reviewed_mock_geometry_reset_and_both_clock_pulses_pass(self):
        result=self.invoke('good')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stderr,'')
        self.assertIn('PASS_MOCK_DUAL_NATIVE_CHECKS',result.stdout)

    def test_reduced_target_unsafe_reset_and_bad_pulses_reject(self):
        for scenario in ('kernels','missing_dsp','ram_missing','ram_half_capacity','missing_child','reset_latch',
                         'reset_clock','state_decode','child_not_driving','empty_cone','startup_count','startup_init',
                         'pulse_negative','pulse_nan','pulse_missing','pulse_duplicate','pulse_clock'):
            with self.subTest(scenario=scenario):
                result=self.invoke(scenario)
                self.assertNotEqual(result.returncode,0,scenario)
                self.assertNotIn('PASS_MOCK_DUAL_NATIVE_CHECKS',result.stdout)


if __name__=='__main__':unittest.main()
