#!/usr/bin/env python3
"""Read-only union-fanin opportunities on a completed shared-and-paired board.

The private-original-array admission rule is not changed. This analyzer uses
the actual three-module board boundary; it does not validate arbitrary masks,
transform a netlist, rerun parent circuit proofs or establish physical fit.
"""
from collections import Counter
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from analyze_union_lut_pairs import proposals, verify_proposals
from audit_lut_pair_sinks import audit_module, multiplicities, DOCS
from prepare_shared_board import PRIVATE, SHARED, physical_counts
from test_fixed_array_board import verify_manifest
from test_paired_mapped_array import validate_pair_metadata, validate_pair_proof_metadata

TOP = 'ypcb_cmac_array_top'
IMPLEMENTATIONS = {TOP, PRIVATE, SHARED}


def validate_shared_metadata(report):
    assert report['status'] == 'PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY', 'Completed shared-cone board required'
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert report['circuit_lift_verified'] is True
    assert report['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    for key in ('numerical_netlist_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False, 'Misrepresented shared-board acceptance'
    commands = report['commands']
    assert [Path(c['log']).stem for c in commands] == ['version', 'export', 'elaborate_check']
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in commands)


def validate_counts(modules, report):
    copies = multiplicities(modules, TOP, IMPLEMENTATIONS)
    assert copies == Counter({TOP: 1, PRIVATE: 16, SHARED: 1}), 'Changed board sharing boundary'
    counts = dict(physical_counts(modules, TOP, IMPLEMENTATIONS))
    assert counts == report['cells_after'], 'Changed actual candidate resources'
    assert sum(v for k, v in counts.items() if k.startswith('LUT')) == report['lut_count']
    assert counts.get('LUT6_2', 0) == report['physical_lut_pairs']
    return copies


def load_parent(path):
    assert path.is_relative_to(ROOT)
    pair = json.loads(path.read_text())
    # Refuse running/failed/private parents before allocating an output directory.
    validate_pair_metadata(pair)
    shared_path = ROOT / pair['parent_report']
    assert shared_path.resolve().is_relative_to(ROOT)
    shared = json.loads(shared_path.read_text()); validate_shared_metadata(shared)
    assert shared['source']['sha256'] == pair['parent_source_sha256']
    assert shared['tool_version'] == pair['tool_version']
    assert pair['cells_before'] == shared['cells_after']
    for report in (pair, shared):
        verify_manifest(report['source']); verify_manifest(report['artifacts'])
    validate_pair_proof_metadata(pair, path.parent)
    for field in ('function_class_inputs', 'function_class_executables'):
        for manifest in pair[field].values(): verify_manifest(manifest)
    original_path = ROOT / shared['mapping_report']
    assert original_path.resolve().is_relative_to(ROOT)
    original = json.loads(original_path.read_text())
    assert original['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert (original['channels'], original['kernels'], original['parallel_products']) == (32, 16, 512)
    assert shared['mapping_source_sha256'] == original['source']['sha256']
    assert shared['cells_before'] == original['cells']
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in original['commands'])
    verify_manifest(original['source']); verify_manifest(original['artifacts'])
    candidate_path = path.parent / 'paired_hierarchy.json'
    assert str(candidate_path.relative_to(ROOT)) in pair['artifacts']['files']
    modules = json.loads(candidate_path.read_text())['modules']
    copies = validate_counts(modules, pair)
    return pair, modules, copies, [path, shared_path, original_path, candidate_path]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paired-report', required=True, type=Path)
    args = parser.parse_args()
    parent_path = args.paired_report.resolve()
    pair, modules, copies, dependencies = load_parent(parent_path)
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), *dependencies, *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-shared-union-lut-opportunities/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='selection', started_utc=timestamp(),
        source=before, python_version=sys.version,
        seed='none; deterministic size/subset/name greedy order',
        parent_report=str(parent_path.relative_to(ROOT)), channels=32, kernels=16, parallel_products=512,
        implementation_copies=dict(copies), candidate_lut_primitives=pair['lut_count'],
        source_documents=DOCS, nominal_part_lut_sites=298600,
        netlist_changed=False, function_classes_hdl_acceptance=False, numerical_netlist_acceptance=False,
        packed_resource_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False,
        scope='Read-only actual completed shared-and-paired board opportunities. Three-module board boundary, exact current parent source/artifact/proof-input hashes and admission metadata. Does not rerun parent literal restoration/export/function proofs. Disjoint proposals and direct O6 roles are not maximum matching, transformed circuit acceptance, four-state proof, full-board/array numerical, packed LUT sites, timing/electrical/DRC, bitstream, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    try:
        records, classes, statistics, audits = {}, {}, {}, {}
        weighted, roles = Counter(), Counter()
        for name in sorted(IMPLEMENTATIONS):
            proposed, functions, skipped = proposals(modules[name])
            verify_proposals(modules[name], proposed, functions)
            records[name] = proposed; classes.update(functions)
            statistics[name] = dict(proposed_pairs=len(proposed), **skipped)
            weighted['additional_disjoint_pairs'] += copies[name] * len(proposed)
            audits[name] = audit_module(modules[name])
            for item in audits[name]:
                roles['pairs'] += copies[name]
                for field in ('o5_has_dedicated_o6_sink', 'both_outputs_need_o6', 'o6_has_dedicated_sink'):
                    roles[field] += int(item[field]) * copies[name]
            print(name, json.dumps(statistics[name], sort_keys=True), flush=True)
        assert roles['pairs'] == pair['physical_lut_pairs']
        paths = [out / 'proposals.json', out / 'function_classes.json', out / 'dedicated_sink_records.json']
        paths[0].write_text(json.dumps(records, indent=2) + '\n')
        paths[1].write_text(json.dumps([classes[k] for k in sorted(classes)], indent=2) + '\n')
        paths[2].write_text(json.dumps(audits, indent=2) + '\n')
        assert fingerprint(tracked) == before, 'Changed shared-board analysis dependency'
        report.update(status='ANALYZED_SHARED_BOARD_UNION_FANIN_LUT_OPPORTUNITIES_ONLY', stage='complete',
            finished_utc=timestamp(), weighted_opportunities=dict(weighted), weighted_roles=dict(roles),
            module_statistics=statistics, unique_proposed_function_classes=len(classes),
            projected_lut_primitives=pair['lut_count'] - weighted['additional_disjoint_pairs'],
            artifacts=fingerprint(paths))
    except BaseException as error:
        report.update(status='FAIL', stage='analysis_failure', finished_utc=timestamp(), error=repr(error))
        raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
