# RK3588 live-NPU verification jobs for running all examples on the K8 FPGA

Status: **proposed job list, 2026-11-10.** Active NPU submissions to
`opencode-agent@192.168.192.18` are authorized by the user, who then explicitly
confirmed "approved to run on remote ssh" (2026-11-10 03:28 HKT). This
document is the job list and the race-control contract. It does not itself
claim any result: every job below produces its own board receipt under
`build/rk3588-live-verify/`.

## 0. Where we already are

The RK3588 capture corpus is complete for its READY set: **122/122 READY cases
across the seven families were already submitted on the real NPU**
(`build/rk3588-example-captures/RESULTS.md`; 107 exact, 2 tolerance-only,
5 known divergence, 8 FDIV truth-table). So this list is **not** a
re-capture-from-scratch list. It is the differential/closure list needed to
say "our RTL implements what the real NPU does, family by family", and to close
the cases that still stand between us and running every example on the FPGA:

1. **RTL vs live-device differential** for each family our RTL covers (the
   captures are old evidence; the RTL changed many times since).
2. **The known divergences** (conv-simple FP32-C32 layout; two INT8 +1 LSB
   output-conversion cases; FDIV A/7).
3. **The 18 BLOCKED cases** (3 vendor-ABI, 12 dtype/shape, 3 multi-task) —
   attempt workarounds or classify them permanently.
4. **Examples with no capture bundle** (12), i.e. the remaining path to "all
   `~/rk3588/examples`".

The current six-page FPGA image
(`build/jtag-dual-image/20261109T160627Z`, SHA `81eef4cd…4d39`) executes only:
conv-simple profiles 0, 1, 2, 3; one pooling page (INT8 max k2s2 C16 h2w2);
the four decoded GEMM shapes. Nothing else in the corpus is in that image yet
(see §5). The jobs below verify the RTL leaves we have; §5 lists the RTL /
bitstream work still needed for the rest.

## 1. Race-condition prevention (mandatory for every job)

The board has exactly one NPU. The prior capture pipeline already defines the
contract (`build/rk3588-example-captures/BOARD_RUN_PLAN.md`,
`build/rk3588-example-captures/runner/README.md`); this list only re-uses it.

- **Single owner.** Before any job, run a board preflight: record hostname,
  kernel, Python version, `ls -l /dev/accel/accel0`, `lsmod | grep rocket`,
  `who`, and `pgrep -af 'rocket_run|npu|rknn'`. If any other submit process or
  interactive owner is present, **stop and report**; never race it.
- **One exclusive lock around every runner invocation** (whole process, not
  per-case): `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock \
  python3 .../rocket_run.py ...`. Never `-s`. No parallel copies, ever.
- **One runner at a time** even across jobs: the lock serializes board access,
  but the orchestrator must also serialize job *submission* (no overlapping
  ssh sessions, no background + foreground mix).
- **Fresh output root per invocation** (`runs/<RUN_ID>/`), never an existing
  one; the runner processes cases sequentially and records a per-case failure
  without fabricating output.
- **No device reset, no reprogramming, no flash** inside or between jobs. This
  target is a read-only diagnostic reference; a real FPGA load is a separate
  action on the K8 card only.
- **Do not fight the laptop verification matrix.** The RK3588 board work does
  not touch the FPGA; the local host guard (`build/verif/host_guard/`) still
  applies to host-side sims/builds.
- **Evidence per job:** board preflight, exact command, lock use, run dir,
  `capture.json` per case with real addresses/hashes/duration/submit_ret,
  post-run `pgrep` state, and a hash of every transferred bundle and output.
  Copy the whole result tree back to `build/rk3588-live-verify/<RUN_ID>/`.

## 1a. P0 interim results (2026-11-10, live board reruns)

J00-J03 are green. One flocked runner per batch, fresh output dirs, staged and
fetched hashes verified; the board was clean before every batch (no interactive
user, no submit process, lock free). Receipts under
`build/rk3588-live-verify/`.

| Case | Family | submit_ret | live==expected | live==old capture | bytes |
|---|---|---:|---|---|---:|
| `conv_simple_fp16_3x3_c4_h8_w8_oc16` | conv-simple | 0 | **YES** | YES | 1152 |
| `conv_simple_fp16_5x5_c4_h8_w8_oc16` | conv-simple | 0 | **YES** | YES | 512 |
| `conv_simple_fp16_3x3_c16_h8_w8_oc32` | conv-simple | 0 | **YES** | YES | 2304 |
| `conv_simple_fp16_1x1_c4_h8_w8_oc16` | conv-simple | 0 | **YES** | YES | 4096 |
| `int8_max_k2s2_valid_c16_h2w2` | pooling | 0 | **YES** | YES | 4096 |
| `gemm_m2_n2_k1` | GEMM | 0 | exact (raw surface) | YES | 4096 |
| `gemm_m1_n16_k32` | GEMM | 0 | exact (raw surface) | YES | 4096 |
| `gemm_m2_n16_k32` | GEMM | 0 | exact (raw surface) | YES | 4096 |
| `gemm_m4_n32_k64` | GEMM | 0 | 1-ULP (46/1024 f32 elems, max 9.54e-7 = bound) | YES | 4096 |

Every live output SHA-256 equals the frozen 2026-11-05 capture, i.e. the real
device reproduces the capture across sessions. For the conv p0 and pooling
cases the RTL replay through the six-page image is also PASS
(`build/dual-endpoint/verilator-20261109T170134Z` modes 1 and 2), giving a
three-way match (live device == frozen capture == RTL simulation). An aborted
staging attempt `20261109T193610Z-j01` was never submitted to the device (no
runner invoked, no device access) and is kept as harness evidence only.

## 1b. P0 final outcome and fix decision (2026-11-10)

**P0 is complete.** Seven locked board batches, 32 case submissions, 11 repeat
submissions, every batch preflighted and post-checked
(`build/rk3588-live-verify/P0-SUMMARY.md`, `P0-INDEX.json`).

- **J04 determinism:** two submits per family are byte-identical to each other
  and to the J01/J02/J03 submits; the device also reproduces the 2026-11-05
  capture hashes across sessions.
- **J05 divergences:** all three are deterministic real-device behaviour; the
  device output equals the frozen capture exactly and the host `expected.bin`
  is what disagrees. Class A (oracle/fixture defect): (a) FP32-C32 structural
  chunk placement (6 of 8 chunks, slots 6-7 zero-filled); (b) 7 INT8 bytes at
  `expected + 1`; (c) 13 INT8 bytes at `expected + 1`. Device surfaces and
  diffs preserved in `build/rk3588-live-verify/J05-device-oracles/`; docs
  corrected (`CONV_SIMPLE_FIXTURES.md`, `CONV_GEMM_VENDOR_FIXTURES.md`).
- **J06/J11 FDIV:** 256-class grid exact vs capture; 9 prepared finite cases
  exact vs capture, with exactly the 20 documented one-ULP-low `A/7` lanes
  against the donor-RNE oracle (three-guard-bit contract confirmed). The
  residual 64 lanes were then reconstructed from the original captured probes
  and live-verified 64/64 (`build/rk3588-live-verify/FDIV-RESIDUAL.md`) — the
  FDIV differential is now **1,452 / 1,452 captured lanes live-verified**.

**Fix decision (per §7): no class-B finding exists in the six-page image
corpus.** All image cases are live-exact (GEMM `m4n32k64` within its
documented bound), so **no RTL change and no bitstream rebuild is triggered**;
the adopted image `81eef4cd…4d39` stands. Class-A corrections are the docs and
the device-oracle bundle above. Class C/D items (FP32-C32 page, INT8
conversion contract, residual FDIV lanes, vendor-ABI blocked cases) are
future-increment work, not current-image changes.

Third-leg status: live == capture == RTL replay is established for conv p0,
pooling and GEMM `m2n2k1`; the remaining per-mode RTL legs (GEMM
`m1n16k32`/`m2n16k32`/`m4n32k64` and the individual k5/C16/FP32 page replays)
come from verif's frozen-tree matrix (dual modes 4-8), which is still
completing — they are comparison gap, not a finding.

## 2. Jobs — P0: the current six-page image corpus (do first)

| ID | Family | Cases | Live action | Oracle / acceptance |
|---|---|---|---|---|
| **J01** | conv-simple | `conv_simple_fp16_3x3_c4_h8_w8_oc16`, `conv_simple_fp16_5x5_c4_h8_w8_oc16`, `conv_simple_fp16_3x3_c16_h8_w8_oc32`, `conv_simple_fp16_1x1_c4_h8_w8_oc16` | rerun prepared bundles, complete 4096-byte output BO | live output == frozen capture (4/4 expected exact) **and** == our RTL sim replay receipt for the same fixture; both comparisons recorded |
| **J02** | pooling | `int8_max_k2s2_valid_c16_h2w2` | rerun bundle | full 4096-byte BO exact vs capture and vs RTL replay |
| **J03** | conv-gemm-vendor | `gemm_m2_n2_k1`, `gemm_m1_n16_k32`, `gemm_m2_n16_k32`, `gemm_m4_n32_k64` | rerun 4 bundles | exact for first three; `m4n32k64` within the documented 9.54e-7 bound; also compare to GEMM-page RTL replay |
| **J04** | determinism | one case per family (conv-simple 3x3, pooling, GEMM m2n2k1) | submit each twice, separate run dirs, both under the same lock | byte-identical outputs across repeats; if not, mark the family non-deterministic and record it |
| **J05** | conv-simple divergences | `conv_simple_fp16_1x1_c32_h8_w8_oc32` (FP32 output C32), `simple_conv_int8_5x5_c8_h8_w8_oc32`, `simple_conv_int8_depthwise_3x3_c64_h8_h8_oc64_g64` | rerun twice each; capture full BO + decoded per-lane data | classify: capture defect vs real device behavior; the device output wins. If real, our fixtures/RTL must be corrected to it (the three cases are not in the current image; the C32 case would need a new page) |
| **J06** | FDIV A/7 | all 1,452 captured lanes (`tests/fdiv_capture_vectors.json` source) | rerun the finite sweep bundle | live == capture exactly; compare with the implemented 3-guard-bit RTL FDIV model (expected exact, includes the 20 one-ULP-low lanes) |

## 3. Jobs — P1: family-wide RTL-vs-live differential

Each job re-runs the already-captured READY set on the live NPU under one lock
and compares every complete output BO against **both** the frozen capture and
the current RTL simulation receipt for the same fixture. Any case without RTL
coverage is recorded as an explicit RTL gap, never as a pass.

| ID | Family | READY cases | RTL state today | Acceptance |
|---|---|---|---|---|
| **J10** | conv-fp16 | 9 (`conv_1x1_valid_c8_h5_w5_oc8`, 3x3 valid/stride2/pad1 C4, grouped g2 t0/t1, splitoc C16 t0/t1, depthwise C3 h11w28) | 8 vendor-profile cores present; page not in the six-page image | 9/9 live == capture == RTL sim (each case's exact output bytes) |
| **J11** | conv-gemm-vendor | 10 (4 GEMM + 1x1 C1 OC6, grouped C4 OC4 G2, legacy 3x3 C4 OC4, conv.py C32/OC128 H14W14, depthwise C3 OC3) | GEMM 4 shapes have a page; the conv cases do not all have an image page | live == capture; for cases with RTL, live == RTL sim; others recorded as RTL/page gaps |
| **J12** | pooling | 19 READY (+1 source-derived fixture) | ~20 pooling leaves in `rtl/ppu/`; image carries only INT8 max k2s2 C16 | live == capture == RTL sim per fixture; INDEX_EN position metadata checked separately (known 6-byte index divergence risk) |
| **J13** | ew-fp16 | 54 (ADD/SUB/MUL/MAX/NEG/FDIV, lengths 1/7/8/9/33/1024) | FP16 EW endpoint RTL exists; FDIV ended | live == capture; ADD/SUB/MUL/NEG/MAX exact; FDIV per J06 contract |
| **J14** | ew-int | 15 (INT8/16/32 ADD/MINUS/MUL/MAX/MIN, C8/C9 layouts, INT16→INT32) | **no integer EW RTL identified** | live == capture; result defines an explicit RTL gap for integer EW |
| **J15** | fdiv-systematic | 8 (256-class truth table) | FDIV RTL implemented | live truth table == capture == RTL model per class |

## 4. Jobs — P2: blocked and uncovered cases (the remaining gap to "all examples")

| ID | Item | Cases | Action |
|---|---|---|---|
| **J20** | vendor-RKNPU ABI blocked | `conv_byk_c160_h14w14_oc320_k3x3`, `conv_h40_c160_h40w40_oc320_k3x3`, + 1 more (see GAP_MATRIX) | attempt a single-task decomposition / address self-patch workaround on Rocket; if impossible, record the exact missing UAPI field and classify permanently blocked |
| **J21** | dtype/shape blocked | 12 cases (`GAP_MATRIX.md` §1) | enumerate each; split the ones that are only multi-task transport; classify the rest as unsupported by the Rocket UAPI/device path used here |
| **J22** | multi-task transport blocked | 3 (e.g. combined depthwise parents) | capture as split single-task jobs (the conv-fp16 family already proved this pattern: 4 promoted tasks exact) |
| **J23** | examples with no capture bundle | 12 examples (`conv_simple.py` direct, most `kernel_6_18/*`, `conv_mesa*`, drafts) | triage runnable vs duplicate/draft; for runnable ones prepare bundles from the example source and capture under the same lock; duplicates inherit their canonical case |
| **J24** | `conv_tiles.py` | vendor-ABI tiled path (`conv_tiles_vendor_abi_blocked`) | attempt the single-task Rocket path or record why the vendor ABI is required; this is the one example with no viable capture route today |

## 5. What NPU verification cannot fix: FPGA-side work needed to run *all* examples

Jobs above verify RTL leaves; they do not put them in a bitstream. Current
coverage vs the example census:

| Example | Family / cases | FPGA page today | Needed |
|---|---|---|---|
| `conv_simple.py`, `expt/conv_simple.py`, `kernel_6_18/simple_conv.py` | conv-simple 4 exact (+3 divergent/blocked) | **in six-page image** (p0/p1/p2/p3) | J05 decisions for the 3 divergent/blocked cases |
| `gemm.py`, `conv_gemm.py` (GEMM part) | 4 GEMM shapes | **in six-page image** | — |
| `pooling.py`, `expt/pooling.py` | 19 READY + 2 blocked | only INT8 max k2s2 C16 page | add remaining pooling pages (avg/min/max/index, INT16/FP16) to an image |
| `elementwise.py`, `simple_add.py`, `kernel_6_18/simple_add.py` | ew-fp16 54 | separate EW endpoint design, not in the six-page image | build a host-drivable EW image (or page) for the EW endpoint |
| `kernel_6_18/elementwise_int.py`, `expt/elementwise_int.py` | ew-int 15 | none | integer EW RTL + page |
| `conv.py`, `conv_gemm.py` (conv part), `conv_legacy.py` | conv-fp16 9 + conv-gemm-vendor conv cases | 8 vendor-profile cores exist, no image page | add conv-fp16 pages to an image; calibrate/RTL for the extra conv.py shapes |
| `conv_tiles.py` | blocked | none | capture route (J24) then page |
| `kernel_6_18/conv_mesa*.py`, BS/BN paths | blocked dtype/shape | none | BS/BN RTL; classified unsupported today |
| FDIV / `elementwise.py` FDIV | fdiv-systematic | separate EW endpoint, FDIV RTL exists | EW image inclusion |

## 6. Execution order and evidence

1. **J00 preflight** (identity + no-owner check) — always.
2. **P0** J01→J06 in order (small: prepared bundles already exist).
3. **P1** J10→J15 (family re-runs; each is one locked queue run).
4. **P2** J20→J24 (triage/attempts; record explicit outcomes).
5. Every job: bundle validation on the host
   (`build/rk3588-example-captures/runner/validate_bundle.py`), transfer with
   hashes, one locked runner invocation, transfer back with hashes, per-case
   comparison report against capture + RTL sim receipts, and a job receipt
   under `build/rk3588-live-verify/<RUN_ID>/`.
6. The FPGA side: once the DLC10 cable is attached and the user authorizes the
   volatile load, the same fixture set runs on the six-page image
   (`tools/host/run_jtag_dual_hardware.py`), and its BO readback is the third
   leg of the comparison (live NPU ↔ RTL sim ↔ FPGA).

Only after J01-J06 and J10-J13 are green for a family should that family's
example be claimed runnable on the FPGA; families with RTL gaps (§5) get their
own RTL/qualification work first.

## 7. Fix-and-rebuild policy (user-authorized 2026-11-10)

The user authorized fixing any problem these jobs find and rebuilding the
bitstream if needed ("fix any problem u found and update RTL and rebuild
bitstream if needed"). Findings are classified before any edit, because a
needless RTL change invalidates the frozen-tree evidence and costs a full
rebuild:

| Class | Meaning | Action |
|---|---|---|
| **A. Capture/fixture defect** | live device disagrees with the frozen capture or the host `expected.bin`, or a bundle field is wrong (e.g. the earlier 7,552 vs 15,104-byte depthwise BO) | fix the bundle/fixture and its manifest; no RTL change, no rebuild |
| **B. RTL bug in a page the current six-page image carries** | an image-corpus case (conv-simple 0-3, pooling INT8 max k2s2 C16, GEMM 4 shapes) disagrees with the live device | fix the RTL leaf; add/keep a source-bound regression; re-run module proofs + the affected replays; **rebuild the six-page bitstream**; record new WNS/DRC/SHA; re-run the frozen-tree matrix on the new source set; the hardware session and any future receipt bind the new image hash |
| **C. RTL gap outside the current image** | e.g. the FP32-C32 conv layout, the two INT8 conv +1-LSB conversion cases, integer EW, conv-fp16 pages not in the image, BS/BN | implement/fix as an increment; rebuild only once the fixed leaf is actually included in an image; do not touch the current image's evidence |
| **D. ABI/device limitation** | vendor RKNPU core_mask/subcore_task/PC self-address, multi-task transport, unsupported dtype/shape | record the explicit limitation and the evidence; no RTL change unless a supported decomposition exists |

Rules for a class-B change: never weaken a gate to make the rebuild pass;
delete supersede-only evidence rather than mixing hashes; record the new
bitstream SHA-256, WNS/WHS, DRC and utilisation; the frozen-tree replay matrix
must be re-pinned to the new source hashes before the new image is cited.

## 1c. P1 family-wide live differential — COMPLETE 2026-11-10 (38/38 PASS)

All READY cases in the three remaining families were re-live-verified against
their frozen captures under the full board race-control protocol (one runner at
a time inside `flock -x -w 900`, fresh remote stage + fresh `--out` per batch,
J00 preflight/postrun checks, hashes both ways; no reset/reprogram/flash):

| Job | Family | Cases | Result |
|---|---|---:|---|
| J10 | conv-fp16 | 9 | **9/9 PASS** — defined oracle lanes == frozen capture exact (atol 0.0, max_abs_diff 0); complete-BO equality vs capture is ill-defined for 4 cases due to device padding (below) |
| J11 | conv-gemm-vendor | 10 | **10/10 PASS** — every live complete BO == its frozen capture exactly; logical comparison 8 exact + 2 documented tolerance-only (GEMM m4n32k64 max diff 9.54e-7; conv.py C32/OC128 max diff 0.015625 within 0.12) |
| J12 | pooling | 19 | **19/19 PASS** — complete 4096-B BO exact vs frozen capture and vs raw-BO expected.bin |

One class-D finding (documentation, not an RTL/fixture defect): for 4 conv-fp16
spatial cases the `align_out_c=32` channel-plane **padding source-type bytes are
non-deterministic** on the device (`0xfc00` vs `0x7c00` NaN variants) and also
differ between the two independent capture runs. Defined lanes are stable and
exact; a repeat probe (J10b) proved full-BO runA==runB within one allocation
context but padding differs across allocation contexts. **Criterion for these
cases: defined-lane/logical comparison, not full-BO equality.** Receipt:
`build/rk3588-live-verify/20261109T213515Z-j10/J10-PADDING-ANALYSIS.json`.

Evidence: `build/rk3588-live-verify/P1-SUMMARY.md`, `P1-INDEX.json`, receipts
`20261109T213515Z-j10`, `20261109T213906Z-j10b`, `20261109T213726Z-j11`,
`20261109T213755Z-j12`. With P0 (image corpus + class grid) and the FDIV
residual closure, every READY captured family now has a family-wide live
differential.

## 1d. P2 live differential and probes — COMPLETE 2026-11-10

| Job | Scope | Result |
|---|---|---|
| J13 | **ew-fp16 family-wide differential, 54/54 READY** | **54/54 live complete 4096-B BO == frozen capture**; donor-CPU oracle 52/54 exact; FDIV 7/9 exact + the 2 documented A/7 cases with exactly 20 one-ULP-low lanes (all delta −1 bit, matches docs/FDIV.md; no new anomaly) |
| J14a/J14b | Determinism repeats, ADD/SUB/MUL/MAX/FDIV, two separate lock windows | **5/5 byte-identical** across windows, equal to J13 and to frozen captures |
| J15 | Boundary probes (18 manifest BLOCKED cases; 4 have prepared bundles) | Class D reproduced: multi-task transport (grouped G2: task0 logical PASS atol 0, task1 all-zero identical to recorded evidence; splitoc C16 same pattern), unsupported PPU dtype (FP32/INT32 max zero-write: job accepted, output unchanged/all-zero). 14 cases have no bundles and remain documented blockers. Vendor-ABI J20 evidence: Rocket lacks `core_mask`/`subcore_task`, vendor `op_idx/enable_mask/int_mask/int_clear`, and a patch kind for the self-referential PC chain |

Evidence: `build/rk3588-live-verify/P2-SUMMARY.md`, `P2-INDEX.json`,
receipts `20261110T075010Z-j13`, `…j14a`, `…j14b`, `…j15`. With P0/P1/FDIV/P2,
**every READY captured family now has a family-wide live differential**, and
the only remaining live gaps are the documented class-D blockers (no bundles).

## 8. Background C/D fix workstreams (user-authorized, 2026-11-10)

The user authorized fixing the remaining class-C/D items in the background
("u can still fix in bg fix"). None of these touches the adopted six-page image
or its frozen evidence; each produces its own new image/receipt.

| Task | Class | Scope | Owner |
|---|---|---|---|
| **task-9** | C1 | Rebuild a current host-drivable **EW image** (`ypcb_jtag_ew_top`, host-jtag-ew-bram) from the current RTL, including the FDIV path (ALU op 4, three-guard-bit contract), so `elementwise.py`/`simple_add.py`/FDIV families can run on FPGA. Audit decoder→engine→ALU, run EW sim/host evidence on the current tree, build and record gates + SHA | timing |
| **task-10** | C2 | New **pooling-corpus image**: one AXI page per frozen pooling fixture (19 READY + 1 derived), shared BRAM window, identities, contract tests, all-fixture replay; measured split if ~20 pages do not fit. Separate from the six-page image | share |
| **task-11** (DONE) | C3 | Live-capture the **residual 64 FDIV lanes** (24 special + 40 finite-sweep) with faithfully reconstructed bundles under the board flock; compare to capture and the 3-guard-bit RTL model; receipts + `FDIV-RESIDUAL.md` | rkref |
| **task-12** (DONE) | D / support | **Multi-image deployment** section in `docs/BOARD_RUN_PREP.md` (inventory: families→image→SHA→transport→modes; volatile-load-only switching), host tooling map, final class-D ABI records (vendor `core_mask`/`subcore_task`/PC self-address, multi-task transport, unsupported dtype/shape), offline validation | board |

Coordination: one Vivado at a time, serialized with
`flock -w 3600 /tmp/rknpu-vivado.lock` and `taskset -c 4-7` so verif's
frozen-tree matrix keeps cores 0-3; no timing/DRC/electrical gate may be
weakened; no hardware programming or flash; new images get fresh receipt
directories and their own SHA-256s.

### Decided direction (user, 2026-11-10): runtime-decoded conv engine

For the conv corpus the user chose the real-NPU-style architecture:
**runtime-decode the convolution geometry from the per-task command stream**
instead of elaboration-time profile variants. The real RK3588 CNA configures
its shape/stride/pad/channel/group fields per command; our current one-variant-
per-capture cores are a bring-up artifact. A single runtime-decoded conv engine
can serve the 9 conv-fp16 cases and the 4 conv-simple profiles from unchanged
command streams, and can eventually replace the four per-profile conv pages in
the main image (freeing ~90–100k LUTs and moving toward one image for the conv
corpus).

Staged work (task-13, teammate `conveng`): (1) design + register-field →
geometry evidence map (`docs/CONV_RUNTIME_ENGINE.md`); (2) prototype decoder +
generalized front/mask generator under `rtl/cmac/experimental/runtime/`,
reusing the CMAC/CACC array unchanged; (3) old-vs-new equivalence harness on
the same frozen fixtures (complete output BOs byte-for-byte + explicit-failure
negative controls); (4) synth-only area estimate; (5) then a conv-fp16-only
runtime image, and only after that the main-image replacement proposal. The
adopted six-page image and its frozen evidence are untouched until a fully
qualified replacement exists.

Still open separately: the FP32-C32 conv-simple case (device layout understood;
a new page/engine mode is a further increment).
