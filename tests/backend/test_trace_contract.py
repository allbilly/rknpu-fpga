"""Synthetic wire controls over an unchanged captured ADD8 command/BO fixture.

These tests qualify the trace verifier only. No native RTL, compiler, network,
or FPGA is executed; the software reference is solely the test oracle.
"""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from model.dma import DMAEmulator
from model.sim import Memory
from tools.backend import qualification as q

ROOT = Path(__file__).resolve().parents[2]
MAGIC = 0x4F54504A


def receipt(data):
    return dict(base64=base64.b64encode(data).decode(),
                sha256=hashlib.sha256(data).hexdigest(), size=len(data))


def event(opcode, address, data=0, result=0, sequence=1):
    packet = data | address << 512 | 15 << 544 | opcode << 548 | sequence << 556 | MAGIC << 572
    response = result | sequence << 520 | MAGIC << 536
    return dict(frame=f'{packet:0160x}', rtl_response=f'{response:0160x}')


class TraceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='backend-trace-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.trace = Path(self.temporary.name)/'frames.jsonl'
        name = getattr(self, 'fixture_name', 'add_8')
        captured = next(c for c in json.loads((ROOT/'tests/backend_ew_captures.json').read_text())['cases']
                        if c['name'] == name)
        before = {}
        for region in captured['regions']:
            data = zlib.decompress(base64.b64decode(region['zlib_base64'], validate=True))
            self.assertEqual(len(data), region['size'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), region['sha256'])
            before[region['address']] = data
        tasks = [t['descriptor'] for t in captured['tasks']]
        address, amount = tasks[0]['regcmd_addr'], tasks[0]['regcfg_amount']
        commands = []
        for desc, task in zip(tasks, captured['tasks']):
            base = next(base for base, image in before.items()
                        if base <= desc['regcmd_addr'] and desc['regcmd_addr']+desc['regcfg_amount']*8 <= base+len(image))
            offset = desc['regcmd_addr']-base
            commands.append(before[base][offset:offset+desc['regcfg_amount']*8])
            self.assertEqual(hashlib.sha256(commands[-1]).hexdigest(), task['sha256'])
        task_fields = ('flags', 'op_idx', 'enable_mask', 'int_mask', 'int_clear',
                       'int_status', 'regcfg_amount', 'regcfg_offset', 'regcmd_addr')
        task_bytes = b''.join(struct.pack('<8IQ', *(d[k] for k in task_fields)) for d in tasks)
        self.assertTrue(any(image[:len(task_bytes)] == task_bytes for image in before.values()))
        reference = Memory()
        for base, image in before.items(): reference.map(base, image)
        emulator = DMAEmulator(reference); emulator.submit_dma(address, amount)
        after = {base: bytes(image) for base, image in reference.regions.items()}
        self.assertEqual(emulator.completed, len(tasks))
        self.output_base = captured['expected_address']
        self.after_line = int.from_bytes(after[self.output_base][:64], 'little')
        job = dict(status='PASS', address=address, amount=amount, tag=7, task_count=len(tasks),
                   before={str(a):receipt(v) for a,v in before.items()},
                   after={str(a):receipt(v) for a,v in after.items()}, tasks=tasks,
                   task_bytes=receipt(task_bytes), command_bytes=[receipt(cmd) for cmd in commands],
                   result=dict(tag=7, completed_tasks=len(tasks), error_code=0, status=0x714))
        operation = name.split('_')[0].upper()
        self.spec = dict(name=name, operation=operation, count=captured['logical_count'], repeat=1)
        self.worker = dict(status='PASS', native_returncode=0, numeric_cpu_fallback=False,
                           hardware_access=False, operation=operation, count=captured['logical_count'], repeat=1,
                           backend=dict(commit=q.PIN), expected_hex=captured['expected_logical_hex'],
                           outputs=[captured['expected_logical_hex']], submissions=[job], submission_count=1)
        self.events = []
        def append(opcode, target, data=0, result=0):
            current = event(opcode, target, data, result, len(self.events)//2+1)
            self.events.extend([current, dict(frame='0'*160, rtl_response=current['rtl_response'])])
        for base, image in before.items():
            for offset in range(0, len(image), 64):
                append(4, base+offset, int.from_bytes(image[offset:offset+64], 'little'))
        for target, value in ((0x10,address), (0x14,amount), (0x18,7), (0x0C,1)):
            append(2, target, value)
        self.after_submit = len(self.events)
        for target, value in ((8,0x714), (0x1C,7), (0x20,len(tasks)), (0x24,0)):
            append(1, target, result=value)
        self.first_read = len(self.events)
        for base, image in after.items():
            for offset in range(0, len(image), 64):
                append(3, base+offset, result=int.from_bytes(image[offset:offset+64], 'little'))
        self.before_ack = len(self.events)
        append(2, 0x0C, 2)

    def validate(self, events):
        worker = deepcopy(self.worker)
        worker['frame_commands'] = sum(int(e['frame'],16) != 0 for e in events)
        self.trace.write_text(''.join(json.dumps(e)+'\n' for e in events))
        return q.validate_execution(worker, self.trace, self.spec)

    def test_complete_capture_upload_readback_and_ack_passes(self):
        result = self.validate(self.events)
        self.assertEqual(result['submissions'], 1)
        self.assertEqual(result['tasks'], 1)
        self.assertEqual(result['whole_bo_bytes_checked'], 94208)

    def test_host_overwrite_after_submit_is_rejected_even_with_correct_bytes(self):
        events = list(self.events)
        events.insert(self.after_submit, event(4, self.output_base, self.after_line, sequence=65535))
        with self.assertRaisesRegex(ValueError, 'Host data write before pending job readback and ACK'):
            self.validate(events)

    def test_host_overwrite_after_readback_but_before_ack_is_rejected(self):
        events = list(self.events)
        events.insert(self.before_ack, event(4, self.output_base, self.after_line, sequence=65535))
        with self.assertRaisesRegex(ValueError, 'Host data write before pending job readback and ACK'):
            self.validate(events)

    def test_upload_after_ack_remains_legal(self):
        events = self.events + [event(4, self.output_base, self.after_line, sequence=65535)]
        self.assertEqual(self.validate(events)['submissions'], 1)

    def test_missing_complete_bo_readback_still_rejects_ack(self):
        events = self.events[:self.first_read] + self.events[self.first_read+2:]
        with self.assertRaisesRegex(ValueError, 'ACK before every actual BO byte was read'):
            self.validate(events)

    def test_every_task_requires_exactly_one_command_receipt(self):
        job = self.worker['submissions'][0]
        original = job['command_bytes']
        for commands in ([], original+original):
            job['command_bytes'] = commands
            with self.assertRaisesRegex(ValueError, 'per-task command receipt inventory'):
                self.validate(self.events)
        other = TraceContractTests();other.fixture_name = 'sub_9';other.setUp()
        try:
            self.assertEqual(other.validate(other.events)['tasks'], 2)
            other.worker['submissions'][0]['command_bytes'].pop()
            with self.assertRaisesRegex(ValueError, 'per-task command receipt inventory'):
                other.validate(other.events)
        finally:
            other.doCleanups()

    def test_task_receipt_must_equal_serialized_descriptor_fields(self):
        job = self.worker['submissions'][0]
        data = bytearray(q.raw(job['task_bytes']));data[0] ^= 1
        job['task_bytes'] = receipt(bytes(data))
        with self.assertRaisesRegex(ValueError, 'raw task bytes differ'):
            self.validate(self.events)

    def test_unsupported_descriptor_fields_fail_even_with_matching_bytes(self):
        job = self.worker['submissions'][0]
        job['tasks'][0]['flags'] = 1
        fields = ('flags', 'op_idx', 'enable_mask', 'int_mask', 'int_clear',
                  'int_status', 'regcfg_amount', 'regcfg_offset', 'regcmd_addr')
        job['task_bytes'] = receipt(struct.pack('<8IQ', *(job['tasks'][0][name] for name in fields)))
        with self.assertRaisesRegex(ValueError, 'unsupported raw task descriptor values'):
            self.validate(self.events)

    def test_task_receipt_also_requires_uploaded_task_bo_bytes(self):
        job = self.worker['submissions'][0]
        packed = q.raw(job['task_bytes'])
        base = next(int(base) for base, image in job['before'].items()
                    if len(q.raw(image)) >= 16384 and q.raw(image).startswith(packed))
        size = len(q.raw(job['before'].pop(str(base))))
        job['after'].pop(str(base))
        events = []
        skip_poll = False
        for e in self.events:
            packet = int(e['frame'], 16)
            if not packet:
                if not skip_poll:events.append(e)
                skip_poll = False
                continue
            opcode, address = packet >> 548 & 255, packet >> 512 & 0xffffffff
            skip_poll = opcode in (3, 4) and base <= address < base+size
            if not skip_poll:events.append(e)
        with self.assertRaisesRegex(ValueError, 'missing from uploaded task BO'):
            self.validate(events)


if __name__ == '__main__': unittest.main()
