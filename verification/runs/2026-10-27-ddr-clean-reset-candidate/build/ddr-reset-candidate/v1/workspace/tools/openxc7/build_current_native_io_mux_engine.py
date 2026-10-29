#!/usr/bin/env python3
"""Build the native-I/O mux candidate on the freshly qualified HeAP parent.

Retain the existing explicit four-state test, wrong-output negative, packer
transition, parent relink and native pack probes. Select only the current
counter-safe HeAP build/qualification reports; this remains build/pack evidence,
not native placement or full physical acceptance.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_current_counter_safe_heap as parent
import build_heap_attempt_limit_candidate as heap
import build_mux_feedthrough_candidate as mux_build
import build_native_io_mux_feedthrough_candidate as mux
import qualify_counter_safe_heap as heap_qualification


def report_path(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(heap.ROOT / 'build/openxc7') and path.name == 'report.json'
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counter-build-report', type=Path, required=True)
    parser.add_argument('--counter-qualification-report', type=Path, required=True)
    parser.add_argument('--strict-build-report', type=Path, required=True)
    parser.add_argument('--strict-qualification-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    parser.add_argument('--arithmetic-report', type=Path, required=True)
    args = parser.parse_args()

    counter_build = report_path(args.counter_build_report)
    counter_qualification = report_path(args.counter_qualification_report)
    strict_build = report_path(args.strict_build_report)
    strict_qualification = report_path(args.strict_qualification_report)
    native = report_path(args.native_report)
    identity = report_path(args.identity_report)
    arithmetic = report_path(args.arithmetic_report)

    # Reuse the exact parent admission used for the counter-safe build and its
    # fresh native qualification. No old saved-placement result is substituted.
    heap.PARENT = strict_build
    heap.QUALIFICATION = strict_qualification
    heap.ARITHMETIC = arithmetic
    heap.verify_qualification = lambda path: parent.verify_strict_parent(
        path, strict_build, native, identity)
    heap_qualification.first.admit = lambda: parent.verify_strict_parent(
        strict_qualification, strict_build, native, identity)

    for namespace in (mux_build.__dict__, mux.previous.NAMESPACE, mux.NAMESPACE):
        namespace['PARENT'] = counter_build
        namespace['QUALIFICATION'] = counter_qualification
        namespace['verify_qualification'] = heap_qualification.verify_qualification
    sys.argv = [sys.argv[0]]
    mux.main()


if __name__ == '__main__':
    main()
