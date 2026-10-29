#!/usr/bin/env python3
"""Experimental fixed-FP16 array through the unchanged raw K65 board bench.

Requires completed source-matching full-array native and composed row proofs.
Verilator runs eight two-state modes; Icarus runs all nine four-state modes.
Neither status satisfies the unchanged baseline Vivado source gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from vivado_array import SPEC, verify_full_board

EXPERIMENTAL = 'rtl/cmac/experimental/'
CELL = EXPERIMENTAL + 'rk_cmac_fp16_cell_fixed.sv'
ARRAY = EXPERIMENTAL + 'rk_cmac_fp16_array_fixed.sv'
ROWS = EXPERIMENTAL + 'rk_cmac_fp16_rows.sv'
ORIGINAL_CELL = 'rtl/cmac/rk_cmac_fp16_cell.sv'
ORIGINAL_ARRAY = 'rtl/cmac/rk_cmac_fp16_array.sv'
JOIN = 'rtl/cmac/rk_cmac_cacc_fp16_array.sv'
BLOCK = 'rk_cmac_fp16_cell_fixed_b'
NATIVE_RESULT = ('PASS sized FP16 CMAC C=32 K=16 frames=208 checked_outputs=3328 '
                 'retired_outputs=3312 reset_canceled=16 held_cycles=520 faults=0')
ROW_FORMAL = 'PASS_COMPOSED_POST_CONFIGURATION_ROWS_AND_ACTIVE_COMPARE'


def verify_manifest(manifest):
    files = manifest['files']
    assert files, 'Empty evidence manifest'
    for name, digest in files.items():
        path = (ROOT / name).resolve()
        assert not Path(name).is_absolute() and path.is_relative_to(ROOT), 'Evidence path escapes workspace'
        assert re.fullmatch('[0-9a-f]{64}', digest), 'Invalid evidence digest'
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, f'Stale evidence: {name}'
    encoded = ''.join(f'{files[name]}  {name}\n' for name in sorted(files, key=Path))
    assert hashlib.sha256(encoded.encode()).hexdigest() == manifest['sha256'], 'Invalid manifest digest'


def completed_commands(report, required=()):
    commands = report['commands']
    assert commands and all(step['status'] == 'PASS' and step['returncode'] == 0 for step in commands), 'Incomplete commands'
    assert set(required) <= {Path(step['log']).stem for step in commands}, 'Missing required commands'


def verify_fixed_native(path):
    report = json.loads(path.read_text())
    assert report['status'] == 'PASS_FIXED_MODE_CMAC_NATIVE_EXPERIMENT_ONLY', 'Completed fixed full-array native evidence required'
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert report['row_formal_status_at_start'] == ROW_FORMAL, 'Completed composed row proofs required'
    assert report['result'] == NATIVE_RESULT, 'Full original numerical/hold/reset corpus required'
    assert report['library_operations'] == ['combo_update', 'create'], 'Actual combinational library calls required'
    completed_commands(report, ('version', 'cxx_version', 'cell_compile', 'top_generate', 'top_compile', 'test'))
    verify_manifest(report['source']); verify_manifest(report['artifacts'])
    vectors = report['vectors']
    assert (vectors['frames'], vectors['outputs'], vectors['seed']) == (208, 3328, '0x35883216')
    verify_manifest(vectors['source']); verify_manifest(vectors['artifacts'])
    for name in (CELL, ARRAY, ROWS, ORIGINAL_CELL, ORIGINAL_ARRAY, 'tools/cmac/test_fixed_array.py'):
        assert name in report['source']['files'], f'Unverified experimental source: {name}'
    rows_path = path.parent / 'rows_report_snapshot.json'
    assert str(rows_path.relative_to(ROOT)) in report['source']['files'], 'Missing proof provenance'
    rows = json.loads(rows_path.read_text())
    assert rows['status'] == 'PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY' and rows['formal_result'] == ROW_FORMAL
    assert rows['simulation_result'] == 'PASS fixed FP16 rows comparisons=2097152 resets=4 seed=3588f016; post-configuration only'
    completed_commands(rows, ('compile', 'test', 'formal_control', 'formal_datapath'))
    verify_manifest(rows['source']); verify_manifest(rows['artifacts'])
    return report


def fixed_join(text):
    old = '    rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K),.TAG_WIDTH(TAG_WIDTH+2)) cmac('
    assert text.count(old) == 1, 'Expected exactly one audited CMAC substitution'
    return text.replace(old, old.replace('rk_cmac_fp16_array #', 'rk_cmac_fp16_array_fixed #'))


def simulation_sources(spec, generated_join):
    names = spec['simulation_helpers'] + spec['synthesis']
    assert all(names.count(name) == 1 for name in (ORIGINAL_CELL, ORIGINAL_ARRAY, JOIN)), 'Ambiguous baseline sources'
    result = []
    for name in names:
        if name == ORIGINAL_CELL:
            result.extend(ROOT / item for item in (ROWS, CELL))
        elif name == ORIGINAL_ARRAY:
            result.append(ROOT / ARRAY)
        elif name == JOIN:
            result.append(generated_join)
        else:
            result.append(ROOT / name)
    assert len(result) == len(set(result)), 'Duplicate simulation sources'
    assert ROOT / ORIGINAL_CELL not in result and ROOT / ORIGINAL_ARRAY not in result and ROOT / JOIN not in result
    return result


def validate_result(text, mode):
    assert mode in range(9), 'Unknown board mode'
    lines = [line for line in text.splitlines() if line.startswith('PASS ')]
    assert len(lines) == 1, 'Expected exactly one board result'
    match = re.fullmatch(r'PASS C32 K16 BRAM board RTL mode=(\d+) success=(\d+) resets=(\d+) faults=(\d+) init=(\d+) check=(\d+) cmd_reads=(\d+) operand_reads=(\d+) writes=(\d+) acks=(\d+) cycles=(\d+); no physical FPGA test', lines[0])
    assert match, 'Unexpected board result format'
    got_mode, successes, resets, faults, init, checked, commands, reads, writes, acks, cycles = map(int, match.groups())
    good = mode in (0, 3, 4, 5, 6)
    assert (got_mode, successes, resets, faults) == (mode, 2 if mode == 6 else int(good), int(mode in (3, 4, 5, 6)), int(not good))
    assert init == 4096 and 0 < cycles < 1048576
    if good:
        assert (checked, commands, reads, writes, acks) == (4096, 196, 6528, 64, 64), 'Incomplete full RAM/transaction checks'
    elif mode == 1:
        assert (checked, commands, reads, writes, acks) == (0, 1, 0, 0, 0), 'Command fault contract changed'
    elif mode == 8:
        assert checked == writes == acks == 0 and commands == 196 and 20 <= reads <= 21, 'Watchdog contract changed'
    else:
        assert (checked, commands, reads, writes, acks) == (1, 196, 6528, 64, 64), 'Readback fault contract changed'
    return lines[0]


def check_warnings(text, allowed, reset_warning=None, wrapper=None):
    warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
    assert len(warnings) == len(re.findall(r'^%Warning-', text, re.M)), 'Unparsed warning'
    permitted = set(allowed)
    if reset_warning is not None:
        assert warnings.count(reset_warning) == 1, 'Reset diagnostic changed'
        permitted.add(reset_warning)
    if wrapper is not None:
        assert wrapper.read_text().splitlines()[51] == '    time last_combo_seqnum__V;', 'Generated wrapper diagnostic changed'
        diagnostic = ('UNUSEDSIGNAL', str(wrapper), '52')
        if diagnostic in warnings:
            assert warnings.count(diagnostic) == 1
            line = f"%Warning-UNUSEDSIGNAL: {wrapper}:52:10: Signal is not used: 'last_combo_seqnum__V'"
            assert line in text.splitlines(), 'Generated timestamp diagnostic changed'
            permitted.add(diagnostic)
    assert set(warnings) <= permitted, f'Unexpected HDL warnings: {warnings}'
    assert not re.search(r'%Error|ERROR\s*:|warning:|sorry:', text, re.I), text[-6000:]
    return warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=('verilator', 'iverilog'), required=True)
    parser.add_argument('--fixed-report', type=Path, required=True)
    parser.add_argument('--board-report', type=Path, required=True)
    parser.add_argument('--donor-report', type=Path, action='append', required=True)
    args = parser.parse_args()
    fixed_path = args.fixed_report.resolve()
    spec = json.loads(SPEC.read_text())
    assert (spec['top'], spec['part'], spec['clock_period_ns'], spec['bench']) == (
        'ypcb_cmac_array_top', 'xc7k480tffg1156-2', 20, 'tests/cmac/tb_cmac_array_bram_demo.sv')
    fixed = verify_fixed_native(fixed_path)
    board = verify_full_board(args.board_report.resolve(), spec)
    baselines = [json.loads(path.read_text()) for path in args.donor_report]
    assert len(baselines) == 2 and {parent['status'] for parent in baselines} == {
        'PASS_PARALLEL_CACC_NATIVE_ONLY', 'PASS_OC16_FRAME_OUTPUT_NATIVE_ONLY'}
    donor = ROOT / 'rtl/vendor/nvdla'
    allowed = set()
    for parent in baselines:
        completed_commands(parent); verify_manifest(parent['source']); verify_manifest(parent['artifacts'])
        assert parent['tool_version'] == fixed['tool_version']
        for code, name, line, *_ in parent['donor_warnings']:
            assert Path(name).parent == donor, 'Non-donor warning approval'
            allowed.add((code, name, line))
    for step in fixed['commands']:
        for warning in step.get('warning_locations', []):
            code, name, line = warning
            if Path(name).parent == donor or (code, name, line) == ('DECLFILENAME', str(ROOT / CELL), '5'):
                allowed.add((code, name, line))
    params = ROOT / 'tools/cmac/empty_hier_parameters.v'
    wrapper = fixed_path.parent / 'cell' / (BLOCK + '.sv')
    library = wrapper.with_name('lib' + BLOCK + '.a')
    for path in (wrapper, library):
        assert str(path.relative_to(ROOT)) in fixed['artifacts']['files'], 'Unverified library'
    assert str(params.relative_to(ROOT)) in fixed['source']['files']
    reset_warning = ('SYNCASYNCNET', str(ROOT / 'fpga/cmac/ypcb_cmac_array_top.sv'), '9')
    assert (ROOT / 'fpga/cmac/ypcb_cmac_array_top.sv').read_text().splitlines()[8].strip() == '(* ASYNC_REG="TRUE" *) reg reset_n;'
    out = ROOT / f'build/rknpu-fixed-array-board/{args.tool}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    join = out / Path(JOIN).name
    join.write_text(fixed_join((ROOT / JOIN).read_text()))
    sources = simulation_sources(spec, join)
    bench = ROOT / spec['bench']
    parents = [('fixed', fixed), ('board', board)] + [(f'donor{i}', parent) for i, parent in enumerate(baselines)]
    snapshots = []
    for name, parent in parents:
        path = out / (name + '_report_snapshot.json')
        path.write_text(json.dumps(parent, indent=2) + '\n'); snapshots.append(path)
    tracked = [ROOT / name for name in board['source']['files']]
    tracked += sources + snapshots + [params, ROOT / 'tools/evidence.py', ROOT / 'tools/cmac/vivado_array.py', Path(__file__).resolve()]
    tracked += [ROOT / name for name in fixed['source']['files'] if not name.startswith('build/')]
    if args.tool == 'verilator':
        tracked += [wrapper, library]
    for path in set(tracked):
        dest = out / 'snapshot' / path.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
    modes = list(range(9)) if args.tool == 'iverilog' else [0, 1, 2, 3, 4, 5, 6, 8]
    report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[], tests=[],
                  channels=32, kernels=16, parallel_products=512, suite='fixed-' + args.tool, seed=board['seed'],
                  simulation_sources=[str(path.relative_to(ROOT)) for path in sources],
                  row_formal_status_at_start=ROW_FORMAL, bitstream_emitted=False, hardware_programmed=False,
                  approved_donor_warnings=[list(item) for item in sorted(allowed)], reviewed_reset_warning=list(reset_warning),
                  four_state_mode_not_run=None if args.tool == 'iverilog' else 7,
                  scope='Experimental fixed-mode C32/K16 raw K65 board RTL replay. Unchanged commands, RAM oracle, resets, faults and transaction counts. Not baseline Vivado acceptance, mapped numerical/fit/timing, physical FPGA or RK silicon evidence.')

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name, lint=False):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            assert code == 0, text[-6000:]
            warnings = check_warnings(text, allowed if lint else (), reset_warning if lint else None, wrapper if lint else None)
            step.update(status='PASS', warning_locations=[list(item) for item in warnings])
            return text
        except Exception:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save()
    try:
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        report['tool_version'] = run([args.tool, '-V' if args.tool == 'iverilog' else '--version'], 'version').splitlines()[0]
        if args.tool == 'iverilog':
            report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
            binary = out / 'sim.vvp'
            run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
                 '-s', bench.stem, '-o', binary, *sources, bench], 'compile')
            simulation = ['vvp', binary]
        else:
            report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
            assert report['tool_version'] == fixed['tool_version']
            assert report['cxx_version'] == fixed['cxx_version']
            obj = out / 'obj'; obj.mkdir()
            (obj / f'V{bench.stem}_hier.mk').write_text('VM_HIER_LIBS := ' + str(library) + '\n')
            run(['verilator', '--cc', '--main', '--exe', '--timing', '--assert', '-Wall', '-Wno-fatal',
                 '--timescale-override', '1ns/1ps', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
                 '--Mdir', obj, '--top-module', bench.stem, '-o', 'sim',
                 '--hierarchical-block', 'rk_cmac_fp16_cell_fixed,' + BLOCK,
                 '--hierarchical-params-file', params, '-LDFLAGS', library, wrapper, *sources, bench], 'generate', True)
            top_cpp = list(obj.glob(f'V{bench.stem}*.cpp')); called = set()
            for path in top_cpp:
                for operation in ('create', 'combo_update', 'seq_update'):
                    if re.search(r'\b' + BLOCK + '_protectlib_' + operation + r'\s*\(', path.read_text()):
                        called.add(operation)
            assert called == {'create', 'combo_update'}, 'Missing actual fixed combinational library calls'
            assert not any('NV_NVDLA_CMAC_CORE_MAC_' in path.name or 'rk_cmac_fp16_rows' in path.name for path in top_cpp), 'Embedded CMAC bypasses library'
            report['library_operations'] = sorted(called); save()
            run(['make', '-C', obj, '-f', f'V{bench.stem}.mk', '-j', '2', 'OPT_FAST=-O2', 'OPT_SLOW=-O2', 'OPT_GLOBAL=-O2'], 'compile')
            binary = obj / 'sim'; simulation = [binary]
        for mode in modes:
            result = validate_result(run([*simulation, f'+MODE={mode}'], f'mode{mode}'), mode)
            report['tests'].append(dict(mode=mode, status='PASS', result=result)); save()
        assert len(report['tests']) == len(modes) and fingerprint(tracked) == report['source']
        verify_fixed_native(fixed_path); verify_full_board(args.board_report.resolve(), spec)
        for parent in baselines:
            verify_manifest(parent['source']); verify_manifest(parent['artifacts'])
        generated = [path for path in (out / 'obj').rglob('*') if path.is_file()] if args.tool == 'verilator' else [binary]
        report.update(status='PASS_FIXED_RAW_ARRAY_BOARD_' + ('FOUR_STATE_RTL' if args.tool == 'iverilog' else 'TWO_STATE_HIERARCHICAL') + '_EXPERIMENT_ONLY',
                      artifacts=fingerprint(generated + [join] + [ROOT / step['log'] for step in report['commands']]))
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'])


if __name__ == '__main__':
    main()
