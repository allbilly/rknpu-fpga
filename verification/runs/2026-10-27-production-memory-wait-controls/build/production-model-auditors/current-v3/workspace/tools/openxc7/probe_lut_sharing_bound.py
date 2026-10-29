"""Read a completed full-group cache and measure an optimistic matching bound.

No netlist/placement input, original report, constraint, tool or FPGA is edited.
This cannot establish placed fit, numerical RTL, timing, DRC or bitstream readiness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, source_revision, timestamp
from lut_sharing_bound import sharing_bound

CACHED = 'PASS_FRESH_FULL_PACKED_INPUT_GROUP_CACHE_NOT_MATCHING_OR_PLACED_FIT'
CONTROL = ROOT / 'tests/cmac/test_lut_sharing_bound.py'
FLOW = ROOT / 'tools/openxc7/lut_sharing_bound.py'

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, 'Duplicate cache/report field'
        result[key] = value
    return result

def validate_metadata(parent):
    assert parent['status'] == CACHED and parent['stage'] == 'complete' and parent['finished_unix']
    assert parent['cache_created'] is True and parent['full_packed_census_rerun'] is True
    assert (parent['controls'], parent['seed'], parent['exhaustive_relaxed_matching_comparisons']) == (9, 3588, 250)
    assert parent['cached_LUT_cells'] == 443938 and parent['cached_input_groups'] > 0
    assert parent['executed_frozen_body']['body_changed'] is False
    for key in ('native_placement_executed', 'physical_fit_verified', 'timing_signoff',
            'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert parent[key] is False
    assert [c['label'] for c in parent['commands']] == ['software_controls', 'generated_check']
    assert all(c['returncode'] == 0 for c in parent['commands'])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-report', type=Path, required=True)
    args = parser.parse_args()
    parent_path = args.cache_report.resolve(strict=True)
    assert parent_path.is_relative_to(ROOT / 'build/openxc7')
    parent = json.loads(parent_path.read_text(), object_pairs_hook=unique_object)
    validate_metadata(parent)  # Reject RUNNING/small/stale scope before output/tools.
    out = ROOT / ('build/openxc7/full-lut-sharing-bound-' + str(time.time_ns()))
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))
    report = dict(status='RUNNING', started_utc=timestamp(), python=platform.python_version(),
        scope=__doc__, parent_report=str(parent_path), commands=[], source={},
        production_source_before=source_revision(), native_placement_executed=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        cache_path = Path(parent['cache']).resolve(strict=True)
        census_path = Path(parent['census_report']).resolve(strict=True)
        assert cache_path.parent == census_path.parent == parent_path.parent
        assert digest(cache_path) == parent['cache_sha256'] and digest(census_path) == parent['census_report_sha256']
        for path, sha in parent['inputs'].items():
            assert digest(path) == sha, 'Changed cache producer input: ' + path
        assert parent['inputs'][str(FLOW)] == digest(FLOW) and parent['inputs'][str(CONTROL)] == digest(CONTROL)
        census = json.loads(census_path.read_text(), object_pairs_hook=unique_object)
        assert census['status'] == 'MEASURED_FULL_PACKED_LUT_NECESSARY_BOUND_NOT_PLACEMENT_OR_SIGNOFF'
        assert census['total_cells'] == 538118 and census['lut_cells'] == 502795
        assert len(census['retained_kernel_dsps']) == 16 and set(census['retained_kernel_dsps'].values()) == {32}
        assert census['source_revision'] == report['production_source_before']
        for path, sha in census['inputs'].items():
            assert digest(path) == sha, 'Changed full-census input: ' + path
        report['source'] = {**parent['inputs'], **census['inputs'],
            **{str(p): digest(p) for p in (parent_path, cache_path, census_path, Path(__file__))}}
        save()
        argv = [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
            '-s', 'tests/cmac', '-p', CONTROL.name, '-v']
        with (out / 'software_controls.log').open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        report['commands'].append(dict(argv=argv, returncode=result.returncode, log=str(out / 'software_controls.log')))
        assert result.returncode == 0
        cache = json.loads(cache_path.read_text(), object_pairs_hook=unique_object)
        assert set(cache) == {'schema', 'census_report_sha256', 'whole', 'positions', 'lut_cells',
            'groups', 'placement_assignment', 'hardware_execution_input'}
        assert cache['schema'] == 1 and cache['census_report_sha256'] == digest(census_path)
        assert cache['placement_assignment'] is cache['hardware_execution_input'] is False
        assert (cache['whole'], cache['positions'], cache['lut_cells']) == (58857, 298600, 502795)
        groups = {}
        for inputs, count in cache['groups']:
            assert isinstance(inputs, list) and inputs == sorted(inputs)
            key = frozenset(inputs)
            assert len(key) == len(inputs) and key not in groups
            groups[key] = count
        assert len(groups) == parent['cached_input_groups'] and sum(groups.values()) == 443938
        measured = sharing_bound(groups, cache['whole'], cache['positions'])
        assert measured['lut_cells'] == 502795 and measured['five_input_LUTs'] == 66340
        assert measured['isolated_position_lower_bound'] == census['necessary_LUT_position_lower_bound']
        assert measured['unpaired_isolated_five_input_LUTs'] == census['five_input_LUTs_without_any_subset_partner']
        report['matching_bound'] = measured
        for path, sha in report['source'].items():
            assert digest(path) == sha, 'Changed matching input: ' + path
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='MEASURED_FULL_SOURCE_BOUND_RELAXED_LUT_MATCHING_NOT_PLACEMENT_OR_SIGNOFF',
            full_target_parallel_products=512, controls=9, seed=3588, exhaustive_relaxed_matching_comparisons=250,
            placement_assignment_generated=False, hardware_execution_input_changed=False)
    except BaseException as error:
        report.update(status='FAIL_LUT_SHARING_BOUND', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()
        print(out / 'report.json', flush=True)
        print(report['status'], flush=True)

if __name__ == '__main__':
    main()
