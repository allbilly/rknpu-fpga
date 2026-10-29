"""Verify this prefix variant's own completed full-array area evidence.

No original DSP/fixed-array result is transferable. These admission and circuit
partition checks are not numerical or physical acceptance by themselves.
"""
from copy import deepcopy
import json

from evidence import ROOT
import map_dsp_prefix_array as array
import replay_dsp_prefix_board as replay
from lane_dsp_library import timing_only_view

CMAC = array.TOP
KERNEL = array.CELL


def validate_area_metadata(report):
    assert report['status'] == 'PASS_FULL_C32K16_DSP_PREFIX_ARRAY_XC7_AREA_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'],
        report['instantiated_lanes'], report['mapped_kernel_instances'], report['dsp_count']) == (32, 16, 512, 512, 16, 512)
    assert report['intended_part'] == 'xc7k480tffg1156-2' and report['target_family'] == 'xc7'
    assert report['cells']['DSP48E1'] == 512
    assert report['lut_count'] == sum(v for k, v in report['cells'].items() if k.startswith('LUT')) > 0
    assert report['ff_count'] == sum(v for k, v in report['cells'].items() if k.startswith('FD')) >= 547
    assert report['original_coarse_stage'] == array.COARSE
    assert report['executed_coarse_stage'] == [s.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for s in array.COARSE if s != 'share']
    replay.command_contract(report, ('version', 'help', 'mapping'))
    diagnostic = report['source_bound_array_mapping_diagnostics']
    assert diagnostic['abc_notice'] == array.ABC_NOTICE
    assert [c['module'] for c in diagnostic['abc_combinational_cuts']] == array.ABC_MODULES
    for cut in diagnostic['abc_combinational_cuts']:
        assert all(type(cut[n]) is int and cut[n] > 0 for n in ('gates', 'wires', 'inputs', 'outputs'))
    for field in ('numerical_acceptance', 'raw_board_numerical_acceptance',
        'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False


def verify_area(path):
    report = json.loads(path.read_text()); validate_area_metadata(report); replay.verify_evidence(report)
    parent_path = replay.workspace_path(report['parent_report'])
    parent = json.loads(parent_path.read_text()); array.validate_parent_metadata(parent); replay.verify_evidence(parent)
    assert report['parent_source_sha256'] == parent['source']['sha256']
    sources = [*array.SOURCES[:-1], array.DSP_CELL, array.DSP_ARRAY]
    for source in (*sources, parent_path):
        assert str(source.relative_to(ROOT)) in report['source']['files'], 'Unbound prefix array prerequisite'
    hierarchy, native_graph, flat_graph = [path.parent / name for name in
        ('mapped_hierarchy.json', 'hierarchy.json', 'mapped.json')]
    for graph in (hierarchy, native_graph, flat_graph):
        assert str(graph.relative_to(ROOT)) in report['artifacts']['files'], 'Missing actual mapping graph'
    elaboration = json.loads(native_graph.read_text())
    array.validate_elaboration(elaboration); array.preparation.validate_geometry(elaboration)
    design = json.loads(hierarchy.read_text())
    counts, audit, kinds = array.validate_partition(design)
    assert dict(counts) == report['cells'] and audit == report['timing_qualifier_counter_audit']
    assert sorted(set(kinds)) == report['mapped_kernel_types']
    flat, flat_audit = array.validate_flat(json.loads(flat_graph.read_text()), counts)
    assert flat == counts and flat_audit == audit
    step = report['commands'][-1]
    assert report['source_bound_array_mapping_diagnostics'] == array.audit_mapping_log(
        replay.workspace_path(step['log']).read_text())
    script = path.parent / 'mapping.ys'
    assert str(script.relative_to(ROOT)) in report['artifacts']['files']
    assert script.read_text() == array.mapping_script(sources, path.parent, report['executed_coarse_stage'])
    assert step['argv'] == ['yosys', '-Q', '-T', '-s', str(script)]
    assert report['compile_inputs']['files'] == {str(p.relative_to(ROOT)): report['artifacts']['files'][str(p.relative_to(ROOT))]
        if p == script else report['source']['files'][str(p.relative_to(ROOT))] for p in (*sources, script)}
    array.validate_sources(); replay.verify_evidence(report); replay.verify_evidence(parent)
    return report, design, hierarchy


def partition(design):
    array.validate_partition(design)
    modules = design['modules']; body = modules[CMAC]
    assert {n: int(v, 2) for n, v in body['parameter_default_values'].items()} == {
        'ATOMIC_C': 32, 'ATOMIC_K': 16, 'TAG_WIDTH': 35}
    kernel = array.kernel_types(modules)[0]
    assert modules[kernel]['attributes']['hdlname'] == KERNEL
    assert {n: int(v, 2) for n, v in modules[kernel]['parameter_default_values'].items()} == {'ATOMIC_C': 32}
    view, _ = timing_only_view(modules)
    counts = array.primitive_counts(view, kernel); assert counts['DSP48E1'] == 32
    # No native replacement, custom arithmetic, pruning or loss of shell state.
    result = dict(design, modules={n: modules[n] for n in (CMAC, kernel)})
    assert result['modules'][kernel] is modules[kernel] and result['modules'][CMAC] is modules[CMAC]
    return result, kernel, counts


def validate_shared_leaf(area, native):
    """Both independent full-array gates must use the same completed leaf."""
    assert replay.workspace_path(area['parent_report']) == replay.workspace_path(native['lane_report'])
    assert area['parent_source_sha256'] == native['lane_source_sha256']
