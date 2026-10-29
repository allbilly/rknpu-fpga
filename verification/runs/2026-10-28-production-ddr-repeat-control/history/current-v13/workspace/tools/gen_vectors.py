#!/usr/bin/env python3
"""Generate synthetic RTL stimuli. These are NOT captured RK3588 goldens."""
import json
from pathlib import Path
import random
import struct
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.profile import REGISTERS, encode, make_commands
from model.sim import Memory, RKEmulator
from model.half import alu
from tools.ew_initialization import initialization_words, initialized_commands
OUT = ROOT / 'build/vectors'
OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(0x3588)
BASE = 0x10000000
A, B, D = BASE + 0x1000, BASE + 0x20000, BASE + 0x40000
cases = []

def case(name, raw, regions, expected_error=0, done=1, bus_error_at=0, drop=0,
         stall_request=0, completed_writes=0):
    path = OUT / name
    path.mkdir(exist_ok=True)
    words = [v for (v,) in struct.iter_unpack('<Q', raw)]
    (path/'commands.hex').write_text(''.join(f'{w:016x}\n' for w in words))
    before = {addr: bytes(data) for addr, data in regions.items()}
    def memhex(mapping):
        return ''.join(f'@{(addr-BASE)//2:x}\n' + ''.join(f'{v:04x}\n' for (v,) in struct.iter_unpack('<H', data))
                       for addr, data in sorted(mapping.items()))
    (path/'input.hex').write_text(memhex(before))
    mem = Memory()
    for addr, data in before.items(): mem.map(addr, data)
    emulator = RKEmulator(mem)
    if not expected_error or completed_writes:
        emulator.submit(raw)
    after = mem.regions if not expected_error else dict(before)
    if completed_writes:
        # These faults use non-aliased ADD into D. Earlier acknowledged writes
        # remain visible after the injected error; no rollback is promised.
        after[D] = bytes(mem.regions[D][:2*completed_writes]) + before[D][2*completed_writes:]
    (path/'check.txt').write_text(''.join(f'{addr+2*i:08x} {v:04x}\n'
        for addr, data in sorted(after.items()) for i, (v,) in enumerate(struct.iter_unpack('<H', data))))
    cases.append({'name': name, 'ncmd': len(words), 'error': expected_error, 'done': done,
                  'checks': sum(len(data)//2 for data in after.values()),
                  'bus_error_at': bus_error_at, 'drop': drop, 'stall_request': stall_request,
                  'transactions': (bus_error_at or int(bool(drop))) if expected_error else emulator.memory_transactions})

def blobs(n):
    p = (n+7)//8*8
    a = [rng.randrange(65536) for _ in range(n)] + [0]*(p-n)
    b = [rng.randrange(65536) for _ in range(n)] + [0]*(p-n)
    return {A: struct.pack('<'+'H'*(p+8), *a, *([0x5aa5]*8)),
            B: struct.pack('<'+'H'*(p+8), *b, *([0x5aa5]*8)),
            D: struct.pack('<'+'H'*(p+8), *([0xdead]*p), *([0x5aa5]*8))}

def mutate(raw, name, v):
    w = [x for (x,) in struct.iter_unpack('<Q', raw)]
    i = next(i for i, (_, _, n, _) in enumerate(REGISTERS) if n == name)
    t, a, *_ = REGISTERS[i]
    w[i] = encode(t, a, v)
    return struct.pack('<'+'Q'*len(w), *w)

for op in ('ADD','SUB','MUL'):
    for n in (1,7,8,9,33,257,1024):
        case(f'{op.lower()}_{n}', make_commands(op,n,A,B,D), blobs(n))
    case(f'{op.lower()}_inplace', make_commands(op,33,A,B,A), blobs(33))
case('two_tasks', make_commands('ADD',8,A,B,D)+make_commands('MUL',8,D,B,A), blobs(8), done=2)
raw = make_commands('ADD',32,A,B,D)
for name, field, v, ec in (
    ('bad_width','width',8000,2), ('mismatched_width','rdma_width',0,6),
    ('bad_fp32','data_format',0xa8000002,2), ('bad_max','ew_config',0x108002c0,2),
    ('bad_chain','next_address',0x10008000,7), ('bad_alignment','dst',D+2,4),
    ('bad_overlap','dst',A+16,4), ('bad_end','dst',0xfffffff0,4)):
    case(name, mutate(raw,field,v), blobs(32), expected_error=ec, done=0)
case('unknown_register', struct.pack('<Q',encode(0x1001,0x4074,0)), blobs(8),expected_error=1,done=0)
case('missing_register', raw[8:],blobs(32),expected_error=3,done=0)
case('read_bus_error',raw,blobs(32),expected_error=5,done=0,bus_error_at=1)
case('write_bus_error',raw,blobs(32),expected_error=5,done=0,bus_error_at=3)
case('timeout',raw,blobs(32),expected_error=8,done=0,drop=1)
case('request_timeout',raw,blobs(32),expected_error=8,done=0,stall_request=1)
case('late_read_bus_error',raw,blobs(32),expected_error=5,done=0,bus_error_at=4,completed_writes=1)
case('final_write_bus_error',make_commands('ADD',8,A,B,D),blobs(8),expected_error=5,
     done=0,bus_error_at=24,completed_writes=7)
for i, (_, _, field, fixed) in enumerate(REGISTERS):
    case(f'missing_{field}',raw[:8*i]+raw[8*(i+1):],blobs(32),expected_error=3,done=0)
    if fixed is not None:
        case(f'invalid_{field}',mutate(raw,field,fixed^1),blobs(32),
             expected_error=7 if field.startswith('next_') else 2,done=0)
# Keep the preceding 77 cases and subsequent ALU seed sequence unchanged.
saved_rng_state = rng.getstate()
for op in ('ADD', 'SUB', 'MUL'):
    for n in (7, 8, 9, 33):
        case(f'initialized_{op.lower()}_{n}', initialized_commands(op,n,A,B,D), blobs(n))
    case(f'initialized_{op.lower()}_inplace', initialized_commands(op,33,A,B,A), blobs(33))
init = initialization_words(33)
for i, word in enumerate(init):
    address, value = word & 0xffff, (word >> 16) & 0xffffffff
    case(f'init_missing_{address:04x}', initialized_commands('ADD',33,A,B,D,init[:i]+init[i+1:]),
         blobs(33),expected_error=3,done=0)
    for bit in (0, 31):
        bad = init.copy()
        bad[i] = encode(0x1001,address,value^(1<<bit))
        case(f'init_invalid_{address:04x}_bit{bit}',initialized_commands('ADD',33,A,B,D,bad),
             blobs(33),expected_error=6 if address==0x405c and bit==0 else 2,done=0)
for value in (8000, 0x2000, 0x10000):
    bad = init.copy()
    bad[6] = encode(0x1001,0x405c,value)
    case(f'init_invalid_width_{value:x}',initialized_commands('ADD',33,A,B,D,bad),blobs(33),expected_error=2,done=0)
case('initialized_then_legacy',initialized_commands('ADD',33,A,B,D)+make_commands('MUL',8,D,B,A),blobs(33),done=2)
case('legacy_then_initialized',make_commands('ADD',8,A,B,D)+initialized_commands('MUL',33,A,B,D),blobs(33),done=2)
case('initialized_twice',initialized_commands('ADD',33,A,B,D)+initialized_commands('MUL',9,D,B,A),blobs(33),done=2)
# A no-effect first task allows the harness to check all memory remains unchanged
# when a following partially reinitialized task fails. Completion is still real.
zero = blobs(33)
zero[A] = b'\0'*len(zero[A])
zero[B] = b'\0'*len(zero[B])
case('init_missing_after_completed',initialized_commands('ADD',8,A,B,A)+initialized_commands('ADD',33,A,B,D,init[1:]),
     zero,expected_error=3,done=1,bus_error_at=0)
# The preceding case performs 24 successful transactions before rejection.
cases[-1]['transactions'] = 24
invalid_bs = encode(0x1001,0x4040,0x52)
case('init_invalid_then_valid',initialized_commands('ADD',33,A,B,D,[invalid_bs]+init),blobs(33),expected_error=2,done=0)
case('init_width_last_write',initialized_commands('ADD',33,A,B,D,[encode(0x1001,0x405c,0)]+init),blobs(33))
rng.setstate(saved_rng_state)
(OUT/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')

special = (0,0x8000,1,0x8001,0x03ff,0x0400,0x3bff,0x3c00,0x3c01,0x7bff,0xfbff,0x7c00,0xfc00,0x7d00,0x7e00)
vectors=[]
for opid, op in enumerate(('ADD','SUB','MUL')):
    pairs = [(a,b) for a in special for b in special]
    pairs += [(rng.randrange(65536),rng.randrange(65536)) for _ in range(4096)]
    vectors += [(opid<<48)|(a<<32)|(b<<16)|alu(a,b,op) for a,b in pairs]
(OUT/'alu.hex').write_text(''.join(f'{x:016x}\n' for x in vectors))
(OUT/'alu_count.txt').write_text(str(len(vectors))+'\n')
print(f'Generated {len(cases)} RTL scenarios and {len(vectors)} ALU vectors (synthetic oracle).')
