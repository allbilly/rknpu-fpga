"""Full512 startup packaging and mocked Vivado controls; no implementation runs."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from tools.cmac.startup import prepare as prep
from tools.cmac.startup import qualification as native
from test_fpga_build import HARNESS

EXTRA = r'''
proc current_fileset {} {return sources_1}
proc get_parts {args} {return xc7k480tffg1156-2}
proc get_clocks {args} {return sys_clk}
rename get_property base_get_property
proc get_property {name object} {
    if {$name eq "NAME"} {return $object}
    if {$name eq "PERIOD"} {return [mock MOCK_PERIOD 20.0]}
    return [base_get_property $name $object]
}
rename get_cells base_get_cells
proc get_cells {args} {
    event get_cells {*}$args
    set filter [lindex $args end]
    if {[string first "ORIG_REF_NAME" $filter]>=0} {
        set cells {}
        for {set k 0} {$k<[mock MOCK_KERNELS 16]} {incr k} {lappend cells [format {demo/cmac/kernels[%d]/cell_core} $k]}
        if {[mock MOCK_DUPLICATE_KERNEL 0]} {lset cells 15 [lindex $cells 0]}
        return $cells
    }
    if {$filter eq "REF_NAME == DSP48E1"} {
        set cells {}
        for {set k 0} {$k<16} {incr k} {
            set count 32
            if {$k==0} {set count [mock MOCK_FIRST_KERNEL_DSPS 32]}
            if {$::routed && $k==15} {set count [mock MOCK_ROUTED_LAST_DSPS 32]}
            for {set lane 0} {$lane<$count} {incr lane} {lappend cells [format {demo/cmac/kernels[%d]/cell_core/lanes[%d]/product} $k $lane]}
        }
        for {set k 0} {$k<[mock MOCK_SHELL_DSPS 0]} {incr k} {lappend cells shell/dsp$k}
        return $cells
    }
    return [base_get_cells {*}$args]
}
rename route_design base_route_design
proc route_design {args} {set ::routed 1;base_route_design {*}$args}
proc report_pulse_width {args} {event report_pulse_width {*}$args}
set ::routed 0
'''


class StartupPreparationTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'build').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='full512-startup-prep-control-',dir=ROOT/'build')
        self.addCleanup(self.temp.cleanup); self.directory = Path(self.temp.name)
        self.parent_dir = self.directory/'parent'; self.parent_dir.mkdir()
        self.parent_path = self.parent_dir/'report.json'
        original = native.original_driver()
        join = self.parent_dir/Path(original.gates.replay.preparation.JOIN).name
        join.write_text(original.gates.replay.preparation.dsp_join((ROOT/original.gates.replay.preparation.JOIN).read_text()))
        _, paths = original.inputs(self.parent_dir)
        paths = set(paths) | {ROOT/'tools/cmac/prepare_dsp_prefix_checkpoint.py'}
        self.parent_proof = self.parent_dir/'external_arithmetic_proof.log'
        self.parent_proof.write_text('MOCK ONLY; NEVER A NUMERICAL QUALIFICATION\n')
        self.parent = dict(status=native.PARENT_STATUS,source_profile='dsp-prefix-c32k16',stage='complete',
            finished_utc='MOCK_ONLY',channels=32,kernels=16,parallel_products=512,
            own_numerical_parents_validated=True,source=native.fingerprint([str(p.relative_to(ROOT)) for p in paths]),
            artifacts=native.fingerprint([str(self.parent_proof.relative_to(ROOT))]))
        prep.write_json(self.parent_path,self.parent)
        self.parent_name = str(self.parent_path.relative_to(ROOT))
        self.revision = native.source_revision(self.parent_name)
        self.report_paths = {}
        for sim in ('iverilog','verilator'):
            directory = self.directory/sim; directory.mkdir()
            binary = directory/'MOCK_BINARY_NEVER_EXECUTE';binary.write_text('MOCK BINARY\n')
            log = directory/'MOCK_RUN.log';log.write_text('MOCK ONLY; NO HDL EXECUTED\n')
            record = dict(status=native.STATUS,execution_schema=1,profile=prep.PROFILE,simulator=sim,
                source_revision=self.revision,compiled_hierarchy=native.EXPECTED_HIERARCHY,
                parent_preflight=self.parent_name,parent_preflight_sha256=prep.digest(self.parent_path),
                parent_source_sha256=self.parent['source']['sha256'],
                artifacts=native.fingerprint([str(p.relative_to(ROOT)) for p in (binary,log)]))
            path = directory/'report.json';prep.write_json(path,record);self.report_paths[sim] = path
        self.copy_verifications = []
        self.api = SimpleNamespace(SPEC=native.SPEC,RESET=native.RESET,source_names=native.source_names,
                                   original_driver=native.original_driver,verify_parent=self.verify_parent,
                                   verify_report=self.verify_report)
        self.mock_api = patch.object(prep,'qualification',return_value=self.api)
        self.mock_api.start();self.addCleanup(self.mock_api.stop)

    def verify_parent(self,path):
        prep.require(Path(path).resolve() == self.parent_path.resolve(), 'Wrong mock external parent path')
        actual = prep.read_json(path)
        prep.require(actual == self.parent, 'Wrong mock external parent')
        prep.require(self.parent_proof.is_file() and prep.digest(self.parent_proof) ==
                     self.parent['artifacts']['files'][str(self.parent_proof.relative_to(ROOT))], 'External mock arithmetic DAG unavailable')
        return actual

    def verify_report(self,path,source_root=ROOT,artifact_root=ROOT,require_parents=True):
        report = prep.read_json(path)
        prep.require(report.get('status') == native.STATUS and report.get('profile') == prep.PROFILE,
                     'Unqualified startup report')
        prep.require(report.get('compiled_hierarchy') == native.EXPECTED_HIERARCHY, 'Reduced mock startup hierarchy')
        prep.require(native.fingerprint(report['source_revision']['files'],source_root) == report['source_revision'], 'Mock startup source mismatch')
        prep.require(native.fingerprint(report['artifacts']['files'],artifact_root) == report['artifacts'], 'Mock startup artifact mismatch')
        if require_parents:self.verify_parent(ROOT/report['parent_preflight'])
        else:self.copy_verifications.append((Path(source_root),Path(artifact_root)))
        return report

    def package(self):
        return prep.prepare(self.parent_path,self.report_paths['iverilog'],self.report_paths['verilator'],self.directory/'package')

    def mock_review(self,directory):
        review = prep.read_json(directory/'board-review.json')
        review.update(reviewer='MOCK CONTROL ONLY',config_voltage='1.8',cfgbvs='GND',led_active_low=0,
            checks={name:True for name in prep.common.BOARD_CHECKS},
            evidence={name:'MOCK NOT PHYSICAL BOARD EVIDENCE' for name in prep.common.BOARD_CHECKS})
        prep.write_json(directory/'board-review.json',review)

    def test_prepare_and_verify_are_file_only_and_review_starts_incomplete(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('No external tool')):
            directory = self.package();result = prep.verify(directory)
            with self.assertRaisesRegex(ValueError,'reviewer'):prep.command(directory)
        self.assertEqual(result['status'],'SOURCE_INTACT_REVIEW_PENDING')
        self.assertTrue(result['external_parent_current']);self.assertFalse(result['external_parent_closure_copied'])
        review = prep.read_json(directory/'board-review.json')
        self.assertTrue(all(value is False for value in review['checks'].values()))
        self.assertTrue(all(review[k] is None for k in ('config_voltage','cfgbvs','led_active_low')))
        self.assertTrue(self.copy_verifications)

    def test_only_top_reset_and_constraints_change_from_original_full_prefix(self):
        directory = self.package();record = prep.read_json(directory/'report.json')
        original_spec,synthesis = prep.selected(self.parent_name,directory/'source')
        self.assertEqual(original_spec,native.original_driver().inputs(self.parent_dir)[0])
        self.assertNotIn(prep.BASE_TOP,synthesis);self.assertIn(prep.TOP,synthesis)
        self.assertEqual(synthesis.count('rtl/rk_startup_reset.sv'),1)
        self.assertEqual((record['channels'],record['kernels'],record['parallel_products']),(32,16,512))
        script = (directory/'build.tcl').read_text()
        reads = [line for line in script.splitlines() if line.startswith('read_verilog ')]
        self.assertEqual(reads,['read_verilog -sv '+prep.quote(directory/'source'/name) for name in synthesis])
        self.assertIn('synth_design -top '+prep.MODULE+' ',script)
        self.assertIn('read_xdc '+prep.quote(directory/'source'/prep.CONSTRAINTS),script)
        self.assertIn(native.original_driver().GUARD,script)
        self.assertEqual(script.count('require_full_dsp_cmac\n'),2)
        self.assertNotRegex(script,r'(?m)^\s*(write_bitstream|program_hw|open_hw|set_clock_groups|set_false_path)\b')

    def test_native_evidence_copies_are_independent_and_closed(self):
        directory = self.package();self.mock_review(directory)
        for path in self.report_paths.values():shutil.rmtree(path.parent)
        with patch.object(subprocess,'Popen',side_effect=AssertionError('Do not launch Vivado')):
            result = prep.command(directory)
        self.assertEqual(result['status'],'READY_FOR_SEPARATELY_AUTHORIZED_FULL512_BUILD')
        self.assertEqual(result['environment']['RK_EMIT_BITSTREAM'],'0')
        record = prep.read_json(directory/'report.json')
        files = {str(p.relative_to(directory)) for section in ('evidence','artifacts')
                 for p in (directory/section).rglob('*') if p.is_file()}
        self.assertEqual(files,set(record['evidence_manifest']['files']))
        extra = directory/'artifacts/unqualified.log';extra.write_text('not qualified')
        with self.assertRaisesRegex(ValueError,'Unmanifested'):prep.verify(directory)

    def test_external_parent_loss_blocks_ready_but_copied_integrity_remains_checkable(self):
        directory = self.package();self.mock_review(directory)
        original_open = Path.open
        def denied_parent(path,*args,**kwargs):
            if Path(path).resolve() == self.parent_path.resolve():raise PermissionError('External parent denied')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',denied_parent):
            result = prep.verify(directory)
            self.assertEqual(result['status'],'SOURCE_INTACT_REVIEW_PENDING')
            self.assertFalse(result['external_parent_current'])
            with self.assertRaisesRegex(ValueError,'External current arithmetic qualification unavailable'):prep.command(directory)
        self.parent_proof.unlink()
        with patch.object(subprocess,'Popen',side_effect=AssertionError('No external execution')):
            result = prep.verify(directory)
            with self.assertRaisesRegex(ValueError,'External current arithmetic qualification unavailable'):prep.command(directory)
        self.assertEqual(result['status'],'SOURCE_INTACT_REVIEW_PENDING')
        self.assertFalse(result['external_parent_current'])
        self.assertFalse(result['external_parent_closure_copied'])
        self.assertTrue(any('External current arithmetic qualification unavailable' in b for b in result['blockers']))

    def test_missing_mismatched_or_legacy_native_evidence_is_rejected_before_output(self):
        path = self.report_paths['iverilog'];original = prep.read_json(path)
        for field,value in [('status','PASS_FULL_C32K16_DSP_PREFIX_RAW_BOARD_FOUR_STATE_FIXTURES_ONLY'),
                            ('parent_preflight_sha256','0'*64),('parent_source_sha256','0'*64),
                            ('parent_preflight','build/wrong/report.json'),('simulator','verilator'),
                            ('compiled_hierarchy',{})]:
            record = deepcopy(original);record[field] = value;prep.write_json(path,record)
            with self.subTest(field=field),self.assertRaises(ValueError):self.package()
            self.assertFalse((self.directory/'package').exists())
        prep.write_json(path,original)

    def test_snapshot_native_report_and_tcl_tampering_fail(self):
        directory = self.package()
        report = prep.read_json(directory/'report.json')
        binary = next(n for n in report['evidence_manifest']['files'] if n.endswith('MOCK_BINARY_NEVER_EXECUTE'))
        for name in ('source/'+prep.TOP,'evidence/verilator.json',binary,'build.tcl'):
            path = directory/name;original = path.read_bytes()
            try:
                path.write_bytes(original+b'\nchanged\n')
                with self.subTest(name=name),self.assertRaises(ValueError):prep.verify(directory)
            finally:path.write_bytes(original)
        self.assertEqual(prep.verify(directory)['status'],'SOURCE_INTACT_REVIEW_PENDING')

    def test_optimized_python_and_build_actions_are_refused(self):
        directory = self.package()
        for args,match in [(['-O',str(Path(prep.__file__)),'verify',str(directory)],'assertions'),
                           ([str(Path(prep.__file__)),'run'],'invalid choice'),
                           ([str(Path(prep.__file__)),'synth'],'invalid choice')]:
            result = subprocess.run([sys.executable,*args],text=True,capture_output=True,timeout=30)
            self.assertNotEqual(result.returncode,0);self.assertIn(match,result.stderr)
        # Load only the copied import closure in isolated Python. Rendering
        # checks neither execute Tcl nor imply that the external DAG is ready.
        code = '''from pathlib import Path
import json,runpy,sys
package=Path(sys.argv[2]);scope=runpy.run_path(sys.argv[1],run_name="copied_startup_prepare")
driver=scope["qualification"]().original_driver()
assert Path(driver.__file__).resolve().is_relative_to(package/"source")
record=json.loads((package/"report.json").read_text())
assert scope["render"](package,record["source"]["sha256"],record["forwarded_parent"]["report"])==(package/"build.tcl").read_text()
print("PASS copied import closure and checkpoint rendering; no external parent admission")
'''
        result = subprocess.run([sys.executable,'-I','-B','-c',code,
            str(directory/'source/tools/cmac/startup/prepare.py'),str(directory)],cwd='/tmp',
            text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('PASS copied import closure',result.stdout)

    def test_actual_rendered_tcl_keeps_all_full512_and_physical_gates(self):
        tclsh = shutil.which(os.environ.get('RK_TEST_TCLSH','tclsh'))
        self.assertIsNotNone(tclsh,'UNAVAILABLE: Tcl interpreter')
        probe = subprocess.run([tclsh],input='puts [info patchlevel]\nputs [llength [info commands auto_load]]\nputs [llength [info commands synth_design]]\n',
                               text=True,capture_output=True,timeout=10)
        self.assertEqual(probe.returncode,0);self.assertEqual(probe.stderr,'');self.assertEqual(probe.stdout.splitlines()[1:],['1','0'])
        directory = self.package();record = prep.read_json(directory/'report.json')
        env = {k:v for k,v in os.environ.items() if not k.startswith(('RK_','MOCK_'))}
        env.update(RK_TEST_BUILD_SCRIPT=str(directory/'build.tcl'),RK_CONFIRM_BOARD=prep.common.BOARD,
                   RK_FULL512_STARTUP_SOURCE_SHA=record['source']['sha256'],RK_CONFIG_VOLTAGE='1.8',RK_CFGBVS='GND',RK_LED_ACTIVE_LOW='0')
        harness = HARNESS.replace('set ::properties {}',EXTRA+'\nset ::properties {}')
        def run(settings):
            return subprocess.run([tclsh],input=harness,env=env|settings,text=True,capture_output=True,timeout=10)
        result = run({'MOCK_SHELL_DSPS':'7'})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix'),2)
        for settings in ({'MOCK_KERNELS':'15'},{'MOCK_FIRST_KERNEL_DSPS':'31'},{'MOCK_FIRST_KERNEL_DSPS':'33'},
                         {'MOCK_ROUTED_LAST_DSPS':'31'},{'MOCK_DUPLICATE_KERNEL':'1'},{'MOCK_NO_BRAM':'1'},
                         {'MOCK_PERIOD':'25'},{'MOCK_SLACK_MIN':'-0.1'},{'MOCK_SLACK_MAX':'NaN'},
                         {'MOCK_EMPTY_MAX':'1'},{'MOCK_DRC_SEVERITY':'Critical Warning'},{'MOCK_DRC_SEVERITY':'unknown'},
                         {'MOCK_NO_CLOCK':'1'},{'MOCK_UNCONSTRAINED_INTERNAL_ENDPOINTS':'1'},
                         {'MOCK_TIMING_REPORT':'unknown'},{'RK_CONFIG_VOLTAGE':'1.8','RK_CFGBVS':'VCCO'},
                         {'RK_EMIT_BITSTREAM':'1'}):
            with self.subTest(settings=settings):
                result = run(settings);self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertNotIn('EVENT write_bitstream',result.stdout)
        for missing in ('RK_CONFIG_VOLTAGE','RK_CFGBVS','RK_LED_ACTIVE_LOW'):
            current = dict(env);current.pop(missing)
            result = subprocess.run([tclsh],input=harness,env=current,text=True,capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0);self.assertNotIn('EVENT create_project',result.stdout)
        self.assertFalse(list(directory.rglob('*.dcp')));self.assertFalse(list(directory.rglob('*.bit')))


if __name__ == '__main__':unittest.main()
