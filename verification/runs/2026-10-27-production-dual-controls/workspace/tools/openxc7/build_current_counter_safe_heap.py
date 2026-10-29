#!/usr/bin/env python3
"""Build a counter-safe HeAP variant from an explicitly qualified strict-search engine.

Keep the existing isolated HeAP build procedure, arithmetic fixtures, native
checks and limits. Select only fresh strict-search build/qualification reports
as the parent; this does not run native qualification or full placement.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_heap_attempt_limit_candidate as heap
import qualify_current_strict_search_engine as strict


def report_path(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(heap.ROOT / 'build/openxc7') and path.name == 'report.json'
    return path


def verify_strict_parent(qualification_path, build_path, native_path, identity_path):
    qualification_path = report_path(qualification_path)
    build_path = report_path(build_path)
    native_path = report_path(native_path)
    identity_path = report_path(identity_path)
    native = json.loads(native_path.read_text())
    identity = json.loads(identity_path.read_text())
    built = json.loads(build_path.read_text())
    strict.build.verify_build_metadata(built)
    assert native['status'] == strict.verifier.QUALIFIED and native['stage'] == 'complete'
    assert identity['status'] == strict.verifier.IDENTIFIED and identity['finished_utc']
    assert identity['selected_qualification_report'] == str(native_path)
    assert identity['selected_qualification_report_sha256'] == strict.digest(native_path)
    assert built['corrected_parent_qualification'] == str(native_path)

    qualifier = strict.qualify
    qualifier.check_strict_log = strict.rounds.check_strict_log
    qualifier.CONTROL = heap.ROOT / 'tests/cmac/test_strict_search_log_multipass.py'
    qualifier.NATIVE = native_path
    qualifier.verify_corrected_evidence = lambda: strict.verifier.verify_corrected_evidence(
        native_path, identity_path)
    strict.build.NATIVE = native_path
    strict.build.verify_corrected_evidence = lambda: strict.verifier.verify_corrected_evidence(
        native_path, identity_path)
    result, before = qualifier.verify_qualification(qualification_path)
    assert result['candidate_build_report'] == str(build_path)
    return result, before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict-build-report', type=Path, required=True)
    parser.add_argument('--strict-qualification-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    parser.add_argument('--arithmetic-report', type=Path, required=True)
    args = parser.parse_args()
    strict_build = report_path(args.strict_build_report)
    strict_qualification = report_path(args.strict_qualification_report)
    native = report_path(args.native_report)
    identity = report_path(args.identity_report)
    arithmetic = report_path(args.arithmetic_report)

    heap.PARENT = strict_build
    heap.QUALIFICATION = strict_qualification
    heap.ARITHMETIC = arithmetic
    heap.verify_qualification = lambda path: verify_strict_parent(
        path, strict_build, native, identity)
    sys.argv = [sys.argv[0]]
    heap.main()


if __name__ == '__main__':
    main()
