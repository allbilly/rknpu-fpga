#!/usr/bin/env python3
"""Rebuild a verified explicit-hierarchy CMAC with optimized host C++ only.

All original source inputs, simulator flags, dimensions, vectors and tests
remain unchanged. Only output paths and make's OPT_* values are replaced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-report',type=Path,required=True)
a=p.parse_args()
parent_path=a.source_report.resolve();parent=json.loads(parent_path.read_text())
assert parent['status']=='PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY'
assert (parent['channels'],parent['kernels'],parent['parallel_products'])==(32,16,512)
assert all(c['status']=='PASS' for c in parent['commands'])
names=[Path(c['log']).stem for c in parent['commands']]
assert names==['version','cxx_version','cell_compile','top_generate','top_compile','test'],names
assert parent['tool_version'].startswith('Verilator 5.048 ')
def verify(m):
    for name,sha in m['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
verify(parent['source']);verify(parent['artifacts'])
vr=parent['vectors'];verify(vr['source']);verify(vr['artifacts'])
assert (vr['frames'],vr['outputs'],vr['seed'])==(208,3328,'0x35883216')
old=parent_path.parent
out=ROOT/f'build/rknpu-cmac-array/c32k16/hierarchical-o2-{time.time_ns()}'
out.mkdir(parents=True,exist_ok=False)
snapshot=out/'original_report_snapshot.json';snapshot.write_text(json.dumps(parent,indent=2)+'\n')
tracked=[ROOT/n for n in parent['source']['files']]+[snapshot,Path(__file__).resolve()]
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
allowed={tuple(w) for c in parent['commands'] for w in c.get('warning_locations',[])}
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),vectors=vr,
            channels=32,kernels=16,parallel_products=512,commands=[],flat_result=parent['result'],
            host_optimization='OPT_FAST=-O2 OPT_SLOW=-O2 OPT_GLOBAL=-O2',
            scope='Fresh optimized-host build of the same explicit-hierarchy C32/K16 RTL. Identical 208-frame native corpus, assertions, holds and resets. No RTL, FPGA execution, numerical policy or timing-constraint change.')
def save():
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def rewrite(argv):
    result=[]
    for arg in argv:
        result.append(arg.replace(str(old),str(out)).replace('OPT_FAST=-O0','OPT_FAST=-O2')
                      .replace('OPT_SLOW=-O0','OPT_SLOW=-O2').replace('OPT_GLOBAL=-O0','OPT_GLOBAL=-O2'))
    return result
def run(argv,name):
    step=dict(argv=argv,status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();start=time.monotonic()
    try:
        with (ROOT/step['log']).open('w') as log:
            with subprocess.Popen(argv,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                try: code=proc.wait(timeout=14400)
                except BaseException:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait();raise
        text=(ROOT/step['log']).read_text();step['returncode']=code
        assert code==0 and 'ERROR :' not in text,text[-6000:]
        warnings=re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:',text,re.M)
        assert len(warnings)==len(re.findall(r'^%Warning-',text,re.M)),'Unparsed warning'
        assert set(warnings)<=allowed,warnings
        assert not re.search(r'%Error|warning:|sorry:',text,re.I),text[-6000:]
        step.update(status='PASS',warning_locations=[list(w) for w in warnings]);return text
    except Exception:
        step['status']='FAIL';raise
    finally: step['seconds']=round(time.monotonic()-start,3);save()
save()
try:
    (out/'top').mkdir()
    (out/'top/Vtb_cmac_fp16_array_hier.mk').write_text(
        '# Fresh optimized cell library; linked by VM_USER_LDLIBS.\nVM_HIER_LIBS := '
        +str(out/'cell/librk_cmac_fp16_cell_b.a')+'\n')
    for step,name in zip(parent['commands'],names):
        argv=rewrite(step['argv'])
        if name=='cell_compile':
            assert 'OPT_FAST=-O2 OPT_SLOW=-O2 OPT_GLOBAL=-O2' in argv
            assert argv[argv.index('--Mdir')+1]==str(out/'cell')
        if name=='top_generate':
            assert argv[argv.index('--Mdir')+1]==str(out/'top')
            assert argv[argv.index('-LDFLAGS')+1]==str(out/'cell/librk_cmac_fp16_cell_b.a')
        if name=='top_compile':
            assert {'OPT_FAST=-O2','OPT_SLOW=-O2','OPT_GLOBAL=-O2'}<=set(argv)
        if name=='test':assert argv[0]==str(out/'top/sim')
        result=run(argv,name)
        if name in ('version','cxx_version'):
            key='tool_version' if name=='version' else name
            report[key]=result.splitlines()[0];assert report[key]==parent[key]
        if name=='top_generate':
            files=list((out/'top').glob('Vtb_cmac_fp16_array*.cpp'));called=set()
            for path in files:
                text=path.read_text()
                for operation in ('create','combo_update','seq_update'):
                    symbol='rk_cmac_fp16_cell_b_protectlib_'+operation
                    if symbol in text and re.search(r'\b'+symbol+r'\s*\(',text):called.add(operation)
            assert called=={'create','combo_update','seq_update'}
            assert not any('NV_NVDLA_CMAC_CORE_MAC_mul' in p.name for p in files)
            report['library_operations']=sorted(called);save()
        if name=='test':
            lines=[line for line in result.splitlines() if line.startswith('PASS ')]
            assert lines==[parent['result']],result
    for name in ('cell_compile','top_compile'):
        log=(out/(name+'.log')).read_text()
        assert re.search(r'^c\+\+ -O2\s',log,re.M),'Host optimization flag absent'
        assert not re.search(r'^c\+\+ -O0\s',log,re.M),'Unexpected unoptimized host compilation'
    assert fingerprint(tracked)==report['source']
    verify(parent['source']);verify(parent['artifacts']);verify(vr['source']);verify(vr['artifacts'])
    artifacts=[p for d in (out/'cell',out/'top') for p in d.rglob('*') if p.is_file()]
    report.update(status='PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY',result=parent['result'],
                  artifacts=fingerprint(artifacts+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'],report['result'])
