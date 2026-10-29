"""Mock constraint scope/admission controls; never native timing evidence."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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
    return [expr {$object eq "source_clock" ? 20.0 : 7.5}]
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
    if {$::scenario eq "payload" && $name eq {request_held_reg[48]}} {return {}}
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
class ConstraintTests(unittest.TestCase):
    def invoke(self,scenario):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.tcl'
            script='set ::scenario '+tcl_literal(scenario)+'\n'+MOCK+'\nsource '+tcl_literal(ROOT/'fpga/ddr/async_mem_cdc.tcl')+'\n'
            instance='../bad' if scenario=='hierarchy' else ''
            script+='rk_mem_cdc_constrain '+tcl_literal(instance)+' source_clock destination_clock\n'
            script+='foreach item $changes {puts $item}\nputs PASS_MOCK_CONSTRAINT_SCOPE_ONLY\n'
            path.write_text(script)
            return subprocess.run([shutil.which('tclsh'),str(path)],capture_output=True,text=True,timeout=15)

    def test_exact_delays_skew_and_only_three_first_stage_cuts(self):
        r=self.invoke('good')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        rows=r.stdout.splitlines()
        self.assertEqual(len([l for l in rows if l.startswith('MAX ')]),2)
        self.assertEqual(len([l for l in rows if l.startswith('SKEW ')]),2)
        self.assertEqual(len([l for l in rows if l.startswith('FALSE -hold ')]),2)
        first=[l for l in rows if l.startswith('FALSE -to ')]
        self.assertEqual(len(first),3)
        for name in ('request_sync','response_sync','fault_sync'):
            self.assertTrue(any(name+'_reg[0]/D' in l for l in first))
        self.assertTrue(any(l.startswith('MAX -datapath_only 15.000 ') for l in rows))
        self.assertTrue(any(l.startswith('MAX -datapath_only 40.000 ') for l in rows))
        self.assertIn('PASS_MOCK_CONSTRAINT_SCOPE_ONLY',r.stdout)

    def test_changed_clock_missing_payload_or_sync_and_depth_fail(self):
        for scenario in ('missing_clock','nan','period','payload','sync','depth','hierarchy'):
            with self.subTest(scenario=scenario):
                r=self.invoke(scenario)
                self.assertNotEqual(r.returncode,0)
                self.assertNotIn('PASS_MOCK_CONSTRAINT_SCOPE_ONLY',r.stdout)


if __name__=='__main__':unittest.main()
