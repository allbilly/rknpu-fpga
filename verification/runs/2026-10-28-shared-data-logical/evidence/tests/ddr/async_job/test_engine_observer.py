"""Reject unproved folded codes when the observer is an engine boundary."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.ddr.async_job.test_constant_codes import MOCK
from tools.hardware.sample_ew import tcl_literal

ROOT=Path(__file__).resolve().parents[3]
# Retain the independent pin/net failure scenarios from the top-port controls.
ENGINE_MOCK=MOCK.replace('job_crossing','engine/job_crossing')+r'''
rename get_cells mock_get_cells
proc get_cells {args} {
    if {[lindex [lindex $args end] 0] eq "engine/wrong_child"} {return engine/wrong_child}
    if {[lindex [lindex $args end] 0] eq "engine"} {
        if {$::scenario eq "missing_engine"} {return {}}
        return engine
    }
    return [mock_get_cells {*}$args]
}
rename get_pins mock_get_pins
proc get_pins {args} {
    if {[lindex $args end] eq "engine"} {
        set pins {}
        foreach bit {4 5 6 7} {
            if {!($::scenario eq "missing_engine_pin" && $bit==7)} {
                lappend pins [format {engine/ui_result_code[%d]} $bit]
            }
        }
        return $pins
    }
    return [mock_get_pins {*}$args]
}
rename get_property mock_get_property
proc get_property {property object} {
    if {$property eq "REF_NAME" && $object eq "engine"} {
        return [expr {$::scenario eq "wrong_engine" ? "unrelated_module" : "rk_ew_async_engine"}]
    }
    if {$property eq "DIRECTION" && [string match {engine/ui_result_code*} $object]} {
        return [expr {$::scenario eq "wrong_engine_direction" ? "IN" : "OUT"}]
    }
    return [mock_get_property $property $object]
}
rename get_nets mock_get_nets
proc get_nets {args} {
    set i [lsearch -exact $args -of_objects]
    set object [lindex $args [expr {$i+1}]]
    if {[regexp {^engine/ui_result_code\[[4-7]\]$} $object]} {
        set b [lsearch -exact $args -boundary_type]
        if {$b<0 || [lindex $args [expr {$b+1}]] ne "lower"} {
            error "Hierarchical output must observe its actual lower driver"
        }
        if {$::scenario eq "missing_internal_net"} {return {}}
        return output_ground_net
    }
    return [mock_get_nets {*}$args]
}
proc get_ports {args} {error "Engine observer must not substitute top-level ports"}
'''


@unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter required')
class EngineObserverTests(unittest.TestCase):
    def invoke(self,scenario,body=None):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'observer.tcl'
            script=ENGINE_MOCK.replace('__SCENARIO__',tcl_literal(scenario))
            script+='\nsource '+tcl_literal(ROOT/'fpga/ddr/async_job_cdc.tcl')+'\n'
            script+=body or ('set p [rk_job_payloads [rk_job_prefix engine/job_crossing] ew_engine_e1_e8]\n'
                'puts "CHECKED_ENGINE_PAYLOAD [llength [lindex $p 0 1]] [llength [lindex $p 1 1]]"\n')
            path.write_text(script)
            return subprocess.run([shutil.which('tclsh'),str(path)],capture_output=True,text=True,timeout=15)

    def test_actual_parent_boundary_is_required_for_64_plus_37(self):
        result=self.invoke('good')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('CHECKED_ENGINE_PAYLOAD 64 37',result.stdout)

    def test_bad_parent_boundary_constant_or_dynamic_bit_fails(self):
        cases={
            'missing_engine':'Expected exactly one EW engine observer hierarchy',
            'wrong_engine':'Unexpected EW observer module',
            'missing_engine_pin':'Expected exactly one job boundary pin ui_result_code[7]',
            'missing_internal_net':'Expected exactly one EW output error bit4 constant net',
            'wrong_engine_direction':'Wrong observable error-code direction',
            'signal_output_net':'EW output error bit4 is not a proved single-driver constant zero',
            'power_output_net':'EW output error bit4 is not a proved single-driver constant zero',
            'two_output_drivers':'EW output error bit4 is not a proved single-driver constant zero',
            'missing_input_pin':'Expected exactly one job boundary pin d_result_code[7]',
            'unexpected_high_ff':'Expected explicitly folded error register',
            'missing_dynamic_bit40':'Expected exactly one crossing register result_held_reg[40]',
        }
        for scenario,message in cases.items():
            with self.subTest(scenario=scenario):
                result=self.invoke(scenario)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn(message,result.stderr)

    def test_full8_and_incorrect_child_remain_failures(self):
        for body,message in [
            ('rk_job_payloads [rk_job_prefix engine/job_crossing] full8',
             'crossing register result_held_reg[36]'),
            ('rk_job_payloads [rk_job_prefix engine/wrong_child] ew_engine_e1_e8',
             'engine job_crossing child'),
        ]:
            with self.subTest(body=body):
                result=self.invoke('good',body)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertIn(message,result.stderr)


if __name__=='__main__':unittest.main()
