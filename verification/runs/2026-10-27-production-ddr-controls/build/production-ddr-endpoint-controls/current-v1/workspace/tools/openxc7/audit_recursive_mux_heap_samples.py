#!/usr/bin/env python3
"""Audit fresh bounded live-HeAP snapshots, not placement/fit acceptance.

Bind the same live native worker, full target, source, database and read-only
debugger script. Compare native queue observations without calling them an
unplaced-cell census, convergence proof or ETA. Check optimistic individual
same-tile/relative-z BEL roles only for explicitly supported observed rows;
occupancy/packing/ports/control sets/all clusters/full fit remain unverified.
Never attach, signal, restart, modify input/RTL/constraints or run native P&R.
No checksum manifest, bitstream or FPGA/flash access occurs.
"""
import argparse
import json
from pathlib import Path
import re
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_recursive_mux_analytic_scope as live
import audit_native_mux_cluster_geometry as geometry

ROOT = live.ROOT
GDB_SCRIPT = ROOT / 'tools/openxc7/read_recursive_mux_heap_state.gdb'
HEAP_SOURCE = ROOT / 'build/openxc7/counter-safe-heap-engine-1791481639500508440/common/place/placer_heap.cc'
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_heap_samples_control.py'
COUNTERS = {'radius', 'iter', 'iter_at_radius', 'total_iters_for_cell', 'total_iters', 'total_iters_noreset', 'need_to_explore'}


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        assert name not in result, 'Duplicate snapshot field'
        result[name] = value
    return result


def bel(value):
    assert set(value) == {'tile', 'index'}
    assert all(type(v) is int and -1 <= v <= 2147483647 for v in value.values())
    assert (value['tile'] == -1) == (value['index'] == -1), 'Partial native BEL identity'


def row(value):
    assert set(value) == {'name', 'type', 'cluster', 'x', 'y', 'z', 'absolute_z', 'bel'}
    assert all(type(value[k]) is str and len(value[k]) <= 4096 and '\n' not in value[k]
               for k in ('name', 'type', 'cluster'))
    assert value['name'] and re.fullmatch(r'\w+', value['type'])
    assert all(type(value[k]) is int and -2147483648 <= value[k] <= 2147483647 for k in ('x', 'y', 'z'))
    assert type(value['absolute_z']) is bool
    bel(value['bel'])


def parse_snapshot(text, pid):
    assert type(pid) is int and pid > 0
    marker = 'READ_ONLY_HEAP_STATE_JSON '
    assert text.count(marker) == 1, 'Missing/ambiguous fresh native state'
    assert text.count(f'[Inferior 1 (process {pid}) detached]') == 1, 'Missing actual detach'
    assert not re.search(r'(?im)Python Exception|Traceback|Error in sourced command file|Cannot access memory|optimized out', text)
    line = next(line for line in text.splitlines() if line.startswith(marker))
    state = json.loads(line[len(marker):], object_pairs_hook=unique_fields)
    assert set(state) == {'native_pid', 'children', 'identifier_count', 'remaining_queued_entries', 'root',
                         'members', 'counters', 'best_bel', 'currently_placed', 'inferior_calls_or_writes'}
    assert state['native_pid'] == pid and type(state['native_pid']) is int
    assert type(state['children']) is int and 0 <= state['children'] <= 64
    assert type(state['identifier_count']) is int and 0 < state['identifier_count'] <= 16000000
    assert type(state['remaining_queued_entries']) is int and 0 <= state['remaining_queued_entries'] <= 600000
    assert type(state['members']) is list and len(state['members']) == state['children']
    assert set(state['counters']) == COUNTERS
    assert all(type(v) is int and 0 <= v <= 2147483647 for v in state['counters'].values())
    assert type(state['currently_placed']) is bool and state['inferior_calls_or_writes'] is False
    bel(state['best_bel']); row(state['root'])
    for member in state['members']: row(member)
    names = [state['root']['name']] + [member['name'] for member in state['members']]
    assert len(names) == len(set(names)), 'Duplicate native member'
    return state


def relative_roles(state):
    rows = [state['root']] + state['members']
    assert state['root']['z'] == 0, 'Unsupported nonzero root offset'
    assert all(r['x'] == r['y'] == 0 and r['absolute_z'] is False for r in rows), 'Unmodeled observed relative geometry'
    if state['members']:
        assert all(r['cluster'] == state['root']['name'] for r in rows), 'Changed observed cluster ownership'
    else:
        assert state['root']['cluster'] == '', 'Unsupported clustered singleton'
    assert len({r['z'] for r in rows}) == len(rows), 'Aliased observed relative locations'
    return [dict(name=r['name'], type=r['type'], z=r['z']) for r in rows]


def compare_samples(states):
    assert len(states) >= 2
    assert len({s['native_pid'] for s in states}) == len({s['identifier_count'] for s in states}) == 1
    return dict(first_queue_entries=states[0]['remaining_queued_entries'],
        last_queue_entries=states[-1]['remaining_queued_entries'],
        arithmetic_queue_decline=states[0]['remaining_queued_entries'] - states[-1]['remaining_queued_entries'],
        first_current_cell=states[0]['root']['name'], last_current_cell=states[-1]['root']['name'],
        current_cell_changed=states[0]['root']['name'] != states[-1]['root']['name'],
        queue_is_complete_unplaced_cell_census=False, placed_percentage_established=False,
        convergence_or_completion_time_established=False)


def source_contract(text):
    assert text.count('remaining.pop();') == 1
    assert 'for (auto cell : p->solve_cells)' in text
    assert 'if (ci->bel != BelId())\n                    continue;' in text
    assert text.count('remaining.emplace(') >= 4, 'Missing native ripup/requeue semantics'
    assert 'if (ci->cluster == ClusterId()) {\n                    try_place_cell(ci, nx, ny);' in text
    return dict(native_queue_contains_pending_priority_entries_with_ripup_requeue_and_already_bound_skips=True,
                observed_queue_is_not_independent_full_unplaced_cell_census=True,
                native_singleton_and_cluster_search_branches_retained=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--snapshot', action='append', type=Path, required=True)
    args = parser.parse_args(); assert len(args.snapshot) >= 2
    path = args.native_report.resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-heap-place-')
    native_bytes = path.read_bytes(); native = json.loads(native_bytes)
    command = live.live_metadata(native); ticks = live.verify_worker(command)
    assert live.source_revision() == native['production_source_before']
    status = Path(f'/proc/{command["pid"]}/status').read_text()
    assert re.search(r'(?m)^TracerPid:\s+0$', status), 'Worker still attached'
    before = {}
    for item in (HEAP_SOURCE, geometry.DATABASE, geometry.CONSTIDS, geometry.HEADER, Path(command['argv'][0]),
                 Path(native['packed_report'])):
        item = item.resolve(strict=True); sha = live.digest(item)
        assert native['source'][str(item)] == sha
        before[str(item)] = sha
    assert before[str(Path(command['argv'][0]))] == native['executable']['sha256']
    pack = json.loads(Path(native['packed_report']).read_text()); live.placement.packer.validate_pack(pack)
    source = source_contract(HEAP_SOURCE.read_text())
    snapshots = [p.resolve(strict=True) for p in args.snapshot]
    assert len(set(snapshots)) == len(snapshots), 'Duplicate snapshot input'
    assert all(p.is_relative_to(ROOT / 'build') and p.suffix == '.log' for p in snapshots)
    files = {*snapshots, GDB_SCRIPT, CONTROL, Path(__file__).resolve(), Path(sys.executable).resolve()}
    files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    for item in files:
        sha = live.digest(item)
        assert str(item) not in native['source'] or native['source'][str(item)] == sha
        before[str(item)] = sha
    states = [parse_snapshot(p.read_text(), command['pid']) for p in snapshots]
    comparison = compare_samples(states)
    roles = [relative_roles(s) for s in states]
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    known = [''] + re.findall(r'^X\((\w+)\)\s*$', geometry.CONSTIDS.read_text(), re.M)
    tiles = list(geometry.database_bels(geometry.DATABASE.read_bytes(), known))
    results = []
    for rows in roles:
        candidates = [dict(tile_type=tile, **c) for tile, bels in tiles for c in geometry.candidate_geometry(rows, bels)]
        assert candidates, 'No database roots of observed native type'
        results.append(dict(observed_root=rows[0]['name'], candidates=len(candidates),
            compatible_individual_role_candidates=[c for c in candidates if not c['missing']],
            occupancy_ports_control_sets_all_clusters_or_full_fit_verified=False))
    assert live.verify_worker(command) == ticks and live.source_revision() == native['production_source_before']
    assert re.search(r'(?m)^TracerPid:\s+0$', Path(f'/proc/{command["pid"]}/status').read_text())
    assert all(live.digest(name) == sha for name, sha in before.items())
    out = ROOT / f'build/openxc7/recursive-mux-observed-heap-samples-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'observed-native-report.json').write_bytes(native_bytes)
    (out / 'executed_source.py').write_bytes(Path(__file__).read_bytes())
    report = dict(status='OBSERVED_SAME_FULL_NATIVE_HEAP_QUEUE_AND_INDIVIDUAL_ROLE_GEOMETRY_NOT_PLACEMENT_ACCEPTANCE',
        finished_utc=live.timestamp(), scope=__doc__, source=before, native_report=str(path), current_native_pid=command['pid'],
        native_worker_start_ticks=ticks, native_version=native['native_version'], production_source=live.source_revision(),
        full_packed_cells=pack['native_census']['cells'], snapshots=[str(p) for p in snapshots],
        actual_states=states, sample_comparison=comparison, compiled_native_source_contract=source,
        observed_individual_role_geometry=results, debugger_attached_by_this_audit=False,
        native_placement_completed=False, full_cell_membership_verified=False, numerical_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, native_worker_signalled_by_this_audit=False,
        native_source_input_constraints_budgets_or_error_expectations_changed=False,
        artifacts={str(p.relative_to(ROOT)):live.digest(p) for p in out.iterdir() if p.is_file()})
    (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
