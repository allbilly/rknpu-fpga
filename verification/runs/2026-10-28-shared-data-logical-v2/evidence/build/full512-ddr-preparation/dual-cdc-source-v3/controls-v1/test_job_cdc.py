"""Synthetic Tcl-mock controls for the private CMAC terminal-full8 job CDC profile."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.hardware.sample_ew import tcl_literal

ROOT=Path('/home/fedora/rknpu-fpga')
HELPER=ROOT/'build/full512-ddr-preparation/dual-cdc-source-v3/job_cdc.tcl'
MOCK=r'''
set ::profile __PROFILE__
set ::fault __FAULT__
proc get_cells {args} {
    # Mock Vivado's list-pattern argument parsing: normalize the one-element
    # list so escaped brackets in register names become literal brackets.
    set name [lindex [lindex $args end] 0]
    if {$name in {platform/endpoint/engine/cmac/job_crossing platform/endpoint/engine/cmac
                  platform/endpoint/engine/ew/job_crossing platform/endpoint/engine/ew
                  job_crossing engine}} {return $name}
    if {[regexp {descriptor_held_reg\[([0-9]+)\]$} $name -> bit] ||
        [regexp {descriptor_latched_reg\[([0-9]+)\]$} $name -> bit]} {return $name}
    if {[regexp {result_held_reg\[([0-9]+)\]$} $name -> bit]} {
        if {$::profile eq "cmac_terminal_full8" && $bit>=1 && $bit<=31} {
            if {$::fault eq "extra_result_held_task" && $bit==1} {return $name}
            return {}
        }
        if {$::profile in {ew_e1_e8 ew_engine_e1_e8} && $bit>=36 && $bit<=39} {return {}}
        if {$::fault eq "missing_result_held_$bit"} {return {}}
        return $name
    }
    if {[regexp {s_result_tasks_reg\[([0-9]+)\]$} $name -> bit]} {
        if {$::profile eq "cmac_terminal_full8" && $bit>=1 && $bit<=31} {
            if {$::fault eq "extra_s_result_tasks_task" && $bit==1} {return $name}
            return {}
        }
        if {$::fault eq "missing_s_result_tasks_$bit"} {return {}}
        return $name
    }
    if {[regexp {s_result_code_reg\[([0-9]+)\]$} $name -> bit]} {
        if {$::profile in {ew_e1_e8 ew_engine_e1_e8} && $bit>=4 && $bit<=7} {return {}}
        if {$::fault eq "missing_s_result_code_$bit"} {return {}}
        return $name
    }
    if {[regexp {(^|/)s_result_error_reg$} $name]} {
        if {$::fault eq "missing_s_result_error"} {return {}}
        return $name
    }
    if {[regexp {result_held_reg\[([0-9]+)\]$} $name -> bit]} {return $name}
    return $name
}
proc get_pins {args} {
    set block [lindex $args end]
    set pins {}
    if {$block in {platform/endpoint/engine/cmac/job_crossing job_crossing}} {
        foreach bit {0 1 2 3 4 5 6 7} {
            lappend pins [format {%s/d_result_code[%d]} $block $bit]
            lappend pins [format {%s/s_result_code[%d]} $block $bit]
            if {!($::fault eq "missing_d_task_pin" && $bit==1)} {lappend pins [format {%s/d_result_tasks[%d]} $block $bit]}
            if {!($::fault eq "missing_s_task_pin" && $bit==1)} {lappend pins [format {%s/s_result_tasks[%d]} $block $bit]}
        }
        for {set bit 8} {$bit<32} {incr bit} {
            foreach side {d s} {
                set name [format {%s/%s_result_tasks[%d]} $block $side $bit]
                if {!($::fault eq "missing_d_task_pin" && $side eq "d" && $bit==1) &&
                    !($::fault eq "missing_s_task_pin" && $side eq "s" && $bit==1)} {lappend pins $name}
            }
        }
        lappend pins "$block/d_result_error" "$block/s_result_error"
    } elseif {$block in {platform/endpoint/engine/cmac platform/endpoint/engine}} {
        for {set bit 0} {$bit<32} {incr bit} {
            if {!($::fault eq "missing_ui_task_pin" && $bit==1)} {lappend pins [format {%s/ui_result_tasks[%d]} $block $bit]}
        }
        for {set bit 0} {$bit<8} {incr bit} {lappend pins [format {%s/ui_result_code[%d]} $block $bit]}
    } elseif {$block in {platform/endpoint/engine/ew/job_crossing job_crossing}} {
        for {set bit 0} {$bit<8} {incr bit} {lappend pins [format {%s/d_result_code[%d]} $block $bit];lappend pins [format {%s/s_result_code[%d]} $block $bit]}
    } elseif {$block in {platform/endpoint/engine/ew engine}} {
        for {set bit 0} {$bit<8} {incr bit} {lappend pins [format {%s/ui_result_code[%d]} $block $bit]}
    } else {error "Unexpected get_pins block $block"}
    return $pins
}
proc get_ports {args} {
    set ports {}
    for {set bit 4} {$bit<8} {incr bit} {lappend ports [format {ui_result_code[%d]} $bit]}
    return $ports
}
proc get_property {key object} {
    if {$key eq "IS_PRIMITIVE"} {return 0}
    if {$key eq "REF_NAME"} {
        if {$object eq "platform/endpoint/engine/cmac"} {return rk_cmac_async_engine}
        if {$object eq "platform/endpoint/engine/ew" || $object eq "engine"} {return rk_ew_async_engine}
        if {$object eq "platform/endpoint/engine/cmac/job_crossing" || $object eq "job_crossing"} {return rk_async_job_port}
        return mock_cell
    }
    if {$key eq "NAME"} {return $object}
    if {$key eq "REF_PIN_NAME"} {return [lindex [split $object /] end]}
    if {$key eq "DIRECTION"} {
        set ref [lindex [split $object /] end]
        if {[regexp {^d_result_tasks\[([0-9]+)\]$} $ref -> bit]} {
            return [expr {$::fault eq "direction_d_task" && $bit==1 ? "OUT" : "IN"}]
        }
        if {[regexp {^s_result_tasks\[([0-9]+)\]$} $ref -> bit]} {
            return [expr {$::fault eq "direction_s_task" && $bit==1 ? "IN" : "OUT"}]
        }
        if {[regexp {^ui_result_tasks\[([0-9]+)\]$} $ref -> bit]} {
            return [expr {$::fault eq "direction_ui_task" && $bit==1 ? "IN" : "OUT"}]
        }
        if {[regexp {^d_result_code\[[4-7]\]$} $ref]} {return IN}
        if {[regexp {^s_result_code\[[4-7]\]$} $ref]} {return OUT}
        if {[regexp {^ui_result_code\[[4-7]\]$} $ref]} {return OUT}
    }
    if {$key eq "TYPE"} {
        if {$::fault eq "type_d_task" && $object eq "net_d_task_1"} {return SIGNAL}
        if {$::fault eq "type_s_task" && $object eq "net_s_task_1"} {return SIGNAL}
        if {$::fault eq "type_ui_task" && $object eq "net_ui_task_1"} {return SIGNAL}
        return GROUND
    }
    if {$key eq "DRIVER_COUNT"} {
        if {$::fault eq "drivers_d_task" && $object eq "net_d_task_1"} {return 2}
        if {$::fault eq "drivers_s_task" && $object eq "net_s_task_1"} {return 2}
        if {$::fault eq "drivers_ui_task" && $object eq "net_ui_task_1"} {return 2}
        return 1
    }
    error "Unexpected property $key on $object"
}
proc get_nets {args} {
    set idx [lsearch -exact $args -of_objects]
    if {$idx<0} {error "Missing of_objects in $args"}
    set object [lindex $args [expr {$idx+1}]]
    set lower [expr {[lsearch -exact $args -boundary_type]>=0}]
    set ref [lindex [split $object /] end]
    if {[regexp {^d_result_tasks\[([0-9]+)\]$} $ref -> bit]} {
        if {$lower} {return {}}
        if {$::fault eq "missing_d_task_net" && $bit==1} {return {}}
        return "net_d_task_$bit"
    }
    if {[regexp {^s_result_tasks\[([0-9]+)\]$} $ref -> bit]} {
        if {!$lower} {return {}}
        if {$::fault eq "missing_s_task_net" && $bit==1} {return {}}
        return "net_s_task_$bit"
    }
    if {[regexp {^ui_result_tasks\[([0-9]+)\]$} $ref -> bit]} {
        if {!$lower} {return {}}
        if {$::fault eq "missing_ui_task_net" && $bit==1} {return {}}
        return "net_ui_task_$bit"
    }
    if {[regexp {^d_result_code\[[4-7]\]$} $ref]} {return net_dynamic}
    if {[regexp {^ui_result_code\[[4-7]\]$} $ref]} {return net_dynamic}
    if {[regexp {^s_result_code\[[4-7]\]$} $ref]} {return {}}
    return {}
}
''' 


@unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter required')
class CmacTerminalFull8Tests(unittest.TestCase):
    def invoke(self,profile='cmac_terminal_full8',fault='none',body=None):
        if body is None:
            body=r'''
set prefix [rk_job_prefix platform/endpoint/engine/cmac/job_crossing]
set facts [rk_job_constant_fields $prefix cmac_terminal_full8]
set payloads [rk_job_payloads $prefix cmac_terminal_full8]
set d [lindex $payloads 0];set r [lindex $payloads 1]
puts "PROFILE cmac_terminal_full8 descriptor=[llength [lindex $d 1]]/[llength [lindex $d 2]] result=[llength [lindex $r 1]]/[llength [lindex $r 2]] zero_tasks=[llength $facts]"
foreach row $facts {puts [join $row "\t"]}
puts PASS_MOCK_CMAC_TERMINAL_FULL8_ONLY
'''
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'cmac-terminal-full8.tcl'
            mock=MOCK.replace('__PROFILE__',tcl_literal(profile)).replace('__FAULT__',tcl_literal(fault))
            script.write_text(mock+'\nsource '+tcl_literal(HELPER)+'\n'+body+'\n')
            return subprocess.run([shutil.which('tclsh'),str(script)],capture_output=True,text=True,timeout=20)

    def test_cmac_terminal_full8_proves31_zero_task_rows_and10_dynamic_result_bits(self):
        r=self.invoke()
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('PROFILE cmac_terminal_full8 descriptor=64/64 result=10/10 zero_tasks=31',r.stdout)
        rows=[x.split('\t') for x in r.stdout.splitlines() if x.startswith('ZERO_TASK\t')]
        self.assertEqual([int(x[1]) for x in rows],list(range(1,32)))
        result=[x for x in r.stdout.splitlines() if x.startswith('PASS_MOCK_CMAC_TERMINAL_FULL8_ONLY')]
        self.assertEqual(len(result),1)

    def test_full8_and_ew_folded_error_profiles_remain_unchanged(self):
        full8=self.invoke('full8','none',r'''
set p [rk_job_payloads [rk_job_prefix platform/endpoint/engine/cmac/job_crossing] full8]
puts "PROFILE full8 descriptor=[llength [lindex [lindex $p 0] 1]] result=[llength [lindex [lindex $p 1] 1]]"
puts PASS_FULL8_BEHAVIOR
''')
        self.assertEqual(full8.returncode,0,full8.stdout+full8.stderr)
        self.assertIn('PROFILE full8 descriptor=64 result=41',full8.stdout)
        ew=self.invoke('ew_e1_e8','none',r'''
set prefix [rk_job_prefix job_crossing]
set facts [rk_job_zero_error_codes $prefix ew_e1_e8]
set payloads [rk_job_payloads $prefix ew_e1_e8]
puts "PROFILE ew_e1_e8 descriptor=[llength [lindex [lindex $payloads 0] 1]] result=[llength [lindex [lindex $payloads 1] 1]] zero_codes=[llength $facts]"
puts PASS_EW_E1_E8_BEHAVIOR
''')
        self.assertEqual(ew.returncode,0,ew.stdout+ew.stderr)
        self.assertIn('PROFILE ew_e1_e8 descriptor=64 result=37 zero_codes=4',ew.stdout)
        ew_engine=self.invoke('ew_engine_e1_e8','none',r'''
set prefix [rk_job_prefix platform/endpoint/engine/ew/job_crossing]
set facts [rk_job_zero_error_codes $prefix ew_engine_e1_e8]
set payloads [rk_job_payloads $prefix ew_engine_e1_e8]
puts "PROFILE ew_engine_e1_e8 descriptor=[llength [lindex [lindex $payloads 0] 1]] result=[llength [lindex [lindex $payloads 1] 1]] zero_codes=[llength $facts]"
puts PASS_EW_ENGINE_E1_E8_BEHAVIOR
''')
        self.assertEqual(ew_engine.returncode,0,ew_engine.stdout+ew_engine.stderr)
        self.assertIn('PROFILE ew_engine_e1_e8 descriptor=64 result=37 zero_codes=4',ew_engine.stdout)
        rejected=self.invoke('cmac_engine_e1_e8','none',r'set p [rk_job_payloads [rk_job_prefix job_crossing] cmac_engine_e1_e8]')
        self.assertNotEqual(rejected.returncode,0)
        self.assertIn('Unsupported job result mapping profile',rejected.stderr)

    def test_missing_wrong_direction_nonground_and_multidriver_reject_on_each_task_boundary(self):
        for boundary in ('d','s','ui'):
            for mutation in ('missing_'+boundary+'_task_pin','direction_'+boundary+'_task',
                             'type_'+boundary+'_task','drivers_'+boundary+'_task'):
                with self.subTest(boundary=boundary,mutation=mutation):
                    r=self.invoke(fault=mutation)
                    self.assertNotEqual(r.returncode,0,r.stdout)
                    if mutation.endswith('_task_pin'):
                        pin={'d':'d_result_tasks[1]','s':'s_result_tasks[1]','ui':'ui_result_tasks[1]'}[boundary]
                        expected='Expected exactly one job boundary pin '+pin
                        self.assertIn(expected,r.stderr)
                    elif mutation.startswith('direction_'):
                        self.assertIn('Changed CMAC terminal task boundary direction',r.stderr)
                    else:
                        expected={'d':'CMAC source task bit1','s':'CMAC child task bit1','ui':'CMAC output task bit1'}[boundary]
                        self.assertIn(expected+' is not a proved single-driver constant zero',r.stderr)
                    self.assertNotIn('PASS_MOCK_CMAC_TERMINAL_FULL8_ONLY',r.stdout)

    def test_every_task_and_result_held_high_ff_must_be_absent(self):
        for fault in ('extra_result_held_task','extra_s_result_tasks_task'):
            with self.subTest(fault=fault):
                r=self.invoke(fault=fault)
                self.assertNotEqual(r.returncode,0,r.stdout)
                self.assertIn('Expected explicitly folded CMAC task register',r.stderr)

    def test_taskbit0_errorflag_and_every_errorcode_bit_remain_required(self):
        missing=('missing_result_held_0',)+tuple(f'missing_result_held_{bit}' for bit in range(32,41))+\
                ('missing_s_result_tasks_0',)+tuple(f'missing_s_result_code_{bit}' for bit in range(8))+('missing_s_result_error',)
        for fault in missing:
            with self.subTest(fault=fault):
                r=self.invoke(fault=fault)
                self.assertNotEqual(r.returncode,0,r.stdout)
                self.assertIn('Expected exactly one crossing register',r.stderr)
                self.assertNotIn('PASS_MOCK_CMAC_TERMINAL_FULL8_ONLY',r.stdout)


if __name__=='__main__':unittest.main()
