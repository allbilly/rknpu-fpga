# Pooling-corpus image — one host-drivable page per frozen pooling fixture

Status: **RTL + generated case tables implemented; all 19 fixtures replay
byte-exactly through the image in the Icarus leg (complete 4096-byte BO per
case, source-hash-bound receipt below). Verilator replay and the synth-only fit
are pending the lead's build-slot coordination.** This image is separate from
the adopted six-page image `build/jtag-dual-image/20261109T160627Z` and does not
modify it.

## Why

The adopted six-page image carries exactly one pooling page (signed-INT8 C16
k2s2 maximum). The `pooling.py` / `expt/pooling.py` families need the whole
frozen pooling corpus: 19 READY cases of
`build/rk3588-example-captures/pooling/manifest.json` (18 live-captured plus one
source-derived `fp16_max_k3s2_pad1_c8_h4w4`). This image gives each fixture its
own AXI4-Lite page so any captured pooling job can run on the FPGA without
touching the six-page image.

Coverage boundary (honest and measured, nothing silently dropped):

* **included:** all 19 READY cases, each with the complete frozen
  `regcmd.bin` / `in.bin` / `out_init.bin` / `expected.bin` and its exact
  captured geometry;
* **excluded — blocked by the capture, not by RTL:**
  `int32_max_k2s2_zero_write_c4_h2w2` and
  `fp32_max_k2s2_zero_write_c4_h2w2` are manifest `BLOCKED` cases: the source
  reported submit success but the PPU wrote all-zero output, so no valid device
  oracle exists to compare against;
* **excluded — not part of the capture manifest:** the legacy
  `fp16_max_k16s16_c8_h16w16` leaf fixture exists in `tests/ppu_pooling` but is
  not a READY case of the frozen capture manifest, so it has no corpus identity
  in this image. It is not counted as covered.

## Page map

| Region | Contents |
|---|---|
| `0x0000_0000 .. 0x0000_7fff` | shared 32 KiB memory aperture (BO load/read) |
| `0x0000_8000 + i*0x1000` | corpus page `i`, `i = 0 .. 18` (19 pages) |
| `0x0001_b000 .. 0xffff_ffff` | unmapped: explicit SLVERR, never an alias |

Each page uses the transport ABI of `rk_ppu_pool_axi` (`DEVID`, `ABI_VERSION`,
`STATUS`, `COMMAND`, `START_ADDRESS/AMOUNT`, `JOB_TAG`, `RESULT_*`) and adds two
read-only identity registers so a host binds page ↔ fixture without trusting the
address alone:

| Offset | Register | Meaning |
|---|---|---|
| `0x00` | `DEVICE_ID` | `0x524b5001 .. 0x524b5013` (one per page) |
| `0x28` | `FIXTURE_INDEX` | corpus page id (also the page order below) |
| `0x2c` | `FIXTURE_CRC32` | CRC32 of the frozen fixture name |

Page order (also the generated `CASE` index, from the sorted READY set):

| Page | Fixture | Page | Fixture |
|---:|---|---:|---|
| 0 | `fp16_avg_global_k3x5_valid_c8_h3w5` | 10 | `int16_avg_q16_k3x3_valid_c8_h3w3` |
| 1 | `fp16_avg_k2s1_pad1_use_cnt0_c8_h1w1` | 11 | `int16_max_k2s2_valid_c8_h2w2` |
| 2 | `fp16_avg_k2s1_pad1_use_cnt7_c8_h1w1` | 12 | `int16_min_k2s2_valid_c8_h2w2` |
| 3 | `fp16_avg_k2s1_valid_c8_h4w4` | 13 | `int8_avg_q16_k2s2_valid_c16_h2w2` |
| 4 | `fp16_max_k2s1_pad1_neg_c8_h2w2` | 14 | `int8_avg_q16_k3x3_valid_c16_h3w3` |
| 5 | `fp16_max_k2s1_valid_c8_h4w4` | 15 | `int8_max_k1s1_valid_c32_h1w1` |
| 6 | `fp16_max_k2s2_c3_tail_h2w2` | 16 | `int8_max_k2s2_valid_c16_h2w2` |
| 7 | `fp16_max_k2s2_index_c8_h2w2` | 17 | `int8_min_k2s2_valid_c16_h2w2` |
| 8 | `fp16_max_k3s2_pad1_c8_h4w4` | 18 | `int16_avg_q16_k2s2_valid_c8_h2w2` |
| 9 | `fp16_min_k2s1_valid_c8_h4w4` | | |

## Architecture

* **Generated strict command gate** (`rtl/ppu/rk_ppu_pool_corpus_case.sv`,
  emitted by `tools/ppu/gen_pool_corpus_tables.py` from the frozen captures):
  every bit of the 26/28-QWORD stream is compared exactly against the captured
  values, except the two 32-bit base-address fields that the host relocates
  (`job.json` patches, QWORD indices `[13,20]` for 26-QWORD streams and
  `[15,22]` for 28-QWORD streams). A wrong field, wrong length or wrong PC tail
  is an explicit page fault. There is no command rewrite.
* **One generic engine** (`rk_ppu_pool_corpus_dma` in
  `rtl/ppu/rk_ppu_pool_corpus_axi.sv`): fetches the complete raw stream, runs
  the generated gate, checks the relocated in/out windows (16-byte alignment,
  in aperture, disjoint from the command block and from each other), then streams
  input atoms through the captured leaf and writes the captured output atoms.
  The FP16 max-with-index leaf has a tiny adapter (`rk_ppu_pool_corpus_index_leaf`)
  because it emits its value and uint16 index atoms on the same handshake; the
  adapter serialises them into the two standard atom beats.
* **All 19 pooling leaves share the identical atom-stream interface**
  (`in_valid/in_ready/in_atom[127:0] -> out_valid/out_ready/out_atom[127:0]/
  out_last`), which is what lets one generic DMA replay every case. Each page
  elaborates exactly one captured leaf through the generated `CASE` branch.
* **Shared memory + arbitration** (`fpga/ypcb_ppu_corpus_top.sv`): one 32 KiB
  BRAM aperture, one BRAM request port, one granted owner per transaction, the
  grant latched until its response returns. A page's `memory_ready` is the
  complement of "any engine busy" plus the host bridge, so at most one corpus
  job can be active; a refused submit is an explicit SLVERR. A second page
  submitting while one is active, and any unmapped address, are covered by the
  bench's negative controls.
* **Transport** (`fpga/ypcb_ppu_corpus_jtag_top.sv`): the same proven USER2
  JTAG-mailbox path as the adopted image (`otpu_jtag_mailbox` +
  `rk_jtag_axil_bridge` + the reviewed mailbox CDC Tcl). Package pins are only
  the audited `SYS_CLK` (AA28) and the three LEDs (P30/M30/N30); the bare-AXI
  top cannot be emitted (NSTD-1/UCIO-1).

## Verification

### Measured receipt so far

* **Icarus Verilog 13.0 full-matrix replay: PASS.**
  `build/pooling-image/sim-iverilog-all1/report.json` — 19/19 fixtures, every
  case reported `mismatches=0 over_tolerance=0` on the full 4096-byte BO,
  page identities and result registers checked, page-0 image-level refusals
  (SLVERR for an unmapped address and for a second-page submit while busy) and
  the tampered-command negative control (`negative_code=1`) exercised. The
  receipt records the before/after source hashes of the image RTL, generated
  case tables, bench, runner and all frozen fixtures; they match the tree
  (`source_changed_during_run=[]`). `hardware_accessed=false`,
  `vivado_executed=false`, no bitstream.
* **Not measured yet:** implementation (timing/DRC/route), bitstream SHA, board
  access. The measured whole-image *synthesis* fit is above.
* **Verilator full-matrix replay: PASS**
  (`build/pooling-image/sim-verilator-all1/report.json`, Verilator 5.048,
  19/19 cases, complete-BO comparisons all pass, source-hash fresh,
  `hardware_accessed=false`).
* **Area — MEASURED WHOLE-IMAGE SYNTHESIS (PASS).**
  `build/pooling-image/synth-20261110T141422Z` (Vivado 2026.1, fresh dir,
  source hashes matched, `general.maxThreads 2`, 918 s): **110,107 slice LUTs
  (36.87% of 298,600), 33,044 slice registers (5.53%), 8 RAMB36 (0.84%)**.
  Hierarchical cost: page 0 (FP16 global-average leaf) 55,306 LUTs; page 3
  (FP16 avg k2s1 4x4) 11,922; page 8 (derived max k3s2 pad1) 7,466; pages
  4/5/6/7/9/11/15 2.0-3.3k; every other page 1.3-1.8k; page sum 107,332 plus
  JTAG bridge 1,216 and image shaping. Reports: `utilization_synth.rpt`,
  `utilization_hier.rpt`, `post_synth.dcp`, `inputs.json`,
  `measured_fit_summary.json` in that directory. The earlier per-page OOC
  samples were validated against it (page7 2,209 vs 2,212; page16 1,345 vs
  1,346); the provisional ~37.8k estimate was low because the two dominant
  FP16-average leaves were not sampled and remains archived as a labelled
  secondary estimate under `build/pooling-image/ooc-fit/`.

### How it is replayed

* `tools/ppu/run_pool_corpus.py` replays all 19 fixtures through real AXI4-Lite
  in Icarus and Verilator: it loads the patched raw command stream and the
  fixture's in/out_init BOs into the shared memory window, submits the unchanged
  descriptor on page `i`, checks the page identity and result registers, and the
  bench compares the **complete 4096-byte BO**: exact for integer/max/min/index
  lanes and untouched bytes, and the capture's declared absolute tolerance for
  FP16 average lanes (compared exactly in FP16 2^-24 fixed-point units, no real
  arithmetic or tolerance rounding). Page 0 additionally runs the image-level
  refusals and a tampered-command negative control. Receipts are source-hash
  bound before/after and live under `build/pooling-image/`.
* `tests/ppu_pooling/test_pool_corpus_contract.py` pins the page count, the
  generated gate coverage, the identity binding, the address map, the shared
  single-owner memory, the build gates and the runner's complete-BO contract.
* `tools/ppu/vivado_pool_corpus.py synth|run` builds into a fresh
  `build/pooling-image/<UTC stamp>/` with the unchanged 20 ns clock, timing/DRC
  gates, page-presence gate for all 19 pages, and source hashes before/after.
  The `synth` action is the fit estimate; the full image is only built after a
  measured fit and an explicit build slot.

## Not claimed

No board run, no bitstream yet, no hardware access. The image is a corpus
transport, not the complete NPU framework, and the two BLOCKED zero-write
captures plus the legacy non-manifest fixture remain out of scope as stated
above.


## Build-gate fixes found by the 2026-11-11 staged build attempt

Two defects in the page-presence gate (present in the single-batch template and
inherited by the staged synth template) made every build fail *after* a full
synthesis pass:

1. **Descendant match, not instance match.** The filter
   `NAME =~ *g_pages*pool_page*` matches every cell below each page instance —
   172,978 cells for 19 pages — so `llength` could never equal N_PAGES. The
   check is now anchored on the page module type.
2. **Uniquification.** After `synth_design` Vivado uniquifies the parameterised
   pages (`rk_ppu_pool_corpus_axi`, `rk_ppu_pool_corpus_axi_0`, ...), so an exact
   `REF_NAME ==` comparison matches exactly one cell. The gate now uses
   `REF_NAME =~ rk_ppu_pool_corpus_axi*` **and** requires the
   `*g_pages*pool_page*` instance path, which is stable across uniquification and
   cannot be satisfied by an unrelated cell.

Both templates (`fpga/ppu/build_pool_corpus.tcl.in` and
`fpga/ppu/build_pool_corpus_synth.tcl.in`) carry the corrected gate; the render
check confirms no unexpanded token remains and the token counts are unchanged.
The failed attempt trees (`build/pooling-image/20261111T0042Z`,
`20261111T0116Z`) are kept as records of the defects (their receipts show the
gate error, no bitstream).


## Measured thermal behaviour of the staged pooling build (2026-11-11)

| attempt | quota / threads | outcome |
|---|---|---|
| `20261111T0116Z` | 100% / 2 | gate defect (counted 172,978 descendant cells) — no thermal kill |
| `20261111T0200Z` | 100% / 2 | **guard kill at 97.1-100.2 C** during Timing Optimization (~25 min in) |
| `20261111T0235Z` | 50% / 1 | queued as the coolest sustainable configuration |

The measured envelope matches the earlier host study: ~1 core sustained drives
this laptop chassis to ~97-100 C within 20-30 minutes; ~0.5 core holds 60-75 C
indefinitely. Long Vivado syntheses therefore run at **CPUQuota=50 with
`maxThreads 1`**, accepting roughly doubled wall time, and the staged design
(synth checkpoint then impl) means a thermal interruption costs only one stage.
