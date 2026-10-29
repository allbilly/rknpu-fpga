#!/usr/bin/env python3
"""Observe the preserved cold-read failure without changing models or gates.

Copy the failed attempt's exact six-RAM wrapper and pinned models. A separate
bench reads model state without force/assign/repair and traces a small set of
primitive-boundary transactions. This runner never accepts the overwrite,
startup, temporal, numerical or physical properties. No SHA256SUMS files.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

FAILED=ROOT/'build/openxc7/prefix-working-bram-overwrite-resume-1791440837448998352/report.json'
BENCH=ROOT/'tests/cmac/tb_prefix_working_bram_cold_diagnostic.sv'


def main():
    out=ROOT/f'build/openxc7/prefix-working-bram-cold-diagnostic-{time.time_ns()}'
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),
        supervisor_pid=os.getpid(),python_version=sys.version,seed=None,commands=[],source={},
        production_source_before=source_revision(),parent_failed_report=str(FAILED),
        retained_full_target_parallel_products=512,observation_only=True,
        working_BRAM_model_overwrite_fixture_acceptance=False,full_board_startup_independence_proved=False,
        temporal_port_ownership_proved=False,write_before_read_proved=False,full_board_numerical_acceptance=False,
        physical_fit_verified=False,timing_signoff=False,electrical_verified=False,drc_signoff=False,
        bitstream_emitted=False,hardware_programmed=False,hardware_input_modified=False,native_PNR_executed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label,argv):
        step=dict(label=label,argv=list(map(str,argv)),cwd=str(ROOT),log=str(out/(label+'.log')),
            status='RUNNING',timeout_seconds=180)
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream,subprocess.Popen(step['argv'],cwd=ROOT,
                    stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as process:
                step['pid']=process.pid;save()
                try:code=process.wait(timeout=180)
                except BaseException:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait();step['returncode']=process.returncode;raise
            step['returncode']=code;text=Path(step['log']).read_text()
            assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout',text),text[-4000:]
            step['status']='PASS_EXECUTION_ONLY_NOT_PROPERTY_ACCEPTANCE';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(BENCH,out/'executed_bench_source.sv')
        failed=json.loads(FAILED.read_text())
        assert failed['status']=='FAIL' and failed['stage']=='negative' and failed['finished_utc']
        assert failed['working_BRAM_model_overwrite_fixture_acceptance'] is False
        assert failed['execution_inputs'] and failed['source'] and failed['artifacts']
        negative=next(c for c in failed['commands'] if c['label']=='negative')
        assert negative['status']=='FAIL' and negative['returncode']==1
        assert 'working BRAM cold-state mismatch index=0 got=xX00/0000/ffff' in Path(negative['log']).read_text()
        before={};bind_report(FAILED,failed,before)
        files={Path(__file__).resolve(),BENCH,Path(sys.executable).resolve(),
            *(Path(shutil.which(tool)).resolve() for tool in ('iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        verify_bindings(before);report['source']=before
        copies=[]
        for source in (FAILED.parent/'models/glbl.v',FAILED.parent/'models/RAMB36E1.v',
                       FAILED.parent/'actual-working-BRAM-configurations.v',BENCH):
            target=out/source.name;shutil.copyfile(source,target);assert digest(target)==digest(source);copies.append(target)
        shutil.copyfile(FAILED.parent/'models/LICENSE',out/'LICENSE')
        execution={str(p):digest(p) for p in copies}
        report['stage']='generated_check';save();run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        report['stage']='compile';save();binary=out/'diagnostic.vvp'
        run('compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_working_bram_cold_diagnostic',
            '-s','glbl','-o',binary,*copies]);execution[str(binary)]=digest(binary)
        report['execution_inputs']=execution;report['stage']='observe';save()
        text=run('observe',['vvp',binary])
        assert 'OBSERVATION_ONLY unchanged actual working BRAM cold trace; no overwrite, startup or hardware acceptance' in text
        report['observed_trace']=text.splitlines()
        verify_bindings(execution);verify_bindings(before)
        report['production_source_after']=source_revision();assert report['production_source_before']==report['production_source_after']
        report.update(status='OBSERVED_ONLY_NOT_OVERWRITE_STARTUP_NUMERICAL_OR_PHYSICAL_ACCEPTANCE',stage='complete')
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp()
        report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
