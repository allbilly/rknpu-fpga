#!/usr/bin/env python3
"""Regroup the existing physical-pair oracle into C32/K16 input frames."""
import hashlib
import json
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
source=ROOT/'build/cmac_vectors'
manifest=source/'vectors_report.json'
vr=json.loads(manifest.read_text())
for group in ('artifacts','generator'):
    for name,sha in vr[group]['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
out=ROOT/'build/rknpu-array-front'
out.mkdir(exist_ok=False)
cases=[];sources=[Path(__file__).resolve(),manifest];artifacts=[]
for case in vr['cases']:
    base=source/case['name'];m,ai,ao=case['rows'],case['ai'],case['ao']
    words=[int(line,16) for line in (base/'commands.hex').read_text().splitlines()]
    assert len(words)==49 and hashlib.sha256(struct.pack('<49Q',*words)).hexdigest()==case['commands_sha256']
    pairs={}
    for line in (base/'expected.txt').read_text().splitlines():
        a,b,d,row,oc,ic,x,w,flags=map(lambda s:int(s,16),line.split())
        assert (row,oc,ic) not in pairs
        pairs[row,oc,ic]=(a,b,d,x,w,flags)
    assert len(pairs)==m*ai*ao
    rows=[]
    for row in range(m):
        for oc in range(0,ao,16):
            for ic in range(0,ai,32):
                data=weights=0
                address=pairs[row,oc,ic][2]
                for lane in range(32):
                    a,_,_,x,_,_=pairs[row,oc,ic+lane]
                    assert a==0x10010000+2*(row*ai+ic+lane)
                    data|=x<<(lane*16)
                    for kernel in range(16):
                        a,b,d,xx,w,_=pairs[row,oc+kernel,ic+lane]
                        assert xx==x and a==0x10010000+2*(row*ai+ic+lane)
                        assert b==0x10020000+oc*ai*2+ic*32+kernel*64+lane*2
                        assert d==address+kernel*2
                        weights|=w<<((kernel*32+lane)*16)
                assert address==0x10040000+row*ao*4+(oc//16)*64
                flags=(int(ic==0)<<2)|(int(ic==ai-32)<<1)|int(row==m-1 and oc==ao-16)
                metadata=(address<<99)|(row<<67)|(oc<<35)|(ic<<3)|flags
                rows.append((data<<(8192+131))|(weights<<131)|metadata)
    dest=out/case['name'];dest.mkdir()
    path=dest/'frames.hex'
    path.write_text(''.join(f'{r:02209x}\n' for r in rows))
    sources += [base/n for n in ('commands.hex','expected.txt','input.hex','weight.hex')]
    artifacts.append(path)
    cases.append(dict(**case,frames=len(rows),reads=len(rows)*544))
report=dict(status='GENERATED_ARRAY_FRONT_REFERENCE_ONLY',created_utc=timestamp(),cases=cases,
            source=fingerprint(sources),artifacts=fingerprint(artifacts),
            scope='Test-only regrouping of unchanged raw command/physical-pair fixtures. No runtime layout fixup or arithmetic oracle.')
(out/'vectors_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(f'Generated {len(cases)} cases, {sum(c["frames"] for c in cases)} C32/K16 frames, {sum(c["reads"] for c in cases)} reads')
