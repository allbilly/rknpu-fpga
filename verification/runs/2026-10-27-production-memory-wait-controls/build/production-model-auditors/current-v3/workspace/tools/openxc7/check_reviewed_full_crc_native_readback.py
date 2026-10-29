#!/usr/bin/env python3
"""Prepared full-target readback of the strict CRC-only candidate.

Keep the qualified small checker's complete native decode, original-byte
comparison, all-frame/ECC readback, fresh CRC check and actual data/CRC bit
negatives. Change only full producer admission, archival identity and explicit
full profile metadata; reject conflicting source bindings rather than replace
them. No original helper/input or physical/numerical acceptance is changed.
"""
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import add_reviewed_full_packet_crc_candidate as full
import check_crc_candidate_native_readback as previous
from audit_empty_output_pairs import source_shaped

ROOT = full.ROOT
CONTROL = ROOT / 'tests/cmac/test_reviewed_full_crc_readback_control.py'
PASS = 'QUALIFIED_FULL_C32K16_CRC_ONLY_EMISSION_NATIVE_FRAME_ECC_READBACK_NOT_SIGNOFF_OR_TEST_READY'
EMITTED = full.PASS
emitter = SimpleNamespace(FLAGS=full.FLAGS, WORDS=full.small.WORDS, __file__=full.__file__)
reader = full.small.reader

METADATA_REPLACEMENTS = (
    ("record['native_control_dsps'] == 4", "record['native_target_dsps'] == 515"),
    ("record['native_control_brams'] == 6", "record['native_target_brams'] == 6"),
    ("record['full_target_parallel_products'] == 512", "record['parallel_products'] == 512"),
    ('genuinely completed CRC-only emitter', 'genuinely completed full CRC-only emitter'),
    ('Changed small/full target profile', 'Changed full C32/K16 target profile'),
)
METADATA_SOURCE = source_shaped(inspect.getsource(previous.metadata), METADATA_REPLACEMENTS)
METADATA_NAMESPACE = dict(previous.__dict__, emitter=emitter, EMITTED=EMITTED)
exec(compile(METADATA_SOURCE, __file__ + ':same-exact-packet-coverage-and-false-acceptance-guards', 'exec'), METADATA_NAMESPACE)


def metadata(record):
    METADATA_NAMESPACE['metadata'](record)
    reader.require((record['channels'], record['kernels'], record['intended_clock_period_ns'], record['seed'])
        == (32, 16, 20, 3588), 'Changed full target/clock/seed')
    reader.require(record['production_source_before'] == record['production_source_after'],
                   'Production source changed during full CRC emission')


ORIGINAL_PARENT = '''        reader.require(old_path == emitter.PARENT, 'Changed original packet owner')
        old = json.loads(old_path.read_text())
        reader.require(old['status'] == 'PASS_SMALL_NATIVE_HEAP_PACKET_DATA_AND_FRAME_ECC_NOT_FULL_BITSTREAM_OR_SIGNOFF',
                       'Changed original small encoding status')
'''
FULL_PARENT = '''        reader.require(old_path.is_relative_to(ROOT / 'build/openxc7') and old_path.name == 'report.json'
            and re.fullmatch(r'full-reviewed-recursive-mux-physical-scope-unreviewed-bit-encoding-[0-9]+', old_path.parent.name),
            'Changed original full packet owner')
        old = json.loads(old_path.read_text())
        full.metadata(old); full.closed(old); full.snapshots(old_path, old, full.producer, True)
'''
REPLACEMENTS = (
    ("r'small-packet-crc-candidate-[0-9]+'", "r'full-reviewed-packet-crc-candidate-[0-9]+'"),
    ("    emitted = json.loads(path.read_text()); metadata(emitted)\n",
     "    emitted = json.loads(path.read_text()); metadata(emitted)\n    full.snapshots(path, emitted, full)\n"),
    ('small-crc-packet-native-readback-', 'full-reviewed-crc-packet-native-readback-'),
    ('FAIL_SMALL_CRC_CANDIDATE_NATIVE_READBACK', 'FAIL_FULL_REVIEWED_CRC_CANDIDATE_NATIVE_READBACK'),
    (ORIGINAL_PARENT, FULL_PARENT),
    ("        supervisor_pid=os.getpid(), scope=__doc__, emitted_candidate_report=str(path), source={}, commands=[],\n",
     "        supervisor_pid=os.getpid(), scope=__doc__, emitted_candidate_report=str(path), source={}, commands=[],\n"
     "        part=reader.PART, channels=32, kernels=16, parallel_products=512, native_target_dsps=515,\n"
     "        native_target_brams=6, intended_clock_period_ns=20, seed=3588,\n"),
    ("            before[str(item.resolve())] = digest(item)\n",
     "            key, value = str(item.resolve()), digest(item)\n"
     "            reader.require(key not in before or before[key] == value, 'Conflicting original source binding')\n"
     "            before[key] = value\n"),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    PASS=PASS, emitter=emitter, full=full, metadata=metadata)
exec(compile(MAIN_SOURCE, __file__ + ':same-native-complete-readback-and-real-CRC-negatives-full-admission', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
