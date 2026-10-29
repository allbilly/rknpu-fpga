#!/usr/bin/env python3
"""Prepare/run the experimental fixed array with unchanged physical gates.

Preparation is not implementation. A run requires this variant's completed
native/proof and nine-mode Icarus board reports, never the original array's
board PASS. Stops at a routed checkpoint; cannot emit or program a bitstream.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from vivado_array import SPEC, inputs as baseline_inputs, render, validate_full_vivado_version
from test_fixed_array_board import (ARRAY, CELL, JOIN, ROWS, ROW_FORMAL,
                                   completed_commands, fixed_join, simulation_sources,
                                   validate_result, verify_fixed_native, verify_manifest)

PROFILE = 'fixed-fp16-c32k16'
ROUTED = 'ROUTED_FIXED_ARRAY_CHECKPOINT_REVIEW_REQUIRED'


def inside(name):
    path = (ROOT / name).resolve()
    assert not Path(name).is_absolute() and path.is_relative_to(ROOT) and path.is_file(), 'Invalid profile evidence path'
    return path


def inputs(directory):
    """Pure validation of a generated source profile; never writes inputs."""
    directory = directory.resolve()
    assert directory.is_relative_to(ROOT)
    spec, tracked = baseline_inputs()
    join = directory / Path(JOIN).name
    assert join.read_text() == fixed_join((ROOT / JOIN).read_text()), 'Generated fixed wrapper differs from the single audited substitution'
    fixed_sources = simulation_sources(dict(spec, simulation_helpers=[]), join)
    spec = dict(spec, synthesis=[str(path.relative_to(ROOT)) for path in fixed_sources], source_profile=PROFILE)
    tracked += fixed_sources + [join, ROOT / JOIN, ROOT / ROWS, ROOT / CELL, ROOT / ARRAY,
                                Path(__file__).resolve(), ROOT / 'tools/cmac/test_fixed_array_board.py']
    metadata = directory / 'profile_evidence.json'
    if metadata.exists():
        provenance = json.loads(metadata.read_text())
        assert set(provenance) == {'native_report', 'board_report'}
        tracked += [metadata, inside(provenance['native_report']), inside(provenance['board_report']),
                    directory / 'fixed_native_snapshot.json', directory / 'fixed_board_snapshot.json']
    return spec, tracked


def verify_board(report, native):
    assert report['status'] == 'PASS_FIXED_RAW_ARRAY_BOARD_FOUR_STATE_RTL_EXPERIMENT_ONLY', 'This fixed variant requires its own completed nine-mode Icarus report'
    assert report['suite'] == 'fixed-iverilog' and report['tool_version'].startswith('Icarus Verilog ')
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    assert report['row_formal_status_at_start'] == ROW_FORMAL and report['four_state_mode_not_run'] is None
    assert report['bitstream_emitted'] is False and report['hardware_programmed'] is False
    tests = report['tests']
    assert len(tests) == 9 and {test['mode'] for test in tests} == set(range(9)), 'All nine fixed board modes required'
    for test in tests:
        assert test['status'] == 'PASS'
        validate_result(test['result'], test['mode'])
    completed_commands(report, ('rom_check', 'version', 'runtime_version', 'compile', *('mode' + str(mode) for mode in range(9))))
    verify_manifest(report['source']); verify_manifest(report['artifacts'])
    spec = json.loads(SPEC.read_text())
    old_joins = [inside(name) for name in report['simulation_sources'] if Path(name).name == Path(JOIN).name]
    assert len(old_joins) == 1 and old_joins[0] != ROOT / JOIN, 'Missing tested generated fixed wrapper'
    join = old_joins[0]
    assert join.read_text() == fixed_join((ROOT / JOIN).read_text()), 'Tested fixed wrapper changed'
    expected = simulation_sources(spec, join)
    assert report['simulation_sources'] == [str(path.relative_to(ROOT)) for path in expected], 'Tested source list differs from fixed profile'
    covered = report['source']['files']
    for name in [str(path.relative_to(ROOT)) for path in expected] + [spec['bench'], spec['rom'], spec['constraints'], str(SPEC.relative_to(ROOT)), JOIN]:
        assert name in covered, f'Untested fixed build input: {name}'
    snapshots = [inside(name) for name in covered if name.endswith('/fixed_report_snapshot.json')]
    assert len(snapshots) == 1 and json.loads(snapshots[0].read_text()) == native, 'Board test did not use this completed fixed native report'
    return report


def validate_evidence(directory):
    metadata = directory / 'profile_evidence.json'
    provenance = json.loads(metadata.read_text())
    native = verify_fixed_native(inside(provenance['native_report']))
    board = verify_board(json.loads(inside(provenance['board_report']).read_text()), native)
    assert json.loads((directory / 'fixed_native_snapshot.json').read_text()) == native, 'Native snapshot differs'
    assert json.loads((directory / 'fixed_board_snapshot.json').read_text()) == board, 'Board snapshot differs'
    return native, board


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'run'))
    parser.add_argument('--fixed-report', type=Path)
    parser.add_argument('--board-report', type=Path)
    parser.add_argument('--vivado', default='vivado')
    args = parser.parse_args()
    native = board = None
    if args.action == 'run':
        assert args.fixed_report is not None and args.board_report is not None, 'Both fixed native and fixed board reports are required'
        native_path, board_path = args.fixed_report.resolve(), args.board_report.resolve()
        assert native_path.is_relative_to(ROOT) and board_path.is_relative_to(ROOT)
        native = verify_fixed_native(native_path)
        board = verify_board(json.loads(board_path.read_text()), native)
    else:
        assert args.fixed_report is None and args.board_report is None, 'prepare does not accept or claim simulation evidence'
    out = ROOT / f'build/rknpu-fixed-array-vivado/{args.action}-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    (out / Path(JOIN).name).write_text(fixed_join((ROOT / JOIN).read_text()))
    if args.action == 'run':
        (out / 'profile_evidence.json').write_text(json.dumps(dict(native_report=str(native_path.relative_to(ROOT)), board_report=str(board_path.relative_to(ROOT))), indent=2) + '\n')
        for name, parent in (('fixed_native_snapshot', native), ('fixed_board_snapshot', board)):
            (out / (name + '.json')).write_text(json.dumps(parent, indent=2) + '\n')
    spec, tracked = inputs(out)
    report = dict(status='RUNNING', started_utc=timestamp(), action=args.action, source_profile=PROFILE,
                  source=fingerprint(tracked), commands=[], bitstream_emitted=False, hardware_programmed=False,
                  implementation_settings={key: os.environ.get(key) for key in ('RK_CONFIRM_BOARD', 'RK_CONFIG_VOLTAGE', 'RK_CFGBVS', 'RK_LED_ACTIVE_LOW')},
                  scope='Experimental fixed-FP16 C32/K16 prepared sources or source-gated checkpoint implementation. Same raw K65 ROM, part, pins, 20 ns clock and physical gates; no bitstream, FPGA/flash programming or RK acceptance.')

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, name, env=None):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    try:
                        code = proc.wait(timeout=86400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            assert code == 0, text[-6000:]
            step['status'] = 'PASS'; return text
        except Exception:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save()
    try:
        run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
        script = out / 'build.tcl'
        script.write_text(render(spec, out, report['source']['sha256']))
        for path in set(tracked):
            dest = out / 'snapshot' / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
        if args.action == 'prepare':
            report.update(status='PREPARED_FIXED_ARRAY_VIVADO_ONLY', prerequisites='No HDL or Vivado executed. run requires completed current fixed-array native/proof and all nine fixed-variant Icarus board modes, full Vivado and explicit board confirmation.')
        else:
            report.update(fixed_native_report=native, board_report=board)
            assert os.environ.get('RK_CONFIRM_BOARD') == 'YPCB_00338_1P1', 'Explicit RK_CONFIRM_BOARD required'
            executable = shutil.which(args.vivado)
            assert executable and Path(executable).name == 'vivado', 'UNAVAILABLE: full Vivado, not Lab, required'
            report['tool_version'] = run([executable, '-version'], 'version')
            validate_full_vivado_version(report['tool_version'])
            env = dict(os.environ, RK_ARRAY_SOURCE_SHA=report['source']['sha256'])
            run([executable, '-mode', 'batch', '-source', script, '-log', out / 'vivado.log', '-journal', out / 'vivado.jou'], 'implementation', env)
            assert (out / 'routed.dcp').is_file() and not list(out.glob('*.bit'))
            assert validate_evidence(out) == (native, board)
            report['status'] = ROUTED
        assert fingerprint(tracked) == report['source'], 'Fixed build inputs changed during run'
        report['artifacts'] = fingerprint([script] + [path for path in out.iterdir() if path.suffix in ('.log', '.jou', '.dcp', '.rpt')])
    except Exception as exc:
        report.update(status='FAIL', reason=str(exc)); raise
    finally:
        report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
    print(report['status'])


if __name__ == '__main__':
    main()
