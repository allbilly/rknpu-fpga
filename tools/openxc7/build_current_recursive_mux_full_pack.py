#!/usr/bin/env python3
"""Pack the full C32/K16 input using the freshly qualified recursive-mux engine.

Keep the existing complete input, 515-DSP, DSP/tie, clock and LUT-capacity
checks. Admit only the explicit fresh recursive-mux qualification and preserve
the old full-DSP encoder certificate as a separate baseline.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_current_counter_safe_heap as parent
import build_heap_attempt_limit_candidate as heap
import build_mux_feedthrough_candidate as mux_build
import build_native_io_mux_feedthrough_candidate as mux
import pack_recursive_mux_prefix_shared_board as packer
import qualify_counter_safe_heap as heap_qualification
import qualify_recursive_mux_feedthrough as qualification

ROOT = packer.ROOT
CONTROL = ROOT / 'tests/cmac/test_current_recursive_mux_full_pack_admission.py'
LEGACY_CONTROL = ROOT / 'tests/cmac/test_recursive_mux_full_pack_control.py'


def report_path(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(heap.ROOT / 'build/openxc7') and path.name == 'report.json'
    return path


def historical_certificate_binding(path):
    """Retain an old certificate by exact report identity, not stale runtime inputs."""
    path = Path(path).resolve(strict=True)
    assert path == packer.previous.QUALIFICATION.resolve(strict=True)
    legacy = json.loads(path.read_text())
    packer.previous.validate_qualification(legacy)
    return {str(path): packer.previous.digest(path)}


def admit_current_qualification(path):
    """Revalidate the fresh engine fully; bind the old certificate as history only."""
    path = report_path(path)
    report = json.loads(path.read_text())
    qualification.verify_metadata(report)

    # This report documents the earlier full-DSP encoder certificate. Its old
    # /usr/bin/python3.14 interpreter is no longer a current pack input; the
    # fresh native/DSP/identity chain is fully rebound by verify_qualification.
    legacy_bindings = historical_certificate_binding(packer.previous.QUALIFICATION)
    admitted, before = qualification.verify_qualification(path)
    assert admitted == report and report['executable'] != report['qualified_parent_executable']
    candidate = qualification.candidate
    built = json.loads(Path(report['build_report']).read_text())
    candidate.verify_metadata(built)
    parent_report = json.loads(candidate.PARENT.read_text())
    link = next(step for step in parent_report['commands'] if step['label'] == 'link_counter_safe_heap')
    changed = next(step for step in built['commands'] if step['label'] == 'link_recursive_mux_feedthrough')
    assert changed['argv'] == candidate.link_argv(link['argv'], Path(built['executable']['path']),
        {candidate.OBJECT: Path(report['build_report']).parent / 'pack.cc.o'})
    assert changed['cwd'] == link['cwd'], 'Changed qualified native link context'
    candidate.heap.merge(before, legacy_bindings)
    candidate.heap.merge(before, {str(LEGACY_CONTROL): candidate.digest(LEGACY_CONTROL)})
    qualification.verify_bindings(before)
    return admitted, before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--counter-build-report', type=Path, required=True)
    parser.add_argument('--counter-qualification-report', type=Path, required=True)
    parser.add_argument('--strict-build-report', type=Path, required=True)
    parser.add_argument('--strict-qualification-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    parser.add_argument('--arithmetic-report', type=Path, required=True)
    args = parser.parse_args()

    mux_qualification = report_path(args.qualification)
    prepared = report_path(args.prepared)
    counter_build = report_path(args.counter_build_report)
    counter_qualification = report_path(args.counter_qualification_report)
    strict_build = report_path(args.strict_build_report)
    strict_qualification = report_path(args.strict_qualification_report)
    native = report_path(args.native_report)
    identity = report_path(args.identity_report)
    arithmetic = report_path(args.arithmetic_report)

    heap.PARENT = strict_build
    heap.QUALIFICATION = strict_qualification
    heap.ARITHMETIC = arithmetic
    heap.verify_qualification = lambda path: parent.verify_strict_parent(
        path, strict_build, native, identity)
    heap_qualification.first.admit = lambda: parent.verify_strict_parent(
        strict_qualification, strict_build, native, identity)
    heap_qualification.first.PARENT = strict_qualification

    for namespace in (mux_build.__dict__, mux.previous.NAMESPACE, mux.NAMESPACE):
        namespace['PARENT'] = counter_build
        namespace['QUALIFICATION'] = counter_qualification
        namespace['verify_qualification'] = heap_qualification.verify_qualification
    qualification.candidate.PARENT = counter_build
    qualification.candidate.QUALIFICATION = counter_qualification
    packer.CONTROL = CONTROL
    packer.admit_qualification = admit_current_qualification
    packer.NAMESPACE['CONTROL'] = CONTROL
    packer.NAMESPACE['admit_qualification'] = admit_current_qualification
    sys.argv = [sys.argv[0], '--prepared', str(prepared),
                '--qualification', str(mux_qualification)]
    packer.main()


if __name__ == '__main__':
    main()
