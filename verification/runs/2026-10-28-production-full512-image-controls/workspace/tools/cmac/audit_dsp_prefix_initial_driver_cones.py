#!/usr/bin/env python3
"""Prove captured temporary-driver cones unobservable; no mapping admission.

Conservatively connect every cell input to every cell output, including state
and hierarchical cells. Module outputs/inouts, outputless side-effect cells,
and explicitly retained cells/nets are roots. A warning reaching any root is
a failure. No mux selection, constant propagation or numerical assumption is
used to prune the graph. Every reachable dead cell must also belong to the
explicit pure mux/register type whitelist; arbitrary output-bearing cells are
not assumed side-effect free. This is an RTLIL connectivity proof, not HDL replay.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import capture_dsp_prefix_initial_driver_fanout as capture

PARENT = 'build/rknpu-dsp-prefix-initial-driver-fanout/1791305786269181565/report.json'
PURE_CONE_TYPES = {'$mux', '$pmux', '$dff', '$adff', '$sdff', '$dffe', '$adffe', '$sdffe'}


def normalized_inventory(before, notices):
    # The saved JSON represents tuples as lists. Normalize only serialization;
    # every diagnostic, bit, consumer and count must still compare exactly.
    return json.loads(json.dumps(capture.fanout_inventory(before, notices)))


def retained(attributes):
    for name in ('keep', 'dont_touch'):
        value = attributes.get(name, '0')
        assert isinstance(value, (str, int)), ('Unknown retention value', name, value)
        if isinstance(value, str):
            assert re.fullmatch('[01]+', value), ('Unknown retention value', name, value)
            value = int(value, 2)
        if value:
            return True
    return False


def integer_bits(bits):
    assert all(type(bit) is int or bit in ('0', '1', 'x', 'z') for bit in bits), 'Unknown RTLIL bit'
    return {bit for bit in bits if type(bit) is int}


def module_graph(body):
    """Overapproximate all combinational and future-state dependencies."""
    roots, drivers, sinks, inputs, outputs = set(), defaultdict(set), defaultdict(set), {}, {}
    root_kinds = defaultdict(int)
    for port in body['ports'].values():
        assert port['direction'] in ('input', 'output', 'inout'), 'Unknown module direction'
        if port['direction'] in ('output', 'inout'):
            bits = integer_bits(port['bits'])
            roots.update(bits)
            root_kinds['module_output_or_inout_bits'] += len(bits)
    for net in body['netnames'].values():
        if retained(net.get('attributes', {})):
            bits = integer_bits(net['bits'])
            roots.update(bits)
            root_kinds['retained_net_bits'] += len(bits)
    for name, cell in body.get('cells', {}).items():
        assert set(cell['connections']) == set(cell['port_directions']), ('Unknown or extra cell pin direction', name)
        ins, outs = set(), set()
        for pin, bits in cell['connections'].items():
            direction = cell['port_directions'][pin]
            assert direction in ('input', 'output', 'inout'), ('Unknown cell direction', name, pin)
            wires = integer_bits(bits)
            if direction in ('input', 'inout'):
                ins.update(wires)
            if direction in ('output', 'inout'):
                outs.update(wires)
            if direction == 'inout':
                roots.update(wires)
                root_kinds['cell_inout_bits'] += len(wires)
        inputs[name], outputs[name] = ins, outs
        for bit in ins:
            sinks[bit].add(name)
        for bit in outs:
            drivers[bit].add(name)
        # An outputless cell can write a memory, assert, print, terminate, or
        # have another side effect. It must never be classified as dead merely
        # because it has no output wire. Constant-output cells are treated the
        # same way, conservatively.
        if not outs or retained(cell.get('attributes', {})):
            roots.update(ins | outs)
            root_kinds['side_effect_or_retained_cell_bits'] += len(ins | outs)
    live = set(roots)
    queue, live_cells = list(roots), set()
    while queue:
        for name in drivers[queue.pop()]:
            if name not in live_cells:
                live_cells.add(name)
                for bit in inputs[name] - live:
                    live.add(bit)
                    queue.append(bit)
    return roots, live, live_cells, sinks, outputs, dict(root_kinds)


def audit_cones(before, after, notices):
    inventory = capture.fanout_inventory(before, notices)
    grouped = defaultdict(list)
    for item in inventory:
        grouped[item['module']].append(item)
    results = []
    for module, warnings in sorted(grouped.items()):
        assert module in after['modules'], ('Removed whole warning module', module)
        body = before['modules'][module]
        roots, live, live_cells, sinks, outputs, root_kinds = module_graph(body)
        bits = {item['export_bit'] for item in warnings}
        assert len(bits) == len(warnings), 'Aliased or repeated warning bits'
        assert not bits & live, ('Warning can reach observable output/state/side effect', module, sorted(bits & live))
        reachable_bits, queue, reachable_cells = set(bits), list(bits), set()
        while queue:
            for name in sinks[queue.pop()]:
                if name not in reachable_cells:
                    reachable_cells.add(name)
                    for bit in outputs[name] - reachable_bits:
                        reachable_bits.add(bit)
                        queue.append(bit)
        assert not reachable_bits & roots and not reachable_cells & live_cells
        unknown = {body['cells'][name]['type'] for name in reachable_cells} - PURE_CONE_TYPES
        assert not unknown, ('Unknown side effects in dead cone', module, sorted(unknown))
        still_present = reachable_cells & after['modules'][module].get('cells', {}).keys()
        assert not still_present, ('Warning cone remains after opt_clean', module, sorted(still_present))
        direct = {consumer[1] for item in warnings for consumer in item['consumers'] if consumer[0] == 'cell_pin'}
        assert all(consumer[0] == 'cell_pin' for item in warnings for consumer in item['consumers'])
        results.append(dict(module=module, warning_bits=len(warnings),
                            actual_direct_consumers=sum(item['direct_consumer_count'] for item in warnings),
                            direct_consumer_cells=len(direct), dead_cone_cells=len(reachable_cells),
                            dead_cone_types=dict(sorted(Counter(
                                body['cells'][name]['type'] for name in reachable_cells).items())),
                            dead_cone_cell_names=sorted(reachable_cells),
                            conservative_live_cells=len(live_cells), root_kinds=root_kinds,
                            no_path_to_any_observable_root=True, entire_cone_removed_after_opt_clean=True))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-report', type=Path, default=Path(PARENT))
    args = parser.parse_args()
    path = capture.mapper.replay.workspace_path(args.capture_report)
    parent = json.loads(path.read_text())
    assert parent['status'] == 'CAPTURED_FULL_BOARD_INITIAL_DRIVER_FANOUT_DIAGNOSTIC_ONLY'
    assert parent['stage'] == 'complete' and parent['finished_utc']
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert parent['initial_driver_notices'] == 288 and parent['checks_problem_counts'] == [288, 0]
    assert all(step['returncode'] == 0 and step['status'] == 'PASS_TOOL_EXECUTION_ONLY' for step in parent['commands'])
    original_path = ROOT / parent['original_report']
    original = json.loads(original_path.read_text())
    assert original['status'] == 'FAIL' and original['tool_version'] == parent['tool_version']
    paths = {path, original_path, Path(__file__).resolve(), Path(capture.__file__).resolve()}
    for report, fields in ((parent, ('source', 'artifacts')), (original, ('source', 'compile_inputs', 'artifacts'))):
        for field in fields:
            bound = [ROOT / name for name in report[field]['files']]
            assert fingerprint(bound) == report[field], ('Changed capture or original evidence', field)
            paths.update(bound)
    source = fingerprint(paths)
    out = ROOT / f'build/rknpu-dsp-prefix-initial-driver-cones/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='connectivity_proof', started_utc=timestamp(), source=source,
                  capture_report=str(path.relative_to(ROOT)), tool_version=parent['tool_version'],
                  channels=32, kernels=16, parallel_products=512,
                  mapping_diagnostics_accepted=False, numerical_netlist_acceptance=False,
                  physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
                  scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    print(out / 'report.json', flush=True)
    try:
        directory = path.parent
        assert (directory / 'frontend_capture.ys').read_text() == capture.frontend_capture_script(
            (original_path.parent / 'mapping.ys').read_text(), directory)
        before = json.loads((directory / 'after_proc.json').read_text())
        after = json.loads((directory / 'after_clean.json').read_text())
        expected = capture.driver_notices((original_path.parent / 'mapping.log').read_text())
        assert sum(expected.values()) == 288
        assert capture.driver_notices((directory / 'frontend.log').read_text()) == expected
        inventory = normalized_inventory(before, expected)
        assert inventory == parent['initial_driver_fanout']
        assert parent['all_initial_notice_bits_have_no_direct_consumers'] is False
        assert all(item['direct_consumer_count'] > 0 for item in inventory)
        partition = json.loads((original_path.parent / 'cmac_partition.json').read_text())
        spec, _ = capture.mapper.inputs()
        assert capture.frontend.validate_frontend(after, spec['top'], original['preserved_kernel'], partition) == parent['compiled_hierarchy']
        report['dead_cone_audit'] = audit_cones(before, after, expected)
        assert sum(item['warning_bits'] for item in report['dead_cone_audit']) == 288
        try:
            capture.mapper.audit_board_mapping_log((original_path.parent / 'mapping.log').read_text(),
                                                  spec['top'], original['preserved_kernel'])
        except AssertionError as error:
            assert 'Unknown whole-board source diagnostics' in str(error)
        else:
            raise AssertionError('Original warning gate unexpectedly accepted')
        assert fingerprint(paths) == source
        report.update(status='PASS_SOURCE_BOUND_INITIAL_DRIVER_DEAD_CONES_ONLY', stage='complete',
                      verified_warning_bits=288, original_warning_gate_unchanged=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()


if __name__ == '__main__':
    main()
