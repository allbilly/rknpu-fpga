"""A narrow tinygrad device using its unchanged Rockchip final command writer.

Install explicitly in a fresh process with an injected, already audited transport
factory. No DRM object, network connection or software numerical fallback is
created here. Only HALF EW plans and immutable literal scratch initializers are
admitted. Compiled images are trusted local compiler output, not a file-loading
API; restricted deserialization additionally rejects unrelated pickle globals.

The runtime owns page-rounded, zero-initialized ctypes BO shadows in the fixed
1 MiB aperture, backed by BRAM or an explicitly selected DDR EW namespace.
All synchronization is byte copying. Completion reads every
owned BO back before ACK. A failed transaction poisons the device permanently;
close does not reset hardware. Registration is process-scoped and single-use,
because tinygrad caches device classes and instances globally.
"""
from __future__ import annotations

import array
import ctypes
from dataclasses import dataclass
import hashlib
import importlib
import io
import os
from pathlib import Path
import pickle
import pickletools
import struct
import subprocess
import sys
import threading
from types import ModuleType, SimpleNamespace
import zlib

PIN = '078eee94d8f1912bb63ce786c250d2c24984844a'
BASE, CAPACITY, PAGE = 0x10000000, 1048576, 4096
MODULE = 'tinygrad.runtime.ops_rknpufpga'
NAME = 'RKNPUFPGA'
EW_CONFIGS = frozenset((0x108202C0, 0x108402C0, 0x108003C4))
EW_ENDPOINTS = {'ew_bram': (0x524B4557, 'RKEW'), 'ew_ddr': (0x524B4144, 'RKAD')}
PINNED_FILES = {
    'tinygrad/runtime/ops_rockchip.py': '73cddbdebaf52c33a9d3cef33bbc016b78357da35a588403c23e35069e223daa',
    'tinygrad/renderer/rockchip.py': 'c84b70e73449a721319981334b746f79aadd095bd39cc2f576c84bd397fbcc1d',
    'tinygrad/runtime/autogen/rockchip.py': '6d6c11176fd78201fa013b5b4485d9a1a67158ba749eca0d892a12e22c8f1f56',
    'tinygrad/device.py': '614fcb30f274dc78d03c2a32ab2a11a9cb579cd663ec3b2f010a707b3a58cb9d',
    'tinygrad/runtime/support/hcq.py': 'e5d045156acb1f207e4568b2610c0e731d709454f2ef203f6cf90d2995b15184',
    'tinygrad/helpers.py': 'ef89394f072e053dee45585dfdc606a2f9e4aafed61ddbe18bd72118a858e7e9',
    'tinygrad/dtype.py': 'e0f604bc1a4dee838f83fd1703aae17e3a5a7c8ca495acc6e97259a32a4faaea',
    'tinygrad/engine/realize.py': '4a1572fe9e8e55b0d4b51400498e25a45403362fb3b0c6b1df6fe9928f69c613',
    'tinygrad/codegen/__init__.py': '182eb030bf673c2b5d342a005e0f9bbe5fa0f0dd0e802194e316e8cfba289e75',
    'tinygrad/codegen/opt/heuristic.py': '7eb9e32cc7346502a8747ce9b9d7bd709e797694ba02ba2034b92d1eb6904a28',
    'tinygrad/codegen/opt/postrange.py': '8dc2169f12e9b34508f6d32dd8f086e3adf73bb3757159b394d28822ba82a443',
    'tinygrad/renderer/__init__.py': '17f51edb6ae81e4c1eee1a30872e9790c92cd8713a1429fb6c66393b084a7a4c',
    'tinygrad/__init__.py': 'fc24d5d0df1b1a14bbee0bd2641a61ca5f34ec7d83f1b0b755adf6eb83d5c0be',
}
_OWNER_LOCK = threading.RLock()
_ACTIVE_DEVICE = None
_REGISTRATION_USED = False


class UnsupportedProfile(ValueError):
    """The request is outside the explicitly implemented raw FPGA profile."""


def require(condition, message):
    if not condition:
        raise UnsupportedProfile(message)


def integer(value, low, high, label):
    require(type(value) is int and low <= value <= high, f'Unsupported {label}')
    return value


def rounded(size):
    return (size + PAGE - 1) // PAGE * PAGE


def verify_backend(backend_path=None):
    root = (Path(backend_path) if backend_path is not None else Path.home() / 'tinygrad').resolve()
    require(sys.byteorder == 'little' and array.array('Q').itemsize == 8 and array.array('H').itemsize == 2,
            'The unchanged encoder requires native little-endian QWORD/halfword storage')
    def git(*args):
        return subprocess.check_output(['git', '--no-optional-locks', '-C', str(root), *args], text=True).strip()
    require(git('rev-parse', 'HEAD') == PIN, 'Unreviewed tinygrad revision')
    require(not git('status', '--porcelain', '--untracked-files=all'), 'tinygrad checkout must be clean')
    for name, expected in PINNED_FILES.items():
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, 'Pinned backend file changed: ' + name)
    tree = {}
    for entry in git('ls-tree', '-r', '-z', PIN, '--', 'tinygrad').split('\0'):
        if entry:
            metadata, name = entry.split('\t', 1)
            tree[name] = metadata.split()[2]
    imported = {}
    for name, module in tuple(sys.modules.items()):
        if name != 'tinygrad' and not name.startswith('tinygrad.'):
            continue
        if name == MODULE:
            continue
        filename = getattr(module, '__file__', None)
        require(filename is not None, 'Unverifiable imported tinygrad module: ' + name)
        path = Path(filename).resolve()
        require(path.is_relative_to(root / 'tinygrad'), 'Foreign tinygrad module already imported: ' + name)
        relative = str(path.relative_to(root))
        raw = path.read_bytes()
        require(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == tree.get(relative),
                'Imported module differs from pinned Git object: ' + name)
        imported[relative] = hashlib.sha256(raw).hexdigest()
    return {'root': str(root), 'commit': PIN, 'clean': True,
            'pinned_files': dict(PINNED_FILES), 'imported_files': dict(sorted(imported.items()))}


def _load_backend(path):
    receipt = verify_backend(path)
    # Read-only foreign checkout: never create foreign __pycache__ files.
    sys.dont_write_bytecode = True
    if receipt['root'] not in sys.path:
        sys.path.insert(0, receipt['root'])
    runtime = importlib.import_module('tinygrad.runtime.ops_rockchip')
    renderer = importlib.import_module('tinygrad.renderer.rockchip')
    device = importlib.import_module('tinygrad.device')
    receipt = verify_backend(receipt['root'])
    return runtime, renderer, device, receipt


def _image(lib, renderer):
    require(type(lib) is bytes, 'Compiler image must be immutable bytes')
    raw = zlib.decompress(lib)
    require(len(raw) <= 16 * CAPACITY, 'Compiler image exceeds the bounded profile')
    require(not any(op.name in ('BUILD', 'PERSID', 'BINPERSID', 'EXT1', 'EXT2', 'EXT4', 'INST', 'OBJ')
                    for op, _, _ in pickletools.genops(raw)), 'Unsupported compiler pickle operation')
    allowed = {name: getattr(renderer, name) for name in
               ('RKImage', 'RKArg', 'RKGather', 'RKEWOp', 'RKCMAC', 'RKBufferKind', 'RKEWMode')}
    class ImageReader(pickle.Unpickler):
        def find_class(self, module, name):
            require(module == 'tinygrad.renderer.rockchip' and name in allowed, 'Unrelated compiler pickle global')
            return allowed[name]
    stream = io.BytesIO(raw)
    result = ImageReader(stream).load()
    require(not stream.read(), 'Trailing compiler pickle data')
    return result


def validate_image(image, renderer):
    require(type(image) is renderer.RKImage and type(image.scratch) is tuple and type(image.program) is tuple,
            'Expected immutable RKImage')
    require(image.program, 'Empty RKImage is unsupported')
    for size in image.scratch:
        integer(size, 1, CAPACITY, 'scratch size')
    require(sum(rounded(size) for size in image.scratch) <= CAPACITY, 'Scratch exceeds BRAM aperture')
    def argument(arg, alignment):
        require(type(arg) is renderer.RKArg and type(arg.kind) is renderer.RKBufferKind,
                'Invalid RKImage buffer reference')
        integer(arg.index, 0, CAPACITY // 2, 'buffer index')
        integer(arg.addend, 0, CAPACITY, 'buffer addend')
        require(arg.addend % alignment == 0, 'Unsupported buffer alignment')
        if arg.kind is renderer.RKBufferKind.SCRATCH:
            require(arg.index < len(image.scratch), 'Undeclared scratch slot')
    seen_ew = False
    for op in image.program:
        if type(op) is renderer.RKGather:
            require(not seen_ew and op.src is None and op.index is None,
                    'Runtime CPU gathers or post-EW layout operations are unsupported')
            argument(op.dst, 2)
            require(op.dst.kind is renderer.RKBufferKind.SCRATCH and op.base == 0 and type(op.base) is int and
                    type(op.axes) is tuple and not op.axes and type(op.offsets) is tuple and not op.offsets and
                    op.fill_bits == 0 and type(op.fill_bits) is int and op.partial is False and
                    type(op.dst_stride) is int and op.dst_stride == 1 and type(op.itemsize) is int and op.itemsize == 2 and
                    type(op.index_itemsize) is int and op.index_itemsize == 4,
                    'Only literal contiguous scratch initialization is supported')
            integer(op.count, 1, CAPACITY // 2, 'literal count')
            require(type(op.values) is tuple and len(op.values) in (1, op.count), 'Literal values must be immutable and complete')
            for value in op.values:
                integer(value, 0, 65535, 'literal halfword bits')
            require(op.dst.addend + op.count * 2 <= image.scratch[op.dst.index], 'Literal initialization exceeds scratch')
        elif type(op) is renderer.RKEWOp:
            seen_ew = True
            require(type(op.mode) is renderer.RKEWMode and op.mode is renderer.RKEWMode.HALF,
                    'Only HALF EW plans are supported')
            require(type(op.ew_cfg) is int and op.ew_cfg in EW_CONFIGS and type(op.submit_barrier) is bool,
                    'Only reviewed ADD/SUB/MUL EW configurations are supported')
            integer(op.count, 1, CAPACITY // 2, 'EW count')
            for arg in (op.dst, op.lhs, op.rhs):
                argument(arg, 16)
                if arg.kind is renderer.RKBufferKind.SCRATCH:
                    require(arg.addend + op.count * 2 <= image.scratch[arg.index] and
                            arg.addend + ((op.count + 7) // 8 * 16) <= rounded(image.scratch[arg.index]),
                            'EW exceeds scratch slot or its owned padding')
        else:
            raise UnsupportedProfile('CMAC and other RKImage operation classes are unsupported')
    require(seen_ew, 'Literal-only CPU execution is unsupported')


@dataclass
class _Allocation:
    storage: object
    buffer: object
    address: int
    physical_size: int
    logical_size: int
    flags: int
    initialized: bool = False


def make_device_class(transport_factory, backend_path=None, *, transport_profile='ew_bram'):
    """Create an unregistered class for one device owner; transport is mandatory."""
    require(callable(transport_factory), 'An explicit transport_factory is required')
    require(type(transport_profile) is str and transport_profile in EW_ENDPOINTS,
            'Unsupported EW transport profile')
    endpoint_id, endpoint_name = EW_ENDPOINTS[transport_profile]
    rt, rr, td, receipt = _load_backend(backend_path)
    rk = rt.rk
    created = False

    class AuditedProgram(rt.RockchipProgram):
        def __init__(self, dev, obj):
            dev._check_healthy()
            dev.backend_receipt = verify_backend(receipt['root'])
            image = _image(obj.lib, rr)
            validate_image(image, rr)
            super().__init__(dev, obj)
            require(self.image == image, 'Compiler image changed during admission')
            self._admitted_image = image
            self._admitted_offsets = self._scratch_offsets
            self._admitted_modes = frozenset(self._ew_modes)

        def __call__(self, *bufs, global_size=(1, 1, 1), local_size=(1, 1, 1), vals=(), wait=False, **kwargs):
            def default_grid(value):
                return value is None or type(value) is tuple and value == (1, 1, 1) and all(type(x) is int for x in value)
            require(default_grid(global_size) and default_grid(local_size),
                    'Nondefault execution dimensions are unsupported')
            require(type(vals) is tuple and not vals and type(wait) is bool and
                    set(kwargs) <= {'timeout'} and kwargs.get('timeout') is None,
                    'Runtime scalar values or extra execution options are unsupported')
            with self.dev._lock:
                self.dev._check_healthy()
                self.dev.backend_receipt = verify_backend(receipt['root'])
                require(self.image == self._admitted_image and self._scratch_offsets == self._admitted_offsets and
                        frozenset(self._ew_modes) == self._admitted_modes, 'Admitted program state changed')
                validate_image(self.image, rr)
                self.dev._validate_bindings(self.image, bufs)
                self.dev._submit_timeout()
                try:
                    return super().__call__(*bufs, global_size=global_size, local_size=local_size, vals=vals, wait=wait)
                except BaseException:
                    self.dev._poisoned = True
                    raise

    class ByteAllocator(td.LRUAllocator):
        # No _as_buffer: tinygrad's generic COPY must call _copyin and upload.
        def _alloc(self, size, options):
            require(type(options) is td.BufferSpec and not options.uncached and not options.cpu_access and
                    not options.host and options.external_ptr is None and type(options.nolru) is bool,
                    'Unsupported allocator options')
            return self.dev._gpu_alloc(size)

        def _free(self, buf, options):
            self.dev._gpu_free(buf)

        def _offset(self, buf, size, offset):
            self.dev._allocation(buf)
            integer(size, 1, buf.size, 'buffer view size')
            integer(offset, 0, buf.size - size, 'buffer view offset')
            return buf.offset(offset, size)

        def _copyin(self, dest, src):
            with self.dev._lock:
                self.dev._check_healthy(); self.dev._allocation(dest)
                require(isinstance(src, memoryview) and src.c_contiguous and src.nbytes <= dest.size, 'Invalid raw input copy')
                ctypes.memmove(int(dest.va_addr), src.cast('B').tobytes(), src.nbytes)
                self.dev._sync_buffers((dest,), rk.RKNPU_MEM_SYNC_TO_DEVICE)

        def _copyout(self, dest, src):
            with self.dev._lock:
                self.dev._check_healthy(); self.dev._allocation(src)
                require(isinstance(dest, memoryview) and dest.c_contiguous and not dest.readonly and dest.nbytes <= src.size,
                        'Invalid raw output copy')
                self.dev._sync_buffers((src,), rk.RKNPU_MEM_SYNC_FROM_DEVICE)
                ctypes.memmove(rt.from_mv(dest.cast('B')), int(src.va_addr), dest.nbytes)

    class RKNPUFPGADevice(rt.RockchipDevice):
        def __init__(self, device=NAME):
            nonlocal created
            global _ACTIVE_DEVICE
            require(device == NAME, 'Only one unindexed RKNPUFPGA device is supported')
            current = verify_backend(receipt['root'])
            with _OWNER_LOCK:
                require(not created and _ACTIVE_DEVICE is None, 'An FPGA runtime owner already exists')
                created = True; _ACTIVE_DEVICE = self
            self._lock = threading.RLock()
            self._buffers, self._owned = {}, {}
            self._poisoned, self._closed = False, False
            self._native_int16, self._npu_clean = False, True
            self.submit_count = self.task_count = self.timeout_retries = 0
            self.records, self.backend_receipt = [], current
            self._fpga_renderer = None
            self._tag = 0
            self.transport_profile = transport_profile
            self.transport = None
            self.fd_ctl = self
            try:
                self.transport = transport_factory()
                require(self.transport is not None and self.transport.reg_read(0) == endpoint_id and
                        self.transport.reg_read(4) == 0x10000 and self.transport.reg_read(8) == 0x10,
                        f'Transport must expose an idle, memory-ready {endpoint_name} ABI 1.0 endpoint')
                td.Compiled.__init__(self, device, ByteAllocator(self, supports_copy_from_disk=False, supports_transfer=False),
                                     [rr.RockchipRenderer], AuditedProgram)
            except BaseException:
                self.finalize()
                raise

        def _check_healthy(self):
            if self._poisoned or self._closed:
                raise RuntimeError('RKNPUFPGA is closed or poisoned; joint hardware recovery is required')

        def _select_renderer(self):
            self._check_healthy()
            from tinygrad.helpers import DEV, Target
            target = DEV.target(NAME)
            require(not target.renderer and not target.arch and not target.interface and not target.indices,
                    'Custom RKNPUFPGA compilation targets are unsupported')
            if self._fpga_renderer is None:
                # Production heuristics and postrange lowering select this
                # backend by target.device; execution still uses RKNPUFPGA.
                self._fpga_renderer = rr.RockchipRenderer(Target(device='ROCKCHIP'))
            return self._fpga_renderer

        def _allocation(self, buf):
            require(type(buf) is rt.HCQBuffer and id(buf.base) in self._owned, 'Foreign or freed HCQ buffer')
            item = self._owned[id(buf.base)]
            base = item.buffer
            require(buf.base is base and buf.meta is base.meta and base.va_addr == ctypes.addressof(item.storage) and
                    base.size == item.logical_size and base.meta.obj_addr == base.va_addr and
                    base.meta.dma_addr == item.address and base.meta.size == item.physical_size and base.meta.flags == item.flags,
                    'Changed BO ownership metadata')
            require(type(buf.va_addr) is int and type(buf.size) is int and buf.size > 0 and
                    base.va_addr <= buf.va_addr and buf.va_addr + buf.size <= base.va_addr + item.logical_size,
                    'HCQ view escapes its owned logical BO')
            require(type(buf.view) is rt.MMIOInterface and buf.view.addr == buf.va_addr and
                    buf.view.nbytes == buf.size and buf.view.fmt == 'B' and buf.view.mv.c_contiguous and
                    not buf.view.mv.readonly and buf.view.mv.nbytes == buf.size and
                    ctypes.addressof(rt.from_mv(buf.view.mv)) == buf.va_addr, 'Changed BO CPU view')
            return item

        def _gpu_alloc(self, size, flags=0):
            with self._lock:
                self._check_healthy()
                integer(size, 1, CAPACITY, 'BO size')
                require(type(flags) is int and flags in (0, rk.RKNPU_MEM_KERNEL_MAPPING), 'Unsupported BO allocation flags')
                physical = rounded(size); address = BASE
                for old in sorted(self._owned.values(), key=lambda x: x.address):
                    if address + physical <= old.address:
                        break
                    address = old.address + old.physical_size
                if address + physical > BASE + CAPACITY:
                    raise MemoryError('RKNPUFPGA 1 MiB BRAM aperture exhausted')
                storage = ctypes.create_string_buffer(physical)
                pointer = ctypes.addressof(storage)
                meta = SimpleNamespace(dma_addr=address, obj_addr=pointer, size=physical, flags=flags, sram_size=0)
                buf = rt.HCQBuffer(pointer, size, meta=meta, view=rt.MMIOInterface(pointer, size))
                self._owned[id(buf)] = _Allocation(storage, buf, address, physical, size, flags)
                return buf

        def _gpu_free(self, buf):
            with self._lock:
                if self._closed:
                    return
                item = self._allocation(buf)
                require(buf is item.buffer, 'Cannot free a buffer view')
                del self._owned[id(buf)]

        def _replace_submit_buffers(self, cmd_size, task_size):
            existing = set(self._owned)
            try:
                return super()._replace_submit_buffers(cmd_size, task_size)
            except BaseException:
                for key in set(self._owned) - existing:
                    del self._owned[key]
                raise

        def _upload(self, item):
            self._allocation(item.buffer)
            self.transport.mem_write(item.address, ctypes.string_at(ctypes.addressof(item.storage), item.physical_size))
            item.initialized = True

        def _download(self, item):
            self._allocation(item.buffer)
            raw = self.transport.mem_read(item.address, item.physical_size)
            require(type(raw) is bytes and len(raw) == item.physical_size, 'Incomplete raw BO readback')
            ctypes.memmove(ctypes.addressof(item.storage), raw, item.physical_size)

        def _sync_buffers(self, bufs, flags):
            with self._lock:
                self._check_healthy()
                require(type(flags) is int and flags in (rk.RKNPU_MEM_SYNC_TO_DEVICE, rk.RKNPU_MEM_SYNC_FROM_DEVICE),
                        'Unsupported BO synchronization flags')
                items = {id(buf.base): self._allocation(buf) for buf in bufs}
                try:
                    for item in items.values():
                        if flags == rk.RKNPU_MEM_SYNC_TO_DEVICE or not item.initialized:
                            self._upload(item)
                        if flags == rk.RKNPU_MEM_SYNC_FROM_DEVICE:
                            self._download(item)
                except BaseException:
                    self._poisoned = True
                    raise

        def _validate_bindings(self, image, bufs):
            for buf in bufs:
                self._allocation(buf)
                require(all(buf.base is not internal.base for internal in self._buffers.values()), 'Internal BO passed as an argument')
            def span(arg, logical_size, size):
                if arg.kind is rr.RKBufferKind.SCRATCH:
                    require(arg.addend + logical_size <= image.scratch[arg.index] and
                            arg.addend + size <= rounded(image.scratch[arg.index]), 'Scratch extent exceeded')
                    return ('scratch', arg.index), arg.addend
                require(arg.index < len(bufs), 'Unbound RKImage argument')
                buf = bufs[arg.index]; item = self._allocation(buf)
                require(arg.addend + logical_size <= buf.size, 'EW logical extent exceeds argument')
                offset = buf.va_addr - item.buffer.va_addr + arg.addend
                limit = item.physical_size if buf is item.buffer else buf.va_addr - item.buffer.va_addr + buf.size
                require(offset + size <= limit and (item.address + offset) % 16 == 0, 'Unsupported argument extent/alignment or view padding')
                return ('argument', id(item.buffer)), offset
            for op in image.program:
                if type(op) is not rr.RKEWOp:
                    continue
                size = (op.count + 7) // 8 * 16
                dst = span(op.dst, op.count * 2, size)
                for arg in (op.lhs, op.rhs):
                    source = span(arg, op.count * 2, size)
                    require(dst[0] != source[0] or dst[1] == source[1] or
                            dst[1] + size <= source[1] or source[1] + size <= dst[1],
                            'Partial EW output/input overlap is unsupported')

        def _submit_timeout(self):
            try:
                milliseconds = int(os.environ.get('ROCKCHIP_SUBMIT_TIMEOUT_MS', '6000'))
            except ValueError as error:
                raise UnsupportedProfile('Invalid submission timeout') from error
            return integer(milliseconds, 1, 0xFFFFFFFF, 'submission timeout')

        def _regions(self):
            return {item.address: ctypes.string_at(ctypes.addressof(item.storage), item.physical_size)
                    for item in sorted(self._owned.values(), key=lambda x: x.address)}

        def ioctl(self, request, payload):
            with self._lock:
                self._check_healthy()
                require(type(payload) is rk.struct_rknpu_submit and
                        request == (3 << 30) | (ctypes.sizeof(rk.struct_rknpu_submit) << 16) | (ord('d') << 8) | 0x41,
                        'Only the exact final RKNPU submit ioctl is supported')
                n = integer(payload.task_number, 1, 4095, 'task count')
                expected = dict(flags=5, timeout=self._submit_timeout(), task_start=0, task_counter=0, priority=0,
                                regcfg_obj_addr=0, task_base_addr=0, user_data=0, core_mask=1, fence_fd=-1)
                require(all(getattr(payload, key) == value for key, value in expected.items()), 'Unsupported final submit fields')
                require([(s.task_start, s.task_number) for s in payload.subcore_task] ==
                        [(0, n), (n, 0), (n, 0), (0, 0), (0, 0)], 'Unsupported submit subcore fields')
                task, cmd = self._buffers.get('task'), self._buffers.get('cmd')
                require(task is not None and cmd is not None, 'Missing final encoder BOs')
                task_owner, cmd_owner = self._allocation(task), self._allocation(cmd)
                for item in self._owned.values():
                    self._allocation(item.buffer)
                require(payload.task_obj_addr == task.meta.obj_addr and task_owner.flags == rk.RKNPU_MEM_KERNEL_MAPPING and
                        cmd_owner.flags == 0 and n * ctypes.sizeof(rk.struct_rknpu_task) <= task.size,
                        'Submit task pointer/range is not owned')
                descriptors = (rk.struct_rknpu_task * n).from_address(task.va_addr)
                tasks = [{name: int(getattr(d, name)) for name, _ in rk.struct_rknpu_task._fields_} for d in descriptors]
                command_bytes = []
                next_address = cmd_owner.address
                for d in tasks:
                    require(all(d[k] == v for k, v in dict(flags=0, op_idx=4, enable_mask=0x18, int_mask=0x300,
                            int_clear=0x1FFFF, int_status=0, regcfg_offset=0).items()), 'Unsupported raw task descriptor')
                    amount = integer(d['regcfg_amount'], 4, 65539, 'initial/body QWORD amount')
                    address = d['regcmd_addr']
                    require(address == next_address and address % 16 == 0 and
                            address + amount * 8 <= cmd_owner.address + cmd.size, 'Command descriptor escapes or overlaps its owned BO')
                    raw = ctypes.string_at(cmd.va_addr + address - cmd_owner.address, amount * 8)
                    command_bytes.append(raw)
                    next_address = (address + amount * 8 + 15) & ~15
                require(next_address + PAGE <= cmd_owner.address + cmd.size, 'Missing final encoder guard page')
                require(not any(ctypes.string_at(cmd.va_addr + next_address - cmd_owner.address, PAGE)), 'Nonzero command guard page')
                for index, raw in enumerate(command_bytes):
                    tail = struct.unpack('<4Q', raw[-32:])
                    keys = tuple((w >> 48, w & 0xFFFF) for w in tail)
                    require(keys == ((0x101, 0x10), (0x101, 0x14), (0x41, 0), (0x81, 8)), 'Unsupported final PC tail framing')
                    values = tuple((w >> 16) & 0xFFFFFFFF for w in tail)
                    target = tasks[index + 1]['regcmd_addr'] if index + 1 < n else next_address
                    amount = tasks[index + 1]['regcfg_amount'] - 4 if index + 1 < n else 0
                    require(values == (target, amount, 0, 0x18), 'Raw chain differs from final task descriptors')
                self._tag = self._tag % 0xFFFFFFFF + 1
                record = dict(status='SUBMITTING', address=tasks[0]['regcmd_addr'], amount=tasks[0]['regcfg_amount'],
                    tag=self._tag, task_count=n, payload={name: int(getattr(payload, name)) for name, _ in payload._fields_ if name != 'subcore_task'},
                    tasks=tasks, task_bytes=bytes(descriptors), command_bytes=command_bytes)
                record['payload']['subcore_task'] = [{'task_start': s.task_start, 'task_number': s.task_number} for s in payload.subcore_task]
                self.records.append(record)
                try:
                    for item in self._owned.values():
                        if not item.initialized:
                            self._upload(item)
                    record['before'] = self._regions()
                    self.transport.submit(record['address'], record['amount'], self._tag)
                    result = self.transport.poll_result(timeout=payload.timeout / 1000)
                    require(all(type(getattr(result, key)) is int and 0 <= getattr(result, key) <= 0xFFFFFFFF
                                for key in ('tag', 'completed_tasks', 'error_code', 'status')) and
                            result.status & 4 and not result.status & (2 | 8 | 32 | 64) and not result.status & ~0x77F,
                            'Malformed hardware completion snapshot')
                    require(result.tag == self._tag and result.completed_tasks == n and result.error_code == 0,
                            'Hardware result tag/task count/error differs from the raw submission')
                    for item in self._owned.values():
                        self._download(item)
                    record['after'] = self._regions()
                    record['result'] = dict(tag=result.tag, completed_tasks=result.completed_tasks,
                                            error_code=result.error_code, status=result.status)
                    self.transport.ack_success()
                    record['status'] = 'PASS'
                except BaseException as error:
                    record.update(status='FAIL', error=str(error))
                    self._poisoned = True
                    raise
                return 0

        def reset_npu(self):
            raise UnsupportedProfile('Runtime reset is unsupported; joint platform reset or reconfiguration is required')

        def synchronize(self):
            self._check_healthy()  # All submitted jobs and transfers are blocking.

        def finalize(self):
            global _ACTIVE_DEVICE
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                self._buffers.clear(); self._owned.clear()
                try:
                    if self.transport is not None:
                        self.transport.close()
                        self.transport = None
                finally:
                    with _OWNER_LOCK:
                        if _ACTIVE_DEVICE is self:
                            _ACTIVE_DEVICE = None

    RKNPUFPGADevice.__name__ = 'RKNPUFPGADevice'
    RKNPUFPGADevice.backend_pin = receipt
    return RKNPUFPGADevice


class Registration:
    def __init__(self, module, device_class, device_registry):
        self.module, self.device_class, self.registry = module, device_class, device_registry
        self.backend_receipt = device_class.backend_pin
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.closed = True
        owner = _ACTIVE_DEVICE
        try:
            if isinstance(owner, self.device_class):
                owner.finalize()
        finally:
            # Remove only this adapter's opened-device entry, never another backend's
            # cached class or device. A fresh process is required for registration again.
            self.registry._opened_devices.discard(NAME)
            if sys.modules.get(MODULE) is self.module:
                del sys.modules[MODULE]

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def install(transport_factory, backend_path=None, *, transport_profile='ew_bram'):
    global _REGISTRATION_USED
    with _OWNER_LOCK:
        require(not _REGISTRATION_USED and MODULE not in sys.modules, 'RKNPUFPGA registration already exists; use a fresh process')
        device_class = make_device_class(transport_factory, backend_path, transport_profile=transport_profile)
        registry = importlib.import_module('tinygrad.device').Device
        require(NAME not in registry._devices and not any(d.split(':')[0] == NAME for d in registry._opened_devices),
                'RKNPUFPGA device binding already exists')
        try:
            registry.get_class(NAME)
        except ModuleNotFoundError as error:
            require(error.name == MODULE, 'Unexpected runtime import failure')
        else:
            raise UnsupportedProfile('RKNPUFPGA class was already cached')
        module = ModuleType(MODULE)
        module.RKNPUFPGADevice = device_class
        sys.modules[MODULE] = module
        _REGISTRATION_USED = True
        return Registration(module, device_class, registry)
