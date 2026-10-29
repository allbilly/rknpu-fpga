"""Mock checks for hierarchical, engine-scoped CDC bus-skew reporting."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.hardware.sample_ew import tcl_literal

ROOT=Path(__file__).resolve().parents[3]
MOCK=r'''
set seen {}
proc get_cells {args} {
    set name [lindex [lindex $args end] 0]
    if {$::scenario eq "missing"} {return {}}
    if {$::scenario eq "duplicate"} {return [list $name ${name}_duplicate]}
    return $name
}
proc get_property {name object} {
    if {$name ne "IS_PRIMITIVE"} {error "Unexpected property query $name"}
    return [expr {$::scenario eq "primitive"}]
}
proc report_bus_skew {args} {
    lappend ::seen $args
    puts "CALL [join $args |]"
}
'''


@unittest.skipUnless(shutil.which('tclsh'),'Tcl interpreter required')
class ScopeTests(unittest.TestCase):
    def invoke(self,scenario='good',instance='engine',both=True):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scope.tcl'
            script='set ::scenario '+tcl_literal(scenario)+'\n'+MOCK
            script+='source '+tcl_literal(ROOT/'fpga/ddr/async_job_cdc.tcl')+'\n'
            script+='source '+tcl_literal(ROOT/'fpga/ddr/async_mem_cdc.tcl')+'\n'
            if both:
                job=instance+'/job_crossing' if instance else ''
                memory=instance+'/memory_crossing' if instance else ''
                script+='rk_job_report_skew '+tcl_literal(job)+' job.rpt\n'
                script+='rk_mem_report_skew '+tcl_literal(memory)+' memory.rpt\n'
            else:
                prefix='rk_job' if instance.startswith('job:') else 'rk_mem'
                cell=instance.split(':',1)[1]
                script+=prefix+'_report_skew '+tcl_literal(cell)+' one.rpt\n'
            script+='puts PASS_MOCK_ENGINE_SCOPE_ONLY\n'
            path.write_text(script)
            return subprocess.run([shutil.which('tclsh'),str(path)],capture_output=True,text=True,timeout=15)

    def test_both_namespaces_coexist_and_filter_distinct_engine_instances(self):
        result=self.invoke()
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        calls=[line for line in result.stdout.splitlines() if line.startswith('CALL ')]
        self.assertEqual(len(calls),2,result.stdout)
        self.assertIn('-cells|engine/job_crossing',calls[0])
        self.assertIn('-file|job.rpt',calls[0])
        self.assertIn('-cells|engine/memory_crossing',calls[1])
        self.assertIn('-file|memory.rpt',calls[1])
        self.assertNotIn('memory_crossing',calls[0])
        self.assertNotIn('job_crossing',calls[1])
        self.assertIn('PASS_MOCK_ENGINE_SCOPE_ONLY',result.stdout)

    def test_empty_instance_reports_standalone_without_cell_filter(self):
        result=self.invoke(instance='')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        calls=[line for line in result.stdout.splitlines() if line.startswith('CALL ')]
        self.assertEqual(len(calls),2,result.stdout)
        self.assertIn('-file|job.rpt',calls[0])
        self.assertIn('-file|memory.rpt',calls[1])
        self.assertTrue(all('-cells|' not in line for line in calls),result.stdout)

    def test_missing_duplicate_primitive_and_invalid_hierarchy_reject(self):
        for helper,instance in (('job','engine/job_crossing'),('mem','engine/memory_crossing')):
            for scenario in ('missing','duplicate','primitive'):
                with self.subTest(helper=helper,scenario=scenario):
                    result=self.invoke(scenario,helper+':'+instance,both=False)
                    self.assertNotEqual(result.returncode,0,result.stdout)
                    self.assertNotIn('PASS_MOCK_ENGINE_SCOPE_ONLY',result.stdout)
                    self.assertNotIn('CALL ',result.stdout)
            with self.subTest(helper=helper,scenario='invalid_hierarchy'):
                result=self.invoke('good',helper+':engine/../bad',both=False)
                self.assertNotEqual(result.returncode,0,result.stdout)
                self.assertNotIn('PASS_MOCK_ENGINE_SCOPE_ONLY',result.stdout)
                self.assertNotIn('CALL ',result.stdout)


if __name__=='__main__':unittest.main()
