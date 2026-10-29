#!/usr/bin/env python3
"""Prove sampled-reset binary ownership and prefix write-before-core-request.

Admit the exact 50-bit DMA-inclusive clocked model only after independently
revalidating its actual-cell, FDCE and async-clear qualification. Actual state
starts at arbitrary binary values; only the ghost reset observer is initially
zero. All 969 unowned producer bits are free each cycle, as is the probe address
sampled on reset. Prove the full strengthened safety conjunction by native
Yosys induction, with base cases and no skipped steps or value assumptions.
First execute a real wrong-golden base-case negative and require its finite
reset/guard/safe/ok trace. This is an abstract binary, positive-edge proof after
an observed sampled reset, not four-state startup, between-edge reset pulses,
initialization liveness, RAM data retention, full numerical or FPGA signoff.
No actual RTL, frozen helper/model/input, live job or SHA256SUMS is changed.
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
import qualify_prefix_temporal_controller_primitives as qualified
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest,timestamp
from evidence import source_revision

QUALIFIED=ROOT/'build/openxc7/prefix-temporal-controller-primitives-1791449421248666952/report.json'
CONTROL=ROOT/'tests/cmac/test_prefix_binary_temporal_ownership_control.py'
SUCCESS='Induction step proven: SUCCESS!'
FAILURE='SAT temporal induction proof finished - model found for base case: FAIL!'
PASS='PROVED_ACTUAL_50_BIT_CONTROLLER_BINARY_SAMPLED_RESET_TEMPORAL_OWNERSHIP_AND_PREFIX_WRITE_BEFORE_CORE_REQUEST_NOT_STARTUP_OR_FPGA_SIGNOFF'
SHOW=('seen_reset','reset_n','safe','writes_seen','index','probe','probe_written',
      'demo_state','dma_state','host_fire','host_write','core_fire','request_valid','ok')


def admit(before):
    cone,library=qualified.admit(before)
    r=json.loads(QUALIFIED.read_text())
    assert r['status']==qualified.PASS and r['stage']=='complete' and r['finished_utc']
    assert r['full_target_parallel_products']==512 and r['actual_controller_configurations']==50
    assert r['controller_binary_fold_qualified'] and r['controller_cone_binary_library_qualified']
    assert r['async_clear_fixed_point_qualified'] and r['post_edge_clear_application_is_fixed_point']
    assert r['temporal_port_ownership_proved'] is False and r['write_before_read_proved'] is False
    bind_report(QUALIFIED,r,before);verify_bindings(before)
    root=QUALIFIED.parent
    regs=json.loads((root/'actual-temporal-controller-FDCE-records.json').read_text())
    assert regs==cone['controller_registers']
    assert (root/'actual-temporal-controller-FDCEs.v').read_text()==qualified.wrapper(regs)
    bench=root/'tb_prefix_temporal_fdce_fold.sv';assert bench.read_text()==qualified.bench_text()
    cmds={c['label']:c for c in r['commands']}
    for label,negative in (('fold_negative',True),('fold_positive',False)):
        c=cmds[label];qualified.validate_fold(Path(c['log']).read_text(),c['returncode'],negative,bench)
    certificate=qualified.clear_certificate(cone)
    assert certificate==json.loads((root/'actual-async-clear-fixed-point.json').read_text())
    assert library==(root/'unchanged_selected_controller_cells.v').read_bytes()
    text,width=qualified.controller.proof.prior.declared.qualify_bench(cone['cells']);assert width==1535
    bench=root/'binary_library_control.sv';assert bench.read_text()==text
    footer=qualified.controller.proof.prior.results.expected_finish(bench,text)
    vendor=Path(cmds['vendor_test']['log']).read_text()
    assert qualified.compare_corpora(vendor,Path(cmds['synthesis_test']['log']).read_text(),width,footer)==r['binary_library_qualification']
    qualified.validate_wrong_corpus(vendor,Path(cmds['synthesis_wrong_golden_test']['log']).read_text(),width,footer)
    model=qualified.controller.clock_model(cone)
    assert model==(qualified.PREPARED.parent/'actual-binary-temporal-controller.v').read_text()
    verify_bindings(before)
    return cone,model,library,certificate


def script(library,model,negative,counterexample):
    text='read_verilog '+str(library)+'\nread_verilog '+str(model)+'\n'
    text+='chparam -set NEGATIVE '+str(int(negative))+' prefix_temporal_controller_model\n'
    text+='hierarchy -check -top prefix_temporal_controller_model\nflatten\nproc\nopt -full\nwreduce\nopt -full\ndffunmap\nopt_clean\ncheck -assert\n'
    text+='sat -seq 1 -tempinduct-def -maxsteps 4 -set-def-inputs -set-init-def -verify -prove ok 1 -timeout 120 '
    text+=' '.join('-show '+name for name in SHOW)+' -dump_json '+str(counterexample)+'\n'
    assert not re.search(r'-(?:set-at|set-init-zero|set-assumes|prove-x|prove-skip|tempinduct-skip|tempinduct-baseonly|tempinduct-inductonly|ignore-unknown-cells|verify-no-timeout)\b',text)
    assert text.count('-prove ok 1')==1
    return text


def validate(text,code,negative):
    assert not re.search(r'(?im)warning:|sorry:|timed out|timeout reached|unknown cell|^FATAL|^FAILED',text)
    errors=re.findall(r'(?m)^ERROR: (.*)$',text)
    if negative:
        assert code==1 and text.count(FAILURE)==1 and SUCCESS not in text
        assert errors==['Called with -verify and proof did fail!']
        assert 'Reached maximum number of time steps -> proof failed.' not in text
    else:
        assert code==0 and text.count(SUCCESS)==1 and FAILURE not in text and not errors
        lengths=[int(x) for x in re.findall(r'(?m)^Base case for induction length (\d+) proven\.$',text)]
        assert lengths and lengths==list(range(1,lengths[-1]+1)) and lengths[-1]<=4
        assert 'Reached maximum number of time steps' not in text
        return lengths[-1]


def negative_trace(text,wave):
    """Require the real base-case witness, never a frontend error or timeout."""
    records={}
    for line in text.splitlines():
        match=re.fullmatch(r'\s*(\d+)\s+\\([A-Za-z_][A-Za-z0-9_]*)\s+(-?\d+|--)\s+([0-9a-fx]+)\s+([01x]+)\s*',line)
        if not match:continue
        t=int(match[1]);name=match[2]
        if name not in SHOW:continue
        assert name not in records.setdefault(t,{}),'Duplicate actual temporal trace row'
        assert re.fullmatch('[01]+',match[5]),'Non-finite actual binary negative trace'
        value=int(match[5],2)
        assert match[3]!='--' and int(match[3])==value and 'x' not in match[4] and int(match[4],16)==value
        records[t][name]=value
    assert sorted(records)==[1,2] and all(set(v)==set(SHOW) for v in records.values()),'Missing actual two-step temporal negative trace'
    first,last=records[1],records[2]
    assert first['seen_reset']==0 and first['reset_n']==0 and first['ok']==1
    assert last['seen_reset']==1 and last['reset_n']==1 and last['safe']==1 and last['ok']==0
    assert last['demo_state']==last['dma_state']==last['writes_seen']==last['probe_written']==0
    assert last['host_fire']==last['core_fire']==last['request_valid']==0
    signals=wave['signal'];names=[x['name'] for x in signals]
    assert len(names)==len(set(names)) and set(names)==set(SHOW),'Changed native WaveJSON trace signals'
    assert all(isinstance(x['wave'],str) and len(x['wave'])==4 for x in signals)
    return dict(actual_frames=records,base_case_steps=2,reset_observed_before_wrong_golden_failure=True,
        actual_safety_true_at_failure=True,only_NEGATIVE_property_golden_inverted=True)


def main():
    out=ROOT/f'build/openxc7/prefix-binary-temporal-ownership-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    report=dict(status='RUNNING',stage='admission',scope=__doc__,started_utc=timestamp(),supervisor_pid=os.getpid(),
        source={},commands=[],python_version=sys.version,seed=None,production_source_before=source_revision(),
        full_target_parallel_products=512,actual_controller_state_bits=50,other_producers_free_each_cycle=969,
        arbitrary_probe_bits=12,input_value_assumptions=[],real_state_initially_unconstrained_binary=True,
        only_ghost_seen_reset_initialized_zero=True,checking_only_after_observed_sampled_reset=True,
        base_cases_skipped=False,induction_steps_skipped=False,binary_model_temporal_port_ownership_proved=False,
        binary_prefix_write_before_core_request_proved=False,arbitrary_probe_prefix_coverage_proved=False,
        temporal_port_ownership_proved=False,write_before_read_proved=False,full_board_startup_independence_proved=False,
        between_edge_reset_pulses_modeled=False,four_state_library_equivalence=False,initialization_liveness_proved=False,
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
            if negative is not None:validate(text,code,negative)
            else:assert code==0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL',text),text[-4000:]
            step['status']='PASS_EXPECTED_REAL_TEMPORAL_BASE_CASE_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        before={};cone,model_text,library_data,certificate=admit(before)
        files={Path(__file__).resolve(),CONTROL,Path(sys.executable).resolve(),Path(shutil.which('yosys')).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for path in files:
            sha=digest(path);assert str(path) not in before or before[str(path)]==sha;before[str(path)]=sha
        verify_bindings(before);report['source']=before
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check']);report['yosys_version']=run('yosys_version',['yosys','-V']).strip()
        model=out/'actual-binary-temporal-controller.v';model.write_text(model_text)
        library=out/'unchanged_selected_controller_cells.v';library.write_bytes(library_data)
        (out/'actual-async-clear-fixed-point.json').write_text(json.dumps(certificate,indent=2,sort_keys=True)+'\n')
        execution={str(p):digest(p) for p in (model,library)};report['execution_inputs']=execution
        for label,negative in (('negative',True),('positive',False)):
            report['stage']='native_binary_temporal_induction_'+label;save()
            target=out/(label+'.ys');witness=out/(label+'-counterexample.json')
            target.write_text(script(library,model,negative,witness));execution[str(target)]=digest(target)
            text=run(label,['yosys','-Q','-T','-s',target],negative)
            if negative:
                report['real_negative']=negative_trace(text,json.loads(witness.read_text()))
                execution[str(witness)]=digest(witness)
            else:
                report['native_induction_length']=validate(text,0,False)
                assert not witness.exists(),'Positive induction unexpectedly emitted counterexample'
            verify_bindings(before);verify_bindings(execution)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        report.update(status=PASS,stage='complete',binary_model_temporal_port_ownership_proved=True,
            binary_prefix_write_before_core_request_proved=True,arbitrary_probe_prefix_coverage_proved=True,
            full_strengthened_safety_conjunction_proved=True,actual_cone_cells=1325,actual_cone_primitive_counts=qualified.COUNTS,
            actual_producer_bits=1019,actual_full_primitive_counts=cone['full_primitive_counts'])
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp();report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
