#!/usr/bin/env python3
"""Freeze a new dual endpoint and checkpoint-only Vivado command. Never run it."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.hardware.sample_ew import tcl_literal
from tools.tinystories.joined_hierarchy import hierarchy_json, EXPECTED

DROP={'rtl/cmac/experimental/rk_cmac_demo_memory_regport.sv','rtl/cmac/rk_cmac_array_demo_rom.sv',
      'rtl/cmac/experimental/rk_cmac_array_bram_demo_regmem.sv',
      'fpga/cmac/startup/ypcb_cmac_array_regmem_top.sv','fpga/cmac/startup/ypcb_cmac_array_startup.xdc'}
CURRENT=['rtl/rk_fp16_alu.sv','rtl/rk_ew_regs.sv','rtl/rk_ew_engine.sv','rtl/rk_ew_dma.sv','rtl/rk_job_control.sv',
         'rtl/host/rk_jtag_backend.sv','rtl/tinystories/rk_shared_bram_regport.sv',
         'rtl/tinystories/rk_cmac_success_rearm.sv','rtl/tinystories/rk_jtag_dual_bram.sv',
         'rtl/vendor/opentpu/otpu_jtag_mailbox.sv','fpga/tinystories/ypcb_tinystories_top.sv']
BUILD=['fpga/ew_checkpoint.tcl.in','fpga/host/ypcb_jtag_ew.xdc','fpga/host/mailbox_cdc.tcl',
       'fpga/tinystories/checks.tcl','tools/tinystories/prepare_fpga.py',
       'rtl/vendor/opentpu/LICENSE','rtl/vendor/opentpu/PROVENANCE.json','rtl/vendor/nvdla/LICENSE']
IMAGE_ONLY={'rtl/vendor/opentpu/otpu_jtag_mailbox.sv','fpga/tinystories/ypcb_tinystories_top.sv'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(condition,message):
    if not condition:raise ValueError(message)
def read(path):return json.loads(Path(path).read_text())
def manifest(files):
    return dict(files=dict(sorted(files.items())),sha256=hashlib.sha256(''.join(h+'  '+n+'\n' for n,h in sorted(files.items())).encode()).hexdigest())


def validate_native(path,simulator,origins):
    path=Path(path).resolve();record=read(path)
    need(record['status']=='PASS_TRAINED_TILE_DUAL_RAW_ENDPOINT_'+simulator.upper()+'_ONLY' and
         record['products']==512 and record['hardware_accessed'] is False,'Missing completed exact joined suite')
    need([t['mode'] for t in record['tests']]==[0,1,2,3,4] and all(t['status']=='PASS' for t in record['tests']),
         'Missing joined numerical/reset/fault coverage')
    need(all(c['status']=='PASS' and c['returncode']==0 for c in record['commands']),'Failed native command')
    # Recheck the actual producer snapshot if an auditor-only driver later
    # changed. Current synthesis RTL must independently match the executed RTL.
    snapshots=read(path.parent/'live-source-snapshot.json') if (path.parent/'live-source-snapshot.json').exists() else {}
    for name,value in record['inputs'].items():
        if Path(name).is_file() and sha(name)==value:continue
        saved=snapshots.get(name)
        need(saved is not None and saved['sha256']==value and sha(saved['snapshot'])==value,'Changed native source/provenance')
    for name,origin in origins.items():
        if name in IMAGE_ONLY:continue
        need(record['inputs'].get(str(origin))==sha(origin),'Synthesis source differs from executed source: '+name)
    binary=Path(record['binary']['path'])
    need(sha(binary)==record['binary']['sha256'],'Changed executed native binary')
    for c in record['commands']:
        need(sha(path.parent/(c['name']+'.log'))==c['log_sha256'],'Changed native log')
    if simulator=='verilator':
        need(hierarchy_json(path.parent/'hierarchy.tree.json')==EXPECTED,'Changed native full512/controller hierarchy')
    else:
        text=binary.read_text()
        for name,count in EXPECTED.items():
            need(len(re.findall(r'\.scope module, "[^"]*" "'+name+r'"',text))==count,'Changed native reachable instance count')
    return record


def render(directory,source,selected):
    root=directory/'source';out=directory/'implementation'
    text=(root/'fpga/ew_checkpoint.tcl.in').read_text()
    reads=['set_property include_dirs [list '+tcl_literal(root/'rtl/vendor/nvdla')+'] [current_fileset]',
           'set_property verilog_define {DESIGNWARE_NOEXIST} [current_fileset]']
    reads += ['read_verilog -sv '+tcl_literal(root/name) for name in selected]
    values=dict(ROOT=tcl_literal(root),OUT=tcl_literal(out),SOURCE_SHA=source['sha256'],
        TOP='ypcb_tinystories_top',CONSTRAINTS=tcl_literal(root/'fpga/host/ypcb_jtag_ew.xdc'),READ_SOURCES='\n'.join(reads))
    for key,value in values.items():
        token='@'+key+'@';need(text.count(token)==1,'Changed checkpoint template');text=text.replace(token,value)
    text=text.replace('RK_EW_PREPARED_SHA','RK_TINYSTORIES_PREPARED_SHA')
    native='synth_design -top ypcb_tinystories_top -part xc7k480tffg1156-2 -generic LED_ACTIVE_LOW=$::env(RK_LED_ACTIVE_LOW)'
    need(text.count(native)==1,'Changed synthesis boundary')
    text=text.replace(native,native+' -flatten_hierarchy none')
    before='file mkdir $out'
    guard='''if {$voltage != 1.8 || $cfgbvs ne "GND" || $::env(RK_LED_ACTIVE_LOW) ne "0"} {
    error "Use only the separately reviewed1.8V/GND/noninverted logical-pad profile"
}
'''
    text=text.replace(before,guard+before)
    marker='set clocks [get_clocks -quiet sys_clk]'
    text=text.replace(marker,'source '+tcl_literal(root/'fpga/host/mailbox_cdc.tcl')+'\n'
        +'source '+tcl_literal(root/'fpga/tinystories/checks.tcl')+'\nrk_host_cdc_constrain\n'
        +'rk_dual_full512\nrk_dual_registered_reset $out synthesized\n'+marker)
    text=text.replace('route_design\n','route_design\nrk_dual_full512\nrk_dual_registered_reset $out routed\n')
    marker='foreach check {no_clock unconstrained_internal_endpoints}'
    need(text.count(marker)==1,'Changed timing boundary')
    text=text.replace(marker,'''rk_host_cdc_audit $out
rk_dual_require [expr {[llength [get_clocks]] == 2}] "Unexpected clock inventory"
rk_dual_require [expr {[llength [get_waivers]] == 0}] "Waivers forbidden"
rk_dual_require [expr {[report_route_status -boolean_check ROUTED_FULLY] == 1 &&
    [report_route_status -boolean_check ERRORS_IN_ROUTES] == 0}] "Routing incomplete/errors"
rk_dual_pulse_gate [report_pulse_width -return_string]
'''+marker)
    expected='[dict create '+' '.join(tcl_literal(root/name)+' '+value for name,value in source['files'].items())+']'
    pin='''set expected_inputs '''+expected+'''
proc rk_dual_pin_inputs {} {
    global expected_inputs
    dict for {path expected} $expected_inputs {
        set output [exec sha256sum -z -- $path]
        if {![regexp {^([0-9a-f]{64})[ \\t]} $output -> actual] || $actual ne $expected} {
            error "Changed prepared source input"
        }
    }
}
rk_dual_pin_inputs
'''
    text=pin+text+'\nrk_dual_pin_inputs\nputs PASS_TINYSTORIES_FULL512_DUAL_ROUTED_CHECKPOINT_ONLY\n'
    need(not re.search(r'@[A-Z_]+@|^\s*(write_bitstream|open_hw\w*|program_hw\w*|set_clock_groups)\b',text,re.M),'Forbidden native action/template residue')
    return text


def prepare(parent,iverilog,verilator,out):
    parent,out=Path(parent).resolve(),Path(out).resolve();basis=read(parent/'report.json')
    need(basis['status']=='PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY','Wrong full512 arithmetic basis')
    for name,h in basis['source']['files'].items():need(sha(parent/'source'/name)==h,'Changed frozen arithmetic basis')
    selected=[n for n in basis['synthesis_sources'] if n not in DROP and n.endswith(('.v','.sv'))]
    need('generated/rk_cmac_cacc_fp16_array.sv' in selected and 'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix_pipe.sv' in selected,
         'Missing exact pipelined arithmetic')
    origins={n:parent/'source'/n for n in selected}
    for name in CURRENT:
        need(name not in origins,'Duplicate synthesis definition');origins[name]=ROOT/name;selected.append(name)
    records={sim:validate_native(path,sim,origins) for sim,path in [('iverilog',iverilog),('verilator',verilator)]}
    need(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh in-workspace package required')
    out.mkdir(parents=True)
    # Include assertion headers, licenses and the actual selected old generator
    # output, even though native executables are not FPGA source files.
    files={}
    def copy(path,name):
        dest=out/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(Path(path).read_bytes());files[name]=sha(dest)
    for name,path in origins.items():copy(path,name)
    for name,h in basis['source']['files'].items():
        if name.startswith('rtl/vendor/nvdla/') and name not in files:copy(parent/'source'/name,name)
    for name in BUILD:
        if name not in files:copy(ROOT/name,name)
    source=manifest(files)
    command=render(out,source,selected);(out/'build.tcl').write_text(command)
    evidence={}
    for sim,path in [('iverilog',iverilog),('verilator',verilator)]:
        data=Path(path).read_bytes();(out/(sim+'.json')).write_bytes(data);evidence[sim]=dict(path=str(Path(path).resolve()),sha256=sha(path))
    report=dict(status='PREPARED_TINYSTORIES_FULL512_DUAL_CHECKPOINT_ONLY',source=source,synthesis_sources=selected,
        arithmetic_basis_sha256=basis['source']['sha256'],native=evidence,top='ypcb_tinystories_top',part='xc7k480tffg1156-2',
        products=512,memory_bytes=1048576,clock_period_ns=20,tck_period_ns=166.666,
        build_tcl_sha256=sha(out/'build.tcl'),vivado_executed=False,bitstream_emitted=False,hardware_programmed=False,
        scope='New source-bound full512 CMAC/EW/USER2 checkpoint preparation; no physical/image/full-model inference acceptance')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    need(all(sha(out/'source'/n)==h for n,h in source['files'].items()),'Snapshot changed during preparation')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arithmetic',type=Path,required=True)
    parser.add_argument('--iverilog',type=Path,required=True)
    parser.add_argument('--verilator',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result=prepare(args.arithmetic,args.iverilog,args.verilator,args.out)
    print(result['status'],result['source']['sha256'])


if __name__=='__main__':main()
