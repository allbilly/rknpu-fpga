"""Exercise the independent scratch checker through saved native scan records."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('scratch_cases',
    Path(__file__).with_name('test_scratch_audit.py'))
cases = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cases)


def native_trace():
    events = [dict(event='TAP_RESET_NOT_FABRIC_RESET')]
    def scan(bits, ir, tdi, tdo):
        events.append(dict(index=len(events)-1, bits=bits, ir=ir,
                           tdi=hex(tdi), tdo=hex(tdo)))
    scan(6, True, 9, 0)
    scan(32, False, 0, 0x23751093)
    scan(6, True, 3, 0)
    retained = 0x4f54504a << 536
    scan(640, False, 0, retained)
    for seq, command in enumerate(cases.valid_wire(), 1):
        request = ((0x4f54504a << 572) | (seq << 556) |
                   (command['op'] << 548) | (15 << 544) |
                   (command['address'] << 512) | command['data'])
        scan(640, False, request, retained)
        retained = (0x4f54504a << 536) | (seq << 520) | command['response']
        scan(640, False, 0, retained)
    return events


class NativeScratchTests(unittest.TestCase):
    def run_audit(self, events):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            trace, out = base/'native-scans.jsonl', base/'result.json'
            trace.write_text(''.join(json.dumps(x)+'\n' for x in events))
            process = subprocess.run([sys.executable,
                str(Path(__file__).with_name('audit_scratch.py')),
                '--trace', str(trace), '--out', str(out)], capture_output=True, text=True)
            result = json.loads(out.read_text()) if out.exists() else None
            return process, result

    def test_complete_synthetic_native_trace(self):
        process, result = self.run_audit(native_trace())
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(result['status'], 'PASS_FIXED_DUAL_DDR_SCRATCH_WIRE_REPLAY_ONLY')
        self.assertEqual(result['wire']['idcodes'], 1)
        self.assertEqual(result['checked_bytes'], 768)

    def test_pending_last_command_rejects_without_receipt(self):
        process, result = self.run_audit(native_trace()[:-1])
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)

    def test_wrong_physical_target_rejects_without_receipt(self):
        events = native_trace(); events[2]['tdo'] = '0x12345678'
        process, result = self.run_audit(events)
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)

    def test_recorded_scan_failure_rejects_without_receipt(self):
        events = native_trace(); events[-1]['error'] = 'synthetic bridge error'
        process, result = self.run_audit(events)
        self.assertNotEqual(process.returncode, 0)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
