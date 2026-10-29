#!/usr/bin/env python3
"""Prepare the full 512-product startup checkpoint profile; never run Vivado.

Copied startup-native evidence is self-contained. The original arithmetic
qualification DAG is deliberately an external, current-workspace prerequisite;
its metadata snapshot is not permission to skip its original admission gates.
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
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools import prepare_ew_fpga as common

PROFILE = 'full512-startup'
STATUS = 'PREPARED_FULL512_STARTUP_CHECKPOINT_ONLY'
TOP = 'fpga/cmac/startup/ypcb_cmac_array_startup_top.sv'
CONSTRAINTS = 'fpga/cmac/startup/ypcb_cmac_array_startup.xdc'
MODULE = 'ypcb_cmac_array_startup_top'
BASE_TOP = 'fpga/cmac/ypcb_cmac_array_top.sv'
BUILD_FILES = ['tools/cmac/startup/prepare.py', 'tests/cmac/startup/test_prepare.py',
               'tools/prepare_ew_fpga.py', 'tools/evidence.py', 'fpga/ew_checkpoint.tcl.in',
               'tests/test_fpga_build.py']
require, digest = common.require, common.digest
read_json, write_json, quote = common.read_json, common.write_json, common.tcl_path


def qualification():
    return importlib.import_module('tools.cmac.startup.qualification')


def checked(root, name):
    root = Path(root)
    relative = Path(name)
    require(not relative.is_absolute() and relative.parts and '..' not in relative.parts,
            'Unsafe startup package path')
    path = root / relative
    require(not root.is_symlink() and path.is_file() and not path.is_symlink() and
            path.resolve().is_relative_to(root.resolve()), 'Missing or escaping startup file: '+name)
    return path


def manifest(files):
    text = ''.join(f'{sha}  {name}\n' for name, sha in sorted(files.items()))
    return dict(sha256=hashlib.sha256(text.encode()).hexdigest(), files=dict(sorted(files.items())))


def selected(parent_name, root):
    """Use the native qualifier's exact prefix sources; assertions are not stubs."""
    native = qualification()
    spec = read_json(checked(root, native.SPEC))
    names = native.source_names(parent_name, root=root)
    synthesis = [n for n in names if n not in spec['simulation_helpers']]
    require(synthesis.count(TOP) == synthesis.count(native.RESET) == 1 and BASE_TOP not in synthesis,
            'Wrong startup top/reset source selection')
    for required in ('rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv',
                     'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv',
                     'rtl/cmac/experimental/rk_cmac_fp16_lane_dsp_prefix.sv',
                     'rtl/cmac/experimental/rk_cmac_fp16_discarded_carry.sv'):
        require(synthesis.count(required) == 1, 'Missing full prefix arithmetic source')
    # Reconstruct the exact original spec only to call its unchanged renderer.
    original_sources = [BASE_TOP if n == TOP else n for n in synthesis if n != native.RESET]
    original_spec = dict(spec, synthesis=original_sources, source_profile='dsp-prefix-c32k16')
    return original_spec, synthesis


def no_clock_checks(root):
    text = checked(root, 'fpga/ew_checkpoint.tcl.in').read_text()
    start = 'foreach check {no_clock unconstrained_internal_endpoints} {'
    end = '\nforeach delay_type {max min} {'
    require(text.count(start) == text.count(end) == 1, 'Changed shared no-clock audit')
    return start+text.split(start, 1)[1].split(end, 1)[0]


def render(directory, source_sha, parent_name):
    require(re.fullmatch('[0-9a-f]{64}', source_sha) is not None, 'Invalid startup source hash')
    snapshot = directory/'source'
    native = qualification(); original = native.original_driver()
    spec, synthesis = selected(parent_name, snapshot)
    text = original.render(spec, directory/'implementation', source_sha)
    root_line = 'set root '+quote(original.ROOT)
    reads = '\n'.join('read_verilog -sv '+quote(original.ROOT/n) for n in spec['synthesis'])
    includes = 'set_property include_dirs [list '+ ' '.join(quote(original.ROOT/n) for n in spec['include_dirs'])+'] [current_fileset]'
    old_xdc = 'read_xdc [file join $root fpga ypcb.xdc]'
    old_top = 'synth_design -top ypcb_cmac_array_top '
    for marker in (root_line, reads, includes, old_xdc, old_top):
        require(text.count(marker) == 1, 'Changed original checkpoint rendering boundary')
    text = text.replace(root_line, 'set root '+quote(snapshot))
    text = text.replace(reads, '\n'.join('read_verilog -sv '+quote(snapshot/n) for n in synthesis))
    text = text.replace(includes, 'set_property include_dirs [list '+
                        ' '.join(quote(snapshot/n) for n in spec['include_dirs'])+'] [current_fileset]')
    text = text.replace(old_xdc, 'read_xdc '+quote(snapshot/CONSTRAINTS))
    text = text.replace(old_top, 'synth_design -top '+MODULE+' ')
    text = text.replace('RK_ARRAY_SOURCE_SHA', 'RK_FULL512_STARTUP_SOURCE_SHA')
    text = text.replace('fpga/ypcb.xdc against your board', CONSTRAINTS+' against your board')
    text = text.replace('tools/cmac/vivado_array.py run with a completed matching full board RTL report',
                        'tools/cmac/startup/prepare.py command after current parent and startup qualification')
    marker = 'set active_low 0\n'
    require(text.count(marker) == 1, 'Changed original electrical admission')
    text = text.replace(marker, '''# The startup package requires all reviewed electrical/polarity inputs.
foreach setting {RK_CONFIG_VOLTAGE RK_CFGBVS RK_LED_ACTIVE_LOW} {
    if {![info exists ::env($setting)]} {error "Missing reviewed startup setting $setting"}
}
'''+marker)
    marker = 'foreach delay_type {max min} {'
    require(text.count(marker) == 1, 'Changed original timing admission')
    text = text.replace(marker, no_clock_checks(snapshot)+'\n'+marker)
    require(original.GUARD in text and text.count('require_full_dsp_cmac\n') == 2 and
            '\nroute_design\nrequire_full_dsp_cmac\n' in text,
            'The sixteen-kernel/512-DSP guard changed')
    require(not re.search(r'^\s*(write_bitstream|open_hw\w*|program_hw\w*|set_false_path|set_clock_groups|create_waiver)\b', text, re.M),
            'Startup checkpoint cannot emit/program images or weaken timing')
    return text


def report_parent_matches(report, forwarded):
    require(report.get('status') == 'PASS_FULL512_STARTUP_NATIVE_ONLY' and
            report.get('parent_preflight') == forwarded['report'] and
            report.get('parent_preflight_sha256') == forwarded['sha256'] and
            report.get('parent_source_sha256') == forwarded['source_sha256'],
            'Startup simulation used a different full-prefix parent')


def evidence_manifest(directory, report):
    files = {}
    require(set(report['simulation_reports']) == {'iverilog', 'verilator'}, 'Both startup simulators are required')
    for simulator, sha in report['simulation_reports'].items():
        name = 'evidence/'+simulator+'.json'
        path = checked(directory, name); require(digest(path) == sha, 'Changed copied startup report')
        files[name] = sha
        for artifact, value in read_json(path)['artifacts']['files'].items():
            relative = Path(artifact)
            require(not relative.is_absolute() and relative.parts and '..' not in relative.parts, 'Unsafe startup artifact path')
            destination = str(Path('artifacts')/relative)
            require(destination not in files or files[destination] == value, 'Conflicting startup artifacts')
            files[destination] = value
    return manifest(files)


def evidence_inventory(directory, expected):
    found = set()
    for section in ('evidence', 'artifacts'):
        folder = directory/section
        require(folder.is_dir() and not folder.is_symlink(), 'Missing or symlinked startup evidence directory')
        for path in folder.rglob('*'):
            require(not path.is_symlink(), 'Symlinked startup evidence entry')
            if path.is_file(): found.add(str(path.relative_to(directory)))
    require(found == set(expected), 'Unmanifested or missing startup evidence')


def prepare(parent_preflight, iverilog_report, verilator_report, out=None):
    require(__debug__, 'Parent qualification requires assertions; do not use Python -O')
    native = qualification()
    parent_path = Path(parent_preflight).resolve()
    require(parent_path.is_relative_to(ROOT), 'Parent preflight must belong to this workspace')
    parent_name = str(parent_path.relative_to(ROOT))
    parent = native.verify_parent(parent_path)
    forwarded = dict(workspace=str(ROOT), report=parent_name, sha256=digest(parent_path),
                     source_sha256=parent['source']['sha256'], closure='EXTERNAL_CURRENT_PARENT_DAG_REQUIRED')
    paths = {'iverilog': Path(iverilog_report), 'verilator': Path(verilator_report)}
    evidence = {sim:native.verify_report(path) for sim,path in paths.items()}
    revisions = []
    for sim, report in evidence.items():
        require(report.get('simulator') == sim, 'Wrong startup simulator')
        report_parent_matches(report, forwarded); revisions.append(report['source_revision'])
    require(revisions[0] == revisions[1], 'Startup simulator sources differ')
    revision = revisions[0]
    require(revision['files'].get(parent_name) == forwarded['sha256'], 'Parent report not bound to startup source')
    require(all(revision['files'].get(n) == h for n,h in parent['source']['files'].items()), 'Startup sources do not retain parent inputs')
    require(set(native.source_names(parent_name,root=ROOT)) <= set(revision['files']),
            'Native startup source manifest omits a selected simulation source')
    original_spec, synthesis = selected(parent_name, ROOT)
    require(native.original_driver().inputs(parent_path.parent)[0] == original_spec, 'Forwarded original prefix source selection changed')
    names = set(revision['files']) | set(BUILD_FILES)
    source = manifest({name:digest(checked(ROOT,name)) for name in names})
    require(all(source['files'][n] == h for n,h in revision['files'].items()), 'Startup inputs changed after simulation')
    directory = (Path(out) if out else ROOT/'build/full512-startup-preparation'/str(time.time_ns())).resolve()
    require(directory.is_relative_to(ROOT/'build') and directory != ROOT/'build' and not directory.exists(), 'Use a fresh startup package directory')
    quote(directory); directory.mkdir(parents=True)
    record = dict(schema=1, status='PREPARING', profile=PROFILE, board=common.BOARD, part=common.PART,
                  channels=32, kernels=16, parallel_products=512, clock_period_ns=20,
                  started_utc=common.timestamp(), source=source, native_source_revision=revision,
                  forwarded_parent=forwarded, synthesis_sources=synthesis, simulation_reports={},
                  vivado_executed=False, implementation_completed=False, physical_fit_verified=False,
                  bitstream_emitted=False, hardware_programmed=False,
                  reset_contract='Registered64-cycle hold with release on edge65; no R28 input or runtime reset opcode')
    try:
        for name, sha in source['files'].items():
            original = checked(ROOT,name); target = directory/'source'/name
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(original,target)
            require(digest(target) == sha, 'Changed source while copying')
        for sim, report in evidence.items():
            path = directory/'evidence'/(sim+'.json'); path.parent.mkdir(exist_ok=True)
            raw = paths[sim].read_bytes(); require(json.loads(raw) == report, 'Native report changed during preparation')
            path.write_bytes(raw); record['simulation_reports'][sim] = digest(path)
            for name, sha in report['artifacts']['files'].items():
                original = checked(ROOT,name); target = directory/'artifacts'/name
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists(): require(digest(target) == sha, 'Conflicting native artifact copy')
                else: shutil.copyfile(original,target)
                require(digest(target) == sha, 'Changed native artifact while copying')
        record['evidence_manifest'] = evidence_manifest(directory,record)
        evidence_inventory(directory,record['evidence_manifest']['files'])
        for sim in ('iverilog','verilator'):
            copied = native.verify_report(directory/'evidence'/(sim+'.json'),source_root=directory/'source',
                                          artifact_root=directory/'artifacts',require_parents=False)
            require(copied == evidence[sim], 'Copied startup execution evidence changed')
        script = directory/'build.tcl'; script.write_text(render(directory,source['sha256'],parent_name))
        record['build_tcl_sha256'] = digest(script)
        write_json(directory/'board-review.json',dict(schema=1,profile=PROFILE,source_sha256=source['sha256'],
            board=common.BOARD,part=common.PART,reviewer='',checks={k:False for k in common.BOARD_CHECKS},
            evidence={k:'' for k in common.BOARD_CHECKS},config_voltage=None,cfgbvs=None,led_active_low=None))
        require(all(digest(checked(ROOT,n)) == h for n,h in source['files'].items()), 'Startup inputs changed during preparation')
        require(native.verify_parent(parent_path) == parent, 'External parent changed during preparation')
        record.update(status=STATUS, scope='Full512 startup source/native qualification and checkpoint preparation only. Arithmetic parent DAG remains external and must be current for command admission. Physical INIT/FF mapping, fit, timing, DRC, image and board execution remain unproved.')
    except BaseException as error:
        record.update(status='FAIL',error=repr(error)); raise
    finally:
        record['finished_utc'] = common.timestamp(); write_json(directory/'report.json',record)
    # Independently consume the copied reports and executed artifacts.
    verify(directory)
    return directory


def verify(directory, require_ready=False):
    require(__debug__, 'Parent qualification requires assertions; do not use Python -O')
    directory = Path(directory).resolve(); record = read_json(checked(directory,'report.json'))
    require(type(record.get('schema')) is int and record['schema'] == 1 and record.get('status') == STATUS and
            record.get('profile') == PROFILE and record.get('board') == common.BOARD and record.get('part') == common.PART and
            (record.get('channels'),record.get('kernels'),record.get('parallel_products'),record.get('clock_period_ns')) == (32,16,512,20),
            'Incomplete or wrong full512 startup package')
    require(all(record.get(k) is False for k in ('vivado_executed','implementation_completed','physical_fit_verified',
                                                'bitstream_emitted','hardware_programmed')), 'Unexpected physical startup acceptance')
    source, revision, forwarded = record['source'], record['native_source_revision'], record['forwarded_parent']
    require(manifest(source['files']) == source and manifest(revision['files']) == revision, 'Invalid startup source manifest')
    require(set(source['files']) == set(revision['files']) | set(BUILD_FILES) and
            all(source['files'][n] == h for n,h in revision['files'].items()), 'Incomplete startup snapshot inventory')
    for name, sha in source['files'].items():
        require(digest(checked(directory/'source',name)) == sha, 'Changed startup snapshot: '+name)
    for name in BUILD_FILES+['tools/cmac/startup/qualification.py']:
        require(digest(checked(ROOT,name)) == source['files'][name], 'Startup preparation/qualification tool changed: '+name)
    require(forwarded['closure'] == 'EXTERNAL_CURRENT_PARENT_DAG_REQUIRED' and
            source['files'].get(forwarded['report']) == forwarded['sha256'], 'Parent source receipt changed')
    parent = read_json(checked(directory/'source',forwarded['report']))
    require(parent['source']['sha256'] == forwarded['source_sha256'] and
            all(revision['files'].get(n) == h for n,h in parent['source']['files'].items()), 'Parent source metadata changed')
    require(record['synthesis_sources'] == selected(forwarded['report'],directory/'source')[1], 'Changed selected full512 sources')
    expected = evidence_manifest(directory,record)
    require(record['evidence_manifest'] == expected, 'Changed startup evidence manifest')
    evidence_inventory(directory,expected['files'])
    native = qualification()
    for sim in ('iverilog','verilator'):
        report = native.verify_report(directory/'evidence'/(sim+'.json'),source_root=directory/'source',
                                      artifact_root=directory/'artifacts',require_parents=False)
        require(report.get('simulator') == sim and report['source_revision'] == revision, 'Wrong copied startup execution')
        report_parent_matches(report,forwarded)
    require(digest(checked(directory,'build.tcl')) == record['build_tcl_sha256'] and
            (directory/'build.tcl').read_text() == render(directory,source['sha256'],forwarded['report']), 'Changed startup checkpoint Tcl')
    blockers = []
    try:
        if any(not (ROOT/n).is_file() or digest(ROOT/n) != h for n,h in revision['files'].items()):
            blockers.append('Current startup/native input set changed; requalify before implementation')
    except OSError as error:
        blockers.append('Current startup/native inputs unavailable: '+str(error))
    parent_current = False
    try:
        workspace = Path(forwarded['workspace']).resolve()
        require(workspace == ROOT.resolve(), 'External arithmetic DAG must be revalidated from its original workspace')
        external = checked(workspace,forwarded['report'])
        require(digest(external) == forwarded['sha256'] and native.verify_parent(external) == parent,
                'External current parent preflight differs')
        require(native.original_driver().inputs(external.parent)[0] == selected(forwarded['report'],ROOT)[0],
                'Current original prefix source selection changed')
        parent_current = True
    except (ValueError,AssertionError,OSError,KeyError,TypeError) as error:
        blockers.append('External current arithmetic qualification unavailable: '+str(error))
    try:
        common.validate_board_review(read_json(directory/'board-review.json'),
            dict(profile=PROFILE,board=common.BOARD,part=common.PART,production_revision=source))
    except (ValueError,KeyError,TypeError,OSError) as error: blockers.append(str(error))
    if require_ready: require(not blockers, '; '.join(blockers))
    return dict(status='SOURCE_INTACT_REVIEW_PENDING' if blockers else 'READY_FOR_SEPARATELY_AUTHORIZED_FULL512_BUILD',
                profile=PROFILE,blockers=blockers,external_parent_current=parent_current,
                external_parent_closure_copied=False,vivado_executed=False,physical_fit_verified=False)


def command(directory):
    result = verify(directory,True); directory = Path(directory).resolve()
    require(not (directory/'implementation').exists(), 'Implementation output exists; prepare a fresh package')
    record = read_json(directory/'report.json'); review = read_json(directory/'board-review.json')
    result['argv'] = ['vivado','-mode','batch','-source',str(directory/'build.tcl'),
                      '-log',str(directory/'vivado.log'),'-journal',str(directory/'vivado.jou')]
    result['environment'] = dict(RK_FULL512_STARTUP_SOURCE_SHA=record['source']['sha256'],RK_CONFIRM_BOARD=common.BOARD,
        RK_CONFIG_VOLTAGE=review['config_voltage'],RK_CFGBVS=review['cfgbvs'],
        RK_LED_ACTIVE_LOW=str(review['led_active_low']),RK_EMIT_BITSTREAM='0')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='action',required=True)
    make = sub.add_parser('prepare')
    make.add_argument('--parent-preflight',type=Path,required=True)
    make.add_argument('--iverilog-report',type=Path,required=True)
    make.add_argument('--verilator-report',type=Path,required=True)
    make.add_argument('--out',type=Path)
    for action in ('verify','command'): sub.add_parser(action).add_argument('directory',type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'prepare':
            directory = prepare(args.parent_preflight,args.iverilog_report,args.verilator_report,args.out)
            print(directory/'report.json'); print(json.dumps(verify(directory),indent=2))
        else: print(json.dumps((verify if args.action == 'verify' else command)(args.directory),indent=2))
    except (ValueError,KeyError,TypeError,OSError,AssertionError) as error: parser.exit(1,str(error)+'\n')


if __name__ == '__main__': main()
