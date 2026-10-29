#!/usr/bin/env python3
"""Write a bounded JSON plan for the DDR capacity-pattern software check.

This command creates no operation stream and contains no hardware executor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.ddr.capacity_pattern import CapacityPlan, DEFAULT_SEED, PHYSICAL_BYTES  # noqa: E402


def parse_int(text):
    try:
        return int(text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError('expected an integer (decimal or 0x-prefixed)') from error


def sha256(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=pathlib.Path,
                        help='new JSON plan path; existing output is refused')
    parser.add_argument('--base', type=parse_int, default=0)
    parser.add_argument('--size', type=parse_int, default=PHYSICAL_BYTES,
                        help='aligned window size; defaults to the full 2 GiB span')
    parser.add_argument('--seed', type=parse_int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        parser.error(f'output already exists: {output}')

    plan = CapacityPlan(base=args.base, size=args.size, seed=args.seed)
    source = ROOT / 'tools/ddr/capacity_pattern.py'
    manifest = plan.manifest()
    scope = ('full 2 GiB address-window software pattern plan' if plan.covers_full_window
             else 'partial-window software pattern plan; no full-capacity claim')
    report = {
        'schema': 'ddr-capacity-pattern-plan-only-v1',
        'status': 'PREPARED_OFFLINE_DDR_CAPACITY_PLAN_ONLY',
        'scope': scope,
        'plan': manifest,
        'pattern_source_path': str(source),
        'pattern_source_sha256': sha256(source),
        'operation_records_materialized': False,
        'hardware_executed': False,
        'physical_capacity_qualified': False,
        'controller_retirement_and_ecc_witness_required_separately': True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': report['status'], 'output': str(output),
                      'lines': plan.lines, 'operations': manifest['operations'],
                      'planned_full_window': plan.covers_full_window,
                      'hardware_executed': False,
                      'physical_capacity_qualified': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
