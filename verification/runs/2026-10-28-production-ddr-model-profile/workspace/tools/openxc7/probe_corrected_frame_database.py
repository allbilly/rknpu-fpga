#!/usr/bin/env python3
"""Convert actual corrected native FASM and read back its 64 added DSP features.

Use the unchanged strict converter with raw native FASM as its only circuit
input. Expected DSP features are secondary readback targets, never assembly
inputs. Complete exact-part frame geometry is checked separately. This small
encoder-chain control is not a bitstream, full routing or physical signoff.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_prefix_frame_database as frame
from verify_corrected_native_evidence import NATIVE, IDENTITY, verify_corrected_evidence
from audit_upstream_dsp_constants import sample_gap
from probe_prefix_native_config import SELECTED, parse_native_features
from pack_prefix_board import ROOT, timestamp, digest
from place_prefix_board import verify_bindings
from evidence import source_revision

CONTROL = ROOT / 'tests/cmac/test_corrected_frame_database_control.py'
PASS = 'PASS_CORRECTED_NATIVE_FASM_EXACT_PART_FRAMES_AND_64_DSP_FEATURE_BITS_NOT_BITSTREAM_OR_SIGNOFF'


def required_features(q):
    selected = json.loads(SELECTED.read_text())
    features, _ = parse_native_features((NATIVE.parent / 'control.fasm').read_text())
    placements = json.loads((NATIVE.parent / 'placement.json').read_text())
    required = {}
    dsps = 0
    for name, source in q['control_origins'].items():
        if selected[source]['type'] != 'DSP48E1':
            continue
        gap = sample_gap(features, placements[name], selected[source])
        assert gap['absent_or_different_features'] == {}, 'Corrected native FASM lacks required DSP features'
        assert not set(required) & set(gap['required_features']), 'Aliased DSP control sites'
        required.update(gap['required_features'])
        dsps += 1
    assert dsps == 4 and len(required) == 64 and set(required.values()) == {'1'}
    return required


def request_features(request):
    name, value, start, end = (request[key] for key in ('feature', 'value', 'start', 'end'))
    assert type(value) is int and value >= 0 and request['kind'] in ('input_lines', 'injected_lines')
    if start is None:
        assert end is None and value in (0, 1)
        return [name] if value else []
    assert type(start) is int and start >= 0
    end = start if end is None else end
    assert type(end) is int and end >= start and value < 1 << (end - start + 1)
    return [f'{name}[{start + bit}]' for bit in range(end - start + 1) if value & (1 << bit)]


def verify_requests(requests, required):
    found = {key: 0 for key in required}
    counts = {'input_lines': 0, 'injected_lines': 0}
    for request in requests:
        enabled = request_features(request)
        counts[request['kind']] += 1
        if request['kind'] == 'input_lines':
            for key in enabled:
                if key in found:
                    found[key] += 1
    assert set(found.values()) == {1}, 'Missing/duplicate corrected native DSP feature request'
    return counts


def check_feature_bits(locations, words):
    assert locations and all(bits for bits in locations.values()), 'DSP feature has no physical DB bits'
    unique = set()
    for feature, bits in locations.items():
        for address, word, bit, expected in bits:
            assert type(expected) is bool and 0 <= word < 101 and 0 <= bit < 32
            assert address in words and len(words[address]) == 101, 'Missing DSP feature frame'
            assert bool(words[address][word] & (1 << bit)) == expected, 'Wrong corrected DSP frame bit: ' + feature
            unique.add((address, word, bit))
    return dict(features_compared=len(locations), physical_DB_bits_compared=len(unique),
                frames_read=len(words), all_set_and_clear_requirements_matched=True,
                database_consistency_only_not_silicon_or_independent_specification=True)


def readback(frames, required_path, output):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(frame.SOURCE))
    from prjxray.db import Database
    required = json.loads(required_path.read_text())
    assert len(required) == 64 and set(required.values()) == {'1'}
    database = Database(str(frame.DATABASE), frame.PART)
    grid = database.grid()
    locations = {}
    for feature in required:
        tile, key = feature.split('.', 1)
        info = grid.gridinfo_at_tilename(tile)
        assert info.tile_type in ('DSP_L', 'DSP_R')
        match = re.fullmatch(r'(.+)\[(\d+)\]', key)
        base, index = (match[1], int(match[2])) if match else (key, 0)
        segbits = grid.get_tile_segbits_at_tilename(tile)
        locations[feature] = [(bit.word_column, bit.word_bit // 32, bit.word_bit % 32, bit.isset)
            for _, bit in segbits.feature_to_bits(info.bits, info.tile_type + '.' + base, index)]
    wanted = {address for bits in locations.values() for address, _, _, _ in bits}
    words = {}
    with frames.open() as stream:
        for line in stream:
            address, payload = line.rstrip('\n').split(' ')
            address = int(address, 16)
            if address in wanted:
                assert address not in words, 'Duplicate DSP feature frame'
                words[address] = [int(word, 16) for word in payload.split(',')]
    result = check_feature_bits(locations, words)
    assert set(words) == wanted
    bad = deepcopy(words)
    address, word, bit, _ = next(iter(locations.values()))[0]
    bad[address][word] ^= 1 << bit
    try:
        check_feature_bits(locations, bad)
    except AssertionError:
        result['actual_frame_bit_corruption_rejected_in_comparison_only'] = True
    else:
        raise AssertionError('Corrupted actual DSP frame bit accepted')
    result.update(locations=locations, frames_sha256=digest(frames), required_features_sha256=digest(required_path))
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print('PASS actual corrected DSP frame-bit readback and comparison-only corruption negative')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--readback', nargs=3, type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.readback:
        readback(*args.readback)
        return
    out = ROOT / f'build/openxc7/corrected-frame-database-control-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source={}, commands=[], scope=__doc__, part=frame.PART, full_target_parallel_products=512,
        native_qualification_report=str(NATIVE), full_packed_identity_report=str(IDENTITY),
        native_control_dsps=4, native_control_brams=6, native_FASM_conversion_executed=False,
        exact_part_frame_validation_executed=False, actual_DSP_feature_frame_readback_executed=False,
        expected_features_used_for_conversion=False, full_board_FASM_conversion_executed=False,
        numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision())
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), log=str(out / (label + '.log')),
                    expected_returncode=0, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step)
        started = time.monotonic()
        save()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        assert 'XRAY_ALLOW_MISSING_FEATURES' not in env, 'No missing-feature override'
        try:
            with Path(step['log']).open('w') as log, subprocess.Popen(step['argv'], cwd=ROOT, env=env,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as child:
                step['pid'] = child.pid
                save()
                try: code = child.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait()
                    step['returncode'] = child.returncode
                    raise
            step['returncode'] = code
            assert code == 0, Path(step['log']).read_text()[-3500:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()
    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_corrected_evidence()
        for path in (Path(__file__), CONTROL, frame.CONVERTER, frame.VALIDATOR, frame.ADAPTER,
                     frame.PYTHON.resolve(strict=True), Path(sys.executable).resolve(strict=True)):
            before[str(path.resolve(strict=True))] = digest(path)
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                path, sha = Path(filename).resolve(), digest(filename)
                assert str(path) not in before or before[str(path)] == sha, 'Changed bound helper'
                before[str(path)] = sha
        fasm = NATIVE.parent / 'control.fasm'
        assert before[str(fasm)] == q['artifacts'][str(fasm.relative_to(ROOT))]
        required = required_features(q)
        expected = out / 'comparison-only-required-DSP-features.json'
        expected.write_text(json.dumps(required, indent=2, sort_keys=True) + '\n')
        before[str(expected)] = digest(expected)
        report.update(source=before, conversion_input=str(fasm), native_executable=q['executable'],
                      compared_added_DSP_features=len(required))
        verify_bindings(before)
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], 120)
        run('generated_check', ['make', 'generated-check'], 120)
        run('parser_runtime_version', [frame.PYTHON, '--version'], 60)
        destination = out / 'native-conversion'
        report.update(stage='native_FASM_conversion', native_FASM_conversion_executed=True)
        run('strict_native_FASM_conversion', [frame.PYTHON, '-B', frame.__file__, '--worker', fasm, destination])
        result = json.loads((destination / 'result.json').read_text())
        frames = frame.validate_conversion(result, destination)
        requests = [json.loads(line) for line in (destination / 'feature-requests.jsonl').read_text().splitlines()]
        assert verify_requests(requests, required) == result['counts']
        assert result['counts']['input_lines'] == q['native_FASM_features'] + len(q['native_FASM_repeated_idempotent_STEPDOWN_lines'])
        for name, sha in result['inputs'].items():
            assert name not in before or before[name] == sha, 'Conflicting converter binding'
            before[name] = sha
        report.update(converter_requests=result['counts'], all_64_added_DSP_features_requested_from_native_input=True,
                      stage='exact_part_frame_geometry', exact_part_frame_validation_executed=True)
        validation_path = out / 'frame-validation.json'
        run('exact_part_frame_geometry', [frame.PYTHON, '-B', frame.VALIDATOR, '--frames', frames,
            '--part', frame.DATABASE / frame.PART / 'part.json', '--tilegrid', frame.DATABASE / 'xc7k480t/tilegrid.json',
            '--output', validation_path], 120)
        validation = json.loads(validation_path.read_text())
        assert validation['status'] == 'FRAME_INPUT_VALIDATION_PASS_ASSEMBLY_PENDING'
        assert validation['physical_verified'] is False and validation['inputs_unchanged'] is True
        report.update(frame_geometry=validation['validation'], stage='DSP_frame_readback',
                      actual_DSP_feature_frame_readback_executed=True)
        readback_path = out / 'DSP-feature-readback.json'
        run('DSP_frame_readback', [frame.PYTHON, '-B', Path(__file__), '--readback', frames, expected, readback_path], 120)
        report['DSP_frame_readback'] = json.loads(readback_path.read_text())
        assert report['DSP_frame_readback']['features_compared'] == 64
        assert report['DSP_frame_readback']['actual_frame_bit_corruption_rejected_in_comparison_only'] is True
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.rglob('*')
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
