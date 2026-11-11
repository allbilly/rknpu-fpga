#!/usr/bin/env python3
"""Build the RKNPU <-> NVDLA field crosswalk from captured RK command streams.

Read-only analysis.  It decodes the captured regcmd.bin QWORDs, parses the
generated NVDLA nv_small_256 register headers, and emits FIELD_CROSSWALK.json
and FIELD_CROSSWALK.md under this directory.

QWORD encoding (from the RK builders' E()):
    (target << 48) | ((value & 0xffffffff) << 16) | reg_addr
"""
import datetime
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAP = "/home/fedora/rknpu-fpga/build/rk3588-example-captures"
SPEC = "/home/fedora/ZYNQ-NVDLA/build/ypcb/nv-small-256-generation-v1/upstream/outdir/nv_small_256/spec/manual"
RK = "/home/fedora/rk3588/examples"
NVDLA_RTL = "/home/fedora/ZYNQ-NVDLA/RTL/vmod/nvdla"

# ---------------------------------------------------------------- spec parser
ADDR_RE = __import__("re").compile(
    r'^#define\s+(NVDLA_[A-Z0-9_]+)\s+_MK_ADDR_CONST\((0x[0-9a-fA-F]+)\)')
SHIFT_RE = __import__("re").compile(
    r'^#define\s+(NVDLA_[A-Z0-9_]+)_SHIFT\s+_MK_SHIFT_CONST\((\d+)\)')
FIELD_RE = __import__("re").compile(
    r'^#define\s+(NVDLA_[A-Z0-9_]+)_FIELD\s+_MK_FIELD_CONST\((0x[0-9a-fA-F]+),\s*(NVDLA_[A-Z0-9_]+)_SHIFT\)')

BLOCK_FILES = {
    "CSC": os.path.join(SPEC, "NVDLA_CSC.h"),
    "CDMA": os.path.join(SPEC, "NVDLA_CDMA.h"),
    "CACC": os.path.join(SPEC, "NVDLA_CACC.h"),
    "SDP": os.path.join(SPEC, "NVDLA_SDP.h"),
    "SDP_RDMA": os.path.join(SPEC, "NVDLA_SDP_RDMA.h"),
    "PDP": os.path.join(SPEC, "NVDLA_PDP.h"),
    "PDP_RDMA": os.path.join(SPEC, "NVDLA_PDP_RDMA.h"),
}


def parse_header(path):
    regs = {}       # regname -> {offset, line}
    fields = {}     # fieldname -> {reg, shift, mask, line}
    shifts = {}
    widths = {}
    shift_lines = {}
    field_lines = {}
    for ln, line in enumerate(open(path), 1):
        m = ADDR_RE.match(line)
        if m:
            regs[m.group(1)] = {"offset": int(m.group(2), 16), "line": ln}
            continue
        m = SHIFT_RE.match(line)
        if m:
            shifts[m.group(1)] = int(m.group(2))
            shift_lines[m.group(1)] = ln
            continue
        m = FIELD_RE.match(line)
        if m:
            widths[m.group(1)] = int(m.group(2), 16)
            field_lines[m.group(1)] = ln
    for fname, sh in shifts.items():
        for reg in sorted(regs, key=len, reverse=True):
            if fname.startswith(reg + "_"):
                fields[fname[len(reg) + 1:]] = {
                    "reg": reg,
                    "shift": sh,
                    "mask": widths.get(fname),
                    "line": field_lines.get(fname, shift_lines.get(fname)),
                }
                break
    return regs, fields


SPEC_DATA = {b: parse_header(p) for b, p in BLOCK_FILES.items()}


def nv(block, reg, field=None):
    """Return a citation/definition dict for a NVDLA register/field."""
    regs, fields = SPEC_DATA[block]
    assert reg in regs, (block, reg)
    out = {
        "block": block,
        "register": reg,
        "offset": regs[reg]["offset"],
        "reg_line": regs[reg]["line"],
        "header": os.path.relpath(BLOCK_FILES[block], "/home/fedora/ZYNQ-NVDLA"),
    }
    if field is not None:
        assert field in fields, (block, reg, field)
        f = fields[field]
        assert f["reg"] == reg, (block, reg, field, f["reg"])
        out.update({
            "field": field,
            "shift": f["shift"],
            "mask": f["mask"],
            "field_line": f["line"],
        })
    return out


# ---------------------------------------------------------------- case decode
CASES = {
    "C1": {
        "id": "conv_simple_fp16_3x3_c16_h8_w8_oc32",
        "family": "conv-simple",
        "dir": os.path.join(CAP, "conv-simple/cases/conv_simple_fp16_3x3_c16_h8_w8_oc32"),
        "source": os.path.join(RK, "expt/conv_simple.py"),
        "shape": "FP16 3x3 valid, C16 H8 W8 -> OC32, stride 1",
        "role": "primary CNA/CORE/DPU case",
    },
    "C2": {
        "id": "conv_3x3_valid_c4_h9_w9_oc4",
        "family": "conv-fp16",
        "dir": os.path.join(CAP, "conv-fp16/cases/conv_3x3_valid_c4_h9_w9_oc4"),
        "source": os.path.join(RK, "kernel_6_18/conv_new_clean.py"),
        "shape": "FP16 3x3 valid, C4 H9 W9 -> OC4, stride 1",
        "role": "second CNA/CORE/DPU case (align_out_c=32)",
    },
    "C3": {
        "id": "simple_conv_int8_5x5_c8_h8_w8_oc32",
        "family": "conv-simple",
        "dir": os.path.join(CAP, "conv-simple/cases/simple_conv_int8_5x5_c8_h8_w8_oc32"),
        "source": os.path.join(RK, "kernel_6_18/simple_conv.py"),
        "shape": "INT8 quantized 5x5 valid, C8 H8 W8 -> OC32, stride 1",
        "role": "INT8 CNA/CORE/DPU/RDMA bias case",
    },
    "C4": {
        "id": "add_p1_n8",
        "family": "ew-fp16",
        "dir": os.path.join(CAP, "ew-fp16/cases/add_p1_n8"),
        "source": os.path.join(RK, "elementwise.py"),
        "shape": "FP16 EW ADD, N=8, 8 physical lanes",
        "role": "primary DPU/RDMA EW case",
    },
    "C4S": {
        "id": "sub_p1_n8",
        "family": "ew-fp16",
        "dir": os.path.join(CAP, "ew-fp16/cases/sub_p1_n8"),
        "source": os.path.join(RK, "elementwise.py"),
        "shape": "FP16 EW SUB, N=8",
        "role": "DPU EW opcode case",
    },
    "C4M": {
        "id": "mul_p1_n8",
        "family": "ew-fp16",
        "dir": os.path.join(CAP, "ew-fp16/cases/mul_p1_n8"),
        "source": os.path.join(RK, "elementwise.py"),
        "shape": "FP16 EW MUL, N=8",
        "role": "DPU EW opcode case",
    },
    "C4X": {
        "id": "max_p1_n8",
        "family": "ew-fp16",
        "dir": os.path.join(CAP, "ew-fp16/cases/max_p1_n8"),
        "source": os.path.join(RK, "elementwise.py"),
        "shape": "FP16 EW MAX, N=8",
        "role": "DPU EW opcode case",
    },
    "C5": {
        "id": "conv_depthwise_3x3_c3_h11_w28_oc3",
        "family": "conv-fp16",
        "dir": os.path.join(CAP, "conv-fp16/cases/conv_depthwise_3x3_c3_h11_w28_oc3"),
        "source": os.path.join(RK, "kernel_6_18/conv_new_clean.py"),
        "shape": "FP16 depthwise 3x3, C3 H11 W28 -> OC3",
        "role": "supporting asymmetric H/W case (not one of the required picks)",
    },
    "C1b": {
        "id": "conv_simple_fp16_1x1_c4_h8_w8_oc16",
        "family": "conv-simple",
        "dir": os.path.join(CAP, "conv-simple/cases/conv_simple_fp16_1x1_c4_h8_w8_oc16"),
        "source": os.path.join(RK, "expt/conv_simple.py"),
        "shape": "FP16 1x1, C4 H8 W8 -> OC16, FP32 output",
        "role": "supporting case for RK-only CONV_CON1 bits and FP32 output",
    },
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_case(case):
    path = os.path.join(case["dir"], "regcmd.bin")
    raw = open(path, "rb").read()
    writes = []
    for i in range(0, len(raw), 8):
        q = struct.unpack("<Q", raw[i:i + 8])[0]
        writes.append({
            "qword": i // 8,
            "target": (q >> 48) & 0xFFFF,
            "value": (q >> 16) & 0xFFFFFFFF,
            "offset": q & 0xFFFF,
            "raw": q,
        })
    job = json.load(open(os.path.join(case["dir"], "job.json")))
    patches = {p["regcmd_index"]: p for p in job.get("patches", [])}
    for w in writes:
        if w["qword"] in patches:
            p = patches[w["qword"]]
            w["patch"] = {"buffer": p["buffer"], "kind": p["kind"]}
    case["path"] = path
    case["sha256"] = sha256(path)
    case["bytes"] = len(raw)
    case["qwords"] = len(writes)
    case["writes"] = writes
    case["job"] = job
    return case


for c in CASES.values():
    decode_case(c)


def write_of(case, target, offset):
    for w in CASES[case]["writes"]:
        if w["target"] == target and w["offset"] == offset:
            return w
    return None


def val(case, target, offset):
    w = write_of(case, target, offset)
    assert w is not None, (case, hex(target), hex(offset))
    return w["value"]


def fld(v, shift, mask):
    return (v >> shift) & mask


def fmt(v, width=8):
    if v is None:
        return "n/a"
    return f"0x{v:0{width}x}"


# ---------------------------------------------------------------- crosswalk rows
ROWS = []


def row(**kw):
    kw.setdefault("confidence", "high")
    kw.setdefault("literal", None)
    kw.setdefault("note", "")
    ROWS.append(kw)


def add_offsets(block, rk_target, rows):
    """rows: list of (rk_offset, rk_field, nvdla_block, nvdla_offset, note)"""
    out = []
    for off, rf, nb, noff, note in rows:
        regs, fields = SPEC_DATA[nb]
        cand = [r for r in regs if regs[r]["offset"] == noff]
        out.append({
            "rk_target": f"0x{rk_target:04x}",
            "rk_offset": f"0x{off:04x}",
            "rk_field": rf,
            "nvdla_block": nb,
            "nvdla_offset": f"0x{noff:04x}",
            "nvdla_registers": cand,
            "note": note,
        })
    return out


OFFSET_ALIAS = {}


def N(block, reg, field, expected, literal="auto", note=""):
    return {"ref": nv(block, reg, field), "expected": expected,
            "literal": literal, "note": note}


def resolve_row(r):
    rk_value = val(r["case"], r["rk_target"], r["rk_offset"])
    r["rk_value"] = rk_value
    w = write_of(r["case"], r["rk_target"], r["rk_offset"])
    r["rk_qword"] = w["qword"]
    r["rk_patch"] = w.get("patch")
    for e in r["nvdla"]:
        ref = e["ref"]
        if e["literal"] == "auto":
            e["literal"] = fld(rk_value, ref["shift"], ref["mask"])
    return r


# ================================================================ CNA
# RK CNA target 0x0201; NVDLA CSC base 0x4000, CDMA base 0x3000.

row(block="CNA", id="cna_conv_con1", case="C1",
    rk_target=0x0201, rk_offset=0x100c, rk_field="CONV_CON1",
    rk_source="expt/conv_simple.py:403,406; kernel_6_18/conv_new_clean.py:495-500",
    nvdla=[N("CSC", "NVDLA_CSC_D_MISC_CFG_0", "CONV_MODE", 0),
           N("CSC", "NVDLA_CSC_D_MISC_CFG_0", "IN_PRECISION", 2),
           N("CSC", "NVDLA_CSC_D_MISC_CFG_0", "PROC_PRECISION", 2)],
    expected_raw="CSC.D_MISC_CFG = (2<<8)|(2<<12) = 0x00002200",
    cls="repacked bits",
    arithmetic="RK in=((v>>4)&7)=2, proc=((v>>7)&7)=2, conv_mode=0. "
               "NVDLA in=[9:8], proc=[13:12]. Literal copy: in=((v>>8)&3)=1 (INT16), proc=((v>>12)&3)=0 (INT8).",
    note="Same relative offset 0xc as NVDLA CSC D_MISC_CFG, but the precision fields moved. "
         "A pure offset alias would run FP16 data as INT16/INT8.",
    rtl="csc/NV_NVDLA_CSC_dual_reg.v:458,462")

row(block="CNA", id="cna_conv_con1_nonalign", case="C1b",
    rk_target=0x0201, rk_offset=0x100c, rk_field="CONV_CON1 (small-channel path)",
    rk_source="expt/conv_simple.py:403,406",
    nvdla=[N("CSC", "NVDLA_CSC_D_MISC_CFG_0", "CONV_MODE", 0),
           N("CSC", "NVDLA_CSC_D_MISC_CFG_0", "IN_PRECISION", 2),
           N("CSC", "NVDLA_CSC_D_MISC_CFG_0", "PROC_PRECISION", 2)],
    expected_raw="CSC.D_MISC_CFG = 0x00002200",
    cls="RK-only bits",
    arithmetic="RK v=0x6000b120: bits 12..15=(7+in_c=11)=0xB, bits 29 and 30 set. "
               "NVDLA proc_precision is 2 bits [13:12] -> literal 3 (reserved/invalid); bits 29/30 are reserved.",
    note="The non-aligned small-channel path uses bits 29,30 and [15:12] for RK-specific DMA/ARGB controls "
         "(conv_simple.py:403). NVDLA has no corresponding fields. This is a hard counterexample to a bit-identical rename.",
    rtl="csc/NV_NVDLA_CSC_dual_reg.v:456-462",
    confidence="high")

row(block="CNA", id="cna_conv_con2", case="C1",
    rk_target=0x0201, rk_offset=0x1010, rk_field="CONV_CON2 / FEATURE_GRAINS",
    rk_source="expt/conv_simple.py:407; _feature_grains at expt/conv_simple.py:251-257",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_FETCH_GRAIN_0", "GRAINS", 10)],
    expected_raw="CDMA.D_FETCH_GRAIN = 10 (if RK's 11 is an actual row count)",
    cls="repacked bits; value convention unproven",
    arithmetic="RK v=0xB0 -> field [15:4]=11. NVDLA GRAINS=[11:0] and RTL fetch_grain=GRAINS+1 "
               "(CDMA_dc.v:926), so 11 rows -> 10. Literal copy 0xB0 -> 177 grains.",
    note="RK shifts the field by 4; the NVDLA field has no shift. The exact count convention is not documented by RK; "
         "the +1 is established by the NVDLA RTL.",
    rtl="cdma/NV_NVDLA_CDMA_dc.v:926",
    confidence="medium")

row(block="CNA", id="cna_conv_con3", case="C1",
    rk_target=0x0201, rk_offset=0x1014, rk_field="CONV_CON3",
    rk_source="expt/conv_simple.py:408; kernel_6_18/conv_new_clean.py:505-507",
    nvdla=[N("CSC", "NVDLA_CSC_D_CONV_STRIDE_EXT_0", "CONV_X_STRIDE_EXT", 1),
           N("CSC", "NVDLA_CSC_D_CONV_STRIDE_EXT_0", "CONV_Y_STRIDE_EXT", 1)],
    expected_raw="CSC.D_CONV_STRIDE_EXT = (1<<16)|1 = 0x00010001",
    cls="repacked bits",
    arithmetic="RK x=v&7=1, y=(v>>3)&7=1. NVDLA x=[2:0], y=[18:16]. Literal copy: x=1, y=0.",
    note="The x field keeps its position; the y field moves from [5:3] to [18:16]. "
         "The stride-2 capture (C2b 0x12) would be x=2,y=2; NVDLA expects 0x00020002.",
    rtl="csc/NV_NVDLA_CSC_dual_reg.v: header NVDLA_CSC_D_CONV_STRIDE_EXT_0")

row(block="CNA", id="cna_data_size0", case="C1",
    rk_target=0x0201, rk_offset=0x1020, rk_field="DATA_SIZE0",
    rk_source="expt/conv_simple.py:409; kernel_6_18/conv_new_clean.py:509-511",
    nvdla=[N("CSC", "NVDLA_CSC_D_DATAIN_SIZE_EXT_0_0", "DATAIN_WIDTH_EXT", 7),
           N("CSC", "NVDLA_CSC_D_DATAIN_SIZE_EXT_0_0", "DATAIN_HEIGHT_EXT", 7)],
    expected_raw="CSC.D_DATAIN_SIZE_EXT_0 = (7<<16)|7 = 0x00070007",
    cls="semantics differ (width/height swapped, actual vs last-index)",
    arithmetic="C1 v=0x00080008: RK width=high16=8, height=low16=8. NVDLA width=[12:0], height=[28:16], both 0-based "
               "(datain_width_w=reg+1, CSC_dl.v:890). Expected 0x00070007. Literal copy: width=8, height=0. "
               "Supporting C5 v=0x001c000b (W=28,H=11) vs expected 0x000a001b proves the swap.",
    note="RK packs width in bits 31:16 and height in 15:0 with actual counts; NVDLA packs width low and height high, both 0-based. "
         "This is not a rename.",
    rtl="csc/NV_NVDLA_CSC_dl.v:890-892")

row(block="CNA", id="cna_data_size1", case="C1",
    rk_target=0x0201, rk_offset=0x1024, rk_field="DATA_SIZE1",
    rk_source="expt/conv_simple.py:410; kernel_6_18/conv_new_clean.py:512-516",
    nvdla=[N("CSC", "NVDLA_CSC_D_DATAIN_SIZE_EXT_1_0", "DATAIN_CHANNEL_EXT", 15),
           N("CSC", "NVDLA_CSC_D_WEIGHT_SIZE_EXT_1_0", "WEIGHT_CHANNEL_EXT", 15, literal=15)],
    expected_raw="CSC.D_DATAIN_SIZE_EXT_1 = 15; CSC.D_WEIGHT_SIZE_EXT_1[12:0] = 15",
    cls="repacked bits (split data-channel / weight-channel)",
    arithmetic="C1 v=0x000f0010: low=16 (aligned data channels) -> NVDLA data channel-1=15; high=15 (real in_c-1) -> "
               "NVDLA weight channel ext=15. C2 v=0x00030010 -> data 15, weight 3. C3 v=0x00070010 -> data 15, weight 7. "
               "C5 v=0x00020008 -> data 7, weight 2. Literal copy: data channel=16 (one too many); the high half is ignored.",
    note="This single RK register carries two different NVDLA concepts: the padded CBUF data channel count and the real weight "
         "channel count. NVDLA keeps them in separate registers (D_DATAIN_SIZE_EXT_1 and D_WEIGHT_SIZE_EXT_1).",
    rtl="csc/NV_NVDLA_CSC_dl.v:2398-2399; csc/NV_NVDLA_CSC_sg.v:649-650; header NVDLA_CSC_D_WEIGHT_SIZE_EXT_1_0")

row(block="CNA", id="cna_data_size2", case="C1",
    rk_target=0x0201, rk_offset=0x1028, rk_field="DATA_SIZE2",
    rk_source="expt/conv_simple.py:411; kernel_6_18/conv_new_clean.py:518",
    nvdla=[N("CSC", "NVDLA_CSC_D_DATAOUT_SIZE_0_0", "DATAOUT_WIDTH", 5)],
    expected_raw="CSC.D_DATAOUT_SIZE_0[12:0] = 5",
    cls="semantics differ (+1 actual vs last-index)",
    arithmetic="C1 out_w=6, RK v=6; NVDLA dataout_width is 0-based (is_w_end uses >= dataout_width_cmp, CSC_dl.v:2313), "
               "expected 5. C5 out_w=26 -> expected 25.",
    note="RK CNA carries only the output width; the output height is in CORE_DATAOUT_SIZE_0 (already 0-based). "
         "A CSC adapter must combine the two blocks' writes.",
    rtl="csc/NV_NVDLA_CSC_dl.v:988,2313")

row(block="CNA", id="cna_data_size3", case="C1",
    rk_target=0x0201, rk_offset=0x102c, rk_field="DATA_SIZE3",
    rk_source="expt/conv_simple.py:412; kernel_6_18/conv_new_clean.py:519",
    nvdla=[N("CSC", "NVDLA_CSC_D_ATOMICS_0", "ATOMICS", 35)],
    expected_raw="CSC.D_ATOMICS = 35",
    cls="semantics differ (+1 actual vs last-index)",
    arithmetic="C1 out_w*out_h=36, RK v=0x24=36; NVDLA data_out_atomic_w=reg2dp_atomics+1 (CSC_sg.v:648), expected 35. "
               "C5 26*9=234 -> 233. Literal copy: 36 atoms (one too many).",
    note="",
    rtl="csc/NV_NVDLA_CSC_sg.v:648")

row(block="CNA", id="cna_weight_size0", case="C1",
    rk_target=0x0201, rk_offset=0x1030, rk_field="WEIGHT_SIZE0",
    rk_source="expt/conv_simple.py:413; kernel_6_18/conv_new_clean.py:522",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_WEIGHT_BYTES_0", "WEIGHT_BYTES", 9216),
           N("CSC", "NVDLA_CSC_D_WEIGHT_BYTES_0", "WEIGHT_BYTES", 9216)],
    expected_raw="CDMA/CSC D_WEIGHT_BYTES = 9216",
    cls="renamed/relocated (same value, duplicate target)",
    arithmetic="C1 32 oc * 3*3*16*2 = 9216 bytes. NVDLA weight_bytes is a byte count used as [31:3] 8-byte bursts "
               "(CDMA_wt.v:864), no +1. RK 0x2400=9216 matches exactly.",
    note="A full CDMA+CSC configuration needs the value written to both blocks; RK has one register.",
    rtl="cdma/NV_NVDLA_CDMA_wt.v:864")

row(block="CNA", id="cna_weight_size1", case="C1",
    rk_target=0x0201, rk_offset=0x1034, rk_field="WEIGHT_SIZE1",
    rk_source="expt/conv_simple.py:414; kernel_6_18/conv_new_clean.py:524",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_WEIGHT_SIZE_0_0", "BYTE_PER_KERNEL", 287)],
    expected_raw="CDMA.D_WEIGHT_SIZE_0 = 287",
    cls="semantics differ (+1 actual vs last-index)",
    arithmetic="C1 3*3*16*2=288 bytes/kernel, RK 0x120=288; NVDLA byte_per_kernel=reg2dp+1 (CDMA_wt.v:763), expected 287. "
               "C3 INT8 5*5*16*1=400 -> 399. C5 3*3*8*2=144 -> 143.",
    note="The per-kernel byte count is 0-based in NVDLA and actual in RK.",
    rtl="cdma/NV_NVDLA_CDMA_wt.v:763")

row(block="CNA", id="cna_weight_size2", case="C1",
    rk_target=0x0201, rk_offset=0x1038, rk_field="WEIGHT_SIZE2",
    rk_source="expt/conv_simple.py:415; kernel_6_18/conv_new_clean.py:526-530",
    nvdla=[N("CSC", "NVDLA_CSC_D_WEIGHT_SIZE_EXT_0_0", "WEIGHT_WIDTH_EXT", 2),
           N("CSC", "NVDLA_CSC_D_WEIGHT_SIZE_EXT_0_0", "WEIGHT_HEIGHT_EXT", 2),
           N("CSC", "NVDLA_CSC_D_WEIGHT_SIZE_EXT_1_0", "WEIGHT_KERNEL", 31)],
    expected_raw="CSC.D_WEIGHT_SIZE_EXT_0 = 0x00020002; CSC.D_WEIGHT_SIZE_EXT_1[28:16] = 31",
    cls="repacked bits + split across registers + 0-based",
    arithmetic="C1 v=0x03030020: kw=(v>>24)=3, kh=(v>>16)=3, kernels=v&0xffff=32. NVDLA width=kw-1=2, height=kh-1=2, "
               "kernel=out_c-1=31 (CSC_sg.v:601). Literal copy to EXT_0: width=v&0x1f=0, height=(v>>16)&0x1f=3. "
               "C3 0x05050020: kw=kh=5, kernels=32 -> width/height 4, kernel 31; literal width=0, height=5.",
    note="One RK register carries three actual-count fields that NVDLA splits across two registers with 0-based values. "
         "This is the clearest single disproof of a rename.",
    rtl="csc/NV_NVDLA_CSC_sg.v:601,649-650")

row(block="CNA", id="cna_cbuf_con0", case="C1",
    rk_target=0x0201, rk_offset=0x1040, rk_field="CBUF_CON0",
    rk_source="expt/conv_simple.py:416; kernel_6_18/conv_new_clean.py:531-534",
    nvdla=[N("CSC", "NVDLA_CSC_D_BANK_0", "DATA_BANK", 1),
           N("CSC", "NVDLA_CSC_D_BANK_0", "WEIGHT_BANK", 11)],
    expected_raw="CSC.D_BANK = (11<<16)|1 = 0x000b0001",
    cls="repacked bits",
    arithmetic="C1 v=0xB1: data_bank=v&0xf=1, weight_bank=(v>>4)&0xf=11. NVDLA data_bank=[4:0], weight_bank=[20:16]. "
               "Literal copy: data_bank=0x11=17 (out of range), weight_bank=0. C5 v=0x1B -> RK data 11, weight 1; "
               "literal data 27, weight 0.",
    note="RK also puts weight_reuse in bit13; NVDLA has it in CSC D_MISC_CFG bit20. Not exercised in the selected captures.",
    rtl="header NVDLA_CSC_D_BANK_0")

row(block="CNA", id="cna_cbuf_con1", case="C1",
    rk_target=0x0201, rk_offset=0x1044, rk_field="CBUF_CON1",
    rk_source="expt/conv_simple.py:417; _cbuf_entries at expt/conv_simple.py:246-248",
    nvdla=[N("CSC", "NVDLA_CSC_D_ENTRY_PER_SLICE_0", "ENTRIES", 3),
           N("CDMA", "NVDLA_CDMA_D_ENTRY_PER_SLICE_0", "ENTRIES", 3)],
    expected_raw="CSC/CDMA D_ENTRY_PER_SLICE = 3",
    cls="semantics differ (+1; entry geometry caveat)",
    arithmetic="C1 v=4; NVDLA entries=reg+1 (CSC_dl.v:977, CDMA_dc.v:924), expected 3. Literal copy: 4 entries (one too many).",
    note="RK uses 128-byte CBUF entries (conv_simple.py:23-26); NVDLA nv_small_256 is 32 banks x 32 B x 128 deep with "
         "256-bit entry width (project.vh:11-13,45). The -1 conversion is necessary but not sufficient to prove CBUF equivalence.",
    rtl="csc/NV_NVDLA_CSC_dl.v:977; cdma/NV_NVDLA_CDMA_dc.v:924",
    confidence="medium")

row(block="CNA", id="cna_cvt_con0", case="C1",
    rk_target=0x0201, rk_offset=0x104c, rk_field="CVT_CON0",
    rk_source="expt/conv_simple.py:418; kernel_6_18/conv_new_clean.py:540-542",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_CVT_CFG_0", "CVT_EN", 0),
           N("CDMA", "NVDLA_CDMA_D_CVT_CFG_0", "CVT_TRUNCATE", 0)],
    expected_raw="CDMA.D_CVT_CFG = 0 (CVT_EN=0, no truncate)",
    cls="semantics differ (enable polarity per RK comment; integer-only CVT)",
    arithmetic="RK v=0x0B has bit0=1, bit1=1, bit3=1. The RK builder comment names bit0 CVT_BYPASS and bit1 CVT_TYPE; "
               "if that comment is correct, NVDLA CVT_EN (bit0) must be 0 for RK bypass, i.e. the polarity is inverted. "
               "Even if the comment is wrong, RK bits 1 and 3 have no NVDLA field.",
    note="NVDLA CDMA CVT is signed integer subtract/multiply/shift/saturate (CDMA_CVT_cell.v:95,107,121,137); "
         "enabling it on FP16 data would reinterpret the bit patterns as integers. This is a datapath difference, "
         "not just a rename.",
    rtl="cdma/NV_NVDLA_CDMA_CVT_cell.v:95,107,121,137")

row(block="CNA", id="cna_cvt_con1_4", case="C1",
    rk_target=0x0201, rk_offset=0x1050, rk_field="CVT_CON1..CVT_CON4",
    rk_source="expt/conv_simple.py:418-420; kernel_6_18/simple_conv.py:571-574",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_CVT_SCALE_0", "CVT_SCALE", 1),
           N("CDMA", "NVDLA_CDMA_D_CVT_OFFSET_0", "CVT_OFFSET", 0)],
    expected_raw="CDMA.D_CVT_SCALE=1, D_CVT_OFFSET=0",
    cls="repacked bits (scale/offset merge) + RK-only multiplicity",
    arithmetic="RK each v=0x00010000: scale=(v>>16)=1, offset=v&0xffff=0. NVDLA scale and offset are separate 16-bit registers. "
               "Literal copy of the 32-bit value: D_CVT_SCALE low16=0 (scale 0), D_CVT_OFFSET low16=0 (offset 0); the RK scale in the high half is lost.",
    note="RK has four independent scale/offset pairs at 0x1050..0x105c; NVDLA has one. The captured values are all identity. "
         "For in_c==1 RK packs four 6-bit truncates into CVT_CON0 (simple_conv.py:567-570), again four lanes vs NVDLA's one.",
    rtl="header NVDLA_CDMA_D_CVT_SCALE_0 / D_CVT_OFFSET_0")

row(block="CNA", id="cna_feature_addr", case="C1",
    rk_target=0x0201, rk_offset=0x1070, rk_field="FEATURE_DATA_ADDR",
    rk_source="expt/conv_simple.py:420; kernel_6_18/conv_new_clean.py:551",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_DAIN_ADDR_LOW_0_0", "DATAIN_ADDR_LOW_0", 0, literal=0),
           N("CDMA", "NVDLA_CDMA_D_DAIN_ADDR_HIGH_0_0", "DATAIN_ADDR_HIGH_0", 0, literal=0)],
    expected_raw="CDMA.D_DAIN_ADDR_LOW_0 = patched buffer address; HIGH = 0",
    cls="renamed/relocated (low 32 bits only)",
    arithmetic="regcmd value is 0 (placeholder); job.json patch index 18 replaces bits [47:16] with the input buffer DMA address. "
               "NVDLA has low/high and a second data address; RK has one 32-bit address.",
    note="No high-address write; RK DMA addresses are 32-bit in this command encoding.",
    rtl="header NVDLA_CDMA_D_DAIN_ADDR_LOW_0_0")

row(block="CNA", id="cna_dma_con0", case="C1",
    rk_target=0x0201, rk_offset=0x1078, rk_field="DMA_CON0",
    rk_source="expt/conv_simple.py:421; kernel_6_18/conv_new_clean.py:552-554",
    nvdla=[],
    expected_raw="no NVDLA register",
    cls="RK-only",
    arithmetic="RK v=0x000f000f: weight burst len [19:16]=15, data burst len [3:0]=15. "
               "NVDLA CSC/CDMA headers have no burst-length register; its memory bursts are internal.",
    note="Performance control only; no correctness mapping.",
    rtl="")

row(block="CNA", id="cna_dma_con1", case="C1",
    rk_target=0x0201, rk_offset=0x107c, rk_field="DMA_CON1",
    rk_source="expt/conv_simple.py:422; kernel_6_18/conv_new_clean.py:274-280,556",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_LINE_STRIDE_0", "LINE_STRIDE", 1024)],
    expected_raw="CDMA.D_LINE_STRIDE = 1024 (32 x 32 B)",
    cls="semantics differ (32-byte unit; 4-row decomposition)",
    arithmetic="RK source comment: 'CDMA_DC stride registers are in 32B units' (conv_new_clean.py:274-276). "
               "C1 v=0x20=32 -> 1024 B. NVDLA D_LINE_STRIDE is a byte stride; RTL slices [31:3] into 8-byte address units "
               "(cdma.v:829-830) and uses grain_addr=fetch_grain*line_stride (dc.v:927). Literal copy: 32 B.",
    note="For C1 the packed input row is 8*8*2=128 B; RK's 1024 B is 8 rows, not one row. "
         "The two addressing decompositions are not interchangeable.",
    rtl="cdma/NV_NVDLA_cdma.v:829-830; cdma/NV_NVDLA_CDMA_dc.v:927")

row(block="CNA", id="cna_dma_con2", case="C1",
    rk_target=0x0201, rk_offset=0x1080, rk_field="DMA_CON2",
    rk_source="expt/conv_simple.py:423; kernel_6_18/conv_new_clean.py:274-280,557",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_SURF_STRIDE_0", "SURF_STRIDE", 1024)],
    expected_raw="CDMA.D_SURF_STRIDE = 1024 (32 x 32 B)",
    cls="semantics differ (32-byte unit; 4-row decomposition)",
    arithmetic="C1 v=0x20=32 -> 1024 B. RK formula width_stride*(in_h-4)=8*4=32 units; C2 9*5=45 (0x2d) -> 1440 B; "
               "C5 28*7=196 (0xc4) -> 6272 B. NVDLA SURF_STRIDE is a byte stride. Literal copy: 32 B.",
    note="The RK surface stride is not the full packed-surface stride (which would be 1024 B for C1 by coincidence); "
         "it follows the 4-row tiling formula. Recompute from the RK layout, do not copy.",
    rtl="cdma/NV_NVDLA_cdma.v:829-830")

row(block="CNA", id="cna_fc_data_size0", case="C1",
    rk_target=0x0201, rk_offset=0x1084, rk_field="FC_DATA_SIZE0",
    rk_source="expt/conv_simple.py:424; kernel_6_18/conv_new_clean.py:559-561",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_DATAIN_SIZE_0_0", "DATAIN_WIDTH", 7),
           N("CDMA", "NVDLA_CDMA_D_DATAIN_SIZE_0_0", "DATAIN_HEIGHT", 7)],
    expected_raw="CDMA.D_DATAIN_SIZE_0 = (7<<16)|7 = 0x00070007",
    cls="semantics differ (width/height swapped, actual vs last-index)",
    arithmetic="C1 v=0x00080008: RK width=high16=8, height=low16=8; NVDLA width=[12:0], height=[28:16], both 0-based "
               "(data_width_inc=reg+1, data_height_w=reg+1; CDMA_dc.v:921,923). Expected 0x00070007. "
               "C5 v=0x001c000b (W=28,H=11) vs expected 0x000a001b.",
    note="RK uses in_w/in_h here (source image) and width_stride/in_h in DATA_SIZE0 (padded CBUF). "
         "The source uses width_stride for DATA_SIZE0 and in_w for FC_DATA_SIZE0, but all captured cases have width_stride==in_w, so the capture cannot prove which NVDLA block each targets. The split is inferred from the variable names and the CSC/CDMA field roles.",
    rtl="cdma/NV_NVDLA_CDMA_dc.v:921,923")

row(block="CNA", id="cna_fc_data_size1", case="C1",
    rk_target=0x0201, rk_offset=0x1088, rk_field="FC_DATA_SIZE1",
    rk_source="expt/conv_simple.py:424; kernel_6_18/conv_new_clean.py:563",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_DATAIN_SIZE_1_0", "DATAIN_CHANNEL", 15)],
    expected_raw="CDMA.D_DATAIN_SIZE_1 = 15",
    cls="semantics differ (+1 actual vs last-index)",
    arithmetic="C1 v=0x10=16 (aligned channels); NVDLA data_surface_inc=channel[12:3]+1 (CDMA_dc.v:914), so 16 -> 15. "
               "C3 v=0x10=16 -> 15; C5 v=8 -> 7.",
    note="This is the padded/aligned channel count. The real weight channel count is DATA_SIZE1[31:16], "
         "which maps to CSC D_WEIGHT_SIZE_EXT_1, not here. NVDLA separates the two.",
    rtl="cdma/NV_NVDLA_CDMA_dc.v:914")

row(block="CNA", id="cna_dcomp_addr", case="C1",
    rk_target=0x0201, rk_offset=0x1110, rk_field="DCOMP_ADDR0",
    rk_source="expt/conv_simple.py:425; kernel_6_18/conv_new_clean.py:565",
    nvdla=[N("CDMA", "NVDLA_CDMA_D_WEIGHT_ADDR_LOW_0", "WEIGHT_ADDR_LOW", 0, literal=0),
           N("CDMA", "NVDLA_CDMA_D_WEIGHT_ADDR_HIGH_0", "WEIGHT_ADDR_HIGH", 0, literal=0)],
    expected_raw="CDMA.D_WEIGHT_ADDR_LOW = patched weight buffer address; HIGH = 0",
    cls="renamed/relocated (low 32 bits only)",
    arithmetic="regcmd value is 0 (placeholder); job.json patch index 24 -> weight buffer. "
               "NVDLA has weight low/high plus WGS/WMB metadata addresses; RK has one 32-bit address.",
    note="'DCOMP' does not imply compression: the builder points it at the plain packed FP16/INT8 weight buffer. "
         "NVDLA D_WEIGHT_FORMAT=0 (uncompressed) is the matching default.",
    rtl="header NVDLA_CDMA_D_WEIGHT_ADDR_LOW_0")

row(block="CNA", id="cna_cvt_con5", case="C1",
    rk_target=0x0201, rk_offset=0x1180, rk_field="CVT_CON5",
    rk_source="expt/conv_simple.py:426; kernel_6_18/conv_new_clean.py:458; kernel_6_18/simple_conv.py:583",
    nvdla=[],
    expected_raw="no NVDLA register (0x1180 is outside CSC 0x4000-0x4064 and CDMA 0x3000-0x30e8)",
    cls="RK-only",
    arithmetic="C1 v=7; C1b v=0xF; C2 v=0; C3 v=0; C5 v=7. conv_simple sets input_pack_c2-1; conv_new_clean forces 0 for groups==1; "
               "simple_conv uses 0xffff only for in_c==1. No consistent NVDLA meaning.",
    note="The conv_new_clean comment calls it PER_CHANNEL_CVT_EN, but the values track input_pack_c2, not a channel enable mask. "
         "This is a good example of why builder comments are not authoritative.",
    rtl="",
    confidence="high")

row(block="CNA", id="cna_pad_con0", case="C3",
    rk_target=0x0201, rk_offset=0x1068, rk_field="PAD_CON0",
    rk_source="kernel_6_18/simple_conv.py:575",
    nvdla=[N("CSC", "NVDLA_CSC_D_ZERO_PADDING_0", "PAD_LEFT", 0),
           N("CSC", "NVDLA_CSC_D_ZERO_PADDING_0", "PAD_TOP", 0),
           N("CDMA", "NVDLA_CDMA_D_ZERO_PADDING_0", "PAD_LEFT", 0),
           N("CDMA", "NVDLA_CDMA_D_ZERO_PADDING_0", "PAD_TOP", 0)],
    expected_raw="CSC/CDMA zero padding = 0",
    cls="renamed/relocated (only zero captured)",
    arithmetic="C3 v=0. RK CNA_PAD_CON0 names left/top; NVDLA CSC has left/top, CDMA has left/right/top/bottom. "
               "The FP16 builders never write this register.",
    note="No non-zero padding capture exists; the SAME-padding case is BLOCKED. Do not claim a padding mapping beyond zero.",
    rtl="header NVDLA_CSC_D_ZERO_PADDING_0 / NVDLA_CDMA_D_ZERO_PADDING_0",
    confidence="medium")

row(block="CNA", id="cna_pad_con1", case="C3",
    rk_target=0x0201, rk_offset=0x1184, rk_field="PAD_CON1",
    rk_source="kernel_6_18/simple_conv.py:522,584",
    nvdla=[N("CSC", "NVDLA_CSC_D_ZERO_PADDING_VALUE_0", "PAD_VALUE", 0x8080),
           N("CDMA", "NVDLA_CDMA_D_ZERO_PADDING_VALUE_0", "PAD_VALUE", 0x8080)],
    expected_raw="CSC/CDMA D_ZERO_PADDING_VALUE = 0x8080 (low 16 bits)",
    cls="repacked bits (low16 candidate; high16 RK-only)",
    arithmetic="C3 v=0xffff8080: low16=0x8080 (two INT8 zero-point bytes), high16=0xffff. NVDLA PAD_VALUE is 16 bits. "
               "Literal copy to a 16-bit field takes 0x8080; the upper half is outside.",
    note="simple_conv.py:522 sets 0xffff8080 when kernel>=3 and INPUT_ZERO_POINT==0. The capture cannot distinguish whether "
         "NVDLA CSC feature padding or CDMA image padding consumes it; both are candidates.",
    rtl="header NVDLA_CSC_D_ZERO_PADDING_VALUE_0 / NVDLA_CDMA_D_ZERO_PADDING_VALUE_0",
    confidence="low")


# ================================================================ CORE
# RK CORE target 0x0801; NVDLA CACC base 0x7000.

row(block="CORE", id="core_misc_cfg", case="C1",
    rk_target=0x0801, rk_offset=0x3010, rk_field="MISC_CFG",
    rk_source="expt/conv_simple.py:427; kernel_6_18/conv_new_clean.py:572-574",
    nvdla=[N("CACC", "NVDLA_CACC_D_MISC_CFG_0", "CONV_MODE", 0),
           N("CACC", "NVDLA_CACC_D_MISC_CFG_0", "PROC_PRECISION", 2)],
    expected_raw="CACC.D_MISC_CFG = (2<<12) = 0x00002000",
    cls="repacked bits + semantics differ (bit0=spatial, not conv_mode)",
    arithmetic="C1 v=0x201: RK proc=(v>>8)&3=2, spatial=v&1=1, dw=(v>>1)&1=0. NVDLA proc=[13:12], conv_mode=bit0. "
               "Expected 0x2000. Literal copy: conv_mode=1 (Winograd), proc=((v>>12)&3)=0 (INT8).",
    note="conv_new_clean.py:572-574 sets bit0=is_spatial for every 3x3/5x5 conv; the comment 'OPERATION_ENABLE' is misleading. "
         "A literal copy would run every spatial conv as NVDLA Winograd. C3 v=0x001 and C5 v=0x203 also set bit0=1.",
    rtl="cacc/NV_NVDLA_CACC_dual_reg.v:244-248")

row(block="CORE", id="core_misc_cfg_int8", case="C3",
    rk_target=0x0801, rk_offset=0x3010, rk_field="MISC_CFG (INT8)",
    rk_source="kernel_6_18/simple_conv.py:585",
    nvdla=[N("CACC", "NVDLA_CACC_D_MISC_CFG_0", "CONV_MODE", 0),
           N("CACC", "NVDLA_CACC_D_MISC_CFG_0", "PROC_PRECISION", 0)],
    expected_raw="CACC.D_MISC_CFG = 0x00000000",
    cls="semantics differ",
    arithmetic="C3 v=0x001: RK proc=0 (INT8), spatial=1. Expected conv_mode=0, proc=0 -> 0x0000. Literal copy: conv_mode=1.",
    note="The INT8 case confirms bit0 is the spatial flag, not an operation enable.",
    rtl="cacc/NV_NVDLA_CACC_dual_reg.v:244-248")

row(block="CORE", id="core_dataout_size0", case="C1",
    rk_target=0x0801, rk_offset=0x3014, rk_field="DATAOUT_SIZE_0",
    rk_source="expt/conv_simple.py:427; kernel_6_18/conv_new_clean.py:575-577",
    nvdla=[N("CACC", "NVDLA_CACC_D_DATAOUT_SIZE_0_0", "DATAOUT_WIDTH", 5),
           N("CACC", "NVDLA_CACC_D_DATAOUT_SIZE_0_0", "DATAOUT_HEIGHT", 5)],
    expected_raw="CACC.D_DATAOUT_SIZE_0 = 0x00050005",
    cls="renamed/relocated (identical encoding)",
    arithmetic="C1 out 6x6: RK ((out_h-1)<<16) + (out_w-1) = (5<<16)+5 = 0x00050005. NVDLA width=[12:0], height=[28:16], "
               "both 0-based. Literal copy is exact. C5 9x26 -> 0x00080019, also exact.",
    note="This is one of the genuinely reusable CACC fields.",
    rtl="header NVDLA_CACC_D_DATAOUT_SIZE_0_0")

row(block="CORE", id="core_dataout_size1", case="C1",
    rk_target=0x0801, rk_offset=0x3018, rk_field="DATAOUT_SIZE_1",
    rk_source="expt/conv_simple.py:428; kernel_6_18/conv_new_clean.py:578",
    nvdla=[N("CACC", "NVDLA_CACC_D_DATAOUT_SIZE_1_0", "DATAOUT_CHANNEL", 31)],
    expected_raw="CACC.D_DATAOUT_SIZE_1 = 31",
    cls="renamed/relocated (identical encoding)",
    arithmetic="C1 align_out_c=32 -> out_channel_field=31. NVDLA channel field is 0-based; literal copy is exact. "
               "C3 and C5 also write 31.",
    note="The real out_c-1 (e.g. 3 for C2) is only in DPU DATA_CUBE_CHANNEL[31:16]; NVDLA CACC has one channel field.",
    rtl="header NVDLA_CACC_D_DATAOUT_SIZE_1_0")

row(block="CORE", id="core_clip", case="C3",
    rk_target=0x0801, rk_offset=0x301c, rk_field="CLIP_TRUNCATE",
    rk_source="kernel_6_18/simple_conv.py:588",
    nvdla=[N("CACC", "NVDLA_CACC_D_CLIP_CFG_0", "CLIP_TRUNCATE", 0)],
    expected_raw="CACC.D_CLIP_CFG = 0",
    cls="renamed/relocated (identical encoding, different relative offset)",
    arithmetic="C3 v=0. RK relative offset 0x1c; NVDLA CACC D_CLIP_CFG relative 0x2c. Literal copy of 0 is exact.",
    note="The previous REFERENCE_MAPPING's '+4 shift' holds for MISC/DATAOUT_SIZE_0/1 but not for CLIP (0x301c vs 0x702c). "
         "The CORE map is compacted, not uniformly shifted.",
    rtl="cacc/NV_NVDLA_CACC_dual_reg.v:206-208")

row(block="CORE", id="core_reserved_3030", case="C1",
    rk_target=0x0801, rk_offset=0x3030, rk_field="RESERVED_3030",
    rk_source="expt/conv_simple.py:428; kernel_6_18/conv_new_clean.py:579",
    nvdla=[N("CACC", "NVDLA_CACC_D_OUT_SATURATION_0", "SAT_COUNT", None, literal=None)],
    expected_raw="no writable NVDLA field; D_OUT_SATURATION is read-only status",
    cls="RK-only (NVDLA read-only at the same relative offset)",
    arithmetic="C1 v=0. NVDLA CACC 0x7030 is D_OUT_SATURATION, driven by dp2reg_sat_count (CACC_regfile.v:16,41,200); "
               "there is no d0/d1 writable field.",
    note="A bridge write of 0 here is harmless but has no NVDLA function. RK calls it RESERVED/clear-stale-state.",
    rtl="cacc/NV_NVDLA_CACC_regfile.v:16,41,200")

# ================================================================ DPU
# RK DPU target 0x1001; NVDLA SDP base 0x9000.

row(block="DPU", id="dpu_s_pointer", case="C4",
    rk_target=0x1001, rk_offset=0x4004, rk_field="S_POINTER",
    rk_source="elementwise.py:302; kernel_6_18/conv_new_clean.py:478-481",
    nvdla=[N("SDP", "NVDLA_SDP_S_POINTER_0", "PRODUCER", 0),
           N("SDP", "NVDLA_SDP_S_POINTER_0", "CONSUMER", 0)],
    expected_raw="Not forwardable; NVDLA S_POINTER is a shadow-group selector",
    cls="semantics differ",
    arithmetic="RK v=0xE sets bits1,2,3 (PP_MODE, EXECUTER_PP_EN, POINTER_PP_EN). NVDLA PRODUCER=bit0, CONSUMER=bit16; "
               "literal 0xE decodes to producer=0, consumer=0 (both d0).",
    note="The bridge must implement NVDLA's d0/d1 producer-consumer commit protocol; it cannot forward RK's PP bits.",
    rtl="header NVDLA_SDP_S_POINTER_0")

row(block="DPU", id="dpu_feature_mode", case="C4",
    rk_target=0x1001, rk_offset=0x400c, rk_field="FEATURE_MODE_CFG",
    rk_source="elementwise.py:303-307; kernel_6_18/conv_new_clean.py:580-583",
    nvdla=[N("SDP", "NVDLA_SDP_D_FEATURE_MODE_CFG_0", "FLYING_MODE", 1),
           N("SDP", "NVDLA_SDP_D_FEATURE_MODE_CFG_0", "OUTPUT_DST", 0),
           N("SDP", "NVDLA_SDP_D_FEATURE_MODE_CFG_0", "WINOGRAD", 0),
           N("SDP", "NVDLA_SDP_D_FEATURE_MODE_CFG_0", "NAN_TO_ZERO", 0),
           N("SDP", "NVDLA_SDP_D_FEATURE_MODE_CFG_0", "BATCH_NUMBER", 0)],
    expected_raw="SDP.D_FEATURE_MODE_CFG = 0x00000001 (EW flying)",
    cls="repacked bits + semantics differ",
    arithmetic="RK C4 v=0x1E5: flying=bit0=1, output_mode=(v>>1)&3=2, conv_mode=(v>>3)&3=0, burst=(v>>5)&0xF=15. "
               "NVDLA flying=bit0, output_dst=bit1, winograd=bit2, nan=bit3, batch=[12:8]. Literal copy: flying=1, "
               "output_dst=0, winograd=1, nan=0, batch=(v>>8)&0x1F=1 (2 batches). C1 conv v=0x1E4: literal flying=0, winograd=1, batch=1.",
    note="RK OUTPUT_MODE=2 sets bit2, which NVDLA reads as WINOGRAD. RK BURST_LEN=15<<5 sets bit8, which NVDLA reads as "
         "batch_number=1. Neither field has an SDP counterpart. A literal copy is wrong.",
    rtl="sdp/NV_NVDLA_SDP_REG_dual.v:931-947")

row(block="DPU", id="dpu_data_format", case="C1",
    rk_target=0x1001, rk_offset=0x4010, rk_field="DATA_FORMAT",
    rk_source="expt/conv_simple.py:429; kernel_6_18/conv_new_clean.py:584-587; elementwise.py:308-312",
    nvdla=[N("SDP", "NVDLA_SDP_D_DATA_FORMAT_0", "PROC_PRECISION", 2),
           N("SDP", "NVDLA_SDP_D_DATA_FORMAT_0", "OUT_PRECISION", 2)],
    expected_raw="SDP.D_DATA_FORMAT = (2<<2)|2 = 0x0000000A",
    cls="repacked bits + RK-only IN_PRECISION",
    arithmetic="C1 v=0x48000002: RK proc=v&3=2, in=(v>>26)&7=2, out=(v>>29)&7=2. NVDLA proc=[1:0], out=[3:2]. "
               "Expected 0x0A. Literal copy: proc=2, out=(v>>2)&3=0 (INT8 output).",
    note="NVDLA SDP has no in_precision; it is in SDP_RDMA D_FEATURE_MODE_CFG[3:2]. "
         "C1b v=0xA8000002 has RK out=5 (FP32); NVDLA SDP's 2-bit OUT_PRECISION cannot encode 5. FP32 output is RK-only.",
    rtl="sdp/NV_NVDLA_SDP_REG_dual.v:727-731")

row(block="DPU", id="dpu_dst_base", case="C1",
    rk_target=0x1001, rk_offset=0x4020, rk_field="DST_BASE_ADDR",
    rk_source="expt/conv_simple.py:430; kernel_6_18/conv_new_clean.py:588",
    nvdla=[N("SDP", "NVDLA_SDP_D_DST_BASE_ADDR_LOW_0", "DST_BASE_ADDR_LOW", 0, literal=0),
           N("SDP", "NVDLA_SDP_D_DST_BASE_ADDR_HIGH_0", "DST_BASE_ADDR_HIGH", 0, literal=0)],
    expected_raw="SDP.D_DST_BASE_ADDR_LOW = patched output buffer address; HIGH = 0",
    cls="renamed/relocated (low 32 bits only)",
    arithmetic="regcmd value 0 (placeholder); job.json patch index 32 -> out buffer. NVDLA has low/high plus line/surface/batch "
               "strides; RK has one 32-bit base and a surface stride.",
    note="",
    rtl="header NVDLA_SDP_D_DST_BASE_ADDR_LOW_0")

row(block="DPU", id="dpu_dst_surf_stride", case="C1",
    rk_target=0x1001, rk_offset=0x4024, rk_field="DST_SURF_STRIDE",
    rk_source="expt/conv_simple.py:430; kernel_6_18/conv_new_clean.py:589",
    nvdla=[N("SDP", "NVDLA_SDP_D_DST_SURFACE_STRIDE_0", "DST_SURFACE_STRIDE", 576)],
    expected_raw="SDP.D_DST_SURFACE_STRIDE = 576 (C1, candidate); 1152 if the NVDLA surface is 16 FP16 channels",
    cls="renamed/relocated (candidate; surface granularity unresolved)",
    arithmetic="C1 v=0x240=576 = out_width_stride<<4 = 36*16 = 6*6*8*2 (one 8-channel NC1HWC2 plane). "
               "C2 v=0x340=832 = 52*16, while W*H*8*2=784; RK pads the plane atom count to a multiple of 4. "
               "C5 v=0xEC0=3776 vs 26*9*8*2=3744.",
    note="NVDLA's DST_SURFACE_STRIDE is a byte stride. The adapter must also synthesize DST_LINE_STRIDE = out_w*8*2 "
         "(RK never writes it). The value matches an 8-channel plane for C1/C3, but NV_NVDLA_SDP_WDMA_cmd.v:155 "
         "says 'Surf is always in unit of ATOMIC (1x1x32B)', i.e. 16 FP16 channels; in that case the candidate is "
         "2x = 1152 (which equals RK's SURFACE_ADD). The reference build's surface grouping must be resolved by simulation.",
    rtl="sdp/NV_NVDLA_SDP_WDMA_cmd.v:136-137,266-306",
    confidence="medium")

row(block="DPU", id="dpu_cube_width", case="C1",
    rk_target=0x1001, rk_offset=0x4030, rk_field="DATA_CUBE_WIDTH",
    rk_source="expt/conv_simple.py:431; elementwise.py:313",
    nvdla=[N("SDP", "NVDLA_SDP_D_DATA_CUBE_WIDTH_0", "WIDTH", 5)],
    expected_raw="SDP.D_DATA_CUBE_WIDTH = 5",
    cls="renamed/relocated (identical 0-based encoding)",
    arithmetic="C1 out_w=6 -> RK 5; NVDLA width is 0-based (cfg_mode_1x1_pack uses width==0, WDMA_cmd.v:146; is_last_w at 210). "
               "C4 EW n=8 -> RK 0; NVDLA 0. Literal copy is exact.",
    note="For EW, RK's width is the number of 8-lane columns minus 1 (elementwise.py:296); NVDLA's width is cube columns, "
         "so the same value describes the same padded cube when channel=7.",
    rtl="sdp/NV_NVDLA_SDP_WDMA_cmd.v:146,210")

row(block="DPU", id="dpu_cube_height", case="C1",
    rk_target=0x1001, rk_offset=0x4034, rk_field="DATA_CUBE_HEIGHT",
    rk_source="expt/conv_simple.py:431; elementwise.py:314",
    nvdla=[N("SDP", "NVDLA_SDP_D_DATA_CUBE_HEIGHT_0", "HEIGHT", 5)],
    expected_raw="SDP.D_DATA_CUBE_HEIGHT = 5",
    cls="renamed/relocated (identical 0-based encoding)",
    arithmetic="C1 out_h=6 -> RK 5; NVDLA height is 0-based (is_last_h=count_h==size_of_height, WDMA_cmd.v:231). "
               "C4 EW height 0. Literal copy is exact.",
    note="",
    rtl="sdp/NV_NVDLA_SDP_WDMA_cmd.v:215,231")

row(block="DPU", id="dpu_cube_notch", case="C1",
    rk_target=0x1001, rk_offset=0x4038, rk_field="DATA_CUBE_NOTCH",
    rk_source="expt/conv_simple.py:431; kernel_6_18/conv_new_clean.py:592",
    nvdla=[],
    expected_raw="no NVDLA SDP field",
    cls="RK-only",
    arithmetic="C1 v=0. The low-12 offset 0x38 collides with NVDLA SDP D_OP_ENABLE at 0x9038; a naive alias would write OP_EN=0.",
    note="RK requires this to be 0; NVDLA derives the cube shape from W/H/C and has no notch control.",
    rtl="header NVDLA_SDP_D_OP_ENABLE_0")

row(block="DPU", id="dpu_cube_channel", case="C1",
    rk_target=0x1001, rk_offset=0x403c, rk_field="DATA_CUBE_CHANNEL",
    rk_source="expt/conv_simple.py:432; kernel_6_18/conv_new_clean.py:593-595; elementwise.py:316-319",
    nvdla=[N("SDP", "NVDLA_SDP_D_DATA_CUBE_CHANNEL_0", "CHANNEL", 31)],
    expected_raw="SDP.D_DATA_CUBE_CHANNEL = 31 (low 13 bits)",
    cls="repacked bits (low field identical; high 16 RK-only)",
    arithmetic="C1 v=0x001F001F: low=align_out_c-1=31, high=out_c-1=31. NVDLA channel=[12:0], 0-based; literal low is exact. "
               "C2 v=0x0003001F: low=31 (padded 32), high=3 (real 4). C4 v=0x00070007: low=7, high=7.",
    note="NVDLA has one channel field. For C2 the low 31 requests 32 padded channels, matching the 32-channel output BO; "
         "the high half is RK metadata.",
    rtl="header NVDLA_SDP_D_DATA_CUBE_CHANNEL_0")

row(block="DPU", id="dpu_bs_cfg", case="C1",
    rk_target=0x1001, rk_offset=0x4040, rk_field="BS_CFG",
    rk_source="expt/conv_simple.py:433; kernel_6_18/conv_new_clean.py:596-600; kernel_6_18/simple_conv.py:598",
    nvdla=[N("SDP", "NVDLA_SDP_D_DP_BS_CFG_0", "BS_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_BS_CFG_0", "BS_ALU_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_BS_CFG_0", "BS_ALU_ALGO", 0),
           N("SDP", "NVDLA_SDP_D_DP_BS_CFG_0", "BS_MUL_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_BS_CFG_0", "BS_RELU_BYPASS", 1)],
    expected_raw="SDP.D_DP_BS_CFG = 0x53 (C1)",
    cls="renamed/relocated for 0x53; repacked + RK-only high bits for INT8 0x20150",
    arithmetic="C1 v=0x53 = bits 0,1,4,6 -> exactly NVDLA BS_BYPASS/ALU_BYPASS/MUL_BYPASS/RELU_BYPASS; literal copy is exact. "
               "C3 v=0x20150 = bits 4,6,8,17; bits 8 and 17 are outside D_DP_BS_CFG[6:0]. Literal copy: BS_BYPASS=0, "
               "ALU_BYPASS=0, ALU_ALGO=0 (MAX), MUL_BYPASS=1, RELU_BYPASS=1.",
    note="The low 7 bits match the NVDLA layout. The INT8 builder adds undocumented bits 8 and 17 (simple_conv.py:598). "
         "Do not assume they are NVDLA fields.",
    rtl="sdp/NV_NVDLA_SDP_REG_dual.v:803-815")

row(block="DPU", id="dpu_bs_ow_cfg", case="C1",
    rk_target=0x1001, rk_offset=0x4050, rk_field="BS_OW_CFG",
    rk_source="expt/conv_simple.py:434; kernel_6_18/conv_new_clean.py:601-605; kernel_6_18/simple_conv.py:602-603",
    nvdla=[],
    expected_raw="no NVDLA SDP register",
    cls="RK-only",
    arithmetic="C1 v=0x126 = (1<<8)+(1<<5)+(1<<2)+(1<<1): SIZE_E_2[9:8], SIZE_E_1[6:5], SIZE_E_0[3:2], OD_BYPASS bit1. "
               "C5 v=0x36E uses 3 in all size fields. The low-12 offset 0x50 collides with D_DST_LINE_STRIDE at 0x9050.",
    note="NVDLA SDP has no output-width/size-E control; its operand widths are fixed by D_DATA_FORMAT. "
         "A naive alias would write 0x126 as the destination line stride.",
    rtl="header NVDLA_SDP_D_DST_LINE_STRIDE_0")

row(block="DPU", id="dpu_wdma_size0", case="C1",
    rk_target=0x1001, rk_offset=0x4058, rk_field="WDMA_SIZE_0",
    rk_source="expt/conv_simple.py:435; kernel_6_18/conv_new_clean.py:606; kernel_6_18/simple_conv.py:605",
    nvdla=[],
    expected_raw="no NVDLA SDP register",
    cls="RK-only (duplicates DATA_CUBE_CHANNEL)",
    arithmetic="C1 v=0x1F=31 (aligned channel-1), same as DATA_CUBE_CHANNEL low. The low-12 offset 0x58 collides with "
               "D_DP_BS_CFG at 0x9058; a naive write of 0x1F would set BS bypass/ALU/MUL/RELU bits.",
    note="The adapter can drop this if it is consistent with DATA_CUBE_CHANNEL.",
    rtl="header NVDLA_SDP_D_DP_BS_CFG_0")

row(block="DPU", id="dpu_wdma_size1", case="C1",
    rk_target=0x1001, rk_offset=0x405c, rk_field="WDMA_SIZE_1",
    rk_source="expt/conv_simple.py:435; kernel_6_18/conv_new_clean.py:607-609; kernel_6_18/simple_conv.py:606",
    nvdla=[],
    expected_raw="no NVDLA SDP register",
    cls="RK-only (duplicates DATA_CUBE_WIDTH/HEIGHT)",
    arithmetic="C1 v=0x00050005 = ((out_h-1)<<16) + (out_w-1), same as the cube dims. The low-12 offset 0x5c collides with "
               "D_DP_BS_ALU_CFG at 0x905c.",
    note="Drop if consistent with the cube dims.",
    rtl="header NVDLA_SDP_D_DP_BS_ALU_CFG_0")

row(block="DPU", id="dpu_bn_cfg", case="C1",
    rk_target=0x1001, rk_offset=0x4060, rk_field="BN_CFG",
    rk_source="expt/conv_simple.py:436; kernel_6_18/conv_new_clean.py:610-614; kernel_6_18/simple_conv.py:607",
    nvdla=[N("SDP", "NVDLA_SDP_D_DP_BN_CFG_0", "BN_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_BN_CFG_0", "BN_ALU_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_BN_CFG_0", "BN_ALU_ALGO", 0),
           N("SDP", "NVDLA_SDP_D_DP_BN_CFG_0", "BN_MUL_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_BN_CFG_0", "BN_RELU_BYPASS", 1)],
    expected_raw="SDP.D_DP_BN_CFG = 0x53",
    cls="renamed/relocated (bit-identical)",
    arithmetic="C1 v=0x53 = bits 0,1,4,6, exactly the NVDLA BN bypass layout. Literal copy is exact. C3 also writes 0x53.",
    note="",
    rtl="sdp/NV_NVDLA_SDP_REG_dual.v:751-767")

row(block="DPU", id="dpu_ew_cfg", case="C4",
    rk_target=0x1001, rk_offset=0x4070, rk_field="EW_CFG",
    rk_source="elementwise.py:320-332; experimental/kernel_6_18/elementwise.py:224-231",
    nvdla=[N("SDP", "NVDLA_SDP_D_DP_EW_CFG_0", "EW_BYPASS", 0),
           N("SDP", "NVDLA_SDP_D_DP_EW_CFG_0", "EW_ALU_BYPASS", 0),
           N("SDP", "NVDLA_SDP_D_DP_EW_CFG_0", "EW_ALU_ALGO", 2),
           N("SDP", "NVDLA_SDP_D_DP_EW_CFG_0", "EW_MUL_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_EW_CFG_0", "EW_LUT_BYPASS", 1),
           N("SDP", "NVDLA_SDP_D_DP_EW_ALU_CFG_0", "EW_ALU_SRC", 1)],
    expected_raw="ADD: D_DP_EW_CFG=(2<<2)|(1<<4)|(1<<6)=0x58, D_DP_EW_ALU_CFG=1",
    cls="repacked bits + semantics differ (opcode width/values, SUB/FDIV absent)",
    arithmetic="ADD v=0x108202c0: ALU_ALGO=(v>>16)&7=2, OP_TYPE=bit2=0, OP_SRC=bit6=1, LUT_BYPASS=bit7=1, "
               "REL=bit9=1. NVDLA ALU_ALGO=[3:2] 2 bits; literal (v>>2)&3=0 (MAX), not SUM. "
               "SUB v=0x108402c0: ALU_ALGO=4 -> cannot fit NVDLA's 2-bit field. MUL v=0x108003c4: OP_TYPE=1 -> "
               "NVDLA literal ALU_ALGO=(v>>2)&3=1 (MIN); NVDLA uses a separate EW_MUL block. "
               "MAX v=0x108002c0: literal ALU_ALGO=0 (MAX) coincides, but MUL_BYPASS=0 leaves the MUL active.",
    note="NVDLA SDP EW ALU supports MAX/MIN/SUM (2-bit, HLS_X_int_alu.v:105-110; enum EQL is treated as SUM). "
         "RK has a 3-bit ALU_ALGO at [18:16] with MAX=0, ADD=2, FDIV=3, SUB=4 and selects MUL via OP_TYPE bit2. "
         "ADD/MAX/MUL/NEG are adapter-mappable; SUB needs operand negation (not proven); FDIV has no NVDLA divider.",
    rtl="sdp/NV_NVDLA_SDP_REG_dual.v:855-903; sdp/NV_NVDLA_SDP_HLS_X_int_alu.v:105-110")

row(block="DPU", id="dpu_ew_cvt_scale", case="C1",
    rk_target=0x1001, rk_offset=0x4078, rk_field="EW_CVT_SCALE_VALUE",
    rk_source="expt/conv_simple.py:437; kernel_6_18/conv_new_clean.py:621; elementwise.py:333",
    nvdla=[N("SDP", "NVDLA_SDP_D_DP_EW_ALU_CVT_SCALE_VALUE_0", "EW_ALU_CVT_SCALE", 1),
           N("SDP", "NVDLA_SDP_D_DP_EW_MUL_CVT_SCALE_VALUE_0", "EW_MUL_CVT_SCALE", 1)],
    expected_raw="SDP EW ALU/MUL CVT scale = 1",
    cls="renamed/relocated (one RK value -> two NVDLA registers)",
    arithmetic="C1 v=1. RK has one scale value; NVDLA has separate ALU and MUL CVT scale/offset/truncate registers. "
               "Literal copy of 1 to either is exact.",
    note="The captured cases only need identity scale; NVDLA offsets/truncates default to 0.",
    rtl="header NVDLA_SDP_D_DP_EW_ALU_CVT_SCALE_VALUE_0 / _MUL_CVT_SCALE_VALUE_0")

row(block="DPU", id="dpu_out_cvt_scale", case="C1",
    rk_target=0x1001, rk_offset=0x4084, rk_field="OUT_CVT_SCALE",
    rk_source="expt/conv_simple.py:437; kernel_6_18/conv_new_clean.py:622-624; kernel_6_18/simple_conv.py:611",
    nvdla=[N("SDP", "NVDLA_SDP_D_CVT_SCALE_0", "CVT_SCALE", 1)],
    expected_raw="SDP.D_CVT_SCALE = 1 (C1); 0x4041 (C3)",
    cls="repacked bits (low 16 mapped; bit16 RK-only)",
    arithmetic="C1 v=0x00010001: low16=1 -> NVDLA CVT_SCALE=1; bit16=FP32TOFP16_EN has no NVDLA field. "
               "C3 v=0x00004041: low16=0x4041 -> NVDLA CVT_SCALE=0x4041. Literal low16 is exact.",
    note="NVDLA SDP has separate D_CVT_OFFSET (0x90c0) and D_CVT_SHIFT (0x90c8); RK writes them at 0x4080/0x4088 in the "
         "INT8 case. For FP16, NVDLA output precision is controlled by D_DATA_FORMAT OUT_PRECISION; RK's bit16 is explicit.",
    rtl="sdp/NV_NVDLA_SDP_REG_dual.v:707-711")

row(block="DPU", id="dpu_surface_add", case="C1",
    rk_target=0x1001, rk_offset=0x40c0, rk_field="SURFACE_ADD",
    rk_source="expt/conv_simple.py:438; kernel_6_18/conv_new_clean.py:625-626",
    nvdla=[],
    expected_raw="no NVDLA SDP register",
    cls="RK-only (derivable output-addressing aid)",
    arithmetic="C1 v=0x480=1152 = (out_width_stride * max(2,align_out_c/16))<<4 = 36*2*16. "
               "In all captured cases align_out_c=32, so SURFACE_ADD = 2 * DST_SURF_STRIDE: C1 2*576=1152, "
               "C2 2*832=1664, C3 2*256=512, C5 2*3776=7552.",
    note="NVDLA has no surface-add; it uses DST_LINE/SURFACE/BATCH_STRIDE. SURFACE_ADD = 2*DST_SURF_STRIDE in all "
         "captured cases, so if NVDLA's surface is 16 FP16 channels (1x1x32B), SURFACE_ADD is the closer candidate for "
         "D_DST_SURFACE_STRIDE and DST_SURF_STRIDE is the 8-channel sub-surface stride. This is unresolved.",
    rtl="header NVDLA_SDP_D_DST_SURFACE_STRIDE_0")

row(block="DPU", id="dpu_out_cvt_offset", case="C3",
    rk_target=0x1001, rk_offset=0x4080, rk_field="OUT_CVT_OFFSET",
    rk_source="kernel_6_18/simple_conv.py:610",
    nvdla=[N("SDP", "NVDLA_SDP_D_CVT_OFFSET_0", "CVT_OFFSET", 0xFFFFFF80)],
    expected_raw="SDP.D_CVT_OFFSET = 0xFFFFFF80",
    cls="renamed/relocated (identical)",
    arithmetic="C3 v=0xFFFFFF80 (signed -128). NVDLA D_CVT_OFFSET is 32-bit; literal copy is exact.",
    note="Only the INT8 builder writes this.",
    rtl="header NVDLA_SDP_D_CVT_OFFSET_0")

row(block="DPU", id="dpu_out_cvt_shift", case="C3",
    rk_target=0x1001, rk_offset=0x4088, rk_field="OUT_CVT_SHIFT",
    rk_source="kernel_6_18/simple_conv.py:612",
    nvdla=[N("SDP", "NVDLA_SDP_D_CVT_SHIFT_0", "CVT_SHIFT", 22)],
    expected_raw="SDP.D_CVT_SHIFT = 22",
    cls="renamed/relocated (identical)",
    arithmetic="C3 v=0x16=22. NVDLA D_CVT_SHIFT is [5:0]; literal copy is exact.",
    note="Only the INT8 builder writes this.",
    rtl="header NVDLA_SDP_D_CVT_SHIFT_0")

# ================================================================ RDMA
# RK RDMA target 0x2001; NVDLA SDP_RDMA base 0x8000.

row(block="RDMA", id="rdma_s_pointer", case="C4",
    rk_target=0x2001, rk_offset=0x5004, rk_field="S_POINTER",
    rk_source="elementwise.py:334; kernel_6_18/simple_conv.py:551-552",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_S_POINTER_0", "PRODUCER", 0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_S_POINTER_0", "CONSUMER", 0)],
    expected_raw="Not forwardable; NVDLA S_POINTER is a shadow-group selector",
    cls="semantics differ",
    arithmetic="RK v=0xE sets bits1,2,3 (PP mode/enables). NVDLA PRODUCER=bit0, CONSUMER=bit16; literal 0xE gives "
               "producer=0, consumer=0 (d0).",
    note="The bridge must implement the d0/d1 commit protocol; RK's PP bits cannot be forwarded.",
    rtl="header NVDLA_SDP_RDMA_S_POINTER_0")

row(block="RDMA", id="rdma_cube_width", case="C4",
    rk_target=0x2001, rk_offset=0x500c, rk_field="DATA_CUBE_WIDTH",
    rk_source="elementwise.py:335; kernel_6_18/simple_conv.py:614",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_DATA_CUBE_WIDTH_0", "WIDTH", 0)],
    expected_raw="SDP_RDMA.D_DATA_CUBE_WIDTH = 0",
    cls="identical (same relative offset, same 0-based encoding)",
    arithmetic="C4 n=8 -> RK 0; NVDLA width 0-based (cfg_mode_1x1_pack at MRDMA_ig.v:192, is_last_w at 253). Literal copy is exact. "
               "C3 out 4x4 -> RK 3; NVDLA 3.",
    note="One of the few exact aliases: RK 0x500c -> NVDLA 0x800c.",
    rtl="sdp/NV_NVDLA_SDP_MRDMA_ig.v:192,253")

row(block="RDMA", id="rdma_cube_height", case="C4",
    rk_target=0x2001, rk_offset=0x5010, rk_field="DATA_CUBE_HEIGHT",
    rk_source="elementwise.py:336; kernel_6_18/simple_conv.py:615",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_DATA_CUBE_HEIGHT_0", "HEIGHT", 0)],
    expected_raw="SDP_RDMA.D_DATA_CUBE_HEIGHT = 0",
    cls="identical (same relative offset, same 0-based encoding)",
    arithmetic="C4 height 0; NVDLA 0-based (is_last_h=count_h==height, MRDMA_ig.v:253). C3 4x4 -> 3. Literal copy is exact.",
    note="Exact alias: RK 0x5010 -> NVDLA 0x8010.",
    rtl="sdp/NV_NVDLA_SDP_MRDMA_ig.v:253")

row(block="RDMA", id="rdma_cube_channel", case="C4",
    rk_target=0x2001, rk_offset=0x5014, rk_field="DATA_CUBE_CHANNEL",
    rk_source="elementwise.py:337; kernel_6_18/simple_conv.py:616",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_DATA_CUBE_CHANNEL_0", "CHANNEL", 7)],
    expected_raw="SDP_RDMA.D_DATA_CUBE_CHANNEL = 7",
    cls="identical (same relative offset, same 0-based encoding)",
    arithmetic="C4 8 lanes -> RK 7; NVDLA channel 0-based (size_of_surf=channel[12:3], MRDMA_ig.v:204-208). C3 32 channels -> 31. "
               "Literal copy is exact.",
    note="Exact alias: RK 0x5014 -> NVDLA 0x8014.",
    rtl="sdp/NV_NVDLA_SDP_MRDMA_ig.v:204-208")

row(block="RDMA", id="rdma_src_base", case="C4",
    rk_target=0x2001, rk_offset=0x5018, rk_field="SRC_BASE_ADDR",
    rk_source="elementwise.py:343",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_SRC_BASE_ADDR_LOW_0", "SRC_BASE_ADDR_LOW", 0, literal=0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_SRC_BASE_ADDR_HIGH_0", "SRC_BASE_ADDR_HIGH", 0, literal=0)],
    expected_raw="SDP_RDMA.D_SRC_BASE_ADDR_LOW = patched a buffer address; HIGH = 0",
    cls="identical (low half) / renamed-relocated (high half)",
    arithmetic="regcmd value 0 (placeholder); job.json patch index 15 -> a buffer. RK 0x5018 -> NVDLA 0x8018 low; high 0x801c is not written.",
    note="The low-half offset is an exact alias. RK has no high-address write.",
    rtl="header NVDLA_SDP_RDMA_D_SRC_BASE_ADDR_LOW_0")

row(block="RDMA", id="rdma_erdma_cfg", case="C4",
    rk_target=0x2001, rk_offset=0x5034, rk_field="ERDMA_CFG",
    rk_source="elementwise.py:338-341; kernel_6_18/simple_conv.py:619",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_ERDMA_CFG_0", "ERDMA_DISABLE", 0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_ERDMA_CFG_0", "ERDMA_DATA_USE", 1),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_ERDMA_CFG_0", "ERDMA_DATA_SIZE", 1),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_ERDMA_CFG_0", "ERDMA_DATA_MODE", 1),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_ERDMA_CFG_0", "ERDMA_RAM_TYPE", 0)],
    expected_raw="SDP_RDMA.D_ERDMA_CFG = (1<<4)|(1<<3)|(1<<1) = 0x1A (ALU use)",
    cls="repacked bits + semantics differ (data_use/data_mode positions)",
    arithmetic="C4 v=0x40000008: RK data_size=2<<2 (bit3=1), data_mode=bit30=1, disable=bit0=0. NVDLA disable=bit0, "
               "data_use=[2:1], data_size=bit3, data_mode=bit4, ram=bit5. Literal copy: disable=0, data_use=(v>>1)&3=0 (MUL), "
               "data_size=1, data_mode=(v>>4)&1=0. C3 v=1: literal disable=1 (plausible: no EW operand in the bias-only conv).",
    note="The adapter must move bit30->bit4 and set data_use=1 for ADD/SUB/MAX (ALU), or 0 for MUL/NEG. "
         "The captured EW value cannot be copied literally. nv_small_256 does not instantiate ERDMA, so this field has no usable datapath in the reference build.",
    rtl="sdp/NV_NVDLA_SDP_RDMA_REG_dual.v:587-603")

row(block="RDMA", id="rdma_ew_base", case="C4",
    rk_target=0x2001, rk_offset=0x5038, rk_field="EW_BASE_ADDR",
    rk_source="elementwise.py:344",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_EW_BASE_ADDR_LOW_0", "EW_BASE_ADDR_LOW", 0, literal=0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_EW_BASE_ADDR_HIGH_0", "EW_BASE_ADDR_HIGH", 0, literal=0)],
    expected_raw="SDP_RDMA.D_EW_BASE_ADDR_LOW = patched b buffer address; HIGH = 0",
    cls="renamed/relocated (low 32 bits only)",
    arithmetic="regcmd value 0 (placeholder); job.json patch index 16 -> b buffer. RK 0x5038 -> NVDLA 0x805c low; "
               "offset is not an alias (0x38 vs 0x5c).",
    note="NVDLA also needs EW_LINE_STRIDE (0x8064), EW_SURFACE_STRIDE (0x8068) and EW_BATCH_STRIDE (0x806c); RK writes none "
         "in the captured EW cases. For a 1x1x8 vector, zero strides are a plausible default, but this is not proven.",
    rtl="header NVDLA_SDP_RDMA_D_EW_BASE_ADDR_LOW_0")

row(block="RDMA", id="rdma_feature_mode", case="C4",
    rk_target=0x2001, rk_offset=0x5044, rk_field="FEATURE_MODE_CFG",
    rk_source="elementwise.py:345-351; kernel_6_18/simple_conv.py:620",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_FEATURE_MODE_CFG_0", "FLYING_MODE", 1),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_FEATURE_MODE_CFG_0", "WINOGRAD", 0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_FEATURE_MODE_CFG_0", "IN_PRECISION", 2),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_FEATURE_MODE_CFG_0", "PROC_PRECISION", 2),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_FEATURE_MODE_CFG_0", "OUT_PRECISION", 2),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_FEATURE_MODE_CFG_0", "BATCH_NUMBER", 0)],
    expected_raw="SDP_RDMA.D_FEATURE_MODE_CFG = (2<<6)|(2<<4)|(2<<2)|1 = 0x000000A9",
    cls="repacked bits + collisions; RK-only BURST_LEN and FP16TOFP32 bits",
    arithmetic="C4 v=0x00017849: flying=bit0=1, in_prec=2<<15 (bit16), proc_prec=2<<5 (bit6), burst=15<<11, fp16tofp32=bit3. "
               "NVDLA flying=bit0, winograd=bit1, in=[3:2], proc=[5:4], out=[7:6], batch=[12:8]. Literal copy: flying=1, "
               "in=(v>>2)&3=2, proc=(v>>4)&3=0, out=(v>>6)&3=1, batch=(v>>8)&0x1f=24. C3 v=0x7810 -> literal proc=1, out=0, batch=24.",
    note="RK's proc field at bit5/6 collides with NVDLA out_precision; the 15<<11 burst field sets batch_number=24 if copied. "
         "The adapter must take precision from DPU DATA_FORMAT/RK FEATURE_MODE and drop burst/fp16tofp32.",
    rtl="sdp/NV_NVDLA_SDP_RDMA_REG_dual.v:627-643")

row(block="RDMA", id="rdma_brdma_cfg", case="C3",
    rk_target=0x2001, rk_offset=0x501c, rk_field="BRDMA_CFG",
    rk_source="kernel_6_18/simple_conv.py:617",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_BRDMA_CFG_0", "BRDMA_DISABLE", 0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_BRDMA_CFG_0", "BRDMA_DATA_USE", 1)],
    expected_raw="SDP_RDMA.D_BRDMA_CFG = 0x00000002 (data_use=ALU)",
    cls="repacked bits (partial; data_size/mode unproven)",
    arithmetic="C3 v=2 -> NVDLA bit1 = BRDMA_DATA_USE=1 (ALU), disable=0. Literal copy is exact for those two bits. "
               "The captured value also leaves BRDMA_DATA_SIZE=0 (one byte) and BRDMA_DATA_MODE=0 (per-kernel); whether those are correct for int32 bias is not resolved.",
    note="The INT8 bias is int32 in the source (simple_conv.py:618 BS_BASE_ADDR); NVDLA BRDMA data_size=0 means one byte. "
         "Whether NVDLA BRDMA must be configured for 4-byte bias is not resolved by the capture. RK writes no BS line/surface strides.",
    rtl="sdp/NV_NVDLA_SDP_RDMA_REG_dual.v:535-551",
    confidence="medium")

row(block="RDMA", id="rdma_bs_base", case="C3",
    rk_target=0x2001, rk_offset=0x5020, rk_field="BS_BASE_ADDR",
    rk_source="kernel_6_18/simple_conv.py:618",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_BS_BASE_ADDR_LOW_0", "BS_BASE_ADDR_LOW", 0, literal=0),
           N("SDP_RDMA", "NVDLA_SDP_RDMA_D_BS_BASE_ADDR_HIGH_0", "BS_BASE_ADDR_HIGH", 0, literal=0)],
    expected_raw="SDP_RDMA.D_BS_BASE_ADDR_LOW = patched bias buffer address; HIGH = 0",
    cls="renamed/relocated (low 32 bits only)",
    arithmetic="regcmd value 0 (placeholder); job.json patch index 61 -> bias buffer. RK 0x5020 -> NVDLA 0x802c low.",
    note="NVDLA also needs BS_LINE_STRIDE/SURFACE_STRIDE/BATCH_STRIDE; RK writes none in the captured case.",
    rtl="header NVDLA_SDP_RDMA_D_BS_BASE_ADDR_LOW_0")

row(block="RDMA", id="rdma_weight", case="C3",
    rk_target=0x2001, rk_offset=0x5068, rk_field="RDMA_WEIGHT",
    rk_source="kernel_6_18/simple_conv.py:621",
    nvdla=[N("SDP_RDMA", "NVDLA_SDP_RDMA_D_EW_SURFACE_STRIDE_0", "EW_SURFACE_STRIDE", None, literal=0x01010101)],
    expected_raw="no matching SDP_RDMA control; offset 0x5068 collides with D_EW_SURFACE_STRIDE at 0x8068",
    cls="RK-only / unmappable",
    arithmetic="C3 v=0x01010101 = four bytes of 0x01. NVDLA D_EW_SURFACE_STRIDE would be 16,843,009 bytes, nonsensical for "
               "a 4x4x32 output. The source comment is only 'RDMA weight config' (simple_conv.py:621).",
    note="This is the strongest RDMA unmappable field. It may be a per-channel weight/scale config, but the available sources "
         "do not define it. Do not invent a mapping.",
    rtl="header NVDLA_SDP_RDMA_D_EW_SURFACE_STRIDE_0",
    confidence="high")



# ---------------------------------------------------------------- alias tables
def alias_candidates(block, rk_offset):
    regs, _ = SPEC_DATA[block]
    low = rk_offset & 0xFFF
    return [{"block": block, "register": r, "offset": d["offset"],
             "line": d["line"]}
            for r, d in regs.items() if (d["offset"] & 0xFFF) == low]


def alias_table(rk_target, items, blocks):
    out = []
    for off, field in items:
        cands = []
        for b in blocks:
            cands.extend(alias_candidates(b, off))
        out.append({
            "rk_target": f"0x{rk_target:04x}",
            "rk_offset": f"0x{off:04x}",
            "rk_field": field,
            "nvdla_same_low12": cands,
        })
    return out


OFFSET_ALIAS["CNA"] = alias_table(0x0201, [
    (0x100c, "CONV_CON1"),
    (0x1010, "CONV_CON2"),
    (0x1014, "CONV_CON3"),
    (0x1020, "DATA_SIZE0"),
    (0x1024, "DATA_SIZE1"),
    (0x1028, "DATA_SIZE2"),
    (0x102c, "DATA_SIZE3"),
    (0x1030, "WEIGHT_SIZE0"),
    (0x1034, "WEIGHT_SIZE1"),
    (0x1038, "WEIGHT_SIZE2"),
    (0x1040, "CBUF_CON0"),
    (0x1044, "CBUF_CON1"),
    (0x104c, "CVT_CON0"),
    (0x1050, "CVT_CON1"),
    (0x1070, "FEATURE_DATA_ADDR"),
    (0x1078, "DMA_CON0"),
    (0x107c, "DMA_CON1"),
    (0x1080, "DMA_CON2"),
    (0x1084, "FC_DATA_SIZE0"),
    (0x1088, "FC_DATA_SIZE1"),
    (0x1110, "DCOMP_ADDR0"),
    (0x1180, "CVT_CON5"),
], ["CSC", "CDMA"])

OFFSET_ALIAS["CORE"] = alias_table(0x0801, [
    (0x3010, "MISC_CFG"),
    (0x3014, "DATAOUT_SIZE_0"),
    (0x3018, "DATAOUT_SIZE_1"),
    (0x301c, "CLIP_TRUNCATE"),
    (0x3030, "RESERVED_3030"),
], ["CACC"])

OFFSET_ALIAS["DPU"] = alias_table(0x1001, [
    (0x4004, "S_POINTER"),
    (0x400c, "FEATURE_MODE_CFG"),
    (0x4010, "DATA_FORMAT"),
    (0x4020, "DST_BASE_ADDR"),
    (0x4024, "DST_SURF_STRIDE"),
    (0x4030, "DATA_CUBE_WIDTH"),
    (0x4034, "DATA_CUBE_HEIGHT"),
    (0x4038, "DATA_CUBE_NOTCH"),
    (0x403c, "DATA_CUBE_CHANNEL"),
    (0x4040, "BS_CFG"),
    (0x4050, "BS_OW_CFG"),
    (0x4058, "WDMA_SIZE_0"),
    (0x405c, "WDMA_SIZE_1"),
    (0x4060, "BN_CFG"),
    (0x4070, "EW_CFG"),
    (0x4078, "EW_CVT_SCALE_VALUE"),
    (0x4084, "OUT_CVT_SCALE"),
    (0x40c0, "SURFACE_ADD"),
], ["SDP"])

OFFSET_ALIAS["RDMA"] = alias_table(0x2001, [
    (0x5004, "S_POINTER"),
    (0x500c, "DATA_CUBE_WIDTH"),
    (0x5010, "DATA_CUBE_HEIGHT"),
    (0x5014, "DATA_CUBE_CHANNEL"),
    (0x5018, "SRC_BASE_ADDR"),
    (0x501c, "BRDMA_CFG"),
    (0x5020, "BS_BASE_ADDR"),
    (0x5034, "ERDMA_CFG"),
    (0x5038, "EW_BASE_ADDR"),
    (0x5044, "FEATURE_MODE_CFG"),
    (0x5068, "RDMA_WEIGHT"),
], ["SDP_RDMA"])

# Naive-alias effects that are worth spelling out in prose.
ALIAS_NOTES = {
    "CNA": {
        0x1010: "RK CONV_CON2=0xB0 would become CDMA D_OP_ENABLE; bit0=0, so no trigger is written.",
        0x1024: "RK DATA_SIZE1=0x000f0010 would become CSC D_ENTRY_PER_SLICE=16.",
        0x1070: "RK FEATURE_DATA_ADDR=0 would become CDMA D_WEIGHT_SIZE_1=0, not a data address.",
        0x107c: "RK DMA_CON1=0x20 would become CDMA D_WEIGHT_ADDR_LOW=32, not a line stride.",
        0x1084: "RK FC_DATA_SIZE0=0x00080008 would become CDMA D_WGS_ADDR_HIGH, not a size.",
        0x1110: "No NVDLA register at 0x1110 (CSC ends 0x4064, CDMA ends 0x30e8).",
        0x1180: "No NVDLA register at 0x1180.",
    },
    "CORE": {
        0x3010: "RK MISC_CFG=0x201 would become CACC D_DATAOUT_SIZE_0: width=513, height=0.",
        0x3014: "RK DATAOUT_SIZE_0=0x00050005 would become CACC D_DATAOUT_SIZE_1: channel=5.",
        0x3018: "RK DATAOUT_SIZE_1=0x1F would become CACC D_DATAOUT_ADDR=31.",
        0x301c: "RK CLIP_TRUNCATE=0 would become CACC D_BATCH_NUMBER=0.",
        0x3030: "RK RESERVED=0 would hit CACC D_OUT_SATURATION (read-only status).",
    },
    "DPU": {
        0x400c: "RK FEATURE_MODE_CFG=0x1E5 would become SDP S_LUT_ACCESS_DATA.",
        0x4010: "RK DATA_FORMAT=0x48000002 would become SDP S_LUT_CFG.",
        0x4038: "RK DATA_CUBE_NOTCH=0 would become SDP D_OP_ENABLE=0: the block would never start.",
        0x4050: "RK BS_OW_CFG=0x126 would become SDP D_DST_LINE_STRIDE=294.",
        0x4058: "RK WDMA_SIZE_0=0x1F would become SDP D_DP_BS_CFG and set four bypass bits.",
        0x405c: "RK WDMA_SIZE_1=0x00050005 would become SDP D_DP_BS_ALU_CFG.",
        0x4060: "RK BN_CFG=0x53 would become SDP D_DP_BS_ALU_SRC_VALUE=83.",
        0x4070: "RK EW_CFG=0x108202c0 would become SDP D_DP_BN_ALU_CFG.",
        0x4084: "RK OUT_CVT_SCALE=0x10001 would become SDP D_DP_EW_ALU_CFG.",
        0x40c0: "RK SURFACE_ADD=0x480 would become SDP D_CVT_OFFSET=1152.",
    },
    "RDMA": {
        0x501c: "RK BRDMA_CFG=2 would become SDP_RDMA D_SRC_BASE_ADDR_HIGH=2 (address 0x2_xxxxxxxx).",
        0x5020: "RK BS_BASE_ADDR=0 would become SDP_RDMA D_SRC_LINE_STRIDE, not a base address.",
        0x5034: "RK ERDMA_CFG=0x40000008 would become SDP_RDMA D_BS_LINE_STRIDE.",
        0x5038: "RK EW_BASE_ADDR=0 would become SDP_RDMA D_BS_SURFACE_STRIDE.",
        0x5044: "RK FEATURE_MODE_CFG=0x17849 would become SDP_RDMA D_BN_BASE_ADDR_LOW.",
        0x5068: "RK RDMA_WEIGHT=0x01010101 would become SDP_RDMA D_EW_SURFACE_STRIDE=16,843,009.",
    },
}

# ---------------------------------------------------------------- block meta
BLOCK_META = {
    "CNA": {
        "rk_target": "0x0201",
        "nvdla": "CSC (0x4000) + CDMA (0x3000)",
        "question": "Is CNA NVDLA CSC + CDMA merged into one target, or a single reorganized CSC?",
        "answer": "Merged, reduced CSC+CDMA register surface - not a single reorganized CSC, and not a copy of either block.",
        "why": [
            "CDMA-only functions are present: feature/weight addresses, line/surface strides, fetch grains, CVT.",
            "CSC-only functions are present: dataout size, atomics, weight width/height/kernel extension.",
            "Many CSC/CDMA fields are absent: batch, dilation, right/bottom padding, pixel/image formats, mean, WGS/WMB, second data address, release.",
            "RK adds fields with no NVDLA counterpart: burst lengths, four CVT lanes, CVT_CON5, a packed real-vs-aligned channel pair.",
        ],
        "verdict": "reusable with adapter plus specific datapath changes",
        "changes": [
            "CVT path: RK's four scale/offset/truncate lanes and bypass convention (per builder comment) do not match the single integer-only CDMA CVT.",
            "CBUF geometry: RK models 12 banks x 256 entries x 128 B; NVDLA nv_small_256 is 32 banks x 32 B x 128 deep with 256-bit entries. The -1 entry conversion alone does not prove equivalence.",
            "Input stride/addressing: RK DMA_CON1/2 are 32-byte-unit, 4-row-tiled strides, while NVDLA D_LINE/SURF_STRIDE are byte strides for a different decomposition.",
            "Channel contract: RK transports both padded CBUF channels and real weight channels in DATA_SIZE1; NVDLA splits them across D_DATAIN_SIZE_EXT_1 and D_WEIGHT_SIZE_EXT_1 (an adapter can do this, but it is cross-register).",
        ],
        "strongest": [
            "DATA_SIZE0=0x00080008 (C1) vs NVDLA 0x00070007; the asymmetric C5 capture 0x001c000b (H=11,W=28) vs 0x000a001b proves the width/height swap and the +1.",
            "WEIGHT_SIZE2=0x03030020 (C1) packs kw=3,kh=3,kernels=32; NVDLA needs D_WEIGHT_SIZE_EXT_0=0x00020002 and D_WEIGHT_SIZE_EXT_1 kernel=31.",
            "DMA_CON1/2 are 32-byte-unit strides (conv_new_clean.py:274-276), while NVDLA line/surface strides are byte-addressed (cdma.v:829-830).",
            "CVT_CON1..4 merge CDMA scale+offset into one word and appear four times; NVDLA has one scale/offset pair.",
        ],
        "rk_only": ["CONV_CON1 bits 29,30 and [15:12] non-aligned path", "CONV_CON2 <<4 field position", "CVT_CON0 bits1,3", "CVT_CON1..4 four-lane packing", "CVT_CON5 0x1180", "DMA_CON0 burst lengths", "DATA_SIZE1 real/aligned pair"],
        "nvdla_only": ["CSC/CDMA D_OP_ENABLE (0x4008/0x3010)", "CSC D_DATAIN_FORMAT/D_WEIGHT_FORMAT/D_BATCH_NUMBER/D_DILATION_EXT", "CDMA D_DAIN_MAP/D_PIXEL_OFFSET/D_MEAN_*/D_NAN_*/D_WGS/D_WMB", "S_POINTER producer/consumer protocol"],
        "unresolved": ["exact CBUF entry-size equivalence", "CVT_CON5 meaning", "CBUF_CON1 unit conversion beyond -1", "whether NVDLA CSC/CDMA can reproduce RK's 4-row input tiling without new address logic"],
    },
    "CORE": {
        "rk_target": "0x0801",
        "nvdla": "CACC (0x7000)",
        "question": "Is CORE a CACC subset with a fixed offset shift?",
        "answer": "A CACC subset, but not a fixed offset shift. The first three registers are +4 relative to CACC; CLIP is -0x10 relative; 0x3030 is a read-only CACC status offset.",
        "why": [
            "DATAOUT_SIZE_0, DATAOUT_SIZE_1 and CLIP_TRUNCATE map bit-for-bit and value-for-value to CACC.",
            "MISC_CFG is repacked: proc_precision moves [10:8] -> [13:12]; bit0 is RK's is_spatial flag, not CACC's direct/Winograd conv_mode; bit1 is an RK-only depthwise enable.",
            "CACC's DATAOUT_ADDR/BATCH/LINE/SURF/DATAOUT_MAP are absent from RK CORE; RK has a compacted map.",
            "0x3030 collides with CACC D_OUT_SATURATION, which is read-only.",
        ],
        "verdict": "reusable with a pure register adapter (for the accumulator/output-size subset)",
        "changes": [
            "Repack MISC_CFG precision and drop the RK spatial/depthwise bits.",
            "If the CACC memory-write path is used, synthesize D_DATAOUT_ADDR and the line/surface strides; RK does not provide them.",
            "Do not forward 0x3030 as a control; it is a read-only CACC status offset.",
        ],
        "strongest": [
            "DATAOUT_SIZE_0=0x00050005 and DATAOUT_SIZE_1=0x1F match CACC exactly (0-based W/H/C).",
            "MISC_CFG=0x201 for a direct 3x3 conv would be CACC conv_mode=1 (Winograd) and proc=0 if copied literally.",
            "CLIP at 0x301c vs CACC 0x702c disproves a single fixed offset shift.",
        ],
        "rk_only": ["MISC_CFG bit0 spatial flag", "MISC_CFG bit1 depthwise enable", "0x3030 reserved write"],
        "nvdla_only": ["D_OP_ENABLE 0x7008", "D_DATAOUT_ADDR 0x7018", "D_BATCH_NUMBER 0x701c", "D_LINE_STRIDE 0x7020", "D_SURF_STRIDE 0x7024", "D_DATAOUT_MAP 0x7028"],
        "unresolved": ["whether the RK CORE actually has a memory-write port", "how the RK CORE feeds DPU without an RDMA source address"],
    },
    "DPU": {
        "rk_target": "0x1001",
        "nvdla": "SDP (0x9000)",
        "question": "Map the DPU fields to NVDLA SDP D_* fields.",
        "answer": "Same SDP BS/BN/EW datapath family, but a repacked control surface. Cube dimensions and several bypass/CVT fields map cleanly; FEATURE_MODE_CFG, DATA_FORMAT and EW_CFG do not.",
        "why": [
            "DATA_CUBE_WIDTH/HEIGHT and the low channel field are exact 0-based aliases.",
            "BS_CFG=0x53 and BN_CFG=0x53 are bit-identical to SDP D_DP_BS_CFG/D_DP_BN_CFG bypass layouts.",
            "OUT_CVT_OFFSET/SHIFT/SCALE map to SDP D_CVT_OFFSET/SHIFT/SCALE (scale low 16 bits).",
            "FEATURE_MODE_CFG packs burst/conv/output mode into bits that SDP reads as Winograd/batch.",
            "DATA_FORMAT has an RK-only IN_PRECISION and a 3-bit OUT_PRECISION; SDP has 2-bit PROC/OUT only.",
            "EW_CFG uses a 3-bit ALU opcode at [18:16], a separate MUL select, and SUB/FDIV opcodes that SDP's EW ALU does not have.",
        ],
        "verdict": "reusable with adapter plus specific datapath changes (EW stage is compile-time disabled in nv_small_256)",
        "build_caveat": "nv_small_256 has NVDLA_SDP_EW_THROUGHPUT=0 (project.vh:16); NV_NVDLA_SDP_core.v ties cfg_ew_en to 0 (lines 329,334) and has no reg2dp_ew_* ports; NV_NVDLA_sdp.v ties the WDMA EW config to ew_bypass=1 (lines 260-262). The EW register definitions exist in the header, but the EW datapath is not usable in this reference build.",
        "changes": [
            "EW datapath enablement: nv_small_256 compiles the SDP EW stage out (NVDLA_SDP_EW_THROUGHPUT=0, cfg_ew_en tied 0). Reusing the reference RTL for RK EW requires enabling/instantiating the EW stage, not just programming D_DP_EW_CFG. If that integration is out of scope, RK EW is not reusable without new RTL.",
            "CORE->DPU feed: the conv streams write no RDMA source address and DPU flying_mode=0, so DPU must be fed by CORE. NVDLA SDP has no CACC->SDP path; use a CACC memory round-trip (requires CACC output address/strides) or add a direct feed.",
            "EW ALU: ADD/MAX/MUL/NEG are adapter-mappable; SUB needs operand negation (not proven) and FDIV needs a divider that SDP does not have.",
            "FP32 output: RK's 1x1 FP16 path uses OUT_PRECISION=5; SDP's 2-bit field cannot encode it.",
            "NC1HWC2 surface addressing: RK's DST_SURF_STRIDE is an 8-channel plane stride (padded to 4 atoms); SDP needs DST_LINE_STRIDE synthesized and its surface granularity validated.",
            "BS_OW_CFG/WDMA_SIZE/SURFACE_ADD are RK-only; the adapter must translate or drop them consistently.",
        ],
        "strongest": [
            "FEATURE_MODE_CFG=0x1E5 decodes in SDP as flying=1, winograd=1, batch=1, but RK means output_mode=2 and burst=15.",
            "EW_CFG=0x108402C0 for SUB has ALU_ALGO=4 at [18:16]; SDP's 2-bit ALU_ALGO at [3:2] cannot represent it and has no SUB enum.",
            "DATA_FORMAT=0x48000002 decodes in SDP as proc=FP16, out=INT8; the RK out=FP16 is at [31:29], not [3:2].",
            "DATA_FORMAT=0xA8000002 uses OUT_PRECISION=5 (FP32), which SDP cannot represent.",
            "nv_small_256 disables the SDP EW stage at compile time: NVDLA_SDP_EW_THROUGHPUT=0, cfg_ew_en=0, and the core has no reg2dp_ew_* ports. RK's EW ops therefore cannot run on this reference build without enabling the EW datapath.",
        ],
        "rk_only": ["FEATURE_MODE_CFG burst/conv/output mode bits", "DATA_FORMAT IN_PRECISION and 3-bit OUT_PRECISION", "DATA_CUBE_NOTCH", "BS_OW_CFG/BS_OW_OP", "WDMA_SIZE_0/1", "EW_CFG ALU_ALGO[18:16]/OP_TYPE/OP_SRC/OP_CVT_BYPASS/RELU_BYPASS/DATA_MODE/EDATA_SIZE", "OUT_CVT_SCALE bit16", "SURFACE_ADD"],
        "nvdla_only": ["D_OP_ENABLE 0x9038", "D_DST_LINE_STRIDE 0x9050", "D_DST_BATCH_STRIDE 0x90b8", "DP_BS_ALU_CFG/MUL_CFG/operands", "DP_BN_ALU_CFG/MUL_CFG/operands", "DP_EW_ALU_CFG/MUL_CFG/CVT offset/truncate", "D_CVT_OFFSET/SHIFT", "LUT registers"],
        "unresolved": ["exact meaning of FEATURE_MODE_CFG BYPASS=15<<5", "whether SDP's EW ALU can implement SUB by operand negation", "how to source DPU from CORE without a memory round-trip", "SDP surface grouping for the RK c2=8 layout"],
    },
    "RDMA": {
        "rk_target": "0x2001",
        "nvdla": "SDP_RDMA (0x8000)",
        "question": "Map S_POINTER, CUBE_*, SRC_BASE, ERDMA_CFG, EW_BASE, FEATURE_MODE_CFG to NVDLA SDP_RDMA.",
        "answer": "SDP_RDMA family. Four fields are exact aliases (cube W/H/C and SRC_BASE low); the rest are relocated/repacked, and one field has no counterpart.",
        "why": [
            "RK 0x500c/0x5010/0x5014/0x5018 are the same low-12 offsets as SDP_RDMA D_DATA_CUBE_WIDTH/HEIGHT/CHANNEL and D_SRC_BASE_ADDR_LOW, with the same 0-based/byte encodings.",
            "ERDMA_CFG moves data_mode to bit30 and uses bits[3:2] for data_size; SDP_RDMA uses bit4 and bit3.",
            "FEATURE_MODE_CFG puts in_precision at [16:15] and proc_precision at [6:5]; SDP_RDMA uses [3:2] and [5:4], and bits 11-14 collide with batch_number.",
            "RDMA_WEIGHT 0x5068 has no SDP_RDMA control; its low-12 offset collides with D_EW_SURFACE_STRIDE.",
            "RK does not write SRC/BS/EW line/surface/batch strides, which SDP_RDMA needs for general tensors.",
            "The nv_small_256 build does not instantiate ERDMA and hardwires erdma_disable=1, so the EW operand read path used by the captured FP16 EW cases is absent from the reference RTL.",
        ],
        "verdict": "adapter + datapath change for the captured FP16 EW cases (ERDMA is not instantiated in nv_small_256); adapter + config addition for the INT8 BRDMA bias path; pure adapter only for the MRDMA cube/source fields",
        "build_caveat": "nv_small_256 has NVDLA_SDP_EW_THROUGHPUT=0 (project.vh:16). NV_NVDLA_SDP_rdma.v hardwires erdma_disable=1 (line 350) and instantiates only BRDMA/NRDMA (lines 216,258); there is no u_erdma instance and NV_NVDLA_sdp.v connects no sdp_erdma2dp_* signals. The ERDMA register definitions exist in the header, but the EW operand read path is absent from this build.",
        "changes": [
            "ERDMA enablement: nv_small_256 does not instantiate the ERDMA block and hardwires erdma_disable=1. RK's FP16 EW cases use ERDMA_CFG/EW_BASE to fetch the B operand, so reusing this reference RTL for those cases requires enabling/instantiating ERDMA, not just repacking fields. If that is out of scope, the captured EW path is not reusable without new RTL.",
            "For captured EW: repack ERDMA_CFG/FEATURE_MODE_CFG, set ERDMA data_use from the DPU op, and default the three EW strides to 0 (1x1x8 tensor).",
            "For INT8 conv: RDMA_WEIGHT 0x5068 is unmappable; the bias path also needs BS strides, and the BRDMA data_size for int32 bias is unproven.",
            "For general tensors: synthesize SRC/BS/EW line/surface/batch strides; RK does not carry them.",
        ],
        "strongest": [
            "Cube W/H/C and SRC_BASE low are exact aliases (0x500c/10/14/18 -> 0x800c/10/14/18).",
            "FEATURE_MODE_CFG=0x17849 copies into SDP_RDMA as proc_precision=0 and batch_number=24; RK means proc=FP16 and burst=15.",
            "ERDMA_CFG=0x40000008 copies as data_use=MUL and data_mode=0; RK means data_mode=1 and the EW operand is used by the ALU for ADD/SUB/MAX.",
            "RDMA_WEIGHT=0x01010101 has no SDP_RDMA register and is nonsensical as EW_SURFACE_STRIDE.",
            "The reference RTL cannot execute the captured EW operand fetch: NV_NVDLA_SDP_rdma.v sets erdma_disable=1 and has no u_erdma instance.",
        ],
        "rk_only": ["S_POINTER PP bits", "ERDMA_CFG bit30 / data_size[3:2]", "FEATURE_MODE BURST_LEN and MRDMA_FP16TOFP32_EN", "RDMA_WEIGHT 0x5068", "SURF_NOTCH/EW_SURF_NOTCH 0x504c/0x506c"],
        "nvdla_only": ["D_OP_ENABLE 0x8008", "D_SRC_LINE/SURFACE_STRIDE 0x8020/0x8024", "D_BS_LINE/SURFACE/BATCH_STRIDE 0x8034/0x8038/0x803c", "D_BN_* 0x8044-0x8054", "D_NRDMA_CFG 0x8040", "D_EW_LINE/SURFACE/BATCH_STRIDE 0x8064/0x8068/0x806c", "D_SRC_DMA_CFG 0x8074"],
        "unresolved": ["RDMA_WEIGHT semantics", "which RK register is the EW surface stride (0x5040 vs 0x5068)", "BRDMA data_size for int32 bias", "general multi-dimensional stride synthesis", "enabling/instantiating ERDMA in the reference build"],
    },
}

# ---------------------------------------------------------------- emit
def canon_class(cls):
    if cls.startswith("identical"):
        return "identical"
    if cls.startswith("renamed"):
        return "renamed/relocated"
    if cls.startswith("repacked"):
        return "repacked bits"
    if cls.startswith("semantics"):
        return "semantics differ"
    if cls.startswith("RK-only"):
        return "RK-only"
    if cls.startswith("NVDLA-only"):
        return "NVDLA-only"
    return cls


def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def field_bits(ref):
    if ref.get("mask") is None:
        return "?"
    bits = ref["mask"].bit_length()
    return f"{ref['shift'] + bits - 1}:{ref['shift']}"


def short_reg(block, reg):
    prefix = "NVDLA_" + block + "_"
    if reg.startswith(prefix):
        return reg[len(prefix):]
    return reg.replace("NVDLA_", "")


def nvdla_cell(e):
    ref = e["ref"]
    bits = field_bits(ref)
    exp = e["expected"]
    lit = e["literal"]
    if exp is None:
        exps = "n/a"
    elif isinstance(exp, str):
        exps = exp
    else:
        exps = f"0x{exp:x}"
    lits = "n/a" if lit is None else f"0x{lit:x}"
    return (f"{ref['block']}.{short_reg(ref['block'], ref['register'])}.{ref['field']} "
            f"[{bits}] exp {exps} / literal {lits}")


def emit_json(path):
    out = {
        "schema": "rk-nvdla-field-crosswalk/v1",
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": "RKNPU CNA/CORE/DPU/RDMA register fields vs NVDLA nv_small_256 CSC/CDMA/CACC/SDP/SDP_RDMA",
        "method": {
            "qword_encoding": "(target << 48) | ((value & 0xffffffff) << 16) | reg_addr",
            "rk_streams": "decoded directly from build/rk3588-example-captures/*/cases/*/regcmd.bin",
            "nvdla_spec": "parsed from generated NVDLA_*.h in the nv_small_256 spec/manual directory",
            "nvdla_rtl": "used to resolve 0-based vs actual counts, byte units, and field positions",
            "classification": ["identical", "renamed/relocated", "repacked bits", "semantics differ", "RK-only", "NVDLA-only"],
        },
        "sources": {
            "rknpu_fpga_revision": "f9b00d8f9a48ab4dea20cb30148890cd9f1443ee",
            "rk_examples_revision": "273d015e08af40c81d2cd9ab84198486b03a17f1",
            "nvdla_revision": "3f1bc4c36c6737d5873f8c1833dffac9322387a0",
            "nvdla_spec_dir": SPEC,
            "rk_builders": [
                {"path": p, "sha256": sha256(p)}
                for p in [
                    os.path.join(RK, "expt/conv_simple.py"),
                    os.path.join(RK, "kernel_6_18/conv_new_clean.py"),
                    os.path.join(RK, "kernel_6_18/simple_conv.py"),
                    os.path.join(RK, "elementwise.py"),
                    "/home/fedora/rk3588/experimental/kernel_6_18/elementwise.py",
                ]
            ],
            "nvdla_headers": [
                {"path": p, "sha256": sha256(p)}
                for p in BLOCK_FILES.values()
            ],
        },
        "cases": {},
        "blocks": {},
        "summary": {},
    }
    for key, c in CASES.items():
        out["cases"][key] = {
            "id": c["id"],
            "family": c["family"],
            "path": os.path.relpath(c["path"], CAP),
            "sha256": c["sha256"],
            "bytes": c["bytes"],
            "qwords": c["qwords"],
            "shape": c["shape"],
            "role": c["role"],
            "source": c["source"],
            "decoded_writes": [
                {k: w[k] for k in ("qword", "target", "offset", "value", "raw", "patch") if k in w}
                for w in c["writes"]
            ],
        }
    for b in ("CNA", "CORE", "DPU", "RDMA"):
        meta = BLOCK_META[b]
        brows = [r for r in ROWS if r["block"] == b]
        out["blocks"][b] = {
            "rk_target": meta["rk_target"],
            "nvdla": meta["nvdla"],
            "question": meta["question"],
            "answer": meta["answer"],
            "why": meta["why"],
            "verdict": meta["verdict"],
            "build_caveat": meta.get("build_caveat", ""),
            "datapath_changes": meta["changes"],
            "strongest_evidence": meta["strongest"],
            "rk_only": meta["rk_only"],
            "nvdla_only": meta["nvdla_only"],
            "unresolved": meta["unresolved"],
            "offset_alias": OFFSET_ALIAS[b],
            "rows": [],
        }
        for r in brows:
            out["blocks"][b]["rows"].append({
                "id": r["id"],
                "case": r["case"],
                "rk": {
                    "target": f"0x{r['rk_target']:04x}",
                    "offset": f"0x{r['rk_offset']:04x}",
                    "field": r["rk_field"],
                    "value": f"0x{r['rk_value']:08x}",
                    "value_dec": r["rk_value"],
                    "qword": r["rk_qword"],
                    "patch": r.get("rk_patch"),
                    "source": r["rk_source"],
                },
                "nvdla": [
                    {
                        "block": e["ref"]["block"],
                        "register": e["ref"]["register"],
                        "offset": f"0x{e['ref']['offset']:04x}",
                        "field": e["ref"]["field"],
                        "shift": e["ref"]["shift"],
                        "mask": f"0x{e['ref']['mask']:x}" if e["ref"].get("mask") is not None else None,
                        "expected": e["expected"],
                        "literal_from_rk_value": e["literal"],
                        "header_line": e["ref"]["field_line"],
                        "header": e["ref"]["header"],
                    }
                    for e in r["nvdla"]
                ],
                "expected_raw": r["expected_raw"],
                "classification": r["cls"],
                "canonical_classification": canon_class(r["cls"]),
                "arithmetic": r["arithmetic"],
                "note": r["note"],
                "rtl": r.get("rtl", ""),
                "confidence": r["confidence"],
            })
    counts = {}
    for r in ROWS:
        counts[canon_class(r["cls"])] = counts.get(canon_class(r["cls"]), 0) + 1
    out["summary"] = {
        "row_count": len(ROWS),
        "classification_counts": counts,
        "identical_rows": [r["id"] for r in ROWS if r["cls"].startswith("identical")],
        "strict_hypothesis": "disproved",
        "strict_hypothesis_reason": "No consistent offset alias exists; only 4 RDMA fields are identical aliases. CNA/CORE/DPU/RDMA fields are repacked with different value conventions, and several fields have no counterpart.",
        "weaker_hypothesis": "consistent with NVDLA-derived blocks and a rewritten register file, but register streams cannot prove RTL identity",
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


def emit_markdown(path):
    lines = []
    A = lines.append
    A("# RKNPU <-> NVDLA field crosswalk")
    A("")
    A("This report tests the hypothesis that the RKNPU RTL is the NVDLA RTL with different register")
    A("names/offsets. It decodes real RK command streams and compares each field with the NVDLA")
    A("nv_small_256 CSC/CDMA/CACC/SDP/SDP_RDMA definitions. It does not use offset similarity as proof.")
    A("")
    A("**Strict hypothesis: disproved.** Only four fields are identical aliases (RDMA cube W/H/C and")
    A("SRC_BASE low). Everything else is relocated, repacked, has a different value convention, or has")
    A("no counterpart. The block decomposition and many field semantics are NVDLA-family, so a weaker")
    A("hypothesis (NVDLA-derived blocks with a rewritten register file) remains plausible, but register")
    A("streams cannot prove RTL identity.")
    A("")
    A("## Method")
    A("")
    A("- Decode each `regcmd.bin` QWORD as `(target << 48) | (value << 16) | reg_addr`.")
    A("- Parse the generated NVDLA headers for register offsets, field shifts and masks.")
    A("- Resolve value conventions from the NVDLA RTL where the header alone is ambiguous")
    A("  (0-based counts, byte strides, integer-only CVT).")
    A("- For every row: extract the RK semantic field, compute the NVDLA expected encoding, and also")
    A("  show what a literal copy of the RK value would decode to in the NVDLA field.")
    A("- Write a row only when a decoded capture value or a source definition supports it.")
    A("")
    A("## Cases")
    A("")
    A("| key | case | shape | regcmd sha256 (first 16) |")
    A("|---|---|---|---|")
    for k, c in CASES.items():
        A(f"| {k} | `{c['id']}` | {md_escape(c['shape'])} | `{c['sha256'][:16]}` |")
    A("")
    A("C1 is the required 3x3 FP16 case; C3 is the required INT8 case; C2 is the required conv-fp16")
    A("3x3 case; C4/C4S/C4M/C4X are the required EW add/sub/mul/max p1_n8 cases. C5 and C1b are")
    A("supporting cases used only to disambiguate swapped dimensions and RK-only bits.")
    A("")
    A("## Bottom line")
    A("")
    A("| Block | NVDLA reference | Verdict |")
    A("|---|---|---|")
    for b in ("CNA", "CORE", "DPU", "RDMA"):
        A(f"| {b} | {BLOCK_META[b]['nvdla']} | {BLOCK_META[b]['verdict']} |")
    A("")
    A("## Classification summary")
    A("")
    cc = {}
    for r in ROWS:
        cc[canon_class(r["cls"])] = cc.get(canon_class(r["cls"]), 0) + 1
    A("| Class | Rows | Meaning |")
    A("|---|---:|---|")
    A(f"| identical | {cc.get('identical', 0)} | same relative offset, field and encoding |")
    A(f"| renamed/relocated | {cc.get('renamed/relocated', 0)} | same field/encoding at a different register or split low/high |")
    A(f"| repacked bits | {cc.get('repacked bits', 0)} | same semantic field at different bit positions, or merged/split fields |")
    A(f"| semantics differ | {cc.get('semantics differ', 0)} | different value convention, units, polarity or datapath meaning |")
    A(f"| RK-only | {cc.get('RK-only', 0)} | no NVDLA counterpart |")
    A(f"| NVDLA-only | {cc.get('NVDLA-only', 0)} | required by NVDLA but not written by RK (listed per block) |")
    A("")
    A("Counts use the primary class; mixed rows are counted once. The only true identical aliases are")
    A("the four RDMA fields (cube W/H/C and SRC_BASE low). NVDLA-only fields are listed per block")
    A("rather than as rows, so their row count is 0.")
    A("")
    A("## Offset-alias test")
    A("")
    A("A naive bridge would map `NVDLA_base + (RK_offset & 0xfff)`. The tables below list the NVDLA")
    A("register that actually lives at each RK low-12 offset. The collisions are not cosmetic: several")
    A("would program an unrelated block.")
    A("")
    for b in ("CNA", "CORE", "DPU", "RDMA"):
        A(f"### {b}")
        A("")
        A("| RK offset | RK field | NVDLA register(s) at same low 12 | Naive effect |")
        A("|---|---|---|---|")
        for a in OFFSET_ALIAS[b]:
            cands = ", ".join(f"{x['block']}.{short_reg(x['block'], x['register'])}@0x{x['offset']:04x}"
                              for x in a["nvdla_same_low12"]) or "none"
            note = ALIAS_NOTES.get(b, {}).get(int(a["rk_offset"], 16), "")
            A(f"| `{a['rk_offset']}` | {md_escape(a['rk_field'])} | {md_escape(cands)} | {md_escape(note)} |")
        A("")
    A("The only exact low-12 aliases with matching semantics are RDMA `0x500c/0x5010/0x5014/0x5018`.")
    A("CNA `0x100c` happens to land on CSC `D_MISC_CFG`, but the precision bits are repacked, so even")
    A("that one is not a rename.")
    A("")
    for b in ("CNA", "CORE", "DPU", "RDMA"):
        meta = BLOCK_META[b]
        A(f"## {b}: {meta['nvdla']}")
        A("")
        A(f"RK target: `{meta['rk_target']}`. NVDLA reference: {meta['nvdla']}.")
        A("")
        A(f"**Question.** {meta['question']}")
        A("")
        A(f"**Answer.** {meta['answer']}")
        A("")
        A(f"**Verdict.** `{meta['verdict']}`")
        A("")
        if meta.get("build_caveat"):
            A(f"**Reference-build caveat.** {meta['build_caveat']}")
            A("")
        A("**Why.**")
        for x in meta["why"]:
            A(f"- {x}")
        A("")
        A("**Datapath changes / adapter work.**")
        for x in meta["changes"]:
            A(f"- {x}")
        A("")
        A("**Strongest evidence.**")
        for x in meta["strongest"]:
            A(f"- {x}")
        A("")
        A("### Field table")
        A("")
        A("| RK field (offset) | RK value | NVDLA field [bits] expected / literal | Class | Evidence / arithmetic |")
        A("|---|---|---|---|---|")
        for r in [x for x in ROWS if x["block"] == b]:
            nvcell = "<br>".join(nvdla_cell(e) for e in r["nvdla"]) if r["nvdla"] else "no NVDLA counterpart"
            ev = f"{r['arithmetic']} Source: {r['rk_source']}."
            if r.get("rtl"):
                ev += f" RTL: {r['rtl']}."
            if r["note"]:
                ev += f" Note: {r['note']}"
            A(f"| {md_escape(r['rk_field'])} (`0x{r['rk_offset']:04x}`) | "
              f"`0x{r['rk_value']:08x}` ({r['case']}) | {md_escape(nvcell)} | {md_escape(r['cls'])} | {md_escape(ev)} |")
        A("")
        A("**RK-only / unmapped.** " + "; ".join(meta["rk_only"]))
        A("")
        A("**NVDLA-only (required for a full block, not written by RK).** " + "; ".join(meta["nvdla_only"]))
        A("")
        A("**Unresolved.** " + "; ".join(meta["unresolved"]))
        A("")
    A("## Cross-block findings")
    A("")
    A("1. **CNA is a merged, reduced CSC+CDMA surface.** It contains CDMA-only CVT/address/stride/grains")
    A("   fields and CSC-only dataout/atomics/weight-extension fields. It is not a single reorganized CSC,")
    A("   and it drops many CSC/CDMA fields (batch, dilation, right/bottom padding, pixel formats, mean,")
    A("   WGS/WMB, second data address).")
    A("2. **CORE is a compacted CACC subset, not a fixed-shift alias.** DATAOUT_SIZE_0/1 and CLIP map")
    A("   bit-for-bit, but MISC_CFG is repacked and 0x3030 is a read-only CACC status offset.")
    A("3. **DPU is the SDP datapath family with a rewritten control surface.** Cube dimensions and")
    A("   BS/BN bypass bits map; FEATURE_MODE_CFG, DATA_FORMAT and EW_CFG do not. The RK conv path")
    A("   appears to feed DPU from CORE, which NVDLA SDP cannot do without a memory round-trip or a new")
    A("   direct feed.")
    A("4. **RDMA is the SDP_RDMA family with four exact aliases.** Cube W/H/C and SRC_BASE low are exact;")
    A("   ERDMA_CFG and FEATURE_MODE_CFG are repacked with collisions; RDMA_WEIGHT has no counterpart.")
    A("5. **Count conventions differ systematically.** RK CNA input/output/weight/entry counts are actual")
    A("   counts; NVDLA CSC/CDMA use last-index (value-1) encodings. RK CORE output sizes are already")
    A("   0-based, matching CACC. This inconsistency is itself evidence against a simple rename.")
    A("6. **No block's OP_ENABLE is written by RK.** RK uses the PC target 0x0081/0x0008 with values")
    A("   0x0d (FP16 conv), 0x1d (INT8 conv), 0x18 (EW). NVDLA needs D_OP_ENABLE for CSC, CDMA, CACC,")
    A("   SDP and SDP_RDMA; the bridge must synthesize them from the PC trigger.")
    A("")
    A("## Caveats")
    A("")
    A("- Register writes prove the programming model, not the RTL internals. The conclusions are about")
    A("  field-level reusability, not about whether any RK RTL file was copied from NVDLA.")
    A("- The NVDLA reference is `nv_small_256`; other NVDLA configurations may have different CBUF/atom")
    A("  geometry.")
    A("- DMA address registers in the captured `regcmd.bin` are zero placeholders patched at runtime;")
    A("  address rows cite the job patch, not a device address.")
    A("- All required geometry cases are square except the supporting C5 depthwise 28x11 case. The")
    A("  width/height swap conclusion uses C5; the required cases alone cannot distinguish it.")
    A("- The padding mapping is only evidenced at zero (C3 PAD_CON0=0). The SAME-padding case is BLOCKED.")
    A("- No non-identity CVT capture exists; the four-lane CVT conclusion is source-level plus the")
    A("  captured identity values.")
    A("- The SUB/FDIV datapath conclusions are based on the NVDLA SDP ALU opcode set and the absence of a")
    A("  divider, not on a device differential test.")
    A("- Builder comments are not authoritative: CVT_CON5 and CORE MISC_CFG bit0 are two examples where")
    A("  the comment and the value disagree.")
    A("")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    for r in ROWS:
        resolve_row(r)
    emit_json(os.path.join(HERE, "FIELD_CROSSWALK.json"))
    emit_markdown(os.path.join(HERE, "FIELD_CROSSWALK.md"))
    print(f"rows={len(ROWS)}")
    counts = {}
    for r in ROWS:
        counts[canon_class(r["cls"])] = counts.get(canon_class(r["cls"]), 0) + 1
    for k, v in sorted(counts.items()):
        print(f"  {v:3d}  {k}")
