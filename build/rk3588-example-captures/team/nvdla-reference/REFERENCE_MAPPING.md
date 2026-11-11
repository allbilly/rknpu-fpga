# RKNPU ↔ ZYNQ-NVDLA reference mapping

Reference: `/home/fedora/ZYNQ-NVDLA`, commit
`3f1bc4c36c6737d5873f8c1833dffac9322387a0`.
NVDLA sources retain the NVIDIA NVDLA Open Hardware License headers; the
existing `rtl/vendor/nvdla/` tree is the precedent for any copied file.

## Verdict

- **RK PPU is a direct NVDLA PDP alias.** The RK PPU register offsets at base
  `0x6000` match NVDLA PDP offsets at base `0xb000` in the low 12 bits.
  RK PPU_RDMA at base `0x7000` matches NVDLA PDP_RDMA at base `0xa000`.
- **The full NVDLA core does not fit this FPGA.** The reference's own
  `RK_NVDLA_PACKING_COMPARISON_20261029.md` records a placement failure of
  3,138 slices for the C32/K32 INT8 1,024-MAC core. The accepted RK image
  already occupies 99.82% of slices. Do not import the full core.
- **The viable path is selective reuse**: start with a pruned PDP/PDP_RDMA for
  pooling, then decide CNA/CDMA, CORE/CACC and DPU/SDP individually with
  measured resource results.

## Evidence: pooling command stream is a PDP program

Example `fp16_avg_k2s1_valid_c8_h4w4` (28 QWORDs):

| RK target/offset | Value | NVDLA PDP address | Field |
|---|---:|---|---|
| `0x4001/0x6004` | `0xe` | `0xb004` | S_POINTER |
| `0x4001/0x600c` | `3` | `0xb00c` | DATA_CUBE_IN_WIDTH |
| `0x4001/0x6010` | `3` | `0xb010` | DATA_CUBE_IN_HEIGHT |
| `0x4001/0x6014` | `7` | `0xb014` | DATA_CUBE_IN_CHANNEL |
| `0x4001/0x6018` | `2` | `0xb018` | DATA_CUBE_OUT_WIDTH |
| `0x4001/0x601c` | `2` | `0xb01c` | DATA_CUBE_OUT_HEIGHT |
| `0x4001/0x6020` | `7` | `0xb020` | DATA_CUBE_OUT_CHANNEL |
| `0x4001/0x6024` | `0x10` | `0xb024` | OPERATION_MODE_CFG (average) |
| `0x4001/0x6034` | `0x101` | `0xb034` | POOLING_KERNEL_CFG (2x2) |
| `0x4001/0x6038` | `0x7800` | `0xb038` | RECIP_KERNEL_WIDTH |
| `0x4001/0x603c` | `0x7800` | `0xb03c` | RECIP_KERNEL_HEIGHT |
| `0x4001/0x6040` | `0` | `0xb040` | POOLING_PADDING_CFG |
| `0x4001/0x6044` | `0` | `0xb044` | PADDING_VALUE_1 |
| `0x4001/0x6048` | `0` | `0xb048` | PADDING_VALUE_2 |
| `0x4001/0x6070` | dst | `0xb070` | DST_BASE_ADDR |
| `0x4001/0x607c` | `0x90` | `0xb07c` | DST_SURFACE_STRIDE |
| `0x4001/0x6084` | `0x92` | `0xb084` | DATA_FORMAT |
| `0x4001/0x60dc` | `3` | `0xb0dc` | MISC_CFG |
| `0x8001/0x7004` | `0xe` | `0xa004` | PDP_RDMA S_POINTER |
| `0x8001/0x7008` | `1` | `0xa008` | PDP_RDMA OP_ENABLE |
| `0x8001/0x700c` | `3` | `0xa00c` | PDP_RDMA IN_WIDTH |
| `0x8001/0x7010` | `3` | `0xa010` | PDP_RDMA IN_HEIGHT |
| `0x8001/0x7014` | `7` | `0xa014` | PDP_RDMA IN_CHANNEL |
| `0x8001/0x701c` | src | `0xa01c` | PDP_RDMA SRC_BASE_ADDR |
| `0x8001/0x7024` | `0x40` | `0xa024` | PDP_RDMA SRC_LINE_STRIDE |
| `0x8001/0x7028` | `0x100` | `0xa028` | PDP_RDMA SRC_SURFACE_STRIDE |
| `0x8001/0x7030` | `2` | `0xa030` | PDP_RDMA DATA_FORMAT (FP16) |
| `0x0081/0x0008` | `0x60` | PC enable | PPU operation trigger |

Pooling method values match NVDLA PDP: `0` average, `1` maximum, `2` minimum.
The two missing pieces are:

1. RK never writes `0x6008` (NVDLA PDP `D_OP_ENABLE`). The bridge must
   synthesize that write when the PC `0x60` trigger arrives, or derive it from
   `PDP_RDMA OP_ENABLE`.
2. RK `INDEX_EN` has no obvious NVDLA PDP field. The index case may need
   separate position tracking or an SDP-side path; do not claim it until the
   capture is matched.

## Block-level mapping

| RK block | NVDLA reference | Register-map relation | Reuse verdict |
|---|---|---|---|
| PPU | PDP | exact low-12 alias | drop-in wrapper candidate |
| PPU_RDMA | PDP_RDMA | exact low-12 alias | drop-in wrapper candidate |
| CNA | CSC + CDMA | same block family, reorganized fields | field crosswalk required |
| CORE | CACC | subset; `+4` shift after S_POINTER because RK omits `D_OP_ENABLE` | close, crosswalk required |
| DPU | SDP | same BS/BN/EW datapath family, reorganized fields | field crosswalk required |
| RDMA | SDP_RDMA | dimensions/src base match; BS/BN/EW fields differ | field crosswalk required |
| CMAC | CMAC | internal arithmetic family | existing partial reuse in `rtl/cmac` |
| CACC | CACC | internal accumulator family | existing partial reuse in `rtl/cmac` |

## Field crosswalk result (2026-11-06)

The strict “same RTL, different register names” hypothesis is **disproved**.
Of 62 decoded fields, only four are true aliases: RDMA cube width/height/
channel and `SRC_BASE` low (`0x500c/10/14/18` → `0x800c/10/14/18`). The rest
are 18 renamed/relocated, 17 repacked, 13 semantically different and 10 RK-only.
The detailed tables and decoded QWORDs are in `team/nvdla-crosswalk/FIELD_CROSSWALK.md`
and `FIELD_CROSSWALK.json`.

Concrete counterexamples:

- **CNA** is a merged, reduced CSC + CDMA surface. `DATA_SIZE0=0x00080008`
  versus NVDLA `0x00070007`; the asymmetric depthwise capture
  `0x001c000b` (H=11, W=28) versus the NVDLA-shaped `0x000a001b` proves the RK
  width-high/height-low actual-count packing is swapped and off by one.
  `WEIGHT_SIZE2=0x03030020` packs kw/kh/kernels that NVDLA splits into two
  weight-size registers. RK `DMA_CON1/2` are 32-byte-unit strides; NVDLA
  line/surface strides are byte-addressed.
- **CORE** is a compacted CACC subset, not a fixed shift. `DATAOUT_SIZE` and
  clip truncation map cleanly, but `MISC_CFG=0x201` puts RK `is_spatial`
  where CACC has `conv_mode` (a literal copy would select Winograd), CLIP is
  at `0x301c` versus CACC `0x702c`, and `0x3030` is CACC's read-only
  saturation status.
- **DPU** shares cube dimensions and BS/BN config, but `FEATURE_MODE_CFG=0x1E5`
  decodes in SDP as flying/Winograd/batch, `EW_CFG` uses a 3-bit opcode at
  `[18:16]` with SUB=4 and FDIV=3 while SDP has a 2-bit ALU opcode at `[3:2]`
  with no SUB/FDIV, and `DATA_FORMAT=0xA8000002` selects OUT_PRECISION=5
  (FP32), which SDP cannot represent.
- **RDMA** aliases only the cube dimensions and source base. The captured
  `FEATURE_MODE_CFG=0x17849` copies as proc=0/batch=24, `ERDMA_CFG=0x40000008`
  copies as data_use=MUL/data_mode=0, and `RDMA_WEIGHT=0x01010101` collides
  with `EW_SURFACE_STRIDE`.
- The `nv_small_256` RTL build **compiles out the SDP EW stage**
  (`NVDLA_SDP_EW_THROUGHPUT=0`, `cfg_ew_en=0`) and does **not instantiate
  ERDMA** (`erdma_disable=1`, only BRDMA/NRDMA). RK's captured FP16
  elementwise path therefore cannot be reused from that build without new RTL
  or a different NVDLA generation configuration.

Per-block verdicts:

| Block | Verdict |
|---|---|
| CNA | adapter + datapath changes: CVT path, CBUF geometry, 32-byte-unit/4-row stride addressing |
| CORE | pure adapter for the accumulator/output-size subset; repack MISC and synthesize output strides |
| DPU | adapter + datapath: the reference SDP EW stage is compiled out; SUB/FDIV and FP32 output are missing |
| RDMA | adapter + datapath: ERDMA is not instantiated; only MRDMA cube/source fields are a pure adapter |
| PPU | exact PDP/PDP_RDMA alias; still the clean reuse candidate |

The deeper scan is important: RK CNA looks like a merged CSC + CDMA block, but
the field order is not an alias. For example:

- RK CNA `DATA_SIZE0` at `0x1020` lands on NVDLA CSC `D_POST_Y_EXTENSION`,
  not a data-size field.
- RK CNA `FEATURE_DATA_ADDR` at `0x1070` lands on NVDLA CDMA
  `D_WEIGHT_SIZE_1`, not a feature address.
- RK CORE `0x3010/0x3014/0x3018/0x3030` line up with CACC
  `0x700c/0x7010/0x7014/0x702c` once the omitted `D_OP_ENABLE` at `0x7008` is
  accounted for.
- RK DPU `FEATURE_MODE_CFG` at `0x400c` is NVDLA SDP
  `D_FEATURE_MODE_CFG` at `0x90b0`, not a low-offset alias.
- RK RDMA `0x500c/0x5010/0x5014/0x5018` match SDP_RDMA
  `0x800c/0x8010/0x8014/0x8018`, but `0x5034/0x5038/0x5044` are RK BS/EW
  fields, not the NVDLA BS line/surface stride and BN base fields at those
  addresses.

So the correct statement is: **the block decomposition is largely NVDLA, but
only PPU/PDP is currently a drop-in register alias.** CNA/CORE/DPU/RDMA need a
field-level crosswalk and capture-driven tests before any RTL is copied.

## Resource and timing

From the reference and the accepted RK image:

| Metric | Full NVDLA C32/K32 INT8 | Accepted RK full512 FP16 |
|---|---:|---:|
| LUTs | ~295,576 (board) / 228,287 (core) | 292,430 routed |
| FFs | 311,927 (board) / 242,238 (core) | 66,506 |
| DSPs | 1,430 | 516 |
| BRAM tiles | 291.5 | 0 |
| Placement | failed, 3,138 slices short | legal, 99.82% slices |

The full NVDLA core cannot be dropped into the current board profile. A
PDP-only pruned configuration is much smaller, but its actual LUT/FF/BRAM cost
must be measured before integration. The reference's `nv_small_256` and
`nv_1024` variants show the generation/pruning flow; the 1,024-MAC 50 MHz
image passed full TinyStories physically.

## PDP prototype result (2026-11-06)

A 42-file PDP/PDP_RDMA prototype with an RK PPU→CSB bridge and a behavioral
MCIF memory model is under `build/ppu-pdp-prototype/`. All four faithful
replays reached `pdp_done=1` with zero CSB errors and the exact device-patched
regcmd hash, but the numerical outputs do not match:

- the reference `nv_small_256` PDP is an **INT8/BPE=8, 8-byte-atom** build;
- RK PPU uses **16-byte atoms** (8 FP16 or 16 INT8 channels);
- the reference PDP's FP16 sum helpers are present but not instantiated, and
  its max/min paths are signed-integer comparisons;
- an explicitly labelled INT8 layout-adapted control matches the device
  exactly, proving the bridge and INT8 datapath are correct.

The bridge also had to synthesize NVDLA-only fields: `PDP D_DST_RAM_CFG=1`,
`PDP D_DST_LINE_STRIDE`, `PDP_RDMA D_SRC_RAM_CFG=1`, and the PDP_RDMA copies
of the kernel/operation registers. RK `PPU_MISC_CTRL` has no PDP equivalent and
is classified RK-only.

The generator supports the required branch:
`FEATURE_DATA_TYPE_INT16_FP16` sets `NVDLA_BPE=16` in `projects.spec`. A
BPE=16/128-bit-atom PDP was generated under `build/ppu-pdp-bpe16/` and the
FP16 arithmetic paths were enabled:

- **FP16 max, average, min, negative-padded max and global average: exact**,
  full 4,096-byte BOs, max diff 0;
- **INT16 max/average/min controls: exact**;
- 16-byte atom output and the three 16-byte write beats are correct;
- **only `INDEX_EN` metadata remains**: six bytes differ in the index case;
  the max values match, but NVDLA PDP has no position-output field. This is an
  RK-only feature gap, not FP16 arithmetic;
- the `+SKIP_SYNTH` control still times out with no read/write traffic,
  confirming the synthesized NVDLA-only fields are required.

RTL changes in the prototype: `reg2dp_input_data` is connected through the PDP
top/core/cal1d/unit1d instances; the reference `cal1d_fp16_pool_sum` is
instantiated for FP16 average; `pdp_fp16_add/mul/max/min` and FP16↔FP17 helpers
are selected for FP16; FP16 NaN/Inf detection and optional flush/counters are
enabled. INT16 retains the original integer path.

Two generator bugs were fixed in the copied tree: the PDP_RDMA reorder FIFO
used the 64-bit primary width instead of the 128-bit interface, and the DMAIF
write ack bit tested bit 77 instead of the 46-bit command packet.

Remaining before tracked integration: measure synthesis/resource/timing and
fit; replace the prototype's eight 4-lane HLS adders with an efficient FP16
path; implement RK `INDEX_EN` position metadata separately; add the
MCIF-to-AXI/DDR bridge; add tracked tests and a physical differential.

## OOC synthesis and fit result (2026-11-06)

Vivado 2026.1, `xc7k480tffg1156-2`, top `ppu_pdp_bpe16_ooc_top`:

| Metric | Routed result |
|---|---:|
| LUTs | 39,636 (13.27%) |
| FFs | 21,068 (3.53%) |
| DSP48E1 | 35 (1.82%) |
| BRAM | 6 tiles (2 RAMB36 + 8 RAMB18) |
| Latches / black boxes | 0 / 0 |
| 100 MHz | WNS **−15.068 ns**, TNS −8,017 ns, 3,010 failing endpoints |
| 50 MHz | WNS **−5.366 ns**, TNS −272.7 ns, 169 failing endpoints |
| Hold / pulse | passes at both clocks |
| Routing | fully routed, 0 errors |
| DRC | 0 errors/critical, 209 warnings |

The worst path is the `cal2d` FP16 reciprocal multiply/normalize path:
24.970 ns data delay, 82 logic levels. The `cal2d → cal1d` ready/backpressure
path and an HLS `HLS_fp17_add` path also fail.

Fit verdict:

- **PDP + bridge alone:** fits resource, not timing.
- **Full existing `ypcb_ddr_dual_top` shell:** does not fit — 292,430 shell
  LUTs + 39,636 PDP = 332,066, which is 33,466 over the 298,600 device.
- **Shell without the 260,398-LUT compute engine:** 71,668 LUTs total,
  leaving 226,932 LUTs. This is resource room only; placement, MCIF/AXI cost,
  clocking and timing are unmeasured.

The NVDLA PDP is therefore a **numerical oracle and register-bridge proof**,
not a drop-in for the current shell. A viable integration needs either a
pipelined/retimed PDP plus a major shell repartition, or a different pruned
NVDLA core as the compute engine. The current shell cannot host it alongside
the existing CMAC.

One synthesis-only adaptation is documented: the unbounded
`while (!norm[10])` loop in `pdp_fp16_to_fp17` was replaced by an equivalent
constant-bound 11-iteration loop. The original failure is preserved; no formal
proof or numerical re-simulation was performed for that rewrite.

## Interface work for a PDP prototype

- RK command stream → NVDLA CSB/APB: address = NVDLA base + `(RK offset & 0xfff)`;
  translate the RK PPU and PPU_RDMA targets to PDP/PDP_RDMA.
- Synthesize `PDP D_OP_ENABLE` from the PC `0x60` trigger (or tie to PDP_RDMA
  op_en after verifying the PDP register-file requirement).
- NVDLA MCIF 64-bit memory interface → the board's AXI/DDR path: reuse the
  reference `nocif`/`NV_NVDLA_MCIF` adapter or write a minimal MCIF-to-AXI
  bridge.
- Map `PPU_DATA_FORMAT=0x92` and `PPU_RDMA_DATA_FORMAT=2` to NVDLA PDP
  `DATA_FORMAT` fields; verify FP16, INT8 and INT16 captures.
- Preserve the NVDLA license headers and record the reference commit/file
  hashes for every copied file.

## Recommended first increment

Build a **PDP pooling prototype** under `build/ppu-pdp-prototype/`, not tracked
RTL:

1. Extract `NV_NVDLA_pdp`, `NV_NVDLA_PDP_RDMA`, and their local dependencies
   from the reference; preserve headers.
2. Add an RK PPU/PDP register bridge and the PC trigger mapping.
3. Connect the PDP memory interface to a behavioral AXI/DDR model.
4. Replay the 19 real pooling captures in order: FP16 max valid, FP16 average,
   padding, INT8/INT16, then INDEX_EN separately.
5. Compare full output BOs, not just the logical region.
6. If it fits and matches, integrate as `rtl/ppu/` with tests and a fresh
   image; if not, report the measured resource/timing reason without weakening
   constraints.

This is the shortest route from the NVDLA reference to a new RK-supported block.
