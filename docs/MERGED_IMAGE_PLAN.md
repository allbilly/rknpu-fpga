# Merged single-image plan: runtime conv engine + pooling + GEMM + EW + USER2 transport

Status: **design/plan (task-15), no RTL changed, no build run.** This document sizes
and stages the single host-drivable image the user asked about ("why not merge
them"). It is written so integration can start the moment the runtime conv engine
(task-13, `docs/CONV_RUNTIME_ENGINE.md`) is equivalence-proven and area-measured.
Two inputs are still pending and are marked **[PENDING]** below. Nothing in this
plan is claimed as measured until its receipt exists.

## 1. Short answer to "why not merge them" (today)

Because it does not fit and does not route. The adopted six-page image is
**231,316 LUTs in 70,434 of 74,650 slices (94.35 %)** — see
`build/jtag-dual-image/20261109T160627Z/implementation/utilization.rpt`. Adding the
EW endpoint (6,157 LUTs + memory tiles) and a 19-fixture pooling corpus
(pre-synth estimate 30–55 k LUTs **[PENDING]**) would ask for roughly
**277 k LUTs ≈ 84 k slices against a 74,650-slice device**, i.e. more slices than
the part has. The four per-profile conv pages are the reason: they cost
~220 k LUTs for one job shape each.

The merge becomes feasible exactly when one runtime-decoded conv engine
(~105 k LUTs estimated, `docs/CONV_RUNTIME_ENGINE.md` §7) replaces those four
pages: the projected total drops to ~150–175 k LUTs (~50–57 k slices, ~67–76 %),
which leaves routing/timing headroom for the EW and pooling additions **and**
gives the conv-fp16 vendor family a page for the first time.

## 2. Component inventory and costs

Family coverage of the merged image, if every stage lands: conv-simple 4 profiles
(8 modes each), the 9 READY conv-fp16 vendor captures (today **no image page
exists** for them; the runtime engine covers them by construction), the 4 frozen
GEMM shapes, the 19 READY pooling fixtures, and the EW endpoint families
(`elementwise.py`, `simple_add.py`, `fdiv-systematic` — FDIV is already
end-to-end in the EW RTL today). That is the union currently split across the
adopted six-page image plus the separate EW image; no new family coverage is
invented here beyond what the runtime engine and pooling corpus tasks already
target.


All LUT/FF/BRAM numbers are "as placed" unless marked estimate. Per-page split is
from a hierarchical census of the routed six-page image build
`20261109T180000Z` (same page structure as the adopted build; the adopted build
adds the measured A-pipeline delta of +2,499 LUTs / +29,328 FFs, so the four conv
rows are quoted with that adjustment). Device: xc7k480tffg1156-2, 298,600 LUTs,
74,650 slices, 597,200 FFs, 955 BRAM tiles, 1,920 DSPs, 4 BSCANE2 sites, 20 ns
SYS_CLK.

| Component | LUTs | FFs | BRAM tiles | DSP | Status / provenance |
|---|---:|---:|---:|---:|---|
| conv profile 0 page (C4 3x3, `conv_page`) | ~40.4 k | ~6.4 k | 2 | 0 | measured 39,904 pre-A + A delta, adopted build |
| conv profile 3 page (C4 1x1 FP32, `conv_fp32_page`) | ~40.4 k | ~6.3 k | 1+1 RAMB18 | 0 | measured 39,770 pre-A + A delta |
| conv profile 1 page (C4 5x5, `conv_k5_page`) | ~40.4 k | ~6.4 k | 3 | 0 | measured 39,780 pre-A + A delta |
| conv profile 2 page (C16 3x3, `conv_c16_page`) | ~101 k | ~10.1 k | 5 | 0 | measured 100,283 pre-A + A delta |
| **four conv pages together** | **~222 k** | ~29 k | 11+1 | 0 | replaced by the runtime engine |
| runtime conv engine (one instance, C16 geometry) | **~105 k est.** | ~30–40 k est. | ~7 (front stores) | 0 | **[PENDING]** task-13 synth-only receipt; doc estimate; >150 k triggers the fallback split |
| pooling corpus (19 fixtures as 19 pages) | 30–55 k est. | — | ~19–38 est. | 0 | **[PENDING]** share's synth-only fit, `build/pooling-image/synth-20261109T211339Z`; current six-page image carries one pool page at 1,114 LUTs/44 LUTRAM/0 BRAM |
| GEMM page (`rk_cmac_gemm_axi`) | 6,016 | 6,791 | 0 | 6 | measured, hierarchical census |
| EW endpoint (`ypcb_jtag_ew_top` datapath) | 6,157 | 5,816 | **256 → ~25** with the sparse aperture of §3.5 | 1 | measured in `build/host-jtag-preparation/20261109T210015Z` (6,157 LUTs, 5,816 regs, 256 BRAM, WNS +0.670 ns); BRAM shrink proposed here |
| EW AXI4-Lite front-end adapter (new, §3.6) | ~0.3–0.6 k est. | ~0.5 k est. | 0 | 0 | new RTL needed to put EW behind the shared AXI bridge; equivalence-proven by replay |
| USER2 mailbox donor + AXI bridge | 1,798 (590 + 1,208) | 4,093 | 0 | 0 | measured; donor mailbox hash unchanged |
| shared memory bridge + startup + misc decode | ~0.65 k est. (106 measured bridge + 0.3–0.6 k new decoder/arbiter) | ~250 | 0 | 0 | measured bridge 106 LUTs; new unified decoder ~0.3–0.6 k est. |
| shared host memory window (32 KiB; 64 KiB variant +8 tiles) | 0 | 0 | 8 (16) | 0 | `rk_bram`; no LUT cost |
| **merged candidate total** | **~150–175 k** | ~80–100 k | **~60–90** | ~7 | estimate; to be replaced by the staged build |

Notes:
- The four conv pages are not a fit for a merged image at any placement effort;
  the runtime engine is the enabling item, not an optimisation.
- BRAM is not the constraint (955 tiles): the merged estimate uses <10 %.
- The EW 256-tile figure comes from implementing the full 1 MiB window as RAM;
  the captured BO layout only needs 100 KiB of physical storage (§3.5).

## 3. Unified architecture

### 3.1 Topology

```
SYS_CLK(AA28) -> IBUF/BUFG -> rk_startup_reset ---- sys_clk / reset_n
BSCANE2(USER2, chain 2) -> otpu_jtag_mailbox -> rk_jtag_axil_bridge -> AXI4-Lite
                                                                       |
                                              ypcb_merged_image_top <--+
                                                 |
   +-------------------+-------------------+---------------+------------------+
   | conv runtime page | pooling page(s)   | GEMM page     | EW page          |
   | (RKCV)            | (RKPP)            | (RKCM)        | (RKEW + aperture)|
   +-------------------+-------------------+---------------+------------------+
                                                 |
                                          shared host memory window (BRAM)
```

Two new tops, mirroring the existing pin-free pattern exactly
(`fpga/ypcb_jtag_dual_top.sv`):

- `ypcb_merged_image_top` — pin-free merge of the page logic (AXI4-Lite slave,
  32-bit byte addresses, same 4 KiB page granularity as
  `fpga/ypcb_dual_endpoint_top.sv`).
- `ypcb_jtag_merged_top` — only package pins are SYS_CLK AA28 (LVCMOS18) and the
  three LEDs P30/M30/N30 (LVCMOS18), matching the audited board file. The
  `u_mailbox`/`u_bscan` hierarchy names are preserved because
  `fpga/host/mailbox_cdc.tcl` constrains them by name.

Transport is the existing reviewed stack: USER2 mailbox frames ->
`rk_jtag_axil_bridge` -> AXI4-Lite (register reads/writes and 64-byte lines).
No DDR, PCIe, MMCM or hardware manager is introduced. All raw-command/BО traffic
keeps the "host writes exactly the frozen words the engine reads" contract.

### 3.2 Unified AXI4-Lite address map

4 KiB page granularity (existing `PAGE_SHIFT=12` decode). Proposed map:

| AXI byte range | Size | Function | Identity / notes |
|---|---:|---|---|
| `0x0000_0000..0x0000_ffff` | 64 KiB | **shared host memory window** | BO upload/readback for every family; existing six-page image uses 32 KiB, extended to 64 KiB here (§3.4) |
| `0x0001_0000..0x0001_0fff` | 4 KiB | **conv runtime page** | new RKCV page: command/status/error/IRQ, geometry is decoded from the raw command QWORDs (task-13) |
| `0x0001_1000..0x0001_1fff` | 4 KiB | **pooling page (runtime form)** | RKPP identity preserved; one page if a runtime pooling engine is available (see §2 fallback) |
| `0x0001_2000..0x0001_2fff` | 4 KiB | **GEMM page** | RKCM identity preserved |
| `0x0001_3000..0x0001_3fff` | 4 KiB | **EW control/status page** | RKEW identity: job submit/status/error/IRQ only; EW registers are fetched by its DMA from the raw command BO, as today |
| `0x0001_4000..0x0001_ffff` | — | unmapped | explicit SLVERR |
| `0x0002_0000..0x0002_2fff` | 19 × 4 KiB | **pooling corpus band (multi-instance form)** | one page per frozen pooling fixture (n = 0..18); used only if the corpus keeps 19 separate pages |
| `0x0002_3000..0x000f_ffff` | — | unmapped | explicit SLVERR (`rk_axil_error_slave` pattern), never a silent alias |
| `0x1000_0000..0x100f_ffff` | 1 MiB decoded | **EW memory aperture** | preserves captured device addresses (`0x10001000` A, `0x10020000` B, `0x10040000` D, `0x10060000` scratch, `0x100e0000` 64 KiB command BO, `0x100f0000` 16 KiB task BO); only ~100 KiB is physically mapped (§3.5); accesses outside the captured apertures are explicit errors |

Rationale for keeping `0x1000_0000`: the nine frozen EW production command BOs
contain absolute device addresses and are uploaded verbatim; the raw final
command words are the execution boundary, so the host may not rewrite those
addresses. A 1 MiB decode with sparse physical apertures keeps the frozen BOs
byte-identical while shrinking storage. (Measured layout: 6 regions, 100 KiB
owned data, span 972 KiB — identical across all nine cases;
`tools.dma_fixtures.production_cases()`.)

The conv/GEMM/pooling runners already patch their three declared BO addresses
from the manifest/BO bases (`register` words 18/24/32), so placing those base
addresses inside the 64 KiB window is a runner constant, not an RTL or
arithmetic change.

### 3.3 Page arbitration and one-job-at-a-time rules

Keep the reviewed mutual-exclusion pattern of `ypcb_dual_endpoint_top.sv`, but
with a single aggregate:

- `any_engine_busy = conv_busy | pool_busy | gemm_busy | ew_busy`.
- Every page's `memory_ready` and the **host memory window** are gated by
  `reset_n && !any_engine_busy && !host_mem_busy`; no second engine can start
  while one is busy, and the host cannot touch the window mid-job. This
  generalises today's per-page `*_memory_ready` terms and keeps the already
  proven cross-page exclusion contract.
- Submit registers are writable only in IDLE (`cmd_ready` gated on page idle and
  `!error`); a submit while busy is refused with the existing explicit error
  status, not ignored.
- Per-page error/status stays readable after a fault; the aggregate error gates
  new submits but does not alias pages together. Query/reset semantics mirror
  `rk_axil_mem_bridge`/page patterns already used.
- Unmapped addresses return SLVERR (`rk_axil_error_slave`); no page ever sees
  another page's traffic.

### 3.4 Shared memory window sizing and port allocation

- Window: `rk_bram` 64 KiB (16 RAMB36-class tiles) at `0x0000_0000`, one true
  dual-port tile set: port A = host (AXI bridge 64-byte line writes/reads),
  port B = engine DMA (halfword reads/writes). Same structure as the current
  32 KiB window, only deeper.
- Why 64 KiB: the largest captured operand sets are the C16 conv weight BO
  (4,608 halfwords = 9 KiB), the runtime engine input store (≤ 320 pixels ×
  32 lanes × 2 B = 20 KiB if kept in the window), EW's 100 KiB (kept in its own
  aperture instead), GEMM/pooling BOs ≤ 4 KiB each, and the 64 KiB command BO is
  EW-only. 64 KiB covers a full C16 conv job (weight + input + command/task +
  output) with margin; the EW 64 KiB command BO and 16 KiB task BO stay in the
  EW aperture so the shared window is not sized for them.
- Port allocation: word writes from the host bridge are 32-bit AXI beats; engine
  side stays 16-bit halfword with the existing `req_ready`/`rsp_valid` contract.
  The runtime engine keeps its own private single-port weight/input front stores
  (7 RAMB36 across the four current pages are replaced by one engine's ~7 tiles),
  exactly as `docs/CONV_RUNTIME_ENGINE.md` §7 expects.

### 3.5 EW sparse memory aperture (shrink 1 MiB decode -> 100 KiB physical)

Measured captured layout (all nine production EW cases identical):

| Captured region | Device address | Size |
|---|---|---:|
| operand A | `0x1000_1000` | 4 KiB |
| operand B | `0x1002_0000` | 4 KiB |
| operand D (output) | `0x1004_0000` | 4 KiB |
| scratch | `0x1006_0000` | 8 KiB |
| command BO | `0x100e_0000` | 64 KiB |
| task BO | `0x100f_0000` | 16 KiB |
| **total owned** | span 972 KiB | **100 KiB** |

Proposal: decode the full 1 MiB aperture (address match only) but map the six
non-overlapping ranges to six physical banks (4+4+4+8 KiB and 64+16 KiB
contiguous): **100 KiB = 25 RAMB36 tiles** instead of 256. Un-owned holes in the
aperture are never touched by the host or the DMA (the host uploads only owned BO
bytes); they must read as explicit errors, not aliases. A simple range-decode
index mapper (upper address bits select bank, lower 14 bits offset) implements
this without touching the BO words. This is an explicit **new RTL + equivalence
proof** item: the EW replay must show identical owned-BO bytes and identical
error behaviour for out-of-bank accesses. If a future capture uses a different
layout, the fallback is a spare aperture or the old 256-tile physical window
(BRAM has room: 955 tiles).

### 3.6 EW AXI4-Lite front end (new adapter)

The EW endpoint currently sits directly on the mailbox backend
(`mailbox -> rk_jtag_ew_bram`), not on an AXI4-Lite slave. The merged image uses
one transport (mailbox -> `rk_jtag_axil_bridge` -> AXI) for every family, so the
EW endpoint needs a small AXI4-Lite front end that:

- implements the `0x0001_3000` control page (submit descriptor address/amount,
  status, error code, IRQ pending/clear) with the same semantics as the current
  EW job control;
- turns AXI 64-byte line writes/reads on the EW aperture into the endpoint's
  existing 64-byte host-port transactions (the protocol is line-for-line
  compatible; the adapter buffers one 64-byte line and one response);
- enforces the existing memory-ownership window (`memory_ready` gating while a
  job is queued/busy/faulted) from §3.3.

Estimated cost ~0.3–0.6 k LUTs / ~0.5 k FFs. Equivalence evidence: the existing
EW host fixture runner, retargeted at the merged AXI slave, must reproduce the
complete owned-BO bytes (100 KiB per job) and every negative control
(unknown-register E1, refusal while busy, partial-transfer/poison behaviour).

### 3.7 CDC, reset, and build-gate topology

- One `sys_clk` 20 ns (AA28 through IBUF/BUFG), one USER2 TCK domain
  (BSCANE2 chain 2), `rk_startup_reset` (64-cycle hold) — unchanged from both
  current images.
- `fpga/host/mailbox_cdc.tcl` is reused **without change**; keep the exact
  `u_mailbox`/`u_bscan` hierarchy and `u_mailbox/held_reg*` synchronizer names so
  the reviewed constraints and `rk_host_cdc_audit` still bind. Any rename would
  require a new CDC review, so the wrapper preserves names.
- Build template: new `fpga/merged_image/build_merged.tcl.in` derived from
  `fpga/jtag_dual/build_jtag_dual.tcl.in` with the same unweakened gates:
  exactly one sys_clk at 20.000 ns, CONFIG_VOLTAGE/CFGBVS pair supplied only for
  emission, at least one inferred BRAM, exactly one BSCANE2 with `JTAG_CHAIN=2`,
  a page-presence `foreach` extended to the merged page list (runtime conv,
  pooling, GEMM, EW + aperture marker), full timing/DRC checks with no waivers,
  and before/after source-hash binding. The `synth.tcl` of the pooling-corpus
  image (`N_PAGES=19`) is the model if the pooling pages stay multi-instance.
- Pin budget unchanged: only AA28 + three LEDs; no new electrical facts.

## 4. Area/timing budget, risks, fallbacks

Slice math (adopted image: 231,316 LUTs -> 70,434 slices = 3.28 LUTs/slice at
high occupancy; lower-occupancy designs pack less aggressively, use 3.0–3.2):

| Scenario | LUTs | Est. slices | vs 74,650 | Verdict |
|---|---:|---:|---:|---|
| today's six-page image | 231,316 | 70,434 (measured) | 94.35 % | closes but no headroom |
| today + EW + 19 pooling pages (no runtime engine) | ~277 k | ~84–86 k | >100 % | **impossible** |
| merged, runtime conv ~105 k + pooling 30 k + GEMM + EW + transport | ~150 k | ~47–50 k | 63–67 % | feasible with headroom |
| merged, runtime conv ~105 k + pooling 55 k | ~175 k | ~55–58 k | 74–78 % | feasible, monitor timing |
| merged, runtime conv = 150 k (worst allowed) + pooling 55 k | ~220 k | ~69–73 k | 92–98 % | marginal; fallback split |

Timing risk sits in three places, in order:
1. **Runtime conv engine Fmax** — it is the largest single block; its own WNS
   must be measured in the merged context (it replaces four pages that each
   closed at 20 ns today; the CMAC/CACC arithmetic is unchanged).
2. **EW endpoint in a congested image** — standalone it closes at WNS +0.670 ns /
   WHS +0.053 ns with only 2 % LUTs; in the merged image it will share routing
   with a much larger conv engine. Its margin is real but thinner than the
   conv/GEMM pages; a dedicated pipeline stage in the AXI adapter / aperture
   decoder is the mitigation.
3. **Hold margin** — the adopted image already has WHS +0.054 ns (skew-dominated);
   adding 256->25 BRAM and a new clock-domain-adjacent adapter must not perturb
   the mailbox synchronizers. Re-run the same hold and CDC gates, no waiver.

Fallbacks, in order of preference:
- **F1 two-image split (recommended default):** Image A = merged conv runtime +
  GEMM (and pooling if it fits); Image B = the current EW image (already emitted:
  `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit`,
  SHA-256 `b373ee70…f59a`). Multi-image deployment already exists and is honest.
- **F2 merged conv+GEMM only, pooling separate:** if the pooling corpus fit
  exceeds the budget or the pooling runtime engine is not ready.
- **F3 merged without EW:** if the EW AXI front end / sparse aperture cannot be
  equivalence-proven in time, ship the merged conv+GEMM+pooling image and keep EW
  as its own image.
- **F4 runtime-engine split:** if the measured runtime engine exceeds ~150 k LUTs,
  follow `docs/CONV_RUNTIME_ENGINE.md` §7: split `FP16-atom` and `FP32-layout`
  paths sharing the same decoder/front storage, or keep two conv images.

## 5. Integration and verification plan

Staged, each stage gated and source-hashed; the adopted six-page image and its
receipt stay the reference until a stage passes every gate.

1. **S0 — runtime conv engine OOC measurement [PENDING task-13]:** synth+impl of
   the single engine; record LUT/FF/BRAM/WNS. Decision gate D1 (§6). No image
   change.
2. **S1 — conv runtime page proto:** one-page image (runtime engine + shared
   window + mailbox transport). Replay the four conv-simple profiles (8 modes
   each) and the nine conv-fp16 vendor profiles against the frozen expectations,
   complete BO compare, old-vs-new byte equality. Negative controls: unsupported
   geometry refused, padded-row stream refused, unmapped page SLVERR, submit while
   busy refused, fault persistence + recovery via reconfiguration.
3. **S2 — conv + GEMM merged:** add the GEMM page and its four frozen shapes
   (decode-driven, unchanged); replay + cross-page exclusion controls.
4. **S3 — + pooling:** add the pooling page(s) (runtime or 19-page corpus; depends
   on D2). Replay all 19 READY pooling fixtures with complete-BO comparison.
5. **S4 — + EW:** add the EW AXI front end + sparse 1 MiB aperture (§3.5/§3.6);
   replay the nine production EW fixtures (ADD/SUB/MUL task sets), repeat-SUB
   without reload, SRAM reconfiguration restart, unknown-register E1, plus the
   FDIV families through the same endpoint (FDIV is already end-to-end in the EW
   RTL: decoder `cfg_op=4` + field pair, engine op passthrough, ALU op 4; see
   `docs/FDIV.md` and the current EW image receipt). Compare the complete 100 KiB
   owned bytes, not a prefix.
6. **S5 — full merged candidate:** page-presence gate, 20 ns timing gate, DRC,
   CDC audit, route status, freshness manifest, bitstream emission with SHA-256,
   and a hardware candidate binding record. The most recent images are the
   templates: `build/jtag-dual-image/20261109T160627Z` (six-page, WNS +3.952 ns)
   and `build/host-jtag-preparation/20261109T210015Z` (EW, WNS +0.670 ns).
7. **Replay matrix extension:** extend `tests/test_dual_endpoint_contract.py`
   (page identities, decode, negative paths) for the merged map; parameterise
   `tools/dual/run_dual_endpoint.py` with an image profile and add a
   merged-image runner that drives every family through one mailbox/AXI transport;
   extend `tools/host/run_jtag_dual.py` modes for the merged page set. Keep the
   existing frozen expectations byte-for-byte; never edit an expected BO to get a
   green run.
8. **Evidence rules:** every receipt records source hashes before/after, tool
   versions, seeds and the exact commands; a source change mid-run fails the
   receipt. Old receipts are not forward-cited for new RTL.

## 6. Dependencies, placeholders, and decision points

**[PENDING] P1 — runtime conv engine measured area.** Source-of-truth receipt:
task-13 synth/impl (to be recorded under `build/` and summarised in
`docs/CONV_RUNTIME_ENGINE.md` §7). Needed before D1.

**[PENDING] P2 — pooling corpus synth fit.** Source-of-truth receipt:
`build/pooling-image/synth-20261109T211339Z/` (task-10, in progress). Needed before
D2. Pre-synth estimate: 19 pages, 30–55 k LUTs.

**[PENDING] P3 — merged-image build licence/thermal window.** The host heavy
queue is serialized and thermally gated; the staged builds (S1–S5) need scheduled
windows via `build/verif/host_guard/safe_run.sh` + `/tmp/rknpu-vivado.lock`.

Decisions:
- **D1 (Lead):** is the runtime conv engine ≤ ~110–115 k LUTs (preferred) and
  ≤ 150 k (hard ceiling)? If not, fall back to F4 before any merged build.
- **D2 (Lead):** pooling corpus fit — 19 pages, runtime pooling engine, or keep
  pooling in a separate image (F2).
- **D3 (Lead):** accept the new EW AXI front end + sparse aperture RTL (with
  byte-exact equivalence proof) as part of the merged image, or keep EW as its own
  image (F3) for the first merged release.
- **D4 (User/Lead):** deployment policy — once the merged image passes S5 and the
  frozen replay matrix, does it become the *preferred* single image (with
  multi-image kept as fallback), or do we keep per-family images indefinitely?
- **D5 (User):** hardware binding of any new bitstream remains a separately
  authorized volatile load; nothing in this plan programs or flashes the card.

## Appendix A — data provenance for this plan

| Number | Source |
|---|---|
| six-page image totals 231,316 LUTs / 71,058 FF / 19.5 BRAM / 6 DSP / 94.35 % slices; WNS +3.952 ns | `build/jtag-dual-image/20261109T160627Z/implementation/utilization.rpt`, `timing.rpt` |
| per-page split (conv 100,283 / 39,770 / 39,780 / 39,904; GEMM 6,016 / 6 DSP; pool 1,114; bridge 1,208; mailbox 590; memory bridge 106; startup 23) | hierarchical census of routed `build/jtag-dual-image/20261109T180000Z` (pre-A page structure; adopted build adds +2,499 LUT / +29,328 FF) |
| A-pipeline delta +2,499 LUTs / +29,328 FFs | adopted vs 180000Z totals |
| device resources 298,600 LUTs / 74,650 slices / 597,200 FF / 955 BRAM / 1,920 DSP | `utilization.rpt` (Available columns) |
| EW endpoint 6,157 LUTs / 5,816 FF / 256 BRAM / 1 DSP / WNS +0.670 / WHS +0.053 / 10,829 routed nets | `build/host-jtag-preparation/20261109T210015Z/implementation/utilization.rpt`, `timing.rpt` |
| EW captured BO layout: 6 regions, 100 KiB owned over 972 KiB span, identical in 9/9 production cases | `tools.dma_fixtures.production_cases()` (frozen captures) |
| runtime engine ~105 k LUTs estimate and >150 k fallback | `docs/CONV_RUNTIME_ENGINE.md` §7 |
| pooling corpus 19 fixtures / 30–55 k pre-synth | task-10 design notes; drift check pending `build/pooling-image/synth-20261109T211339Z` |
| six-page address map / page arbitration / page-presence gate pattern | `fpga/ypcb_dual_endpoint_top.sv`, `fpga/ypcb_jtag_dual_top.sv`, `fpga/jtag_dual/build_jtag_dual.tcl.in` |
| EW transport and mailbox CDC constraints | `fpga/host/ypcb_jtag_ew_top.sv`, `rtl/host/rk_jtag_ew_bram.sv`, `fpga/host/mailbox_cdc.tcl` |


## Lead decisions on D1-D5 (adopted 2026-11-10)

- **D1 (runtime engine area):** preferred target **<= ~115k LUTs**; hard ceiling
  **150k LUTs**. Above 150k the merged single-image plan is not attempted; fall
  back to the F1/F2 split ladder first.
- **D2 (pooling corpus fit):** decided by the measured whole-image synth number
  (share's rerun at corrected quota). Target <= 55k LUTs to stay in the merged
  candidate; higher values trigger F1 (two-image split) or a reduced pooling
  page set, explicitly documented.
- **D3 (EW integration):** the **first merged release keeps EW as a separate
  image** (fallback F1 default) — do not add the new EW AXI front end / sparse
  aperture until the merged conv+pooling+GEMM image passes its gates and
  replays. EW integration is a second iteration with its own equivalence proof.
- **D4 (deployment policy):** once the merged image passes byte-exact replays
  for every included family and closes timing/DRC, it becomes the **preferred
  single image**; the per-family images (six-page `81eef4…`, EW `b373ee70…`,
  pooling corpus when emitted) remain documented fallbacks, not deleted.
- **D5 (hardware):** any FPGA load remains exactly as before — separate explicit
  authorization, audited board identity, volatile load only, never flash.
  Passing the merged image's gates/SHA is evidence, not authorization.



## D1/D4 update — measured runtime-engine area and split decision (2026-11-11)

Parameterised experimental runtime engine (C16xK16, additive copies, explicit
SDP-BRAM stores) OOC synthesis receipt
`build/runtime-conv-lab/area/ooc-20261110T131218Z`:

- **167,858 LUTs (56.2 %), 29,664 FFs, 12 BRAM, 15 DSP** (vs 334,991 LUTs / 112 %
  for the 32-lane prototype; -49.9 % LUTs).
- Breakdown: CMAC+CACC 143,295; front 9,813 (weight-store fix); decoder 2,046;
  arbiter 24; remaining ~12k frame stage + output stages.
- Frozen production files untouched; engine lives in additive experimental
  copies; frozen manifest 518/518.

**Decision (D1/D4 revised):** the merged single-image plan is **not adopted** —
the engine alone is 17,858 LUTs over the 150k single-image ceiling and a merged
candidate would exceed the slice/congestion envelope of the adopted 231k/94.35 %
image. Adopt the **two-image split**:
- **Image A - conv+GEMM:** runtime conv engine (~168k) + GEMM page (~6k) +
  transport (~2k) ~= 176k LUTs (59 %), replacing the four per-profile conv pages
  and the GEMM page.
- **Image B - pooling + elementwise:** pooling-corpus pages (~30-35k) +
  EW FP16/FDIV (~6k) + ew-int (~small) + transport ~= 40-45k LUTs.
Both images fit comfortably and reuse the proven templates/transport; the
existing six-page/EW/ew-int/pooling-corpus images remain fallbacks. A further
area cut (smaller arrays/CACC) could re-open the merged option later but is not
on the critical path.

Before S1, the parameterised construction needs hash-bound equivalence: re-run
leg A (primary 3 cases) and leg B (controls) against the new front/core hashes;
S1 will re-run equivalence on the attached page anyway.


### D2 update — measured pooling fit (2026-11-11)

Whole-image pooling-corpus synth receipt `build/pooling-image/synth-20261110T141422Z`
(Vivado 2026.1, maxThreads 2, source_match=true): **110,107 LUTs (36.87 %),
33,044 regs, 8 RAMB36** — 2.4x the labelled pre-synth estimate (37.8k), because
the two most expensive leaves were never sampled then: page 0 (FP16
global-average) 55,306 LUTs and page 3 (FP16 avg k2s1 4x4) 11,922 LUTs; page
sum 107,332 + JTAG bridge 1,216 + shaping ~1k. OOC methodology validated
(page7 2,209 OOC vs 2,212 in-image; page16 1,345 vs 1,346).

D2 decision: the old 55k figure was a merged-image budget and is moot (the
merged single image was rejected at D1). For the adopted two-image split,
Image B cost is pooling ~110k + EW FP16/FDIV ~6k + ew-int (small) +
transport ~2k ~= 120k LUTs (~40 %), so **D2 is confirmed as feasible** and the
full pooling image build proceeds now; the page0/page3 hotspot reduction is a
future optimisation, explicitly not on the critical path.
