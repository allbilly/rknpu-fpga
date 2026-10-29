#!/usr/bin/env python3
"""Qualify a strict-search build against explicit fresh DSP/identity parents.

This dispatcher changes only which completed parent reports the original
qualifier receives. Its illegal-pair, normal-refinement, placement, FASM,
feature and timeout gates are unchanged. It selects the already-tested native
two-pass log parser because StaticPlacer runs separate DSP/BRAM and logic
legalization passes; it does not qualify full placement.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_strict_search_candidate as build
import qualify_strict_search_candidate as qualify
import qualify_strict_search_rounds as rounds
import verify_corrected_native_evidence as verifier


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    args = parser.parse_args()
    build_path = args.build_report.resolve(strict=True)
    native_path = args.native_report.resolve(strict=True)
    identity_path = args.identity_report.resolve(strict=True)
    for path in (build_path, native_path, identity_path):
        assert path.is_relative_to(build.ROOT / 'build/openxc7') and path.name == 'report.json'
    native = json.loads(native_path.read_text())
    identity = json.loads(identity_path.read_text())
    built = json.loads(build_path.read_text())
    build.verify_build_metadata(built)
    assert native['status'] == verifier.QUALIFIED and native['stage'] == 'complete'
    assert identity['status'] == verifier.IDENTIFIED and identity['finished_utc']
    assert identity['selected_qualification_report'] == str(native_path)
    assert identity['selected_qualification_report_sha256'] == digest(native_path)
    assert built['corrected_parent_qualification'] == str(native_path)
    qualify.check_strict_log = rounds.check_strict_log
    qualify.CONTROL = build.ROOT / 'tests/cmac/test_strict_search_log_multipass.py'
    qualify.NATIVE = native_path
    qualify.verify_corrected_evidence = lambda: verifier.verify_corrected_evidence(native_path, identity_path)
    build.NATIVE = native_path
    build.verify_corrected_evidence = lambda: verifier.verify_corrected_evidence(native_path, identity_path)
    sys.argv = [sys.argv[0], '--build', str(build_path)]
    qualify.main()


if __name__ == '__main__':
    main()
