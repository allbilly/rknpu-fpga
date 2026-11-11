# Runtime-decoded conv engine (experimental prototype)

Status: **design + prototype in progress (task-13)**. This is an experimental
staging area; the adopted six-page image, the production conv cores, the
FINAL-freeze manifest and every existing receipt are untouched.

Direction chosen by the user on 2026-11-10: *"Make the conv engine geometry
runtime-decoded is more like real NPU"*. Today every captured conv task needs a
per-profile elaboration variant of `rk_conv_3x3_valid_c4_front` /
`rk_conv_simple_core`, because the geometry (input/output H/W, kernel H/W,
stride, depthwise mode, real channels, kernel lanes, C1 blocking, weight layout
and output layout) is a parameter. The real RK3588 CNA is configured per task
from the register stream. This document specifies one runtime-decoded engine
that derives the same geometry from the **unchanged raw command QWORDs**, and
the evidence that every derivation is source-backed.

## 1. Corpus and evidence sources

| Family | Command length | Captures | Pinned fixture |
|---|---:|---|---|
| `conv-fp16` (vendor) | 54 QWORDs (CNA body prefixed by 3 DPU-RDMA clear words) | 8 | `tests/conv/fixtures/conv_{3x3_valid,3x3_stride2,3x3_pad1_zero_frame,grouped_*,splitoc_*,depthwise_*}` |
| `conv-fp16` (vendor) | 54 QWORDs | 1 (unpinned) | `build/rk3588-example-captures/conv-fp16/cases/conv_1x1_valid_c8_h5_w5_oc8` — READY capture bundle, **no pinned `device_capture.json`/fixture**, so it is exercised against its captured bundle's own `expected.bin` and labelled separately in every receipt |
| `conv-simple` | 52 QWORDs (CNA body + 4 PC-tail words + 1 zero padding word) | 4 | `tests/conv/fixtures/conv_simple_fp16_*` |

Field-map evidence (never guessed; each row cites the pinned donor function):

* `/home/fedora/rk3588/examples/kernel_6_18/conv_new_clean.py` (SHA-256
  `f70e9810868bf95dd8e89ed83a3af3be00cc890fad8209756e09735cb9795c51`) —
  `make_conv2d_regs` lines 445-629, `write_regs_to_npu_task` 631-676,
  `_conv_params`/`_cdma_dc_feature_input_pack_c2`/`_feature_grains`/
  `_data_bank`/`_dma_strides` lines 308-460, packing 380-401.
* `/home/fedora/rk3588/examples/conv_simple.py` — `make_regs` lines 309-367,
  `_conv_params`/`pack_input`/`pack_weights` lines 223-330.
* The captured command streams themselves and the frozen fixture manifests
  (`layout`, `command`, `execution_geometry`) are the cross-check: the decoder
  model derives the BO byte sizes and they equal the actual fixture file sizes
  for all 12 pinned captures plus the 1x1 bundle.

## 2. Register-field -> geometry map

Notation: a command QWORD is `{target[63:48], value[47:16], offset[15:0]}`.
`E(target, reg_addr, value) = (target << 48) | (value << 16) | reg_addr`.
The two families share this grammar; the target/offset pairs identify a field
independently of its position. The canonical **sequence** is the evidence for
the family (see §3).

| Target:offset | Donor symbol | Decoded / checked quantity | Evidence |
|---|---|---|---|
| `0201:100c` | `CNA_CONV_CON1` | `[1:0]==3` depthwise; `[6:4]==2` input FP16; `[9:7]==2` processing FP16 | `make_conv2d_regs` 495-500 |
| `0201:1010` | `CNA_CONV_CON2` | `feature_grains = value>>4`; re-derived as `IH+KH` (deepwise: `min(13,IH+KH)`; pointwise vendor: `max(,52)`) and compared | `_feature_grains` |
| `0201:1014` | `CNA_CONV_CON3` | `stride = value[2:0] = value[5:3]` (x must equal y; `>2` refused, no capture evidence); upper bits must be zero | 505-508 |
| `0201:1020` | `CNA_DATA_SIZE0` | `IH = [15:0]`, `width_stride = [31:16]` | 509-512 |
| `0201:1024` | `CNA_DATA_SIZE1` | `IC = [31:16]+1`, `align_c = [15:0]` | 513-516 |
| `0201:1028` | `CNA_DATA_SIZE2` | `OW = value` | 517 |
| `0201:102c` | `CNA_DATA_SIZE3` | `atoms = value`; checked `atoms == OH*OW` | 518 |
| `0201:1030` | `CNA_WEIGHT_SIZE0` | weight BO bytes; re-derived from layout and compared | 521 |
| `0201:1034` | `CNA_WEIGHT_SIZE1` | weight bytes per output kernel `= KH*KW*align_c*2`; re-derived and compared | 524 |
| `0201:1038` | `CNA_WEIGHT_SIZE2` | `KW=[31:24]`, `KH=[23:16]`, `kernels=[15:0]` (`1` for depthwise, else `OC` per task) | 526-529 |
| `0201:1040` | `CNA_CBUF_CON0` | CBUF bank split; validated (`data_bank+weight_bank==12`, 1..11) and data bank re-derived from the donor formula (split-OC captures use the donor `full_data_bank` option -> `11` is an evidenced alternative) | 530-533 |
| `0201:1044` | `CNA_CBUF_CON1` | CBUF data entries; re-derived from geometry and compared | 534 |
| `0201:104c` | `CNA_CVT_CON0` | packing family control: vendor packed `0x01`; conv-simple spatial `0x0b` / pointwise `0x01` | 536, `conv_simple.make_regs` |
| `0201:1050..105c` | `CNA_CVT_CON1..4` | all `1<<16` (unit scale), required constant | 537-540 |
| `0201:1070` | `CNA_FEATURE_DATA_ADDR` | **input BO base** | 541 |
| `0201:1078` | `CNA_DMA_CON0` | burst configuration `0x000f000f`, required constant | 545-547 |
| `0201:107c`/`1080` | `CNA_DMA_CON1/2` | line/surface stride; re-derived from `width_stride`, `IH` and the packing mode and compared | `_dma_strides` |
| `0201:1084` | `CNA_FC_DATA_SIZE0` | `IW=[31:16]`, `IH=[15:0]` cross-check | 549-552 |
| `0201:1088` | `CNA_FC_DATA_SIZE1` | `align_c` cross-check | 554 |
| `0201:1110` | `CNA_DCOMP_ADDR0` | **weight BO base** | 556 |
| `0201:1180` | `CNA_CVT_CON5` | packing selection: vendor families (captured value `0` or `(1<<C2)-1`); conv-simple `(1<<IC)-1` -> NHWC `C2=IC`, else `C2=CVT5+1` | 557, `conv_simple.make_regs` |
| `0801:3010` | `CORE_MISC_CFG` | `[9:8]==2` FP16, `[1]` depthwise, `[0]` spatial; all cross-checked | 558-561 |
| `0801:3014` | `CORE_DATAOUT_SIZE_0` | `OH=[31:16]+1`, `OW=[15:0]+1` cross-check | 562 |
| `0801:3018` | `CORE_DATAOUT_SIZE_1` | `align_out_c = [15:0]+1` | 564 |
| `0801:3030` | `CORE_RESERVED_3030` | required zero | 565 |
| `1001:4004` | `DPU_S_POINTER` | required `0x0e` (PP mode) | 484 |
| `1001:400c` | `DPU_FEATURE_MODE_CFG` | depthwise conv mode `[4:3]`, output mode `[2:1]==2`, burst `[9:5]==15` | 590-594 |
| `1001:4010` | `DPU_DATA_FORMAT` | `out_precision[31:29]` (`2`=FP16, `5`=FP32), `proc[28:26]==2`, `in[2:0]==2` | 596-600 |
| `1001:4020` | `DPU_DST_BASE_ADDR` | **output BO base** | 601 |
| `1001:4024` | `DPU_DST_SURF_STRIDE` | `out_width_stride = value>>4`; re-derived from `atoms`/spatial rule and compared | 602 |
| `1001:4030..403c` | `DPU_DATA_CUBE_{WIDTH,HEIGHT,NOTCH,CHANNEL}` | cross-checks for `OW/OH/0/OC-1` and `align_out_c` | 603-613 |
| `1001:4040`/`4060`/`4070` | `DPU_BS_CFG`/`BN_CFG`/`EW_CFG` | bypass words `0x53`/`0x53`/`0x383`, required constants | 615-641 |
| `1001:4050` | `DPU_BS_OW_CFG` | conversion block size pattern (`e=3` depthwise/FP32 tail, `1` FP16 atom tail) | 631-635 |
| `1001:4058`/`405c` | `DPU_WDMA_SIZE_0/1` | output channel field and `OH/OW` cross-checks | 643-645 |
| `1001:4078` | `DPU_EW_CVT_SCALE_VALUE` | required 1 | 639 |
| `1001:4084` | `DPU_OUT_CVT_SCALE` | `[16]` FP32TOFP16 enable, must agree with `DATA_FORMAT[31:29]`; selects FP16 atom vs FP32 output layout | 640-641 |
| `1001:40c0` | `DPU_SURFACE_ADD` | surface distance; re-derived from `out_width_stride` and `align_out_c` | 663-664 |
| `2001:5004/5034/5044` | DPU-RDMA clear words | required zero (**54-word family only**) | 486-490 |
| `0101:0010`/`0014`, `0041:0000`, `0081:0008` | PC tail | required `0/0/0/0x0d` (one job, no chained task) | `write_regs_to_npu_task` 631-676 |

Derived quantities and the exact formulas implemented (all validated against
every fixture's actual BO file sizes):

| Quantity | Formula |
|---|---|
| `kernels` (OC lanes per frame) | `min(OC, 8)` |
| `C1_BLOCKS` | `ceil(OC / kernels)` (1 for every vendor capture, 2/4 for conv-simple OC16/OC32) |
| `taps` | `KH*KW` |
| weight layout | `depthwise` (vendor, `[ky][kx][C2]`), `kh_major` (vendor, `[ky][kx][OC][align_c]`), `chunked` (conv-simple, `[oc_chunk][kh][kw][16 OC lanes][align_c]`, `chunk_lanes=16`) |
| `plane_words` | `IH * IW * C2` (dense pixel walk; every captured case has `width_stride == IW` — a stream with row padding is refused) |
| input walk planes | `ceil(IC/C2)` real-channel planes loaded by the front (the production front's `PLANES = ceil(INPUT_CHANNELS/PACK_C2)`); the aligned BO may hold extra padded planes that are never read |
| `input_bytes` | `alloc_planes * IH*IW*C2*2`, `alloc_planes = 1` for NHWC (`C2==IC`) else `ceil(max(IC,align_c)/C2)` — the captured BO allocation, used only for the range gate |
| `weight_bytes` | per layout: vendor non-dw `taps*OC*align_c*2`; depthwise `taps*align_c*2`; conv-simple `ceil(C1_BLOCKS*kernels/16)*taps*16*align_c*2` — always equals the captured `CNA_WEIGHT_SIZE0` |
| `output_bytes` (FP16) | `DPU_DST_SURF_STRIDE * align_out_c/8` |
| `output_bytes` (FP32) | `OC * atoms * 4` (captured `[c1][pixel][c2=4]` FP32 surface) |
| validity | `IH == (OH-1)*stride + KH`, `IW == (OW-1)*stride + KW` (explicit-zero-frame captures become plain valid convolutions on the expanded input, which is exactly what the register fields describe) |

The golden model `tests/conv/runtime/conv_runtime_model.py` implements this
map. `python3 tests/conv/runtime/conv_runtime_model.py` decodes all 13 command
streams with **0 field-map problems** and every derived BO size equal to the
actual fixture file size; this is the offline evidence table for the RTL.

## 3. Decoder architecture and fail-closed policy

`rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv`:

1. **Canonical sequence whitelist.** Word 0 is always `DPU_S_POINTER`. Word 1
   discriminates the family: `RDMA_S_POINTER` -> 54-word (`conv_fp16`),
   `CNA_CONV_CON1` -> 52-word (`conv_simple`). From then on every word's
   `(target, offset)` must equal the next field of that family's table, in
   order; any other word, duplicate control field, wrong length or misplaced
   `cmd_last` is an explicit fault. The weight/output packing layout is a
   property of the captured driver path, not a register field; it is therefore
   **bound to the canonical sequence** and no other stream is accepted. This is
   a bring-up seam: a future unified image must add the real CNA layout
   selector once evidence exists.
2. **Decode** of the primary fields listed in §2 into a config register block.
3. **Derive-and-compare**: the redundant geometry/BO-size/schedule fields are
   re-derived from the primary fields with the donor formulas above and
   compared. A mismatch is an explicit fault; nothing is "corrected".
4. **Buffer gate**: all three bases 16-byte aligned, ranges inside the 32-bit
   address space, and pairwise non-overlapping using the derived byte sizes —
   the same gate the strict per-profile decoders apply.
5. **Supported-geometry gate**: `KH,KW <= 5`, `stride <= 2 && stride_x==stride_y`,
   `IC <= 32`, `IC <= align_c <= 32`, `C2 in {4,8}`, `OC <= 32`, `C1_BLOCKS <= 4`,
   `IH*IW <= 320` (store bound), weight halfwords <= 4608, square depthwise
   kernel. A self-consistent stream outside these bounds is **refused** with
   the unsupported-geometry code rather than executed with a widened
   interpretation.
6. One job per configuration: a second stream after validation is fault 7.

Error codes (decoder): `1` unknown/out-of-order/non-canonical field,
`2` field value or derived geometry unsupported (includes dtype/packing/
constant mismatch), `3` framing (`cmd_last`, length, family mismatch),
`4` buffer range/alignment/overlap, `7` second stream. Memory/front faults keep
the existing codes `5` (bus error), `6` (data), `8` (timeout).

## 4. Generalized front

`rtl/cmac/experimental/runtime/rk_conv_runtime_front.sv` keeps the production
frame contract exactly (`frame_data[511:0]`, `frame_weight[8191:0]`, masks,
`frame_output_address`, `frame_first/last/last_output`) but replaces every
elaboration-time loop bound and address expression with a runtime counter and a
runtime delta register:

* **Storage is sized for the corpus maxima**, not per case:
  `input_store[0:320*32-1]`, `weight_store[0:4607]` (single-port RAMs, same
  structure that keeps Vivado inferring block RAM; ~7 RAMB36).
* **Load phase** walks the weight BO linearly and the input BO pixel-major /
  plane / real-channel with the decoded `pack_c2`, `align_c`-derived plane
  stride and `IH/IW`; only real channels are fetched (padded BO lanes are never
  read, exactly like the production front).
* **Emit phase** is the same scheduled order as production
  (`block -> output atom -> kernel tap`), with `(bx,by,tx,ty)` counters instead
  of `atom%OW`, `tap/KW` runtime divisions and precomputed deltas
  (`tap_row_delta`, `tap_wrap_delta`, `atom_row_delta`, weight-lane step,
  block plane step). Two counters accumulate the frame weight group base and
  the output atom address; `frame_last_output` is an atom-count comparison.
* Masks and the depthwise diagonal mask are generated from the runtime
  `IC/KERNELS` values.

The front never writes memory; the CMAC/CACC array, the frame stage and the
arbiter are used unchanged, so the arithmetic is bit-identical by construction
and the equivalence harness can compare the frame stream as well as the output.

## 5. Output-layout modes

* **FP16 atom writer** (`rk_conv_output_atom`, `ATOMIC_K=8`): selected when
  `DATA_FORMAT[31:29]==2` and `OUT_CVT_SCALE[16]==1`; the runtime front supplies
  the atom address (block-major, 16-byte atoms), so the vendor profiles and the
  three FP16 `conv-simple` profiles use the same writer.
* **FP32 surface writer** (`rk_cmac_fp32_writer` behind a runtime placement
  stage): selected when `DATA_FORMAT[31:29]==5` and `OUT_CVT_SCALE==0`. The
  captured FP32 surface is `[c1][pixel][c2=4]` 32-bit words (measured, not
  assumed — see `docs/CONV_SIMPLE_FIXTURES.md`); the placement stage derives
  plane/slot from the frame's block index and writes the value unchanged. One
  captured case (`conv_simple_fp16_1x1_c4_h8_w8_oc16`).

## 6. Equivalence methodology

`tests/conv/runtime/tb_conv_runtime.sv` instantiates **both** the adopted
per-profile core and the runtime engine on the same clock and drives the same
unchanged command stream, operand BOs and memory handshake contract into two
independent memory models. Per case it compares:

1. frame stream equality (every frame's address, first/last/last_output, data,
   weight, data mask, weight mask, in order);
2. operand read sequence equality and the exact read count/addresses;
3. output write sequence equality;
4. **complete output BO equality** — the full output memory array (written
   region byte-for-byte against the fixture's `expected.bin`/`device_out.bin`
   plus the untouched canary padding) compared between the two engines and
   against the frozen capture;
5. error/busy/done/traffic counters.

For the pinned fixtures the reference is the adopted per-profile core; the
unpinned `conv_1x1_valid_c8_h5_w5_oc8` bundle has no per-profile core, so it is
replayed against its own captured bundle only and labelled `UNPINNED-BUNDLE` in
every receipt.

Negative controls (runtime engine only; each must raise the explicit code and
touch no operand/output memory): unknown target, unknown offset, swapped order,
early `cmd_last`, extra word, second stream, misaligned base, overlapping
buffers, 32-bit range overflow, dtype mismatch (`CONV_CON1` precision),
packing mismatch (`CVT_CON5` vs `align_c`/`C2`), `WEIGHT_SIZE2` vs weight BO,
out-channel/C1-block inconsistency, `stride>2`, non-square stride, depthwise
flag disagreement, unsupported kernel `>5`, X/Z DMA address.

## 6a. Prototype implementation map and current status

| Artifact | Role | Status |
|---|---|---|
| `tests/conv/runtime/conv_runtime_model.py` | golden runtime decoder + field-map evidence checker/twin of the RTL decoder | **PASS**: 13/13 command streams decode with 0 field-map problems; every derived BO size equals the actual fixture file size |
| `tests/conv/runtime/tb_runtime_decode_unit.sv` + `run_decode_unit.py` | decoder-only unit bench: replays all 13 command streams through the RTL decoder and diffs every config field against the golden model | **PASS 13/13** (`build/runtime-conv-lab/decode-unit/iverilog-20261109T224052Z/report.json`): geometry, packing, OC blocking, weight mode, BO sizes, loop constants and masks all equal the golden model; compile clean. One semantic bug found and fixed: the FP32-layout `block_plane_bytes` step was derived from input pixels instead of output atoms (invisible in the sole FP32 case, where both are 64) |
| `rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv` | strict canonical-sequence decoder, donor-formula derive/compare, buffer gate, bounded-geometry gate | drafted; Icarus-verified parse-clean in an earlier guarded syntax pass (heavy re-compile pending the Lead's window) |
| `rtl/cmac/experimental/runtime/rk_conv_runtime_front.sv` | generalized runtime-counted front, corpus-sized single-port operand stores | drafted |
| `rtl/cmac/experimental/runtime/rk_conv_runtime_fp32_output.sv` | runtime-configurable FP32 `[c1][pixel][c2]` placement (unchanged `rk_cmac_fp32_writer`) | drafted |
| `rtl/cmac/experimental/runtime/rk_conv_runtime_core.sv` | decode + front + unchanged `rk_frame_stage`/`rk_cmac_cacc_fp16_array` + runtime-selected output stage + one arbitrated memory master | drafted |
| `tests/conv/runtime/tb_conv_runtime_equiv.sv` | adopted per-profile core vs runtime engine equivalence bench (same stream/BOs; complete read/write sequence and complete memory-image compare) + decoder negative controls | drafted |
| `tests/conv/runtime/run_runtime_equiv.py` | fixture rebuild, guarded compile/run, output-BO-vs-capture compare, source-hash-bound receipts under `build/runtime-conv-lab/` | drafted; offline setup/compare logic self-checked for all 13 cases |

Verification sequence (heavy jobs only through
`build/verif/host_guard/safe_run.sh`, one at a time):

1. representative subset (`VALID`, `STRIDE2`, `conv_simple_fp16_3x3_c4_h8_w8_oc16`)
   in Icarus: equivalence + negative controls + capture compare;
2. the remaining vendor profiles and conv-simple profiles;
3. the unpinned `conv_1x1_valid_c8_h5_w5_oc8` bundle replay-only leg;
4. Verilator cross-check of the same cases;
5. synth-only area estimate with the parameterised maxima
   (`BENCH_CPUS=4-7 BENCH_CPU_QUOTA=200`, Tcl caps `general.maxThreads 2`).

Heavy-job status: **blocked by hardware** — the verification host's cooling has
failed (idle Tctl 92–100 °C with the fans reporting 3200 RPM), so no
simulation can complete; the Lead has put all launches on indefinite hold. One
attempted subset run was interrupted by thermal guard kills after a clean
compile; its partial results are recorded as **non-evidence** in
`build/runtime-conv-lab/PARTIAL_SIGNAL_NON_EVIDENCE.md`. The decoder-only unit
receipt (13/13 config-field PASS) is unaffected. The runner now supports split
`--leg primary` / `--leg controls` submissions so each post-repair window can be
short; this section will be replaced with the signed receipts (case -> PASS/FAIL,
complete BO bytes, source hashes) when a stable window exists.

## 7. Area estimate (synth-only) and fit

Method: out-of-context Vivado synthesis of `rk_conv_runtime_core` alone
(`tests/conv/runtime/synth_runtime_core.tcl`, driven by
`tests/conv/runtime/run_area_estimate.py`, synthesis only; no opt/place/route,
no bitstream), plus the per-block hierarchical utilization, compared with the
measured per-page costs from `build/jtag-dual-image/20261109T160627Z` and the
page-scaling notes (C4 pages ~39.8k LUTs, C16 page ~100.3k LUTs, six-page image
231,316 LUTs at 94.35% slices). The runtime engine has **no geometry
parameters** (geometry is runtime-decoded and the operand stores are sized for
the corpus maxima), so a single OOC synthesis is the complete area estimate —
it is the same one-engine area whether the incoming job is C4 or C16. The
receipt is written under `build/runtime-conv-lab/area/ooc-<stamp>/report.json`
with `source_hashes_before/after`, the tool version and the utilization
breakdown.

### 7.1 Explicit SDP-BRAM mapping for the D1 area estimate

Vivado 2026.1 refuses to infer block RAM for the prototype front's plain
unpacked-array operands in out-of-context synthesis (it offers only to dissolve
them into flip-flops, which would make the area number meaningless). The D1
area number therefore covers an **explicit simple-dual-port BRAM mapping** of
the same two stores, `input_store` (163,840 bits, 16-bit x 10,240) and
`weight_store` (73,728 bits, 16-bit x 4,608), via
`rtl/cmac/experimental/runtime/rk_runtime_sdp_bram.sv`, instantiated in
`rk_conv_runtime_front.sv` under `` `ifdef SYNTHESIS ``. The weight store is
padded to a power-of-two depth (8192 entries, only 4608 used) so Vivado infers
BRAM instead of ~19.8k LUTs of logic. The corpus-verified lane parameters are
implemented **additively** in experimental copies
(`rk_runtime_fp16_cell.sv`, `rk_runtime_fp16_array.sv`,
`rk_runtime_cacc_fp16_array.sv`, `rk_runtime_frame_stage.sv`, all under
`rtl/cmac/experimental/runtime/`) so the FINAL-frozen leaf files are untouched;
the runtime core uses C=16 channels x K=16 kernel lanes (C4/C16 corpus; the
frozen cell only supports C in {8,32,64}). Geometry and semantics
are identical to the arrays: one synchronous write port and one synchronous
registered read port, read data holds when `re` is low; no scheduling, gating
or arithmetic change. **The simulation RTL path is unchanged** (the arrays are
still used when `SYNTHESIS` is not defined), so the accepted Leg A/Leg B
receipts remain valid for the simulation path; the source file hash changes only
by the `` `ifdef SYNTHESIS `` block. S1 page integration will adopt this
explicit memory mapping in the built image and re-run equivalence, so the
synthesized design and the simulated design are the same memory mapping.

Expected shape (to be replaced by the measured receipt):

| Block | Expected cost |
|---|---|
| 512-lane CMAC array + CACC (unchanged) | identical to the large page |
| generalized front stores | 7 RAMB36 (same as the four conv pages together) |
| runtime decode + derive | small (a few hundred LUTs; tiny arithmetic) |
| generalized front counters/deltas | ~2-4k LUTs over a fixed front |
| both output stages | ~1-2k LUTs |

A single runtime engine capable of the C16 geometry (~105k LUTs estimated)
would replace the four per-profile conv pages (C4, C4 k5, C16, FP32 C4; the C16
page alone is 100.3k) and free roughly 110-140k LUTs / a large share of the
current 94.35% slice occupancy. If the measured engine exceeds ~150k LUTs, the
fallback split is `FP16-atom` and `FP32-layout` paths sharing the same decoder
and front storage.

## 8. Staged integration plan

1. **Now (task-13)**: design + prototype + old-vs-new equivalence on the frozen
   fixtures; production image untouched.
2. **Stage 2** (needs a separate task/approval): conv-fp16-only runtime image —
   replace the vendor conv pages with one runtime engine instance, keep the
   conv-simple/GEMM/pooling pages, rebuild + re-run the page-presence and
   contract gates, emit a new bitstream receipt. The adopted image stays the
   reference until that image passes the same gates.
3. **Stage 3**: main-image replacement — one runtime engine page for the whole
   conv corpus; re-run the full frozen-tree replay matrix (dual 0-8, mailbox
   0-6, conv-simple, vendor profiles) against the new image hash and update
   `progress.md`/`handoff.md`; do not cite the superseded tree.
4. Any hardware step remains separately authorized (no programming here).

## 9. Risks and blockers

* **Layout seam**: the weight/output packing difference between the two
  driver families is not encoded in the register stream. The prototype binds it
  to the canonical sequence; unifying images must either keep the two families
  as two accepted sequences or add an evidenced layout field.
* **Row padding**: all captured cases have `width_stride == IW`; a stream with
  padded rows is refused (`unsupported`), not silently mis-walked.
* **Bounded geometry**: store sizing is the corpus maxima (320 input pixels,
  4608 weight halfwords, OC<=32, C1_BLOCKS<=4), not full RK3588 CNA limits.
* **CBUF schedule fields**: the front streams operands from memory and does not
  implement CBUF, so `feature_grains`/`data_bank`/`cbuf_entries` are validated
  against the donor formulas rather than consumed. The split-OC
  `full_data_bank` alternative is accepted as an evidenced value.
* **Area/timing** must be re-measured on the real image; a single engine is
  time-multiplexed across jobs anyway (one AXI job at a time), so no throughput
  is lost relative to the per-page image.
* **Heavy-job policy**: every compile/synthesis goes through
  `build/verif/host_guard/safe_run.sh`; no hardware access.
