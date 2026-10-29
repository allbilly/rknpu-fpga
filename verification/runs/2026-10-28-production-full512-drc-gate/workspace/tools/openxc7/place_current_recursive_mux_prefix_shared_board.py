#!/usr/bin/env python3
"""Run full placement against the freshly packed recursive-mux C32/K16 graph.

Rebind every parent certificate to the current counter-safe/strict-search/
corrected-DSP chain before qualification. Require the actual completed pack
report as input; retain all full-scope native placement, identity, counter,
clock and 515-DSP/4,120-tie checks. Bind the analytic marker to the compiled
active-root population; the full output still must contain every packed cell
on a unique BEL. This is not routing or physical signoff.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_current_counter_safe_heap as parent
import build_heap_attempt_limit_candidate as heap
import build_mux_feedthrough_candidate as mux_build
import build_native_io_mux_feedthrough_candidate as mux
import place_recursive_mux_prefix_shared_board as placement
import qualify_counter_safe_heap as heap_qualification
import qualify_recursive_mux_feedthrough as qualification
import audit_recursive_mux_analytic_scope as analytic

ROOT = placement.ROOT
CONTROL = ROOT / 'tests/cmac/test_current_recursive_mux_full_place_control.py'


def report_path(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    return path


def packed_report_path(path):
    path = report_path(path)
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-native-pack-')
    return path


def bind_current_parent_chain(counter_build, counter_qualification, strict_build,
                              strict_qualification, native, identity, arithmetic):
    heap.PARENT = strict_build
    heap.QUALIFICATION = strict_qualification
    heap.ARITHMETIC = arithmetic
    heap.verify_qualification = lambda path: parent.verify_strict_parent(
        path, strict_build, native, identity)
    heap_qualification.first.admit = lambda: parent.verify_strict_parent(
        strict_qualification, strict_build, native, identity)
    heap_qualification.first.PARENT = strict_qualification

    # These modules captured older defaults when imported; all executed copies
    # must point at this run's counter-safe parent and qualification.
    for namespace in (mux_build.__dict__, mux.previous.NAMESPACE, mux.NAMESPACE):
        namespace['PARENT'] = counter_build
        namespace['QUALIFICATION'] = counter_qualification
        namespace['verify_qualification'] = heap_qualification.verify_qualification
    qualification.candidate.PARENT = counter_build
    qualification.candidate.QUALIFICATION = counter_qualification


def admit_current_qualification(path):
    path = report_path(path)
    assert path.parent.name.startswith('recursive-mux-feedthrough-qualification-')
    report = json.loads(path.read_text())
    qualification.verify_metadata(report)
    admitted, before = qualification.verify_qualification(path)
    assert admitted == report
    assert report['executable'] != report['qualified_parent_executable']
    assert report['only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent'] is True
    assert report['counter_safe_HeAP_parent_retained'] is True
    assert report['old_native_result_inherited'] is False
    return admitted, before


def analytic_source_contract(packed):
    """Bind the analytic-root marker to the exact compiled/linked HeAP source."""
    def bound(path):
        path = Path(path).resolve(strict=True)
        assert packed['source'][str(path)] == analytic.digest(path), 'Changed analytic-scope input'
        return path

    qualified = json.loads(bound(packed['encoder_qualification']).read_text())
    qualification.verify_metadata(qualified)
    assert qualified['executable'] == packed['executable']
    built = json.loads(bound(qualified['build_report']).read_text())
    qualification.candidate.verify_metadata(built)
    assert built['executable'] == packed['executable']
    counter_path = bound(Path(built['parent_executable']['path']).parent / 'report.json')
    counter = json.loads(counter_path.read_text())
    assert counter['executable'] == built['parent_executable']
    source = bound(counter_path.parent / 'common/place/placer_heap.cc')
    assert analytic.digest(source) == counter['generated_source_sha256']
    compiles = [step for step in counter['commands']
                if '-c' in step['argv'] and str(source) in step['argv']]
    assert len(compiles) == 1, 'Missing or ambiguous actual HeAP compilation'
    compile_step = compiles[0]
    assert compile_step['status'] == 'PASS_TOOL_EXECUTION_ONLY' and compile_step['returncode'] == 0
    argv = compile_step['argv']
    assert argv.count('-o') == 1
    obj = bound(argv[argv.index('-o') + 1])
    link = analytic.verify_native_link_command(built['commands'], obj, packed['executable']['path'])
    assert link.get('expected_returncode', 0) == 0, 'HeAP link must be a successful build'
    return dict(compiled_source=str(source), compiled_object=str(obj),
                contract=analytic.source_contract(source.read_text()))


def full_log_checks(text, packed):
    """Check active-root scope; the unchanged output guards check every cell."""
    placement.packer.validate_pack(packed)
    placement.check_heap_log(0, text)
    scope = analytic_source_contract(packed)
    pack_log = Path(packed['commands'][-1]['log']).resolve(strict=True)
    assert packed['artifacts'][str(pack_log)] == analytic.digest(pack_log), 'Changed actual pack log'
    checksums = re.findall(r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$', pack_log.read_text())
    assert len(checksums) == 1, 'Missing or ambiguous actual packed checksum'
    count = packed['native_census']['cells']
    observed = analytic.log_observation(text, count, checksums[0])
    limits = re.findall(r'(?m)^Info: Running main analytical placer, max placement attempts per cell = (\d+)\.$', text)
    limit = placement.previous.qualification.build.candidate.limit(count, 8)
    assert limit == 2147483646 and limits == [str(limit)], 'Wrong source-bound counter-safe finite limit'
    return dict(actual_packed_checksum=checksums[0], actual_full_packed_cells=count,
                actual_logged_analytic_active_roots=observed['actual_logged_analytic_active_roots'],
                actual_logged_maximum_attempts_per_cell=limit, finite_counter_rejection_preserved=True,
                old_fixed_packed_census_or_checksum_inherited=False, physical_fit_verified=False,
                analytic_marker_used_as_full_census=False, complete_output_membership_required=True,
                native_analytic_scope=scope)


def validate_current_pack(packed):
    placement.packer.validate_pack(packed)
    analytic_source_contract(packed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packed', type=Path, required=True)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--counter-build-report', type=Path, required=True)
    parser.add_argument('--counter-qualification-report', type=Path, required=True)
    parser.add_argument('--strict-build-report', type=Path, required=True)
    parser.add_argument('--strict-qualification-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    parser.add_argument('--arithmetic-report', type=Path, required=True)
    args = parser.parse_args()

    packed = packed_report_path(args.packed)
    mux_qualification = report_path(args.qualification)
    counter_build = report_path(args.counter_build_report)
    counter_qualification = report_path(args.counter_qualification_report)
    strict_build = report_path(args.strict_build_report)
    strict_qualification = report_path(args.strict_qualification_report)
    native = report_path(args.native_report)
    identity = report_path(args.identity_report)
    arithmetic = report_path(args.arithmetic_report)
    bind_current_parent_chain(counter_build, counter_qualification, strict_build,
                              strict_qualification, native, identity, arithmetic)

    placement.CONTROL = CONTROL
    placement.admit_qualification = admit_current_qualification
    placement.NAMESPACE['CONTROL'] = CONTROL
    placement.NAMESPACE['admit_qualification'] = admit_current_qualification
    placement.NAMESPACE['full_log_checks'] = full_log_checks
    placement.NAMESPACE['validate_pack'] = validate_current_pack
    sys.argv = [sys.argv[0], '--packed', str(packed),
                '--qualification', str(mux_qualification)]
    placement.main()


if __name__ == '__main__':
    main()
