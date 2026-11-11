#!/usr/bin/env python3
"""Decode a bundle's regcmd.bin into a human-readable register table.

Usage::

    python3 tools/decode_regcmd.py cases/int8_add_c8_w1

Prints QWORD index, target, register offset, value, and marks patched
address fields.  Read-only; no device access.
"""

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NAMES = {
    (0x1001, 0x4004): "DPU.S_POINTER",
    (0x1001, 0x400C): "DPU.FEATURE_MODE_CFG",
    (0x1001, 0x4010): "DPU.DATA_FORMAT",
    (0x1001, 0x4020): "DPU.DST_BASE_ADDR",
    (0x1001, 0x4024): "DPU.DST_SURF_STRIDE",
    (0x1001, 0x4030): "DPU.DATA_CUBE_WIDTH",
    (0x1001, 0x4034): "DPU.DATA_CUBE_HEIGHT",
    (0x1001, 0x4038): "DPU.DATA_CUBE_NOTCH",
    (0x1001, 0x403C): "DPU.DATA_CUBE_CHANNEL",
    (0x1001, 0x4040): "DPU.BS_CFG",
    (0x1001, 0x4044): "DPU.BS_ALU_CFG",
    (0x1001, 0x4048): "DPU.BS_MUL_CFG",
    (0x1001, 0x4050): "DPU.BS_OW_CFG",
    (0x1001, 0x4058): "DPU.WDMA_SIZE_0",
    (0x1001, 0x405C): "DPU.WDMA_SIZE_1",
    (0x1001, 0x4060): "DPU.BN_CFG",
    (0x1001, 0x4064): "DPU.BN_ALU_CFG",
    (0x1001, 0x4068): "DPU.BN_MUL_CFG",
    (0x1001, 0x4070): "DPU.EW_CFG",
    (0x1001, 0x4074): "DPU.EW_CVT_OFFSET_VALUE",
    (0x1001, 0x4078): "DPU.EW_CVT_SCALE_VALUE",
    (0x1001, 0x4080): "DPU.OUT_CVT_OFFSET",
    (0x1001, 0x4084): "DPU.OUT_CVT_SCALE",
    (0x1001, 0x4088): "DPU.OUT_CVT_SHIFT",
    (0x1001, 0x40C0): "DPU.SURFACE_ADD",
    (0x2001, 0x5004): "RDMA.S_POINTER",
    (0x2001, 0x500C): "RDMA.DATA_CUBE_WIDTH",
    (0x2001, 0x5010): "RDMA.DATA_CUBE_HEIGHT",
    (0x2001, 0x5014): "RDMA.DATA_CUBE_CHANNEL",
    (0x2001, 0x5018): "RDMA.SRC_BASE_ADDR",
    (0x2001, 0x501C): "RDMA.BRDMA_CFG",
    (0x2001, 0x5028): "RDMA.NRDMA_CFG",
    (0x2001, 0x5034): "RDMA.ERDMA_CFG",
    (0x2001, 0x5038): "RDMA.EW_BASE_ADDR",
    (0x2001, 0x5040): "RDMA.EW_SURF_STRIDE",
    (0x2001, 0x5044): "RDMA.FEATURE_MODE_CFG",
    (0x2001, 0x5048): "RDMA.SRC_DMA_CFG",
    (0x2001, 0x504C): "RDMA.SURF_NOTCH",
    (0x2001, 0x5068): "RDMA.WEIGHT",
    (0x2001, 0x506C): "RDMA.EW_SURF_NOTCH",
    (0x0081, 0x0008): "PC.OPERATION_ENABLE",
    (0x0101, 0x0010): "PC_REG.BASE_ADDRESS",
    (0x0101, 0x0014): "PC_REG.REGISTER_AMOUNTS",
    (0x0041, 0x0000): "VERSION",
}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    case_dir = Path(sys.argv[1])
    job = json.loads((case_dir / "job.json").read_text(encoding="utf-8"))
    raw = (case_dir / "regcmd.bin").read_bytes()
    qwords = struct.unpack(f"<{len(raw) // 8}Q", raw)
    patches = {patch["regcmd_index"]: patch["buffer"] for patch in job["patches"]}
    print(f"{case_dir.name}: {len(qwords)} QWORDs, {len(raw)} bytes")
    print(f"{'idx':>3}  {'target':>6}  {'offset':>6}  {'value':>10}  register")
    for index, qword in enumerate(qwords):
        target = (qword >> 48) & 0xFFFF
        offset = qword & 0xFFFF
        value = (qword >> 16) & 0xFFFFFFFF
        name = NAMES.get((target, offset), "?")
        suffix = ""
        if index in patches:
            suffix = f"  <== value32 patch buffer={patches[index]}"
        print(
            f"{index:>3}  0x{target:04x}  0x{offset:04x}  0x{value:08x}  "
            f"{name}{suffix}"
        )


if __name__ == "__main__":
    main()
