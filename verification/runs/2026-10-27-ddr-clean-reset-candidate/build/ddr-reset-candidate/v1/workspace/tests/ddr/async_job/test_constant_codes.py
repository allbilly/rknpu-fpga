"""Mock evidence controls for the selected EW E1-E8 result-code profile."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.hardware.sample_ew import tcl_literal

ROOT=Path(__file__).resolve().parents[3]
MOCK=r'''
set scenario __SCENARIO__
proc get_cells {args} {
    set name [lindex [lindex $args end] 0]
    if {$name eq "job_crossing"} {return $name}
    if {![string match {job_crossing/*} $name]} {return {}}
    if {[regexp {result_held_reg\[([0-9]+)\]$} $name -> bit]} {
        if {$bit>=36 && $bit<=39} {
            if {$::scenario eq "unexpected_high_ff" && $bit==36} {return $name}
            return {}
        }
        if {$::scenario eq "missing_dynamic_bit40" && $bit==40} {return {}}
    }
    if {[regexp {s_result_code_reg\[([0-9]+)\]$} $name -> bit] && $bit>=4 && $bit<=7} {
        if {$::scenario eq "unexpected_high_ff" && $bit==4} {return $name}
        return {}
    }
    return $name
}
proc get_pins {args} {
    set block [lindex $args end]
    if {$block ne "job_crossing"} {error "Unexpected boundary block $block"}
    set pins {}
    foreach bit {4 5 6 7} {
        if {!($::scenario eq "missing_input_pin" && $bit==7)} {
            lappend pins [format {job_crossing/d_result_code[%d]} $bit]
        }
        lappend pins [format {job_crossing/s_result_code[%d]} $bit]
    }
    return $pins
}
proc get_property {property object} {
    if {$property eq "IS_PRIMITIVE"} {
        return [expr {$::scenario eq "primitive_hierarchy"}]
    }
    if {$property eq "REF_PIN_NAME"} {return [lindex [split $object /] end]}
    if {$property eq "DIRECTION"} {
        set ref [lindex [split $object /] end]
        if {[regexp {^d_result_code\[[4-7]\]$} $ref]} {
            return [expr {$::scenario eq "wrong_input_direction" ? "OUT" : "IN"}]
        }
        if {[regexp {^s_result_code\[[4-7]\]$} $ref]} {
            return [expr {$::scenario eq "wrong_child_direction" ? "IN" : "OUT"}]
        }
        if {[string match ui_result_code* $object]} {
            return [expr {$::scenario eq "wrong_output_direction" ? "IN" : "OUT"}]
        }
    }
    if {$property eq "NAME"} {return $object}
    if {$property eq "TYPE"} {
        if {$::scenario eq "signal_net"} {return SIGNAL}
        if {$::scenario eq "power_net"} {return POWER}
        if {$::scenario eq "signal_output_net" && $object eq "output_ground_net"} {return SIGNAL}
        if {$::scenario eq "power_output_net" && $object eq "output_ground_net"} {return POWER}
        return GROUND
    }
    if {$property eq "DRIVER_COUNT"} {
        return [expr {$::scenario eq "two_drivers" ||
            ($::scenario eq "two_output_drivers" && $object eq "output_ground_net") ? 2 : 1}]
    }
    error "Unexpected property $property on $object"
}
proc get_ports {args} {
    set ports {}
    foreach bit {4 5 6 7} {
        if {!($::scenario eq "missing_output_port" && $bit==7)} {
            lappend ports [format {ui_result_code[%d]} $bit]
        }
    }
    return $ports
}
proc get_nets {args} {
    set object [lindex $args end]
    set child_bit4 [format {job_crossing/s_result_code[%d]} 4]
    if {$object eq $child_bit4 && $::scenario eq "connected_child_output"} {return child_output_net}
    if {[regexp {^job_crossing/d_result_code\[[4-7]\]$} $object]} {return input_ground_net}
    if {[regexp {^ui_result_code\[[4-7]\]$} $object]} {return output_ground_net}
    return {}
}
'''


@unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter required')
class ConstantCodeProfileTests(unittest.TestCase):
    def invoke(self,scenario,body):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'constant-profile.tcl'
            mock=MOCK.replace('__SCENARIO__',tcl_literal(scenario))
            script=mock+'\nsource '+tcl_literal(ROOT/'fpga/ddr/async_job_cdc.tcl')+'\n'+body+'\n'
            path.write_text(script)
            return subprocess.run([shutil.which('tclsh'),str(path)],capture_output=True,text=True,timeout=15)

    def test_selected_profile_proves_four_constant_codes_and_64_plus_37_dynamic_bits(self):
        body=r'''
set facts [rk_job_zero_error_codes [rk_job_prefix job_crossing]]
set payloads [rk_job_payloads [rk_job_prefix job_crossing] ew_e1_e8]
set descriptor [lindex $payloads 0]
set result [lindex $payloads 1]
puts "PROFILE ew_e1_e8 descriptor=[llength [lindex $descriptor 1]]/[llength [lindex $descriptor 2]] result=[llength [lindex $result 1]]/[llength [lindex $result 2]] zero_facts=[llength $facts]"
foreach fact $facts {puts [join $fact "\t"]}
puts PASS_MOCK_EW_E1_E8_ONLY
'''
        result=self.invoke('good',body)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PROFILE ew_e1_e8 descriptor=64/64 result=37/37 zero_facts=4',result.stdout)
        facts=[line.split('\t') for line in result.stdout.splitlines() if line.startswith('ZERO_CODE\t')]
        self.assertEqual([row[1] for row in facts],['4','5','6','7'])
        self.assertTrue(all(row[2].endswith(f'd_result_code[{row[1]}]') for row in facts))
        self.assertTrue(all(row[4].endswith(f'ui_result_code[{row[1]}]') for row in facts))
        self.assertIn('PASS_MOCK_EW_E1_E8_ONLY',result.stdout)

    def test_default_full8_stays_strict_and_unrecognized_profile_fails(self):
        cases=[('good','rk_job_payloads [rk_job_prefix job_crossing] full8','crossing register result_held_reg[36]'),
               ('good','rk_job_payloads [rk_job_prefix job_crossing] unknown','Unsupported job result mapping profile')]
        for scenario,body,message in cases:
            with self.subTest(body=body):
                result=self.invoke(scenario,body)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn(message,result.stderr)
                self.assertNotIn('PASS_MOCK_EW_E1_E8_ONLY',result.stdout)

    def test_actual_pin_port_direction_and_ground_proofs_are_mandatory(self):
        cases=(
            ('missing_input_pin','Expected exactly one job boundary pin d_result_code[7]'),
            ('missing_output_port','Expected exactly one observable EW error-code port'),
            ('wrong_input_direction','Changed folded error boundary direction'),
            ('wrong_child_direction','Changed folded error boundary direction'),
            ('wrong_output_direction','Wrong observable error-code direction'),
            ('signal_net','EW source error bit4 is not a proved single-driver constant zero'),
            ('power_net','EW source error bit4 is not a proved single-driver constant zero'),
            ('two_drivers','EW source error bit4 is not a proved single-driver constant zero'),
            ('signal_output_net','EW output error bit4 is not a proved single-driver constant zero'),
            ('power_output_net','EW output error bit4 is not a proved single-driver constant zero'),
            ('two_output_drivers','EW output error bit4 is not a proved single-driver constant zero'),
            ('connected_child_output','Folded child error output unexpectedly connected'),
            ('unexpected_high_ff','Expected explicitly folded error register'),
            ('missing_dynamic_bit40','Expected exactly one crossing register result_held_reg[40]'),
            ('primitive_hierarchy','Folded EW job must be hierarchical'),
        )
        for scenario,message in cases:
            with self.subTest(scenario=scenario):
                result=self.invoke(scenario,'rk_job_payloads [rk_job_prefix job_crossing] ew_e1_e8')
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn(message,result.stderr)
                self.assertNotIn('PASS_MOCK_EW_E1_E8_ONLY',result.stdout)


if __name__=='__main__':unittest.main()
