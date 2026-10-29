#!/usr/bin/env python3
"""Fresh mux candidate attempt with explicit instances in the test-only bench.

Retain the failed generated-bench attempt/source. The exhaustive four-state
enumeration, original/candidate logic, unused-input cases, wrong-output negative,
source correction, parent byte-relink, native pack fixtures and all gates are
unchanged. Replace only the benchmark file, output namespace and control file.
No production RTL, vendor model, default tool or checksum manifest is changed.
This remains a build/pack probe, not placement/routing/full FPGA acceptance.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mux_feedthrough_candidate as original
from audit_empty_output_pairs import source_shaped

BENCH = original.ROOT / 'tests/cmac/tb_mux_feedthrough_explicit_equivalence.sv'
CONTROL = original.ROOT / 'tests/cmac/test_explicit_mux_feedthrough_candidate_control.py'
REPLACEMENTS = (('recursive-mux-feedthrough-engine-', 'recursive-mux-feedthrough-explicit-engine-'),)
MAIN_SOURCE = source_shaped(inspect.getsource(original.main), REPLACEMENTS)
NAMESPACE = dict(original.__dict__, __file__=__file__, __doc__=__doc__, BENCH=BENCH, CONTROL=CONTROL)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-build-and-native-procedure', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
