#!/usr/bin/env python3
"""Freshly qualify the counter-safe HeAP engine on its exact strict-search parent.

Keep the existing native legality, refinement, LUT, beta-inspection, DSP/BRAM,
clock-feature and timeout gates. Replace only the stale parent admission with
the explicitly source-bound strict-search reports supplied on the command line.
This is small native qualification, not full fit or physical signoff.
"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_current_counter_safe_heap as parent
import build_heap_attempt_limit_candidate as heap
import qualify_counter_safe_heap as qualify


def report_path(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(heap.ROOT / 'build/openxc7') and path.name == 'report.json'
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', type=Path, required=True)
    parser.add_argument('--strict-build-report', type=Path, required=True)
    parser.add_argument('--strict-qualification-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    parser.add_argument('--arithmetic-report', type=Path, required=True)
    args = parser.parse_args()

    build_report = report_path(args.build_report)
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
    qualify.first.admit = lambda: parent.verify_strict_parent(
        strict_qualification, strict_build, native, identity)
    qualify.NAMESPACE['CONTROL'] = qualify.CONTROL
    sys.argv = [sys.argv[0], '--build-report', str(build_report)]
    qualify.main()


if __name__ == '__main__':
    main()
