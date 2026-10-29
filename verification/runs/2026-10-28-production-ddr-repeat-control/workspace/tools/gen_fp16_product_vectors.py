#!/usr/bin/env python3
"""Independent Python binary64/struct oracle; synthetic, not RK goldens."""
import json
import math
from pathlib import Path
import random
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evidence import ROOT,fingerprint,source_revision,timestamp
OUT=ROOT/'build/fp16_product_vectors';OUT.mkdir(exist_ok=True)
revision=source_revision();vectors=[];counts={'finite_nonzero':0,'zero':0,'infinity':0,'nan':0}
def half(bits):return struct.unpack('<e',struct.pack('<H',bits))[0]
def add(a,b):
    z=half(a)*half(b)
    if math.isnan(z):bits=0x7fc00000;category='nan'
    else:
        packed=struct.pack('<f',z);bits=struct.unpack('<I',packed)[0]
        if math.isfinite(z):
            assert struct.unpack('<f',packed)[0]==z # No finite precision loss.
            if z==0:
                assert bits==((a^b)&0x8000)<<16
                category='zero'
            else:
                assert 0<(bits>>23)&255<255 # All nonzero finite products are FP32 normal.
                category='finite_nonzero'
        else:category='infinity'
    counts[category]+=1;vectors.append((a<<48)|(b<<32)|bits)
for bits in range(65536):
    add(bits,0x3555);add(bits,0x03ff)
for bits in range(65536):add((bits*109+137)&65535,bits)
special=(0,0x8000,1,0x8001,2,0x8002,0x03ff,0x83ff,0x0400,0x8400,0x07ff,
         0x3bff,0x3c00,0x3c01,0x3e00,0xbc00,0x7bfe,0x7bff,0xfbff,0x7c00,
         0xfc00,0x7c01,0xfc01,0x7dff,0xfdff,0x7e00,0xfe00,0x7fff,0xffff,0x3555,0xb555,0x0401)
for a in special:
    for b in special:add(a,b)
rng=random.Random(0x3588ca04)
for _ in range(32768):add(rng.randrange(65536),rng.randrange(65536))
assert len(vectors)==230400
path=OUT/'vectors.hex';path.write_text(''.join(f'{v:016x}\n' for v in vectors))
donors={
 '/home/fedora/vortex/hw/rtl/tcu/tfr/VX_tcu_tfr_mul_f16.sv':'41c58778019b44355e533a19c7283326f74b74fef2f70bdecce386057b1d82ea',
 '/home/fedora/vortex/hw/rtl/tcu/fpnew/VX_tcu_fpnew_mulfp32.sv':'2e52b11376528f80ceecf099540fa88352f48c76800d78debbf9340a80f46d2d'}

report=dict(status='GENERATED_INDEPENDENT_PRODUCT_REFERENCE',recorded_utc=timestamp(),source_revision=revision,
            count=len(vectors),seed='0x3588ca04',categories=counts,
            coverage='All 65536 encodings as A against two partners; all encodings as B against a bijection; 32x32 boundary/special pairs; 32768 seeded random pairs. Not exhaustive over all 2^32 operand pairs.',
            oracle='Python binary64 multiplication of struct-decoded half, then struct.pack float32; all finite products explicitly checked exact.',
            numerical_policy='Exact finite FP16-to-FP32 product, gradual half subnormals, signed zero, signed infinity, positive canonical quiet NaN including zero*infinity. Candidate RK behavior, not silicon goldens or accumulation order.',
            inspected_reference_sources=donors,donor_code_imported=False,
            artifacts=fingerprint([path,Path(__file__).resolve()]))
assert source_revision()==revision
(OUT/'vectors_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(count=len(vectors),categories=counts),indent=2))
