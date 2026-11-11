#!/usr/bin/env python3
"""Capture real RK3588 Rocket MAX on raw FP16 special values; no numpy."""
import ctypes, hashlib, json, os, struct, sys
os.environ['EW_OP'] = 'MAX'
sys.path.insert(0, '/home/opencode-agent')
import rk3588_rocket_max as R

A_BITS = [0x3c00, 0xbc00, 0x0000, 0x8000, 0x7c00, 0xfc00, 0x7e00, 0x7bff]
B_BITS = [0x4000, 0xc000, 0x8000, 0x0000, 0xfc00, 0x7c00, 0x3c00, 0x7e00]
N = 8
TARGET_DPU, TARGET_RDMA, TARGET_PC = 0x1001, 0x2001, 0x0081
fd, path = R.open_dev()
regcmd_map, regcmd_bo = R.alloc(fd, 4096)
a_map, a_bo = R.alloc(fd, 4096)
b_map, b_bo = R.alloc(fd, 4096)
o_map, o_bo = R.alloc(fd, 4096)
width = (N + 7) // 8 - 1
regs = [
    (TARGET_DPU << 48) | (0x0000000e << 16) | 0x4004,
    (TARGET_DPU << 48) | (0x000001e5 << 16) | 0x400c,
    (TARGET_DPU << 48) | (0x48000002 << 16) | 0x4010,
    (TARGET_DPU << 48) | (width << 16) | 0x4030,
    (TARGET_DPU << 48) | (0x00070007 << 16) | 0x403c,
    (TARGET_DPU << 48) | (R.CFG << 16) | 0x4070,
    (TARGET_DPU << 48) | (0x00010001 << 16) | 0x4084,
    (TARGET_RDMA << 48) | (0x0000000e << 16) | 0x5004,
    (TARGET_RDMA << 48) | (width << 16) | 0x500c,
    (TARGET_RDMA << 48) | (0 << 16) | 0x5010,
    (TARGET_RDMA << 48) | (7 << 16) | 0x5014,
    (TARGET_RDMA << 48) | (0x40000008 << 16) | 0x5034,
    (TARGET_DPU << 48) | ((o_bo.dma_address & 0xffffffff) << 16) | 0x4020,
    (TARGET_RDMA << 48) | ((a_bo.dma_address & 0xffffffff) << 16) | 0x5018,
    (TARGET_RDMA << 48) | ((b_bo.dma_address & 0xffffffff) << 16) | 0x5038,
    (TARGET_RDMA << 48) | (0x00017849 << 16) | 0x5044,
    (TARGET_PC << 48) | (0x00000018 << 16) | 0x0008,
]
ctypes.memset(ctypes.addressof(ctypes.c_char.from_buffer(regcmd_map)), 0, 4096)
q = (ctypes.c_uint64 * len(regs)).from_buffer(regcmd_map)
q[:] = regs
ai = (ctypes.c_uint16 * N).from_buffer(a_map); ai[:] = A_BITS
bi = (ctypes.c_uint16 * N).from_buffer(b_map); bi[:] = B_BITS
oi = (ctypes.c_uint16 * N).from_buffer(o_map); oi[:] = [0] * N
for bo in (regcmd_bo, a_bo, b_bo, o_bo): R.prep(fd, bo)
for bo in (regcmd_bo, a_bo, b_bo, o_bo): R.fini(fd, bo)
ret = R.submit(fd, regcmd_bo, len(regs), (regcmd_bo, a_bo, b_bo), (o_bo,))
print('SUBMIT_RET', ret)
R.prep(fd, o_bo)
out = [oi[i] for i in range(N)]
raw = bytes(o_map[:4096])
print('A_BITS', ' '.join(f'{x:04x}' for x in A_BITS))
print('B_BITS', ' '.join(f'{x:04x}' for x in B_BITS))
print('OUT_BITS', ' '.join(f'{x:04x}' for x in out))
d = '/home/opencode-agent/rk3588-ew-capture/max-special'
os.makedirs(d, exist_ok=True)
open(d + '/input-a.fp16', 'wb').write(struct.pack('<8H', *A_BITS))
open(d + '/input-b.fp16', 'wb').write(struct.pack('<8H', *B_BITS))
open(d + '/output-raw.fp16', 'wb').write(struct.pack('<8H', *out))
open(d + '/output-full-bo.bin', 'wb').write(raw)
open(d + '/commands.bin', 'wb').write(b''.join(x.to_bytes(8, 'little') for x in regs))
meta = {'device': path, 'op': 'MAX', 'ew_cfg': R.CFG, 'n': N,
        'a_bits': A_BITS, 'b_bits': B_BITS, 'out_bits': out, 'submit_ret': ret,
        'commands_sha256': hashlib.sha256(b''.join(x.to_bytes(8, 'little') for x in regs)).hexdigest(),
        'output_full_sha256': hashlib.sha256(raw).hexdigest(),
        'scope': 'real RK3588 Rocket DPU EW MAX special values; not a silicon specification'}
open(d + '/capture.json', 'w').write(json.dumps(meta, indent=2, sort_keys=True) + '\n')
print('CAPTURE_DIR', d)
