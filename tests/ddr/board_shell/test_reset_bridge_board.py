"""Fail-closed Tcl mocks for the physical startup/reset-bank bridge.

These exercise inventory, constraint scope, and audit rejection only. They do
not model Vivado timing, hardware reset behavior, or physical qualification.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.hardware.sample_ew import tcl_literal

ROOT = Path(__file__).resolve().parents[3]
STATUS_HELPER = ROOT / 'fpga/ddr/reset_status_cdc.tcl'
BOARD_HELPER = ROOT / 'fpga/ddr/reset_bridge_board_cdc.tcl'

MOCK = r'''
set scenario __SCENARIO__
set changes {}
array set dont_touch {}
array set path_info {}
set path_serial 0
proc pin_name {pin} {return [string range $pin 4 end]}
proc startup_cells {} {
    set result {}
    for {set i 0} {$i<64} {incr i} {lappend result [format {startup/release_pipe_reg[%d]} $i]}
    lappend result startup/rst_n_reg startup/GND startup/VCC
    if {$::scenario eq "extra_startup_cell" || $::scenario eq "extra_constant_primitive"} {lappend result startup/rogue_reg}
    return $result
}
proc get_clocks {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        set name [pin_name [lindex $args end]]
        if {[regexp {ui_domain\[0\]} $name]} {
            if {$::scenario eq "wrong_ui_clock"} {return [list CLOCK:sys_clock]}
            return [list CLOCK:clk_pll_i]
        }
        if {[regexp {ui_domain\[1\]} $name]} {return [list CLOCK:clk_pll_i_1]}
        return [list CLOCK:sys_clock]
    }
    set name [lindex [lindex $args end] 0]
    if {[string match "CLOCK:*" $name]} {return [list $name]}
    if {$name eq "sys_clock"} {return [list CLOCK:sys_clock]}
    if {$name eq "clk_pll_i"} {return [list CLOCK:clk_pll_i]}
    if {$name eq "clk_pll_i_1"} {return [list CLOCK:clk_pll_i_1]}
    return {}
}
proc get_property {key object} {
    if {$key eq "PERIOD"} {
        if {![string match "CLOCK:*" $object]} {error "clock property requires typed object: $object"}
        set name [string range $object 6 end]
        if {$name eq "sys_clock"} {return 20.0}
        if {$name in {clk_pll_i clk_pll_i_1}} {return 7.5}
        error "Unknown clock $object"
    }
    if {$key eq "REF_NAME"} {
        if {$object eq "startup"} {return [expr {$::scenario eq "wrong_startup_module" ? "FDRE" : "rk_startup_reset"}]}
        if {$object eq "startup/GND"} {return [expr {$::scenario eq "wrong_constant_ref" ? "GND" : "GND"}]}
        if {$object eq "startup/VCC"} {return [expr {$::scenario eq "wrong_constant_ref" ? "LUT1" : "VCC"}]}
        if {$object eq "platform_i_1"} {return [expr {$::scenario eq "wrong_inverter_ref" ? "LUT2" : "LUT1"}]}
        if {$object eq "platform/endpoint/reset_owner"} {return rk_mig_reset_coordinator}
        if {[regexp {^startup/(release_pipe_reg\[[0-9]+\]|rst_n_reg)$} $object]} {return FDRE}
        if {[regexp {^platform/endpoint/reset_owner/(mig_sys_rst_n_reg|release_permit_reg)$} $object]} {return FDRE}
        if {[regexp {^platform/endpoint/reset_owner/ui_domain\[[01]\]\.(reset_pipe_reg\[[01]\]|local_rst_n_reg|permit_sync_reg\[[0-2]\])$} $object]} {return FDCE}
        return "UNKNOWN:$object"
    }
    if {$key eq "INIT"} {
        if {$object eq "platform_i_1"} {return [expr {$::scenario eq "wrong_inverter_init" ? "2'h0" : "2'h1"}]}
        if {$::scenario eq "wrong_startup_init" && [regexp {^startup/release_pipe_reg\[7\]$} $object]} {return "1'b1"}
        return "1'b0"
    }
    if {$key eq "ASYNC_REG"} {
        if {$::scenario eq "missing_async_reg" && [regexp {^platform/endpoint/reset_owner/ui_domain\[0\]\.permit_sync_reg\[0\]$} $object]} {return 0}
        if {[regexp {^platform/endpoint/reset_owner/ui_domain\[[01]\]\.(reset_pipe_reg\[[01]\]|local_rst_n_reg|permit_sync_reg\[[0-2]\])$} $object]} {return 1}
        return 0
    }
    if {$key eq "DONT_TOUCH"} {return [info exists ::dont_touch($object)]}
    if {$key eq "TYPE"} {
        if {$object eq "NET:VCC" || $object eq "NET:cfg_vcc"} {return POWER}
        if {$object eq "NET:GND"} {return GROUND}
        return SIGNAL
    }
    if {$key eq "DRIVER_COUNT"} {return 1}
    if {$key eq "NAME"} {return $object}
    if {$key eq "IS_PRIMITIVE"} {return 1}
    if {[string match {PATH:*} $object]} {
        if {![info exists ::path_info($object)]} {error "unknown path object $object"}
        set info $::path_info($object)
        switch -- $key {
            EXCEPTION {return [dict get $info exception]}
            SLACK {return [dict get $info slack]}
            REQUIREMENT {return [dict get $info requirement]}
            REQUIRED_TIME {return [dict get $info required_time]}
            STARTPOINT_PIN {return [dict get $info start]}
            ENDPOINT_PIN {return [dict get $info end]}
            default {error "unexpected path property $key"}
        }
    }
    error "Unexpected property $key on $object"
}
proc get_cells {args} {
    set joined [join $args " "]
    if {[string match {*IS_PRIMITIVE == 1*} $joined]} {return [startup_cells]}
    set arg [lindex $args end];set name [lindex $arg 0]
    if {[llength $arg] != 1} {return {}}
    if {[regexp {^startup/(release_pipe_reg\[[0-9]+\]|rst_n_reg)$} $name]} {return [list $name]}
    if {$name eq "startup" || $name eq "platform_i_1" || $name eq "platform/endpoint" ||
        $name eq "platform/endpoint/reset_owner" || $name in {startup/GND startup/VCC} ||
        $name in {platform/endpoint/reset_owner/mig_sys_rst_n_reg platform/endpoint/reset_owner/release_permit_reg}} {return [list $name]}
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[[01]\]\.(reset_pipe_reg\[[01]\]|local_rst_n_reg|permit_sync_reg\[[0-2]\])$} $name]} {return [list $name]}
    return {}
}
proc get_pins {args} {
    set arg [lindex $args end];set name [lindex $arg 0]
    regsub {^\{(.*)\}/(.*)$} $name {\1/\2} name
    return [list "PIN:$name"]
}
proc get_ports {args} {
    if {$::scenario eq "cfg_port_present"} {return {cfg_reset}}
    return {}
}
proc get_nets {args} {
    set pin [pin_name [lindex $args end]]
    if {[regexp {^startup/(release_pipe_reg\[[0-9]+\]|rst_n_reg)/(CE|D)$} $pin]} {return {NET:VCC}}
    if {[regexp {^startup/(release_pipe_reg\[[0-9]+\]|rst_n_reg)/R$} $pin]} {return {NET:GND}}
    if {$pin eq "startup/rst_n_reg/Q"} {return {NET:cfg_registered}}
    if {$pin eq "platform_i_1/I0"} {return [expr {$::scenario eq "wrong_inverter_net" ? "NET:wrong_registered" : "NET:cfg_registered"}]}
    if {$pin eq "platform_i_1/O"} {return {NET:cfg_reset}}
    if {$pin eq "platform/endpoint/cfg_reset"} {return [expr {$::scenario eq "wrong_cfg_net" ? "NET:wrong_cfg" : "NET:cfg_reset"}]}
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.(reset_pipe_reg\[[01]\]|local_rst_n_reg)/D$} $pin] && [regexp {reset_pipe_reg\[0\]/D$} $pin]} {return {NET:VCC}}
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.permit_sync_reg\[0\]/D$} $pin]} {return {NET:VCC}}
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.reset_pipe_reg\[[01]\]/CLR$|^platform/endpoint/reset_owner/ui_domain\[[01]\]\.local_rst_n_reg/CLR$} $pin]} {
        if {$::scenario eq "wrong_epoch_shared_net" && [string match {*reset_pipe_reg[1]/CLR} $pin]} {return {NET:epoch_other}}
        return {NET:epoch_CLR}
    }
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.permit_sync_reg\[[0-2]\]/CLR$} $pin -> d]} {
        return [list "NET:permit_CLR$d"]
    }
    return [list "NET:$pin"]
}
proc all_fanin {args} {
    set dest [pin_name [lindex $args end]]
    if {$dest eq "platform/endpoint/cfg_reset"} {
        set starts "PIN:startup/rst_n_reg/C"
        if {$::scenario eq "cfg_extra_source"} {lappend starts [format {PIN:startup/release_pipe_reg[%d]/C} 3]}
        return $starts
    }
    if {[regexp {^startup/(release_pipe_reg\[([0-9]+)\]|rst_n_reg)/D$} $dest -> cell idx]} {
        if {[regexp {^startup/release_pipe_reg\[0\]/D$} $dest]} {return {}}
        if {$cell eq "rst_n_reg"} {return [format {PIN:startup/release_pipe_reg[%d]/C} 63]}
        if {$idx>0} {set prev [expr {$idx-1}];set starts [format {PIN:startup/release_pipe_reg[%d]/C} $prev]} else {set starts {}}
        if {$::scenario eq "startup_mux_data" && $idx==5} {lappend starts PIN:startup/other_reg/C}
        return $starts
    }
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.reset_pipe_reg\[([01])\]/D$} $dest -> d i]} {
        if {$i==0} {return {}}
        set j [expr {$i-1}];return [format {PIN:platform/endpoint/reset_owner/ui_domain[%d].reset_pipe_reg[%d]/C} $d $j]
    }
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.local_rst_n_reg/D$} $dest -> d]} {
        return [format {PIN:platform/endpoint/reset_owner/ui_domain[%d].reset_pipe_reg[1]/C} $d]
    }
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.permit_sync_reg\[([0-2])\]/D$} $dest -> d i]} {
        if {$i==0} {return {}}
        set j [expr {$i-1}];set starts [format {PIN:platform/endpoint/reset_owner/ui_domain[%d].permit_sync_reg[%d]/C} $d $j]
        if {$::scenario eq "ui_mux_data" && $i==2} {lappend starts PIN:platform/endpoint/reset_owner/release_permit_reg/C}
        return $starts
    }
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.(reset_pipe_reg\[[01]\]|local_rst_n_reg)/CLR$} $dest]} {
        set starts [list "PIN:platform/endpoint/reset_owner/mig_sys_rst_n_reg/C" "PIN:startup/rst_n_reg/C"]
        if {$::scenario eq "extra_epoch_source"} {lappend starts "PIN:platform/endpoint/reset_owner/release_permit_reg/C"}
        return [lsort $starts]
    }
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[([01])\]\.permit_sync_reg\[[0-2]\]/CLR$} $dest -> d]} {
        set starts [list "PIN:platform/endpoint/reset_owner/release_permit_reg/C" [format {PIN:platform/endpoint/reset_owner/ui_domain[%d].local_rst_n_reg/C} $d]]
        if {$::scenario eq "extra_permit_source"} {lappend starts "PIN:platform/endpoint/reset_owner/mig_sys_rst_n_reg/C"}
        return [lsort $starts]
    }
    return {}
}
proc get_timing_paths {args} {
    set fi [lsearch -exact $args -from];set ti [lsearch -exact $args -to];set di [lsearch -exact $args -delay_type]
    set start [lindex $args [expr {$fi+1}]];set end [lindex $args [expr {$ti+1}]];set delay [lindex $args [expr {$di+1}]]
    set s [pin_name $start];set e [pin_name $end]
    set async 0;set local 0;set data 0
    if {[string match */CLR $e] && ($s eq "platform/endpoint/reset_owner/mig_sys_rst_n_reg/C" ||
        $s eq "startup/rst_n_reg/C" || $s eq "platform/endpoint/reset_owner/release_permit_reg/C")} {set async 1}
    if {[regexp {^platform/endpoint/reset_owner/ui_domain\[[01]\]\.local_rst_n_reg/C$} $s] && [regexp {permit_sync_reg\[[0-2]\]/CLR$} $e]} {set local 1}
    if {[string match */D $e]} {set data 1}
    set exc "";set slack [expr {$delay eq "max" ? 2.0 : 0.5}];set req [expr {$delay eq "max" ? 7.5 : 0.0}];set rt ""
    if {$async} {
        set exc "False Path";set slack "";set req "";set rt ""
        if {$::scenario eq "audit_async_numeric"} {set slack 0.0;set req 7.5;set rt 7.5}
        if {$::scenario eq "audit_async_absent"} {set exc ""}
        if {$::scenario eq "audit_async_wrong_endpoint"} {set e "PIN:wrong/endpoint"}
    } else {
        if {$data || $local} {
            if {$delay eq "max"} {set req 7.5}
            if {$::scenario eq "audit_data_cut" && $data} {set exc "False Path"}
            if {$::scenario eq "audit_data_loosened" && $data && $delay eq "max"} {set req 8.0}
            if {$::scenario eq "audit_reset_pipe_hold" && $data && $delay eq "min" &&
                [regexp {ui_domain\[[01]\]\.reset_pipe_reg\[1\]/D$} $e]} {set slack -0.006}
            if {$::scenario eq "audit_local_cut" && $local} {set exc "False Path"}
            if {$::scenario eq "audit_local_hold" && $local && $delay eq "min"} {set slack -0.006}
            if {$::scenario eq "audit_wrong_path_endpoint" && $data} {set s "PIN:wrong/start"}
        }
    }
    incr ::path_serial;set id "PATH:$::path_serial"
    set ::path_info($id) [dict create exception $exc slack $slack requirement $req required_time $rt start "PIN:$s" end "PIN:$e"]
    return [list $id]
}
proc set_property {key value cells} {
    if {$key eq "DONT_TOUCH" && $value eq "TRUE"} {foreach c $cells {set ::dont_touch($c) 1}}
    lappend ::changes [list PROPERTY $key $value $cells]
}
proc set_false_path {args} {lappend ::changes [linsert $args 0 FALSE]}
proc get_waivers {} {return {}}
proc report_exceptions {args} {lappend ::changes [linsert $args 0 REPORT_EXCEPTIONS]}
'''


@unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter required')
class ResetBridgeBoardTests(unittest.TestCase):
    def invoke(self, scenario, body, output=None):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            report_dir = output if output is not None else temp/'reports'
            report_dir.mkdir(parents=True, exist_ok=True)
            script = temp/'board-reset-mock.tcl'
            mock = MOCK.replace('__SCENARIO__', tcl_literal(scenario))
            source = ('source '+tcl_literal(ROOT/'fpga/ddr/reset_status_cdc.tcl')+'\nsource '+
                      tcl_literal(ROOT/'fpga/ddr/reset_bridge_board_cdc.tcl')+'\n')
            script.write_text(mock+'\n'+source+body+'\n')
            return subprocess.run([shutil.which('tclsh'), str(script)], capture_output=True,
                                  text=True, timeout=30)

    def constrain_body(self):
        return r'''
set code [catch {rk_board_reset_constrain platform/endpoint startup platform_i_1 sys_clock clk_pll_i clk_pll_i_1} message]
puts "RESULT\t$code\t$message\tMUTATIONS\t[llength $changes]"
foreach change $changes {puts [join $change "\t"]}
'''

    def test_valid_inventory_and_exact18_prevalidated_constraints(self):
        result = self.invoke('good', r'''
set inventory [rk_board_reset_inventory platform/endpoint startup platform_i_1 sys_clock clk_pll_i clk_pll_i_1]
puts "INVENTORY [llength $inventory]"
rk_board_reset_constrain platform/endpoint startup platform_i_1 sys_clock clk_pll_i clk_pll_i_1
foreach change $changes {puts [join $change "\t"]}
puts PASS_BOARD_RESET_CONSTRAINTS
''')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('INVENTORY 4', result.stdout)
        rows=result.stdout.splitlines()
        false=[line for line in rows if line.startswith('FALSE\t')]
        props=[line for line in rows if line.startswith('PROPERTY\t')]
        self.assertEqual(len(false),18)
        self.assertEqual(len(props),4)
        self.assertTrue(all('DONT_TOUCH' in line and 'TRUE' in line for line in props))
        # Assert the complete directed cut set. No local-to-permit CLR or D-pin
        # path is permitted, and no broad from-only/through cut can hide here.
        expected=set()
        for domain in (0,1):
            stem=f'platform/endpoint/reset_owner/ui_domain[{domain}]'
            epoch_targets=[f'{stem}.reset_pipe_reg[0]/CLR',f'{stem}.reset_pipe_reg[1]/CLR',f'{stem}.local_rst_n_reg/CLR']
            for source in ('platform/endpoint/reset_owner/mig_sys_rst_n_reg/C','startup/rst_n_reg/C'):
                expected.update({('FALSE','-from','PIN:'+source,'-to','PIN:'+target) for target in epoch_targets})
            permit_targets=[f'{stem}.permit_sync_reg[{i}]/CLR' for i in range(3)]
            source='platform/endpoint/reset_owner/release_permit_reg/C'
            expected.update({('FALSE','-from','PIN:'+source,'-to','PIN:'+target) for target in permit_targets})
        actual={tuple(line.split('\t')) for line in false}
        self.assertEqual(actual,expected)
        self.assertIn('PASS_BOARD_RESET_CONSTRAINTS',result.stdout)

    def test_all_structural_admission_failures_precede_any_mutation(self):
        cases=(
            ('cfg_port_present','Physical profile cannot use OOC cfg_reset'),
            ('wrong_startup_module','Wrong startup producer module'),
            ('wrong_inverter_ref','Configuration reset must invert registered startup'),
            ('wrong_inverter_init','Configuration reset must invert registered startup'),
            ('wrong_startup_init','Unreviewed startup register'),
            ('wrong_inverter_net','Changed startup inverter connectivity'),
            ('wrong_cfg_net','Changed startup inverter connectivity'),
            ('cfg_extra_source','Unregistered physical configuration reset'),
            ('extra_startup_cell','Changed boot startup chain'),
            ('extra_constant_primitive','Changed boot startup chain'),
            ('wrong_constant_ref','Changed mapped startup constant primitive'),
            ('startup_mux_data','Startup release contains another source'),
            ('missing_async_reg','Unreviewed board reset-release register'),
            ('extra_epoch_source','Unexpected physical reset source in release bank'),
            ('extra_permit_source','Unexpected physical reset source in release bank'),
            ('ui_mux_data','Board reset release contains another data source'),
            ('wrong_ui_clock','Wrong status register clock'),
        )
        for scenario,message in cases:
            with self.subTest(scenario=scenario):
                result=self.invoke(scenario,self.constrain_body())
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('RESULT\t1\t'+message+'\tMUTATIONS\t0',result.stdout)
                self.assertNotIn('PASS_BOARD_RESET_CONSTRAINTS',result.stdout)

    def audit_body(self,out):
        return (r'''
rk_board_reset_constrain platform/endpoint startup platform_i_1 sys_clock clk_pll_i clk_pll_i_1
set code [catch {rk_board_reset_audit platform/endpoint startup platform_i_1 sys_clock clk_pll_i clk_pll_i_1 '''+
                tcl_literal(out)+r'''} message]
puts "AUDIT\t$code\t$message"
if {!$code} {puts PASS_BOARD_RESET_AUDIT}
''')

    def test_valid_strict_audit_inventory_and_timed_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'reports';out.mkdir()
            result=self.invoke('good',self.audit_body(out),output=out)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('PASS_BOARD_RESET_AUDIT',result.stdout)
            rows=(out/'reset_bridge_board.tsv').read_text().splitlines()
            async_rows=[tuple(x.split('\t')) for x in rows if x.startswith('ASYNC_CLR\t')]
            self.assertEqual(len(async_rows),36)
            expected_async=set()
            for domain in (0,1):
                stem=f'platform/endpoint/reset_owner/ui_domain[{domain}]'
                for kind,sources,cells in (
                    ('epoch',('PIN:platform/endpoint/reset_owner/mig_sys_rst_n_reg/C','PIN:startup/rst_n_reg/C'),
                     (f'{stem}.reset_pipe_reg[0]',f'{stem}.reset_pipe_reg[1]',f'{stem}.local_rst_n_reg')),
                    ('permit',('PIN:platform/endpoint/reset_owner/release_permit_reg/C',),
                     tuple(f'{stem}.permit_sync_reg[{i}]' for i in range(3))),
                ):
                    for source in sources:
                        for cell in cells:
                            for typ in ('max','min'):
                                expected_async.add(('ASYNC_CLR',str(domain),kind,typ,source,cell))
            self.assertEqual(set(async_rows),expected_async)
            self.assertEqual(sum(x.startswith('DATA\t') for x in rows),16)
            self.assertEqual(sum(x.startswith('LOCAL_CLR\t') for x in rows),12)
            self.assertEqual(sum(x.startswith('BANK\t') for x in rows),4)
            self.assertTrue(all(len(x.split('\t'))==6 for x in rows if x.startswith(('DATA\t','LOCAL_CLR\t'))))

    def test_audit_rejects_negative_hold_cut_data_local_clr_bad_endpoints_and_bad_async_objects(self):
        cases=(
            ('audit_local_hold','Local board reset path is cut, changed or failing'),
            ('audit_reset_pipe_hold','Local board reset path is cut, changed or failing'),
            ('audit_data_cut','Local board reset path is cut, changed or failing'),
            ('audit_data_loosened','Local board reset path is cut, changed or failing'),
            ('audit_local_cut','Local board reset path is cut, changed or failing'),
            ('audit_wrong_path_endpoint','Local board reset path is cut, changed or failing'),
            ('audit_async_numeric','Physical reset exception has wrong scope'),
            ('audit_async_absent','Physical reset exception has wrong scope'),
            ('audit_async_wrong_endpoint','Physical reset exception has wrong scope'),
        )
        for scenario,message in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                out=Path(directory)/'reports';out.mkdir()
                result=self.invoke(scenario,self.audit_body(out),output=out)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('AUDIT\t1\t'+message,result.stdout)
                self.assertNotIn('PASS_BOARD_RESET_AUDIT',result.stdout)
                if scenario == 'audit_reset_pipe_hold':
                    observed=(out/'reset_bridge_board.tsv').read_text().splitlines()
                    self.assertTrue(any(
                        line.startswith('OBSERVED_DATA\tmin\t'
                            'platform/endpoint/reset_owner/ui_domain[0].reset_pipe_reg[0]\t'
                            'PIN:platform/endpoint/reset_owner/ui_domain[0].reset_pipe_reg[1]/D\t0.0\t-0.006\t')
                        for line in observed), observed)


if __name__=='__main__':
    unittest.main()
