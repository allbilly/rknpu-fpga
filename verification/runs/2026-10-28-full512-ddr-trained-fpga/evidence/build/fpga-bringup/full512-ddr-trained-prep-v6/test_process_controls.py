from __future__ import annotations
import ast, ctypes, importlib.util, json, os, pathlib, signal, subprocess, sys, tempfile, time, unittest
from unittest import mock

PKG=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('full512_ddr_trained_runner_v2',PKG/'run_sram_test.py')
runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)

class OwnedProcessTests(unittest.TestCase):
    def setUp(self): self.old_children=runner.OWNED_CHILDREN; runner.OWNED_CHILDREN=[]
    def tearDown(self): runner.OWNED_CHILDREN=self.old_children

    def test_spawn_masks_parent_and_restores_child_mask(self):
        blocked={signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGALRM}
        before=signal.pthread_sigmask(signal.SIG_BLOCK,set())
        seen={}; original=runner.subprocess.Popen
        def observe(*args,**kwargs):
            seen['during']=signal.pthread_sigmask(signal.SIG_BLOCK,set())
            return original(*args,**kwargs)
        code="import signal; print(','.join(str(int(s)) for s in signal.pthread_sigmask(signal.SIG_BLOCK,set())))"
        with tempfile.TemporaryDirectory() as td, (pathlib.Path(td)/'child.log').open('w+') as log:
            with mock.patch.object(runner.subprocess,'Popen',side_effect=observe):
                child=runner.start_owned([sys.executable,'-c',code],log,td)
            self.assertIs(runner.OWNED_CHILDREN[-1],child)
            self.assertTrue(blocked <= seen['during'])
            self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK,set()),before)
            self.assertEqual(runner.wait_owned_natural(child,10)['returncode'],0)
            log.flush(); log.seek(0)
            child_mask={int(x) for x in log.read().strip().split(',') if x}
            self.assertEqual(child_mask,{int(x) for x in before})

    def test_group_cleanup_kills_descendant_after_leader_exits(self):
        with tempfile.TemporaryDirectory() as td, (pathlib.Path(td)/'parent.log').open('w+') as log:
            descendant="import time; time.sleep(60)"
            parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"+repr(descendant)+"]); time.sleep(.25)"
            leader=runner.start_owned([sys.executable,'-c',parent],log,td)
            self.assertEqual(leader.wait(timeout=10),0)
            self.assertTrue(any(row['pid']!=leader.pid for row in runner.process_group_members(leader.pid)))
            result=runner.stop_owned(leader)
            self.assertEqual(result['members_after'],[])
            self.assertEqual(runner.live_process_group_members(leader.pid),[])

    def test_unreaped_orphan_zombie_does_not_block_group_cleanup(self):
        libc=ctypes.CDLL(None,use_errno=True)
        prctl=libc.prctl; prctl.restype=ctypes.c_int
        # Linux PR_SET_CHILD_SUBREAPER is process-local; reset it in finally.
        self.assertEqual(prctl(36,1,0,0,0),0)
        zombie_pids=[]
        try:
            with tempfile.TemporaryDirectory() as td, (pathlib.Path(td)/'parent.log').open('w+') as log:
                parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','pass']); time.sleep(.25)"
                leader=runner.start_owned([sys.executable,'-c',parent],log,td)
                self.assertEqual(leader.wait(timeout=10),0)
                deadline=time.monotonic()+3
                while time.monotonic()<deadline:
                    members=runner.process_group_members(leader.pid)
                    zombie_pids=[row['pid'] for row in members if row['state']=='Z']
                    if zombie_pids: break
                    time.sleep(.02)
                self.assertTrue(zombie_pids,'Test did not create an adopted orphan zombie')
                result=runner.stop_owned(leader)
                self.assertEqual(result['members_after'],[])
                self.assertEqual([row['pid'] for row in result['zombies_after']],zombie_pids)
                # This test process is the subreaper; explicitly reap its adopted child.
                for pid in zombie_pids: os.waitpid(pid,0)
                self.assertEqual(runner.process_group_members(leader.pid),[])
        finally:
            self.assertEqual(prctl(36,0,0,0,0),0)

    def test_actual_bridge_helper_with_mocked_ready_process(self):
        with tempfile.TemporaryDirectory() as td:
            base=pathlib.Path(td); run=base/'run'; run.mkdir(); runner.write(run/'report.json',{})
            out=base/'scratch'; calls=[]
            class Child:
                pid=990001
                def poll(self): return None
            child=Child()
            def render(target,server,tag,ready,port):
                calls.append((target,server,tag,port))
                pathlib.Path(ready).write_text('PASS_AUDITED_NATIVE_USER2_BRIDGE_READY\n')
                return 'mocked bridge script'
            logfiles=[]
            def fake_start(argv,log,cwd):
                logfiles.append(log); runner.OWNED_CHILDREN.append(child); return child
            with mock.patch.object(runner,'start_owned',side_effect=fake_start):
                actual,ready=runner.launch_bridge(out,render,None,{},run,[])
            self.assertIs(actual,child)
            self.assertEqual(calls,[(runner.TARGET,'localhost:3125',runner.SOURCE,3721)])
            self.assertEqual(ready.read_text().strip(),'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY')
            self.assertTrue((out/'bridge.tcl').is_file())
            for f in logfiles: f.close()

    def test_program_receipt_rejects_malformed_rows_and_duplicate_keys(self):
        with self.assertRaisesRegex(RuntimeError,'Malformed'):
            runner.parse_program_receipt('TARGET\tx\nBROKEN\n')
        with self.assertRaisesRegex(RuntimeError,'Duplicate'):
            runner.parse_program_receipt('TARGET\tx\nTARGET\ty\n')
        self.assertEqual(runner.parse_program_receipt('TARGET\tx\nDNA\ty\n'),{'TARGET':'x','DNA':'y'})

    def test_scratch_trace_hash_is_taken_after_trace_context_closes(self):
        source=(PKG/'run_sram_test.py').read_text()
        tree=ast.parse(source)
        trace_with=next(node for node in ast.walk(tree) if isinstance(node,ast.With) and
                        any('trace_path.open' in ast.unparse(item.context_expr) for item in node.items))
        receipt=next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and
                     'trace_sha256' in ast.unparse(node))
        trace_hash=next(node for node in ast.walk(receipt) if isinstance(node,ast.Call) and
                        ast.unparse(node.func)=='sha' and node.args and ast.unparse(node.args[0])=='trace_path')
        self.assertGreater(trace_hash.lineno,trace_with.end_lineno)
        self.assertIn('wait_owned_natural(bridge,20)',source)

    def test_scratch_directory_is_created_by_exactly_launch_bridge_owner(self):
        source=(PKG/'run_sram_test.py').read_text(); tree=ast.parse(source)
        launch=next(node for node in ast.walk(tree) if isinstance(node,ast.Call) and
                    ast.unparse(node.func)=='launch_bridge' and node.args and ast.unparse(node.args[0])=='scratch_dir')
        assignment=next(node for node in ast.walk(tree) if isinstance(node,ast.Assign) and
                        any(ast.unparse(target)=='scratch_dir' for target in node.targets))
        lines=source.splitlines()
        self.assertFalse(any('scratch_dir.mkdir' in line for line in lines[assignment.lineno-1:launch.lineno-1]))
        helper=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='launch_bridge')
        self.assertTrue(any(isinstance(node,ast.Call) and ast.unparse(node.func)=='out.mkdir' for node in ast.walk(helper)))

    def test_original_memory_gate_and_whole_trial_deadline_remain(self):
        source=(PKG/'run_sram_test.py').read_text()
        self.assertIn('require_memory(4096)',source)
        self.assertIn('signal.alarm(1200)',source)
        self.assertIn('signal.SIGALRM',source)

if __name__=='__main__': unittest.main()
