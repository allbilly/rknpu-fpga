#!/usr/bin/env python3
"""Qualify the exact 50 controller FDCEs, 1325 combinational cells and clears.

Independently retrace the completed source-bound DMA-inclusive extraction.
Preserve all actual parameters, literal unknown INIT and complete unchanged
selected synthesis definitions. Run default-GSR vendor FDCE seed/async/next
checks for all sixteen binary tuples, and freshly exhaust every actual
combinational instance against pinned vendor and synthesis models. Execute
both real finite wrong-golden negatives. Certify all 50 clear roots over the
32 reset/demo-state combinations, with no opaque dependencies or cycles.
This qualifies a binary post-edge clear fixed point, not temporal induction,
four-state startup, full numerical acceptance or physical signoff. No RTL,
old helper/model/input, live job or standalone SHA256SUMS is changed.
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
import audit_prefix_temporal_controller_cone as controller
import qualify_prefix_state_fdce_fold as original
import unisim_board_models as models
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

PREPARED=ROOT/'build/openxc7/prefix-temporal-controller-cone-1791448312463936386/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_temporal_controller_primitives_control.py'
COUNTS=dict(CARRY4=30,INV=58,LUT1=30,LUT2=402,LUT3=120,LUT4=91,LUT5=102,LUT6=351,MUXF7=110,MUXF8=31)
MARKER='PASS actual 50 controller FDCE binary folds vectors=16 seed_checks=800 async_checks=800 next_checks=800 default_gsr=100ns; not temporal startup or physical acceptance'
PASS='QUALIFIED_ACTUAL_50_CONTROLLER_FDCE_AND_1325_BINARY_CELLS_AND_ASYNC_CLEAR_FIXED_POINT_NOT_TEMPORAL_PROOF_OR_SIGNOFF'


def replay_cone(cone,selected):
    drivers={}
    def add(wire,record):
        assert type(wire) is int and wire>=2 and wire not in drivers,'Duplicate/unknown temporal controller driver'
        drivers[wire]=record
    for name,cell in cone['cells'].items():
        _,outputs=controller.base.prior.state.coherent.validate_cell(cell)
        for pin in outputs:
            for bit,wire in enumerate(cell['connections'][pin]):add(wire,(name,cell,pin,bit))
    for wire,r in cone['producer_cuts'].items():
        w=int(wire);cell=r['original_primitive'];pin=r['pin'];bit=r['bit']
        assert cell['connections'][pin][bit]==w
        add(w,(r['cell'],cell,pin,bit))
    def driver(wire):
        assert wire in drivers,'Incomplete cached temporal controller cone'
        return drivers[wire]
    actual=controller.trace_controller(cone['signals'],driver,selected)
    assert actual=={k:cone[k] for k in actual},'Changed/unreachable cached temporal controller cone'
    assert len(actual['cells'])==1325 and len(actual['producer_cuts'])==1019
    assert dict(Counter(c['type'] for c in actual['cells'].values()))==COUNTS
    return actual


def admit(before):
    r=json.loads(PREPARED.read_text())
    assert r['status']==controller.PASS and r['stage']=='complete' and r['finished_utc']
    assert r['full_target_parallel_products']==512 and r['controller_state_bits']==50 and r['observed_control_bits']==10
    assert r['actual_cone_cells']==1325 and r['actual_producer_bits']==1019 and r['actual_cone_primitive_counts']==COUNTS
    assert r['actual_controller_state_initially_unconstrained'] and r['other_producers_free_each_cycle']
    assert r['temporal_port_ownership_proved'] is False and r['write_before_read_proved'] is False
    bind_report(PREPARED,r,before);verify_bindings(before)
    cone=json.loads((PREPARED.parent/'actual-initialization-controller-cone.json').read_text())
    assert cone['full_primitive_counts']==r['actual_full_primitive_counts'] and sum(cone['full_primitive_counts'].values())==503128
    assert cone['full_primitive_counts']['DSP48E1']==515 and cone['full_primitive_counts']['RAMB36E1']==6
    selected=json.loads((ROOT/'build/openxc7/prefix-config-contract-1791401020849392343/actual-selected-primitives.json').read_text())
    actual=replay_cone(cone,selected)
    assert controller.miter(actual)==(PREPARED.parent/'actual-initialization-controller-miter.v').read_text()
    assert controller.clock_model(actual)==(PREPARED.parent/'actual-binary-temporal-controller.v').read_text()
    regs=cone['controller_registers']
    assert [(x['signal'],x['offset']) for x in regs]==[(name,i) for name,width in controller.REGISTERS.items() for i in range(width)]
    for x in regs:
        c=x['original_primitive'];controller.base.validate_fold_register(c,[8])
        assert c['parameters']=={'INIT':'x'} and c['connections']['Q']==[cone['signals'][x['signal']][x['offset']]]
    library,definitions=controller.base.selected_definitions(controller.base.LIBRARY.read_bytes(),set(COUNTS))
    assert library==(PREPARED.parent/'unchanged_selected_controller_cells.v').read_bytes()
    assert definitions==r['selected_unchanged_library_definitions']
    return cone,library


def wrapper(regs):
    assert len(regs)==50 and len({r['cell'] for r in regs})==50
    lines=['module actual_prefix_temporal_fdces(input clk,clear,enable,data,output [49:0] observed);']
    for i,r in enumerate(regs):
        c=r['original_primitive'];controller.base.validate_fold_register(c,[8])
        parameters=','.join('.'+name+"(1'b"+value+')' for name,value in sorted(c['parameters'].items()))
        parameter=' #('+parameters+')' if parameters else ''
        lines.append('FDCE'+parameter+' actual_'+str(i)+'(.C(clk),.CE(enable),.D(data),.CLR(clear),.Q(observed['+str(i)+']));')
    return '\n'.join(lines+['endmodule'])+'\n'


def bench_text():
    source=original.BENCH.read_text();text=source
    substitutions=(('tb_prefix_state_fdce_fold','tb_prefix_temporal_fdce_fold'),
        ('wire [3:0] observed;','wire [49:0] observed;'),
        ('actual_prefix_state_fdces','actual_prefix_temporal_fdces'),
        ('cell_index<4;','cell_index<50;'),
        ('seeds!=64||async_checks!=64||next_checks!=64','seeds!=800||async_checks!=800||next_checks!=800'),
        (original.MARKER,MARKER))
    assert source.count('cell_index<4;')==3
    for old,new in substitutions:
        assert old in text and new not in text
        text=text.replace(old,new)
    restored=text
    for old,new in reversed(substitutions):restored=restored.replace(new,old)
    assert restored==source,'Changed original FDCE stimulus or golden'
    return text


def validate_fold(text,code,negative,bench):
    assert text.count(MARKER)==(0 if negative else 1) and original.MARKER not in text
    original.validate(text.replace(MARKER,original.MARKER),code,negative,bench)


def clear_certificate(cone):
    """Exact binary clear function plus a structural one-pass fixed point."""
    cuts=set(map(int,cone['producer_cuts']));drivers={}
    for name,cell in cone['cells'].items():
        inputs,outputs=controller.base.prior.state.coherent.validate_cell(cell)
        for pin in outputs:
            for offset,w in enumerate(cell['connections'][pin]):
                assert w not in drivers and w not in cuts,'Duplicate clear cone driver'
                drivers[w]=(name,cell,inputs,pin,offset)
    reset=cone['signals']['demo.rst_n'][0];state=cone['signals']['demo.state']
    assert reset==15190 and state==[29117,29119,44287,44288]
    dependencies={};clear_cells=set()
    def leaves(w,stack=frozenset()):
        if w in ('0','1'):return frozenset()
        if w in cuts:return frozenset({w})
        assert w not in stack and w in drivers,'Unknown/cyclic async clear dependency'
        if w in dependencies:return dependencies[w]
        name,cell,inputs,pin,offset=drivers[w]
        assert cell['type'] in {'INV','MUXF7','MUXF8',*('LUT'+str(i) for i in range(1,7))},'Unqualified async clear primitive'
        assert offset==0 and pin in ('O','Z')
        clear_cells.add(name)
        value=frozenset().union(*(leaves(x,stack|{w}) for p in inputs for x in cell['connections'][p]))
        dependencies[w]=value;return value
    records=[]
    for r in cone['controller_registers']:
        root=r['original_primitive']['connections']['CLR'][0]
        demo=r['signal'] in ('demo.state','demo.index','demo.watchdog','demo.error_code')
        expected={reset} if demo else {reset,*state}
        actual=leaves(root)
        assert actual==expected,'Unexpected actual async clear producer'
        records.append(dict(signal=r['signal'],offset=r['offset'],cell=r['cell'],root=root,
            leaves=sorted(actual),golden='!reset_n' if demo else '!reset_n || demo_state==10'))
    assert len(records)==50 and sum(x['golden']=='!reset_n' for x in records)==44
    rows=[]
    for reset_value in range(2):
        for state_value in range(16):
            values={reset:reset_value,**{w:(state_value>>i)&1 for i,w in enumerate(state)}}
            def evaluate(w):
                if w in ('0','1'):return int(w)
                if w in values:return values[w]
                assert w in drivers,'Unbound async clear input'
                _,cell,_,_,_=drivers[w];ports=cell['connections'];kind=cell['type']
                def b(p):return evaluate(ports[p][0])
                if kind=='INV':value=1-b('I')
                elif kind.startswith('LUT'):
                    n=int(kind[3:]);index=sum(b('I'+str(i))<<i for i in range(n))
                    value=(int(cell['parameters']['INIT'],2)>>index)&1
                elif kind in ('MUXF7','MUXF8'):value=b('I1') if b('S') else b('I0')
                else:raise AssertionError('Unqualified async clear evaluation')
                values[w]=value;return value
            outputs=[]
            for r in records:
                actual=evaluate(r['root']);golden=int(not reset_value or (r['golden']!='!reset_n' and state_value==10))
                assert actual==golden,'Actual binary async clear golden mismatch'
                outputs.append(actual)
            rows.append(dict(reset_n=reset_value,demo_state=state_value,clear_bits_lsb_first=outputs))
    return dict(actual_register_clear_roots=records,actual_clear_cells=sorted(clear_cells),binary_rows=rows,
        actual_roots_checked=50,reset_state_cases=32,binary_root_comparisons=1600,
        demo_clear_depends_only_on_reset=True,other_owned_clears_depend_only_on_reset_and_demo_state=True,
        other_owned_state_cannot_change_its_own_clear=True,one_post_edge_clear_application_is_fixed_point=True,
        between_edge_reset_pulses_modeled=False,four_state_clear_equivalence=False)


def compare_corpora(vendor,synthesis,width,footer):
    results=controller.proof.prior.results
    a=results.vectors(vendor,width,footer);b=results.vectors(synthesis,width,footer)
    assert a==b,'Actual temporal controller binary library mismatch'
    return dict(actual_instances=1325,binary_vectors=1024,per_instance_comparisons=1325*1024,
        output_bits=width,every_actual_combinational_input_combination_exhausted=True,four_state_library_equivalence=False)


def validate_wrong_corpus(vendor,wrong,width,footer):
    results=controller.proof.prior.results
    a=results.vectors(vendor,width,footer);b=results.vectors(wrong,width,footer)
    assert a[0]^b[0]==1 and a[1:]==b[1:],'Not the executed one-bit temporal corpus mutation'
    try:compare_corpora(vendor,wrong,width,footer)
    except AssertionError as e:assert str(e)=='Actual temporal controller binary library mismatch'
    else:raise AssertionError('Actual temporal binary corpus negative accepted')


def main():
    out=ROOT/f'build/openxc7/prefix-temporal-controller-primitives-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        full_target_parallel_products=512,controller_binary_fold_qualified=False,controller_cone_binary_library_qualified=False,
        async_clear_fixed_point_qualified=False,temporal_port_ownership_proved=False,write_before_read_proved=False,
        full_board_startup_independence_proved=False,full_board_numerical_acceptance=False,four_state_library_equivalence=False,
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
            if negative is not None:validate_fold(text,code,negative,fold_bench)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_WRONG_GOLDEN_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={};cone,library_data=admit(before);pinned=models.selected_models(set(COUNTS)|{'FDCE'})
        files={Path(__file__).resolve(),CONTROL,original.BENCH,*pinned,Path(sys.executable).resolve(),
            *(Path(shutil.which(t)).resolve() for t in ('iverilog','vvp'))}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        for path,sha in pinned.items():assert digest(path)==sha,'Changed pinned temporal controller model'
        verify_bindings(before);report['source']=before
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        report['iverilog_version']=run('iverilog_version',['iverilog','-V']).splitlines()[0]
        report['vvp_version']=run('vvp_version',['vvp','-V']).splitlines()[0]
        certificate=clear_certificate(cone)
        cert=out/'actual-async-clear-fixed-point.json';cert.write_text(json.dumps(certificate,indent=2,sort_keys=True)+'\n')
        regs=cone['controller_registers'];source=out/'actual-temporal-controller-FDCEs.v';source.write_text(wrapper(regs))
        regfile=out/'actual-temporal-controller-FDCE-records.json';regfile.write_text(json.dumps(regs,indent=2,sort_keys=True)+'\n')
        fold_bench=out/'tb_prefix_temporal_fdce_fold.sv';fold_bench.write_text(bench_text())
        library=out/'unchanged_selected_controller_cells.v';library.write_bytes(library_data)
        text,width=controller.proof.prior.declared.qualify_bench(cone['cells']);assert width==1535
        bench=out/'binary_library_control.sv';bench.write_text(text)
        footer=controller.proof.prior.results.expected_finish(bench,text);frozen=[]
        for path in pinned:
            target=out/'models'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
            if target.suffix=='.v':frozen.append(target)
        execution={str(p):digest(p) for p in (cert,source,regfile,fold_bench,library,bench,*frozen)}
        binary=out/'fold.vvp';report.update(stage='native_actual_50_FDCE_qualification',execution_inputs=execution);save()
        run('fold_compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_temporal_fdce_fold','-s','glbl','-o',binary,
            *[p for p in frozen if p.name in ('FDCE.v','glbl.v')],source,fold_bench])
        execution[str(binary)]=digest(binary)
        for label,options,negative in (('fold_negative',['+NEGATIVE=1'],True),('fold_positive',[],False)):
            run(label,['vvp',binary,*options],negative);verify_bindings(execution)
        report.update(controller_binary_fold_qualified=True,actual_controller_configurations=50,
            binary_old_Q_D_CE_CLR_tuples=16,seed_checks=800,async_checks=800,next_checks=800,
            default_GSR_unchanged=True,actual_INIT_preserved=True,old_Q_established_only_by_clocked_writes=True,
            stage='fresh_actual_1325_cell_binary_library_qualification');save();outputs={}
        for view,models_used in (('vendor',frozen),('synthesis',[library,*[p for p in frozen if p.name=='glbl.v']])):
            binary=out/(view+'.vvp')
            run(view+'_compile',['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl','-o',binary,*models_used,bench])
            execution[str(binary)]=digest(binary);outputs[view]=run(view+'_test',['vvp',binary])
        report['binary_library_qualification']=compare_corpora(outputs['vendor'],outputs['synthesis'],width,footer)
        wrong=run('synthesis_wrong_golden_test',['vvp',out/'synthesis.vvp','+NEGATIVE=1'])
        validate_wrong_corpus(outputs['vendor'],wrong,width,footer)
        verify_bindings(before);verify_bindings(execution)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',controller_cone_binary_library_qualified=True,async_clear_fixed_point_qualified=True,
            binary_library_real_negative='REJECTED_EXECUTED_FIRST_VECTOR_ONE_BIT_MUTATION',
            actual_cone_cells=1325,actual_cone_primitive_counts=COUNTS,actual_producer_bits=1019,
            actual_full_primitive_counts=cone['full_primitive_counts'],async_clear_root_comparisons=1600,
            async_clear_reset_state_cases=32,post_edge_clear_application_is_fixed_point=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
