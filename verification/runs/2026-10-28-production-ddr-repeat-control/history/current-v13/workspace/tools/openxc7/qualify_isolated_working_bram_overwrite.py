#!/usr/bin/env python3
"""Full original primitive corpus, with each independent startup view isolated.

The six-instance compilation corrupts one internal INIT parameter table. The
actual isolated two-RAM contexts preserve all parameters. Execute all three
views separately, preserving each view's original cold golden and all 4096
addresses, writes, known reads, READ_FIRST, retention and reinitialization.
No model, original failed bench/gate, RTL, hardware input or live job changes.
Require exact parameter forwarding, genuine finite wrong-golden negatives,
strict native positive records and unchanged 180-second command limits. This
is only primitive unit qualification, not board startup/ownership/signoff.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1]/'cmac')]
import diagnose_prefix_working_bram_cold as base
import test_prefix_working_bram_overwrite as original
import resume_bram_parameter_forwarding_diagnostic as parameter
from audit_empty_output_pairs import source_shaped

CONTROL=base.ROOT/'tests/cmac/test_isolated_working_bram_overwrite_control.py'
ISOLATED=base.ROOT/'build/openxc7/isolated-working-bram-views-resume-1791442263393374080/report.json'
PASS='PASS_ACTUAL_TWO_WORKING_BRAM_CONFIGURATIONS_THREE_ISOLATED_STARTUP_VIEWS_COMPLETE_OVERWRITE_CORPUS_ONLY_NOT_BOARD_STARTUP_OR_SIGNOFF'


def marker(view):
    assert view in ('mapped','zero','one')
    return 'PASS actual working BRAM overwrite configurations=2 view='+view+' default_gsr=100ns cold_words=4096 writes=12288 reads=20480 read_first=12288 retention=34; not board startup or physical acceptance'


def bench(view,rom):
    assert view in ('mapped','zero','one')
    text=original.render_bench(rom)
    instances='''    actual_working_bram_mapped mapped(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_m),.core_rdata(c_m));
    actual_working_bram_zero zero_encoded(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_z),.core_rdata(c_z));
    actual_working_bram_one counterfactual_one(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(h_o),.core_rdata(c_o));
'''
    selected='    actual_working_bram_'+view+''' selected(.clk,.host_enable,.core_enable,.host_we,.core_we,
        .host_index,.core_index,.host_wdata,.core_wdata,.host_rdata(host_rdata),.core_rdata(core_rdata));
'''
    known='''    task automatic check_known(input string phase,input integer index,
                               input [15:0] a,b,c,expected);
        if(a!==expected||b!==expected||c!==expected)
            $fatal(1,"working BRAM mismatch phase=%s index=%0d got=%04h/%04h/%04h expected=%04h",phase,index,a,b,c,expected);
    endtask
'''
    single_known='''    task automatic check_known(input string phase,input integer index,
                               input [15:0] a,expected);
        if(a!==expected)
            $fatal(1,"working BRAM mismatch phase=%s index=%0d got=%04h expected=%04h",phase,index,a,expected);
    endtask
'''
    cold='''    task automatic check_cold(input integer index,input [15:0] a,b,c);
        if(a!==16'hxxxx||b!==16'h0000||c!==16'hffff)
            $fatal(1,"working BRAM cold-state mismatch index=%0d got=%04h/%04h/%04h",index,a,b,c);
    endtask
'''
    expected={'mapped':'xxxx','zero':'0000','one':'ffff'}[view]
    single_cold='''    task automatic check_cold(input integer index,input [15:0] a);
        if(a!==16'h'''+expected+''')
            $fatal(1,"working BRAM cold-state mismatch index=%0d got=%04h",index,a);
    endtask
'''
    text=source_shaped(text,((instances,selected),(known,single_known),(cold,single_cold),
        ('wire [15:0] h_m,h_z,h_o,c_m,c_z,c_o;','wire [15:0] host_rdata,core_rdata;'),
        ('configurations=2 variants=3','configurations=2 view='+view)))
    assert text.count('h_m,h_z,h_o')==6 and text.count('c_m,c_z,c_o')==4
    text=text.replace('h_m,h_z,h_o','host_rdata').replace('c_m,c_z,c_o','core_rdata')
    assert not re.search(r'\b[hc]_[mzo]\b',text)
    return text


def validate_result(text,code,negative,source,first_word,view):
    assert not re.search(r'(?im)\bwarning:|\berror:|\bsorry:|timeout',text),'Unaccepted primitive qualification diagnostic'
    if negative:
        expected=f'working BRAM mismatch phase=core_after_host_init index=0 got={first_word:04x} expected={first_word^1:04x}'
        fatals=[line for line in text.splitlines() if line.startswith('FATAL:')]
        assert code==1 and expected in text and marker(view) not in text
        assert len(fatals)==1 and expected in fatals[0]
    else:
        finish=[i+1 for i,line in enumerate(source.read_text().splitlines()) if line.strip()=='$finish;']
        assert len(finish)==1
        assert code==0 and text.splitlines()==[marker(view),f'{source}:{finish[0]}: $finish called at 655812000 (1ps)'],text[-4000:]


def bind_isolated(before):
    isolated=json.loads(ISOLATED.read_text())
    assert isolated['status']=='OBSERVED_ONLY_NOT_OVERWRITE_STARTUP_NUMERICAL_OR_PHYSICAL_ACCEPTANCE'
    assert isolated['stage']=='complete' and isolated['finished_utc']
    assert isolated['observation_only'] and isolated['working_BRAM_model_overwrite_fixture_acceptance'] is False
    records=isolated['isolated_view_observations'];assert set(records)=={'mapped','zero','one'}
    for view,record in records.items():
        assert record['parameters_per_instance']==148 and record['only_two_selected_actual_RAM_instances_instantiated']
        assert len(record['parameter_forwarding_differences'])==2 and all(not changes for changes in record['parameter_forwarding_differences'].values())
        expected={'mapped':'xxxx','zero':'0000','one':'ffff'}[view]
        assert f'TRACE phase=cold_read_0 t=132000 GSR=0 host={expected}/zzzz/zzzz core={expected}/zzzz/zzzz' in record['native_observations']
    base.bind_report(ISOLATED,isolated,before)


OLD_BIND="        before={};bind_report(FAILED,failed,before)"
NEW_BIND=OLD_BIND+"""
        bind_isolated(before)
        for path in (CONTROL,original.BENCH,original.ROM):before[str(path)]=digest(path)
        shutil.copyfile(CONTROL,out/'executed_control_source.py')
        shutil.copyfile(original.BENCH,out/'preserved_original_failed_bench.sv')
        (out/'executed_main.py').write_text(MAIN_SOURCE)
"""
OLD_GENERATED="        report['stage']='generated_check';save();run('generated_check',['make','generated-check'])"
NEW_GENERATED="""        report['stage']='software_controls';save()
        run('software_controls',[sys.executable,'-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
"""+OLD_GENERATED
START="        report['stage']='compile';save();binary=out/'diagnostic.vvp'"
END="        report['observed_trace']=text.splitlines()"
original_main=inspect.getsource(base.main)
OLD_EXECUTION=original_main[original_main.index(START):original_main.index(END)+len(END)]
NEW_EXECUTION="""        rom=out/'actual-source-ROM.hex';shutil.copyfile(original.ROM,rom)
        execution[str(rom)]=digest(rom);first_word=int(rom.read_text().splitlines()[0],16)&65535
        report['isolated_view_qualifications']={}
        for view in ('mapped','zero','one'):
            directory=out/view;directory.mkdir()
            source=directory/'tb_prefix_working_bram_overwrite.sv';source.write_text(bench(view,rom))
            binary=directory/'overwrite.vvp';report['stage']=view+'_compile';save()
            run(view+'_compile',['iverilog','-g2012','-Ttyp','-s','tb_prefix_working_bram_overwrite',
                '-s','glbl','-o',binary,*copies[:3],source])
            execution.update({str(p):digest(p) for p in (source,binary)})
            report['execution_inputs']=execution
            tables=parameter.parameter_tables(binary);forwarded={}
            for index in (0,1):
                outer='tb_prefix_working_bram_overwrite.selected.actual_'+str(index)
                internal=outer+'.gen_tdp.INT_RAMB_TDP';a=tables[outer];b=tables[internal]
                assert len(a)==148 and set(a)==set(b)
                assert all(a[key].zfill(len(b[key]))[-len(b[key]):]==b[key] for key in a),'Actual isolated INIT forwarding mismatch'
                forwarded[outer]=dict(parameters=148,all_unchanged=True)
            for label,options,negative in (('negative',['+NEGATIVE=1'],True),('positive',[],False)):
                report['stage']=view+'_'+label;save()
                run(view+'_'+label,['vvp',binary,*options],negative)
                verify_bindings(execution);verify_bindings(before)
            report['isolated_view_qualifications'][view]=dict(actual_RAM_instances=2,
                parameter_forwarding=forwarded,cold_words=4096,writes=12288,reads=20480,
                read_first=12288,retention=34,original_per_view_cold_expectation_preserved=True,
                finite_real_wrong_golden_negative_passed=True,complete_positive_passed=True)
            save()
        assert set(report['isolated_view_qualifications'])=={'mapped','zero','one'}
"""
OLD_NATIVE="            assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout',text),text[-4000:]"
NEW_NATIVE="""            if negative is not None:validate_result(text,code,negative,source,first_word,view)
            else:
    """+OLD_NATIVE
OLD_STATUS="        report.update(status='OBSERVED_ONLY_NOT_OVERWRITE_STARTUP_NUMERICAL_OR_PHYSICAL_ACCEPTANCE',stage='complete')"
NEW_STATUS="""        report.update(status=PASS,stage='complete',observation_only=False,
            working_BRAM_model_overwrite_fixture_acceptance=True,full_original_primitive_corpus_per_view=True,
            startup_views_executed_in_independent_two_RAM_contexts=True,unknown_consumed_source_memory_bits=65536)
"""
MAIN_SOURCE=source_shaped(original_main,(
    ('prefix-working-bram-cold-diagnostic-','isolated-working-bram-overwrite-'),
    ('def run(label,argv):','def run(label,argv,negative=None):'),
    (OLD_NATIVE,NEW_NATIVE),(OLD_BIND,NEW_BIND),(OLD_GENERATED,NEW_GENERATED),
    (OLD_EXECUTION,NEW_EXECUTION),(OLD_STATUS,NEW_STATUS)))
NAMESPACE=dict(vars(base),__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,original=original,
    parameter=parameter,bench=bench,bind_isolated=bind_isolated,validate_result=validate_result,
    MAIN_SOURCE=MAIN_SOURCE,PASS=PASS)
exec(compile(MAIN_SOURCE,__file__+':isolated-full-native-corpus','exec'),NAMESPACE)


if __name__=='__main__':NAMESPACE['main']()
