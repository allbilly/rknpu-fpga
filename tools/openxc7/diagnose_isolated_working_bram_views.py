#!/usr/bin/env python3
"""Isolate actual primitive startup views and typed constant forwarding.

Remove only the two unselected, independent test-only RAM-view instances from
the observation bench. Retain the selected two-RAM wrapper byte-for-byte,
unchanged vendor models, original data/control transactions, default GSR and
hierarchical read-only probes. Also change just the outer constant parameter
to its actual vendor-model packed unsigned type in the independent example.
No old model/bench/gate/binary/RTL/live job is changed. Observation, not proof
of overwrite, startup, temporal, numerical or physical acceptance. No manifests.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
import diagnose_prefix_working_bram_cold as base
import resume_bram_parameter_forwarding_diagnostic as parameter
from audit_empty_output_pairs import source_shaped

CONTROL=base.ROOT/'tests/cmac/test_isolated_working_bram_views_control.py'
UNTYPED=base.ROOT/'tests/cmac/tb_bram_parameter_forwarding_diagnostic.sv'
OBSERVED=base.ROOT/'build/openxc7/bram-parameter-forwarding-resume-1791441885268583217/report.json'


def isolated_bench(view):
    assert view in ('mapped','zero','one')
    original=base.BENCH.read_text()
    remove=[]
    for kind,label,host,core in (('zero','zero_encoded','h_z','c_z'),('one','counterfactual_one','h_o','c_o')):
        fragment=f'''    actual_working_bram_{kind} {label}(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata({host}),.core_rdata({core}));
'''
        assert original.count(fragment)==1;remove.append((fragment,''))
    if view!='mapped':remove.append(('actual_working_bram_mapped mapped(','actual_working_bram_'+view+' mapped('))
    return source_shaped(original,tuple(remove))


TYPED_OLD='module diagnostic_forwarding #(parameter RAM_MODE="TDP",parameter INIT_00=256\'h0)'
TYPED_NEW='module diagnostic_forwarding #(parameter RAM_MODE="TDP",parameter [255:0] INIT_00=256\'h0)'


def typed_bench():
    return source_shaped(UNTYPED.read_text(),((TYPED_OLD,TYPED_NEW),))


def bind_observations(before):
    observed=json.loads(OBSERVED.read_text())
    assert observed['status']=='OBSERVED_ONLY_NOT_OVERWRITE_STARTUP_NUMERICAL_OR_PHYSICAL_ACCEPTANCE'
    assert observed['stage']=='complete' and observed['finished_utc'] and observed['observation_only']
    assert observed['working_BRAM_model_overwrite_fixture_acceptance'] is False
    records=observed['actual_failed_binary_parameter_forwarding']
    assert len(records)==6 and len(records['tb_prefix_working_bram_overwrite.mapped.actual_0']['differences'])==144
    base.bind_report(OBSERVED,observed,before)


OLD_BIND="        before={};bind_report(FAILED,failed,before)"
NEW_BIND=OLD_BIND+"""
        bind_observations(before)
        for path in (CONTROL,UNTYPED):before[str(path)]=digest(path)
        shutil.copyfile(CONTROL,out/'executed_control_source.py')
        (out/'executed_main.py').write_text(MAIN_SOURCE)
"""
OLD_GENERATED="        report['stage']='generated_check';save();run('generated_check',['make','generated-check'])"
NEW_GENERATED="""        report['stage']='software_controls';save()
        run('software_controls',[sys.executable,'-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
"""+OLD_GENERATED
START="        report['stage']='compile';save();binary=out/'diagnostic.vvp'"
END="        report['observed_trace']=text.splitlines()"
original_main=inspect.getsource(base.main)
start=original_main.index(START);end=original_main.index(END)+len(END)
OLD_EXECUTION=original_main[start:end]
NEW_EXECUTION="""        report['isolated_view_observations']={}
        for view in ('mapped','zero','one'):
            directory=out/view;directory.mkdir()
            bench=directory/'isolated.sv';bench.write_text(isolated_bench(view))
            binary=directory/'diagnostic.vvp'
            report['stage']=view+'_compile';save()
            run(view+'_compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_working_bram_cold_diagnostic',
                '-s','glbl','-o',binary,*copies[:3],bench])
            execution.update({str(p):digest(p) for p in (bench,binary)})
            tables=parameter.parameter_tables(binary);differences={}
            for index in (0,1):
                outer='tb_prefix_working_bram_cold_diagnostic.mapped.actual_'+str(index)
                inner=outer+'.gen_tdp.INT_RAMB_TDP';a=tables[outer];b=tables[inner]
                assert len(a)==148 and set(a)==set(b)
                differences[outer]={key:dict(outer=a[key],internal=b[key]) for key in a
                    if a[key].zfill(len(b[key]))[-len(b[key]):]!=b[key]}
            report['stage']=view+'_observe';save()
            text=run(view+'_observe',['vvp',binary])
            assert 'OBSERVATION_ONLY unchanged actual working BRAM cold trace; no overwrite, startup or hardware acceptance' in text
            report['isolated_view_observations'][view]=dict(parameters_per_instance=148,
                parameter_forwarding_differences=differences,native_observations=text.splitlines(),
                only_two_selected_actual_RAM_instances_instantiated=True)
            verify_bindings(execution);save()
        typed=out/'typed_parameter_forwarding.sv';typed.write_text(typed_bench())
        typed_binary=out/'typed_parameter_forwarding.vvp';report['stage']='typed_compile';save()
        run('typed_compile',['iverilog','-g2012','-s','tb_bram_parameter_forwarding_diagnostic',
            '-o',typed_binary,typed])
        execution.update({str(p):digest(p) for p in (typed,typed_binary)})
        report['stage']='typed_observe';save();text=run('typed_observe',['vvp',typed_binary])
        assert 'PASS independent constant parameter forwarding only; not vendor-model or board acceptance' in text
        report['typed_constant_forwarding_log']=text.splitlines()
        report['execution_inputs']=execution
"""
MAIN_SOURCE=source_shaped(original_main,(
    ('prefix-working-bram-cold-diagnostic-','isolated-working-bram-views-diagnostic-'),
    (OLD_BIND,NEW_BIND),(OLD_GENERATED,NEW_GENERATED),(OLD_EXECUTION,NEW_EXECUTION)))
NAMESPACE=dict(vars(base),__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,UNTYPED=UNTYPED,
    parameter=parameter,bind_observations=bind_observations,isolated_bench=isolated_bench,
    typed_bench=typed_bench,MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE,__file__+':isolated-native-observation-main','exec'),NAMESPACE)


if __name__=='__main__':NAMESPACE['main']()
