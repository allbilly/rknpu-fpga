"""Render a source-bound full512 dual image emitter; never execute tools.

The caller validates the native/source/routed review DAG before rendering.
Rendering grants neither image nor physical programming admission.
"""
from pathlib import Path
import re

from tools.hardware.sample_ew import tcl_literal

TEMPLATE = Path(__file__).resolve().parents[2]/'fpga/tinystories/emit.tcl.in'


def render(dcp, output, inputs, cdc, checks, source_tag):
    if not inputs or any(not re.fullmatch('[0-9a-f]{64}', v) for v in inputs.values()):
        raise ValueError('Require nonempty qualified input hashes')
    if not re.fullmatch('[0-9a-f]{8}', source_tag):
        raise ValueError('Require exact source-derived image tag')
    text = TEMPLATE.read_text()
    values = dict(DCP=tcl_literal(dcp), OUTPUT=tcl_literal(output),
                  CDC=tcl_literal(cdc), CHECKS=tcl_literal(checks), SOURCE_TAG=source_tag,
                  INPUTS='[dict create '+' '.join(tcl_literal(p)+' '+v
                         for p, v in sorted(inputs.items()))+']')
    for name, value in values.items():
        token = '@'+name+'@'
        if text.count(token) != 1:
            raise ValueError('Changed emitter marker '+name)
        text = text.replace(token, value)
    return text
