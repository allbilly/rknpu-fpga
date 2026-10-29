#!/usr/bin/env python3
"""Raw final commands + synthetic raw-lane memory/scoreboard, not RK goldens."""
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from evidence import ROOT,fingerprint,source_revision,timestamp
OUT=ROOT/'build/cmac_vectors'
OUT.mkdir(exist_ok=True)
fixture=ROOT/'tests/backend_cmac_captures.json'
audit=json.loads(fixture.read_text())
assert audit['schema']==1 and audit['command_words_rewritten'] is False
revision=source_revision()
files=[];cases=[]
for number,case in enumerate(audit['cases']):
    name=case['name'];directory=OUT/name;directory.mkdir(exist_ok=True)
    raw=bytes.fromhex(case['commands_le_hex'])
    assert hashlib.sha256(raw).hexdigest()==case['commands_sha256']
    words=struct.unpack('<49Q',raw)
    m,_,_=case['encoded_stage_shape'];ai,ao,_=case['physical_layout']
    a,b,d=0x10010000,0x10020000,0x10040000
    # Unique physical halfword labels per buffer for these bounded cases. They
    # are opaque 16-bit data, deliberately not interpreted as numeric FP16.
    inputs=[(i*797+number*61+0x1247)&65535 for i in range(m*ai)]
    logical_weights=[(i*193+number*67+0x8359)&65535 for i in range(ao*ai)]
    packed_weights=[]
    # Explicit nested pack order, independent of the RTL's incremental walk.
    for ob in range(ao//16):
        for ib in range(ai//32):
            for ol in range(16):
                for il in range(32):packed_weights.append(logical_weights[(ob*16+ol)*ai+ib*32+il])
    for filename,values,width in [('commands.hex',words,16),('input.hex',inputs,4),('weight.hex',packed_weights,4)]:
        path=directory/filename;path.write_text(''.join(f'{x:0{width}x}\n' for x in values));files.append(path)
    path=directory/'expected.txt'
    with path.open('w') as out:
        for row in range(m):
            for oc in range(ao):
                for ic in range(ai):
                    addr_a=a+2*(row*ai+ic)
                    addr_b=b+2*((oc//16)*(ai//32)*512+(ic//32)*512+(oc%16)*32+ic%32)
                    addr_d=d+2*(row*ao*2+oc+(oc//16)*16)
                    flags=(int(ic==0)<<2)|(int(ic==ai-1)<<1)|int(row==m-1 and oc==ao-1)
                    out.write(f'{addr_a:08x} {addr_b:08x} {addr_d:08x} {row:08x} {oc:08x} {ic:08x} '
                              f'{inputs[row*ai+ic]:04x} {logical_weights[oc*ai+ic]:04x} {flags:x}\n')
    files.append(path)
    path=directory/'products.hex'
    # Numerical reference only: no runtime execution or host layout fallback.
    with path.open('w') as out:
        for row in range(m):
            for oc in range(ao):
                for ic in range(ai):
                    x=struct.unpack('<e',struct.pack('<H',inputs[row*ai+ic]))[0]
                    y=struct.unpack('<e',struct.pack('<H',logical_weights[oc*ai+ic]))[0]
                    z=x*y
                    result=0x7fc00000 if math.isnan(z) else struct.unpack('<I',struct.pack('<f',z))[0]
                    if math.isfinite(z):assert struct.unpack('<f',struct.pack('<I',result))[0]==z
                    out.write(f'{result:08x}\n')
    files.append(path)
    cases.append(dict(name=name,rows=m,ai=ai,ao=ao,pairs=m*ai*ao,commands_sha256=hashlib.sha256(raw).hexdigest()))
report=dict(status='GENERATED_RAW_COMMAND_AND_SYNTHETIC_OPERANDS',recorded_utc=timestamp(),
            source_revision=revision,backend_commit=audit['backend_commit'],seed='0x3588ca03',
            scope='Seven unchanged compiled/final-writer command images; synthetic physical operand BOs and address/lane and exact-product reference only. No runtime CPU gather, RK output capture or accumulated GEMM.',
            cases=cases,total_pairs=sum(c['pairs'] for c in cases),artifacts=fingerprint(files),
            generator=fingerprint([Path(__file__).resolve(),fixture]))
(OUT/'vectors_report.json').write_text(json.dumps(report,indent=2)+'\n')
assert source_revision()==revision
print(f'Generated {len(cases)} unchanged command streams, {report["total_pairs"]} reference operand pairs')
