#!/usr/bin/env python3
"""Execute unchanged whole production make test without touching live fixtures.

Copy exactly the complete current production source manifest and all four
existing complete stimulus directories to a fresh, private build workspace.
Require identical per-file source/fixture digests before and after. Run the
literal production test target, holding only vector-generator prerequisites
because their existing outputs are frozen. Every model, lint, native RTL,
four-state RTL and product test target still executes with its original
warnings, numerical goldens, seeds and per-command timeouts. A return code
alone is insufficient: require all five source-bound numeric/simulator reports.
No nested experimental CMAC/mapped board or FPGA acceptance follows. Existing
build outputs, live physical/replay inputs and SHA256SUMS are not modified.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,source_revision,timestamp
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pack_prefix_board import digest
from place_prefix_board import verify_bindings

FIXTURE_DIRECTORIES=('vectors','dma_vectors','cmac_vectors','fp16_product_vectors')
REPORTS={'numeric_report.json':'PASS','rtl/report.json':'PASS','iverilog/report.json':'PASS',
         'cmac_verilator/report.json':'PASS_RAW_PRODUCT_PATH_ONLY','cmac_iverilog/report.json':'PASS_RAW_PRODUCT_PATH_ONLY'}


def main():
    out=ROOT/f'build/source-identical-production-regression/{time.time_ns()}';out.mkdir(parents=True,exist_ok=False)
    work=out/'source_identical_workspace';work.mkdir(exist_ok=False)
    report=dict(status='RUNNING',stage='prepare_exact_production_sources_and_frozen_vectors',scope=__doc__,
        started_utc=timestamp(),supervisor_pid=os.getpid(),python_version=sys.version,commands=[],
        production_source_before=source_revision(),source={},execution_inputs={},actual_make_test_executed=False,
        all_original_test_targets_retained=True,only_vector_generator_prerequisites_held=True,
        source_identical_workspace=str(work.relative_to(ROOT)),full_board_numerical_acceptance=False,
        physical_fit_verified=False,timing_signoff=False,electrical_verified=False,drc_signoff=False,
        bitstream_emitted=False,hardware_programmed=False,hardware_input_modified=False)
    def save():(out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    save();print(out/'report.json',flush=True)
    signal.signal(signal.SIGTERM,lambda s,f:(_ for _ in ()).throw(SystemExit(128+s)))
    try:
        shutil.copyfile(__file__,out/'executed_source.py')
        before={};copied={};sources=report['production_source_before']['files']
        for name,sha in sources.items():
            source=ROOT/name;assert source.is_file() and digest(source)==sha
            target=work/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            assert digest(target)==sha;before[str(source)]=sha;copied[str(target)]=sha
        report['declared_source_files']=len(sources)
        for directory in FIXTURE_DIRECTORIES:
            origin=ROOT/'build'/directory;assert origin.is_dir()
            inputs=sorted(p for p in origin.rglob('*') if p.is_file());assert inputs
            for source in inputs:
                assert not source.is_symlink(),'Unresolved production stimulus symlink'
                name=source.relative_to(ROOT);target=work/name;target.parent.mkdir(parents=True,exist_ok=True)
                sha=digest(source);shutil.copyfile(source,target);assert digest(target)==sha
                before[str(source)]=sha;copied[str(target)]=sha
        for source in (Path(__file__).resolve(),Path(sys.executable).resolve(),
            *(Path(shutil.which(name)).resolve() for name in ('make','c++','verilator','iverilog','vvp'))):before[str(source)]=digest(source)
        report.update(source=before,execution_inputs=copied)
        verify_bindings(before);verify_bindings(copied)
        for relative in sources:assert digest(work/relative)==sources[relative]
        argv=['make','-j2','-o','vectors','-o','cmac-vectors','test']
        step=dict(argv=argv,cwd=str(work),log=str(out/'make_test.log'),status='RUNNING',timeout_seconds=7200)
        report['commands'].append(step);report.update(stage='actual_whole_production_make_test',actual_make_test_executed=True);save()
        start=time.monotonic()
        try:
            with Path(step['log']).open('w') as stream,subprocess.Popen(argv,cwd=work,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as process:
                step['pid']=process.pid;save()
                try:code=process.wait(timeout=7200)
                except BaseException:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait();step['returncode']=process.returncode;raise
            step.update(returncode=code,status='PASS_TOOL_EXECUTION_ONLY' if code==0 else 'FAIL')
        finally:step['seconds']=round(time.monotonic()-start,3);save()
        verify_bindings(before);verify_bindings(copied)
        report['production_source_after']=source_revision();assert report['production_source_after']==report['production_source_before']
        assert code==0,'Actual unchanged production make test failed; inspect fresh native subreports'
        results={}
        for name,status in REPORTS.items():
            path=work/'build'/name;r=json.loads(path.read_text())
            revision=r.get('source_revision')
            assert isinstance(revision,dict) and revision==report['production_source_before'],'Production simulator source identity changed'
            assert r['status']==status and r['finished_utc'],'Production report incomplete or failed'
            if name!='numeric_report.json':
                assert r['commands'] and r['tests'] and all(c['status']=='PASS' and c['returncode']==0 for c in r['commands'])
                assert all(t['status']=='PASS' for t in r['tests'])
            else:assert r['cases']>1000000 and r['seed']=='0x3588'
            results[name]=dict(status=r['status'],sha256=digest(path),tests=len(r.get('tests',[])),finished_utc=r['finished_utc'])
        report.update(status='PASS_UNCHANGED_COMPLETE_PRODUCTION_REGRESSION_ONLY_NOT_EXPERIMENTAL_BOARD_OR_FPGA',
            stage='complete',production_reports=results)
    except BaseException as error:report.update(status='FAIL',error=repr(error));raise
    finally:
        report['production_source_after']=source_revision()
        report['finished_utc']=timestamp()
        report['artifacts']={str(p.relative_to(ROOT)):digest(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        report['subreport_artifacts']={str(p.relative_to(ROOT)):digest(p) for p in (work/'build').rglob('report.json') if p.is_file()}
        save();print(out/'report.json',flush=True)


if __name__=='__main__':main()
