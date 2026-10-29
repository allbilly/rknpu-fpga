#!/usr/bin/env python3
"""Run the public same-clock actual-NPU JTAG/PCIe replay. Never accesses hardware."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime
import hashlib
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
from tools.ddr import endpoint_vectors
from tools.ddr.dual_host_profile import core_source_paths
from tools.owned_process import run_owned

TOP = 'tb_dual_host_npu_replay'
TEST = ROOT / 'tests/ddr/dual_host'
HEADER = ROOT / 'tests/ddr/endpoint/strict_line_image.svh'
EXPECTED_VECTOR_HASHES = {
    'upload.txt': '68cf7b0689343f22c979db0312eb718906a34d51c54e893699039f7630c885fb',
    'expected.txt': 'aca0f96badf878e82a9358eb2e5405f1ff97db706220e25e712555c38f10efec',
}
STRUCTURAL_WARNING_CODES = ('PINMISSING', 'PINNOTFOUND', 'LATCH', 'MULTIDRIVEN', 'UNOPTFLAT')


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git_status() -> str:
    return subprocess.check_output(
        ['git', 'status', '--porcelain=v2', '--untracked-files=all'], cwd=ROOT, text=True
    )


def launcher_identity(path: str) -> dict[str, str]:
    """Keep argv[0] spelling (notably ccache's c++ symlink) and bind its target."""
    invocation = os.path.abspath(path)
    target = str(Path(invocation).resolve())
    return {
        'path': invocation,
        'sha256': sha(Path(invocation)),
        'resolved_target': target,
        'resolved_target_sha256': sha(Path(target)),
    }


def resource_snapshot() -> dict[str, object]:
    """Read effective cgroup/rlimit state without changing any resource limit."""
    cgroup = {'version': 'unknown', 'path': None, 'limits': {}}
    try:
        row = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
                   if line.startswith('0::'))
        relative = row.split('::', 1)[1].lstrip('/')
        directory = Path('/sys/fs/cgroup') / relative
        cgroup.update(version=2, path=str(directory))
        for name in ('cpu.max', 'memory.max', 'memory.high', 'memory.swap.max', 'pids.max'):
            try:
                cgroup['limits'][name] = (directory / name).read_text().strip()
            except OSError:
                cgroup['limits'][name] = 'unavailable'
    except (OSError, StopIteration):
        pass
    rlimits = {}
    for name in ('RLIMIT_AS', 'RLIMIT_CPU', 'RLIMIT_DATA', 'RLIMIT_NOFILE', 'RLIMIT_STACK'):
        key = getattr(resource, name, None)
        if key is not None:
            try:
                current, maximum = resource.getrlimit(key)
                rlimits[name] = [str(current), str(maximum)]
            except (OSError, ValueError):
                rlimits[name] = 'unavailable'
    return {'cgroup': cgroup, 'rlimits': rlimits,
            'runner_changed_limits': False}


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def create_vectors(directory: Path) -> dict[str, str]:
    """Write only the original two-task SUB9 capture from the public oracle generator."""
    content, _ = endpoint_vectors.vector_contents()
    case = 'capture_sub_9'
    directory.mkdir(parents=True)
    output_hashes = {}
    for name, expected_hash in EXPECTED_VECTOR_HASHES.items():
        key = case + '/' + name
        require(key in content, 'Missing captured fixture from endpoint vector generator: ' + key)
        payload = content[key].encode('ascii')
        actual_hash = hashlib.sha256(payload).hexdigest()
        require(actual_hash == expected_hash, 'Generated fixture differs from accepted SUB9: ' + name)
        require(len(payload.splitlines()) == 1600, 'SUB9 fixture must contain 1600 complete lines: ' + name)
        path = directory / name
        path.write_bytes(payload)
        output_hashes[str(path)] = sha(path)
    return output_hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-reviewed-run', action='store_true',
                        help='explicitly compile and execute the public native replay')
    parser.add_argument('--out', type=Path,
                        help='fresh output directory under build/ (default is timestamped)')
    args = parser.parse_args()
    require(args.execute_reviewed_run, 'Pass --execute-reviewed-run to compile and execute')

    timestamp = time.time_ns()
    out = (args.out if args.out is not None else ROOT / 'build' / f'dual-host-npu-public-{timestamp}').resolve()
    require(out.is_relative_to(ROOT / 'build') and out != ROOT / 'build' and not out.exists(),
            'Output must be a fresh directory below build/')
    status_before_out = git_status()
    out.mkdir(parents=True)
    vectors = out / 'vectors' / 'ew_sub9'
    observed = out / 'observed'
    obj = out / 'obj'
    vectors.parent.mkdir(parents=True)
    observed.mkdir()
    obj.mkdir()

    sources = core_source_paths(ROOT)
    require(len(sources) == 72 and len(set(sources)) == 72, 'Expected strict 72-source dual-host core closure')
    extra_inputs = [
        ROOT / 'tools/ddr/dual_host_profile.py', ROOT / 'tools/ddr/framework_profile.py',
        ROOT / 'rtl/ddr/dual_host/sources.json', ROOT / 'rtl/ddr/dual_host/frontend-sources.json',
        ROOT / 'tools/ddr/run_dual_host_npu.py', ROOT / 'tools/ddr/endpoint_vectors.py',
        ROOT / 'tools/ddr/interface.py', ROOT / 'tests/backend_ew_captures.json',
        ROOT / 'model/__init__.py', ROOT / 'model/dma.py', ROOT / 'model/sim.py',
        ROOT / 'model/profile.py', ROOT / 'model/half.py',
        TEST / 'tb_dual_host_npu_replay.sv', TEST / 'rk_fast_parent_axi_model.sv',
        TEST / 'README.md', HEADER, ROOT / 'tools/owned_process.py',
    ]
    inputs = list(dict.fromkeys(sources + extra_inputs))
    require(all(path.is_file() and not path.is_symlink() for path in inputs), 'Missing/linked input path')
    source_hashes_before = {str(path): sha(path) for path in inputs}
    git_dirty_paths = [line for line in status_before_out.splitlines() if line]
    report = {
        'schema': 1, 'status': 'RUNNING',
        'scope': 'Actual rk_dual_host_ddr same-clock RTL with independent AXI RAM/ECC-control model; no PCIe IP/CDC or hardware claim',
        'top': TOP, 'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'git_dirty_status_before': status_before_out, 'git_dirty_sha256_before': hashlib.sha256(status_before_out.encode()).hexdigest(),
        'git_dirty_path_count': len(git_dirty_paths), 'source_hashes_before': source_hashes_before,
        'source_order': [str(path.relative_to(ROOT)) for path in sources],
        'runner_applied_resource_limits': False,
        'effective_resources_before_run': resource_snapshot(),
        'stimulus': 'Deterministic captured raw SUB9 program; no random seed',
        'commands': [], 'hardware_accessed': False, 'vivado_executed': False,
        'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    report_path = out / 'report.json'

    def save() -> None:
        write_json(report_path, report)

    expected_fixture_hashes: dict[str, str] | None = None

    def check_fixtures(stage: str) -> dict[str, str]:
        require(expected_fixture_hashes is not None, 'Fixtures are not generated before ' + stage)
        current = {name: sha(vectors / name) for name in EXPECTED_VECTOR_HASHES}
        require(current == EXPECTED_VECTOR_HASHES, 'Fixture differs from accepted SUB9 at ' + stage)
        require(current == expected_fixture_hashes, 'Fixture drift at ' + stage)
        return current

    def run(name: str, argv: list[str], timeout: int) -> Path:
        require({str(path): sha(path) for path in inputs} == source_hashes_before,
                'Source/input drift before ' + name)
        fixture_hashes_before = check_fixtures('before ' + name)
        log_path = out / (name + '.log')
        row = {'name': name, 'argv': list(map(str, argv)), 'timeout_seconds': timeout,
               'log': str(log_path), 'status': 'RUNNING'}
        report['commands'].append(row)
        save()
        start = time.monotonic()
        with log_path.open('xb') as stream:
            try:
                result = run_owned(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            except BaseException as error:
                cleanup = getattr(error, 'owned_process_cleanup', {})
                row.update(status='EXCEPTION', returncode=None, timed_out=False,
                           pid=cleanup.get('pid'), pgid=cleanup.get('pgid'),
                           live_before_cleanup=cleanup.get('live_before_cleanup'),
                           live_after_cleanup=cleanup.get('live_after_cleanup'),
                           wall_seconds=round(time.monotonic() - start, 3),
                           log_sha256=sha(log_path), exception=repr(error))
                save()
                raise
        return_code = result.returncode
        live_before = list(result.live_before_cleanup)
        live_after = list(result.live_after_cleanup)
        fixture_hashes_after = check_fixtures('after ' + name)
        row.update(returncode=return_code, timed_out=result.timed_out,
                   wall_seconds=round(time.monotonic() - start, 3),
                   pid=result.pid, pgid=result.pid,
                   live_before_cleanup=live_before, live_after_cleanup=live_after,
                   process_group_closed=not live_after,
                   fixture_hashes_before=fixture_hashes_before,
                   fixture_hashes_after=fixture_hashes_after,
                   status='PASS' if return_code == 0 and not result.timed_out and
                   not live_before and not live_after else 'FAIL',
                   log_sha256=sha(log_path))
        save()
        require(row['status'] == 'PASS', name + ' failed; see ' + str(log_path))
        require({str(path): sha(path) for path in inputs} == source_hashes_before,
                'Source/input drift after ' + name)
        return log_path

    save()
    try:
        create_vectors(vectors)
        expected_fixture_hashes = {name: sha(vectors / name) for name in EXPECTED_VECTOR_HASHES}
        require(expected_fixture_hashes == EXPECTED_VECTOR_HASHES,
                'Initial generated fixture hashes differ from accepted SUB9')
        report['fixture_hashes'] = {str(vectors / name): digest
                                    for name, digest in expected_fixture_hashes.items()}
        report['fixture_source'] = {
            'generator': 'tools.ddr.endpoint_vectors.vector_contents capture_sub_9',
            'accepted_run_v2_upload_sha256': EXPECTED_VECTOR_HASHES['upload.txt'],
            'accepted_run_v2_expected_sha256': EXPECTED_VECTOR_HASHES['expected.txt'],
            'generated_files_byte_identical_to_accepted_run_v2': True,
        }
        save()
        tool_identities = {}
        tool_paths = {}
        report['tool_identities'] = tool_identities
        report['tool_versions'] = {}
        for tool in ('verilator', 'make', 'c++'):
            found = shutil.which(tool)
            require(found is not None, 'Required tool unavailable: ' + tool)
            identity = launcher_identity(found)
            tool_identities[tool] = identity
            tool_paths[tool] = identity['path']
            version_log = run(tool + '-version', [identity['path'], '--version'], 30)
            report['tool_versions'][tool] = version_log.read_text(errors='strict').splitlines()[0]
        report['effective_resources_before_compile'] = resource_snapshot()
        save()
        command = [
            tool_paths['verilator'], '--cc', '--main', '--exe', '--timing', '--assert', '-Wall', '-Wno-fatal',
            '--output-groups', '0', '--output-split', '5000', '--output-split-cfuncs', '1000',
            '--top-module', TOP, '--Mdir', str(obj), '-I' + str(HEADER.parent),
            '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', '-MAKEFLAGS',
            'CXX=' + shlex.quote(tool_paths['c++']), *map(str, sources),
            str(TEST / 'rk_fast_parent_axi_model.sv'), str(TEST / (TOP + '.sv')),
        ]
        frontend = run('frontend', command, 1200)
        frontend_text = frontend.read_text(errors='strict')
        warning_counts = Counter(re.findall(r'^%Warning-([A-Z0-9_]+):', frontend_text, re.M))
        structural_warnings = [line for line in frontend_text.splitlines()
                               if re.match(r'^%Warning-(?:' + '|'.join(STRUCTURAL_WARNING_CODES) + r'):', line)]
        report['warning_counts'] = dict(warning_counts)
        report['new_structural_warning_count'] = len(structural_warnings)
        report['new_structural_warnings'] = structural_warnings
        save()
        require(not structural_warnings, 'New structural HDL warnings found')
        run('build', [tool_paths['make'], '-C', str(obj), '-f', 'V' + TOP + '.mk', '-j2',
                     'CXX=' + shlex.quote(tool_paths['c++'])], 1800)
        binary = obj / ('V' + TOP)
        require(binary.is_file(), 'Verilator binary missing')
        report['binary_path'] = str(binary)
        report['binary_sha256'] = sha(binary)
        save()
        observed_files = [observed / 'jtag-ew-sub9-observed.txt', observed / 'pcie-ew-sub9-observed.txt']
        require(not any(path.exists() for path in observed_files), 'Observed files must be fresh')
        replay_log = run('replay', [str(binary), '+VECTORS=' + str(vectors), '+OUT=' + str(observed)], 1200)
        replay_text = replay_log.read_text(errors='strict')
        markers = {
            'DUAL_HOST_JTAG_EW_SUB9_PASS': 'DUAL_HOST_JTAG_EW_SUB9_PASS jobs=1 tasks=2 bo_lines=1600 ack_after_complete_readback=1',
            'DUAL_HOST_PCIE_EW_SUB9_PASS': 'DUAL_HOST_PCIE_EW_SUB9_PASS jobs=1 tasks=2 bo_lines=1600 ack_after_complete_readback=1 outer_packet_ack_kept_owner=1',
            'DUAL_HOST_NPU_REPLAY_PASS': 'DUAL_HOST_NPU_REPLAY_PASS jobs=2 tasks=4 bo_images=2 bo_bytes=204800 physical_read64=3203 lease_epoch=2 owner=0',
        }
        for marker, exact_line in markers.items():
            require(len(re.findall(r'^' + re.escape(exact_line) + r'$', replay_text, re.M)) == 1,
                    'Missing/duplicate exact replay marker: ' + marker)
        require('NORMAL_CASE_PASS csr_base=00000000 lines=1600 tasks=2 read64=1603 axi_reads=1603' in replay_text,
                'JTAG per-job completion counters differ')
        expected = (vectors / 'expected.txt').read_bytes()
        require(len(expected.splitlines()) == 1600, 'Expected complete BO line count differs')
        for path in observed_files:
            require(path.is_file() and path.read_bytes() == expected,
                    'Complete 1600-line BO mismatch: ' + str(path))
        require(all(row['process_group_closed'] for row in report['commands']), 'A child process group remains open')
        final_fixture_hashes = check_fixtures('final report')
        status_after = git_status()
        final_source_hashes = {str(path): sha(path) for path in inputs}
        require(final_source_hashes == source_hashes_before,
                'Frozen source/generator/bench/header inputs changed during replay')
        report.update(
            status='PASS_ACTUAL_NPU_DUAL_HOST_NATIVE_ONLY',
            source_hashes_after=final_source_hashes,
            fixture_hashes_after=final_fixture_hashes,
            git_dirty_status_after=status_after,
            git_dirty_sha256_after=hashlib.sha256(status_after.encode()).hexdigest(),
            git_dirty_changed=status_after != status_before_out,
            observed={str(path): sha(path) for path in observed_files},
            totals={'jobs': 2, 'tasks': 4, 'complete_bo_images': 2,
                    'complete_bo_bytes': 204800, 'modeled_read64_axi_reads': 3203},
            closed_process_groups=[row['pgid'] for row in report['commands']],
            finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
    except BaseException as error:
        report.update(status='FAIL', error=repr(error),
                      finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        raise
    finally:
        status_after = git_status()
        report['git_dirty_status_after'] = status_after
        report['git_dirty_sha256_after'] = hashlib.sha256(status_after.encode()).hexdigest()
        report['git_dirty_changed'] = status_after != status_before_out
        report['source_hashes_after_finally'] = {
            str(path): sha(path) for path in inputs if path.is_file()
        }
        if expected_fixture_hashes is not None:
            report['fixture_hashes_finally'] = {
                name: sha(vectors / name) for name in EXPECTED_VECTOR_HASHES
                if (vectors / name).is_file()
            }
            report['fixtures_match_expected_finally'] = (
                report['fixture_hashes_finally'] == EXPECTED_VECTOR_HASHES
            )
        save()
    print(report['status'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
