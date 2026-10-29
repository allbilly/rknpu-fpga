#!/usr/bin/env python3
"""Run the DDR fabric's independent protocol model and full-default-span sink.

No controller/PHY, real ECC encoding or physical memory contents are qualified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import load_json, require
from tools.ddr.run_monitor import (ENVIRONMENT, diagnostics, digest, fingerprint,
                                   manifest, relative, tool_identity, version_plan)
from tools.evidence import timestamp

LOCAL = ('tools/ddr/run_fabric.py', 'tools/ddr/run_monitor.py', 'tools/ddr/interface.py',
         'tools/ddr/__init__.py', 'tools/evidence.py', 'fpga/ddr/fabric.mk',
         'fpga/ddr/xdma_retirement_contract.json', 'fpga/ddr/xdma_lifecycle_contract.json',
         'rtl/rk_axi_mem.sv', 'rtl/ddr/rk_mig_write_fence.sv', 'rtl/ddr/rk_ddr_memory_fabric.sv',
         'tests/ddr/tb_ddr_memory_fabric.sv', 'tests/ddr/fabric/test_runner.py')
INPUTS = ('rtl/rk_axi_mem.sv', 'rtl/ddr/rk_mig_write_fence.sv',
          'rtl/ddr/rk_ddr_memory_fabric.sv', 'tests/ddr/tb_ddr_memory_fabric.sv')
SCOPE = ('Owned C0 fabric protocol and optional default 2-GiB zero-write stream sink only; '
         'no actual MC/PHY, ECC encoding, DDR contents, global platform or physical proof')
FLAGS = ('vivado_executed', 'vendor_ip_generated', 'hardware_accessed',
         'controller_phy_simulated', 'ddr_contents_verified', 'physical_integration_ready',
         'memory_retirement_verified', 'joined_platform_verified')
FABRIC_ERROR = 'DDR fabric needs aligned nonempty C0 span and positive timeout'
FENCE_ERROR = 'Fence timeout must be positive'
TOP = 'tb_ddr_memory_fabric'
FULL_RESULT = ('PASS ddr_memory_fabric default_span_bytes=2147483648 lines=33554432 '
               'last=7fffffc0 full_strobes=1 init_fences=1 no_DDR_contents_or_physical_proof')


def source_revision():
    return fingerprint([ROOT/p for p in LOCAL])


def cases(simulator, mode):
    require(simulator in ('iverilog', 'verilator') and mode in ('portable', 'full-span'), 'Unknown fabric profile')
    if mode == 'full-span':
        require(simulator == 'verilator', 'Full-span qualification requires Verilator')
        return [dict(name='full-span', overrides={'FULL_SPAN':1}, rejected=False, expected=FULL_RESULT)]
    result = [dict(name='portable', overrides={}, rejected=False,
        expected=f"PASS ddr_memory_fabric cases={21 if simulator == 'iverilog' else 19} window_bytes=256 scope=independent_owned_fabric_only")]
    for name, overrides in (
        ('zero-bytes', {'DUT_BYTES':0}), ('short-span', {'DUT_BYTES':32}),
        ('unaligned-base', {'DUT_BASE':1}),
        ('span-overflow', {'DUT_BASE':2147483584, 'DUT_BYTES':128}),
        ('channel-one-base', {'DUT_BASE':2147483648}),
        ('zero-timeout', {'DUT_TIMEOUT_CYCLES':0}),
    ):
        result.append(dict(name=name, overrides=overrides, rejected=True,
                           expected=[FABRIC_ERROR, FENCE_ERROR] if name == 'zero-timeout' else [FABRIC_ERROR]))
    return result


def plans(simulator, mode, producer, output, tools):
    base = Path(producer)
    directory = base/relative(output)
    result = []
    for case in cases(simulator, mode):
        name = case['name']
        inputs = [str(base/p) for p in INPUTS]
        # Match the declared parameter widths, including the 33-bit byte span.
        # Untyped nonzero -G literals otherwise cause a real width diagnostic
        # before the intended time-zero invalid-span assertion can execute.
        values = {key:(str(value) if key == 'FULL_SPAN' else
                       str(33 if key == 'DUT_BYTES' else 32)+"'d"+str(value))
                  for key,value in case['overrides'].items()}
        if simulator == 'iverilog':
            image = str(relative(output)/(name+'.vvp'))
            overrides = ['-P'+TOP+'.'+key+'='+value for key, value in values.items()]
            build = [tools['simulator']['path'], '-g2012', '-Wall', '-s', TOP, *overrides,
                     '-o', str(base/image), *inputs]
            run = [tools['runtime']['path'], str(base/image)]
        else:
            image = str(relative(output)/name/'sim')
            overrides = ['-G'+key+'='+value for key, value in values.items()]
            build = [tools['simulator']['path'], '--binary', '--timing', '--assert', '-Wall',
                     '--top-module', TOP, *overrides, '-j', '2', '-MAKEFLAGS',
                     'CXX='+shlex.quote(tools['cxx']['path']), '--Mdir', str(directory/name),
                     '-o', 'sim', *inputs]
            run = [str(base/image)]
        result.append(case | dict(build=build, run=run, image=image))
    return result


def check_result(text, plan, code, simulator):
    require(type(code) is int, 'Process return code must be an integer')
    if plan['rejected']:
        require(code != 0 and any(reason in text for reason in plan['expected']), 'Missing specific invalid-parameter rejection')
        require(('Time: 0' in text) if simulator == 'iverilog' else re.search(r'(?m)^\[0\]', text),
                'Invalid parameter did not reject at time zero')
        return 'EXPECTED_TIME_ZERO_REJECTION'
    require(code == 0 and [s for s in text.splitlines() if s.startswith('PASS ')] == [plan['expected']] and
            not re.search(r'(?m)^(?:FATAL:|ERROR:|FAIL|%Error)', text), 'Fabric model result differs')
    progress = []
    for line in text.splitlines():
        if line.startswith('PROGRESS'):
            match = re.fullmatch(r'PROGRESS default_c0_init_lines=([0-9]+)', line)
            require(match is not None, 'Unrecognized stream progress record')
            progress.append(int(match[1]))
    if plan['name'] == 'full-span':
        require(progress == list(range(1048576, 33554433, 1048576)), 'Full-span progress/write inventory changed')
    else:
        require(not progress, 'Portable case cannot claim a full-span stream')
    return plan['expected']


def verify_report(path):
    report = load_json(path)
    require(report['status'] == 'PASS_DDR_FABRIC_MODEL_ONLY' and type(report['execution_schema']) is int
            and report['execution_schema'] == 1 and report['scope'] == SCOPE, 'Unsupported fabric receipt')
    require(all(report[key] is False for key in FLAGS), 'Fabric model cannot claim actual DDR or hardware')
    simulator, mode, tools = report['simulator'], report['mode'], report['tools']
    require(set(tools) == ({'simulator', 'runtime'} if simulator == 'iverilog' else {'simulator', 'cxx'}),
            'Tool-role inventory differs')
    for role, identity in tools.items():
        basename = simulator if role == 'simulator' else 'vvp' if role == 'runtime' else 'c++'
        require(set(identity) == {'path', 'sha256'} and Path(identity['path']).is_absolute() and
                Path(identity['path']).name == basename and re.fullmatch('[0-9a-f]{64}', identity['sha256']),
                'Tool role/identity differs')
    producer = Path(report['execution_root'])
    require(producer.is_absolute(), 'Original producer root must be absolute')
    source = source_revision()
    require(report['source'] == report['execution_inputs'] == source, 'Fabric source/input inventory changed')
    scheduled = plans(simulator, mode, producer, report['output_directory'], tools)
    versions = version_plan(simulator, tools)
    expected = [(name, argv, role, None, False) for name, argv, role in versions]
    expected += [(p['name']+'-'+stage, p[stage], 'simulator' if stage == 'build' else
                  ('runtime' if simulator == 'iverilog' else None), p, stage == 'run')
                 for p in scheduled for stage in ('build', 'run')]
    require([c['name'] for c in report['commands']] == [v[0] for v in expected], 'Command inventory/order differs')
    artifacts = {}; tests = []
    for entry, (name, argv, role, plan, running) in zip(report['commands'], expected):
        require(entry['status'] == 'PASS', 'Incomplete command status')
        require(entry['argv'] == argv and entry['environment'] == ENVIRONMENT, 'Execution command/environment differs')
        log = str(relative(report['output_directory'])/(name+'.log'))
        require(entry['log'] == log and digest(ROOT/log) == entry['log_sha256'], 'Execution log changed')
        artifacts[log] = entry['log_sha256']
        identity = tools[role] if role else dict(path=str(producer/plan['image']),
                                               sha256=digest(ROOT/relative(plan['image'])))
        require(entry['executable_before'] == entry['executable_after'] == identity, 'Tool/execution image differs')
        require(entry['tools_before'] == entry['tools_after'] == tools, 'Toolchain changed during execution')
        require(entry['inputs_before'] == entry['inputs_after'] == source, 'Inputs changed during execution')
        text = (ROOT/log).read_text()
        if plan is None:
            field = {'simulator':'tool_version', 'runtime':'runtime_version', 'cxx':'cxx_version'}[role]
            require(type(entry['returncode']) is int and entry['returncode'] == 0 and
                    text.splitlines() and text.splitlines()[0] == report[field], 'Version/log binding differs')
        elif not running:
            require(type(entry['returncode']) is int and entry['returncode'] == 0 and diagnostics(text, simulator) == [],
                    'Compiler failed or emitted unadmitted diagnostics')
            image = plan['image']; image_hash = digest(ROOT/relative(image))
            require(entry['output_image'] == dict(path=image, sha256=image_hash), 'Compiled image changed')
            artifacts[image] = image_hash
        else:
            image = plan['image']; image_hash = digest(ROOT/relative(image))
            require(entry['image'] == image and entry['image_before'] == entry['image_after'] == image_hash,
                    'Executed image changed')
            result = check_result(text, plan, entry['returncode'], simulator)
            tests.append(dict(name=plan['name'], outcome='EXPECTED_REJECTION' if plan['rejected'] else 'PASS',
                              result=result, image=image, image_sha256=image_hash))
    require(report['tests'] == tests and report['artifacts'] == manifest(artifacts), 'Results/artifact inventory differs')
    require(fingerprint([ROOT/p for p in artifacts]) == report['artifacts'], 'Artifact bytes changed')
    return dict(status='VERIFIED_DDR_FABRIC_MODEL_ONLY', simulator=simulator, mode=mode,
                tests=len(tests), ddr_contents_verified=False)


def no_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), default='verilator')
    parser.add_argument('--mode', choices=('portable', 'full-span'), default='portable')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        require(args.out is None, 'Verification does not launch another model')
        print(json.dumps(verify_report(args.verify), indent=2))
        return 0
    cases(args.simulator, args.mode)
    out = (args.out or ROOT/'build/ddr-fabric'/f'{args.simulator}-{args.mode}-{time.time_ns()}').resolve()
    require(out.is_relative_to(ROOT) and not out.exists(), 'Fresh in-workspace output required')
    out.mkdir(parents=True)
    source = source_revision()
    report = dict(status='RUNNING', execution_schema=1, scope=SCOPE, started_utc=timestamp(),
        execution_root=str(ROOT), output_directory=str(out.relative_to(ROOT)), simulator=args.simulator,
        mode=args.mode, source=source, execution_inputs=source, tools={}, commands=[], tests=[],
        stimulus='Directed; full-span sink has no 2-GiB backing RAM', **{key:False for key in FLAGS})
    path = out/'report.json'; artifacts = set()
    def save():path.write_text(json.dumps(report, indent=2)+'\n')
    def execute(name, argv, role, plan=None, running=False):
        require(source_revision() == source, 'Source changed before command')
        before = {key:tool_identity(value['path']) for key, value in report['tools'].items()}
        require(before == report['tools'], 'Toolchain changed before execution')
        identity = report['tools'][role] if role else tool_identity(argv[0])
        require(tool_identity(argv[0]) == identity, 'Wrong command executable')
        entry = dict(name=name, argv=argv, environment=ENVIRONMENT, executable_before=identity,
                     tools_before=before, inputs_before=source, status='RUNNING',
                     log=str((out/(name+'.log')).relative_to(ROOT)))
        if running:entry.update(image=plan['image'], image_before=digest(ROOT/plan['image']))
        report['commands'].append(entry);save();begin=time.monotonic();process=None
        try:
            with (ROOT/entry['log']).open('w') as log:
                process=subprocess.Popen(argv, cwd=ROOT, env=dict(os.environ, **ENVIRONMENT),
                    stdout=log, stderr=subprocess.STDOUT, preexec_fn=no_core, start_new_session=True)
                entry['pid']=process.pid;save()
                result=process.wait(timeout=300)
            entry.update(returncode=result, executable_after=tool_identity(argv[0]),
                         tools_after={key:tool_identity(value['path']) for key,value in report['tools'].items()},
                         inputs_after=source_revision(), status='PASS' if result==0 or (running and plan['rejected']) else 'FAIL')
            require(entry['executable_after'] == identity and entry['tools_after'] == report['tools'] and
                    entry['inputs_after'] == source, 'Tool or source changed during command')
            text=(ROOT/entry['log']).read_text()
            if running:
                entry['image_after']=digest(ROOT/plan['image'])
                require(entry['image_before'] == entry['image_after'], 'Run image changed')
                result_text=check_result(text, plan, result, args.simulator)
            else:
                require(result==0, 'Build/version command failed')
                if plan:
                    require(diagnostics(text,args.simulator)==[], 'Unexpected compiler diagnostic')
                    entry['output_image']=dict(path=plan['image'],sha256=digest(ROOT/plan['image']))
                result_text=''
            return text,result_text
        except subprocess.TimeoutExpired:
            entry['status']='TIMEOUT'
            if process is not None and process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
            raise
        finally:
            entry['seconds']=round(time.monotonic()-begin,3)
            log=ROOT/entry['log']
            if log.exists():entry['log_sha256']=digest(log);artifacts.add(log)
            save()
    save()
    try:
        roles={'simulator':args.simulator, **({'runtime':'vvp'} if args.simulator=='iverilog' else {'cxx':'c++'})}
        for role,name in roles.items():
            executable=shutil.which(name);require(executable is not None,'UNAVAILABLE: '+name)
            report['tools'][role]=tool_identity(executable)
        for name,argv,role in version_plan(args.simulator,report['tools']):
            field={'simulator':'tool_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
            text,_=execute(name,argv,role);report[field]=text.splitlines()[0]
        for plan in plans(args.simulator,args.mode,ROOT,str(out.relative_to(ROOT)),report['tools']):
            execute(plan['name']+'-build',plan['build'],'simulator',plan)
            artifacts.add(ROOT/plan['image'])
            _,result_text=execute(plan['name']+'-run',plan['run'],'runtime' if args.simulator=='iverilog' else None,plan,True)
            report['tests'].append(dict(name=plan['name'],outcome='EXPECTED_REJECTION' if plan['rejected'] else 'PASS',
                result=result_text,image=plan['image'],image_sha256=digest(ROOT/plan['image'])))
        report.update(status='PASS_DDR_FABRIC_MODEL_ONLY',finished_utc=timestamp(),artifacts=fingerprint(artifacts))
        save();verify_report(path);print(path);return 0
    except BaseException as error:
        report.update(status='TIMEOUT' if isinstance(error,subprocess.TimeoutExpired) else
                      'UNAVAILABLE' if 'UNAVAILABLE:' in str(error) else 'FAIL',
                      error=repr(error),finished_utc=timestamp(),artifacts=fingerprint(artifacts));save();raise


if __name__ == '__main__':raise SystemExit(main())
