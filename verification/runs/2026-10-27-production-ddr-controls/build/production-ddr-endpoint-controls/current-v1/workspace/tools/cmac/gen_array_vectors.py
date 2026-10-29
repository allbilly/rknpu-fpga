#!/usr/bin/env python3
"""Generate sized-CMAC unit vectors using NVIDIA's executed Booth helper.

This is not the upstream nvdla_utb/SystemC regression or an RK silicon oracle.
It changes the tested group size explicitly, retaining older C64 expectations.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--channels',type=int,choices=(8,32,64),default=32)
p.add_argument('--kernels',type=int,choices=(1,8,16,32),default=16)
a=p.parse_args();C,K=a.channels,a.kernels
out=ROOT/'build/rknpu-cmac-array'/f'c{C}k{K}';out.mkdir(parents=True,exist_ok=False)
helper=ROOT/'build/cmac_group_candidate/donor_booth_helper.cpp'
assert hashlib.sha256(helper.read_bytes()).hexdigest()=='f7c53e8e4d0d12db0c9d62e2c0b2fac3fe95458b3af85328b6f0b3bf9036d2f0'
binary=out/'donor_helper'
compile_command=['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',str(helper),'-o',str(binary)]
r=subprocess.run(compile_command,capture_output=True,text=True)
(out/'compile.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
seed=0x35883216;rng=random.Random(seed);cases=[]
edges=[0,0x8000,1,0x8001,0x3ff,0x400,0x3c00,0xbc00,0x7bff,0xfbff,0x7c00,0xfc00,0x7c01,0xfc01,0x7fff,0xfe00]
ones=(1<<C)-1
for x in edges:cases.append(('uniform_edges',[x]*C,[[edges[k%16]]*C for k in range(K)],ones,[ones]*K))
for i in range(C):
    data=[0]*C;data[i]=0x3c00
    cases.append(('one_channel',data,[[edges[k%16]]*C for k in range(K)],ones,[ones]*K))
for _ in range(64):
    data=[rng.randrange(65536) for _ in range(C)]
    weights=[[rng.randrange(65536) for _ in range(C)] for _ in range(K)]
    cases.append(('random_bits',data,weights,ones,[ones]*K))
    finite=lambda x:(x&0x83ff)|(rng.randrange(31)<<10)
    cases.append(('random_finite',list(map(finite,data)),[list(map(finite,w)) for w in weights],ones,[ones]*K))
for _ in range(32):
    data=[rng.choice(edges) for _ in range(C)]
    weights=[[rng.choice(edges) for _ in range(C)] for _ in range(K)]
    cases.append(('masked_edges',data,weights,rng.getrandbits(C),[rng.getrandbits(C) for _ in range(K)]))
def nan(x):return x&0x7c00==0x7c00 and x&1023!=0
def mant(x):
    e=(x>>10)&31
    return ((x&1023)|(1024 if e else 0))<<(e&3 if e else 1)
requests=[];meta=[]
for _,data,weights,dm,wm in cases:
    for k,w in enumerate(weights):
        active=[bool((dm>>i)&(wm[k]>>i)&1) and bool(data[i]&0x7fff) and bool(w[i]&0x7fff) for i in range(C)]
        exps=[((data[i]>>12)&7)+((w[i]>>12)&7) if active[i] else 0 for i in range(C)]
        maximum=max(exps);begin=len(requests)
        for i in range(C):
            if active[i]:requests.append(f'{(data[i]^w[i])>>15} {mant(w[i])} {mant(data[i])} {(maximum-exps[i])*4}\n')
        special=next((w[i] for i in range(C) if (wm[k]>>i)&1 and nan(w[i])),None)
        if special is None:special=next((data[i] for i in range(C) if (dm>>i)&1 and nan(data[i])),None)
        meta.append((maximum,begin,len(requests),special))
r=subprocess.run([binary],input=''.join(requests),capture_output=True,text=True);assert r.returncode==0,r.stderr
values=list(map(int,r.stdout.split()));assert len(values)==len(requests)
expected=[]
for maximum,begin,end,special in meta:
    expected.append((63<<38)|((special>>15)<<37)|((special&1023)<<27) if special is not None else
                    (maximum<<40)|(sum(values[begin:end])&((1<<38)-1)))
def pack(words,width):return sum(v<<(width*i) for i,v in enumerate(words))
bits=C*16+K*C*16+C+K*C+K*44
rows=[]
for i,(_,data,weights,dm,wm) in enumerate(cases):
    row=pack(data,16)
    row=(row<<(K*C*16))|pack([x for w in weights for x in w],16)
    row=(row<<C)|dm;row=(row<<(K*C))|pack(wm,C)
    row=(row<<(K*44))|pack(expected[i*K:(i+1)*K],44)
    rows.append(f'{row:0{(bits+3)//4}x}')
vectors=out/'vectors.hex';vectors.write_text('\n'.join(rows)+'\n')
report=dict(status='PASS_SIZED_CMAC_VECTOR_GENERATION',created_utc=timestamp(),channels=C,kernels=K,
            frame_bits=bits,frames=len(cases),outputs=len(expected),lane_checks=len(values),seed=hex(seed),
            categories=dict(Counter(c[0] for c in cases)),compiler=subprocess.run(['c++','--version'],capture_output=True,text=True).stdout.splitlines()[0],
            compile_command=compile_command,source=fingerprint([Path(__file__).resolve(),helper]),
            artifacts=fingerprint([vectors,binary,out/'compile.log']),
            scope='Independent sized grouping/mask/NaN oracle with executed NVIDIA integer Booth helper; not full SystemC, upstream UTB or RK numerical validation.')
(out/'vectors_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(report['status'],C,K,len(cases),len(expected))
