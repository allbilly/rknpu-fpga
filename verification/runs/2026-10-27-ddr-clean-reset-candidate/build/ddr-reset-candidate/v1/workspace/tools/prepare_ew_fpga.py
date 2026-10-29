#!/usr/bin/env python3
"""Freeze and check EW Vivado inputs. This tool NEVER launches Vivado or hardware.

prepare writes a source snapshot, checkpoint Tcl, and an incomplete board review.
verify checks package integrity and reports remaining admission requirements.
command prints a future batch invocation only after matching simulator evidence
and completed board review. Executing that command requires separate authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import ROOT, fingerprint, source_revision, timestamp

PART = 'xc7k480tffg1156-2'
BOARD = 'YPCB_00338_1P1'
TEMPLATE = 'fpga/ew_checkpoint.tcl.in'
COMMON = ['rtl/' + name + '.sv' for name in (
    'rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma', 'rk_bram',
    'rk_demo_memory', 'rk_dma_demo_rom', 'rk_ew_dma_demo')]
PROFILES = {
    'external-r28': {'top': 'ypcb_top', 'constraints': 'fpga/ypcb.xdc',
                     'sources': COMMON + ['fpga/ypcb_top.sv'], 'board_test': 'ypcb',
                     'reset': 'Audited external R28 input; three-edge synchronized release'},
    'startup': {'top': 'ypcb_ew_startup_top', 'constraints': 'fpga/ypcb_ew_startup.xdc',
                'sources': COMMON + ['rtl/rk_startup_reset.sv', 'fpga/ypcb_ew_startup_top.sv'],
                'board_test': 'ypcb_ew_startup',
                'reset': 'Configuration-initialized registered reset: 64 held edges, release on edge65; reconfiguration restarts the image'},
}
BOARD_CHECKS = ('target_identity', 'clock_input', 'led_pins_and_polarity',
                'reset_contract', 'configuration_bank')
BOARD_RESULTS = {
    'alu': [r'PASS ALU: 12963 vectors, [1-9][0-9]* cycles'],
    'dma_demo': [re.escape(s) for s in (
        'PASS DMA board workload: verbatim SUB(9), two tasks, 324 requests, 336 memory checks',
        'PASS DMA demo reset during command fetch and restart',
        'PASS DMA demo reset during data execution and restart',
        'PASS DMA demo initialization bus error', 'PASS DMA demo command bus error',
        'PASS DMA demo completion-count mismatch', 'PASS DMA demo known readback corruption',
        'PASS DMA demo watchdog and fault recovery')],
    'demo_memory': [re.escape('PASS sparse demo BRAM: 80 checked transfers, adjacent requests, dual-port reset')],
    'ypcb': [re.escape('PASS YPCB top: startup, asynchronous reset, synchronized release, both LED polarities')],
    'startup_reset': [re.escape('PASS startup reset: initial hold, exact release, synchronous restart, held and repeated requests')],
    'ypcb_ew_startup': [re.escape('PASS YPCB startup profile: no external reset, 64-cycle hold, raw SUB(9), both LED polarities')],
}
BOARD_TOPS = {'alu': 'tb_fp16', 'dma_demo': 'tb_dma_demo', 'demo_memory': 'tb_demo_memory',
              'ypcb': 'tb_ypcb', 'startup_reset': 'tb_startup_reset', 'ypcb_ew_startup': 'tb_ypcb_ew_startup'}


def board_test_sources(name):
    sources = {'alu': ['rtl/rk_fp16_alu.sv'], 'dma_demo': COMMON,
               'demo_memory': ['rtl/rk_bram.sv', 'rtl/rk_demo_memory.sv'],
               'ypcb': COMMON + ['fpga/ypcb_top.sv'],
               'startup_reset': ['rtl/rk_startup_reset.sv'],
               'ypcb_ew_startup': COMMON + ['rtl/rk_startup_reset.sv', 'fpga/ypcb_ew_startup_top.sv']}[name]
    return sources + ['tests/' + BOARD_TOPS[name] + '.sv']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def tcl_path(path):
    value = str(path)
    require(not any(c in value for c in '{}\\\n\r'), 'Unsupported Tcl path characters')
    return '{' + value + '}'


def render(directory, profile, source_sha):
    require(profile in PROFILES, 'Unknown EW profile')
    require(re.fullmatch('[0-9a-f]{64}', source_sha) is not None, 'Invalid source fingerprint')
    spec = PROFILES[profile]
    snapshot = directory / 'source'
    text = (snapshot / TEMPLATE).read_text()
    replacements = {
        '@ROOT@': tcl_path(snapshot), '@OUT@': tcl_path(directory / 'implementation'),
        '@SOURCE_SHA@': source_sha, '@TOP@': spec['top'],
        '@CONSTRAINTS@': tcl_path(snapshot / spec['constraints']),
        '@READ_SOURCES@': '\n'.join('read_verilog -sv ' + tcl_path(snapshot / name)
                                    for name in spec['sources']),
    }
    for token, value in replacements.items():
        require(text.count(token) == 1, 'Unexpected template token: ' + token)
        text = text.replace(token, value)
    require(re.search(r'@[A-Z_]+@', text) is None, 'Unexpanded Tcl token')
    require(re.search(r'^\s*(write_bitstream|open_hw\w*|program_hw\w*)\b', text, re.M) is None,
            'Preparation template contains image emission or hardware commands')
    return text


def simulation_evidence(report, expected_simulator, revision, profile, artifact_root=None):
    require(report.get('status') == 'PASS' and report.get('finished_utc'), 'Incomplete RTL evidence')
    require(report.get('simulator') == expected_simulator, 'Wrong simulator evidence')
    require(report.get('source_revision', {}).get('sha256') == revision['sha256'] and
            report['source_revision'].get('files') == revision['files'], 'Stale RTL source evidence')
    commands = report.get('commands')
    require(isinstance(commands, list) and commands and all(
        c.get('status') == 'PASS' and type(c.get('returncode')) is int and c['returncode'] == 0
        for c in commands), 'Failed or missing RTL command evidence')
    tests = report.get('tests')
    require(isinstance(tests, list) and tests and all(t.get('status') == 'PASS' for t in tests),
            'Failed or missing RTL tests')
    names = {t.get('name') for t in tests}
    require(len(names) == len(tests), 'Duplicate RTL test evidence')
    required = {'alu', 'dma_demo', 'demo_memory', PROFILES[profile]['board_test']}
    if profile == 'startup':
        required.add('startup_reset')
    require(required <= names, 'Missing selected-profile board/reset tests')
    require(type(report.get('execution_schema')) is int and report['execution_schema'] == 1,
            'Missing executed RTL artifact evidence; rerun the current producer')
    execution_root = Path(report.get('execution_root', ''))
    require(execution_root.is_absolute() and '..' not in execution_root.parts, 'Invalid RTL execution root')
    root = Path(artifact_root) if artifact_root is not None else execution_root
    prefix = 'build/' + ('rtl' if expected_simulator == 'verilator' else 'iverilog') + '/'
    artifact_record = report.get('artifacts', {})
    artifacts = artifact_record.get('files', {})
    require(isinstance(artifacts, dict) and artifacts, 'Missing RTL artifact manifest')
    stimulus_record = report.get('stimuli', {})
    stimuli = stimulus_record.get('files', {})
    require(isinstance(stimuli, dict) and stimuli, 'Missing RTL stimulus manifest')
    stimulus_manifest = ''.join(f'{sha}  {name}\n' for name, sha in sorted(stimuli.items()))
    require(hashlib.sha256(stimulus_manifest.encode()).hexdigest() == stimulus_record.get('sha256') and
            all(name.startswith(('build/vectors/', 'build/dma_vectors/')) and artifacts.get(name) == sha
                for name, sha in stimuli.items()), 'Unbound RTL stimuli')
    manifest = ''.join(f'{sha}  {name}\n' for name, sha in sorted(artifacts.items()))
    require(hashlib.sha256(manifest.encode()).hexdigest() == artifact_record.get('sha256'),
            'Invalid RTL artifact manifest')
    for name, sha in artifacts.items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts and
                (name.startswith(prefix) or name in stimuli),
                'Unsafe RTL artifact path')
        path = root / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
                and digest(path) == sha, 'Missing or changed RTL artifact: ' + name)
    by_name = {c.get('name'): c for c in commands}
    require(None not in by_name and len(by_name) == len(commands), 'Missing or duplicate RTL command names')
    referenced = set(stimuli)
    for name, cmd in by_name.items():
        require(isinstance(name, str) and re.fullmatch('[a-zA-Z0-9_]+', name), 'Invalid RTL command name')
        log = prefix + name + '.log'
        require(cmd.get('log') == log and cmd.get('log_sha256') == artifacts.get(log),
                'Unbound RTL command log: ' + name)
        require(isinstance(cmd.get('argv'), list) and cmd['argv'] and
                all(isinstance(a, str) for a in cmd['argv']), 'Missing RTL command argv')
        referenced.add(log)
        if 'output' in cmd:
            image = cmd['output']
            require(image.get('build_command') == name and image.get('sha256') == artifacts.get(image.get('path')),
                    'Unbound compiled RTL executable')
            referenced.add(image['path'])
    version = by_name.get('version', {})
    expected_version_prefix = 'Verilator ' if expected_simulator == 'verilator' else 'Icarus Verilog version '
    require(isinstance(report.get('tool_version'), str) and report['tool_version'].startswith(expected_version_prefix)
            and version.get('argv', [None])[-1] == ('--version' if expected_simulator == 'verilator' else '-V'),
            'Missing or incorrect simulator version evidence')
    version_lines = (root / version['log']).read_text().splitlines()
    require(version_lines and version_lines[0] == report['tool_version'],
            'Simulator version does not match its log')
    compiler = version['argv'][0]
    require(Path(compiler).name == expected_simulator, 'Incorrect simulator version command')
    if expected_simulator == 'iverilog':
        runtime = report.get('runtime', {})
        runtime_version = by_name.get('runtime_version', {})
        runtime_lines = (root / runtime_version['log']).read_text().splitlines() if runtime_version else []
        require(isinstance(runtime.get('path'), str) and Path(runtime['path']).is_absolute() and
                re.fullmatch('[0-9a-f]{64}', runtime.get('sha256', '')) and
                runtime_version.get('argv') == [runtime['path'], '-V'] and
                isinstance(report.get('runtime_version'), str) and
                report['runtime_version'].startswith('Icarus Verilog runtime version ') and
                runtime_lines and runtime_lines[0] == report['runtime_version'],
                'Missing or incorrect Icarus runtime evidence')
    for test in tests:
        name = test['name']
        execution = test.get('execution', {})
        cmd = by_name.get(execution.get('command'), {})
        image = execution.get('path')
        require(execution.get('command') == name and cmd and image in artifacts and
                execution.get('sha256') == artifacts[image], 'Unbound RTL test execution: ' + name)
        build = by_name.get(execution.get('build_command'), {})
        require(build.get('output') == {k: execution[k] for k in ('path', 'sha256', 'build_command')},
                'RTL test does not match its compiled executable: ' + name)
        binary = str(execution_root / image)
        expected_argv = [binary] if expected_simulator == 'verilator' else [report['runtime']['path'], binary]
        require(cmd['argv'][:len(expected_argv)] == expected_argv and
                all(a.startswith('+') for a in cmd['argv'][len(expected_argv):]),
                'RTL test argv does not execute the bound binary: ' + name)
        actual = [line for line in (root / cmd['log']).read_text().splitlines() if line.startswith('PASS ')]
        require(actual and actual == test.get('results'), 'Missing or changed RTL PASS results: ' + name)
        if name not in required:
            continue
        patterns = BOARD_RESULTS[name].copy()
        if name == 'dma_demo' and expected_simulator == 'iverilog':
            patterns.insert(-1, re.escape('PASS DMA demo unknown readback corruption'))
        require(len(actual) == len(patterns) and all(re.fullmatch(pattern, line)
                for pattern, line in zip(patterns, actual)), 'Incorrect selected board/reset results: ' + name)
        top = BOARD_TOPS[name]
        expected_image = prefix + ('obj_' + top + '/sim' if expected_simulator == 'verilator' else top + '.vvp')
        require(image == expected_image and execution['build_command'] == top + '_build',
                'Incorrect selected board/reset executable: ' + name)
        if name == 'alu':
            require(cmd['argv'][len(expected_argv):] ==
                    [f'+VECTORS={execution_root}/build/vectors/alu.hex', '+COUNT=12963'] and
                    'build/vectors/alu.hex' in stimuli, 'Incorrect ALU stimulus binding')
        else:
            require(cmd['argv'] == expected_argv, 'Unexpected selected board/reset runtime arguments')
        if expected_simulator == 'verilator':
            expected_build = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                              '--top-module', top, '--Mdir', str(execution_root / prefix / ('obj_' + top)), '-o', 'sim']
        else:
            expected_build = [compiler, '-g2012', '-Wall', '-s', top, '-o', binary]
        expected_build += [str(execution_root / source) for source in board_test_sources(name)]
        require(build['argv'] == expected_build, 'Incorrect selected board/reset compilation: ' + name)
    require(referenced == set(artifacts), 'Unexpected or missing RTL artifact inventory')
    return {name: root / name for name in artifacts}


def prepare(profile, out=None, reports=None):
    require(profile in PROFILES, 'Unknown EW profile')
    reports = reports or {}
    require(not reports or set(reports) == {'verilator', 'iverilog'}, 'Supply both simulator reports')
    revision = source_revision()
    spec = PROFILES[profile]
    # The production manifest covers the RTL, generators, fixtures and runners.
    # Keep the extra build template in its own explicitly bound input group.
    files = dict(revision['files'])
    files[TEMPLATE] = digest(ROOT / TEMPLATE)
    for name in spec['sources'] + [spec['constraints']]:
        require(name in files, 'Source manifest omitted ' + name)
    evidence = {}
    for simulator, path in reports.items():
        record = read_json(path)
        artifacts = simulation_evidence(record, simulator, revision, profile)
        evidence[simulator] = (record, artifacts)
    directory = (Path(out) if out is not None else ROOT / 'build' / 'ew-fpga-preparation' /
                 (profile + '-' + str(time.time_ns()))).resolve()
    require(directory.is_relative_to(ROOT / 'build') and directory != ROOT / 'build',
            'Output must be a fresh directory below build/')
    require(not directory.exists(), 'Output already exists; preserve earlier evidence')
    # Validate path rendering before creating any output.
    tcl_path(directory)
    directory.mkdir(parents=True)
    record = dict(schema=1, status='PREPARING', profile=profile, board=BOARD, part=PART,
                  clock_hz=50_000_000, reset_contract=spec['reset'], started_utc=timestamp(),
                  production_revision=revision, snapshot_files=files,
                  simulation_reports={}, vivado_executed=False, implementation_completed=False,
                  bitstream_emitted=False, hardware_programmed=False)
    try:
        for name, sha in files.items():
            source = ROOT / name
            require(source.is_file() and not source.is_symlink() and digest(source) == sha,
                    'Source changed or is a symlink: ' + name)
            target = directory / 'source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            require(digest(target) == sha, 'Snapshot copy mismatch: ' + name)
        for simulator, (report, artifacts) in evidence.items():
            path = directory / 'evidence' / (simulator + '.json')
            path.parent.mkdir(exist_ok=True)
            write_json(path, report)
            record['simulation_reports'][simulator] = digest(path)
            artifact_root = directory / 'evidence' / simulator / 'artifacts'
            for name, source in artifacts.items():
                target = artifact_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            simulation_evidence(report, simulator, revision, profile, artifact_root)
        record['hardware_inputs'] = fingerprint([ROOT / n for n in spec['sources'] + [spec['constraints']]])
        record['build_inputs'] = fingerprint([ROOT / TEMPLATE, Path(__file__).resolve()])
        script = directory / 'build.tcl'
        script.write_text(render(directory, profile, revision['sha256']))
        record['build_tcl_sha256'] = digest(script)
        write_json(directory / 'board-review.json', dict(
            schema=1, profile=profile, source_sha256=revision['sha256'], board=BOARD, part=PART,
            reviewer='', checks={key: False for key in BOARD_CHECKS},
            evidence={key: '' for key in BOARD_CHECKS},
            config_voltage=None, cfgbvs=None, led_active_low=None))
        require(source_revision()['sha256'] == revision['sha256'] and
                all(digest(ROOT / n) == sha for n, sha in files.items()), 'Inputs changed during preparation')
        record.update(status='PREPARED_EW_CHECKPOINT_ONLY', simulation_bound=bool(evidence),
                      remaining=['Complete the exact board review',
                                 'Supply both current simulator reports' if not evidence else
                                 'Simulator source binding checked; physical validation remains pending',
                                 'Obtain separate authorization before any Vivado build',
                                 'Validate tool licensing/device support and review actual implementation',
                                 'Image emission and SRAM/flash programming are separate actions'])
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        record['finished_utc'] = timestamp()
        write_json(directory / 'report.json', record)
    return directory


def validate_board_review(review, record):
    require(type(review.get('schema')) is int and review['schema'] == 1, 'Unknown board-review schema')
    require(set(review) == {'schema', 'profile', 'source_sha256', 'board', 'part',
                            'reviewer', 'checks', 'evidence', 'config_voltage', 'cfgbvs',
                            'led_active_low'}, 'Unknown or missing board-review fields')
    for key in ('profile', 'board', 'part'):
        require(review.get(key) == record[key], 'Wrong board review ' + key)
    require(review.get('source_sha256') == record['production_revision']['sha256'], 'Stale board review')
    require(isinstance(review.get('reviewer'), str) and review['reviewer'].strip(), 'Missing board reviewer')
    require(set(review.get('checks', {})) == set(BOARD_CHECKS) and all(
        review['checks'][key] is True for key in BOARD_CHECKS), 'Incomplete board checks')
    require(set(review.get('evidence', {})) == set(BOARD_CHECKS) and all(
        isinstance(review['evidence'][key], str) and review['evidence'][key].strip()
        for key in BOARD_CHECKS), 'Missing board evidence references')
    require(type(review.get('led_active_low')) is int and review['led_active_low'] in (0, 1),
            'LED polarity must be an explicit 0 or 1')
    require((review.get('config_voltage'), review.get('cfgbvs')) in
            {('1.5', 'GND'), ('1.8', 'GND'), ('2.5', 'VCCO'), ('3.3', 'VCCO')},
            'Invalid board electrical pair')


def verify(directory, require_ready=False):
    directory = Path(directory).resolve()
    record = read_json(directory / 'report.json')
    require(type(record.get('schema')) is int and record['schema'] == 1 and
            record.get('status') == 'PREPARED_EW_CHECKPOINT_ONLY',
            'Incomplete or unsupported preparation')
    require(record.get('profile') in PROFILES and record.get('board') == BOARD and
            record.get('part') == PART and record.get('clock_hz') == 50_000_000, 'Changed hardware profile')
    revision = record['production_revision']
    manifest = ''.join(f'{sha}  {name}\n' for name, sha in sorted(revision['files'].items()))
    require(hashlib.sha256(manifest.encode()).hexdigest() == revision['sha256'],
            'Invalid production source manifest')
    spec = PROFILES[record['profile']]
    require(set(spec['sources'] + [spec['constraints'], 'tools/run_rtl.py',
                                  'tests/tb_' + spec['board_test'] + '.sv']) <= set(revision['files']),
            'Production manifest omitted selected profile inputs')
    for name, sha in record['snapshot_files'].items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe snapshot path')
        path = directory / 'source' / relative
        require(path.is_file() and path.resolve().is_relative_to(directory / 'source') and
                not path.is_symlink() and digest(path) == sha, 'Changed snapshot: ' + name)
    required = set(record['production_revision']['files']) | {TEMPLATE}
    require(set(record['snapshot_files']) == required, 'Incomplete snapshot inventory')
    require(all(record['snapshot_files'][n] == h for n, h in record['production_revision']['files'].items()),
            'Snapshot does not match simulation source inventory')
    # A changed validator must not silently reinterpret an earlier package.
    for name in ('tools/prepare_ew_fpga.py', TEMPLATE):
        require(digest(ROOT / name) == record['snapshot_files'][name], 'Preparation tool/template changed')
    script = directory / 'build.tcl'
    require(not script.is_symlink() and digest(script) == record['build_tcl_sha256'] and
            script.read_text() == render(directory, record['profile'], record['production_revision']['sha256']),
            'Changed generated Tcl or moved package')
    blockers = []
    for name in spec['sources'] + [spec['constraints']]:
        live = ROOT / name
        if not live.is_file() or digest(live) != record['snapshot_files'][name]:
            blockers.append('Selected hardware source changed; prepare again: ' + name)
    bound = record.get('simulation_reports', {})
    require(not bound or set(bound) == {'iverilog', 'verilator'}, 'Incomplete simulator evidence inventory')
    for simulator, sha in bound.items():
        path = directory / 'evidence' / (simulator + '.json')
        require(path.is_file() and not path.is_symlink() and digest(path) == sha, 'Changed simulator evidence')
        simulation_evidence(read_json(path), simulator, record['production_revision'], record['profile'],
                            directory / 'evidence' / simulator / 'artifacts')
    if not bound:
        blockers.append('Both matching simulator reports are required')
    try:
        validate_board_review(read_json(directory / 'board-review.json'), record)
    except (ValueError, KeyError, TypeError, FileNotFoundError) as error:
        blockers.append(str(error))
    if require_ready:
        require(not blockers, '; '.join(blockers))
    return dict(status='SOURCE_INTACT_REVIEW_PENDING' if blockers else 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD',
                profile=record['profile'], blockers=blockers, vivado_executed=False,
                scope='Package integrity and recorded evidence only; no physical or license validation')


def command(directory):
    result = verify(directory, require_ready=True)
    directory = Path(directory).resolve()
    require(not (directory / 'implementation').exists(), 'Implementation output already exists; prepare a fresh package')
    record = read_json(directory / 'report.json')
    review = read_json(directory / 'board-review.json')
    result['argv'] = ['vivado', '-mode', 'batch', '-source', str(directory / 'build.tcl'),
                      '-log', str(directory / 'vivado.log'), '-journal', str(directory / 'vivado.jou')]
    result['environment'] = dict(RK_EW_PREPARED_SHA=record['production_revision']['sha256'],
        RK_CONFIRM_BOARD=BOARD, RK_CONFIG_VOLTAGE=review['config_voltage'],
        RK_CFGBVS=review['cfgbvs'], RK_LED_ACTIVE_LOW=str(review['led_active_low']), RK_EMIT_BITSTREAM='0')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('prepare')
    make.add_argument('--profile', choices=tuple(PROFILES), required=True)
    make.add_argument('--out', type=Path)
    make.add_argument('--verilator-report', type=Path)
    make.add_argument('--iverilog-report', type=Path)
    for action in ('verify', 'command'):
        sub.add_parser(action).add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            reports = {name: value for name in ('verilator', 'iverilog')
                       if (value := getattr(args, name + '_report')) is not None}
            directory = prepare(args.profile, args.out, reports)
            print(directory / 'report.json')
            print(json.dumps(verify(directory), indent=2))
        else:
            print(json.dumps((verify if args.action == 'verify' else command)(args.directory), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
