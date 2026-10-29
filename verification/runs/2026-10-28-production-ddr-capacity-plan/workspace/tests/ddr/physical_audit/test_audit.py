"""Synthetic-only controls for the fixed physical wire replay auditor."""
from pathlib import Path
import tempfile
import unittest

from tools.ddr import audit_physical


class PhysicalAuditTests(unittest.TestCase):
    count = 1600

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="physical replay synthetic ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upload = self.root / "upload.txt"
        self.expected = self.root / "expected.txt"
        self.before = [(0x10001000 + i * 64, (0x9e3779b97f4a7c15 * (i + 1)) & ((1 << 512) - 1))
                       for i in range(self.count)]
        self.after = [(a, value ^ (1 << (i % 512))) for i, (a, value) in enumerate(self.before)]
        self.write_fixture(self.upload, self.before)
        self.write_fixture(self.expected, self.after)
        self.wire = self.valid_stream()

    @staticmethod
    def write_fixture(path, rows):
        path.write_text("".join(f"{address:08x} {value:0128x}\n" for address, value in rows))

    @staticmethod
    def command(op, address, data=0, response=0):
        return dict(op=op, address=address, data=data, response=response)

    def valid_stream(self):
        stream = [self.command(1, 0, response=0x524b4144),
                  self.command(1, 4, response=0x10000),
                  self.command(1, 8, response=17)]
        addresses = (0x40, 0x1000, 0x1800, 0x200040, 0x1000040, 0x7fffffc0)
        for trial in range(2):
            values = {address: int.from_bytes(bytes((i * 37 + index * 19 + trial * 83) % 256
                      for i in range(64)), "little") for index, address in enumerate(addresses)}
            order = addresses if trial == 0 else addresses[::-1]
            stream.extend(self.command(4, address, data=values[address]) for address in order)
            stream.extend(self.command(3, address, response=values[address]) for address in addresses)
        stream.extend(self.command(4, address, data=value) for address, value in self.before)
        stream.extend((self.command(2, 16, 0x100e0000), self.command(2, 20, 35),
                       self.command(2, 24, 0x44445201), self.command(2, 12, 1),
                       self.command(1, 8, response=4),
                       self.command(1, 28, response=0x44445201),
                       self.command(1, 32, response=2), self.command(1, 36, response=0)))
        stream.extend(self.command(3, address, response=value) for address, value in self.after)
        stream.extend((self.command(2, 12, 2), self.command(1, 8, response=16)))
        return stream

    def replay(self, stream=None):
        return audit_physical.replay(self.wire if stream is None else stream,
                                     self.upload, self.expected)

    def test_positive_complete_synthetic_trial_is_only_a_wire_replay_control(self):
        self.assertEqual(len(self.before), 1600)
        self.assertEqual(len(self.after), 1600)
        self.assertEqual(self.before[0][0], 0x10001000)
        self.assertEqual(self.before[-1][0], 0x10019fc0)
        self.assertNotEqual(self.before, self.after)
        result = self.replay()
        self.assertEqual(result["status"], "PASS_FIXED_CH1_SCRATCH_SUB9_WIRE_REPLAY_ONLY")
        self.assertEqual((result["scratch_bytes"], result["complete_bo_bytes"], result["tasks"]),
                         (768, 102400, 2))
        self.assertTrue(result["complete_readback_before_ack"])
        self.assertFalse(result["full_capacity_qualified"])
        self.assertFalse(result["full512_integrated"])

    def test_early_ack_and_omitted_tail_readback_reject(self):
        early_ack = list(self.wire)
        ack_index = next(i for i, x in enumerate(early_ack)
                         if x["op"] == 2 and x["address"] == 12 and x["data"] == 2)
        ack = early_ack.pop(ack_index)
        first_readback = next(i for i, x in enumerate(early_ack)
                              if x["op"] == 3 and x["address"] == self.after[0][0])
        early_ack.insert(first_readback, ack)
        with self.assertRaisesRegex(ValueError, "ACK precedes complete output validation"):
            self.replay(early_ack)
        omitted = list(self.wire)
        last = next(i for i, x in enumerate(omitted)
                    if x["op"] == 3 and x["address"] == self.after[-1][0])
        omitted.pop(last)
        with self.assertRaisesRegex(ValueError, "ACK precedes complete output validation"):
            self.replay(omitted)

    def test_changed_input_upload_rejects(self):
        stream = list(self.wire)
        index = next(i for i, x in enumerate(stream)
                     if x["op"] == 4 and x["address"] == self.before[400][0])
        stream[index] = dict(stream[index], data=stream[index]["data"] ^ 1)
        with self.assertRaisesRegex(ValueError, "Actual raw upload changed"):
            self.replay(stream)

    def test_changed_result_byte_rejects(self):
        stream = list(self.wire)
        index = next(i for i, x in enumerate(stream)
                     if x["op"] == 3 and x["address"] == self.after[777][0])
        stream[index] = dict(stream[index], response=stream[index]["response"] ^ 1)
        with self.assertRaisesRegex(ValueError, "Actual complete output differs"):
            self.replay(stream)

    def test_wrong_completion_tag_or_task_count_rejects(self):
        for offset, value in ((28, 0x44445202), (32, 3)):
            with self.subTest(offset=offset):
                stream = list(self.wire)
                index = next(i for i, x in enumerate(stream)
                             if x["op"] == 1 and x["address"] == offset)
                stream[index] = dict(stream[index], response=value)
                with self.assertRaisesRegex(ValueError, "Actual completion tag/task/error differs"):
                    self.replay(stream)

    def test_missing_identity_and_unmodeled_csr_or_reset_reject(self):
        missing_id = list(self.wire)
        missing_id.pop(0)
        with self.assertRaisesRegex(ValueError, "Wrong actual ABI"):
            self.replay(missing_id)
        stream = list(self.wire)
        stream.insert(3, self.command(1, 0x80, response=0))
        with self.assertRaisesRegex(ValueError, "Unmodeled actual CSR read"):
            self.replay(stream)
        stream = list(self.wire)
        stream.append(self.command(2, 12, 4))
        with self.assertRaisesRegex(ValueError, "Unmodeled CSR write or reset attempt"):
            self.replay(stream)


if __name__ == "__main__":
    unittest.main()
