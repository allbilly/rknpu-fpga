#!/usr/bin/env python3
"""Prove one-step actual state independence from cold host data in INIT 0..2.

Rebind and independently retrace the complete actual 497-cell/695-producer
cone. Require the actual four FDCE binary/async fold qualification. Exhaust
all binary inputs of every actual combinational instance against unchanged
pinned vendor and byte-identical selected synthesis-library models. Execute
its genuine one-bit corpus negative before fresh warning-free actual SAT
positive and real next-state-golden negative at original 120-second limits.
All non-host producer values are shared by construction; the two 16-bit host
data inputs are independent. This is a conditional binary single-step state
property after GSR, not reachability, four-state, initialization completion,
write-before-read, temporal ownership, whole startup/numerical or signoff.
No RTL, input, model, old gate/live job or SHA256SUMS is changed.
"""
from collections import Counter
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
import qualify_prefix_state_fdce_fold as fold
import resume_declared_binary_prefix_bram_address as declared
import resume_binary_result_prefix_bram_address as results
import unisim_board_models as models
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

PREPARED=ROOT/'build/openxc7/prefix-initialization-state-cone-1791443814047584119/report.json'
FOLD=ROOT/'build/openxc7/prefix-state-fdce-fold-1791444111003194131/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_initialization_state_independence_control.py'
PASS='PROVED_ACTUAL_INITIALIZATION_STATE_BINARY_SINGLE_STEP_HOST_DATA_INDEPENDENCE_OVER_SHARED_PRODUCER_BOUNDARY_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
COUNTS=dict(INV=4,LUT2=197,LUT3=36,LUT4=43,LUT5=27,LUT6=184,MUXF7=4,MUXF8=2)


def replay_cone(cone,selected):
    drivers={}
    def add(wire,record):
        assert type(wire) is int and wire>=2 and wire not in drivers,'Duplicate/unknown cached driver'
        drivers[wire]=record
    for name,cell in cone['cells'].items():
        _,outputs=state.coherent.validate_cell(cell)
        for pin in outputs:
            for bit,wire in enumerate(cell['connections'][pin]):add(wire,(name,cell,pin,bit))
    for wire,record in cone['producer_cuts'].items():
        w=int(wire);cell=record['original_primitive'];pin=record['pin'];bit=record['bit']
        assert cell['connections'][pin][bit]==w
        add(w,(record['cell'],cell,pin,bit))
    def driver(wire):
        assert wire in drivers,'Incomplete cached state cone';return drivers[wire]
    actual=state.trace_state(cone['signals'],driver,selected)
    assert actual=={key:cone[key] for key in actual},'Unreachable/changed cached state cone'
    assert len(actual['cells'])==497 and len(actual['producer_cuts'])==695
    assert dict(Counter(c['type'] for c in actual['cells'].values()))==COUNTS
    return state.miter(actual)


def admit(before):
    prepared=json.loads(PREPARED.read_text());qualified=json.loads(FOLD.read_text())
    assert prepared['status']=='EXTRACTED_ACTUAL_INITIALIZATION_STATE_CONE_AND_FRONTEND_CHECKED_PAIRED_MITER_NOT_INDEPENDENCE_OR_STARTUP_PROOF'
    assert prepared['stage']=='complete' and prepared['finished_utc'] and prepared['full_target_parallel_products']==512
    assert prepared['initialization_state_data_independence_proved'] is False
    assert prepared['actual_cone_cells']==497 and prepared['actual_producer_bits']==695
    assert prepared['actual_cone_primitive_counts']==COUNTS
    assert qualified['status']==fold.PASS and qualified['stage']=='complete' and qualified['finished_utc']
    assert qualified['next_state_binary_fold_qualified'] is True and qualified['retained_full_target_parallel_products']==512
    for path,record in ((PREPARED,prepared),(FOLD,qualified)):bind_report(path,record,before)
    verify_bindings(before)
    cone=json.loads((PREPARED.parent/'actual-initialization-state-cone.json').read_text())
    assert cone['full_primitive_counts']==prepared['actual_full_primitive_counts']
    assert sum(cone['full_primitive_counts'].values())==503128
    assert cone['full_primitive_counts']['DSP48E1']==515 and cone['full_primitive_counts']['RAMB36E1']==6
    selected=json.loads(state.raw.ROOT.joinpath('build/openxc7/prefix-config-contract-1791401020849392343/actual-selected-primitives.json').read_text())
    text=replay_cone(cone,selected)
    assert text==(PREPARED.parent/'actual-initialization-state-miter.v').read_text()
    regs=json.loads((FOLD.parent/'actual-state-FDCE-records.json').read_text())
    assert [dict(cell=r['cell'],original_primitive=r['original_primitive']) for r in regs]==cone['state_registers']
    assert (FOLD.parent/'actual-state-FDCEs.v').read_text()==fold.wrapper(regs)
    bench=FOLD.parent/fold.BENCH.name;assert bench.read_bytes()==fold.BENCH.read_bytes()
    cmds={c['label']:c for c in qualified['commands']}
    for label,negative in (('negative',True),('positive',False)):
        c=cmds[label];fold.validate(Path(c['log']).read_text(),c['returncode'],negative,bench)
    assert state.digest(state.LIBRARY)==state.digest(PREPARED.parent/'unchanged_selected_combinational_cells.v')
    return cone,text


def compare_corpora(vendor,synthesis,width,footer):
    a=results.vectors(vendor,width,footer);b=results.vectors(synthesis,width,footer)
    assert a==b,'Actual state-cone binary library mismatch'
    return dict(actual_instances=497,binary_vectors=1024,per_instance_comparisons=497*1024,
        output_bits=width,every_actual_combinational_input_combination_exhausted=True,
        four_state_library_equivalence=False)


def validate_wrong_corpus(vendor,wrong,width,footer):
    a=results.vectors(vendor,width,footer);b=results.vectors(wrong,width,footer)
    assert a[0]^b[0]==1 and a[1:]==b[1:],'Not the executed one-bit first-vector mutation'
    try:compare_corpora(vendor,wrong,width,footer)
    except AssertionError as error:assert str(error)=='Actual state-cone binary library mismatch'
    else:raise AssertionError('Actual binary corpus negative unexpectedly accepted')


def main():
    out=ROOT/f'build/openxc7/prefix-initialization-state-independence-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        full_target_parallel_products=512,actual_symbolic_binary_input_bits=711,shared_producer_bits=679,
        independently_variable_host_data_bits_per_copy=16,compared_next_state_bits=4,
        property_antecedent='actual retained four-bit state in 0,1,2; after GSR at positive clock edge',
        input_assumptions=[],other_producer_values_shared_by_construction=True,
        initialization_state_data_independence_proved=False,next_state_binary_fold_qualified=False,
        actual_cone_binary_library_qualified=False,four_state_library_equivalence=False,
        temporal_port_ownership_proved=False,write_before_read_proved=False,full_board_startup_independence_proved=False,
        full_board_numerical_acceptance=False,physical_fit_verified=False,timing_signoff=False,
        electrical_verified=False,drc_signoff=False,bitstream_emitted=False,hardware_programmed=False,
        hardware_input_modified=False,native_PNR_executed=False)
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
            if negative is not None:state.raw.validate_result(text,code,negative)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_FORMAL_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={};cone,miter=admit(before);kinds=set(COUNTS);pinned=models.selected_models(kinds)
        for path,sha in pinned.items():assert digest(path)==sha,'Changed pinned vendor model'
        files={Path(__file__).resolve(),CONTROL,*pinned,Path(sys.executable).resolve(),
            *(Path(shutil.which(t)).resolve() for t in ('iverilog','vvp','yosys'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        verify_bindings(before);report['source']=before
        report['stage']='software_controls';save()
        run('software_controls',[sys.executable,'-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        report['yosys_version']=run('yosys_version',['yosys','-V']).strip()
        (out/'actual-initialization-state-cone.json').write_text(json.dumps(cone,indent=2,sort_keys=True)+'\n')
        source=out/'actual-initialization-state-miter.v';source.write_text(miter)
        library=out/'unchanged_selected_combinational_cells.v';shutil.copyfile(state.LIBRARY,library)
        bench_text,width=declared.qualify_bench(cone['cells']);assert width==497
        bench=out/'binary_library_control.sv';bench.write_text(bench_text);footer=results.expected_finish(bench,bench_text)
        frozen=[]
        for path in pinned:
            target=out/'models'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            if target.suffix=='.v':frozen.append(target)
        execution={str(p):digest(p) for p in (source,library,bench,*frozen)};outputs={}
        report['stage']='fresh_actual_cone_binary_library_qualification';save()
        for view,files in (('vendor',frozen),('synthesis',[library,*[p for p in frozen if p.name=='glbl.v']])):
            binary=out/(view+'.vvp')
            run(view+'_compile',['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl','-o',binary,*files,bench])
            execution[str(binary)]=digest(binary);outputs[view]=run(view+'_test',['vvp',binary])
        report['binary_library_qualification']=compare_corpora(outputs['vendor'],outputs['synthesis'],width,footer)
        wrong=run('synthesis_wrong_golden_test',['vvp',out/'synthesis.vvp','+NEGATIVE=1'])
        validate_wrong_corpus(outputs['vendor'],wrong,width,footer)
        report['binary_library_real_negative']='REJECTED_EXECUTED_FIRST_VECTOR_ONE_BIT_MUTATION'
        report['actual_cone_binary_library_qualified']=True;report['next_state_binary_fold_qualified']=True
        report['execution_inputs']=execution;verify_bindings(execution);verify_bindings(before)
        report['stage']='actual_binary_single_step_state_SAT';save()
        for label,negative in (('negative',True),('positive',False)):
            script=out/(label+'.ys')
            script.write_text('read_verilog '+str(library)+'\nread_verilog '+str(source)+'\nchparam -set NEGATIVE '+str(int(negative))+' prefix_init_state_miter\nhierarchy -check -top prefix_init_state_miter\nflatten\nproc\nopt -full\nwreduce\nopt -full\ncheck -assert\n'
                'sat -verify -prove ok 1 -show-inputs -show-outputs -show state -show next_0 -show next_1 -show init_phase -timeout 120 -dump_json '+str(out/(label+'-counterexample.json'))+'\n')
            execution[str(script)]=digest(script);run(label,['yosys','-Q','-T','-s',script],negative)
            verify_bindings(execution);verify_bindings(before)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',initialization_state_data_independence_proved=True,
            actual_cone_cells=497,actual_cone_primitive_counts=COUNTS,actual_producer_bits=695,
            actual_full_primitive_counts=cone['full_primitive_counts'],proof_is_binary_single_step_conditional_only=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
