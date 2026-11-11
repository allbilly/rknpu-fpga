# Progress — running the RK3588 examples on the K8 FPGA

Updated: **2026-11-10**

This is the one-screen snapshot for the next agent. The long-form, per-feature
status is `docs/PROGRESS_TABLE.md`; feature contracts are the other files under
`docs/`. Every binary receipt lives under `build/` and is workspace-local.

## Bottom line

- **The six-page bitstream exists and closes 50 MHz with margin.**
  `build/jtag-dual-image/20261109T160627Z` (Vivado 2026.1, 48 min):
  **PASS**, `bitstream_emitted=true`, `hardware_accessed=false`,
  `source_match=true`; **WNS +3.952 ns**, TNS 0, **0 / 202,615** failing setup
  endpoints; WHS +0.054 ns; 231,316 / 298,600 LUTs (77.47%); 71,058 registers;
  19.5 BRAM tiles (19 RAMB36); 331,098 / 331,098 routable nets routed, 0 errors;
  DRC warnings only. Bitstream: 18,735,215 bytes, SHA-256
  `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39`.
  Pages: conv p0, pooling, GEMM, conv FP32 p3, conv k5 p1, conv C16 p2.
- The blocker was closed by **option A**: `rk_cmac_fp16_cell` is now a
  three-leg registered pipeline and `rk_cmac_fp16_array` has a matching elastic
  valid/tag pipe. The CACC chain and all page/transport contracts are unchanged;
  the arithmetic is bit-identical and proved on frozen hashes (see below).
- **No RK3588 example has run on FPGA.** Nothing has been programmed or
  flashed, no cold boot was measured, and no host driver has touched the card.
  Every receipt records `hardware_accessed=false`. The DLC10 JTAG cable is not
  attached to this machine right now, and a volatile load still needs the
  user's explicit authorization (see `docs/BOARD_RUN_PREP.md`).
- Hardware preparation is complete and dry-run-validated: real-board USER2
  mailbox harness (`tools/host/run_jtag_dual_hardware.py`, refuses without
  authorization + audited image), read-only cable preflight
  (`tools/host/jtag_preflight.py`), and the audited programming/run procedure
  (`docs/BOARD_RUN_PREP.md`).
- The frozen-tree replay matrix (dual 0-8, mailbox 0-6, four conv-simple
  profiles, eight vendor profiles) is being refreshed; only receipts whose
  recorded hashes match the FINAL-freeze manifest
  (`build/verif/frozen_hashes.json`) count.
- **Option B** (one shared CMAC array across the four conv pages, with
  structural 8x16 pruning) was implemented but is **parked and not
  integrated**: it is the route to LUT/slice headroom for further pages, not a
  requirement for closure. Archived at `build/timing-lab-share/`.
- New tooling this cycle: the vendor conv core now compiles in Icarus (the
  declaration-order regression is fixed), `run_conv_simple_axi.py` records
  source hashes, and `vivado_jtag_dual.py` fails a build if any input changes
  mid-run.

## Toolchain

| Tool | Version |
|---|---|
| Icarus Verilog | 13.0 (stable) `v13_0` |
| Verilator | 5.048 2026-04-26 |
| Python | 3.14.5 |
| Vivado | 2026.1 (build 6511674) |

Part: `xc7k480tffg1156-2`. Clock: 20 ns (50 MHz). Device: 298,600 LUTs,
597,200 registers, 955 RAMB tiles.

## Corpus coverage

Checked against the family manifests in `build/rk3588-example-captures/` and the
fixtures in `tests/`.

| Family | READY | Fixtures pinned | State |
|---|---:|---|---|
| `ew-fp16` | 54 | vectors + fixtures | elementwise leaf has real-silicon differential evidence |
| `ew-int` | 15 | vectors | INT8/16/32; 3 captures blocked |
| `pooling` | 19 (+1 source-derived) | **20 / 20** | all 20 replay in both simulators, complete 4096-byte BO |
| `fdiv-systematic` | 8 | vectors | 8 class matrices pass |
| `conv-fp16` | 9 | **9 / 9** | 9 READY captures pinned; 5 more BLOCKED; raw cores have dual-simulator PASS receipts (matrix refresh in progress) |
| `conv-gemm-vendor` | 10 | **7 frozen** | 4 GEMM + 3 conv frozen; the 3 initially-rejected cases are reconciled live (depthwise BO-size fix → 702/702 exact; conv.py within 0.12 tolerance); 3 BLOCKED with no RTL |
| `conv-simple` | 7 | **4 frozen** | 4 executable and on the six-page image; 3 live-confirmed device/host-oracle divergences (class A, outside the image; see `docs/CONV_SIMPLE_FIXTURES.md`) |

`~/rk3588/examples` contains the source scripts (`conv.py`, `conv_simple.py`,
`conv_legacy.py`, `conv_gemm.py`, `conv_tiles.py`, `gemm.py`, `pooling.py`,
`elementwise.py`, `simple_add.py`, `kernel_6_18/`, `expt/`). The capture corpus
is the executable proxy; not every script/case has a capture or a website-ready
fixture.

## Image page map

`ypcb_dual_endpoint_top` has one AXI4-Lite slave with a 32 KiB memory window
(`0x0000..0x7fff`) and six transport pages:

| Page | Address | Identity | Capture |
|---|---|---|---|
| conv FP16 profile 0 | `0x8000` | `0x524b4353` `RKCS` | 3x3 C4 OC16 |
| pooling | `0x9000` | `0x524b5050` `RKPP` | INT8 max k2s2 C16 |
| FP32 GEMM | `0xa000` | `0x524b434d` `RKCM` | all four frozen GEMM shapes (decode-driven) |
| conv FP32 profile 3 | `0xb000` | `0x524b4415` | 1x1 C4 OC16, FP32 out |
| conv k5 profile 1 | `0xc000` | `0x524b4416` | 5x5 C4 OC16 |
| conv C16 profile 2 | `0xd000` | `0x524b4417` | 3x3 C16 OC32 |

`0xe000` and above is an explicit SLVERR. Each conv page is a separate
`rk_conv_simple_axi` instantiation because geometry is an elaboration parameter.
`ypcb_jtag_dual_top` wraps the same image behind the pin-free USER2 mailbox
transport; it is the buildable form (the bare-AXI variant has no board pin
budget and stays unbuildable rather than inventing pins).

## What has been measured

### Contracts (re-run on the final adopted tree, 2026-11-10)

```
tests.test_dual_endpoint_contract                 -> Ran 61 tests  OK
tests/conv/test_*contract.py                      -> Ran 60 tests  OK
tests/ppu_pooling/test_pool_*contract.py          -> Ran 106 tests OK
tests/cmac/test_*contract*.py                     -> Ran 20 tests  OK
make generated-check                              -> demo ROMs match frozen captures
git diff --check                                  -> clean
tests/host (mailbox harness + preflight)          -> Ran 64 tests  OK (isolated run)
```

### RTL shape

- `rtl/cmac/rk_cmac_fp16_cell.sv` (`845d7843…`) — **three-leg registered
  pipeline**. Leg 1 decodes `pair_nz`/normalised mantissas, adds lane
  exponents, reduces them with a balanced 32-entry maximum tree, and computes
  the donor's weight-before-data, lowest-channel NaN priority in
  isolate-lowest-set-bit form. Leg 2 instantiates the unmodified
  `NV_NVDLA_CMAC_CORE_MAC_mul` Booth/CSA donor with its sign-compensation shift
  and per-lane 32-bit row sums. Leg 3 performs the balanced sign-extended
  32-way modulo-2^38 accumulate and the NaN result mux. The balanced max and
  adder trees are exact reassociations of the original integer arithmetic; the
  donor row decomposition is untouched.
- `rtl/cmac/rk_cmac_fp16_array.sv` (`473177ec…`) — elastic three-deep valid/tag
  pipe plus a hold-until-ready result register. `in_ready` is the head of the
  pipe; an illegal donor row tag or an X/Z operand frame sets the sticky error
  and is never emitted. The 13-port external interface is unchanged; latency
  +2 cycles, throughput unchanged.
- `rtl/cmac/rk_conv_3x3_valid_c4_front.sv` — weights and the feature window are
  single-read-port block RAMs; `frame_weight`/`frame_data` are registered buses
  assembled one halfword per cycle. The front walks only the real
  `INPUT_CHANNELS` of each kernel lane; padded BO lanes stay zero and masked.
- `rtl/cmac/rk_frame_stage.sv` — one-deep register slice on the front/CMAC
  boundary; carries address, `first`, `last`, `last_output` with the payload
  and clears on cancel. The pipelined array keeps the same tag/order contract.
- `rk_cmac_cacc_fp16_array` / `rk_cacc_fp16_array` / `rk_nvdla_cacc` — unchanged
  by the pipeline work (hashes `b66904ee…`, `b55f02cd…`, `5a970a4d…`).

### Live RK3588 NPU verification of the image corpus (2026-11-10)

A separate authorized live-NPU pass ran the exact fixtures the six-page image
executes on the real RK3588 NPU (`orangepi5`, mainline Rocket
`/dev/accel/accel0`) under an exclusive board lock — one runner at a time,
fresh output dirs, hashes verified both ways. Results (complete BO compares):

- **conv-simple 4/4 exact**: live device == frozen expected == RTL replay for
  conv p0 (`1f002aea…`, 1152 B); 5x5 C4 (512 B), 3x3 C16 OC32 (2304 B) and
  1x1 C4 FP32 (4096 B) live == expected == capture.
- **pooling 1/1 exact**: `e1519ae1…`, 4096 B, live == expected == RTL replay.
- **GEMM 4/4**: three bit-exact raw surfaces (`e42209d1…`, `d17a7aaa…`,
  `ed9c5a8d…`); `m4n32k64` 46/1024 f32 one ULP low, `max_abs_diff
  9.5367e-07` within the documented `9.54e-7` bound (`f9a9fca4…`).
- **Determinism**: two submits per family byte-identical, and identical across
  sessions to the frozen 2026-11-05 captures.
- **FDIV**: **1,452/1,452 captured lanes live-verified** — 8/8 class-grid
  cases and 9/9 prepared finite cases exact vs capture (with exactly the 20
  documented one-ULP-low `A/7` lanes vs donor-RNE), plus the 64 residual lanes
  reconstructed from the original captured probes and verified live 64/64
  (`build/rk3588-live-verify/FDIV-RESIDUAL.md`).
- **Divergences**: the three conv-simple host-oracle divergences are stable
  device behaviour (device wins); device-oracle evidence under
  `build/rk3588-live-verify/J05-device-oracles/`. No image-corpus bug was
  found, so **no RTL change and no bitstream rebuild was triggered**.

Full job list, race-control protocol and fix/rebuild policy:
[`docs/RK3588_LIVE_VERIFICATION_JOBS.md`](docs/RK3588_LIVE_VERIFICATION_JOBS.md);
consolidated evidence: `build/rk3588-live-verify/P0-SUMMARY.md` and the
per-job receipt trees (`build/rk3588-live-verify/<RUN_ID>/`).

### Pipeline equivalence proofs (frozen hashes, before the image build)

| Proof | Tool | Result |
|---|---|---|
| `cell_equiv`: pre-change combinational cell vs pipelined cell, 20,000 random/directed vectors incl. NaN/Inf/zero/denormal heads, random masks | Verilator 5.048 | result + `invalid` identical on every vector |
| `array_stream`: pre-change 1-cycle array vs pipelined array, 40 ordered frames with independent random `out_ready` backpressure on both sides | Verilator 5.048 | 160 groups emitted identically and in order, tags stable |
| X-reject: X operand frame at the seam | Icarus 13.0 (4-state) | sticky error, `out_valid` never emitted |
| Contracts after the change | unittest | 61 image + 20 CMAC tests OK |

Benches live under `build/timing-lab/`. The image build independently records
the same two source hashes with `source_match=true`.

### Simulation receipts

| Work | Latest state | Notes |
|---|---|---|
| 8 vendor conv profiles (valid, stride2, pad1, grouped t0/t1, splitoc t0/t1, depthwise) | `build/convolution-3x3-*` | Icarus now compiles after the declaration-order fix; both-simulator receipts are being re-run against the FINAL-freeze tree |
| conv-simple endpoint profiles 0..3, 8 modes each | `build/conv-axi/*` | runner now records `source_hashes_before/after`; refresh against FINAL-freeze tree in progress |
| dual endpoint modes 0..8 | `build/dual-endpoint/*` | refresh against FINAL-freeze tree in progress; older PASS trees are history |
| USER2 mailbox modes 0..6 | `build/jtag-dual/*` | refresh against FINAL-freeze tree in progress |
| pooling 20 fixtures | earlier `build/ppu-*` receipts | PASS both sims; pooling RTL untouched this cycle |
| GEMM four shapes | `--gemm-case` on dual mode 4 | cell unchanged in semantics; refresh part of the matrix |


### Frozen-tree evidence confirmed so far

- **Vendor conv profiles: 16 / 16 PASS** — all eight frozen cases, both
  simulators (Icarus 13.0 `v13_0`, Verilator 5.048 2026-04-26), every receipt
  hash-matches the FINAL-freeze manifest (before==after==frozen) and compares
  the full device output BO (768 to 15,104 bytes per case). Receipts under
  `build/convolution-3x3-*` (latest sim stamps `20261109T154709Z`..`T175040Z`).
- **FPGA-host harnesses are pinned (2026-11-10/11):** six-page `tools/host/run_jtag_dual_hardware.py` + preflight; EW image `tools/host/run_jtag_ew_hardware.py` (774 lines) with fail-closed admission/tag/identity checks, raw captured-BO replay of all 9 EW production cases (872,448 B, complete-BO compare before ACK), E1 negative, volatile-load-only receipts; operator runbook `docs/BOARD_SESSION_RUNBOOK.md` (671 lines). Offline host-tool suite now **85 tests OK**; dry-run receipts: `PASS_CHECK_PENDING_ADMISSION`, no-auth REFUSED, admission-pending REFUSED. Remaining gates: user authorization (per family), DLC10 cable + init, audited identity re-read, electrical confirmation, EW human board-review admission.
- **Host limitations (2026-11-10):** the verification host hard-crashed twice
  under heavy multi-core compilation while its battery was at ~0 % and charging
  (power-delivery brownout; fixed by a new higher-wattage charger), and later a
  thermally induced guard kill occurred when a 53-min single-core sim pushed
  Tctl to 98.2 °C with both fans at maximum (degraded cooling, not a project
  fault). No evidence or source was lost. Heavy jobs now run one-at-a-time
  under a global lock (`/tmp/rknpu-heavy.lock`), with battery gate, Tctl < 82 °C
  launch gate, optional CPU quota, a strict-matching thermal watchdog, and
  short-burst scheduling. Full evidence and prevention in
  `docs/HOST_CRASH_POSTMORTEM.md`.
- The six-page image replay matrix (dual endpoint, USER2 mailbox, conv-simple
  standalone) runs against the same frozen manifest; before the machine reboot,
  dual modes 0, 1, 2 and mailbox mode 0 were PASS. The host crashed and was
  manually rebooted at 2026-11-10 02:15 HKT, killing the in-flight mode-3 dual
  and mode-1 mailbox runs (their RUNNING dirs are aborted receipts, not
  evidence). The tree and all receipts survived (518/518 frozen hashes still
  match), and the matrix was resumed after reboot. Only FINAL-freeze-matching
  PASS receipts count.
- **Runtime-decoded conv engine (2026-11-11) — VERIFIED:** leg A primary replay **3/3 PASS** (VALID reads900/writes392, STRIDE2 reads1060/writes200, conv-simple reads1408/writes576; all complete-memory-image equality, canary 0, written-region SHA-256 == frozen capture — `4011bdea…`, `2759906b…`, `1f002aea…`; frame META/DATA/WEIGHT matched for every atom/tap; source_match true; adopted cores/fronts unchanged). Leg B negative controls **51/51 expected==actual** (17/case: code1×3, code2×9, code3×1, code4×3, code7×1), receipts under build/runtime-conv-lab. Ledgers: `LEG_A_PRIMARY_RECEIPTS.md`, `LEG_B_CONTROLS_RECEIPTS.md`. Next: OOC area estimate (D1) → S1 page integration → merged-image candidate.
- **Merged single-image S0/S1 scaffolding (2026-11-11):** `fpga/ypcb_merged_top.sv` skeleton + `fpga/merged/` build template + `docs/MERGED_INTEGRATION_NOTES.md` (18 map/template tests), renderer `tools/merged/vivado_merged_image.py` (render/verify/check, fail-closed `synth`), mailbox→AXI scaffold bench `tests/tb_ypcb_merged_top.sv` (4 hole configs PASS), and **`docs/EW_APERTURE_AUDIT.md` PASS** (54/54 ew-fp16 + 8/8 fdiv-systematic fit the sparse six-bank aperture; 1 MiB decode + sparse banks safe; alternate-bundle failure mode documented). 35 merged offline tests OK; S1 (attach runtime conv page) unblocked on D1.


Important: only receipts whose recorded source hashes equal
`build/verif/frozen_hashes.json` (`FINAL-freeze-20261109T160627Z`, 518 files)
count. The pre-change baseline had only five source-matched receipts before the
option-A RTL landed; the frozen-tree matrix supersedes them.

## Bitstream receipts

All paths in this table are under `build/`.

| Image | Pages | WNS (ns) | WHS (ns) | LUTs | BRAM | Bitstream SHA-256 |
|---|---|---:|---:|---:|---:|---|
| `ppu-image/20261108T170500Z` | pooling | +14.633 | +0.037 | 924 | 2 | `1908003f62ac4e22d2f48470fb204208311ebeced540d926f71a451ae77836a5` |
| `conv-image/20261108T171500Z` | conv p0 | +0.412 | +0.076 | 46,026 | 8 | `cddb583b961636868432a9d0e8af5ea4d015fc0d80f4046e8d6836bb4b848b08` |
| `jtag-dual-image/20261109T001500Z` | 2 | +0.076 | +0.065 | 48,833 | 8 | `f53ae24a241972113201e8c4f0d3de0ff845d6f7f5128935327e2277439b02e1` |
| `jtag-dual-image/20261109T040000Z` | 3 | +0.227 | +0.056 | 49,038 | 8 | `4e8880d9b3c9a52086ad7173630b781824ec0aa660905f5b35c68c13fe21c8bb` |
| `jtag-dual-image/20261109T043000Z` | 3 | +0.141 | +0.036 | 55,137 | 8 | `f86d4d9cda6d56582c18a49adb1566acb595c75ad2f5d6d9a957ad98c7f31416` |
| `jtag-dual-image/20261109T062000Z` | 4 | +0.044 | +0.058 | 96,749 | 8 | `c849a69c5e3ca16687c1b63a7b9bec8fcfc6c4f914087a93f059048a4c02061e` |
| `jtag-dual-image/20261109T073000Z` | 4, page-gated | +0.044 | +0.058 | 96,749 | 8 | `73dd0365055b4664c2d8d05af634d05a754cc333808fd2ed1c5d974706c94cf7` |
| `jtag-dual-image/20261109T180000Z` | **6** | **-1.549** | +0.016 | 228,817 | 19.5 | **none: timing gate refused** (superseded) |
| **`jtag-dual-image/20261109T160627Z`** | **6, page-gated** | **+3.952** | **+0.054** | **231,316** | **19.5** | **`81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39`** |

All images record `hardware_accessed=false`. None has been loaded.
`20261109T160627Z` was built in a snapshot tree while option B held the working
tree; the adopted tree was restored to the same sources and all 73 build inputs
compare byte-identical
(`build/timing-lab-share/a_only_adoption_manifest.json`,
`build/jtag-dual-image/20261109T160627Z/ADOPTION_PROVENANCE.md`).

## Six-page timing, final numbers

`build/jtag-dual-image/20261109T160627Z`, Vivado 2026.1, 2,908 s:

| Gate | Value |
|---|---|
| Status | **PASS**, `bitstream_emitted=true`, `hardware_accessed=false`, `source_match=true` |
| WNS / TNS | **+3.952 ns** / 0.000 ns |
| Failing endpoints | **0 / 202,615** |
| WHS / THS | +0.054 ns / 0 |
| WPWS | 9.232 ns, 0 failing |
| Slice LUTs | 231,316 / 298,600 (77.47%) |
| Slice registers | 71,058 (11.90%) |
| Slices | 70,434 / 74,650 (94.35%) |
| Block RAM | 19.5 tiles (2.04%), 19 RAMB36 |
| Routed nets | 331,098 / 331,098 fully routed, 0 errors |
| DRC | 0 errors; warnings only (`CHECK-3`x2, `DPIP-1`x12, `DPOP-1`x6, `DPOP-2`x6, `REQP-1839`x20, `REQP-1840`x20) |
| Bitstream | 18,735,215 bytes, SHA-256 `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` |

Worst setup path is no longer arithmetic:

```
Source:      image/conv_page/engine/state_q_reg[0]/C
Destination: image/gemm_page/engine/core/frontend/reader/error_code_reg[2]/CE
Delay:       15.549 ns  (logic 1.305 ns = 8.4%, route 14.244 ns = 91.6%)
Levels:      18  (LUT3/4/5/6 only, no CARRY4)
```

This is the cross-page stall/error aggregation net
(`state_q -> arithmetic_error -> arbiter/request_pending -> memory_bridge
rsp_ready -> gemm reader CE`), not a CMAC leg. Hold margin is thin (+0.054 ns,
skew-dominated on a front->frame-stage one-flop hop): re-check it after any
clock or pin-plan change. Slice occupancy is 94.35% (4,216 slices free), so a
new page should start from option B headroom.

Superseded failure (history), `build/jtag-dual-image/20261109T180000Z`: WNS
-1.549 ns, TNS -160.574, 244/115,597 failing endpoints, 228,817 LUTs, no
bitstream. Worst path then was
`conv_c16_page/.../stage/data_q_reg[21] -> arithmetic/cmac/out_groups_reg[121]`,
21.538 ns with 80% route delay — the entire failing cluster was the C16 CMAC
cell cloud that the pipeline split.

## Why the six-page build got this far

Round 1 (2026-11-09) fixed a real synthesis blocker: the front used many-port
arrays, so Vivado could not infer block RAM and refused to dissolve profile 2's
73,728-bit weight store (`Synth 8-3391`). The streaming rewrite moved both
operands into single-port RAMs; the frame then takes
`KERNELS*INPUT_CHANNELS + INPUT_CHANNELS` cycles to assemble. Round two added
`rk_frame_stage`; it moved the path source off the front's 8,704-bit bus but
timing still failed at -1.549 ns because the CMAC cell was one combinational
cloud. Round three pipelined the cell into three registered legs (balanced max
tree, untouched donor Booth/CSA, balanced modulo-2^38 accumulate) and gave the
array an elastic valid/tag pipe: WNS +3.952 ns, bitstream emitted. Round three
also fixed the vendor-core Icarus declaration-order bug and added source-hash
receipts to the conv-simple runner. The option-B shared-array prototype was
built as a contingency and parked after A closed with margin.

## Hardware status and remaining preparation

- **Target:** Inspur YPCB-00338-1P1, `xc7k480tffg1156-2`, Xilinx Platform
  Cable USB II (DLC10). Prior physical sessions (2026-10-27/30, different
  images) used cable serial `80802026a77a01`, DNA `004E544714C705C`, IDCODE
  `0x23751093`, an owned hw_server on `localhost:3125`, and wrote no flash.
- **Current availability:** no DLC10 cable attached (`lsusb` shows no `03fd:`
  device), no hw_server, lease free. `tools/host/jtag_preflight.py` reports
  this read-only state and exits 2.
- **Prepared:** volatile-JTAG-load procedure (Vivado hw_server and
  openFPGALoader routes), `tools/host/run_jtag_dual_hardware.py` (requires
  `--authorized`, an emitted-image hash, exact local target URI and lease; it
  never programs/resets/flashes; modes 1-6 with complete 4096-byte BO
  compares, mode 0 last), offline `--check` PASS for the six-page image hash
  and modes 0-6, 64 offline host tests.
- **Needs the user:** cable attached, explicit authorization for a volatile
  load, audited target identity confirmation, LED polarity, and
  `CONFIG_VOLTAGE 1.8`/`CFGBVS GND` confirmation. Flash stays unauthorized.

## Open gaps

1. **Hardware execution.** No board run yet: needs the cable and the user's
   volatile-load authorization (see above).
2. **Frozen-tree replay matrix refresh.** Dual 0-8, mailbox 0-6, four
   conv-simple profiles and eight vendor profiles are being re-run against
   `build/verif/frozen_hashes.json`; only source-matched PASS receipts count.
   Until that table is complete, the image's functional evidence rests on the
   module-level proofs + contract suites.
3. **3 vendor cases have no RTL**: two BY_K cases
   (`conv_byk_c160_h14w14_oc320_k3x3`, `conv_h40_c160_h40w40_oc320_k3x3`) and
   the multitask depthwise case. Rocket has no `core_mask`/`subcore_task`, and
   the bundle cannot patch the self-referential `PC_BASE_ADDRESS`.
4. **Device/host-oracle divergences classified by the 2026-11-10 live P0
   verification** (evidence only, device wins): the conv-gemm-vendor
   depthwise tasks and `conv_py_3x3_c32_oc128_h14w14_fullsetup` were bundle-
   size/packed-oracle defects and are reconciled (702/702 exact after the
   15,104-byte BO fix; conv.py within 0.12 tolerance). The three conv-simple
   cases are stable real device behaviour that the host oracle does not model
   (FP32-C32 structural chunk placement; two INT8 cases with 7/13 bytes at
   `expected + 1`); device surfaces are preserved in
   `build/rk3588-live-verify/J05-device-oracles/`. None is in the six-page
   image, so no RTL/bitstream change was required.
5. **Electrical/release gates.** `CONFIG_VOLTAGE 1.8` / `CFGBVS GND` is
   donor-derived (OpenTPU) plus a prior-image CFGBVS_PIN read, not a strap
   measurement; LED polarity unverified. The image carries no USR_ACCESS tag;
   hardware identity must use DNA + INIT/DONE + page map.
6. **Slice/LUT headroom.** 94.35% slices / 77.47% LUTs: fine for this image,
   but further pages need option B v2 (archived, not integrated or qualified).
7. **Electrical, DRC and timing gates are unchanged** — the six-page image
   passes the existing gates; no gate was relaxed.

## Chosen direction for the conv corpus (2026-11-10)

The user selected the **real-NPU-style runtime-decoded conv engine** over
per-profile/per-case images (task-13, `docs/CONV_RUNTIME_ENGINE.md`): decode the
convolution geometry from the per-task command stream, so one engine serves the
9 conv-fp16 cases + 4 conv-simple profiles and can eventually replace the four
per-profile conv pages in the main image. Staged: design + evidence map →
experimental prototype + old-vs-new byte-exact equivalence on frozen fixtures →
synth-only area estimate → conv-fp16-only image → main-image replacement
proposal. The adopted six-page image and FINAL-freeze evidence stay untouched
until a fully qualified replacement exists. The archived option-B two-image
idea remains only as a fallback if the runtime engine stalls.

## Not claimed

- No FPGA execution, cold boot, PCIe observation or driver run.
- No hardware qualification of this image (it has never been loaded).
- No byte-exactness claim for the frozen-tree replays until the refreshed
  source-matched receipts are in; the module-level proofs and contract suites
  are separate evidence.
- No numerical special-value policy beyond what the existing fixture contracts
  pin. `docs/PPU_Q16_AVERAGE.md` still marks Q16 rounding as candidate
  behaviour.
- No general RK3588 backend or completed soDLA fork; this is a strict FP16
  slice plus the conv/pooling/GEMM pages needed for the captured examples.

## Superseded history

The 2026-10-23 preparation-only text that used to live here (openXC7 stopped
run, DSP-prefix preparation, "do not start a Vivado build") is retired. The
continuation is the Vivado streaming-RAM + pipelined-CMAC design described
above; older artifacts remain under `build/` as history and are not evidence
for the current RTL. The four-page `20261109T073000Z` image and the failing
`20261109T180000Z` six-page build are superseded by
`20261109T160627Z`.

## 2026-11-11 session state (post teammate-restart)

Host: dedicated (another project's workstreams finished), cooling-bound
(idle ~45-50 C, ~1 core sustained is the envelope). Guard v4.3 + shared lock.

Completed since the two-image decision:
- **Runtime-decoded conv engine**: decoder 13/13 config-field PASS; leg A
  primary replay 3/3 PASS (written-region SHA == frozen capture) and leg B
  negative controls 51/51 PASS on the PRE-parameterisation construction.
  D1 area measured at **167,858 LUTs (56.2 %)** with the additive
  C16xK16 construction (frozen production files untouched, manifest 518/518).
- **Runtime-engine parameterised re-run**: blocked by two harness issues
  (core's staged wire widths vs ATOMIC_C=16 -> Icarus port-width warnings that
  the runner rejects; TB frame-bus comparator compares different lane
  packings). Both are harness/layout fixes, no RTL logic finding; fix
  instructions issued.
- **Image B scaffold**: pooling-corpus measured whole-image fit
  **110,107 LUTs / 33,044 regs / 8 RAMB36** (D2 confirmed); ew-int page-form
  integrated (RKEI page + 4-bank 16 KiB aperture, both-sim 15/15 replays and
  8 negatives), current-file evidence refreshed; EW/FP16/FDIV oracle policy
  recorded; S3/S4 replay plan PLAN_READY.
- **Image A scaffold**: top/profile/renderer with REF_NAME page-presence,
  `{DESIGNWARE_NOEXIST SYNTHESIS}` define, ABI bench PASS, replay plan
  15 fixtures/796 QWORDs PLAN_READY; `rk_conv_runtime_axi` wrapper pending
  conveng green.
- **Hardware**: dual 0-8 PASS (9/9), vendor 16/16, mailbox mode 0; 270 contract
  tests green; mailbox 1-2 blocked-by-host-hardware; uECable still absent.

In flight: pooling image staged synth (build-synth) in the cool window; impl
stage and bitstream follow if the host stays cool.

Update (01:42 HKT): **LEG A GREEN 3/3** on the parameterised construction —
valid `4011bdea...`, stride2 `2759906b...`, conv-simple `1f002aea...`, each
identical to its frozen capture with complete memory image equality and 37/39
source hashes before==after. Receipts: `iverilog-20261110T171049Z`,
`...T171818Z`, `...T172423Z`. Leg B (51 controls) queued.

Update (01:20 HKT): the parameterised runtime engine now PASSES leg A case 1
hash-bound (`iverilog-20261110171049Z`, written BO `4011bdea...` == frozen
capture, complete memory image equal, 37 source hashes before==after). The
blocker was three harness defects, now fixed: core staged-wire widths
(#10), frame-bus lane-packing normalisation (#11), and X-propagation in that
normalisation (#12). Also fixed the staged-build page-presence gate, which
counted 172,978 descendant cells instead of 19 page instances; and guard v4.4,
which kept a stale 97 C median after a kill and killed new jobs at 58 C.


- **S1 page wrapper**: contract PASS (`PASS PAGE_AXI_CONTRACT captured=54
  streamed=0`, receipt `build/runtime-conv-lab/page-contract/20261110T191732Z`).
  Three real RTL defects were found and fixed: AXI write AW/W same-cycle
  deadlock, AXI read stale-address race, and — most important — the command
  fetch reading only 2 of the 4 halfwords per 64-bit QWORD (silently truncating
  the upper 32 bits of every command word). The bench itself also had to be
  fixed: it waited for the engine to accept arbitrary pattern words, which the
  decoder correctly rejects, and it had no watchdog so failures were silent.

- **S1 ATTACH COMPLETE** (2026-11-11 05:54): the real `rk_conv_runtime_page_axi`
  is instantiated in `ypcb_merged_top`'s `conv_runtime_page` slot, with a proper
  two-master arbiter for the single 64 KiB halfword memory port. Evidence:
  page contract **PASS captured=54 streamed=0**, merged scaffold bench **PASS on
  all four SLVERR holes (frames=19 checks=31)**, merged offline suite **79/79 OK**,
  Image-A render `VERIFIED_RENDER_ONLY`, replay `full` = `WRAPPER_ATTACHED`
  (15 cases prepared), frozen manifest **518/518**. Six RTL defects found and
  fixed (AXI write deadlock, AXI stale read address, 2-of-4-halfword command
  truncation, write-only registers, 31-bit STATUS concat, arbiter deadlock).
  Close-out receipt: `build/verif/S1_ATTACH_SUMMARY.md`.

- **S1 family replay executor** (2026-11-11 09:53): `tools/merged/gen_image_a_case_bench.py`
  drives each frozen fixture through the real page and compares the complete
  runtime output region with the leg A/B oracle rule. Building it exposed and
  fixed **three more page defects**: byte-reversed command-QWORD assembly, a
  non-simultaneous `data/last/valid` handshake, and `cmd_last` asserted on the
  wrong word (stream boundary is index 50 for the 52-QWORD family, 53 for the
  54-QWORD family). Verified: `conv_3x3_valid_c4_h9_w9_oc4` replays with
  `atoms=49 out_c=4 written=392 mismatches=0` (`build/merged-image/probeL`);
  eight further vendor fixtures match in
  `build/merged-image/s1-family-20261111T003438Z`; summary
  `build/merged-image/S1_FAMILY_SUMMARY.json`. The full 15-case sweep is not
  Icarus-throughput-feasible on this host (~800 cycles/s) and is recorded as
  such rather than papered over. Merged suite stays **79/79 OK**, frozen
  **518/518**, page contract still PASS.

- **S2 ATTACH COMPLETE** (2026-11-11 10:12): the real `rk_cmac_gemm_axi` page
  replaces the GEMM stub, so Image A now carries **both** real engines
  (runtime conv page + CMAC GEMM page) behind a **three-master** shared-memory
  arbiter. One defect found and fixed: page slaves were given the full window
  address instead of a window-relative one, so the first GEMM access decoded as
  unmapped and quarantined the host bridge. Evidence: scaffold bench PASS on
  all four SLVERR holes, merged suite **79/79 OK**, render
  `VERIFIED_RENDER_ONLY`, frozen **518/518**. Receipt
  `build/verif/S2_ATTACH_SUMMARY.md`.

- **IMAGE A BUILD COMPLETE + BITSTREAM EMITTED** (2026-11-11 12:32): routed and
  fully gated. **172,923 implemented LUTs (57.9 %)**, 44,446 registers, 28 BRAM;
  **WNS +158.03 ns / WHS +0.084 ns with 0 failing endpoints**; 0 no-clock pins,
  0 unconstrained endpoints, 231,668 fully routed nets, DRC warnings only.
  `host-merged.bit` **18,735,212 B, SHA-256
  `5b03e7388ea0d0a95462dcd7d9279277c6264085d8a801f484ea928a12ac2bfb`**,
  USR_ACCESS `396e6429`, emitted from the verified routed checkpoint through
  `fpga/merged/emit_routed.tcl` (same reviewed emission gates), **NOT
  programmed**. Receipt `build/merged-image/image-a-emit-20261111T041526Z/`.

- **S3 ATTACH COMPLETE** (2026-11-11 12:50): the real **19 x 4 KiB pooling-corpus
  band** replaces the pooling stub in Image B, behind a new additive wrapper
  (`rtl/ppu/rk_ppu_pool_band_axi.sv`: page selection + 19->1 memory arbitration,
  one AXI slave / one memory master so the top's bus is unchanged). Image B
  gained the two-master shared-memory arbiter. Evidence: wrapper compiles
  **0 warnings**, `ypcb_image_b_top` elaborates rc 0, profile render
  `VERIFIED_RENDER_ONLY` (tag `1135cf02`), merged suite **79/79 OK**. Receipt
  `build/verif/S3_POOL_BAND_SUMMARY.md`. Remaining S4: `ew_page` (`rk_ew_axi`
  exists) and the EW sparse aperture (new RTL).

- **S4 ATTACH COMPLETE** (2026-11-11 13:23): the real EW control page
  (`rk_ew_axi`) and the new six-bank sparse EW aperture
  (`rtl/rk_ew_aperture.sv`, 100 KiB physical instead of a dense 1 MiB, every
  other decoded address an explicit hole) are attached. **All six Image-B pages
  are now real modules**; profile render `VERIFIED_RENDER_ONLY` (tag `55e69cfb`),
  `ypcb_image_b_top` elaborates rc 0, merged suite **79/79 OK**, and Image-B
  replay `full` now reports **`HEAVY_WINDOW_REQUIRED`** instead of the missing-page
  refusal. Receipt `build/verif/S4_EW_PAGES_SUMMARY.md`.

- **Image B build attempt → TIMING FAILS on pooling datapath** (2026-11-11 20:10,
  `build/merged-image/IMAGE_B_TIMING_FAILURE_20261111.md`): routed, **DRC clean
  (the 19 `LUTLP-1` loops were my own band-wrapper self-reference and are fixed)**,
  0 no-clock/unconstrained, but the **authoritative Design Timing Summary is
  WNS −92.008 ns / 10,682 failing endpoints** on a path with **816 logic levels
  (745 CARRY4) in ONE 20 ns cycle** — the FP16-average leaf adder trees need
  ~5–6× pipelining. This is a real RTL finding: the pooling RTL had only ever
  been synthesised and OOC-fit, never routed+timed. Image A is unaffected
  (0 violations, WNS +158 ns). Also fixed the templates' worst-slack gate: it
  read SLACK off `get_timing_paths` (generic pin slack, giving −90 ns on a clean
  design) instead of parsing the Design Timing Summary; note `timing.rpt` carries
  a **jtag_tck** table and a **sys_clk** table and they must be read per-domain
  (I mis-read this once and corrected it).

- **Image-B timing root cause isolated** (2026-11-11 23:10): the whole failure is
  in ONE frozen leaf, `rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv`,
  where `fp16_mean15()` performs three 64-bit `/15 %15` operations
  combinationally in a single 20 ns cycle on top of an 8-channel 43-bit
  accumulator. Fix routes: serialise the divide (shift-and-subtract over several
  cycles) or pipeline accumulate vs. mean. Needs a **freeze exception** + a fresh
  pooling dual-sim matrix proving identical bytes, then an Image-B rebuild.
  Recorded in `build/merged-image/IMAGE_B_TIMING_FAILURE_20261111.md`.

- **Image-B rebuild attempt 4 aborted (process mistake, 2026-11-12 00:18)**: I
  launched it with `hold_foreign=0`, so the guard did not pause the ungoverned
  foreign Verilator/pytest chain in `/tmp/v3/ladder` (81 % CPU). Combined with
  my 50 %-quota Vivado that exceeded the laptop's degraded cooling, Tctl hit
  106 degC and the guard killed both at median 97.5 degC, 37 min into synthesis.
  **The foreign_hold matcher was already correct** (`*vortex/tinygpu*`,
  `*hw/unittest/*`) - I just never set `BENCH_HOLD_FOREIGN=1`. No checkpoint was
  produced; nothing else is lost, and `LUTLP` stayed **0** all through
  synthesis, confirming the combinational-loop fix holds. Record:
  `build/merged-image/IMAGE_B_ABORT_FOREIGN_HOLD_20261112.md`.
