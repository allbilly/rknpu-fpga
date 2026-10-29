"""Comparison-only mux probe with the source-defined XC7 I/O decomposition names.

The native packer decomposes an OBUF named output_padN into
output_padN$intcell$OBUF. Preserve the original failed-name checker and change
only this lookup in a separate derived checker. No circuit, packed graph,
connectivity, parameter, numerical or expected-error guard is edited.
"""
import inspect
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mux_feedthrough_candidate as original
from audit_empty_output_pairs import source_shaped

IO_SOURCE = original.NATIVE_SRC / 'pack_io.cc'
REPLACEMENTS = (("pad = cells['output_pad' + str(i)]",
                 "pad = cells['output_pad' + str(i) + '$intcell$OBUF']"),)
PROBE_SOURCE = source_shaped(inspect.getsource(original.packed_probe), REPLACEMENTS)
NAMESPACE = dict(original.__dict__)
exec(compile(PROBE_SOURCE, __file__ + ':source-defined-native-OBUF-name-only', 'exec'), NAMESPACE)
packed_probe = NAMESPACE['packed_probe']


def validate_source_contract():
    io = IO_SOURCE.read_text()
    pack = original.SOURCE.read_text()
    assert 'bool is_se_obuf = xil_iob->type.in(id_OBUF, id_OBUFT);' in io
    assert ('int_name(xil_iob->name, (is_se_iobuf || xil_iob->type == id_OBUFT) ? "OBUFT" : "OBUF", !is_se_obuf)') in io
    assert 'return ctx->id(base.str(ctx) + (is_hierarchy ? "$subcell$" : "$intcell$") + postfix);' in pack
    return dict(original_type='OBUF', original_fixture_name='output_padN',
                is_se_obuf=True, is_hierarchy=False, decomposition_suffix='$intcell$OBUF',
                source_files=[str(IO_SOURCE), str(original.SOURCE)], comparison_only=True)
