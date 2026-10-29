#!/usr/bin/env python3
"""Qualify completed SMALL CRC-only emission with native all-frame/ECC readback.

No original packet, encoder, frame input, expectation, physical guard or FPGA
is changed. Reject incomplete/cross-profile input before creating output or
executing tools. Fresh native decoding must match the saved decoded bytes and
all source frame/ECC words. Real new-candidate CRC/data corruptions are checked
separately against the frozen CRC reader. This is NOT full C32/K16 acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import add_packet_crc_candidate as emitter
import verify_packet_crc as reader
from pack_prefix_board import ROOT, digest, timestamp
from place_prefix_board import verify_bindings
from evidence import source_revision

CONTROL = ROOT / 'tests/cmac/test_crc_candidate_native_readback_control.py'
PASS = 'QUALIFIED_SMALL_CRC_ONLY_EMISSION_NATIVE_FRAME_ECC_READBACK_NOT_FULL_TARGET_OR_SIGNOFF'
EMITTED = 'EMITTED_SMALL_CRC_ONLY_PACKET_CANDIDATE_NOT_NATIVE_READBACK_OR_SIGNOFF'


def metadata(record):
    reader.require(record['status'] == EMITTED and record['stage'] == 'complete' and record['finished_utc'],
                   'Require genuinely completed CRC-only emitter')
    reader.require(record['part'] == reader.PART and record['native_control_dsps'] == 4
        and record['native_control_brams'] == 6 and record['full_target_parallel_products'] == 512,
        'Changed small/full target profile')
    reader.require(all(record[k] is False for k in emitter.FLAGS), 'Unsupported acceptance changed')
    reader.require(record['packet_crc_checks_match'] is True and record['all_parent_packet_sources_revalidated'] is True,
                   'Missing completed CRC/source checks')
    e = record['crc_only_byte_transform']
    reader.require(e['original_packet_count'] == 546 and e['original_payload_bytes'] == 18735004
        and e['candidate_payload_bytes'] == 18735020 and len(e['crc_insertions']) == 2,
        'Changed complete packet extent')
    reader.require(e['original_payload_projection_byte_identical'] is True
        and e['original_header_except_length_byte_identical'] is True,
        'Missing literal original-byte preservation')
    checked = e['crc_verification']
    reader.require(checked['status'] == 'PASS_SOFTWARE_PACKET_CRC_ONLY_NOT_SIGNOFF_OR_TEST_READY'
        and checked['part'] == reader.PART and checked['idcode'] == reader.IDCODE
        and checked['fdri_words'] == emitter.WORDS and len(checked['crc_checks']) == 2
        and checked['packet_crc_checks_match'] is True,
        'Incomplete packet-CRC extent')
    for key in ('physical_configuration_crc_verified', 'timing_signoff', 'electrical_verified',
                'drc_signoff', 'numerical_acceptance', 'full_target_acceptance',
                'test_ready_bitstream', 'hardware_accessed', 'input_modified'):
        reader.require(checked[key] is False, 'CRC-reader scope changed')


def comparison(record):
    reader.require(record['status'] == 'BITSTREAM_FRAME_DATA_AND_CONFIGURATION_ECC_PASS'
        and record['inputs_unchanged'] is True and record['physical_verified'] is False
        and record['configuration_crc_verified'] is False, 'Incomplete native frame comparison')
    counts = record['verification']
    reader.require((counts['decoded_frames'], counts['compared_words'], counts['source_frames'], counts['zero_filled_frames'])
        == (46336, 4679936, 45892, 444) and counts['configuration_frame_ecc_compared'] is True,
        'Incomplete exact-part frame/ECC coverage')
    return counts


def corrupt(raw, register):
    reader.require(register in (0, 2), 'Unsupported corruption role')
    _, data = reader.payload(raw, reader.PART)
    offset = next(offset for offset, reg, values in reader.packets(data) if reg == register and values)
    changed = bytearray(raw)
    changed[len(raw) - len(data) + (offset + 1) * 4 + 3] ^= 1
    reader.require(bytes(changed) != raw, 'Missing actual corruption')
    return bytes(changed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-report', type=Path, required=True)
    args = parser.parse_args()
    path = args.candidate_report.resolve(strict=True)
    reader.require(path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
        and re.fullmatch(r'small-packet-crc-candidate-[0-9]+', path.parent.name), 'Wrong producer ownership')
    emitted = json.loads(path.read_text()); metadata(emitted)
    reader.require(not Path(f"/proc/{emitted['supervisor_pid']}").exists(), 'Emitter still live')
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/openxc7/small-crc-packet-native-readback-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), finished_utc=None,
        supervisor_pid=os.getpid(), scope=__doc__, emitted_candidate_report=str(path), source={}, commands=[],
        production_source_before=source_revision(), **dict.fromkeys(emitter.FLAGS, False))

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, expected=0, timeout=900):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')),
            expected_returncode=expected, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step); save()
        started = time.monotonic()
        try:
            with Path(step['log']).open('x') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                step['pid'] = process.pid; save()
                try:
                    step['returncode'] = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode
                    raise
            text = Path(step['log']).read_text()
            reader.require(step['returncode'] == expected, text[-3000:])
            reader.require(not re.search(r'(?im)\b(?:warning|fatal)\s*:|\bsorry:', text), 'Unexpected native diagnostic')
            step['status'] = 'PASS_TOOL_OR_EXPECTED_CONTROL_ONLY'
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save(); print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        shutil.copyfile(__file__, out / 'executed_source.py')
        shutil.copyfile(CONTROL, out / 'executed_control_source.py')
        old_path = Path(emitted['parent_packet_report']).resolve(strict=True)
        reader.require(old_path == emitter.PARENT, 'Changed original packet owner')
        old = json.loads(old_path.read_text())
        reader.require(old['status'] == 'PASS_SMALL_NATIVE_HEAP_PACKET_DATA_AND_FRAME_ECC_NOT_FULL_BITSTREAM_OR_SIGNOFF',
                       'Changed original small encoding status')
        before = dict(emitted['source'])
        for name, sha in emitted['artifacts'].items():
            item = (ROOT / name).resolve(strict=True)
            reader.require(item.is_relative_to(path.parent), 'Emitter artifact outside owner')
            before[str(item)] = sha
        for item in (path, Path(__file__), CONTROL, Path(reader.__file__), Path(emitter.__file__), Path(sys.executable).resolve()):
            before[str(item.resolve())] = digest(item)
        candidate = Path(emitted['candidate']).resolve(strict=True)
        reader.require(candidate.parent == path.parent and before[str(candidate)] == emitted['candidate_sha256'],
                       'Changed candidate ownership/fingerprint')
        verify_bindings(before)
        report.update(source=before, candidate=str(candidate), stage='fresh_host_controls'); save()
        run('host_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
            '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        decoded = out / 'decoded.frames'
        original_decode = next(c for c in old['commands'] if c['label'] == 'native_decode_frames')
        reader.require(original_decode['returncode'] == 0 and Path(original_decode['argv'][0]).resolve() == Path(old['decoder']).resolve(),
                       'Missing original qualified native decoder')
        argv = list(original_decode['argv'])
        argv[argv.index('-o') + 1] = str(decoded)
        argv[-1] = str(candidate)
        report['stage'] = 'fresh_native_frame_decode'; save()
        run('native_crc_candidate_decode', argv)
        original_decoded = Path(original_decode['argv'][original_decode['argv'].index('-o') + 1]).resolve(strict=True)
        reader.require(digest(decoded) == old['artifacts'][str(original_decoded.relative_to(ROOT))],
                       'Native decoded original bytes changed')
        original_compare = next(c for c in old['commands'] if c['label'] == 'all_frame_data_and_ECC')
        reader.require(original_compare['returncode'] == 0, 'Missing original all-frame comparator')
        result_path = out / 'frame-comparison.json'
        argv = list(original_compare['argv'])
        argv[argv.index('--decoded') + 1] = str(decoded)
        argv[argv.index('--output') + 1] = str(result_path)
        run('fresh_all_frame_data_and_ECC', argv)
        report['frame_verification'] = comparison(json.loads(result_path.read_text()))
        run('fresh_candidate_packet_crc', [sys.executable, '-B', '-W', 'error', reader.__file__, candidate])
        checked = json.loads(Path(report['commands'][-1]['log']).read_text())
        reader.require(checked['packet_crc_checks_match'] is True and checked['fdri_words'] == emitter.WORDS,
                       'Incomplete fresh CRC check')
        negatives = []
        for name, register in (('frame_data_bit', 2), ('CRC_word_bit', 0)):
            broken = out / ('comparison-only-' + name + '.bit')
            with broken.open('xb') as stream: stream.write(corrupt(candidate.read_bytes(), register))
            run('negative_' + name, [sys.executable, '-B', '-W', 'error', reader.__file__, broken], 1)
            result = json.loads(Path(report['commands'][-1]['log']).read_text())
            reader.require(result['status'] == 'FAIL_SOFTWARE_PACKET_CRC' and result['error'].startswith('CRC mismatch at payload word ')
                and result['test_ready_bitstream'] is False and result['hardware_accessed'] is False,
                'Wrong actual CRC negative failure')
            negatives.append(dict(role=name, rejected=True, failure=result['error']))
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        reader.require(report['production_source_after'] == report['production_source_before'], 'Production source changed')
        reader.require(all(report[k] is False for k in emitter.FLAGS), 'Unsupported signoff changed')
        report.update(status=PASS, stage='complete', native_decoded_bytes_identical_to_original=True,
            packet_crc_checks_match=True, fresh_all_frame_ECC_readback_verified=True, actual_candidate_crc_negatives=negatives)
    except BaseException as error:
        report.update(status='FAIL_SMALL_CRC_CANDIDATE_NATIVE_READBACK', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
            if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
