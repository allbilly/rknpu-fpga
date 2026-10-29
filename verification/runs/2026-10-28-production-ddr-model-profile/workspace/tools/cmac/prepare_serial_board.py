#!/usr/bin/env python3
"""Prepare the existing serialized CMAC BRAM board without launching Vivado.

This is the independent numerical GEMM candidate, not the EW product path or
the full C32/K16 array. Its external R28 reset still requires board review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as native
from board_contract import validate_board_result
from evidence import ROOT, fingerprint, timestamp
from prepare_ew_fpga import (BOARD, PART, BOARD_CHECKS, require, digest, read_json,
                             write_json, tcl_path, validate_board_review)

PROFILE = 'serial-cmac-r28'
TEMPLATE = 'fpga/cmac/build_array.tcl.in'
BUILD_INPUTS = ['tools/cmac/prepare_serial_board.py', 'tools/prepare_ew_fpga.py',
                'tests/cmac/test_prepare_serial_board.py', TEMPLATE]


def producer_prelude(simulator, binary, jobs=None):
    """The source/compile commands emitted by the bound native board producer."""
    require(simulator in ('verilator', 'iverilog'), 'Unknown board simulator')
    spec = read_json(ROOT / 'fpga/cmac/sources.json')
    sources = [str(ROOT/n) for n in spec['simulation_helpers'] + spec['synthesis']]
    bench = ROOT / spec['benches']['board']
    defines = ['-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
               *['-I'+str(ROOT/n) for n in spec['include_dirs']]]
    binary = ROOT / binary
    if simulator == 'verilator':
        require(binary.name == 'sim' and binary.parent.name == 'obj', 'Wrong Verilator binary path')
        require(jobs in ('1', '2', '3', '4'), 'Invalid native compile parallelism')
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal',
                 '--timescale-override', '1ns/1ps', *defines]
        return dict(version=['verilator', '--version'],
            baseline_lint=['verilator', '--lint-only', *flags, '--top-module', spec['tops']['board'], *sources],
            bench_lint=['verilator', '--lint-only', *flags, '--top-module', bench.stem, *sources, str(bench)],
            cxx_version=['c++', '--version'],
            compile=['verilator', '--binary', *flags, '-j', jobs, '--top-module', bench.stem,
                     '--Mdir', str(binary.parent), '-o', 'sim', *sources, str(bench)])
    require(binary.name == 'sim.vvp', 'Wrong Icarus binary path')
    return dict(version=['iverilog', '-V'],
        compile=['iverilog', '-g2012', *defines, '-s', bench.stem, '-o', str(binary), *sources, str(bench)],
        vvp_version=['vvp', '-V'])


def checked_path(root, name):
    require(not root.is_symlink(), 'Symlinked artifact root')
    path = Path(name)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe artifact path')
    path = root / path
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()),
            'Missing or escaping artifact: ' + name)
    return path


def validate_report(record, simulator, source, artifact_root=ROOT):
    require(simulator in ('verilator', 'iverilog'), 'Unknown board simulator')
    require(record.get('status') == 'PASS_CONSOLIDATED_CMAC_NATIVE_BOARD' and
            record.get('action') == 'test' and record.get('suite') == 'board' and
            record.get('finished_utc'), 'Completed serialized board evidence is required')
    version = 'Verilator ' if simulator == 'verilator' else 'Icarus Verilog '
    require(record.get('tool_version', '').startswith(version), 'Wrong board simulator')
    require(record.get('source') == source, 'Stale serialized numerical source')
    for flag in ('bitstream_emitted', 'hardware_programmed'):
        require(record.get(flag) is False, 'Unexpected physical evidence claim')
    commands = record.get('commands', [])
    require(commands and all(c.get('status') == 'PASS' and type(c.get('returncode')) is int and
                            c['returncode'] == 0 for c in commands), 'Failed native command')
    artifacts = record.get('artifacts', {}).get('files', {})
    binaries = record.get('runtime_binary', {}).get('files', {})
    require(len(binaries) == 1 and all(artifacts.get(n) == h for n, h in binaries.items()),
            'Unbound executed simulator binary')
    for name, sha in artifacts.items():
        require(digest(checked_path(artifact_root, name)) == sha, 'Changed native artifact: ' + name)
    binary = next(iter(binaries))
    expected = set(range(7 if simulator == 'verilator' else 8)) | {8}
    labels = [Path(c.get('log', '')).stem for c in commands]
    require(labels.count('compile') == 1, 'Missing or duplicate native compile command')
    compile_args = commands[labels.index('compile')].get('argv', [])
    jobs = None
    if simulator == 'verilator':
        require(compile_args.count('-j') == 1 and compile_args.index('-j') + 1 < len(compile_args),
                'Missing native compile parallelism')
        jobs = compile_args[compile_args.index('-j') + 1]
    prelude = producer_prelude(simulator, binary, jobs)
    require(labels[:len(prelude)] == list(prelude) and
            len(labels) == len(prelude) + len(expected) and
            set(labels[len(prelude):]) == {'mode' + str(n) for n in expected},
            'Incomplete or unexpected native command inventory')
    for label, argv in prelude.items():
        step = commands[labels.index(label)]
        require(step.get('argv') == argv, 'Changed native ' + label + ' command')
    for step in commands:
        require(step['log'] in artifacts, 'Unbound native command log')
        text = checked_path(artifact_root, step['log']).read_text()
        require('ERROR :' not in text, 'Native command contains a donor assertion failure')
    for label, field in [('version', 'tool_version')] + (
            [('cxx_version', 'cxx_version')] if simulator == 'verilator' else [('vvp_version', 'vvp_version')]):
        lines = checked_path(artifact_root, commands[labels.index(label)]['log']).read_text().splitlines()
        require(lines and lines[0] == record.get(field), 'Native version/log mismatch')
    tests = record.get('tests', [])
    require(len(tests) == len(expected) and {t.get('name') for t in tests} ==
            {'mode' + str(n) for n in expected}, 'Incomplete board-mode coverage')
    for mode in expected:
        name = 'mode' + str(mode)
        test = next(t for t in tests if t['name'] == name)
        require(test.get('status') == 'PASS', 'Failed board mode')
        steps = [c for c in commands if Path(c.get('log', '')).stem == name]
        require(len(steps) == 1, 'Missing or duplicate board command')
        step = steps[0]
        prefix = [str(ROOT / binary)] if simulator == 'verilator' else ['vvp', str(ROOT / binary)]
        require(step.get('argv') == prefix + ['+MODE=' + str(mode)], 'Changed board execution command')
        require(step['log'] in artifacts, 'Unbound board log')
        lines = [line for line in checked_path(artifact_root, step['log']).read_text().splitlines()
                 if line.startswith('PASS ')]
        require(len(lines) == 1 and lines[0] == test.get('result'), 'Board result/log mismatch')
        validate_board_result(lines[0], mode)


def render(directory, source_sha):
    snapshot = directory / 'source'
    spec = read_json(snapshot / 'fpga/cmac/sources.json')
    require(spec['tops']['board'] == 'ypcb_cmac_top', 'Unexpected serialized board top')
    text = (snapshot / TEMPLATE).read_text()
    values = {'@ROOT@': tcl_path(snapshot), '@OUT@': tcl_path(directory/'implementation'),
              '@SOURCE_SHA@': source_sha,
              '@INCLUDE_DIRS@': ' '.join(tcl_path(snapshot/n) for n in spec['include_dirs']),
              '@READ_SOURCES@': '\n'.join('read_verilog -sv '+tcl_path(snapshot/n) for n in spec['synthesis'])}
    for key, value in values.items():
        require(text.count(key) == 1, 'Changed template token: '+key)
        text = text.replace(key, value)
    require(text.count('synth_design -top ypcb_cmac_array_top') == 1, 'Changed array template top')
    text = text.replace('synth_design -top ypcb_cmac_array_top', 'synth_design -top ypcb_cmac_top')
    text = text.replace('RK_ARRAY_SOURCE_SHA', 'RK_SERIAL_SOURCE_SHA')
    text = text.replace('C32/K16', 'Serialized CMAC')
    text = text.replace('tools/cmac/vivado_array.py run', 'tools/cmac/prepare_serial_board.py command')
    text = text.replace('tools/cmac/vivado_array.py;', 'tools/cmac/prepare_serial_board.py;')
    require(not re.search(r'@[A-Z_]+@|^\s*(write_bitstream|program_hw\w*|open_hw\w*)\b', text, re.M),
            'Unexpanded token or hardware command')
    return text


def prepare(out=None, reports=None):
    require(__debug__, 'Use Python without -O for the imported source checks')
    spec, numerical = native.inputs(); native.check_rom()
    require(spec['tops']['board'] == 'ypcb_cmac_top', 'Wrong serialized source specification')
    reports = reports or {}
    require(not reports or set(reports) == {'verilator','iverilog'}, 'Supply both numerical board reports')
    evidence = {sim: read_json(path) for sim, path in reports.items()}
    for sim, record in evidence.items(): validate_report(record, sim, numerical)
    paths = [ROOT/n for n in numerical['files']] + [ROOT/n for n in BUILD_INPUTS]
    source = fingerprint(paths)
    directory = (Path(out) if out else ROOT/'build/serial-cmac-vivado-preparation'/str(time.time_ns())).resolve()
    require(directory.is_relative_to(ROOT/'build') and directory != ROOT/'build' and not directory.exists(),
            'Use a fresh output directory below build/')
    tcl_path(directory); directory.mkdir(parents=True)
    record = dict(schema=1,status='PREPARING',started_utc=timestamp(),profile=PROFILE,board=BOARD,part=PART,
                  source=source,numerical_source=numerical,build_inputs=fingerprint([ROOT/n for n in BUILD_INPUTS]),
                  simulation_reports={},native_qualification_bound=bool(evidence),vivado_executed=False,
                  bitstream_emitted=False,hardware_programmed=False,physical_fit_verified=False)
    try:
        for name, sha in source['files'].items():
            original=checked_path(ROOT,name); require(digest(original)==sha,'Changed source: '+name)
            target=directory/'source'/name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(original,target)
        for sim, report in evidence.items():
            path=directory/'evidence'/(sim+'.json'); path.parent.mkdir(exist_ok=True)
            write_json(path,report);record['simulation_reports'][sim]=digest(path)
            for name, sha in report['artifacts']['files'].items():
                original=checked_path(ROOT,name);target=directory/'artifacts'/name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
                require(digest(target)==sha,'Changed copied numerical artifact')
        (directory/'build.tcl').write_text(render(directory,source['sha256']))
        record['build_tcl_sha256']=digest(directory/'build.tcl')
        write_json(directory/'board-review.json',dict(schema=1,profile=PROFILE,source_sha256=source['sha256'],
            board=BOARD,part=PART,reviewer='',checks={k:False for k in BOARD_CHECKS},
            evidence={k:'' for k in BOARD_CHECKS},config_voltage=None,cfgbvs=None,led_active_low=None))
        require(fingerprint(paths)==source and native.inputs()[1]==numerical,'Inputs changed during preparation')
        record.update(status='PREPARED_SERIAL_CMAC_VIVADO_ONLY',reset_profile='External R28 remains unverified',
            scope='Frozen serialized K65 numerical board candidate; not full C32/K16, FPGA or RK acceptance')
    except BaseException as error:record.update(status='FAIL',error=repr(error));raise
    finally:record['finished_utc']=timestamp();write_json(directory/'report.json',record)
    return directory


def verify(directory, require_ready=False):
    require(__debug__, 'Use Python without -O for the imported source checks')
    directory=Path(directory).resolve();record=read_json(directory/'report.json')
    require(record.get('schema')==1 and record.get('status')=='PREPARED_SERIAL_CMAC_VIVADO_ONLY' and
            record.get('profile')==PROFILE and record.get('board')==BOARD and record.get('part')==PART,
            'Incomplete or wrong preparation profile')
    files=record['source']['files']
    manifest=''.join(f'{sha}  {name}\n' for name,sha in sorted(files.items()))
    require(hashlib.sha256(manifest.encode()).hexdigest()==record['source']['sha256'],'Invalid package manifest')
    require(set(files)==set(record['numerical_source']['files'])|set(BUILD_INPUTS),'Incomplete package inventory')
    require(all(files[n]==h for n,h in record['numerical_source']['files'].items()),'Numerical snapshot mismatch')
    for name,sha in record['source']['files'].items():
        require(digest(checked_path(directory/'source',name))==sha,'Changed snapshot: '+name)
    for name in BUILD_INPUTS:
        require(digest(ROOT/name)==record['source']['files'].get(name),'Build input changed: '+name)
    require(digest(checked_path(directory,'build.tcl'))==record['build_tcl_sha256'] and
            (directory/'build.tcl').read_text()==render(directory,record['source']['sha256']), 'Changed generated Tcl')
    blockers=[]
    if native.inputs()[1]!=record['numerical_source']:blockers.append('Numerical inputs changed; requalify this profile')
    bound=record.get('simulation_reports',{})
    require(not bound or set(bound)=={'verilator','iverilog'},'Incomplete evidence inventory')
    for sim,sha in bound.items():
        path=checked_path(directory/'evidence',sim+'.json');require(digest(path)==sha,'Changed copied simulator report')
        validate_report(read_json(path),sim,record['numerical_source'],directory/'artifacts')
    if not bound:blockers.append('Both complete numerical board suites are required')
    try:
        validate_board_review(read_json(directory/'board-review.json'),
            dict(profile=PROFILE,board=BOARD,part=PART,production_revision=record['source']))
    except (ValueError,KeyError,TypeError,FileNotFoundError) as error:blockers.append(str(error))
    if require_ready:require(not blockers,'; '.join(blockers))
    return dict(status='SOURCE_INTACT_REVIEW_PENDING' if blockers else 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD',
                profile=PROFILE,blockers=blockers,vivado_executed=False)


def command(directory):
    result=verify(directory,True);directory=Path(directory).resolve()
    require(not (directory/'implementation').exists(),'Implementation output exists; prepare a fresh package')
    record=read_json(directory/'report.json');review=read_json(directory/'board-review.json')
    result['argv']=['vivado','-mode','batch','-source',str(directory/'build.tcl'),
                    '-log',str(directory/'vivado.log'),'-journal',str(directory/'vivado.jou')]
    result['environment']=dict(RK_SERIAL_SOURCE_SHA=record['source']['sha256'],RK_CONFIRM_BOARD=BOARD,
        RK_CONFIG_VOLTAGE=review['config_voltage'],RK_CFGBVS=review['cfgbvs'],
        RK_LED_ACTIVE_LOW=str(review['led_active_low']),RK_EMIT_BITSTREAM='0')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    make=sub.add_parser('prepare');make.add_argument('--out',type=Path)
    for sim in ('verilator','iverilog'):make.add_argument('--'+sim+'-report',type=Path)
    for action in ('verify','command'):sub.add_parser(action).add_argument('directory',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            reports={s:p for s in ('verilator','iverilog') if (p:=getattr(args,s+'_report')) is not None}
            directory=prepare(args.out,reports);print(directory/'report.json');print(json.dumps(verify(directory),indent=2))
        else:print(json.dumps((verify if args.action=='verify' else command)(args.directory),indent=2))
    except (ValueError,KeyError,TypeError,OSError,AssertionError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
