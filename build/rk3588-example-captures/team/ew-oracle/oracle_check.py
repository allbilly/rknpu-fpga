#!/usr/bin/env python3
"""Independent EW oracle validation for the prepared RK3588 capture families.

This script deliberately does NOT import or reuse the preparation agents'
generators/validators, and it does not trust expected.bin.  It decodes the
command stream, decodes the input BO bytes, recomputes the result from the
original source semantics, and compares bit-for-bit.

Oracles used
------------
FP16 ADD/SUB/MUL/MAX/NEG:
    /home/fedora/rknpu-fpga/model/half.py::alu  (binary16, captured RK quirks)
    NEG is decoded as EW_OP_TYPE=MUL with the B weight -1.0, which is the
    source's own NEG datapath; no separate arithmetic path is invented.
FP16 FDIV:
    exact rational a/b rounded to binary16 with round-to-nearest, ties-to-even.
    That rule is validated against every lane of the real captured 32-lane
    finite sweep and against the finite lanes of the real special capture.
INT (INT8/INT16/INT32):
    the source examples' integer_expected semantics with dtype saturation.
    INT32 MUL additionally applies the source-captured signed-INT16 operand
    rule; that is candidate behavior, not a documented ABI.

Writes only under build/rk3588-example-captures/team/ew-oracle/.
No device access, no ssh/scp, no RTL simulation.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import platform
import struct
import sys
from fractions import Fraction
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
BUILD = REPO / "build"
CAP = BUILD / "rk3588-example-captures"
OUTDIR = CAP / "team/ew-oracle"
FP16_DIR = CAP / "ew-fp16"
INT_DIR = CAP / "ew-int"
HALF_PY = REPO / "model/half.py"
SWEEP = BUILD / "rk3588-kernel-comparison-v1/real-rocket-fdiv8-finite-sweep/capture.json"
SPECIAL = BUILD / "rk3588-kernel-comparison-v1/real-rocket-fdiv8-special/capture.json"
SRC_EW = Path("/home/fedora/rk3588/examples/elementwise.py")
SRC_ADD = Path("/home/fedora/rk3588/examples/simple_add.py")
SRC_DONOR = Path("/home/fedora/rk3588/experimental/kernel_6_18/elementwise.py")
SRC_INT_KERNEL = Path("/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py")
SRC_INT_EXPT = Path("/home/fedora/rk3588/examples/expt/elementwise_int.py")

TARGET_DPU = 0x1001
TARGET_RDMA = 0x2001
TARGET_PC = 0x0081
TARGET_PC_REG = 0x0101
TARGET_VERSION = 0x0041

PRECISION_INT8 = 0
PRECISION_INT16 = 1
PRECISION_FP16 = 2
PRECISION_INT32 = 4
ERDMA_SIZE = {1: "INT8", 2: "INT16", 3: "INT32"}
DTYPE_ITEMSIZE = {"INT8": 1, "INT16": 2, "INT32": 4}
DTYPE_LIMITS = {
    "INT8": (-128, 127),
    "INT16": (-32768, 32767),
    "INT32": (-2**31, 2**31 - 1),
}
EW_ALU = {0: "MAX", 1: "MIN", 2: "ADD", 3: "DIV", 4: "MINUS",
          5: "ABS", 6: "NEG", 7: "FLOOR", 8: "CEIL"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_half():
    spec = importlib.util.spec_from_file_location("ew_oracle_half", HALF_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HALF = load_half()


def bits_from_half_file(path: Path, count: int) -> list[int]:
    raw = path.read_bytes()
    if len(raw) < 2 * count:
        raise ValueError(f"{path} too short for {count} halfwords")
    return list(struct.unpack("<%dH" % count, raw[: 2 * count]))


def f16_bits_to_fraction(bits: int) -> Fraction:
    sign = -1 if bits >> 15 else 1
    exp = (bits >> 10) & 0x1F
    frac = bits & 0x3FF
    if exp == 0x1F:
        raise ValueError("non-finite operand")
    if exp == 0:
        return sign * Fraction(frac, 1 << 24)
    return sign * Fraction(1024 + frac, 1024) * Fraction(2) ** (exp - 15)


def is_half_tie(value: Fraction) -> bool:
    """True when the exact finite value is exactly between two binary16s."""
    v = abs(value)
    if v == 0:
        return False
    if v < Fraction(1, 1 << 14):
        scaled = v * (1 << 24)
    else:
        e = v.numerator.bit_length() - v.denominator.bit_length()
        if Fraction(2) ** e > v:
            e -= 1
        while Fraction(2) ** (e + 1) <= v:
            e += 1
        scaled = v / Fraction(2) ** e * 1024
    return scaled - (scaled.numerator // scaled.denominator) == Fraction(1, 2)


def round_nearest_even_half(value: Fraction) -> int:
    """Correct binary16 round-to-nearest, ties-to-even for a finite rational."""
    sign = 0x8000 if value < 0 else 0
    v = abs(value)
    if v == 0:
        return sign
    if v < Fraction(1, 1 << 14):
        scaled = v * (1 << 24)
        n = scaled.numerator // scaled.denominator
        rem = scaled - n
        if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and n % 2):
            n += 1
        if n >= 1024:  # rounded up into the smallest normal
            return sign | 0x0400
        return sign | n
    e = v.numerator.bit_length() - v.denominator.bit_length()
    if Fraction(2) ** e > v:
        e -= 1
    while Fraction(2) ** (e + 1) <= v:
        e += 1
    scaled = v / Fraction(2) ** e * 1024
    n = scaled.numerator // scaled.denominator
    rem = scaled - n
    if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and n % 2):
        n += 1
    if n == 2048:
        n = 1024
        e += 1
    if e > 15:
        return sign | 0x7C00
    return sign | ((e + 15) << 10) | (n - 1024)


def fdiv_bits(a: int, b: int) -> int:
    """Finite FDIV oracle; raises on a non-finite operand or zero divisor.

    Special-value FDIV behavior is deliberately out of scope for this family:
    all nine FDIV bundles use finite operands and a strictly positive divisor.
    """
    if (a & 0x7C00) == 0x7C00 or (b & 0x7C00) == 0x7C00:
        raise ValueError("non-finite FDIV operand")
    if (b & 0x7FFF) == 0:
        raise ValueError("zero FDIV divisor")
    return round_nearest_even_half(f16_bits_to_fraction(a) / f16_bits_to_fraction(b))


def read_qwords(path: Path) -> list[int]:
    raw = path.read_bytes()
    if len(raw) % 8:
        raise ValueError(f"{path} is not a multiple of 8 bytes")
    return list(struct.unpack("<%dQ" % (len(raw) // 8), raw))


def reg_map(qwords: list[int]) -> tuple[dict[tuple[int, int], int], list[str]]:
    regs: dict[tuple[int, int], int] = {}
    issues: list[str] = []
    for q in qwords:
        target = (q >> 48) & 0xFFFF
        value = (q >> 16) & 0xFFFFFFFF
        offset = q & 0xFFFF
        key = (target, offset)
        if key in regs and regs[key] != value:
            issues.append(
                f"conflicting duplicate write target=0x{target:04x} "
                f"offset=0x{offset:04x}: 0x{regs[key]:08x} then 0x{value:08x}"
            )
        regs[key] = value
    return regs, issues


def decode_fp16_op(ew_cfg: int) -> str:
    if ew_cfg & (1 << 2):
        return "MUL"  # covers the source's NEG path (weight -1.0)
    algo = (ew_cfg >> 16) & 0x7
    if algo == 0:
        return "MAX"
    if algo == 2:
        return "ADD"
    if algo == 3:
        return "FDIV"
    if algo == 4:
        return "SUB"
    raise ValueError(f"unhandled FP16 EW_CFG 0x{ew_cfg:08x} (ALU {algo})")


def int_from_bytes(raw: bytes, off: int, itemsize: int) -> int:
    return int.from_bytes(raw[off: off + itemsize], "little", signed=True)


def sat(value: int, dtype: str) -> int:
    lo, hi = DTYPE_LIMITS[dtype]
    return lo if value < lo else hi if value > hi else value


def pack_c1wc2_positions(width: int, channels: int, itemsize: int):
    """Yield (logical_index, byte_offset) for the source pack_c1wc2 layout."""
    atom = 16 // itemsize
    for w in range(width):
        for c in range(channels):
            surface = c // atom
            slot = c % atom
            index = ((surface * width) + w) * atom + slot
            yield w * channels + c, index * itemsize


def unpack_c1wc2(raw: bytes, width: int, channels: int, itemsize: int) -> list[int]:
    atom = 16 // itemsize
    out = [0] * (width * channels)
    for logical, off in pack_c1wc2_positions(width, channels, itemsize):
        out[logical] = int_from_bytes(raw, off, itemsize)
    return out


def source_int_values(dtype: str, width: int, channels: int, kind: str):
    """The exact DTYPES values / lane formulas the source examples submit."""
    kernel = {
        "INT8": ([-100, -24, -7, -1, 0, 1, 24, 100], [20, -6, 2, -1, 1, 2, -3, 5]),
        "INT16": ([-30000, -1200, -7, -1, 0, 1, 1200, 30000],
                  [1000, -30, 2, -1, 1, 2, -30, 1000]),
        "INT32": ([-1000, -2000, -7, -1, 0, 1, 2000, 1000],
                  [50000, -50000, 2, -1, 1, 2, -50000, 50000]),
    }
    if kind == "simple":
        return kernel[dtype]
    if kind == "mul":
        # The generator deliberately replaces the source DTYPES vectors for the
        # INT8/INT16 MUL probes so the products stay inside range (documented).
        return ([-8, -6, -4, -2, -1, 0, 1, 3], [3, -2, 5, -1, 1, 7, 2, 4])
    lane = [w * channels + c for w in range(width) for c in range(channels)]
    a = [((i * 17 + 3) % 101 - 50) for i in lane]
    b = [((i * 11 + 7) % 31 - 15) for i in lane]
    return a, b


def integer_expected(op: str, a: list[int], b: list[int], dtype: str) -> list[int]:
    if op == "MAX":
        return [max(x, y) for x, y in zip(a, b)]
    if op == "MIN":
        return [min(x, y) for x, y in zip(a, b)]
    if op == "ADD":
        return [sat(x + y, dtype) for x, y in zip(a, b)]
    if op == "MINUS":
        return [sat(x - y, dtype) for x, y in zip(a, b)]
    if op == "MUL":
        if dtype == "INT32":
            # source-captured limitation: the EW MUL operand is signed INT16
            b = [((y & 0xFFFF) - 65536 if (y & 0xFFFF) >= 32768 else (y & 0xFFFF))
                 for y in b]
        return [sat(x * y, dtype) for x, y in zip(a, b)]
    raise ValueError(f"unsupported integer oracle op {op}")


def compare_lanes(case: str, expected_bits: list[int], oracle_bits: list[int],
                  a_bits: list[int], b_bits: list[int]) -> list[dict]:
    mismatches = []
    for lane, (e, o) in enumerate(zip(expected_bits, oracle_bits)):
        if e != o:
            mismatches.append({
                "case": case,
                "lane": lane,
                "a_bits": f"0x{a_bits[lane]:04x}" if lane < len(a_bits) else None,
                "b_bits": f"0x{b_bits[lane]:04x}" if lane < len(b_bits) else None,
                "expected_bits": f"0x{e:04x}",
                "oracle_bits": f"0x{o:04x}",
            })
    return mismatches


# ---------------------------------------------------------------- FP16 family

def fp16_case(case_dir: Path, entry: dict) -> dict:
    name = entry["case"]
    qs = read_qwords(case_dir / "regcmd.bin")
    regs, dup_issues = reg_map(qs)
    dpu_width = regs[(TARGET_DPU, 0x4030)]
    rdma_width = regs[(TARGET_RDMA, 0x500C)]
    ew_cfg = regs[(TARGET_DPU, 0x4070)]
    op = decode_fp16_op(ew_cfg)
    out_convert = regs.get((TARGET_DPU, 0x4084))
    rdma_mode = regs.get((TARGET_RDMA, 0x5044))
    cfg_table = {
        "ADD": (0x108202C0, 0x00010001, 0x00017849),
        "SUB": (0x108402C0, 0x00010001, 0x00017849),
        "MUL": (0x108003C4, 0x00010001, 0x00017849),
        "MAX": (0x108002C0, 0x00010001, 0x00017849),
        "FDIV": (0x108303C0, 0x00000001, 0x00017841),
    }
    want_cfg, want_cvt, want_rdma = cfg_table[op]
    cfg_ok = (ew_cfg, out_convert, rdma_mode) == (want_cfg, want_cvt, want_rdma)
    padded = 8 * (dpu_width + 1)
    n = entry["logical_count"]
    expected_raw = (case_dir / "expected.bin").read_bytes()

    a_raw = (case_dir / "a.bin").read_bytes()
    b_raw = (case_dir / "b.bin").read_bytes()
    a_bits = list(struct.unpack("<%dH" % padded, a_raw[: 2 * padded]))
    b_bits = list(struct.unpack("<%dH" % padded, b_raw[: 2 * padded]))

    # extents / fill
    issues = list(dup_issues)
    if not cfg_ok:
        issues.append(
            f"per-op register config mismatch: ew_cfg=0x{ew_cfg:08x} "
            f"out_convert={out_convert} rdma_mode={rdma_mode} "
            f"expected (0x{want_cfg:08x}, 0x{want_cvt:08x}, 0x{want_rdma:08x})")
    if dpu_width != rdma_width:
        issues.append(f"DPU/RDMA width mismatch {dpu_width} != {rdma_width}")
    if n > padded:
        issues.append(f"logical N={n} exceeds padded={padded}")
    if len(expected_raw) != 2 * n:
        issues.append(f"expected.bin is {len(expected_raw)} bytes, expected {2*n}")
    for label, raw in (("a.bin", a_raw), ("b.bin", b_raw)):
        if any(raw[2 * padded:]):
            issues.append(f"{label} has nonzero bytes after {2*padded}")
    for lane in range(n, padded):
        if a_bits[lane] != 0x0000:
            issues.append(f"a padded lane {lane} is 0x{a_bits[lane]:04x}, not +0")
        want_b = 0x3C00 if op == "FDIV" else 0x0000
        if b_bits[lane] != want_b:
            issues.append(f"b padded lane {lane} is 0x{b_bits[lane]:04x}, not 0x{want_b:04x}")

    # expected values, logical lanes only
    expected_bits = list(struct.unpack("<%dH" % n, expected_raw[: 2 * n]))
    oracle_bits = []
    inexact_result_lanes = 0
    for lane in range(n):
        a, b = a_bits[lane], b_bits[lane]
        if op == "FDIV":
            oracle_bits.append(fdiv_bits(a, b))
            exact = f16_bits_to_fraction(a) / f16_bits_to_fraction(b)
        else:
            oracle_bits.append(HALF.alu(a, b, op))
            if op == "ADD":
                exact = f16_bits_to_fraction(a) + f16_bits_to_fraction(b)
            elif op == "SUB":
                exact = f16_bits_to_fraction(a) - f16_bits_to_fraction(b)
            elif op == "MUL":
                exact = f16_bits_to_fraction(a) * f16_bits_to_fraction(b)
            else:
                exact = None
        if exact is not None and f16_bits_to_fraction(oracle_bits[-1]) != exact:
            inexact_result_lanes += 1

    # donor-numpy cross-check (the path the preparation agent documented)
    import numpy as np

    def donor() -> list[int]:
        af = np.frombuffer(struct.pack("<%dH" % n, *a_bits[:n]), dtype="<f2").astype(np.float32)
        bf = np.frombuffer(struct.pack("<%dH" % n, *b_bits[:n]), dtype="<f2").astype(np.float32)
        with np.errstate(all="ignore"):
            if op == "ADD":
                r = af + bf
            elif op == "SUB":
                r = af - bf
            elif op == "MUL":
                r = af * bf
            elif op == "MAX":
                r = np.maximum(af, bf)
            elif op == "FDIV":
                r = af / bf
            else:
                raise ValueError(op)
        return list(r.astype(np.float16).view(np.uint16))

    donor_bits = donor()
    donor_delta = [
        {"lane": i, "donor_bits": f"0x{d:04x}", "oracle_bits": f"0x{o:04x}"}
        for i, (d, o) in enumerate(zip(donor_bits, oracle_bits)) if d != o
    ]

    # input pattern fidelity against the documented closed forms
    idx = list(range(n))
    if entry["pattern"] == "p1":
        want_a = [HALF.to_bits(float(i + 1)) for i in idx]
        want_b = [HALF.to_bits(float(8 - (i % 8))) for i in idx]
    else:
        want_a = [HALF.to_bits((i % 11 - 5) * 0.5) for i in idx]
        want_b = [HALF.to_bits((i % 7 + 1) * 0.5) for i in idx]
    if entry.get("op") == "NEG":
        want_b = [0xBC00] * n
    elif op == "MUL" and entry.get("op") == "NEG":
        want_b = [0xBC00] * n
    if a_bits[:n] != want_a:
        bad = [(i, f"0x{a_bits[i]:04x}", f"0x{want_a[i]:04x}")
               for i in range(n) if a_bits[i] != want_a[i]][:8]
        issues.append(f"a pattern mismatch: {bad}")
    if b_bits[:n] != want_b:
        bad = [(i, f"0x{b_bits[i]:04x}", f"0x{want_b[i]:04x}")
               for i in range(n) if b_bits[i] != want_b[i]][:8]
        issues.append(f"b pattern mismatch: {bad}")

    mismatches = compare_lanes(name, expected_bits, oracle_bits,
                               a_bits[:n], b_bits[:n])
    return {
        "case": name,
        "op_decoded": op,
        "manifest_op": entry.get("op"),
        "pattern": entry.get("pattern"),
        "logical_count": n,
        "padded_count": padded,
        "width": dpu_width,
        "expected_bytes": len(expected_raw),
        "mismatches": mismatches,
        "donor_numpy_deltas": donor_delta,
        "issues": issues,
        "lane_zero_operand": [
            i for i in range(n) if a_bits[i] == 0x0000 or b_bits[i] == 0x0000],
        "lane_signed_zero": [
            i for i in range(n) if (a_bits[i] & 0x7FFF) == 0 and (a_bits[i] >> 15)
            or (b_bits[i] & 0x7FFF) == 0 and (b_bits[i] >> 15)],
        "lane_negative": [
            i for i in range(n) if (a_bits[i] >> 15) or (b_bits[i] >> 15)],
        "lane_exact_cancel": [
            i for i in range(n)
            if HALF.from_bits(a_bits[i]) == HALF.from_bits(b_bits[i])
            and (a_bits[i] & 0x7FFF) != 0],
        "lane_subnormal_operand": [
            i for i in range(n)
            if 0 < (a_bits[i] & 0x7FFF) < 0x0400
            or 0 < (b_bits[i] & 0x7FFF) < 0x0400],
        "lane_subnormal_result": [
            i for i in range(n) if 0 < (oracle_bits[i] & 0x7FFF) < 0x0400],
        "lane_overflow_result": [
            i for i in range(n) if (oracle_bits[i] & 0x7FFF) == 0x7C00],
        "lane_nan_result": [
            i for i in range(n) if (oracle_bits[i] & 0x7C00) == 0x7C00
            and (oracle_bits[i] & 0x03FF)],
        "zero_result": [
            i for i in range(n) if (oracle_bits[i] & 0x7FFF) == 0],
        "zero_result_bits": [
            {"lane": i, "expected_bits": f"0x{expected_bits[i]:04x}",
             "oracle_bits": f"0x{oracle_bits[i]:04x}"}
            for i in range(n) if (oracle_bits[i] & 0x7FFF) == 0],
        "command_config_ok": cfg_ok,
        "inexact_result_lanes": inexact_result_lanes,
    }


# ----------------------------------------------------------------- INT family

def int_case(case_dir: Path, entry: dict) -> dict:
    name = entry["case"]
    qs = read_qwords(case_dir / "regcmd.bin")
    regs, dup_issues = reg_map(qs)
    issues = list(dup_issues)

    fmt = regs[(TARGET_DPU, 0x4010)]
    in_prec = (fmt >> 26) & 0x7
    out_prec = (fmt >> 29) & 0x7
    dtype = {0: "INT8", 1: "INT16", 4: "INT32"}.get(in_prec)
    out_dtype = {0: "INT8", 1: "INT16", 4: "INT32"}.get(out_prec)
    ew_cfg = regs[(TARGET_DPU, 0x4070)]
    if ew_cfg & (1 << 2):
        op = "MUL"
    else:
        op = {0: "MAX", 1: "MIN", 2: "ADD", 3: "DIV", 4: "MINUS"}.get(
            (ew_cfg >> 16) & 0x7, "UNKNOWN")
    channels = (regs[(TARGET_DPU, 0x403C)] & 0x1FFF) + 1
    width = regs[(TARGET_DPU, 0x4030)] + 1
    if width * channels != entry["shape"]["width"] * entry["shape"]["channels"]:
        issues.append("decoded width*channels disagrees with manifest shape")
    itemsize = DTYPE_ITEMSIZE[dtype]
    atom = 16 // itemsize
    layout = len(qs) in (31, 44) or (TARGET_DPU, 0x4024) in regs or \
        (TARGET_DPU, 0x40C0) in regs

    a_raw = (case_dir / "a.bin").read_bytes()
    b_raw = (case_dir / "b.bin").read_bytes()
    expected_raw = (case_dir / "expected.bin").read_bytes()
    mask_raw = (case_dir / "expected.mask.bin").read_bytes()

    if out_dtype != dtype and not (dtype == "INT16" and out_dtype == "INT32"):
        issues.append(f"input/output dtype pair {dtype}->{out_dtype} unexpected")
    if out_dtype == "INT32" and dtype == "INT16":
        # INT16 -> INT32 writeback: plain INT16 inputs, 8 INT32 results.
        count = width * channels
        a = [int_from_bytes(a_raw, i * 2, 2) for i in range(count)]
        b = [int_from_bytes(b_raw, i * 2, 2) for i in range(count)]
        src_a, src_b = source_int_values("INT16", 1, 8, "simple")
        if a != src_a or b != src_b:
            issues.append("INT16->INT32 inputs are not the source DTYPES values")
        result = [sat(x + y, "INT32") for x, y in zip(a, b)]
        out_bytes = b"".join(struct.pack("<i", v) for v in result)
        asserted = list(range(len(result) * 4))
    elif layout:
        count = width * channels
        a = unpack_c1wc2(a_raw, width, channels, itemsize)
        b = unpack_c1wc2(b_raw, width, channels, itemsize)
        src_a, src_b = source_int_values(dtype, width, channels, "layout")
        if a != src_a or b != src_b:
            bad = [(i, a[i], src_a[i]) for i in range(count) if a[i] != src_a[i]][:8]
            badb = [(i, b[i], src_b[i]) for i in range(count) if b[i] != src_b[i]][:8]
            issues.append(f"layout input mismatch a={bad} b={badb}")
        result = integer_expected(op, a, b, dtype)
        surfaces = (channels + atom - 1) // atom
        packed = [0] * (surfaces * width * atom)
        for logical, off in pack_c1wc2_positions(width, channels, itemsize):
            packed[off // itemsize] = result[logical]
        out_bytes = b"".join(
            struct.pack("<b" if itemsize == 1 else "<h" if itemsize == 2 else "<i", v)
            for v in packed)
        asserted = sorted({off + k
                           for _, off in pack_c1wc2_positions(width, channels, itemsize)
                           for k in range(itemsize)})
    else:
        count = width * channels
        a = [int_from_bytes(a_raw, i * itemsize, itemsize) for i in range(count)]
        b = [int_from_bytes(b_raw, i * itemsize, itemsize) for i in range(count)]
        kind = "mul" if (op == "MUL" and dtype != "INT32") else "simple"
        src_a, src_b = source_int_values(dtype, width, channels, kind)
        if a != src_a or b != src_b:
            bad = [(i, a[i], src_a[i]) for i in range(count) if a[i] != src_a[i]][:8]
            badb = [(i, b[i], src_b[i]) for i in range(count) if b[i] != src_b[i]][:8]
            issues.append(f"simple input mismatch a={bad} b={badb}")
        result = integer_expected(op, a, b, dtype)
        out_bytes = b"".join(
            struct.pack("<b" if itemsize == 1 else "<h" if itemsize == 2 else "<i", v)
            for v in result)
        asserted = list(range(len(result) * itemsize))

    # compare expected/mask
    expected_first = expected_raw[: len(out_bytes)]
    oracle_first = out_bytes
    byte_mismatches = []
    for i, (e, o) in enumerate(zip(expected_first, oracle_first)):
        if e != o:
            byte_mismatches.append({
                "case": name,
                "byte": i,
                "lane": asserted.index(i) // itemsize if i in asserted else None,
                "expected_byte": f"0x{e:02x}",
                "oracle_byte": f"0x{o:02x}",
            })
    mask_asserted = {i for i, v in enumerate(mask_raw) if v}
    bad_mask_values = sorted({v for v in mask_raw if v not in (0x00, 0xFF)})
    if bad_mask_values:
        issues.append(f"mask contains values other than 0x00/0xFF: {bad_mask_values}")
    if mask_asserted != set(asserted):
        issues.append(
            f"mask bytes differ from independently derived asserted set: "
            f"extra={sorted(mask_asserted - set(asserted))[:8]} "
            f"missing={sorted(set(asserted) - mask_asserted)[:8]}")
    outside = [i for i in range(len(expected_raw))
               if i not in set(asserted) and expected_raw[i] != 0]
    if outside:
        issues.append(f"expected.bin has nonzero unasserted bytes at {outside[:8]}")
    if len(mask_raw) != 4096 or len(expected_raw) != 4096:
        issues.append("expected.bin/expected.mask.bin sizes are not 4096")

    # operand coverage facts
    if op == "MUL":
        model_b = b if dtype != "INT32" else [
            ((y & 0xFFFF) - 65536 if (y & 0xFFFF) >= 32768 else (y & 0xFFFF))
            for y in b]
        pre_sat = [x * y for x, y in zip(a, model_b)]
    elif op == "ADD":
        pre_sat = [x + y for x, y in zip(a, b)]
    elif op == "MINUS":
        pre_sat = [x - y for x, y in zip(a, b)]
    else:
        pre_sat = list(result)
    lo, hi = DTYPE_LIMITS[dtype]
    zero_operand = [i for i in range(len(a)) if a[i] == 0 or b[i] == 0]
    neg_operand = [i for i in range(len(a)) if a[i] < 0 or b[i] < 0]
    saturation_lanes = [i for i, v in enumerate(pre_sat) if v < lo or v > hi]
    value_changed_by_sat = [
        i for i, v in enumerate(pre_sat) if result[i] != v]
    int16_operand_delta = []
    if op == "MUL" and dtype == "INT32":
        int16_operand_delta = [
            {"lane": i, "b": b[i], "b_s16": model_b[i],
             "full_int32_product": a[i] * b[i],
             "model_product": pre_sat[i]}
            for i in range(len(a))]

    return {
        "case": name,
        "dtype_decoded": dtype,
        "out_dtype_decoded": out_dtype,
        "op_decoded": op,
        "width": width,
        "channels": channels,
        "itemsize": itemsize,
        "layout": "layout" if layout else "contiguous",
        "expected_bytes": len(expected_raw),
        "asserted_bytes": len(asserted),
        "oracle_bytes": len(out_bytes),
        "mismatches": byte_mismatches,
        "issues": issues,
        "zero_operand_lanes": zero_operand,
        "negative_operand_lanes": neg_operand,
        "pre_saturation_values": pre_sat,
        "saturation_lanes": saturation_lanes,
        "value_changed_by_saturation": value_changed_by_sat,
        "manifest_special_values": entry.get("special_values"),
        "int32_mul_int16_operand_delta": int16_operand_delta,
    }


# ------------------------------------------------------------------- driver

def main() -> int:
    import numpy as np

    started = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    result = {
        "schema": "ew-oracle/v1",
        "generated_utc": started.isoformat().replace("+00:00", "Z"),
        "scope": "independent host-side oracle validation only; no device access, "
                 "no ssh/scp, no submit, no RTL simulation, no program/flash",
        "environment": {
            "python": sys.version.split()[0],
            "python_path": sys.executable,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "method": {
            "half_oracle": str(HALF_PY) + "::alu (binary16; captured RK quirks)",
            "neg": "decoded as EW_OP_TYPE=MUL with B weight -1.0",
            "fdiv": "exact rational quotient rounded to binary16 nearest-even; "
                    "validated against the real captured finite sweep",
            "int": "source integer_expected saturation semantics; INT32 MUL "
                   "applies the source-captured signed-INT16 operand rule",
            "inputs": "decoded from a.bin/b.bin, not from expected.bin; layout "
                      "decoded/repacked with the source C1WC2 rule",
        },
        "sources": {},
        "fdiv_validation": {},
        "families": {},
        "mismatches": [],
        "structural_issues": [],
        "coverage_gaps": [],
        "caveats": [],
    }

    for label, path in [
        ("rknpu-fpga/half.py", HALF_PY),
        ("examples/elementwise.py", SRC_EW),
        ("examples/simple_add.py", SRC_ADD),
        ("experimental/kernel_6_18/elementwise.py", SRC_DONOR),
        ("examples/kernel_6_18/elementwise_int.py", SRC_INT_KERNEL),
        ("examples/expt/elementwise_int.py", SRC_INT_EXPT),
        ("fdiv finite sweep capture", SWEEP),
        ("fdiv special capture", SPECIAL),
        ("ew-fp16 manifest", FP16_DIR / "manifest.json"),
        ("ew-int manifest", INT_DIR / "manifest.json"),
    ]:
        if path.exists():
            result["sources"][label] = {"path": str(path), "sha256": sha256(path),
                                        "bytes": path.stat().st_size}
        else:
            result["sources"][label] = {"path": str(path), "missing": True}

    # FDIV rule evidence
    sweep = json.loads(SWEEP.read_text())
    sweep_detail = []
    bad_sweep = []
    sweep_ties = []
    for lane, (a, b, o) in enumerate(
            zip(sweep["a_bits"], sweep["b_bits"], sweep["out_bits"])):
        got = fdiv_bits(a, b)
        q = f16_bits_to_fraction(a) / f16_bits_to_fraction(b)
        if is_half_tie(q):
            sweep_ties.append({"lane": lane, "a": f"0x{a:04x}",
                               "b": f"0x{b:04x}", "captured": f"0x{o:04x}"})
        sweep_detail.append({
            "lane": lane, "a": f"0x{a:04x}", "b": f"0x{b:04x}",
            "captured": f"0x{o:04x}", "oracle": f"0x{got:04x}",
            "exact_tie": is_half_tie(q),
            "match": got == o})
        if got != o:
            bad_sweep.append({"lane": lane, "a": f"0x{a:04x}",
                              "b": f"0x{b:04x}", "captured": f"0x{o:04x}",
                              "oracle": f"0x{got:04x}"})
    special = json.loads(SPECIAL.read_text())
    special_finite = 0
    special_detail = []
    special_ties = []
    bad_special = []
    for lane, (a, b, o) in enumerate(
            zip(special["a_bits"], special["b_bits"], special["out_bits"])):
        exp_a, exp_b = (a >> 10) & 0x1F, (b >> 10) & 0x1F
        if exp_a == 0x1F or exp_b == 0x1F or (b & 0x7FFF) == 0:
            continue
        special_finite += 1
        got = fdiv_bits(a, b)
        q = f16_bits_to_fraction(a) / f16_bits_to_fraction(b)
        if is_half_tie(q):
            special_ties.append({"lane": lane, "a": f"0x{a:04x}",
                                 "b": f"0x{b:04x}", "captured": f"0x{o:04x}"})
        special_detail.append({
            "lane": lane, "a": f"0x{a:04x}", "b": f"0x{b:04x}",
            "captured": f"0x{o:04x}", "oracle": f"0x{got:04x}",
            "exact_tie": is_half_tie(q),
            "match": got == o})
        if got != o:
            bad_special.append({"lane": lane, "a": f"0x{a:04x}",
                                "b": f"0x{b:04x}", "captured": f"0x{o:04x}",
                                "oracle": f"0x{got:04x}"})
    result["fdiv_validation"] = {
        "finite_sweep_lanes": sweep["lanes"],
        "finite_sweep_match": sweep["lanes"] - len(bad_sweep),
        "finite_sweep_mismatches": bad_sweep,
        "finite_sweep_exact_tie_lanes": sweep_ties,
        "finite_sweep_detail": sweep_detail,
        "special_capture_finite_nonzero_divisor_lanes": special_finite,
        "special_capture_match": special_finite - len(bad_special),
        "special_capture_mismatches": bad_special,
        "special_capture_exact_tie_lanes": special_ties,
        "special_capture_finite_detail": special_detail,
        "rule": "round-to-nearest, ties-to-even of the exact quotient",
        "note": "All 32 finite-sweep and 11 finite special-capture lanes match "
                "exact-rational nearest-even. Six sweep lanes reject truncation "
                "toward zero; eight exact subnormal-range ties (six in the "
                "sweep, two in the special capture) confirm ties-to-even. The "
                "four README 'RK-specific' quotients are correctly rounded "
                "under nearest-even, so that wording is not supported by the "
                "capture.",
    }

    # FP16 family
    fp16_manifest = json.loads((FP16_DIR / "manifest.json").read_text())
    fp16_cases = []
    for entry in fp16_manifest["cases"]:
        if entry["status"] != "READY":
            continue
        fp16_cases.append(fp16_case(FP16_DIR / "cases" / entry["case"], entry))
    result["families"]["ew-fp16"] = {
        "manifest_total": len(fp16_manifest["cases"]),
        "ready": sum(1 for e in fp16_manifest["cases"] if e["status"] == "READY"),
        "checked": len(fp16_cases),
        "case_mismatch_count": sum(len(c["mismatches"]) for c in fp16_cases),
        "cases": fp16_cases,
    }
    for c in fp16_cases:
        result["mismatches"].extend(c["mismatches"])
        for issue in c["issues"]:
            result["structural_issues"].append({"case": c["case"], "issue": issue})
        if c["op_decoded"] != c["manifest_op"] and not (
                c["manifest_op"] == "NEG" and c["op_decoded"] == "MUL"):
            result["structural_issues"].append({
                "case": c["case"],
                "issue": f"decoded op {c['op_decoded']} != manifest {c['manifest_op']}"})

    # INT family
    int_manifest = json.loads((INT_DIR / "manifest.json").read_text())
    int_cases = []
    for entry in int_manifest["cases"]:
        if entry["status"] != "READY":
            continue
        int_cases.append(int_case(INT_DIR / "cases" / entry["case"], entry))
    result["families"]["ew-int"] = {
        "manifest_total": len(int_manifest["cases"]),
        "ready": sum(1 for e in int_manifest["cases"] if e["status"] == "READY"),
        "blocked": sum(1 for e in int_manifest["cases"] if e["status"] == "BLOCKED"),
        "checked": len(int_cases),
        "case_mismatch_count": sum(len(c["mismatches"]) for c in int_cases),
        "cases": int_cases,
    }
    for c in int_cases:
        result["mismatches"].extend(c["mismatches"])
        for issue in c["issues"]:
            result["structural_issues"].append({"case": c["case"], "issue": issue})

    # The README/manifest claim three saturating lanes.  Check the arithmetic.
    claim_lanes = {
        "int8_add_c8_w1": 7,
        "int16_add_c8_w1": 7,
        "int16_minus_c8_w1": 0,
    }
    claim_checks = []
    for c in int_cases:
        if c["case"] not in claim_lanes:
            continue
        lane = claim_lanes[c["case"]]
        pre = c["pre_saturation_values"][lane]
        lo, hi = DTYPE_LIMITS[c["dtype_decoded"]]
        saturates = pre < lo or pre > hi
        claim_checks.append({
            "case": c["case"],
            "lane": lane,
            "pre_saturation_value": pre,
            "dtype": c["dtype_decoded"],
            "limits": [lo, hi],
            "saturates": saturates,
            "manifest_claim": c["manifest_special_values"],
        })
        if not saturates:
            result["structural_issues"].append({
                "case": c["case"],
                "issue": (
                    f"documentation claim is false: manifest/README says lane "
                    f"{lane} saturates, but the decoded operands produce {pre}, "
                    f"which is inside [{lo}, {hi}] for {c['dtype_decoded']}"),
            })
    result["families"]["ew-int"]["saturation_claim_checks"] = claim_checks
    result["families"]["ew-int"]["total_saturation_lanes"] = sum(
        len(c["saturation_lanes"]) for c in int_cases)
    result["families"]["ew-fp16"]["zero_result_signs"] = {
        c["case"]: c["zero_result_bits"] for c in fp16_cases if c["zero_result_bits"]}
    result["families"]["ew-fp16"]["command_config_all_ok"] = all(
        c["command_config_ok"] for c in fp16_cases)
    rounding = {}
    for c in fp16_cases:
        if c["op_decoded"] == "MAX":
            continue
        key = c["op_decoded"]
        entry_r = rounding.setdefault(key, {"lanes": 0, "inexact": 0})
        entry_r["lanes"] += c["logical_count"]
        entry_r["inexact"] += c["inexact_result_lanes"]
    result["families"]["ew-fp16"]["inexact_result_lanes_by_op"] = rounding
    result["families"]["ew-fp16"]["logical_lanes_compared"] = sum(
        c["logical_count"] for c in fp16_cases)
    result["families"]["ew-fp16"]["fdiv_case_count"] = sum(
        1 for c in fp16_cases if c["op_decoded"] == "FDIV")
    result["families"]["ew-int"]["asserted_bytes_compared"] = sum(
        c["asserted_bytes"] for c in int_cases)
    result["commands"] = {
        "oracle_check": "/usr/bin/python3 oracle_check.py",
        "fdiv_sweep_analysis": "/usr/bin/python3 analyze_fdiv_sweep.py",
        "working_directory": str(OUTDIR),
    }
    result["tooling_hashes"] = {
        "oracle_check.py": sha256(Path(__file__)),
        "analyze_fdiv_sweep.py": sha256(OUTDIR / "analyze_fdiv_sweep.py"),
    }
    result["source_revisions"] = {}
    for repo in ("/home/fedora/rknpu-fpga", "/home/fedora/rk3588"):
        try:
            import subprocess
            rev = subprocess.check_output(
                ["git", "-C", repo, "rev-parse", "HEAD"], text=True,
                stderr=subprocess.DEVNULL).strip()
        except Exception:
            rev = "unavailable"
        result["source_revisions"][repo] = rev

    # verify every manifest-pinned case file hash against the bytes on disk
    hash_checks = {"ew-fp16": {"checked": 0, "failed": []},
                   "ew-int": {"checked": 0, "failed": []}}
    for entry in fp16_manifest["cases"]:
        if entry["status"] != "READY":
            continue
        for fname, meta in entry["bundle"].items():
            path = FP16_DIR / "cases" / entry["case"] / fname
            ok = path.exists() and path.stat().st_size == meta["bytes"] and \
                sha256(path) == meta["sha256"]
            hash_checks["ew-fp16"]["checked"] += 1
            if not ok:
                hash_checks["ew-fp16"]["failed"].append(
                    f"{entry['case']}/{fname}")
    for entry in int_manifest["cases"]:
        if entry["status"] != "READY":
            continue
        for fname, want in entry["hashes"].items():
            path = INT_DIR / "cases" / entry["case"] / fname
            ok = path.exists() and sha256(path) == want
            hash_checks["ew-int"]["checked"] += 1
            if not ok:
                hash_checks["ew-int"]["failed"].append(
                    f"{entry['case']}/{fname}")
    result["bundle_hash_verification"] = hash_checks
    for fam, rec in hash_checks.items():
        for failed in rec["failed"]:
            result["structural_issues"].append({
                "case": failed.split("/")[0],
                "issue": f"{fam} manifest hash mismatch for {failed}"})


    result["covered_points"] = [
        {
            "family": "ew-int",
            "point": "INT32 MUL signed-INT16 operand is exercised",
            "detail": "lanes 0,1,6,7 carry b=50000/-50000; they decode as "
                      "-15536/+15536 and the oracle products are "
                      "15,536,000 / -31,072,000 / 31,072,000 / -15,536,000. "
                      "All four differ from the full-int32 product. Candidate "
                      "behavior, not a documented ABI.",
        },
        {
            "family": "ew-int",
            "point": "layout tail channel is exercised",
            "detail": "the 9-channel layout cases assert the tail lane in the "
                      "second/third 16-byte surface (INT8 9/16, INT16 18/32, "
                      "INT32 36/48 asserted bytes).",
        },
        {
            "family": "ew-fp16",
            "point": "FDIV finite rounding is exercised",
            "detail": "9 finite FDIV cases compare 1132 lanes, 413 of them "
                      "inexact; the exact-rational nearest-even oracle also "
                      "reproduces all 32 captured finite-sweep lanes and the 11 "
                      "finite lanes of the special capture.",
        },
        {
            "family": "ew-fp16",
            "point": "exact cancellation and signed zero result",
            "detail": "ADD p2 has +0 results at lanes 2/11; SUB p2 n33 has a "
                      "run of five exact cancellations at lanes 28..32; NEG p2 "
                      "produces -0.0 (0x8000) at lanes 5/16/27.",
        },
        {
            "family": "ew-fp16",
            "point": "MAX tie at p2 lane 28 (n=33)",
            "detail": "A=B=0.5; the oracle and bundle return 0x3800. No signed-"
                      "zero or NaN MAX ordering is covered.",
        },
    ]
    # coverage gaps (stated explicitly, computed facts above support them)
    result["coverage_gaps"] = [
        {
            "family": "ew-fp16",
            "gap": "no Inf/NaN operands or results in any case",
            "detail": "finite-only family; NaN canonicalization and the SUB "
                      "infinity quirk are not exercised.",
        },
        {
            "family": "ew-fp16",
            "gap": "no subnormal inputs or subnormal/underflow results",
            "detail": "smallest magnitudes are 0.125 (1/8) and 0.5; no lane "
                      "reaches the 2^-14 normal boundary or 2^-24 subnormal unit.",
        },
        {
            "family": "ew-fp16",
            "gap": "no overflow/Inf result, no signed-zero operand",
            "detail": "largest result is 8192; only +0 appears (p2 A and "
                      "padded lanes), no -0 operand for MAX/sign-of-zero policy.",
        },
        {
            "family": "ew-fp16",
            "gap": "physical 8-lane padding lanes are never asserted",
            "detail": "N=1,7,9,33 cases process 8/16/40 lanes but expected.bin "
                      "covers only N. A tail lane-shift or padded-lane write bug "
                      "is invisible; recommended assertion is +0 for non-FDIV "
                      "padded lanes and +0 for FDIV 0/1 lanes.",
        },
        {
            "family": "ew-fp16",
            "gap": "ADD/SUB never round; MUL/FDIV rounding is sparse",
            "detail": "all 1132 ADD and 1132 SUB lane results are exactly "
                      "representable binary16. MUL (incl. NEG) has 98 inexact "
                      "lanes of 2264; FDIV has 413 inexact of 1132. No round-half "
                      "tie is constructed on purpose.",
        },
        {
            "family": "ew-fp16",
            "gap": "MAX has no unsigned/encoded-magnitude edge and no NaN tie",
            "detail": "MAX lanes are positive-vs-positive or negative-vs-positive; "
                      "the equal pair at p2 lane 28 is the only tie, and no -0/+0 "
                      "ordering case exists.",
        },
        {
            "family": "ew-fp16",
            "gap": "FDIV rounding evidence is only 32 finite sweep lanes",
            "detail": "nearest-even and eight subnormal exact ties are "
                      "confirmed, but only 32 captured lanes exist; no "
                      "normal-range exact tie, no quotient just above the "
                      "subnormal/normal boundary, and no flush-to-zero policy "
                      "test.",
        },
        {
            "family": "ew-fp16",
            "gap": "logical N is metadata, not encoded in regcmd",
            "detail": "only padded=8*(width+1) is in the command stream; N comes "
                      "from manifest/expected.bin length. A worker cannot infer N "
                      "from the device command alone.",
        },
        {
            "family": "ew-int",
            "gap": "no saturation/overflow lane exists anywhere in the family",
            "detail": "the manifest claims three saturating lanes, but all three "
                      "are inside range: INT8 lane 7 is 100+5=105 in [-128,127], "
                      "INT16 lane 7 is 30000+1000=31000 in [-32768,32767], "
                      "INT16 lane 0 is -30000-1000=-31000 in range. INT8/INT16 "
                      "MUL use small operands; INT32 MUL products are ~5e7, far "
                      "below 2^31. The saturation policy is therefore entirely "
                      "untested despite the documentation.",
        },
        {
            "family": "ew-int",
            "gap": "no exact saturation boundary or signed-overflow edge",
            "detail": "no +127/+128/-128/-129, +/-32767/+/-32768, and no "
                      "INT32 2^31-1/2^31 boundary; no INT32_MIN operand; no "
                      "double-overflow (e.g. 100+100) lane.",
        },
        {
            "family": "ew-int",
            "gap": "INT32 MUL full-width semantics are only rejected, not measured",
            "detail": "the bundle asserts the signed-INT16 operand model "
                      "(50000 -> -15536, -50000 -> 15536). A full INT32 operand "
                      "would produce different results, so a device mismatch is "
                      "informative candidate behavior, not a bundle bug. No "
                      "b=0x8000/-32768 lane and no product exactly on 2^31-1 or "
                      "-2^31 is included.",
        },
        {
            "family": "ew-int",
            "gap": "INT8/INT16 MUL reuse one small operand vector",
            "detail": "both MUL cases submit the same MUL_A_8/MUL_B_8 values "
                      "(-8,-6,... / 3,-2,...), replacing the source DTYPES "
                      "vectors. No MUL saturation or signed-product boundary is "
                      "exercised for INT8 or INT16.",
        },
        {
            "family": "ew-int",
            "gap": "INT32 layout 9-channel stream is offline-only in the source",
            "detail": "the source never claims a device pass for that exact "
                      "combination; a device mismatch there is an open question.",
        },
        {
            "family": "ew-int",
            "gap": "surface/BO padding is unasserted",
            "detail": "INT8 asserted 8 of 16 surface bytes, INT8 layout 9 of 16, "
                      "INT16 layout 18 of 32, INT32 layout 36 of 48. A padding "
                      "corruption or a surface-stride bug in unused slots is "
                      "invisible by design.",
        },
        {
            "family": "ew-int",
            "gap": "missing operations and dtypes",
            "detail": "no INT32 MIN/MINUS, no INT8/INT16 MIN beyond one INT8 case, "
                      "no INT8 MINUS, no ABS/NEG/FLOOR/CEIL; DIV/FLOOR/CEIL are "
                      "proven floating-point and correctly BLOCKED.",
        },
    ]
    result["caveats"] = [
        "All expected.bin files are host oracles, never device outputs; these "
        "checks only validate bundle consistency and source fidelity.",
        "model/half.py is an independent binary16 model that also encodes "
        "captured RK quirks (NaN 0x7c01, ADD/SUB zero -> +0, SUB infinity rule, "
        "MAX signed-zero ordering). It is not an RK silicon specification.",
        "The FP16 input patterns p1/p2 are deterministic preparation-time "
        "closed forms, not the source examples' seeded np.random.uniform data; "
        "the arithmetic formula is the source donor formula, the operands are "
        "not.",
        "INT saturation is candidate behavior: it follows the source's "
        "integer_expected clip(), but no bundled lane actually overflows, so "
        "the capture cannot establish the device's saturation policy.",
        "INT32 MUL signed-INT16 operand is a source-captured limitation and "
        "candidate behavior, not a documented ABI.",
        "The FDIV oracle is exact-rational nearest-even; the real sweep covers "
        "32 lanes and the special capture 11 finite lanes with nonzero divisor, "
        "including eight exact subnormal-range ties. Normal-range exact ties "
        "and the full rounding space are not covered.",
        "No local RTL, Verilator, FPGA or RK3588 execution was used or is "
        "claimed; C++/RTL results would not be device evidence anyway.",
        "No ssh/scp/192.168.192.18 access, no submit, no program or flash.",
    ]

    OUTDIR.mkdir(parents=True, exist_ok=True)
    result["summary"] = {
        "ew-fp16": {
            "ready": result["families"]["ew-fp16"]["ready"],
            "checked": result["families"]["ew-fp16"]["checked"],
            "logical_lanes_compared":
                result["families"]["ew-fp16"]["logical_lanes_compared"],
            "mismatches": result["families"]["ew-fp16"]["case_mismatch_count"],
        },
        "ew-int": {
            "ready": result["families"]["ew-int"]["ready"],
            "blocked": result["families"]["ew-int"]["blocked"],
            "checked": result["families"]["ew-int"]["checked"],
            "asserted_bytes_compared":
                result["families"]["ew-int"]["asserted_bytes_compared"],
            "mismatches": result["families"]["ew-int"]["case_mismatch_count"],
        },
        "total_case_mismatches": len(result["mismatches"]),
        "structural_issues": len(result["structural_issues"]),
        "coverage_gaps": len(result["coverage_gaps"]),
        "device_evidence": False,
    }
    out = OUTDIR / "ORACLE.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {out}")
    print(f"fp16 checked={len(fp16_cases)} mismatches="
          f"{result['families']['ew-fp16']['case_mismatch_count']}")
    print(f"int  checked={len(int_cases)} mismatches="
          f"{result['families']['ew-int']['case_mismatch_count']}")
    print(f"structural issues={len(result['structural_issues'])}")
    for issue in result["structural_issues"][:20]:
        print("  ISSUE", issue)
    for m in result["mismatches"][:20]:
        print("  MISMATCH", m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
