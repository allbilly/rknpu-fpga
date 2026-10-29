"""Render the exact USER2 EW native-emission checks; never runs native tools.

The caller must first validate the source, numerical, routed and review DAG.
Rendering alone grants neither image nor programming admission.
"""
from pathlib import Path
import re

from tools.hardware.sample_ew import tcl_literal

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT/'fpga/host/emit.tcl.in'


def render(dcp, output, inputs, cdc, source_tag):
    if not inputs or any(not re.fullmatch('[0-9a-f]{64}', value) for value in inputs.values()):
        raise ValueError('Require nonempty exact qualified input hashes')
    if not re.fullmatch('[0-9a-f]{8}', source_tag):
        raise ValueError('Require exact source-derived image tag')
    text = TEMPLATE.read_text()
    values = dict(DCP=tcl_literal(dcp), OUTPUT=tcl_literal(output), CDC=tcl_literal(cdc), SOURCE_TAG=source_tag,
                  INPUTS='[dict create '+' '.join(tcl_literal(path)+' '+digest
                         for path, digest in sorted(inputs.items()))+']')
    for name, value in values.items():
        token = '@'+name+'@'
        if text.count(token) != 1:
            raise ValueError('Changed emitter marker '+name)
        text = text.replace(token, value)
    return text
