#!/usr/bin/env python3
"""Qualify all 47 exact actual controller FDCE binary/async folds.

Require the completed source-bound full controller-cone extraction. Preserve
every actual parameter and unchanged pinned FDCE/glbl source. Reuse the
original ordinary-write stimulus, default GSR, sixteen binary tuples and
finite wrong-golden expectation for every one of the 47 configurations.
No forced Q, INIT substitution, missing state bit or timing waiver. This
primitive rule qualification is not the actual controller independence SAT,
reachability, temporal ownership, full-board startup or physical acceptance.
No original helper, RTL, model, input, live job or SHA256SUMS is changed.
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
import audit_prefix_initialization_controller_cone as controller
import qualify_prefix_state_fdce_fold as original
import unisim_board_models as models
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

PREPARED=ROOT/'build/openxc7/prefix-initialization-controller-cone-1791446127029039711/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_controller_fdce_fold_control.py'
MARKER='PASS actual 47 controller FDCE binary folds vectors=16 seed_checks=752 async_checks=752 next_checks=752 default_gsr=100ns; not actual controller independence or temporal startup or physical acceptance'
PASS='QUALIFIED_ACTUAL_47_CONTROLLER_FDCE_BINARY_NEXT_AND_ASYNC_FOLDS_ONLY_NOT_INITIALIZATION_OR_TEMPORAL_PROOF'


def records(before):
    report=json.loads(PREPARED.read_text())
    assert report['status']==controller.PASS and report['stage']=='complete' and report['finished_utc']
    assert report['full_target_parallel_products']==512 and report['controller_state_bits']==47 and report['observed_control_bits']==9
    assert report['initialization_controller_data_independence_proved'] is False
    bind_report(PREPARED,report,before);verify_bindings(before)
    cone=json.loads((PREPARED.parent/'actual-initialization-controller-cone.json').read_text())
    regs=cone['controller_registers']
    assert len(regs)==47 and len({r['cell'] for r in regs})==47
    expected=[(name,i) for name,width in controller.REGISTERS.items() for i in range(width)]
    assert [(r['signal'],r['offset']) for r in regs]==expected
    for r in regs:
        c=r['original_primitive'];controller.validate_fold_register(c,cone['signals']['demo.memory.clk'])
        assert c['connections']['Q']==[cone['signals'][r['signal']][r['offset']]]
    return regs


def wrapper(regs):
    assert len(regs)==47 and len({r['cell'] for r in regs})==47
    lines=['module actual_prefix_controller_fdces(input clk,clear,enable,data,output [46:0] observed);']
    for i,r in enumerate(regs):
        c=r['original_primitive'];controller.validate_fold_register(c,[8])
        parameters=','.join('.'+name+"(1'b"+value+')' for name,value in sorted(c['parameters'].items()))
        parameter=' #('+parameters+')' if parameters else ''
        lines.append('FDCE'+parameter+' actual_'+str(i)+'(.C(clk),.CE(enable),.D(data),.CLR(clear),.Q(observed['+str(i)+']));')
    return '\n'.join(lines+['endmodule'])+'\n'


def bench_text():
    source=original.BENCH.read_text();text=source
    substitutions=(('tb_prefix_state_fdce_fold','tb_prefix_controller_fdce_fold'),
        ('wire [3:0] observed;','wire [46:0] observed;'),
        ('actual_prefix_state_fdces','actual_prefix_controller_fdces'),
        ('cell_index<4;','cell_index<47;'),
        ('seeds!=64||async_checks!=64||next_checks!=64','seeds!=752||async_checks!=752||next_checks!=752'),
        (original.MARKER,MARKER))
    assert source.count('cell_index<4;')==3
    for old,new in substitutions:
        assert old in text and new not in text
        text=text.replace(old,new)
    restored=text
    for old,new in reversed(substitutions):restored=restored.replace(new,old)
    assert restored==source,'Changed original FDCE stimulus or golden'
    return text


def validate(text,code,negative,bench):
    assert text.count(MARKER)==(0 if negative else 1)
    assert original.MARKER not in text
    original.validate(text.replace(MARKER,original.MARKER),code,negative,bench)


def main():
    out=ROOT/f'build/openxc7/prefix-controller-fdce-fold-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        full_target_parallel_products=512,controller_binary_fold_qualified=False,
        initialization_controller_data_independence_proved=False,temporal_port_ownership_proved=False,
        write_before_read_proved=False,full_board_startup_independence_proved=False,full_board_numerical_acceptance=False,
        physical_fit_verified=False,timing_signoff=False,electrical_verified=False,drc_signoff=False,
        bitstream_emitted=False,hardware_programmed=False,hardware_input_modified=False,native_PNR_executed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label,argv,negative=None):
        step=dict(label=label,argv=list(map(str,argv)),cwd=str(ROOT),log=str(out/(label+'.log')),status='RUNNING',timeout_seconds=180)
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream,subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as process:
                step['pid']=process.pid;save()
                try:code=process.wait(timeout=180)
                except BaseException:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait();step['returncode']=process.returncode;raise
            step['returncode']=code;text=Path(step['log']).read_text()
            if negative is not None:validate(text,code,negative,bench)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_WRONG_GOLDEN_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={};regs=records(before);pinned=models.selected_models({'FDCE'})
        files={Path(__file__).resolve(),CONTROL,original.BENCH,*pinned,Path(sys.executable).resolve(),
            *(Path(shutil.which(t)).resolve() for t in ('iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        for path,sha in pinned.items():assert digest(path)==sha,'Changed pinned model'
        verify_bindings(before);report['source']=before
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        source=out/'actual-controller-FDCEs.v';source.write_text(wrapper(regs))
        (out/'actual-controller-FDCE-records.json').write_text(json.dumps(regs,indent=2,sort_keys=True)+'\n')
        bench=out/'tb_prefix_controller_fdce_fold.sv';bench.write_text(bench_text());frozen=[]
        for path in pinned:
            target=out/path.name;shutil.copyfile(path,target)
            if target.suffix=='.v':frozen.append(target)
        execution={str(p):digest(p) for p in (source,bench,*frozen)};binary=out/'fold.vvp'
        report['stage']='compile';save()
        run('compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_controller_fdce_fold','-s','glbl','-o',binary,*frozen,source,bench])
        execution[str(binary)]=digest(binary);report['execution_inputs']=execution
        for label,options,negative in (('negative',['+NEGATIVE=1'],True),('positive',[],False)):
            report['stage']=label;save();run(label,['vvp',binary,*options],negative);verify_bindings(execution)
        verify_bindings(before);report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',controller_binary_fold_qualified=True,actual_controller_configurations=47,
            binary_old_Q_D_CE_CLR_tuples=16,seed_checks=752,async_checks=752,next_checks=752,
            default_GSR_unchanged=True,actual_INIT_preserved=True,old_Q_established_only_by_clocked_writes=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
