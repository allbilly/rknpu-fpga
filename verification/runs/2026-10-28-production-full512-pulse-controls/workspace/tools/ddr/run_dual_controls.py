#!/usr/bin/env python3
"""Native ownership controls only; dispatcher children are nonnumeric models."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def require(ok,message):
    if not ok:raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=(args.out or ROOT/'build/ddr-dual-controls'/stamp).resolve()
    require(not out.exists(),'Fresh control output required')
    out.mkdir(parents=True)
    csr=[ROOT/name for name in ('rtl/rk_job_control.sv','rtl/ddr/rk_dual_job_control.sv',
                               'tests/ddr/dual_csr/tb_dual_job_control.sv')]
    dispatch=[ROOT/name for name in ('rtl/ddr/rk_dual_async_dispatch.sv',
        'tests/ddr/dispatch/control_models.sv','tests/ddr/dispatch/tb_dual_dispatch.sv')]
    inputs={str(p):sha(p) for p in [Path(__file__),*csr,*dispatch]}
    record=dict(status='RUNNING_DUAL_CONTROL_BENCHES',scope='Raw control only; dispatcher children are nonnumeric models',
        inputs=inputs,seed='deterministic-control-no-prng',commands=[],tool_versions={},
        control_models_selected=True,numerical_qualified=False,ddr_qualified=False,hardware_accessed=False)
    report=out/'report.json'
    def save():report.write_text(json.dumps(record,indent=2)+'\n')
    def interrupted(signum,frame):raise InterruptedError('Control runner interrupted: '+str(signum))
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
    save()
    try:
        for tool,argv in {'iverilog':['iverilog','-V'],'vvp':['vvp','-V'],'verilator':['verilator','--version']}.items():
            require(shutil.which(tool) is not None,'UNAVAILABLE: '+tool+' required')
            result=subprocess.run(argv,capture_output=True,text=True,timeout=15)
            require(result.returncode==0,'Tool version failed: '+tool)
            record['tool_versions'][tool]=dict(argv=argv,stdout=result.stdout,stderr=result.stderr)
        csr_marker='PASS dual job control namespace identity readiness global owner result readback ACK errors late fault joint reset'
        dispatch_marker='PASS dual_async_dispatch control_only=1 chain=EW-CMAC-EW req_result_backpressure=1 admission_readback_gate=1 failed_owner_late_drain=1 unowned_response=1 unknown_selection=1 duplicate_offer_without_ready=1'
        jobs=[('csr_compile',['iverilog','-g2012','-Wall','-s','tb_dual_job_control','-o',str(out/'csr.vvp'),*map(str,csr)],120,None),
              ('csr_run',['vvp',str(out/'csr.vvp')],30,csr_marker),
              ('dispatch_compile',['iverilog','-g2012','-Wall','-s','tb_dual_dispatch','-o',str(out/'dispatch.vvp'),*map(str,dispatch)],120,None),
              ('dispatch_run',['vvp',str(out/'dispatch.vvp')],30,dispatch_marker),
              ('csr_verilator_compile',['verilator','--binary','--timing','--assert','-Wall','-j','1','--top-module','tb_dual_job_control','--Mdir',str(out/'verilator_obj'),*map(str,csr)],180,None),
              ('csr_verilator_run',[str(out/'verilator_obj/Vtb_dual_job_control')],30,csr_marker)]
        for name,argv,limit,marker in jobs:
            command=dict(name=name,argv=argv,timeout_seconds=limit,status='RUNNING')
            record['commands'].append(command);save();start=time.monotonic()
            with (out/(name+'.stdout.log')).open('x') as stdout,(out/(name+'.stderr.log')).open('x') as stderr:
                child=subprocess.Popen(argv,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
                command['pid']=child.pid;save()
                try:code=child.wait(timeout=limit)
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid,signal.SIGTERM)
                        try:child.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid,signal.SIGKILL);child.wait()
            command.update(returncode=code,seconds=time.monotonic()-start,status='PASS' if code==0 else 'FAIL',
                stdout_sha256=sha(out/(name+'.stdout.log')),stderr_sha256=sha(out/(name+'.stderr.log')));save()
            require(code==0,'Native control command failed: '+name)
            require(not (out/(name+'.stderr.log')).read_bytes(),'Unexpected native diagnostic: '+name)
            if marker is not None:
                lines=(out/(name+'.stdout.log')).read_text().splitlines()
                require(lines and lines[0]==marker and lines.count(marker)==1,'Missing/excess exact control marker: '+name)
        require(all(sha(name)==digest for name,digest in inputs.items()),'Control source changed during run')
        record.update(status='PASS_DUAL_CONTROL_BENCHES_ONLY',all_inputs_unchanged=True)
    except BaseException as error:
        record.update(status='FAIL_DUAL_CONTROL_BENCHES',error=repr(error));raise
    finally:
        record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(json.dumps(dict(status=record['status'],report=str(report),hardware_accessed=False)))


if __name__=='__main__':main()
