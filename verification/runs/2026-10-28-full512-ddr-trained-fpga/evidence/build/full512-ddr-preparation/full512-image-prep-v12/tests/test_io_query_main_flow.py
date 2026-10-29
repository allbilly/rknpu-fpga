import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest import mock

PACKAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_io_query_main',PACKAGE/'run_io_query.py')
query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)

class InjectedStop(RuntimeError): pass

class IOQueryMainFlowTests(unittest.TestCase):
    def test_nested_old_pin_spec_source_hash_is_required(self):
        metadata={'source_inputs':{'board_xdc':{'path':'board.xdc','preserved_copy':'copy/board.xdc','sha256':'a'*64}}}
        self.assertEqual(query.comparison_source_sha256(metadata,'board_xdc'),'a'*64)
        with self.assertRaisesRegex(ValueError,'Malformed nested source binding'):
            query.comparison_source_sha256({'source_inputs':{'board_xdc':'a'*64}},'board_xdc')

    def test_fully_admitted_main_binds_runner_and_reaches_mocked_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); base=root/'package'; base.mkdir()
            out=root/'io-snapshot'; out.mkdir(); report=out/'query-report.json'
            runner=base/'run_io_query.py'; runner.write_bytes((PACKAGE/'run_io_query.py').read_bytes())
            query_tcl=base/'io_query.tcl'; query_tcl.write_text('mock query')
            parser=base/'io_snapshot.py'; parser.write_text('# mock parser\n')
            vivado=root/'vivado'; vivado.write_text('fake vivado executable')
            dcp=root/'post_route.dcp'; dcp.write_bytes(b'bound dcp')
            route_report=root/'route-report.json'; review=root/'route-review.json'
            route_status='PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW'
            def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
            route_report.write_text(json.dumps({'status':route_status,'returncode':0,'output_hashes':{'post_route.dcp':sha(dcp)}}))
            review_status='PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY'
            review.write_text(json.dumps({'status':review_status,'post_route_dcp_sha256':sha(dcp)}))
            source=root/'source-prep'; source.mkdir(); (source/'source').mkdir()
            board=source/'source/board.xdc'; board.write_text('board')
            mig=source/'source/mig-original.xdc'; mig.write_text('mig')
            old=root/'old-pin-reference'; old.mkdir()
            for name in ('facts.tsv','properties.txt','report_io.rpt'):(old/name).write_text(name)
            comparison=old/'comparison.json'
            comparison.write_text(json.dumps({'status':'PASS_READONLY_ROUTED_IO_FACTS_COLLECTED','port_count':242,
                'mismatches':[],'unknown_actual_properties':[],
                'source_inputs':{'board_xdc':{'path':str(board),'preserved_copy':str(board),'sha256':sha(board)},
                                 'original_mig_xdc':{'path':str(mig),'preserved_copy':str(mig),'sha256':sha(mig)}}}))
            manifest={
                'vivado_sha256':sha(vivado),
                'source_inputs':{str(runner):sha(runner)},
                'route_gate':{'report_sha256':sha(route_report),'review_path':str(review),
                    'review_sha256':sha(review),'post_route_dcp_sha256':sha(dcp),
                    'post_route_dcp_path':str(dcp),'route_report_path':str(route_report),
                    'required_report_status':route_status,
                    'independent_route_review_status':review_status},
            }
            prep=base/'image-preparation.json'; prep.write_text(json.dumps(manifest))
            cg=root/'cgroup';cg.mkdir()
            for name,value in {'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'100000 100000','pids.max':'128'}.items():
                (cg/name).write_text(value)
            olddir=query.OLD; source_dir=query.SOURCE
            real_read_text=Path.read_text
            def proc_read_text(path,*args,**kwargs):
                p=str(path)
                if p=='/proc/meminfo':return 'MemAvailable: 16000000 kB\n'
                if p=='/proc/pressure/memory':return 'some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n'
                if p=='/proc/pressure/cpu':return 'some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n'
                return real_read_text(path,*args,**kwargs)
            called=[]
            def stop_at_spawn(argv,env,stdout,stderr,oldmask):
                called.append((argv,env,oldmask))
                raise InjectedStop('reached mocked native spawn boundary')
            with mock.patch.object(query,'BASE',base),mock.patch.object(query,'PREP_PATH',prep),\
                 mock.patch.object(query,'RUNNER',runner),mock.patch.object(query,'OUT',out),\
                 mock.patch.object(query,'REPORT',report),mock.patch.object(query,'QUERY_TCL',query_tcl),\
                 mock.patch.object(query,'PARSER',parser),mock.patch.object(query,'VIVADO',vivado),\
                 mock.patch.object(query,'OLD',old),mock.patch.object(query,'SOURCE',source),\
                 mock.patch.object(query,'cgroup_dir',return_value=cg),\
                 mock.patch.object(query.subprocess,'run',return_value=subprocess.CompletedProcess(['vivado','-version'],0,'Vivado mock\n','')) as version,\
                 mock.patch.object(query,'spawn_query',side_effect=stop_at_spawn),\
                 mock.patch.object(Path,'read_text',proc_read_text):
                rc=query.main()
            self.assertEqual(rc,1)
            self.assertEqual(len(called),1,json.loads(report.read_text()).get('error'))
            self.assertEqual(version.call_args.args[0],[str(vivado),'-version'])
            self.assertEqual(called[0][0][0],str(vivado))
            self.assertEqual(called[0][2],set())
            final=json.loads(report.read_text())
            self.assertEqual(final['status'],'FAIL_READ_ONLY_FULL512_IO_QUERY')
            self.assertIn(str(runner),final['input_hashes_expected'])
            self.assertEqual(final['input_hashes_expected'][str(runner)],sha(runner))
            self.assertFalse(final['hardware_accessed'])
            self.assertFalse(final['design_mutated'])

if __name__=='__main__':unittest.main()
