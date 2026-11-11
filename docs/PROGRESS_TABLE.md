# Progress table — 2026-11-09

Status of the "run the RK3588 examples on FPGA" objective. Rows marked
**bitstream** come from a real Vivado implementation; nothing on this card has
been programmed, so **no FPGA execution has been observed**.

## 2026-11-10/11 current status (supersedes the dated rows below where they conflict)

Updated 14:10 HKT. The sections after this one are the 2026-11-09 long-form
snapshot; this block is the current state. Live: the runtime-engine equivalence
verdict run is executing (long, ~35 min so far) on a cool host window.

### A. Objective-level status ("run all ~/rk3588/examples on the FPGA")

| Definition-of-done item | State |
|---|---|
| Every captured example has an executing command stream / page or leaf | **Partial, much improved**: conv-simple 4/4 in adopted image; pooling 19/19 replay through the pooling-corpus image (Icarus+Verilator PASS, bitstream deferred by cooling); GEMM 4/4 in image; conv-fp16 9/9 live-verified (defined-lane) and runtime-decoded engine prototype at equivalence-verdict stage; EW families covered by the emitted EW image; ew-int / vendor-ABI / dtype-shape cases explicitly unsupported |
| One bitstream carries needed pages, closes timing/DRC, SHA recorded | **Two emitted**: six-page `20261109T160627Z` (PASS, WNS +3.952, SHA `81eef4cd…4d39`) and EW image `host-jtag-preparation/20261109T210015Z-emission` (PASS, WNS +0.670, SHA `b373ee70…f59a`). Pooling-corpus image: design+dual-sim PASS, bitstream deferred (thermal); merged single-image plan written (`docs/MERGED_IMAGE_PLAN.md`, D1-D5 decided) |
| Image programmed onto an audited board | **No** — nothing programmed/flashed, `hardware_accessed=false`; DLC10 cable not attached |
| Examples submitted/read back/compared on hardware | **No** — FPGA board session awaits cable + user authorization (RK3588 live differential is separate silicon evidence) |

### B. Real-silicon (RK3588) differential status

| Item | State |
|---|---|
| Live capture corpus | 122/122 READY captured across 7 families |
| P0 image-corpus verification | Complete: 8 locked jobs / 35 case-runs; conv-simple 4/4, pooling 1/1, GEMM 3/4 exact + 1 within 9.54e-7; live SHA == frozen captures |
| P1 family-wide differential | **38/38 READY PASS** (conv-fp16 9/9 defined-lane exact; conv-gemm-vendor 10/10; pooling 19/19); one class-D padding non-determinism documented |
| P2 live differential + probes | **ew-fp16 54/54 complete-BO exact** (donor oracle 52/54; exactly the 20 documented A/7 one-ULP lanes), determinism **5/5 byte-identical** across separate lock windows, boundary probes reproduce only the documented class-D blockers |
| FDIV differential | **Closed 1,452/1,452 captured lanes** live-verified vs capture + three-guard-bit model |
| Race control | Single owner, `flock -x -w 900`, one runner, fresh dirs, hashes both ways — no violations |

### C. RTL / image / engine workstreams

| Workstream | State |
|---|---|
| Six-page adopted image | PASS + bitstream `81eef4cd…4d39`; replay matrix partially refreshed (vendor 16/16, dual 0-5, mailbox 0) |
| CMAC cell/array timing fix (option A) | Done; proofs PASS; 50 MHz closed |
| EW image (elementwise/simple_add/FDIV) | **Emitted** `b373ee70…f59a` (WNS +0.670, 6,157 LUTs), admission `SOURCE_INTACT_REVIEW_PENDING` (human reviewer); FDIV audited end-to-end |
| Pooling-corpus image (19 fixtures) | **Design frozen**; Icarus+Verilator 19/19 PASS; **D2 measured whole-image synth: 110,107 LUTs (36.87 %), 33,044 regs, 8 RAMB36** (2.4× the labelled pre-synth estimate — two expensive leaves page0/page3 were never sampled; OOC method validated); full build queued; hotspots page0 55.3k/page3 11.9k noted as future optimisation only. Image B budget ~120k (40 %), ample headroom |
| Runtime-decoded conv engine | **FULLY VERIFIED** (leg A 3/3 PASS byte-exact; leg B 51/51 controls); **D1 measured: 167,858 LUTs (56.2 %), 29,664 FFs, 12 BRAM, 15 DSP** with additive C16xK16 engine (-49.9 % vs 335k prototype); frozen production files untouched (518/518); **two-image split adopted** (Image A conv+GEMM ~176k; Image B pooling+EW ~40-45k); next: parameterised leg A/B hash-bound re-run → S1 page attach → builds in cool windows |
| Multi-image deployment | Documented (`BOARD_RUN_PREP.md` §15-17); **85 offline host tests OK**; two pinned fail-closed replay harnesses + operator runbook; EW inventory filled; pooling pending bitstream |
| Two-image split (S1/S3 scaffolding) | **Adopted** after D1: Image A = runtime conv + GEMM (~176k LUTs), Image B = pooling band + EW FP16/FDIV + ew-int (~40-45k). Image A top/profile/renderer/REF_NAME gates + ABI bench PASS + replay plan (15 fixtures/796 QWORDs, PLAN_READY). Image B top/profile/renderer scaffolded; **ew-int page-form complete**: 4-bank 16 KiB aperture audit PASS, RKEI page + aperture RTL, 15/15 both-sim BO replays + 8 negatives PASS, ABI STATUS correction pending profile fix; 50+ merged offline tests. Gates: conveng GREEN + wrapper → S1 replays; ewint refs flip + S3/S4 replays; builds in Lead-scheduled cool windows |
| Host power/thermal | New charger fixed brownouts; guard **v4.3** (sustained median 97 °C / instant 104 °C / streak 101×2 — temporary for shared host); shared cooperative heavy lock + gate documented (`docs/HOST_SHARED_LOCK.md`) |
| Shared host coordination | **Done**: one lock `/tmp/rknpu-heavy.lock`, shared gate `/tmp/rknpu-heavy-gate.sh` (sustained <72 °C, pin/quota, log), FIFO fairness; `foreign_hold` SIGSTOP only as fallback |

### D. Verification matrix (FINAL-freeze source-hash bound)

| Leg | State |
|---|---|
| Vendor conv 8 cases × 2 simulators | **16/16 PASS** |
| Dual-endpoint (six-page image) | modes **0-5 PASS**; mode 6 aborted ×4 (all thermal/foreign-load interruptions, excluded); modes 7-8 pending |
| USER2 mailbox | mode 0 PASS; modes 1-2 pending; 3-6 deferred |
| Conv-simple standalone 4 profiles | queued behind priority legs |
| Contract suites | 247 image/conv/ppu/cmac tests OK; `make generated-check` OK; frozen manifest 518/518 |
| Runtime-engine equivalence | decoder 13/13 PASS; replay verdict in progress (frame-stream + full-image compare) |

### E. Open blockers / decisions

| Item | Owner |
|---|---|
| DLC10 cable attached + explicit authorization for volatile load | **user** |
| Host cooling marginal + shared TPU/openTPU/ladder load; cooperative lock now in place, TPU side to adopt `/tmp/rknpu-heavy-gate.sh` | user + both projects |
| Runtime-engine equivalence verdict → leg B controls → area estimate (D1) | conveng (running) |
| verif mode-6/7/8 + mailbox 1-2; conv-simple | verif |
| Pooling exact fit + Icarus receipt refresh + full build (cool window needed) | share |
| Merged-image staged build (D1-D4 decisions recorded; needs cooling + area numbers) | timing/Lead |

## 1. Capture corpus and fixture coverage

Checked against the family manifests under
`build/rk3588-example-captures/` and the fixtures under `tests/`.

| Capture family | READY | BLOCKED | Fixtures pinned | Missing |
|---|---:|---:|---|---|
| `ew-fp16` | 54 | 0 | vectors + fixtures | 0 |
| `ew-int` | 15 | 3 | vectors | — |
| `pooling` | 19 | 2 | **19 / 19 READY** (+1 source-derived) | **0** |
| `fdiv-systematic` | 8 | 0 | vectors | 0 |
| `conv-fp16` | 9 | 5 | **9 / 9** | **0** |
| `conv-gemm-vendor` | 10 | 3 | **7 frozen** | **3 rejected** |
| `conv-simple` | 7 | 5 | **4 frozen, all executing** | **3 rejected** |

Notes that the counts above hide:

* The 20th pooling fixture, `fp16_max_k16s16_c8_h16w16`, is source-derived
  rather than captured; all 19 READY captures are frozen.
* All four frozen `conv-simple` captures now execute. The fourth,
  `conv_simple_fp16_1x1_c4_h8_w8_oc16`, has FP32 device output and runs through
  profile 3 plus `rk_conv_output_c1c2_fp32`; it is no longer data-only.
* Three `conv-simple` READY captures are **rejected**, not pending: the device
  output disagrees with the host oracle (1536, 7 and 13 elements respectively).
  Details in `docs/CONV_SIMPLE_FIXTURES.md`.

## 2. Convolution RTL — replay status

| Profile | Case | Icarus | Verilator |
|---|---|---|---|
| 1×1 C8 | `conv_1x1_valid_c8_h5_w5_oc8` | PASS | PASS |
| `VALID` | `conv_3x3_valid_c4_h9_w9_oc4` | PASS | PASS |
| `STRIDE2` | `conv_3x3_stride2_c4_h11_w11_oc4` | PASS | PASS |
| `PAD1_ZERO_FRAME` | `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` | PASS | PASS |
| `GROUPED_C2` t0 / t1 | `conv_grouped_3x3_c4_h5_w5_oc8_g2_task0/1` | PASS | PASS |
| `SPLIT_OC_C16` t0 / t1 | `conv_splitoc_3x3_c16_h9_w9_oc16_task0/1` | PASS | PASS |
| `DEPTHWISE_C3` | `conv_depthwise_3x3_c3_h11_w28_oc3` | PASS | PASS |
| **conv-simple k3×3 C4 OC16** | `conv_simple_fp16_3x3_c4_h8_w8_oc16` | **PASS** | **PASS** |
| **conv-simple k5×5 C4 OC16** | `conv_simple_fp16_5x5_c4_h8_w8_oc16` | **PASS** | **PASS** |
| **conv-simple k3×3 C16 OC32** | `conv_simple_fp16_3x3_c16_h8_w8_oc32` | **PASS** | **PASS** |
| **conv-simple k1×1 C4 OC16 (FP32)** | `conv_simple_fp16_1x1_c4_h8_w8_oc16` | **PASS** | **PASS** |

The FP32 row is a single-job replay (`tools/conv/run_conv_simple_fp32.py`,
profile 3, `OUTPUT_FP16=0`; receipts
`build/conv-simple-fp32/{iverilog,verilator}-20261108T193215Z`). The complete
4096-byte BO is compared with an explicit `0.001` absolute bound: 63 of 1024
words differ at the last bit, worst deviation 4.77e-7. Byte-exactness is not
claimed there, because the capture's oracle is float64 rounded to float32 and
this RTL accumulates in the NVDLA CACC.

The conv-simple rows run 13 modes each (complete output BO plus six
raw-profile rejections, four memory faults and one second-stream rejection) in
both simulators. The 5×5 and C16 cases only pass once their captured BO
placement (`0x4000`/`0x5000` output) is honoured; the earlier failures were
hardcoded addresses in the bench, not arithmetic.

## 3. Pooling RTL — executing profiles

**All 20 frozen pooling fixtures now execute, each in both simulators**, with
a complete-4096-byte-BO comparison and two negative controls per run:

| Group | Cases |
|---|---|
| FP16 max | valid C8 4×4, padded (−inf) 2×2, C3 tail 2×2 s2, indexed 2×2 s2, global 16×16, **padded 3×3 s2 H4W4** |
| FP16 min | valid C8 4×4 |
| FP16 average | C8 4×4 s1 (atol 0.0625), global C8 3×5, **padded 2×2 s1 H1W1 ×2** |
| INT8 | max/min C16 2×2 s2, **1×1 C32 identity**, **Q16 averages ×2** |
| INT16 | max/min C8 2×2 s2, **Q16 averages ×2** |

The Q16 average rule is documented as **candidate behaviour**: every captured
lane sum is an exact multiple of the area, so truncation toward zero and floor
division are indistinguishable in the data. The leaf divides by the kernel area
and records that the reciprocal form does *not* reproduce the k3×3 captures.
See `docs/PPU_Q16_AVERAGE.md`.

## 4. Elementwise

| Profile group | Evidence |
|---|---|
| `ew-fp16` ADD/SUB/MUL/MAX/NEG | real RK3588 differential, exact at 8 lanes |
| `ew-fp16` FDIV | 1,452 captured lanes match, incl. 20 A/7 one-ULP-low |
| `ew-int` INT8/16/32 | captured vectors, model + RTL suites pass |
| `fdiv-systematic` | 8 class-row matrices pass |

This is the only group with real-silicon differential evidence.

## 5. Endpoint / board

| Layer | State |
|---|---|
| Raw conv cores | 9 profiles + 4 conv-simple profiles, dual-simulator |
| FP32 GEMM page | **exists** — `rk_cmac_gemm_axi` (RKCM), 5 standalone modes + 2 image modes + 1 mailbox mode, all in both simulators; the page is decode-driven, so **one page serves all four frozen GEMM shapes** |
| AXI4 -> halfword bridge | **exists** — `rk_axi_mem_slave`, unit bench PASS |
| Conv descriptor DMA | C4 profiles only |
| Conv AXI-Lite endpoint | **exists** — `rk_conv_simple_axi` (RKCS), 8 modes; all four profiles pass in both simulators, and each profile is now its own image page |
| Pooling AXI-Lite endpoint | **exists** — `rk_ppu_pool_axi` (RKPP), 8 modes, both simulators |
| Host memory bridge | **exists** — `rk_axil_mem_bridge`, unit bench, 8 cases |
| Unmapped-address rejection | **exists** — `rk_axil_error_slave`, always SLVERR |
| Dual-endpoint image (`ypcb_dual_endpoint_top`) | **exists and simulates** — one AXI port, **six** pages (conv FP16 p0, pooling, FP32 GEMM, conv FP32 p3, conv k5 p1, conv C16 p2), host-loaded BOs |
| Dual-endpoint build profile | `fpga/dual/sources.json`, renderer + gates |
| Conv in a top-level design | **yes** — `ypcb_conv_simple_top`, bitstream emitted |
| conv-simple descriptor + core (`rk_conv_simple_core`) | exists, 4 profiles; all four are now separate image pages |
| Pooling raw DMA + 8 FP16 profiles | exists, simulation only |
| Signed-integer k2s2 reducer | exists, dual-simulator |
| INT8 26-QWORD descriptor endpoint | exists, 9 modes, dual-simulator |
| Pooling board image (`ypcb_ppu_i8_top`) | routed **and emitted**: `rk_ppu_i8.bit` |
| Conv board image (`ypcb_conv_simple_top`) | routed **and emitted**: `rk_conv_simple.bit` |
| Build profiles | explicit in `fpga/ppu/sources.json`, `fpga/conv/sources.json`, `fpga/dual/sources.json` |
| Bitstream | **six emitted**, all with `CONFIG_VOLTAGE 1.8` / `CFGBVS GND`. The newest (`...T073000Z`) carries **four** pages and asserts each instance exists. The **six-page** top synthesizes and routes but **FAILED the 50 MHz timing gate** (WNS -1.549 ns, no bitstream) — see "The six-page build: from synthesis failure to timing closure" below |
| FPGA board run | **none** — nothing programmed, no cold boot |
| Host driver | **none** — no driver has run on the card. The pin-free USER2 image now exists as a bitstream; the bare-AXI variant stays unbuilt (no pin budget) |

| Image | Receipt | WNS | WHS | BRAM | Bitstream SHA-256 |
|---|---|---:|---:|---:|---|
| pooling | `build/ppu-image/20261108T170500Z` | +14.633 ns | +0.037 ns | 2 | `1908003f…36a5` |
| conv | `build/conv-image/20261108T171500Z` | +0.412 ns | +0.076 ns | 8 | `cddb583b…8b08` |
| host-drivable (JTAG), two pages | `build/jtag-dual-image/20261109T001500Z` | +0.076 ns | +0.065 ns | 8 | `f53ae24a…b02e1` |
| host-drivable, three pages incl. FP32 GEMM | `build/jtag-dual-image/20261109T043000Z` | +0.141 ns | +0.036 ns | 8 | `f86d4d9c…f31416` |
| host-drivable, four pages incl. FP32 conv | `build/jtag-dual-image/20261109T062000Z` | +0.044 ns | +0.058 ns | 8 | `c849a69c…02061e` |
| **host-drivable, four pages, page-presence gated** | `build/jtag-dual-image/20261109T073000Z` | **+0.044 ns** | **+0.058 ns** | 8 | `73dd0365…94cf7` |
| host-drivable, six pages (many-port arrays) | `build/jtag-dual-image/20261109T120000Z` | **none** | **none** | — | synthesis failed: 73,728-bit many-port store |
| host-drivable, six pages (streaming RAMs) | `build/jtag-dual-image/20261109T180000Z` | **-1.549 ns** | **+0.016 ns** | 19.5 | **no bitstream: timing gate refused** (records core `7ed427c9`; current is `9da3dac4`, so rebuild for a source-matched number) |
| **host-drivable EW (elementwise/simple_add/FDIV), separate image** | `build/host-jtag-preparation/20261109T210015Z-emission/bitstream` | **+0.670 ns** | **+0.053 ns** | 256 | `b373ee70…f59a` |

All six completed runs have 0 failing endpoints, 0 `no_clock` pins and 0
unconstrained internal endpoints. The newest image adds `DPIP-1`/`DPOP-1`/`DPOP-2`
pipelining advisories alongside the existing `CHECK-3`/`REQP-1839` warnings;
none is a blocking severity. The conv image keeps three DRC warnings (`REQP-1839` ×20 on the BRAM
write address, `RTSTAT-10` on two unobserved `error_code` bits, and a `CHECK-3`
rule-limit notice); the pooling image has no DRC findings; the host-drivable
image carries `CHECK-3` and the same `REQP-1839` class, both warnings only.
CFGBVS-1 disappears once the electrical pair is supplied.

Two receipts are deliberately **not** published as evidence:

* `build/jtag-dual-image/20261109T031500Z` wrote a `.bit` but its process was
  stopped before the final report, so its `inputs.json` still says `RUNNING`.
  A `.bit` without a completed gate report is not a receipt.
* `build/jtag-dual-image/20261109T040000Z` and `...T043000Z` are superseded
  builds: the first had only three pages, the second predates the FP32 conv
  page. Their gate reports are real, but they do not describe the current top.

### The six-page build: from synthesis failure to timing closure

`build/jtag-dual-image/20261109T120000Z` was a real Vivado run of the six-page
top and it **failed at `synth_design`**. The error was not a constraint or
timing gate, it was the datapath:

```
ERROR: [Synth 8-3391] Unable to infer a block/distributed RAM for
'weight_store_reg' ... the number of bits (73728) is too large
[dissolveMemorySizeLimit is 65536]
```

`rk_conv_3x3_valid_c4_front` reads `weight_store` **combinationally at many
indices at once** (one read per kernel lane per channel) to build the 8192-bit
`frame_weight` bus. That is a many-port array, so Vivado cannot map it to BRAM
(`RAM has too many ports`), and it falls back to registers. Profile 2's C16
geometry needs `TAPS*WEIGHT_LANES*CHUNKS = 9*16*16*2 = 4608` halfwords =
**73,728 bits**, which is over the dissolve limit, so synthesis stops instead of
spending a quarter of the device on flip-flops.

Measured weight-store sizes per profile:

| Page | Capture | Weight halfwords | Bits | Fits the 65536 dissolve limit |
|---|---|---:|---:|---|
| profile 0 | 3×3 C4 OC16 | 1,152 | 18,432 | yes |
| profile 3 | 1×1 C4 OC16 | 128 | 2,048 | yes |
| profile 1 | 5×5 C4 OC16 | 3,200 | 51,200 | yes, but ~51k LUTs |
| profile 2 | 3×3 C16 OC32 | 4,608 | **73,728** | **no** |

### Round 1: the many-port arrays are gone (synthesis now passes)

`rk_conv_3x3_valid_c4_front` no longer holds a many-port array. Both the weight
BO and the feature window are **single-port block RAMs**, and
`frame_weight`/`frame_data` are registered buses filled one halfword per cycle.
Vivado maps all four conv pages' stores to block RAM:

```
conv_page       input_store_reg 2 K x 16, weight_store_reg 1 K x 16
conv_fp32_page  input_store_reg 2 K x 16, weight_store_reg 128 x 16
conv_k5_page    input_store_reg 2 K x 16, weight_store_reg 3 K x 16
conv_c16_page   input_store_reg 2 K x 16, weight_store_reg 4 K x 16
```

Synthesis now completes. `build/jtag-dual-image/20261109T180000Z` reached
routing with **324,049 nets fully routed** and a clean DRC (`CHECK-3`×2,
`DPIP-1`×12, `DPOP-1`×6, `DPOP-2`×6, `REQP-1839`×20 — all warnings).

### Round 2: it does not close timing at 50 MHz

That same run **failed the timing gate**. Receipt:

| Gate | Value |
|---|---|
| Status | **FAIL**, `bitstream_emitted=false`, `hardware_accessed=false` |
| WNS / TNS | **-1.549 ns** / -160.574 ns |
| Failing endpoints | **244 of 115,597** |
| WHS / THS | +0.016 ns / 0 |
| Slice LUTs | **228,817 (76.63%)** |
| Slice registers | 41,730 (6.99%) |
| Block RAM | 19.5 tiles (2.04%) |
| Worst path | `conv_c16_page/.../stage/data_q_reg[21]` -> `.../arithmetic/cmac/out_groups_reg[121]` |
| Path delay | 21.538 ns: **logic 4.325 ns (20%)**, **route 17.213 ns (80%)**, 52 logic levels |

`rk_frame_stage` did what it was for — the worst path starts at the stage's
output register, not the front's — but the CMAC cell's own combinational work
(32-lane exponent max, the donor multiplier, row sums, per-tag compensation and
a 32-way serial sum) plus the routing needed to reach it is 21.5 ns. With the
device at 76.6% LUT utilisation, 80% of that is routing.

**The six-page image with four separate 512-lane CMAC arrays does not fit 50 MHz.**
The failing endpoint count is 244, not a handful, so this is not a placement
outlier that another seed fixes.

Options, none of them free:

1. **Pipeline `rk_cmac_fp16_cell`.** Split the exponent-max reduction and the
   32-way sum into registered stages and carry valid/tag through them. This
   changes the cell's latency, so every conv and GEMM replay must be re-proven
   byte-for-byte.
2. **Share one CMAC array** between the conv pages with a time-multiplexed
   scheduler instead of four copies. Big architectural change; it also removes
   the 76.6% LUT pressure that makes routing dominant.
3. **Drop the C16 page** and ship five pages. Fewer endpoints failing because
   less logic, but it concedes profile 2 to simulation only.
4. **Lower the clock.** Legitimate but changes the documented 50 MHz contract;
   not done, and not proposed as a shortcut here.

No option was implemented in this turn. The receipt above is the deliverable:
the six-page build is **routed, DRC-clean and timing-refused**, and the exact
failing path is recorded rather than rounded away. See
`docs/CONV_PAGE_SCALING.md`.

### Dual-endpoint image

`ypcb_dual_endpoint_top` is the first host-drivable image: one AXI4-Lite slave
serves a 32 KiB memory window (`0x0000..0x7fff`) and **six** transport pages.

| Page | Address | Identity | Capture |
|---|---|---|---|
| conv FP16 profile 0 | `0x8000` | `0x524b4353` `RKCS` | 3×3 C4 OC16 |
| pooling | `0x9000` | `0x524b5050` `RKPP` | INT8 max k2s2 C16 |
| FP32 GEMM | `0xa000` | `0x524b434d` `RKCM` | all four GEMM shapes (decode-driven) |
| conv FP32 profile 3 | `0xb000` | `0x524b4415` | 1×1 C4 OC16, FP32 out |
| conv k5 profile 1 | `0xc000` | `0x524b4416` | 5×5 C4 OC16 |
| conv C16 profile 2 | `0xd000` | `0x524b4417` | 3×3 C16 OC32 |

`0xe000` and above is an explicit SLVERR. The host loads the frozen BOs through
the memory window (`rk_axil_mem_bridge`, one 32-bit access -> two halfword
transactions), submits through a page, and reads the complete output BO back.

Each page is a **separate instantiation**, not a run-time profile switch: the
conv geometry is an elaboration parameter. The GEMM page is the exception —
`rk_cmac_profile` derives rows/ai/ao from the command stream, so one page serves
`gemm_m2_n2_k1`, `gemm_m1_n16_k32`, `gemm_m2_n16_k32` and `gemm_m4_n32_k64`
with no extra LUTs.

`tools/dual/run_dual_endpoint.py` replays **nine** modes (0-8). Modes 1 and 2
compare the entire captured BO; mode 3 asserts the cross-page exclusion while a
conv job runs; modes 4-5 do the same for the FP32 GEMM page; mode 6 runs the
FP32 conv profile on `0xb000`; modes 7-8 run conv profiles 1 and 2 on `0xc000`
and `0xd000`. The GEMM case is selectable (`--gemm-case`). See
`docs/DUAL_ENDPOINT_IMAGE.md`, `docs/CONV_FP32_PAGE.md` and
`docs/GEMM_FP32_AXI_PAGE.md`.

A full Vivado run of the current top (`build/dual-image/20261108T134500Z`)
reached route with **WNS +0.260 ns / WHS +0.055 ns, 8 × RAMB36, 46,819 LUTs,
19,972 registers, 0 DSPs, 0 failing endpoints**, then stopped before a
bitstream on `NSTD-1`/`UCIO-1`: 152 of 156 logical ports are the 32-bit AXI
slave, and no board pin budget for it exists. **No bitstream exists for this
image, and none should be invented.** Use the pin-free successor instead:
`ypcb_jtag_dual_top` over the USER2 mailbox is routed and emitted —
see `docs/JTAG_DUAL_IMAGE.md`.

## 6. Verification run just now

```
python3 -m unittest tests.test_dual_endpoint_contract    -> Ran 61 tests  OK
python3 -m unittest discover -s tests/conv  -p 'test_*contract.py'  -> Ran 60 tests  OK
python3 -m unittest discover -s tests/ppu_pooling -p 'test_pool_*contract.py'
                                                          -> Ran 106 tests OK
python3 -m unittest discover -s tests/cmac -p 'test_*contract*.py'
                                                          -> Ran 20 tests  OK
make axil-mem-bridge-test   -> PASS AXI_MEM_BRIDGE responses=14
make jtag-axil-bridge-test  -> PASS JTAG_AXIL_BRIDGE sequences=9
make cmac-fp32-writer-test  -> PASS CMAC_FP32_WRITER writes=6 (Icarus + Verilator)
make cmac-output-fp32-test  -> PASS CMAC_OUTPUT_FP32 writes=6 (Icarus + Verilator)
make cmac-gemm-fp32-test     -> 4/4 GEMM fixtures PASS (Verilator)
make cmac-gemm-fp32-four-state-test -> 4/4 GEMM fixtures PASS (Icarus)
make conv-simple-fp32-test   -> profile 3 PASS in both simulators
make gemm-fp32-axi-test     -> 5/5 modes PASS (Verilator), k=1 byte-exact
make gemm-fp32-axi-four-state-test -> 5/5 modes PASS (Icarus)
make generated-check        -> pooling demo ROM matches the frozen capture
git diff --check           -> clean
```

Dual-endpoint replay (`tools/dual/run_dual_endpoint.py`) on the **six-page**
top: all nine modes (0-8) have **PASS** Verilator receipts
(`build/dual-endpoint/verilator-20261109T034423Z` modes 0-6,
`...verilator-20261109T031949Z` modes 7-8). Their recorded **top** hash matches
the file on disk, but the recorded `rk_conv_3x3_valid_c4_front.sv`,
`rk_frame_stage.sv` and `rk_conv_simple_core.sv` hashes predate the streaming
front and the stage, so they are **stale for the current RTL** and must be
regenerated. The Icarus nine-mode replay was started and abandoned when the
server restarted; **no Icarus receipt is claimed**, and older trees were deleted
rather than carried forward.

Mode 6 compares the complete 4096-byte BO with its explicit `0.001` bound (63 of
1024 words differ at the last bit, worst 4.77e-7). Modes 7-8 compare the complete
4096-byte BO at the capture's own output base (`0x4000` and `0x5000`) and are
byte-exact.

USER2-mailbox replay (`tools/host/run_jtag_dual.py`) on the pin-free top:
**five modes PASS in Verilator** on the **four-page** image
(`build/jtag-dual/verilator-20261109T013805Z`, modes 0-4), plus a selectable-GEMM
mode-3 run (`...T020931Z`, `gemm_m2_n16_k32`). Those receipts record a real
`Verilator 5.048` version string and source hashes before/after the run.
Mailbox modes 5 and 6 (conv profiles 1 and 2 on `0xc000`/`0xd000`) also
**PASS in Verilator**, with real tool versions and matching top hashes
(`...verilator-20261109T034146Z` mode 5, `...verilator-20261109T040013Z`
mode 6). The first mode-6 attempt failed on a **bench defect**, not RTL: the
mailbox bench's scratch arrays were fixed at 2048 words and profile 2's weight
BO is 2304; they are now 4096.

Mode 1 is a conv job loaded entirely through 64-byte frame writes with the
**complete 4096-byte BO** compared back (195 frames); mode 2 is the same for
pooling (212 frames); mode 3 is the FP32 GEMM job (280 frames); mode 4 is the
FP32 conv profile-3 job (175 frames, explicit `0.001` bound). Mode 0 covers page
identities, word/block round trips, misaligned-block refusal and unmapped-page
SLVERR + quarantine.

Conv endpoint sweep (`tools/conv/run_conv_simple_axi.py`): **8/8 modes pass in
both simulators for the three FP16 endpoint profiles**
(`build/conv-axi/iverilog-20261108T150115Z-{0,1}`,
`build/conv-axi/iverilog-20261108T163358Z-2`,
`build/conv-axi/verilator-20261108T150115Z-{0,1,2}`). The C16 run needed the
runner's wall-clock cap raised from 900 s to 7200 s; it was a timeout, never a
numerical failure.

The **FP32 endpoint profile (3)** is 8/8 in Icarus
(`build/conv-axi/iverilog-20261108T194552Z-3`). Its Verilator leg was stopped
after 3 of 8 modes, so that partial tree was deleted and **no Verilator receipt
is claimed for the FP32 endpoint** until a complete run exists.
Pooling endpoint sweep (`tools/ppu/run_pool_axi.py`): 8 modes pass in both.

GEMM FP32 replay (`tools/cmac/run_gemm_fp32.py`): **all four frozen
`conv-gemm-vendor` fixtures pass in both simulators**, each comparing the
complete 4096-byte output BO. Latest complete pair of sets:
`build/cmac-gemm-fp32/iverilog-20261108T195133Z-*` and
`build/cmac-gemm-fp32/verilator-20261108T200138Z-*`. The k=1 case is byte-exact
(worst deviation 0); the k=32 and k=64 cases carry the family's declared `0.1`
bound and measure 1.9e-6, 1.9e-6 and 1.27e-4.

## 7. Ordered remaining work

| # | Gap | Size |
|---|---|---|
| 1 | Conv + pooling AXI endpoints | **done** — both pages, 8 modes, dual-simulator |
| 2 | Host-drivable dual image | **done as a bitstream** via the pin-free USER2 wrap; the bare-AXI variant stays unbuilt |
| 3 | Physical host transport | **done to a bitstream** — `rk_jtag_axil_bridge` + `ypcb_jtag_dual_top`; Verilator replays load both BOs through frames and compare the complete output; Vivado emitted `rk_jtag_dual.bit` |
| 4 | `conv-gemm-vendor` GEMM / FP32 / vendor-BY_K RTL | **GEMM FP32 leaf done**: decoder variant, FP32 tail, FP32 address mode; 4/4 frozen GEMM fixtures pass in both simulators. Two BY_K cases and one multitask depthwise case still need a separate datapath |
| 5 | conv-simple: 3 device/host-disagreement captures | **3 captures rejected**; needs capture investigation, not RTL. The FP32 capture now executes |
| 6 | Pooling leaves | **done** — all 20 fixtures execute in both simulators |
| 7 | Board run, cold boot, PCIe observation | **none** — this is the only remaining step that needs the card and explicit authorization |
| 8 | Audited release gate: `CONFIG_VOLTAGE`/`CFGBVS` pair is donor-derived, not measured on this card | release gate |
| 9 | Six-page bitstream | **FAILED timing**: routed and DRC-clean, WNS -1.549 ns on 244/115,597 endpoints. Worst path is the C16 CMAC cell output (`stage/data_q` -> `cmac/out_groups`), 21.5 ns with 80% route at 76.6% LUT utilisation. Four 512-lane CMAC arrays do not fit 50 MHz |

The honest answer to "can it run on FPGA?" is **not yet observed**. Six
bitstreams exist, and the newest emitted one is the **four-page** image; the
six-page top synthesizes and routes but **fails 50 MHz timing**, so it has no
bitstream. Nothing has been programmed, no cold boot was measured. The corpus is
covered much more broadly in **simulation** - every frozen conv-simple profile,
all four GEMM shapes and all 20 pooling fixtures replay - but simulation is not
FPGA execution.

What remains between this tree and "all examples run on FPGA":

1. **All four conv-simple profiles are now image pages**: profile 0 at
   `0x8000`, profile 3 at `0xb000`, profile 1 at `0xc000`, profile 2 at
   `0xd000`. The GEMM page at `0xa000` is decode-driven and serves **all four
   frozen GEMM shapes**. Dual modes 0-8 and mailbox modes 0-6 have Verilator
   PASS receipts, but those receipts predate the streaming front and the frame
   stage; they are stale and must be regenerated.
2. `ypcb_dual_endpoint_top` has **six** pages now. Its bare-AXI variant still
   cannot become a bitstream (no pin budget); the JTAG USER2 image is the
   buildable form.
3. Scaling by adding pages has now been **measured and found not to close**.
   The four-page image already used **96,749 LUTs (32.4%)** with only
   **+0.044 ns WNS**. The six-page streaming-RAM design reaches placement and
   routing but misses 50 MHz at **WNS -1.549 ns** (244 endpoints, 76.6% LUTs).
   See `docs/CONV_PAGE_SCALING.md`; four separate 512-lane CMAC arrays do not
   fit the period, so the fix is architectural (pipeline the cell or share one
   array), not another page.
4. The three vendor-BY_K conv cases have no RTL at all; the four GEMM cases
   do, and pass through the page.
5. Three conv-simple and three conv-gemm-vendor captures are rejected because
   the device contradicts the host oracle. That is a capture-integrity
   question, not an RTL one.
6. The image still serves seven selected jobs, not the whole corpus. Pooling
   is one capture per image; only the GEMM page is multi-shape.
7. Programming the card and reading a cold-boot result requires an explicit
   instruction and an audited target. Nothing in this tree touches hardware.
