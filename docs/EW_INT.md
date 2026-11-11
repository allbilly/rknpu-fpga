# ew-int: evidenced integer elementwise support

Status: **additive integer EW path implemented and replayed offline** (15 READY
captured cases, 3 BLOCKED cases with no oracle). The project previously had only
FP16 elementwise RTL; this increment adds an integer decoder, engine and ALU
without editing any FINAL-freeze file or the adopted six-page/EW image profiles.

- Capture family: `build/rk3588-example-captures/ew-int/` (manifest + 15 READY
  bundles; 3 BLOCKED), source revision `273d015e…`, source examples
  `/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py` and
  `…/expt/elementwise_int.py`.
- Software reference: `model/int_profile.py` (fail-closed decoder),
  `model/int_alu.py` (integer arithmetic), `model/int_sim.py` (BO emulator).
- RTL: `rtl/rk_int_alu.sv`, `rtl/rk_ew_int_regs.sv`,
  `rtl/rk_ew_int_engine.sv`, `rtl/rk_ew_int_dma.sv`,
  `rtl/host/rk_jtag_ew_int_bram.sv`, `fpga/ewint/ypcb_jtag_ew_int_top.sv`,
  profile `fpga/ewint/sources.json`, prepare flow
  `tools/host/prepare_ew_int.py`.
- Replay/tooling: `tools/ew_int/run_ew_int.py` (Python reference + Verilator +
  Icarus Verilog, ALU vectors, negative controls), `tests/tb_ew_int.sv`,
  `tests/tb_int_alu.sv`, `tests/test_ew_int.py`; receipts under
  `build/ew-int/<stamp>/`.
- Frozen evidence untouched: `build/verif/frozen_hashes.json` (518 files,
  label `FINAL-freeze-20261109T160627Z`) includes `rtl/rk_ew_engine.sv`,
  `rtl/rk_ew_regs.sv`, `rtl/rk_ew_dma.sv`, `rtl/rk_ew_dma_demo.sv`,
  `rtl/rk_fp16_alu.sv` and `fpga/ypcb_ew_startup_top.sv`. None of them, the
  adopted six-page image, or the FP16 EW production image profile were edited.

## 1. Captured register-stream shapes

Every captured stream is a sequence of little-endian QWORDs
`(target << 48) | ((value & 0xffffffff) << 16) | offset` (the capture format
already documents this). Three shapes exist and only these are accepted; mode
inference is presence-based and the per-mode register *set* must match exactly.

| mode | QWORDs | source | distinguishing registers |
|---|---|---|---|
| `simple` | 18 | kernel_6_18 `make_regcmds` lines 314-352 | no surface/init registers |
| `layout` | 44 | expt `prepare_and_run` prefix (4) + `make_layout_regcmds` (40), lines 529-596/752-760 | `DPU.DST_SURF_STRIDE`, `SURFACE_ADD`, `RDMA_EW_SURF_STRIDE`, BS/BN block |
| `regroup` | 31 | kernel_6_18 `run_int16_add_to_int32` lines 586-651 | `EW_CVT_OFFSET` + OUT_CVT block + 16→32 writeback |

All three end with the same four tail QWORDs, which is also the frozen DMA
framing contract: `PC_REG.BASE_ADDRESS` (`0x01010010`),
`PC_REG.REGISTER_AMOUNTS` (`0x01010014`), `VERSION` (`0x00410000`),
`PC.OPERATION_ENABLE` (`0x00810008`, value `0x18`). The integer streams use the
same tail as the FP16 EW streams, so the frozen `rk_ew_dma` framing logic is
reused verbatim (new file `rtl/rk_ew_int_dma.sv`, no edit of the frozen file).

## 2. Field encodings (tied to captured values)

Precision codes: `INT8=0`, `INT16=1`, `FP16=2`, `INT32=4`.
ERDMA element-size codes: `INT8=1`, `INT16=2`, `INT32=3`. Item sizes follow:
1, 2, 4 bytes.

| register (target:offset) | captured rule | evidence |
|---|---|---|
| `DPU.DATA_FORMAT` 0x1001:4010 | `(out_prec<<29)\|(in_prec<<26)\|proc_prec`; all three equal the integer code, except regroup `(INT32<<29)\|(INT16<<26)\|INT16 = 0x84000001` | `dpu_data_format()`, bundles |
| `DPU.DATA_CUBE_CHANNEL` 0x403c | `((channels-1)<<16)\|(channels-1)`; both halves must agree | `dpu_cube_channel()` |
| `DPU.DATA_CUBE_WIDTH` 0x4030 | `width-1`; must equal `RDMA.DATA_CUBE_WIDTH` | `make_regcmds()` |
| `DPU.EW_CFG` 0x4070 | bit28 per-pixel ERDMA data mode; bits[23:22] element size; bit21 `EW_EQUAL_EN` for MAX/MIN; bit9/7/6 fixed set; bits[19:16] ALU code; bit2 `EW_OP_TYPE_MUL` lane; bit8 converter bypass (INT32 only) | `dpu_ew_cfg()` lines 181-201 |
| ALU codes | `MAX=0`, `MIN=1`, `ADD=2`, `DIV=3`, `MINUS=4`, `ABS=5`, `NEG=6`, `FLOOR=7`, `CEIL=8`; MUL is `EW_OP_TYPE_MUL`, not an ALU code | `OPERATIONS`, README table |
| `DPU.EW_CVT_SCALE` 0x4078 | `1` (integer EW needs scale 1); INT32 additionally bypasses the converter via EW_CFG bit 8 | bundles |
| `RDMA.ERDMA_CFG` 0x2001:5034 | `(1<<30)\|(element_size<<2)` → `0x40000004/08/0c` for INT8/16/32 | `rdma_erdma_cfg()` |
| `RDMA.DATA_CUBE_*` 0x500c/5010/5014 | width `width-1`, height `0`, channels `channels-1` | `make_regcmds()` |
| `RDMA.FEATURE_MODE_CFG` 0x5044 | `(prec<<15)\|(15<<11)\|(prec<<5)\|1` → `0x00007801/0x0000f821/0x00027881` | `rdma_feature_mode()` |
| layout-only stride registers | `DST_SURF_STRIDE = SURFACE_ADD = RDMA_EW_SURF_STRIDE = width<<4` (16 for the captured width=1 cases) | `make_layout_regcmds()` |
| layout-only BS/BN block | `BS_CFG=BN_CFG=0x53`, `BS_ALU=BS_MUL=BN_ALU=BN_MUL=0`, `BS_OW=2`, `WDMA_SIZE_0=channels-1`, `WDMA_SIZE_1=width-1`, `RDMA_WEIGHT=0x01010101`, `S_POINTER=0xE` on both targets, `BRDMA_CFG=NRDMA_CFG=1`, `SRC_DMA_CFG=SURF_NOTCH=EW_SURF_NOTCH=0` | `make_layout_regcmds()` |
| regroup-only registers | `DST_SURF_STRIDE=16`, `BS_OW_CFG=0x126` (SIZE_E_0/1/2=1), `WDMA_SIZE_0=7`, `WDMA_SIZE_1=0`, `SURFACE_ADD=32`, `EW_CVT_OFFSET=OUT_CVT_OFFSET=OUT_CVT_SHIFT=0`, EW/OUT scale 1 | `run_int16_add_to_int32` |
| addresses | `DPU.DST_BASE_ADDR`, `RDMA.SRC_BASE_ADDR` (A), `RDMA.EW_BASE_ADDR` (B), all 16-byte aligned by the capture worker contract | job.json patches |
| PC tail | next address/amount `0`, VERSION `0`, enable `0x18` | bundles |

Captured simple-path geometry is a capture fact, not a TRM rule: INT8 and INT16
use `channels=8`, INT32 uses `channels=4`; `count = width*channels` (8 in every
captured simple case: INT8/INT16 `w1c8`, INT32 `w2c4`). Layout-path captures are
all `width=1, channels=9`. The regroup capture is `width=1, channels=8`.

## 3. Operation semantics

The captured expected byte images follow the examples' `integer_expected()`
(kernel_6_18 lines 659-682; expt lines 2185-2213) and the capture's own
`expected.mask.bin`:

```
MAX   : max(a[i], b[i])            (signed)
MIN   : min(a[i], b[i])            (signed)
ADD   : clamp_dtype(a[i] + b[i])
MINUS : clamp_dtype(a[i] - b[i])
MUL   : clamp_dtype(a[i] * b[i]), except INT32 MUL uses s16(b[i]) (below)
```

`clamp_dtype` is the source `saturate()` = `np.clip(value, iinfo.min, iinfo.max)`.
Operands are signed little-endian native-dtype values (`ndarray.tobytes()` for
the simple path, `pack_c1wc2` for the layout path).

**Saturation evidence caveat (important).** The README/manifest prose claims
saturating overflow lanes ("`31000 -> 32767`", "`105 -> 127`", "`-31000 ->
-32768`"), but those claims are arithmetically inconsistent with the captured
bytes: `31000 < 32767`, `-31000 > -32768`, `105 < 127`. An independent byte
decode of all 15 `expected.bin` images (not the prose) shows that **no captured
lane overflows**: every captured result equals plain in-range arithmetic.
Consequences, recorded honestly:

- Saturating clamp is **source-formula behaviour** (kernel_6_18 `saturate()`),
  not a differentially captured overflow lane.
- INT16 ADD/MINUS captured lanes are in range; INT8 and INT32 have no overflow
  lane at all. The RTL implements clamp (the only defined behaviour), and the
  labelled non-captured ALU edge vectors exercise it; a hardware differential
  test is still needed to promote saturation beyond candidate behaviour.

**INT32 MUL signed-INT16 operand (source-captured limitation).**
kernel_6_18 `run_operation` lines 430-443 computes
`ew_int16 = (b & 0xffff).view(int16)` and requires the device result to equal
`saturate(a * ew_int16)` *and* to differ from the full-INT32 product. Captured
bundle `int32_mul_int16_operand_c8_w2` encodes exactly that oracle
(`50000 -> -15536`, `-50000 -> 15536`). This is a captured hardware limitation,
not an ABI: the engine truncates the B operand to signed INT16 only for
`MUL` + `INT32`, and the ALU unit test is fed the already-truncated operand.

**INT16→INT32 regroup.** `int16_add_to_int32_c8_w1` keeps INT16 inputs and
writes eight INT32 results (`int32(a[i]) + int32(b[i])`, no INT16 clamp before
widening — the source oracle is exact integer addition). The captured output is
two four-lane INT32 surfaces. The manifest's "31000 exceeds INT16 range" claim
is also arithmetically false; the widening itself is still the point of the
case and is captured. Overflow behaviour of the widening path is unverified
(no captured lane overflows int16), so the implementation performs the addition
at the destination (INT32) width.

**Layout packing.** expt `pack_c1wc2` (lines 505-526) maps logical
`pixel, channel` to
`(((channel//atom)*width + pixel)*atom + channel%atom) * item`,
`atom = 16//item`. For every captured layout stream `width == 1`, so this
reduces exactly to contiguous `lane*item`; the surface padding bytes (e.g. INT8
c9 byte 9..15) are never asserted by the mask and are never written by the RTL.
The decoder rejects `width != 1` in surface mode as unevidenced.

## 4. Fail-closed policy (explicit error codes)

The decoder accepts only the exact per-mode register set and exact captured /
source-derived values. Error codes are shared with the FP16 profile
(`model/profile.py` `ERRORS`):

| code | meaning | integer triggers |
|---|---|---|
| 1 | unknown register/target | any key outside the union of the three captured streams |
| 2 | unsupported value/op/dtype | outside-mode register, conflicting duplicate write, unsupported ALU code (`DIV=3`, `ABS=5`, `NEG=6`, `FLOOR=7`, `CEIL=8`), FP16/FP32 `DATA_FORMAT`, EW_CFG not reconstructing to the captured word (including MUL+ALU conflict, missing/wrong `EW_EQUAL_EN`, wrong converter bypass), wrong fixed register value, non-zero PC tail |
| 3 | incomplete configuration | mode-required register missing; stream ends without enable; removed enable QWORD (DMA framing) |
| 4 | invalid address | 16-byte misalignment, 32-bit range wrap, partial output/input alias (exact in-place is allowed) |
| 5 | memory bus error | engine/memory response error |
| 6 | shape mismatch | DPU/RDMA width or channel disagreement, non-captured simple geometry, non-captured channel field halves, surface layout width > 1, `count` outside 1..64000 |
| 7 | unsupported PC chain | multi-task next address/amount (not evidenced for ew-int); also DMA fetch framing |
| 8 | memory timeout | stalled memory transaction |

Not supported by design (no captured oracle): `DIV`, `ABS`, `NEG`, `FLOOR`,
`CEIL`, FP16/FP32 EW, INT32 9-channel device answer (stream accepted, but the
capture's own note says the device behaviour is the open question this capture
answers — this RTL provides the oracle-side answer only), multi-input sums,
ReLU/PReLU/batchnorm, and any non-captured layout width.

## 5. BLOCKED cases (no invented expectations)

| case | why blocked |
|---|---|
| `int32_div_c8_w2` | Source proves DIV/FLOOR/CEIL use floating-point semantics (`integer_supported=False`); no trustworthy integer oracle. Rejected by the decoder with code 2. |
| `fp16_four_input_sum_c8_w1` | Only multi-input sum in either source is FP16 with FP32 BRDMA/NRDMA operands; belongs to an ew-fp16 family. Not materialised, not implemented. |
| `fp16_bs_bn_relu_prelu_c8_w1` | ReLU-X/PReLU appear only in FP16 BS/BN auxiliary stages; no integer activation path exists. Not materialised, not implemented. |

## 6. RTL implementation mapping

- `rk_ew_int_regs`: captures the register stream (set-of-writes decoder), infers
  mode, validates the exact captured contract, and emits a compact config
  `{op, alu dtype, in/out item, count, a, b, dst}`. Error codes as above.
- `rk_ew_int_engine`: one lane at a time over the 16-bit BRAM interface
  (one outstanding transaction, response required for reads and writes, as in
  the frozen FP16 engine). Lane addressing is `base + lane*item` (see layout
  theorem above). 1-byte sources are read as an aligned halfword and the
  addressed byte lane is selected; 1-byte destinations use a
  read-modify-write halfword (BRAM has no byte strobes); 2/4-byte destinations
  are aligned by the decoder contract. INT32-MUL truncates the B operand to
  signed INT16 before the ALU.
- `rk_int_alu`: 64-bit signed intermediate, clamp to INT8/INT16/INT32; MAX/MIN
  are signed selects; one-cycle registered result with ready/valid
  backpressure. No FP16/NaN/rounding path.
- `rk_ew_int_dma`: identical PC fetch/framing boundary as the frozen FP16
  `rk_ew_dma` (same four tail QWORDs), instantiating the integer decoder/engine.
- `rk_jtag_ew_int_bram` + `ypcb_jtag_ew_int_top`: additive host BRAM endpoint
  and top. Differential review: the top differs from the FP16 shell only in the
  module name/comment and the endpoint instantiation; the endpoint differs only
  in the engine instantiation (integer DMA) and comments. Constraints, CDC
  audit, mailbox, BSCAN and clocking are the same audited shell.

## 7. Verification evidence

Reproduce:

```sh
/usr/bin/python3 tools/ew_int/run_ew_int.py --simulator both
/usr/bin/python3 -m unittest tests.test_ew_int -v
```

Each replay case loads a 32 KiB simulated device window containing the exact
4096-byte `a.bin`/`b.bin` BO images, a zeroed 4096-byte output BO and the
captured regcmd BO with the three worker `value32` address patches applied. The
RTL output BO is compared with `expected.bin` under `expected.mask.bin`
(masked byte equality over all 4096 bytes; asserted byte counts are 8/16/32 for
the simple cases, 8/16/32 for the regroup case and 9/18/36 for the layout
cases). Receipts contain source hashes, capture manifest hash, bundle hashes,
per-case actual/expected/mask SHA-256, byte counts, transaction counts, ALU
vectors (captured lanes and labelled source-formula edges) and the negative
control error codes for both simulators.

Scope limits: this is offline RTL/software replay. It does not validate RK3588
silicon, the DRM driver, the frozen USB-JTAG transport on hardware, Vivado
timing/DRC/route, or the physical board. Transport modules are frozen and
unchanged; the new image package reuses them.

## 8. Image readiness

Two additive forms exist; the Lead adopted the **Image-B page form** for the
two-image split, and the standalone mailbox-direct image remains the fallback.

Image-B page form (integrated by `timing` into `fpga/ypcb_image_b_top.sv`):

- `rtl/rk_ew_int_page_axi.sv` — `RKEI` (`0x524b4549`) AXI4-Lite page at
  `0x0002_4000` on the frozen `rk_job_control` ABI, raw-QWORD
  capture-then-issue into the integer decoder/engine, reset per job,
  `START_AMOUNT` fail-closed to the three captured shapes.
- `rtl/rk_ew_int_aperture.sv` — four 4 KiB spare banks inside the 1 MiB decoded
  aperture at `0x1100_0000` (A/B/D operands+output, C command BO), explicit
  SLVERR holes, host staging AXI + engine 16-bit port, `memory_ready`/
  `page_busy` gating; see `docs/EW_INT_APERTURE_AUDIT.md` (PASS, 4 RAMB36 tiles
  vs 256 dense).
- `tests/tb_ew_int_page.sv` + `tools/merged/run_ew_int_page_replay.py` — page-
  level replay of all 15 READY cases (both simulators, complete masked BO
  compare, a/b readback exactness, command-BO preservation, back-to-back
  reset-per-job, 8 fail-closed negatives); receipts under `build/ew-int-page/`.
- `tools/merged/ew_int_aperture_audit.py`,
  `tests/merged/test_ew_int_aperture_audit.py`,
  `tests/merged/test_image_b_ew_int_contract.py` — offline audit and ABI/map
  contract tests.

Standalone fallback image: `fpga/ewint/sources.json` +
`fpga/ewint/ypcb_jtag_ew_int_top.sv` (same shell: `fpga/host/ypcb_jtag_ew.xdc`,
`fpga/host/mailbox_cdc.tcl`, 1 MiB at `0x10000000`, JC2 USER2). Preparation is
`tools/host/prepare_ew_int.py prepare --verilator-report … --iverilog-report …`;
it hash-binds the two replay receipts, snapshots sources into
`build/ew-int-image-prep/<stamp>/`, renders the shared checkpoint Tcl and writes
`build-request.json` with status `QUEUED_WAITING_FOR_COOL_BUILD_WINDOW`.
**No Vivado run, bitstream, board programming or flash was performed.** The
build stays queued behind the Lead-ordered heavy jobs and requires a
Lead-scheduled cool window plus a completed board review.
