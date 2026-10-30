#!/usr/bin/env python3
"""Run the retained USER2/UI and USER3/SYS mailbox native component test."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.owned_process import run_owned

CONTRACT = ROOT / 'tests/host/retained_mailbox/source-contract.json'
RUNNER = Path(__file__).resolve()
TOP = 'tb_retained_jtag_reset'
MARKER = re.compile(
    r'^PASS retained mailbox warm-reset checks=(\d+) ui_startup_edges=(\d+) '
    r'sys_startup_edges=(\d+) normal_successes=(\d+) backend_accepts=(\d+) '
    r'sys_identity_reads=(\d+) sys_control_accepts=(\d+) held_denials=(\d+)$', re.M)
WARNING = re.compile(r'(?im)(?:^%Warning-[A-Z0-9_]+:.*$|\bwarning:.*$|\bsorry:.*$)')
ERROR = re.compile(r'(?im)(?:%Error\b.*|%Fatal\b.*|\bFATAL:.*|Assertion failed.*|ERROR\s*:.*)')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def normalize_diagnostic(line):
    return line.replace(str(ROOT) + '/', '')


def warnings(text):
    return [normalize_diagnostic(line.strip()) for line in text.splitlines()
            if re.match(r'^%Warning-[A-Z0-9_]+:', line) or re.search(r'(?i)\bwarning:|\bsorry:', line)]


def check_no_errors(text, name):
    found = ERROR.findall(text)
    require(not found, f'{name}: tool reported HDL errors/assertions: {found[:10]!r}')


def check_warning_counter(text, expected, name):
    actual = Counter(warnings(text))
    desired = Counter(expected)
    require(actual == desired,
            f'{name}: warning Counter differs from pinned baseline; '
            f'actual={dict(actual)!r}, expected={dict(desired)!r}')
    return list(actual.elements())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, help='fresh result directory (must not exist)')
    args = ap.parse_args()

    contract = json.loads(CONTRACT.read_text())
    require(contract.get('status') == 'PUBLIC_RETAINED_MAILBOX_COMPONENT_CONTRACT', 'Unsupported contract status')
    require(contract.get('input_count') == 7 and len(contract.get('inputs', [])) == 7,
            'Contract must bind exactly seven HDL/bench/helper inputs')
    require(contract.get('top') == TOP and contract.get('timescale') == '1ns/1ps',
            'Unexpected bench top or timescale contract')
    required_roles = Counter(row['role'] for row in contract['inputs'])
    require(required_roles == Counter({'hdl': 5, 'bench': 1, 'include': 1}),
            f'Unexpected source profile roles: {required_roles!r}')

    inputs = []
    for row in contract['inputs']:
        rel = Path(row['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, f'Nonportable source path: {rel}')
        path = ROOT / rel
        require(path.is_file() and not path.is_symlink(), f'Missing or symlinked source input: {rel}')
        require(sha(path) == row['sha256'], f'Pinned input hash mismatch: {rel}')
        inputs.append(path)
    helper = ROOT / 'tools/owned_process.py'
    contract_hash = sha(CONTRACT)
    runner_hash = sha(RUNNER)
    helper_hash = sha(helper)
    before = {str(path.relative_to(ROOT)): sha(path) for path in inputs}
    before[str(CONTRACT.relative_to(ROOT))] = contract_hash
    before[str(RUNNER.relative_to(ROOT))] = runner_hash
    before[str(helper.relative_to(ROOT))] = helper_hash

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = (args.out if args.out else ROOT / 'build/retained-mailbox-native-v1' / stamp).resolve()
    require(not out.exists(), f'Output path must be fresh: {out}')
    out.mkdir(parents=True)

    found = {name: shutil.which(name) for name in ('iverilog', 'vvp', 'verilator')}
    require(all(found.values()), 'UNAVAILABLE: iverilog, vvp and Verilator are required')
    shim_selection = shutil.which('g++')
    require(shim_selection is not None, 'UNAVAILABLE: PATH has no g++ selection')
    excluded_driver_names = {'ccache', 'sccache', 'distcc', 'icecc'}
    direct_gxx = None
    for path_entry in os.environ.get('PATH', '').split(os.pathsep):
        candidate = Path(path_entry or '.') / 'g++'
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        resolved = candidate.resolve()
        if resolved.name.lower() not in excluded_driver_names:
            direct_gxx = str(candidate)
            break
    require(direct_gxx is not None, 'UNAVAILABLE: no direct g++ compiler found in PATH (ccache/sccache/distcc/icecc shims are excluded)')
    found['g++'] = direct_gxx
    shim_resolved = Path(shim_selection).resolve()
    direct_resolved = Path(direct_gxx).resolve()
    compiler_provenance = {
        'first_path_selection_invocation': shim_selection,
        'first_path_selection_resolved': str(shim_resolved),
        'first_path_selection_sha256': sha(shim_resolved),
        'direct_compiler_invocation': direct_gxx,
        'direct_compiler_resolved': str(direct_resolved),
        'direct_compiler_sha256': sha(direct_resolved),
        'compiler_executable_name_exclusions': sorted(excluded_driver_names),
    }
    tool_ids = {name: {'path': str(Path(path).resolve()), 'invocation_path': path, 'sha256': sha(Path(path).resolve())}
                for name, path in found.items()}

    hdl = [str(ROOT / row['path']) for row in contract['inputs'] if row['role'] == 'hdl']
    bench = str(ROOT / next(row['path'] for row in contract['inputs'] if row['role'] == 'bench'))
    expected = contract['warning_policy']
    iv_expected = expected['iverilog_compile']['expected_lines']
    vl_expected = expected['verilator_lint']['expected_lines']
    vb_expected = expected['verilator_build']['expected_lines']
    ivbin = out / 'iverilog' / 'retained.vvp'
    vobj = out / 'verilator' / 'obj'
    vbin = vobj / 'retained'
    iv_compile = [found['iverilog'], '-g2012', '-Wall', '-s', TOP, '-o', str(ivbin), *hdl, bench]
    iv_run = [found['vvp'], str(ivbin)]
    vflags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps']
    v_lint = [found['verilator'], '--lint-only', *vflags, '--top-module', TOP, *hdl, bench]
    make_overrides = {'CXX': found['g++'], 'LINK': found['g++'], 'OBJCACHE': ''}
    makeflags = ' '.join(shlex.quote(f'{key}={value}') for key, value in make_overrides.items())
    v_build = [found['verilator'], '--binary', *vflags, '-j', '2', '-MAKEFLAGS', makeflags,
               '--top-module', TOP, '--Mdir', str(vobj), '-o', 'retained', *hdl, bench]
    v_run = [str(vbin)]

    report = {
        'schema': 1,
        'status': 'RUNNING_RETAINED_MAILBOX_NATIVE',
        'scope': contract['scope'],
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'stimulus_seed': contract['counts']['stimulus_seed'],
        'contract_path': str(CONTRACT.relative_to(ROOT)), 'contract_sha256': contract_hash,
        'runner_path': str(RUNNER.relative_to(ROOT)), 'runner_sha256': runner_hash,
        'source_hashes_before': before, 'tools': tool_ids, 'compiler_provenance': compiler_provenance, 'commands': [], 'results': {},
        'warning_diagnostics': [], 'resource_limits_added': False,
        'environment_overrides': make_overrides, 'verilator_make_overrides': make_overrides,
        'hardware_accessed': False, 'bscane2_instantiated': False, 'vivado_executed': False,
    }
    report_path = out / 'report.json'

    def save():
        temp = report_path.with_suffix('.json.tmp')
        temp.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        temp.replace(report_path)

    def run(name, argv, timeout):
        for rel, digest in before.items():
            path = ROOT / rel
            require(path.is_file() and sha(path) == digest, f'Input changed before {name}: {rel}')
        stdout_path = out / f'{name}.stdout.log'
        stderr_path = out / f'{name}.stderr.log'
        row = {'name': name, 'argv': list(map(str, argv)), 'timeout_seconds': timeout,
               'stdout_path': str(stdout_path), 'stderr_path': str(stderr_path),
               'started_utc': datetime.now(timezone.utc).isoformat()}
        report['commands'].append(row)
        save()
        started = time.monotonic()
        with stdout_path.open('xb') as stdout, stderr_path.open('xb') as stderr:
            try:
                env = os.environ.copy()
                env.update(make_overrides)
                result = run_owned(argv, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout, env=env)
            except BaseException as error:
                cleanup = getattr(error, 'owned_process_cleanup', {})
                row.update(status='EXCEPTION', failure=repr(error), pid=cleanup.get('pid'),
                           pgid=cleanup.get('pgid'), live_before_cleanup=cleanup.get('live_before_cleanup'),
                           live_after_cleanup=cleanup.get('live_after_cleanup'),
                           stdout_sha256=sha(stdout_path), stderr_sha256=sha(stderr_path))
                save()
                raise
        row.update(returncode=result.returncode, timed_out=result.timed_out, pid=result.pid, pgid=result.pid,
                   live_before_cleanup=list(result.live_before_cleanup),
                   live_after_cleanup=list(result.live_after_cleanup),
                   process_group_closed=not result.live_after_cleanup,
                   seconds=round(time.monotonic() - started, 3),
                   stdout_sha256=sha(stdout_path), stderr_sha256=sha(stderr_path),
                   finished_utc=datetime.now(timezone.utc).isoformat())
        row['status'] = ('PASS' if result.returncode == 0 and not result.timed_out
                         and not result.live_before_cleanup and not result.live_after_cleanup else 'FAIL')
        save()
        require(row['status'] == 'PASS', f'{name} failed or left owned process group')
        for rel, digest in before.items():
            path = ROOT / rel
            require(path.is_file() and sha(path) == digest, f'Input changed after {name}: {rel}')
        text = stdout_path.read_text(errors='replace') + '\n' + stderr_path.read_text(errors='replace')
        check_no_errors(text, name)
        return text, row

    try:
        for name, flag in (('iverilog', '-V'), ('vvp', '-V'), ('verilator', '--version'), ('g++', '--version')):
            text, _ = run(name + '_version', [found[name], flag], contract['timeouts_seconds']['tool_version'])
            diagnostics = warnings(text)
            require(not diagnostics, f'Unexpected warning during {name} version query: {diagnostics!r}')
            first = next((line.strip() for line in text.splitlines() if line.strip()), '')
            tool_ids[name]['version'] = first
            if name == 'verilator':
                required = expected['verilator_version_required']
                require(first == required,
                        f'Unsupported Verilator warning-baseline version: got {first!r}; expected {required!r}')
            report['tools'][name]['version'] = first
            save()

        for name, argv, timeout, expected_warnings in (
            ('iverilog_compile', iv_compile, contract['timeouts_seconds']['iverilog_compile'], iv_expected),
            ('iverilog_run', iv_run, contract['timeouts_seconds']['iverilog_run'], []),
            ('verilator_lint', v_lint, contract['timeouts_seconds']['verilator_lint'], vl_expected),
            ('verilator_build', v_build, contract['timeouts_seconds']['verilator_build'], vb_expected),
            ('verilator_run', v_run, contract['timeouts_seconds']['verilator_run'], []),
        ):
            if name == 'iverilog_compile':
                (out / 'iverilog').mkdir()
            if name == 'verilator_lint':
                (out / 'verilator').mkdir()
            text, row = run(name, argv, timeout)
            observed = warnings(text)
            require(Counter(observed) == Counter(expected_warnings),
                    f'{name} full warning Counter differs: actual={dict(Counter(observed))!r} '
                    f'expected={dict(Counter(expected_warnings))!r}')
            report['warning_diagnostics'].extend({'command': name, 'line': item} for item in observed)
            if name in ('iverilog_run', 'verilator_run'):
                matches = MARKER.findall(text)
                required_tuple = (55, 65, 65, 2, 2, 1, 1, 1)
                require(len(matches) == 1, f'{name}: expected exactly one PASS marker, got {len(matches)}')
                values = tuple(map(int, matches[0]))
                require(values == required_tuple, f'{name}: marker values differ: {values!r}')
                report['results'][name] = {'status': 'PASS', 'marker_values': list(values),
                                           'marker': next(line for line in text.splitlines() if line.startswith('PASS retained mailbox'))}
                if name == 'verilator_run':
                    require(vbin.is_file(), 'Verilator executable missing after build')
                    report['results'][name]['binary_path'] = str(vbin.relative_to(ROOT))
                    report['results'][name]['binary_sha256'] = sha(vbin)
            elif name == 'iverilog_compile':
                report['results'][name] = {'status': 'PASS', 'warnings': observed}
            elif name == 'verilator_lint':
                report['results'][name] = {'status': 'PASS', 'warnings': observed}
            elif name == 'verilator_build':
                report['results'][name] = {'status': 'PASS', 'warnings': observed}
            save()
        report['status'] = 'PASS_RETAINED_MAILBOX_BOTH_NATIVE'
    except BaseException as error:
        report['status'] = 'FAIL_RETAINED_MAILBOX_NATIVE'
        report['failure'] = repr(error)
        raise
    finally:
        report['source_hashes_after'] = {rel: sha(ROOT / rel) for rel in before}
        report['source_hashes_unchanged'] = report['source_hashes_after'] == before
        report['all_owned_process_groups_closed'] = all(
            row.get('process_group_closed') is True and not row.get('live_before_cleanup')
            and not row.get('live_after_cleanup') for row in report['commands'])
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        if report['status'].startswith('PASS_') and not report['source_hashes_unchanged']:
            report['status'] = 'FAIL_SOURCE_HASH_DRIFT'
        if report['status'].startswith('PASS_') and not report['all_owned_process_groups_closed']:
            report['status'] = 'FAIL_OWNED_PROCESS_CLEANUP'
        save()
        print(report_path)
    return 0 if report['status'] == 'PASS_RETAINED_MAILBOX_BOTH_NATIVE' and report['source_hashes_unchanged'] and report['all_owned_process_groups_closed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
