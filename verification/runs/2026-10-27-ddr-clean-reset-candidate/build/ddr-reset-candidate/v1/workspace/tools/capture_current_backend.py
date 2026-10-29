#!/usr/bin/env python3
"""Capture production tinygrad compilation and final RK submission without a device.

Only host-owned BO allocation, synchronization and the final ioctl are replaced.
No tensor-data gather, numeric fallback, command rewriting or hardware access is
allowed. Captures are synthetic inputs plus real encoder bytes, NOT RK outputs.
An unsupported replay is recorded as unsupported, never as numerical success.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import pickle
import platform
import struct
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch
import zlib

from evidence import ROOT, source_revision, timestamp

PIN = '078eee94d8f1912bb63ce786c250d2c24984844a'
BASE, A, B, D, S, C, T = 0x10000000, 0x10001000, 0x10020000, 0x10040000, 0x10060000, 0x100e0000, 0x100f0000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=Path, default=Path('/home/fedora/tinygrad'))
    parser.add_argument('--rtl', action='store_true', help='Also replay the unchanged first task in the existing core testbench')
    args = parser.parse_args()
    backend = args.backend.resolve()

    def git(*arguments):
        return subprocess.check_output(['git', '-C', str(backend), *arguments], text=True).strip()

    if git('rev-parse', 'HEAD') != PIN or git('status', '--porcelain'):
        raise RuntimeError(f'Expected the clean, audited backend revision {PIN}')
    os.environ.update(CACHELEVEL='0', PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(backend), str(ROOT)]
    from tinygrad import Tensor
    from tinygrad.codegen import to_program, to_program_cache
    from tinygrad.dtype import dtypes
    from tinygrad.helpers import Context, Target
    from tinygrad.renderer.rockchip import RockchipRenderer, RKEWOp, RKGather, RKEWMode
    from tinygrad.runtime import ops_rockchip as runtime
    from tinygrad.runtime.autogen import rockchip as rk
    from tinygrad.runtime.support.hcq import HCQBuffer, MMIOInterface
    from tinygrad.uop.ops import Ops, UOp
    from model.half import to_bits, alu
    from model.profile import Decoder, ProfileError

    out = ROOT / 'build/backend-current'
    out.mkdir(parents=True, exist_ok=True)
    revision = source_revision()
    report = dict(status='CAPTURING', started_utc=timestamp(), source_revision=revision,
                  backend_commit=PIN, python_version=platform.python_version(), cases=[],
                  scope='Production to_program and final ioctl bytes with synthetic BOs; no RK or FPGA execution',
                  hardware_outputs=None, command_words_rewritten=False, runtime_data_gathers=False)
    report['backend_files'] = {name: hashlib.sha256((backend/name).read_bytes()).hexdigest() for name in (
        'tinygrad/renderer/rockchip.py', 'tinygrad/runtime/ops_rockchip.py', 'tinygrad/runtime/autogen/rockchip.py')}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.rtl:
        rtl = json.loads((ROOT/'build/rtl/report.json').read_text())
        if rtl['status'] != 'PASS' or rtl['source_revision']['sha256'] != revision['sha256']:
            raise RuntimeError('Run make rtl-test for these exact sources before --rtl')
        report['rtl_tool_version'] = rtl['tool_version']

    class CaptureDevice:
        def __init__(self, path):
            self.path, self.buffers, self.storage, self.submissions = path, {}, [], []
            self.fd_ctl, self._lock = self, threading.Lock()
            self._native_int16, self._poisoned, self._npu_clean = False, False, True
            self.submit_count = self.task_count = self.timeout_retries = 0

        def allocate(self, address, size):
            size = max(4096, (size+4095)&-4096)
            if any(address < other+buf.size and other < address+size for other, buf in self.buffers.items()):
                raise RuntimeError('Capture BO overlap')
            storage = ctypes.create_string_buffer(size)
            self.storage.append(storage)  # Own every pointer used by the real runtime.
            va = ctypes.addressof(storage)
            buf = HCQBuffer(va, size, meta=SimpleNamespace(dma_addr=address, obj_addr=va, size=size),
                            view=MMIOInterface(va, size))
            self.buffers[address] = buf
            return buf

        def _ensure_buffer(self, name, size, minimum, flags=0):
            if name != 'scratch' or flags:
                raise RuntimeError('Unexpected allocation')
            return self.allocate(S, max(size, minimum))

        def _replace_submit_buffers(self, cmd_size, task_size):
            return self.allocate(C, max(cmd_size, 65536)), self.allocate(T, max(task_size, 16384))

        def _sync_buffers(self, bufs, flags):
            for buf in bufs:
                if buf.base not in self.buffers.values():
                    raise RuntimeError('Non-owned buffer')

        def reset_npu(self):
            raise RuntimeError('Unexpected reset: capture only the audited HALF EW path')

        def ioctl(self, request, payload):
            if not isinstance(payload, rk.struct_rknpu_submit) or payload.core_mask != 1 or payload.task_start:
                raise RuntimeError('Unexpected submission')
            cmd, task = self.buffers[C], self.buffers[T]
            n = payload.task_number
            if payload.task_obj_addr != task.va_addr or not 0 < n <= task.size//ctypes.sizeof(rk.struct_rknpu_task):
                raise RuntimeError('Descriptor outside owned buffer')
            descs = (rk.struct_rknpu_task*n).from_address(task.va_addr)
            records = []
            for i, desc in enumerate(descs):
                offset, size = desc.regcmd_addr-C, desc.regcfg_amount*8
                if desc.enable_mask != 0x18 or offset < 0 or offset+size > cmd.size:
                    raise RuntimeError('Commands outside audited EW BO')
                raw = ctypes.string_at(cmd.va_addr+offset, size)
                filename = f'task{i}.bin'
                (self.path/filename).write_bytes(raw)
                records.append(dict(file=filename, sha256=hashlib.sha256(raw).hexdigest(),
                                    descriptor={name: int(getattr(desc,name)) for name,_ in desc._fields_}))
            regions = {}
            for address, buf in self.buffers.items():
                data = ctypes.string_at(buf.va_addr, buf.size)
                filename = f'bo_{address:08x}.bin'
                (self.path/filename).write_bytes(data)
                regions[address] = data
            (self.path/'submit.bin').write_bytes(bytes(payload))
            self.submissions.append(dict(tasks=records, regions=regions))
            return 0

    def no_device(*args, **kwargs):
        raise RuntimeError('Hardware device access forbidden in offline capture')

    with patch.object(runtime.RockchipDevice, '__init__', no_device), patch.object(runtime, 'FileIOInterface', no_device):
        with Context(DEV='ROCKCHIP', DEFAULT_FLOAT='HALF', NOOPT=0):
            for op in ('ADD', 'SUB', 'MUL'):
                for count in (8, 9, 33):
                    name = f'{op.lower()}_{count}'
                    path = out/name
                    path.mkdir(exist_ok=True)
                    a,b = (Tensor(UOp.new_buffer('ROCKCHIP',count,dtypes.half,num=76000+i)) for i in range(2))
                    tensor = {'ADD': lambda: a+b, 'SUB': lambda: a-b, 'MUL': lambda: a*b}[op]()
                    calls = tensor.schedule_linear().src
                    if len(calls) != 1:
                        raise RuntimeError('Unexpected multi-kernel schedule')
                    to_program_cache.clear()
                    program = to_program(calls[0].src[0], RockchipRenderer(Target(device='ROCKCHIP')))
                    lib = next(x.arg for x in program.src if x.op is Ops.BINARY)
                    image = pickle.loads(zlib.decompress(lib))  # Locally compiled, never an external pickle.
                    saw_ew = False
                    for item in image.program:
                        if isinstance(item, RKEWOp) and item.mode is RKEWMode.HALF:
                            saw_ew = True
                        elif (isinstance(item, RKGather) and not saw_ew and item.src is None
                              and item.index is None and item.values):
                            pass  # Compile-time constant BO initialization, no runtime tensor movement.
                        else:
                            raise RuntimeError(f'Unsupported runtime operation: {item}')
                    device = CaptureDevice(path)
                    bufs = [device.allocate(addr, count*2) for addr in (D,A,B)]
                    av = [to_bits((i%13-6)/4) for i in range(count)]
                    bv = [to_bits((i%7-3)/2) for i in range(count)]
                    ctypes.memset(bufs[0].va_addr, 0xa5, bufs[0].size)
                    for buf, values in zip(bufs[1:], (av,bv)):
                        data = struct.pack('<'+'H'*count, *values)
                        ctypes.memmove(buf.va_addr, data, len(data))
                    expected = struct.pack('<'+'H'*count, *(alu(x,y,op) for x,y in zip(av,bv)))
                    (path/'expected_logical.bin').write_bytes(expected)
                    (path/'program.bin').write_bytes(lib)
                    runtime.RockchipProgram(device, SimpleNamespace(name=name,lib=lib))(*bufs)
                    if len(device.submissions) != 1:
                        raise RuntimeError('Unexpected multiple submissions')
                    submission = device.submissions[0]
                    raw = (path/submission['tasks'][0]['file']).read_bytes()
                    decoder, error = Decoder(), None
                    for index, (word,) in enumerate(struct.iter_unpack('<Q',raw)):
                        try:
                            decoder.feed(word)
                        except ProfileError as exc:
                            error = dict(code=exc.code, qword_index=index, word=f'{word:016x}', detail=str(exc))
                            break
                    result = dict(name=name, logical_count=count, tasks=submission['tasks'],
                                  initialization_only_gathers=sum(isinstance(x,RKGather) for x in image.program),
                                  replay_status='UNSUPPORTED' if error else 'DECODED_NOT_EXECUTED', rejection=error,
                                  bo_files=[f'bo_{addr:08x}.bin' for addr in submission['regions']])
                    if args.rtl:
                        if error is None:
                            raise RuntimeError('Decoder now accepts the stream: implement numerical replay before claiming RTL acceptance')
                        regions = submission['regions']
                        (path/'commands.hex').write_text(''.join(f'{w:016x}\n' for (w,) in struct.iter_unpack('<Q',raw)))
                        (path/'input.hex').write_text(''.join(f'@{(addr-BASE)//2:x}\n'+''.join(
                            f'{w:04x}\n' for (w,) in struct.iter_unpack('<H',data)) for addr,data in sorted(regions.items())))
                        (path/'check.txt').write_text(''.join(f'{addr+2*i:08x} {w:04x}\n' for addr,data in sorted(regions.items())
                            for i,(w,) in enumerate(struct.iter_unpack('<H',data))))
                        command = [str(ROOT/'build/rtl/obj_tb_ew/sim'), f'+CASE={path}', f'+NCMD={len(raw)//8}',
                                   f'+ECODE={error["code"]}', '+NDONE=0', '+NTRANS=0', f'+NCHECKS={sum(len(data)//2 for data in regions.values())}']
                        run = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
                        (path/'rtl.log').write_text(run.stdout)
                        if run.returncode or 'PASS ' not in run.stdout:
                            raise RuntimeError(f'RTL rejection check failed: {run.stdout}')
                        result['rtl_rejection_check'] = dict(status='PASS', command=command, log=f'{name}/rtl.log')
                    report['cases'].append(result)
                    print(f'{name}: {len(submission["tasks"])} raw task(s); replay {result["replay_status"]}: {error}', flush=True)
    if source_revision()['sha256'] != revision['sha256'] or git('rev-parse','HEAD') != PIN or git('status','--porcelain'):
        raise RuntimeError('Sources changed during capture')
    report.update(status='CAPTURED', finished_utc=timestamp())
    report['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in out.rglob('*') if p.is_file() and p.name != 'report.json'
                       and (args.rtl or p.suffix == '.bin')}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    main()
