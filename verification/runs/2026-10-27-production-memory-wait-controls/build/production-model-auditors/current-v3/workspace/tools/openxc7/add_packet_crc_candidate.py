#!/usr/bin/env python3
"""Add only CRC checks to the literal qualified SMALL native packet sample.

Offline encoding control, not a smaller substitute for the full C32/K16 goal.
Original frames, ordinary register/startup words, encoder and inputs are never
changed. Exactly two CRC packets precede the existing post-data/post-startup
resets; only the .bit payload length changes in the original header. Output
remains NOT_FOR_PROGRAMMING, never physical/numerical/full-target signoff.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_packet_crc as reader
from pack_prefix_board import ROOT, digest, timestamp
from place_prefix_board import verify_bindings
from evidence import source_revision

PARENT = ROOT / 'build/openxc7/small-native-heap-bit-encoding-1791491349869461344/report.json'
CONTROL = ROOT / 'tests/cmac/test_packet_crc_emission_control.py'
READER_SHA = 'ac8410088b1283c1d5fc1c090bcd38bd6e35ab460b7285c687ce89d34185e1e0'
INPUT_SHA = '35f6459a5d2a082d815cfb1e8586fd29517e25020868d8b8dfb038d4075e9519'
WORDS = 4683168
# Exact native Series7 builder profile, bound to the inspected pinned source.
# Empty/data FDRI ownership is represented separately; no write is ignored.
PROFILE = [(17, 0), (16, 0), (4, 0), (4, 7), (19, 0), (9, 0x02003fe5),
           (14, 0), (12, reader.IDCODE), (4, 9), (6, 0x401), (5, 0x501),
           (6, 0), (24, 0), (1, 0), (4, 1), (2, 'EMPTY'), (2, 'DATA'),
           (4, 7), (4, 10), (4, 3), (4, 5), (1, 0x03be0000),
           (6, 0x501), (5, 0x501), (4, 7), (4, 13)]
FLAGS = ('physical_configuration_crc_verified', 'configuration_crc_verified',
         'timing_signoff', 'electrical_verified', 'drc_signoff', 'numerical_acceptance',
         'full_target_acceptance', 'test_ready_bitstream', 'hardware_programmed',
         'original_input_modified', 'original_encoder_modified', 'new_native_assembly_executed')


def native_profile(data, fdri_words=WORDS):
    reader.require(type(fdri_words) is int and fdri_words > 0, 'Invalid expected frame-data word count')
    observed, packet_count = [], 0
    for _, reg, values in reader.packets(data):
        packet_count += 1
        if reg is None:
            continue
        if reg == 2:
            reader.require(len(values) in (0, 4 * fdri_words), 'Changed complete FDRI length')
            observed.append((reg, 'DATA' if values else 'EMPTY'))
        else:
            reader.require(len(values) == 4, 'Changed native scalar count')
            observed.append((reg, struct.unpack('>I', values)[0]))
    reader.require(observed == PROFILE, 'Changed native register/startup profile')
    return packet_count


def inject(raw, fdri_words=WORDS):
    """Pure byte transform; fdri_words override is for bounded host fixtures only."""
    _, data = reader.payload(raw, reader.PART)
    packet_count = native_profile(data, fdri_words)
    state, initialized, dirty, cursor = 0, False, 0, 0
    pieces, insertions = [], []
    for offset, reg, values in reader.packets(data):
        if reg is None:
            continue
        scalar = struct.unpack('>I', values)[0] if reg != 2 else None
        if reg == 4 and scalar == 7:
            if initialized and dirty:
                pieces.extend((data[cursor:offset * 4], struct.pack('>II', 0x30000001, state)))
                insertions.append(dict(original_payload_word=offset, crc=state, covered_words=dirty))
                cursor = offset * 4
            state, initialized, dirty = 0, True, 0
        elif reg == 4 and scalar == 13:
            reader.require(initialized and dirty == 0, 'Unchecked data at DESYNC')
        elif initialized:
            for (word,) in struct.iter_unpack('>I', values):
                state = reader.update(reg, word, state)
                dirty += 1
    reader.require(len(insertions) == 2 and dirty == 0, 'Missing exact two CRC checks')
    pieces.append(data[cursor:])
    updated = b''.join(pieces)
    reader.require(len(updated) == len(data) + 16, 'Changed non-CRC payload length')
    # Independent literal projection: delete only newly inserted CRC packets.
    projection, cursor = [], 0
    for index, insertion in enumerate(insertions):
        offset = insertion['original_payload_word'] * 4 + index * 8
        projection.append(updated[cursor:offset])
        reader.require(updated[offset:offset + 8] == struct.pack('>II', 0x30000001, insertion['crc']), 'Changed inserted packet')
        cursor = offset + 8
    projection.append(updated[cursor:])
    reader.require(b''.join(projection) == data, 'Original packet/frame bytes changed')
    base = len(raw) - len(data)
    result = raw[:base - 4] + struct.pack('>I', len(updated)) + updated
    reader.require(result[:base - 4] == raw[:base - 4], 'Original metadata changed')
    checked = reader.verify(result)
    reader.require(checked['fdri_words'] == fdri_words and len(checked['crc_checks']) == 2, 'Incomplete CRC coverage')
    return result, dict(original_packet_count=packet_count, original_payload_bytes=len(data),
        candidate_payload_bytes=len(updated), crc_insertions=insertions,
        original_payload_projection_byte_identical=True, original_header_except_length_byte_identical=True,
        crc_verification=checked)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    saved = json.loads(PARENT.read_text())
    reader.require(saved['status'] == 'PASS_SMALL_NATIVE_HEAP_PACKET_DATA_AND_FRAME_ECC_NOT_FULL_BITSTREAM_OR_SIGNOFF'
        and saved['stage'] == 'complete' and saved['configuration_crc_verified'] is False
        and saved['native_control_dsps'] == 4 and saved['native_control_brams'] == 6,
        'Require exact completed small encoding control, not full acceptance')
    path = Path(saved['small_unreviewed_packet_artifact']['path']).resolve(strict=True)
    reader.require(path.parent == PARENT.parent and digest(path) == INPUT_SHA
        and saved['small_unreviewed_packet_artifact']['sha256'] == INPUT_SHA,
        'Changed literal small packet')
    reader.require(digest(Path(reader.__file__)) == READER_SHA, 'Changed qualified CRC reader')
    out = ROOT / f'build/openxc7/small-packet-crc-candidate-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), finished_utc=None,
        supervisor_pid=os.getpid(), scope=__doc__, parent_packet_report=str(PARENT),
        part=reader.PART, native_control_dsps=4, native_control_brams=6,
        full_target_parallel_products=512, source={}, crc_only_byte_transform=None,
        production_source_before=source_revision(), **dict.fromkeys(FLAGS, False))

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    save(); print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        shutil.copyfile(__file__, out / 'executed_source.py')
        shutil.copyfile(CONTROL, out / 'executed_control_source.py')
        before = dict(saved['source'])
        for item in (PARENT, path, Path(__file__), CONTROL, Path(reader.__file__), Path(sys.executable).resolve()):
            before[str(item.resolve())] = digest(item)
        # These are immutable qualification references, not inherited hardware
        # acceptance; CRC is freshly calculated and verified for this candidate.
        for item in (ROOT / 'build/packet_crc_reader_qualification_actual_20261009.md',
                     ROOT / 'build/packet_crc_first_xray_normal_actual_20261009.log',
                     ROOT / 'build/packet_crc_xray_corpus_controls_actual_20261009.log',
                     ROOT / 'build/packet_crc_header_comparison_actual_20261009.log'):
            before[str(item.resolve(strict=True))] = digest(item)
        verify_bindings(before)
        report.update(source=before, stage='crc_only_transform'); save()
        result, evidence = inject(path.read_bytes())
        reader.require(evidence['original_packet_count'] == 546, 'Changed complete native packet census')
        candidate = out / 'small-control.CRC-candidate.NOT_FOR_PROGRAMMING.unverified.bit'
        with candidate.open('xb') as stream:
            stream.write(result)
        verify_bindings(before)
        reader.require(digest(candidate) == hashlib.sha256(result).hexdigest(), 'Candidate changed after write')
        report['production_source_after'] = source_revision()
        reader.require(report['production_source_after'] == report['production_source_before'], 'Production source changed')
        reader.require(all(report[k] is False for k in FLAGS), 'Unsupported acceptance changed')
        report.update(status='EMITTED_SMALL_CRC_ONLY_PACKET_CANDIDATE_NOT_NATIVE_READBACK_OR_SIGNOFF',
            stage='complete', candidate=str(candidate), candidate_sha256=digest(candidate),
            crc_only_byte_transform=evidence, packet_crc_checks_match=True,
            all_parent_packet_sources_revalidated=True, python_version=sys.version)
    except BaseException as error:
        report.update(status='FAIL_SMALL_CRC_ONLY_PACKET_CANDIDATE', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
            if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
