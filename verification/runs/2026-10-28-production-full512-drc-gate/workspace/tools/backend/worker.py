#!/usr/bin/env python3
"""Fresh production tinygrad Tensor compilation/execution against an offline RTL link.

The software arithmetic model below is exclusively a post-execution test oracle.
The runtime adapter never imports it or receives expected output bytes.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from contextlib import ExitStack
import gc
import hashlib
import inspect
import json
import os
from pathlib import Path
import socket
import struct
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from tools.backend.rtl_link import RtlLink
from tools.host.transport import JtagTransport


def json_value(value):
    if isinstance(value, bytes):
        return {'base64': base64.b64encode(value).decode(),
                'sha256': hashlib.sha256(value).hexdigest(), 'size': len(value)}
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def implementation(function, name, filename):
    """Locate an original decorated function without replacing any pipeline code."""
    pending, seen, matches = [function], set(), []
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:continue
        seen.add(id(candidate))
        if candidate.__code__.co_name == name and Path(candidate.__code__.co_filename).resolve() == filename.resolve():
            matches.append(candidate)
        for cell in candidate.__closure__ or ():
            if inspect.isfunction(cell.cell_contents):pending.append(cell.cell_contents)
    if len(matches) != 1:
        raise RuntimeError('Cannot identify original production implementation: '+name)
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--endpoint', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--operation', choices=('ADD', 'SUB', 'MUL'), required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--expect-reject-runtime-gather', action='store_true')
    args = parser.parse_args()
    args.backend = args.backend.resolve()
    if sys.flags.optimize:
        parser.error('optimized Python is unsupported for the qualification oracle')
    args.out.mkdir(parents=True, exist_ok=False)
    os.environ.update(OTPU_RUN_DIR=str(args.out / 'locks'), CACHELEVEL='0', PYTHONDONTWRITEBYTECODE='1')
    record = {'status': 'RUNNING', 'operation': args.operation, 'count': args.count,
              'repeat': args.repeat, 'numeric_cpu_fallback': False, 'hardware_access': False,
              'scope': 'Actual production compiler/final writer and Verilator frame RTL; test TAP shim, no FPGA/RK/DDR/PCIe proof'}
    report_path = args.out / 'report.json'
    def save():
        report_path.write_text(json.dumps(record, indent=2) + '\n')
    save()
    link = installation = None
    guards = ExitStack()
    try:
        # A missed offline injection must fail, rather than reaching any XVC server.
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden in offline backend qualification')):
            from tools.backend.runtime import UnsupportedProfile, install
            link = RtlLink(args.endpoint, args.out/'frames.jsonl', args.out/'rtl-stderr.log')
            transport = JtagTransport(host=link.host, port=link.port, link=link)
            installation = install(lambda: transport, backend_path=args.backend)
            from tinygrad import Tensor
            from tinygrad.device import Device
            from tinygrad.dtype import dtypes
            from tinygrad.helpers import Context
            from tinygrad.runtime import ops_rockchip as upstream
            from tinygrad import codegen
            from model.half import alu, to_bits
            guards.enter_context(patch.object(upstream.RockchipDevice,'__init__',
                side_effect=AssertionError('DRM device creation forbidden in offline qualification')))
            guards.enter_context(patch.object(upstream,'FileIOInterface',
                side_effect=AssertionError('DRM IO forbidden in offline qualification')))

            tracked = {'to_program':codegen.to_program.__code__,
                       'do_to_program':implementation(codegen.do_to_program,'do_to_program',args.backend/'tinygrad/codegen/__init__.py').__code__,
                       'render':upstream.RockchipRenderer.render.__code__,
                       'program_init':upstream.RockchipProgram.__init__.__code__,
                       'submit_bodies':upstream.RockchipProgram._submit_bodies.__code__,
                       'submit':upstream.RockchipProgram._submit.__code__,
                       'regular_gather':upstream._regular_gather_payload.__code__}
            counts = {name:0 for name in tracked}
            foreign_compilation, compiled_images = [], []
            def profile(frame, event, value):
                if event != 'call':return
                for name, code in tracked.items():
                    if frame.f_code is not code:continue
                    if name in ('to_program','do_to_program'):
                        renderer = frame.f_locals.get('renderer')
                        target = getattr(getattr(renderer,'target',None),'device',None)
                        if target != 'ROCKCHIP':
                            if name == 'to_program':foreign_compilation.append(target)
                            continue
                        if type(renderer) is not upstream.RockchipRenderer:
                            raise RuntimeError('Production renderer class replaced')
                    counts[name] += 1
                    if name == 'program_init':
                        image = frame.f_locals['obj'].lib
                        (args.out/f'program-{len(compiled_images)}.bin').write_bytes(image)
                        compiled_images.append(hashlib.sha256(image).hexdigest())
            if sys.getprofile() is not None:
                raise RuntimeError('Qualification requires an uninstrumented fresh process')

            # Test data includes nonzero signed values; the real framework COPY
            # path must upload them before the native runtime's FROM_DEVICE sync.
            a_bits = [to_bits((i % 13-6)/4) for i in range(args.count)]
            b_bits = [to_bits((i % 7-3)/2) for i in range(args.count)]
            a_storage = (ctypes.c_uint16 * args.count)(*a_bits)
            b_storage = (ctypes.c_uint16 * args.count)(*b_bits)
            expected = struct.pack('<'+'H'*args.count, *(alu(a,b,args.operation) for a,b in zip(a_bits,b_bits)))
            record['input_a_hex'] = bytes(a_storage).hex()
            record['input_b_hex'] = bytes(b_storage).hex()
            record['expected_hex'] = None if args.expect_reject_runtime_gather else expected.hex()
            record['expect_reject_runtime_gather'] = args.expect_reject_runtime_gather
            record['outputs'] = []
            sys.setprofile(profile)
            with Context(DEV='RKNPUFPGA', DEFAULT_FLOAT='HALF', NOOPT=0):
                a = Tensor.from_blob(ctypes.addressof(a_storage), (args.count,), dtype=dtypes.half, device='CPU').to('RKNPUFPGA').realize()
                b = Tensor.from_blob(ctypes.addressof(b_storage), (args.count,), dtype=dtypes.half, device='CPU').to('RKNPUFPGA').realize()
                dev = Device['RKNPUFPGA']
                if hasattr(dev.allocator, '_as_buffer'):
                    raise RuntimeError('Remote shadow allocator exposes an unsynchronized COPY fast path')
                if dev.runtime_t._submit_bodies is not upstream.RockchipProgram._submit_bodies:
                    raise RuntimeError('The production final command encoder was replaced')
                for _ in range(args.repeat):
                    if args.expect_reject_runtime_gather:
                        try:
                            (a.flip(0)+b).realize()
                        except UnsupportedProfile as error:
                            if 'Runtime CPU gathers or post-EW layout operations are unsupported' not in str(error):raise
                            record['expected_rejection'] = str(error)
                        else:
                            raise RuntimeError('Runtime gather graph was accepted')
                    else:
                        result = {'ADD': lambda: a+b, 'SUB': lambda: a-b, 'MUL': lambda: a*b}[args.operation]().realize()
                        observed = bytes(result._buffer().as_memoryview())
                        if observed != expected:
                            raise RuntimeError(f'production Tensor result differs: {observed.hex()} != {expected.hex()}')
                        record['outputs'].append(observed.hex())
                record['backend'] = installation.backend_receipt
                record['submissions'] = json_value(dev.records)
                record['submission_count'] = len(dev.records)
                sys.setprofile(None)
                required = ('to_program','do_to_program','render') if args.expect_reject_runtime_gather else (
                    'to_program','do_to_program','render','program_init','submit_bodies','submit')
                if foreign_compilation or counts['regular_gather'] or any(counts[name]<1 for name in required):
                    raise RuntimeError('Missing original compiler execution or unexpected CPU compilation/gather')
                expected_submits = 0 if args.expect_reject_runtime_gather else args.repeat
                if counts['submit_bodies'] != expected_submits or counts['submit'] != expected_submits:
                    raise RuntimeError('Unexpected final-writer/submission multiplicity')
                record['pipeline'] = {'calls':counts,'foreign_compilation':foreign_compilation,
                    'compiler_images':compiled_images,'code':{name:{'file':str(Path(code.co_filename).relative_to(args.backend)),
                    'line':code.co_firstlineno,'source_sha256':hashlib.sha256(Path(code.co_filename).read_bytes()).hexdigest()}
                    for name,code in tracked.items()}}
                # Record first, then let an independent test-only raw DMA oracle
                # check complete BO memory against those actual submissions.
                record['reference_scope'] = ('Unsupported graph rejection only; no arithmetic result' if args.expect_reject_runtime_gather
                                             else 'Post-execution test only; never runtime fallback')
                # Driver receipt structure is validated by the parent runner.
                record['frame_commands'] = link.frames
                if not args.expect_reject_runtime_gather:del result
                del a, b
                gc.collect()
                installation.close(); installation=None
            if link.returncode != 0:
                raise RuntimeError(f'native RTL exited {link.returncode}')
            record['native_returncode'] = link.returncode
        record['status'] = 'PASS'
    except Exception as exc:
        record.update(status='FAIL', reason=str(exc))
    finally:
        sys.setprofile(None)
        if installation is not None:
            installation.close()
        elif link is not None:
            link.close()
        guards.close()
        save()
    if record['status'] != 'PASS':
        print(record['reason'], file=sys.stderr)
        return 1
    if args.expect_reject_runtime_gather:
        print('PASS backend_runtime_gather explicitly_rejected_before_final_writer_and_submission')
    else:
        print(f'PASS backend_tensor {args.operation} count={args.count} repeats={args.repeat} actual_final_writer_and_RTL')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
