"""Render a source-bound full512 CH1 DDR bitstream-emission Tcl script.

Rendering is pure text generation. It never starts Vivado or touches hardware.
The generated Tcl only audits an already-routed image before emitting a
checkpoint and bitstream; it does not apply constraints or run implementation.
"""
from pathlib import Path
import os
import re

from tools.hardware.sample_ew import tcl_literal

TEMPLATE = Path(__file__).resolve().parents[2] / "fpga/ddr/emit_full512_ch1.tcl.in"
HELPERS = (
    "reset_status",
    "board_reset",
    "job_crossing",
    "memory_crossing",
    "mailbox_ui",
    "cmac_permit",
)
PORT_PROPERTIES = (
    "PACKAGE_PIN",
    "IOSTANDARD",
    "SLEW",
    "DRIVE",
    "PULLTYPE",
    "DIFF_TERM",
    "IN_TERM",
    "DIRECTION",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def render(dcp, output, inputs, helpers, ports, source_tag):
    """Render the offline emission Tcl from a complete hash-bound input map."""
    if not isinstance(inputs, dict) or not inputs or any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None
        for value in inputs.values()
    ):
        raise ValueError("Nonempty exact qualified input hashes required")
    if not isinstance(helpers, dict) or set(helpers) != set(HELPERS):
        raise ValueError("All six reviewed full512 constraint helpers required")

    # Normalize caller-relative spellings exactly once, before the generated
    # script runs in its own output directory. Keep conflicting path aliases
    # visible and reject aliases that claim different bytes.
    absolute = lambda path: os.path.abspath(os.fspath(path))
    normalized = {}
    for path, digest in inputs.items():
        name = absolute(path)
        if name in normalized and normalized[name] != digest:
            raise ValueError("Conflicting qualified hashes for one image input")
        normalized[name] = digest

    dcp = absolute(dcp)
    output = absolute(output)
    helpers = {name: absolute(path) for name, path in helpers.items()}
    renderer = absolute(__file__)
    template = absolute(TEMPLATE)
    required_files = [dcp, renderer, template, *helpers.values()]
    if any(path not in normalized for path in required_files):
        raise ValueError(
            "Checkpoint, renderer, template and all helpers must be hash-bound image inputs"
        )

    if (
        not isinstance(ports, dict)
        or len(ports) != 242
        or any(
            not isinstance(name, str)
            or not isinstance(properties, dict)
            or set(properties) != set(PORT_PROPERTIES)
            or any(not isinstance(value, str) for value in properties.values())
            for name, properties in ports.items()
        )
    ):
        raise ValueError("Exact242-port property snapshot required")
    if (
        not isinstance(source_tag, str)
        or re.fullmatch(r"[0-9a-f]{8}", source_tag) is None
        or source_tag == "00000000"
    ):
        raise ValueError("Nonzero source-derived image tag required")

    port_snapshot = "[dict create " + " ".join(
        tcl_literal(name)
        + " [dict create "
        + " ".join(
            tcl_literal(key) + " " + tcl_literal(value)
            for key, value in sorted(properties.items())
        )
        + "]"
        for name, properties in sorted(ports.items())
    ) + "]"
    input_snapshot = "[dict create " + " ".join(
        tcl_literal(path) + " " + digest
        for path, digest in sorted(normalized.items())
    ) + "]"
    values = {
        "DCP": tcl_literal(dcp),
        "OUTPUT": tcl_literal(output),
        "PORTS": port_snapshot,
        "INPUTS": input_snapshot,
        "HELPERS": "\n".join(
            "source " + tcl_literal(helpers[name]) for name in HELPERS
        ),
        "SOURCE_TAG": source_tag,
    }

    text = TEMPLATE.read_text()
    for name, value in values.items():
        token = "@" + name + "@"
        if text.count(token) != 1:
            raise ValueError("Changed full512 DDR image template marker " + name)
        text = text.replace(token, value)

    forbidden = re.compile(
        r"\b(?:open_hw\w*|connect_hw\w*|program_hw\w*|write_cfgmem|"
        r"create_clock|set_clock_groups|set_false_path|set_max_delay|"
        r"set_bus_skew|place_design|phys_opt_design|route_design|synth_design)\b",
        re.IGNORECASE,
    )
    if forbidden.search(text) or re.search(r"@[A-Z_]+@", text):
        raise ValueError("Forbidden hardware/implementation command or template residue")
    property_lines = re.findall(r"(?m)^\s*set_property\b.*$", text)
    if property_lines != [
        "set_property BITSTREAM.CONFIG.USR_ACCESS 0x" + source_tag + " [current_design]"
    ]:
        raise ValueError("Only source-tag USR_ACCESS metadata may be changed")
    return text
