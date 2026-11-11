#!/usr/bin/env python3
"""Capture real RK3588 Rocket FP16 special-value results for ADD/SUB/MUL/MAX."""
import ctypes, hashlib, json, os, struct, sys
os.environ['EW_OP'] = 'MAX'
sys.path.insert(0, '/home/opencode-agent')
import rk3588_rocket_max as R

CFG = {'ADD': 0x108202c0, 'SUB': 0x108402c0, 'MUL': 0x108003c4, 'MAX': 0x108002c0}
PAIRS = [
    (0x7e00, 0x3c00), (0x3c00, 0x7e00),
    (0x7c01, 0x3c00), (0x3c00, 0x7c01),
    (0x7e00, 0x7e00), (0x7c00, 0xfc00), (0xfc00, 0x7c00),
    (0x0000, 0x8000), (0x8000, 0x0000),
    (0x7bff, 0x7bff), (0x7e00, 0x7c00), (0x7c00, 0x7e00),
    (0x7d00, 0x3c00), (0x3c00, 0x7d00),
]
N = len(PAIRS)
TARGET_DPU, TARGET_RDMA, TARGET_PC = 0x1001, 0x2001, 0x0081
fd, path = R.open_dev()
regcmd_map, regcmd_bo = R.alloc(fd, 4096)
a_map, a_bo = R.alloc(fd, 4096)
b_map, b_bo = R.alloc(fd, 4096)
o_map, o_bo = R.alloc(fd, 4096)
width = (N + 7) // 8 - 1
ai = (ctypes.c_uint16 * N).from_buffer(a_map)
bi = (ctypes.c_uint16 * N).from_buffer(b_map)
oi = (ctypes.c_uint16 * N).from_buffer(o_map)
results = {}
for op, cfg in CFG.items():
    ai[:] = [a for a, _ in PAIRS]
    bi[:] = [b for _, b in PAIRS]
    oi[:] = [0] * N
    regs = [
        (TARGET_DPU << 48) | (0x0000000e << 16) | 0x4004,
        (TARGET_DPU << 48) | (0x000001e5 << 16) | 0x400c,
        (TARGET_DPU << 48) | (0x48000002 << 16) | 0x4010,
        (TARGET_DPU << 48) | (width << 16) | 0x4030,
        (TARGET_DPU << 48) | (0x00070007 << 16) | 0x403c,
        (TARGET_DPU << 48) | (cfg << 16) | 0x4070,
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
    for bo in (regcmd_bo, a_bo, b_bo, o_bo): R.prep(fd, bo)
    for bo in (regcmd_bo, a_bo, b_bo, o_bo): R.fini(fd, bo)
    ret = R.submit(fd, regcmd_bo, len(regs), (regcmd_bo, a_bo, b_bo), (o_bo,))
    R.prep(fd, o_bo)
    out = [oi[i] for i in range(N)]
    results[op] = {'out_bits': out, 'submit_ret': ret,
                   'commands_sha256': hashlib.sha256(b''.join(x.to_bytes(8, 'little') for x in regs)).hexdigest()}
    print(op, ' '.join(f'{x:04x}' for x in out))
summary = {'device': path, 'pairs': PAIRS, 'cfg': CFG, 'results': results,
           'scope': 'real RK3588 Rocket DPU EW special-value matrix; not a silicon specification'}
d = '/home/opencode-agent/rk3588-ew-capture/special-matrix'
os.makedirs(d, exist_ok=True)
open(d + '/capture.json', 'w').write(json.dumps(summary, indent=2, sort_keys=True) + '\n')
print('CAPTURE_DIR', d)
