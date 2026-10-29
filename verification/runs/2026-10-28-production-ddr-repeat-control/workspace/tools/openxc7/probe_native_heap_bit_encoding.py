#!/usr/bin/env python3
"""Qualify packet assembly/readback of the completed SMALL native frame control.

The full C32/K16 target remains unchanged and pending. This offline control
assembles only the admitted four-DSP/six-BRAM sample, preserving its exact
validated frames. It checks native decoding, all 46,336 frames/4,679,936 words,
frame ECC and actual decoded-data/ECC corruption negatives. It NEVER creates
a reviewed/test-ready full-board image, changes physical constraints, checks
configuration CRC, programs hardware or writes a SHA256SUMS manifest.
"""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert_full_heap_frames as parent
from place_prefix_board import bind_report, verify_bindings
from pack_prefix_board import ROOT, digest, timestamp
from evidence import source_revision

SMALL = parent.SMALL
CONTROL = ROOT / 'tests/cmac/test_native_heap_bit_encoding_control.py'
PASS = 'PASS_SMALL_NATIVE_HEAP_PACKET_DATA_AND_FRAME_ECC_NOT_FULL_BITSTREAM_OR_SIGNOFF'
DONOR = Path('/home/fedora/soDLA/tools')
FLAGS = ('full_target_bitstream_emitted', 'test_ready_bitstream', 'timing_signoff',
         'electrical_verified', 'drc_signoff', 'configuration_crc_verified',
         'hardware_programmed', 'numerical_acceptance', 'new_native_PNR_executed')


def verify_comparison(result, source_frames):
    assert result['status'] == 'BITSTREAM_FRAME_DATA_AND_CONFIGURATION_ECC_PASS'
    assert result['inputs_unchanged'] is True
    assert result['physical_verified'] is False and result['configuration_crc_verified'] is False
    checked = result['verification']
    assert checked['decoded_frames'] == 46336 and checked['compared_words'] == 4679936
    assert checked['source_frames'] == source_frames == 45892
    assert checked['zero_filled_frames'] == 444
    assert checked['configuration_frame_ecc_compared'] is True
    assert checked['nonzero_words_including_ecc'] > 0
    return checked


def corrupt_decoded(source, destination, word_index):
    """Flip exactly one actual decoded bit in a COMPARISON-ONLY copy."""
    assert word_index in (0, 50) and source.resolve() != destination.resolve()
    address, index, flipped = None, 0, False
    with source.open() as reader, destination.open('x') as writer:
        for line in reader:
            fields = line.split()
            if not flipped and fields and fields[0] == '.frame':
                assert len(fields) == 2 and address is None
                address = int(fields[1], 16)
            elif not flipped and fields:
                assert address is not None
                assert all(re.fullmatch('[0-9a-fA-F]{8}', token) for token in fields)
                if index <= word_index < index + len(fields):
                    offset = word_index - index
                    fields[offset] = f'{int(fields[offset], 16) ^ 1:08x}'
                    line = ' '.join(fields) + '\n'
                    flipped = True
                index += len(fields)
            writer.write(line)
    assert flipped, 'No actual decoded word to corrupt'
    return f'Decoded frame {address:#x} word {word_index} differs:'


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    saved = json.loads(SMALL.read_text())
    parent.verify_small_metadata(saved)  # Failed/incomplete/full profiles cannot create output.
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/openxc7/small-native-heap-bit-encoding-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), finished_utc=None,
                  supervisor_pid=os.getpid(), scope=__doc__, parent_frame_report=str(SMALL),
                  full_target_parallel_products=512, native_control_dsps=4, native_control_brams=6,
                  part='xc7k480tffg1156-2', source={}, commands=[],
                  production_source_before=source_revision(), **dict.fromkeys(FLAGS, False))

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, expected=0):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')),
                    status='RUNNING', expected_returncode=expected, timeout_seconds=600)
        report['commands'].append(step); save()
        started = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                step['pid'] = process.pid; save()
                try:
                    code = process.wait(timeout=600)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == expected, text[-3000:]
            assert not re.search(r'(?im)\b(?:warning|error|fatal)\s*:|\bsorry:', text), text[-3000:]
            step['status'] = 'PASS_TOOL_OR_CONTROL_ONLY'
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save(); print(out / 'report.json', flush=True)
    try:
        shutil.copyfile(__file__, out / 'executed_source.py')
        shutil.copyfile(CONTROL, out / 'executed_control_source.py')
        before = {}; bind_report(SMALL, saved, before)
        verify_bindings(before)
        assert source_revision() == saved['production_source_after']
        sys.path.insert(0, str(DONOR))
        import ypcb_assemble_openxc7 as donor
        import ypcb_bitstream
        frame = parent.small.original.frame
        donor.check_sources(frame.TOOL)
        methods, decoder, qualified, qualification_path = donor.verified_frame_tools(frame.TOOL)
        assembler = frame.TOOL / 'prjxray-build/tools/xc7frames2bit'
        assert qualified[str(assembler)] == digest(assembler), 'Assembler lacks actual donor qualification binding'
        for name, sha in qualified.items():
            assert name not in before or before[name] == sha
            before[name] = sha
        files = {Path(__file__), CONTROL, Path(sys.executable).resolve(), assembler, decoder,
                 frame.PYTHON.resolve(), frame.DATABASE / frame.PART / 'part.yaml'}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and
                     (Path(m.__file__).resolve().is_relative_to(ROOT / 'tools') or
                      Path(m.__file__).resolve().is_relative_to(DONOR)))
        for path in files:
            name, sha = str(path.resolve(strict=True)), digest(path)
            assert name not in before or before[name] == sha
            before[name] = sha
        conversion_path = SMALL.parent / 'native-conversion/result.json'
        converted = json.loads(conversion_path.read_text())
        frames = frame.validate_conversion(converted, conversion_path.parent)
        validation = SMALL.parent / 'frame-validation.json'
        assert str(frames) in before and str(validation) in before
        verify_bindings(before)
        native_path = Path(saved['saved_native_evidence_report']).resolve(strict=True)
        assert str(native_path) in before
        native = json.loads(native_path.read_text())
        pnr = [c for c in native['commands'] if c['label'] == 'small_native_PNR_FASM']
        assert len(pnr) == 1 and pnr[0]['returncode'] == 0
        assert pnr[0]['argv'][pnr[0]['argv'].index('--seed') + 1] == '3588'
        report.update(source=before, stage='software_controls', frame_input=str(frames),
                      donor_frame_tool_qualification=str(qualification_path), assembler=str(assembler), decoder=str(decoder),
                      tool_source_pins=donor.PINS, full_target_seed=3588,
                      saved_native_execution_seed=3588, saved_native_PNR_report=str(native_path))
        run('prjxray_source_revision', ['git', '-C', frame.TOOL / 'prjxray', 'rev-parse', 'HEAD'])
        assert Path(report['commands'][-1]['log']).read_text().strip() == donor.PINS['prjxray']
        run('native_assembler_version', [assembler, '--version'])
        report['assembler_version'] = Path(report['commands'][-1]['log']).read_text().strip()
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        report['stage'] = 'native_small_packet_assembly'; save()
        bit = out / 'small-control.NOT_FOR_PROGRAMMING.unverified.bit'
        part_yaml = frame.DATABASE / frame.PART / 'part.yaml'
        part_json = frame.DATABASE / frame.PART / 'part.json'
        run('native_frames_to_bit', [assembler, '--part_file', part_yaml, '--part_name', frame.PART,
                                    '--frm_file', frames, '--output_file', bit])
        metadata = ypcb_bitstream.inspect(bit)
        decoded = out / 'decoded.frames'
        run('native_decode_frames', [decoder, '--part_file', part_yaml, '-C', '-o', decoded, bit])
        verification = methods['verify_bitstream_frames.py']
        comparison = out / 'frame-comparison.json'
        def comparison_argv(data, result):
            return [frame.PYTHON, '-B', verification, '--frames', frames, '--decoded', data,
                    '--part', part_json, '--validation', validation, '--output', result]
        run('all_frame_data_and_ECC', comparison_argv(decoded, comparison))
        report['frame_verification'] = verify_comparison(json.loads(comparison.read_text()),
                                                        saved['frame_geometry']['supplied_frames'])
        negatives = []
        for label, index in (('data_bit', 0), ('ECC_bit', 50)):
            corrupted = out / ('comparison-only-corrupt-' + label + '.frames')
            prefix = corrupt_decoded(decoded, corrupted, index)
            result_path = out / ('negative-' + label + '.json')
            run('negative_' + label, comparison_argv(corrupted, result_path), 1)
            failed = json.loads(result_path.read_text())
            assert failed['status'] == 'FAIL' and failed['failure'].startswith(prefix)
            assert failed['physical_verified'] is False and failed['configuration_crc_verified'] is False
            negatives.append(dict(word=index, expected_actual_difference=prefix, rejected=True))
        report['actual_decoded_bit_negatives'] = negatives
        assert digest(bit) == metadata['sha256']
        verify_bindings(before); donor.check_sources(frame.TOOL)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        assert all(report[key] is False for key in FLAGS)
        report.update(status=PASS, stage='complete', small_unreviewed_packet_artifact=metadata)
    except BaseException as error:
        report.update(status='FAIL_SMALL_NATIVE_HEAP_BIT_ENCODING', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
