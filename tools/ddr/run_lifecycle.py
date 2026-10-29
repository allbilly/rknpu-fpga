#!/usr/bin/env python3
"""Qualify owned reset and fence protocol components; no hardware execution."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import canonical, load_json, require
from tools.ddr.run_monitor import (ENVIRONMENT, diagnostics, digest, fingerprint,
                                   manifest, relative, tool_identity, version_plan)
from tools.evidence import timestamp

COMMON = ('tools/ddr/run_lifecycle.py', 'tools/ddr/run_monitor.py',
          'tools/ddr/interface.py', 'tools/ddr/__init__.py', 'tools/evidence.py',
          'fpga/ddr/lifecycle.mk', 'fpga/ddr/xdma_archive_reference.json',
          'tests/ddr/lifecycle/test_runner.py')
SPEC = {
    'reset': dict(top='tb_mig_reset_coordinator', rtl='rk_mig_reset_coordinator',
        contract='fpga/ddr/xdma_lifecycle_contract.json', counts={'iverilog':32, 'verilator':23},
        result='PASS mig_reset_coordinator cases={count} sys_hold=64 ui_fresh=4 sync=3 scope=owned_reset_sequence_model_only',
        fatal='Reset coordinator requires positive counts and at least two synchronizer stages',
        invalid=('DUT_SYS_HOLD_CYCLES', 'DUT_UI_FRESH_CYCLES', 'DUT_SYNC_STAGES', 'DUT_WAIT_TIMEOUT_CYCLES')),
    'fence': dict(top='tb_mig_write_fence', rtl='rk_mig_write_fence',
        contract='fpga/ddr/xdma_retirement_contract.json', counts={'iverilog':71, 'verilator':54},
        result='PASS mig_write_fence cases={count} scope=independent_fence_protocol_only controller_ordering_unqualified',
        fatal='Fence timeout must be positive', invalid=('DUT_TIMEOUT_CYCLES',)),
}
SCOPE = ('Owned SYS/UI0/UI1 reset and fence protocol simulation only; '
         'controller ordering, joined-platform coverage, initialization and physical DDR require separate evidence')
FLAGS = ('vivado_executed', 'vendor_ip_generated', 'hardware_accessed',
         'physical_integration_ready', 'memory_retirement_verified', 'joined_platform_verified')


def sources(profiles):
    names = set(COMMON)
    for name in profiles:
        spec = SPEC[name]
        names.update((f"rtl/ddr/{spec['rtl']}.sv", f"tests/ddr/{spec['top']}.sv", spec['contract']))
    return sorted(names)


def cases(profiles):
    result = []
    for profile in profiles:
        result.append((profile, profile, None, None))
        for parameter in SPEC[profile]['invalid']:
            result.append((profile+'-'+parameter+'-zero', profile, parameter, 0))
        if profile == 'reset':
            result.append(('reset-DUT_SYNC_STAGES-one', profile, 'DUT_SYNC_STAGES', 1))
    return result


def plans(simulator, profiles, producer, output, tools):
    base = Path(producer); directory = base/relative(output)
    result = []
    for label, profile, parameter, value in cases(profiles):
        spec = SPEC[profile]; top = spec['top']
        inputs = [str(base/f"rtl/ddr/{spec['rtl']}.sv"), str(base/f'tests/ddr/{top}.sv')]
        if simulator == 'iverilog':
            image = str(relative(output)/(label+'.vvp'))
            override = ['-P'+top+'.'+parameter+'='+str(value)] if parameter else []
            build = [tools['simulator']['path'], '-g2012', '-Wall', '-s', top, *override,
                     '-o', str(base/image), *inputs]
            run = [tools['runtime']['path'], str(base/image)]
        else:
            image = str(relative(output)/label/'sim')
            override = ['-G'+parameter+'='+str(value)] if parameter else []
            build = [tools['simulator']['path'], '--binary', '--timing', '--assert', '-Wall',
                     '--top-module', top, *override, '-j', '2', '-MAKEFLAGS',
                     'CXX='+shlex.quote(tools['cxx']['path']), '--Mdir', str(directory/label),
                     '-o', 'sim', *inputs]
            run = [str(base/image)]
        result.append(dict(name=label, profile=profile, parameter=parameter, value=value,
            build=build, run=run, image=image, rejected=parameter is not None,
            expected=spec['fatal'] if parameter else spec['result'].format(count=spec['counts'][simulator])))
    return result


def check_result(text, plan, returncode, simulator):
    if plan['rejected']:
        require(returncode != 0 and plan['expected'] in text, 'Missing specific parameter rejection')
        require(('Time: 0' in text) if simulator == 'iverilog' else re.search(r'(?m)^\[0\]', text),
                'Parameter rejection did not occur at time zero')
    else:
        require(returncode == 0 and [x for x in text.splitlines() if x.startswith('PASS ')] == [plan['expected']]
                and not re.search(r'(?m)^(?:FATAL:|ERROR:|FAIL|%Error)', text), 'Wrong protocol result')


def verify_report(path):
    report = load_json(path)
    require(report['status'] == 'PASS_DDR_LIFECYCLE_PROTOCOLS_ONLY' and report['execution_schema'] == 1
            and type(report['execution_schema']) is int and report['scope'] == SCOPE, 'Unsupported protocol receipt')
    require(all(report[key] is False for key in FLAGS), 'Protocol receipt cannot claim hardware/integration')
    profiles = report['profiles']; simulator = report['simulator']; tools = report['tools']
    require(profiles in (['reset'], ['fence'], ['reset', 'fence']) and simulator in ('iverilog', 'verilator'),
            'Unknown protocol profile')
    require(set(tools) == ({'simulator', 'runtime'} if simulator == 'iverilog' else {'simulator', 'cxx'}),
            'Tool-role inventory changed')
    for role, item in tools.items():
        basename = simulator if role == 'simulator' else 'vvp' if role == 'runtime' else 'c++'
        require(set(item) == {'path', 'sha256'} and Path(item['path']).is_absolute() and
                Path(item['path']).name == basename and
                re.fullmatch('[0-9a-f]{64}', item['sha256']), 'Invalid tool identity')
    require(Path(report['execution_root']).is_absolute(), 'Missing absolute original execution root')
    expected_source = fingerprint([ROOT/p for p in sources(profiles)])
    require(report['source'] == report['execution_inputs'] == expected_source, 'Protocol source changed')
    versions = version_plan(simulator, tools)
    scheduled = plans(simulator, profiles, report['execution_root'], report['output_directory'], tools)
    expected = [(name, argv, role, None, False) for name, argv, role in versions]
    expected += [(p['name']+'-'+stage, p[stage], 'simulator' if stage == 'build' else
                  ('runtime' if simulator == 'iverilog' else None), p, stage == 'run')
                 for p in scheduled for stage in ('build', 'run')]
    require([x['name'] for x in report['commands']] == [x[0] for x in expected], 'Command inventory changed')
    artifact_files = {}; tests = []
    for entry, (name, argv, role, plan, running) in zip(report['commands'], expected):
        require(entry['argv'] == argv and entry['environment'] == ENVIRONMENT, 'Command/environment changed')
        log_name = str(relative(report['output_directory'])/(name+'.log'))
        require(entry['log'] == log_name and digest(ROOT/log_name) == entry['log_sha256'], 'Command log changed')
        artifact_files[log_name] = entry['log_sha256']
        identity = tools[role] if role else dict(path=str(Path(report['execution_root'])/plan['image']),
                                               sha256=report['artifacts']['files'][plan['image']])
        require(entry['executable_before'] == entry['executable_after'] == identity, 'Executable binding changed')
        require(entry['tools_before'] == entry['tools_after'] == tools, 'Toolchain identity changed')
        require(entry['inputs_before'] == entry['inputs_after'] == expected_source, 'Command inputs changed')
        text = (ROOT/log_name).read_text()
        if plan is None:
            field = {'simulator':'tool_version', 'runtime':'runtime_version', 'cxx':'cxx_version'}[role]
            require(entry['returncode'] == 0 and text.splitlines()[0] == report[field], 'Version/log link changed')
        elif not running:
            require(entry['returncode'] == 0 and diagnostics(text, simulator) == [], 'Build/warnings failed')
            image = plan['image']; image_sha = digest(ROOT/relative(image))
            require(entry['output_image'] == dict(path=image, sha256=image_sha), 'Build output image changed')
            artifact_files[image] = image_sha
        else:
            image = plan['image']; image_sha = digest(ROOT/relative(image))
            require(entry['image'] == image and entry['image_before'] == entry['image_after'] == image_sha,
                    'Run image changed')
            check_result(text, plan, entry['returncode'], simulator)
            tests.append(dict(name=plan['name'], outcome='EXPECTED_REJECTION' if plan['rejected'] else 'PASS',
                              result=plan['expected'], image=image, image_sha256=image_sha))
    require(report['tests'] == tests and report['artifacts'] == manifest(artifact_files), 'Result/artifact inventory changed')
    require(fingerprint([ROOT/p for p in artifact_files]) == report['artifacts'], 'Execution artifact changed')
    return dict(status='VERIFIED_DDR_LIFECYCLE_PROTOCOLS_ONLY', profiles=profiles,
                simulator=simulator, tests=len(tests), memory_retirement_verified=False)


def no_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), default='verilator')
    parser.add_argument('--profile', choices=('reset', 'fence', 'all'), default='all')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        require(args.out is None, 'Verification does not execute a new test')
        print(json.dumps(verify_report(args.verify), indent=2)); return 0
    profiles = ['reset', 'fence'] if args.profile == 'all' else [args.profile]
    out = (args.out or ROOT/'build/ddr-lifecycle'/f'{args.simulator}-{time.time_ns()}').resolve()
    require(out.is_relative_to(ROOT) and not out.exists(), 'Fresh in-workspace output required')
    out.mkdir(parents=True); source = fingerprint([ROOT/p for p in sources(profiles)])
    report = dict(status='RUNNING', execution_schema=1, scope=SCOPE, started_utc=timestamp(),
        execution_root=str(ROOT), output_directory=str(out.relative_to(ROOT)), profiles=profiles,
        simulator=args.simulator, source=source, execution_inputs=source, tools={}, commands=[], tests=[],
        stimulus='Directed; no bench PRNG', **{name:False for name in FLAGS})
    report_path = out/'report.json'; artifacts = set()
    def save():report_path.write_text(json.dumps(report, indent=2)+'\n')
    def execute(name, argv, role, plan=None, running=False):
        require(fingerprint([ROOT/p for p in sources(profiles)]) == source, 'Inputs changed before command')
        tools_before={key:tool_identity(item['path']) for key,item in report['tools'].items()}
        require(tools_before == report['tools'], 'Toolchain changed before command')
        identity = report['tools'][role] if role else tool_identity(argv[0])
        require(tool_identity(argv[0]) == identity, 'Command executable differs')
        entry = dict(name=name, argv=argv, environment=ENVIRONMENT, executable_before=identity,
                     tools_before=tools_before, inputs_before=source, log=str((out/(name+'.log')).relative_to(ROOT)))
        if running:entry.update(image=plan['image'], image_before=digest(ROOT/plan['image']))
        report['commands'].append(entry); save(); begin=time.monotonic()
        try:
            with (ROOT/entry['log']).open('w') as log:
                result=subprocess.run(argv, cwd=ROOT, env=dict(os.environ, **ENVIRONMENT),
                    stdout=log, stderr=subprocess.STDOUT, timeout=300, preexec_fn=no_core)
            entry.update(returncode=result.returncode, executable_after=tool_identity(argv[0]),
                         inputs_after=fingerprint([ROOT/p for p in sources(profiles)]),
                         tools_after={key:tool_identity(item['path']) for key,item in report['tools'].items()})
            require(entry['executable_after'] == identity and entry['inputs_after'] == source, 'Command inputs/tool changed')
            require(entry['tools_after'] == report['tools'], 'Toolchain changed during command')
            text=(ROOT/entry['log']).read_text()
            if running:
                entry['image_after']=digest(ROOT/plan['image'])
                require(entry['image_before'] == entry['image_after'], 'Run image changed')
                check_result(text, plan, result.returncode, args.simulator)
            else:
                require(result.returncode == 0, 'Build/version command failed: '+name)
                if plan:
                    require(diagnostics(text, args.simulator) == [], 'Unexpected compiler warning')
                    entry['output_image']=dict(path=plan['image'], sha256=digest(ROOT/plan['image']))
            return text
        finally:
            entry['seconds']=round(time.monotonic()-begin,3)
            path=ROOT/entry['log']
            if path.exists():entry['log_sha256']=digest(path);artifacts.add(path)
            save()
    save()
    try:
        roles={'simulator':args.simulator, **({'runtime':'vvp'} if args.simulator=='iverilog' else {'cxx':'c++'})}
        for role, name in roles.items():
            tool=shutil.which(name);require(tool is not None,'UNAVAILABLE: '+name)
            report['tools'][role]=tool_identity(tool)
        for name, argv, role in version_plan(args.simulator, report['tools']):
            field={'simulator':'tool_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
            report[field]=execute(name,argv,role).splitlines()[0]
        scheduled=plans(args.simulator,profiles,ROOT,str(out.relative_to(ROOT)),report['tools'])
        for plan in scheduled:
            execute(plan['name']+'-build',plan['build'],'simulator',plan)
            artifacts.add(ROOT/plan['image'])
            execute(plan['name']+'-run',plan['run'],'runtime' if args.simulator=='iverilog' else None,plan,True)
            report['tests'].append(dict(name=plan['name'], outcome='EXPECTED_REJECTION' if plan['rejected'] else 'PASS',
                result=plan['expected'], image=plan['image'], image_sha256=digest(ROOT/plan['image'])))
        report.update(status='PASS_DDR_LIFECYCLE_PROTOCOLS_ONLY',finished_utc=timestamp(),artifacts=fingerprint(artifacts))
        save();verify_report(report_path);print(report_path);return 0
    except BaseException as error:
        report.update(status='UNAVAILABLE' if 'UNAVAILABLE:' in str(error) else 'FAIL',
                      error=repr(error), finished_utc=timestamp(), artifacts=fingerprint(artifacts));save();raise


if __name__ == '__main__':raise SystemExit(main())
