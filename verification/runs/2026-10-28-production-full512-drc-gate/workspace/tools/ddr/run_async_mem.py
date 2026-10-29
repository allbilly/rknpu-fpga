#!/usr/bin/env python3
"""Strict native tests of a serial halfword CDC leaf, never physical signoff."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.interface import require


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    def interrupted(signum,frame):raise InterruptedError('Bridge test interrupted '+str(signum))
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator',choices=('iverilog','verilator'),required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh workspace output required')
    tool=shutil.which(args.simulator);runtime=shutil.which('vvp') if args.simulator=='iverilog' else None
    require(tool is not None and (args.simulator!='iverilog' or runtime is not None),'UNAVAILABLE: requested simulator/runtime')
    out.mkdir(parents=True)
    names=('rtl/ddr/rk_async_mem_port.sv','tests/ddr/tb_async_mem_port.sv','tools/ddr/run_async_mem.py')
    inputs={}
    for name in names:
        target=out/'source'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes());inputs[str(target)]=sha(target)
    report=dict(status='RUNNING',simulator=args.simulator,scope=__doc__,inputs=inputs,seed='0x3588cdc1',
        source_period_ns=20,destination_period_ns=7.5,commands=[],tests=[],hardware_accessed=False,
        physical_cdc_qualified=False,global_reset_or_first_cause_qualified=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def execute(name,argv,timeout):
        require(all(sha(p)==h for p,h in inputs.items()),'Changed frozen bridge source')
        start=time.monotonic()
        with (out/(name+'.log')).open('x') as stream:
            watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP}
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
            try:
                process=subprocess.Popen(argv,cwd=out,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                    preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            try:process.wait(timeout=timeout)
            except BaseException:
                if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                raise
        text=(out/(name+'.log')).read_text()
        report['commands'].append(dict(name=name,argv=argv,returncode=process.returncode,
            seconds=time.monotonic()-start,log_sha256=sha(out/(name+'.log'))))
        save();return process.returncode,text
    save()
    try:
        _,version=execute('version',[tool,'-V' if args.simulator=='iverilog' else '--version'],30)
        report['tool_version']=version.splitlines()[0]
        if runtime:
            _,version=execute('runtime_version',[runtime,'-V'],30);report['runtime_version']=version.splitlines()[0]
        rtl=[str(out/'source'/n) for n in names[:2]]
        for stages in (3,5,0,2):
            key='stages'+str(stages)
            if args.simulator=='iverilog':
                image=out/(key+'.vvp')
                build=[tool,'-g2012','-Wall','-s','tb_async_mem_port',
                    '-Ptb_async_mem_port.DUT_STAGES='+str(stages),'-o',str(image),*rtl]
                run=[runtime,str(image)]
            else:
                image=out/key/'sim'
                build=[tool,'--binary','--timing','--assert','-Wall','--top-module','tb_async_mem_port',
                    '-GDUT_STAGES='+str(stages),'-j','1','--Mdir',str(out/key),'-o','sim',*rtl]
                run=[str(image)]
            code,text=execute(key+'-compile',build,180)
            require(code==0 and not re.search(r'(?mi)%Warning|warning:|sorry:|^%Error',text),'Unadmitted compiler diagnostic')
            binary_hash=sha(image)
            for mode in ((0,1,2) if stages>=3 else (0,)):
                code,text=execute(key+'-mode'+str(mode),[*run,'+MODE='+str(mode)],30)
                require(sha(image)==binary_hash,'Executed image changed')
                if stages<3:
                    require(code!=0 and 'Memory crossing requires at least three synchronizer stages' in text,
                            'Missing specific synchronizer-count rejection')
                    require(('Time: 0' in text) if runtime else re.search(r'(?m)^\[0\]',text),'Parameter did not fail at time zero')
                    result='EXPECTED_TIME_ZERO_REJECTION'
                else:
                    result=f'PASS async_mem_port mode={mode} completed={256 if mode==0 else 3} seed=3588cdc1 source_only_no_physical_CDC'
                    require(code==0 and [s for s in text.splitlines() if s.startswith('PASS ')]==[result]
                        and not re.search(r'(?mi)^FATAL|^ERROR|%Error|warning:',text),'Bridge protocol result differs')
                report['tests'].append(dict(stages=stages,mode=mode,status='PASS',result=result,binary_sha256=binary_hash));save()
        require(all(sha(p)==h for p,h in inputs.items()),'Bridge source changed')
        report['status']='PASS_ASYNC_HALFWORD_MEMORY_PROTOCOL_LEAF_ONLY'
    except BaseException as error:
        report.update(status='FAIL',error=repr(error));raise
    finally:
        report['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(report['status'],out/'report.json')


if __name__=='__main__':main()
