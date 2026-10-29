#!/usr/bin/env python3
"""Freeze the full512 registered-preparation candidate; never execute Vivado.

The new in-flight busy signal is connected explicitly. Old source reports are
kept as component history, never relabeled as current pipeline verification.
Fresh mapped/startup/timing/DRC review remains required before any image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.cmac.pipeline import run as native
from tools.cmac.balanced_max.prepare import copy,digest,read,require
from tools.evidence import timestamp


def native_report(path,simulator):
    r=read(path)
    require(r['status']=='PASS_FULL512_TWO_STAGE_NATIVE_ONLY' and r['simulator']==simulator and
            (r['channels'],r['kernels'],r['parallel_products'],r['pipeline_stages'],r['frames'],r['outputs'])
            ==(32,16,512,2,208,3328),'Incomplete or wrong pipeline native evidence')
    for name,h in r['source']['files'].items():require(digest(ROOT/name)==h,'Changed native source '+name)
    for name,h in r['artifacts']['files'].items():require(digest(ROOT/name)==h,'Changed native artifact '+name)
    require(digest(r['compiled_image']['path'])==r['compiled_image']['sha256'],'Changed native image')
    names=['version']+(['runtime_version'] if simulator=='iverilog' else [])+['compile','negative','actual']
    require([c['name'] for c in r['commands']]==names and all(c['status']=='PASS' for c in r['commands']),
            'Incomplete pipeline command plan')
    require(r['commands'][-2]['returncode']!=0 and r['commands'][-1]['returncode']==0,'Missing oracle rejection/completion')
    for c in r['commands']:
        require(digest(Path(path).parent/(c['name']+'.log'))==c['log_sha256'],'Native log changed')
    return r


def wrapper_text(original):
    replacements=[
        ('    wire group_ready,group_valid,group_error,bank_ready,bank_valid,bank_busy,bank_error;',
         '    wire group_busy;\n    wire group_ready,group_valid,group_error,bank_ready,bank_valid,bank_busy,bank_error;'),
        ('(group_valid||bank_busy)','(group_busy||bank_busy)'),
        ('rk_cmac_fp16_array_dsp_prefix #','rk_cmac_fp16_array_dsp_prefix_pipe #'),
        ('.out_tag(group_tag),.error(group_error));','.out_tag(group_tag),.error(group_error),.busy(group_busy));')]
    for old,new in replacements:
        require(original.count(old)==1,'Changed original wrapper contract: '+old)
        original=original.replace(old,new)
    return original


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent-package',type=Path,required=True)
    ap.add_argument('--iverilog-report',type=Path,required=True)
    ap.add_argument('--verilator-report',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();parent=args.parent_package.resolve();original=read(parent/'report.json')
    require((original['channels'],original['kernels'],original['parallel_products'],original['clock_period_ns'])
            ==(32,16,512,20),'Wrong original full geometry/clock')
    checked=subprocess.run([sys.executable,str(ROOT/'tools/cmac/startup/prepare.py'),'verify',str(parent)],
        cwd=ROOT,capture_output=True,text=True,timeout=300)
    require(checked.returncode==0,'Original current-parent verification failed: '+checked.stderr[-2000:])
    admission=json.loads(checked.stdout)
    require(admission['external_parent_current'] is True and admission['blockers']==['Missing board reviewer'],
            'Unresolved original source/arithmetic gate')
    reports={s:native_report(p,s) for s,p in [('iverilog',args.iverilog_report),('verilator',args.verilator_report)]}
    out=args.out.resolve();require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh package required')
    out.mkdir(parents=True);snapshot=out/'source'
    for name,h in original['source']['files'].items():
        require(digest(parent/'source'/name)==h and digest(ROOT/name)==h,'Original source changed '+name)
        copy(parent/'source'/name,snapshot/name)
    for name in [native.CELL,native.ARRAY,'tools/cmac/pipeline/run.py','tools/cmac/pipeline/prepare.py',
                 'tools/cmac/balanced_max/run.py','tools/cmac/balanced_max/prepare.py']:
        copy(ROOT/name,snapshot/name)
    old_wrapper=next(n for n in original['synthesis_sources'] if n.endswith('/rk_cmac_cacc_fp16_array.sv'))
    generated='generated/rk_cmac_cacc_fp16_array.sv';(snapshot/'generated').mkdir()
    (snapshot/generated).write_text(wrapper_text((snapshot/old_wrapper).read_text()))
    files={str(p.relative_to(snapshot)):digest(p) for p in snapshot.rglob('*') if p.is_file()}
    manifest=''.join(h+'  '+n+'\n' for n,h in sorted(files.items()))
    source=dict(files=dict(sorted(files.items())),sha256=hashlib.sha256(manifest.encode()).hexdigest())
    text=(parent/'build.tcl').read_text();require(digest(parent/'build.tcl')==original['build_tcl_sha256'],'Original Tcl changed')
    text=text.replace(str(parent/'source'),str(snapshot)).replace(str(parent/'implementation'),str(out/'implementation'))
    text=text.replace(original['source']['sha256'],source['sha256'])
    old='read_verilog -sv {'+str(snapshot/old_wrapper)+'}'
    require(text.count(old)==1,'Changed wrapper read')
    text=text.replace(old,'read_verilog -sv {'+str(snapshot/generated)+'}')
    require(text.count('read_xdc {')==1,'Changed clock/pin constraint read')
    extra=''.join('read_verilog -sv {'+str(snapshot/n)+'}\n' for n in [native.CELL,native.ARRAY])
    text=text.replace('read_xdc {',extra+'read_xdc {')
    old_filter='ORIG_REF_NAME == rk_cmac_fp16_cell_dsp_prefix || REF_NAME == rk_cmac_fp16_cell_dsp_prefix'
    require(text.count(old_filter)==1 and text.count('require_full_dsp_cmac\n')==2,'Missing full512 retention checks')
    text=text.replace(old_filter,old_filter.replace('rk_cmac_fp16_cell_dsp_prefix','rk_cmac_fp16_cell_dsp_prefix_pipe'))
    require('if {$emit_bitstream} { error "Bitstream emission is disabled' in text and
            '20.0' in text and 'Negative $delay_type slack' in text,'Lost original physical gates')
    (out/'build.tcl').write_text(text)
    qualification=out/'qualification'
    for name,path in [('iverilog',args.iverilog_report),('verilator',args.verilator_report),
                      ('original-preparation',parent/'report.json')]:copy(path,qualification/(name+'.json'))
    selected=[generated if n==old_wrapper else n for n in original['synthesis_sources']]
    selected += [native.CELL,native.ARRAY,'fpga/cmac/startup/ypcb_cmac_array_startup.xdc']
    report=dict(status='PREPARED_PIPELINED_FULL512_CHECKPOINT_ONLY',created_utc=timestamp(),
        scope='Actual registered preparation stage; full512 native numeric/protocol evidence, no mapped/physical/RK acceptance',
        channels=32,kernels=16,parallel_products=512,pipeline_stages=2,clock_period_ns=20,
        top='ypcb_cmac_array_startup_top',part='xc7k480tffg1156-2',source=source,
        synthesis_sources=selected,hardware_inputs={n:files[n] for n in selected},build_tcl_sha256=digest(out/'build.tcl'),
        original_parent_package=str(parent),original_parent_report_sha256=digest(parent/'report.json'),
        original_verification=admission,qualification_reports={p.name:digest(p) for p in qualification.iterdir()},
        external_native_reports={s:str(p.resolve()) for s,p in [('iverilog',args.iverilog_report),('verilator',args.verilator_report)]},
        external_qualification_must_be_rechecked_before_build=True,
        busy_contract='Includes preparation and output ownership; cancel/reset invalidate every pending frame',
        original_raw_board_reports_reused_as_new_candidate_pass=False,
        fresh_mapped_and_startup_review_required_before_bitstream=True,electrical_review_required=True,
        vivado_executed=False,bitstream_emitted=False,hardware_programmed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(out/'report.json')


if __name__=='__main__':main()
