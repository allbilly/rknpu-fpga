#!/usr/bin/env python3
"""Fresh full-512 startup board simulation only; never launches implementation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tools.cmac.startup import qualification as q
from tools.evidence import timestamp


def update_fields(lock, entry, **fields):
    """Publish shared fields under the same lock used by JSON serialization."""
    with lock:
        entry.update(fields)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-preflight',type=Path,required=True)
    parser.add_argument('--simulator',choices=('iverilog','verilator'),default='iverilog')
    args=parser.parse_args()
    if sys.flags.optimize:parser.error('Python -O cannot qualify this source profile')
    parent_path=args.parent_preflight.resolve();parent=q.verify_parent(parent_path)
    parent_name=q.relative(parent_path)
    out=ROOT/'build/full512-startup-native'/f'{args.simulator}-{time.time_ns()}';out.mkdir(parents=True)
    report_path=out/'report.json'
    report={'status':'RUNNING','execution_schema':1,'profile':q.PROFILE,'simulator':args.simulator,
            'started_utc':timestamp(),'execution_root':str(ROOT),'output_directory':str(out.relative_to(ROOT)),
            'source_revision':q.source_revision(parent_name),'simulation_sources':q.source_names(parent_name),
            'parent_preflight':parent_name,'parent_preflight_sha256':q.digest(parent_path),
            'parent_source_sha256':parent['source']['sha256'],'channels':32,'kernels':16,'parallel_products':512,
            'seed':'Unchanged directed raw K65 board ROM; no randomized stimulus',
            'scope':'Full DSP-prefix startup wrapper native simulation. Fresh processes model configuration initialization only; no runtime reset, physical reconfiguration, FPGA/RK, fit/timing/DRC or bitstream acceptance.',
            'physical_fit_verified':False,'mapped_startup_board_verified':False,'bitstream_emitted':False,
            'hardware_programmed':False,'commands':[],'tests':[],'compiled_hierarchy':{},'python_version':sys.version,'python_executable':sys.executable}
    artifacts=set();lock=threading.RLock();results={}
    def save():
        with lock:report_path.write_text(json.dumps(report,indent=2)+'\n')
    def execute(name,argv,timeout=1800,**extra):
        log=out/(name+'.log');entry={'name':name,'argv':list(map(str,argv)),'status':'RUNNING','log':str(log.relative_to(ROOT))}|extra
        with lock:report['commands'].append(entry)
        save();start=time.monotonic();completed={}
        try:
            with log.open('w') as stream:
                result=subprocess.run(entry['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,check=False)
            completed.update(returncode=result.returncode,status='PASS' if result.returncode==0 else 'FAIL')
        except subprocess.TimeoutExpired:
            completed['status']='TIMEOUT';raise
        except BaseException:
            completed['status']='FAIL';raise
        finally:
            completed['seconds']=round(time.monotonic()-start,3)
            logged = log.exists()
            if logged:
                completed['log_sha256']=q.digest(log)
            with lock:
                update_fields(lock,entry,**completed)
                if logged:artifacts.add(str(log.relative_to(ROOT)))
                save()
        text=log.read_text()
        if result.returncode:raise RuntimeError(f'{name} failed ({result.returncode}); see {log}')
        return text
    save()
    try:
        compiler=shutil.which(args.simulator)
        if compiler is None or (args.simulator=='iverilog' and shutil.which('vvp') is None):
            raise FileNotFoundError('UNAVAILABLE: selected startup simulator')
        compiler=str(Path(compiler).absolute());update_fields(lock,report,compiler={'path':compiler,'sha256':q.digest(compiler)})
        update_fields(lock,report,tool_version=execute('version',[compiler,'--version' if args.simulator=='verilator' else '-V']).splitlines()[0])
        if args.simulator=='iverilog':
            runtime=str(Path(shutil.which('vvp')).absolute());update_fields(lock,report,runtime={'path':runtime,'sha256':q.digest(runtime)})
            update_fields(lock,report,runtime_version=execute('runtime_version',[runtime,'-V']).splitlines()[0])
        else:
            cxx=shutil.which('c++')
            if cxx is None:raise FileNotFoundError('UNAVAILABLE: C++ compiler for Verilator')
            update_fields(lock,report,cxx={'path':cxx,'sha256':q.digest(cxx)})
            update_fields(lock,report,cxx_version=execute('cxx_version',[cxx,'--version']).splitlines()[0])
        execute('rom_check',[sys.executable,str(ROOT/'tools/cmac/gen_array_board.py'),'--check'])
        execute('controls',[sys.executable,'-m','unittest','discover','-s','tests/cmac/startup','-p','test_qualification.py','-v'])
        warning_sets=[]
        for polarity in (0,1):
            (out/f'led{polarity}/obj').mkdir(parents=True)
            if args.simulator=='verilator':
                for action in ('lint','hierarchy'):
                    text=execute(f'{action}_led{polarity}',q.build_argv(report,polarity,action))
                    warnings=q.reviewed_warnings(text)
                    with lock:update_fields(lock,report['commands'][-1],reviewed_warnings=warnings)
                    warning_sets.append(warnings)
                path=out/f'led{polarity}/hierarchy.tree.json';artifacts.add(str(path.relative_to(ROOT)))
                artifacts.add(str((out/f'led{polarity}/hierarchy.meta.json').relative_to(ROOT)))
                census=q.hierarchy_json(path)
                with lock:report['compiled_hierarchy'][str(polarity)]=census
            text=execute(f'compile_led{polarity}',q.build_argv(report,polarity))
            if args.simulator=='verilator':
                warnings=q.reviewed_warnings(text)
                with lock:update_fields(lock,report['commands'][-1],reviewed_warnings=warnings)
                warning_sets.append(warnings)
            else:q.require(not re.search(r'(?im)\b(?:error|warning):|sorry:',text),'Icarus compile diagnostics require review')
            binary=q.binary_path(args.simulator,report['output_directory'],polarity);artifacts.add(binary)
            image={'path':binary,'sha256':q.digest(ROOT/binary)}
            with lock:update_fields(lock,report['commands'][-1],binary=image)
            if args.simulator=='iverilog':
                census=q.hierarchy_vvp((ROOT/binary).read_text())
                with lock:report['compiled_hierarchy'][str(polarity)]=census
            save()
        if args.simulator=='verilator':
            q.require(all(sorted(items,key=str)==sorted(warning_sets[0],key=str) for items in warning_sets),
                      'Lint/elaboration/compile warning locations changed')
            update_fields(lock,report,reviewed_warning_locations=warning_sets[0],
                reset_warning_reason='Registered SYS-clock startup reset also gates synchronous memory enables; native hold/release is checked. No physical reset validation.')
        def run_polarity(polarity):
            for spec in [s for s in q.specs(args.simulator) if s['polarity']==polarity]:
                binary=q.binary_path(args.simulator,report['output_directory'],polarity)
                binding={'path':binary,'sha256':q.digest(ROOT/binary)}
                compiled=next(c['binary'] for c in report['commands'] if c['name']==f'compile_led{polarity}')
                q.require(binding==compiled,'Startup image changed after compile')
                text=execute(spec['name'],q.run_argv(report,spec),binary_before=binding)
                after={'path':binary,'sha256':q.digest(ROOT/binary)}
                q.require(after==binding,'Startup image changed during execution')
                with lock:update_fields(lock,next(c for c in report['commands'] if c['name']==spec['name']),binary_after=after)
                result=q.validate_result(text,spec)
                with lock:
                    results[spec['name']]={'spec':spec,'status':'PASS','result':result}
                    report['tests']=[results[s['name']] for s in q.specs(args.simulator) if s['name'] in results]
                print(result,flush=True);save()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run_polarity,p) for p in (0,1)]
            for future in futures:future.result()
        q.require(q.source_revision(parent_name)==report['source_revision'],'Startup sources changed during qualification')
        q.require(q.digest(compiler)==report['compiler']['sha256'],'Simulator changed during qualification')
        if args.simulator=='iverilog':q.require(q.digest(runtime)==report['runtime']['sha256'],'Runtime changed during qualification')
        q.verify_parent(parent_path)
        update_fields(lock,report,status=q.STATUS,finished_utc=timestamp(),artifacts=q.fingerprint(artifacts));save();q.verify_report(report_path)
    except Exception as error:
        update_fields(lock,report,status='UNAVAILABLE' if isinstance(error,FileNotFoundError) else 'FAIL',reason=str(error),finished_utc=timestamp(),artifacts=q.fingerprint(artifacts));save()
        print(f'{report["status"]}: {error}; report {report_path}',file=sys.stderr)
        return 2 if report['status']=='UNAVAILABLE' else 1
    print(report_path,flush=True);return 0


if __name__=='__main__':raise SystemExit(main())
