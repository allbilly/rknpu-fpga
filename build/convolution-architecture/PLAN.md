# Convolution architecture and staged implementation plan

Status: **architecture plus the capture-backed Gate 1A RTL increment** for
`conv_1x1_valid_c8_h5_w5_oc8`. The implemented slice accepts the original raw
54-QWORD task and captured BO layouts; no board, bitstream, full-top Vivado,
other convolution shape, or RK silicon claim is made. The execution boundary
stays the raw final command QWORD stream; no tensor-operation shortcut and no
runtime CPU layout repair is proposed.

Evidence base:
`rknpu-fpga@a9b5d02` (this worktree, on top of main),
RK3588 example source `rk3588@273d015e08af40c81d2cd9ab84198486b03a17f1`,
NVDLA reference `/home/fedora/ZYNQ-NVDLA@3f1bc4c36c6737d5873f8c1833dffac9322387a0`.
Capture families: `conv-simple`, `conv-fp16`, `conv-gemm-vendor`.
Team reports: `team/gap-matrix/GAP_MATRIX.md`,
`team/nvdla-crosswalk/FIELD_CROSSWALK.md`,
`team/nvdla-reference/REFERENCE_MAPPING.md`.

Gate 1A source was developed in the isolated worktree based at
`rknpu-fpga@9c00eeb`; the local run report records that base revision and
content hashes for the actual RTL, testbench, runner and frozen BO/QWORD inputs.

## 0. Executive answer

1. A first minimal engine can cover **four READY 1x1, valid, single-group,
   FP16 conv cases** (C1/C4/C8/C32, OC6/OC8/OC16/OC32), with the C8/OC8 case as
   the primary target. INT8 is **not** coverable by the existing FP16 CMAC
   slice: there is no integer MAC/CACC and no captured INT8 1x1 case. All
   3x3/5x5, stride, padding, depthwise, grouped, split-OC and split-K cases
   require the spatial CNA/CSC class (and, for some, multi-task or split-K
   accumulation).
2. The exact first-case layouts and their mapping to the K8 front's OC16
   weight traversal are in section 2. The captured BOs are read unchanged;
   the IC32/OC16 expansion is done in hardware, not by the CPU.
3. CNA/CBUF/CSC responsibilities and the minimal first implementation are in
   section 3. The first engine is a conv-specific front feeding the existing
   C32 CMAC/CACC leaves; the K8 GEMM output-atom schedule is **not** reused.
4. Area/test estimates and the NVDLA reuse split are in section 4. The
   **39.6K-LUT PDP result is not a convolution design estimate** and must not
   be used as one.
5. The one-feature-at-a-time sequence with gates is in section 5: first case,
   then stride/pad, then 3x3/5x5, then depthwise/grouped/split-OC/split-K.

## 1. Answer 1: captured-case coverage

### 1.1 Inventory

The three capture families contain **35 conv entries** (22 READY, 13 BLOCKED)
plus four READY GEMM entries in `conv-gemm-vendor` that are out of scope here.
This is consistent with the GAP matrix's 39 conv/GEMM cases (26 READY / 13
BLOCKED): 22 conv READY + 4 GEMM READY = 26.

| Family | Conv entries | READY | BLOCKED |
|---|---:|---:|---:|
| `conv-simple` | 12 | 7 | 5 |
| `conv-fp16` | 14 | 9 | 5 |
| `conv-gemm-vendor` (conv only) | 9 | 6 | 3 |
| **Total** | **35** | **22** | **13** |

The machine-readable matrix is `CONV_MATRIX.json`. It classifies every entry by
engine gate, required blocks, first-engine coverage, and blocker.

### 1.2 First minimal engine envelope

Envelope: 1x1, stride 1, pad 0, groups 1, FP16 input/weight, real C <= 32,
real OC <= 16 (with OC32 as two OC16 blocks), output either FP16
(`c2=8`) or FP32 (`c2=4`). All captured candidates are READY and exact on RK
except the known C32 FP32 structural divergence.

| Case | Shape | Output | First engine? | Notes |
|---|---|---|---|---|
| `conv_1x1_valid_c8_h5_w5_oc8` | C8 5x5 -> OC8 5x5 | FP16 | **Yes, primary (gate 1A)** | Exact RK capture; one OC8 half of one OC16 block; ideal first target. |
| `conv_1x1_c1_oc6_h4w4` | C1 4x4 -> OC6 4x4 | FP16 | Yes (gate 1C) | NHWC C1 input variant; OC6 padded to 8/16; exact RK capture. |
| `conv_simple_fp16_1x1_c4_h8_w8_oc16` | C4 8x8 -> OC16 8x8 | FP32 | Yes (gate 1B) | NHWC C4 input; full OC16 block; requires FP32 atom writer; exact RK capture. |
| `conv_simple_fp16_1x1_c32_h8_w8_oc32` | C32 8x8 -> OC32 8x8 | FP32 | Yes, with caveat (gate 1B) | Two OC16 blocks; C32 needs no IC pad; RK capture has a known FP32-output structural placement/zero-fill divergence. Do not use as an exact oracle. |

No captured INT8 1x1 case exists. The INT8 5x5 and INT8 depthwise cases need
both a spatial front and an integer MAC/CACC; they are not first-engine cases.

### 1.3 What requires the spatial CNA/CSC class

Every case with `kh>1` or `kw>1` needs feature rows to be retained/reused and a
kh/kw traversal. Small cases need only a `kh`-row line buffer, not the full
12-bank RK CBUF; large/tiled cases need bank reuse and capacity checks.

| Feature class | READY representative cases | Why the 1x1 engine is insufficient | Gate |
|---|---|---|---|
| 3x3/5x5 valid, single group | `conv_3x3_valid_c4_h9_w9_oc4`, `conv_legacy_3x3_c4_oc4_h9w9`, `conv_simple_fp16_3x3_c4_h8_w8_oc16`, `conv_simple_fp16_5x5_c4_h8_w8_oc16`, `conv_simple_fp16_3x3_c16_h8_w8_oc32`, `conv_py_3x3_c32_oc128_h14w14_fullsetup` | kh/kw window, kh-major weight order, row reuse, output atom stride | 3 |
| stride 2 | `conv_3x3_stride2_c4_h11_w11_oc4` | input row/column skip and output geometry | 2 |
| explicit zero-frame pad | `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | 3-row window sees a zero border; no `CNA_PAD_CON0` required | 2 |
| depthwise | `conv_depthwise_3x3_c3_h11_w28_oc3`, `conv_depthwise_3x3_c3_oc3_h11w28_task0/1` | spatial-major single-channel weights, per-channel dot product | 4 |
| grouped, single-task captured | `conv_grouped_3x3_c4_oc4_g2_h5w5` | group-aware C/OC slicing and grouped weight block order | 4 |
| grouped, promoted one-task | `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0/1` | each promoted task is a plain C2/OC4 3x3; the parent needs multi-task | 4 |
| split-OC, promoted one-task | `conv_splitoc_3x3_c16_h9_w9_oc16_task0/1` | each promoted task is a plain C16/OC8 3x3; the parent needs multi-task | 4 |
| INT8 5x5 / depthwise | `simple_conv_int8_5x5_c8_h8_w8_oc32`, `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` | spatial front plus integer MAC/CACC, zero points, bias and quantized output | 5 |
| split-K | `conv_split_k_reduction_blocked` (no READY bundle) | partial-K accumulation across tasks is not defined by any READY capture | 5 |

Important distinctions:

- **Grouped is not only multi-task.** `conv_grouped_3x3_c4_oc4_g2_h5w5`
  is a single-task READY grouped capture in `conv-gemm-vendor`; it needs a
  group-aware spatial engine. The `conv-fp16` grouped parent is blocked only
  because Rocket executed task 0 of a two-task job; its promoted one-task
  children are plain single-group 3x3 tasks.
- **Split-OC is not arithmetic.** The promoted split-OC children are plain
  3x3 tasks with OC8. The unsupported part is the single-job split-OC
  scheduling/PC chain, not the MAC.
- **Split-K is not "more tasks".** It needs an accumulator persistence or
  output read-modify-write contract. The source clears the output BO per tile
  and leaves tile offsets at zero, so the current captures do not define it.
- **True `CNA_PAD_CON0` FP16 padding is BLOCKED.** The READY padded case is an
  explicit zero frame. Do not claim pad-register support from it.

### 1.4 Blocked/unsupported entries

| Blocker | Entries | Consequence |
|---|---|---|
| Source/ABI/shape | `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2`, `..._samepad`, `..._unpadded_pack`, `simple_conv_int8_addition_c8_h8_w8_oc32` | The named source does not encode the feature. Do not invent registers. |
| Multi-task | `conv_grouped_3x3_c4_h5_w5_oc8_g2`, `conv_splitoc_3x3_c16_h9_w9_oc16`, `conv_depthwise_3x3_c3_oc3_h11w28` (parent) | Use promoted one-task cases; full single-job feature needs a PC chain. |
| Pad register | `conv_3x3_pad_register_fp16_blocked` | No Rocket-capable FP16 pad register evidence. |
| Split-K | `conv_split_k_reduction_blocked` | No accumulator contract. |
| Vendor/multi-core | `conv_tiles_vendor_abi_blocked`, `conv_byk_c160_h14w14_oc320_k3x3`, `conv_h40_c160_h40w40_oc320_k3x3` | Vendor `core_mask`/`subcore_task` and self-referential PC rows are outside the current ABI. |

## 2. Answer 2: exact first-case layouts

### 2.1 Selected first case

**`conv_1x1_valid_c8_h5_w5_oc8`** from `conv-fp16`:
FP16 1x1 valid, C8 H5 W5 -> OC8 5x5, stride 1, groups 1, FP16 output.
It is a READY, exactly matched RK capture (9/9 exact family).

Case files and hashes (from the manifest and the result tree):

| File | Bytes | SHA-256 |
|---|---:|---|
| `a.bin` (packed input) | 800 | `fa1cfc610a9d473bbef852dac62bef6d63f67727b0d8a20587962b0418739c71` |
| `w.bin` (packed weight) | 256 | `52a1b39b6ef32d87bed51b67d32b67073f2aefae3fc96d265a0a82b6ba838418` |
| `expected.bin` (logical NCHW oracle) | 400 | `7a364a2c20910f0b00f4f522856009ed69d5a477ea4b9fdee5ac146193d2058c` |
| `regcmd.bin` (54 QWORDs) | 432 | `a66063b1df7be1c913ee9851a65270a0644a98312db640fbc58216a97855ac6c` |
| RK `out.bin` (result tree) | 1600 | `82f8bdb91b780e54f6d90b1ea4281d01913f7561d688f0e5a75df89b5f604f0e` |

The RK result tree is
`build/rk3588-example-captures/results/conv-fp16-20261105T222300Z/board-run/conv-fp16/conv_1x1_valid_c8_h5_w5_oc8/out.bin`.
Only the defined plane 0 (first 400 bytes) is compared; planes 1..3 contain
undefined allocator/device bytes (plane 1 is nonzero garbage in the capture,
planes 2..3 are zero). The test must not compare the full 1600-byte BO against
the 400-byte logical oracle.

### 2.2 Input layout (`a.bin`, 800 bytes, 400 halfwords)

RK writes `[c1][H][width_stride][c2]` with `c2=8`, `c1=2`,
`width_stride=5`, `H=5`. Only C0..C7 are real; C8..C15 are the aligned zero
pad.

Halfword index:

```
in_h = ((c/8)*5 + y)*5*8 + x*8 + (c%8)
byte = 2*in_h
```

for `c=0..7`, `y=0..4`, `x=0..4`. The second 8-channel group
(halfwords 200..399) is all zero in the capture and is not read by the
first engine.

Example: pixel `(y=0,x=0)` has C0..C7 at bytes 0,2,...,14; pixel
`(y=0,x=1)` starts at byte 16. Pixel atom `a = y*5+x` starts at byte `16*a`.

### 2.3 Weight layout (`w.bin`, 256 bytes, 128 halfwords)

RK writes `[oc][ic]` for this 1x1 non-depthwise case, with `align_c=16`:
8 real kernels (OC0..OC7) by 16 aligned input channels (IC0..IC7 real,
IC8..IC15 zero).

Halfword index:

```
w_h = oc*16 + ic
byte = 2*w_h
```

for `oc=0..7`, `ic=0..15`.

Example: kernel 0 real row is bytes 0..15; kernel 1 real row starts at byte
32; the unused IC8..IC15 tail of kernel 0 is bytes 16..31 (zero).

### 2.4 Output layout (raw BO, 1600 bytes, 800 halfwords)

RK uses the `flat_1x1` atom layout `[c1][out_width_stride][c2]` with
`c2=8`, `out_width_stride=25`, `align_out_c=32`, `c1=4`.
The spatial atom is `a = y*5+x` (0..24). The defined plane is `c1=0`
(OC0..OC7). Planes 1..3 are allocator/device padding and are not part of the
oracle.

Halfword index:

```
out_h = (plane*25 + a)*8 + lane
     = (plane*25 + y*5 + x)*8 + lane
byte = 2*out_h
```

with `plane = oc/8` (only plane 0 defined), `lane = oc%8`.

The captured `expected.bin` is logical NCHW, not the raw BO:

```
expected_h = oc*25 + y*5 + x
```

Test transform (test-only, not runtime repair):

```
raw = out.bin[0:1600] as 800 little-endian halfwords
raw = raw.reshape(4,25,8)
logical = raw[0].reshape(25,8).T.reshape(8,5,5)
compare logical to expected.bin (8,5,5)
```

The host-side verifier `verify_first_case.py` checks this transform and the
frame mapping against the captured files.

### 2.5 Mapping to the K8 front's original OC16 weight traversal

The K8 front's original traversal (K16/OC16 weight BO, FP16) is, in halfwords:

```
W_h(oc,ic) = weight_base_h
           + (oc/16)*(16*ai)
           + (ic/32)*(16*32)
           + (oc%16)*32
           + (ic%32)
```

with `ai` the physical input-channel group (32 for C32). The K8 front advances
OC by `ATOMIC_K` and keeps the OC16 group stride at `16*ai` halfwords, so the
OC8 halves are at `oc%16 = 0` and `oc%16 = 8`.

For the first case, use `ai=32`, `ao=16` (one padded OC16 block):

```
W_h(k,c) = weight_base_h + k*32 + c        (k=0..15, c=0..31)
```

The captured weight BO is only 8 kernels x 16 aligned channels. The hardware
weight fetch expands it on the fly into the 16x32 frame:

| Frame position | Source | Value |
|---|---|---|
| `k=0..7, c=0..7` | `w.bin` halfword `k*16+c` | real weight |
| `k=0..7, c=8..31` | none | 0, weight mask 0 |
| `k=8..15, c=0..31` | none | 0, weight mask 0 |

The source BO is **not** rewritten. The expansion is a hardware address/mask
function, not a CPU repack. This preserves the K8 front's original OC16 atom
formula exactly: the first OC8 frame reads halfwords `0..255`
(kernels 0..7, each 32 halfwords); the second OC8 half would start at
`+8*32 = +256 halfwords = +512 bytes`, not at `+16 bytes`. The K8 front's
`next_weight_atom_base` uses `(oc%16)*32` halfwords, which is the same
`+512` bytes for the second half.

### 2.6 Frame format fed to the C32 arithmetic

For each spatial atom `a=0..24`:

| Frame field | Value |
|---|---|
| `frame_data[c]`, c=0..31 | `a.bin` halfword `a*8+c` for c<8; 0 for c>=8 |
| `frame_data_mask[c]` | 1 for c<8; 0 for c>=8 |
| `frame_weight[k*32+c]` | expanded weight above; 0 for padding |
| `frame_weight_mask[k*32+c]` | 1 for k<8,c<8; 0 otherwise |
| `frame_first` / `frame_last` | 1 / 1 (one IC32 group per output pixel) |
| `frame_output_address` | `out_base + a*16` (FP16 `c2=8`, plane 0) |

The CACC produces `out_values[k*32 +: 32]` FP32 for kernels `k=0..7`.
`k` is the OC lane; there is no reordering. Convert each once to FP16 and
write halfword `out_base + a*16 + k*2`.

If the implementation uses K2/K4 serial kernel slices (section 4), the same
frame mapping applies per slice; only the number of kernel rows per frame
changes. `k` remains the OC lane.

### 2.7 Do not reuse the K8 GEMM output-atom advance

The K8 GEMM writer places an OC8 half at `+0`, the second OC8 half at `+16`
bytes, and the next OC16 block at `+64` bytes with a 16-halfword gap. That is
the GEMM scratch/output atom layout, not the RK conv layout.

For the first case, the plane stride is:

```
25 atoms * 8 halfwords * 2 bytes = 400 bytes
```

So an OC16 result's second OC8 half is at `+400` bytes (plane 1), not `+16`
bytes. A conv output scheduler is mandatory. Reuse the FP32->FP16 converter
and halfword writer leaves, not the K8 address schedule.

For FP32 output (`c2=4`), one OC8 CACC frame scatters into **two** 16-byte
atoms: channels 0..3 to plane `p`, channels 4..7 to plane `p+1`, with plane
stride `out_width_stride*4*4` bytes. The companion C4/OC16 case therefore needs
an atom-assembly buffer. The first case (FP16, c2=8) maps one OC8 frame to one
atom and needs no scatter.

### 2.8 Raw-command profile for the first case

The stream is 54 QWORDs: 50 body + 4 terminal tail. The first engine must
decode the actual captured words, validate every field, and reject any
different value or unknown target. Fields that do not affect the reduced
1x1 data path (CBUF bank counts, DMA strides, feature grains) are **validated
profile constants**, not silently ignored.

| Register | Captured value | First-engine use |
|---|---|---|
| `CNA 0x100c` CONV_CON1 | `0x00000120` | FP16 in/proc, conv_mode 0; require. |
| `CNA 0x1010` feature grains | `0x00000340` | CBUF scheduling constant; validate only. |
| `CNA 0x1014` CONV_CON3 | `0x00000009` | stride 1x1; require. |
| `CNA 0x1020` DATA_SIZE0 | `0x00050005` | H=5, W=5; use. |
| `CNA 0x1024` DATA_SIZE1 | `0x00070010` | real C=8, aligned C=16; use real C, validate aligned. |
| `CNA 0x1028` DATA_SIZE2 | `0x00000005` | out_w=5; use. |
| `CNA 0x102c` DATA_SIZE3 | `0x00000019` | out atoms=25; use. |
| `CNA 0x1030` WEIGHT_SIZE0 | `0x00000100` | 256 weight bytes; validate BO. |
| `CNA 0x1034` WEIGHT_SIZE1 | `0x00000020` | 32 bytes/kernel; use source stride. |
| `CNA 0x1038` WEIGHT_SIZE2 | `0x01010008` | kw=1, kh=1, kernels=8; use. |
| `CNA 0x1040` CBUF_CON0 | `0x000000b1` | data bank 1, weight bank 11; validate only. |
| `CNA 0x1044` CBUF_CON1 | `0x00000003` | 4 entries; validate only. |
| `CNA 0x104c..0x105c` CVT | `0x1/0x10000 x4` | identity/bypass; validate. |
| `CNA 0x1070` FEATURE address | patch | input base; use. |
| `CNA 0x1078` DMA_CON0 | `0x000f000f` | burst lengths; validate only. |
| `CNA 0x107c/0x1080` DMA_CON1/2 | `0x14`/`0x5` | 32B-unit strides; validate; reduced engine uses per-pixel addressing. |
| `CNA 0x1084/0x1088` FC sizes | `0x00050005`/`0x10` | source H/W, aligned C; validate. |
| `CNA 0x1110` weight address | patch | weight base; use. |
| `CNA 0x1180` CVT_CON5 | 0 | validate. |
| `CORE 0x3010` MISC_CFG | `0x00000200` | FP16, spatial=0; require. |
| `CORE 0x3014` DATAOUT_SIZE_0 | `0x00040004` | 5x5 output; use. |
| `CORE 0x3018` DATAOUT_SIZE_1 | `0x1f` | 32 aligned OC; use/validate. |
| `CORE 0x3030` reserved | 0 | require zero. |
| `DPU 0x400c` FEATURE_MODE | `0x1e4` | output mode/burst; validate. |
| `DPU 0x4010` DATA_FORMAT | `0x48000002` | FP16 output; use. |
| `DPU 0x4020` DST address | patch | output base; use. |
| `DPU 0x4024` DST_SURF_STRIDE | `0x190` | 400 B plane stride; use. |
| `DPU 0x4030/34` cube W/H | `4`/`4` | 5x5; use. |
| `DPU 0x4038` notch | 0 | require zero. |
| `DPU 0x403c` cube channel | `0x0007001f` | real OC=8, aligned 32; use/validate. |
| `DPU 0x4040/0x4060` BS/BN | `0x53` | bypass; require. |
| `DPU 0x4050` BS_OW | `0x126` | output-width config; validate. |
| `DPU 0x4058/0x405c` WDMA sizes | `0x1f`/`0x00040004` | duplicate dims; validate. |
| `DPU 0x4070` EW_CFG | `0x383` | EW bypass/identity; require. |
| `DPU 0x4078/0x4084` scales | `1`/`0x10001` | identity; require. |
| `DPU 0x40c0` SURFACE_ADD | `0x320` | validate against layout. |
| Tail `0x01010010/14`, `0x00410000`, `0x00810008` | 0/0/0/`0xd` | terminal; require. |

The 54-QWORD conv framing is **not** the 49-QWORD CMAC framing. The existing
`rk_cmac_array_dma` requires `amount=45` and four CMAC tail keys and cannot be
used unchanged. Reuse its raw fetch/response discipline, not its amount/tail
check.

## 3. Answer 3: CNA/CBUF/CSC responsibilities and minimal implementation

### 3.1 Responsibilities

| Block | Responsibility | First implementation | Not implemented |
|---|---|---|---|
| CNA profile/decode | Parse raw CNA/CORE/DPU words, validate every field, derive geometry | New strict `rk_conv_profile`; exact first-case values only | General vendor field set, multi-task |
| Feature fetch | Turn RK packed feature BO + addresses into C32 operand vectors | Per-pixel gather with NHWC/C1C2 modes; zero/mask padding | Full CDMA image/WG modes, CVT arithmetic |
| Weight fetch | Turn RK packed weight BO into OC16x Kx C32 frames | On-the-fly IC/OC expansion; resident 1x1 weight tile | Compression, WGS/WMB, Winograd |
| CBUF / line buffer | Hold rows/channels for reuse; bank reuse | 1x1: no line buffer; spatial: `kh`-row line buffer; small weight tile | Full 12x256x128 B logical CBUF virtualization |
| CSC / sequencer | Generate (spatial, OC block, IC group, kernel) frame order and first/last reduction tags | Pixel-major for 1x1; kh/kw-major for spatial | Tiling, multi-core, split-K accumulation |
| CMAC/CACC | C32 x K products, per-kernel FP48/FP32 accumulation | Reuse existing C32 cell/CACC; K2/K4/K8 slice | INT8 MAC/CACC |
| Output scheduler | Convert/place results in RK flat_1x1/NC1HWC2 atom layout | New conv atom writer; reuse converter/halfword writer | GEMM 64-byte atom schedule, FP32 special modes beyond profile |
| DPU | BS/BN/EW/LUT/activation | Bypass-only; validate identity fields | Any DPU arithmetic, ReLU, LUT, FP32 output policy beyond profile |

### 3.2 First-engine block diagram (text)

```
raw 54-QWORD stream
        |
  rk_conv_profile  (strict field validation, geometry)
        |
  rk_conv_front
    - feature fetch  -> C32 data frame + mask
    - weight fetch   -> OC16 x C32 weight frame + mask (expanded from RK BO)
    - frame scheduler-> first/last, output atom address
        |
  rk_cmac_fp16_array (C32 x K2/K4/K8)
        |
  rk_cacc_fp16_array (one FP48 accumulator per kernel)
        |
  rk_conv_output_atom
    - FP32 -> FP16 (or FP32 path)
    - assemble c2=8 / c2=4 atoms
    - write RK flat_1x1 / NC1HWC2 addresses
        |
  rk_cmac_rw_arbiter -> one-outstanding halfword memory port
```

The Gate 1A capture replay instantiates the existing full C32/K16
512-product CMAC/CACC array. K8/4/2 arithmetic slices remain possible future
area variants, but are not the implementation measured by this first-case
replay.

### 3.3 Feature fetch

Modes, selected by the decoded profile:

- **C1C2** (`c2=8`, C>4 or aligned C=16/32):
  `base + ((c/8)*H*width_stride + y*width_stride + x)*8 + (c%8)`.
  For the first case, fetch only c<8 and zero/mask c=8..31.
- **NHWC** (C<=4, `use_nhwc`): `base + (y*width_stride + x)*C + c`.
  This covers C1 and C4 captures.
- Spatial: fetch rows into a `kh`-row line buffer; each output pixel extracts
  `kh*kw` C32 vectors. Stride skips input coordinates; it does not change the
  line-buffer format.
- Padding: explicit zero fill / operand mask. True `CNA_PAD_CON0` is rejected
  until source evidence exists.

### 3.4 Weight fetch

- 1x1: one resident expanded OC16x32 tile (1024 B) per OC16 block. Load once,
  reuse for all spatial atoms.
- Spatial: resident `kh*kw` expanded OC16x32 tiles (or a streamed tile), in
  RK kh-major order. Weight fetch uses the same OC16 atom formula as the K8
  front; only the kernel index is added.
- Depthwise: spatial-major single-channel weights, one channel per kernel
  lane; use a diagonal weight matrix on the C32 array or a dedicated
  depthwise MAC.
- No weight decompression, WGS/WMB or Winograd.

### 3.5 Line buffer / bank reuse

- 1x1: no line buffer. The input vector is one pixel; the weight tile is
  resident.
- 3x3/5x5: a `kh`-row line buffer of `width_stride * align_c` halfwords per
  row. For the small captures this is 3-5 rows, not the full RK CBUF. Rows are
  reused across output rows; the oldest row is replaced.
- CBUF banks: the first engine validates the captured `CBUF_CON0/1` values but
  implements only the local buffer. Full 12-bank x 256-entry x 128-B logical
  CBUF virtualization is required only when a workload exceeds the local
  buffer or when tile/bank scheduling is added. Do not claim full CBUF
  capacity from a small line buffer.
- Bank reuse across output-channel blocks: the weight tile for the current
  OC16 block stays resident while the input window is traversed; then advance
  OC. For 1x1, this is a single weight load per OC16 block.

### 3.6 Padding

- First case: no padding (valid 1x1).
- Gate 2: explicit zero frame first (captured). The engine fills out-of-range
  window positions with zero and masks the corresponding products. This
  matches `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4`.
- True `CNA_PAD_CON0` left/top (and right/bottom) remains unsupported. No
  FP16 pad register value is proven by the READY captures.
- INT8 pad value uses the zero point; that is a later integer-path contract.

### 3.7 MAC frame sequence

1x1, one OC16 block, implemented C32/K16 array:

```
load expanded weight tile W[16][32] once
for a = 0..24:                    # y*5+x
    D[0..31] = feature(a)         # 8 real, 24 zero/masked
    emit frame(D, W[0..7][*], first=1, last=1, out_addr=out_base+a*16)
    # CACC -> 8 FP32 -> convert -> 8 halfwords -> atom
```

For K2/K4, loop the kernel slices within the OC16 block; each kernel still
accumulates its own C32 dot product. For spatial, the inner loop is
`ky,kx,ic_group` with `first` on the first frame and `last` on the last frame of
the reduction; the output frame is emitted once per output atom.

### 3.8 Output atom

Definition: a 16-byte RK atom holds `c2` channels at one spatial position,
`c2=8` FP16 (16 B) or `c2=4` FP32 (16 B).

```
atom_addr(oc,y,x) = out_base
                  + (oc/c2)*out_width_stride*16
                  + (y*out_w+x)*16
                  + (oc%c2)*elem_bytes
```

- FP16, c2=8: one OC8 CACC frame -> one atom; no scatter.
- FP32, c2=4: one OC8 CACC frame -> two atoms (planes `p`, `p+1`); assemble
  four channels per atom.
- `flat_1x1` and `NC1HWC2` use the same atom formula; only `out_h`, `out_w`
  and `out_width_stride` differ. `out_width_stride` is the padded atom count
  (e.g. 25, 52, 144), not necessarily a row width.
- Never use the K8 GEMM `+16/+64` OC8/OC16 advance for conv.

### 3.9 Raw-command boundary and failure policy

- The engine accepts only the raw final QWORD stream; address fields are
  patched by the test/runner exactly as the bundle schema does.
- Every unknown target/offset, duplicate/incomplete field, unsupported shape,
  unsupported dtype, unaligned address, bad BO extent or unsupported CBUF/pad
  value is an explicit error. There is no "ignore and continue" path.
- The first-case profile is exact; broadening within 1x1 is a parameterized
  profile with its own tests, not a silent fallback.
- No CPU arithmetic, no CPU repack, no runtime gather. The host may zero the
  output allocation before submission; that is initialization, not layout
  repair.

## 4. Answer 4: area/test estimate, reuse, risks

### 4.1 NVDLA reuse split

| NVDLA block/file | Reuse verdict | Reason |
|---|---|---|
| `NV_NVDLA_CMAC_CORE_MAC_mul.v` | **Already reused** | FP16 product donor in `rk_cmac_fp16_cell`. |
| `NV_NVDLA_CACC_*` / `NV_NVDLA_cacc.v` | **Already reused in part** | `rk_nvdla_cacc` / `rk_cacc_fp16_array` provide per-kernel FP48 accumulation. |
| `NV_NVDLA_CSC_dl/sg/wl` | Reference only | NVDLA stripe/atom/register format; not RK CNA fields. Custom sequencer is smaller and auditable. |
| `NV_NVDLA_CDMA_dc/wt/img` | Reference only | NVDLA 8-byte atom, MCIF/CSB, 0-based sizes; RK uses 16-byte atoms, 32B-unit/4-row strides, different fields. |
| `NV_NVDLA_cbuf.v` | Bank-wrapper reference only | nv_small_256 is 32 banks x 32 B x 128 (128 KiB); RK is 12 banks x 256 entries x 128 B (384 KiB). Not drop-in. |
| `NV_NVDLA_CDMA_*_fifo`, `WT_wrr_arb` | Possible leaf reuse | Useful FIFO/arbiter patterns; interface changes required. |
| `NV_NVDLA_CACC_assembly/delivery` | Reference only | NVDLA output format; conv atom writer is custom. |
| Full NVDLA core | **Do not import** | Full core failed fit (3,138 slices short; ~295K LUT / 1,430 DSP / 291.5 BRAM board). The reference build is INT8/BPE=8 and does not instantiate SDP EW. |

What must be custom:

- RK CNA/CORE/DPU profile decoder and field validation.
- RK feature address generator (C1C2/NHWC, 32B-unit/4-row tiling, aligned C).
- RK weight address generator/expander (default/kh-major/depthwise/pointwise
  layouts, OC16/C32 grouping).
- Line buffer / bank reuse and padding/stride control.
- Conv output atom scheduler (flat_1x1/NC1HWC2, FP16/FP32).
- INT8 MAC/CACC path, if/when required.
- Split-OC/split-K/multi-task accumulation and PC chain, if/when required.

### 4.2 Area estimate (estimate, not synthesis)

Measured reference: the existing full C32/K16 512-product CMAC demo uses
267,210 LUTs, 35,776 FFs, 6 BRAM tiles and 515 DSPs (standalone board demo).
The full board is already around 293K LUTs. Scaling per product (~522 LUT,
~70 FF, ~1 DSP) gives rough arithmetic-only estimates:

| Variant | Products | Est. LUT | Est. FF | DSP | BRAM | First-case frames | Role |
|---|---:|---:|---:|---:|---:|---:|---|
| C32/K8 (existing slice) | 256 | 120-145K | 17-20K | 256-260 | 2-4 | 25 | Functional bring-up / reference |
| C32/K4 | 128 | 60-75K | 9-11K | 128-132 | 2-4 | 50 | Balanced |
| C32/K2 | 64 | 30-40K | 5-7K | 64-68 | 2-4 | 100 | Area-first |
| C8/K2 (new C8 layout) | 16 | 8-12K | 1.5-2K | 16-18 | 1-2 | 100 | Not faithful to OC16 traversal; later |

Add roughly 5-12K LUT and 2-6 BRAM for the conv front, line buffer and output
scheduler (1x1 at the low end, 5x5 at the high end). Full RK CBUF
virtualization is ~384 KiB and is not included; it is a separate capacity
decision. These numbers must be replaced by fresh OOC synthesis in gate 1/2;
they are not fit, timing or full-top evidence.

**Do not use the 39.6K-LUT PDP prototype as a convolution estimate.** The PDP
has no CBUF, no CSC traversal, no weight fetch, no line buffer, no
padding/stride, and no output atom scheduler. Its 39.6K LUT / 21K FF / 35 DSP /
6 BRAM result describes a pooling datapath plus bridge; it cannot bound a
convolution engine. A C32/K2 conv engine landing near that LUT count is a
different function with different BRAM/DSP/control costs, not a "PDP plus
something" result.

### 4.3 Test estimate

| Level | What | Count/effort |
|---|---|---|
| Layout golden | Python frame/address golden for the first case (25 atoms, 8 kernels, 32 C lanes); compare to `a.bin`/`w.bin`/`expected.bin`/captured `out.bin` | 1 script, seconds |
| Decoder unit | Accept exact 54-QWORD stream; one-field-flip rejection; unknown target; truncation; bad tail; bad alignment | ~10-15 directed tests |
| Frame unit | All 25 atoms: data/weight/mask/first/last/output address vs golden | 1 exhaustive test |
| Core numeric | Full first case through front + K8/K4/K2 + output writer; compare defined 400 B after donor unpack within `atol=0.2`; also compare raw plane0 offsets | 1 replay, 2 simulators |
| Negative | 3x3/stride2/groups/C>32/OC>16/FP32/unsupported CBUF/pad/timeout | ~10 tests |
| Synthesis | OOC first engine (C32/K8 and C32/K4/K2), resource/timing report | 1-3 runs, background |
| Later gates | Each new feature adds its captured replay + negative fields; spatial cases multiply frames by `kh*kw` and OC blocks | per gate |

First-case simulation is small: 25 frames, 8 input halfword reads per frame,
a few hundred weight reads with a resident tile, and 200 output halfwords.
Compile dominates; runtime should be well under a minute per simulator after
compile. The 3x3/5x5 cases are larger (hundreds to thousands of frames) but
still small by FPGA standards; full large-case replay is a later gate.

### 4.4 Top risks

1. **Layout/traversal correctness (highest).** The RK conv layouts are not the
   K8 GEMM layouts: weight IC/OC expansion, aligned-C padding, flat_1x1 vs
   NC1HWC2 atom planes, FP16 c2=8 vs FP32 c2=4, and the `out_width_stride`
   padding all have to be exact. A mathematically correct MAC with the wrong
   atom address produces byte-wrong outputs. Mitigation: exhaustive frame/
   address golden, captured `out.bin` plane-0 check, no CPU fixup, decoder
   rejects every unmodeled field.
2. **Area/fit and timing.** The faithful C32/K8 slice is ~120-145K LUT before
   the conv front, and the board is already near 293K LUTs. The 39.6K PDP
   number is not a conv estimate. Mitigation: functional K8 simulation first,
   then K4/K2 area reduction with lower-slice equality tests, fresh OOC
   synthesis, and no full-top/bitstream claim until fit and timing are
   measured. Do not weaken constraints.
3. **CBUF/line-buffer, stride/pad and spatial sequencing.** NVDLA CBUF
   geometry does not match RK (32x32Bx128 vs 12x128Bx256), true FP16
   `CNA_PAD_CON0` is unproven, and stride/pad/kh-kw sequencing is where
   boundary errors appear. Mitigation: explicit zero-frame padding first,
   small line buffer with directed boundary tests, stride-2 capture replay,
   and a clear statement that full CBUF capacity is not implemented until
   measured.

Secondary risks: INT8 numerics (zero points, bias, +1 LSB divergences),
split-K accumulation, multi-task PC chain, and CACC special-value/rounding
policy. These are separate gates, not silently folded into the first engine.

## 5. Answer 5: staged sequence with gates

Each gate ends with a source-bound report: tool versions, source hashes,
test names, seeds, pass/fail, and explicit non-claims. No old log is reused for
modified RTL. Long builds/simulations run in the background.

### Gate 0: contracts and golden model

Scope:
- Freeze the first-case profile table (section 2.8), frame/address formulas,
  and error taxonomy.
- Build `verify_first_case.py` and the JSON matrix from the manifests.
- Add parameterization tests for C32/K2/K4/K8 lower-slice equality (existing
  K1/K8 tests are the precedent).

Exit:
- Layout verifier reproduces the captured plane-0 bytes exactly and the
  logical `expected.bin`; frame/address goldens are checked in.
- K2/K4 numeric results equal the corresponding K8/K16 lower slice for the
  same kernels; no new numerical policy.
- No RTL change yet.

### Gate 1: first case (1x1, valid, single-group, FP16, C8/OC8)

1A (primary):
- New `rk_conv_profile` for the exact 54-QWORD first-case stream.
- New feature fetch (C1C2), weight expander (8x16 -> 16x32), frame scheduler.
- Reuse the full C32/K16 CMAC/CACC and converter/writer leaves; new conv atom
  writer.
- Replay the captured `a.bin`/`w.bin`/`regcmd.bin` unchanged. Compare all 200
  written FP16 values exactly against both the raw captured plane 0 and
  `expected.bin`; compare the complete 1600-byte output BO, seeding the three
  capture-undefined planes from the captured post-run allocation and requiring
  them to remain untouched.

1B (1x1 FP32/OC16):
- Add FP32 atom writer (`c2=4`), two-atom scatter per OC8 frame, OC16 block.
- Replay `conv_simple_fp16_1x1_c4_h8_w8_oc16`; compare full 4096 B raw output
  to its raw oracle.
- Treat `conv_simple_fp16_1x1_c32_h8_w8_oc32` as a structural/known-divergence
  case, not an exact oracle.

1C (1x1 C1 NHWC):
- Add NHWC C1 gather and OC6 padding.
- Replay `conv_1x1_c1_oc6_h4w4`; compare via donor unpack.

Exit:
- Exact frame/address match for every Gate-1 case (25 atoms for 1A, 64 for
  1B, 16 for 1C).
- Exact numeric match for 1A; later cases use their documented capture oracle
  and tolerance only where their source evidence requires it.
- Every unsupported field/shape is an explicit failure; no CPU fixup.
- OOC synthesis report for C32/K8 and C32/K4/K2; no full-top.

Gate 1A now has an RTL implementation in `rtl/cmac/rk_conv_profile.sv`,
`rk_conv_array_front.sv`, `rk_conv_output_atom.sv` and
`rk_conv_array_core.sv`, with capture replay and strict negative/memory-fault
tests in `tests/conv/tb_conv_array_core.sv` and
`tools/conv/test_first_case.py`. The front expands the unchanged C8/OC8 BOs to
C32/K16 frames in hardware and the sink uses the 400-byte conv plane stride,
not the K8 GEMM schedule. The dual-simulator run is recorded at
`build/convolution-first-case/report.json`; broader Gate 1 OOC synthesis and
Gate 1B/1C remain outstanding. No full-top or physical qualification follows
from this simulation result.

The initial pre-merge `make test` run passed the convolution target, then
stopped at the stale dual-host frontend/backend manifest pin; that failure and
its log remain preserved in the worktree history. After merging current main
(merge `3e379c9`), `core_source_paths()` returned all 72 expected sources and
the full `make test` completed with exit code 0, including the reviewed
dual-host native test and both process-control runs. The convolution replay
report records Icarus 13.0 and Verilator 5.048, 11/11 passing modes on each,
and matching hashes for all 28 source/fixture inputs. The terminal log and exit
receipt are `build/convolution-first-case/post-main-merge/make-test.log` and
`make-test.rc`. This remains simulation evidence, not full-top or physical
qualification.

After integration as main commit `6a40c18`, the focused `make
conv-first-case-test` target was rerun on main and passed with exit code 0;
both simulators again passed all 11 modes with all 28 source/fixture hashes
matching. Its mainline report and command log are
`build/convolution-first-case/report.json` and
`build/convolution-first-case/post-main-merge/main-integration-focused.log`.

### Gate 2: stride and padding (first spatial skeleton)

Scope:
- Introduce a 3-row line buffer and window extraction.
- Add stride 1/2 input coordinate skip and output geometry.
- Add explicit zero-frame padding (out-of-range = 0/masked).
- Replay `conv_3x3_valid_c4_h9_w9_oc4`, `conv_3x3_stride2_c4_h11_w11_oc4`,
  `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4`.
- Reject `CNA_PAD_CON0` nonzero until evidence exists.

Exit:
- 3x3 valid, stride-2 and zero-frame outputs match their oracles.
- Boundary/corner tests cover top/bottom/left/right, stride tails, zero
  borders.
- The line buffer is explicitly a reduced buffer, not a full CBUF claim.

### Gate 3: 3x3/5x5 breadth

Scope:
- Generalize to 5x5, larger C (C16/C32) and larger OC (OC32/OC128 multiple
  OC16 blocks).
- Implement kh-major weight order and NC1HWC2 atom output for spatial cases.
- Replay `conv_simple_fp16_3x3_c4_h8_w8_oc16`,
  `conv_simple_fp16_5x5_c4_h8_w8_oc16`,
  `conv_simple_fp16_3x3_c16_h8_w8_oc32`,
  `conv_legacy_3x3_c4_oc4_h9w9`,
  `conv_py_3x3_c32_oc128_h14w14_fullsetup`.

Exit:
- All listed spatial cases match their oracles (full raw where the oracle is
  raw; donor unpack where the oracle is logical NCHW).
- 5x5 line buffer and multiple OC16 blocks are covered.
- No claim of full CBUF capacity or large tiling.

### Gate 4: depthwise, grouped, split-OC

Depthwise:
- Spatial-major single-channel weight layout; diagonal weight matrix on the
  C32 array (correct but inefficient) or a dedicated depthwise MAC.
- Replay `conv_depthwise_3x3_c3_h11_w28_oc3` and the promoted
  `conv_depthwise_3x3_c3_oc3_h11w28_task0/1`.

Grouped:
- Group-aware C/OC slicing and grouped weight block order.
- Replay the single-task `conv_grouped_3x3_c4_oc4_g2_h5w5`.
- The promoted `conv_grouped_..._task0/1` are plain single-group tasks; run
  them individually. The parent needs multi-task support.

Split-OC:
- Run the promoted `conv_splitoc_..._task0/1` individually (plain OC8 3x3).
- Full single-job split-OC requires a PC chain/shared input and is deferred.

Exit:
- Each promoted/single-task case matches; depthwise diagonal and grouped
  order are proven.
- Parent multi-task cases remain explicitly unsupported until a PC-chain
  contract exists.

### Gate 5: split-K, INT8, multi-task/vendor

Split-K:
- Define an explicit partial-K accumulation contract (persistent CACC across
  tasks or output read-modify-write). No READY capture exists; keep blocked
  until new source evidence.

INT8:
- Add integer MAC/CACC, zero-point handling, int32 bias, quantized output
  rounding/saturation.
- Replay `simple_conv_int8_5x5_c8_h8_w8_oc32` and
  `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` with the known +1 LSB
  output-conversion caveat; do not call them exact.

Multi-task/vendor:
- PC chain, `core_mask`/`subcore_task`, self-referential `PC_BASE_ADDRESS`.
- Only after a supported ABI/source contract; do not invent fields.

Exit:
- Each feature has its own numerical/shape contract, negative tests and
  source evidence. Unsupported entries remain explicit failures.

## 6. Gate 1A implementation files and later planned blocks

```
rtl/cmac/rk_conv_profile.sv          # implemented strict 54-QWORD decoder
rtl/cmac/rk_conv_array_front.sv      # implemented C8/OC8 fetch/expansion/schedule
rtl/cmac/rk_conv_output_atom.sv      # implemented FP16 conv atom sink
rtl/cmac/rk_conv_array_core.sv       # implemented raw-stream first-case core
tests/conv/tb_conv_array_core.sv     # capture replay, negatives, memory faults
tools/conv/test_first_case.py        # dual-simulator runner and source manifest
rtl/conv/rk_conv_line_buffer.sv      # future spatial row buffer (gate 2+)
rtl/conv/rk_conv_dma.sv              # future raw DMA framing (not implemented)
```

Reuse as leaves: `rtl/cmac/rk_cmac_fp16_array.sv`,
`rtl/cmac/rk_cacc_fp16_array.sv`, `rtl/cmac/rk_nvdla_cacc.sv`,
`rtl/cmac/rk_cmac_output_nvdla.sv`, `rtl/rk_fp32_to_fp16.sv`,
`rtl/cmac/rk_cmac_rw_arbiter.sv`.

## 7. Open evidence questions

- True FP16 `CNA_PAD_CON0` semantics and a Rocket-capable capture.
- Split-K accumulation/clearing contract.
- Multi-task PC-chain behavior for grouped/split-OC.
- INT8 zero-point, bias and output rounding; the two READY INT8 cases already
  show +1 LSB divergences.
- CACC special-value/rounding policy on RK (candidate behavior only).
- Full CBUF capacity/bank virtualization and large-tile scheduling.
- Whether the existing FP16 CACC donor matches RK's reduction order bit-for-bit;
  current acceptance is tolerance-based, not exact.

## 8. Reproduce this increment

```sh
cd build/convolution-architecture
/usr/bin/python3 generate_matrix.py
/usr/bin/python3 verify_first_case.py
python3 -m json.tool CONV_MATRIX.json >/dev/null
python3 -m json.tool first_case_layout_check.json >/dev/null
```

`verify_first_case.py` is host-side only. It reads the captured packed BOs and
the RK result receipt, reconstructs the donor logical tensor and the raw plane
0, and requires both to match. It does not run RTL, a device, a board or a
bitstream.

## 9. References

- `build/rk3588-example-captures/conv-fp16/manifest.json` and `README.md`
- `build/rk3588-example-captures/conv-simple/manifest.json` and `README.md`
- `build/rk3588-example-captures/conv-gemm-vendor/manifest.json` and `README.md`
- `build/rk3588-example-captures/team/gap-matrix/GAP_MATRIX.md`
- `build/rk3588-example-captures/team/nvdla-crosswalk/FIELD_CROSSWALK.md`
- `build/rk3588-example-captures/team/nvdla-reference/REFERENCE_MAPPING.md`
- `docs/CMAC_ENCODER_CONTRACT.md`, `docs/CMAC_K8_CORE.md`,
  `docs/CMAC_K8_ARRAY.md`, `docs/CMAC_ADDRESS_CANDIDATE.md`,
  `docs/CMAC_OUTPUT_CANDIDATE.md`, `docs/CMAC_PIPELINE_TIMING.md`,
  `docs/REVIEW_AND_PLAN.md`
- `rtl/cmac/rk_cmac_array_front.sv`, `rk_cmac_array_core.sv`,
  `rk_cmac_array_datapath.sv`, `rk_cmac_array_dma.sv`,
  `rk_cmac_frame_output.sv`, `rk_cmac_rw_arbiter.sv`
- `/home/fedora/ZYNQ-NVDLA/RTL/vmod/nvdla/{csc,cdma,cbuf,cacc,cmac}/`
