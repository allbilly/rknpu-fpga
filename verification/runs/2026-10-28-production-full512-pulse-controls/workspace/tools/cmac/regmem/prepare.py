#!/usr/bin/env python3
"""Freeze registered RAM controls around the unchanged qualified full512 pipe.

Source preparation only. Fresh whole-board native evidence and root electrical
review are required before implementation; no vendor tools are launched here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.cmac.balanced_max.prepare import require,digest,read,copy
from tools.evidence import timestamp

MEMORY='rtl/cmac/experimental/rk_cmac_demo_memory_regport.sv'
DEMO='rtl/cmac/experimental/rk_cmac_array_bram_demo_regmem.sv'
TOP='fpga/cmac/startup/ypcb_cmac_array_regmem_top.sv'
BENCH='tests/cmac/startup/tb_array_startup.sv'
REPLACEMENTS={'rtl/cmac/rk_cmac_demo_memory.sv':MEMORY,
              'rtl/cmac/rk_cmac_array_bram_demo.sv':DEMO,
              'fpga/cmac/startup/ypcb_cmac_array_startup_top.sv':TOP}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-package',type=Path,required=True)
    ap.add_argument('--memory-iverilog-report',type=Path,required=True)
    ap.add_argument('--memory-verilator-report',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();parent=args.parent_package.resolve();basis=read(parent/'report.json')
    require(basis['status']=='PREPARED_PIPELINED_FULL512_CHECKPOINT_ONLY' and
            (basis['channels'],basis['kernels'],basis['parallel_products'],basis['clock_period_ns'])==(32,16,512,20),
            'Wrong qualified arithmetic basis')
    for sim,path in [('iverilog',args.memory_iverilog_report),('verilator',args.memory_verilator_report)]:
        r=read(path);require(r['status']=='PASS_REGISTERED_BRAM_PORT_MEMORY_NATIVE_ONLY' and r['simulator']==sim,
                            'Missing fresh complete memory contract')
        for name,h in r['source']['files'].items():require(digest(ROOT/name)==h,'Memory input changed '+name)
        for name,h in r['artifacts']['files'].items():require(digest(ROOT/name)==h,'Memory artifact changed '+name)
        require(all(c['status']=='PASS' and c['returncode']==0 for c in r['commands']),'Failed memory command')
    out=args.out.resolve();require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh package required')
    out.mkdir(parents=True);source=out/'source'
    for name,h in basis['source']['files'].items():
        require(digest(parent/'source'/name)==h,'Changed parent snapshot '+name)
        copy(parent/'source'/name,source/name)
    for name in [MEMORY,DEMO,TOP,'tools/cmac/regmem/run_memory.py','tools/cmac/regmem/prepare.py']:
        copy(ROOT/name,source/name)
    original=(ROOT/BENCH).read_text();old='ypcb_cmac_array_startup_top #'
    require(original.count(old)==1,'Changed original board bench')
    (source/BENCH).write_text(original.replace(old,'ypcb_cmac_array_regmem_top #'))
    names={str(p.relative_to(source)):digest(p) for p in source.rglob('*') if p.is_file()}
    manifest=''.join(h+'  '+n+'\n' for n,h in sorted(names.items()))
    selected_source=dict(files=dict(sorted(names.items())),sha256=hashlib.sha256(manifest.encode()).hexdigest())
    text=(parent/'build.tcl').read_text();require(digest(parent/'build.tcl')==basis['build_tcl_sha256'],'Changed parent Tcl')
    text=text.replace(str(parent/'source'),str(source)).replace(str(parent/'implementation'),str(out/'implementation'))
    text=text.replace(basis['source']['sha256'],selected_source['sha256'])
    for before,after in REPLACEMENTS.items():
        old_read='read_verilog -sv {'+str(source/before)+'}'
        require(text.count(old_read)==1,'Changed read selection '+before)
        text=text.replace(old_read,'read_verilog -sv {'+str(source/after)+'}')
    require(text.count('synth_design -top ypcb_cmac_array_startup_top ')==1,'Changed synth top')
    text=text.replace('synth_design -top ypcb_cmac_array_startup_top ','synth_design -top ypcb_cmac_array_regmem_top ')
    require(text.count('require_full_dsp_cmac\n')==2 and 'Expected 512 retained parallel CMAC DSP products.' in text,
            'Lost full512 retention gates')
    require('20.0' in text and 'Negative $delay_type slack' in text and
            'if {$emit_bitstream} { error "Bitstream emission is disabled' in text,'Lost physical/image guards')
    (out/'build.tcl').write_text(text)
    selected=[REPLACEMENTS.get(n,n) for n in basis['synthesis_sources']]
    qualification=out/'qualification'
    for name,p in [('memory-iverilog',args.memory_iverilog_report),('memory-verilator',args.memory_verilator_report),
                   ('arithmetic-basis',parent/'report.json')]:copy(p,qualification/(name+'.json'))
    report=dict(status='PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY',created_utc=timestamp(),
        scope='Same full512 two-stage arithmetic; synchronous BRAM-facing controls/index, fresh raw-board tests required before implementation',
        top='ypcb_cmac_array_regmem_top',part='xc7k480tffg1156-2',channels=32,kernels=16,parallel_products=512,
        pipeline_stages=2,clock_period_ns=20,source=selected_source,synthesis_sources=selected,
        hardware_inputs={n:names[n] for n in selected},build_tcl_sha256=digest(out/'build.tcl'),
        parent_package=str(parent),parent_report_sha256=digest(parent/'report.json'),
        fresh_board_native_required=True,fresh_synthesis_drc_and_timing_required=True,
        vivado_executed=False,bitstream_emitted=False,hardware_programmed=False,
        qualification_reports={p.name:digest(p) for p in qualification.iterdir()})
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'report.json')


if __name__=='__main__':main()
