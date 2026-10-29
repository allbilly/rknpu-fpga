#!/usr/bin/env python3
"""Prepared full C32/K16 raw-FASM frame conversion, not bitstream/signoff.

Require a completed source-bound full HeAP route and revalidate every native
placement/scan/route, physical/logical identity and full DSP/BRAM feature gate.
Convert only its unchanged raw FASM with the already-qualified strict pinned
converter. Read back all 8,240 corrected DSP features and all actual HCLK bits;
comparison targets never become assembly/hardware inputs. Geometry, warnings,
missing-feature failures and source bindings stay strict. No circuit repair,
runtime CPU arithmetic/layout fixups, native P&R, bitstream assembly/emission,
FPGA/flash access or standalone checksum manifest occurs here.
"""
import argparse
from collections import Counter
import inspect
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import probe_native_heap_frames as small
import verify_full_heap_route as admission
from audit_empty_output_pairs import source_shaped
from check_full_native_features import placed_primitives
from audit_upstream_dsp_constants import sample_gap
from pack_prefix_board import ROOT,digest,timestamp
from place_prefix_board import bind_report,verify_bindings
from evidence import source_revision

CONTROL=ROOT/'tests/cmac/test_full_heap_frame_control.py'
SMALL=ROOT/'build/openxc7/native-heap-frame-control-1791462156684206950/report.json'
PASS='PASS_FULL_C32K16_RAW_FASM_EXACT_PART_FRAMES_8240_DSP_AND_ACTUAL_CLOCK_BITS_NOT_BITSTREAM_OR_SIGNOFF'
FLAGS=('numerical_acceptance','physical_fit_verified','timing_signoff','electrical_verified','drc_signoff',
       'bitstream_emitted','hardware_programmed','expected_features_used_for_conversion','clock_targets_used_for_conversion',
       'new_native_PNR_executed')
FRAME_TIMEOUT=43200


def verify_small_metadata(r):
    assert r['status']==small.PASS and r['stage']=='complete' and r['finished_utc']
    assert (r['part'],r['full_target_parallel_products'],r['native_control_dsps'],r['native_control_brams'])==(
        'xc7k480tffg1156-2',512,4,6)
    assert all(r[k] is False for k in FLAGS) and r['full_board_FASM_conversion_executed'] is False
    for field,count in (('DSP_frame_readback',64),('clock_frame_readback',2)):
        assert r[field]['features_compared']==r[field]['physical_DB_bits_compared']==count
        assert r[field]['actual_frame_bit_corruption_rejected_in_comparison_only'] is True
    assert r['converter_requests']==dict(input_lines=7875,injected_lines=97)
    assert r['production_source_before']==r['production_source_after']
    labels=['software_controls','generated_check','parser_runtime_version','strict_native_FASM_conversion',
            'exact_part_frame_geometry','DSP_frame_readback','clock_frame_readback']
    assert [c['label'] for c in r['commands']]==labels
    assert all(c['status']=='PASS_TOOL_EXECUTION_ONLY' and c['returncode']==c['expected_returncode']==0 for c in r['commands'])


def required_features(fasm,placements,selected,contracts):
    assert Counter(c['type'] for c in selected.values())=={'DSP48E1':515,'RAMB36E1':6},'Not full515-DSP/six-BRAM source'
    features,io,clocks=small.clock.parse_clock_bound_features(Path(fasm).read_text(),contracts)
    locations=placed_primitives(placements,selected);required={};count=0
    for name,source in selected.items():
        if source['type']!='DSP48E1':continue
        gap=sample_gap(features,locations[name],source)
        assert not gap['absent_or_different_features'],'Missing corrected full DSP feature'
        assert not set(required)&set(gap['required_features']),'Aliased full DSP sites'
        required.update(gap['required_features']);count+=1
    assert count==515 and len(required)==8240 and set(required.values())=={'1'}
    statements=len(features)+sum(len(v)-1 for v in io.values())+sum(len(v)-1 for v in clocks.values())
    return required,statements


def converter_requests(path):
    """Bound memory while preserving every actual request and its order."""
    def unique_fields(pairs):
        result={}
        for key,value in pairs:
            assert key not in result,'Duplicate converter request field'
            result[key]=value
        return result
    with Path(path).open() as stream:
        for line in stream:
            value=json.loads(line,object_pairs_hook=unique_fields)
            assert set(value)=={'feature','value','start','end','kind'},'Unmodeled converter request fields'
            yield value


DSP_READBACK_SOURCE=source_shaped(inspect.getsource(small.original.readback),(
    ("assert len(required) == 64 and set(required.values()) == {'1'}",
     "assert len(required) == 8240 and set(required.values()) == {'1'}"),
    ('PASS actual corrected DSP frame-bit readback and comparison-only corruption negative',
     'PASS actual full corrected DSP frame-bit readback and comparison-only corruption negative')))
DSP_NAMESPACE=dict(small.original.__dict__)
exec(compile(DSP_READBACK_SOURCE,__file__+':unchanged-DSP-frame-readback-scaled-only-to-full8240','exec'),DSP_NAMESPACE)
dsp_readback=DSP_NAMESPACE['readback']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routed',type=Path)
    parser.add_argument('--DSP-readback',nargs=3,type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--clock-readback',nargs=3,type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    assert sum(bool(v) for v in (args.routed,args.DSP_readback,args.clock_readback))==1,'Specify exactly one action'
    if args.DSP_readback:dsp_readback(*args.DSP_readback);return
    if args.clock_readback:small.clock_readback(*args.clock_readback);return
    path=args.routed.resolve(strict=True)
    # Reject RUNNING/small/build-only reports before even creating an attempt.
    assert path.is_relative_to(ROOT/'build/openxc7')
    admission.verify_metadata(json.loads(path.read_text()))
    out=ROOT/f'build/openxc7/full-native-heap-frames-{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    r=dict(status='RUNNING',stage='full_native_route_admission',started_utc=timestamp(),supervisor_pid=os.getpid(),
           scope=__doc__,source={},commands=[],channels=32,kernels=16,parallel_products=512,part='xc7k480tffg1156-2',
           intended_clock_period_ns=20,seed=3588,full_route_report=str(path),small_frame_report=str(SMALL),
           production_source_before=source_revision(),full_board_FASM_conversion_executed=False,
           **{k:False for k in FLAGS})
    def save():(out/'report.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    def run(label,argv,timeout):
        c=dict(label=label,argv=list(map(str,argv)),cwd=str(ROOT),log=str(out/(label+'.log')),
               expected_returncode=0,timeout_seconds=timeout,status='RUNNING');r['commands'].append(c);save();start=time.monotonic()
        assert 'XRAY_ALLOW_MISSING_FEATURES' not in os.environ
        try:
            with Path(c['log']).open('w') as stream,subprocess.Popen(c['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),start_new_session=True,
                  preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_CORE,(0,0))) as p:
                c['pid']=p.pid;save()
                try:code=p.wait(timeout=timeout)
                except BaseException:
                    try:os.killpg(p.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    p.wait();c['returncode']=p.returncode;raise
            c['returncode']=code;assert code==0,Path(c['log']).read_text()[-3500:];c['status']='PASS_TOOL_EXECUTION_ONLY'
        except BaseException:c['status']='FAIL';raise
        finally:c['seconds']=round(time.monotonic()-start,3);save()
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        routed,before,fasm,placements,contracts=admission.verify_route(path)
        control=json.loads(SMALL.read_text());verify_small_metadata(control);bind_report(SMALL,control,before)
        for p in (Path(__file__),CONTROL,Path(sys.executable).resolve(),small.original.frame.PYTHON.resolve(),
                  small.original.frame.CONVERTER,small.original.frame.VALIDATOR,small.original.frame.ADAPTER):
            p=p.resolve(strict=True);sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
        for m in list(sys.modules.values()):
            if getattr(m,'__file__',None) and Path(m.__file__).resolve().is_relative_to(ROOT/'tools'):
                p=Path(m.__file__).resolve();sha=digest(p);assert str(p) not in before or before[str(p)]==sha;before[str(p)]=sha
        verify_bindings(before)
        selected=json.loads(admission.route.previous.original.checker.checkpoint.SELECTED.read_text())
        required,statements=required_features(fasm,placements,selected,contracts)
        expected=out/'comparison-only-8240-DSP-features.json';expected.write_text(json.dumps(required,sort_keys=True)+'\n')
        clock_expected=out/'comparison-only-clock-features.json';clock_expected.write_text(json.dumps(dict.fromkeys(contracts,'1'),sort_keys=True)+'\n')
        for p in (expected,clock_expected):before[str(p)]=digest(p)
        r.update(source=before,conversion_input=str(fasm),native_executable=routed['executable'],
                 source_defined_DSP_features=8240,source_defined_native_statements=statements,clock_contracts=contracts)
        run('software_controls',[sys.executable,'-B','-W','error','-m','unittest','discover','-s','tests/cmac','-p',CONTROL.name,'-v'],120)
        run('generated_check',['make','generated-check'],120)
        frame=small.original.frame
        run('parser_runtime_version',[frame.PYTHON,'--version'],60)
        r.update(stage='full_raw_native_FASM_conversion',full_board_FASM_conversion_executed=True)
        destination=out/'native-conversion'
        run('strict_full_native_FASM_conversion',[frame.PYTHON,'-B',frame.__file__,'--worker',fasm,destination],FRAME_TIMEOUT)
        result=json.loads((destination/'result.json').read_text());frames=frame.validate_conversion(result,destination)
        request_path=destination/'feature-requests.jsonl'
        assert small.original.verify_requests(converter_requests(request_path),required)==result['counts']
        assert result['counts']['input_lines']==statements
        r['clock_converter_requests']=small.verify_clock_requests(converter_requests(request_path),contracts)
        for name,sha in result['inputs'].items():assert name not in before or before[name]==sha;before[name]=sha
        r.update(converter_requests=result['counts'],stage='exact_part_frame_geometry')
        validation_path=out/'frame-validation.json'
        run('exact_part_frame_geometry',[frame.PYTHON,'-B',frame.VALIDATOR,'--frames',frames,'--part',
            frame.DATABASE/frame.PART/'part.json','--tilegrid',frame.DATABASE/'xc7k480t/tilegrid.json','--output',validation_path],120)
        validation=json.loads(validation_path.read_text())
        assert validation['status']=='FRAME_INPUT_VALIDATION_PASS_ASSEMBLY_PENDING'
        assert validation['inputs_unchanged'] is True and validation['physical_verified'] is False
        r['frame_geometry']=validation['validation']
        for label,option,target,count in (('DSP_frame_readback','--DSP-readback',expected,8240),
                                          ('clock_frame_readback','--clock-readback',clock_expected,len(contracts))):
            r['stage']=label;output=out/(label+'.json')
            run(label,[frame.PYTHON,'-B',Path(__file__),option,frames,target,output],1800)
            readback=json.loads(output.read_text());assert readback['features_compared']==readback['physical_DB_bits_compared']==count
            assert readback['actual_frame_bit_corruption_rejected_in_comparison_only'] is True;r[label]=readback
        verify_bindings(before);r['production_source_after']=source_revision()
        assert r['production_source_before']==r['production_source_after']
        r.update(status=PASS,stage='complete')
    except BaseException as error:r.update(status='FAIL',error=repr(error));raise
    finally:
        r['finished_utc']=timestamp();r['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
