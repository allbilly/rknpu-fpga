#!/usr/bin/env python3
"""Characterize original and fixed-FP16 row logic with the same XC7 flow.

No correctness, integrated array, physical fit or timing conclusion follows
from this area-only experiment. Formal and numerical acceptance are separate.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
from xc7_primitive_counts import primitive_counts

out=ROOT/f'build/rknpu-fixed-fp16-rows/area-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
donor=ROOT/'rtl/vendor/nvdla'
sources=[donor/'NV_DW02_tree.v',donor/'NV_NVDLA_CMAC_CORE_MAC_mul.v',
         ROOT/'rtl/cmac/experimental/rk_cmac_fp16_rows.sv',ROOT/'tests/cmac/fp16_rows_area_top.sv']
tracked=sources+[Path(__file__).resolve(),ROOT/'tools/cmac/xc7_primitive_counts.py']
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),commands=[],results={},
            scope='Single partial-row helper, identical unconstrained sign/magnitude/shift/mask ports. Fixed-mode candidate assumes completed setup. Area-only mapping, no numerical, integrated C32/K16, packed utilization, timing, FPGA or RK claim.')
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def run(argv,name):
    step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();start=time.monotonic()
    try:
        with (ROOT/step['log']).open('w') as log:
            with subprocess.Popen(step['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                try: code=proc.wait(timeout=3600)
                except BaseException:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait();raise
        text=(ROOT/step['log']).read_text();step['returncode']=code
        assert code==0 and 'ERROR:' not in text,text[-5000:]
        step['status']='PASS';return text
    except Exception: step['status']='FAIL';raise
    finally: step['seconds']=round(time.monotonic()-start,3);save()
save();artifacts=[]
try:
    report['tool_version']=run(['yosys','-V'],'version').strip()
    help_text=run(['yosys','-Q','-T','-p','help synth_xilinx'],'help')
    coarse=re.search(r'\n    coarse:\n(.*?)\n    map_memory:',help_text,re.S);assert coarse
    commands=[line.strip() for line in coarse.group(1).splitlines() if line.strip()]
    assert commands==['techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=[46]',
                      'alumacc','share','opt','memory -nomap','opt_clean'],commands
    unshared=[line.replace('LUT_WIDTH=[46]','LUT_WIDTH=6') for line in commands if line!='share']
    report.update(original_coarse_stage=commands,executed_coarse_stage=unshared)
    for mode,label in ((0,'original'),(1,'fixed')):
        hierarchy=out/(label+'_hierarchy.json');design=out/(label+'_mapped.json');netlist=out/(label+'_mapped.v');script=out/(label+'.ys')
        top='fp16_rows_area_top';flags=f'-family xc7 -top {top} -flatten -noiopad -noclkbuf'
        text='read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST '+' '.join(json.dumps(str(s)) for s in sources)
        text+=f'; chparam -set STATIC_MODE {mode} {top}; hierarchy -check -top {top}; proc; opt_clean; check -assert'
        text+=f'; write_json {json.dumps(str(hierarchy))}; synth_xilinx {flags} -run begin:map_dsp; '+'; '.join(unshared)
        text+=f'; synth_xilinx {flags} -run map_memory:; check -assert; write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}'
        script.write_text(text.replace('; ',';\n')+'\n')
        log=run(['yosys','-Q','-T','-s',script],label)
        assert 'Executing SHARE pass' not in log
        modules=json.loads(hierarchy.read_text())['modules']
        def booths(name):
            if name=='NV_NVDLA_CMAC_CORE_MAC_booth': return 1
            return sum(booths(c['type']) for c in modules[name].get('cells',{}).values() if c['type'] in modules)
        assert booths(top)==8
        mapped=json.loads(design.read_text())['modules'];cells=primitive_counts(mapped,top)
        for name,width in (('res_a',32),('res_b',32),('res_tag',8)):
            bits=mapped[top]['ports'][name]['bits'];assert len(bits)==width and any(isinstance(b,int) for b in bits),(name,bits)
        luts=sum(n for t,n in cells.items() if t.startswith('LUT'));assert luts>0
        report['results'][label]=dict(cells=dict(cells),lut_count=luts,
                                     ff_count=sum(n for t,n in cells.items() if t.startswith('FD')),
                                     dsp_count=cells['DSP48E1'],booth_instances=8)
        artifacts += [hierarchy,design,netlist,script];save()
    assert fingerprint(tracked)==report['source']
    report.update(status='PASS_FIXED_FP16_ROW_AREA_ONLY',
                  artifacts=fingerprint(artifacts+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc: report.update(status='FAIL',reason=str(exc));raise
finally: report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'],report['results'])
