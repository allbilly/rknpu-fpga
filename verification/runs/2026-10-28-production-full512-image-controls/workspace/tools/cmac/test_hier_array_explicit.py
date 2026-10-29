#!/usr/bin/env python3
"""Full C32/K16 regression with explicit 5.048 hierarchy parameter transport.

Fresh library and top compilation; unchanged RTL, assertions and corpus.
Requires the small sequential tool probe and original flat regression to pass.
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
p.add_argument('--flat-report',type=Path,required=True)
p.add_argument('--probe-report',type=Path,required=True)
a=p.parse_args()
flat=json.loads(a.flat_report.read_text());probe=json.loads(a.probe_report.read_text())
assert flat['status']=='PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY'
assert probe['status']=='PASS_HIERARCHY_TOOL_PROBE_ONLY'
assert probe['explicit_library_call_files'] and not probe['stock_library_call_files']
assert probe['tool_version']==flat['tool_version'] and probe['tool_version'].startswith('Verilator 5.048 ')
def verify(manifest):
    for name,sha in manifest['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
for parent in (flat,probe):
    verify(parent['source']);verify(parent['artifacts'])
vr=flat['vectors'];verify(vr['source']);verify(vr['artifacts'])
assert (vr['channels'],vr['kernels'],vr['frames'],vr['outputs'])==(32,16,208,3328)
donor=ROOT/'rtl/vendor/nvdla'
sources=[donor/n for n in ('compat/nv_assert_never.v','compat/nv_assert_no_x.v','NV_DW02_tree.v','NV_NVDLA_CMAC_CORE_MAC_mul.v')]
cell=ROOT/'rtl/cmac/rk_cmac_fp16_cell.sv'
array=ROOT/'rtl/cmac/rk_cmac_fp16_array.sv'
bench=ROOT/'tests/cmac/tb_cmac_fp16_array.sv'
params=ROOT/'tools/cmac/empty_hier_parameters.v'
control=ROOT/'tools/cmac/array_hierarchy.vlt'
for path in sources+[cell,array,bench]:
    assert str(path.relative_to(ROOT)) in flat['source']['files']
assert str(params.relative_to(ROOT)) in probe['source']['files']
out=ROOT/f'build/rknpu-cmac-array/c32k16/hierarchical-explicit-{time.time_ns()}'
out.mkdir(parents=True,exist_ok=False)
snapshots=[]
for name,value in (('flat',flat),('probe',probe)):
    path=out/(name+'_report_snapshot.json');path.write_text(json.dumps(value,indent=2)+'\n');snapshots.append(path)
tracked=sorted(set([ROOT/n for n in flat['source']['files']]+[params,control,Path(__file__).resolve()]+snapshots))
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
allowed={tuple(item[:3]) for item in flat['donor_warnings']}
rename=('DECLFILENAME',str(cell),'5')
allowed.add(rename)
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),vectors=vr,
            channels=32,kernels=16,parallel_products=512,commands=[],flat_result=flat['result'],
            scope='Explicit 5.048 hierarchy parameter transport. Fresh library and top builds, unchanged full native CMAC bench. No production RTL substitution, CPU fallback, four-state, physical FPGA or RK claim.')
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
        assert set(warnings)<=(allowed if lint else set()),warnings
        for line in text.splitlines():
            if line.startswith('%Warning-DECLFILENAME: '+str(cell)+':'):
                assert line==f"%Warning-DECLFILENAME: {cell}:5:8: Filename 'rk_cmac_fp16_cell' does not match MODULE name: 'rk_cmac_fp16_cell_b'",line
        assert not re.search(r'%Error|warning:|sorry:',text,re.I),text[-6000:]
        step.update(status='PASS',warning_locations=[list(w) for w in warnings]);return text
    except Exception:
        step['status']='FAIL';raise
    finally: step['seconds']=round(time.monotonic()-start,3);save()
save()
try:
    report['tool_version']=run(['verilator','--version'],'version').splitlines()[0]
    assert report['tool_version']==flat['tool_version']
    report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
    flags=['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps',
           '-DDESIGNWARE_NOEXIST','-DASSERT_ON',f'-I{donor}']
    optimization='OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0'
    block='rk_cmac_fp16_cell_b';libdir=out/'cell';obj=out/'top'
    run(['verilator','--cc','--build','-j','2',*flags,'-MAKEFLAGS',optimization,
         '--Mdir',libdir,'--prefix','V'+block,'--mod-prefix','V'+block,
         '--top-module-encoded',block,'--lib-create',block,'--hierarchical-child','1',
         '--hierarchical-block','rk_cmac_fp16_cell,'+block,control,*sources,cell],'cell_compile',True)
    wrapper=libdir/(block+'.sv');library=libdir/('lib'+block+'.a')
    assert wrapper.is_file() and library.is_file()
    obj.mkdir()
    (obj/'Vtb_cmac_fp16_array_hier.mk').write_text(
        '# Freshly built cell library; linked explicitly by VM_USER_LDLIBS.\n'
        +'VM_HIER_LIBS := '+str(library)+'\n')
    wrapper_text=wrapper.read_text()
    for pattern in (r'input logic \[511:0\]\s+data',r'input logic \[511:0\]\s+weight',
                    r'input logic \[31:0\]\s+data_mask',r'output logic \[43:0\]\s+result'):
        assert re.search(pattern,wrapper_text),pattern
    run(['verilator','--cc','--main','--exe',*flags,'-GATOMIC_C=32','-GATOMIC_K=16',
         '--top-module',bench.stem,'--Mdir',obj,'-o','sim',
         '--hierarchical-block','rk_cmac_fp16_cell,'+block,'--hierarchical-params-file',params,
         '-LDFLAGS',library,wrapper,*sources,cell,array,bench],'top_generate',True)
    top_cpp=sorted(obj.glob('Vtb_cmac_fp16_array*.cpp'))
    called=set()
    for path in top_cpp:
        text=path.read_text()
        for operation in ('create','combo_update','seq_update'):
            symbol=block+'_protectlib_'+operation
            if symbol in text and re.search(r'\b'+symbol+r'\s*\(',text):called.add(operation)
    assert called=={'create','combo_update','seq_update'},'Missing actual library calls'
    assert not any('NV_NVDLA_CMAC_CORE_MAC_mul' in path.name for path in top_cpp),'Donor internals leaked into top'
    report['library_operations']=sorted(called);save()
    run(['make','-C',obj,'-f','Vtb_cmac_fp16_array.mk','-j','2',*optimization.split()],'top_compile')
    result=run([obj/'sim',f'+VECTORS={ROOT / "build/rknpu-cmac-array/c32k16/vectors.hex"}','+COUNT=208'],'test')
    lines=[line for line in result.splitlines() if line.startswith('PASS ')]
    assert lines==[flat['result']],result
    assert fingerprint(tracked)==report['source']
    for parent in (flat,probe):verify(parent['source']);verify(parent['artifacts'])
    verify(vr['source']);verify(vr['artifacts'])
    generated=[p for d in (libdir,obj) for p in d.rglob('*') if p.is_file()]
    report.update(status='PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY',result=lines[0],
                  artifacts=fingerprint(generated+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'],report['result'])
