#!/usr/bin/env python3
"""Run and verify public capacity-parent controls; no hardware access."""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = (
    'rtl/ddr/capacity/rk_jtag_dual_ddr_async.sv',
    'rtl/ddr/capacity/rk_ddr_memory_fabric_snapshot_capacity.sv',
    'rtl/ddr/capacity/rk_axil_diagnostic_router.sv',
    'rtl/ddr/capacity/rk_ddr_capacity_owner.sv',
    'rtl/ddr/capacity/rk_ddr_capacity_regs.sv',
    'rtl/ddr/capacity/rk_ddr_diagnostic_mux.sv',
    'rtl/ddr/capacity/rk_ddr_capacity_service.sv',
    'rtl/ddr/capacity/rk_job_control_admission.sv',
    'rtl/ddr/capacity/rk_dual_job_control_admission.sv',
    'tools/ddr/capacity_client.py',
)
BASELINE = (
    'rtl/ddr/rk_jtag_dual_ddr_async.sv',
    'rtl/ddr/rk_ddr_memory_fabric_snapshot.sv',
)
HELPERS = (
    'rtl/ddr/rk_ddr_capacity_pattern.sv',
    'rtl/ddr/rk_ddr_capacity_sweep.sv',
    'rtl/ddr/rk_ddr_capacity_axi.sv',
    'rtl/ddr/rk_ddr_capacity_bist.sv',
    'rtl/ddr/rk_mig_write_fence.sv',
    'rtl/ddr/rk_mig_ecc_monitor.sv',
    'rtl/ddr/rk_dual_job_control.sv',
    'rtl/rk_job_control.sv',
)
TESTS = (
    'tests/ddr/capacity_parent/tb_ddr_capacity_service.sv',
    'tests/ddr/capacity_parent/tb_axil_diagnostic_router.sv',
    'tests/ddr/capacity_parent/tb_capacity_parent_controls.sv',
    'tests/ddr/capacity_parent/test_capacity_client.py',
    'tests/ddr/capacity_parent/test_capacity_wire.py',
    'tests/ddr/capacity_parent/test_raw_case_wire.py',
    'tests/ddr/capacity_parent/tb_job_control_equivalence.sv',
    'tests/ddr/capacity_parent/tb_dual_job_control_equivalence.sv',
)
SERVICE_RTL = (
    'rtl/ddr/capacity/rk_ddr_capacity_service.sv',
    'rtl/ddr/capacity/rk_ddr_capacity_owner.sv',
    'rtl/ddr/capacity/rk_ddr_capacity_regs.sv',
    'rtl/ddr/capacity/rk_ddr_diagnostic_mux.sv',
    'rtl/ddr/rk_ddr_capacity_pattern.sv',
    'rtl/ddr/rk_ddr_capacity_sweep.sv',
    'rtl/ddr/rk_ddr_capacity_axi.sv',
    'rtl/ddr/rk_mig_write_fence.sv',
    'rtl/ddr/rk_mig_ecc_monitor.sv',
    'rtl/ddr/rk_ddr_capacity_bist.sv',
)
PROFILES = (('base0_256', 0, 256), ('base1000_512', 4096, 512))
NATIVE_SUITES = (
    ('router_v7_public', 'tb_axil_diagnostic_router',
     ('rtl/ddr/capacity/rk_axil_diagnostic_router.sv', TESTS[1]),
     {'iverilog': 'PASS_AXIL_DIAGNOSTIC_ROUTER transactions=73 full_address_decode=PASS',
      'verilator': 'PASS_AXIL_DIAGNOSTIC_ROUTER transactions=73 full_address_decode=PASS'}),
    ('actual_parent_controls', 'tb_capacity_parent_controls',
     ('rtl/ddr/capacity/rk_axil_diagnostic_router.sv', 'rtl/ddr/capacity/rk_dual_job_control_admission.sv',
      'rtl/ddr/capacity/rk_job_control_admission.sv', 'rtl/ddr/capacity/rk_ddr_capacity_regs.sv', TESTS[2]),
     {'iverilog': 'PASS_CAPACITY_PARENT_CONTROLS reads=22 writes=13 actual_normal_banks=EW+CMAC RKMT=public_decoder scopes=control_only',
      'verilator': 'PASS_CAPACITY_PARENT_CONTROLS reads=22 writes=13 actual_normal_banks=EW+CMAC RKMT=public_decoder scopes=control_only'}),
    ('single_admission_equivalence', 'tb_job_control_equivalence',
     ('rtl/rk_job_control.sv', 'rtl/ddr/capacity/rk_job_control_admission.sv', TESTS[6]),
     {'iverilog': 'PASS_JOB_CONTROL_CYCLE_EQUIVALENCE four_state=1',
      'verilator': 'PASS_JOB_CONTROL_CYCLE_EQUIVALENCE four_state=0'}),
    ('dual_admission_equivalence', 'tb_dual_job_control_equivalence',
     ('rtl/rk_job_control.sv', 'rtl/ddr/rk_dual_job_control.sv',
      'rtl/ddr/capacity/rk_job_control_admission.sv', 'rtl/ddr/capacity/rk_dual_job_control_admission.sv', TESTS[7]),
     {'iverilog': 'PASS_DUAL_JOB_CONTROL_CYCLE_EQUIVALENCE',
      'verilator': 'PASS_DUAL_JOB_CONTROL_CYCLE_EQUIVALENCE'}),
)
TIMEOUT = 300
SCOPE = ('Public capacity-client fake-owner controls, modeled service/router profiles, and actual EW/CMAC AXI-Lite control banks. '
         'No physical DDR, full-capacity, CDC, routing, board, or hardware qualification.')


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(ROOT))


def local_module_paths(module: str) -> set[str]:
    parts = module.split('.')
    found: set[str] = set()
    for count in range(1, len(parts) + 1):
        init = ROOT.joinpath(*parts[:count], '__init__.py')
        if init.is_file():
            found.add(rel(init))
    module_file = ROOT.joinpath(*parts).with_suffix('.py')
    if module_file.is_file():
        found.add(rel(module_file))
    return found


def python_import_closure(seeds: tuple[str, ...]) -> set[str]:
    pending = list(seeds)
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        path = ROOT / current
        if not path.is_file():
            raise FileNotFoundError(current)
        seen.add(current)
        tree = ast.parse(path.read_text(), filename=current)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.append(node.module)
                modules.extend(f'{node.module}.{alias.name}' for alias in node.names if alias.name != '*')
        for module in modules:
            if module == 'tools' or module.startswith('tools.'):
                pending.extend(local_module_paths(module) - seen)
    return seen


def source_paths() -> list[str]:
    direct = {
        'Makefile', 'tools/ddr/run_capacity_parent.py', *PUBLISHED, *BASELINE, *HELPERS, *TESTS,
        *(source for _suite, _top, sources, _markers in NATIVE_SUITES for source in sources),
    }
    imported = python_import_closure((
        'tools/ddr/run_capacity_parent.py',
        'tests/ddr/capacity_parent/test_capacity_client.py',
        'tests/ddr/capacity_parent/test_capacity_wire.py',
        'tests/ddr/capacity_parent/test_raw_case_wire.py',
    ))
    paths = sorted(direct | imported)
    missing = [path for path in paths if not (ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError('missing source inputs: ' + ', '.join(missing))
    return paths


def fingerprint(paths: list[str]) -> dict[str, str]:
    return {path: sha(ROOT / path) for path in paths}


def run_command(output: Path, name: str, argv: list[str]) -> dict:
    stdout = output / 'results' / f'{name}.stdout.log'
    stderr = output / 'results' / f'{name}.stderr.log'
    started = utc()
    clock = time.monotonic()
    with stdout.open('xb') as out, stderr.open('xb') as err:
        process = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=err, start_new_session=True)
        try:
            returncode = process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            except ProcessLookupError:
                process.wait()
            returncode = 124
    return {
        'name': name, 'argv': argv, 'cwd': str(ROOT), 'started_utc': started, 'finished_utc': utc(),
        'returncode': returncode, 'timed_out': returncode == 124, 'timeout_seconds': TIMEOUT,
        'wall_seconds': round(time.monotonic() - clock, 6),
        'stdout_path': rel(stdout), 'stdout_sha256': sha(stdout), 'stdout_bytes': stdout.stat().st_size,
        'stderr_path': rel(stderr), 'stderr_sha256': sha(stderr), 'stderr_bytes': stderr.stat().st_size,
    }


def command_text(command: dict) -> tuple[str, str]:
    return ((ROOT / command['stdout_path']).read_text(errors='replace'),
            (ROOT / command['stderr_path']).read_text(errors='replace'))


def known_icarus_diagnostics(kind: str) -> list[str]:
    result: list[str] = []
    if kind == 'service':
        result.append("rtl/ddr/rk_ddr_capacity_pattern.sv:13: sorry: constant selects in always_* processes are not fully supported (the process will be sensitive to all bits in 'address[30:0]').")
    if kind in ('service', 'parent'):
        for line, signal in ((73, 'saved_awaddr[31:0]'), (86, 's_axil_araddr[31:0]'),
                             (105, 's_axil_araddr[31:0]'), (107, 's_axil_araddr[31:0]')):
            result.append(f"rtl/ddr/capacity/rk_ddr_capacity_regs.sv:{line}: sorry: constant selects in always_* processes are not fully supported (the process will be sensitive to all bits in '{signal}').")
    if kind == 'service':
        for line in (220, 234, 257, 274, 292):
            result.append(f'tests/ddr/capacity_parent/tb_ddr_capacity_service.sv:{line}: warning: System task ($fatal) cannot be synthesized in an always_ff process.')
    return result


def normalize_log_lines(text: str) -> list[str]:
    prefix = str(ROOT) + '/'
    return [line.replace(prefix, '') for line in text.splitlines() if line]


def check_compile_diagnostics(name: str, simulator: str, stderr: str) -> list[str]:
    diagnostics = normalize_log_lines(stderr)
    if simulator == 'verilator':
        if diagnostics:
            raise RuntimeError(f'strict Verilator compile emitted diagnostics in {name}: {diagnostics!r}')
        return []
    if 'service_' in name:
        expected = known_icarus_diagnostics('service')
    elif 'actual_parent_controls' in name:
        expected = known_icarus_diagnostics('parent')
    else:
        expected = []
    if diagnostics != expected:
        raise RuntimeError(f'Icarus diagnostic inventory changed in {name}: {diagnostics!r}')
    return diagnostics


def expected_service_marker(base: int, span: int) -> str:
    lines = span // 64
    return (f'PASS capacity_service base={base:08x} span={span:08x} lines={lines} '
            f'diagnostic_writes={2 * lines} diagnostic_reads={2 * lines} fences=4')


def marker_lines(text: str, prefix: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(prefix)]


def expected_results() -> list[dict]:
    results = [
        {'name': 'public_capacity_client_mock_tests', 'status': 'PASS', 'tests': 12,
         'hardware_accessed': False, 'socket_calls': 0, 'device_calls': 0},
        {'name': 'capacity_wire_audit_tests', 'status': 'PASS', 'tests': 12,
         'hardware_accessed': False, 'socket_calls': 0, 'device_calls': 0},
        {'name': 'raw_case_wire_audit_tests', 'status': 'PASS', 'tests': 16,
         'hardware_accessed': False, 'socket_calls': 0, 'device_calls': 0},
    ]
    for simulator in ('iverilog', 'verilator'):
        for profile, base, span in PROFILES:
            results.append({'name': f'{simulator}_service_{profile}', 'status': 'PASS', 'base': base,
                            'span': span, 'marker': expected_service_marker(base, span)})
    for simulator in ('iverilog', 'verilator'):
        for suite_name, _top, _sources, markers in NATIVE_SUITES:
            results.append({'name': f'{simulator}_{suite_name}', 'status': 'PASS', 'marker': markers[simulator]})
    return results


def command_plan(output: Path, tools: dict[str, dict], python_executable: str) -> list[tuple[str, list[str], str | None, str | None]]:
    plan: list[tuple[str, list[str], str | None, str | None]] = []
    for key, flag in (('iverilog', '-V'), ('vvp', '-V'), ('verilator', '--version'), ('cxx', '--version')):
        plan.append((f'version_{key}', [tools[key]['path'], flag], None, None))
    plan.append(('version_python', [python_executable, '--version'], None, None))
    plan.append(('capacity_client_mock_tests', [python_executable, str(ROOT / TESTS[3]), '-v'], None, None))
    plan.append(('capacity_wire_audit_tests', [python_executable, '-m', 'unittest', 'discover', '-s',
                 str(ROOT / 'tests/ddr/capacity_parent'), '-p', 'test_capacity_wire.py', '-v'], None, None))
    plan.append(('raw_case_wire_audit_tests', [python_executable, '-m', 'unittest', 'discover', '-s',
                 str(ROOT / 'tests/ddr/capacity_parent'), '-p', 'test_raw_case_wire.py', '-v'], None, None))
    service_sources = [str(ROOT / source) for source in SERVICE_RTL] + [str(ROOT / TESTS[0])]
    for simulator in ('iverilog', 'verilator'):
        for profile, base, span in PROFILES:
            label = f'{simulator}_service_{profile}'
            if simulator == 'iverilog':
                image = output / 'results' / f'{label}.vvp'
                build = [tools['iverilog']['path'], '-g2012', '-Wall', '-s', 'tb_ddr_capacity_service',
                         f'-Ptb_ddr_capacity_service.TB_BASE={base}', f'-Ptb_ddr_capacity_service.TB_SPAN={span}',
                         '-o', str(image), *service_sources]
                execute = [tools['vvp']['path'], str(image)]
            else:
                mdir = output / 'results' / f'{label}-obj'
                build = [tools['verilator']['path'], '--binary', '--timing', '--assert', '--Wall',
                         '--top-module', 'tb_ddr_capacity_service', '--build-jobs', '2', '-MAKEFLAGS',
                         'CXX=' + shlex.quote(tools['cxx']['path']), '--Mdir', str(mdir),
                         f"-GTB_BASE=31'd{base}", f"-GTB_SPAN=32'd{span}", *service_sources]
                execute = [str(mdir / 'Vtb_ddr_capacity_service')]
            plan.extend([(label + '_compile', build, simulator, 'service'),
                         (label + '_simulation', execute, simulator, 'service')])
    for simulator in ('iverilog', 'verilator'):
        for suffix, top, source_names, markers in NATIVE_SUITES:
            label = f'{simulator}_{suffix}'
            marker = markers[simulator]
            sources = [str(ROOT / source) for source in source_names]
            if simulator == 'iverilog':
                image = output / 'results' / f'{label}.vvp'
                build = [tools['iverilog']['path'], '-g2012', '-Wall', '-s', top, '-o', str(image), *sources]
                execute = [tools['vvp']['path'], str(image)]
            else:
                mdir = output / 'results' / f'{label}-obj'
                build = [tools['verilator']['path'], '--binary', '--timing', '--assert', '--Wall',
                         '--top-module', top, '--build-jobs', '2', '-MAKEFLAGS',
                         'CXX=' + shlex.quote(tools['cxx']['path']), '--Mdir', str(mdir), *sources]
                execute = [str(mdir / ('V' + top))]
            plan.extend([(label + '_compile', build, simulator, suffix),
                         (label + '_simulation', execute, simulator, marker)])
    return plan


def verify_report(report_path: Path) -> dict:
    report_path = report_path.resolve()
    report = json.loads(report_path.read_text())
    if report.get('schema') != 'capacity-parent-controls-v2' or report.get('status') != 'PASS_PUBLIC_CAPACITY_PARENT_AND_CLIENT_CONTROLS_ONLY':
        raise RuntimeError('unsupported or failed capacity-parent report')
    if report.get('runner_returncode') != 0 or report.get('hardware_accessed') is not False or report.get('socket_calls') != 0 or report.get('device_calls') != 0 or report.get('flash_written') is not False:
        raise RuntimeError('report indicates failure or outside-scope activity')
    for claim in ('vivado_executed', 'physical_capacity_qualified', 'full_capacity_qualified'):
        if report.get(claim, False) is not False:
            raise RuntimeError(f'out-of-scope claim set: {claim}')
    if report.get('execution_root') != str(ROOT):
        raise RuntimeError('report was created by a different source workspace')
    before = report.get('source_hashes_before')
    after = report.get('source_hashes_after')
    if not isinstance(before, dict) or before != after or fingerprint(sorted(before)) != before:
        raise RuntimeError('source/import closure differs from before/after/current hashes')
    if report.get('baseline_parent_sources') != {path: before[path] for path in BASELINE}:
        raise RuntimeError('baseline-parent source inventory changed')
    if report.get('published_profile_sources') != {path: before[path] for path in PUBLISHED}:
        raise RuntimeError('published capacity-profile source inventory changed')
    if report.get('runner_sha256') != before.get('tools/ddr/run_capacity_parent.py'):
        raise RuntimeError('runner source hash differs from frozen input')
    tools = report.get('tools')
    if not isinstance(tools, dict) or set(tools) != {'iverilog', 'vvp', 'verilator', 'cxx', 'python'}:
        raise RuntimeError('tool-role inventory changed')
    for role, item in tools.items():
        if set(item) != {'path', 'sha256', 'version'} or sha(Path(item['path'])) != item['sha256']:
            raise RuntimeError(f'tool identity changed: {role}')
    output = ROOT / report['output_directory']
    plan = command_plan(output, tools, report['python_executable'])
    commands = report.get('commands')
    if not isinstance(commands, list) or len(commands) != len(plan):
        raise RuntimeError('native command count changed')
    for command, (name, argv, simulator, kind) in zip(commands, plan):
        if command.get('name') != name or command.get('argv') != argv or command.get('cwd') != str(ROOT) or command.get('returncode') != 0 or command.get('timed_out') is not False:
            raise RuntimeError(f'native command/exit status changed: {name}')
        stdout_path = ROOT / command['stdout_path']
        stderr_path = ROOT / command['stderr_path']
        for path, sha_key, bytes_key in ((stdout_path, 'stdout_sha256', 'stdout_bytes'), (stderr_path, 'stderr_sha256', 'stderr_bytes')):
            if not path.is_file() or sha(path) != command[sha_key] or path.stat().st_size != command[bytes_key]:
                raise RuntimeError(f'command log changed: {path}')
        stdout, stderr = stdout_path.read_text(errors='replace'), stderr_path.read_text(errors='replace')
        if name.startswith('version_'):
            role = name.removeprefix('version_')
            combined = stdout + '\n' + stderr
            first = next((line.strip() for line in combined.splitlines() if line.strip()), '')
            if first != tools[role]['version']:
                raise RuntimeError(f'tool-version log mismatch: {role}')
        elif name in ('capacity_client_mock_tests', 'capacity_wire_audit_tests', 'raw_case_wire_audit_tests'):
            combined = stdout + '\n' + stderr
            expected_count = {'capacity_client_mock_tests': 12, 'capacity_wire_audit_tests': 12, 'raw_case_wire_audit_tests': 16}[name]
            if f'Ran {expected_count} tests' not in combined or '\nOK\n' not in combined or 'FAILED' in combined:
                raise RuntimeError(f'Python mock footer/count/status mismatch: {name}')
        elif name.endswith('_compile'):
            diagnostics = check_compile_diagnostics(name, simulator or '', stderr)
            if diagnostics != command.get('known_diagnostics', []):
                raise RuntimeError(f'known Icarus/Verilator diagnostic list changed: {name}')
        elif name.endswith('_simulation'):
            marker = (expected_service_marker(next(base for profile, base, _ in PROFILES if profile in name),
                                              next(span for profile, _, span in PROFILES if profile in name))
                      if kind == 'service' else kind)
            if marker_lines(stdout + '\n' + stderr, marker.split(' ')[0]) != [marker]:
                raise RuntimeError(f'exact PASS marker/footer mismatch: {name}')
            if any(line.startswith(('FATAL:', 'ERROR:', 'FAIL', '%Error')) for line in (stdout + '\n' + stderr).splitlines()):
                raise RuntimeError(f'failure marker in simulation log: {name}')
    if report.get('results') != expected_results():
        raise RuntimeError('final result inventory/counts differ')
    artifacts = report.get('artifacts')
    if not isinstance(artifacts, list):
        raise RuntimeError('compiled output inventory missing')
    # Use the exact executed command order rather than a second nested loop
    # which can disagree with the producer's service/router/parent ordering.
    expected_artifact_paths = [rel(Path(argv[1] if simulator == 'iverilog' else argv[0]))
                               for name, argv, simulator, _ in plan
                               if name.endswith('_simulation')]
    if [artifact.get('path') for artifact in artifacts] != expected_artifact_paths:
        raise RuntimeError('compiled-image artifact inventory/order differs from expected commands')
    for artifact in artifacts:
        path = ROOT / artifact['path']
        if not path.is_file() or path.stat().st_size != artifact['bytes'] or sha(path) != artifact['sha256']:
            raise RuntimeError(f'compiled simulator artifact changed: {path}')
    return {'status': 'VERIFIED_PUBLIC_CAPACITY_PARENT_CONTROLS_ONLY', 'commands': len(commands),
            'results': len(report['results']), 'source_inputs': len(before), 'compiled_artifacts': len(artifacts),
            'hardware_accessed': False, 'flash_written': False}


def make_report(output: Path, before: dict[str, str], tools: dict[str, dict]) -> dict:
    current = Path('/proc/meminfo').read_text()
    return {
        'schema': 'capacity-parent-controls-v2', 'status': 'RUNNING', 'started_utc': utc(),
        'finished_utc': None, 'runner_returncode': None, 'execution_root': str(ROOT),
        'output_directory': rel(output), 'runner_sha256': before['tools/ddr/run_capacity_parent.py'],
        'python_executable': tools['python']['path'], 'source_hashes_before': before, 'source_hashes_after': None,
        'published_profile_sources': {path: before[path] for path in PUBLISHED},
        'baseline_parent_sources': {path: before[path] for path in BASELINE},
        'tools': tools, 'versions': {key: value['version'] for key, value in tools.items()},
        'commands': [], 'results': [], 'artifacts': [], 'timeout_per_command_seconds': TIMEOUT,
        'host_admission': {
            'MemAvailable_kib': int(next(line.split()[1] for line in current.splitlines() if line.startswith('MemAvailable:'))),
            'memory_pressure': Path('/proc/pressure/memory').read_text(), 'cpu_pressure': Path('/proc/pressure/cpu').read_text(),
            'cgroup': next((line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')), 'unknown'),
            'requested_limits': {'MemoryMax': '6G', 'MemorySwapMax': '0', 'CPUQuota': '200%', 'TasksMax': 256},
        },
        'hardware_accessed': False, 'socket_calls': 0, 'device_calls': 0, 'flash_written': False,
        'scope': SCOPE,
    }


def run_report(output: Path) -> tuple[dict, int]:
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise RuntimeError('fresh output directory inside source workspace required')
    output.mkdir(parents=True)
    (output / 'results').mkdir()
    before = fingerprint(source_paths())
    tool_names = {'iverilog': 'iverilog', 'vvp': 'vvp', 'verilator': 'verilator', 'cxx': 'c++', 'python': sys.executable}
    tools: dict[str, dict[str, str]] = {}
    for role, name in tool_names.items():
        found = name if role == 'python' else shutil.which(name)
        if not found:
            raise RuntimeError('UNAVAILABLE: required tool ' + name)
        # Preserve ccache's argv0 symlink spelling (for example c++) so it
        # invokes the compiler rather than interpreting compiler flags itself.
        executable = str(Path(found).resolve()) if role == 'python' else str(Path(found))
        tools[role] = {'path': executable, 'sha256': sha(Path(executable)), 'version': ''}
    report = make_report(output, before, tools)
    report_path = output / 'report.json'
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def save() -> None:
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def execute(name: str, argv: list[str], marker: str | None = None, simulator: str | None = None) -> tuple[str, dict]:
        command = run_command(output, name, argv)
        report['commands'].append(command)
        stdout, stderr = command_text(command)
        if command['returncode'] != 0:
            save()
            raise RuntimeError(f'{name} failed with exit {command["returncode"]}; see command logs')
        if name.endswith('_compile'):
            command['known_diagnostics'] = check_compile_diagnostics(name, simulator or '', stderr)
        text = stdout + '\n' + stderr
        if marker and marker not in text:
            save()
            raise RuntimeError(f'{name} missing required completion marker {marker!r}')
        save()
        return text, command

    try:
        for role, flag in (('iverilog', '-V'), ('vvp', '-V'), ('verilator', '--version'), ('cxx', '--version'), ('python', '--version')):
            text, _ = execute('version_' + role, [tools[role]['path'], flag])
            first = next((line.strip() for line in text.splitlines() if line.strip()), '')
            if not first:
                raise RuntimeError(f'empty tool-version output for {role}')
            tools[role]['version'] = first
        report['versions'] = {key: value['version'] for key, value in tools.items()}
        save()

        python_controls = (
            ('capacity_client_mock_tests', [tools['python']['path'], str(ROOT / TESTS[3]), '-v'],
             'public_capacity_client_mock_tests', 12),
            ('capacity_wire_audit_tests', [tools['python']['path'], '-m', 'unittest', 'discover', '-s',
             str(ROOT / 'tests/ddr/capacity_parent'), '-p', 'test_capacity_wire.py', '-v'],
             'capacity_wire_audit_tests', 12),
            ('raw_case_wire_audit_tests', [tools['python']['path'], '-m', 'unittest', 'discover', '-s',
             str(ROOT / 'tests/ddr/capacity_parent'), '-p', 'test_raw_case_wire.py', '-v'],
             'raw_case_wire_audit_tests', 16),
        )
        for command_name, argv, result_name, expected_tests in python_controls:
            text, _ = execute(command_name, argv)
            if f'Ran {expected_tests} tests' not in text or '\nOK\n' not in text or 'FAILED' in text:
                raise RuntimeError(f'{result_name} requires exactly {expected_tests} passing offline tests')
            report['results'].append({'name': result_name, 'status': 'PASS', 'tests': expected_tests,
                                      'hardware_accessed': False, 'socket_calls': 0, 'device_calls': 0})

        service_sources = [str(ROOT / source) for source in SERVICE_RTL] + [str(ROOT / TESTS[0])]
        for simulator in ('iverilog', 'verilator'):
            for profile, base, span in PROFILES:
                label = f'{simulator}_service_{profile}'
                if simulator == 'iverilog':
                    image = output / 'results' / f'{label}.vvp'
                    build = [tools['iverilog']['path'], '-g2012', '-Wall', '-s', 'tb_ddr_capacity_service',
                             f'-Ptb_ddr_capacity_service.TB_BASE={base}', f'-Ptb_ddr_capacity_service.TB_SPAN={span}',
                             '-o', str(image), *service_sources]
                    execute_argv = [tools['vvp']['path'], str(image)]
                else:
                    objects = output / 'results' / f'{label}-obj'
                    build = [tools['verilator']['path'], '--binary', '--timing', '--assert', '--Wall',
                             '--top-module', 'tb_ddr_capacity_service', '--build-jobs', '2', '-MAKEFLAGS',
                             'CXX=' + shlex.quote(tools['cxx']['path']), '--Mdir', str(objects),
                             f"-GTB_BASE=31'd{base}", f"-GTB_SPAN=32'd{span}", *service_sources]
                    execute_argv = [str(objects / 'Vtb_ddr_capacity_service')]
                execute(label + '_compile', build, simulator=simulator)
                image_path = image if simulator == 'iverilog' else objects / 'Vtb_ddr_capacity_service'
                report['artifacts'].append({'path': rel(image_path), 'sha256': sha(image_path), 'bytes': image_path.stat().st_size})
                text, _ = execute(label + '_simulation', execute_argv, 'PASS capacity_service')
                expected = expected_service_marker(base, span)
                if marker_lines(text, 'PASS capacity_service') != [expected]:
                    raise RuntimeError(f'{label} exact marker/count mismatch')
                report['results'].append({'name': label, 'status': 'PASS', 'base': base, 'span': span, 'marker': expected})

        for simulator in ('iverilog', 'verilator'):
            for suffix, top, source_names, markers in NATIVE_SUITES:
                label = f'{simulator}_{suffix}'
                marker = markers[simulator]
                sources = [str(ROOT / source) for source in source_names]
                if simulator == 'iverilog':
                    image = output / 'results' / f'{label}.vvp'
                    build = [tools['iverilog']['path'], '-g2012', '-Wall', '-s', top, '-o', str(image), *sources]
                    execute_argv = [tools['vvp']['path'], str(image)]
                    image_path = image
                else:
                    objects = output / 'results' / f'{label}-obj'
                    build = [tools['verilator']['path'], '--binary', '--timing', '--assert', '--Wall',
                             '--top-module', top, '--build-jobs', '2', '-MAKEFLAGS',
                             'CXX=' + shlex.quote(tools['cxx']['path']), '--Mdir', str(objects), *sources]
                    execute_argv = [str(objects / ('V' + top))]
                    image_path = objects / ('V' + top)
                execute(label + '_compile', build, simulator=simulator)
                report['artifacts'].append({'path': rel(image_path), 'sha256': sha(image_path), 'bytes': image_path.stat().st_size})
                text, _ = execute(label + '_simulation', execute_argv, marker)
                if marker_lines(text, marker.split(' ')[0]) != [marker]:
                    raise RuntimeError(f'{label} exact marker/count mismatch')
                report['results'].append({'name': label, 'status': 'PASS', 'marker': marker})

        after = fingerprint(source_paths())
        if after != before:
            raise RuntimeError('source/import dependency closure changed during run')
        report['source_hashes_after'] = after
        report['published_sources_unchanged'] = {path: after[path] for path in PUBLISHED} == {path: before[path] for path in PUBLISHED}
        if not report['published_sources_unchanged']:
            raise RuntimeError('published capacity-profile files changed during test')
        if report['results'] != expected_results():
            raise RuntimeError('final results/counts differ from expected inventory')
        report['status'] = 'PASS_PUBLIC_CAPACITY_PARENT_AND_CLIENT_CONTROLS_ONLY'
        report['runner_returncode'] = 0
    except BaseException as error:
        report['status'] = 'FAIL_PUBLIC_CAPACITY_PARENT_AND_CLIENT_CONTROLS_ONLY'
        report['failure'] = repr(error)
        report['runner_returncode'] = 1
        try:
            report['source_hashes_after'] = fingerprint(source_paths())
        except BaseException as hash_error:
            report['source_hash_audit_failure'] = repr(hash_error)
    finally:
        report['finished_utc'] = utc()
        save()
    print(json.dumps({'status': report['status'], 'report': str(report_path), 'commands': len(report['commands']),
                      'results': report['results'], 'failure': report.get('failure')}, indent=2))
    return report['runner_returncode']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        if args.out:
            raise SystemExit('--verify and --out cannot be combined')
        try:
            result = verify_report(args.verify)
        except BaseException as error:
            print(json.dumps({'status': 'VERIFY_FAIL', 'error': repr(error)}))
            return 1
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.out is not None:
        output = args.out if args.out.is_absolute() else ROOT / args.out
    else:
        output = ROOT / 'build/ddr-capacity-parent-controls' / f'iverilog-verilator-{time.time_ns()}'
    return run_report(output)


if __name__ == '__main__':
    raise SystemExit(main())
