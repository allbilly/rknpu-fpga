#!/usr/bin/env python3
"""Generate the convolution architecture matrix from the capture manifests.

Read-only over the capture trees. No device, board or RTL execution.
Usage:
    /usr/bin/python3 generate_matrix.py [--captures DIR] [--output FILE]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FAMILIES = ("conv-simple", "conv-fp16", "conv-gemm-vendor")

# Every conv entry in the three manifests. GEMM entries in conv-gemm-vendor are
# deliberately excluded; they are not convolution cases.
CASES = {
    # conv-simple
    "conv_simple_fp16_1x1_c4_h8_w8_oc16": dict(
        gate="1B", cls="M1_FP32_OC16", first_engine=True,
        requires=["1x1", "valid", "g1", "fp16", "c<=32", "oc<=16", "fp32_out"],
        note="NHWC C4; full OC16 block; requires FP32 atom writer; exact RK capture.",
    ),
    "conv_simple_fp16_3x3_c4_h8_w8_oc16": dict(
        gate="3", cls="SPATIAL_VALID", first_engine=False,
        requires=["spatial", "3x3", "line_buffer", "nc1hwc2"],
        note="3x3 valid, C4/OC16, FP16 out.",
    ),
    "conv_simple_fp16_5x5_c4_h8_w8_oc16": dict(
        gate="3", cls="SPATIAL_VALID", first_engine=False,
        requires=["spatial", "5x5", "line_buffer", "nc1hwc2"],
        note="5x5 valid, C4/OC16; not in donor LIST_SHAPES but READY register stream.",
    ),
    "conv_simple_fp16_1x1_c32_h8_w8_oc32": dict(
        gate="1B", cls="M1_FP32_OC32", first_engine=True,
        requires=["1x1", "valid", "g1", "fp16", "c32", "oc32", "fp32_out", "two_oc16_blocks"],
        note="C32 maps exactly to the K8 C32 frame; two OC16 blocks; RK capture has a known FP32 structural/zero-fill divergence, so not an exact oracle.",
    ),
    "conv_simple_fp16_3x3_c16_h8_w8_oc32": dict(
        gate="3", cls="SPATIAL_VALID", first_engine=False,
        requires=["spatial", "3x3", "line_buffer", "nc1hwc2", "two_oc16_blocks"],
        note="3x3 valid, C16/OC32.",
    ),
    "simple_conv_int8_5x5_c8_h8_w8_oc32": dict(
        gate="5", cls="INT8_SPATIAL", first_engine=False,
        requires=["spatial", "5x5", "line_buffer", "int8_mac", "zero_point", "bias", "quantized_out"],
        note="INT8 quantized; requires integer MAC/CACC; known +1 LSB output-conversion divergence.",
    ),
    "simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64": dict(
        gate="5", cls="INT8_DEPTHWISE", first_engine=False,
        requires=["spatial", "3x3", "depthwise", "int8_mac", "zero_point", "bias", "quantized_out"],
        note="INT8 depthwise; CORE DW_EN and depthwise weight layout; known +1 LSB divergence.",
    ),
    "conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2": dict(
        gate="2R", cls="BLOCKED_SOURCE", first_engine=False,
        requires=["spatial", "stride2", "line_buffer"],
        note="BLOCKED: the named FP16/INT8 builders hardcode stride 1; no source encoding for stride 2.",
    ),
    "conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad": dict(
        gate="2R", cls="BLOCKED_SOURCE", first_engine=False,
        requires=["spatial", "padding", "line_buffer"],
        note="BLOCKED: no SAME-padding path; FP16 builder never writes CNA_PAD_CON0/1.",
    ),
    "conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack": dict(
        gate="1R", cls="BLOCKED_SOURCE", first_engine=False,
        requires=["1x1_or_spatial", "c8"],
        note="BLOCKED: align_c=16 but input pack c2=8 for C8; no source-supported fill contract.",
    ),
    "conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2": dict(
        gate="4R", cls="BLOCKED_MULTITASK_SOURCE", first_engine=False,
        requires=["spatial", "3x3", "grouped", "multi_task"],
        note="BLOCKED: FP16 builder has no group field; only grouped path is per-group resubmit with shared-BO overwrite.",
    ),
    "simple_conv_int8_addition_c8_h8_w8_oc32": dict(
        gate="5R", cls="BLOCKED_ABI", first_engine=False,
        requires=["spatial", "int8", "addition_input"],
        note="BLOCKED: addition_input/add_tensor knobs do not produce an addition tensor BO or address.",
    ),
    # conv-fp16
    "conv_1x1_valid_c8_h5_w5_oc8": dict(
        gate="1A", cls="M1_FP16_PRIMARY", first_engine=True,
        requires=["1x1", "valid", "g1", "fp16", "c8", "oc8", "fp16_out", "flat_1x1"],
        note="PRIMARY first case. Exact RK capture; OC8 half of one OC16 block; FP16 output; one C8 frame maps to one 16-byte atom.",
    ),
    "conv_3x3_valid_c4_h9_w9_oc4": dict(
        gate="3", cls="SPATIAL_VALID", first_engine=False,
        requires=["spatial", "3x3", "line_buffer", "nc1hwc2"],
        note="3x3 valid, C4/OC4; exact RK capture.",
    ),
    "conv_3x3_stride2_c4_h11_w11_oc4": dict(
        gate="2", cls="SPATIAL_STRIDE", first_engine=False,
        requires=["spatial", "3x3", "stride2", "line_buffer", "nc1hwc2"],
        note="Source-supported stride-2 variant; exact RK capture; table-uncovered.",
    ),
    "conv_3x3_pad1_zero_frame_c4_h9_w9_oc4": dict(
        gate="2", cls="SPATIAL_PAD_ZERO_FRAME", first_engine=False,
        requires=["spatial", "3x3", "zero_frame_pad", "line_buffer", "nc1hwc2"],
        note="Explicit 1-pixel zero frame, valid 3x3; not CNA_PAD_CON0.",
    ),
    "conv_depthwise_3x3_c3_h11_w28_oc3": dict(
        gate="4", cls="DEPTHWISE", first_engine=False,
        requires=["spatial", "3x3", "depthwise", "spatial_major_weight", "nc1hwc2"],
        note="FP16 depthwise C3/OC3; single READY capture.",
    ),
    "conv_grouped_3x3_c4_h5_w5_oc8_g2_task0": dict(
        gate="4", cls="GROUPED_PROMOTED", first_engine=False,
        requires=["spatial", "3x3", "grouped", "promoted_one_task"],
        note="Promoted group 0: plain C2/OC4 3x3. Parent needs multi-task.",
    ),
    "conv_grouped_3x3_c4_h5_w5_oc8_g2_task1": dict(
        gate="4", cls="GROUPED_PROMOTED", first_engine=False,
        requires=["spatial", "3x3", "grouped", "promoted_one_task"],
        note="Promoted group 1: plain C2/OC4 3x3. Parent needs multi-task.",
    ),
    "conv_splitoc_3x3_c16_h9_w9_oc16_task0": dict(
        gate="4", cls="SPLIT_OC_PROMOTED", first_engine=False,
        requires=["spatial", "3x3", "split_oc", "promoted_one_task"],
        note="Promoted OC0..7: plain C16/OC8 3x3. Parent needs multi-task/shared input.",
    ),
    "conv_splitoc_3x3_c16_h9_w9_oc16_task1": dict(
        gate="4", cls="SPLIT_OC_PROMOTED", first_engine=False,
        requires=["spatial", "3x3", "split_oc", "promoted_one_task"],
        note="Promoted OC8..15: plain C16/OC8 3x3. Parent needs multi-task/shared input.",
    ),
    "conv_grouped_3x3_c4_h5_w5_oc8_g2": dict(
        gate="4R", cls="BLOCKED_MULTITASK", first_engine=False,
        requires=["spatial", "3x3", "grouped", "multi_task"],
        note="BLOCKED: Rocket executed only task 0 of a two-task job; use promoted one-task cases.",
    ),
    "conv_splitoc_3x3_c16_h9_w9_oc16": dict(
        gate="4R", cls="BLOCKED_MULTITASK", first_engine=False,
        requires=["spatial", "3x3", "split_oc", "multi_task"],
        note="BLOCKED: Rocket executed only task 0 of a two-task job; use promoted one-task cases.",
    ),
    "conv_tiles_vendor_abi_blocked": dict(
        gate="6", cls="BLOCKED_VENDOR_ABI", first_engine=False,
        requires=["vendor_abi", "multi_core", "pc_chain"],
        note="BLOCKED: vendor /dev/dri rknpu ABI and PC/subcore task policy.",
    ),
    "conv_3x3_pad_register_fp16_blocked": dict(
        gate="2R", cls="BLOCKED_PAD_REGISTER", first_engine=False,
        requires=["spatial", "3x3", "cna_pad_con0"],
        note="BLOCKED: no Rocket-capable FP16 CNA_PAD_CON0 capture.",
    ),
    "conv_split_k_reduction_blocked": dict(
        gate="5R", cls="BLOCKED_SPLIT_K", first_engine=False,
        requires=["spatial", "3x3", "split_k", "accumulator_persistence"],
        note="BLOCKED: no partial-K accumulation/clearing contract in any READY capture.",
    ),
    # conv-gemm-vendor (conv only)
    "conv_1x1_c1_oc6_h4w4": dict(
        gate="1C", cls="M1_NHWC_C1", first_engine=True,
        requires=["1x1", "valid", "g1", "fp16", "c1", "oc6", "fp16_out", "nhwc", "flat_1x1"],
        note="NHWC C1 input, OC6 padded to 8/16; exact RK capture.",
    ),
    "conv_grouped_3x3_c4_oc4_g2_h5w5": dict(
        gate="4", cls="GROUPED_SINGLE_TASK", first_engine=False,
        requires=["spatial", "3x3", "grouped", "grouped_weight_order", "nc1hwc2"],
        note="Single-task grouped 3x3, C4/OC4/G2; exact RK capture. This is the grouped proof, not the multi-task conv-fp16 parent.",
    ),
    "conv_legacy_3x3_c4_oc4_h9w9": dict(
        gate="3", cls="SPATIAL_VALID", first_engine=False,
        requires=["spatial", "3x3", "line_buffer", "flat_1x1"],
        note="Legacy 3x3 valid, C4/OC4; exact RK capture.",
    ),
    "conv_depthwise_3x3_c3_oc3_h11w28": dict(
        gate="4R", cls="BLOCKED_MULTITASK", first_engine=False,
        requires=["spatial", "3x3", "depthwise", "multi_task"],
        note="BLOCKED parent: source double-submits the same task; Rocket executes only task 0.",
    ),
    "conv_depthwise_3x3_c3_oc3_h11w28_task0": dict(
        gate="4", cls="DEPTHWISE", first_engine=False,
        requires=["spatial", "3x3", "depthwise", "spatial_major_weight", "flat_1x1"],
        note="Promoted depthwise task 0; exact RK capture.",
    ),
    "conv_depthwise_3x3_c3_oc3_h11w28_task1": dict(
        gate="4", cls="DEPTHWISE", first_engine=False,
        requires=["spatial", "3x3", "depthwise", "spatial_major_weight", "flat_1x1"],
        note="Promoted depthwise task 1; exact RK capture.",
    ),
    "conv_py_3x3_c32_oc128_h14w14_fullsetup": dict(
        gate="3", cls="SPATIAL_LARGE", first_engine=False,
        requires=["spatial", "3x3", "line_buffer", "nc1hwc2", "multiple_oc16_blocks", "full_setup"],
        note="C32/OC128 large spatial, full 108-QWORD setup; exact tolerance PASS.",
    ),
    "conv_byk_c160_h14w14_oc320_k3x3": dict(
        gate="6", cls="BLOCKED_VENDOR_ABI", first_engine=False,
        requires=["vendor_abi", "multi_core", "pc_chain", "split_k"],
        note="BLOCKED: vendor BY_K multi-core PC chain; no core_mask/subcore_task or regcmd self-address patch.",
    ),
    "conv_h40_c160_h40w40_oc320_k3x3": dict(
        gate="6", cls="BLOCKED_VENDOR_ABI", first_engine=False,
        requires=["vendor_abi", "multi_core", "pc_chain", "large_tiling"],
        note="BLOCKED: vendor H40 spatial six-task/17-row chain; no core_mask/subcore_task or self-address patch.",
    ),
}


def load_family(root: Path, family: str) -> dict:
    return json.loads((root / family / "manifest.json").read_text())


def shape_of(family: str, case: dict) -> dict:
    if family == "conv-gemm-vendor":
        return case.get("source_shape_parameters") or {}
    return case.get("shape") or {}


def dtype_of(family: str, case: dict) -> str | None:
    if family == "conv-simple":
        return (case.get("dtype") or {}).get("output")
    if family == "conv-fp16":
        return (case.get("oracle") or {}).get("dtype")
    if family == "conv-gemm-vendor":
        oracle = case.get("expected_oracle") or {}
        return oracle.get("dtype")
    return None


def layout_of(family: str, case: dict) -> str | None:
    if family == "conv-simple":
        return (case.get("layout") or {}).get("output_raw")
    if family == "conv-fp16":
        layouts = case.get("output_layouts") or []
        return layouts[0].get("layout") if layouts else None
    if family == "conv-gemm-vendor":
        return (case.get("conv_layout") or {}).get("unpack_function")
    return None


def blocker_of(case: dict) -> str | None:
    return (
        case.get("blocker")
        or case.get("blocked_reason")
        or case.get("reason")
        or case.get("blocked_code")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--captures",
        default="/home/fedora/rknpu-fpga/build/rk3588-example-captures",
        type=Path,
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("CONV_MATRIX.json")),
        type=Path,
    )
    args = parser.parse_args()

    rows = []
    seen = set()
    for family in FAMILIES:
        manifest = load_family(args.captures, family)
        for case in manifest["cases"]:
            name = case["case"]
            if family == "conv-gemm-vendor" and name.startswith("gemm_"):
                continue
            if name not in CASES:
                raise SystemExit(f"unclassified conv case: {family}/{name}")
            meta = CASES[name]
            shape = shape_of(family, case)
            row = {
                "family": family,
                "case": name,
                "status": case["status"],
                "engine_gate": meta["gate"],
                "class": meta["cls"],
                "first_engine": bool(meta["first_engine"]),
                "requires": meta["requires"],
                "note": meta["note"],
                "shape": {
                    "in_c": shape.get("in_c"),
                    "in_h": shape.get("in_h"),
                    "in_w": shape.get("in_w"),
                    "out_c": shape.get("out_c"),
                    "kh": shape.get("kh"),
                    "kw": shape.get("kw"),
                    "stride": shape.get("stride", 1),
                    "groups": shape.get("groups", 1),
                },
                "dtype_output": dtype_of(family, case),
                "output_layout": layout_of(family, case),
                "blocker": blocker_of(case),
                "source": f"{args.captures}/{family}/cases/{name}",
            }
            rows.append(row)
            seen.add(name)

    missing = sorted(set(CASES) - seen)
    if missing:
        raise SystemExit(f"manifest cases missing: {missing}")

    ready = [r for r in rows if r["status"] == "READY"]
    blocked = [r for r in rows if r["status"] == "BLOCKED"]
    first = sorted(
        [r for r in rows if r["first_engine"]],
        key=lambda r: {"1A": 0, "1B": 1, "1C": 2}.get(r["engine_gate"], 9),
    )
    if (len(rows), len(ready), len(blocked)) != (35, 22, 13):
        raise SystemExit(
            f"unexpected counts: total={len(rows)} ready={len(ready)} blocked={len(blocked)}"
        )
    if len(first) != 4:
        raise SystemExit(f"unexpected first-engine count: {len(first)}")

    matrix = {
        "schema": "rknpu-fpga-convolution-architecture-matrix-v1",
        "generated_from": str(args.captures),
        "scope": (
            "Architecture/planning only. Read-only classification of the captured conv cases. "
            "No RTL, board, bitstream, full-top or RK-silicon claim."
        ),
        "source_revisions": {
            "rknpu_fpga_worktree": "a9b5d02 (conv-arch, on top of main)",
            "rk3588_examples": "273d015e08af40c81d2cd9ab84198486b03a17f1",
            "nvdla_reference": "3f1bc4c36c6737d5873f8c1833dffac9322387a0",
        },
        "counts": {
            "conv_entries": len(rows),
            "ready": len(ready),
            "blocked": len(blocked),
            "first_engine_ready": len(first),
            "gemm_entries_excluded": 4,
            "conv_plus_gemm_ready": len(ready) + 4,
            "conv_plus_gemm_total": len(rows) + 4,
        },
        "first_engine_envelope": {
            "kernels": "1x1",
            "stride": 1,
            "padding": "valid/zero",
            "groups": 1,
            "dtype": "FP16 input/weight; FP16 or FP32 output",
            "c_limit": 32,
            "oc_limit": "16 (OC32 as two OC16 blocks)",
            "no_int8": "No captured INT8 1x1 case and no integer MAC/CACC in the current slice.",
            "cases": [r["case"] for r in first],
        },
        "gates": [
            {
                "id": "0",
                "name": "contracts + golden",
                "scope": "first-case profile, frame/address golden, K2/K4/K8 lower-slice equality",
                "exit": "layout verifier exact; no RTL change",
            },
            {
                "id": "1A",
                "name": "first case: 1x1 valid single-group FP16 C8/OC8",
                "scope": "strict 54-QWORD profile, feature fetch, weight expand, frame scheduler, K8/K2 arithmetic, FP16 atom writer",
                "exit": "exact frame/address; defined plane-0 matches oracle; unsupported fields fail",
            },
            {
                "id": "1B",
                "name": "1x1 FP32 output / OC16",
                "scope": "FP32 c2=4 atom scatter, OC16 block, C4 and C32 cases",
                "exit": "C4 raw output exact; C32 treated as known structural divergence",
            },
            {
                "id": "1C",
                "name": "1x1 C1 NHWC",
                "scope": "NHWC C1 gather, OC6 padding",
                "exit": "exact via donor unpack",
            },
            {
                "id": "2",
                "name": "stride/pad + first spatial skeleton",
                "scope": "3-row line buffer, stride 1/2, explicit zero-frame padding",
                "exit": "3x3 valid/stride2/zero-frame match; pad register still rejected",
            },
            {
                "id": "3",
                "name": "3x3/5x5 breadth",
                "scope": "5x5, C16/C32, OC32/OC128, kh-major weight, NC1HWC2 atoms",
                "exit": "listed spatial cases match; no full CBUF claim",
            },
            {
                "id": "4",
                "name": "depthwise/grouped/split-OC",
                "scope": "depthwise diagonal/spatial-major weights, grouped single-task, promoted split-OC",
                "exit": "single/promoted cases match; multi-task parents remain explicit failures",
            },
            {
                "id": "5",
                "name": "split-K/INT8/multi-task/vendor",
                "scope": "partial-K accumulation, integer MAC/CACC, PC chain",
                "exit": "new source/ABI evidence and contracts; otherwise blocked",
            },
        ],
        "cases": rows,
        "first_case": {
            "case": "conv_1x1_valid_c8_h5_w5_oc8",
            "family": "conv-fp16",
            "shape": {
                "in_c": 8, "in_h": 5, "in_w": 5,
                "out_c": 8, "kh": 1, "kw": 1, "stride": 1, "groups": 1,
                "out_h": 5, "out_w": 5,
            },
            "dtype": "FP16 in/weight/out",
            "files": {
                "a.bin": {
                    "bytes": 800,
                    "sha256": "fa1cfc610a9d473bbef852dac62bef6d63f67727b0d8a20587962b0418739c71",
                },
                "w.bin": {
                    "bytes": 256,
                    "sha256": "52a1b39b6ef32d87bed51b67d32b67073f2aefae3fc96d265a0a82b6ba838418",
                },
                "expected.bin": {
                    "bytes": 400,
                    "sha256": "7a364a2c20910f0b00f4f522856009ed69d5a477ea4b9fdee5ac146193d2058c",
                },
                "regcmd.bin": {
                    "bytes": 432,
                    "sha256": "a66063b1df7be1c913ee9851a65270a0644a98312db640fbc58216a97855ac6c",
                },
                "rk_out.bin": {
                    "bytes": 1600,
                    "sha256": "82f8bdb91b780e54f6d90b1ea4281d01913f7561d688f0e5a75df89b5f604f0e",
                    "path": "build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/board-run/conv-fp16/conv_1x1_valid_c8_h5_w5_oc8/out.bin",
                },
            },
            "input_layout": {
                "format": "[c1=2][H=5][width_stride=5][c2=8] halfwords; C0..C7 real, C8..C15 zero",
                "halfword_index": "((c/8)*5 + y)*5*8 + x*8 + (c%8)",
                "byte_offset": "2*((((c/8)*5 + y)*5 + x)*8 + (c%8))",
                "pixel_atom_byte": "16*(y*5+x)",
            },
            "weight_layout": {
                "format": "[oc=8][ic=16] halfwords; IC0..IC7 real, IC8..IC15 zero",
                "halfword_index": "oc*16 + ic",
                "byte_offset": "2*(oc*16+ic)",
                "kernel_byte_stride": 32,
            },
            "output_layout": {
                "format": "[c1=4][out_width_stride=25][c2=8] halfwords; plane 0 (OC0..OC7) defined",
                "halfword_index": "(plane*25 + y*5 + x)*8 + lane",
                "byte_offset": "2*((plane*25 + y*5 + x)*8 + lane)",
                "defined_bytes": 400,
                "defined_region": "plane 0 only",
                "test_transform": "raw.reshape(4,25,8)[0].reshape(25,8).T.reshape(8,5,5) == expected.bin",
            },
            "k8_weight_traversal": {
                "formula_halfwords": "W_h(oc,ic)=base_h+(oc/16)*(16*ai)+(ic/32)*512+(oc%16)*32+(ic%32)",
                "first_case_ai": 32,
                "first_case_ao": 16,
                "reduced": "W_h(k,c)=base_h+k*32+c for k=0..15,c=0..31",
                "source_to_frame": {
                    "k=0..7,c=0..7": "w.bin halfword k*16+c",
                    "k=0..7,c=8..31": "zero, weight mask 0",
                    "k=8..15,c=0..31": "zero, weight mask 0",
                },
                "oc8_second_half_offset_bytes": 512,
                "note": "The source BO is unchanged; expansion is a hardware address/mask function.",
            },
            "frame_sequence": {
                "frames_per_case": 25,
                "frame_data": "8 real input halfwords at a*16, lanes 8..31 zero/masked",
                "frame_weight": "16x32 expanded OC16 block, cached once",
                "first_last": "first=1, last=1 (one IC32 group)",
                "output_atom_bytes": 16,
                "output_atom_address": "out_base + a*16",
                "cacc_lanes": "out_values[k*32 +: 32], k=0..7; no reordering",
            },
            "do_not_reuse": (
                "The K8 GEMM output advance (+0/+16 within 64 B, 16-halfword gap) is not the RK conv layout. "
                "For the first case the OC8-plane stride is 25*8*2=400 B, so the second OC8 half is at +400 B, not +16 B."
            ),
            "register_profile": {
                "stream_qwords": 54,
                "body_qwords": 50,
                "tail_qwords": 4,
                "key_values": {
                    "CNA 0x100c": "0x00000120",
                    "CNA 0x1010": "0x00000340",
                    "CNA 0x1014": "0x00000009",
                    "CNA 0x1020": "0x00050005",
                    "CNA 0x1024": "0x00070010",
                    "CNA 0x1028": "0x00000005",
                    "CNA 0x102c": "0x00000019",
                    "CNA 0x1030": "0x00000100",
                    "CNA 0x1034": "0x00000020",
                    "CNA 0x1038": "0x01010008",
                    "CNA 0x1040": "0x000000b1",
                    "CNA 0x1044": "0x00000003",
                    "CNA 0x1078": "0x000f000f",
                    "CNA 0x107c": "0x00000014",
                    "CNA 0x1080": "0x00000005",
                    "CNA 0x1084": "0x00050005",
                    "CNA 0x1088": "0x00000010",
                    "CORE 0x3010": "0x00000200",
                    "CORE 0x3014": "0x00040004",
                    "CORE 0x3018": "0x0000001f",
                    "DPU 0x400c": "0x000001e4",
                    "DPU 0x4010": "0x48000002",
                    "DPU 0x4024": "0x00000190",
                    "DPU 0x4030": "0x00000004",
                    "DPU 0x4034": "0x00000004",
                    "DPU 0x403c": "0x0007001f",
                    "DPU 0x4050": "0x00000126",
                    "DPU 0x4070": "0x00000383",
                    "DPU 0x4084": "0x00010001",
                    "DPU 0x40c0": "0x00000320",
                    "TAIL 0x00810008": "0x0000000d",
                },
                "policy": (
                    "Every body word is decoded. Unknown target/offset, duplicate/incomplete field, or a value "
                    "different from the profiled value is an explicit error. Scheduling-only constants are validated, "
                    "not silently ignored."
                ),
            },
            "verification": {
                "host_layout_check": "first_case_layout_check.json",
                "expected_check": "captured plane 0 reconstructs expected.bin exactly; host-side only",
                "numeric_gate": "FP16 engine output compared after donor unpack within atol=0.2",
            },
        },
        "components": [
            {
                "name": "rk_conv_profile",
                "responsibility": "strict raw CNA/CORE/DPU + 54-QWORD tail decode; geometry and field validation",
                "first": "exact first-case profile; parameterized 1x1 envelope later",
                "reuse": "new",
            },
            {
                "name": "rk_conv_front",
                "responsibility": "feature fetch, weight expand, frame scheduler, first/last tags, output atom address",
                "first": "C1C2 and NHWC feature modes; OC16xC32 weight tile",
                "reuse": "new; K8 front weight formula is the reference",
            },
            {
                "name": "CMAC/CACC",
                "responsibility": "C32 x K products and per-kernel FP48/FP32 accumulation",
                "first": "reuse C32/K8; add K2/K4 parameterization",
                "reuse": "rtl/cmac/rk_cmac_fp16_array.sv, rk_cacc_fp16_array.sv, rk_nvdla_cacc.sv",
            },
            {
                "name": "rk_conv_output_atom",
                "responsibility": "FP16/FP32 atom assembly and flat_1x1/NC1HWC2 placement",
                "first": "FP16 c2=8 one-frame-one-atom; FP32 c2=4 two-atom scatter",
                "reuse": "reuse rk_cmac_output_nvdla / rk_fp32_to_fp16 leaves, not the K8 atom advance",
            },
            {
                "name": "CBUF / line buffer",
                "responsibility": "row/channel reuse, padding/stride windows",
                "first": "1x1 none; 3x3/5x5 kh-row line buffer; local weight tile",
                "reuse": "new; NVDLA cbuf bank wrapper is reference only",
            },
            {
                "name": "rk_conv_dma",
                "responsibility": "raw 54-QWORD conv framing, terminal tail, one-outstanding memory",
                "first": "new amount/tail; do not reuse CMAC 45/49 framing",
                "reuse": "rk_cmac_rw_arbiter and existing memory contract",
            },
        ],
        "nvdla_reuse": {
            "already_reused": [
                "NV_NVDLA_CMAC_CORE_MAC_mul.v (FP16 product donor)",
                "NV_NVDLA_CACC_* / rk_nvdla_cacc (FP48 accumulation donor)",
            ],
            "reference_only": [
                "NV_NVDLA_CSC_dl/sg/wl (stripe/atom sequencing)",
                "NV_NVDLA_CDMA_dc/wt/img (feature/weight fetch)",
                "NV_NVDLA_cbuf.v (bank wrapper)",
                "NV_NVDLA_CACC_assembly/delivery (output format)",
            ],
            "custom": [
                "RK CNA/CORE/DPU profile decode",
                "RK feature address generator (C1C2/NHWC, 32B-unit/4-row tiling)",
                "RK weight address generator/expander (default/kh-major/depthwise)",
                "line buffer / bank reuse / padding / stride",
                "conv output atom scheduler",
                "INT8 MAC/CACC, split-OC/split-K/multi-task",
            ],
            "do_not_import": (
                "Full NVDLA core: failed fit (3,138 slices short; ~295K LUT / 1,430 DSP / 291.5 BRAM). "
                "nv_small_256 is INT8/BPE=8 with 32x32Bx128 CBUF; RK is 12x256x128 B and FP16 here."
            ),
        },
        "area_estimate": {
            "basis": (
                "Measured full C32/K16 512-product CMAC demo: 267,210 LUT, 35,776 FF, 6 BRAM, 515 DSP. "
                "Scaled per product (~522 LUT, ~70 FF, ~1 DSP). Estimate only; replace with OOC synthesis."
            ),
            "variants": [
                {"name": "C32/K8", "products": 256, "lut": "120-145K", "ff": "17-20K", "dsp": "256-260", "bram": "2-4", "frames_first_case": 25},
                {"name": "C32/K4", "products": 128, "lut": "60-75K", "ff": "9-11K", "dsp": "128-132", "bram": "2-4", "frames_first_case": 50},
                {"name": "C32/K2", "products": 64, "lut": "30-40K", "ff": "5-7K", "dsp": "64-68", "bram": "2-4", "frames_first_case": 100},
                {"name": "C8/K2 (new C8 layout)", "products": 16, "lut": "8-12K", "ff": "1.5-2K", "dsp": "16-18", "bram": "1-2", "frames_first_case": 100},
            ],
            "front_add": "~5-12K LUT, 2-6 BRAM for conv front + line buffer + output scheduler",
            "full_cbuf": "~384 KiB (12 x 256 x 128 B), not included; separate capacity decision",
            "pdp_disclaimer": (
                "The 39.6K-LUT PDP prototype is a pooling datapath plus bridge, not a convolution engine. "
                "It has no CBUF, CSC traversal, weight fetch, line buffer, padding/stride or output atom scheduler. "
                "Do not use it as a convolution area estimate."
            ),
        },
        "test_estimate": {
            "first_case_frames": 25,
            "first_case_input_reads": "8 halfwords per frame with resident weight tile",
            "first_case_output_halfwords": 200,
            "decoder_tests": "~10-15 directed accept/reject cases",
            "frame_tests": "exhaustive 25-atom frame/address golden",
            "core_tests": "1 replay on Icarus and Verilator; compare defined 400 B after donor unpack",
            "synthesis": "1-3 OOC runs (K8/K4/K2), background, report resource/timing",
            "later": "each gate adds captured replay + negative fields; spatial multiplies frames by kh*kw*OC blocks",
        },
        "risks": [
            {
                "rank": 1,
                "risk": "layout/traversal mismatch",
                "detail": (
                    "RK conv layouts are not K8 GEMM layouts: weight IC/OC expansion, aligned-C padding, "
                    "flat_1x1 vs NC1HWC2 atom planes, FP16 c2=8 vs FP32 c2=4, and out_width_stride padding. "
                    "A correct MAC with the wrong atom address is byte-wrong."
                ),
                "mitigation": "exhaustive frame/address golden; captured plane-0 check; no CPU fixup; reject unmodeled fields",
            },
            {
                "rank": 2,
                "risk": "area/fit and timing",
                "detail": (
                    "Faithful C32/K8 is ~120-145K LUT before the conv front; the board is already near 293K LUT. "
                    "The 39.6K PDP number is not a conv estimate."
                ),
                "mitigation": "functional K8 sim first, then K4/K2 lower-slice equality, fresh OOC synthesis; no full-top claim",
            },
            {
                "rank": 3,
                "risk": "CBUF/line-buffer, stride/pad and spatial sequencing",
                "detail": (
                    "NVDLA CBUF geometry differs from RK; true FP16 CNA_PAD_CON0 is unproven; boundary/stride errors "
                    "are easy to miss."
                ),
                "mitigation": "explicit zero-frame first; small line buffer with directed boundary tests; stride-2 replay; no full CBUF claim",
            },
            {
                "rank": 4,
                "risk": "INT8/split-K/multi-task numerics and ABI",
                "detail": "INT8 has +1 LSB divergences, split-K has no accumulation contract, multi-task PC chains are blocked.",
                "mitigation": "separate gates with new source/ABI evidence; keep unsupported entries explicit failures",
            },
        ],
    }

    args.output.write_text(json.dumps(matrix, indent=2) + "\n")
    print(
        f"wrote {args.output}: {len(rows)} conv entries, "
        f"{len(ready)} READY, {len(blocked)} BLOCKED, {len(first)} first-engine"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
