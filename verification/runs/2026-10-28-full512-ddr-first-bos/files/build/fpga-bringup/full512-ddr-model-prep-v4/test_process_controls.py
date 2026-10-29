from __future__ import annotations
import ast,ctypes,importlib.util,json,os,pathlib,signal,subprocess,sys,tempfile,time,unittest,io,contextlib
from unittest import mock

PKG=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('full512_ddr_model_runner',PKG/'run_full_model.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class OwnedProcessTests(unittest.TestCase):
    def setUp(self):self.old=runner.OWNED;runner.OWNED=[]
    def tearDown(self):runner.OWNED=self.old

    def test_spawn_masks_parent_and_restores_child_signal_mask(self):
        blocked={signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGALRM}
        before=signal.pthread_sigmask(signal.SIG_BLOCK,set());seen={};original=runner.subprocess.Popen
        def observe(*args,**kwargs):
            seen['mask']=signal.pthread_sigmask(signal.SIG_BLOCK,set());return original(*args,**kwargs)
        code="import signal; print(','.join(str(int(s)) for s in signal.pthread_sigmask(signal.SIG_BLOCK,set())))"
        with tempfile.TemporaryDirectory() as td,(pathlib.Path(td)/'log').open('w+') as log:
            with mock.patch.object(runner.subprocess,'Popen',side_effect=observe):child=runner.start_owned([sys.executable,'-c',code],log,td)
            self.assertIs(runner.OWNED[-1],child);self.assertTrue(blocked<=seen['mask'])
            self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK,set()),before)
            self.assertEqual(runner.wait_owned_natural(child,10)['returncode'],0)
            log.flush();log.seek(0);child_mask={int(x) for x in log.read().strip().split(',') if x}
            self.assertEqual(child_mask,{int(x) for x in before})

    def test_owned_group_kills_live_descendant_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as td,(pathlib.Path(td)/'parent.log').open('w+') as log:
            descendant='import time;time.sleep(60)'
            parent='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(descendant)+']);time.sleep(.25)'
            leader=runner.start_owned([sys.executable,'-c',parent],log,td);self.assertEqual(leader.wait(timeout=10),0)
            self.assertTrue(any(x['pid']!=leader.pid for x in runner.process_group_members(leader.pid)))
            result=runner.stop_owned(leader);self.assertEqual(result['live_after'],[])
            self.assertEqual(runner.live_group_members(leader.pid),[])

    def test_final_cleanup_scans_exited_leader_group_for_live_descendant(self):
        with tempfile.TemporaryDirectory() as td,(pathlib.Path(td)/'parent.log').open('w+') as log:
            descendant='import time;time.sleep(60)'
            parent='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(descendant)+']);time.sleep(.25)'
            leader=runner.start_owned([sys.executable,'-c',parent],log,td)
            self.assertEqual(leader.wait(timeout=10),0)
            self.assertTrue(any(x['pid']!=leader.pid and x['state'] not in {'Z','X'} for x in runner.process_group_members(leader.pid)))
            result=runner.cleanup_owned()
            self.assertTrue(any(x['pid']==leader.pid for x in result))
            self.assertEqual(runner.live_group_members(leader.pid),[])

    def test_main_finally_checks_every_owned_group_without_leader_poll_guard(self):
        tree=ast.parse((PKG/'run_full_model.py').read_text())
        main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
        cleanup=next(x for x in ast.walk(main) if isinstance(x,ast.Try) and x.finalbody and
                     any(isinstance(n,ast.Call) and ast.unparse(n.func)=='cleanup_owned' for n in ast.walk(ast.Module(body=x.finalbody,type_ignores=[]))))
        self.assertFalse(any(isinstance(n,ast.If) and 'child.poll()' in ast.unparse(n.test) and
                             'cleanup_owned' in ast.unparse(n) for n in ast.walk(cleanup)))

    def test_artifact_map_excludes_only_parent_report_and_keeps_worker_and_load_reports(self):
        with tempfile.TemporaryDirectory() as td:
            physical=pathlib.Path(td)/'physical-tests';physical.mkdir()
            (physical/'report.json').write_text('{"parent":true}\n')
            jobs=physical/'one-complete-forward-position'/'jobs';jobs.mkdir(parents=True)
            worker=jobs/'report.json';worker.write_text('{"worker":true}\n')
            load=physical/'load-1';load.mkdir();load_report=load/'report.json';load_report.write_text('{"load":true}\n')
            native_log=load/'native.stdout.log';native_log.write_text('native capture\n')
            artifacts=runner.physical_artifact_map(physical)
            self.assertNotIn('report.json',artifacts)
            self.assertEqual(set(artifacts),{
                'one-complete-forward-position/jobs/report.json',
                'load-1/report.json','load-1/native.stdout.log'})
            self.assertEqual(artifacts['one-complete-forward-position/jobs/report.json'],runner.sha(worker))

    def test_orphaned_unreaped_zombie_does_not_block_group_cleanup(self):
        libc=ctypes.CDLL(None,use_errno=True);prctl=libc.prctl;prctl.restype=ctypes.c_int
        self.assertEqual(prctl(36,1,0,0,0),0);zombies=[]
        try:
            with tempfile.TemporaryDirectory() as td,(pathlib.Path(td)/'parent.log').open('w+') as log:
                leader=runner.start_owned([sys.executable,'-c',"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','pass']);time.sleep(.25)"],log,td)
                self.assertEqual(leader.wait(timeout=10),0);limit=time.monotonic()+3
                while time.monotonic()<limit:
                    zombies=[x['pid'] for x in runner.process_group_members(leader.pid) if x['state']=='Z']
                    if zombies:break
                    time.sleep(.02)
                self.assertTrue(zombies)
                result=runner.stop_owned(leader);self.assertEqual(result['live_after'],[])
                self.assertEqual([x['pid'] for x in result['zombies_after']],zombies)
                for pid in zombies:os.waitpid(pid,0)
        finally:self.assertEqual(prctl(36,0,0,0,0),0)

    def test_phase_bridge_helper_creates_its_own_directory_and_tracks_process(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td);physical=base/'physical';physical.mkdir();runner.write(physical/'report.json',{})
            phase=physical/'one-complete-forward-position';phase.mkdir();record={};logs=[];calls=[]
            class Child:
                pid=992021
                def poll(self):return None
            child=Child()
            def render(target,server,tag,ready,port):
                calls.append((target,server,tag,port));pathlib.Path(ready).write_text('PASS_AUDITED_NATIVE_USER2_BRIDGE_READY\n');return 'mock tcl'
            def start(argv,out,cwd):runner.OWNED.append(child);logs.append(out);return child
            with mock.patch.object(runner,'start_owned',side_effect=start):actual,ready=runner.launch_phase_bridge(phase,render,record,physical,logs)
            self.assertIs(actual,child);self.assertEqual(calls,[(runner.TARGET,'localhost:3125',runner.SOURCE_TAG,3721)])
            self.assertEqual(ready.read_text().strip(),'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY')
            self.assertTrue((phase/'bridge'/'bridge.tcl').is_file())
            for f in logs:
                if not f.closed:f.close()

    def test_model_worker_has_original_per_worker_deadline_and_no_trial_alarm(self):
        source=(PKG/'run_full_model.py').read_text();prep=json.loads((PKG/'preparation.json').read_text())
        self.assertEqual(prep['worker_contract']['per_worker_timeout_seconds'],14400)
        self.assertIn('worker.wait(timeout=14400)',source)
        self.assertNotIn('signal.alarm(',source)
        self.assertIn("'--memory-wait-budget-seconds','900'",source)

    def test_successful_main_entry_returns_zero_for_actual_system_exit(self):
        report={'status':'PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT','hardware_accessed':False}
        stdout=io.StringIO()
        with mock.patch.object(runner,'main',return_value=report),contextlib.redirect_stdout(stdout):
            code=runner.main_entry()
        with self.assertRaises(SystemExit) as raised:
            raise SystemExit(code)
        self.assertEqual(raised.exception.code,0)
        self.assertIn('"hardware_accessed": false',stdout.getvalue())

    def test_failed_main_entry_reports_recorded_programming_state_truthfully(self):
        with tempfile.TemporaryDirectory() as td:
            old_pkg=runner.PKG;runner.PKG=pathlib.Path(td)
            report=runner.PKG/'physical-test'/'physical-tests'/'report.json';report.parent.mkdir(parents=True)
            report.write_text(json.dumps({'status':'FAIL_USER2_PHYSICAL_TEST','hardware_accessed':True,
                'hardware_programmed':True,'hardware_programming_may_have_occurred':True,
                'flash_written':False,'failure_utc':'2026-10-28T03:00:00+00:00','error':'phase failure'})+'\n')
            stderr=io.StringIO()
            try:
                with mock.patch.object(runner,'main',side_effect=RuntimeError('phase failure')),contextlib.redirect_stderr(stderr):
                    code=runner.main_entry()
            finally:runner.PKG=old_pkg
            self.assertEqual(code,2)
            row=json.loads(stderr.getvalue())
            self.assertEqual(row['status'],'FAIL_USER2_PHYSICAL_TEST')
            self.assertIs(row['hardware_accessed'],True)
            self.assertIs(row['hardware_programmed'],True)
            self.assertIs(row['hardware_programming_may_have_occurred'],True)
            self.assertIs(row['flash_written'],False)
            self.assertNotIn('"hardware_accessed": false',stderr.getvalue())

    def test_controls_audit_immediately_and_greedy_audits_after_services_stop(self):
        tree=ast.parse((PKG/'run_full_model.py').read_text());main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
        loop=next(x for x in ast.walk(main) if isinstance(x,ast.For) and 'phase_specs()' in ast.unparse(x.iter))
        self.assertTrue(any(isinstance(x,ast.Call) and ast.unparse(x.func)=='launch_phase_bridge' for x in ast.walk(loop)))
        self.assertTrue(any(isinstance(x,ast.Call) and ast.unparse(x.func)=='run_public_phase_audit' for x in ast.walk(loop)))
        audits=[x.lineno for x in ast.walk(loop) if isinstance(x,ast.Call) and ast.unparse(x.func)=='run_public_phase_audit']
        worker=[x.lineno for x in ast.walk(loop) if isinstance(x,ast.Call) and ast.unparse(x.func)=='worker_argv']
        self.assertEqual(len(audits),1);self.assertEqual(len(worker),1)
        self.assertGreater(audits[0],worker[0])
        final_phase=next(x for x in ast.walk(loop) if isinstance(x,ast.If) and "PHASES[-1][0]" in ast.unparse(x.test))
        self.assertTrue(any(isinstance(x,ast.Call) and ast.unparse(x.func)=='stop_owned' for x in ast.walk(final_phase)))
        self.assertGreater(audits[0],final_phase.end_lineno)

if __name__=='__main__':unittest.main()
