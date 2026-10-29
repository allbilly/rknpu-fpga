#!/usr/bin/env python3
"""Run the parallel sized FP16 CMAC unit, without changing raw-path tests."""
import argparse
from collections import Counter
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
p.add_argument('--tool',choices=('verilator','iverilog'),default='verilator')
p.add_argument('--channels',type=int,choices=(8,32,64),default=32)
p.add_argument('--kernels',type=int,choices=(1,8,16,32),default=16)
a=p.parse_args();C,K=a.channels,a.kernels
base=ROOT/'build/rknpu-cmac-array'/f'c{C}k{K}'
vr=json.loads((base/'vectors_report.json').read_text())
def verify(manifest):
    for name,sha in manifest['files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
verify(vr['source']);verify(vr['artifacts'])
assert vr['channels']==C and vr['kernels']==K
out=base/(a.tool+'-'+str(time.time_ns()));out.mkdir(exist_ok=False)
donor=ROOT/'rtl/vendor/nvdla'
sources=[donor/'compat/nv_assert_never.v',donor/'compat/nv_assert_no_x.v',donor/'NV_DW02_tree.v',
         donor/'NV_NVDLA_CMAC_CORE_MAC_mul.v',ROOT/'rtl/cmac/rk_cmac_fp16_cell.sv',ROOT/'rtl/cmac/rk_cmac_fp16_array.sv']
bench=ROOT/'tests/cmac/tb_cmac_fp16_array.sv'
tracked=sources+[bench,Path(__file__).resolve(),base/'vectors_report.json']
tracked += [donor/n for n in ('nv_assert_never.vlib','nv_assert_no_x.vlib','assertion_header.h','assertion_task.h')]
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),vectors=vr,
            channels=C,kernels=K,parallel_products=C*K,commands=[],
            scope='Parallel CxK FP16 array tested with executed NVIDIA Booth helper and sized independent grouping oracle. Not upstream nvdla_utb, full SystemC, FPGA timing or RK numerical evidence.')
def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
baseline=None
def run(argv,name,lint=False):
    global baseline
    step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();start=time.monotonic()
    try:
        with (ROOT/step['log']).open('w') as f:r=subprocess.run(step['argv'],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=7200)
        result=(ROOT/step['log']).read_text();step['returncode']=r.returncode
        assert r.returncode==0 and 'ERROR :' not in result,result[-5000:]
        if lint:
            locations=Counter(re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:',result,re.M))
            assert all(Path(path).parent==donor for _,path,_ in locations),locations
            if baseline is None:
                baseline=locations;report['donor_warnings']=[list(k)+[v] for k,v in sorted(locations.items())]
            else:assert locations==baseline,locations
        elif name=='compile':assert 'warning:' not in result.lower() and 'sorry:' not in result.lower(),result[-2000:]
        step['status']='PASS';return result
    except Exception:step['status']='FAIL';raise
    finally:step['seconds']=round(time.monotonic()-start,3);save()
save()
try:
    report['tool_version']=run([a.tool,'--version' if a.tool=='verilator' else '-V'],'version').splitlines()[0]
    defines=['-DDESIGNWARE_NOEXIST','-DASSERT_ON',f'-I{donor}']
    if a.tool=='verilator':
        flags=['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps',*defines,
               f'-GATOMIC_C={C}',f'-GATOMIC_K={K}']
        run(['verilator','--lint-only',*flags,'--top-module','rk_cmac_fp16_array',*sources],'baseline_lint',True)
        run(['verilator','--lint-only',*flags,'--top-module',bench.stem,*sources,bench],'bench_lint',True)
        binary=out/'obj/sim'
        report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
        run(['verilator','--binary',*flags,'-j','2','--top-module',bench.stem,'--Mdir',out/'obj','-o','sim',*sources,bench],'compile',True)
        execute=[binary]
    else:
        binary=out/'sim.vvp'
        run(['iverilog','-g2012',*defines,'-s',bench.stem,f'-P{bench.stem}.ATOMIC_C={C}',f'-P{bench.stem}.ATOMIC_K={K}',
             '-o',binary,*sources,bench],'compile')
        report['vvp_version']=run(['vvp','-V'],'vvp_version').splitlines()[0];execute=['vvp',binary]
    result=run(execute+[f'+VECTORS={base/"vectors.hex"}',f'+COUNT={vr["frames"]}'],'test')
    lines=[s for s in result.splitlines() if s.startswith('PASS ')]
    assert len(lines)==1 and f'C={C} K={K} frames={vr["frames"]} checked_outputs={vr["outputs"]}' in lines[0],result
    assert f'retired_outputs={vr["outputs"]-K} reset_canceled={K}' in lines[0],lines
    assert f'faults={int(a.tool=="iverilog")}' in lines[0],lines
    assert fingerprint(tracked)==report['source'];verify(vr['source']);verify(vr['artifacts'])
    report.update(status='PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY',result=lines[0],
                  artifacts=fingerprint([binary]+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc:report.update(status='FAIL',reason=str(exc));raise
finally:report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'],report['result'])
