#!/usr/bin/env python3
"""Compile a hash-bound copy of the actual generated top, then all 208 frames."""
import argparse
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

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
import dsp_prefix_top_compile_admission as admission
import dsp_prefix_protected_library_contract as protected
import dsp_prefix_build_contract as build_contract
original=admission.kernel.runner


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('top','fdce-verilator','fdce-iverilog','top-archive','interface-archive','build-errors-archive'):
        parser.add_argument('--'+name+'-report',type=Path,required=True)
    args=parser.parse_args()
    paths=[getattr(args,name+'_report').resolve() for name in
        ('top','fdce_verilator','fdce_iverilog','top_archive')]
    interface_archive=args.interface_archive_report.resolve()
    build_errors_archive=args.build_errors_archive_report.resolve()
    assert build_errors_archive.is_relative_to(ROOT) and build_errors_archive.is_file()
    assert interface_archive.is_relative_to(ROOT) and interface_archive.is_file()
    preserved=json.loads(interface_archive.read_text())
    assert preserved['status']=='ARCHIVED_ACTUAL_GENERATED_PREFIX_TOP_LIBRARY_OPERATION_GUARD_FAILURE'
    assert preserved['original_required_operations']==['combo_update','create']
    assert preserved['observed_operations']==['combo_update','create','seq_update']
    assert all(path.is_relative_to(ROOT) and path.is_file() for path in paths)
    out=ROOT/f'build/rknpu-dsp-prefix-array-generated-top-replay/{time.time_ns()}'
    out.mkdir(parents=True,exist_ok=False)
    initial=[*paths,interface_archive,build_errors_archive,Path(__file__).resolve(),*[Path(module.__file__).resolve()
        for module in list(sys.modules.values()) if getattr(module,'__file__',None)
        and Path(module.__file__).resolve().is_relative_to(ROOT/'tools')]]
    initial_binding=fingerprint(initial)
    report=dict(status='RUNNING',stage='admission',started_utc=timestamp(),supervisor_pid=os.getpid(),commands=[],
        source=initial_binding,initial_admission_inputs=initial_binding,
        preserved_interface_failure=str(interface_archive.relative_to(ROOT)),
        preserved_build_errors=str(build_errors_archive.relative_to(ROOT)),
        parent_reports={name:str(path.relative_to(ROOT)) for name,path in zip(
            ('top','fdce_verilator','fdce_iverilog','top_archive'),paths,strict=True)},
        channels=32,kernels=16,parallel_products=512,frames=208,expected_outputs=3328,seed='0x35883216',
        reused_compiled_kernel=True,reused_actual_generated_top=True,original_failures_preserved=True,
        numerical_netlist_binary_fixture_acceptance=False,complete_build_diagnostics_accepted=False,
        full_mapped_gate_accepted=False,four_state_x_acceptance=False,
        raw_board_numerical_acceptance=False,physical_fit_verified=False,bitstream_emitted=False,
        hardware_programmed=False,scope=__doc__)
    def save():
        (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    def run(argv,label,negative=None):
        step=dict(argv=list(map(str,argv)),log=str((out/(label+'.log')).relative_to(ROOT)),status='RUNNING')
        report['commands'].append(step);save();start=time.monotonic()
        try:
            with (ROOT/step['log']).open('w') as stream:
                def no_core():resource.setrlimit(resource.RLIMIT_CORE,(0,0))
                with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,
                    start_new_session=True,preexec_fn=no_core) as proc:
                    step['pid']=proc.pid;save()
                    try:code=proc.wait(timeout=14400)
                    except BaseException:
                        try:os.killpg(proc.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                        proc.wait();raise
            step['returncode']=code;text=(ROOT/step['log']).read_text()
            if negative is None:
                assert code==0
                build_contract.require_clean_build(text)
                step['exact_admitted_diagnostic_count']=len(admission.kernel.validate_followup(text,admitted))
            else:
                result=original.validate_result(text,code,negative)
                if result:report['result']=result
            step['status']='PASS';return text
        except BaseException:step['status']='FAIL';raise
        finally:step['seconds']=round(time.monotonic()-start,3);save()
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    save()
    try:
        preserved_build,template=build_contract.verify_preserved_errors(build_errors_archive)
        report['preserved_build_error_archive_sha256']=preserved_build['archive_sha256']
        parent,kernel_certificate,top_certificate,admitted=admission.admit(*paths)
        report['compiler_admission']=kernel_certificate;report['top_admission']=top_certificate
        cp=ROOT/parent['parent_reports']['compile'];compiled=json.loads(cp.read_text());old=cp.parent
        area_path,native_path=[ROOT/compiled['parent_reports'][name] for name in ('area','native')]
        area,_,_=original.mapping.verify_area(area_path);native=original.replay.verify_native(native_path)
        original.mapping.validate_shared_leaf(area,native)
        vector_report=ROOT/native['vector_report'];vectors=vector_report.parent/'vectors.hex'
        negative=old/'negative_vectors.hex';bench=old/(original.BENCH+'.sv')
        assert len(vectors.read_text().splitlines())==208
        assert negative.read_text()==original.negative_vectors(vectors.read_text())
        assert bench.read_text()==original.mapped_bench(original.SOURCE_BENCH.read_text())
        library=old/'cell'/('lib'+original.BLOCK+'.a')
        generated=paths[0].parent/'top';obj=out/'top'
        source_files=sorted(path for path in generated.rglob('*') if path.is_file())
        assert source_files and not any(path.suffix in ('.o','.a') or path.name=='sim' for path in source_files)
        for path in source_files:
            assert str(path.relative_to(ROOT)) in parent['artifacts']['files']
            target=obj/path.relative_to(generated);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)
            assert target.read_bytes()==path.read_bytes()
        cpp=list(obj.glob('V'+original.BENCH+'*.cpp'))
        wrapper=old/'cell'/(original.BLOCK+'.sv')
        bridge=old/'cell'/(original.BLOCK+'.cpp')
        for path in (wrapper,bridge):
            assert str(path.relative_to(ROOT)) in kernel_certificate['compiled_products']['files']
        interface=protected.validate(wrapper.read_text(),bridge.read_text(),[path.read_text() for path in cpp])
        operations=interface['actual_library_operations']
        assert not any('LUT' in path.name or original.SIM_KERNEL in path.name for path in cpp)
        report['library_operations']=operations
        report['source_bound_protected_library_interface']=interface
        imported=[Path(module.__file__).resolve() for module in list(sys.modules.values())
            if getattr(module,'__file__',None) and Path(module.__file__).resolve().is_relative_to(ROOT/'tools')]
        hierarchy=obj/('V'+original.BENCH+'_hier.mk')
        changed,path_contract=build_contract.relative_hierarchy_library(hierarchy.read_text(),obj,library)
        hierarchy.write_text(changed)
        report['operational_library_path_contract']=path_contract
        assert all((obj/path.relative_to(generated)).read_bytes()==path.read_bytes()
            for path in source_files if path.relative_to(generated)!=hierarchy.relative_to(obj))
        tracked=[*initial,cp,area_path,native_path,vector_report,vectors,negative,bench,library,wrapper,bridge,template,
            ROOT/'tests/cmac/test_dsp_prefix_protected_library_control.py',
            ROOT/'tests/cmac/test_dsp_prefix_build_contract_control.py',*source_files,*imported]
        before=fingerprint(tracked);report['source']=before
        copied=fingerprint([obj/path.relative_to(generated) for path in source_files]);report['copied_generated_inputs']=copied
        for path in sorted(set(tracked)):
            target=out/'snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(path.read_bytes())
        report['tool_version']=run(['verilator','--version'],'verilator_version').splitlines()[0]
        report['cxx_version']=run(['c++','--version'],'cxx_version').splitlines()[0]
        report['make_version']=run(['make','--version'],'make_version').splitlines()[0]
        report['ar_version']=run(['ar','--version'],'ar_version').splitlines()[0]
        installed_root=Path(run(['verilator','--getenv','VERILATOR_ROOT'],'verilator_root').strip())
        installed_template=installed_root/'include/verilated.mk'
        assert installed_template.read_bytes()==template.read_bytes(), 'Changed installed archive recipe'
        report['installed_make_template_sha256']=fingerprint([template])['files'][str(template.relative_to(ROOT))]
        assert report['tool_version']==parent['tool_version'] and report['cxx_version']==parent['cxx_version']
        report['stage']='top_compile';save()
        run(['make','-C',obj,'-f','V'+original.BENCH+'.mk','-j','2',
            'OPT_FAST=-O2','OPT_SLOW=-O2','OPT_GLOBAL=-O2'],'top_compile')
        assert fingerprint([ROOT/name for name in copied['files']])==copied
        assert installed_template.read_bytes()==template.read_bytes()
        kernel_members=run(['ar','-t',library],'kernel_archive_members')
        merged=obj/('V'+original.BENCH+'__ALL.a')
        merged_members=run(['ar','-t',merged],'merged_archive_members')
        top_objects=[path.name for path in obj.glob('V'+original.BENCH+'*.o')]
        report['archive_member_contract']=build_contract.validate_archive_members(kernel_members,merged_members,top_objects)
        report['complete_build_diagnostics_accepted']=True
        binary=obj/'sim';execution=fingerprint([binary,library]);report['execution_inputs']=execution
        report['stage']='simulation';save()
        for label,stimulus,is_negative in (('negative_test',negative,True),('actual_test',vectors,False)):
            binding=fingerprint([stimulus]);report.setdefault('stimulus_inputs',{})[label]=binding;save()
            run([binary,f'+VECTORS={stimulus}','+COUNT=208'],label,is_negative)
            assert fingerprint([stimulus])==binding and fingerprint([binary,library])==execution
        assert fingerprint(tracked)==before and fingerprint(initial)==initial_binding
        assert fingerprint([ROOT/name for name in kernel_certificate['compiled_products']['files']])==kernel_certificate['compiled_products']
        report.update(status='PASS_FULL_C32K16_DSP_PREFIX_ARRAY_MAPPED_BINARY_CLEAN_REUSED_TOP_FIXTURES_ONLY',
            stage='complete',numerical_netlist_binary_fixture_acceptance=True,full_mapped_gate_accepted=True)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['finished_utc']=timestamp()
        report['artifacts']=fingerprint([path for path in out.rglob('*') if path.is_file() and path!=out/'report.json'])
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
