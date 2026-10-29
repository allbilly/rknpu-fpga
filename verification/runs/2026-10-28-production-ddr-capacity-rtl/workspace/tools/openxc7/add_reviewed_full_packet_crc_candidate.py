#!/usr/bin/env python3
"""Prepared CRC-only encoding of the completed FULL C32/K16 native packet.

Admit the frozen reviewed-full packet producer and the actual completed small
native CRC readback control. Preserve every original packet/frame/header byte
except the payload-length field and two inserted CRC writes. The original
encoder, input, hardware, expectations and physical guards are unchanged.
This emits only NOT_FOR_PROGRAMMING encoding evidence, never test readiness.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import add_packet_crc_candidate as small
import check_crc_candidate_native_readback as readback
import assemble_physical_scope_reviewed_recursive_mux_unreviewed_bits as producer
from pack_prefix_board import ROOT, digest, timestamp
from place_prefix_board import bind_report, verify_bindings
from evidence import source_revision

CONTROL = ROOT / 'tests/cmac/test_reviewed_full_packet_crc_emission_control.py'
QUALIFICATION = ROOT / 'build/openxc7/small-crc-packet-native-readback-1791510144013646328/report.json'
PASS = 'EMITTED_FULL_C32K16_CRC_ONLY_PACKET_CANDIDATE_NOT_NATIVE_READBACK_OR_SIGNOFF'
FLAGS = small.FLAGS + ('physical_fit_verified', 'reviewed_full_target_bitstream_emitted')
LABELS = ['prjxray_source_revision', 'native_assembler_version', 'software_controls',
          'generated_check', 'native_frames_to_bit', 'native_decode_frames',
          'all_frame_data_and_ECC', 'negative_data_bit', 'negative_ECC_bit']
QLABELS = ['host_controls', 'generated_check', 'native_crc_candidate_decode',
           'fresh_all_frame_data_and_ECC', 'fresh_candidate_packet_crc',
           'negative_frame_data_bit', 'negative_CRC_word_bit']


def commands(record, labels, status):
    small.reader.require([c['label'] for c in record['commands']] == labels,
                         'Changed complete native/control execution list')
    for step in record['commands']:
        expected = 1 if step['label'].startswith('negative_') else 0
        small.reader.require(step['status'] == status
            and step['returncode'] == step['expected_returncode'] == expected
            and type(step['pid']) is int and step['pid'] > 0,
            'Missing actual native execution or corruption negative')


def metadata(record):
    small.reader.require(record['status'] == producer.PASS
        and record['stage'] == 'complete' and record['finished_utc'],
        'Require genuinely completed reviewed full packet producer')
    small.reader.require((record['channels'], record['kernels'],
        record['full_target_parallel_products'], record['native_target_dsps'],
        record['native_target_brams'], record['part'], record['full_target_seed'],
        record['saved_native_execution_seed']) == (32, 16, 512, 515, 6, small.reader.PART, 3588, 3588),
        'Changed full C32/K16 packet target')
    small.reader.require(record['full_target_bitstream_emitted'] is True
        and all(record[k] is False for k in producer.FLAGS),
        'Changed unreviewed producer acceptance scope')
    small.reader.require(record['production_source_before'] == record['production_source_after'],
                         'Production source changed during full packet production')
    commands(record, LABELS, 'PASS_TOOL_OR_CONTROL_ONLY')
    small.reader.require(readback.comparison(dict(
        status='BITSTREAM_FRAME_DATA_AND_CONFIGURATION_ECC_PASS', inputs_unchanged=True,
        physical_verified=False, configuration_crc_verified=False,
        verification=record['frame_verification'])) == record['frame_verification'],
        'Incomplete original full frame/ECC extent')
    negative = record['actual_decoded_bit_negatives']
    small.reader.require([item['word'] for item in negative] == [0, 50]
        and all(item['rejected'] is True and item['expected_actual_difference'].startswith('Decoded frame ')
                for item in negative), 'Missing actual original data/ECC bit negatives')
    small.reader.require(type(record['supervisor_pid']) is int and record['supervisor_pid'] > 0,
                         'Invalid original producer supervisor')


def qualification(record):
    small.reader.require(record['status'] == readback.PASS and record['stage'] == 'complete'
        and record['finished_utc'], 'Require completed actual small native CRC qualification')
    small.reader.require(record['production_source_before'] == record['production_source_after']
        and all(record[k] is False for k in small.FLAGS), 'Changed small qualification scope/source')
    for field in ('native_decoded_bytes_identical_to_original', 'packet_crc_checks_match',
                  'fresh_all_frame_ECC_readback_verified'):
        small.reader.require(record[field] is True, 'Missing actual CRC/native frame readback')
    readback.comparison(dict(status='BITSTREAM_FRAME_DATA_AND_CONFIGURATION_ECC_PASS',
        inputs_unchanged=True, physical_verified=False, configuration_crc_verified=False,
        verification=record['frame_verification']))
    commands(record, QLABELS, 'PASS_TOOL_OR_EXPECTED_CONTROL_ONLY')
    negatives = record['actual_candidate_crc_negatives']
    small.reader.require([n['role'] for n in negatives] == ['frame_data_bit', 'CRC_word_bit']
        and all(n['rejected'] is True and n['failure'].startswith('CRC mismatch at payload word ')
                for n in negatives), 'Missing actual emitted-candidate CRC negatives')
    small.reader.require(type(record['supervisor_pid']) is int and record['supervisor_pid'] > 0,
                         'Invalid qualification supervisor')


def closed(record):
    for pid in [record['supervisor_pid']] + [step['pid'] for step in record['commands']]:
        small.reader.require(not Path(f'/proc/{pid}').exists(), 'Native producer/control still live')


def snapshots(path, record, module, prepared=False):
    expected = {'executed_source.py': Path(module.__file__).read_text(),
                'executed_control_source.py': module.CONTROL.read_text()}
    if prepared:
        expected['executed_prepared_main.py'] = module.MAIN_SOURCE
    for name, value in expected.items():
        item = path.parent / name
        small.reader.require(record['artifacts'][str(item.relative_to(ROOT))] == digest(item)
            and item.read_text() == value, 'Changed actual frozen producer/control snapshot')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet-report', type=Path, required=True)
    args = parser.parse_args()
    path = args.packet_report.resolve(strict=True)
    small.reader.require(path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
        and re.fullmatch(r'full-reviewed-recursive-mux-physical-scope-unreviewed-bit-encoding-[0-9]+', path.parent.name),
        'Wrong full packet producer ownership')
    saved = json.loads(path.read_text()); metadata(saved)
    qualified = json.loads(QUALIFICATION.read_text()); qualification(qualified)
    closed(saved); closed(qualified)
    small.reader.require(digest(Path(small.reader.__file__)) == small.READER_SHA,
                         'Changed independently qualified CRC reader')
    snapshots(path, saved, producer, True); snapshots(QUALIFICATION, qualified, readback)
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/openxc7/full-reviewed-packet-crc-candidate-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), finished_utc=None,
        supervisor_pid=os.getpid(), scope=__doc__, parent_packet_report=str(path),
        small_crc_native_qualification=str(QUALIFICATION), part=small.reader.PART,
        channels=32, kernels=16, parallel_products=512, native_target_dsps=515,
        native_target_brams=6, intended_clock_period_ns=20, seed=3588, source={},
        production_source_before=source_revision(), **dict.fromkeys(FLAGS, False))

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    save(); print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        shutil.copyfile(__file__, out / 'executed_source.py')
        shutil.copyfile(CONTROL, out / 'executed_control_source.py')
        before = {}; bind_report(path, saved, before)
        bind_report(QUALIFICATION, qualified, before)
        for module in (sys.modules[__name__], small, small.reader, readback, producer):
            for item in (Path(module.__file__).resolve(), module.CONTROL if hasattr(module, 'CONTROL') else Path(module.__file__).resolve()):
                key, value = str(item), digest(item)
                small.reader.require(key not in before or before[key] == value, 'Conflicting producer/control binding')
                before[key] = value
        item = Path(sys.executable).resolve(); before[str(item)] = digest(item)
        verify_bindings(before)
        small.reader.require(report['production_source_before'] == saved['production_source_after']
            == qualified['production_source_after'], 'Changed production revision after qualification')
        frame_path = Path(saved['parent_frame_report']).resolve(strict=True)
        small.reader.require(str(frame_path) in before, 'Missing bound full frame producer')
        producer.verify_full_frame_metadata(json.loads(frame_path.read_text()))
        packet = Path(saved['full_unreviewed_packet_artifact']['path']).resolve(strict=True)
        small.reader.require(packet.parent == path.parent and before[str(packet)]
            == saved['full_unreviewed_packet_artifact']['sha256'] == digest(packet), 'Changed literal full packet')
        report.update(source=before, original_packet=str(packet), stage='crc_only_transform'); save()
        result, evidence = small.inject(packet.read_bytes())
        small.reader.require((evidence['original_packet_count'], evidence['original_payload_bytes'],
            evidence['candidate_payload_bytes']) == (546, 18735004, 18735020), 'Changed complete native packet extent')
        candidate = out / 'full-C32K16.CRC-candidate.NOT_FOR_PROGRAMMING.unverified.bit'
        with candidate.open('xb') as stream:
            stream.write(result)
        verify_bindings(before)
        small.reader.require(digest(candidate) == hashlib.sha256(result).hexdigest(), 'Candidate changed after write')
        report['production_source_after'] = source_revision()
        small.reader.require(report['production_source_after'] == report['production_source_before'], 'Production source changed')
        small.reader.require(all(report[k] is False for k in FLAGS), 'Unsupported acceptance changed')
        report.update(status=PASS, stage='complete', candidate=str(candidate), candidate_sha256=digest(candidate),
            crc_only_byte_transform=evidence, packet_crc_checks_match=True,
            all_parent_packet_sources_revalidated=True, python_version=sys.version)
    except BaseException as error:
        report.update(status='FAIL_FULL_REVIEWED_CRC_ONLY_PACKET_CANDIDATE', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
            if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
