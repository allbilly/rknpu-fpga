import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.ddr import capacity_client as client


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeOwner:
    """Direct fake owner API only: no raw socket, TAP, or hardware use."""
    def __init__(self, *, base=0, size=1 << 31, statuses=None, counters=None,
                 identity=client.ID, abi=client.ABI, namespace_status=(0x10, 0x10),
                 seed_readback=None, faults=None):
        self._mutex = threading.RLock()
        self._active_tag = None
        self._result = None
        self._failed = False
        self._clock = FakeClock()
        self._usable_calls = 0
        self._statuses = list(statuses or [1, 0x40, 0x68])
        self._counters = list(counters or [(0, 0), (0, 0), (4, 4)])
        self._counter_index = 0
        self._namespace_status = namespace_status
        self._seed_readback = seed_readback
        self._faults = faults or (0, 0, 0, 0, [0] * 16, [0] * 16)
        self._regs = {0x200: identity, 0x204: abi, 0x214: size, 0x218: base,
                      0x21c: 0x00020040, 0x220: 0, 0x224: 0, 0x228: 0,
                      0x22c: 0, 0x230: 0}
        self.writes = []
        self.reads = []
        self.progress = []

    def _usable(self):
        self._usable_calls += 1
        if self._failed:
            raise client.ProtocolError('owner poisoned')

    def _sleep(self, seconds):
        self._clock.advance(seconds)

    def _command(self, opcode, address, value=None, *, deadline=None):
        if opcode == 2:
            self.writes.append((address, value))
            if address == 0x210:
                self._regs[0x210] = value if self._seed_readback is None else self._seed_readback
            elif address == 0x20c:
                self._regs[0x20c] = value
            return 0
        if opcode != 1:
            raise AssertionError(f'unexpected opcode {opcode}')
        self.reads.append(address)
        if address == 0x208:
            if len(self._statuses) > 1:
                return self._statuses.pop(0)
            return self._statuses[0]
        if address in (0x220, 0x224):
            pair = self._counters[min(self._counter_index, len(self._counters) - 1)]
            if address == 0x224:
                self._counter_index += 1
            return pair[0 if address == 0x220 else 1]
        if address == 0x008:
            return self._namespace_status[0]
        if address == 0x108:
            return self._namespace_status[1]
        if address == 0x210 and self._seed_readback is not None:
            return self._seed_readback
        mismatch, expected, actual = self._faults[3], self._faults[4], self._faults[5]
        if address == 0x228:
            return self._faults[0]
        if address == 0x22c:
            return self._faults[1]
        if address == 0x230:
            return mismatch
        if 0x240 <= address < 0x280 and address % 4 == 0:
            return expected[(address - 0x240) // 4]
        if 0x280 <= address < 0x2c0 and address % 4 == 0:
            return actual[(address - 0x280) // 4]
        return self._regs.get(address, 0)


class CapacityClientTests(unittest.TestCase):
    def run_client(self, owner, **kwargs):
        return client.CapacityClient(owner).run(timeout=kwargs.pop('timeout', 1.0), poll_seconds=kwargs.pop('poll_seconds', 0.1), **kwargs)

    def test_success_full_window_and_exact_counts(self):
        owner = FakeOwner(counters=[(0, 0), (1 << 26, 1 << 26)])
        c = client.CapacityClient(owner)
        result = c.run(timeout=1, poll_seconds=.1, on_progress=lambda row: owner.progress.append(row))
        self.assertEqual(result['status'], 'PASS_DEVICE_BIST_REQUIRES_IMAGE_AND_WIRE_AUDIT')
        self.assertEqual(result['device_status'], 0x68)
        self.assertEqual((result['completed_writes'], result['completed_reads']), (1 << 26, 1 << 26))
        self.assertEqual(result['full_window_executed'], True)
        self.assertEqual(result['physical_capacity_qualified'], False)
        self.assertEqual(owner.writes, [(0x210, 0x3588c350), (0x20c, 1)])
        self.assertEqual(owner.progress[-1]['status'], 0x68)
        self.assertFalse(owner._failed)

    def test_partial_window_rejected_by_default_before_writes(self):
        owner = FakeOwner(base=0x1000, size=0x100)
        with self.assertRaisesRegex(client.ProtocolError, 'complete two-GiB'):
            self.run_client(owner)
        self.assertEqual(owner.writes, [])
        self.assertTrue(owner._failed)

    def test_partial_window_requires_explicit_opt_in_and_never_claims_full(self):
        owner = FakeOwner(base=0x1000, size=0x100, counters=[(0, 0), (8, 8)])
        result = self.run_client(owner, require_full_window=False)
        self.assertEqual(result['base'], 0x1000)
        self.assertEqual(result['size'], 0x100)
        self.assertFalse(result['full_window_executed'])
        self.assertFalse(result['physical_capacity_qualified'])

    def test_identity_and_abi_fail_before_any_write(self):
        for kwargs in ({'identity': 0}, {'abi': 2}):
            with self.subTest(kwargs=kwargs):
                owner = FakeOwner(**kwargs)
                with self.assertRaisesRegex(client.ProtocolError, 'identity/ABI'):
                    self.run_client(owner)
                self.assertEqual(owner.writes, [])

    def test_both_job_namespaces_must_be_idle_before_write(self):
        for status in ((0x10, 0), (0, 0x10)):
            with self.subTest(status=status):
                owner = FakeOwner(namespace_status=status)
                with self.assertRaisesRegex(client.DeviceBusy, 'Both raw job namespaces'):
                    self.run_client(owner)
                self.assertEqual(owner.writes, [])

    def test_seed_readback_mismatch_never_starts_and_poisons_uncertain_owner(self):
        owner = FakeOwner(seed_readback=0x12345678)
        with self.assertRaisesRegex(client.ProtocolError, 'Seed readback mismatch'):
            self.run_client(owner)
        self.assertEqual(owner.writes, [(0x210, 0x3588c350)])
        self.assertTrue(owner._failed)
        self.assertFalse(any(address == 0x20c for address, _ in owner.writes))

    def test_fault_retains_full_sixteen_word_expected_actual_snapshot(self):
        expected = [0x1000 + i for i in range(16)]
        actual = [0x2000 + i for i in range(16)]
        faults = (0x12, 0x3, 0x55, 0x1234, expected, actual)
        owner = FakeOwner(statuses=[1, 0x50], counters=[(0, 0)], faults=faults)
        c = client.CapacityClient(owner)
        with self.assertRaises(client.CapacityFault) as caught:
            c.run(timeout=1, poll_seconds=.1)
        snapshot = caught.exception.snapshot
        self.assertEqual(snapshot['mismatch_address'], 0x1234)
        self.assertEqual(snapshot['mismatch_expected_words'], expected)
        self.assertEqual(snapshot['mismatch_actual_words'], actual)
        self.assertEqual(owner.writes[-1], (0x20c, 1))
        self.assertTrue(owner._failed)

    def test_counter_regression_rejected_and_poisons_owner(self):
        owner = FakeOwner(statuses=[1, 0x40, 0x40], counters=[(0, 0), (3, 3), (2, 2)])
        with self.assertRaisesRegex(client.ProtocolError, 'counters regressed'):
            self.run_client(owner)
        self.assertTrue(owner._failed)

    def test_unknown_status_bits_rejected_and_poisons_owner(self):
        owner = FakeOwner(statuses=[1, 0xC0], counters=[(0, 0)])
        with self.assertRaisesRegex(client.ProtocolError, 'Unmodeled RKMT status'):
            self.run_client(owner)
        self.assertTrue(owner._failed)

    def test_final_health_change_rejects_cached_success(self):
        owner = FakeOwner(base=0x1000, size=0x80,
                          statuses=[1, 0x40, 0x68, 0x40], counters=[(0, 0), (4, 4)])
        with self.assertRaisesRegex(client.ProtocolError, 'Health/ownership changed'):
            self.run_client(owner, require_full_window=False)
        self.assertTrue(owner._failed)

    def test_timeout_after_start_poisons_owner_without_retry_or_reset(self):
        owner = FakeOwner(statuses=[1, 0x40], counters=[(0, 0)])
        with self.assertRaises(TimeoutError):
            self.run_client(owner, timeout=.1, poll_seconds=.1)
        self.assertEqual([a for a, _ in owner.writes].count(0x20c), 1)
        self.assertTrue(owner._failed)
        self.assertFalse(any(a not in (0x210, 0x20c) for a, _ in owner.writes))

    def test_status_and_window_argument_contracts(self):
        with self.assertRaises(ValueError):
            self.run_client(FakeOwner(), require_full_window=1)
        with self.assertRaises(ValueError):
            self.run_client(FakeOwner(), seed=-1)
        owner = FakeOwner(base=1, size=64)
        with self.assertRaisesRegex(client.ProtocolError, 'address window'):
            self.run_client(owner, require_full_window=False)
        self.assertEqual(owner.writes, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
