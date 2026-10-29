"""Render CH1 EW/DDR image checks; the caller admits the complete review DAG.

Rendering never invokes Vivado, grants programming approval or accesses a card.
"""
from pathlib import Path
import os
import re

from tools.hardware.sample_ew import tcl_literal

TEMPLATE = Path(__file__).resolve().parents[2]/'fpga/ddr/emit_ch1.tcl.in'
HELPERS = ('reset_status', 'board_reset', 'job_crossing', 'memory_crossing', 'mailbox_ui')
PORT_PROPERTIES = ('PACKAGE_PIN', 'IOSTANDARD', 'SLEW', 'DRIVE', 'PULLTYPE', 'DIFF_TERM', 'IN_TERM', 'DIRECTION')


def render(dcp, output, inputs, helpers, ports, source_tag):
    if not inputs or any(not re.fullmatch('[0-9a-f]{64}', value) for value in inputs.values()):
        raise ValueError('Nonempty exact qualified input hashes required')
    if set(helpers) != set(HELPERS):
        raise ValueError('All five reviewed constraint helpers required')
    # The native emitter runs in its own fresh directory. Anchor caller-relative
    # paths now, while preserving symlink spellings and conflicting-hash checks.
    absolute = lambda path: os.path.abspath(os.fspath(path))
    normalized = {}
    for path, digest in inputs.items():
        name = absolute(path)
        if name in normalized and normalized[name] != digest:
            raise ValueError('Conflicting qualified hashes for one image input')
        normalized[name] = digest
    inputs = normalized
    dcp, output = absolute(dcp), absolute(output)
    helpers = {name:absolute(path) for name,path in helpers.items()}
    required_files = [dcp] + list(helpers.values())
    if any(path not in inputs for path in required_files):
        raise ValueError('Checkpoint and all helpers must be hash-bound image inputs')
    if len(ports) != 242 or any(set(properties) != set(PORT_PROPERTIES) for properties in ports.values()):
        raise ValueError('Exact242-port property snapshot required')
    if not isinstance(source_tag, str) or not re.fullmatch('[0-9a-f]{8}', source_tag) or source_tag == '00000000':
        raise ValueError('Nonzero source-derived image tag required')
    snapshot = '[dict create '+' '.join(tcl_literal(name)+' [dict create '+
        ' '.join(tcl_literal(key)+' '+tcl_literal(value) for key,value in sorted(properties.items()))+
        ']' for name,properties in sorted(ports.items()))+']'
    values = dict(DCP=tcl_literal(dcp), OUTPUT=tcl_literal(output), PORTS=snapshot,
        INPUTS='[dict create '+' '.join(tcl_literal(path)+' '+value for path,value in sorted(inputs.items()))+']',
        HELPERS='\n'.join('source '+tcl_literal(helpers[name]) for name in HELPERS), SOURCE_TAG=source_tag)
    text = TEMPLATE.read_text()
    for name,value in values.items():
        token = '@'+name+'@'
        if text.count(token) != 1:
            raise ValueError('Changed DDR image template marker '+name)
        text = text.replace(token,value)
    if re.search(r'@[A-Z_]+@|\b(?:open_hw\w*|connect_hw\w*|program_hw\w*|write_cfgmem|set_clock_groups)\b',text):
        raise ValueError('Forbidden hardware/timing action or template residue')
    return text
