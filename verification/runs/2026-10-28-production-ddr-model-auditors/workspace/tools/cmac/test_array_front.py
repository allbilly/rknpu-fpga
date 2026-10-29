#!/usr/bin/env python3
"""Test raw-command C32/K16 frame assembly against physical-address fixtures."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--tool',choices=('iverilog','verilator'),default='iverilog')
a=p.parse_args()
base=ROOT/'build/rknpu-array-front'
vr=json.loads((base/'vectors_report.json').read_text())
def verify(m):
    for name,sha in m['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
verify(vr['source']);verify(vr['artifacts'])
sources=[ROOT/'rtl/rk_cmac_profile.sv',ROOT/'rtl/cmac/rk_cmac_array_front.sv']
bench=ROOT/'tests/cmac/tb_cmac_array_front.sv'
tracked=sources+[bench,Path(__file__).resolve(),base/'vectors_report.json']
out=base/f'{a.tool}-{time.time_ns()}'
out.mkdir(exist_ok=False)
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),vectors=vr,commands=[],seed='0x3588af16',
            scope='Unchanged terminal RK command words to physical C32/K16 frames, no arithmetic or job-completion claim.')
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def run(argv,name):
    step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();start=time.monotonic()
    try:
        with (ROOT/step['log']).open('w') as log:
            result=subprocess.run(step['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
        text=(ROOT/step['log']).read_text();step['returncode']=result.returncode
        assert result.returncode==0,text[-5000:]
        if name in ('lint','compile'):
            assert not re.search(r'warning:|sorry:|%Warning',text,re.I),text[-5000:]
        assert 'ERROR :' not in text,text[-5000:]
        step['status']='PASS';return text
    except Exception:
        step['status']='FAIL';raise
    finally:
        step['seconds']=round(time.monotonic()-start,3);save()
save()
try:
    report['tool_version']=run([a.tool,'-V' if a.tool=='iverilog' else '--version'],'version').splitlines()[0]
    if a.tool=='iverilog':
        binary=out/'sim.vvp'
        run(['iverilog','-g2012','-s',bench.stem,'-o',binary,*sources,bench],'compile')
        report['runtime_version']=run(['vvp','-V'],'runtime_version').splitlines()[0];execute=['vvp',binary]
    else:
        flags=['--timing','--assert','-Wall','--timescale-override','1ns/1ps']
        run(['verilator','--lint-only',*flags,'--top-module',bench.stem,*sources,bench],'lint')
        report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
        binary=out/'obj/sim'
        run(['verilator','--binary',*flags,'-j','2','--top-module',bench.stem,'--Mdir',out/'obj','-o','sim',*sources,bench],'compile');execute=[binary]
    text=run(execute+[f'+SOURCE={ROOT/"build/cmac_vectors"}',f'+FRONT={base}'],'test')
    lines=[line for line in text.splitlines() if line.startswith('PASS ')]
    assert len(lines)==1,text
    match=re.fullmatch(r'PASS raw C32 K16 array front good_runs=(\d+) fault_runs=(\d+) reset_phases=(\d+) cancels=(\d+) profile_faults=(\d+) checked_frames=(\d+) seed=3588af16',lines[0])
    assert match,lines
    good,faults,resets,cancels,profiles,frames=map(int,match.groups())
    assert [good,faults,resets,cancels,profiles]==[13,14 if a.tool=='iverilog' else 10,5,3,3] and frames>=109,lines
    assert fingerprint(tracked)==report['source'];verify(vr['source']);verify(vr['artifacts'])
    report.update(status='PASS_RAW_ARRAY_FRONT_NATIVE_ONLY',result=lines[0],artifacts=fingerprint([binary]+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'],report['result'])
