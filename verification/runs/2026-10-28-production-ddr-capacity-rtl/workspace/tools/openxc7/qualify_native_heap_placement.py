#!/usr/bin/env python3
"""Qualify HeAP on the same frozen corrected engine, not full physical fit.

Revalidate the completed static qualification and engine first. Change only
the placer selection in fresh commands, preserving all original fixtures,
part, clocks, seeds, warnings, normal refinement and feature expectations.
Require genuine illegal-pair rejection before postPlace, three native positive
placements and the unchanged four-DSP/six-BRAM route/FASM control. A failed
negative must not be accepted because it crashed or produced another error.
Keep the live full static placement/replay and full C32/K16 target unchanged.
No original source/input/gate, default tool, SHA256SUMS or FPGA is modified.
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
import qualify_strict_search_rounds as parent
from audit_empty_output_pairs import source_shaped
from pack_prefix_board import ROOT,digest,timestamp
from place_prefix_board import bind_report,verify_bindings
from evidence import source_revision

PARENT=ROOT/'build/openxc7/strict-search-qualification-1791428735139099414/report.json'
CONTROL=ROOT/'tests/cmac/test_native_heap_placement_control.py'
QUALIFIED='QUALIFIED_SMALL_NATIVE_HEAP_UNCHANGED_CORRECTED_ENGINE_LEGALITY_AND_DSP_BRAM_PNR_NOT_FULL_FIT_OR_SIGNOFF'
FLAGS=parent.first.FLAGS
LABELS=parent.first.LABELS
COMMANDS=['software_controls','generated_check','version',*LABELS,'small_native_PNR_FASM']
ROUTE_NAMESPACE=dict(parent.first.__dict__)
ROUTE_SOURCE=source_shaped(inspect.getsource(parent.first.check_native_log),(
    ('Running Static placer...','HeAP Placer Time:'),))
exec(compile(ROUTE_SOURCE,__file__+':equivalent-HeAP-route-completion-markers','exec'),ROUTE_NAMESPACE)
check_route_log=ROUTE_NAMESPACE['check_native_log']


def admit():
    q,before=parent.verify_qualification(PARENT)
    assert q['status']==parent.QUALIFIED and q['production_source_after']==source_revision()
    return q,before


def heap_argv(original):
    result=list(map(str,original));assert result.count('--placer')==1
    i=result.index('--placer')+1;assert result[i]=='static';result[i]='heap'
    assert '--Werror' in result and result[result.index('--freq')+1]=='50'
    assert result[result.index('--device')+1]=='xc7k480tffg1156-2'
    for flag in ('--force','--timing-allow-fail','--no-pack','--no-place','--parallel-refine',
                 '--placer-static-refine-max-iterations','--placer-heap-beta','--placer-heap-alpha'):
        assert flag not in result
    assert result[:i]+['static']+result[i+1:]==list(map(str,original))
    return result


def check_heap_log(code,text,negative=False):
    assert code==(125 if negative else 0),text[-4000:]
    assert text.count('Xilinx HeAP effective beta: 0.500000 (architecture default)')==1
    assert 'Creating initial analytic placement for ' in text
    assert not re.search(r'(?im)\bWARNING:|sorry:|target is ignored|matched nothing|Assertion failure|terminate called|bad_alloc',text)
    assert 'Running Static placer...' not in text and 'RKNPU strict search:' not in text
    if negative:
        assert 'post-placement validity check failed for Bel ' in text
        for marker in ('HeAP Placer Time:','Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...','Program finished normally.'):
            assert marker not in text,'Illegal placement continued into later stage: '+marker
        errors=[line for line in text.splitlines() if line.startswith('ERROR:')]
        assert errors and all('post-placement validity check failed for Bel ' in line or
                              'Placing design failed.' in line for line in errors),errors
    else:
        assert not re.search(r'(?im)\b(?:ERROR|FATAL):',text)
        for marker in ('HeAP Placer Time:','Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...','Program finished normally.'):
            assert marker in text,'Missing normal HeAP completion: '+marker


def expected_argv(q,label,out):
    if label=='small_native_PNR_FASM':
        original=json.loads(parent.first.NATIVE.read_text())
        return heap_argv(parent.first.small_argv(q['executable']['path'],original,out))
    c=next(c for c in q['commands'] if c['label']==label)
    xdc=next(v[4:] for v in c['argv'] if v.startswith('xdc='))
    return heap_argv(parent.first.probe_argv(q['executable']['path'],c['argv'][c['argv'].index('--json')+1],xdc,out/(label+'-placed.json')))


def verify_metadata(r):
    assert r['status']==QUALIFIED and r['stage']=='complete' and r['finished_utc']
    assert r['part']=='xc7k480tffg1156-2' and r['full_parallel_products']==512 and r['placer']=='heap'
    assert r['native_positive_placements']==3 and r['lut_output_comparisons']==1024
    assert r['illegal_pair_rejected_before_postPlace'] and r['small_native_PNR_FASM_executed']
    assert r['native_control_cell_counts']['DSP48E1_DSP48E1']==4 and r['native_control_cell_counts']['RAMB36E1_RAMB36E1']==6
    assert len(r['DSP_feature_comparison'])==4 and len(r['BRAM_feature_comparison'])==6
    assert [c['label'] for c in r['commands']]==COMMANDS
    assert all(r[k] is False for k in FLAGS)
    assert r['production_source_before']==r['production_source_after']
    for c in r['commands']:
        expected=125 if c['label']=='invalid-forced' else 0
        assert c['returncode']==c['expected_returncode']==expected
        assert c['status']==('PASS_EXPECTED_NATIVE_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')


def verify_qualification(path):
    path=Path(path).resolve(strict=True);r=json.loads(path.read_text());verify_metadata(r)
    q,before=admit();bind_report(path,r,before);verify_bindings(before)
    assert r['executable']==q['executable'] and r['native_version']==q['native_version']
    for c in r['commands']:
        label=c['label'];text=Path(c['log']).read_text()
        if label in LABELS:
            assert c['argv']==expected_argv(q,label,path.parent)
            check_heap_log(c['returncode'],text,label=='invalid-forced')
            output=path.parent/(label+'-placed.json')
            if label=='invalid-forced':assert not output.exists()
            else:
                fixture=c['argv'][c['argv'].index('--json')+1]
                assert c['placement_checks']==parent.first.validate_placed(output,47 if label=='counter' else 49,None if label=='counter' else fixture)
        elif label=='small_native_PNR_FASM':
            assert c['argv']==expected_argv(q,label,path.parent);check_heap_log(c['returncode'],text);check_route_log(text)
            original=json.loads(parent.first.NATIVE.read_text())
            assert all(r[k]==v for k,v in parent.first.compare_features(path.parent,original).items())
        else:assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',text)
    verify_bindings(before);return r,before


def main():
    out=ROOT/f'build/openxc7/native-heap-qualification-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    r=dict(status='RUNNING',stage='completed_frozen_static_engine_admission',scope=__doc__,started_utc=timestamp(),
           supervisor_pid=os.getpid(),source={},commands=[],part='xc7k480tffg1156-2',full_parallel_products=512,
           placer='heap',native_source_or_executable_changed=False,production_source_before=source_revision(),**{k:False for k in FLAGS})
    def save():(out/'report.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    def run(label,argv,expected=0,timeout=600):
        c=dict(label=label,argv=list(map(str,argv)),log=str(out/(label+'.log')),cwd=str(ROOT),
               expected_returncode=expected,timeout_seconds=timeout,status='RUNNING')
        r['commands'].append(c);save();start=time.monotonic()
        try:
            with Path(c['log']).open('w') as stream,subprocess.Popen(c['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
                  preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_CORE,(0,0))) as p:
                c['pid']=p.pid;save()
                try:code=p.wait(timeout=timeout)
                except BaseException:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    p.wait();c['returncode']=p.returncode;raise
            c['returncode']=code;text=Path(c['log']).read_text()
            if label in LABELS:check_heap_log(code,text,label=='invalid-forced')
            elif label=='small_native_PNR_FASM':check_heap_log(code,text);check_route_log(text)
            else:assert code==expected and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):',text),text[-4000:]
            c['status']='PASS_EXPECTED_NATIVE_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY';return text
        except BaseException:c['status']='FAIL';raise
        finally:c['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        q,before=admit()
        files={Path(__file__).resolve(),CONTROL,Path(sys.executable).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'))
        for p in files:sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
        verify_bindings(before);r.update(source=before,executable=q['executable'],native_version=q['native_version'],stage='small_heap_native_legality_controls')
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'],timeout=120)
        run('generated_check',['make','generated-check'],timeout=120)
        assert run('version',[q['executable']['path'],'--version'],timeout=60).strip()==q['native_version']
        positives=[]
        for label in LABELS:
            argv=expected_argv(q,label,out);run(label,argv,expected=125 if label=='invalid-forced' else 0)
            output=out/(label+'-placed.json')
            if label=='invalid-forced':assert not output.exists()
            else:
                fixture=argv[argv.index('--json')+1]
                value=parent.first.validate_placed(output,47 if label=='counter' else 49,None if label=='counter' else fixture)
                r['commands'][-1]['placement_checks']=value;positives.append(value);save()
        assert sum(v['lut_output_comparisons'] for v in positives)==1024
        r.update(native_positive_placements=3,lut_output_comparisons=1024,illegal_pair_rejected_before_postPlace=True,stage='small_heap_native_PNR_FASM',small_native_PNR_FASM_executed=True)
        run('small_native_PNR_FASM',expected_argv(q,'small_native_PNR_FASM',out),timeout=3600)
        original=json.loads(parent.first.NATIVE.read_text());r.update(parent.first.compare_features(out,original));verify_bindings(before)
        r['production_source_after']=source_revision();r.update(status=QUALIFIED,stage='complete',finished_utc=timestamp());verify_metadata(r)
    except BaseException as error:r.update(status='FAIL',error=repr(error));raise
    finally:
        r['finished_utc']=timestamp();r['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
