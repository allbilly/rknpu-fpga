# RK3588 example -> FPGA RTL gap matrix

Snapshot: **2026-11-05T22:41:40Z**  
Host source: `rknpu-fpga@f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`, `rk3588@273d015e08af40c81d2cd9ab84198486b03a17f1`.  
Board access: **none** (no ssh/scp, no submit, no FPGA program/flash). All capture facts below are read from existing host-side receipts.

This is a strict FP16 EW slice, not full RK3588 or a completed soDLA fork. The matrix separates **RK silicon capture**, **device-free prepared bundle**, **missing ABI**, **missing RTL**, **unsupported dtype/shape**, and **unknown**. FDIV is additionally marked **captured-not-implemented**: the real device output exists but the RTL has no divider. The fdiv-systematic truth table is **captured-characterization** because it has no pass/fail oracle by design. A `READY` manifest never means captured, and an RK result never means the FPGA RTL contains the block.

## 1. Counts

| Item | Count |
|---|---:|
| Python examples under `/home/fedora/rk3588/examples` | 25 |
| Top-level / `expt/` / `kernel_6_18/` | 9 / 3 / 13 |
| Runnable / duplicate / draft | 17 / 6 / 2 |
| Non-Python notes | 6 |
| Vendor RKNPU `/dev/dri/card1` ABI | 8 |
| Vendor default + Rocket option | 1 |
| Rocket `/dev/accel` ABI (direct or `rocket_runtime`) | 16 |
| Examples with a capture bundle | 13 |
| Examples with no bundle | 12 |
| Capture bundles | 7 |
| Manifest cases | 140 |
| READY / BLOCKED | 122 / 18 |
| Captured on RK3588 Rocket | **122** |
| Exact PASS | **107** |
| Tolerance-only PASS | **2** |
| Known divergence | **5** |
| Truth-table characterization | **8** |
| Captured, oracle comparison pending | **0** |
| Prepared, runner-valid, not run | **0** |
| Manifest READY but runner-invalid | **0** |
| Blocked total (manifest + runner-invalid) | **18** |
| Blocked cases by missing ABI / dtype-shape / multi-task / integrity | 3 / 12 / 3 / 0 |
| FPGA executions of these bundles | **0** |

Check: captured + prepared + blocked total = 122 + 0 + 18 = 140 = 140.

Captured breakdown: 107 exact PASS + 2 tolerance PASS + 5 known divergence + 8 truth table + 0 pending = 122.

Non-exclusive example labels: `blocked_missing_abi` 9, `blocked_missing_rtl` 22, `blocked_multitask_execution` 2, `blocked_unsupported_dtype_shape` 12, `captured_exact` 9, `captured_known_divergence` 3, `captured_not_implemented` 1, `captured_tolerance` 2, `captured_truth_table` 1, `unknown` 10

## 2. Capture queue

A case is **captured** only when its result directory contains `capture.json` plus a real output BO (`out.bin`, `out0.bin`, `out1.bin` or `output.bin`). Exact, tolerance-only, known-divergence and truth-table states are shown separately. All 122 READY cases are captured. `ew-int` is 15/15 exact; `pooling` is 19/19 full-BO exact; `fdiv-systematic` is an 8-case, 256-class truth table. `conv-fp16` is 9/9 exact after the multi-task split. `conv-gemm-vendor` is 10/10 PASS (8 exact, 2 tolerance), including the depthwise 702/702 rerun after the 15,104-byte BO fix. `conv-simple` is 4/7 exact, with 1 FP32-output C32 structural mismatch and 2 INT8 +1 LSB output-conversion divergences.

| Family | Total | READY | BLOCKED | Captured | Bytes | Exact | Tolerance | Known | Truth | Pending | Prepared |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `conv-fp16` | 14 | 9 | 5 | 9 | 35392 | 9 | 0 | 0 | 0 | 0 | 0 |
| `conv-gemm-vendor` | 13 | 10 | 3 | 10 | 95744 | 8 | 2 | 0 | 0 | 0 | 0 |
| `conv-simple` | 12 | 7 | 5 | 7 | 21888 | 4 | 0 | 3 | 0 | 0 | 0 |
| `ew-fp16` | 54 | 54 | 0 | 54 | 221184 | 52 | 0 | 2 | 0 | 0 | 0 |
| `ew-int` | 18 | 15 | 3 | 15 | 61440 | 15 | 0 | 0 | 0 | 0 | 0 |
| `fdiv-systematic` | 8 | 8 | 0 | 8 | 512 | 0 | 0 | 0 | 8 | 0 | 0 |
| `pooling` | 21 | 19 | 2 | 19 | 77824 | 19 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **140** | **122** | **18** | **122** | **513984** | **107** | **2** | **5** | **8** | **0** | **0** |

Result roots: `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/conv-fp16-20261105T205900Z` (2 cases, 8192 bytes, 2 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/conv-fp16-20261105T222300Z` (9 cases, 35392 bytes, 9 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/conv-gemm-depthwise-rerun-20261105T221115Z` (2 cases, 30208 bytes, 2 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/conv-gemm-vendor-20261105T214000Z` (8 cases, 65536 bytes, 8 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/conv-simple-20261105T215921Z` (7 cases, 21888 bytes, 7 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-fp16-20261105T201400Z` (54 cases, 221184 bytes, 54 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/ew-int-20261105T200154Z` (15 cases, 61440 bytes, 15 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z` (8 cases, 512 bytes, 8 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64); `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/pooling-20261105T203205Z` (19 cases, 77824 bytes, 19 submit_ret=0, orangepi5 / 6.18.24-current-rockchip64).

Result-root accounting: the old `conv-fp16-20261105T205900Z` tree contributes only the 2 now-BLOCKED combined captures (8,192 bytes); the current 9/9 exact count comes from `conv-fp16-20261105T222300Z` (35,392 bytes). `conv-gemm-vendor-20261105T214000Z` contributes 8 cases/65,536 bytes; the depthwise rerun `conv-gemm-depthwise-rerun-20261105T221115Z` contributes 2 cases/30,208 bytes (15,104 bytes each) and supersedes the failed depthwise outputs. `conv-simple-20261105T215921Z` contributes 7 cases/21,888 bytes (4 exact + 3 known divergence).

## 3. Example census

Block symbols: `Y` exercised, `B` configured/bypass only, `P` partial/helper or non-main path, `D` definition only, `PC-only` = PC command chain used without a data-path RDMA block, `-` not used. `V` = vendor `/dev/dri/card1` RKNPU; `R` = Rocket `/dev/accel`; `R*` = Rocket via `rocket_runtime`; `V+R` = vendor default with Rocket option. Bundle counts are `READY/BLOCKED/CAPTURED`.

| Example | Kind | ABI | EW-F16 | EW-INT | PPU | CNA/conv | CMAC/GEMM | BS/BN | RDMA/PC | Bundle R/B/C | Evidence |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `conv_gemm.py` | runnable | V | - | - | - | Y | Y | B | PC-only | `conv-gemm-vendor` 2R/0B/2C | captured_exact, blocked_missing_abi, blocked_missing_rtl |
| `conv_legacy.py` | runnable | V | - | - | - | Y | - | B | PC-only | `conv-gemm-vendor` 3R/1B/3C | captured_exact, blocked_missing_abi, blocked_missing_rtl, blocked_multitask_execution |
| `conv.py` | runnable | V | - | - | - | Y | - | B | PC-only | `conv-gemm-vendor` 1R/2B/1C | captured_tolerance, blocked_missing_abi, blocked_missing_rtl, unknown |
| `conv_simple.py` | runnable | V | - | - | - | Y | - | B | PC-only | — | blocked_missing_abi, blocked_missing_rtl |
| `conv_tiles.py` | runnable | V | - | - | D | Y | - | B | PC-only | `conv-fp16` 0R/1B/0C | blocked_missing_abi, blocked_missing_rtl |
| `elementwise.py` | runnable | V | Y | - | - | - | - | - | Y | `ew-fp16, fdiv-systematic` 62R/0B/62C | captured_exact, captured_known_divergence, captured_truth_table, captured_not_implemented, blocked_missing_abi, blocked_missing_rtl, unknown |
| `gemm.py` | runnable | V | - | - | - | - | Y | B | PC-only | `conv-gemm-vendor` 4R/0B/4C | captured_exact, captured_tolerance, blocked_missing_abi, blocked_unsupported_dtype_shape, unknown |
| `pooling.py` | runnable | R | - | - | Y | - | - | - | Y | — | blocked_missing_rtl |
| `simple_add.py` | duplicate | V | Y | - | - | - | - | - | Y | — | blocked_missing_abi, blocked_unsupported_dtype_shape, unknown |
| `expt/conv_simple.py` | runnable | V+R | - | - | - | Y | - | B | PC-only | `conv-simple` 5R/4B/5C | captured_exact, captured_known_divergence, blocked_missing_abi, blocked_missing_rtl, blocked_unsupported_dtype_shape, unknown |
| `expt/elementwise_int.py` | runnable | R | P | Y | - | - | - | Y | Y | `ew-int` 4R/2B/4C | captured_exact, blocked_missing_rtl, blocked_unsupported_dtype_shape |
| `expt/pooling.py` | runnable | R | - | - | Y | - | - | - | Y | `pooling` 19R/2B/19C | captured_exact, blocked_missing_rtl, blocked_unsupported_dtype_shape, unknown |
| `kernel_6_18/conv_0522.py` | draft | R* | - | - | - | Y | - | B | PC-only | `conv-fp16` 0R/1B/0C | blocked_missing_rtl, blocked_unsupported_dtype_shape, unknown |
| `kernel_6_18/conv_draft.py` | draft | R* | - | - | - | Y | - | B | PC-only | — | blocked_missing_rtl, blocked_unsupported_dtype_shape, unknown |
| `kernel_6_18/conv_legacy.py` | runnable | R | P | - | - | Y | - | B | PC-only | — | blocked_missing_rtl |
| `kernel_6_18/conv_mesa.py` | runnable | R | - | - | - | Y | - | Y | Y | — | blocked_missing_rtl, blocked_unsupported_dtype_shape |
| `kernel_6_18/conv_mesa_fp16.py` | duplicate | R | - | - | - | Y | - | Y | Y | — | blocked_missing_rtl, blocked_unsupported_dtype_shape, unknown |
| `kernel_6_18/conv_new_clean.py` | runnable | R* | - | - | - | Y | - | B | PC-only | `conv-fp16` 9R/3B/9C | captured_exact, blocked_missing_rtl, blocked_multitask_execution |
| `kernel_6_18/conv_new.py` | duplicate | R* | - | - | - | Y | - | B | PC-only | — | blocked_missing_rtl |
| `kernel_6_18/conv_new_trscrs.py` | duplicate | R* | - | - | - | Y | - | B | PC-only | — | blocked_missing_rtl |
| `kernel_6_18/conv.py` | duplicate | R* | - | - | P | Y | - | B | PC-only | — | blocked_missing_rtl, unknown |
| `kernel_6_18/elementwise_int.py` | runnable | R | P | Y | - | - | - | P | Y | `ew-int` 11R/1B/11C | captured_exact, blocked_missing_rtl, blocked_unsupported_dtype_shape |
| `kernel_6_18/simple_add.py` | duplicate | R | Y | - | - | - | - | - | Y | — | blocked_unsupported_dtype_shape |
| `kernel_6_18/simple_conv.py` | runnable | R | - | - | - | Y | - | Y | Y | `conv-simple` 2R/1B/2C | captured_known_divergence, blocked_missing_rtl, blocked_unsupported_dtype_shape |
| `kernel_6_18/simple_conv_fp16.py` | runnable | R | P | - | - | Y | - | B | PC-only | — | blocked_missing_rtl |

Notes: `expt/ppu_pooling_findings.md`, `ppu_pooling_findings.md`, `expt/trm_register_findings.md`, `expt/trm_register_matrix.md`, `kernel_6_18/README.md`, `kernel_6_18/tile.md`.

Key entry points / CLI:

- `conv_gemm.py` — module __main__; run_conv2d() and run_gemm(); `python3 conv_gemm.py [conv [shape_filter]] [gemm [shape_filter]]`
- `conv_legacy.py` — module __main__; run_conv2d() matrix; `python3 conv_legacy.py [--out fp16]`
- `conv.py` — module __main__; planner-driven run_shape()/guarded direct-spatial paths; `python3 conv.py <shape> | --list | --dry-run-* | --allow-*-submit`
- `conv_simple.py` — module __main__; run_shape(); `python3 conv_simple.py <shape> | --list`
- `conv_tiles.py` — module __main__; run_shape_suite(); `python3 conv_tiles.py [shape ...] [--start-index N] [--count N] [--skip-index N]`
- `elementwise.py` — module __main__; run_op() over OPS; `python3 elementwise.py [OP|ALL|CAST_BOOL_HALF] [--out fp16|fp32]`
- `gemm.py` — module __main__; run_gemm(); `python3 gemm.py [--out fp16]`
- `pooling.py` — module __main__; cases()/run_pool_case(); `python3 pooling.py [case|all|--list|--surface]`
- `simple_add.py` — module __main__; run_op() ADD only; `python3 simple_add.py [ADD|ALL]`
- `expt/conv_simple.py` — module __main__; run_shape() (vendor) and run_shape_rocket(); `python3 expt/conv_simple.py <shape> | --list | --validate-rgb-regs | --validate-mesa-cna-regs | --rocket-rgb`
- `expt/elementwise_int.py` — module __main__; run_operation()/probe dispatch; `python3 expt/elementwise_int.py [DTYPE] [OP] | --validate-* | --probe-*`
- `expt/pooling.py` — module __main__; cases()/run_pool_case(); `python3 expt/pooling.py [case|all|--list|--validate|--validate-multi-pass|--surface]`
- `kernel_6_18/conv_0522.py` — module __main__; run_conv() over a hardcoded shape list; `python3 kernel_6_18/conv_0522.py (no CLI filter)`
- `kernel_6_18/conv_draft.py` — module __main__; run_conv() for three shapes; `python3 kernel_6_18/conv_draft.py`
- `kernel_6_18/conv_legacy.py` — module __main__; run_conv2d() matrix; `python3 kernel_6_18/conv_legacy.py [--out fp16]`
- `kernel_6_18/conv_mesa.py` — module __main__; shape_matrix_runner() / conv_py_shape_matrix_runner(); `python3 kernel_6_18/conv_mesa.py [--input-packer ...] [--compare-packed-input ...]`
- `kernel_6_18/conv_mesa_fp16.py` — module __main__; same Mesa matrix plus FP16 packing options; `python3 kernel_6_18/conv_mesa_fp16.py [--compare-fp16-packed-input | --submit-fp16-packed-input ...]`
- `kernel_6_18/conv_new_clean.py` — module __main__; run_conv2d() matrix; `python3 kernel_6_18/conv_new_clean.py`
- `kernel_6_18/conv_new.py` — module __main__; run_conv2d() matrix; `python3 kernel_6_18/conv_new.py`
- `kernel_6_18/conv_new_trscrs.py` — module __main__; run_conv2d() matrix; `python3 kernel_6_18/conv_new_trscrs.py`
- `kernel_6_18/conv.py` — module __main__; run_shape_suite(); `python3 kernel_6_18/conv.py [shape ...]`
- `kernel_6_18/elementwise_int.py` — module __main__; run_operation() over DTYPES x OPERATIONS; `python3 kernel_6_18/elementwise_int.py [DTYPE] [OP]`
- `kernel_6_18/simple_add.py` — module __main__; run_op() ADD only; `python3 kernel_6_18/simple_add.py [ADD|ALL]`
- `kernel_6_18/simple_conv.py` — module __main__; run_conv2d_shape() matrix; `python3 kernel_6_18/simple_conv.py`
- `kernel_6_18/simple_conv_fp16.py` — module __main__; run_conv2d() matrix; `python3 kernel_6_18/simple_conv_fp16.py [--out fp16] [--keep-going]`

Register families (abridged; full lists in `EXAMPLE_MATRIX.json`):

| Example | Target families |
|---|---|
| `conv_gemm.py` | CNA, CORE, DPU, PC, PC_REG, VERSION |
| `conv_legacy.py` | CNA, CORE, DPU, PC, PC_REG, VERSION |
| `conv.py` | CNA, CORE, DPU, PC, PC_REG, VERSION |
| `conv_simple.py` | CNA, CORE, DPU, PC, PC_REG, VERSION |
| `conv_tiles.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, PPU, RDMA |
| `elementwise.py` | DPU, RDMA, PC, PC_REG, VERSION |
| `gemm.py` | CNA, CORE, DPU, PC, PC_REG, VERSION |
| `pooling.py` | PPU, PPU_RDMA, PC |
| `simple_add.py` | DPU, RDMA, PC, PC_REG, VERSION |
| `expt/conv_simple.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `expt/elementwise_int.py` | DPU, RDMA, PC |
| `expt/pooling.py` | PPU, PPU_RDMA, PC |
| `kernel_6_18/conv_0522.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_draft.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_legacy.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_mesa.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_mesa_fp16.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_new_clean.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_new.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv_new_trscrs.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/conv.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, PPU, RDMA |
| `kernel_6_18/elementwise_int.py` | DPU, RDMA, PC |
| `kernel_6_18/simple_add.py` | DPU, RDMA, PC, PC_REG, VERSION |
| `kernel_6_18/simple_conv.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |
| `kernel_6_18/simple_conv_fp16.py` | CNA, CORE, DPU, PC, PC_REG, VERSION, RDMA |

## 4. Block support in the actual RTL

| Block | FPGA status | RTL present | Scope / gap |
|---|---|---|---|
| **EW_FP16** — DPU elementwise FP16 ALU | **supported_strict** | `rtl/rk_fp16_alu.sv`<br>`rtl/rk_ew_engine.sv`<br>`rtl/rk_ew_core.sv`<br>`rtl/rk_ew_regs.sv`<br>`rtl/rk_ew_dma.sv` | Supported: Binary16 ADD, SUB, MUL, MAX; NEG is MUL by -1. Eight lanes per group; width is count-minus-one in groups of eight, up to 7999. Strict fixed profile: DPU pointer/mode/data-format, height=0, notch=0, channels=0x00070007, RDMA mode 0x00017849, OUT_CVT 0x00010001. Round-to-nearest-even, gradual underflow, RK-captured NaN 0x7c01, signed-zero and SUB-infinity policy.<br>Not supported: FDIV (captured on RK, decoder rejects EW_CFG 0x108303c0). INT8/INT16/INT32 EW, BS/BN arithmetic, LUT/activation, FP32 output, CAST_BOOL_HALF. General surface strides, ERDMA broadcast, BRDMA/NRDMA, multi-input, runtime gather/layout repair. |
| **EW_INT** — DPU elementwise integer ALU | **missing_rtl** | **none** | Supported: RK examples exercise INT8/INT16/INT32 ADD/MIN/SUB/MUL/MAX, saturation and INT16->INT32 regrouping. RK silicon evidence is strong: 15/15 ew-int bundled cases captured and oracle-verified on Rocket.<br>Not supported: No integer ALU exists. rk_fp16_alu.sv is half-precision only and rk_ew_regs.sv fixes DATA_FORMAT to 0x48000002. No integer saturation, no EDATA_SIZE integer modes, no INT16->INT32 WDMA. |
| **PPU** — PPU pooling | **missing_rtl** | **none** | Supported: RK examples exercise average/max/min, FP16/INT8/INT16, INDEX_EN, padding, kernel/stride 16, multi-pass. 19 READY pooling cases are captured and 19/19 full-BO exact (77,824 bytes); 2 FP32/INT32 zero-write probes are BLOCKED and were not run.<br>Not supported: No rtl/ module named PPU or implementing pool arithmetic. PPU 0x4001/0x8001 targets are not decoded by rk_ew_regs. No DPU-flying PPU input, no PPU_RDMA, no INDEX_EN. |
| **CNA_CONV** — CNA / CBUF / CSC convolution | **missing_rtl** | **none** | Supported: RK examples exercise 1x1/3x3/5x5 valid conv, depthwise, grouped, split-OC, stride, explicit zero-frame pad, CBUF banks, input/weight packing. 39 conv cases: 26 captured (9 conv-fp16 exact; 10 conv-gemm-vendor PASS, 8 exact + 2 tolerance; 7 conv-simple: 4 exact + 3 known divergence), 0 prepared and 13 BLOCKED (3 ABI, 3 multi-task, 7 other shape/source).<br>Not supported: No CNA, CBUF, CSC, CDMA, pad/stride/dilation, im2col or convolution data-fetch RTL. rk_cmac_array_* consumes already-packed C32/K16 GEMM frames; it is not a convolution engine. No INT8 CNA, no grouped/depthwise hardware decomposition, no multi-core/subcore scheduling. |
| **CMAC_GEMM** — CMAC / CACC FP16 GEMM | **partial_supported_strict** | `rtl/rk_cmac_profile.sv`<br>`rtl/cmac/rk_cmac_array_front.sv`<br>`rtl/cmac/rk_cmac_array_datapath.sv`<br>`rtl/cmac/rk_cmac_array_core.sv`<br>`rtl/cmac/rk_cmac_array_dma.sv`<br>`rtl/cmac/rk_cmac_cacc_fp16_array.sv`<br>`rtl/cmac/rk_cmac_frame_output.sv`<br>`rtl/cmac/rk_cmac_array_axi.sv`<br>`rtl/ddr/framework/rk_cmac_async_engine.sv` | Supported: FP16 C32/K16, 512 parallel products, FP48 accumulation and FP32 finalization followed by FP16 output writes. Strict terminal 49-QWORD profile: rows 1..2047, input/output channels multiples of 32, input channels >= output channels, no ReLU, no FP32 output, physical packed operands. Framework full profile adds layout DMA and six compiler shapes; default EW board top does not instantiate the CMAC product path.<br>Not supported: No general GEMM ABI, no runtime gathers, no arbitrary K/N/M, no FP32 output, no activation, no INT8/INT4. Not the default EW endpoint; requires the explicit RKCD/RKLY/RKRS framework profile. |
| **DPU_BS_BN** — DPU batch/scale/norm and LUT stages | **missing_rtl** | **none** | Supported: RK examples exercise BS/BN ALU/MUL/ReLU/PReLU, BRDMA/NRDMA inputs, four-input sums, 513-entry LUTs. rk_ew_regs.sv accepts BS_CFG/BN_CFG and related fields only at fixed no-op values as part of the all-or-none FP16 initialization group.<br>Not supported: No BS/BN add/mul/relu/prelu arithmetic, no BRDMA/NRDMA, no LUT, no nonzero EW scale/offset/shift. Nonzero BS/BN values in conv_mesa/simple_conv/elementwise_int are rejected by the strict decoder. |
| **RDMA_PC** — RDMA and PC command chain | **partial_supported_strict** | `rtl/rk_ew_dma.sv`<br>`rtl/rk_ew_regs.sv`<br>`rtl/rk_ew_engine.sv`<br>`rtl/cmac/rk_cmac_array_dma.sv`<br>`rtl/ddr/framework/rk_ew_async_engine.sv` | Supported: EW DMA fetches raw QWORDs from command memory, supports linked terminal EW tasks, next-address/amount tails and a task limit. One outstanding halfword memory request; A/B/D scalar reads and writes; 16-byte aligned bases.<br>Not supported: General DPU RDMA: surface line strides, ERDMA per-channel broadcast, BRDMA/NRDMA, multi-surface, FP32 operands, bursts. Vendor core_mask/subcore_task multi-core dispatch; CMAC linked PC chains (CMAC DMA is one terminal task). |

Evidence by block:

- **EW_FP16**: build/rk3588-kernel-comparison-v1: real Rocket capture + RTL simulation for ADD/SUB/MUL/NEG/MAX at N=8.; build/rk3588-example-captures/results/ew-fp16-20261105T201400Z: 45/45 supported-op logical PASS; 9 FDIV captured, 7 exact, 2 A/7 cases (20 halfwords) explained by the three-guard-bit ties-to-even contract, matching 1452/1452 real lanes.; build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z: 8 cases, 512 bytes, 256 operand classes; the 32-lane finite sweep and 256-class truth table are correctly rounded nearest-even, with no pass/fail oracle by design.
- **EW_INT**: build/rk3588-example-captures/results/ew-int-20261105T200154Z: 15/15 submit_ret=0 and masked oracle PASS.; int16_add_to_int32_c8_w1 is a 31-QWORD bundle; one zero fetch-padding QWORD is needed only for generic-runner replay.; docs/REVIEW_AND_PLAN.md lists quantized/integer paths as deferred.
- **PPU**: build/rk3588-example-captures/results/pooling-20261105T203205Z-host-analysis/comparison.json: 19/19 full-BO exact, 77,824 bytes.; grep of rtl/**/*.sv finds no PPU module.; docs/REVIEW_AND_PLAN.md: 'PPU ... remain deferred'.
- **CNA_CONV**: build/rk3588-example-captures/results/conv-fp16-20261105T222300Z: 9/9 exact, 35,392 bytes. The older 205900 tree retains only 2 now-BLOCKED combined captures (8,192 bytes) as task-1-all-zero evidence.; build/rk3588-example-captures/results/conv-gemm-vendor-20261105T214000Z plus results/conv-gemm-depthwise-rerun-20261105T221115Z: 10/10 PASS (8 exact, 2 tolerance), 95,744 bytes; depthwise 702/702 after the 15,104-byte BO fix.; build/rk3588-example-captures/results/conv-simple-20261105T215921Z: 7 captured, 4 exact + 3 known divergence (1 FP32 structural, 2 INT8 +1 LSB).; No rtl/ module implements CNA/CBUF/CSC/convolution.; docs/REVIEW_AND_PLAN.md lists general convolution as deferred.
- **CMAC_GEMM**: docs/CMAC_PROFILE_CANDIDATE.md and docs/FRAMEWORK_FULL_PROFILE.md.; docs/CMAC_PRODUCT_PATH.md: the product leaf is not instantiated by the EW DMA/host/board top.
- **DPU_BS_BN**: rtl/rk_ew_regs.sv: fixed 0x53/0x00/0x02 init values and no arithmetic.; docs/REVIEW_AND_PLAN.md lists LUT/activation/conversion modes as deferred.
- **RDMA_PC**: docs/PC_DMA.md and rtl/rk_ew_dma.sv.; rtl/cmac/rk_cmac_array_dma.sv comments: one terminal task for the CMAC controller.

## 5. Top five blocking gaps

### 1. CNA/CBUF/CSC convolution datapath is absent

The RTL has a CMAC array that consumes packed C32/K16 GEMM frames, but no CNA, CBUF, CSC, CDMA, im2col, pad, stride or convolution data-fetch engine. All 26 READY conv cases are captured: conv-fp16 9/9 exact, conv-gemm-vendor 10/10 PASS (8 exact, 2 tolerance), and conv-simple 4/7 exact plus 3 known divergences. The 13 BLOCKED cases are 3 vendor-ABI, 3 multi-task and 7 other shape/source. None can execute on the FPGA.

examples: 17; queue cases: 39; captured: 26; prepared: 0; blocked: 13.

Affected: `conv_gemm.py`, `conv_legacy.py`, `conv.py`, `conv_simple.py`, `conv_tiles.py`, `expt/conv_simple.py`, `kernel_6_18/conv_0522.py`, `kernel_6_18/conv_draft.py`, `kernel_6_18/conv_legacy.py`, `kernel_6_18/conv_mesa.py`, `kernel_6_18/conv_mesa_fp16.py`, `kernel_6_18/conv_new_clean.py`, `kernel_6_18/conv_new.py`, `kernel_6_18/conv_new_trscrs.py`, `kernel_6_18/conv.py`, `kernel_6_18/simple_conv.py`, `kernel_6_18/simple_conv_fp16.py`

Evidence: rtl/ has no CNA/CBUF/CSC/convolution module; docs/REVIEW_AND_PLAN.md lists general convolution as deferred; results/conv-fp16-20261105T222300Z, results/conv-gemm-vendor-20261105T214000Z, results/conv-gemm-depthwise-rerun-20261105T221115Z and results/conv-simple-20261105T215921Z are the current receipts

### 2. PPU pooling is absent

No PPU or PPU_RDMA RTL exists. The 19 READY pooling bundles are captured on RK3588 Rocket with 19/19 full-BO exact comparisons and 77,824 captured bytes, but none can execute on the FPGA. The two BLOCKED FP32/INT32 probes were not run. The kernel_6_18/conv.py PPU 'separator' record is not a pool operation and its semantics are unknown.

examples: 3; queue cases: 21; captured: 19; prepared: 0; blocked: 2.

Affected: `pooling.py`, `expt/pooling.py`, `kernel_6_18/conv.py`

Evidence: grep of rtl/**/*.sv finds no PPU module; docs/REVIEW_AND_PLAN.md lists PPU as deferred

### 3. Integer EW and DPU BS/BN/LUT arithmetic are absent

15 ew-int cases are verified on RK3588 Rocket, but the FPGA ALU is FP16-only. The 3-case INT8 conv family is also captured: 2 INT8 cases show +1 LSB output-conversion divergences, 1 addition-input case is BLOCKED. rk_ew_regs accepts BS/BN fields only as fixed no-op initialization; there is no integer saturation, BS/BN ALU/MUL/ReLU/PReLU, BRDMA/NRDMA or LUT path.

examples: 5; queue cases: 21; captured: 17; prepared: 0; blocked: 4.

Affected: `expt/elementwise_int.py`, `kernel_6_18/conv_mesa.py`, `kernel_6_18/conv_mesa_fp16.py`, `kernel_6_18/elementwise_int.py`, `kernel_6_18/simple_conv.py`

Evidence: rtl/rk_fp16_alu.sv is half-precision only; rtl/rk_ew_regs.sv fixes DATA_FORMAT to 0x48000002 and BS/BN init to fixed no-op values; results/ew-int 15/15 verified on RK

### 4. FDIV is captured on RK but has no RTL

FDIV is captured in 9 ew-fp16 cases and the 8-case, 256-class fdiv-systematic truth table. The 32-lane finite sweep and the 256-class truth table are correctly rounded nearest-even. The EW FP16 A/7 cases fdiv_p1_n33 and fdiv_p1_n1024 are the known divergence: 20 halfwords differ, explained by the three-guard-bit ties-to-even contract, which matches 1452/1452 real lanes. Do not model the divider as globally truncating toward zero. rk_ew_regs still rejects EW_CFG 0x108303c0 with error 2, and rk_fp16_alu has no divide operation.

examples: 1; queue cases: 17; captured: 17; prepared: 0; blocked: 0.

Affected: `elementwise.py`

Evidence: build/rk3588-kernel-comparison-v1 real-rocket-fdiv8* captures; results/fdiv-systematic-20261105T204746Z (8 cases, 512 bytes, 256 classes, oracle none); rtl/rk_ew_regs.sv rejects FDIV EW_CFG; rtl/rk_fp16_alu.sv implements only ADD/SUB/MUL/MAX

### 5. Vendor RKNPU ABI and multi-core/PC-chain submission are not implemented

Eight examples use /dev/dri/card1 and DRM_IOCTL_RKNPU_*; expt/conv_simple.py defaults to that path. Rocket/FPGA has no core_mask/subcore_task fields, no RKNPU job ABI and no PC_BASE_ADDRESS self-address patch in the bundle schema. This blocks direct execution and three bundles: conv_tiles.py, plus conv.py's BY_K and H40 cases.

examples: 9; queue cases: 3; captured: 0; prepared: 0; blocked: 3.

Affected: `conv_gemm.py`, `conv_legacy.py`, `conv.py`, `conv_simple.py`, `conv_tiles.py`, `elementwise.py`, `gemm.py`, `simple_add.py`, `expt/conv_simple.py`

Evidence: examples/kernel_6_18/README.md documents the vendor-to-Rocket port; conv-fp16/conv-gemm-vendor BLOCKED reasons; docs/PC_DMA.md limits the FPGA PC chain to raw EW tasks

## 6. Additional gaps and unknowns

- **CMAC/GEMM is only a strict FP16 C32/K16 terminal profile** (4): gemm.py's four captured cases use small shapes and default FP32 output. The CMAC RTL requires physically packed operands, 32-multiple channels, rows 1..2047, FP16 output and no activation. General GEMM, runtime gathers and FP32 output remain missing.
- **General DPU RDMA/layout is missing** (many cases across ew-int, conv, BS/BN): No ERDMA per-channel broadcast, BRDMA/NRDMA, surface strides, multi-surface or FP32 operand path. EW scalar A/B/D works only for the strict contiguous profile. This is an underlying limitation for the integer/BS-BN/conv examples even after their arithmetic is added.
- **Blocked queue cases split across ABI, dtype/shape, multi-task and integrity** (18): 12 cases are blocked by unsupported dtype/shape or missing source evidence (SAME pad, stride-2 FP16, C8 unpadded packing, grouped FP16, split-K, INT32 DIV, FP32/INT32 PPU, addition-input conv); 3 are blocked by the vendor/multi-core ABI; 3 are combined multi-task jobs (depthwise and conv-fp16 grouped/split-OC) where Rocket completes only task 0, each split into READY one-task cases; 0 current runner-invalid.
- **Unknown semantics** (10): 10 examples carry explicit unknown notes. Three contracts are especially important: conv_draft.py has an inconsistent FP16/FP32 output contract; conv_0522.py split-K/tile offsets are unproven; kernel_6_18/conv.py's PPU 'separator' record has unknown semantics. These are marked unknown, not supported.

Explicit unknowns:

- `conv.py`: Direct-spatial template tables are described as RKNN-observed templates, not a general tiling compiler.
- `elementwise.py`: The FP32 output path is real on RK but not implemented by the FPGA EW slice; its timing-sensitive polling loop is not a hardware contract.
- `gemm.py`: Whether every emitted task fits the CMAC profile's physical channel/row rules without padding is not established by the example.
- `simple_add.py`: No bundle and no direct RTL replay of this exact minimal stream.
- `expt/conv_simple.py`: The --rocket-rgb path is a separate re-hosting path from the default vendor submission.
- `expt/pooling.py`: PPU DPU-flying input (FLYING_MODE=0) is register-defined but not silicon-proven by this script.
- `kernel_6_18/conv_0522.py`: Tile-offset handling and split-K accumulation contract are unproven.
- `kernel_6_18/conv_draft.py`: Output dtype/unpack contract is inconsistent; no bundle and no trusted oracle.
- `kernel_6_18/conv_mesa_fp16.py`: FP16 pad-register semantics are not validated by the bundled sources.
- `kernel_6_18/conv.py`: PPU separator record semantics in the direct-spatial stream are unknown and not modeled by RTL.

## 7. What is actually verified

| Evidence level | What it covers | What it does not cover |
|---|---|---|
| Real RK3588 Rocket capture | 122 cases: 54 ew-fp16 (52 exact + 2 known), 15 ew-int exact, 19 pooling exact, 8 fdiv truth table, 9 conv-fp16 exact, 10 conv-gemm-vendor (8 exact + 2 tolerance), 7 conv-simple (4 exact + 3 known). | Not FPGA, not vendor RKNPU, not SystemVerilog |
| RTL simulation | EW FP16 ADD/SUB/MUL/MAX/NEG8 and special matrices in `build/rk3588-kernel-comparison-v1` | Not the full captured queues, not physical FPGA, not timing closure |
| Prepared bundles | 0 runner-valid READY cases remain; all 122 READY cases are captured | Not applicable |
| Blocked cases | 18 manifest BLOCKED; 0 current runner-invalid | No bundle may be submitted |
| RTL block support | EW FP16 strict, CMAC strict partial, RDMA/PC strict partial | No CNA/conv, PPU, EW INT, BS/BN/LUT, FDIV |

## 8. Caveats

- READY is a bundle-preparation state, not a device result. All 122 READY cases now have real RK3588 Rocket captures; 0 remain prepared and 18 are manifest BLOCKED.
- The 122 captures are RK3588 Rocket behavior, not FPGA execution. No FPGA run of any bundle in this queue is recorded here.
- Exact/tolerance split: 107 exact PASS, 2 tolerance-only PASS (conv-gemm GEMM m4n32k64 and conv.py full-setup), 5 known divergences, 8 fdiv-systematic truth-table cases, 0 unverified. The 18 BLOCKED cases are 3 ABI, 12 dtype/shape/oracle and 3 multi-task.
- ew-int is 15/15 verified. int16_add_to_int32_c8_w1 is a 31-QWORD bundle that needs one zero fetch-padding QWORD only for generic-runner replay.
- ew-fp16 has 54 captures: 52/54 match the donor oracle exactly. The two A/7 cases fdiv_p1_n33 and fdiv_p1_n1024 differ on 20 halfwords; the three-guard-bit ties-to-even contract explains them and matches 1452/1452 real lanes. This is a known divergence from the donor oracle, not global truncation.
- pooling is 19/19 full-BO exact over 77,824 bytes; the 2 blocked FP32/INT32 probes were not run. fdiv-systematic is 8/8 captured, 512 bytes and 256 operand classes, with oracle none by design.
- conv-fp16 is now split: 9/9 READY cases are captured and exact (35,392 bytes) after the multi-task cases were promoted to one-task _task0/_task1 bundles. The 5 BLOCKED cases (2 combined multi-task, pad-register, split-K, vendor ABI) were not run.
- conv-gemm-vendor is 10/10 PASS (80,640 bytes before the depthwise BO fix; 95,744 bytes counting the 15,104-byte depthwise rerun): 8 exact and 2 tolerance-only. The depthwise _task0/_task1 rerun is 702/702 exact after the 15,104-byte BO fix.
- conv-simple is 4/7 exact, 1 FP32-output C32 structural placement/zero-fill mismatch, and 2 INT8 +1 LSB output-conversion divergences. These are known divergences, not exact passes.
- The queue-index team snapshot is stale for this census: it still lists runner-invalid and prepared counts that the current job fixes and captures supersede.
- The conv-fp16-task-diagnostic result tree is task-level diagnostic evidence, not a separate case capture; it is excluded from the current conv-fp16 count to avoid double counting.
- The capture results are consumed as host-side receipts. This census did not re-audit the board run, oracle implementation or result hashes independently.
- C++/Python/RTL simulation and RK capture do not validate SystemVerilog timing, the physical FPGA or a new image. No bitstream or flash action is implied.

Method and file-level notes are in `README.md`; the machine-readable form is `EXAMPLE_MATRIX.json`.

