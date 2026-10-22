#!/usr/bin/env python3
"""Qualify actual four FDCE parameter sets against binary next-state folding.

Use the exact source-bound state-Q records already retained by the address
cone and require positive un-inverted common clock, unknown INIT preserved.
Run unchanged pinned vendor FDCE/glbl models; seed old Q through ordinary
writes, then exhaust all 16 old-Q/D/CE/CLR tuples. Check async behavior and
next-edge results. A finite one-bit wrong-golden negative is separately run.
This establishes only that binary primitive fold, not actual state data
independence, register initialization, temporal board behavior or signoff.
No RTL, models, hardware input, old gate or SHA256SUMS is changed.
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
import audit_prefix_initialization_state_cone as state
import unisim_board_models as models
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

BENCH=ROOT/'tests/cmac/tb_prefix_state_fdce_fold.sv'
CONTROL=ROOT/'tests/cmac/test_prefix_state_fdce_fold_control.py'
MARKER='PASS actual four state FDCE binary fold vectors=16 seed_checks=64 async_checks=64 next_checks=64 default_gsr=100ns; not temporal startup or physical acceptance'
PASS='QUALIFIED_ACTUAL_FOUR_STATE_FDCE_BINARY_NEXT_AND_ASYNC_FOLD_ONLY_NOT_INITIALIZATION_OR_TEMPORAL_PROOF'


def records():
    report=json.loads(state.ADDRESS.read_text())
    assert report['stage']=='complete' and report['finished_utc'] and report['address_decoder_binary_cut_proved']
    assert report['full_target_parallel_products']==512
    result=[]
    for q in state.STATE_Q:
        record=report['actual_producer_cuts'][str(q)];cell=record['original_primitive']
        state.coherent.validate_register(cell,record['pin'],record['bit'])
        assert cell['type']=='FDCE' and cell['connections']['Q']==[q] and cell['connections']['C']==[8]
        assert cell['parameters']=={'INIT':'x'},'Changed actual state primitive configuration'
        result.append(record)
    assert len({r['cell'] for r in result})==4
    return result


def wrapper(regs):
    assert len(regs)==4
    lines=['module actual_prefix_state_fdces(input clk,clear,enable,data,output [3:0] observed);']
    for i,record in enumerate(regs):
        cell=record['original_primitive'];state.coherent.validate_register(cell,'Q',0)
        assert cell['type']=='FDCE' and cell['parameters']=={'INIT':'x'} and cell['connections']['C']==[8]
        lines.append("FDCE #(.INIT(1'bx)) actual_"+str(i)+'(.C(clk),.CE(enable),.D(data),.CLR(clear),.Q(observed['+str(i)+']));')
    lines.append('endmodule');return '\n'.join(lines)+'\n'


def validate(text,code,negative,bench):
    assert not re.search(r'(?im)warning:|error:|sorry:|timeout',text)
    if negative:
        marker='FDCE next fold mismatch cell=0 vector=0 got=0 expected=1'
        fatal=[line for line in text.splitlines() if line.startswith('FATAL:')]
        assert code==1 and len(fatal)==1 and marker in fatal[0] and MARKER not in text
        assert 'Time: 152000' in text
    else:
        finish=[i+1 for i,line in enumerate(bench.read_text().splitlines()) if line.strip()=='$finish;']
        assert len(finish)==1
        assert code==0 and text.splitlines()==[MARKER,f'{bench}:{finish[0]}: $finish called at 752000 (1ps)'],text[-4000:]


def main():
    out=ROOT/f'build/openxc7/prefix-state-fdce-fold-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        retained_full_target_parallel_products=512,next_state_binary_fold_qualified=False,
        initialization_state_data_independence_proved=False,temporal_port_ownership_proved=False,
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
        regs=records();before={};bind_report(state.ADDRESS,json.loads(state.ADDRESS.read_text()),before)
        pinned=models.selected_models({'FDCE'})
        files={Path(__file__).resolve(),BENCH,CONTROL,Path(sys.executable).resolve(),*pinned,
            *(Path(shutil.which(t)).resolve() for t in ('iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        for path,sha in pinned.items():assert digest(path)==sha,'Changed pinned model'
        verify_bindings(before);report['source']=before
        run('software_controls',[sys.executable,'-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        source=out/'actual-state-FDCEs.v';source.write_text(wrapper(regs))
        (out/'actual-state-FDCE-records.json').write_text(json.dumps(regs,indent=2,sort_keys=True)+'\n')
        bench=out/BENCH.name;shutil.copyfile(BENCH,bench);frozen=[]
        for path in pinned:
            target=out/path.name;shutil.copyfile(path,target)
            if target.suffix=='.v':frozen.append(target)
        execution={str(p):digest(p) for p in (source,bench,*frozen)};binary=out/'fold.vvp'
        report['stage']='compile';save()
        run('compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_state_fdce_fold','-s','glbl','-o',binary,*frozen,source,bench])
        execution[str(binary)]=digest(binary);report['execution_inputs']=execution
        for label,options,negative in (('negative',['+NEGATIVE=1'],True),('positive',[],False)):
            report['stage']=label;save();run(label,['vvp',binary,*options],negative);verify_bindings(execution)
        verify_bindings(before);report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',next_state_binary_fold_qualified=True,
            actual_state_parameter_sets=4,binary_old_Q_D_CE_CLR_tuples=16,seed_checks=64,async_checks=64,next_checks=64,
            default_GSR_unchanged=True,unknown_INIT_preserved=True,old_Q_established_only_by_clocked_writes=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
