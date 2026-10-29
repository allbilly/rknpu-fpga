#!/usr/bin/env python3
"""Full C32/K16 fixed-mode experiment, retaining the original unit assertions.

Requires source-matching donor baseline, passing row simulation and formal
checks, area report and hierarchy tool probe.
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
from evidence import ROOT,fingerprint,timestamp

p=argparse.ArgumentParser(description=__doc__)
for name in ('flat','rows','area','probe'): p.add_argument('--'+name+'-report',type=Path,required=True)
a=p.parse_args()
parents={name:json.loads(getattr(a,name+'_report').read_text()) for name in ('flat','rows','area','probe')}
flat,rows,area,probe=[parents[n] for n in ('flat','rows','area','probe')]
assert flat['status']=='PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY'
assert (flat['channels'],flat['kernels'])==(32,16)
assert rows['status']=='PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY'
assert rows['formal_result']=='PASS_COMPOSED_POST_CONFIGURATION_ROWS_AND_ACTIVE_COMPARE'
assert {Path(c['log']).stem for c in rows['commands']} >= {'formal_control','formal_datapath'}
assert all(c['status']=='PASS' and c['returncode']==0 for c in rows['commands'])
assert rows['simulation_result']=='PASS fixed FP16 rows comparisons=2097152 resets=4 seed=3588f016; post-configuration only'
assert all(c['status']=='PASS' for c in rows['commands'] if Path(c['log']).stem in ('compile','test'))
assert {Path(c['log']).stem for c in rows['commands']} >= {'compile','test'}
assert area['status']=='PASS_FIXED_FP16_ROW_AREA_ONLY'
assert probe['status']=='PASS_HIERARCHY_TOOL_PROBE_ONLY' and probe['explicit_library_call_files']
def verify(manifest):
    for name,sha in manifest['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
for name,parent in parents.items():
    verify(parent['source'])
    verify(parent['artifacts'])
vr=flat['vectors'];verify(vr['source']);verify(vr['artifacts'])
assert (vr['frames'],vr['outputs'],vr['seed'])==(208,3328,'0x35883216')
donor=ROOT/'rtl/vendor/nvdla';experimental=ROOT/'rtl/cmac/experimental'
cell=experimental/'rk_cmac_fp16_cell_fixed.sv';array=experimental/'rk_cmac_fp16_array_fixed.sv'
row_source=experimental/'rk_cmac_fp16_rows.sv'
assert str(row_source.relative_to(ROOT)) in rows['source']['files']
original_cell=ROOT/'rtl/cmac/rk_cmac_fp16_cell.sv';original_array=ROOT/'rtl/cmac/rk_cmac_fp16_array.sv'
original_instance='''        NV_NVDLA_CMAC_CORE_MAC_mul donor(
            .nvdla_core_clk(clk),.nvdla_core_rstn(rst_n),.cfg_is_fp16(1'b1),
            .cfg_is_int8(1'b0),.cfg_reg_en(1'b1),.exp_sft(maximum-exponent[i]),
            .op_a_dat({b[i][15],bm}),.op_a_nz({2{pair_nz}}),.op_a_pvld(1'b1),
            .op_b_dat({a[i][15],am}),.op_b_nz({2{pair_nz}}),.op_b_pvld(1'b1),
            .res_a(row_a[i]),.res_b(row_b[i]),.res_tag(row_tag[i]));'''
fixed_instance='''        rk_cmac_fp16_rows donor(
            .op_a({b[i][15],bm}),.op_b({a[i][15],am}),.pair_nz,
            .exp_sft(maximum-exponent[i]),
            .res_a(row_a[i]),.res_b(row_b[i]),.res_tag(row_tag[i]));'''
def replace(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new)
expected=replace(original_cell.read_text(),'module rk_cmac_fp16_cell #','module rk_cmac_fp16_cell_fixed #')
expected=replace(expected,'    input wire clk,rst_n,\n','')
expected=replace(expected,original_instance,fixed_instance)
assert cell.read_text()==expected,'Experimental cell has changes beyond the audited fixed-mode substitution'
expected=replace(original_array.read_text(),'module rk_cmac_fp16_array #','module rk_cmac_fp16_array_fixed #')
expected=replace(expected,'rk_cmac_fp16_cell #','rk_cmac_fp16_cell_fixed #')
expected=replace(expected,'            .clk,.rst_n,.data(in_data)','            .data(in_data)')
assert array.read_text()==expected,'Warmup, flow, tags, reset and error logic must remain unchanged'
out=ROOT/f'build/rknpu-cmac-array/c32k16/fixed-hierarchical-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
bench_source=ROOT/'tests/cmac/tb_cmac_fp16_array.sv';bench=out/bench_source.name
bench.write_text(replace(bench_source.read_text(),'rk_cmac_fp16_array #','rk_cmac_fp16_array_fixed #'))
snapshots=[]
for name,parent in parents.items():
    path=out/(name+'_report_snapshot.json');path.write_text(json.dumps(parent,indent=2)+'\n');snapshots.append(path)
params=ROOT/'tools/cmac/empty_hier_parameters.v';control=ROOT/'tools/cmac/fixed_array_hierarchy.vlt'
sources=[donor/n for n in ('compat/nv_assert_never.v','compat/nv_assert_no_x.v','NV_DW02_tree.v','NV_NVDLA_CMAC_CORE_MAC_mul.v')]+[row_source]
tracked=sources+[cell,array,original_cell,original_array,bench_source,bench,params,control,Path(__file__).resolve()]+snapshots
tracked += [donor/n for n in ('nv_assert_never.vlib','nv_assert_no_x.vlib','assertion_header.h','assertion_task.h')]
for path in tracked:
    dest=out/'snapshot'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(path.read_bytes())
allowed={tuple(w[:3]) for w in flat['donor_warnings']};allowed.add(('DECLFILENAME',str(cell),'5'))
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),vectors=vr,
            channels=32,kernels=16,parallel_products=512,commands=[],
            row_formal_status_at_start=rows.get('formal_result','NOT_COMPLETED'),
            scope='Experimental fixed-mode full array. Exact original numerical/hold/tag/reset assertions and corpus, unchanged configured-ready gate. Not raw integration, four-state, formal signoff, mapped fit/timing, FPGA or RK evidence.')
def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
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
        assert code==0 and 'ERROR :' not in text,text[-5000:]
        warnings=re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:',text,re.M)
        assert len(warnings)==len(re.findall(r'^%Warning-',text,re.M))
        step_allowed=set(allowed if lint else ())
        if name=='top_generate':
            wrapper=out/'cell/rk_cmac_fp16_cell_fixed_b.sv'
            wrapper_lines=wrapper.read_text().splitlines()
            assert wrapper_lines[51]=='    time last_combo_seqnum__V;'
            diagnostic=('UNUSEDSIGNAL',str(wrapper),'52')
            if diagnostic in warnings:
                assert warnings.count(diagnostic)==1
                expected_line=f"%Warning-UNUSEDSIGNAL: {wrapper}:52:10: Signal is not used: 'last_combo_seqnum__V'"
                assert expected_line in text.splitlines()
                step_allowed.add(diagnostic)
                step['generated_wrapper_diagnostic']='Unused timestamp in Verilator 5.048 combinational protectlib wrapper'
        assert set(warnings)<=step_allowed,warnings
        assert not re.search(r'%Error|warning:|sorry:',text,re.I),text[-5000:]
        step.update(status='PASS',warning_locations=[list(w) for w in warnings]);return text
    except Exception: step['status']='FAIL';raise
    finally: step['seconds']=round(time.monotonic()-start,3);save()
save()
try:
    report['tool_version']=run(['verilator','--version'],'version').splitlines()[0]
    assert report['tool_version']==flat['tool_version']==probe['tool_version']==rows['tool_version']
    report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
    flags=['--timing','--assert','-Wall','-Wno-fatal','--timescale-override','1ns/1ps','-DDESIGNWARE_NOEXIST','-DASSERT_ON',f'-I{donor}']
    optimization='OPT_FAST=-O2 OPT_SLOW=-O2 OPT_GLOBAL=-O2'
    block='rk_cmac_fp16_cell_fixed_b';libdir=out/'cell';obj=out/'top'
    run(['verilator','--cc','--build','-j','2',*flags,'-MAKEFLAGS',optimization,
         '--Mdir',libdir,'--prefix','V'+block,'--mod-prefix','V'+block,
         '--top-module-encoded',block,'--lib-create',block,'--hierarchical-child','1',
         '--hierarchical-block','rk_cmac_fp16_cell_fixed,'+block,control,*sources,cell],'cell_compile',True)
    wrapper=libdir/(block+'.sv');library=libdir/('lib'+block+'.a')
    assert wrapper.is_file() and library.is_file()
    for pattern in (r'input logic \[511:0\]\s+data',r'input logic \[511:0\]\s+weight',r'input logic \[31:0\]\s+data_mask',r'output logic \[43:0\]\s+result'):
        assert re.search(pattern,wrapper.read_text()),pattern
    obj.mkdir();(obj/'Vtb_cmac_fp16_array_hier.mk').write_text('VM_HIER_LIBS := '+str(library)+'\n')
    run(['verilator','--cc','--main','--exe',*flags,'-GATOMIC_C=32','-GATOMIC_K=16',
         '--top-module',bench.stem,'--Mdir',obj,'-o','sim','--hierarchical-block','rk_cmac_fp16_cell_fixed,'+block,
         '--hierarchical-params-file',params,'-LDFLAGS',library,wrapper,*sources,cell,array,bench],'top_generate',True)
    top_cpp=list(obj.glob('Vtb_cmac_fp16_array*.cpp'));called=set()
    for path in top_cpp:
        for operation in ('create','combo_update','seq_update'):
            if re.search(r'\b'+block+'_protectlib_'+operation+r'\s*\(',path.read_text()):called.add(operation)
    assert {'create','combo_update'}<=called,'Missing real combinational library calls'
    assert not any('NV_NVDLA_CMAC_CORE_MAC_' in path.name or 'rk_cmac_fp16_rows' in path.name for path in top_cpp),'Embedded donor arithmetic bypasses library'
    report['library_operations']=sorted(called);save()
    run(['make','-C',obj,'-f','Vtb_cmac_fp16_array.mk','-j','2',*optimization.split()],'top_compile')
    result=run([obj/'sim',f'+VECTORS={ROOT/"build/rknpu-cmac-array/c32k16/vectors.hex"}','+COUNT=208'],'test')
    assert [line for line in result.splitlines() if line.startswith('PASS ')]==[flat['result']],result
    assert fingerprint(tracked)==report['source']
    for name,parent in parents.items():
        verify(parent['source'])
        verify(parent['artifacts'])
    verify(vr['source']);verify(vr['artifacts'])
    generated=[path for d in (libdir,obj) for path in d.rglob('*') if path.is_file()]
    report.update(status='PASS_FIXED_MODE_CMAC_NATIVE_EXPERIMENT_ONLY',result=flat['result'],
                  artifacts=fingerprint(generated+[ROOT/c['log'] for c in report['commands']]))
except Exception as exc: report.update(status='FAIL',reason=str(exc));raise
finally: report['finished_utc']=timestamp();save();print(out/'report.json')
print(report['status'],report['result'])
