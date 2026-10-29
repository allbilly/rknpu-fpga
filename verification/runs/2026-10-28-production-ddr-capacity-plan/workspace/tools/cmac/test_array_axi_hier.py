#!/usr/bin/env python3
"""Run the full public-port C32/K16 AXI suite using the verified RTL library.

The saved RAM images are test inputs/oracles, not execution-side CPU fixups.
Raw command words, the testbench and all error expectations remain unchanged.
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
p.add_argument('--native-report',type=Path,required=True)
p.add_argument('--cmac-report',type=Path,required=True)
p.add_argument('--donor-report',type=Path,action='append',required=True)
a=p.parse_args()
native=json.loads(a.native_report.read_text());cmac=json.loads(a.cmac_report.read_text())
assert native['status']=='PASS_RAW_ARRAY_AXI_SMOKE_ONLY'
assert cmac['status']=='PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY'
assert (cmac['channels'],cmac['kernels'],cmac['parallel_products'])==(32,16,512)
def verify(m):
    for name,sha in m['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
for r in (native,cmac):
    assert all(c['status']=='PASS' for c in r['commands'])
    verify(r['source']);verify(r['artifacts'])
vr=native['vectors'];verify(vr['source']);verify(vr['artifacts']);verify(native['memory_images'])
assert len(vr['cases'])==8 and native['seed']=='0x3588ae16'
donor=ROOT/'rtl/vendor/nvdla'
baselines=[json.loads(path.read_text()) for path in a.donor_report]
assert {r['status'] for r in baselines}=={'PASS_PARALLEL_CACC_NATIVE_ONLY','PASS_OC16_FRAME_OUTPUT_NATIVE_ONLY'}
allowed=set()
for step in cmac['commands']:
    for code,name,line in step.get('warning_locations',[]):
        if Path(name).parent==donor:
            allowed.add((code,name,line))
for r in baselines:
    assert r['tool_version']==cmac['tool_version']
    verify(r['source']);verify(r['artifacts'])
    for code,name,line,*count in r['donor_warnings']:
        assert Path(name).parent==donor
        allowed.add((code,name,line))
bench=ROOT/'tests/cmac/tb_cmac_array_axi.sv'
host=ROOT/'tests/axil_host.svh'
sources=[ROOT/n for n in native['source']['files'] if Path(n).suffix in ('.sv','.v') and ROOT/n!=bench]
libdir=a.cmac_report.resolve().parent/'cell'
block='rk_cmac_fp16_cell_b';wrapper=libdir/(block+'.sv');library=libdir/('lib'+block+'.a')
params=ROOT/'tools/cmac/empty_hier_parameters.v'
for path in (wrapper,library):
    assert str(path.relative_to(ROOT)) in cmac['artifacts']['files']
assert str(params.relative_to(ROOT)) in cmac['source']['files']
directories={case['name']:a.native_report.resolve().parent/'vectors'/case['name'] for case in vr['cases']}
for directory in directories.values():
    for name in ('input.hex','check.txt'):
        assert str((directory/name).relative_to(ROOT)) in native['memory_images']['files']
out=ROOT/f'build/rknpu-array-axi/full-hierarchical-{time.time_ns()}'
out.mkdir(parents=True,exist_ok=False)
snapshots=[]
for name,r in [('native',native),('cmac',cmac)]+[(f'donor{i}',r) for i,r in enumerate(baselines)]:
    path=out/(name+'_report_snapshot.json');path.write_text(json.dumps(r,indent=2)+'\n');snapshots.append(path)
tracked=[ROOT/n for n in native['source']['files']]+[wrapper,library,params,Path(__file__).resolve()]+snapshots
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),vectors=vr,
            memory_images=native['memory_images'],seed='0x3588ae16',suite='full',commands=[],tests=[],
            approved_donor_warnings=[list(x) for x in sorted(allowed)],
            scope='Full unchanged C32/K16 AXI bench with source-verified compiled RTL cell library. Eight numerical fixtures, ten fault/reset cases, repeated job. Two-state behavioral AXI RAM, not PCIe/DDR, FPGA timing or RK silicon.')
def save():
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def run(argv,name,lint=False):
    step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();start=time.monotonic()
    try:
        with (ROOT/step['log']).open('w') as log:
            with subprocess.Popen(step['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                try: code=proc.wait(timeout=14400)
                except BaseException:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait();raise
        text=(ROOT/step['log']).read_text();step['returncode']=code
        assert code==0 and 'ERROR :' not in text,text[-6000:]
        warnings=re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:',text,re.M)
        assert len(warnings)==len(re.findall(r'^%Warning-',text,re.M)),'Unparsed warning'
        unexpected=[w for w in warnings if not (lint and (w in allowed or (w[0]=='BLKSEQ' and Path(w[1]) in (bench,host))))]
        assert not unexpected,unexpected
        assert not re.search(r'%Error|warning:|sorry:',text,re.I),text[-6000:]
        step.update(status='PASS',warning_locations=[list(w) for w in warnings]);return text
    except Exception:
        step['status']='FAIL';raise
    finally: step['seconds']=round(time.monotonic()-start,3);save()
save()
try:
    report['tool_version']=run(['verilator','--version'],'version').splitlines()[0]
    assert report['tool_version']==cmac['tool_version']
    report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
    assert report['cxx_version']==cmac['cxx_version']
    obj=out/'obj';obj.mkdir()
    (obj/(f'V{bench.stem}_hier.mk')).write_text('# Verified cell library; linked by VM_USER_LDLIBS.\nVM_HIER_LIBS := '+str(library)+'\n')
    run(['verilator','--cc','--main','--exe','--timing','--assert','-Wall','-Wno-fatal',
         '--timescale-override','1ns/1ps','-DDESIGNWARE_NOEXIST','-DASSERT_ON',f'-I{donor}','-I.',
         '--Mdir',obj,'--top-module',bench.stem,'-o','sim',
         '--hierarchical-block','rk_cmac_fp16_cell,'+block,'--hierarchical-params-file',params,
         '-LDFLAGS',library,wrapper,*sources,bench],'generate',True)
    top_cpp=list(obj.glob('Vtb_cmac_array_axi*.cpp'));called=set()
    for path in top_cpp:
        text=path.read_text()
        for operation in ('create','combo_update','seq_update'):
            symbol=block+'_protectlib_'+operation
            if symbol in text and re.search(r'\b'+symbol+r'\s*\(',text):called.add(operation)
    assert called=={'create','combo_update','seq_update'},'Missing actual library calls'
    assert not any('NV_NVDLA_CMAC_CORE_MAC_mul' in p.name for p in top_cpp),'Embedded donor multiplier internals'
    report['library_operations']=sorted(called);save()
    run(['make','-C',obj,'-f',f'V{bench.stem}.mk','-j','2','OPT_FAST=-O0','OPT_SLOW=-O0','OPT_GLOBAL=-O0'],'compile')
    common=vr['cases'][3]
    tests=[(case,0,1) for case in vr['cases']]+[(common,mode,1) for mode in range(1,11)]+[(common,0,2)]
    assert len(tests)==19
    outputs=[]
    for case,mode,repeats in tests:
        name=f'{case["name"]}-fault{mode}-repeat{repeats}';output=out/(name+'.memory.txt')
        result=run([obj/'sim',f'+CASE={directories[case["name"]]}','+START=100e0000','+AMOUNT=45','+NTASKS=1',
                    f'+NTRANS={196+case["reads"]+case["writes"]}',f'+WRITES={case["writes"]}',
                    f'+NCHECKS={196+case["rows"]*case["ai"]+case["ai"]*case["ao"]+2*case["rows"]*case["ao"]+256}',
                    f'+FAULT={mode}',f'+REPEATS={repeats}',f'+OUTPUT={output}'],name)
        lines=[line for line in result.splitlines() if line.startswith('PASS ')]
        error={0:0,1:5,2:8,3:8,4:5,5:8,6:5,7:7,8:1,9:0,10:5}[mode]
        assert len(lines)==1 and lines[0].startswith('PASS C32 K16 host_axi ')
        assert f'repeats={repeats} fault_mode={mode} error={error} ' in lines[0] and lines[0].endswith('seed=3588ae16'),result
        if not error:
            assert output.read_bytes()==(directories[case['name']]/'check.txt').read_bytes();outputs.append(output)
        else: assert not output.exists()
        report['tests'].append(dict(name=name,status='PASS',result=lines[0]));save()
    assert len(report['tests'])==19 and len(outputs)==10
    assert fingerprint(tracked)==report['source']
    for r in (native,cmac,*baselines):verify(r['source']);verify(r['artifacts'])
    verify(vr['source']);verify(vr['artifacts']);verify(native['memory_images'])
    generated=[p for p in obj.rglob('*') if p.is_file()]
    report.update(status='PASS_RAW_ARRAY_AXI_FULL_HIERARCHICAL_ONLY',
                  artifacts=fingerprint(generated+outputs+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'])
