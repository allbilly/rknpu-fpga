"""Controls use the actual Vivado2026.1 property dump, not its text rendering."""
from pathlib import Path
import subprocess,tempfile,unittest
HELPER=Path(__file__).resolve().parent/'workspace/fpga/ddr/reset_status_cdc.tcl'
MOCK=r'''
proc get_pins {args} {return [lindex [lindex $args end] 0]}
proc get_timing_paths {args} {
    set f [lindex $args [expr {[lsearch -exact $args -from]+1}]]
    set t [lindex $args [expr {[lsearch -exact $args -to]+1}]]
    if {$f ne "source/C" || $t ne "first/D"} {error "Changed timing endpoints"}
    if {$::scenario eq "missing"} {return {}}
    if {$::scenario eq "duplicate"} {return {path0 path1}}
    return path0
}
proc get_property {name object} {
    if {$object ne "path0"} {error "Unexpected timing object"}
    if {$name eq "EXCEPTION"} {
        if {$::scenario eq "timed"} {return {}}
        if {$::scenario eq "wrong_exception"} {return "Max Delay"}
        return "False Path"
    }
    if {$name eq "SLACK"} {
        if {$::scenario eq "finite" || $::scenario eq "timed"} {return 1.25}
        if {$::scenario eq "nan"} {return NaN}
        if {$::scenario eq "rendered_inf"} {return inf}
        return {}
    }
    if {$name eq "REQUIREMENT"} {return [expr {$::scenario eq "finite_requirement" ? "20.0" : ""}]}
    if {$name eq "REQUIRED_TIME"} {return [expr {$::scenario eq "finite_required_time" ? "21.0" : ""}]}
    if {$name eq "STARTPOINT_PIN"} {return source/C}
    if {$name eq "ENDPOINT_PIN"} {return [expr {$::scenario eq "wrong_endpoint" ? "other/D" : "first/D"}]}
    error "Unknown timing property"
}
'''
class TimingObjectTests(unittest.TestCase):
    def run_case(self,scenario):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'control.tcl'
            literal=lambda s:'[encoding convertfrom utf-8 [binary format H* {'+str(s).encode().hex()+'}]]'
            p.write_text('set scenario '+scenario+'\n'+MOCK+'\nsource '+literal(HELPER)+
                '\nrk_status_first_path_audit source first\nputs PASS_EXPLICIT_FALSE_PATH_OBJECT\n')
            return subprocess.run(['tclsh',str(p)],capture_output=True,text=True,timeout=10)
    def test_native_false_path_object_is_accepted(self):
        c=self.run_case('good');self.assertEqual(c.returncode,0,c.stdout+c.stderr)
        self.assertIn('PASS_EXPLICIT_FALSE_PATH_OBJECT',c.stdout)
    def test_synchronous_or_inconsistent_paths_fail(self):
        for case in ('timed','wrong_exception','finite','nan','rendered_inf',
                     'finite_requirement','finite_required_time','wrong_endpoint'):
            with self.subTest(case=case):
                c=self.run_case(case);self.assertNotEqual(c.returncode,0,c.stdout)
                self.assertIn('not an explicit untimed false path',c.stderr)
    def test_missing_or_ambiguous_objects_fail(self):
        for case in ('missing','duplicate'):
            with self.subTest(case=case):
                c=self.run_case(case);self.assertNotEqual(c.returncode,0,c.stdout)
                self.assertIn('Expected one first status timing object',c.stderr)
if __name__=='__main__':unittest.main()
