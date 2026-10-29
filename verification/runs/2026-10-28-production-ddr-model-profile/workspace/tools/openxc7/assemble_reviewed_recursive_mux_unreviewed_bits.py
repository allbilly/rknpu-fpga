#!/usr/bin/env python3
"""Prepared reviewed-full-route packet roundtrip, still NOT test-ready.

Require the actual complete reviewed route and converted raw-FASM/frame chain.
Keep every source-defined8240-DSP/clock-bit/geometry/request/corruption check
and qualified native assembler/decoder/all-frame/ECC/decoded-bit negatives.
An emitted full packet remains explicitly NOT_FOR_PROGRAMMING and unreviewed:
numerical, timing, electrical, DRC and configuration-CRC gates remain false.
No old producer edit, standalone checksum manifest or FPGA/flash access.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble_recursive_mux_shared_unreviewed_bits as previous
import convert_reviewed_recursive_mux_full_frames as frames
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_reviewed_recursive_mux_full_bit_control.py'
PASS = 'PASS_REVIEWED_FULL_C32K16_RECURSIVE_MUX_PACKET_FRAME_DATA_AND_ECC_UNREVIEWED_NOT_TEST_READY_OR_SIGNOFF'
FLAGS = previous.FLAGS

METADATA_SOURCE = inspect.getsource(previous.verify_full_frame_metadata)
METADATA_NAMESPACE = dict(previous.__dict__, frames=frames)
exec(compile(METADATA_SOURCE, __file__ + ':unchanged-entire-full-frame-metadata-reviewed-route', 'exec'), METADATA_NAMESPACE)
verify_full_frame_metadata = METADATA_NAMESPACE['verify_full_frame_metadata']


def verify_frame_snapshots(path, saved, before):
    assert not Path(f'/proc/{saved["commands"][-1]["pid"]}').exists(), 'Frame readback worker still live'
    assert not Path(f'/proc/{saved["supervisor_pid"]}').exists(), 'Frame producer still live'
    expected = {'executed_source.py': Path(frames.__file__).read_text(),
        'executed_control_source.py': frames.CONTROL.read_text(), 'executed_prepared_main.py': frames.MAIN_SOURCE}
    for name, text in expected.items():
        item = path.parent / name
        assert str(item) in before and before[str(item)] == previous.previous.digest(item)
        assert item.read_text() == text, 'Changed full-frame producer/guard snapshot'
    for source in (Path(frames.__file__).resolve(), frames.CONTROL):
        assert before[str(source)] == previous.previous.digest(source)


CHAIN_REPLACEMENTS = (
    ('full-recursive-mux-shared-native-heap-frames-', 'full-reviewed-recursive-mux-native-heap-frames-'),
    ('full-prefix-shared-recursive-mux-heap-literal-empty-v2-scan-route-',
     'full-reviewed-recursive-mux-literal-empty-v2-scan-route-'),
    ('    previous.bind_report(path, saved, before)\n    previous.verify_bindings(before)\n',
     '    previous.bind_report(path, saved, before)\n    previous.verify_bindings(before)\n    verify_frame_snapshots(path, saved, before)\n'),
)
CHAIN_SOURCE = source_shaped(inspect.getsource(previous.verify_full_frame_chain), CHAIN_REPLACEMENTS)
CHAIN_NAMESPACE = dict(previous.__dict__, frames=frames, verify_full_frame_metadata=verify_full_frame_metadata,
    verify_frame_snapshots=verify_frame_snapshots)
exec(compile(CHAIN_SOURCE, __file__ + ':all-original-raw-frame-chain-and-fresh-bit-negatives', 'exec'), CHAIN_NAMESPACE)
verify_full_frame_chain = CHAIN_NAMESPACE['verify_full_frame_chain']

REPLACEMENTS = (
    ('full-recursive-mux-shared-native-heap-frames-', 'full-reviewed-recursive-mux-native-heap-frames-'),
    ('full-recursive-mux-shared-unreviewed-bit-encoding-', 'full-reviewed-recursive-mux-unreviewed-bit-encoding-'),
    ('FAIL_FULL_RECURSIVE_MUX_UNREVIEWED_BIT_ENCODING', 'FAIL_FULL_REVIEWED_RECURSIVE_MUX_UNREVIEWED_BIT_ENCODING'),
    ("        shutil.copyfile(CONTROL, out / 'executed_control_source.py')\n",
     "        shutil.copyfile(CONTROL, out / 'executed_control_source.py')\n        (out / 'executed_prepared_main.py').write_text(MAIN_SOURCE)\n"),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    FLAGS=FLAGS, PASS=PASS, MAIN_SOURCE=MAIN_SOURCE, verify_full_frame_metadata=verify_full_frame_metadata,
    verify_full_frame_chain=verify_full_frame_chain)
exec(compile(MAIN_SOURCE, __file__ + ':same-qualified-native-packet-all-frame-ECC-and-negatives', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
