# Handoff — running the RK3588 examples on the K8 FPGA

Last updated: **2026-11-12 00:25 HKT**
Audience: the next coding agent picking up the work, on a better-cooled machine.

> **Read §16 first if you only read one section.** It is the current state, the
> exact next action, and the five mistakes already made (so you don't repeat them).
> §4-§13 remain the standing design map, commands, traps and evidence index.

## 0. State in one paragraph

The project has split into two images. **Image A** (runtime conv engine + real
GEMM page + USER2 transport) is **built, timing-clean, and its bitstream is
emitted and committed** — the first gate-clean candidate for a volatile load.
**Image B** (pooling corpus + EW FP16/FDIV + ew-int) has **all six pages real and
DRC clean**, and a real timing defect was found and fixed in a frozen pooling
leaf under a documented freeze exception, but **Image B has not yet completed a
clean build**: its last attempt was killed by the thermal guard because it was
launched without `BENCH_HOLD_FOREIGN=1` while ungoverned foreign work saturated
the host. **Nothing has ever been programmed or observed on a board**; every
receipt says `hardware_accessed=false`, and the hardware session is blocked only
on the DLC10 cable being attached plus explicit authorisation. The host that
produced all of this is thermal-throttled and is being replaced, which is why
this file now leads with a §16 that a fresh session can act on directly.

## 1. Read first

1. `AGENTS.md` — the binding rules for this repository.
2. `README.md`, `docs/INTERFACE.md`, `docs/REVIEW_AND_PLAN.md`.
3. `progress.md` — the one-screen measured status.
4. `docs/PROGRESS_TABLE.md` — the long-form status and remaining-work list.
5. `docs/CONV_PAGE_SCALING.md` — why the six-page build exists and why it
   currently fails timing.
6. `docs/CONV_FP32_PAGE.md`, `docs/GEMM_FP32_AXI_PAGE.md`,
   `docs/CONV_SIMPLE_FIXTURES.md`, `docs/CONV_GEMM_VENDOR_FIXTURES.md`.

## 2. Definition of done

The user's objective is "all `~/rk3588/examples` run on the FPGA". That means:

1. every captured example has a supported command stream and a page/leaf that
   reproduces its captured output within the family's stated bound;
2. one bitstream carries every page needed for the corpus, closes timing/DRC
   without weakening a gate, and is emitted with a recorded SHA-256;
3. that bitstream is programmed onto an **audited** board;
4. each example is submitted from the host, the output read back, and compared
   against the capture **on hardware**.

Only part of (1) is true today: all four conv-simple profiles, all four GEMM
shapes and all 20 pooling fixtures have executing leaves/pages, but the
conv-fp16 family still has captures without an image page and three vendor-BY_K
cases have no RTL. The six capture disagreements that used to be listed as
"rejected" are now classified by the 2026-11-10 live-NPU pass: three were
bundle/oracle defects (reconciled), three are stable real device behaviour the
host oracle does not model (device wins; none is in the image — see §10). (2) is now true for the six
pages the image carries — `build/jtag-dual-image/20261109T160627Z` closes
timing/DRC without weakening a gate and records a bitstream SHA-256. (3) and
(4) have never happened: no board has been programmed, and no example has been
submitted from a host to real silicon in this project.

## 3. Non-negotiable rules

- Raw final command QWORDs are the execution boundary. Do not bypass the backend
  encoder by passing tensor operations directly.
- Do not introduce CPU arithmetic or layout repair into the FPGA path. The
  software reference is a test target, not a hardware fallback.
- Unsupported fields must fail explicitly. Do not silently ignore unmodeled
  register writes; add support only with source evidence, shape/numerical
  contracts and tests.
- Do not weaken timing, DRC or electrical constraints to get a bitstream. Do
  not raise `dissolveMemorySizeLimit`, and do not lower the 50 MHz clock, as a
  shortcut.
- Do not program the card or flash anything without an explicit user request and
  an audited target. The RK3588 SSH target is read-only unless separately
  authorized.
- Default builds/simulations expected to exceed ~30 s to the background. Record
  tool version, source revision, seed and exact command with every receipt.
- Delete superseded receipt trees rather than citing them as evidence for
  changed RTL.

## 4. Design map

| Path | Role |
|---|---|
| `fpga/ypcb_dual_endpoint_top.sv` | six-page image, AXI4-Lite slave, 32 KiB memory window, page arbitration |
| `fpga/ypcb_jtag_dual_top.sv` | pin-free USER2 mailbox wrapper around the image (the buildable form) |
| `fpga/jtag_dual/build_jtag_dual.tcl.in` | Vivado template: synth, place, route, timing/DRC gates, page-presence gate |
| `fpga/jtag_dual.xdc` | clock, pin constraints; only `AA28` + `P30/M30/N30` may be assigned |
| `rtl/cmac/rk_conv_3x3_valid_c4_front.sv` | streaming operand front: single-port weight/input RAMs, per-frame assembly |
| `rtl/cmac/rk_frame_stage.sv` | one-deep register slice; carries address/tag fields, clears on cancel |
| `rtl/cmac/rk_conv_simple_core.sv` | four-profile conv core (FP16 tail and FP32 tail variants) |
| `rtl/cmac/rk_conv_3x3_valid_c4_core.sv` | vendor-profile conv core (8 profiles) |
| `rtl/cmac/rk_cmac_fp16_cell.sv` | 32-lane FP16 cell, **three-leg registered pipeline** (`845d7843…`): leg 1 operand decode + balanced exponent-max tree + NaN priority; leg 2 unmodified donor Booth/CSA multiply/shift + row sums; leg 3 balanced 32-way modulo-2^38 accumulate + NaN mux |
| `rtl/cmac/rk_cmac_fp16_array.sv` | K16 array of cells + **elastic 3-deep valid/tag pipe** (`473177ec…`); hold-until-ready result register; 13-port external interface unchanged, latency +2 cycles, throughput unchanged |
| `rtl/cmac/rk_cmac_cacc_fp16_array.sv` | group formation + CACC accumulation + FP32 finalisation (unchanged by the pipeline work) |
| `rtl/cmac/rk_cmac_gemm_axi.sv` | decode-driven GEMM page (all four frozen shapes) |
| `tools/dual/run_dual_endpoint.py` | nine-mode dual replay, source-hash receipts |
| `tools/host/run_jtag_dual.py` | USER2 mailbox modes 0-6 |
| `tools/conv/run_3x3_valid_c4.py` | eight vendor-profile replays, both simulators |
| `tools/conv/run_conv_simple_axi.py` | four conv-simple endpoint profiles, eight modes each |
| `tools/dual/vivado_jtag_dual.py` | source-gated Vivado runner; never programs |
| `tests/test_dual_endpoint_contract.py` | 61-test image/page contract |

Page map: `0x8000` conv p0 (RKCS), `0x9000` pooling (RKPP), `0xa000` GEMM
(RKCM), `0xb000` conv FP32 p3, `0xc000` conv k5 p1, `0xd000` conv C16 p2,
`0xe000+` SLVERR.

## 5. Resolved: the vendor core now compiles in Icarus

The declaration-after-use regression in `rtl/cmac/rk_conv_3x3_valid_c4_core.sv`
(`logic staged_valid, staged_ready;` was first used by
`assign frame_ready = staged_ready && !error;` and declared ~45 lines later) is
fixed: the block now sits next to
`logic front_busy, front_error, frame_valid, frame_ready;`. It was a
declaration-order bug, not a logic change.

First source-hashed PASS receipt (16/16 modes, Icarus 13.0, clean compile with
zero warnings): `build/convolution-3x3-valid-c4/iverilog-20261109T150257Z`.
The runner keeps treating any `warning:`/`sorry:` as a compile failure; never
suppress a warning to obtain a green run.

## 6. Resolved: the six-page image closes 50 MHz

Adopted receipt: **`build/jtag-dual-image/20261109T160627Z`** (Vivado 2026.1,
2,908 s, six pages present per the build's page-presence gate).

| Gate | Value |
|---|---|
| Status | **PASS**, `bitstream_emitted=true`, `hardware_accessed=false`, `source_match=true` |
| WNS / TNS | **+3.952 ns** / 0.000 ns |
| Failing endpoints | **0 / 202,615** |
| WHS / THS | +0.054 ns / 0 |
| Slice LUTs | 231,316 / 298,600 (77.47%) |
| Slice registers | 71,058 (11.90%) |
| Block RAM | 19.5 tiles (19 RAMB36) |
| Routed nets | 331,098 / 331,098, 0 errors |
| DRC | 0 errors; warnings only (`CHECK-3`x2, `DPIP-1`x12, `DPOP-1`x6, `DPOP-2`x6, `REQP-1839`x20, `REQP-1840`x20) |
| Bitstream | 18,735,215 bytes, SHA-256 `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` |

The superseded failing build (`build/jtag-dual-image/20261109T180000Z`, WNS
-1.549 ns, 244/115,597 failing endpoints, worst path
`conv_c16_page/.../stage/data_q_reg[21] -> arithmetic/cmac/out_groups_reg[121]`,
52 levels) stays as history for the failure shape; the C16 CMAC cell cloud was
the entire failing cluster.

What changed: `rk_cmac_fp16_cell` is a three-leg registered pipeline and
`rk_cmac_fp16_array` owns a matching elastic 3-deep valid/tag pipe; the CACC
chain and all page/transport contracts are unchanged. The arithmetic is
bit-identical and the proofs are listed in §7. The worst routed path is no
longer arithmetic: it is a cross-page stall/error aggregation chain
(`conv_page/engine/state_q_reg[0] -> gemm_page/.../reader/error_code_reg[2]/CE`,
15.549 ns, 91.6% route, 18 levels). Closure is a design property, not a
placement outlier. Option-B's shared array is archived and not part of this
image (see §12).

Adoption note: the build ran in a separate snapshot tree while the option-B
experiment held the working tree. The tree was then restored to the same pre-B
sources and all 73 build inputs compare byte-identical
(`build/timing-lab-share/a_only_adoption_manifest.json`;
`build/jtag-dual-image/20261109T160627Z/ADOPTION_PROVENANCE.md`). Any future
re-timing should re-check hold (+0.054 ns, skew-dominated on a
front->frame-stage hop) and the 94.35% slice occupancy.

## 7. Evidence debt: which receipts are still valid

A receipt is evidence for the current tree only when **all** of these hold:

1. `status == "PASS"`;
2. `source_hashes_before == source_hashes_after`;
3. those hashes equal the files on disk now;
4. `tool_version` is a real version string;
5. the comparison is the one claimed (full BO, tolerance bound, negative
   controls), not a prefix.

Current state (final tree, 2026-11-10):

- Contracts pass on the current tree: 61 + 60 + 106 + 20 = **247 tests**, plus
  `make generated-check` and a clean `git diff --check`.
- The adopted six-page image `build/jtag-dual-image/20261109T160627Z` is PASS,
  source-matched (73/73 before==after) and is the image the replay receipts
  must match. Its provenance/adoption note is inside the receipt directory.
- Module-level pipeline equivalence proofs on the frozen cell/array hashes
  (Verilator 5.048 / Icarus 13.0): cell_equiv 20,000 random/directed vectors
  with identical result and invalid; array_stream 40 ordered frames / 160
  groups under independent random backpressure on both sides with identical,
  ordered groups/tags; array_xreject X operand frame rejected at the seam with
  sticky error and no emission. Benches under `build/timing-lab/`.
- `tools/conv/run_conv_simple_axi.py` now records
  `source_hashes_before`/`source_hashes_after` and fails closed if a source
  changes mid-run. `tools/dual/vivado_jtag_dual.py` likewise records
  before/after hashes and fails the build if any input changes.
- **Live RK3588 NPU verification of the image corpus (2026-11-10, authorized
  active submissions, exclusive board lock):** FDIV differential fully closed
  at **1,452/1,452 captured lanes** (class grid + 1,132 finite + 64
  reconstructed residual; three-guard-bit model confirmed live; see
  `build/rk3588-live-verify/FDIV-RESIDUAL.md`). conv-simple 4/4, pooling 1/1,
  GEMM 3/4 bit-exact raw surfaces + `m4n32k64` within 9.54e-7, all live SHA-256
  equal to the frozen 2026-11-05 captures; deterministic repeats; FDIV
  256-class grid and 1,132 finite lanes exact against the three-guard-bit
  contract. Conv p0, pooling and GEMM `m2n2k1` are three-way matched (live ==
  capture == RTL replay). Job list/race protocol:
  `docs/RK3588_LIVE_VERIFICATION_JOBS.md`; evidence
  `build/rk3588-live-verify/P0-SUMMARY.md`. No image-corpus bug was found, so
  no RTL/bitstream change was triggered.
- Frozen-tree evidence confirmed so far (label `FINAL-freeze-20261109T160627Z`):
  the **eight vendor conv profiles PASS in both simulators (16/16)**, every
  receipt hash-matching the frozen manifest with full-BO compares
  (Icarus 13.0 / Verilator 5.048). The six-page image replay matrix (dual
  0-8, mailbox 0-6, four conv-simple profiles) is still running; dual modes
  0-2 and mailbox mode 0 are PASS so far. The old dual/mailbox PASS trees
  (`build/dual-endpoint/verilator-20261109T03…`) predate the streaming front
  and are history.
- Pooling's 20 fixtures and the four GEMM shapes were measured on unchanged
  leaf RTL; their end-to-end image replay is part of the frozen-tree matrix.
- Killed-compile artifacts from the 2026-11-10 memory intervention are not
  functional failures: `build/dual-endpoint/verilator-20261109T160842Z`,
  `build/jtag-dual/verilator-20261109T155740Z`,
  `build/dual-endpoint/verilator-20261109T153555Z`, and the killed
  `build/timing-lab/ooc-*` lab trees. Abandoned `RUNNING` markers with live
  process count 0 (`build/jtag-dual-image/20261109T200000Z`,
  `/20261109T031500Z`) are not running builds either.

## 8. Exact commands

### Contracts

```sh
python3 -m unittest tests.test_dual_endpoint_contract
python3 -m unittest discover -s tests/conv -p 'test_*contract.py'
python3 -m unittest discover -s tests/ppu_pooling -p 'test_pool_*contract.py'
python3 -m unittest discover -s tests/cmac -p 'test_*contract*.py'
make generated-check
git diff --check
```

### Vendor conv profiles (eight cases, both simulators)

```sh
for c in \
  conv_3x3_valid_c4_h9_w9_oc4 \
  conv_3x3_stride2_c4_h11_w11_oc4 \
  conv_3x3_pad1_zero_frame_c4_h9_w9_oc4 \
  conv_grouped_3x3_c4_h5_w5_oc8_g2_task0 \
  conv_grouped_3x3_c4_h5_w5_oc8_g2_task1 \
  conv_splitoc_3x3_c16_h9_w9_oc16_task0 \
  conv_splitoc_3x3_c16_h9_w9_oc16_task1 \
  conv_depthwise_3x3_c3_h11_w28_oc3; do
  python3 tools/conv/run_3x3_valid_c4.py --case "$c" --simulator both
done
```

Expect the Icarus compile to fail until section 5 is fixed. The runner treats
any compiler warning as a failure on purpose.

### conv-simple endpoint (four profiles, eight modes each)

```sh
for c in \
  conv_simple_fp16_3x3_c4_h8_w8_oc16 \
  conv_simple_fp16_5x5_c4_h8_w8_oc16 \
  conv_simple_fp16_3x3_c16_h8_w8_oc32 \
  conv_simple_fp16_1x1_c4_h8_w8_oc16; do
  python3 tools/conv/run_conv_simple_axi.py --case "$c" --simulator iverilog
  python3 tools/conv/run_conv_simple_axi.py --case "$c" --simulator verilator
done
python3 tools/conv/run_conv_simple_fp32.py --simulator both
```

### Dual endpoint (nine modes)

```sh
python3 tools/dual/run_dual_endpoint.py --simulator verilator
python3 tools/dual/run_dual_endpoint.py --simulator iverilog
```

The runner has a 14,400 s per-mode wall-clock cap because the streaming feed
makes C16 frames 144 cycles long. A timeout is reported as FAIL; do not treat
it as a pass. Icarus on the six-page top is very slow; run it in the background.

### USER2 mailbox (seven modes)

```sh
python3 tools/host/run_jtag_dual.py --simulator verilator
```

Mailbox modes 1-4 are conv, pooling, GEMM and FP32 conv; modes 5-6 add the
conv k5 and C16 pages. The exact frame count is recorded in each receipt and
changes with the image and profile; do not hard-code it. Icarus at 640 scan
edges per frame is impractical; Verilator is the supported leg.

### Six-page image build

```sh
RK_CONFIRM_BOARD=YPCB_00338_1P1 \
RK_CONFIG_VOLTAGE=1.8 \
RK_CFGBVS=GND \
RK_EMIT_BITSTREAM=1 \
RK_LED_ACTIVE_LOW=0 \
python3 tools/dual/vivado_jtag_dual.py run \
  --out build/jtag-dual-image/$(date -u +%Y%m%dT%H%M%SZ)
```

`YPCB_00338_1P1`, `1.8`, `GND` and `0` are the values used so far; they are
**not** audited on this card. The Tcl refuses a bitstream without a confirmed
board/voltage pair. The gate now passes: the adopted receipt is
`build/jtag-dual-image/20261109T160627Z` (48 min, WNS +3.952 ns). The runner
records before/after hashes for all 73 inputs and fails the build if any source
changes mid-run, so freeze the tree for the whole run. Start hour-long builds
detached (`nohup ... > log 2>&1 &`) instead of as a tracked tool background job
that a session restart can SIGTERM; poll `inputs.json` status.

Read the receipt:

```sh
python3 - <<'PY'
import json, hashlib
from pathlib import Path
d = Path('build/jtag-dual-image/<stamp>')
r = json.loads((d / 'inputs.json').read_text())
print(r['status'], 'bitstream_emitted=', r['bitstream_emitted'],
      'hardware_accessed=', r['hardware_accessed'])
t = (d / 'implementation/timing.rpt').read_text().splitlines()
for i, line in enumerate(t):
    if 'WNS(ns)' in line:
        print(' '.join(t[i+2].split())); break
b = d / 'implementation/rk_jtag_dual.bit'
print(hashlib.sha256(b.read_bytes()).hexdigest() if b.exists() else 'no bitstream')
PY
```

### Freshness audit for a receipt tree

```sh
python3 - <<'PY'
import hashlib, json, glob
from pathlib import Path
files = [
  'rtl/cmac/rk_conv_3x3_valid_c4_front.sv',
  'rtl/cmac/rk_frame_stage.sv',
  'rtl/cmac/rk_conv_simple_core.sv',
  'rtl/cmac/rk_conv_3x3_valid_c4_core.sv',
  'fpga/ypcb_dual_endpoint_top.sv',
]
cur = {f: hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in files}
for p in sorted(glob.glob('build/dual-endpoint/*/mode-*/report.json')):
    r = json.loads(Path(p).read_text())
    h = r.get('source_hashes_before') or {}
    fresh = all(h.get(f) == v for f, v in cur.items())
    print('FRESH' if fresh else 'STALE', r['status'], p)
PY
```

## 9. Traps

- **Uncommitted tree.** There are ~260 untracked and ~38 modified paths; the
  new RTL/docs are not in git history. Do not run `git clean`, `git checkout
  -- .`, or a reset. Work with the files on disk.
- **Source hashes are the evidence boundary.** A PASS receipt whose recorded
  hashes differ from the current files is history. Delete superseded trees
  rather than leaving them to be mistaken for current.
- **Icarus compile warnings are errors** in `run_3x3_valid_c4.py`
  (`warning:|sorry:`). Fix the warning; never suppress it.
- **Icarus prints its version on stderr**, and `vvp` does not accept `-P`;
  parameters are compile-time (`iverilog -P...`), and only for parameters in the
  module's formal list.
- **conv-simple frozen `regcmd.bin` has three zeroed address fields.** The
  runners patch them from the manifest / BO bases. Do not assume the frozen
  command stream is self-contained.
- **`rk_conv_simple_dma` needs `result_ready` tied high**, otherwise it never
  leaves `ST_FINISH`.
- **Mailbox bench scratch arrays are 4096 words.** Profile 2's weight BO is
  2304 words; a 2048-word array aborts with a `$readmem` bounds error.
- **Do not reset RAM arrays.** A reset on `weight_store`/`input_store` prevents
  block-RAM inference. Only the write port is enabled during load.
- **The front walks real channels only.** `FRAME_WEIGHT_HALFWORDS =
  KERNELS*INPUT_CHANNELS`; padded BO lanes stay zero and are masked. The frame
  bus is cleared at the start of every frame.
- **`rk_frame_stage` must clear `full_q` on cancel** and carry
  address/first/last/last_output with the payload; the CACC tag must stay stable
  across every tap of an atom.
- **The page-presence `foreach` gate** in `build_jtag_dual.tcl.in` asserts each
  page instance exists. If you add a page, update the gate and
  `tests/test_dual_endpoint_contract.py` together.
- **Vivado timing gate failure is a real refusal.** A missing timing path or an
  unparsable count is an error by design; do not edit the gate to pass.
- **Long builds:** ~48-55 min. Start them detached (`nohup ... > log 2>&1 &`)
  and poll `inputs.json` status; a tracked tool background job can be killed on
  a session restart (it happened once here and is not a functional failure).
- **One memory-heavy job at a time on this 36 GB box.** Verilator `--binary`
  with `-j 4` spawns several multi-GB `cc1plus` jobs, and two Vivado instances
  plus sims once pushed the machine to 19 GB of swap; several compiles were
  SIGTERM'd as collateral. Use `-j 1` for Verilator compiles, check `free -g`
  before launching, and never run two Vivado instances concurrently.
- **Host power + thermal limits (this ThinkPad).** Two hard crashes on
  2026-11-10 came from a power-delivery brownout with a near-empty battery and
  a weak charger (fixed with a new 39 W charger); a later thermal event killed
  runs at Tctl 98.2 °C with both fans at max (degraded cooling — idle/heat-soak
  ~84 °C). Diagnosis/prevention: `docs/HOST_CRASH_POSTMORTEM.md`. ALL heavy
  host jobs must go through `build/verif/host_guard/safe_run.sh`: battery gate
  plus a global heavy-job lock (`/tmp/rknpu-heavy.lock`), a Tctl < 82 °C
  cool-down gate, optional `BENCH_CPU_QUOTA`, and CPU pinning; the strict
  `host_guard.py` v2 kills real heavy tools above 95 °C. Run short bursts with
  cool-downs, never two heavy jobs, and prefer `BENCH_CPU_QUOTA=55-70` for long
  legs. If thermal kills recur, treat it as host cooling hardware.
- **Adopted builds from a snapshot tree are only valid with a byte-identical
  input proof.** `tools/dual/vivado_jtag_dual.py`'s `inputs()` list is the
  authority: compare every file between the snapshot and the adopted tree
  (`build/timing-lab-share/a_only_adoption_manifest.json` is the example) before
  citing the receipt against the working tree.
- **The testbench runners rebuild the RTL list per run**, so a mid-run source
  edit fails closed by design (source-hash serialization). Do not edit RTL while
  an evidence run is in flight; re-run instead.

## 10. Blocked work that RTL cannot invent

These are capture/contract questions and should not be "fixed" by guessing:

- `conv_byk_c160_h14w14_oc320_k3x3` — vendor BY_K path uses `np_submit(...,
  task_count=3, core_mask=0, subcores=((0,1),(0,1),(0,1),(0,0),(0,0)))`; Rocket
  has no `core_mask`/`subcore_task` UAPI. The 11-row layout also patches
  `PC_BASE_ADDRESS` to the regcmd BO's own DMA address, which the bundle schema
  cannot express.
- `conv_h40_c160_h40w40_oc320_k3x3` — six-task BY_Y distribution, same class of
  limitation.
- `conv_depthwise_3x3_c3_oc3_h11w28` — multitask (task0/task1) is BLOCKED; the
  two READY task captures are frozen individually.
- Capture disagreements (resolved 2026-11-10, device wins): the three
  conv-gemm-vendor "rejected" cases were bundle defects and are reconciled
  (depthwise 15,104-byte BO fix → 702/702 exact; `conv.py` case within the
  0.12 tolerance). The three conv-simple cases are stable real device behaviour
  the host oracle does not model: FP32-C32 structural chunk placement
  (6 of 8 chunks emitted, slots 6-7 zero) and two INT8 cases with 7/13 bytes at
  `expected + 1`. Device surfaces are in
  `build/rk3588-live-verify/J05-device-oracles/`. None is in the six-page image;
  no RTL or bitstream change was needed. They remain unfrozen until a
  device-derived oracle is pinned.

## 11. What only the user can decide or provide

Do not guess any of these. No new RTL decision is pending: the five-page and
clock-change options are moot because all six pages closed at 50 MHz.

1. **Authorization to program** the card with a **volatile** JTAG load, and the
   session's **audited board identity**. No DLC10 cable is attached to this
   machine right now (`lsusb` has no `03fd:` device; the read-only preflight
   exits 2). `YPCB_00338_1P1` is only the build-time string. A prior physical
   session (2026-10-27, a different EW image) recorded cable serial
   `80802026a77a01`, DNA `004E544714C705C` and IDCODE `0x23751093`.
2. **LED polarity** (`RK_LED_ACTIVE_LOW` 0 or 1). The donor records it
   unverified; the six-page images were built with 0.
3. Confirmation of the **configuration bank**: `CONFIG_VOLTAGE 1.8` /
   `CFGBVS GND` is donor-derived from OpenTPU plus a prior-image `CFGBVS_PIN=0`
   read, not a strap measurement on this card.
4. Whether a **cold boot from flash** is ever wanted. Flash remains
   unauthorized; only volatile JTAG loads are prepared.
5. Practical session details: who attaches the cable and when, and the shared
   board lease window (`/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock`).

## 12. Suggested work order

**Current order (2026-11-12) — start with §16.4.**

1. **Rebuild Image B** with `BENCH_HOLD_FOREIGN=1` and verify the *Design Timing
   Summary* (not the first `Setup :` line). If it closes, emit; if not, pipeline
   the remaining pooling leaves and record which ones failed.
2. **Run the Image-B replay suite** (`--mode full`, needs a heavy window) and the
   merged offline suite, and cite only source-matched PASS receipts.
3. **Ask the user for the hardware session** (DLC10 cable attached + explicit
   authorisation for one volatile load + audited target). Image A
   `5b03e738...` is a valid candidate now.
4. **With authorisation, and only then:** preflight -> DLC10 init -> read-only
   target audit -> volatile load of the exact image ->
   `tools/host/run_jtag_dual_hardware.py --authorized`, capturing receipts.
   **Never flash.**
5. **Compare read-back against the frozen fixtures.** A hardware PASS binds the
   exact image hash and that session's target identity only.
6. **Future increments** (not required for the objective): the conv corpus
   direction is a runtime-decoded conv engine (user choice 2026-11-10; task-13,
   `docs/CONV_RUNTIME_ENGINE.md`) that decodes geometry from the per-task command
   stream; staged work is under `rtl/cmac/experimental/runtime/`. The archived
   option-B shared-array work (`build/timing-lab-share/`) stays as a fallback.
   BY_K/multitask capture work stays blocked on UAPI/bundle evidence (§10).
7. Keep `progress.md` and this handoff in sync; superseded receipts stay as
   history, never as evidence for changed RTL.

Historical note: the older version of this section led with "finish the frozen-tree
replay matrix" against the six-page image and `81eef4cd...`. That image is now one
of several candidates; the replay matrix work is largely done and is recorded in
§7 and §13.

## 13. Evidence index

| Path | What it proves |
|---|---|
| `build/jtag-dual-image/20261109T160627Z` | **adopted six-page bitstream**: PASS, WNS +3.952 / WHS +0.054, 0/202,615 failing, 231,316 LUTs, bitstream SHA `81eef4cd…4d39`. Provenance/adoption note inside the directory |
| `build/timing-lab-share/a_only_adoption_manifest.json` | the 73 build inputs of that receipt are byte-identical to the adopted working tree |
| `build/jtag-dual-image/20261109T180000Z` | superseded: six pages, timing **FAIL** WNS -1.549, no bitstream (history of the failure shape) |
| `build/jtag-dual-image/20261109T073000Z` | superseded four-page interim image, WNS +0.044 (history; do not load as current) |
| `build/timing-lab/` | pipelined-cell equivalence proofs (`tb_cell_equiv`, `tb_array_stream`, X-reject) and the killed OOC lab (non-evidence) |
| `build/timing-lab-share/` | option-B v2 archive (`option-b-v2/`, `option_b_v2.patch`, `OPTION_B_STATUS.md`), the verified pre-B baseline copies, and the A-only adoption manifest. B is not integrated or qualified |
| `build/convolution-3x3-*` | vendor-profile replays, both simulators (each receipt records its tracked hashes; the Icarus leg now compiles) |
| `build/conv-axi/*` | conv-simple endpoint replays (source-hashed since the runner fix; check `source_hashes_*` in each report) |
| `build/dual-endpoint/*` | nine-mode dual replays through the six-page top; only receipts matching the FINAL-freeze hashes count |
| `build/jtag-dual/*` | USER2 mailbox replays modes 0-6; same hash rule |
| `build/verif/frozen_hashes.json` | FINAL-freeze manifest (label `FINAL-freeze-20261109T160627Z`) used to audit receipts |
| `docs/BOARD_RUN_PREP.md` | audited hardware programming/run procedure, preflight, user decisions, no-flash rule |
| `docs/RK3588_LIVE_VERIFICATION_JOBS.md` | live RK3588 NPU job list, race-control contract, fix/rebuild policy |
| `build/rk3588-live-verify/P0-SUMMARY.md` | live-NPU P0 evidence: per-case live==capture tables, determinism, divergence classification, FDIV |
| `build/rk3588-live-verify/J05-device-oracles/` | device surfaces and diffs for the three conv-simple host-oracle divergences |
| `tools/host/run_jtag_dual_hardware.py` + `tools/host/jtag_preflight.py` + `tests/host/` | real-board USER2-mailbox harness (refuses without authorization/audited image) and read-only cable preflight, with offline controls |
| `build/rk3588-live-verify/P1-SUMMARY.md` | P1 family-wide live differential: conv-fp16 9/9 defined-lane exact, conv-gemm-vendor 10/10, pooling 19/19 |
| `build/rk3588-live-verify/P2-SUMMARY.md` | P2 live evidence: ew-fp16 54/54 complete-BO exact (last family gap), determinism 5/5 across lock windows, class-D boundary probes |
| `build/rk3588-live-verify/FDIV-RESIDUAL.md` | FDIV differential closure: 1,452/1,452 captured lanes live-verified |
| `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit` | emitted EW image: WNS +0.670, 6,157 LUTs, SHA `b373ee70…f59a`, admission REVIEW_PENDING (human reviewer) |
| `docs/BOARD_SESSION_RUNBOOK.md` | operator runbook for the FPGA session (both emitted images, load/replay/acceptance/rollback, no-flash rules) |
| `tools/host/run_jtag_ew_hardware.py` + `tests/host/test_run_jtag_ew_hardware.py` | pinned fail-closed EW-image replay harness (9-case raw-BO replay 872,448 B, E1 negative) + 13 offline tests; dry-run receipts in build/board-prep/ |
| `docs/HOST_SHARED_LOCK.md` | cooperative shared-lock/gate protocol for the shared laptop (one lock, sustained-cool gate, FIFO) |
| `build/host-jtag/verilator-1794255585420701915/report.json`, `build/iverilog/report.json` | EW-image qualification evidence (current tree, source-bound) |
| `docs/EW_APERTURE_AUDIT.md` | EW aperture audit PASS: 54/54 ew-fp16 + 8/8 fdiv-systematic fit the sparse six-bank layout; 1 MiB decode safe |
| `fpga/ypcb_merged_top.sv` + `fpga/merged/` + `tools/merged/` + `tests/merged/` | merged-image S0/S1 scaffolding: top skeleton, build template, renderer/`--check`, mailbox→AXI scaffold bench, address-map + EW aperture contract (35 offline tests) |
| `docs/MERGED_INTEGRATION_NOTES.md` | merged-image S0-S5 integration plan, attach points, ambiguities, build-window items |
| `docs/CONV_RUNTIME_ENGINE.md` + `build/runtime-conv-lab/` | runtime-decoded conv engine design, evidence map, decoder unit 13/13 PASS, front-fix history (#1-#9), **leg A 3/3 PASS + leg B 51/51 controls PASS** (ledgers `LEG_A_PRIMARY_RECEIPTS.md`, `LEG_B_CONTROLS_RECEIPTS.md`); area estimate pending |
| `docs/CONV_PAGE_SCALING.md` | front weight-store scaling, timing rounds 1-3, and the adopted cell-pipeline result |
| `docs/CONV_SIMPLE_FIXTURES.md` | frozen vs rejected conv-simple captures |
| `docs/CONV_GEMM_VENDOR_FIXTURES.md` | frozen vs rejected vendor/GEMM captures |
| `docs/PPU_Q16_AVERAGE.md` | Q16 average candidate semantics |
| `docs/PROGRESS_TABLE.md` | long-form status, per-family notes, remaining-work table |

## 14. Phase log (chronological; superseded by §16 for current state)

These are the dated snapshots that produced §16. Keep them for history and for
the receipt names they cite; **do not treat any of them as current state.**

- 2026-11-10: two-image split adopted (D1). Image A = runtime conv engine +
  GEMM (~176k LUTs), Image B = pooling band + EW/ew-int (~120k LUTs). Merged
  single image rejected (engine alone 17,858 LUTs over the 150k ceiling).
- 2026-11-11: runtime engine **LEG A GREEN 3/3** on the parameterised C16xK16
  construction (receipts `iverilog-20261110T171049Z`, `T171818Z`, `T172423Z`;
  written BOs identical to the frozen captures, complete memory image equal,
  source hashes before==after). Leg B 51/51.
- 2026-11-11: **Image A S1 attach complete** — real `rk_conv_runtime_page_axi`
  replaces the ABI stub, two-master memory arbiter, page contract PASS (54/54
  captured QWORDs), scaffold bench PASS on 4/4 SLVERR holes, six RTL defects
  fixed. Receipt `build/verif/S1_ATTACH_SUMMARY.md`.
- 2026-11-11: **Image A S2 attach complete** — real `rk_cmac_gemm_axi`.
  Receipt `build/verif/S2_ATTACH_SUMMARY.md`.
- 2026-11-11: **Image A BUILD + EMIT** — 172,923 LUTs, sys_clk WNS +1.525 ns,
  bitstream `5b03e738...`. Receipt
  `build/merged-image/image-a-20261111T022739Z/BUILD_CLOSEOUT.md`.
- 2026-11-11: **Image B S3 attach complete** — real 19 x 4 KiB pooling band
  behind `rtl/ppu/rk_ppu_pool_band_axi.sv`. Receipt
  `build/verif/S3_POOL_BAND_SUMMARY.md`.
- 2026-11-11: **Image B S4 attach complete** — real `rk_ew_axi` page plus the
  new six-bank `rtl/rk_ew_aperture.sv`; all six pages real. Receipt
  `build/verif/S4_EW_PAGES_SUMMARY.md`.
- 2026-11-11: **Image B build: timing FAIL** at sys_clk -92.008 ns; pooling leaf
  isolated; freeze exception #1 filed. Receipt
  `build/merged-image/IMAGE_B_TIMING_FAILURE_20261111.md`.
- 2026-11-12: **Image B leaf fix landed** (400,012-value equivalence, 19/19
  dual-sim) and the rebuild was **aborted by the thermal guard** because it was
  launched without `BENCH_HOLD_FOREIGN=1`. Receipt
  `build/merged-image/IMAGE_B_ABORT_FOREIGN_HOLD_20261112.md`.
- Historical note: the pre-parameterisation construction was also leg-A 3/3 and
  leg-B 51/51, D1 area 167,858 LUTs. Superseded by the hash-bound reruns above.
- Verification standing totals: vendor 16/16; dual modes 0-8 9/9; 270 contracts
  green; mailbox mode 0; mailbox modes 1-2 blocked-by-host-hardware.

## 15. The three documents that explain Image B precisely

Read these before touching Image B; they contain the measured paths, the
decision record and the abort reason:

- `build/merged-image/IMAGE_B_TIMING_FAILURE_20261111.md` — the 816-level
  combinational path, per-domain timing tables, and the remediation scope.
- `build/verif/freeze-exceptions/FREEZE_EXCEPTION_001_global_avg_leaf.md` —
  what was authorised to change, why, and the full evidence chain.
- `build/merged-image/IMAGE_B_ABORT_FOREIGN_HOLD_20261112.md` — why the last
  build died, and the exact reproducer for the fix.

---

## 16. CURRENT STATE AND THE EXACT NEXT ACTION (2026-11-12)

### 16.1 Where the repository stands

```
branch: main
HEAD:   39c6957  "docs: port bundle now travels as a git commit, not a zip"
ahead:  31 commits of origin/main   (origin/main = 6aa8e7a, 2026-11-06)
tree:   clean (0 dirty entries)
```

**Nothing has been pushed.** Everything needed is in the local commits. To
continue on the new machine:

```sh
# on the OLD machine (if still available):
cd ~/rknpu-fpga && git push origin main
# or without GitHub:
git bundle create ~/rknpu.bundle main

# on the NEW machine:
git clone https://github.com/allbilly/rknpu-fpga
# or: git clone ~/rknpu.bundle rknpu-fpga
```

`.gitignore` tracks exactly two things under `build/`:

- `build/rk3588-example-captures/` — 803 frozen capture fixtures. Every replay
  runner reads this path and **102 tools hardcode it**, so it cannot be moved
  without editing all of them.
- `build/merged-image/image-a-emit-20261111T041526Z/host-merged.bit` — the
  deliverable. The repo already tracks emitted bitstreams
  (`build/framework-factored-sys-reset-v1/emission/full512-sys-reset.bit`), so this
  follows existing convention rather than inventing a new one.

Everything else under `build/` is 197 GB of regenerable output (`.dcp` 40 GB,
`.vvp` 15 GB, object files, multi-GB `packed.json` dumps). It is **not** in git and
you do **not** need it — it reappears when you rebuild. `.Xil/` (Vivado scratch,
2.6 GB) and `verification/` (4.7 GB of historical evidence tarballs) are excluded
too.

### 16.2 Image A — DONE, ready to load

| | |
|---|---|
| Bitstream | `build/merged-image/image-a-emit-20261111T041526Z/host-merged.bit` |
| Size | 18,735,212 B |
| SHA-256 | `5b03e7388ea0d0a95462dcd7d9279277c6264085d8a801f484ea928a12ac2bfb` |
| USR_ACCESS | `396e6429` |
| Programmed? | **No** (`programmed=false`, `hardware_accessed=false`) |
| Pages | `rk_conv_runtime_page_axi` @ `0x1_0000`, `rk_cmac_gemm_axi` @ `0x1_1000`, shared 64 KiB window @ `0x0` |
| Memory arbitration | 3-master (host > conv > gemm), one outstanding response, owner latched |
| LUTs | 172,923 implemented (57.91 % of 298,600) |
| Registers / BRAM | 44,446 (7.44 %) / 28 (2.93 %) |
| **sys_clk timing** | **WNS +1.525 ns, WHS +0.062 ns, 0 failing endpoints** |
| jtag_tck timing | WNS +158.030 ns, WHS +0.084 ns |
| Constraints | 0 no-clock pins, 0 unconstrained internal endpoints, "All user specified timing constraints are met" |
| DRC | warnings only (20× `REQP-1839` RAMB36 async-control, `DPREG-4`); no errors |

**Read `timing.rpt` per clock domain.** The file holds one table per clock. The
+158.030 ns figure is the `jtag_tck` domain; the number that matters for datapath
closure is `sys_clk` **+1.525 ns**. Taking the first `Setup :` line in the file
gives the wrong domain — that mistake was made once here and had to be corrected
in the docs.

Re-emitting from an existing routed checkpoint costs ~15 min, not ~2 h, because
`fpga/merged/emit_routed.tcl` is an emission-only pass over `routed.dcp`.

### 16.3 Image B — pages attached and DRC clean, but NOT yet built clean

All six pages are real modules:

| slot | window | module |
|---|---|---|
| `memory` | `0x0000_0000` | `rk_bram` + halfword AXI bridge |
| `pool_band_page` | `0x0001_0000..0x0002_2fff` | `rk_ppu_pool_band_axi` (19 x 4 KiB corpus pages) |
| `ew_page` | `0x0002_3000` | `rk_ew_axi` |
| `ew_aperture_page` | `0x1000_0000` (1 MiB decoded) | `rk_ew_aperture` (six banks, 100 KiB) |
| `ew_int_page` | `0x0002_4000` | `rk_ew_int_page_axi` |
| `ew_int_aperture_page` | `0x1100_0000` (1 MiB decoded) | `rk_ew_int_aperture` |

New RTL added in this phase: `rtl/ppu/rk_ppu_pool_band_axi.sv` (band wrapper:
per-page selection + 19-to-1 memory arbitration) and `rtl/rk_ew_aperture.sv`
(six physical banks A/B/D/scratch/command/task = 100 KiB, every other decoded
address an explicit hole; host staging refused with SLVERR while the page is busy).

Profile state: `--profile image-b check` gives `VERIFIED_RENDER_ONLY`.
Merged offline suite: **79/79**.
Image-B replay `--mode full` now reports **`HEAVY_WINDOW_REQUIRED`** — the
missing-page refusal is gone; only the heavy-window gate remains.

#### The timing defect that was found and fixed

Image B routed with **DRC clean (0 violations)** but **failed sys_clk timing**:

```
WNS -92.008 ns, TNS -48,615 ns, 10,682 failing endpoints of 113,012
worst path: pool_band_page/g_page_inst[0].pool_page/engine/
            input_atom_q_reg[27]_replica -> corpus/g_case_0.leaf/out_atom_q_reg[20]
Data Path Delay 111.685 ns (logic 59.062, route 52.623), Requirement 20.000 ns
Logic Levels 816 (CARRY4 = 745)
```

Root cause: `fp16_mean15()` in the **frozen** leaf
`rtl/ppu/rk_ppu_pool_avg_global3x5_c8_fp16_capture.sv` evaluated, combinationally
between two registers, three 64-bit `/ 15` and `% 15` operations **and a
variable-divisor 64-bit divide** `numerator / (15 << shift_amount)`. That is a
~5.6x overrun of the period. The pooling RTL had only ever been synthesised and
OOC-fit, never routed and timed, so it had never been visible.

**Freeze exception #1 (Lead-approved) was granted and applied.** The
variable-divisor divide was removed *by algebra*: with `total = 15*F + R`,
`shift = highest - 10`, `den = 15 << shift`, the quotient/remainder of
`total/den` are exactly `Q = F >> shift` and `rem = 15*M + R` with
`M = F & (2^shift - 1)`. Only a divide by the **constant 15** remains (it
synthesises to a multiply-high), evaluated in separate clock cycles. The
`highest < 10` branch is the same formula with `shift = 0`. **No arithmetic,
rounding, special-case or output value changed.**

Evidence, all re-run after the change:

| check | result |
|---|---|
| Formula equivalence, old vs new, 400,012 values (boundaries + random) | **0 mismatches** |
| `tools/ppu/run_pool_avg_global3x5.py` Icarus / Verilator | **PASS / PASS**, complete 4096-byte BO exact |
| `tools/ppu/run_pool_corpus.py --simulator both`, 19 cases | **PASS / PASS**, 19/19 each, 0 mismatches per case |
| `tests/ppu_pooling` | **129/129 OK** |
| Frozen manifest | **517/518** — only the authorised leaf changed |
| New leaf SHA-256 | `d9cc41a239c764e98df117ce30b1776a7323949e22d9ff72ab9588f0bf6a3e5f` |

### 16.4 THE EXACT NEXT ACTION

**Rebuild Image B with the foreign-hold enabled, then verify the gate properly.**
Everything needed is committed and verified; this is build-and-verify, not design.

```sh
cd ~/rknpu-fpga

# 1. render to obtain the source-hash the build gate requires
python3 tools/merged/vivado_merged_image.py render --profile image-b \
  --out build/merged-image/image-b-render
SHA=$(python3 -c "import json;print(json.load(open('build/merged-image/image-b-render/inputs.json'))['source_manifest_sha256'])")

# 2. build. BENCH_HOLD_FOREIGN=1 is THE lesson from the last abort (see §16.6).
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BENCH_HOLD_FOREIGN=1 BENCH_CPU_QUOTA=200 BENCH_CPUS=4-7 \
RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_CONFIG_VOLTAGE=1.8 RK_CFGBVS=GND \
RK_LED_ACTIVE_LOW=0 RK_MERGED_SOURCE_SHA=$SHA \
  build/verif/host_guard/safe_run.sh python3 tools/merged/vivado_merged_image.py \
  synth --execute --profile image-b --out build/merged-image/image-b-$STAMP
```

The quota/cpuset above suits a real workstation. The old laptop was pinned to
`BENCH_CPU_QUOTA=50 BENCH_CPUS=0-1` purely because of its degraded cooling — that
limit is **not** a design requirement.

Then verify with the authoritative section, never the first `Setup :` line:

```sh
D=build/merged-image/image-b-<stamp>/implementation
grep -A6 "Design Timing Summary" $D/timing.rpt    # sys_clk WNS must be >= 0
grep -c "Slack (VIOLATED)" $D/timing.rpt          # must be 0
grep -c "Combinatorial Loop Alert" $D/drc.rpt     # must be 0   (LUTLP-1)
grep -c "All user specified timing constraints are met" $D/timing.rpt   # must be 1
```

If it closes, emit the bitstream (§8 has the emission command) and Image B joins
Image A as a loadable candidate. If it does **not** close, the remaining leverage
is pipelining the other pooling leaves' adders — identify which leaves the failing
paths land in and record it honestly. Do **not** relax the 20 ns clock or waive DRC.

### 16.5 Secondary work

- **Image B replays.** `--mode full` needs a heavy window (the ewint page replay is
  ~2 min Verilator, ~10 min Icarus single-core). Run it while the build is going.
- **Hardware session.** Image A `5b03e738...` is a valid candidate now. It needs
  the DLC10 cable attached (`lsusb -d 03fd:` is the check) plus explicit
  authorisation for one volatile load. Procedure: `docs/BOARD_RUN_PREP.md`; harness:
  `tools/host/run_jtag_dual_hardware.py`. **Never flash.**
- **Other candidate bitstreams present on disk** (under `build/`, therefore NOT in
  git; copy them separately if wanted):
  - six-page image `81eef4cdcf97c3c86f34b4bce64ba3f436c4da22982950ea11e4b31fff674d39`
    at `build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit`
  - EW image `b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a`
    at `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit`

### 16.6 Five mistakes already made — do not repeat them

1. **Launching a build without `BENCH_HOLD_FOREIGN=1`.** Ungoverned foreign
   Verilator/pytest work then shares the host, combined heat exceeds the cooling,
   and the guard kills the build (and the foreign job) at a median ~97 degC. The
   matcher in `build/verif/host_guard/foreign_hold.sh` already covers
   `*vortex/tinygpu*`, `*hw/unittest/*`, `*ladder*`, `*rv32*` and friends —
   **enable it rather than extending it.** `safe_run.sh:26` reads that variable.
2. **Reading the wrong `Setup :` table in `timing.rpt`.** One table per clock
   domain. Use the `Design Timing Summary` section. The build templates were fixed
   to do exactly this; if you write your own gate, do the same.
3. **`get_timing_paths -max_paths 1` + `get_property SLACK`** returns the
   *generic pin slack*, not the path slack, and returns a single object rather than
   a list (so a naive `foreach` walks fields). It once reported -90 ns on a design
   that was +152 ns in the jtag_tck domain. Use `report_timing_summary`.
4. **Re-including a whole `build/` subtree in `.gitignore`.** `!/build/merged-image/`
   dragged 1.7 GB of `.dcp`/`.vvp` probe output into the commit. Scope the rules to
   exact paths, and remember git will not descend into an excluded parent — every
   level must be re-opened.
5. **A `**/*.tar.gz` pattern silently matches nothing.** `/verification/runs/**/*.tar.gz`
   matched zero files (a `**/` needs an intervening directory), so 1.45 GB of
   historical evidence archives were queued for commit. The rule is now `*.tar.gz`.

### 16.7 Tooling notes from the old machine

The old laptop was **cooling-bound, not compute-bound**: idle-degraded cooling sat
at 84-99 degC with 98 % idle CPU, ~1 core sustained killed it within 20-30 min,
sensor swings of +/-15 degC were normal, and the fan was healthy (0 rpm at idle
~52 degC, 1800-3600 rpm under load). The new machine should not need any of this,
but the guard is still useful for long builds: `host_guard.py` (sustained kill at
median 97 degC, instant 104 degC, streak 2x >= 101 degC) and `safe_run.sh`
(battery gate, cool gate, CPU quota/cpuset, shared lock, optional foreign hold).
`/tmp/rknpu-heavy.lock` is a cooperative single-heavy-job lock shared with another
project on that host — keep using it if the new machine is shared.

Toolchain: **Vivado 2026.1**, part `xc7k480tffg1156-2`, 50 MHz / 20 ns. Icarus
13.0 and Verilator are the simulators; Icarus is usable but slow (~17 cycles/s on
the full merged top, hence the page-level replays).

### 16.8 Verification totals (all source-matched)

Frozen manifest **517/518** (only the authorised leaf changed); merged offline
suite **79/79**; vendor 16/16; dual modes 0-8 9/9; P1 38/38; P2 ew-fp16 54/54 +
determinism 5/5; FDIV 1,452/1,452; pooling 19/19 dual-sim; ew-int 15/15 dual-sim;
runtime leg A 3/3 + leg B 51/51; page contract 54/54 captured QWORDs; Image A
0 timing violations with constraints met.

Superseded figure: **518/518** appears throughout older documents. It is now
**517/518** because freeze exception #1 authorised exactly one file to change.
