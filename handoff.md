# Handoff — running the RK3588 examples on the K8 FPGA

Last updated: **2026-11-10**
Audience: the next coding agent picking up the work.

## 0. State in one paragraph

The design has a six-page AXI image (`ypcb_dual_endpoint_top`) and a pin-free
USER2 mailbox wrapper (`ypcb_jtag_dual_top`). All four frozen conv-simple
profiles, pooling, and all four GEMM shapes have RTL pages. **The six-page
image now closes the 20 ns gate and emits a bitstream:**
`build/jtag-dual-image/20261109T160627Z`, Vivado 2026.1, status PASS, WNS
**+3.952 ns**, TNS 0, WHS +0.054 ns, 0 failing endpoints, 231,316 LUTs
(77.47%), 19.5 BRAM tiles, 331,098 routed nets with 0 errors, DRC warnings
only, bitstream SHA-256
`81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39`. That
closes the timing blocker by pipelining `rk_cmac_fp16_cell` into three
registered legs and giving the array a matching elastic valid/tag pipe; the
CACC chain and every page/transport contract are unchanged. The vendor-core
Icarus compile regression is fixed, and `tools/conv/run_conv_simple_axi.py` now
records source hashes. The replay matrix on the frozen tree is being refreshed
(see §7 for what is already PASS). **Nothing has ever been programmed or
observed on a board**; every receipt says `hardware_accessed=false`, and the
DLC10 JTAG cable is currently not attached to this machine. A read-only hardware
harness plus the audited programming procedure are prepared in
`docs/BOARD_RUN_PREP.md` and `tools/host/run_jtag_dual_hardware.py`.

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

1. Finish the frozen-tree replay matrix (§7): dual modes 0-8, mailbox modes 0-6,
   four conv-simple profiles (both sims), eight vendor profiles (both sims), and
   the contract suites. Cite only source-matched PASS receipts.
2. After the matrix: mark the image ready in `docs/BOARD_RUN_PREP.md`, re-run
   the harness's offline `--check` against
   `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` for
   modes 0-6, and re-run `tools/host/jtag_preflight.py`.
3. Ask the user for the hardware session (cable attached + explicit
   authorization for a volatile JTAG load + audited target).
4. With authorization, and only then: preflight -> DLC10 cable init -> read-only
   target audit -> volatile load of the exact image -> `python3
   tools/host/run_jtag_dual_hardware.py --authorized ...` modes 1-6 (mode 0
   last, it deliberately quarantines the mailbox) -> capture the receipts.
   Never flash.
5. Compare the read-back on hardware against the frozen fixtures. A hardware
   PASS binds the exact image hash and that session's target identity only.
6. Future increments (not required for the current objective): the conv
   corpus direction is now a **runtime-decoded conv engine** (user choice,
   2026-11-10; task-13, `docs/CONV_RUNTIME_ENGINE.md`) that decodes geometry
   from the per-task command stream and can replace the four per-profile conv
   pages; staged prototype/equivalence/area work runs under
   `rtl/cmac/experimental/runtime/`. The archived option-B shared-array work
   (`build/timing-lab-share/`) stays as a fallback. The BY_K/multitask capture
   work stays blocked on UAPI/bundle evidence (§10).
7. When a six-page bitstream has been emitted and (later) hardware-tested,
   keep `progress.md` and this handoff in sync; superseded receipts stay as
   history, never as evidence for changed RTL.

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

## 14. 2026-11-11 status snapshot (for a fresh session)

- Two-image split adopted (D1): Image A = runtime conv engine + GEMM
  (~176k LUTs), Image B = pooling band + EW/ew-int (~120k LUTs). Merged
  single image rejected (engine alone 17.8k over the 150k ceiling).
- Runtime engine: **LEG A GREEN 3/3 on the parameterised C16xK16 construction**
  (2026-11-11; receipts iverilog-20261110T171049Z / T171818Z / T172423Z, written
  BOs identical to the frozen captures, complete memory image equal, source
  hashes before==after). The earlier "verified on the pre-parameterisation
  construction" note is superseded by this hash-bound rerun.
- Old note kept for history: verified on the pre-parameterisation construction
  (leg A 3/3, leg B 51/51); D1 area 167,858 LUTs; parameterised re-run
  blocked by harness width/layout fixes (instructions issued), no logic
  finding.
- Image B: pooling fit measured 110,107 LUTs; ew-int page/aperture integrated
  and current-file evidenced; S3/S4 plan PLAN_READY. Image A: scaffold + ABI
  bench + replay plan ready; real page wrapper pending conveng green.
- Verification: FINAL-freeze 518/518; vendor 16/16; dual 0-8 (9/9); mailbox
  mode 0; 270 contracts green; mailbox 1-2 blocked-by-host-hardware.
- Hardware session: DLC10 cable absent; harnesses + runbook pinned offline.
  Two emitted images remain the load candidates: six-page `81eef4cd...`
  and EW `b373ee70...`.
- Cooling is the binding constraint: keep one heavy job at a time through
  `build/verif/host_guard/safe_run.sh`, stage long builds (synth then impl),
  and never retry into heat.


- **Image A S1 attach COMPLETE** (2026-11-11): real `rk_conv_runtime_page_axi`
  in place of the ABI stub + two-master memory arbiter; page contract PASS
  (54/54 captured QWORDs), scaffold bench PASS on 4/4 SLVERR holes, merged suite
  79/79, render `VERIFIED_RENDER_ONLY`, replay `full` = `WRAPPER_ATTACHED`.
  Six RTL defects fixed. Receipt `build/verif/S1_ATTACH_SUMMARY.md`.


## 15. State as of 2026-11-11 23:05 HKT (two-image era, post-build)

**Image A — BUILT, TIMING-CLEAN, BITSTREAM EMITTED.**
- Both real engines attached: `rk_conv_runtime_page_axi` (0x1_0000, S1) and
  `rk_cmac_gemm_axi` (0x1_1000, S2), behind a **three-master** shared-memory
  arbiter (host > conv > gemm).
- Build: **172,923 implemented LUTs (57.91 %)**, 44,446 regs, 28 BRAM.
- Timing (`timing.rpt`, per-clock tables — read them per domain):
  **sys_clk WNS +1.525 ns / WHS +0.062 ns, 0 failing endpoints**;
  jtag_tck WNS +158.030 ns / WHS +0.084 ns. 0 no-clock pins,
  0 unconstrained endpoints. 0 timing violations. DRC warnings only.
- Bitstream `build/merged-image/image-a-emit-20261111T041526Z/host-merged.bit`
  **18,735,212 B, SHA-256 `5b03e7388ea0d0a95462dcd7d9279277c6264085d8a801f484ea928a12ac2bfb`**,
  USR_ACCESS `396e6429`. Emitted from the routed checkpoint via
  `fpga/merged/emit_routed.tcl` (same reviewed emission gates). **NOT programmed.**

**Image B — pages attached, BUILD FAILS ON TIMING (real RTL limit).**
- All six pages are real: pool band (19 x 4 KiB, S3), ew page (`rk_ew_axi`, S4),
  ew aperture (`rtl/rk_ew_aperture.sv`, new six-bank 100 KiB, S4), ew-int page +
  aperture. Merged suite 79/79.
- Build: 115,172 synth / 114,609 implemented LUTs (38.4 %), 45 BRAM,
  **DRC clean (0 violations)**, routed (108 MB checkpoint), 0 no-clock /
  unconstrained.
- **Timing FAILS: sys_clk WNS −92.008 ns, TNS −48,615 ns, 10,682 failing
  endpoints.** Worst path is inside one frozen pooling leaf: 816 logic levels
  (745 CARRY4) with 111.7 ns delay in a 20 ns cycle — the FP16-average adder
  trees were never pipelined, and the pooling RTL had only ever been
  synthesised/OOC-fit, never routed+timed.
- Fix path needs RTL work on **frozen** leaf files (pipeline/serialise the adder
  tree) with a freeze exception, or a slower clock domain for the band. Not a
  gate to relax.

**Two template defects fixed this round** (both in `fpga/merged/` and
`fpga/image_b/`): the worst-slack gate read `get_property SLACK` off
`get_timing_paths -max_paths 1` (generic pin slack, reported −90 ns on a clean
design) and could pick the wrong clock domain. It now anchors on the
**Design Timing Summary** section and reads the correct column per delay type.

**Host**: fan is healthy (0 rpm at idle ~52 °C, spins to 1800-3600 rpm on load);
8 cores at `performance` governor boosting to ~4.2 GHz. No reboot needed. The
guard kills CPU-active processes at median 97 °C and kills foreign unguarded
jobs too; that is what aborted two builds.

**Hardware session**: still blocked only on the **DLC10 cable + explicit
authorization**. Image A `5b03e738…` is the first timing-clean, gate-clean
candidate for a volatile load.

**Verification totals**: frozen manifest 518/518, merged offline suite 79/79,
vendor 16/16, dual 0-8 9/9, P1 38/38, P2 ew-fp16 54/54 + determinism 5/5,
FDIV 1,452/1,452, pooling 19/19 dual-sim, ew-int 15/15 dual-sim, runtime leg A
3/3 + leg B 51/51, page contract 54/54 captured QWORDs.
