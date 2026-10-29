#!/usr/bin/env python3
"""Compare stock hierarchy planning with an explicit parameter-file sub-run.

Small simulator diagnostic, not CMAC verification. No production RTL changes.
"""
import json
import os
from pathlib import Path
import re
import signal
import shlex
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

out=ROOT/f'build/hierarchy-probe/{time.time_ns()}'
out.mkdir(parents=True,exist_ok=False)
leaf=ROOT/'tests/cmac/hierarchy_probe_leaf.sv'
bench=ROOT/'tests/cmac/tb_hierarchy_probe.sv'
params=ROOT/'tools/cmac/empty_hier_parameters.v'
tracked=[leaf,bench,params,Path(__file__).resolve()]
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(path.read_bytes())
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),commands=[],
            scope='Four small sequential instances only. Simulator partition diagnostic, not CMAC, FPGA or RK validation.')
def save():
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
def run(argv,name):
    step=dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();start=time.monotonic()
    try:
        with (ROOT/step['log']).open('w') as log:
            with subprocess.Popen(step['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                try: code=proc.wait(timeout=300)
                except BaseException:
                    try: os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait();raise
        text=(ROOT/step['log']).read_text();step['returncode']=code
        assert code==0,text[-4000:]
        warnings=re.findall(r'^%Warning-([^:]+):',text,re.M)
        assert set(warnings)<={'DECLFILENAME'},warnings
        assert not re.search(r'%Error|warning:|sorry:',text,re.I),text[-4000:]
        step.update(status='PASS',warning_codes=warnings);return text
    except Exception:
        step['status']='FAIL';raise
    finally: step['seconds']=round(time.monotonic()-start,3);save()
def calls(obj,mangled):
    return [str(p.relative_to(ROOT)) for p in obj.glob('Vtb_hierarchy_probe*.cpp')
            if mangled+'_protectlib_create(' in p.read_text()]
save()
try:
    report['tool_version']=run(['verilator','--version'],'version').splitlines()[0]
    assert report['tool_version'].startswith('Verilator 5.048 ')
    flags=['--binary','--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps','-j','2',
           '-MAKEFLAGS','OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
           '--top-module','tb_hierarchy_probe','-o','sim']
    stock=out/'stock'
    run(['verilator',*flags,'--hierarchical','--Mdir',stock,leaf,bench],'stock_compile')
    stock_result=run([stock/'sim'],'stock_test')
    args=shlex.split((stock/'Vtb_hierarchy_probe__hierMkArgs.f').read_text())
    mapping=args[args.index('--hierarchical-block')+1]
    original,mangled=mapping.split(',')
    assert original=='hierarchy_probe_leaf' and re.fullmatch(r'hierarchy_probe_leaf_[a-z]+',mangled)
    report['block_mapping']=mapping
    report['stock_library_call_files']=calls(stock,mangled)
    wrapper=stock/('V'+mangled)/(mangled+'.sv')
    library=stock/('V'+mangled)/('lib'+mangled+'.a')
    assert wrapper.is_file() and library.is_file()
    fixed=out/'explicit_params'
    fixed.mkdir()
    # This explicit sub-run reuses the completed leaf library, rather than
    # invoking the stock planner again. Its generated top makefile still
    # includes a hierarchy fragment; record that already-built dependency.
    (fixed/'Vtb_hierarchy_probe_hier.mk').write_text(
        '# Completed probe library; linked explicitly by VM_USER_LDLIBS.\n'
        +'VM_HIER_LIBS := '+str(library)+'\n')
    run(['verilator',*flags,'--Mdir',fixed,
         '--hierarchical-block',mapping,
         '--hierarchical-params-file',params,'-LDFLAGS',library,
         wrapper,leaf,bench],'explicit_params_compile')
    report['explicit_library_call_files']=calls(fixed,mangled)
    assert report['explicit_library_call_files'],'Explicit parameter file did not activate library substitution'
    result=run([fixed/'sim'],'explicit_params_test')
    expected='PASS hierarchy probe instances=4 outputs=128 resets=2'
    assert [s for s in stock_result.splitlines() if s.startswith('PASS ')]==[expected]
    assert [s for s in result.splitlines() if s.startswith('PASS ')]==[expected]
    assert fingerprint(tracked)==report['source']
    artifacts=[p for p in out.rglob('*') if p.is_file() and p.name!='report.json']
    report.update(status='PASS_HIERARCHY_TOOL_PROBE_ONLY',artifacts=fingerprint(artifacts))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'])
