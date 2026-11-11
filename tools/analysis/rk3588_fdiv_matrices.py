#!/usr/bin/env python3
"""Capture real RK3588 Rocket FP16 FDIV matrices (special + finite sweep).

Capture-only. Mirrors /home/opencode-agent/rk3588_rocket_fdiv.py: same
register list, same 4096-byte BO allocation and prep/fini/submit flow.
"""
import ctypes
import hashlib
import json
import os
import platform
import struct
import sys
import time

sys.path.insert(0, '/home/opencode-agent')
import rk3588_rocket_max as R

CFG = 0x108303c0
OUT_CONVERT = 1
RDMA_MODE = 0x00017841
TARGET_DPU, TARGET_RDMA, TARGET_PC = 0x1001, 0x2001, 0x0081

# Task 1: exact requested order, 24 lanes.
SPECIAL_A = [
    0x3c00, 0xbc00, 0x0000, 0x8000,
    0x7c00, 0xfc00, 0x7c00, 0x3c00,
    0xbc00, 0x7c00, 0x0000, 0x7e00,
    0x3c00, 0x3c00, 0x4000, 0x3c00,
    0x7bff, 0x0001, 0x0400, 0x7bff,
    0x7bff, 0x3c00, 0x0001, 0x8001,
]
SPECIAL_B = [
    0x0000, 0x0000, 0x0000, 0x0000,
    0x7c00, 0x7c00, 0x3c00, 0x7c00,
    0x7c00, 0x0000, 0x7c00, 0x3c00,
    0x7e00, 0x4200, 0x4200, 0x4900,
    0x4200, 0x4000, 0x4000, 0x3c00,
    0x0400, 0x0001, 0x7bff, 0x4000,
]

# Task 2: 32 lanes, finite inputs only, rounding/subnormal focused.
SWEEP_A = [
    0x3c00, 0x4000, 0x3c00, 0x4900,  # 1/3, 2/3, 1/10, 10/1
    0x7bff, 0x4200, 0x0001, 0x0400,  # max/3, 3/max, sMin/2, minNorm/3
    0x3c01, 0x7bff, 0x0001, 0x0003,  # 0x3c01/0x4001, max/max, sMin/sMin, 1.5ulp tie
    0x0005, 0x0400, 0x0401, 0x7bff,  # 2.5ulp tie, minNorm/2, (minNorm+1ulp)/2, max/2
    0x7bff, 0x4900, 0x4800, 0x4200,  # max/10, 10/3, 8/3, 3/8
    0x3c00, 0x4600, 0x3c00, 0x3c01,  # 1/7, 7/3, 1/0x3c01, 0x3c01/1
    0x4001, 0x3c00, 0x3555, 0x3c00,  # 0x4001/3, 1/0x4201, 0x3555/1, 1/0x3555
    0x8001, 0x8001, 0x8003, 0xbc00,  # -sMin/2, -sMin/3, -1.5ulp tie, -1/2
]
SWEEP_B = [
    0x4200, 0x4200, 0x4900, 0x3c00,
    0x4200, 0x7bff, 0x4000, 0x4200,
    0x4001, 0x7bff, 0x0001, 0x4000,
    0x4000, 0x4000, 0x4000, 0x4000,
    0x4900, 0x4200, 0x4200, 0x4800,
    0x4600, 0x4200, 0x3c01, 0x3c00,
    0x4200, 0x4201, 0x3c00, 0x3555,
    0x4000, 0x4200, 0x4000, 0x4000,
]

assert len(SPECIAL_A) == len(SPECIAL_B) == 24
assert len(SWEEP_A) == len(SWEEP_B) == 32
assert all((x & 0x7c00) != 0x7c00 for x in SWEEP_A + SWEEP_B), 'sweep input not finite'


def build_regs(width, out_bo, a_bo, b_bo):
    return [
        (TARGET_DPU << 48) | (0x0000000e << 16) | 0x4004,
        (TARGET_DPU << 48) | (0x000001e5 << 16) | 0x400c,
        (TARGET_DPU << 48) | (0x48000002 << 16) | 0x4010,
        (TARGET_DPU << 48) | (width << 16) | 0x4030,
        (TARGET_DPU << 48) | (0x00070007 << 16) | 0x403c,
        (TARGET_DPU << 48) | (CFG << 16) | 0x4070,
        (TARGET_DPU << 48) | (OUT_CONVERT << 16) | 0x4084,
        (TARGET_RDMA << 48) | (0x0000000e << 16) | 0x5004,
        (TARGET_RDMA << 48) | (width << 16) | 0x500c,
        (TARGET_RDMA << 48) | (0 << 16) | 0x5010,
        (TARGET_RDMA << 48) | (7 << 16) | 0x5014,
        (TARGET_RDMA << 48) | (0x40000008 << 16) | 0x5034,
        (TARGET_DPU << 48) | ((out_bo.dma_address & 0xffffffff) << 16) | 0x4020,
        (TARGET_RDMA << 48) | ((a_bo.dma_address & 0xffffffff) << 16) | 0x5018,
        (TARGET_RDMA << 48) | ((b_bo.dma_address & 0xffffffff) << 16) | 0x5038,
        (TARGET_RDMA << 48) | (RDMA_MODE << 16) | 0x5044,
        (TARGET_PC << 48) | (0x00000018 << 16) | 0x0008,
    ]


def run_capture(name, a_bits, b_bits, scope):
    lanes = len(a_bits)
    width = (lanes + 7) // 8 - 1
    fd, path = R.open_dev()
    print('DEVICE', path)
    print('LANES', lanes, 'WIDTH', width)
    regcmd_map, regcmd_bo = R.alloc(fd, 4096)
    a_map, a_bo = R.alloc(fd, 4096)
    b_map, b_bo = R.alloc(fd, 4096)
    o_map, o_bo = R.alloc(fd, 4096)
    regs = build_regs(width, o_bo, a_bo, b_bo)

    ctypes.memset(ctypes.addressof(ctypes.c_char.from_buffer(regcmd_map)), 0, 4096)
    q = (ctypes.c_uint64 * len(regs)).from_buffer(regcmd_map)
    q[:] = regs
    ai = (ctypes.c_uint16 * lanes).from_buffer(a_map)
    ai[:] = a_bits
    bi = (ctypes.c_uint16 * lanes).from_buffer(b_map)
    bi[:] = b_bits
    oi = (ctypes.c_uint16 * lanes).from_buffer(o_map)
    oi[:] = [0] * lanes

    ret = None
    for attempt in range(6):
        for bo in (regcmd_bo, a_bo, b_bo, o_bo):
            R.prep(fd, bo)
        for bo in (regcmd_bo, a_bo, b_bo, o_bo):
            R.fini(fd, bo)
        ret = R.submit(fd, regcmd_bo, len(regs), (regcmd_bo, a_bo, b_bo), (o_bo,))
        print('SUBMIT_RET', ret, 'attempt', attempt + 1)
        if ret == 0:
            break
        time.sleep(0.5)
    if ret != 0:
        sys.exit('submit failed (no capture written): ret=%r' % (ret,))

    R.prep(fd, o_bo)
    out = [oi[i] for i in range(lanes)]
    raw = bytes(o_map[:4096])
    cmdb = b''.join(x.to_bytes(8, 'little') for x in regs)
    cmd_sha = hashlib.sha256(cmdb).hexdigest()
    full_sha = hashlib.sha256(raw).hexdigest()

    print('A_BITS', ' '.join(f'{x:04x}' for x in a_bits))
    print('B_BITS', ' '.join(f'{x:04x}' for x in b_bits))
    print('OUT_BITS', ' '.join(f'{x:04x}' for x in out))
    print('OUT_PAIRS', ' '.join(f'{a:04x}/{b:04x}=>{o:04x}'
                                for a, b, o in zip(a_bits, b_bits, out)))
    print('COMMANDS_SHA256', cmd_sha)
    print('OUTPUT_FULL_SHA256', full_sha)

    d = '/home/opencode-agent/rk3588-ew-capture/' + name
    os.makedirs(d, exist_ok=True)
    open(d + '/input-a.fp16', 'wb').write(struct.pack('<%dH' % lanes, *a_bits))
    open(d + '/input-b.fp16', 'wb').write(struct.pack('<%dH' % lanes, *b_bits))
    open(d + '/output-raw.fp16', 'wb').write(struct.pack('<%dH' % lanes, *out))
    open(d + '/output-full-bo.bin', 'wb').write(raw)
    open(d + '/commands.bin', 'wb').write(cmdb)
    meta = {
        'op': 'FDIV',
        'ew_cfg': CFG,
        'out_convert': OUT_CONVERT,
        'rdma_mode': RDMA_MODE,
        'lanes': lanes,
        'width_0x4030_0x500c': width,
        'a_bits': a_bits,
        'b_bits': b_bits,
        'out_bits': out,
        'submit_ret': ret,
        'device': path,
        'device_node': '/dev/accel/accel0',
        'commands_sha256': cmd_sha,
        'output_full_sha256': full_sha,
        'dma': {'regcmd': regcmd_bo.dma_address, 'a': a_bo.dma_address,
                'b': b_bo.dma_address, 'out': o_bo.dma_address},
        'bo_size_bytes': 4096,
        'python_version': platform.python_version(),
        'platform': platform.platform(),
        'scope': scope,
    }
    open(d + '/capture.json', 'w').write(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    print('CAPTURE_DIR', d)
    return out


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('special', 'sweep'):
        sys.exit('usage: %s special|sweep' % sys.argv[0])
    if sys.argv[1] == 'special':
        run_capture(
            'fdiv-special', SPECIAL_A, SPECIAL_B,
            'real RK3588 Rocket DPU EW FDIV 24-lane special-value capture on '
            '/dev/accel/accel0; not a silicon specification')
    else:
        run_capture(
            'fdiv-finite-sweep', SWEEP_A, SWEEP_B,
            'real RK3588 Rocket DPU EW FDIV 32-lane finite/rounding sweep on '
            '/dev/accel/accel0; not a silicon specification')


if __name__ == '__main__':
    main()
