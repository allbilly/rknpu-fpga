#!/usr/bin/env python3
"""Fresh registered-BRAM-port replay of the original complete memory contract."""
from pathlib import Path
import argparse
import json
import os
import resource
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.evidence import fingerprint,timestamp


def require(ok,message):
    if not ok:raise ValueError(message)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--simulator',choices=('iverilog','verilator'),required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh output required')
    old=ROOT/'tests/cmac/tb_cmac_demo_memory.sv'
    text=old.read_text();source=ROOT/'rtl/cmac/experimental/rk_cmac_demo_memory_regport.sv'
    require(text.count('rk_cmac_demo_memory dut(.*);')==1,'Changed original memory bench')
    out.mkdir(parents=True);bench=out/old.name
    bench.write_text(text.replace('rk_cmac_demo_memory dut(.*);','rk_cmac_demo_memory_regport dut(.*);'))
    inputs=[source,old,bench,Path(__file__),ROOT/'tools/evidence.py'];before=fingerprint(inputs)
    report=dict(status='RUNNING',started_utc=timestamp(),simulator=args.simulator,source=before,
        scope='Original3712mapped/4096flat aperture, held-response and reset-pending-write assertions on registered RAM ports; no synthesis or hardware proof',commands=[],hardware_accessed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def run(name,argv,limit):
        entry=dict(name=name,argv=list(map(str,argv)),status='RUNNING');report['commands'].append(entry);save()
        child=None;start=time.monotonic()
        try:
            with (out/(name+'.log')).open('w') as log:
                child=subprocess.Popen(entry['argv'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                entry['pid']=child.pid;save();code=child.wait(timeout=limit)
            entry['returncode']=code;require(code==0,'Memory '+name+' failed')
            require(fingerprint(inputs)==before,'Memory source changed during execution')
            text=(out/(name+'.log')).read_text();entry['status']='PASS';return text
        except BaseException as error:
            entry.update(status='FAIL',error=str(error))
            if child is not None and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise
        finally:
            entry['seconds']=time.monotonic()-start;save()
    def interrupt(sig,frame):raise InterruptedError('Memory check interrupted '+str(sig))
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,interrupt)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0));save()
    try:
        report['tool_version']=run('version',[args.simulator,'-V' if args.simulator=='iverilog' else '--version'],30).splitlines()[0]
        if args.simulator=='iverilog':
            image=out/'sim.vvp';cmd=['iverilog','-g2012','-s','tb_cmac_demo_memory','-o',image,source,bench];launch=['vvp',image]
            report['runtime_version']=run('runtime_version',['vvp','-V'],30).splitlines()[0]
        else:
            image=out/'obj/sim';cmd=['verilator','--binary','--timing','--assert','-Wall','--top-module','tb_cmac_demo_memory','-j','1','--Mdir',out/'obj','-o','sim',source,bench];launch=[image]
        compile_text=run('compile',cmd,180)
        require('error:' not in compile_text.lower() and 'warning:' not in compile_text.lower(),'Unadmitted compile diagnostic')
        actual=run('actual',launch,180)
        marker='PASS CMAC demo memory mapped_halfwords=3712 flat_halfwords=4096 transactions=11144 rejected=3720 reset_pending_write=1'
        require([line for line in actual.splitlines() if line.startswith('PASS ')]==[marker],'Original full memory contract differs')
        report.update(status='PASS_REGISTERED_BRAM_PORT_MEMORY_NATIVE_ONLY',result=marker,finished_utc=timestamp())
    except BaseException as error:report.update(status='FAIL',error=str(error),finished_utc=timestamp());raise
    finally:
        report['artifacts']=fingerprint([p for p in out.iterdir() if p.is_file() and p.name!='report.json']);save()
    print(out/'report.json')


if __name__=='__main__':main()
