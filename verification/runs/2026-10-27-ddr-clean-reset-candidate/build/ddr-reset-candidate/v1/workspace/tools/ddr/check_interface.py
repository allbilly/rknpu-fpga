#!/usr/bin/env python3
"""Audit the preserved ECC MIG source interface. Never runs vendor tools."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr.interface import audit, canonical, load_json, require, verify

SCOPE = 'Source metadata and integrity only; not controller, DDR, FPGA or RK execution proof'
FLAGS = ('vivado_executed', 'vendor_ip_executed', 'hardware_accessed', 'flash_written')
TOOL_FILES = ('tools/ddr/__init__.py', 'tools/ddr/interface.py',
              'tools/ddr/check_interface.py', 'fpga/ddr/Makefile')


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_revision():
    files = {name: file_sha(ROOT / name) for name in TOOL_FILES}
    return dict(files=files, sha256=hashlib.sha256(canonical(files)).hexdigest())


def inspect(source_root, reference_path, argv):
    reference = load_json(reference_path)
    result = audit(source_root, reference)
    return dict(schema_version=1, status=result['status'], scope=SCOPE,
                argv=argv, python=platform.python_version(),
                reference_sha256=file_sha(reference_path), tool_source=tool_revision(),
                audit=result, **{name: False for name in FLAGS})


def verify_envelope(report, source_root, reference_path):
    keys = {'schema_version', 'status', 'scope', 'argv', 'python',
            'reference_sha256', 'tool_source', 'audit', *FLAGS}
    require(type(report) is dict and set(report) == keys, 'Invalid audit envelope fields')
    require(type(report['schema_version']) is int and report['schema_version'] == 1,
            'Unsupported audit envelope schema')
    require(report['scope'] == SCOPE and all(report[name] is False for name in FLAGS),
            'Source audit cannot claim vendor or hardware execution')
    require(type(report['argv']) is list and len(report['argv']) > 1 and
            all(type(arg) is str and arg for arg in report['argv']), 'Invalid command record')
    require(type(report['python']) is str and report['python'], 'Missing Python version')
    require(report['reference_sha256'] == file_sha(reference_path), 'Reference contract changed')
    require(report['tool_source'] == tool_revision(), 'Audit tool source changed')
    result = verify(report['audit'], source_root, load_json(reference_path))
    require(report['status'] == result['status'] == 'BLOCKED_DDR_INTEGRATION',
            'Unsupported DDR readiness claim')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('inspect', 'verify'):
        command = sub.add_parser(action)
        command.add_argument('--source-root', type=Path, required=True,
                             help='Root of the original YPCB reference checkout')
        command.add_argument('--reference', type=Path,
                             default=ROOT / 'fpga/ddr/mig_c0_reference.json')
        if action == 'inspect':
            command.add_argument('--out', type=Path, required=True, help='Fresh output directory')
        else:
            command.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source_root = args.source_root.expanduser().resolve(strict=True)
        require(source_root.is_dir(), 'Source root is not a directory')
        reference = args.reference.expanduser().resolve(strict=True)
        if args.action == 'inspect':
            # Preserve an earlier result even if a caller repeats --out.
            out = args.out.expanduser().absolute()
            require(not out.exists() and not out.is_symlink(), 'Output already exists')
            invocation = [sys.executable, str(Path(__file__).resolve()),
                          *(sys.argv[1:] if argv is None else argv)]
            report = inspect(source_root, reference, invocation)
            out.mkdir(parents=True, exist_ok=False)
            report_path = out / 'report.json'
            report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
            result = report['audit']
        else:
            report_path = args.report.expanduser().resolve(strict=True)
            result = verify_envelope(load_json(report_path), source_root, reference)
        print(json.dumps(dict(report=str(report_path), status=result['status'],
                              interface_status=result['interface_status'],
                              blockers=result['blockers']), indent=2))
        # This inspected reference is unresolved. Integrity does not authorize integration.
        return 2
    except (OSError, ValueError, TypeError, KeyError) as error:
        print('DDR source audit rejected: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
