#!/usr/bin/env python3
"""Check the explicit source-only maintenance/FI profile."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'rtl/ddr/maintenance_fi/sources.json'
MANIFEST_SHA256 = 'cbe122496f39bd91853704572c92d759e05a7f57808e2d4ab338597c8705d092'


def source_paths():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise ValueError('Profile manifest bytes/order changed')
    profile = json.loads(raw)
    if set(profile) != {'schema', 'top', 'atomic_c', 'atomic_k', 'precision', 'sources'} or (profile['schema'], profile['top'], profile['atomic_c'], profile['atomic_k'], profile['precision']) != (1, 'rk_whole_reset_fi_parent', 32, 16, 'FP16'):
        raise ValueError('Unexpected profile schema or numerical contract')
    rows = profile['sources']
    if not isinstance(rows, list) or len(rows) != 72:
        raise ValueError('Expected 72 ordered project sources')
    seen = set()
    selected = []
    for row in rows:
        if set(row) != {'path', 'sha256'}:
            raise ValueError('Unexpected source entry')
        path = PurePosixPath(row['path'])
        if path.is_absolute() or '..' in path.parts or str(path) != row['path'] or not path.parts or path.parts[0] != 'rtl':
            raise ValueError('Source path is not a contained RTL path')
        if path.name.startswith('mig_7series_') or path.name in {'mig_logic_model.sv', 'RAM32M.v', 'SRLC32E.v'}:
            raise ValueError('Vendor or test model in hardware profile')
        candidate = ROOT
        for part in path.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ValueError('Symlink in source path')
        if row['path'] in seen or not candidate.is_file():
            raise ValueError('Duplicate or missing source')
        seen.add(row['path'])
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Source hash mismatch: ' + row['path'])
        selected.append(candidate)
    return selected


def check():
    source_paths()
    print('PASS maintenance/FI source profile: 72 ordered sources')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', required=True)
    parser.parse_args()
    check()


if __name__ == '__main__':
    main()
