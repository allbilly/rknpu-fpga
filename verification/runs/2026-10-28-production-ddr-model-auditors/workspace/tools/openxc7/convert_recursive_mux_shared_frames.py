#!/usr/bin/env python3
"""Prepared full corrected-mux raw-FASM conversion, not a bitstream/signoff.

Require actual fresh full packing, placement and routing through the strict
new-graph admission. Keep every source/geometry/8240-DSP/actual-clock readback
and corruption-negative gate. Convert unchanged raw FASM only; expected or
comparison artifacts never become execution inputs. No checksum manifest,
electrical/timing/DRC waiver, old producer edit or FPGA/flash access occurs.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert_counter_safe_shared_frames as previous
import verify_recursive_mux_shared_route as admission
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_full_frame_control.py'
PASS = 'PASS_FULL_C32K16_RECURSIVE_MUX_SHARED_RAW_FASM_EXACT_PART_FRAMES_8240_DSP_AND_ACTUAL_CLOCK_BITS_NOT_BITSTREAM_OR_SIGNOFF'
FLAGS = previous.FLAGS
FRAME_TIMEOUT = previous.FRAME_TIMEOUT
REPLACEMENTS = (('full-counter-safe-shared-native-heap-frames-', 'full-recursive-mux-shared-native-heap-frames-'),)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__,
                 admission=admission, CONTROL=CONTROL, PASS=PASS)
exec(compile(MAIN_SOURCE, __file__ + ':same-unchanged-raw-FASM-and-frame-readback-gates', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
