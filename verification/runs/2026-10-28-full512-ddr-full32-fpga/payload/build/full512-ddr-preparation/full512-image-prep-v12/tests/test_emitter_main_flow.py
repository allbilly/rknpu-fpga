import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_emitter_main',BASE/'run_image.py')
emitter=importlib.util.module_from_spec(spec);spec.loader.exec_module(emitter)

class InjectedStop(RuntimeError):pass

class EmitterMainFlowTests(unittest.TestCase):
    def test_fully_admitted_main_reaches_mocked_popen_with_no_precreated_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prep=root/'image-preparation.json';binding_path=root/'root-bindings.json'
            output=root/'emission';emit=root/'emit_full512_ch1.tcl';emit.write_text('generated Tcl text')
            dcp=root/'post_route.dcp';dcp.write_bytes(b'routed dcp')
            route_report=root/'route-report.json';route_report.write_text(json.dumps({'status':'PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW','returncode':0,'output_hashes':{'post_route.dcp':hashlib.sha256(dcp.read_bytes()).hexdigest()}}))
            route_review=root/'route-review.json';route_review.write_text(json.dumps({'status':'PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY','post_route_dcp_sha256':hashlib.sha256(dcp.read_bytes()).hexdigest()}))
            io=root/'io.json';io.write_text(json.dumps({'status':'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT','port_count':242,'dcp':{'sha256':hashlib.sha256(dcp.read_bytes()).hexdigest()}}))
            gates={};inputs={}
            for name in ['controller_case_union_33','cell_reference_review','dispatcher_review','trained_alternation_review','production_v12_regression','production_v12_root_review']:
                value={'status':'PASS_TEST'}
                if name=='controller_case_union_33':value['total_cases']=33
                path=root/(name+'.json');path.write_text(json.dumps(value));digest=hashlib.sha256(path.read_bytes()).hexdigest()
                gates[name]={'path':str(path),'sha256':digest,'required_status':'PASS_TEST','status_field':'status'}
                if name=='controller_case_union_33':gates[name].update(expected_case_count=33,count_field='total_cases')
                inputs[str(path)]=digest
            review_sha=hashlib.sha256(route_review.read_bytes()).hexdigest();report_sha=hashlib.sha256(route_report.read_bytes()).hexdigest()
            dcp_sha=hashlib.sha256(dcp.read_bytes()).hexdigest();io_sha=hashlib.sha256(io.read_bytes()).hexdigest()
            inputs.update({str(route_report):report_sha,str(route_review):review_sha,str(dcp):dcp_sha,str(io):io_sha,str(emit):hashlib.sha256(emit.read_bytes()).hexdigest()})
            sm={'schema':'full512-hardware-source-manifest-v1','top':'ypcb_ddr_dual_top','part':'xc7k480tffg1156-2','verilog_defines':['DESIGNWARE_NOEXIST'],'files':{'a':'b'}}
            hw=hashlib.sha256(json.dumps(sm,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            manifest={'status':'READY_FOR_ROOT_REVIEWED_FULL512_IMAGE_EMISSION','image_emission_approved':True,'hardware_source_manifest':sm,
              'hardware_source_sha256':hw,'source_tag':hw[:8],'route_gate':{'route_report_path':str(route_report),'report_sha256':report_sha,'required_report_status':'PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW','post_route_dcp_path':str(dcp),'post_route_dcp_sha256':dcp_sha,'review_path':str(route_review),'review_sha256':review_sha},
              'io_snapshot_gate':{'future_snapshot_json_path':str(io)},'qualification_gates':gates,'rendered_inputs':inputs,
              'resource_limits':{'timeout_seconds':2400},'vivado_path':str(root/'vivado'),'vivado_sha256':None,
              'emission_tcl_path':str(emit),'emission_tcl_sha256':hashlib.sha256(emit.read_bytes()).hexdigest()}
            actual_runner=Path(spec.origin);run_copy=root/'run_image.py';run_copy.write_bytes(actual_runner.read_bytes())
            prepare_copy=root/'prepare_image.py';prepare_copy.write_bytes((BASE/'prepare_image.py').read_bytes())
            tool=root/'vivado';tool.write_bytes(b'fake tool identity')
            manifest['vivado_path']=str(tool);manifest['vivado_sha256']=hashlib.sha256(tool.read_bytes()).hexdigest()
            manifest['emission_tcl_path']=str(emit);manifest['emission_tcl_sha256']=hashlib.sha256(emit.read_bytes()).hexdigest()
            prep.write_text(json.dumps(manifest));binding={'status':'ROOT_REVIEWED_FULL512_IMAGE_EMISSION','launch_approved':True,
              'image_preparation_sha256':hashlib.sha256(prep.read_bytes()).hexdigest(),'run_image_sha256':hashlib.sha256(run_copy.read_bytes()).hexdigest(),
              'prepare_image_sha256':hashlib.sha256(prepare_copy.read_bytes()).hexdigest(),'hardware_source_sha256':hw,'source_tag':manifest['source_tag'],
              'post_route_dcp_sha256':dcp_sha,'emission_tcl_path':str(emit),'emission_tcl_sha256':manifest['emission_tcl_sha256']}
            binding_path.write_text(json.dumps(binding))
            binding['image_preparation_sha256']=hashlib.sha256(prep.read_bytes()).hexdigest();binding_path.write_text(json.dumps(binding))
            cgroup=root/'cgroup';cgroup.mkdir()
            for name,value in {'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256','memory.peak':'0','memory.events':'oom 0'}.items():(cgroup/name).write_text(value)
            def fake_spawn(expected,output_dir,argv,env,stdout,stderr,parent_mask,cwd=BASE):
                self.assertFalse(output.exists())
                self.assertEqual(output_dir,output)
                self.assertIsInstance(env,dict)
                self.assertIn('PATH',env)
                raise InjectedStop('stop exactly at the spawn boundary')
            original_read_text=Path.read_text
            def fake_proc_read_text(path,*args,**kwargs):
                if str(path)=='/proc/meminfo':return 'MemAvailable: 30000000 kB\n'
                if str(path)=='/proc/pressure/memory':return 'some avg10=0.0 avg60=0.0 avg300=0.0 total=0\nfull avg10=0.0 avg60=0.0 avg300=0.0 total=0\n'
                if str(path)=='/proc/pressure/cpu':return 'some avg10=0.0 avg60=0.0 avg300=0.0 total=0\nfull avg10=0.0 avg60=0.0 avg300=0.0 total=0\n'
                return original_read_text(path,*args,**kwargs)
            with (
                mock.patch.object(emitter,'BASE',root),
                mock.patch.object(emitter,'PREP_PATH',prep),
                mock.patch.object(emitter,'BINDING_PATH',binding_path),
                mock.patch.object(emitter,'REPORT_PATH',root/'report.json'),
                mock.patch.object(emitter,'OUTPUT',output),
                mock.patch.object(emitter,'VIVADO',tool),
                mock.patch.object(emitter,'cgroup_dir',lambda:cgroup),
                mock.patch.object(Path,'read_text',fake_proc_read_text),
                mock.patch('subprocess.run',return_value=types.SimpleNamespace(stdout='Vivado test version',stderr='',returncode=0)),
                mock.patch.object(emitter,'spawn_emitter',side_effect=fake_spawn),
            ):
                rc=emitter.main()
            self.assertEqual(rc,1)
            report=json.loads((root/'report.json').read_text())
            self.assertIn('stop exactly at the spawn boundary',report['error'])
            self.assertEqual(report['timeout_seconds'],2400)
            self.assertFalse(output.exists())

if __name__=='__main__':unittest.main()
