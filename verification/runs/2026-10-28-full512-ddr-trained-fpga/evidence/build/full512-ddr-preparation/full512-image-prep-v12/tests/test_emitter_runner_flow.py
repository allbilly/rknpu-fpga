import hashlib
import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

RUNNER=Path(__file__).resolve().parents[1]/'run_image.py'
spec=importlib.util.spec_from_file_location('full512_image_runner',RUNNER)
image_runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(image_runner)

class EmitterRunnerFlowTests(unittest.TestCase):
    def test_root_approval_required_before_emission(self):
        with self.assertRaisesRegex(ValueError,'Full512 image DAG is not ready'):
            image_runner.require_root_emission_approval({'status':'UNLAUNCHABLE','image_emission_approved':False},
                {'status':'UNLAUNCHABLE','launch_approved':False})

    def test_output_directory_is_absent_at_spawn_and_no_output_is_created_by_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'emission';input_file=root/'route.dcp';input_file.write_bytes(b'bound route')
            expected={str(input_file):hashlib.sha256(input_file.read_bytes()).hexdigest()};observed=[]
            parent_mask=signal.pthread_sigmask(signal.SIG_BLOCK,set())
            def fake_popen(argv,**kwargs):
                self.assertFalse(out.exists())
                observed.append((argv,kwargs['cwd']))
                return object()
            result=image_runner.spawn_emitter(expected,out,['fake-vivado'],{},None,None,parent_mask,cwd=root,popen=fake_popen)
            signal.pthread_sigmask(signal.SIG_SETMASK,parent_mask)
            self.assertEqual(len(observed),1);self.assertIsNotNone(result)
            self.assertFalse(out.exists())

    def test_changed_input_fails_before_emitter_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'emission';route=root/'route.dcp';route.write_bytes(b'expected')
            expected={str(route):hashlib.sha256(route.read_bytes()).hexdigest()};route.write_bytes(b'tampered')
            called=[]
            with self.assertRaisesRegex(ValueError,'bound full512 image inputs changed'):
                image_runner.spawn_emitter(expected,out,['fake-vivado'],{},None,None,set(),cwd=root,popen=lambda *a,**k:called.append(True))
            self.assertEqual(called,[]);self.assertFalse(out.exists())

    def test_existing_output_fails_before_emitter_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'emission';out.mkdir();route=root/'route.dcp';route.write_bytes(b'route')
            expected={str(route):hashlib.sha256(route.read_bytes()).hexdigest()};called=[]
            with self.assertRaisesRegex(ValueError,'output directory must be absent'):
                image_runner.spawn_emitter(expected,out,['fake-vivado'],{},None,None,set(),cwd=root,popen=lambda *a,**k:called.append(True))
            self.assertEqual(called,[])

    def test_child_signal_mask_restored_before_exec(self):
        original=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGTERM})
        try:
            proc=subprocess.Popen([sys.executable,'-c',
                'import signal,sys; mask=signal.pthread_sigmask(signal.SIG_BLOCK,set()); sys.exit(0 if signal.SIGTERM not in mask else 19)'],
                start_new_session=True,preexec_fn=lambda:image_runner.restore_child_signal_mask(original),
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        finally:signal.pthread_sigmask(signal.SIG_SETMASK,original)
        stdout,stderr=proc.communicate(timeout=10)
        self.assertEqual(proc.returncode,0,(stdout,stderr))

    def test_cleanup_stops_only_owned_group(self):
        proc=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
        image_runner.CHILD=proc
        image_runner.kill_owned(signal.SIGTERM)
        self.assertIsNotNone(proc.poll())
        self.assertEqual(image_runner.group_pids(proc.pid),[])

if __name__=='__main__':unittest.main()
