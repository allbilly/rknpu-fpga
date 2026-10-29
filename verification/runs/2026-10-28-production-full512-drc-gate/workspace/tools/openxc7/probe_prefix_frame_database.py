#!/usr/bin/env python3
"""Exercise the actual small native FASM against the exact-part frame DB.

Reuse the source-pinned strict soDLA converter and VeriGPU's immutable-grid
cache/single-line syntax profile. Preserve complete lines in bounded grammar
chunks, including whitespace the donor adapter trims. No feature filtering, missing-feature waiver,
bitstream assembly or programming. This is an encoder-chain control, not
full-board routing, electrical, numerical or timing acceptance.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from place_prefix_board import ROOT, timestamp, digest, bind_report, verify_bindings
from check_full_native_features import FEATURE_CONTROL, verify_feature_control_metadata

TOOL = Path('/home/fedora/tiny-gpu/build/ypcb')
SOURCE = TOOL / 'prjxray'
DATABASE = TOOL / 'prjxray-db/kintex7'
PYTHON = TOOL / 'xray-venv/bin/python'
CONVERTER = Path('/home/fedora/soDLA/tools/ypcb_frames/convert_fasm.py')
VALIDATOR = Path('/home/fedora/soDLA/tools/ypcb_frames/validate_frames.py')
ADAPTER = Path('/home/fedora/verigpu/fpga/ypcb/fasm_to_frames.py')
PART = 'xc7k480tffg1156-2'
PASS = 'PASS_SMALL_NATIVE_FASM_EXACT_PART_FRAME_DATABASE_CONTROL_NOT_BITSTREAM_OR_SIGNOFF'


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bounded_native_lines(filename, parse_string, syntax, chunk_lines=500, progress=None):
    """Bound the original grammar without trimming any complete source line."""
    assert type(chunk_lines) is int and chunk_lines > 0
    lines = Path(filename).read_text().splitlines(keepends=True)
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if text and not text.startswith('#') and syntax.fullmatch(text) is None:
            raise ValueError(f'Unsupported native FASM syntax on line {number}')
    for offset in range(0, len(lines), chunk_lines):
        chunk = ''.join(lines[offset:offset + chunk_lines])
        if not chunk.endswith('\n'):
            chunk += '\n'
        yield from parse_string(chunk)
        completed = min(offset + chunk_lines, len(lines))
        if progress is not None and (completed % 20000 == 0 or completed == len(lines)):
            progress(completed, len(lines))


def validate_conversion(result, destination):
    assert result['status'] == 'STRICT_NATIVE_FASM_CONVERSION_PASS_FRAME_VALIDATION_PENDING'
    assert result['part'] == PART and result['physical_verified'] is False
    assert result['inputs_unchanged'] is True
    assert result['counts']['input_lines'] > 0 and result['counts']['injected_lines'] > 0
    assert result['missing_clock_activity_requests'] == []
    assert not result.get('missing_features'), 'Missing features must remain failures'
    frames = Path(result['frames']).resolve(strict=True)
    assert frames == destination.resolve(strict=True) / 'configuration.frames'
    assert frames.stat().st_size == result['frame_bytes'] > 0
    assert digest(frames) == result['frames_sha256']
    return frames


def worker(fasm_file, destination):
    """Only parse/assemble frames; the parent separately binds all inputs."""
    sys.dont_write_bytecode = True
    assert os.environ.get('XRAY_ALLOW_MISSING_FEATURES') is None, 'No missing-feature override'
    sys.path.insert(0, str(SOURCE))
    import fasm
    from prjxray.db import Database
    adapter = load_module(ADAPTER, 'rknpu_bounded_fasm_adapter')
    converter = load_module(CONVERTER, 'rknpu_strict_native_frame_converter')
    adapter.cache_database_grids(Database)
    original_parser = fasm.parse_fasm_string
    # Fresh grammar equivalence controls, including enabled/zero vectors,
    # comments, a blank line and the source-defined repeated I/O feature.
    sample = "\n# control\nDSP_L_X1Y2.DSP_0.AREG_0\n" + \
        "BRAM_L_X1Y2.RAMB36.INIT_00[255:0] = 256'h01\n" + \
        "BRAM_L_X1Y2.RAMB36.INIT_01[255:0] = 256'h0\n" + \
        "LIOB33_X1Y2.IOB_Y0.STEPDOWN\nLIOB33_X1Y2.IOB_Y0.STEPDOWN\n\n"
    sample_path = destination.parent / 'adapter-grammar-control.fasm'
    sample_path.write_text(sample)
    assert list(bounded_native_lines(sample_path, original_parser, adapter.STATEMENT, chunk_lines=2)) == list(original_parser(sample))
    bad = destination.parent / 'adapter-unsupported-control.fasm'
    bad.write_text('DSP_L_X1Y2.BAD { unknown = 1 }\n')
    try:
        list(bounded_native_lines(bad, original_parser, adapter.STATEMENT, chunk_lines=2))
    except ValueError:
        pass
    else:
        raise AssertionError('Unsupported adapter syntax accepted')
    print('PASS native FASM grammar equivalence and unsupported-syntax control; no features dropped', flush=True)
    def progress(done, total):
        print(f'PARSED {done}/{total} actual native FASM lines', flush=True)
    fasm.parse_fasm_filename = lambda filename: bounded_native_lines(filename, original_parser, adapter.STATEMENT, progress=progress)
    converter.convert(SOURCE, DATABASE, fasm_file.resolve(strict=True), destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feature-control', type=Path, default=FEATURE_CONTROL)
    parser.add_argument('--worker', nargs=2, type=Path, metavar=('FASM', 'OUTPUT'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(*args.worker)
        return
    parent_path = (ROOT / args.feature_control).resolve(strict=True)
    assert parent_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/prefix-frame-database-control-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        commands=[], source={}, part=PART, native_control_dsps=4, native_control_brams=6,
        full_target_parallel_products=512, native_FASM_conversion_executed=False,
        exact_part_frame_validation_executed=False, full_board_FASM_conversion_executed=False,
        numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        source_defined_default_features_injected=True, scope=__doc__)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, timeout):
        step = dict(label=label, argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)),
            status='RUNNING', timeout_seconds=timeout)
        report['commands'].append(step)
        started = time.monotonic()
        save()
        env = dict(os.environ)
        # The converter also rejects this override. Never inherit it.
        env.pop('XRAY_ALLOW_MISSING_FEATURES', None)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        try:
            with (ROOT / step['log']).open('w') as log, subprocess.Popen(step['argv'], cwd=ROOT,
                    env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as child:
                step['pid'] = child.pid
                save()
                try:
                    code = child.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait()
                    step['returncode'] = child.returncode
                    raise
            step['returncode'] = code
            assert code == 0, (ROOT / step['log']).read_text()[-4000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    print(out / 'report.json', flush=True)
    before = {}
    try:
        parent = json.loads(parent_path.read_text())
        verify_feature_control_metadata(parent, parent['native_tool_transition'])
        bind_report(parent_path, parent, before)
        fasm_file = parent_path.parent / 'control.fasm'
        assert str(fasm_file) in before, 'Unbound actual native FASM'
        for path in (Path(__file__), ROOT / 'tests/cmac/test_prefix_frame_database_control.py',
                     CONVERTER, VALIDATOR, ADAPTER, PYTHON.resolve(strict=True), Path(sys.executable).resolve(strict=True)):
            before[str(path.resolve(strict=True))] = digest(path)
        # Bind the newly imported admission helper too; it postdates the
        # completed native control and is not in that parent's manifest.
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename:
                path = Path(filename).resolve()
                if path.is_relative_to(ROOT / 'tools'):
                    sha = digest(path)
                    assert str(path) not in before or before[str(path)] == sha, 'Changed imported admission helper'
                    before[str(path)] = sha
        report.update(source=before, feature_control_report=str(parent_path.relative_to(ROOT)),
            conversion_input=str(fasm_file.relative_to(ROOT)))
        verify_bindings(before)
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac',
                                 '-p', 'test_prefix_frame_database_control.py', '-v'], 120)
        run('generated_check', ['make', 'generated-check'], 120)
        run('parser_runtime_version', [PYTHON, '--version'], 60)
        report.update(stage='native_FASM_conversion', native_FASM_conversion_executed=True)
        destination = out / 'native-conversion'
        run('strict_native_FASM_conversion', [PYTHON, '-B', Path(__file__), '--worker', fasm_file, destination], 1800)
        result_path = destination / 'result.json'
        result = json.loads(result_path.read_text())
        frames = validate_conversion(result, destination)
        for name, sha in result['inputs'].items():
            assert name not in before or before[name] == sha, 'Conflicting converter binding'
            before[name] = sha
        report.update(native_conversion_result=str(result_path.relative_to(ROOT)),
            converter_requests=result['counts'], stage='exact_part_frame_geometry_validation',
            exact_part_frame_validation_executed=True)
        validation_path = out / 'frame-validation.json'
        run('exact_part_frame_geometry', [PYTHON, '-B', VALIDATOR, '--frames', frames,
            '--part', DATABASE / PART / 'part.json', '--tilegrid', DATABASE / 'xc7k480t/tilegrid.json',
            '--output', validation_path], 120)
        validation = json.loads(validation_path.read_text())
        assert validation['status'] == 'FRAME_INPUT_VALIDATION_PASS_ASSEMBLY_PENDING'
        assert validation['physical_verified'] is False and validation['inputs_unchanged'] is True
        report['frame_geometry'] = validation['validation']
        verify_bindings(before)
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
