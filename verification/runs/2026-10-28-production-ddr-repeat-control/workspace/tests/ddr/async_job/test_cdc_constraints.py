"""Mock constraint scope/admission controls; never native timing evidence."""
import shutil
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.hardware.sample_ew import tcl_literal

ROOT=Path(__file__).resolve().parents[3]
MOCK=r'''
set changes {}
proc get_clocks {args} {
    set name [lindex [lindex $args end] 0]
    if {$::scenario eq "missing_clock"} {return {}}
    return $name
}
proc get_property {key object} {
    if {$key ne "PERIOD"} {error "Unexpected property read"}
    if {$::scenario eq "nan"} {return NaN}
    if {$::scenario eq "period"} {return 21.0}
    return [expr {$object eq "source_clock" ? 7.5 : 20.0}]
}
proc get_cells {args} {
    if {[lsearch -exact $args -hier]>=0} {
        set filter [lindex $args end]
        if {![regexp {NAME =~ (.*)_reg\*} $filter -> stem]} {error filter}
        set count [expr {$::scenario eq "depth" ? 2 : 3}]
        set result {}
        for {set i 0} {$i<$count} {incr i} {lappend result [format {%s_reg[%d]} $stem $i]}
        return $result
    }
    set name [lindex [lindex $args end] 0]
    if {$::scenario eq "descriptor63" && $name eq {descriptor_held_reg[63]}} {return {}}
    if {$::scenario eq "result40" && $name eq {result_held_reg[40]}} {return {}}
    if {$::scenario eq "sync" && $name eq {fault_sync_reg[2]}} {return {}}
    return $name
}
proc get_pins {name} {return $name}
proc set_max_delay {args} {lappend ::changes [linsert $args 0 MAX]}
proc set_bus_skew {args} {lappend ::changes [linsert $args 0 SKEW]}
proc set_false_path {args} {lappend ::changes [linsert $args 0 FALSE]}
proc set_property {key value cells} {
    if {$key ni {ASYNC_REG DONT_TOUCH} || $value ne "TRUE" || [llength $cells]!=3} {error "Unreviewed property mutation"}
    lappend ::changes [list PROPERTY $key $value $cells]
}
'''


@unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter required')
class JobConstraintTests(unittest.TestCase):
    def invoke(self,scenario):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tcl'
            script='set ::scenario '+tcl_literal(scenario)+'\n'+MOCK+'\nsource '+tcl_literal(ROOT/'fpga/ddr/async_job_cdc.tcl')+'\n'
            instance='../bad' if scenario=='hierarchy' else ''
            script+='rk_job_cdc_constrain '+tcl_literal(instance)+' source_clock destination_clock\n'
            script+='foreach item $changes {puts $item}\nputs PASS_MOCK_JOB_CONSTRAINT_SCOPE_ONLY\n'
            path.write_text(script)
            return subprocess.run([shutil.which('tclsh'),str(path)],capture_output=True,text=True,timeout=15)

    def test_exact_payload_inventories_bounds_skew_and_first_stage_cuts(self):
        r=self.invoke('good')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        rows=r.stdout.splitlines()
        max_rows=[line for line in rows if line.startswith('MAX ')]
        skew_rows=[line for line in rows if line.startswith('SKEW ')]
        self.assertEqual(len(max_rows),2)
        self.assertEqual(len(skew_rows),2)
        self.assertEqual(len([line for line in rows if line.startswith('FALSE -hold ')]),2)
        first=[line for line in rows if line.startswith('FALSE -to ')]
        self.assertEqual(len(first),3)
        for name in ('request_sync','result_sync','fault_sync'):
            self.assertTrue(any(name+'_reg[0]/D' in line for line in first))
        descriptor=next(line for line in max_rows if '40.000' in line)
        result=next(line for line in max_rows if '15.000' in line)
        self.assertEqual(len(re.findall(r'descriptor_held_reg\[\d+\]',descriptor)),64)
        self.assertEqual(len(re.findall(r'descriptor_latched_reg\[\d+\]',descriptor)),64)
        self.assertEqual(len(re.findall(r'result_held_reg\[\d+\]',result)),41)
        self.assertEqual(len(re.findall(r's_result_tasks_reg\[\d+\]',result)),32)
        self.assertEqual(len(re.findall(r's_result_code_reg\[\d+\]',result)),8)
        self.assertIn('s_result_error_reg',result)
        self.assertTrue(any(line.startswith('MAX -datapath_only 40.000 ') for line in max_rows))
        self.assertTrue(any(line.startswith('MAX -datapath_only 15.000 ') for line in max_rows))
        self.assertTrue(any(line.startswith('SKEW 40.000 ') for line in skew_rows))
        self.assertTrue(any(line.startswith('SKEW 15.000 ') for line in skew_rows))
        self.assertIn('PASS_MOCK_JOB_CONSTRAINT_SCOPE_ONLY',r.stdout)

    def test_wrong_clocks_missing_payload_or_sync_and_depth_or_hierarchy_fail(self):
        for scenario in ('missing_clock','nan','period','descriptor63','result40','sync','depth','hierarchy'):
            with self.subTest(scenario=scenario):
                r=self.invoke(scenario)
                self.assertNotEqual(r.returncode,0)
                self.assertNotIn('PASS_MOCK_JOB_CONSTRAINT_SCOPE_ONLY',r.stdout)


if __name__=='__main__':unittest.main()
