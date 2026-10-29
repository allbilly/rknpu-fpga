#!/usr/bin/env python3
"""Prepared raw-FASM frame conversion for the full counter-safe shared graph.

Require the completed own full route, native scan/connectivity, physical/logical
identity and fresh qualification first. Convert unchanged actual raw FASM with
the same strict pinned converter; retain all 8240 corrected DSP bits, every
actual HCLK bit, complete exact-part geometry and actual corruption negatives.
Only admission/profile/output and own selected-input paths differ from the
original full-frame procedure. No electrical/timing/DRC acceptance, circuit
repair, bitstream assembly, FPGA access or standalone SHA256SUMS occurs here.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert_full_heap_frames as previous
import verify_counter_safe_shared_route as admission
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_heap_frame_control.py'
PASS = 'PASS_FULL_C32K16_COUNTER_SAFE_SHARED_RAW_FASM_EXACT_PART_FRAMES_8240_DSP_AND_ACTUAL_CLOCK_BITS_NOT_BITSTREAM_OR_SIGNOFF'
FLAGS = previous.FLAGS
FRAME_TIMEOUT = previous.FRAME_TIMEOUT
OLD_SELECTED = '        selected=json.loads(admission.route.previous.original.checker.checkpoint.SELECTED.read_text())\n'
NEW_SELECTED = "        selected=admission.route.NAMESPACE['selected_inputs'](json.loads(Path(routed['placed_report']).read_text()),before)\n"
REPLACEMENTS = (
    ('full-native-heap-frames-', 'full-counter-safe-shared-native-heap-frames-'),
    (OLD_SELECTED, NEW_SELECTED),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__,
                 admission=admission, CONTROL=CONTROL, PASS=PASS)
exec(compile(MAIN_SOURCE, __file__ + ':same-raw-full-frame-conversion-gates', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
