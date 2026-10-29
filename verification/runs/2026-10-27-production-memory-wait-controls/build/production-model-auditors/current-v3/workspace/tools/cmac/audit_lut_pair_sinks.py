#!/usr/bin/env python3
"""Audit actual LUT6_2 dedicated-output consumers, not placed utilization.

UG474 requires O6 for carry S and wide-mux LUT inputs. The local nextpnr
packer can split constrained pairs or insert feed-throughs; raw pair counts
therefore cannot establish physical LUT-site savings. No netlist is edited.
"""
from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from test_paired_mapped_array import validate_pair_parent
from prepare_shared_board import physical_counts

PACKER = ROOT / 'build/reference/nextpnr-xilinx/xilinx/pack.cc'
CARRY_PACKER = PACKER.with_name('pack_carry_xc7.cc')
DOCS = {
    'lut': 'https://docs.amd.com/r/en-US/ug474_7Series_CLB/Look-Up-Table',
    'carry': 'https://docs.amd.com/r/en-US/ug474_7Series_CLB/Carry-Logic',
    'mux': 'https://docs.amd.com/r/en-US/ug474_7Series_CLB/Multiplexers',
    'capacity': 'https://docs.amd.com/v/u/en-US/ds180_7Series_Overview',
}


def audit_module(module):
    """Record every direct carry-S/F7 sink on both outputs of each pair.

    This is a necessary-output-role audit, not a sufficient placement rule.
    A flagged pair may be reoriented, split or buffered by a physical tool;
    none of those changes is assumed to have happened here.
    """
    users = defaultdict(list)
    for name, cell in module['cells'].items():
        kind = cell['type']
        if kind == 'CARRY4':
            assert len(cell['connections']['S']) == 4
            assert cell['port_directions']['S'] == 'input'
            for index, bit in enumerate(cell['connections']['S']):
                if type(bit) is int:
                    users[bit].append(dict(cell=name, kind=kind, pin='S', index=index))
        elif kind == 'MUXF7':
            for pin in ('I0', 'I1'):
                bits = cell['connections'][pin]
                assert len(bits) == 1 and cell['port_directions'][pin] == 'input'
                if type(bits[0]) is int:
                    users[bits[0]].append(dict(cell=name, kind=kind, pin=pin, index=0))
    records = []
    for name, cell in sorted(module['cells'].items()):
        if cell['type'] != 'LUT6_2':
            continue
        assert set(cell['connections']) == {*(f'I{i}' for i in range(6)), 'O5', 'O6'}
        assert set(cell['parameters']) == {'INIT'}
        assert re.fullmatch('[01]{64}', cell['parameters']['INIT'])
        assert cell['connections']['I5'] == ['1'], 'Audit is for the actual two-five-input candidate'
        assert all(len(bits) == 1 for bits in cell['connections'].values())
        assert all(cell['port_directions'][f'I{i}'] == 'input' for i in range(6))
        assert all(cell['port_directions'][pin] == 'output' for pin in ('O5', 'O6'))
        bits = [cell['connections'][pin][0] for pin in ('O5', 'O6')]
        assert all(type(bit) is int for bit in bits) and bits[0] != bits[1]
        roles = {pin: list(users[bit]) for pin, bit in zip(('O5', 'O6'), bits)}
        records.append(dict(cell=name, outputs=dict(zip(('O5', 'O6'), bits)), dedicated_o6_sinks=roles,
            o5_has_dedicated_o6_sink=bool(roles['O5']),
            both_outputs_need_o6=bool(roles['O5'] and roles['O6']),
            o6_has_dedicated_sink=bool(roles['O6'])))
    return records


def multiplicities(modules, top, implementations):
    assert top in implementations and set(implementations) <= set(modules)
    counts = Counter()

    def visit(name, stack):
        assert name not in stack, 'Recursive implementation hierarchy'
        counts[name] += 1
        for cell in modules[name]['cells'].values():
            if cell['type'] in implementations:
                visit(cell['type'], (*stack, name))

    visit(top, ())
    assert set(counts) == set(implementations), 'Unreachable implementation module'
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paired-report', required=True, type=Path)
    args = parser.parse_args()
    parent_path = args.paired_report.resolve()
    assert parent_path.is_relative_to(ROOT)
    # This preserves all existing positive/negative, literal-restoration,
    # source/artifact and export checks. No running/failed parent is admitted.
    parent, original_report, original, candidate, dependencies = validate_pair_parent(parent_path)
    top, kernel = 'ypcb_cmac_array_top', original_report['preserved_kernel']
    implementations = {top, kernel}
    copies = multiplicities(candidate['modules'], top, implementations)
    assert copies == Counter({top: 1, kernel: 16})
    assert dict(physical_counts(candidate['modules'], top, implementations)) == parent['cells_after']
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [parent_path, Path(__file__).resolve(), PACKER, CARRY_PACKER, *dependencies, *imported]
    before = fingerprint(tracked)
    started = timestamp()
    audits = {name: audit_module(candidate['modules'][name]) for name in sorted(implementations)}
    weighted = Counter()
    for name, records in audits.items():
        for item in records:
            weighted['pairs'] += copies[name]
            for key in ('o5_has_dedicated_o6_sink', 'both_outputs_need_o6', 'o6_has_dedicated_sink'):
                weighted[key] += int(item[key]) * copies[name]
    assert weighted['pairs'] == parent['physical_lut_pairs']
    assert fingerprint(tracked) == before, 'Changed audit dependency'
    out = ROOT / f'build/rknpu-lut-pair-sink-audit/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    detail = out / 'dedicated_sink_records.json'
    detail.write_text(json.dumps(audits, indent=2) + '\n')
    report = dict(status='AUDITED_ACTUAL_LUT_PAIR_DEDICATED_SINK_ROLES_ONLY', started_utc=started,
        finished_utc=timestamp(), source=before, parent_report=str(parent_path.relative_to(ROOT)),
        channels=32, kernels=16, parallel_products=512, implementation_copies=dict(copies),
        weighted_roles=dict(weighted), candidate_lut_primitives=parent['lut_count'],
        intended_part='xc7k480tffg1156-2', part_slices=74650, lut_sites_per_slice=4,
        nominal_part_lut_sites=298600, source_documents=DOCS,
        packed_resource_acceptance=False, numerical_netlist_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False, artifacts=fingerprint([detail]),
        scope='Read-only actual completed C32/K16 LUT-pair candidate audit. Dedicated O6 requirements identify reorientation/splitting/feed-through risk; physical tools may change packing and counts. The weighted direct-sink roles and nominal part capacity are not placed utilization, routing/timing/DRC, a numerical test, bitstream, FPGA or RK acceptance.')
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'report.json')
    print(json.dumps(weighted, sort_keys=True))


if __name__ == '__main__':
    main()
