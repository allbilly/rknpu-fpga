#!/usr/bin/env python3
"""Qualify real tinygrad final-writer execution against the native EW frame RTL."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.backend.qualification import (PIN, binary_path, build_argv, digest, fingerprint,
                                         run_argv, source_revision, specs, validate_execution, validate_pipeline, verify_report)
from tools.evidence import timestamp


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=Path, default=Path(os.environ.get(
        'TINYGRAD_ROOT', os.environ.get('RKNPU_TINYGRAD', Path.home()/'tinygrad'))))
    return parser


def execution_environment(backend):
    # Explicit CLI selection wins over either inherited spelling, including
    # the legacy variable accepted by standalone runtime controls.
    return dict(os.environ, TINYGRAD_ROOT=str(backend), RKNPU_TINYGRAD=str(backend),
                CACHELEVEL='0', PYTHONDONTWRITEBYTECODE='1')


def launcher_identity(path):
    # ccache's c++ symlink selects the compiler through argv[0]. Resolving that
    # link before execution probes ccache itself instead of the C++ compiler.
    launcher = os.path.abspath(path)
    return {'path': launcher, 'resolved_target': str(Path(launcher).resolve()), 'sha256': digest(launcher)}


def main():
    parser = argument_parser()
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('optimized Python is unsupported for qualification')
    backend = args.backend.resolve()
    out = ROOT/'build/backend-rtl'/str(time.time_ns());out.mkdir(parents=True)
    report_path = out/'report.json'
    report = {'status':'RUNNING','execution_schema':1,'started_utc':timestamp(),
              'execution_root':str(ROOT),'output_directory':str(out.relative_to(ROOT)),
              'backend_root':str(backend),'backend_commit':PIN,'python':sys.executable,
              'python_version':sys.version,'source_revision':source_revision(),
              'scope':'Actual production compiler/final writer to native EW frame RTL only; no BSCANE2, FPGA, RK silicon, DDR or PCIe proof',
              'commands':[],'tests':[]}
    artifacts=set()
    def save():report_path.write_text(json.dumps(report,indent=2)+'\n')
    def execute(name,argv,timeout=600,**extra):
        log=out/(name+'.log');entry={'name':name,'argv':argv,'status':'RUNNING','log':str(log.relative_to(ROOT))}|extra
        report['commands'].append(entry);save();start=time.monotonic()
        try:
            with log.open('w') as stream:
                result=subprocess.run(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout,check=False,
                                      env=execution_environment(backend))
            entry.update(returncode=result.returncode,status='PASS' if result.returncode==0 else 'FAIL')
        except subprocess.TimeoutExpired:
            entry['status']='TIMEOUT';raise
        finally:
            entry['seconds']=round(time.monotonic()-start,3)
            if log.exists():entry['log_sha256']=digest(log);artifacts.add(str(log.relative_to(ROOT)))
            save()
        text=log.read_text()
        if result.returncode:raise RuntimeError(f'{name} failed ({result.returncode}); see {log}')
        return text
    save()
    try:
        compiler=shutil.which('verilator');cxx=shutil.which('c++')
        if compiler is None or cxx is None:raise FileNotFoundError('UNAVAILABLE: Verilator and C++ are required')
        if not (backend/'.git').exists():raise FileNotFoundError('UNAVAILABLE: audited tinygrad checkout required')
        def git(*argv):return subprocess.check_output(['git','-C',str(backend),*argv],text=True).strip()
        if git('rev-parse','HEAD')!=PIN or git('status','--porcelain'):raise RuntimeError('Expected the clean pinned tinygrad backend')
        compiler=str(Path(compiler).resolve())
        report['compiler']={'path':compiler,'sha256':digest(compiler)}
        report['cxx']=launcher_identity(cxx);cxx=report['cxx']['path']
        report['tool_version']=execute('version',[compiler,'--version']).splitlines()[0]
        report['cxx_version']=execute('cxx_version',[cxx,'--version']).splitlines()[0]
        execute('unit',[sys.executable,'-m','unittest','discover','-s','tests/backend','-p','test_runtime.py','-v'])
        execute('trace_unit',[sys.executable,'-m','unittest','discover','-s','tests/backend','-p','test_trace_contract.py','-v'])
        execute('runner_unit',[sys.executable,'-m','unittest','discover','-s','tests/backend','-p','test_runner.py','-v'])
        (out/'obj').mkdir()
        execute('compile',build_argv(compiler,str(ROOT),str(out.relative_to(ROOT))))
        binary=binary_path(str(out.relative_to(ROOT)));artifacts.add(binary)
        image={'path':binary,'sha256':digest(ROOT/binary)}
        report['commands'][-1]['binary']=image
        for spec in specs():
            if digest(ROOT/binary)!=image['sha256']:raise ValueError('image changed since compile')
            text=execute(spec['name'],run_argv(report,spec),binary_before=image)
            report['commands'][-1]['binary_after']={'path':binary,'sha256':digest(ROOT/binary)}
            if digest(ROOT/binary)!=image['sha256']:raise ValueError('image changed during worker')
            directory=out/spec['name'];worker=json.loads((directory/'report.json').read_text())
            coverage=validate_execution(worker,directory/'frames.jsonl',spec)
            pipeline=validate_pipeline(worker,directory)
            report['tests'].append({'spec':spec,'status':'PASS','coverage':coverage,
                                    'pipeline_calls':pipeline,
                                    'results':[line for line in text.splitlines() if line.startswith('PASS ')]})
            artifacts.update(str(p.relative_to(ROOT)) for p in directory.rglob('*') if p.is_file() and 'locks' not in p.parts)
            print(f'PASS {spec["name"]}: {coverage}',flush=True);save()
        if source_revision()!=report['source_revision'] or git('rev-parse','HEAD')!=PIN or git('status','--porcelain'):
            raise ValueError('source changed during backend qualification')
        if digest(compiler)!=report['compiler']['sha256'] or digest(cxx)!=report['cxx']['sha256']:
            raise ValueError('tool changed during qualification')
        report.update(status='PASS',finished_utc=timestamp(),artifacts=fingerprint(artifacts));save();verify_report(report_path)
    except Exception as exc:
        report.update(status='UNAVAILABLE' if isinstance(exc,FileNotFoundError) else 'FAIL',reason=str(exc),finished_utc=timestamp())
        report['artifacts']=fingerprint(artifacts);save();print(f'{report["status"]}: {exc}; report {report_path}',file=sys.stderr)
        return 2 if report['status']=='UNAVAILABLE' else 1
    print(report_path);return 0


if __name__=='__main__':raise SystemExit(main())
