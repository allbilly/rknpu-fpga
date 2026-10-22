#!/usr/bin/env python3
"""Prove a binary sampled-reset barrier at the actual two working-BRAM pins.

Preserve the full C32/K16 input, all 512 parallel products and old evidence.
Revalidate the completed controller proof and exact six-BRAM wiring/control
audits. Freshly census the complete 503128-cell input, then trace the actual
working-RAM enables and write drivers too: never assume these two missing
drivers are the same as controller fire. Qualify every expanded combinational
instance against unchanged pinned models, with an executed corpus negative.
Run actual initialization-phase host-data independence and temporal induction,
each with a genuine wrong-golden negative. Ghost initialization writes/probe
coverage use the physical A enable/write/address pins. No RAM contents or
ROM data are substituted. Binary read/write-before-use and pin ownership are
not four-state/full-board startup, data-value/liveness or physical signoff.
No RTL, frozen helper/model/input, live job or SHA256SUMS is changed.
"""
from collections import Counter
import inspect
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
import audit_prefix_temporal_controller_cone as temporal
import resume_wavejson_prefix_binary_temporal_ownership as completed
import audit_prefix_memory_wiring as wiring
import audit_prefix_bram_control_wiring as controls
import unisim_board_models as models
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

PARENT=ROOT/'build/openxc7/prefix-binary-temporal-ownership-wavejson-1791450218791135300/report.json'
WIRING=ROOT/'build/openxc7/prefix-memory-wiring-audit-1791408308815007879/report.json'
CONTROLS=ROOT/'build/openxc7/prefix-bram-control-wiring-1791422081130315089/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_actual_bram_barrier_control.py'
PASS='PROVED_ACTUAL_WORKING_BRAM_BINARY_SAMPLED_RESET_PHYSICAL_PIN_OWNERSHIP_AND_READ_BARRIER_NOT_FULL_STARTUP_OR_FPGA_SIGNOFF'
REGISTERS=temporal.REGISTERS
PIN_SIGNALS={'bram.host_enable':'ENARDEN','bram.core_enable':'ENBWREN','bram.host_we':'WEA','bram.core_we':'WEBWE'}
SEMANTIC_WIDTHS={**temporal.WIDTHS,'demo.memory.req_write':1}
WIDTHS={**SEMANTIC_WIDTHS,**dict.fromkeys(PIN_SIGNALS,1)}
OUTPUTS=(*temporal.OUTPUTS,*PIN_SIGNALS)
SHOW=(*completed.previous.SHOW,'bram_host_enable','bram_core_enable','bram_host_we','bram_core_we')

NAMESPACE=dict(temporal.base.__dict__,REGISTERS=REGISTERS,WIDTHS=WIDTHS,OUTPUTS=OUTPUTS)
exec(compile(temporal.TRACE_SOURCE,__file__+':unchanged-expanded-actual-driver-trace','exec'),NAMESPACE)
trace_controller=NAMESPACE['trace_controller']
MITER_SOURCE=source_shaped(temporal.MITER_SOURCE,(('prefix_temporal_controller_miter','prefix_actual_bram_miter'),))
exec(compile(MITER_SOURCE,__file__+':unchanged-expanded-actual-paired-miter','exec'),NAMESPACE)
miter=NAMESPACE['miter']
ALIAS_NAMESPACE=dict(temporal.base.__dict__,WIDTHS=SEMANTIC_WIDTHS)
exec(compile(inspect.getsource(temporal.base.aliases),__file__+':literal-expanded-semantic-aliases','exec'),ALIAS_NAMESPACE)


def verify_completed_temporal(before):
    cone,model,library,certificate=completed.admit(before)
    r=json.loads(PARENT.read_text())
    assert r['status']==completed.previous.PASS and r['stage']=='complete' and r['finished_utc']
    assert r['full_target_parallel_products']==512 and r['native_induction_length']==1
    assert r['binary_model_temporal_port_ownership_proved'] and r['binary_prefix_write_before_core_request_proved']
    assert r['arbitrary_probe_prefix_coverage_proved'] and r['full_strengthened_safety_conjunction_proved']
    assert r['full_board_startup_independence_proved'] is False and r['bitstream_emitted'] is False
    bind_report(PARENT,r,before);verify_bindings(before)
    assert (PARENT.parent/'actual-binary-temporal-controller.v').read_text()==model
    assert (PARENT.parent/'unchanged_selected_controller_cells.v').read_bytes()==library
    commands={c['label']:c for c in r['commands']}
    for label,negative in (('negative',True),('positive',False)):
        c=commands[label];text=Path(c['log']).read_text();length=completed.previous.validate(text,c['returncode'],negative)
        root=PARENT.parent;witness=root/(label+'-counterexample.json')
        assert (root/(label+'.ys')).read_text()==completed.previous.script(root/'unchanged_selected_controller_cells.v',root/'actual-binary-temporal-controller.v',negative,witness)
        if negative:assert json.loads(json.dumps(completed.negative_trace(text,json.loads(witness.read_text()))))==r['real_negative']
        else:assert length==1 and not witness.exists()
    return cone,certificate


def admit(before):
    original,certificate=verify_completed_temporal(before)
    a=json.loads(WIRING.read_text());b=json.loads(CONTROLS.read_text());consumer=json.loads(wiring.CONSUMER.read_text())
    assert a['status']=='AUDITED_FULL_ROM_AND_WORKING_RAM_ADDRESS_DATA_WIRING_NOT_STARTUP_OR_FASM_SIGNOFF'
    assert b['status']=='AUDITED_FULL_BRAM_ENABLE_AND_LOCAL_BINARY_WRITE_GATING_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
    assert a['stage']==b['stage']=='complete' and a['finished_utc'] and b['finished_utc']
    for p,r in ((WIRING,a),(CONTROLS,b),(wiring.CONSUMER,consumer)):bind_report(p,r,before)
    selected=json.loads(wiring.SELECTED.read_text());brams={n:c for n,c in selected.items() if c['type']=='RAMB36E1'}
    classification=consumer['BRAM_memory_classification']
    wire=json.loads((WIRING.parent/'actual-memory-wire-bindings.json').read_text())
    control=json.loads((CONTROLS.parent/'actual-BRAM-control-cones.json').read_text())
    checked=wiring.verify_wiring(brams,classification,wire['logical_signal_physical_wires'])
    assert json.loads(json.dumps(checked))==wire['wiring_checks']==a['wiring_checks']
    drivers={int(w):r for w,r in control['actual_control_drivers'].items()}
    assert controls.binary_control_contract(brams,classification,control['logical_signal_physical_wires'],drivers)==control['checks']==b['checks']
    rams={n:c for n,c in brams.items() if not classification[n]['readonly']}
    assert set(rams)=={'rk_mapped_cell_86684','rk_mapped_cell_86685'}
    assert wire['logical_signal_physical_wires']['demo.index']==original['signals']['demo.index']
    assert wire['logical_signal_physical_wires']['demo.memory.host_rdata']==original['signals']['demo.memory.host_rdata']
    assert control['logical_signal_physical_wires']['host_fire']==original['signals']['demo.memory.host_fire'][0]
    assert control['logical_signal_physical_wires']['core_fire']==original['signals']['demo.memory.core_fire'][0]
    assert all(c['connections']['ADDRARDADDR']==['0']*3+original['signals']['demo.index']+['1'] for c in rams.values())
    verify_bindings(before)
    return original,certificate,selected,brams,classification,wire,control


def aliases(logical,physical,rams):
    result=ALIAS_NAMESPACE['aliases'](logical,physical)
    assert {name:result[name] for name in temporal.WIDTHS}==temporal.aliases(logical,physical)
    for signal,pin in PIN_SIGNALS.items():
        bits={tuple(c['connections'][pin]) for c in rams.values()};assert len(bits)==1
        value=next(iter(bits));assert type(value[0]) is int and value[0]>=2
        if pin=='WEA':assert value==(value[0],)*4
        elif pin=='WEBWE':assert value==(value[0],)*4+('0',)*4
        else:assert len(value)==1
        result[signal]=[value[0]]
    assert result['bram.host_enable']==result['demo.memory.host_fire']
    assert result['bram.core_enable']==result['demo.memory.core_fire']
    return result


def clock_model(cone):
    original=temporal.clock_model(cone)
    regs=cone['controller_registers'];q={r['original_primitive']['connections']['Q'][0]:i for i,r in enumerate(regs)}
    other={w:i for i,w in enumerate(sorted(set(map(int,cone['producer_cuts']))-set(q)))}
    def bit(w):
        if w in ('0','1'):return "1'b"+w
        if w in q:return 'storage_state['+str(q[w])+']'
        if w in other:return 'producer_input['+str(other[w])+']'
        return 't0_'+str(w)
    bridge='\n'.join('wire '+name.replace('.','_')+'='+bit(cone['signals'][name][0])+';' for name in PIN_SIGNALS)+'\n'
    golden='wire physical_write_equivalence=((bram_host_enable&&bram_host_we)==(host_fire&&host_write));\n'
    golden+='wire physical_ports_exclusive=!(bram_host_enable&&bram_core_enable);\n'
    golden+="wire physical_read_barrier=(!(bram_host_enable&&!bram_host_we)&&!bram_core_enable)||(writes_seen==13'd4096&&probe_written);\n"
    old='wire safe=prefix_coverage&&index_relation&&coverage_bound&&state_bound&&dma_idle_relation&&ports_exclusive&&core_after_complete;'
    new=golden+old[:-1]+'&&physical_write_equivalence&&physical_ports_exclusive&&physical_read_barrier;'
    text=source_shaped(original,(('prefix_temporal_controller_model','prefix_actual_bram_model'),
        ("reg seen_reset=1'b0;reg [12:0] writes_seen;reg [11:0] probe;reg probe_written;",bridge+"reg seen_reset=1'b0;reg [12:0] writes_seen;reg [11:0] probe;reg probe_written;"),
        ('else if(host_fire&&host_write)','else if(bram_host_enable&&bram_host_we)'),(old,new)))
    assert not re.search(r'\b(?:assume|anyseq|anyconst|force)\b',text)
    assert 'storage_state=' not in text
    return text


TRACE_NAMESPACE=dict(completed.previous.__dict__,SHOW=SHOW,WIDTHS={**completed.WIDTHS,**dict.fromkeys(SHOW,1),
    **{k:v for k,v in completed.WIDTHS.items() if v>1}})
exec(compile(inspect.getsource(completed.decode_signal),__file__+':strict-native-wave-decoder','exec'),TRACE_NAMESPACE)
crosscheck=source_shaped(inspect.getsource(completed.crosscheck_wave),(('set(previous.SHOW)','set(SHOW)'),))
exec(compile(crosscheck,__file__+':strict-expanded-native-wave-table-crosscheck','exec'),TRACE_NAMESPACE)
numeric=source_shaped(inspect.getsource(completed.previous.negative_trace),(
    ("    signals=wave['signal'];names=[x['name'] for x in signals]\n"
     "    assert len(names)==len(set(names)) and set(names)==set(SHOW),'Changed native WaveJSON trace signals'\n"
     "    assert all(isinstance(x['wave'],str) and len(x['wave'])==4 for x in signals)\n",
     '    initial_values=crosscheck_wave(text,wave,records)\n'
     "    assert all(records[2][name]==0 for name in ('bram_host_enable','bram_core_enable','bram_host_we','bram_core_we'))\n"),
    ('return dict(actual_frames=records,base_case_steps=2,','return dict(actual_frames=records,actual_initial_values=initial_values,native_wavejson_table_crosschecked=True,base_case_steps=2,'),))
exec(compile(numeric,__file__+':unchanged-negative-with-actual-BRAM-pins','exec'),TRACE_NAMESPACE)
negative_trace=TRACE_NAMESPACE['negative_trace']
SCRIPT_NAMESPACE=dict(completed.previous.__dict__,SHOW=SHOW)
old_clock_script=inspect.getsource(completed.previous.script)
assert old_clock_script.count('prefix_temporal_controller_model')==2
clock_script=old_clock_script.replace('prefix_temporal_controller_model','prefix_actual_bram_model')
assert clock_script.replace('prefix_actual_bram_model','prefix_temporal_controller_model')==old_clock_script
exec(compile(clock_script,__file__+':unchanged-native-induction-flags','exec'),SCRIPT_NAMESPACE)
script=SCRIPT_NAMESPACE['script']


def compare_corpora(vendor,synthesis,width,footer,count):
    results=temporal.proof.prior.results
    a=results.vectors(vendor,width,footer);b=results.vectors(synthesis,width,footer)
    assert a==b,'Expanded actual BRAM binary library mismatch'
    return dict(actual_instances=count,binary_vectors=1024,per_instance_comparisons=count*1024,output_bits=width,
        every_actual_combinational_input_combination_exhausted=True,four_state_library_equivalence=False)


def main():
    out=ROOT/f'build/openxc7/prefix-actual-bram-barrier-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        full_target_parallel_products=512,actual_controller_state_bits=50,physical_pin_read_barrier_proved_binary=False,
        physical_pin_port_ownership_proved_binary=False,initialization_host_data_independence_proved_binary=False,
        full_board_startup_independence_proved=False,temporal_port_ownership_proved=False,write_before_read_proved=False,
        four_state_library_equivalence=False,between_edge_reset_pulses_modeled=False,initialization_liveness_proved=False,
        RAM_data_value_independence_proved=False,full_board_numerical_acceptance=False,physical_fit_verified=False,
        timing_signoff=False,electrical_verified=False,drc_signoff=False,bitstream_emitted=False,hardware_programmed=False,
        hardware_input_modified=False,native_PNR_executed=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(label,argv,kind=None):
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
            if kind is not None:
                negative=label.endswith('negative')
                (completed.previous.validate if kind=='temporal' else temporal.base.prior.state.raw.validate_result)(text,code,negative)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_FORMAL_NEGATIVE' if kind is not None and label.endswith('negative') else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={};original,prior_clear,selected,brams,classification,wire,control=admit(before)
        prepared=json.loads(temporal.base.prior.state.raw.PREPARED.read_text());physical=ROOT/prepared['pack_input']
        files={Path(__file__).resolve(),CONTROL,Path(sys.executable).resolve()}
        for name in ('yosys','iverilog','vvp'):
            executable=shutil.which(name);assert executable,'UNAVAILABLE: '+name;files.add(Path(executable).resolve())
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for p in files:
            sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
        verify_bindings(before);report['source']=before
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        for name,option in (('yosys','-V'),('iverilog','-V'),('vvp','-V')):report[name+'_version']=run(name+'_version',[name,option]).splitlines()[0]
        report['stage']='fresh_full_driver_census_and_actual_BRAM_pin_cone';save();start=time.monotonic()
        rams={n:c for n,c in brams.items() if not classification[n]['readonly']}
        with wiring.HIERARCHY.open('rb') as a,mmap.mmap(a.fileno(),0,access=mmap.ACCESS_READ) as logical,physical.open('rb') as b,mmap.mmap(b.fileno(),0,access=mmap.ACCESS_READ) as actual:
            signals=aliases(logical,actual,rams);drivers,census=temporal.base.prior.state.raw.driver_index(actual,original['full_primitive_counts'])
            def driver(w):
                assert w in drivers,'Missing actual BRAM control primitive driver'
                begin,end,name,pin,bit,direction=drivers[w];assert direction=='output'
                c=json.loads(b'{'+actual[begin+1:end]+b'}')[name];return name,c,pin,bit
            cone=trace_controller(signals,driver,selected)
            fresh=wiring.translated_signals(logical,actual)[0]
            assert fresh==wire['logical_signal_physical_wires']
            assert signals['demo.memory.req_write']==[control['logical_signal_physical_wires']['req_write']]
        del drivers
        assert cone['controller_registers']==original['controller_registers']
        assert all(cone['cells'].get(n)==c for n,c in original['cells'].items())
        assert all(cone['producer_cuts'].get(w)==c for w,c in original['producer_cuts'].items())
        cone['full_primitive_counts']=census;certificate=completed.previous.qualified.clear_certificate(cone)
        assert certificate==prior_clear,'Changed actual fifty-register async clear rules'
        model_text=clock_model(cone);miter_text=miter(cone)
        counts=dict(Counter(c['type'] for c in cone['cells'].values()))
        library_data,definitions=temporal.base.selected_definitions(temporal.base.LIBRARY.read_bytes(),set(counts))
        pinned=models.selected_models(set(counts))
        for p,sha in pinned.items():assert digest(p)==sha;before[str(p.resolve())]=sha
        report.update(actual_cone_cells=len(cone['cells']),actual_producer_bits=len(cone['producer_cuts']),
            actual_cone_primitive_counts=counts,actual_full_primitive_counts=census,selected_unchanged_library_definitions=definitions,
            actual_pin_bindings={name:signals[name] for name in PIN_SIGNALS},actual_audit_seconds=round(time.monotonic()-start,3),
            added_actual_cells=sorted(set(cone['cells'])-set(original['cells'])),added_producer_bits=sorted(set(cone['producer_cuts'])-set(original['producer_cuts'])))
        (out/'actual-BRAM-pin-controller-cone.json').write_text(json.dumps(cone,indent=2,sort_keys=True)+'\n')
        model=out/'actual-BRAM-pin-clocked-model.v';model.write_text(model_text)
        paired=out/'actual-BRAM-pin-initialization-miter.v';paired.write_text(miter_text)
        library=out/'unchanged_selected_controller_cells.v';library.write_bytes(library_data)
        text,width=temporal.proof.prior.declared.qualify_bench(cone['cells']);bench=out/'binary_library_control.sv';bench.write_text(text)
        footer=temporal.proof.prior.results.expected_finish(bench,text);frozen=[]
        for p in pinned:
            target=out/'models'/p.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
            if target.suffix=='.v':frozen.append(target)
        execution={str(p):digest(p) for p in (model,paired,library,bench,*frozen)}
        report.update(execution_inputs=execution,stage='fresh_full_expanded_binary_library_qualification');save();outputs={}
        for view,sources in (('vendor',frozen),('synthesis',[library,*[p for p in frozen if p.name=='glbl.v']])):
            binary=out/(view+'.vvp');run(view+'_compile',['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl','-o',binary,*sources,bench])
            execution[str(binary)]=digest(binary);outputs[view]=run(view+'_test',['vvp',binary])
        report['binary_library_qualification']=compare_corpora(outputs['vendor'],outputs['synthesis'],width,footer,len(cone['cells']))
        wrong=run('synthesis_wrong_golden_test',['vvp',out/'synthesis.vvp','+NEGATIVE=1'])
        a=temporal.proof.prior.results.vectors(outputs['vendor'],width,footer);b=temporal.proof.prior.results.vectors(wrong,width,footer)
        assert a[0]^b[0]==1 and a[1:]==b[1:]
        try:compare_corpora(outputs['vendor'],wrong,width,footer,len(cone['cells']))
        except AssertionError as e:assert str(e)=='Expanded actual BRAM binary library mismatch'
        else:raise AssertionError('Actual expanded corpus wrong golden accepted')
        report['binary_library_real_negative']='REJECTED_EXECUTED_FIRST_VECTOR_ONE_BIT_MUTATION'
        verify_bindings(before);verify_bindings(execution)
        for kind in ('initialization','temporal'):
            for label,negative in ((kind+'_negative',True),(kind+'_positive',False)):
                report['stage']='native_'+label;save();target=out/(label+'.ys');witness=out/(label+'-counterexample.json')
                if kind=='temporal':body=script(library,model,negative,witness)
                else:body='read_verilog '+str(library)+'\nread_verilog '+str(paired)+'\nchparam -set NEGATIVE '+str(int(negative))+' prefix_actual_bram_miter\nhierarchy -check -top prefix_actual_bram_miter\nflatten\nproc\nopt -full\nwreduce\nopt -full\ncheck -assert\nsat -verify -prove ok 1 -show state -show compared_0 -show compared_1 -show init_phase -show ok -timeout 120 -dump_json '+str(witness)+'\n'
                target.write_text(body);execution[str(target)]=digest(target)
                log=run(label,['yosys','-Q','-T','-s',target],'temporal' if kind=='temporal' else 'combinational')
                if negative:
                    wave=json.loads(witness.read_text());execution[str(witness)]=digest(witness)
                    if kind=='temporal':report['real_temporal_negative']=negative_trace(log,wave)
                    else:
                        values={s['name']:s for s in wave['signal']};assert values['init_phase']['wave']=='14' and values['ok']['wave']=='04'
                        assert values['compared_0']['data']==values['compared_1']['data']
                        assert re.fullmatch('[01]+',values['compared_0']['data'][0]) and int(values['state']['data'][0],2)<=2
                        report['real_initialization_negative']='ACTUAL_COMPARED_VECTORS_EQUAL_ONLY_PROPERTY_GOLDEN_MUTATED'
                elif kind=='temporal':report['native_induction_length']=completed.previous.validate(log,0,False);assert not witness.exists()
                else:assert not witness.exists()
                verify_bindings(before);verify_bindings(execution)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',physical_pin_read_barrier_proved_binary=True,
            physical_pin_port_ownership_proved_binary=True,initialization_host_data_independence_proved_binary=True,
            ghost_writes_count_actual_A_enable_and_WE=True,actual_host_word_address_is_index=True,
            consumed_working_RAM_bits_covered_by_prefix=65536,actual_working_RAMs=2)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
