#!/usr/bin/env python3
"""Prove actual 47-bit controller/nine-control single-step host-data independence.

Independently retrace all actual 1245 cells/954 producer bits. Require the
completed qualification of all 47 literal FDCE configurations. Freshly exhaust
every combinational instance's binary inputs against unchanged pinned vendor
and byte-identical selected synthesis models, including the actual new LUT1
instances. Run the executed wrong corpus and real one-bit SAT negative before
the warning-free positive, preserving the 120-second SAT limit. The antecedent
is current actual state 0..2 after GSR; all 938 other current producer values
are shared, the two 16-bit host data values are independent. This is a binary
conditional single-step property, not temporal induction, initialization
completion, write-before-read, startup, full numerical or physical signoff.
No original helper, RTL, model, input, live job or SHA256SUMS is changed.
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
import audit_prefix_initialization_controller_cone as controller
import qualify_prefix_controller_fdce_fold as fold
import prove_prefix_initialization_state_independence as prior
import unisim_board_models as models
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

PREPARED=fold.PREPARED
FOLD=ROOT/'build/openxc7/prefix-controller-fdce-fold-1791446444581356133/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_initialization_controller_independence_control.py'
PASS='PROVED_ACTUAL_47_BIT_CONTROLLER_AND_NINE_CONTROLS_BINARY_SINGLE_STEP_HOST_DATA_INDEPENDENCE_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
COUNTS=dict(CARRY4=24,INV=49,LUT1=30,LUT2=365,LUT3=114,LUT4=86,LUT5=97,LUT6=339,MUXF7=110,MUXF8=31)


def replay_cone(cone,selected):
    drivers={}
    def add(wire,record):
        assert type(wire) is int and wire>=2 and wire not in drivers,'Duplicate/unknown cached controller driver'
        drivers[wire]=record
    for name,cell in cone['cells'].items():
        _,outputs=controller.prior.state.coherent.validate_cell(cell)
        for pin in outputs:
            for bit,wire in enumerate(cell['connections'][pin]):add(wire,(name,cell,pin,bit))
    for wire,r in cone['producer_cuts'].items():
        w=int(wire);cell=r['original_primitive'];pin=r['pin'];bit=r['bit']
        assert cell['connections'][pin][bit]==w
        add(w,(r['cell'],cell,pin,bit))
    def driver(wire):
        assert wire in drivers,'Incomplete cached controller cone'
        return drivers[wire]
    actual=controller.trace_controller(cone['signals'],driver,selected)
    assert actual=={k:cone[k] for k in actual},'Changed/unreachable cached controller cone'
    assert len(actual['cells'])==1245 and len(actual['producer_cuts'])==954
    assert dict(Counter(c['type'] for c in actual['cells'].values()))==COUNTS
    return controller.miter(actual)


def admit(before):
    prepared=json.loads(PREPARED.read_text());qualified=json.loads(FOLD.read_text())
    assert prepared['status']==controller.PASS and prepared['stage']=='complete' and prepared['finished_utc']
    assert prepared['full_target_parallel_products']==512 and prepared['initialization_controller_data_independence_proved'] is False
    assert prepared['actual_cone_cells']==1245 and prepared['actual_producer_bits']==954 and prepared['actual_cone_primitive_counts']==COUNTS
    assert qualified['status']==fold.PASS and qualified['stage']=='complete' and qualified['finished_utc']
    assert qualified['controller_binary_fold_qualified'] and qualified['actual_controller_configurations']==47 and qualified['full_target_parallel_products']==512
    for path,r in ((PREPARED,prepared),(FOLD,qualified)):bind_report(path,r,before)
    verify_bindings(before)
    cone=json.loads((PREPARED.parent/'actual-initialization-controller-cone.json').read_text())
    assert cone['full_primitive_counts']==prepared['actual_full_primitive_counts'] and sum(cone['full_primitive_counts'].values())==503128
    assert cone['full_primitive_counts']['DSP48E1']==515 and cone['full_primitive_counts']['RAMB36E1']==6
    selected=json.loads((ROOT/'build/openxc7/prefix-config-contract-1791401020849392343/actual-selected-primitives.json').read_text())
    miter=replay_cone(cone,selected)
    assert miter==(PREPARED.parent/'actual-initialization-controller-miter.v').read_text()
    regs=json.loads((FOLD.parent/'actual-controller-FDCE-records.json').read_text())
    assert regs==cone['controller_registers'] and (FOLD.parent/'actual-controller-FDCEs.v').read_text()==fold.wrapper(regs)
    bench=FOLD.parent/'tb_prefix_controller_fdce_fold.sv';assert bench.read_text()==fold.bench_text()
    cmds={c['label']:c for c in qualified['commands']}
    for label,negative in (('negative',True),('positive',False)):
        c=cmds[label];fold.validate(Path(c['log']).read_text(),c['returncode'],negative,bench)
    library,definitions=controller.selected_definitions(controller.LIBRARY.read_bytes(),set(COUNTS))
    assert library==(PREPARED.parent/'unchanged_selected_controller_cells.v').read_bytes()
    assert definitions==prepared['selected_unchanged_library_definitions']
    return cone,miter,library


def compare_corpora(vendor,synthesis,width,footer):
    a=prior.results.vectors(vendor,width,footer);b=prior.results.vectors(synthesis,width,footer)
    assert a==b,'Actual controller-cone binary library mismatch'
    return dict(actual_instances=1245,binary_vectors=1024,per_instance_comparisons=1245*1024,
        output_bits=width,every_actual_combinational_input_combination_exhausted=True,four_state_library_equivalence=False)


def validate_wrong_corpus(vendor,wrong,width,footer):
    a=prior.results.vectors(vendor,width,footer);b=prior.results.vectors(wrong,width,footer)
    assert a[0]^b[0]==1 and a[1:]==b[1:],'Not the actual one-bit controller corpus mutation'
    try:compare_corpora(vendor,wrong,width,footer)
    except AssertionError as e:assert str(e)=='Actual controller-cone binary library mismatch'
    else:raise AssertionError('Actual controller binary corpus negative accepted')


def main():
    out=ROOT/f'build/openxc7/prefix-initialization-controller-independence-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        full_target_parallel_products=512,actual_symbolic_binary_input_bits=970,shared_producer_bits=938,
        independently_variable_host_data_bits_per_copy=16,compared_next_controller_bits=47,compared_observed_controls=9,
        property_antecedent='actual retained four-bit state 0,1,2; after GSR at positive clock edge',input_assumptions=[],
        other_producer_values_shared_by_construction=True,initialization_controller_data_independence_proved=False,
        controller_binary_fold_qualified=False,controller_cone_binary_library_qualified=False,four_state_library_equivalence=False,
        temporal_port_ownership_proved=False,write_before_read_proved=False,full_board_startup_independence_proved=False,
        full_board_numerical_acceptance=False,physical_fit_verified=False,timing_signoff=False,electrical_verified=False,
        drc_signoff=False,bitstream_emitted=False,hardware_programmed=False,hardware_input_modified=False,native_PNR_executed=False)
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
            if negative is not None:controller.prior.state.raw.validate_result(text,code,negative)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_FORMAL_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={};cone,miter,library_data=admit(before);pinned=models.selected_models(set(COUNTS))
        for path,sha in pinned.items():assert digest(path)==sha,'Changed pinned controller model'
        files={Path(__file__).resolve(),CONTROL,*pinned,Path(sys.executable).resolve(),*(Path(shutil.which(t)).resolve() for t in ('iverilog','vvp','yosys'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        verify_bindings(before);report['source']=before
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        report['yosys_version']=run('yosys_version',['yosys','-V']).strip()
        (out/'actual-initialization-controller-cone.json').write_text(json.dumps(cone,indent=2,sort_keys=True)+'\n')
        source=out/'actual-initialization-controller-miter.v';source.write_text(miter)
        library=out/'unchanged_selected_controller_cells.v';library.write_bytes(library_data)
        text,width=prior.declared.qualify_bench(cone['cells']);assert width==1413
        bench=out/'binary_library_control.sv';bench.write_text(text);footer=prior.results.expected_finish(bench,text)
        frozen=[]
        for path in pinned:
            target=out/'models'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            if target.suffix=='.v':frozen.append(target)
        execution={str(p):digest(p) for p in (source,library,bench,*frozen)};outputs={}
        report['stage']='fresh_actual_controller_binary_library_qualification';save()
        for view,models_used in (('vendor',frozen),('synthesis',[library,*[p for p in frozen if p.name=='glbl.v']])):
            binary=out/(view+'.vvp')
            run(view+'_compile',['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl','-o',binary,*models_used,bench])
            execution[str(binary)]=digest(binary);outputs[view]=run(view+'_test',['vvp',binary])
        report['binary_library_qualification']=compare_corpora(outputs['vendor'],outputs['synthesis'],width,footer)
        wrong=run('synthesis_wrong_golden_test',['vvp',out/'synthesis.vvp','+NEGATIVE=1'])
        validate_wrong_corpus(outputs['vendor'],wrong,width,footer)
        report.update(binary_library_real_negative='REJECTED_EXECUTED_FIRST_VECTOR_ONE_BIT_MUTATION',
            controller_cone_binary_library_qualified=True,controller_binary_fold_qualified=True,execution_inputs=execution)
        verify_bindings(execution);verify_bindings(before);report['stage']='actual_binary_single_step_controller_SAT';save()
        for label,negative in (('negative',True),('positive',False)):
            script=out/(label+'.ys')
            script.write_text('read_verilog '+str(library)+'\nread_verilog '+str(source)+'\nchparam -set NEGATIVE '+str(int(negative))+' prefix_init_controller_miter\nhierarchy -check -top prefix_init_controller_miter\nflatten\nproc\nopt -full\nwreduce\nopt -full\ncheck -assert\n'
                'sat -verify -prove ok 1 -show-inputs -show-outputs -show state -show compared_0 -show compared_1 -show init_phase -timeout 120 -dump_json '+str(out/(label+'-counterexample.json'))+'\n')
            execution[str(script)]=digest(script);run(label,['yosys','-Q','-T','-s',script],negative)
            verify_bindings(execution);verify_bindings(before)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',initialization_controller_data_independence_proved=True,
            actual_cone_cells=1245,actual_cone_primitive_counts=COUNTS,actual_producer_bits=954,
            actual_full_primitive_counts=cone['full_primitive_counts'],proof_is_binary_single_step_conditional_only=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
