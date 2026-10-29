#!/usr/bin/env python3
"""Prepared full HeAP checkpoint v2 scan/route, not routing or FPGA signoff.

Admit only a completed source-bound full C32/K16 HeAP placement and its actual
small native qualification. Preserve the v2 literal checkpoint, full imported
BEL/pair/carry scan, router connectivity, logical identity, all 515 DSP/six-BRAM
features, exact part/clock/seed and original resource/time limits. Reuse the
same corrected-DSP native base rather than changing an encoder or a graph.
This wrapper does not relax the original static route admission or alter a
live job, source/input, warning, electrical/DRC/timing gate, checksum manifest
or FPGA. A prepared runner is not a routed result or permission to emit/load.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import route_empty_output_board as previous
import place_native_heap_board as placement
from audit_empty_output_pairs import source_shaped
from check_full_heap_clock_features import verify_full_features
from clock_bound_native_features import clock_contracts, SOURCES as clock_feature_sources

ROOT=previous.original.ROOT
CONTROL=ROOT/'tests/cmac/test_native_heap_route_control.py'
ROUTED='ROUTED_FULL_C32K16_HEAP_CHECKPOINT_V2_SCAN_AND_CONNECTIVITY_NOT_PHYSICAL_SIGNOFF'
OLD_OBJECT="    assert report['changed_static_placer_object'] == 1"
NEW_OBJECT="""    assert report['placement_algorithm']=='heap' and report['native_source_or_executable_changed'] is False
    assert report['commands'][-1]['native_heap_completion_checked'] is True"""
METADATA_NAMESPACE=dict(previous.original.__dict__,PLACED=placement.PLACED)
METADATA_SOURCE=source_shaped(inspect.getsource(previous.original.verify_placed_metadata),((OLD_OBJECT,NEW_OBJECT),))
exec(compile(METADATA_SOURCE,__file__+':same-full-target-placement-admission','exec'),METADATA_NAMESPACE)
verify_placed_metadata=METADATA_NAMESPACE['verify_placed_metadata']


def verify_placed_native_evidence(report,path):
    c=report['commands'][-1];placement.verify_full_argv(c['argv'])
    assert c['argv'][0]==report['executable']['path']
    output=(ROOT/report['placed_design']).resolve(strict=True)
    assert output.is_relative_to(path.parent) and c['argv'][c['argv'].index('--write')+1]==str(output)
    log=Path(c['log']).resolve(strict=True);assert log.is_relative_to(path.parent)
    placement.qualified.check_heap_log(c['returncode'],log.read_text())
    prepared=json.loads(Path(report['prepared_report']).read_text())
    assert c['argv'][c['argv'].index('--json')+1]==str((ROOT/prepared['pack_input']).resolve(strict=True))


def placement_build(candidate,before):
    path=placement.qualified.previous.first.PARENT.resolve(strict=True)
    assert str(path) in before
    static=json.loads(path.read_text())
    assert static['executable']==candidate['executable'] and static['production_source_after']==candidate['production_source_after']
    built_path=Path(static['candidate_build_report']).resolve(strict=True)
    assert str(built_path) in before
    built=json.loads(built_path.read_text());assert built['executable']==candidate['executable']
    return built


def check_full_scan(text,cells,pairs,carry_roles):
    previous.original.check_full_scan(text,cells,pairs,carry_roles)
    for marker in ('Creating initial analytic placement for ','HeAP Placer Time:',
                   'Running simulated annealing placer for refinement.','Running post-placement legalisation...'):
        assert marker not in text,'Checkpoint route unexpectedly ran placement: '+marker


OLD_BUILD="        placing_build = json.loads(Path(candidate['candidate_build_report']).read_text())"
NEW_BUILD='        placing_build = placement_build(candidate,before)'
OLD_BIND='        bind_report(placed_path, placed, before); verify_bindings(before)'
NEW_BIND=OLD_BIND+'''\n        verify_placed_native_evidence(placed,placed_path)
        assert all(str(p) in before and before[str(p)]==digest(p) for p in clock_feature_sources)'''
OLD_CLOCK="        report['physical_resource_checks'] = verify_routed_footprint(module, footprint, placed['placement_checks']['retained_kernel_dsps']); del footprint"
NEW_CLOCK=OLD_CLOCK+"\n        report['full_native_clock_fanout_contracts']=clock_contracts(module)"
OLD_FEATURE="verify_full_features(fasm, placements, output, selected, placed['placement_checks']['retained_kernel_dsps'])"
NEW_FEATURE=OLD_FEATURE[:-1]+", report['full_native_clock_fanout_contracts'])"
REPLACEMENTS=(('full-prefix-literal-empty-v2-scan-route-','full-prefix-heap-literal-empty-v2-scan-route-'),
              (OLD_BUILD,NEW_BUILD),(OLD_BIND,NEW_BIND),(OLD_CLOCK,NEW_CLOCK),(OLD_FEATURE,NEW_FEATURE))
MAIN_SOURCE=source_shaped(previous.MAIN_SOURCE,REPLACEMENTS)
NAMESPACE=dict(previous.original.__dict__,__file__=__file__,__doc__=__doc__,CONTROL=CONTROL,
               SMALL=previous.QUALIFIED,ROUTED=ROUTED,MAIN_SOURCE=MAIN_SOURCE,
               audit_pairs=previous.audit_pairs,local_carry_roles=previous.local_carry_roles,
               literal_outputs=previous.literal_outputs,verify_small_evidence=previous.verify_qualification,
               check_import_count=previous.check_import_count,verify_placed_metadata=verify_placed_metadata,
               verify_placement_engine=placement.qualified.verify_qualification,
               verify_placed_module=placement.verify_placed_module,check_full_scan=check_full_scan,
               placement_build=placement_build,verify_placed_native_evidence=verify_placed_native_evidence,
               verify_full_features=verify_full_features,clock_contracts=clock_contracts,
               clock_feature_sources=clock_feature_sources)
exec(compile(MAIN_SOURCE,__file__+':v2-route-full-HeAP-admission-only','exec'),NAMESPACE)


def main():NAMESPACE['main']()


if __name__=='__main__':main()
