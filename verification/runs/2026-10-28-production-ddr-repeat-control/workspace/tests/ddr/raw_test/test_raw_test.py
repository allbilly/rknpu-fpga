"""Pure fake-device controls for raw BO DDR test helpers; no hardware proof."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.ddr import raw_test


class FakeRecordingDevice:
    def __init__(self, memory=None, *, mismatch_at=None, fail_read_at=None,
                 result=None, output_memory=None):
        self.memory = dict(memory or {})
        self.mismatch_at = mismatch_at
        self.fail_read_at = fail_read_at
        self.result = result
        self.output_memory = output_memory
        self.calls = []

    def wait_memory_ready(self, timeout=30.0):
        self.calls.append(("wait_memory_ready", timeout))

    def mem_write(self, address, data):
        self.calls.append(("mem_write", address, bytes(data)))
        self.memory[address] = bytes(data)

    def submit(self, command_address, initial_amount, tag):
        self.calls.append(("submit", command_address, initial_amount, tag))
        if self.output_memory is not None:
            self.memory.update(self.output_memory)

    def poll_result(self, timeout=30.0):
        self.calls.append(("poll_result", timeout))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result or Result(self.calls[-2][3], 3, 0, 4)

    def mem_read(self, address, size):
        self.calls.append(("mem_read", address, size))
        if address == self.fail_read_at:
            raise TimeoutError("fake read timeout")
        data = self.memory[address]
        if address == self.mismatch_at:
            return bytes([data[0] ^ 1]) + data[1:]
        return data[:size]

    def ack_success(self):
        self.calls.append(("ack_success",))


class Result:
    def __init__(self, tag, completed_tasks, error_code, status):
        self.tag = tag
        self.completed_tasks = completed_tasks
        self.error_code = error_code
        self.status = status


def raw_line(address, data):
    return f"{address:08x} {int.from_bytes(data, 'little'):0128x}\n"


def calls_of(device, name):
    return [call for call in device.calls if call[0] == name]


class RawTestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="raw BO fake test ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.upload = self.root / "upload.txt"
        self.expected = self.root / "expected.txt"
        self.output = self.root / "captured.txt"
        self.addresses = (0, 0x1000, 0x1080)
        self.upload_data = {a: bytes((i * 5 + n * 17) & 255 for i in range(64))
                            for n, a in enumerate(self.addresses)}
        self.expected_data = {a: bytes((x ^ 0xA5) for x in data)
                              for a, data in self.upload_data.items()}
        self.write_image(self.upload, self.upload_data)
        self.write_image(self.expected, self.expected_data)

    @staticmethod
    def write_image(path, rows):
        path.write_text("".join(raw_line(a, rows[a]) for a in sorted(rows)))

    def device(self, **kwargs):
        return FakeRecordingDevice(self.upload_data, output_memory=self.expected_data, **kwargs)

    def run_valid(self, device=None, **kwargs):
        device = device or self.device()
        result = raw_test.run_case(device, self.upload, self.expected, self.output,
                                   command_address=0, initial_amount=9,
                                   expected_tasks=3, tag=0x12345678, **kwargs)
        return device, result

    def test_uploads_exact_raw_bytes_and_command_address_zero_is_legal_when_uploaded(self):
        device, result = self.run_valid()
        self.assertEqual(calls_of(device, "mem_write"),
                         [("mem_write", a, self.upload_data[a]) for a in self.addresses])
        self.assertEqual(calls_of(device, "submit"), [("submit", 0, 9, 0x12345678)])
        self.assertEqual(result["checked_bo_bytes"], 3 * 64)
        self.assertEqual(result["status"], "PASS_RAW_CASE_READBACK_AND_ACK")
        self.assertEqual(self.output.read_text(), "".join(raw_line(a, self.expected_data[a]) for a in self.addresses))
        self.assertEqual(calls_of(device, "ack_success"), [("ack_success",)])
        self.assertEqual([x[1] for x in calls_of(device, "mem_read")], list(self.addresses))

    def test_rejects_invalid_records_result_contract_and_bad_output_before_device_actions(self):
        malformed = ["bad\n", "00000000 " + "0" * 127 + "\n",
                     raw_line(0, bytes(64)) + raw_line(0, bytes(64)),
                     raw_line(1, bytes(64)), raw_line(0x80000000, bytes(64))]
        for i, contents in enumerate(malformed):
            with self.subTest(kind=i):
                self.upload.write_text(contents)
                dev = self.device()
                with self.assertRaises(ValueError):
                    self.run_valid(dev)
                self.assertEqual(dev.calls, [])
        self.write_image(self.upload, self.upload_data)
        self.write_image(self.expected, self.upload_data)
        dev = self.device()
        with self.assertRaisesRegex(ValueError, "require observable memory changes"):
            self.run_valid(dev)
        self.assertEqual(dev.calls, [])
        self.write_image(self.expected, self.expected_data)
        for result in (Result(7, 3, 0, 4), Result(0x12345678, 2, 0, 4),
                       Result(0x12345678, 3, 1, 4), Result(0x12345678, 3, 0, 0x24)):
            with self.subTest(result=(result.tag, result.completed_tasks, result.error_code, result.status)):
                dev = self.device(result=result)
                with self.assertRaisesRegex(ValueError, "fixed descriptor contract"):
                    self.run_valid(dev)
                self.assertFalse(calls_of(dev, "mem_read"))
                self.assertFalse(calls_of(dev, "ack_success"))
        occupied = self.root / "occupied"
        occupied.write_text("keep")
        dev = self.device()
        with self.assertRaisesRegex(ValueError, "Fresh complete readback path"):
            raw_test.run_case(dev, self.upload, self.expected, occupied,
                              command_address=0, initial_amount=9,
                              expected_tasks=3, tag=0x12345678)
        self.assertEqual(dev.calls, [])
        dev = self.device()
        with self.assertRaisesRegex(ValueError, "Fresh complete readback path"):
            raw_test.run_case(dev, self.upload, self.expected, self.root / "missing" / "out",
                              command_address=0, initial_amount=9,
                              expected_tasks=3, tag=0x12345678)
        self.assertEqual(dev.calls, [])

    def test_command_and_descriptor_contract_rejects_invalid_fields_before_device_actions(self):
        for address, amount, tasks, tag in ((1, 9, 3, 7), (0x80000000, 9, 3, 7),
                                             (0x2000, 9, 3, 7), (0, 0, 3, 7),
                                             (0, 9, 4096, 7), (0, 9, 3, 0)):
            with self.subTest(values=(address, amount, tasks, tag)):
                dev = self.device()
                with self.assertRaises(ValueError):
                    raw_test.run_case(dev, self.upload, self.expected, self.output,
                                      command_address=address, initial_amount=amount,
                                      expected_tasks=tasks, tag=tag)
                self.assertEqual(dev.calls, [])

    def test_first_mismatch_preserves_actual_partial_file_and_never_acks_or_retries(self):
        first = self.addresses[0]
        dev = self.device(mismatch_at=first)
        with self.assertRaisesRegex(ValueError, "Complete raw BO differs"):
            self.run_valid(dev)
        self.assertEqual(self.output.read_text(), raw_line(first, bytes([self.expected_data[first][0] ^ 1]) + self.expected_data[first][1:]))
        self.assertEqual(len(calls_of(dev, "mem_read")), 1)
        self.assertFalse(calls_of(dev, "ack_success"))
        self.assertEqual(len(calls_of(dev, "submit")), 1)
        self.assertEqual(len(calls_of(dev, "wait_memory_ready")), 1)

    def test_read_timeout_preserves_partial_capture_and_never_acks(self):
        second = self.addresses[1]
        dev = self.device(fail_read_at=second)
        with self.assertRaisesRegex(TimeoutError, "fake read timeout"):
            self.run_valid(dev)
        self.assertEqual(self.output.read_text(), raw_line(self.addresses[0], self.expected_data[self.addresses[0]]))
        self.assertEqual([x[1] for x in calls_of(dev, "mem_read")], list(self.addresses[:2]))
        self.assertFalse(calls_of(dev, "ack_success"))

    def test_poll_fault_or_timeout_never_reads_or_acks_and_keeps_no_retry_path(self):
        for failure in (TimeoutError("poll timeout"), RuntimeError("late fault")):
            with self.subTest(failure=str(failure)):
                dev = self.device(result=failure)
                with self.assertRaises(type(failure)):
                    self.run_valid(dev)
                self.assertFalse(calls_of(dev, "mem_read"))
                self.assertFalse(calls_of(dev, "ack_success"))
                self.assertEqual(len(calls_of(dev, "submit")), 1)
                self.assertFalse(self.output.exists())

    def test_scratch_checks_six_addresses_in_forward_and_reverse_orders(self):
        dev = FakeRecordingDevice()
        result = raw_test.scratch(dev)
        addresses = (0x40, 0x1000, 0x1800, 0x200040, 0x1000040, 0x7FFFFFC0)
        writes = calls_of(dev, "mem_write")
        reads = calls_of(dev, "mem_read")
        self.assertEqual([x[1] for x in writes], list(addresses) + list(reversed(addresses)))
        self.assertEqual([x[1] for x in reads], list(addresses) * 2)
        self.assertEqual(len({x[2] for x in writes[:6]}), 6)
        self.assertEqual(len({x[2] for x in writes[6:]}), 6)
        self.assertNotEqual([x[2] for x in writes[:6]], [x[2] for x in writes[6:]])
        self.assertEqual(result["checked_bytes"], 2 * 6 * 64)
        self.assertFalse(result["full_capacity_qualified"])

    def test_scratch_detects_aliasing_fake_without_capacity_claim(self):
        class Aliasing(FakeRecordingDevice):
            def mem_write(self, address, data):
                super().mem_write(0, data)
            def mem_read(self, address, size):
                return super().mem_read(0, size)
        dev = Aliasing()
        with self.assertRaisesRegex(ValueError, "scratch mismatch"):
            raw_test.scratch(dev)


if __name__ == "__main__":
    unittest.main()
