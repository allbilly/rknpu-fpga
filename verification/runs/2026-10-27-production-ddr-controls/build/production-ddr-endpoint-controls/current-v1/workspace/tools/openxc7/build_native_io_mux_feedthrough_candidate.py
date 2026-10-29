#!/usr/bin/env python3
"""Fresh explicit mux bench/native probe using evidenced decomposed OBUF names.

Keep previous executed helpers, benches, logs and failures intact. Relative to
the explicit-instance procedure, select only a comparison-only source-defined
OBUF-name checker, new controls and a separate output directory. No execution
input, numerical expectation, native-source correction or gate is changed.
Actual native packer qualification and full physical acceptance remain needed.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_explicit_mux_feedthrough_candidate as previous
import mux_native_io_probe as probe
from audit_empty_output_pairs import source_shaped

CONTROL = previous.original.ROOT / 'tests/cmac/test_native_io_mux_feedthrough_candidate_control.py'
REPLACEMENTS = (('recursive-mux-feedthrough-explicit-engine-', 'recursive-mux-feedthrough-native-io-engine-'),)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__,
                 CONTROL=CONTROL, packed_probe=probe.packed_probe)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-execution-input-and-build-gates', 'exec'), NAMESPACE)


def main():
    probe.validate_source_contract()
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
