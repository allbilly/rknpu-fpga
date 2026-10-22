#!/usr/bin/env python3
"""Replay actual backend-emitted QWORDs with synthetic BO data; no device is opened.

The renderer and runtime PC-tail writer execute unchanged. Only allocation and
submission are intercepted. This is NOT a silicon capture or test_ops integration.
Run make test first, then use Python with NumPy and --backend pointing at the
pinned allbilly/tinygrad checkout described in docs/SOURCES.md.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PIN = 'c6784623afc4f116ae7dc326ab9842e6bf9a3dcf'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backend', type=Path, required=True)
args = parser.parse_args()
backend = args.backend.resolve()
commit = subprocess.check_output(['git', '-C', str(backend), 'rev-parse', 'HEAD'], text=True).strip()
if commit != PIN:
    sys.exit(f'Backend revision {commit} differs from audited {PIN}; audit before changing this pin')
if subprocess.check_output(['git', '-C', str(backend), 'status', '--porcelain'], text=True).strip():
    sys.exit('Backend checkout must be clean for this provenance check')
sys.path.insert(0, str(backend))
sys.path.insert(1, str(ROOT))
from tinygrad.renderer.rockchip import RKArg, RKBufferKind, _EW_CFG, emit_ew_stage, patch_stage
from tinygrad.runtime.ops_rockchip import RockchipProgram
from tinygrad.uop.ops import Ops
from model.profile import make_commands
from tools.evidence import source_revision

rtl_report = json.loads((ROOT / 'build/rtl/report.json').read_text())
if rtl_report['status'] != 'PASS' or rtl_report['source_revision']['sha256'] != source_revision()['sha256']:
    sys.exit('Run make rtl-test for the current sources before replaying backend commands')
if Path(emit_ew_stage.__code__.co_filename).resolve() != backend / 'tinygrad/renderer/rockchip.py':
    sys.exit('The renderer was not imported from the pinned checkout')

out = ROOT / 'build/backend_encoder'
out.mkdir(parents=True, exist_ok=True)
report = {'status': 'RUNNING', 'backend_commit': commit,
          'scope': 'Actual final backend encoder plus synthetic buffers; no RK3588 execution, no test_ops coverage',
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'rtl_source_revision': rtl_report['source_revision']['sha256'],
          'rtl_executable_sha256': hashlib.sha256((ROOT / 'build/rtl/obj_tb_ew/sim').read_bytes()).hexdigest(),
          'python': sys.version, 'cases': []}
for op in ('ADD', 'SUB', 'MUL'):
    for count in (8, 9, 33):
        addresses = (0x10040000, 0x10001000, 0x10020000)  # destination, A, B
        arguments = tuple(RKArg(RKBufferKind.ARG, i) for i in range(3))
        stage = emit_ew_stage(*arguments, count, _EW_CFG[getattr(Ops, op)])
        body = patch_stage(stage, lambda kind, index: addresses[index])
        program = object.__new__(RockchipProgram)
        program._pcchain_bodies = None
        program._cmd_buf = program._task_buf = None
        allocations, captured = [], []

        def allocate(name, size, minimum, flags=0):
            storage = ctypes.create_string_buffer(max(size, minimum))
            allocations.append(storage)
            return type('TestBO', (), {'va_addr': ctypes.addressof(storage), 'size': len(storage)})()

        program._ensure_buffer = allocate
        program._dma = lambda bo: 0x100e0000
        program._submit = lambda cmd, task, n: captured.append(ctypes.string_at(cmd.va_addr, (len(body)+4)*8))
        program._submit_pcchain([body])
        if len(captured) != 1:
            raise AssertionError('Expected one intercepted submission')
        raw = captured[0]
        expected = make_commands(op, count, addresses[1], addresses[2], addresses[0])
        if raw != expected:
            raise AssertionError(f'{op}/{count}: final encoded bytes differ from the supported profile')
        name = f'{op.lower()}_{count}'
        case = out / name
        case.mkdir(exist_ok=True)
        (case / 'commands.bin').write_bytes(raw)
        (case / 'commands.hex').write_text(''.join(f'{word:016x}\n' for word, in struct.iter_unpack('<Q', raw)))
        for filename in ('input.hex', 'check.txt'):
            shutil.copyfile(ROOT / 'build/vectors' / name / filename, case / filename)
        command = [str(ROOT / 'build/rtl/obj_tb_ew/sim'), f'+CASE={case}', f'+NCMD={len(raw)//8}',
                   '+ECODE=0', '+NDONE=1', '+BUS_ERROR_AT=0', '+DROP=0', '+STALL_REQUEST=0',
                   f'+NTRANS={3*((count+7)//8)*8}', f'+NCHECKS={3*(((count+7)//8)*8+8)}']
        result = subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
        (case / 'rtl.log').write_text(result.stdout + result.stderr)
        if result.returncode or not result.stdout.startswith('PASS '):
            raise AssertionError(f'{name}: RTL replay failed: {result.stdout}{result.stderr}')
        report['cases'].append({'name': name, 'status': 'PASS', 'qwords': len(raw)//8,
                                'raw_sha256': hashlib.sha256(raw).hexdigest(), 'argv': command})
        print(f'PASS backend encoder -> final command bytes -> RTL: {name}', flush=True)
report['status'] = 'PASS'
(out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
