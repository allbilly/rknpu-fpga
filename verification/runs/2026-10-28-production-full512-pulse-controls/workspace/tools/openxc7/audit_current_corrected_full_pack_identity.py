#!/usr/bin/env python3
"""Run the existing full-pack identity audit against an explicit fresh report.

The underlying comparator and all acceptance checks remain unchanged. This
small dispatcher makes the selected qualification report explicit and binds
its exact bytes into the resulting audit report; it does not modify the
historical baseline or claim placement/route/signoff.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_corrected_full_pack_identity as audit

QUALIFIED_NATIVE = 'PASS_ISOLATED_CORRECTED_DSP_NATIVE_PACK_AND_SMALL_LEGAL_PNR_FASM_CONTROLS_NOT_FULL_ROUTE_OR_SIGNOFF'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class Tee:
    def __init__(self, target):
        self.target = target
        self.buffer = io.StringIO()

    def write(self, value):
        self.target.write(value)
        self.target.flush()
        return self.buffer.write(value)

    def flush(self):
        self.target.flush()
        self.buffer.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-report', type=Path, required=True)
    args = parser.parse_args()
    native = args.native_report.resolve(strict=True)
    assert native.is_relative_to(audit.ROOT / 'build/openxc7') and native.name == 'report.json'
    selected = json.loads(native.read_text())
    assert selected['status'] == QUALIFIED_NATIVE
    assert selected['stage'] == 'complete' and selected['finished_utc']
    audit.NATIVE = native

    captured = Tee(sys.stdout)
    with contextlib.redirect_stdout(captured):
        audit.main()
    paths = [line.strip() for line in captured.buffer.getvalue().splitlines() if line.strip()]
    assert paths, 'Underlying audit did not return its report path'
    report_path = Path(paths[-1]).resolve(strict=True)
    assert report_path.is_relative_to(audit.ROOT / 'build/openxc7')
    report = json.loads(report_path.read_text())
    expected_status = ('PASS_FULL_PACKED_LOGICAL_IDENTITY_EXCEPT_EXACT_DSP_TILE_CONSTANT_REPRESENTATION_NOT_PLACEMENT_TRANSFER_OR_SIGNOFF')
    assert report['status'] == expected_status
    report['selected_qualification_report'] = str(native)
    report['selected_qualification_report_sha256'] = digest(native)
    report['source'][str(native)] = report['selected_qualification_report_sha256']
    audit.verify_bindings(report['source'])
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(report_path)


if __name__ == '__main__':
    main()
