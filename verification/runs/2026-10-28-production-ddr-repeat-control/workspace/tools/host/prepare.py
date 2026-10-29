#!/usr/bin/env python3
"""Freeze the USER2 EW BRAM physical shell. Never launch Vivado or hardware."""
import argparse
import hashlib
import importlib
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import prepare_ew_fpga as common

ROOT, BOARD, PART = common.ROOT, common.BOARD, common.PART
require, digest = common.require, common.digest
read_json, write_json, tcl_path = common.read_json, common.write_json, common.tcl_path
PROFILE = 'host-jtag-ew-bram'
SPEC = 'fpga/host/sources.json'
TEMPLATE = 'fpga/ew_checkpoint.tcl.in'
BUILD_FILES = [SPEC, TEMPLATE, 'fpga/host/reference.json', 'fpga/host/mailbox_cdc.tcl',
               'fpga/host/ypcb_jtag_ew.xdc', 'fpga/host/ypcb_jtag_ew_top.sv',
               'tools/host/prepare.py', 'tests/host/test_prepare.py',
               'tools/prepare_ew_fpga.py', 'tools/evidence.py',
               'rtl/vendor/opentpu/LICENSE', 'rtl/vendor/opentpu/PROVENANCE.json']


def qualification():
    return importlib.import_module('tools.host.qualification')


def checked_path(root, name):
    path = Path(name)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe package path')
    path = root / path
    require(path.is_file() and not path.is_symlink() and not root.is_symlink() and
            path.resolve().is_relative_to(root.resolve()), 'Missing or escaping file: ' + name)
    return path


def manifest(files):
    text = ''.join(f'{sha}  {name}\n' for name, sha in sorted(files.items()))
    return dict(sha256=hashlib.sha256(text.encode()).hexdigest(), files=dict(sorted(files.items())))


def specification(root=ROOT):
    spec = read_json(root / SPEC)
    require((spec['profile'], spec['top'], spec['part'], spec['clock_period_ns'],
             spec['tck_period_ns'], spec['jtag_chain'], spec['memory_bytes'], spec['memory_base']) ==
            (PROFILE, 'ypcb_jtag_ew_top', PART, 20.0, 166.666, 2, 1048576, '10000000'),
            'Unexpected host physical profile')
    require(spec['constraints'] == 'fpga/host/ypcb_jtag_ew.xdc' and
            spec['cdc'] == 'fpga/host/mailbox_cdc.tcl', 'Unexpected host constraints')
    require(len(spec['synthesis']) == len(set(spec['synthesis'])), 'Duplicate hardware source')
    for name in spec['synthesis']: checked_path(root, name)
    return spec


def render(directory, source_sha):
    require(re.fullmatch('[0-9a-f]{64}', source_sha) is not None, 'Invalid source fingerprint')
    snapshot = directory / 'source'
    spec = specification(snapshot)
    text = (snapshot / TEMPLATE).read_text()
    values = {'@ROOT@': tcl_path(snapshot), '@OUT@': tcl_path(directory / 'implementation'),
              '@SOURCE_SHA@': source_sha, '@TOP@': spec['top'],
              '@CONSTRAINTS@': tcl_path(snapshot / spec['constraints']),
              '@READ_SOURCES@': '\n'.join('read_verilog -sv '+tcl_path(snapshot/n)
                                          for n in spec['synthesis'])}
    for token, value in values.items():
        require(text.count(token) == 1, 'Changed checkpoint template: '+token)
        text = text.replace(token, value)
    # Reuse all existing electrical/BRAM/timing/DRC checks unchanged. Add only
    # this shell's post-synthesis CDC constraints and routed path audits.
    synth = ('synth_design -top '+spec['top']+' -part '+PART+
             ' -generic LED_ACTIVE_LOW=$::env(RK_LED_ACTIVE_LOW)')
    require(text.count(synth) == 1 and text.count('foreach check {no_clock unconstrained_internal_endpoints}') == 1,
            'Changed shared checkpoint control flow')
    text = text.replace(synth, synth+'\nsource '+tcl_path(snapshot/spec['cdc'])+'\nrk_host_cdc_constrain')
    marker = 'foreach check {no_clock unconstrained_internal_endpoints}'
    text = text.replace(marker, 'rk_host_cdc_audit $out\n'+marker)
    text = text.replace('RK_EW_PREPARED_SHA', 'RK_HOST_PREPARED_SHA')
    text = text.replace('Rendered by prepare_ew_fpga.py.', 'Rendered by tools/host/prepare.py.')
    require(not re.search(r'@[A-Z_]+@|^\s*(write_bitstream|open_hw\w*|program_hw\w*|set_clock_groups)\b', text, re.M),
            'Unexpanded token, broad clock cut or forbidden hardware command')
    return text


def prepare(out=None, reports=None):
    native = qualification()
    protocol = native.source_revision()
    spec = specification()
    reports = reports or {}
    require(not reports or set(reports) == {'verilator', 'iverilog'}, 'Supply both host simulator reports')
    evidence = {}
    for simulator, path in reports.items():
        submitted = read_json(path)
        execution_root = submitted.get('execution_root')
        require(isinstance(execution_root, str) and Path(execution_root).is_absolute() and
                '..' not in Path(execution_root).parts,
                'Missing or invalid host qualification execution_root')
        producer = Path(execution_root).resolve()
        record = native.verify_report(path, artifact_root=producer)
        require(record.get('execution_root') == execution_root, 'Host qualification origin changed')
        require(record.get('simulator') == simulator and record['source_revision'] == protocol,
                'Wrong or stale host qualification')
        evidence[simulator] = (record, producer)
    names = set(protocol['files']) | set(BUILD_FILES) | set(spec['synthesis'])
    source = manifest({name: digest(checked_path(ROOT, name)) for name in names})
    directory = (Path(out) if out else ROOT/'build/host-jtag-preparation'/str(time.time_ns())).resolve()
    require(directory.is_relative_to(ROOT/'build') and directory != ROOT/'build' and not directory.exists(),
            'Use a fresh package directory below build/')
    tcl_path(directory); directory.mkdir(parents=True)
    record = dict(schema=1, status='PREPARING', profile=PROFILE, board=BOARD, part=PART,
                  started_utc=common.timestamp(), source=source, protocol_source=protocol,
                  simulation_reports={}, vivado_executed=False, implementation_completed=False,
                  bitstream_emitted=False, hardware_programmed=False)
    try:
        for name, sha in source['files'].items():
            original = checked_path(ROOT, name)
            require(digest(original) == sha, 'Changed preparation input: '+name)
            target = directory/'source'/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            require(digest(target) == sha, 'Changed source copy: '+name)
        for simulator, (report, producer) in evidence.items():
            report_path = directory/'evidence'/(simulator+'.json')
            report_path.parent.mkdir(exist_ok=True); write_json(report_path, report)
            record['simulation_reports'][simulator] = digest(report_path)
            for name, sha in report['artifacts']['files'].items():
                original = checked_path(producer, name)
                target = directory/'artifacts'/name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
                require(digest(target) == sha, 'Changed host artifact copy: '+name)
        (directory/'build.tcl').write_text(render(directory, source['sha256']))
        record['build_tcl_sha256'] = digest(directory/'build.tcl')
        write_json(directory/'board-review.json', dict(schema=1, profile=PROFILE,
            source_sha256=source['sha256'], board=BOARD, part=PART, reviewer='',
            checks={name: False for name in common.BOARD_CHECKS},
            evidence={name: '' for name in common.BOARD_CHECKS},
            config_voltage=None, cfgbvs=None, led_active_low=None))
        require(native.source_revision() == protocol and all(digest(ROOT/n) == h for n,h in source['files'].items()),
                'Inputs changed during preparation')
        record.update(status='PREPARED_HOST_JTAG_EW_ONLY', native_qualification_bound=bool(evidence),
            scope='Source preparation for USER2-controlled raw EW execution in1MiB BRAM only. No DDR/PCIe, full NPU, physical timing or hardware claim; startup and CDC need actual implementation review.')
    except BaseException as error:
        record.update(status='FAIL', error=repr(error)); raise
    finally:
        record['finished_utc'] = common.timestamp(); write_json(directory/'report.json', record)
    return directory


def verify(directory, require_ready=False):
    directory = Path(directory).resolve(); record = read_json(directory/'report.json')
    require(type(record.get('schema')) is int and record['schema'] == 1 and
            record.get('status') == 'PREPARED_HOST_JTAG_EW_ONLY' and record.get('profile') == PROFILE and
            record.get('board') == BOARD and record.get('part') == PART, 'Wrong or incomplete host package')
    for flag in ('vivado_executed', 'implementation_completed', 'bitstream_emitted', 'hardware_programmed'):
        require(record.get(flag) is False, 'Unexpected physical qualification claim')
    source = record['source']; protocol = record['protocol_source']
    require(manifest(source['files']) == source and manifest(protocol['files']) == protocol, 'Invalid source manifest')
    spec = specification(directory/'source')
    require(set(source['files']) == set(protocol['files']) | set(BUILD_FILES) | set(spec['synthesis']),
            'Incomplete host package inventory')
    require(all(source['files'][n] == h for n,h in protocol['files'].items()), 'Protocol source binding changed')
    for name, sha in source['files'].items():
        require(digest(checked_path(directory/'source', name)) == sha, 'Changed host snapshot: '+name)
    for name in BUILD_FILES:
        require(digest(ROOT/name) == source['files'][name], 'Preparation input changed: '+name)
    require(digest(checked_path(directory, 'build.tcl')) == record['build_tcl_sha256'] and
            (directory/'build.tcl').read_text() == render(directory, source['sha256']), 'Changed host checkpoint Tcl')
    blockers = []
    if any(not (ROOT/n).is_file() or digest(ROOT/n) != h for n,h in source['files'].items()):
        blockers.append('Live host source changed; requalify and prepare again')
    native = qualification()
    bound = record.get('simulation_reports', {})
    require(not bound or set(bound) == {'verilator', 'iverilog'}, 'Incomplete host report inventory')
    for simulator, sha in bound.items():
        path = checked_path(directory/'evidence', simulator+'.json')
        require(digest(path) == sha, 'Changed copied host report')
        report = native.verify_report(path, source_root=directory/'source', artifact_root=directory/'artifacts')
        require(report.get('simulator') == simulator and report['source_revision'] == protocol,
                'Wrong copied host qualification')
    if not bound: blockers.append('Both current host endpoint simulator reports are required')
    try:
        common.validate_board_review(read_json(directory/'board-review.json'),
            dict(profile=PROFILE, board=BOARD, part=PART, production_revision=source))
    except (ValueError, KeyError, TypeError, FileNotFoundError) as error:
        blockers.append(str(error))
    if require_ready: require(not blockers, '; '.join(blockers))
    return dict(status='SOURCE_INTACT_REVIEW_PENDING' if blockers else 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD',
                profile=PROFILE, blockers=blockers, vivado_executed=False)


def command(directory):
    result = verify(directory, True); directory = Path(directory).resolve()
    require(not (directory/'implementation').exists(), 'Implementation output exists; prepare a fresh package')
    report = read_json(directory/'report.json'); review = read_json(directory/'board-review.json')
    result['argv'] = ['vivado', '-mode', 'batch', '-source', str(directory/'build.tcl'),
                      '-log', str(directory/'vivado.log'), '-journal', str(directory/'vivado.jou')]
    result['environment'] = dict(RK_HOST_PREPARED_SHA=report['source']['sha256'], RK_CONFIRM_BOARD=BOARD,
        RK_CONFIG_VOLTAGE=review['config_voltage'], RK_CFGBVS=review['cfgbvs'],
        RK_LED_ACTIVE_LOW=str(review['led_active_low']), RK_EMIT_BITSTREAM='0')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('prepare'); make.add_argument('--out', type=Path)
    for sim in ('verilator', 'iverilog'): make.add_argument('--'+sim+'-report', type=Path)
    for action in ('verify', 'command'): sub.add_parser(action).add_argument('directory', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            reports = {sim: path for sim in ('verilator', 'iverilog')
                       if (path := getattr(args, sim+'_report')) is not None}
            directory = prepare(args.out, reports)
            print(directory/'report.json'); print(common.json.dumps(verify(directory), indent=2))
        else: print(common.json.dumps((verify if args.action == 'verify' else command)(args.directory), indent=2))
    except (ValueError, KeyError, TypeError, OSError, AssertionError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__': main()
