#!/usr/bin/env python3
"""Same unreviewed full packet with an explicit false physical-fit report gate.

The first prepared packet control correctly finds that its inherited flag
tuple omits physical_fit_verified, although upstream full-frame admission
requires that value false. Keep that helper/control failure intact. Add only
this explicit false output/final guard and separate archival/control identity;
all qualified actual-frame/packet/ECC/corruption checks are unchanged. An
emitted artifact remains NOT_FOR_PROGRAMMING, not physical or test-ready.
No standalone checksum manifest, FPGA/JTAG detection or programming occurs.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assemble_reviewed_recursive_mux_unreviewed_bits as first
from audit_empty_output_pairs import source_shaped

ROOT = first.ROOT
previous = first.previous
frames = first.frames
CONTROL = ROOT / 'tests/cmac/test_physical_scope_reviewed_recursive_mux_full_bit_control.py'
PASS = 'PASS_PHYSICAL_SCOPE_REVIEWED_FULL_C32K16_RECURSIVE_MUX_PACKET_DATA_AND_ECC_UNREVIEWED_NOT_TEST_READY_OR_SIGNOFF'
FLAGS = first.FLAGS + ('physical_fit_verified',)
assert 'physical_fit_verified' in frames.FLAGS and 'physical_fit_verified' not in first.FLAGS

METADATA_SOURCE = first.METADATA_SOURCE
METADATA_NAMESPACE = first.METADATA_NAMESPACE
verify_full_frame_metadata = first.verify_full_frame_metadata
verify_frame_snapshots = first.verify_frame_snapshots
CHAIN_REPLACEMENTS = first.CHAIN_REPLACEMENTS
CHAIN_SOURCE = first.CHAIN_SOURCE
CHAIN_NAMESPACE = first.CHAIN_NAMESPACE
verify_full_frame_chain = first.verify_full_frame_chain

# Derive directly from the same frozen full-packet body; avoid layering any
# native execution or numerical/electrical/timing acceptance change.
REPLACEMENTS = tuple((old, new.replace('full-reviewed-recursive-mux-unreviewed-bit-encoding-',
    'full-reviewed-recursive-mux-physical-scope-unreviewed-bit-encoding-')) for old, new in first.REPLACEMENTS)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(first.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
    PASS=PASS, FLAGS=FLAGS, MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-packet-contract-add-explicit-false-physical-fit-gate', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
