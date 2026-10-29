#!/usr/bin/env python3
"""Fresh read-only qualification of unchanged native HeAP evidence.

Preserve the typed-inspection FAIL and its old parser. Independently revalidate
all original native commands/outputs, then compare the same DSP/BRAM features
with a source/chipdb/segbits/consumer-bound HCLK multiplicity model. No native
log is copied forward or described as a new native execution. No RTL, command,
input, FASM, executable, original live job or warning/physical gate is changed.
This qualifies small native evidence, not full fit/timing/numerical/FPGA success.
No standalone checksum manifest is written.
"""
import inspect
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import qualify_native_heap_typed_inspection as native
import clock_bound_native_features as clock
from pack_prefix_board import ROOT,digest,timestamp
from place_prefix_board import bind_report,verify_bindings
from evidence import source_revision

previous=native.previous
first=previous.first
FAILED=ROOT/'build/openxc7/native-heap-typed-inspection-1791459029556778888/report.json'
CONTROL=ROOT/'tests/cmac/test_native_heap_clock_qualification_control.py'
CLOCK_CONTROL=ROOT/'tests/cmac/test_clock_bound_native_features.py'
QUALIFIED='QUALIFIED_SOURCE_BOUND_SAVED_NATIVE_HEAP_AND_CLOCK_FANOUT_DSP_BRAM_FEATURES_NOT_FULL_FIT_OR_SIGNOFF'
FLAGS=first.FLAGS
COMMANDS=['clock_contract_controls','qualification_controls','generated_check']
check_heap_log=native.check_heap_log
ERROR="AssertionError('Unsupported repeated native FASM feature: HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0')"


def check_saved_metadata(r):
    assert r['status']=='FAIL' and r['stage']=='small_heap_native_PNR_FASM' and r['finished_utc']
    assert r['error']==ERROR and r['part']=='xc7k480tffg1156-2' and r['full_parallel_products']==512 and r['placer']=='heap'
    assert r['native_source_or_executable_changed'] is False and all(r[k] is False for k in FLAGS)
    assert r['native_positive_placements']==3 and r['lut_output_comparisons']==1024
    assert r['illegal_pair_rejected_before_postPlace'] and r['small_native_PNR_FASM_executed']
    assert [c['label'] for c in r['commands']]==native.COMMANDS
    for c in r['commands']:
        expected=125 if c['label']=='invalid-forced' else 0
        assert c['returncode']==c['expected_returncode']==expected
        assert c['status']==('PASS_EXPECTED_NATIVE_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')


def recheck_saved(q,r):
    assert r['executable']==q['executable'] and r['native_version']==q['native_version']
    commands={c['label']:c for c in r['commands']}
    for c in r['commands']:
        label=c['label'];text=Path(c['log']).read_text()
        if label in first.LABELS:
            assert c['argv']==first.expected_argv(q,label,FAILED.parent)
            check_heap_log(c['returncode'],text,label=='invalid-forced')
            output=FAILED.parent/(label+'-placed.json')
            if label=='invalid-forced':assert not output.exists()
            else:
                fixture=c['argv'][c['argv'].index('--json')+1]
                assert c['placement_checks']==first.parent.first.validate_placed(output,47 if label=='counter' else 49,None if label=='counter' else fixture)
        elif label=='small_native_PNR_FASM':
            assert c['argv']==first.expected_argv(q,label,FAILED.parent)
            check_heap_log(c['returncode'],text);first.check_route_log(text)
        elif label=='compiled_heap_symbol_census':native.check_symbol_census(text)
        else:assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',text)
    address,size=previous.getter_symbol(Path(commands['compiled_heap_symbol_census']['log']).read_text())
    assert r['compiled_heap_beta_store_certificate']==previous.validate_getter(
        Path(commands['compiled_heap_getter']['log']).read_text(),address,size,previous.HEAD.read_text())
    assert commands['compiled_heap_symbol_census']['argv']==['nm','-S','-C',q['executable']['path']]
    assert commands['compiled_heap_getter']['argv']==['objdump','-d','-C','--start-address='+hex(address),'--stop-address='+hex(address+size),q['executable']['path']]


def admit():
    q,before=native.admit();r=json.loads(FAILED.read_text());check_saved_metadata(r)
    assert r['production_source_before']==source_revision()
    bind_report(FAILED,r,before)
    for p in clock.SOURCES:
        sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
    verify_bindings(before);recheck_saved(q,r);return r,before


def compare_saved_features():
    out=FAILED.parent;module=next(iter(json.loads((out/'routed.json').read_text())['modules'].values()))
    assert module['settings']['placer']=='heap' and float(module['settings']['target_freq'])==50_000_000
    for key in ('pack','place','route'):assert int(module['settings'][key],2)==1
    contracts=clock.clock_contracts(module);text=(out/'control.fasm').read_text()
    features,io,clocks=clock.parse_clock_bound_features(text,contracts)
    try:first.parent.first.parse_native_features(text)
    except AssertionError as error:assert str(error)==ERROR[len("AssertionError('"):-2]
    else:raise AssertionError('Frozen original parser no longer rejects its original input')
    # Independent namespace, identical full DSP/BRAM comparator body and guards.
    namespace=dict(first.parent.first.__dict__,parse_native_features=lambda t:clock.parse_clock_bound_features(t,contracts)[:2])
    exec(compile(inspect.getsource(first.parent.first.compare_features),__file__+':unchanged-DSP-BRAM-comparison-body','exec'),namespace)
    original=json.loads(first.parent.first.NATIVE.read_text());compared=namespace['compare_features'](out,original)
    assert compared['native_FASM_features']==len(features) and compared['native_FASM_repeated_idempotent_STEPDOWN_lines']==io
    return dict(**compared,clock_source_contract=clock.source_contract(),clock_fanout_contracts=contracts,
                native_FASM_repeated_clock_enable_lines=clocks,consumer_merge_contract=clock.consumer_merge_check())


def verify_metadata(r):
    assert r['status']==QUALIFIED and r['stage']=='complete' and r['finished_utc']
    assert r['part']=='xc7k480tffg1156-2' and r['full_parallel_products']==512 and r['placer']=='heap'
    assert r['native_evidence_parent']==str(FAILED) and r['original_failure_relabelled'] is False
    assert r['reused_completed_native_commands_without_execution'] is True and r['new_native_PNR_executed'] is False
    assert r['native_source_or_executable_changed'] is False and all(r[k] is False for k in FLAGS)
    assert r['native_positive_placements']==3 and r['lut_output_comparisons']==1024 and r['illegal_pair_rejected_before_postPlace']
    assert r['native_control_cell_counts']['DSP48E1_DSP48E1']==4 and r['native_control_cell_counts']['RAMB36E1_RAMB36E1']==6
    assert len(r['DSP_feature_comparison'])==4 and len(r['BRAM_feature_comparison'])==6
    assert r['clock_fanout_contracts'] and r['native_FASM_repeated_clock_enable_lines']
    assert r['consumer_merge_contract']['conflicting_assignment_rejected']
    assert r['production_source_before']==r['production_source_after']
    assert [c['label'] for c in r['commands']]==COMMANDS
    assert all(c['status']=='PASS_TOOL_EXECUTION_ONLY' and c['returncode']==c['expected_returncode']==0 for c in r['commands'])


def verify_qualification(path):
    path=Path(path).resolve(strict=True);r=json.loads(path.read_text());verify_metadata(r)
    original,before=admit();bind_report(path,r,before);verify_bindings(before)
    assert r['executable']==original['executable'] and r['native_version']==original['native_version']
    compared=compare_saved_features();assert all(r[k]==v for k,v in compared.items())
    for c in r['commands']:assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',Path(c['log']).read_text())
    verify_bindings(before);return r,before


def main():
    out=ROOT/f'build/openxc7/native-heap-clock-features-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    r=dict(status='RUNNING',stage='source_bound_saved_native_admission',started_utc=timestamp(),supervisor_pid=os.getpid(),
           scope=__doc__,source={},commands=[],part='xc7k480tffg1156-2',full_parallel_products=512,placer='heap',
           native_evidence_parent=str(FAILED),original_failure_relabelled=False,native_source_or_executable_changed=False,
           new_native_PNR_executed=False,reused_completed_native_commands_without_execution=True,
           production_source_before=source_revision(),**{k:False for k in FLAGS})
    def save():(out/'report.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    def run(label,argv):
        c=dict(label=label,argv=list(map(str,argv)),log=str(out/(label+'.log')),cwd=str(ROOT),expected_returncode=0,
               timeout_seconds=120,status='RUNNING');r['commands'].append(c);save();start=time.monotonic()
        try:
            with Path(c['log']).open('w') as stream,subprocess.Popen(c['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                  preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_CORE,(0,0))) as p:
                c['pid']=p.pid;save()
                try:code=p.wait(timeout=120)
                except BaseException:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    p.wait();c['returncode']=p.returncode;raise
            c['returncode']=code;assert code==0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',Path(c['log']).read_text())
            c['status']='PASS_TOOL_EXECUTION_ONLY'
        except BaseException:c['status']='FAIL';raise
        finally:c['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        for p,name in ((Path(__file__),'executed_source.py'),(CONTROL,'executed_control_source.py'),(CLOCK_CONTROL,'executed_clock_control_source.py')):
            shutil.copyfile(p,out/name)
        original,before=admit()
        files={Path(__file__).resolve(),CONTROL,CLOCK_CONTROL,Path(sys.executable).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for p in files:sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
        verify_bindings(before);r.update(source=before,executable=original['executable'],native_version=original['native_version'],stage='clock_bound_feature_comparison',
            python_version=sys.version,native_positive_placements=3,lut_output_comparisons=1024,illegal_pair_rejected_before_postPlace=True,
            compiled_heap_beta_store_certificate=original['compiled_heap_beta_store_certificate'])
        run('clock_contract_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CLOCK_CONTROL.name,'-v'])
        run('qualification_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'])
        run('generated_check',['make','generated-check'])
        r.update(compare_saved_features());verify_bindings(before);r['production_source_after']=source_revision()
        r.update(status=QUALIFIED,stage='complete',finished_utc=timestamp());verify_metadata(r)
    except BaseException as error:r.update(status='FAIL',error=repr(error));raise
    finally:
        r['finished_utc']=timestamp();r['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
