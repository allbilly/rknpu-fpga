#!/usr/bin/env python3
"""Strict native tests of the raw BO/two-clock EW boundary only."""
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
from tools.ddr import endpoint_vectors
from tools.ddr.interface import require

RTL=('rtl/rk_fp16_alu.sv','rtl/rk_ew_regs.sv','rtl/rk_ew_engine.sv','rtl/rk_ew_core.sv',
     'rtl/rk_ew_dma.sv','rtl/ddr/rk_async_job_port.sv','rtl/ddr/rk_async_mem_port.sv',
     'rtl/ddr/rk_ew_async_engine.sv')
TB='tests/ddr/tb_ew_async_engine.sv'
HEADER='tests/ddr/endpoint/strict_line_image.svh'
SEED='3588cdce'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture_specs(generated):
    by_name={spec['name']:spec for spec in generated}
    captures=[spec for spec in generated if spec['name'].startswith('capture_')]
    require(len(captures)==9,'Expected exactly nine complete captured BO cases')
    sub=dict(by_name['capture_sub_9'])
    cases=[dict(spec,jobs=1,negative=0,stop_clocks=0) for spec in captures]
    cases.append(dict(sub,name='repeat_sub_9',jobs=2,negative=0,stop_clocks=0))
    cases.extend([
        dict(by_name['unknown_command'],name='unknown_command',jobs=1,negative=1,stop_clocks=0),
        dict(by_name['rmw_ue'],name='memory_error',jobs=1,negative=2,stop_clocks=0),
        dict(by_name['dropped_return'],name='late_response_timeout',jobs=1,negative=3,stop_clocks=0),
        dict(by_name['phy_write_stall'],name='offered_request_timeout',jobs=1,negative=4,stop_clocks=0),
        dict(by_name['joint_reset_recovery'],name='joint_reset_recovery',jobs=1,negative=5,stop_clocks=0),
        dict(sub,name='stopped_clocks',jobs=1,negative=0,stop_clocks=1),
    ])
    cases.append(dict(sub,name='joint_reset_inflight',jobs=1,negative=6,stop_clocks=0))
    cases.append(dict(sub,name='joint_reset_stopped_core',jobs=1,negative=7,stop_clocks=0))
    for case in cases:case.pop('reset_recovery',None)
    require(len(cases)==18 and len({case['name'] for case in cases})==18,
            'Async EW case inventory differs')
    return cases


def metrics(spec,captured):
    original=captured[spec['case']]['production']
    ntasks=len(original['tasks'])
    require(ntasks==spec['tasks'],'Captured BO task count changed')
    padded=((original['logical_count']+7)//8)*8
    per_reads=4*sum(task['descriptor']['regcfg_amount'] for task in original['tasks'])+2*padded*ntasks
    per_writes=padded*ntasks
    negative=spec['negative']
    if negative==1:
        reads,writes,responses=4,0,4
    elif negative in (2,3,4):
        reads,writes,responses=1,0,1
    else:
        reads=per_reads*spec['jobs'];writes=per_writes*spec['jobs'];responses=reads+writes
    submitted=2 if negative in (5,6,7) else spec['jobs']
    consumed=2 if negative in (5,7) else 1 if negative==6 else spec['jobs']
    recovered=1 if negative in (5,6,7) else 0
    return dict(per_job_reads=per_reads,per_job_writes=per_writes,padded_n=padded,ntasks=ntasks,
        submitted=submitted,consumed=consumed,recovered=recovered,stopped=spec['stop_clocks'],
        reads=reads,writes=writes,responses=responses)


def main():
    def interrupted(signum,frame):raise InterruptedError('Async EW boundary test interrupted '+str(signum))
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,interrupted)
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator',choices=('iverilog','verilator'),required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh workspace output required')
    tool=shutil.which(args.simulator);runtime=shutil.which('vvp') if args.simulator=='iverilog' else None
    require(tool is not None and (args.simulator!='iverilog' or runtime is not None),
            'UNAVAILABLE: requested simulator/runtime')
    out.mkdir(parents=True)

    local=tuple(sorted(set(endpoint_vectors.LOCAL+RTL+(TB,HEADER,'tools/ddr/run_async_ew.py'))))
    source_inputs={str(ROOT/name):sha(ROOT/name) for name in local}
    snapshot_inputs={}
    for name,digest in source_inputs.items():
        relative=Path(name).relative_to(ROOT)
        target=out/'source'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(Path(name).read_bytes())
        snapshot_inputs[str(target)]=digest

    vector_dir=out/'vectors'
    generated=endpoint_vectors.generate(vector_dir)
    require(endpoint_vectors.verify_vectors(vector_dir)==generated,'Generated endpoint BO vectors changed')
    vector_inputs={str(p):sha(p) for p in vector_dir.rglob('*') if p.is_file()}
    require(vector_inputs,'Missing generated capture vectors')
    inputs=source_inputs|snapshot_inputs|vector_inputs
    captured={case['name']:case for case in endpoint_vectors.captured_cases()}
    cases=capture_specs(generated)
    report=dict(status='RUNNING',simulator=args.simulator,
        scope='Raw original BO/two-clock EW boundary protocol only; no MIG, physical DDR, image, '
              'global-reset epoch or system CDC qualification',
        inputs=inputs,local_source={name:digest for name,digest in source_inputs.items()},
        vectors={str(Path(name).relative_to(vector_dir)):digest for name,digest in vector_inputs.items()},
        seed='0x'+SEED,ui_period_ns=7.5,core_period_ns=20.0,
        cases=[case['name'] for case in cases],commands=[],tests=[],hardware_accessed=False,
        vivado_executed=False,bitstream_emitted=False,physical_ddr_qualified=False,
        image_qualified=False,global_reset_or_first_cause_qualified=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def check_inputs():
        for path,digest in inputs.items():
            require(Path(path).is_file() and sha(path)==digest,'Changed frozen async EW input: '+path)
    def execute(name,argv,timeout):
        check_inputs();start=time.monotonic()
        with (out/(name+'.log')).open('x') as stream:
            watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP}
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
            try:
                process=subprocess.Popen(argv,cwd=out,stdout=stream,stderr=subprocess.STDOUT,
                    start_new_session=True,
                    preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            try:process.wait(timeout=timeout)
            except BaseException:
                if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()
                raise
        check_inputs()
        text=(out/(name+'.log')).read_text()
        report['commands'].append(dict(name=name,argv=argv,returncode=process.returncode,
            seconds=time.monotonic()-start,log_sha256=sha(out/(name+'.log'))))
        save();return process.returncode,text

    save()
    try:
        _,version=execute('version',[tool,'-V' if args.simulator=='iverilog' else '--version'],30)
        report['tool_version']=version.splitlines()[0]
        if runtime:
            _,version=execute('runtime_version',[runtime,'-V'],30)
            report['runtime_version']=version.splitlines()[0]
        frozen_rtl=[str(out/'source'/name) for name in RTL+(TB,)]
        header=str(out/'source'/HEADER)
        define='-DRK_DDR_LINE_IMAGE_HEADER='+json.dumps(Path(header).name)
        include='-I'+str(Path(header).parent)
        for stages in (3,5):
            key='stages'+str(stages)
            if args.simulator=='iverilog':
                image=out/(key+'.vvp')
                build=[tool,'-g2012','-Wall','-s','tb_ew_async_engine',
                    '-Ptb_ew_async_engine.DUT_STAGES='+str(stages),define,include,
                    '-o',str(image),*frozen_rtl]
                run=[runtime,str(image)]
            else:
                image=out/key/'sim'
                build=[tool,'--binary','--timing','--assert','-Wall','--top-module','tb_ew_async_engine',
                    '-GDUT_STAGES='+str(stages),'-j','1','--Mdir',str(out/key),'-o','sim',define,include,*frozen_rtl]
                run=[str(image)]
            code,text=execute(key+'-compile',build,180)
            require(code==0 and not re.search(r'(?mi)%Warning|warning:|sorry:|^%Error',text),
                    'Unadmitted compiler diagnostic')
            binary_hash=sha(image)
            for spec in cases:
                name=spec['name'];case_dir=vector_dir/spec['case']
                # Keep every stage/case output in one deterministic directory.
                result_dir=out/'runs'/key/name
                result_dir.mkdir(parents=True)
                observed=result_dir/'observed.txt'
                m=metrics(spec,captured)
                argv=[*run,'+CASE='+str(case_dir),'+OUTPUT='+str(observed),
                    '+START='+f"{spec['address']:08x}",'+AMOUNT='+str(spec['amount']),
                    '+NTASKS='+str(spec['tasks']),'+NLINES='+str(spec['lines']),
                    '+READS='+str(m['per_job_reads']),'+WRITES='+str(m['per_job_writes']),
                    '+JOBS='+str(spec['jobs']),'+NEGATIVE='+str(spec['negative']),
                    '+STOPCLOCKS='+str(spec['stop_clocks'])]
                code,text=execute(key+'-'+name,argv,60)
                require(sha(image)==binary_hash,'Executed image changed')
                marker=(f"PASS async_ew_boundary negative={spec['negative']} submitted={m['submitted']} "
                    f"consumed={m['consumed']} recovered={m['recovered']} stopped={m['stopped']} "
                    f"reads={m['reads']} writes={m['writes']} responses={m['responses']} "
                    f"seed={SEED} raw_BO_two_clocks_only")
                require(code==0 and [line for line in text.splitlines() if line.startswith('PASS async_ew_boundary ')]==[marker]
                    and not re.search(r'(?mi)^FATAL|^ERROR|%Error|warning:',text),
                    'Async EW boundary result differs: '+name)
                needs_output=spec['negative'] in (0,5,6,7)
                if needs_output:
                    expected=(case_dir/'expected.txt').read_bytes()
                    require(observed.is_file() and observed.read_bytes()==expected,
                            'Complete captured BO image differs: '+name)
                    output_sha=sha(observed)
                else:
                    require(not observed.exists(),'Unexpected BO output from negative job: '+name)
                    output_sha=None
                report['tests'].append(dict(stages=stages,name=name,spec=spec,metrics=m,status='PASS',
                    marker=marker,binary_sha256=binary_hash,observed_sha256=output_sha))
                save()
        check_inputs()
        report['status']='PASS_ASYNC_EW_RAW_BO_CLOCK_BOUNDARY_ONLY'
    except BaseException as error:
        report.update(status='FAIL',error=repr(error));raise
    finally:
        report['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(report['status'],out/'report.json')


if __name__=='__main__':main()
