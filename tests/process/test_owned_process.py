"""OS-backed lifecycle controls for tools.owned_process; no mocked process operations."""
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tools import owned_process
from tools.owned_process import live_group, run_owned


class OwnedProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='owned-process-test-')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def fixture_argv(pid_file, *, grandchild_ignores_term=False, exits=False):
        if grandchild_ignores_term:
            grand_code = 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'
        else:
            grand_code = 'import time; time.sleep(60)'
        child_code = (
            'import pathlib,subprocess,sys,time,os; '
            f'g=subprocess.Popen([sys.executable,"-c",{grand_code!r}]); '
            f'pathlib.Path({str(pid_file)!r}).write_text(f"{{os.getpid()}} {{g.pid}}\\n"); '
            + ('sys.exit(0); ' if exits else '')
            + 'exec("while True: time.sleep(0.02)")'
        )
        return [sys.executable, '-c', child_code]

    @staticmethod
    def read_pids(path, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                words = Path(path).read_text().split()
                if len(words) == 2:
                    return tuple(map(int, words))
            except OSError:
                pass
            time.sleep(0.01)
        raise AssertionError('bounded fixture did not publish child/grandchild PIDs')

    @staticmethod
    def process_alive(pid):
        try:
            fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
            return fields[0] not in ('Z', 'X')
        except FileNotFoundError:
            return False

    @classmethod
    def wait_exited(cls, pids, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not any(cls.process_alive(pid) for pid in pids):
                return True
            time.sleep(0.01)
        return False

    @classmethod
    def kill_fixture_group(cls, pid_file):
        try:
            parent, unused_grand = cls.read_pids(pid_file, timeout=0.2)
        except AssertionError:
            return
        try:
            os.killpg(parent, signal.SIGKILL)
        except ProcessLookupError:
            pass
        cls.wait_exited((parent,), timeout=2)

    def test_normal_and_nonzero_exit_results(self):
        for code in (0, 7):
            with self.subTest(returncode=code):
                result = run_owned([sys.executable, '-c', f'import sys;sys.exit({code})'],
                    timeout=5, stdout=subprocess.DEVNULL)
                self.assertEqual(result.returncode, code)
                self.assertFalse(result.timed_out)
                self.assertEqual(result.live_before_cleanup, ())
                self.assertEqual(result.live_after_cleanup, ())
                self.assertGreater(result.pid, 0)

    def test_timeout_terminates_child_and_grandchild(self):
        pid_file = self.root / 'timeout-pids'
        ready = threading.Event()
        def observe():
            try:
                self.read_pids(pid_file)
                ready.set()
            except AssertionError:
                pass
        observer = threading.Thread(target=observe, daemon=True)
        observer.start()
        try:
            result = run_owned(self.fixture_argv(pid_file), timeout=1.5, stdout=subprocess.DEVNULL)
            observer.join(1)
            self.assertTrue(ready.is_set())
            self.assertTrue(result.timed_out)
            self.assertTrue(result.live_before_cleanup)
            self.assertEqual(result.live_after_cleanup, ())
            pids = self.read_pids(pid_file)
            self.assertTrue(self.wait_exited(pids))
            self.assertEqual(live_group(result.pid), ())
        finally:
            observer.join(5.5)
            self.kill_fixture_group(pid_file)

    def test_normal_parent_exit_with_live_grandchild_is_reported_not_clean(self):
        pid_file = self.root / 'orphan-pids'
        try:
            result = run_owned(self.fixture_argv(pid_file, exits=True), timeout=5,
                               stdout=subprocess.DEVNULL)
            parent, grandchild = self.read_pids(pid_file)
            self.assertEqual(result.returncode, 0)
            self.assertFalse(result.timed_out)
            self.assertIn(grandchild, result.live_before_cleanup)
            self.assertEqual(result.live_after_cleanup, ())
            self.assertTrue(self.wait_exited((parent, grandchild)))
            self.assertEqual(live_group(result.pid), ())
        finally:
            self.kill_fixture_group(pid_file)

    def test_term_int_hup_interruptions_clean_whole_owned_group_and_restore_state(self):
        for caught_signal in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            with self.subTest(signal=caught_signal):
                pid_file = self.root / ('signal-' + str(caught_signal))
                ready = threading.Event()
                sender_errors = []
                old_handlers = {sig: signal.getsignal(sig)
                                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
                old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())

                def sender():
                    try:
                        self.read_pids(pid_file)
                        ready.set()
                        os.kill(os.getpid(), caught_signal)
                    except BaseException as error:
                        sender_errors.append(error)

                thread = threading.Thread(target=sender, daemon=True)
                thread.start()
                try:
                    with self.assertRaises(InterruptedError) as caught:
                        run_owned(self.fixture_argv(pid_file), timeout=8,
                                  stdout=subprocess.DEVNULL)
                finally:
                    thread.join(6)
                    self.kill_fixture_group(pid_file)
                self.assertFalse(thread.is_alive(), 'signal sender exceeded its bound')
                self.assertTrue(ready.is_set(), 'signal sent before child fixture became live')
                self.assertEqual(sender_errors, [])
                details = caught.exception.owned_process_cleanup
                self.assertEqual(details['live_after_cleanup'], [])
                parent, grandchild = self.read_pids(pid_file)
                self.assertTrue(self.wait_exited((parent, grandchild)))
                self.assertEqual(live_group(details['pgid']), ())
                self.assertEqual({sig: signal.getsignal(sig) for sig in old_handlers}, old_handlers)
                self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), old_mask)

    def test_signal_during_popen_return_is_deferred_until_pid_is_owned(self):
        pid_file = self.root / 'construction-window-pids'
        wrapper_entered = threading.Event()
        signal_sent = threading.Event()
        sender_errors = []
        old_handlers = {sig: signal.getsignal(sig)
                        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        real_popen = subprocess.Popen

        def delayed_popen(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            parent, grandchild = self.read_pids(pid_file)
            if parent != child.pid or os.getpgid(grandchild) != child.pid:
                raise RuntimeError('fixture child/grandchild escaped the new owned group')
            wrapper_entered.set()
            if not signal_sent.wait(3):
                raise TimeoutError('bounded construction-window signal was not delivered')
            return child

        def sender():
            try:
                if not wrapper_entered.wait(5):
                    raise TimeoutError('Popen construction window was not reached')
                os.kill(os.getpid(), signal.SIGTERM)
                signal_sent.set()
            except BaseException as error:
                sender_errors.append(error)

        thread = threading.Thread(target=sender, daemon=True)
        thread.start()
        try:
            with patch.object(owned_process.subprocess, 'Popen', side_effect=delayed_popen):
                with self.assertRaises(InterruptedError) as caught:
                    run_owned(self.fixture_argv(pid_file), timeout=8, stdout=subprocess.DEVNULL)
        finally:
            thread.join(6)
            self.kill_fixture_group(pid_file)
        self.assertFalse(thread.is_alive(), 'construction-window sender exceeded its bound')
        self.assertEqual(sender_errors, [])
        self.assertTrue(wrapper_entered.is_set() and signal_sent.is_set())
        details = caught.exception.owned_process_cleanup
        parent, grandchild = self.read_pids(pid_file)
        self.assertEqual(details['pid'], parent)
        self.assertEqual(details['pgid'], parent)
        self.assertIn(parent, details['live_before_cleanup'])
        self.assertIn(grandchild, details['live_before_cleanup'])
        self.assertEqual(details['live_after_cleanup'], [])
        self.assertTrue(self.wait_exited((parent, grandchild)))
        self.assertEqual({sig: signal.getsignal(sig) for sig in old_handlers}, old_handlers)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), old_mask)

    def test_term_ignoring_grandchild_escalates_to_kill(self):
        pid_file = self.root / 'ignore-term-pids'
        ready = threading.Event()
        def observe():
            try:
                self.read_pids(pid_file)
                ready.set()
            except AssertionError:
                pass
        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        try:
            result = run_owned(self.fixture_argv(pid_file, grandchild_ignores_term=True),
                               timeout=1.5, stdout=subprocess.DEVNULL)
            thread.join(1)
            self.assertTrue(ready.is_set())
            self.assertTrue(result.timed_out)
            self.assertTrue(result.live_before_cleanup)
            self.assertEqual(result.live_after_cleanup, ())
            pids = self.read_pids(pid_file)
            self.assertTrue(self.wait_exited(pids))
            self.assertEqual(live_group(result.pid), ())
        finally:
            thread.join(5.5)
            self.kill_fixture_group(pid_file)

    def test_invalid_timeout_does_not_start_process_and_restores_handlers_and_mask(self):
        marker = self.root / 'must-not-exist'
        argv = [sys.executable, '-c', f'from pathlib import Path;Path({str(marker)!r}).write_text("started")']
        old_handlers = {sig: signal.getsignal(sig)
                        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        for timeout in (True, False, 0, -1, float('nan'), float('inf'), -float('inf'), '1'):
            with self.subTest(timeout=repr(timeout)), self.assertRaises(ValueError):
                run_owned(argv, timeout=timeout, stdout=subprocess.DEVNULL)
            self.assertFalse(marker.exists())
        self.assertEqual({sig: signal.getsignal(sig) for sig in old_handlers}, old_handlers)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), old_mask)

    def test_spawn_failure_restores_handlers_and_signal_mask(self):
        old_handlers = {sig: signal.getsignal(sig)
                        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        with self.assertRaises(FileNotFoundError):
            run_owned([str(self.root / 'missing-executable')], timeout=2,
                      stdout=subprocess.DEVNULL)
        self.assertEqual({sig: signal.getsignal(sig) for sig in old_handlers}, old_handlers)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), old_mask)


if __name__ == '__main__':
    unittest.main()
