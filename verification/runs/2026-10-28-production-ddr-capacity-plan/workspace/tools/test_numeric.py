#!/usr/bin/env python3
"""Check integer datapath design against an independently implemented oracle."""
import ctypes
import json
from pathlib import Path
import random
import sys
import time
from evidence import source_revision, timestamp
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.half import alu

library = ctypes.CDLL(str(ROOT / 'build/half_datapath.so'))
f = library.rk_half_alu
f.argtypes = (ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint)
f.restype = ctypes.c_uint16
rng = random.Random(0x3588)
start = time.monotonic()
revision = source_revision()
started_utc = timestamp()
count = 0
special = (0, 0x8000, 1, 0x8001, 0x03ff, 0x0400, 0x0401,
           0x3bff, 0x3c00, 0x3c01, 0x7bff, 0xfbff, 0x7c00, 0xfc00,
           0x7d00, 0x7e00, 0xfeff)
def check(a, b, op_id, name):
    global count
    got = f(a, b, op_id)
    expected = alu(a, b, name)
    if got != expected:
        raise AssertionError(f'{name}: {a:04x} {b:04x}: C++={got:04x} Python={expected:04x}')
    count += 1
for op_id, name in enumerate(('ADD', 'SUB', 'MUL')):
    for a in special:
        for b in special:
            check(a, b, op_id, name)
    # Every input encoding against zero, one, minimum subnormal, and max finite.
    for a in range(65536):
        for b in (0, 0x3c00, 1, 0x7bff):
            check(a, b, op_id, name)
    for _ in range(100000):
        check(rng.randrange(65536), rng.randrange(65536), op_id, name)
report = {'test': 'integer_datapath_vs_independent_python_binary16_oracle',
          'cases': count, 'status': 'PASS', 'seed': '0x3588',
          'source_revision': revision, 'started_utc': started_utc, 'finished_utc': timestamp(),
          'seconds': round(time.monotonic() - start, 3),
          'scope': 'C++ arithmetic model only; NOT RTL simulation or RK hardware validation'}
if source_revision()['sha256'] != revision['sha256']:
    raise RuntimeError('Sources changed during the numeric run; rerun before accepting results')
(ROOT / 'build/numeric_report.json').write_text(json.dumps(report, indent=2) + '\n')
print(f"PASS C++ numeric model: {count:,} comparisons, seed=0x3588, {report['seconds']} seconds")
