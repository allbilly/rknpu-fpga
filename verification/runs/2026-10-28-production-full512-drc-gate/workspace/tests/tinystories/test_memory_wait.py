"""Host resource admission controls; no transport, model or FPGA execution."""
from pathlib import Path
import tempfile
import unittest

from tools.tinystories.progress import MemoryGate


class Clock:
    def __init__(self):self.now=0.0;self.sleeps=[];self.after_sleep=lambda:None
    def __call__(self):return self.now
    def sleep(self,seconds):
        self.sleeps.append(seconds);self.now+=seconds;self.after_sleep()


class MemoryWaitTests(unittest.TestCase):
    def fixture(self,budget=10):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        path=Path(directory.name)/'meminfo';clock=Clock()
        def available(kib):path.write_text(f'MemAvailable: {kib} kB\n')
        available(1024)
        return MemoryGate(2,budget,path=path,clock=clock,sleep=clock.sleep),clock,available

    def test_default_is_immediate_explicit_failure_without_wait(self):
        gate,clock,_=self.fixture(0)
        with self.assertRaisesRegex(ValueError,'Host memory resource gate: 1024 KiB available, 2048 KiB required'):
            gate.check()
        self.assertEqual(clock.sleeps,[]);self.assertEqual(gate.waited_seconds,0)

    def test_recovery_waits_without_retrying_or_replacing_work(self):
        gate,clock,available=self.fixture();states=[]
        clock.after_sleep=lambda:available(3072)
        self.assertEqual(gate.check(states.append),3072)
        self.assertEqual(clock.sleeps,[5])
        self.assertEqual([s['waiting'] for s in states],[True,False])
        self.assertEqual(gate.waited_seconds,5);self.assertEqual(gate.summary()['remaining_seconds'],5)

    def test_budget_is_cumulative_across_projection_boundaries(self):
        gate,clock,available=self.fixture(7)
        clock.after_sleep=lambda:available(4096)
        self.assertEqual(gate.check(),4096)
        available(512);clock.after_sleep=lambda:None
        with self.assertRaisesRegex(ValueError,'budget exhausted'):gate.check()
        self.assertEqual(clock.sleeps,[5,2]);self.assertEqual(gate.waited_seconds,7)
        self.assertEqual(gate.wait_events,2)

    def test_scheduler_and_recording_stalls_cannot_extend_budget(self):
        gate,clock,available=self.fixture(4)
        def scheduler_stall():clock.now+=1;available(4096)
        clock.after_sleep=scheduler_stall
        with self.assertRaisesRegex(ValueError,'budget exhausted'):gate.check()
        self.assertEqual(gate.waited_seconds,5)
        gate,clock,_=self.fixture(4)
        def recorder_stall(state):clock.now+=5
        with self.assertRaisesRegex(ValueError,'budget exhausted'):gate.check(recorder_stall)
        self.assertEqual(clock.sleeps,[])

    def test_wait_errors_are_not_hidden_or_restarted(self):
        gate,clock,_=self.fixture()
        def disk_failure(state):raise OSError('progress recording failed')
        with self.assertRaisesRegex(OSError,'progress recording failed'):gate.check(disk_failure)
        self.assertEqual(clock.sleeps,[])
        gate.path.write_text('MemAvailable: unknown MB\n')
        with self.assertRaisesRegex(ValueError,'not readable'):gate.check()

    def test_disabled_guard_does_not_sample_and_invalid_policies_fail(self):
        gate=MemoryGate(0,0,path=Path('/unavailable/fixture/meminfo'))
        self.assertIsNone(gate.check())
        for minimum,budget in [(0,1),(2,-1),(2,float('inf')),(2,float('nan')),(True,0),(2,True)]:
            with self.subTest(minimum=minimum,budget=budget):
                with self.assertRaises(ValueError):MemoryGate(minimum,budget)


if __name__=='__main__':unittest.main()
