#!/usr/bin/env python3
"""Full512 two-stage CMAC qualification; no implementation or hardware calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.cmac.balanced_max import run as base
from tools.evidence import fingerprint,timestamp

CELL='rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix_pipe.sv'
ARRAY='rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix_pipe.sv'
SOURCES=base.SOURCES[:-4]+[CELL,ARRAY]


def bench_text():
    text=(ROOT/base.BENCH).read_text()
    old='rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);'
    base.require(text.count(old)==1,'Changed original bench instance')
    text=text.replace(old,'wire busy;\n    rk_cmac_fp16_array_dsp_prefix_pipe #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);')
    old='''            tick();
            if(!out_valid||error||out_groups!==expected||out_tag!==35'(i))'''
    new='''            tick();
            if(out_valid||error||!busy||!in_ready)$fatal(1,"preparation-stage contract");
            @(negedge clk);in_valid=0;in_data='1;in_weight='1;in_tag='1;
            tick();
            if(!out_valid||error||!busy||out_groups!==expected||out_tag!==35'(i))'''
    base.require(text.count(old)==1,'Changed original corpus acceptance check')
    text=text.replace(old,new)
    boundary='        end\n`ifndef VERILATOR'
    base.require(text.count(boundary)==1,'Changed original corpus loop end')
    extra='''            if(i==0||(i+1)%16==0)begin $display("PROGRESS pipeline_frames=%0d",i+1);$fflush();end
        end
        // Fill both stages, hold both, and drain in order at one result/cycle.
        reset_all();
        @(negedge clk);{in_data,in_weight,in_data_mask,in_weight_mask,expected}=vectors[2];
        burst_first=expected;in_tag=35'h1001;in_valid=1;tick();
        if(out_valid||!in_ready||!busy||error)$fatal(1,"burst preparation");
        @(negedge clk);{in_data,in_weight,in_data_mask,in_weight_mask,expected}=vectors[5];
        burst_second=expected;in_tag=35'h1002;tick();
        if(!out_valid||out_groups!==burst_first||out_tag!==35'h1001||in_ready||!busy||error)
            $fatal(1,"two-stage fill or first result");
        @(negedge clk);in_valid=0;in_data='1;in_weight='1;in_tag='1;
        repeat(3)begin
            tick();
            if(!out_valid||out_groups!==burst_first||out_tag!==35'h1001||in_ready||!busy||error)
                $fatal(1,"full pipeline did not hold");
        end
        @(negedge clk);out_ready=1;tick();
        if(!out_valid||out_groups!==burst_second||out_tag!==35'h1002||!busy||error)
            $fatal(1,"queued second result lost or reordered");
        tick();if(out_valid||busy||!in_ready||error)$fatal(1,"pipeline drain");
        // Cancel a preparation-stage frame before it can become output-valid.
        reset_all();
        @(negedge clk);{in_data,in_weight,in_data_mask,in_weight_mask,expected}=vectors[3];
        in_tag=35'h1003;in_valid=1;tick();
        if(out_valid||!busy)$fatal(1,"missing prepared frame before reset");
        reset_all();repeat(3)begin tick();if(out_valid||busy||error)$fatal(1,"stale prepared frame after reset");end
        $display("CHECK pipeline_contract latency=2 burst_outputs=32 prepared_reset_canceled=16");
`ifndef VERILATOR'''
    text=text.replace(boundary,extra)
    text=text.replace('logic [ATOMIC_K*44-1:0] out_groups,expected;',
        'logic [ATOMIC_K*44-1:0] out_groups,expected,burst_first,burst_second;')
    return text


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--simulator',choices=('iverilog','verilator'),required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();out=args.out.resolve()
    base.require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh output required')
    out.mkdir(parents=True)
    bench=out/'tb_cmac_fp16_array.sv';bench.write_text(bench_text())
    vectors=base.VECTOR_ROOT/'vectors.hex';vr=json.loads((base.VECTOR_ROOT/'vectors_report.json').read_text())
    base.require(vr['seed']=='0x35883216' and vr['frames']==208 and vr['outputs']==3328,'Wrong unchanged corpus')
    base.require(vr['artifacts']['files'][str(vectors.relative_to(ROOT))]==base.digest(vectors),'Changed oracle corpus')
    rows=vectors.read_text().splitlines();base.require(len(rows)==208,'Wrong frame count')
    rows[0]=format(int(rows[0],16)^1,'0'+str(len(rows[0]))+'x')
    negative=out/'negative.hex';negative.write_text('\n'.join(rows)+'\n')
    tracked=[ROOT/n for n in SOURCES+[base.BENCH]]+[Path(__file__),Path(base.__file__),ROOT/'tools/evidence.py',
        bench,vectors,negative,base.VECTOR_ROOT/'vectors_report.json']
    tracked += [base.DONOR/n for n in ['assertion_header.h','assertion_task.h','nv_assert_never.vlib','nv_assert_no_x.vlib','LICENSE']]
    source=fingerprint(tracked)
    report=dict(status='RUNNING',started_utc=timestamp(),simulator=args.simulator,source=source,
        channels=32,kernels=16,parallel_products=512,pipeline_stages=2,frames=208,outputs=3328,
        original_numeric_assertions_preserved=True,commands=[],hardware_programmed=False,vivado_executed=False,
        scope='Separate two-stage CMAC native corpus/burst/reset/X contract; no mapped/FPGA/RK acceptance')
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(name,argv,limit,negative_test=False):
        base.require(fingerprint(tracked)==source,'Source changed before command')
        entry=dict(name=name,argv=list(map(str,argv)),status='RUNNING');report['commands'].append(entry);save()
        child=None;start=time.monotonic()
        try:
            with (out/(name+'.log')).open('w') as log:
                child=subprocess.Popen(entry['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                entry['pid']=child.pid;save();rc=child.wait(timeout=limit)
            entry['returncode']=rc;text=(out/(name+'.log')).read_text()
            if negative_test:base.require(rc!=0 and 'sized array mismatch frame=0' in text and '\nPASS ' not in text,'Corrupted oracle did not reject')
            else:base.require(rc==0,'Native command failed')
            if name=='compile':
                entry['reviewed_messages']=base.admitted_compile_messages(text,args.simulator)
            if name=='actual':
                faults=1 if args.simulator=='iverilog' else 0
                marker=('PASS sized FP16 CMAC C=32 K=16 frames=208 checked_outputs=3328 '
                    f'retired_outputs=3312 reset_canceled=16 held_cycles=520 faults={faults}')
                base.require([l for l in text.splitlines() if l.startswith('PASS ')]==[marker],'Changed original corpus result')
                base.require(text.splitlines().count('CHECK pipeline_contract latency=2 burst_outputs=32 prepared_reset_canceled=16')==1,'Missing pipeline contract')
                report['result']=marker
            base.require(fingerprint(tracked)==source,'Source changed during command')
            entry['status']='PASS';return text
        except BaseException as e:
            entry.update(status='FAIL',error=str(e))
            if child is not None and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise
        finally:
            entry['seconds']=time.monotonic()-start
            if (out/(name+'.log')).exists():entry['log_sha256']=base.digest(out/(name+'.log'))
            save()
    def stop(sig,frame):raise InterruptedError('Native pipeline run interrupted '+str(sig))
    for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,stop)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));save()
    try:
        report['tool_version']=run('version',[args.simulator,'-V' if args.simulator=='iverilog' else '--version'],30).splitlines()[0]
        defs=['-DDESIGNWARE_NOEXIST','-DASSERT_ON','-I'+str(base.DONOR)]
        files=[str(ROOT/n) for n in SOURCES]+[str(bench)]
        if args.simulator=='iverilog':
            image=out/'sim.vvp';argv=['iverilog','-g2012',*defs,'-s','tb_cmac_fp16_array','-o',str(image),*files];launch=['vvp',str(image)]
            report['runtime_version']=run('runtime_version',['vvp','-V'],30).splitlines()[0]
        else:
            image=out/'obj/sim';argv=['verilator','--binary','--timing','--assert','-Wall','-Wno-fatal',*defs,
                '--top-module','tb_cmac_fp16_array','-j','1','-MAKEFLAGS','OPT_FAST=-O0 OPT_SLOW=-O0',
                '--Mdir',str(out/'obj'),'-o','sim',*files];launch=[str(image)]
        run('compile',argv,1200);h=base.digest(image);report['compiled_image']=dict(path=str(image),sha256=h)
        run('negative',launch+['+VECTORS='+str(negative),'+COUNT=208'],1800,True)
        run('actual',launch+['+VECTORS='+str(vectors),'+COUNT=208'],1800)
        base.require(base.digest(image)==h,'Native image changed')
        report.update(status='PASS_FULL512_TWO_STAGE_NATIVE_ONLY',finished_utc=timestamp())
    except BaseException as e:report.update(status='FAIL',error=str(e),finished_utc=timestamp());raise
    finally:
        report['artifacts']=fingerprint([p for p in out.iterdir() if p.is_file() and p.name!='report.json']);save()
    print(out/'report.json')


if __name__=='__main__':main()
