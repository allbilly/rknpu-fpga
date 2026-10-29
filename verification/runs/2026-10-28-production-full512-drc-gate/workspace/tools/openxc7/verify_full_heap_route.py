"""Read-only full HeAP route admission; never accept a small/prepared PASS.

Revalidate actual placement/engine/native v2 qualification parents and the
full route command, scan, logical/physical identity, all DSP/BRAM features
and actual clock PIP contracts. No route/placement/repack, circuit repair,
physical signoff, bitstream or programming occurs here.
"""
import json
from pathlib import Path

import route_native_heap_board as route
from evidence import source_revision
from place_prefix_board import bind_report,verify_bindings
from pack_prefix_board import ROOT,digest


def verify_metadata(r):
    assert r['status']==route.ROUTED and r['stage']=='complete' and r['finished_utc']
    assert (r['channels'],r['kernels'],r['parallel_products'],r['intended_part'],
            r['intended_clock_period_ns'],r['seed'])==(32,16,512,'xc7k480tffg1156-2',20,3588)
    assert all(r[k] is False for k in route.previous.original.FLAGS)
    for k in ('native_routing_executed','full_native_imported_checkpoint_scan_executed','full_native_FASM_emitted',
              'full_DSP_BRAM_source_defined_features_compared','native_v2_literal_LUT_output_declarations_imported',
              'placement_engine_not_executed_during_route','placement_and_route_share_corrected_DSP_base'):
        assert r[k] is True,'Incomplete full-route evidence: '+k
    assert r['full_bound_cells']==538118
    resource=r['physical_resource_checks'];groups=resource['retained_kernel_dsps']
    assert resource['unchanged_physical_bel_assignments']==538118
    assert len(groups)==16 and set(groups.values())=={32}
    assert r['original_logical_circuit_identity']['logical_board']['cells']==538118
    compared=r['full_DSP_BRAM_FASM_feature_comparison']
    assert compared['selected_primitives_compared']==521 and len(compared['primitive_checks'])==521
    assert compared['kernel_dsps']==groups and compared['corrected_DSP_tile_pins_compared']==4120
    assert compared['clock_contracts_from_actual_routed_module']==r['full_native_clock_fanout_contracts']
    assert r['full_native_clock_fanout_contracts']
    assert r['production_source_before']==r['production_source_after']
    assert r['constraint_translation']['target_period_ns']==20.0
    assert r['constraint_translation']['signoff_constraint_profile'] is False
    labels=['software_controls','generated_check','version','linked_router_check','native_scan_and_route']
    assert [c['label'] for c in r['commands']]==labels
    assert all(c['status']=='PASS_TOOL_EXECUTION_ONLY' and c['returncode']==c['expected_returncode']==0
               for c in r['commands'])


def own_file(path,r,field,before):
    value=(ROOT/r[field]).resolve(strict=True)
    assert value.is_relative_to(path.parent) and str(value) in before,'Unbound/outside full-route artifact'
    return value


def verify_route(path):
    path=Path(path).resolve(strict=True);assert path.is_relative_to(ROOT/'build/openxc7')
    r=json.loads(path.read_text());verify_metadata(r)
    assert r['production_source_after']==source_revision(),'Changed production source'
    placed_path=Path(r['placed_report']).resolve(strict=True);placed=json.loads(placed_path.read_text())
    route.verify_placed_metadata(placed)
    candidate,before=route.placement.qualified.verify_qualification(Path(placed['qualified_engine_report']))
    bind_report(placed_path,placed,before);route.verify_placed_native_evidence(placed,placed_path)
    support,built=route.previous.verify_qualification(before)
    placing_build=route.placement_build(candidate,before)
    assert Path(placing_build['parent_build_report'])==Path(built['parent_build_report'])
    assert r['executable']==support['executable'] and r['native_version']==support['native_version']
    assert r['production_source_after']==placed['production_source_after']==support['production_source_after']
    bind_report(path,r,before);verify_bindings(before)
    output=own_file(path,r,'routed_design',before);fasm=own_file(path,r,'native_FASM',before)
    placements=path.parent/'native-placement.json';assert str(placements) in before
    input_path=(ROOT/placed['placed_design']).resolve(strict=True)
    assert r['hardware_execution_input']==str(input_path) and str(input_path) in before
    xdc=path.parent/'literal.xdc';assert str(xdc) in before
    checker=route.previous.original.checker
    argv=checker.checkpoint.resume_argv(r['executable']['path'],input_path,
        r['checkpoint_label_translation']['emitted_context_label'],xdc,output,route=True)
    argv+=['-o',route.previous.NEW_PROFILE,'-o','fasm='+str(fasm),'-o','placement='+str(placements)]
    c=r['commands'][-1];assert c['argv']==argv and c['timeout_seconds']==43200
    log=Path(c['log']).resolve(strict=True);assert log.is_relative_to(path.parent) and str(log) in before
    text=log.read_text();route.check_full_scan(text,538118,r['fixed_logic_pairs'],r['expected_local_carry_DI_roles'])
    route.previous.check_import_count(text,r['literal_disconnected_LUT_outputs'])
    for command in r['commands']:
        text=Path(command['log']).read_text()
        assert not route.previous.original.re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing',text)
    for name,sha in r['comparison_artifact_bindings'].items():assert digest(ROOT/name)==sha
    design=json.loads(output.read_text());labels=r['checkpoint_label_translation']
    assert design['creator']==labels['producer'] and list(design['modules'])==[labels['emitted_context_label']]
    module=next(iter(design['modules'].values()));del design
    footprints=json.loads((path.parent/'comparison-only-physical-footprint.json').read_text())
    groups=r['physical_resource_checks']['retained_kernel_dsps']
    assert route.previous.original.verify_routed_footprint(module,footprints,groups)==r['physical_resource_checks'];del footprints
    contracts=route.clock_contracts(module);assert contracts==r['full_native_clock_fanout_contracts']
    design=json.loads(input_path.read_text())
    original_module,original_labels=route.previous.original.native_export_module(design,r['native_version'])
    assert original_labels==labels
    ports=original_module['ports'];del design,original_module
    empty=json.loads((path.parent/'comparison-only-empty-port-source.json').read_text())
    view,annotations=route.previous.original.full_export_view(empty,module)
    assert annotations==r['comparison_only_empty_port_annotations']
    canonical=route.previous.original.proof_module(view,ports);del module,view,empty
    identity=route.previous.original.assert_circuit_identity(
        json.loads((path.parent/'comparison-only-logical-input.json').read_text()),canonical);del canonical
    assert identity==r['original_logical_circuit_identity']
    selected=json.loads(checker.checkpoint.SELECTED.read_text())
    assert route.verify_full_features(fasm,placements,output,selected,groups,contracts)==r['full_DSP_BRAM_FASM_feature_comparison']
    verify_bindings(before)
    return r,before,fasm,placements,contracts
