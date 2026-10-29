#!/usr/bin/env python3
"""Build the unchanged strict-search candidate from explicit fresh parents.

This dispatcher selects a newly qualified DSP engine and its exact full-pack
identity audit without modifying the original builder or its checks. The
underlying build still changes only the isolated static-placer object and is
not native-qualified or full-fit evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_strict_search_candidate as build
import verify_corrected_native_evidence as verifier


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--identity-report', type=Path, required=True)
    args = parser.parse_args()
    native_path = args.native_report.resolve(strict=True)
    identity_path = args.identity_report.resolve(strict=True)
    for path in (native_path, identity_path):
        assert path.is_relative_to(build.ROOT / 'build/openxc7') and path.name == 'report.json'
    native = json.loads(native_path.read_text())
    identity = json.loads(identity_path.read_text())
    assert native['status'] == verifier.QUALIFIED and native['stage'] == 'complete'
    assert identity['status'] == verifier.IDENTIFIED and identity['finished_utc']
    assert identity['selected_qualification_report'] == str(native_path)
    assert identity['selected_qualification_report_sha256'] == digest(native_path)
    assert identity['comparison']['cells_compared'] == 538118
    assert identity['comparison']['changed_DSP_records'] == 515
    assert identity['comparison']['source_defined_tile_pin_disconnections_compared'] == 4120
    build.NATIVE = native_path
    build.verify_corrected_evidence = lambda: verifier.verify_corrected_evidence(native_path, identity_path)
    build.main()


if __name__ == '__main__':
    main()
