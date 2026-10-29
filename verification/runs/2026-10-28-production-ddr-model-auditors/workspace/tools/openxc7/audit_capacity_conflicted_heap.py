#!/usr/bin/env python3
"""Read-only exact original-job supersession audit; never signal a process.

Recompute the complete source-bound matching lower bound, verify its packed
graph/policy/input matches the one original running HeAP worker, and archive
current state. Only the fixed 538118-cell original mapping is in scope, never
the full shared 523410-cell candidate, numerical jobs or another user's work.
This is capacity/scheduling evidence, not native rejection, fit or signoff.
"""
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, source_revision, timestamp
from lut_sharing_bound import sharing_bound
from probe_lut_sharing_bound import validate_metadata
from place_native_heap_board import verify_full_argv

BOUND = ROOT / 'build/openxc7/full-lut-sharing-bound-1791469159980053569/report.json'
LIVE = ROOT / 'build/openxc7/full-prefix-native-heap-place-1791461555717052444/report.json'
UNIT = 'rknpu-full-prefix-native-heap-place-20261008.service'
INVOCATION = '8ee59c7e6cb44f7bbc746a3d1ff1c526'
SUPERVISOR, NATIVE = 1416947, 1417350
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_original_capacity_control.py'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_live(report, unit, command):
    assert report['status'] == 'RUNNING' and report['stage'] == 'native_place'
    assert report['supervisor_pid'] == SUPERVISOR
    assert unit['ActiveState'] == 'active' and unit['SubState'] == 'running'
    assert unit['MainPID'] == str(SUPERVISOR) and unit['InvocationID'] == INVOCATION
    step = report['commands'][-1]
    assert step['label'] == 'native_place' and step['status'] == 'RUNNING' and step['pid'] == NATIVE
    verify_full_argv(step['argv'])
    assert step['argv'] == command and command[0] == report['executable']['path']
    assert command[command.index('--json') + 1] == str(ROOT / 'build/openxc7/full-prefix-pack-input-1791392677842220299/pack_input.json')
    assert command[command.index('--write') + 1] == str(LIVE.parent / 'placed.json')
    assert not (LIVE.parent / 'placed.json').exists(), 'Completed checkpoint must not be retired as an uncompleted job'


def check_bound(report):
    assert report['status'] == 'MEASURED_FULL_SOURCE_BOUND_RELAXED_LUT_MATCHING_NOT_PLACEMENT_OR_SIGNOFF'
    assert report['finished_utc'] and report['full_target_parallel_products'] == 512 and report['seed'] == 3588
    bound = report['matching_bound']
    assert (bound['lut_cells'], bound['necessary_position_lower_bound'], bound['physical_LUT_positions']) == (502795, 302998, 298600)
    assert bound['lower_bound_exceeds_device'] is True
    assert bound['maximum_five_to_smaller_matching'] == bound['minimum_cut_capacity'] == 18140
    for key in ('native_placement_executed', 'physical_fit_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'bitstream_emitted', 'hardware_programmed', 'placement_assignment_generated',
                'hardware_execution_input_changed'):
        assert report[key] is False


def main():
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    bound = json.loads(BOUND.read_text())
    check_bound(bound)
    for path, sha in bound['source'].items():
        assert digest(path) == sha, 'Changed capacity evidence input: ' + path
    wrapper_path = Path(bound['parent_report'])
    wrapper = json.loads(wrapper_path.read_text())
    validate_metadata(wrapper)
    census_path, cache_path = Path(wrapper['census_report']), Path(wrapper['cache'])
    assert digest(census_path) == wrapper['census_report_sha256'] and digest(cache_path) == wrapper['cache_sha256']
    census = json.loads(census_path.read_text())
    assert census['total_cells'] == 538118 and census['lut_cells'] == 502795
    assert census['source_revision'] == bound['production_source_after'] == source_revision()
    cache = json.loads(cache_path.read_text())
    groups = {}
    for inputs, count in cache['groups']:
        assert inputs == sorted(inputs) and len(set(inputs)) == len(inputs)
        key = frozenset(inputs)
        assert key not in groups
        groups[key] = count
    recomputed = sharing_bound(groups, cache['whole'], cache['positions'])
    assert recomputed == bound['matching_bound']
    props = ['ActiveState', 'SubState', 'MainPID', 'InvocationID', 'MemoryCurrent', 'MemorySwapCurrent']
    observed = subprocess.run(['systemctl', '--user', 'show', UNIT, *(word for key in props for word in ('-p', key))],
                              capture_output=True, text=True, check=True)
    unit = dict(line.split('=', 1) for line in observed.stdout.splitlines() if '=' in line)
    unit = {key: unit[key] for key in props}
    live_bytes = LIVE.read_bytes()
    live = json.loads(live_bytes)
    command = Path(f'/proc/{NATIVE}/cmdline').read_bytes().rstrip(b'\0').decode().split('\0')
    check_live(live, unit, command)
    assert Path(f'/proc/{NATIVE}/exe').resolve(strict=True) == Path(live['executable']['path']).resolve(strict=True)
    assert digest(live['executable']['path']) == live['executable']['sha256']
    input_path = command[command.index('--json') + 1]
    qualified_path = ROOT / 'build/openxc7/dsp-constant-qualification-1791414657664905509/report.json'
    qualified = json.loads(qualified_path.read_text())
    pack = next(c for c in qualified['commands'] if c['label'] == 'full_native_pack')
    assert pack['argv'][pack['argv'].index('--json') + 1] == input_path
    assert pack['status'] == 'PASS_TOOL_EXECUTION_ONLY' and pack['returncode'] == 0
    assert qualified['source'][input_path] == live['source'][input_path] == digest(input_path)
    policies = [path for path in bound['source'] if path.endswith(('/xilinx_place.cc', '/xilinx.cc'))]
    assert len(policies) == 2
    assert all(live['source'][path] == bound['source'][path] for path in policies), 'Different linked LUT policy evidence'
    log = Path(live['commands'][-1]['log']).read_bytes()
    checksum = r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$'
    actual = re.findall(checksum, log.decode().split('Creating initial analytic placement for ', 1)[0])
    original = re.findall(checksum, Path(pack['log']).read_text())
    assert actual == original == ['0x68a070d4']
    assert live['production_source_before'] == bound['production_source_after']
    for path, sha in bound['source'].items():
        assert digest(path) == sha
    out = ROOT / f'build/openxc7/original-capacity-supersession-audit-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'observed-live-report.json').write_bytes(live_bytes)
    (out / 'observed-native-place.log').write_bytes(log)
    (out / 'observed-unit.txt').write_text(observed.stdout)
    shutil.copyfile(__file__, out / 'executed_source.py')
    result = dict(status='CONFIRMED_EXACT_ORIGINAL_LIVE_HEAP_CAPACITY_CONFLICT_NO_PROCESS_SIGNALLED',
        finished_utc=timestamp(), unit=UNIT, invocation=INVOCATION, supervisor_pid=SUPERVISOR, native_pid=NATIVE,
        observed_unit=unit, matching_bound=recomputed, actual_packed_checksum=actual[0],
        complete_original_packed_cells=538118, full_target_parallel_products=512,
        original_report=str(LIVE), capacity_report=str(BOUND), native_argv=command,
        production_source=source_revision(), python=sys.version, seed=3588,
        original_report_sha256=hashlib.sha256(live_bytes).hexdigest(),
        source=dict(bound['source'], **{str(p): digest(p) for p in (BOUND, qualified_path, Path(__file__), CONTROL)}),
        process_signalled=False, shared_candidate_changed=False, numerical_job_changed=False,
        native_rejection_claimed=False, physical_fit_verified=False, bitstream_emitted=False)
    (out / 'report.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
