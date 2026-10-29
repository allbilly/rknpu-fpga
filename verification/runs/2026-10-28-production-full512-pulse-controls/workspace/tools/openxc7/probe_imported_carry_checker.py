#!/usr/bin/env python3
"""Qualify the separate local-carry-tag checkpoint checker.

Reuse every original native/identity/feature gate unchanged, add two real
carry-role corruptions and require explicit native role counts. This is
small native verification, not full placement transfer or physical signoff.
No old report, circuit input, expectation or SHA256SUMS file is modified.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_imported_placement_checker as probe
from build_imported_carry_checker import BASE_TEMPLATE, extended_template, local_carry_roles

CONTROL = probe.ROOT / 'tests/cmac/test_imported_carry_checker_probe.py'
OLD_CORRUPT = probe.corrupt_checkpoint
OLD_SCAN_LOG = probe.scan_log
OLD_VERIFY = probe.verify_corrected_evidence
BASE_BUILD = probe.ROOT / 'build/openxc7/imported-placement-checker-engine-1791424380429306004/report.json'
EXTRA_REASONS = {'wrong_local_carry_DI': 'wrong local carry DI role',
                 'local_carry_extra_user': 'native BEL legality rejected'}


def verify_extension_evidence():
    q, before = OLD_VERIFY()
    # The inherited builder binds the generated supplemental template, not
    # this generator reference. Bind/recheck the original and its completed
    # build snapshot independently before native qualification. Do not edit
    # or relabel that builder's source table.
    original = json.loads(BASE_BUILD.read_text())
    probe.verify_build_metadata(original)
    saved = BASE_BUILD.parent / BASE_TEMPLATE.name
    sha = probe.checkpoint.digest(BASE_TEMPLATE)
    assert original['inputs'][str(BASE_TEMPLATE)] == sha
    assert original['artifacts'][str(saved.relative_to(probe.ROOT))] == sha
    assert probe.checkpoint.digest(saved) == sha
    for path in (BASE_BUILD, BASE_TEMPLATE, saved):
        key = str(path); value = probe.checkpoint.digest(path)
        assert key not in before or before[key] == value, 'Conflicting template provenance'
        before[key] = value
    return q, before


def corrupt_checkpoint(original, kind):
    if kind not in EXTRA_REASONS:
        return OLD_CORRUPT(original, kind)
    bad = deepcopy(original); module = next(iter(bad['modules'].values()))
    roles = local_carry_roles(module)
    assert len(roles) == 8, 'Changed original carry-role fixture'
    role = next(r for r in roles if r['di'] == 'DI3' and 'Y204/' in r['bel'])
    carry = module['cells'][role['carry']]
    if kind == 'wrong_local_carry_DI':
        carry['connections']['DI2'], carry['connections']['DI3'] = carry['connections']['DI3'], carry['connections']['DI2']
    else:
        ff = next(c for c in module['cells'].values() if c['type'] == 'SLICE_FFX' and c['attributes']['NEXTPNR_BEL'].endswith('5FF'))
        assert ff['connections']['D'] != [role['net']]
        ff['connections']['D'] = [role['net']]
        assert len(local_carry_roles(module)) == 7, 'Extra sink must prevent tag restoration'
    assert bad != original
    return bad


def scan_log(code, text, cells=None, pairs=None, rejection=None):
    OLD_SCAN_LOG(code, text, cells, pairs, rejection)
    if rejection:
        return
    expected = {49: 8, 286: 0}
    assert cells in expected, 'Unsupported small native profile'
    marker = f'RKNPU imported placement scan: verified {expected[cells]} local carry DI roles.'
    assert text.count(marker) == 1, 'Missing actual native carry-role verification'
    assert text.index(marker) < text.index('RKNPU imported placement scan: passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args()
    template = args.build.resolve(strict=True).parent / BASE_TEMPLATE.name
    assert template.read_text() == extended_template(BASE_TEMPLATE.read_text()), 'Wrong supplemental native source'
    # Configure the immutable procedure in this process only. Each old gate
    # remains the same function; new checks and corruptions are additions.
    probe.TEMPLATE = template
    probe.CONTROL = CONTROL
    probe.REASONS = {**probe.REASONS, **EXTRA_REASONS}
    probe.corrupt_checkpoint = corrupt_checkpoint
    probe.scan_log = scan_log
    probe.verify_corrected_evidence = verify_extension_evidence
    probe.__doc__ = __doc__
    probe.main()


if __name__ == '__main__':
    main()
