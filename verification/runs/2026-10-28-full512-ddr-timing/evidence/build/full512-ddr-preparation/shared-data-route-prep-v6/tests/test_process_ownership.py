import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'run.py'
spec = importlib.util.spec_from_file_location('route_runner_process', RUNNER)
route_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_runner)

class RouteProcessOwnershipTests(unittest.TestCase):
    def test_child_signal_mask_is_restored_before_exec(self):
        parent_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            child = subprocess.Popen(
                [sys.executable, '-c',
                 'import signal,sys; mask=signal.pthread_sigmask(signal.SIG_BLOCK,set()); sys.exit(0 if signal.SIGTERM not in mask else 17)'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True,
                preexec_fn=lambda: route_runner.restore_child_signal_mask(parent_mask))
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, parent_mask)
        stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, (stdout, stderr))

    def test_cleanup_reaps_only_owned_process_group(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        route_runner.child = child
        route_runner.kill_owned(signal.SIGTERM)
        self.assertIsNotNone(child.poll())
        self.assertEqual(route_runner.owned_group_members(child.pid), [])

if __name__ == '__main__':
    unittest.main()
