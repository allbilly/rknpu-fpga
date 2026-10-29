#!/usr/bin/env python3
"""Prepare BOS/layer0 Wq raw commands and donor-policy test expectations.

Uses the pinned production emitters and final writer, not Tensor integration.
All normalization/packing/arithmetic here prepares a static test fixture.
Nothing opens a hardware transport or supplies runtime hardware results.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import pickle
import struct
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from tools.tinystories.prepare import require, verify
from tools.backend.runtime import verify_backend
from tools.cmac.cacc_reference import add, final

HELPER_SHA = 'f7c53e8e4d0d12db0c9d62e2c0b2fac3fe95458b3af85328b6f0b3bf9036d2f0'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def forbidden(*args, **kwargs):
    raise RuntimeError('Hardware access and runtime gathers are forbidden in fixture preparation')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--backend', type=Path, default=Path.home()/'tinygrad')
    parser.add_argument('--booth-helper', type=Path, default=ROOT/'build/cmac_group_candidate/donor_booth_helper.cpp')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Optimized Python is unsupported for test expectations')
    package = args.prepared.resolve()
    prepared = verify(package)
    backend = verify_backend(args.backend)
    require(digest(args.booth_helper) == HELPER_SHA, 'Changed reviewed donor test helper')
    out = args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(), 'Use a fresh fixture directory below build')
    out.mkdir(parents=True)
    sys.path.insert(0, backend['root'])
    from tinygrad.renderer.rockchip import RKArg, RKBufferKind, RKCMAC, RKEWOp, RKImage, emit_cmac_stage, emit_ew_stage
    from tinygrad.runtime import ops_rockchip as runtime
    from tinygrad.runtime.autogen import rockchip as rk
    from tinygrad.runtime.support.hcq import HCQBuffer, MMIOInterface
    report = dict(status='RUNNING', scope='Static first learned projection through original stage emitters/final writer and test oracle; no FPGA/Tensor execution',
                  hardware_accessed=False, runtime_cpu_layout_fixups=False, backend=backend,
                  model_package_sha256=digest(package/'report.json'), files={}, commands=[])
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    def artifact(name, raw):
        path = out/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        report['files'][name] = dict(sha256=digest(path), bytes=len(raw))
    class Capture:
        def __init__(self, name):
            self.name, self.storage, self.buffers, self.submissions = name, [], {}, []
            self.fd_ctl = self
            self._npu_clean, self._poisoned = True, False
            self.submit_count = self.task_count = self.timeout_retries = self.resets = 0
        def allocate(self, address, size):
            owner = ctypes.create_string_buffer(size)
            self.storage.append(owner)
            va = ctypes.addressof(owner)
            value = HCQBuffer(va, size, meta=SimpleNamespace(dma_addr=address, obj_addr=va, size=size), view=MMIOInterface(va, size))
            self.buffers[address] = value
            return value
        def _replace_submit_buffers(self, command_size, task_size):
            return self.allocate(0x100e0000, max(65536, command_size)), self.allocate(0x100f0000, max(4096, task_size))
        def _sync_buffers(self, buffers, flags):
            require(all(b.base in self.buffers.values() for b in buffers), 'Unowned encoder buffer')
        def reset_npu(self):
            # Recording only: live successful-standalone reset/rearm remains
            # an explicit integration gate, not an ignored hardware action.
            self.resets += 1
            self._npu_clean = True
        def ioctl(self, request, payload):
            require(isinstance(payload, rk.struct_rknpu_submit) and payload.core_mask == 1 and payload.task_start == 0,
                    'Unexpected production submission')
            cmd, task = self.buffers[0x100e0000], self.buffers[0x100f0000]
            require(payload.task_obj_addr == task.va_addr, 'Unexpected task address')
            descriptors = (rk.struct_rknpu_task*payload.task_number).from_address(task.va_addr)
            rows = [{n: int(getattr(d, n)) for n, _ in d._fields_} for d in descriptors]
            artifact(self.name+'/command_bo.bin', ctypes.string_at(cmd.va_addr, cmd.size))
            artifact(self.name+'/task_bo.bin', ctypes.string_at(task.va_addr, task.size))
            artifact(self.name+'/submit.bin', bytes(payload))
            self.submissions.append(rows)
            return 0
    save()
    try:
        tensors = __import__('tools.tinystories.prepare', fromlist=['tensor_layout']).tensor_layout()
        model = (package/'assets/stories260K.bin').read_bytes()
        # Invoke the actual unmodified official C RMSNorm to obtain the
        # test input. No NumPy dependency or independently reordered reduction.
        probe = out/'reference_probe.c'
        probe.write_text('#define TESTING\n#include "run.c"\n'
            'int main(int argc,char**argv) {\n'
            ' if(argc!=2)return 2; Transformer t; build_transformer(&t,argv[1]);\n'
            ' if(t.config.dim!=64||t.config.n_layers!=5)return 3; float values[64];\n'
            ' rmsnorm(values,t.weights.token_embedding_table+64,t.weights.rms_att_weight,64);\n'
            ' int ok=fwrite(values,sizeof(float),64,stdout)==64; free_transformer(&t);return ok?0:4; }\n')
        compile_probe = ['gcc', '-O3', '-I'+str(package/'reference'), str(probe), '-lm', '-o', str(out/'reference_probe')]
        built = subprocess.run(compile_probe, capture_output=True, check=False)
        artifact('reference_probe_compile.log', built.stdout+built.stderr)
        report['commands'].append(dict(argv=compile_probe, returncode=built.returncode))
        require(built.returncode == 0, 'Official RMSNorm reference probe compilation failed')
        probe_binary_sha = digest(out/'reference_probe')
        probe_argv = [str(out/'reference_probe'), str(package/'assets/stories260K.bin')]
        observed = subprocess.run(probe_argv, capture_output=True, check=False)
        report['commands'].append(dict(argv=probe_argv, returncode=observed.returncode))
        require(observed.returncode == 0 and len(observed.stdout) == 256 and not observed.stderr,
                'Official RMSNorm reference probe failed')
        require(digest(out/'reference_probe') == probe_binary_sha, 'Reference probe binary changed')
        report['reference_probe_binary_sha256'] = probe_binary_sha
        normalized_bytes = observed.stdout
        normalized = struct.unpack('<64f', normalized_bytes)
        input_bytes = b''.join(struct.pack('<e', value) for value in normalized)
        inputs = list(struct.unpack('<64H', input_bytes))
        tile = prepared['tiles'][0]
        require((tile['projection'], tile['first_output'], tile['ai'], tile['ao']) == ('layers.0.wq', 0, 64, 32), 'Wrong first projection tile')
        weights_raw = (package/tile['file']).read_bytes()
        weights = list(struct.unpack('<2048H', weights_raw))
        dest, lhs, rhs = (RKArg(RKBufferKind.ARG, i) for i in range(3))
        cmac = RKCMAC(dest, lhs, rhs, 1, 32, 64)
        addresses = {dest:0x10040000, lhs:0x10010000, rhs:0x10020000}
        with patch.object(runtime.RockchipDevice, '__init__', forbidden), patch.object(runtime, 'FileIOInterface', forbidden), \
             patch.object(runtime, '_apply_gathers', forbidden):
            device = Capture('cmac')
            body = emit_cmac_stage(cmac, addresses.__getitem__)
            require(len(body) == 45, 'Changed CMAC body contract')
            image = zlib.compress(pickle.dumps(RKImage(program=(cmac,))))
            runtime.RockchipProgram(device, SimpleNamespace(name='tinystories_bos_wq0', lib=image))._submit_bodies((body,), standalone=True, cmac=True)
            require(len(device.submissions) == 1 and device.resets == 1, 'Changed standalone/reset callback contract')
            descriptor = device.submissions[0][0]
            require(descriptor['regcfg_amount'] == 45 and descriptor['enable_mask'] == 0xd, 'Changed CMAC descriptor')
            words = struct.unpack_from('<49Q', ctypes.string_at(device.buffers[0x100e0000].va_addr, 392))
            require(words[:45] == body and words[45:] == (0x0001000000000000, 0x0101000000000014,
                    0x0041000000000000, 0x00810000000d0008), 'Final CMAC words were changed')
            # Source-evidenced hardware movement candidate, two16-halfword MUL1
            # tasks. The actual encoder owns PC tails, padding and descriptors.
            ew = Capture('compaction')
            a, b, d = (RKArg(RKBufferKind.ARG, i) for i in range(3))
            bodies = []
            for source, target in ((0x10040000, 0x10050000), (0x10040040, 0x10050020)):
                op = RKEWOp(d, a, b, 16, 0x108003c4)
                mapping = {a:source, b:0x10060000, d:target}
                bodies.append(emit_ew_stage(op, mapping.__getitem__))
            runtime.RockchipProgram(ew, SimpleNamespace(name='finite_native_to_linear', lib=zlib.compress(pickle.dumps(RKImage()))))._submit_bodies(bodies)
            require(len(ew.submissions) == 1 and len(ew.submissions[0]) == 2 and ew.resets == 0, 'Changed EW chain contract')
        compile_argv = ['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', str(args.booth_helper), '-o', str(out/'donor_helper')]
        compiled = subprocess.run(compile_argv, capture_output=True, text=True, check=False)
        artifact('donor_compile.log', (compiled.stdout+compiled.stderr).encode())
        report['commands'].append(dict(argv=compile_argv, returncode=compiled.returncode))
        require(compiled.returncode == 0, 'Donor test helper compilation failed')
        helper_binary_sha = digest(out/'donor_helper')
        requests, metadata, reads = [], [], []
        for oc in (0, 16):
            for ic in (0, 32):
                data = inputs[ic:ic+32]
                begin = oc*64+ic*16
                reads += [((0x10010000+2*(ic+c))<<16)|data[c] for c in range(32)]
                reads += [((0x10020000+2*(begin+j))<<16)|weights[begin+j] for j in range(512)]
                for kernel in range(16):
                    weight = weights[begin+kernel*32:begin+(kernel+1)*32]
                    active = [bool(x&0x7fff) and bool(w&0x7fff) for x,w in zip(data, weight)]
                    exponents = [((x>>12)&7)+((w>>12)&7) if used else 0 for x,w,used in zip(data,weight,active)]
                    maximum, start = max(exponents), len(requests)
                    def mant(value):
                        e = (value>>10)&31
                        return ((value&1023)|(1024 if e else 0)) << (e&3 if e else 1)
                    for x,w,used,e in zip(data,weight,active,exponents):
                        if used:
                            requests.append(f'{(x^w)>>15} {mant(w)} {mant(x)} {(maximum-e)*4}\n')
                    metadata.append((oc, ic, kernel, maximum, start, len(requests)))
        result = subprocess.run([str(out/'donor_helper')], input=''.join(requests), capture_output=True, text=True, check=False)
        report['commands'].append(dict(argv=[str(out/'donor_helper')], returncode=result.returncode,
                                       binary_sha256=helper_binary_sha))
        require(result.returncode == 0 and len(result.stdout.split()) == len(requests), 'Donor grouping reference failed')
        require(digest(out/'donor_helper') == helper_binary_sha, 'Donor test helper binary changed')
        report['donor_helper_binary_sha256'] = helper_binary_sha
        artifact('donor_requests.txt', ''.join(requests).encode())
        artifact('donor_results.txt', result.stdout.encode())
        artifact('donor_stderr.log', result.stderr.encode())
        partials = list(map(int, result.stdout.split()))
        accumulators = [0]*16
        groups, writes, fp32 = [], [], []
        for oc,ic,kernel,maximum,start,end in metadata:
            group = (maximum<<40)|(sum(partials[start:end])&((1<<38)-1))
            groups.append(group)
            accumulators[kernel] = add(group, accumulators[kernel], ic != 0)
            if ic == 32:
                bits = final(accumulators[kernel])
                value, = struct.unpack('<f', struct.pack('<I', bits))
                try:
                    half, = struct.unpack('<H', struct.pack('<e', value))
                    if half&0x7fff == 0x7c00:
                        half = (half&0x8000)|0x7bff
                except OverflowError:
                    half = ((bits>>16)&0x8000)|0x7bff
                require(half&0x7c00 != 0x7c00, 'First projection expectation is nonfinite')
                writes.append(((0x10040000+(oc//16)*64+kernel*2)<<16)|half)
                fp32.append(bits)
        require(len(reads) == 2176 and len(writes) == 32 and len(groups) == 64, 'Incomplete projection corpus')
        for name, values, width in [('commands.hex', words, 16), ('input.hex', inputs, 4), ('weight.hex', weights, 4),
                                    ('reads.hex', reads, 12), ('writes.hex', writes, 12), ('groups.hex', groups, 11), ('fp32.hex', fp32, 8)]:
            artifact('fixture/'+name, ''.join(f'{v:0{width}x}\n' for v in values).encode())
        artifact('reference_input_fp32.bin', normalized_bytes)
        artifact('reference_probe.c', probe.read_bytes())
        artifact('donor_helper.cpp', args.booth_helper.read_bytes())
        artifact('source/first_projection.py', Path(__file__).read_bytes())
        require(verify_backend(args.backend)['commit'] == backend['commit'], 'Backend changed during emission')
        verify(package)
        report.update(status='PREPARED_FIRST_TINYSTORIES_RAW_PROJECTION_AND_COMPACTION_COMMANDS',
            model_input=dict(token_id=1, layer=0, operator='wq', selected_outputs=[0,32], input_precision='FP32 RMSNorm then binary16 RNE'),
            fixture=dict(rows=1, ai=64, ao=32, frames=4, reads=2176, writes=32, commands_sha256=hashlib.sha256(struct.pack('<49Q',*words)).hexdigest()),
            cmac_descriptor=descriptor, compaction_descriptors=ew.submissions[0],
            successful_cmac_reset_callbacks_recorded=1, live_reset_protocol_implemented=False,
            backend_final_writer_unchanged=True, tensor_framework_integration_performed=False,
            expected_fp16=[f'{v&65535:04x}' for v in writes],
            scope='Actual trained BOS first-query data, original emitters/final writer, donor arithmetic TEST expectations; native RTL, mixed-engine memory/rearm and physical execution remain separate gates')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        save()
    print(json.dumps(dict(status=report['status'], fixture=report['fixture'], report=str(out/'report.json'))))


if __name__ == '__main__':
    main()
