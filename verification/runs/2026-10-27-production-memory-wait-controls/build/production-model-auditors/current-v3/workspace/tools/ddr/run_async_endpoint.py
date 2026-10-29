#!/usr/bin/env python3
"""Freeze/build/run the SYS50/UI133 async endpoint model, never FPGA tools.

Build once, then execute selected cases in separate fresh directories. A
subset receipt cannot claim the complete21-case matrix. The encoded-beat PHY
model supplies neither pad training nor physical DDR qualification.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr import async_endpoint_contract as contract, endpoint_vectors, mig_logic_sources, staged_compile
from tools.ddr.interface import load_json, require

RTL = ('rtl/rk_fp16_alu.sv', 'rtl/rk_ew_regs.sv', 'rtl/rk_ew_engine.sv',
       'rtl/rk_ew_core.sv', 'rtl/rk_ew_dma.sv', 'rtl/rk_axi_mem.sv',
       'rtl/rk_job_control.sv', 'rtl/host/rk_jtag_backend.sv',
       'rtl/ddr/rk_mig_reset_coordinator.sv', 'rtl/ddr/rk_mig_ecc_monitor.sv',
       'rtl/ddr/rk_mig_write_fence.sv', 'rtl/ddr/rk_ddr_memory_fabric.sv',
       'rtl/ddr/rk_async_job_port.sv', 'rtl/ddr/rk_async_mem_port.sv',
       'rtl/ddr/rk_ew_async_engine.sv', 'rtl/ddr/rk_jtag_ew_ddr_async.sv',
       'tests/ddr/tb_jtag_ew_ddr_async.sv')
LOCAL = tuple(sorted(set(RTL + endpoint_vectors.LOCAL + mig_logic_sources.LOCAL + (
    'tools/ddr/run_async_endpoint.py', 'tools/ddr/async_endpoint_contract.py',
    'tools/ddr/staged_compile.py',
    'tools/ddr/endpoint_contract.py',
    'tests/ddr/async_endpoint/warnings.json', 'tests/ddr/endpoint/strict_line_image.svh',
    'tests/ddr/async_endpoint/test_contract.py',
    'tests/ddr/async_endpoint/test_staged.py',
    'fpga/ddr/async_endpoint.mk'))))
sha = contract.sha


def expanded_specs(specs):
    require(len(specs)==20,'Original twenty scenarios must remain intact')
    sub=next(s for s in specs if s['name']=='capture_sub_9')
    return specs+[dict(sub,name='partial_task_fault',negative=10)]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, data):
    path.write_text(json.dumps(data, indent=2)+'\n')


def fresh(path):
    path = Path(path).resolve()
    require(path.is_relative_to(ROOT/'build') and not path.exists(), 'Fresh workspace build directory required')
    path.mkdir(parents=True)
    return path


def check_inputs(inputs):
    for name, expected in inputs.items():
        require(Path(name).is_file() and sha(name) == expected, 'Changed frozen input: '+name)


def run_plan(package, trial, spec):
    case = Path(package)/'vectors'/spec['case']
    return [str(Path(package)/'obj/sim'), '+CASE='+str(case), '+OUTPUT='+str(Path(trial)/'observed.txt'),
            f"+START={spec['address']:08x}", f"+AMOUNT={spec['amount']}", f"+NTASKS={spec['tasks']}",
            f"+NLINES={spec['lines']}", f"+JOBS={spec['jobs']}", f"+NEGATIVE={spec['negative']}",
            f"+RESET_RECOVERY={spec['reset_recovery']}"]


def runtime_inputs(package, built):
    return dict(built['inputs']) | {str(package/'report.json'): sha(package/'report.json'),
        str(package/'obj/sim'): built['binary_sha256'],
        str(package/'compile.log'): built['compile']['log_sha256']}


def runtime_timeout(spec, data):
    return 1800 if data['successful_jobs'] or spec['negative'] == 8 else 300


def execute(argv, directory, name, timeout, inputs):
    check_inputs(inputs)
    record = dict(argv=argv, timeout_seconds=timeout, started_utc=now(), status='RUNNING')
    path = directory/(name+'.json')
    write(path, record)
    child = None
    start = time.monotonic()
    try:
        with (directory/(name+'.log')).open('x') as stream:
            watched = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP}
            mask = signal.pthread_sigmask(signal.SIG_BLOCK, watched)
            try:
                child = subprocess.Popen(argv, cwd=directory, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True, env=dict(os.environ, MAKEFLAGS='', MFLAGS=''),
                    preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, mask))
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, mask)
            record['pid'] = child.pid
            write(path, record)
            try:
                record['returncode'] = child.wait(timeout=timeout)
            except BaseException:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                raise
        check_inputs(inputs)
        record['status'] = 'EXITED'
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record.update(seconds=time.monotonic()-start, finished_utc=now(),
                      log_sha256=sha(directory/(name+'.log')))
        write(path, record)
    return record, (directory/(name+'.log')).read_text()


def build(args):
    out = fresh(args.out)
    source = {name: sha(ROOT/name) for name in LOCAL}
    report = dict(schema=contract.SCHEMA, status='RUNNING', scope=contract.SCOPE,
                  local_source=source, hardware_accessed=False, vivado_executed=False,
                  physical_integration_ready=False, started_utc=now(), random_seed=None,
                  stimulus='Directed fixed clocks, original complete BO captures and explicit fault inputs')
    def save():
        write(out/'report.json', report)
    save()
    try:
        for name in source:
            dest = out/'source'/name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, dest)
        logic = mig_logic_sources.prepare(args.archive, out/'logic', args.primitive_library)
        write(out/'logic-plan.json', logic)
        specs = expanded_specs(endpoint_vectors.generate(out/'vectors'))
        report.update(specs=specs, logic_plan_sha256=sha(out/'logic-plan.json'))
        inputs = {str(p): sha(p) for directory in ('source', 'logic', 'vectors')
                  for p in (out/directory).rglob('*') if p.is_file()}
        inputs[str(out/'logic-plan.json')] = sha(out/'logic-plan.json')
        check_inputs({str(ROOT/n): h for n, h in source.items()})
        report['inputs'] = inputs
        tool = shutil.which('verilator')
        cxx = args.cxx or shutil.which('c++')
        require(tool is not None and cxx is not None, 'UNAVAILABLE: Verilator and C++ compiler required')
        version = subprocess.check_output([tool, '--version'], text=True).strip()
        report['tools'] = dict(verilator=dict(path=tool, sha256=sha(tool), version=version),
                               cxx=dict(path=cxx, sha256=sha(cxx),
                                        version=subprocess.check_output([cxx, '--version'], text=True).splitlines()[0]))
        sources = [str(out/'source'/n) for n in RTL]
        sources += [str(out/'source'/n) if n == 'tests/ddr/mig_logic_model.sv' else str(ROOT/n)
                    for n in logic['compiled_relative']]
        require(len(sources) == len(set(sources)), 'Duplicate compiler source')
        definitions = list(logic['definitions']) + ['-DRK_DDR_LINE_IMAGE_HEADER='+
            json.dumps(str(out/'source/tests/ddr/endpoint/strict_line_image.svh'))]
        make=shutil.which('make');require(make is not None,'UNAVAILABLE: GNU Make required')
        report['tools']['make']=dict(path=make,sha256=sha(make),
            version=subprocess.check_output([make,'--version'],text=True).splitlines()[0])
        translation,cpp=staged_compile.plans(tool,make,cxx,contract.TOP,out,definitions,sources)
        report['compiler_sources']=sources
        report['compile_plan']=[translation,cpp]
        budget=staged_compile.Budget(900)
        report['compile_method']='Verilator translation exits before ungrouped serial C++ make; shared900s budget'
        translated,log=execute(translation,out,'compile_translation',budget.remaining(),inputs)
        require(translated['returncode']==0,'Async DDR translation failed')
        policy = load_json(out/'source/tests/ddr/async_endpoint/warnings.json')
        admitted = contract.check_warnings(log, policy, sources, version, out/'source')
        # Reject new HDL diagnostics before starting a memory-intensive C++
        # compiler. The Verilator process has exited and released its IR.
        compiled,cpp_log=execute(cpp,out,'compile_cpp',budget.remaining(),inputs)
        require(compiled['returncode']==0,'Async DDR C++ compilation failed')
        elapsed=budget.finish()
        (out/'compile.log').write_text(log+'\n'+cpp_log)
        result=dict(status='EXITED',returncode=0,timeout_seconds=900,seconds=elapsed,
            argv=[translation,cpp],phases=[translated,compiled],log_sha256=sha(out/'compile.log'))
        staged_compile.verify_record(result,(translation,cpp),(translated,compiled))
        write(out/'compile.json',result)
        contract.check_warnings((out/'compile.log').read_text(),policy,sources,version,out/'source')
        require((out/'obj/sim').is_file(), 'Missing native image')
        report.update(status='PASS_ASYNC_DDR_NATIVE_BUILD_ONLY', compiler_sources=sources,
                      admitted_diagnostics=admitted, binary_sha256=sha(out/'obj/sim'),
                      binary_path=str(out/'obj/sim'), compile=result)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = now()
        save()
    print(report['status'], out/'report.json', flush=True)


def verify_build(package):
    package = Path(package).resolve()
    report = load_json(package/'report.json')
    require(report['schema'] == contract.SCHEMA and report['status'] == 'PASS_ASYNC_DDR_NATIVE_BUILD_ONLY'
            and report['scope'] == contract.SCOPE, 'Unsupported/incomplete native build')
    require(report['hardware_accessed'] is False and report['vivado_executed'] is False and
            report['physical_integration_ready'] is False, 'Invalid simulation scope')
    require(set(report['local_source']) == set(LOCAL), 'Source inventory differs')
    for name, digest in report['local_source'].items():
        require(sha(package/'source'/name) == digest, 'Frozen local source differs')
    check_inputs(report['inputs'])
    require(sha(package/'logic-plan.json') == report['logic_plan_sha256'], 'Logical source plan changed')
    require(report['specs'] == expanded_specs(endpoint_vectors.verify_vectors(package/'vectors')), 'Case vectors differ')
    require(sha(package/'obj/sim') == report['binary_sha256'], 'Native image changed')
    require(sha(package/'compile.log') == report['compile']['log_sha256'] and report['compile']['returncode'] == 0,
            'Compiler receipt changed')
    logic=load_json(package/'logic-plan.json')
    sources=[str(package/'source'/n) for n in RTL]+[
        str(package/'source'/n) if n=='tests/ddr/mig_logic_model.sv' else str(ROOT/n)
        for n in logic['compiled_relative']]
    require(sources==report['compiler_sources'],'Changed ordered compiler source inventory')
    definitions=list(logic['definitions'])+['-DRK_DDR_LINE_IMAGE_HEADER='+
        json.dumps(str(package/'source/tests/ddr/endpoint/strict_line_image.svh'))]
    tools=report['tools']
    plan=staged_compile.plans(tools['verilator']['path'],tools['make']['path'],tools['cxx']['path'],
        contract.TOP,package,definitions,sources)
    require(report['compile_plan']==list(plan) and
            report['compile_method']=='Verilator translation exits before ungrouped serial C++ make; shared900s budget',
            'Changed staged compilation recipe')
    phases=[load_json(package/(name+'.json')) for name in ('compile_translation','compile_cpp')]
    require(load_json(package/'compile.json')==report['compile'],'Changed aggregate compile artifact')
    for name,phase in zip(('compile_translation','compile_cpp'),phases):
        require(sha(package/(name+'.log'))==phase['log_sha256'],'Changed compilation phase log')
    require((package/'compile.log').read_text()==(package/'compile_translation.log').read_text()+'\n'+
            (package/'compile_cpp.log').read_text(),'Changed combined compile log')
    staged_compile.verify_record(report['compile'],plan,phases)
    policy = load_json(package/'source/tests/ddr/async_endpoint/warnings.json')
    admitted = contract.check_warnings((package/'compile.log').read_text(), policy,
        report['compiler_sources'], report['tools']['verilator']['version'], package/'source')
    require(admitted == report['admitted_diagnostics'], 'Diagnostic receipt changed')
    return report


def run(args):
    package = args.package.resolve()
    built = verify_build(package)
    selected = contract.selection(built['specs'], args.case)
    out = fresh(args.out)
    inputs = runtime_inputs(package, built)
    # Compilation and execution drivers have distinct recorded identities.
    # Wrapper-only repairs need no HDL recompilation; every live Python/oracle
    # input used by this process is still hash-closed for the whole run.
    execution_inputs = {str(ROOT/n): sha(ROOT/n) for n in LOCAL
                        if n.endswith('.py') or n == 'tests/backend_ew_captures.json'}
    inputs.update(execution_inputs)
    report = dict(schema=contract.SCHEMA, status='RUNNING', scope=contract.SCOPE, started_utc=now(),
                  build=str(package), build_report_sha256=sha(package/'report.json'), inputs=inputs,
                  execution_inputs=execution_inputs,
                  selected=[s['name'] for s in selected], cases=[], hardware_accessed=False,
                  vivado_executed=False, physical_integration_ready=False)
    def save():
        write(out/'report.json', report)
    save()
    try:
        for spec in selected:
            trial = out/spec['name']
            trial.mkdir()
            data = contract.metrics(spec, package/'vectors')
            case = package/'vectors'/spec['case']
            observed = trial/'observed.txt'
            argv = run_plan(package, trial, spec)
            result, log = execute(argv, trial, 'run', runtime_timeout(spec, data), inputs)
            checked = contract.check_result(log, result['returncode'], spec, data, observed, case/'expected.txt')
            item = dict(name=spec['name'], status='PASS', spec=spec, metrics=data, command=result, **checked)
            write(trial/'result.json', item)
            report['cases'].append(item)
            save()
            print('PASS_ASYNC_DDR_CASE', spec['name'], checked['readback_physical_bytes'], flush=True)
        check_inputs(inputs)
        report['status'] = ('PASS_ASYNC_DDR_ALL21_LOGICAL_CASES_ONLY' if len(selected) == contract.CASE_COUNT
                            else 'PASS_ASYNC_DDR_SELECTED_LOGICAL_CASES_ONLY')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = now()
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'report.json'}
        save()
    print(report['status'], out/'report.json', flush=True)


def verify_run(path):
    path = Path(path).resolve()
    report = load_json(path)
    require(report['schema'] == contract.SCHEMA and report['scope'] == contract.SCOPE and
            report['status'] in ('PASS_ASYNC_DDR_ALL21_LOGICAL_CASES_ONLY',
                                 'PASS_ASYNC_DDR_SELECTED_LOGICAL_CASES_ONLY'), 'Incomplete async DDR run')
    require(all(report[k] is False for k in ('hardware_accessed', 'vivado_executed',
                                            'physical_integration_ready')), 'Invalid physical claim')
    package = Path(report['build'])
    built = verify_build(package)
    require(sha(package/'report.json') == report['build_report_sha256'], 'Native build receipt changed')
    inputs = runtime_inputs(package, built)
    execution_inputs = {str(ROOT/n): sha(ROOT/n) for n in LOCAL
                        if n.endswith('.py') or n == 'tests/backend_ew_captures.json'}
    require(execution_inputs == report['execution_inputs'], 'Execution driver/oracle sources changed')
    inputs.update(execution_inputs)
    require(report['inputs'] == inputs, 'Run input inventory differs')
    check_inputs(inputs)
    specs = contract.selection(built['specs'], report['selected'])
    require(bool(report['selected']) and len(report['cases']) == len(specs), 'Missing/extra executed case')
    require((len(specs) == contract.CASE_COUNT) == (report['status'] == 'PASS_ASYNC_DDR_ALL21_LOGICAL_CASES_ONLY'),
            'Subset cannot claim complete coverage')
    directory = path.parent
    artifacts = {str(p.relative_to(directory)): sha(p) for p in directory.rglob('*')
                 if p.is_file() and p.name != 'report.json'}
    require(artifacts == report['artifacts'], 'Run artifacts changed')
    for item, spec in zip(report['cases'], specs):
        trial = directory/spec['name']
        data = contract.metrics(spec, package/'vectors')
        command = load_json(trial/'run.json')
        require(command == item['command'] and command['status'] == 'EXITED' and
                command['argv'] == run_plan(package, trial, spec) and
                command['timeout_seconds'] == runtime_timeout(spec, data) and
                command['log_sha256'] == sha(trial/'run.log'), 'Execution command/log differs')
        checked = contract.check_result((trial/'run.log').read_text(), command['returncode'], spec,
            data, trial/'observed.txt', package/'vectors'/spec['case']/'expected.txt')
        require(item == dict(name=spec['name'], status='PASS', spec=spec, metrics=data,
                             command=command, **checked) == load_json(trial/'result.json'),
                'Result/coverage differs from actual execution')
    return report


def main():
    def interrupted(signum, frame):
        raise InterruptedError('Async endpoint runner interrupted by signal '+str(signum))
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    p = subs.add_parser('build')
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--primitive-library', type=Path, required=True)
    p.add_argument('--cxx')
    p.add_argument('--out', type=Path, required=True)
    p = subs.add_parser('run')
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--case', action='append')
    p.add_argument('--out', type=Path, required=True)
    p = subs.add_parser('verify-build')
    p.add_argument('--package', type=Path, required=True)
    p = subs.add_parser('verify-run')
    p.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'build':
        build(args)
    elif args.action == 'run':
        run(args)
    elif args.action == 'verify-build':
        verify_build(args.package)
        print('VERIFIED_ASYNC_DDR_NATIVE_BUILD_ONLY')
    else:
        verify_run(args.report)
        print('VERIFIED_ASYNC_DDR_EXECUTED_CASES_ONLY')


if __name__ == '__main__':
    main()
