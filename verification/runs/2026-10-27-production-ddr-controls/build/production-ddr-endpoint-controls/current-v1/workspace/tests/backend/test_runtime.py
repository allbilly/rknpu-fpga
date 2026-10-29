"""Actual encoder with byte-only mock transport; no simulated arithmetic or DRM."""
from copy import deepcopy
import ctypes
import os
from pathlib import Path
import pickle
import socket
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from tools.backend import runtime as adapter


class ByteTransport:
    """Stores bytes and returns canned completion metadata, never computes EW."""
    def __init__(self):
        self.memory, self.calls = {}, []
        self.tasks = 1
        self.wrong_tag = False
        self.error = None
        self.closed = False
        self.tag = 0

    def reg_read(self, offset):
        return {0: 0x524B4557, 4: 0x10000, 8: 0x10}[offset]

    def mem_write(self, address, data):
        self.calls.append(('write', address, len(data)))
        self.memory[address] = bytes(data)

    def mem_read(self, address, size):
        self.calls.append(('read', address, size))
        return self.memory[address][:size]

    def submit(self, address, amount, tag):
        self.calls.append(('submit', address, amount, tag)); self.tag = tag
        if self.error:
            raise self.error

    def poll_result(self, timeout):
        self.calls.append(('poll', timeout))
        return SimpleNamespace(tag=self.tag ^ int(self.wrong_tag), completed_tasks=self.tasks, error_code=0, status=0x714)

    def ack_success(self): self.calls.append(('ack',))
    def close(self): self.closed = True


def selected_backend():
    return Path(os.environ.get('TINYGRAD_ROOT', os.environ.get('RKNPU_TINYGRAD', str(Path.home() / 'tinygrad'))))


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = selected_backend()
        if not cls.backend.exists():
            raise unittest.SkipTest('UNAVAILABLE: pinned tinygrad checkout is required')
        cls.rt, cls.rr, cls.td, cls.receipt = adapter._load_backend(cls.backend)
        print('Pinned runtime:', cls.receipt['commit'], 'byte-only mock transport; no numeric execution', flush=True)

    def setUp(self):
        network = patch.object(socket, 'create_connection', side_effect=AssertionError('No network in runtime unit controls'))
        network.start(); self.addCleanup(network.stop)
        drm = patch.object(self.rt.FileIOInterface, '__init__', side_effect=AssertionError('No DRM device allowed'))
        drm.start(); self.addCleanup(drm.stop)
        self.transport = ByteTransport()
        self.device_class = adapter.make_device_class(lambda: self.transport, self.backend)
        self.device = self.device_class('RKNPUFPGA')
        self.addCleanup(self.device.finalize)

    def arg(self, index, kind=None, addend=0):
        return self.rr.RKArg(self.rr.RKBufferKind.ARG if kind is None else kind, index, addend)

    def image(self, count=9, cfg=0x108202C0):
        return self.rr.RKImage((), (self.rr.RKEWOp(self.arg(0), self.arg(1), self.arg(2), count, cfg),))

    def program(self, image):
        obj = SimpleNamespace(name='mock_byte_contract', lib=zlib.compress(pickle.dumps(image, protocol=5)))
        return self.device.runtime(obj)

    def buffers(self, count=9):
        return [self.device._gpu_alloc(count * 2) for _ in range(3)]

    def test_original_final_writer_and_renderer_are_unchanged(self):
        self.assertIs(self.device.runtime_t._submit_bodies, self.rt.RockchipProgram._submit_bodies)
        self.assertIs(self.device.runtime_t._submit, self.rt.RockchipProgram._submit)
        self.assertIs(self.device.runtime_t._run_ew_ops, self.rt.RockchipProgram._run_ew_ops)
        self.assertEqual(self.device.renderers, [self.rr.RockchipRenderer])
        self.assertIs(type(self.device.renderer), self.rr.RockchipRenderer)
        self.assertEqual(self.device.renderer.target.device, 'ROCKCHIP')
        self.assertFalse(hasattr(self.device.allocator, '_as_buffer'))
        with self.assertRaises(adapter.UnsupportedProfile): self.device.reset_npu()

    def test_first_fit_page_padding_view_bounds_and_free(self):
        first = self.device._gpu_alloc(18)
        second = self.device._gpu_alloc(5000)
        third = self.device._gpu_alloc(2)
        self.assertEqual((first.size, first.meta.size, first.meta.dma_addr), (18, 4096, adapter.BASE))
        self.assertEqual((second.meta.size, third.meta.dma_addr), (8192, adapter.BASE + 12288))
        self.device._gpu_free(second)
        reused = self.device._gpu_alloc(4096)
        self.assertEqual(reused.meta.dma_addr, adapter.BASE + 4096)
        self.device.allocator._copyin(first, memoryview(b'\x55\xAA' * 9))
        self.assertEqual(self.transport.memory[adapter.BASE], b'\x55\xAA' * 9 + bytes(4096 - 18))
        for size, offset in ((0, 0), (19, 0), (2, -1), (2, 18)):
            with self.assertRaises(adapter.UnsupportedProfile): self.device.allocator._offset(first, size, offset)
        self.assertEqual(self.transport.calls, [('write', adapter.BASE, 4096)])

    def test_hardware_page_readback_precedes_ack_and_receipts_are_raw(self):
        buffers = self.buffers()
        self.device.allocator._copyin(buffers[1], memoryview(b'\x01\x02' * 9))
        self.device.allocator._copyin(buffers[2], memoryview(b'\x03\x04' * 9))
        self.program(self.image())(*buffers, timeout=None)
        record = self.device.records[-1]
        self.assertEqual(record['status'], 'PASS')
        self.assertEqual((record['amount'], record['task_count']), (35, 1))
        self.assertEqual(len(record['task_bytes']), 40)
        self.assertEqual(len(record['command_bytes'][0]), 35 * 8)
        self.assertEqual(record['tasks'][0]['regcmd_addr'], record['address'])
        self.assertEqual(record['tasks'][0]['enable_mask'], 0x18)
        self.assertEqual(record['before'], record['after'])  # mock performs NO arithmetic
        self.assertEqual(self.transport.calls[-1], ('ack',))
        start = max(i for i, call in enumerate(self.transport.calls) if call[0] == 'submit')
        reads = {call[1] for call in self.transport.calls[start:] if call[0] == 'read'}
        self.assertEqual(reads, set(record['after']))
        self.assertTrue(all(len(data) % 4096 == 0 for data in record['before'].values()))

    def test_literal_prelude_uses_real_runtime_without_layout_operations(self):
        scratch = self.rr.RKBufferKind.SCRATCH
        literal = self.rr.RKGather(None, self.arg(0, scratch), 9, values=(0xBC00,))
        op = self.rr.RKEWOp(self.arg(0), self.arg(1), self.arg(0, scratch), 9, 0x108003C4)
        self.program(self.rr.RKImage((64,), (literal, op)))(*self.buffers())
        arena = self.device._buffers['scratch']
        self.assertEqual(self.device.records[-1]['before'][arena.meta.dma_addr], b'\x00\xBC' * 9 + bytes(4096 - 18))

    def test_entire_image_is_rejected_before_scratch_or_transport_effects(self):
        scratch = self.rr.RKBufferKind.SCRATCH
        good = self.image().program[0]
        literal = self.rr.RKGather(None, self.arg(0, scratch), 9, values=(0xBC00,))
        bad = [good._replace(mode=self.rr.RKEWMode.INT16), good._replace(ew_cfg=0x108002C0),
               self.rr.RKCMAC(self.arg(0), self.arg(1), self.arg(2), 1, 8, 8),
               literal._replace(src=self.arg(1)), literal._replace(index=self.arg(1)),
               literal._replace(dst=self.arg(0)), literal._replace(axes=((1, 9, 1),)),
               literal._replace(offsets=tuple(range(9))), literal._replace(base=1),
               literal._replace(partial=True), literal._replace(dst_stride=8),
               literal._replace(itemsize=4), literal._replace(index_itemsize=2),
               literal._replace(fill_bits=1), literal._replace(values=[0xBC00]),
               literal._replace(values=(0xBC00, 0xBC00)), literal._replace(values=(-1,)),
               good._replace(count=0), good._replace(lhs=self.arg(-1)), good._replace(rhs=self.arg(0, scratch, 2))]
        for item in bad:
            with self.subTest(item=item):
                image = self.rr.RKImage((64,), (literal, good, item)) if type(item) is not self.rr.RKGather else self.rr.RKImage((64,), (item, good))
                before = (len(self.device._owned), len(self.transport.calls))
                with self.assertRaises(adapter.UnsupportedProfile): self.program(image)
                self.assertEqual((len(self.device._owned), len(self.transport.calls)), before)
        with self.assertRaises(adapter.UnsupportedProfile): self.program(self.rr.RKImage((64,), (good, literal)))

    def test_call_options_and_binding_errors_fail_before_side_effects(self):
        program = self.program(self.image())
        buffers = self.buffers()
        for kwargs in ({'vals': (1,)}, {'global_size': (2, 1, 1)}, {'local_size': (1, 2, 1)},
                       {'local_size': (True, 1, 1)}, {'timeout': 1}, {'unknown': None}, {'wait': 1}):
            before = len(self.transport.calls)
            with self.subTest(kwargs=kwargs), self.assertRaises(adapter.UnsupportedProfile): program(*buffers, **kwargs)
            self.assertEqual(len(self.transport.calls), before)
        with self.assertRaises(adapter.UnsupportedProfile): program(*buffers[:2])
        short_view = self.device.allocator._offset(self.device._gpu_alloc(64), 18, 16)
        with self.assertRaises(adapter.UnsupportedProfile): program(short_view, buffers[1], buffers[2])
        overlapping = self.device._gpu_alloc(64)
        partial = self.program(self.image(count=16))
        with self.assertRaises(adapter.UnsupportedProfile): partial(overlapping.offset(16, 32), overlapping.offset(0, 32), self.device._gpu_alloc(32))
        self.assertEqual(len(self.transport.calls), 0)

    def test_private_scratch_padding_and_default_no_grid_metadata(self):
        kind = self.rr.RKBufferKind.SCRATCH
        literal = self.rr.RKGather(None, self.arg(0, kind), 33, values=(0xBC00,))
        op = self.rr.RKEWOp(self.arg(0), self.arg(1), self.arg(0, kind), 33, 0x108003C4)
        self.program(self.rr.RKImage((68,), (literal, op)))(*self.buffers(33), global_size=None, local_size=None, timeout=None)
        self.assertEqual(self.device.records[-1]['status'], 'PASS')
        bad = op._replace(rhs=self.arg(0, kind, 4080), count=9)
        with self.assertRaises(adapter.UnsupportedProfile): self.program(self.rr.RKImage((4096,), (bad,)))

    def test_program_and_owned_view_tampering_are_rejected(self):
        program = self.program(self.image()); buffers = self.buffers()
        program.image = program.image._replace(scratch=(8192,))
        with self.assertRaisesRegex(adapter.UnsupportedProfile, 'program state'): program(*buffers)
        program.image = program._admitted_image
        original = buffers[0].view
        buffers[0].view = buffers[1].view
        with self.assertRaisesRegex(adapter.UnsupportedProfile, 'CPU view'): program(*buffers)
        buffers[0].view = original
        self.assertFalse(self.transport.calls)

    def test_remote_failure_or_wrong_completion_poison_without_retry_or_ack(self):
        program = self.program(self.image()); buffers = self.buffers()
        self.transport.error = OSError('mock remote error')
        with self.assertRaises(OSError): program(*buffers)
        count = len(self.transport.calls)
        self.assertEqual(sum(call[0] == 'submit' for call in self.transport.calls), 1)
        self.assertFalse(any(call[0] == 'ack' for call in self.transport.calls))
        with self.assertRaises(RuntimeError): program(*buffers)
        self.assertEqual(len(self.transport.calls), count)

    def test_task_count_mismatch_rejects_before_ack(self):
        self.transport.tasks = 2
        with self.assertRaisesRegex(adapter.UnsupportedProfile, 'task count'):
            self.program(self.image())(*self.buffers())
        self.assertFalse(any(call[0] == 'ack' for call in self.transport.calls))
        self.assertTrue(self.device._poisoned)

    def test_allocator_capacity_rollback_and_repeat_preserve_data_bos(self):
        buffers = self.buffers(); program = self.program(self.image())
        first_addresses = [buf.meta.dma_addr for buf in buffers]
        for _ in range(4): program(*buffers)
        self.assertEqual([buf.meta.dma_addr for buf in buffers], first_addresses)
        self.assertEqual(len(self.device._owned), 5)
        self.assertEqual(len(self.device.records), 4)
        self.assertEqual([r['tag'] for r in self.device.records], [1, 2, 3, 4])
        current = set(self.device._owned)
        with self.assertRaises(MemoryError): self.device._replace_submit_buffers(adapter.CAPACITY - 131072, 131072)
        self.assertEqual(set(self.device._owned), current)
        with self.assertRaises(adapter.UnsupportedProfile): self.device._gpu_alloc(4096, 1)

    def test_submit_payload_and_descriptor_fields_fail_before_launch(self):
        buffers = self.buffers(); program = self.program(self.image()); program(*buffers)
        raw_record = self.device.records[-1]
        rk = self.rt.rk
        base = dict(raw_record['payload']); subcores = base.pop('subcore_task')
        def payload():
            return rk.struct_rknpu_submit(**base, subcore_task=(rk.struct_rknpu_subcore_task * 5)(
                *(rk.struct_rknpu_subcore_task(**fields) for fields in subcores)))
        request = 0xC0686441
        before = len(self.transport.calls)
        for name in ('flags', 'timeout', 'task_start', 'task_counter', 'priority', 'regcfg_obj_addr',
                     'task_base_addr', 'user_data', 'core_mask', 'fence_fd', 'task_obj_addr'):
            value = payload(); setattr(value, name, getattr(value, name) + 1)
            with self.subTest(field=name), self.assertRaises(adapter.UnsupportedProfile): self.device.ioctl(request, value)
        value = payload(); value.subcore_task[4].task_number = 1
        with self.assertRaises(adapter.UnsupportedProfile): self.device.ioctl(request, value)
        task = self.device._buffers['task']; descriptor = rk.struct_rknpu_task.from_address(task.va_addr)
        original = bytes(descriptor)
        for name in ('flags', 'op_idx', 'enable_mask', 'int_mask', 'int_clear', 'int_status', 'regcfg_amount', 'regcfg_offset', 'regcmd_addr'):
            try:
                setattr(descriptor, name, getattr(descriptor, name) + 1)
                with self.subTest(field=name), self.assertRaises(adapter.UnsupportedProfile): self.device.ioctl(request, payload())
            finally: ctypes.memmove(task.va_addr, original, len(original))
        self.assertEqual(len(self.transport.calls), before)

    def test_source_pin_checks_and_single_owner_are_enforced(self):
        self.assertEqual(self.device.backend_receipt['commit'], adapter.PIN)
        self.assertIn('tinygrad/runtime/ops_rockchip.py', self.device.backend_receipt['imported_files'])
        another = adapter.make_device_class(ByteTransport, self.backend)
        with self.assertRaisesRegex(adapter.UnsupportedProfile, 'owner'): another('RKNPUFPGA')
        with patch.dict(adapter.PINNED_FILES, {'tinygrad/device.py': '0' * 64}):
            with self.assertRaisesRegex(adapter.UnsupportedProfile, 'Pinned'): adapter.verify_backend(self.backend)
        with patch.dict(sys.modules, {'tinygrad.foreign_control': SimpleNamespace(__file__='/tmp/foreign-tinygrad-control.py')}):
            with self.assertRaisesRegex(adapter.UnsupportedProfile, 'Foreign tinygrad'): adapter.verify_backend(self.backend)
        def dirty_git(argv, **kwargs):
            return adapter.PIN if argv[-2:] == ['rev-parse', 'HEAD'] else ' M tinygrad/device.py\n'
        with patch.object(adapter.subprocess, 'check_output', side_effect=dirty_git):
            with self.assertRaisesRegex(adapter.UnsupportedProfile, 'must be clean'): another('RKNPUFPGA')

    def test_restricted_compiler_image_rejects_unrelated_globals(self):
        with self.assertRaises(adapter.UnsupportedProfile):
            self.device.runtime(SimpleNamespace(name='bad', lib=zlib.compress(pickle.dumps(Path('/tmp/not-an-image')))))
        self.assertFalse(self.transport.calls)

    def test_registration_is_process_scoped_and_preserves_other_device_entries(self):
        # A fresh child avoids clearing tinygrad's global cache for unrelated devices.
        code = r'''
from tools.backend.runtime import install, UnsupportedProfile, MODULE
from tinygrad.device import Device
from types import ModuleType
import sys
class T:
 def reg_read(self,n): return {0:0x524b4557,4:0x10000,8:0x10}[n]
 def close(self): pass
before=Device.get_class
sys.modules[MODULE]=ModuleType(MODULE)
try: install(T,sys.argv[1])
except UnsupportedProfile: pass
else: raise AssertionError('foreign module binding accepted')
del sys.modules[MODULE]
handle=install(T,sys.argv[1]); device=Device['RKNPUFPGA']
assert Device.get_class is before or Device.get_class.__func__ is before.__func__
try: install(T,sys.argv[1])
except UnsupportedProfile: pass
else: raise AssertionError('duplicate registration accepted')
handle.close()
assert MODULE not in sys.modules and 'RKNPUFPGA' not in Device._opened_devices
assert device._closed
print('PASS registry ownership and cleanup; no cache clearing')
'''
        env = dict(os.environ, PYTHONPATH=str(self.backend), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-c', code, str(self.backend)], env=env, cwd=Path(__file__).resolve().parents[2],
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS registry ownership', result.stdout)


if __name__ == '__main__': unittest.main()
