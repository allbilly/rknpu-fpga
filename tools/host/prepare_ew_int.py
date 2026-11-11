#!/usr/bin/env python3
"""Prepare (never execute) the additive ew-int FPGA image package.

This tool freezes the evidenced INTEGER EW image sources into a fresh
build/ew-int-image-prep/<stamp>/ package, binds them to the source-hash-bound
simulator receipts produced by tools/ew_int/run_ew_int.py, renders the shared
checkpoint Tcl, and writes a QUEUED build request. It never launches Vivado,
never opens hardware and never emits a bitstream.

The image shell (constraints, CDC audit, mailbox, BSCAN, clocking) is the same
audited USB-JTAG/USER2 BRAM shell as the FP16 EW image; only the command
execution path changes (integer decoder + integer engine). The frozen FP16 EW
files are not part of this profile and are not edited.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import prepare_ew_fpga as common  # noqa: E402

ROOT = common.ROOT
BOARD = common.BOARD
PART = common.PART
BOARD_CHECKS = common.BOARD_CHECKS
require, digest = common.require, common.digest
read_json, write_json, tcl_path = common.read_json, common.write_json, common.tcl_path
timestamp = common.timestamp

PROFILE = 'host-jtag-ew-int-bram'
SPEC = 'fpga/ewint/sources.json'
TEMPLATE = 'fpga/ew_checkpoint.tcl.in'
CONSTRAINTS = 'fpga/host/ypcb_jtag_ew.xdc'
CDC = 'fpga/host/mailbox_cdc.tcl'
EXPECTED_SYNTHESIS = [
    'rtl/rk_int_alu.sv',
    'rtl/rk_ew_int_regs.sv',
    'rtl/rk_ew_int_engine.sv',
    'rtl/rk_ew_int_dma.sv',
    'rtl/rk_bram.sv',
    'rtl/rk_job_control.sv',
    'rtl/rk_startup_reset.sv',
    'rtl/host/rk_jtag_backend.sv',
    'rtl/host/rk_jtag_ew_int_bram.sv',
    'rtl/vendor/opentpu/otpu_jtag_mailbox.sv',
    'fpga/ewint/ypcb_jtag_ew_int_top.sv',
]
REPLAY_TOOL = 'tools/ew_int/run_ew_int.py'
REPLAY_EVIDENCE = ('rtl/rk_int_alu.sv', 'rtl/rk_ew_int_regs.sv',
                   'rtl/rk_ew_int_engine.sv', 'rtl/rk_ew_int_dma.sv',
                   'model/int_alu.py', 'model/int_profile.py',
                   'model/int_sim.py', 'tests/tb_ew_int.sv',
                   'tests/tb_int_alu.sv', 'tools/ew_int/run_ew_int.py',
                   'tests/test_ew_int.py', 'docs/EW_INT.md',
                   'fpga/ewint/sources.json',
                   'fpga/ewint/ypcb_jtag_ew_int_top.sv',
                   'rtl/host/rk_jtag_ew_int_bram.sv',
                   'build/rk3588-example-captures/ew-int/manifest.json')
BUILD_FILES = [SPEC, TEMPLATE, CONSTRAINTS, CDC, REPLAY_TOOL,
               'tools/host/prepare_ew_int.py']


def checked_path(root, name):
    path = Path(name)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe package path')
    path = root / path
    require(path.is_file() and not path.is_symlink() and not root.is_symlink() and
            path.resolve().is_relative_to(root.resolve()),
            'Missing or escaping file: ' + name)
    return path


def manifest(files):
    text = ''.join(f'{sha}  {name}\n' for name, sha in sorted(files.items()))
    return dict(sha256=hashlib.sha256(text.encode()).hexdigest(),
                files=dict(sorted(files.items())))


def specification(root=ROOT):
    spec = read_json(root / SPEC)
    require((spec['profile'], spec['top'], spec['part'], spec['clock_period_ns'],
             spec['tck_period_ns'], spec['jtag_chain'], spec['memory_bytes'],
             spec['memory_base']) ==
            (PROFILE, 'ypcb_jtag_ew_int_top', PART, 20.0, 166.666, 2,
             1048576, '10000000'), 'Unexpected integer host physical profile')
    require(spec['constraints'] == CONSTRAINTS and spec['cdc'] == CDC,
            'Unexpected integer host constraints')
    require(spec['synthesis'] == EXPECTED_SYNTHESIS,
            'Integer image synthesis list changed; review is required')
    for name in spec['synthesis']:
        checked_path(root, name)
    return spec


def verify_receipt(path, simulator):
    path = Path(path).resolve()
    record = read_json(path)
    require(record.get('status') == 'PASS', f'{simulator} replay receipt is not PASS')
    require(not record.get('failures'), f'{simulator} replay receipt has failures')
    require(record.get('scope', '').startswith('Offline RTL/software replay only'),
            f'{simulator} receipt scope changed')
    require(set(record.get('simulators', {})) == {'verilator', 'iverilog'},
            f'{simulator} receipt must carry both simulator reports')
    for name, entry in record['simulators'].items():
        require(entry.get('status') == 'PASS', f'{simulator} {name} status is not PASS')
        cases = entry.get('cases', {})
        require(len(cases) == 15 and all(c.get('status') == 'PASS'
                                        for c in cases.values()),
                f'{simulator} {name} does not carry 15 PASS cases')
        require(len(entry.get('negative_controls', {})) == 19 and all(
            c.get('status') == 'PASS' for c in entry['negative_controls'].values()),
            f'{simulator} {name} does not carry 19 PASS negative controls')
    require(len(record.get('negative_controls', {})) == 19 and all(
        c.get('software_status') == 'PASS'
        for c in record['negative_controls'].values()),
        f'{simulator} receipt software negative controls incomplete')
    require(len(record.get('cases', {})) == 15 and all(
        c.get('status') == 'PASS' for c in record['cases'].values()),
        f'{simulator} receipt software replay incomplete')
    require(record['alu']['vectors'] > 100, f'{simulator} receipt ALU vectors missing')
    require(record['alu']['captured_lanes'] > 100, f'{simulator} receipt captured ALU lanes missing')
    # Hash binding: every evidence file named in the receipt must still match.
    for name in REPLAY_EVIDENCE:
        recorded = record['source_hashes'].get(name)
        require(recorded == digest(ROOT / name),
                f'{simulator} receipt is stale for {name}')
    return record


def render(directory, source_sha):
    require(re.fullmatch('[0-9a-f]{64}', source_sha) is not None,
            'Invalid source fingerprint')
    snapshot = directory / 'source'
    spec = specification(snapshot)
    text = (snapshot / TEMPLATE).read_text()
    values = {'@ROOT@': tcl_path(snapshot),
              '@OUT@': tcl_path(directory / 'implementation'),
              '@SOURCE_SHA@': source_sha, '@TOP@': spec['top'],
              '@CONSTRAINTS@': tcl_path(snapshot / spec['constraints']),
              '@READ_SOURCES@': '\n'.join('read_verilog -sv ' + tcl_path(snapshot / n)
                                          for n in spec['synthesis'])}
    for token, value in values.items():
        require(text.count(token) == 1, 'Changed checkpoint template: ' + token)
        text = text.replace(token, value)
    synth = ('synth_design -top ' + spec['top'] + ' -part ' + PART +
             ' -generic LED_ACTIVE_LOW=$::env(RK_LED_ACTIVE_LOW)')
    require(text.count(synth) == 1 and text.count('foreach check {no_clock unconstrained_internal_endpoints}') == 1,
            'Changed shared checkpoint control flow')
    text = text.replace(synth, synth + '\nsource ' + tcl_path(snapshot / spec['cdc']) +
                        '\nrk_host_cdc_constrain')
    marker = 'foreach check {no_clock unconstrained_internal_endpoints}'
    text = text.replace(marker, 'rk_host_cdc_audit $out\n' + marker)
    text = text.replace('RK_EW_PREPARED_SHA', 'RK_EW_INT_PREPARED_SHA')
    text = text.replace('Rendered by prepare_ew_fpga.py.',
                        'Rendered by tools/host/prepare_ew_int.py.')
    require(not re.search(r'@[A-Z_]+@|^\s*(write_bitstream|open_hw\w*|program_hw\w*|set_clock_groups)\b',
                          text, re.M),
            'Unexpanded token, broad clock cut or forbidden hardware command')
    return text


def prepare(out=None, reports=None):
    spec = specification()
    reports = reports or {}
    require(set(reports) == {'verilator', 'iverilog'},
            'Supply both integer replay receipts (--verilator-report/--iverilog-report)')
    evidence = {}
    for simulator, path in reports.items():
        evidence[simulator] = verify_receipt(path, simulator)
    capture_shas = {record['capture_manifest_sha256'] for record in evidence.values()}
    require(len(capture_shas) == 1, 'Replay receipts disagree on the capture manifest')
    names = set(spec['synthesis']) | set(BUILD_FILES) | set(REPLAY_EVIDENCE)
    names |= {spec['constraints'], spec['cdc']}
    source = manifest({name: digest(checked_path(ROOT, name)) for name in names})
    source['capture_manifest_sha256'] = capture_shas.pop()
    stamp = timestamp().replace(':', '').replace('-', '')
    directory = (Path(out) if out else ROOT / 'build/ew-int-image-prep' / stamp).resolve()
    require(directory.is_relative_to(ROOT / 'build') and directory != ROOT / 'build' and
            not directory.exists(), 'Use a fresh package directory below build/')
    tcl_path(directory)
    directory.mkdir(parents=True)
    record = dict(schema=1, status='PREPARING', profile=PROFILE, board=BOARD, part=PART,
                  started_utc=timestamp(), source=source, evidence={},
                  vivado_executed=False, implementation_completed=False,
                  bitstream_emitted=False, hardware_programmed=False,
                  scope=('Additive evidenced INTEGER EW BRAM image package. Same audited '
                         'USB-JTAG/USER2 BRAM shell; no DDR/PCIe/DRM/full-NPU claim. '
                         'No Vivado run, no bitstream, no hardware access in this step.'))
    try:
        for name, sha in source['files'].items():
            original = checked_path(ROOT, name)
            require(digest(original) == sha, 'Changed preparation input: ' + name)
            target = directory / 'source' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            require(digest(target) == sha, 'Changed source copy: ' + name)
        for simulator, report in evidence.items():
            # copy the receipt and the simulator logs it references
            report_path = directory / 'evidence' / (simulator + '.json')
            report_path.parent.mkdir(exist_ok=True)
            record['evidence'][simulator] = digest(reports[simulator])
            shutil.copyfile(Path(reports[simulator]).resolve(), report_path)
            receipt_dir = Path(reports[simulator]).resolve().parent
            for entry in ([report['alu']] +
                          [report['simulators'][simulator].get('alu', {})] +
                          list(report['simulators'][simulator]['cases'].values()) +
                          list(report['simulators'][simulator].get('negative_controls', {}).values())):
                log = entry.get('log') if isinstance(entry, dict) else None
                if not log:
                    continue
                source_log = receipt_dir / log
                require(source_log.is_file(), 'Missing simulator log ' + str(source_log))
                target_log = directory / 'evidence' / simulator / Path(log).name
                target_log.parent.mkdir(parents=True, exist_ok=True)
                if not target_log.exists():
                    shutil.copyfile(source_log, target_log)
        (directory / 'build.tcl').write_text(render(directory, source['sha256']))
        record['build_tcl_sha256'] = digest(directory / 'build.tcl')
        write_json(directory / 'board-review.json',
                   dict(schema=1, profile=PROFILE, source_sha256=source['sha256'],
                        board=BOARD, part=PART, reviewer='',
                        checks={key: False for key in BOARD_CHECKS},
                        evidence={key: '' for key in BOARD_CHECKS},
                        config_voltage=None, cfgbvs=None, led_active_low=None))
        write_json(directory / 'build-request.json',
                   dict(schema=1, status='QUEUED_WAITING_FOR_COOL_BUILD_WINDOW',
                        profile=PROFILE, top=spec['top'], part=PART,
                        prepared_source_sha256=source['sha256'],
                        prepared_utc=timestamp(),
                        requested_by='ewint (task-22 class-C increment)',
                        priority_note=('Behind the Lead-ordered heavy queue (verif dual '
                                       'mode-8, conveng D1 area re-measure, share pooling '
                                       'synth/build, hardware session). Build only in a '
                                       'Lead-scheduled cool window through the shared guard.'),
                        command=build_command(directory, source['sha256']),
                        preconditions=['Board review completed and audited',
                                       'Two integer replay receipts copied and hash-bound',
                                       'Fresh package directory and no implementation/ present',
                                       'Lead-scheduled cool window via host_guard']))
        require(all(digest(ROOT / n) == h for n, h in source['files'].items()),
                'Inputs changed during preparation')
        record['finished_utc'] = timestamp()
        record['status'] = 'PREPARED_EW_INT_IMAGE_PENDING_BUILD_WINDOW'
        write_json(directory / 'report.json', record)
    except BaseException as error:
        record.update(status='FAIL', error=repr(error), finished_utc=timestamp())
        write_json(directory / 'report.json', record)
        raise
    return directory


def build_command(directory, source_sha=None):
    directory = Path(directory).resolve()
    if source_sha is None:
        source_sha = read_json(directory / 'report.json')['source']['sha256']
    return {'argv': ['vivado', '-mode', 'batch', '-source', str(directory / 'build.tcl'),
                     '-log', str(directory / 'vivado.log'),
                     '-journal', str(directory / 'vivado.jou')],
            'environment': dict(RK_EW_INT_PREPARED_SHA=source_sha,
                                RK_CONFIRM_BOARD=BOARD, RK_EMIT_BITSTREAM='0'),
            'note': ('Environment additionally needs reviewed RK_CONFIG_VOLTAGE, '
                     'RK_CFGBVS and RK_LED_ACTIVE_LOW from the completed board review.')}


def verify(directory, require_ready=False):
    directory = Path(directory).resolve()
    record = read_json(directory / 'report.json')
    require(type(record.get('schema')) is int and record['schema'] == 1 and
            record.get('profile') == PROFILE and record.get('part') == PART,
            'Wrong or incomplete integer package')
    for flag in ('vivado_executed', 'implementation_completed', 'bitstream_emitted',
                 'hardware_programmed'):
        require(record.get(flag) is False, 'Unexpected physical qualification claim')
    source = record['source']
    require(manifest({n: h for n, h in source['files'].items()})['sha256'] == source['sha256'],
            'Invalid source manifest')
    require(all(digest(checked_path(directory / 'source', n)) == h
                for n, h in source['files'].items()), 'Changed source snapshot')
    require(digest(directory / 'build.tcl') == record['build_tcl_sha256'],
            'Changed checkpoint Tcl')
    blockers = []
    if record.get('status') != 'PREPARED_EW_INT_IMAGE_PENDING_BUILD_WINDOW':
        blockers.append('Package is not in a prepared state')
    if all(digest(ROOT / n) != h for n, h in source['files'].items()):
        blockers.append('Live sources changed; requalify and prepare again')
    review = read_json(directory / 'board-review.json')
    if not review.get('reviewer'):
        blockers.append('Board review is incomplete')
    if require_ready:
        require(not blockers, '; '.join(blockers))
    return dict(status='READY_FOR_SEPARATELY_AUTHORIZED_BUILD' if not blockers
                else 'SOURCE_INTACT_REVIEW_PENDING',
                profile=PROFILE, blockers=blockers, vivado_executed=False,
                build_request=str(directory / 'build-request.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('prepare')
    make.add_argument('--out', type=Path)
    make.add_argument('--verilator-report', type=Path, required=True)
    make.add_argument('--iverilog-report', type=Path, required=True)
    for action in ('verify', 'command'):
        sub.add_parser(action).add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            directory = prepare(args.out, {'verilator': args.verilator_report,
                                           'iverilog': args.iverilog_report})
            print(directory / 'report.json')
            print(json.dumps(verify(directory), indent=2))
        elif args.action == 'verify':
            print(json.dumps(verify(args.directory), indent=2))
        else:
            print(json.dumps(build_command(args.directory), indent=2))
    except (ValueError, KeyError, TypeError, OSError, AssertionError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
