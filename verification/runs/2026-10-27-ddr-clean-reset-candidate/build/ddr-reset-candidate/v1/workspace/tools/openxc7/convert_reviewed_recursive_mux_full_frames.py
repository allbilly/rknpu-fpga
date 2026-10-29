#!/usr/bin/env python3
"""Prepared reviewed-full-route raw-FASM conversion, not bitstream/signoff.

Require actual complete reviewed placement and full native routing; keep the
unchanged qualified strict converter, all8240 DSP and actual-clock frame-bit
readbacks, exact-part geometry and corruption negatives. Only admission and
archival identity differ. Never convert a comparison target or change raw
execution input. No checksum manifest, old producer edit, physical waiver,
bitstream, FPGA/JTAG detection, programming or flash access occurs.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convert_recursive_mux_shared_frames as previous
import verify_reviewed_recursive_mux_full_route as admission
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_reviewed_recursive_mux_full_frame_control.py'
PASS = 'PASS_REVIEWED_FULL_C32K16_RECURSIVE_MUX_RAW_FASM_EXACT_PART_FRAMES_8240_DSP_AND_ACTUAL_CLOCK_BITS_NOT_BITSTREAM_OR_SIGNOFF'
FLAGS = previous.FLAGS
FRAME_TIMEOUT = previous.FRAME_TIMEOUT
REPLACEMENTS = (
    ('full-recursive-mux-shared-native-heap-frames-', 'full-reviewed-recursive-mux-native-heap-frames-'),
    ("        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')\n",
     """        shutil.copyfile(__file__,out/'executed_source.py');shutil.copyfile(CONTROL,out/'executed_control_source.py')
        (out/'executed_prepared_main.py').write_text(MAIN_SOURCE)
"""),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, admission=admission,
    CONTROL=CONTROL, PASS=PASS, MAIN_SOURCE=MAIN_SOURCE)
exec(compile(MAIN_SOURCE, __file__ + ':same-raw-FASM-converter-all-bit-readbacks-and-geometry', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
