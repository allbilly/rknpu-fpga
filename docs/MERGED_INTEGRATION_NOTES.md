# Two-image split integration notes: Image A (conv+GEMM) / Image B (pooling+EW)

Status: **Image-A S1 scaffolding; no synthesis, no bitstream, no hardware.**
This note supersedes the earlier merged-single-image integration notes after the
Lead's D1/D4 decision. The adopted architecture is the **two-image split**; the
single merged image is not adopted.

## 0. Decision this note is built on

* D1 measured the parameterised runtime conv engine at **167,858 LUTs (56.2 %)**,
  which is **17,858 over the 150,000-LUT single-image ceiling**
  (`build/runtime-conv-lab/D1_AREA_PARAMETERISED_RECEIPT.md`).
* Decision (2026-11-11, recorded in `docs/MERGED_IMAGE_PLAN.md` §D1/D4 update):
  **two-image split**, not a merged single image:
  * **Image A** — runtime conv engine (~168k) + FP32 GEMM page (~6k) + USER2
    transport (~2k) ≈ 176k LUTs (59 %), this scaffolding's target.
  * **Image B** — pooling corpus pages (~30–35k) + EW FP16/FDIV endpoint (~6k)
    + ew-int + transport ≈ 40–45k LUTs, separate top/profile.
* The adopted six-page, EW, ew-int and pooling-corpus images remain fallbacks.
  Nothing here replaces them until a split image passes the same gates and the
  byte-exact replay matrix.

## 1. What exists after this scaffolding pass

| File | Role | State |
|---|---|---|
| `fpga/ypcb_merged_top.sv` | **Image A** pin-free top: USER2 mailbox -> AXI bridge -> Image-A decode -> shared 64 KiB window + `conv_runtime_page`/`gemm_page` stubs | Skeleton; Icarus-elaborates; pages are `merged_page_stub` |
| `fpga/ypcb_image_b_top.sv` | **Image B** pin-free top scaffold: pooling corpus band (19 x 4 KiB) + RKEW control page + EW 1 MiB sparse aperture (six measured banks) + ew-int control page/aperture placeholders | Scaffold only; preserves the pooling/EW work from the abandoned merged top |
| `fpga/image_b/image_b_sources.json`, `fpga/image_b/build_image_b.tcl.in` | Image-B fail-closed profile + build template (same gates, REF_NAME page presence, no SYNTHESIS define) | S3/S4 scaffold; `--profile image-b` renders/verifies |
| `rtl/rk_ew_int_page_axi.sv`, `rtl/rk_ew_int_aperture.sv` + `docs/EW_INT_APERTURE_AUDIT.md`, `tools/merged/ew_int_aperture_audit.py`, `tests/tb_ew_int_page.sv`, `tools/merged/run_ew_int_page_replay.py` (ewint task-23) | **INTEGRATED** Image-B ew-int page form: page at `0x2_4000` + four 4 KiB sparse banks at `0x1100_0000`, frozen `rk_job_control` ABI, raw-command capture | both-sim replay 15/15 PASS (`build/ew-int-page/20261110T142754Z`, report sha `0b684d91…`); 26 offline contracts |
| `tools/merged/run_image_b_replay.py`, `tests/merged/test_image_b_replay.py` | Image-B S3/S4 replay plan: pooling 19 + EW FP16 54 + FDIV 8 + ew-int 15, staging/complete-BO scopes, negatives, heavy-window policy | `PLAN_READY`; `full` refuses until real pool/EW pages + Lead window |
| `fpga/merged/merged_job_stub.sv` | Runtime-page ABI **reference model** (rk_job_control-compatible registers + modeled submit→done lifecycle; no memory access) used while the engine is gated | Scaffold; replaced by `rk_conv_runtime_axi` at S1 |
| `tests/tb_image_a_job_abi.sv`, `tools/merged/run_image_a_replay.py` | Page-ABI bench + Image-A replay scaffolding (frozen-fixture complete-BO plan, fixture mode, ABI mode, fail-closed `full` mode) | ABI PASS; plan `PLAN_READY` (7 conv-simple + 8 vendor); full mode refuses until wrapper pinned |
| `fpga/merged/merged_page_stub.sv` | Generic AXI4-Lite page placeholder (ID/scratch/memory-ready) | Scaffolding only |
| `fpga/merged/merged_sources.json` | Image-A profile: top/part/20 ns/JTAG chain 2/64 KiB window/XDC/CDC/`{DESIGNWARE_NOEXIST SYNTHESIS}`/page table with per-page REF_NAME/required pages/S1 attach ABI + pending source hashes | S1 scaffold profile |
| `fpga/merged/build_merged.tcl.in` | Image-A build template: unchanged gates + source-hash binding + rendered **REF_NAME page-presence** block + reviewed emission | Not rendered into a build yet |
| `tools/merged/vivado_merged_image.py` | Fail-closed renderer/verifier: `render`/`verify`/`check` (no Vivado) and `synth` (refuses without `--execute`) | Implemented; `check` PASS |
| `tools/merged/ew_aperture_audit.py`, `docs/EW_APERTURE_AUDIT.md` | Offline EW aperture audit (now the Image-B aperture): 54 ew-fp16 + 8 fdiv-systematic cases fit the six banks | **PASS** |
| `tools/merged/README.md` | Tool usage | — |
| `tests/tb_ypcb_merged_top.sv`, `tests/merged/merged_primitive_stubs.sv` | Mailbox->AXI bench for the Image-A top: page IDs, scratch isolation, 64 KiB window, memory_ready, SLVERR hole + quarantine, unwritten-page control | 4 hole configs PASS (17 frames / 28 checks each) |
| `tests/merged/*` | Offline contracts: two-image map/plan, Image-B profile/renderer, renderer refusals/gates, scaffold bench, page-ABI bench, replay plan, aperture audit | 49 offline tests PASS (no Vivado) |

No RTL outside the new scaffolding files was modified; the adopted six-page
image, its receipt, the EW package and every frozen fixture are untouched.

## 2. Image A architecture (pinned by tests)

Address map (4 KiB pages, 32-bit AXI4-Lite byte addresses):

| Range | Target | Instance | Real slave to attach | Stage |
|---|---|---|---|---|
| `0x0000_0000..0x0000_ffff` | `T_MEMORY` | `memory_bridge` + `memory` (`rk_bram`, 64 KiB) | already real | S0 |
| `0x0001_0000..0x0001_0fff` | `T_RKCV` | `conv_runtime_page` | `rk_conv_runtime_axi` around `rk_conv_runtime_core` | **S1** |
| `0x0001_1000..0x0001_1fff` | `T_RKCM` | `gemm_page` | `rk_cmac_gemm_axi` (decode-driven, unchanged) | S2 |
| everything else | `T_UNMAPPED` | `error_page` (`rk_axil_error_slave`) | already real | S0 |

* **Page mask/presence**: `PAGE_MASK = 7'b000_0111` (bit0 memory, bit1 RKCV,
  bit2 RKCM), bits [6:3] reserved and refused if set; `REQUIRED_PAGE_MASK =
  7'b000_0011` (S1 minimum). A disabled page decodes to SLVERR, never aliases.
  The build-time presence gate is rendered from the profile as a
  **REF_NAME-checked** check, so a `merged_page_stub` cannot silently satisfy a
  real page slot once the profile expects the real page.
* **Arbitration**: one AXI transaction at a time; `any_engine_busy` disables the
  host window; pages receive `engine_memory_ready`. TODO(S1/S2): replace the
  aggregate with the dual-image complement pattern once real engines expose
  independent busy lines (same rule the six-page image already proves).
* **Shared window**: one 64 KiB `rk_bram` (`host + engine` arbitrated request
  port) is enough for the runtime engine's command BO, weight/input front stores
  and output BO; the page's memory master must reach the **whole** window
  because operand/output addresses live inside the raw command stream.
* **Transport/CDC/pins**: unchanged from the adopted images — USER2 mailbox ->
  `rk_jtag_axil_bridge` -> AXI, reviewed `fpga/host/mailbox_cdc.tcl` applies to
  the preserved `u_mailbox`/`u_bscan` hierarchy, AA28 + three LEDs, 20 ns sys_clk,
  `rk_startup_reset` hold 64.
* **Synthesis define**: Image A must elaborate with
  `verilog_define = {DESIGNWARE_NOEXIST SYNTHESIS}` so the runtime engine's
  explicit SDP-BRAM mapping and C16 construction are used (the D1 area receipt
  used the same define set). The template pins this; the renderer refuses a
  profile without it.

## 3. Image-A S1 attach plan: runtime conv page (agreed with conveng)

**Gate first:** do not attach the real page until conveng's **parameterised C16
construction** passes the hash-bound old-vs-new equivalence rerun (leg A primary
3/3 + leg B 51/51 controls + decoder 13/13 are pre-parameterisation PASS
receipts; the parameterised rerun is staged for a Lead-scheduled cool window).
The current stub keeps the profile/scaffold valid meanwhile.

**Current page slot:** `merged_job_stub` (ABI reference model). It implements the
exact register/lifecycle contract below without an engine, so the ABI bench,
replay plan and negative controls are already proven. At S1 the profile `ref`
flips to `rk_conv_runtime_axi` and only then does replay `full` mode turn green.

**Page wrapper** (`rk_conv_runtime_axi`, owned by Image A; instantiates
`rk_conv_runtime_core` unmodified, co-signed with conveng):

```
rk_job_control-compatible AXI4-Lite page at 0x0001_0000, DEVICE_ID 0x524b4356
("RKCV"), ABI_VERSION 0x00010000:
  0x00 ID  0x04 ABI  0x08 STATUS  0x0c COMMAND
  0x10 START_ADDRESS  0x14 START_AMOUNT  0x18 JOB_TAG
  0x1c RESULT_TAG     0x20 RESULT_TASKS   0x24 RESULT_CODE
```

Contract (confirmed by conveng):
1. `START_ADDRESS` is 16-byte aligned inside the 64 KiB window;
   `START_AMOUNT` is the exact raw QWORD count (52 conv-simple, 54 vendor
   conv-fp16). The wrapper fetches little-endian QWORDs unmodified and drives
   `cmd_valid/cmd_data/cmd_last` in order (`cmd_last` only on the final word);
   `cmd_ready` may stall — no minimum rate.
2. The wrapper captures all `START_AMOUNT` QWORDs **before** asserting the first
   `cmd_valid`.
3. **Re-arm**: pulse `rst_n` between jobs (the decoder is one-job-locked; a
   second stream without reset is fault 7). Do not reuse the conv pages' "hold
   in reset while idle" wording blindly — the pulse happens between accepted
   jobs, not after every frame.
4. Status mapping: `completed_tasks = done && !error ? 1 : 0`; `error/error_code`
   sticky until reset; `acknowledged`/`frame_done` are observation-only.
5. **Memory owner switch** (new logic in the wrapper): wrapper owns the shared
   memory master while fetching/validating the command QWORDs; the core owns it
   from first `cmd_valid` until `done|error`; the wrapper re-owns it afterwards.
   Single-outstanding halfword transactions; no `memory_ready` input exists in
   the core, so arbiter gating is wrapper-side; tie `mem_rsp_error = 0` unless a
   fault-injection control is added.
6. Observation ports (`config_*`, `*_bytes`, `obs_*`) may be left unconnected.
7. Same `clk`, async active-low `rst_n`, 20 ns; the core is synthesized from the
   additive experimental files (see `s1_attach.source_hashes` in the profile:
   core/decode/front/fp32-output/frame-stage/cell/array/cacc/sdp-bram) plus the
   frozen donor deps already listed in the profile. FINAL-frozen
   `rk_cmac_fp16_*`/`rk_frame_stage` are neither changed nor instantiated by the
   runtime core.

**Attach sequence once conveng is green:**
1. Update the profile: add the runtime-page source list + their exact hashes
   (replacing the informational `s1_attach.source_hashes` entries), set the
   `conv_runtime_page` entry's `ref` from `merged_job_stub` to
   `rk_conv_runtime_axi`, and update the renderer's expected page ref (the tool
   is fail-closed on ref changes).
2. Add the wrapper file + register it in `sources`; keep the GEMM page stub.
3. Re-render/verify; the rendered page gate now requires the real REF_NAME.
4. Bench: keep `tb_ypcb_merged_top.sv` as the transport/decode scaffold; add the
   family replay runner for the runtime page (conv-simple 4 profiles x 8 modes,
   nine vendor conv-fp16 captures, negative controls: unknown/unsupported
   geometry, second stream without reset, unaligned START, out-of-window BO,
   overlapping buffers) — complete-BO byte compare against the frozen captures.
5. Build only in a Lead-scheduled cool window through the shared heavy-job
   wrapper; record WNS/WHS/TNS/slices/LUTs/BRAM/SHA and keep the six-page image
   as the reference until the replay matrix passes.
6. S2 adds `rk_cmac_gemm_axi` the same way (sources/hashes/ref + four frozen
   GEMM shapes), completing Image A.

## 4. Image B (pooling + EW) scaffolding

`fpga/ypcb_image_b_top.sv` keeps the abandoned merged top's non-conv half:

* shared 64 KiB host window at `0x0`;
* pooling corpus **multi-page band** `0x0001_0000..0x0002_2fff` (19 x 4 KiB
  pages, one per READY pooling fixture). **D2 decision (Lead, 2026-11-11): the
  multi-page band is the adopted provisional Image-B shape; confirm it against
  share's measured whole-image synth fit (queued third in the heavy FIFO). The
  measured-estimate band remains the intended shape; if share's fit differs the
  form is re-recorded before the Image-B build.**;
* RKEW control page `0x0002_3000..0x0002_3fff`;
* **RKEW-int control page + sparse aperture (page-form adopted, Lead
  2026-11-11; CONFIRMED by ewint's PASS address audit).** `rk_ew_int_page_axi`
  at `0x0002_4000` (4 KiB, DEVICE_ID `RKEI` `0x524b4549`, ABI `0x00010000`,
  frozen `rk_job_control`-compatible register map/status word — **authoritative
  LSB-anchored layout `[0] can_submit, [1] active, [2] result_valid,
  [3] result_error, [4] memory_ready, [5] core_error, [6] core_busy,
  [10:8] fields_valid`** (the early-coordination `[16]/[20:18]` sketch was
  wrong; the frozen RTL concatenation is authoritative and the page RTL/bench
  poll these bits); START_ADDRESS
  must be 8-byte aligned inside the aperture, expected `0x1100_4000`;
  START_AMOUNT fail-closed at one of the captured shapes `{18,31,44}`; the page
  fetches exactly that many little-endian QWORDs into a 44-entry capture, drives
  them unchanged into the integer decoder, never rewrites the command BO, and
  result/error codes are the frozen map with sticky error until fabric reset).
  `rk_ew_int_aperture` at `0x1100_0000` keeps the **1 MiB decode** with **four
  4 KiB physical banks** (A `0x1100_1000`, B `0x1100_2000`, D `0x1100_3000`,
  C command `0x1100_4000`; 16 KiB physical = 4 RAMB36 tiles vs 256 dense) and
  explicit SLVERR/`mem_rsp_error` holes `0x1100_0000..0x1100_0fff` and
  `0x1100_5000..0x110f_ffff`. Audit facts: 15/15 READY bundles (3 BLOCKED
  excluded), 3 x 4 KiB buffers + 144/248/352 B command BO, max 4 regions, union
  span `0x1100_1000..0x1100_4160` (12,640 B), the only address-bearing fields
  are `DPU.DST_BASE_ADDR`/`RDMA.SRC_BASE_ADDR`/`RDMA.EW_BASE_ADDR` (all in the
  patch list; terminal PC tail zero, layout-mode stride/surface fields are
  geometry, not pointers). **Command BO lives in bank C** (alternative adopted)
  so the page needs exactly one 16-bit serialized memory master and Image B
  needs no new shared-window arbiter; host stages all four regions through the
  aperture AXI port. Wiring: page `page_busy` gates aperture host access
  (SLVERR while busy), aperture staging idle raises `memory_ready` to the page,
  aperture owns the engine master; no changes to EW/pooling arbitration. The
  standalone mailbox-direct ew-int image (`fpga/ewint/ypcb_jtag_ew_int_top.sv`)
  remains the fallback. **State: INTEGRATED into `fpga/ypcb_image_b_top.sv`** — page bus `[3]` →
`rk_ew_int_page_axi` (16-bit offsets, absolute memory master), page bus `[4]` →
`rk_ew_int_aperture` (absolute staging AXI), page `mem_*` ↔ aperture
`engine_*`, `page_busy → page_busy`, `memory_ready → page`, `page_cancel=0`;
profile sources/refs flipped and the required-page mask is now `0110011`
(`memory`, `pool_band_page`, `ew_int_page`, `ew_int_aperture_page`), so the
rendered REF_NAME gate requires the real modules. ewint's both-sim page replay
is **15/15 READY PASS** (`build/ew-int-page/20261110T142754Z`, report sha
`0b684d91…`); page-level ABI/status-layout tests are in the offline suite.
**Gate:** the remaining Image-B work is the pooling/EW real pages + S3/S4
replays executed in a Lead-scheduled cool window.
* EW 1 MiB aperture `0x1000_0000..0x100f_ffff` decoded with six sparse physical
  banks (A/B/D 4 KiB, scratch 8 KiB, command 64 KiB, task 16 KiB = 100 KiB);
* page mask `7'b000_1111` (memory, pool band, EW page, aperture), bits [6:4]
  reserved; `REQUIRED_PAGE_MASK = 7'b000_0011` (S3 minimum);
* same USER2 transport/CDC/pin budget; three LEDs.

`docs/EW_APERTURE_AUDIT.md` (PASS) tells exactly where the full ew-fp16 family
(54), `fdiv-systematic` (8) and the `simple_add` grammar stage into those banks
(3 buffers 4096/64 B + 22-word command BO; host patches `out/a/b`; no PC chain).
Image B now has its own fail-closed profile/template
(`fpga/image_b/image_b_sources.json`, `--profile image-b`), REF_NAME page
presence and contract tests. Both Lead decisions are recorded in that profile's
`decisions` block: **ew-int page-form** (control page + aperture; ewint delivers
the wrapper/adapter/address audit; standalone ew-int image is the fallback) and
**D2 multi-page band as the provisional shape** (confirm with share's measured
fit; estimate-based band remains the fallback plan). The EW AXI front end +
sparse-bank adapter remain new RTL (with a byte-exact owned-BO equivalence
proof) before its image can be built.

## 5. Staged plan and gates (two-image version)

| Stage | Work | Gate |
|---|---|---|
| S0 | scaffolding (this pass) | offline tests PASS; no build |
| S1 | Image A runtime conv page attach (conveng equivalence green + wrapper + profile refs + replays) | page presence + byte-exact conv replays + negative controls; build receipt |
| S2 | Image A GEMM page attach | 4 frozen GEMM shapes byte-exact; build receipt; Image A complete (planned ~176k LUTs) |
| S3 | Image B pooling pages (D2 band; profile/renderer done) | 19 READY pooling fixtures complete-BO exact |
| S4 | Image B EW front end + sparse aperture; **ew-int page form integrated** | ew-fp16/FDIV replays, ew-int both-sim replay PASS (done), negative controls; aperture holes SLVERR |
| S5 | builds/emission for A and/or B in scheduled cool windows | timing/DRC/route/CDC/page-presence gates, bitstream SHA, hardware candidate binding |
| fallback | adopted six-page + current EW image | keep as reference until S1/S2/S3/S4 pass |

Every build is Lead-scheduled (`build/verif/host_guard/safe_run.sh`, one heavy
job, cool window); no gate may be weakened; no hardware action is implied.

## 6. Renderer/build contract (Image A)

`tools/merged/vivado_merged_image.py --profile {image-a,image-b}` renders the
selected profile (Image A: `fpga/merged/merged_sources.json`/`build_merged.tcl.in`;
Image B: `fpga/image_b/image_b_sources.json`/`build_image_b.tcl.in`) with tokens `ROOT OUT PART TOP CONSTRAINTS CDC INCLUDE_DIRS READ_SOURCES
SOURCE_SHA SOURCE_TAG PAGE_LIST PAGE_MASK PAGE_GATES`.
`PAGE_GATES` renders the per-page `REF_NAME`-checked presence block, closing the
earlier "a stub can satisfy a page slot" gap. `check` is a pure offline
render+verify; `synth` refuses without `--execute` and must be run through the
heavy-job wrapper. Open build-window items:
* the `-generic PAGE_MASK=7'b...` vector override is still unverified against
  Vivado (fallback: render a localparam include; no RTL change);
* when the real pages attach, update the profile `ref` and the renderer's
  expected refs in the same change (the tool will otherwise refuse the profile);
* Image A's real area/timing number is unknown until the S1/S2 builds.

## 7. Verification contract

```sh
python3 -m unittest discover -s tests/merged -p 'test_*.py' -v   # 49 offline tests
python3 tools/merged/vivado_merged_image.py check --out build/merged-image/check-<stamp>
python3 tools/merged/vivado_merged_image.py check --profile image-b --out build/merged-image/check-b-<stamp>
python3 -m unittest tests.merged.test_merged_scaffold_bench -v   # 4 bench configs
python3 tools/merged/run_image_a_replay.py --mode fixtures       # complete-BO plan
python3 tools/merged/run_image_a_replay.py --mode abi            # page-ABI bench
python3 tools/merged/run_image_a_replay.py --mode full           # refuses until wrapper
python3 tools/merged/ew_aperture_audit.py                        # Image-B EW aperture audit
python3 tools/merged/run_image_b_replay.py --mode fixtures       # S3/S4 replay plan (pooling/EW/ew-int)
python3 tools/merged/ew_int_aperture_audit.py                    # ew-int aperture audit (ewint)
python3 tools/merged/run_ew_int_page_replay.py --simulator both  # HEAVY (~10 min Icarus): Lead window only
```

**S3/S4 replay oracle decisions (Lead, 2026-11-11):**
* **EW FP16 54 device-free bundles** — oracle = **logical `expected.bin`
  comparison only**; the complete-BO/oracle-surface leg stays reserved for the
  9 production captures (`tests/backend_ew_captures.json`). No invented device
  expectations; these bundles are prepared fixtures, not capture-derived BOs.
* **FDIV 8 truth-table bundles** — expected-value oracle = the
  **three-guard-bit RTL model in `docs/FDIV.md`** (Lead decision), which is
  device-confirmed on the full live differential (**1,452/1,452** captured
  lanes; `build/rk3588-live-verify/FDIV-RESIDUAL.md`,
  `build/rk3588-live-verify/20261109T201838Z-j07/`, `build/rtl/report.json`).
  Comparison = logical float compare against that model with the documented
  exception set: exactly the **20 documented A/7 one-ULP-low lanes** (19 unique
  A/7 operand pairs + the `p1_n33` repeat) are expected to differ by −1 bit from
  donor-RNE; **a value outside that set fails**. This is a **model/contract
  oracle, device-confirmed — not a capture-derived expected BO** for these
  bundles; the special-value policy remains **candidate behaviour**, not an
  RK3588 specification or IEEE-clean divider. Recorded in
  `tools/merged/run_image_b_replay.py` (`oracle_decision`) and pinned by
  `tests/merged/test_image_b_replay.py`.

**Evidence refresh policy for the ew-int page (COMPLETED 2026-11-11):** the
page replay receipt is **whole-file-hash bound**. `ewint` refreshed the
`rk_ew_int_page_axi.sv` **header comment only** (now shows the authoritative
LSB-anchored STATUS layout and marks the old `[20:18]/[16]/[15]/[14]` sketch
wrong; lint clean, logic/ports/ABI unchanged). Comment-only proof:
`build/ew-int-page/comment-only-refresh-20261110T143500Z.txt` (reconstructing
the pre-edit file by replacing only the 13 changed comment lines reproduces the
previous receipt-bound hash `fcc88d94…` exactly; diff is comment lines only).
A fresh both-simulator page replay then ran through
`build/verif/host_guard/safe_run.sh` (BENCH_MIN_BATTERY=30, BENCH_CPUS=0-1,
BENCH_CPU_QUOTA=50; global heavy lock; sustained-cool gate satisfied — 5
consecutive samples <72 °C, start Tctl 57 °C; no build/bitstream/hardware):
**`build/ew-int-page/20261110T151749Z/report.json` sha
`4170b058…`, report.txt sha `1e0e6875…`** — PASS both simulators
(Verilator 5.048 + Icarus 13.0), 15/15 READY page-level BO replays, 8/8
fail-closed negatives, back-to-back reset-per-job PASS, aperture audit PASS,
command-BO-untouched/a/b byte-exactness per case, 14 evidence sources bound and
the current page RTL `71d716f1…` + `docs/EW_INT.md` `bbbfde29…` bound. The
**refreshed receipt is the current-file evidence**; the previous
`20261110T142754Z` receipt (sha `0b684d91…`) is recorded as
`stale_for_current_file: true`/`logic_evidence_remains: true` — it remains the
correct numerical evidence for the identical logic but is **superseded for
current-file evidence**. Profile field:
`decisions.ew_int_image_b_form.page_replay_receipt` +
`comment_only_refresh` (`state: COMPLETED`); build gate unchanged.

Replays extend the existing frozen-tree tools rather than re-deriving
expectations: conv-simple (`tools/conv/run_conv_simple_axi.py`), vendor conv
(`tools/conv/run_3x3_valid_c4.py`), GEMM (`tools/dual/run_dual_endpoint.py`
modes 4/5), and the mailbox/dual harness pattern for the merged transport. Every
family compares the **complete** BO bytes, never a prefix; negative controls are
explicit refusals (SLVERR/error codes), not silent passes. Receipts bind source
hashes before/after and tool versions.

## 8. Open decisions / blockers

* **D1 result**: single merged image not adopted; two-image split adopted
  (recorded by the Lead in the plan + progress table). Further runtime-engine
  area reduction remains possible but is not on the critical path.
* **S1 gate**: conveng's parameterised equivalence rerun must pass before the
  real page is integrated; until then the stub stays.
* **Decisions recorded (2026-11-11)**: ew-int Image-B integration form =
  **page-form, CONFIRMED by ewint's PASS address audit and now INTEGRATED**
  (control page RKEI `0x2_4000` + 1 MiB decode / 4 x 4 KiB sparse banks at
  `0x1100_0000`, command BO in bank C `0x1100_4000`, both-sim page replay
  15/15 PASS, frozen `rk_job_control` ABI with the corrected LSB-anchored
  STATUS layout; standalone ew-int image fallback) and
  D2 pooling form = **multi-page band adopted provisionally** (19 x 4 KiB at
  `0x1_0000`; confirm with share's measured whole-image fit; estimate fallback
  if the fit differs). Both are in `fpga/image_b/image_b_sources.json`
  `decisions` and pinned by `tests/merged/test_image_b_contract.py`.
* **Build gates (explicit)**: **Image A build is gated on conveng's green
  parameterised equivalence + the `rk_conv_runtime_axi` wrapper + S1 family
  replays + a Lead-scheduled cool window.** **Image B build is gated on D2
  pooling form confirmed (share's measured synth fit) + ew-int page/aperture
  integration (done, refs flipped, REF_NAME gate on real modules) + pooling/EW
  real pages + the S3/S4 replay plan executed in a Lead-scheduled cool window.**
  ewint's page replay is ~2 min Verilator / ~10 min Icarus single-core, so it is
  a heavy-window item, never a quick local check. No heavy job starts without
  such a window; no gate may be weakened.
* **Hardware**: any programming/load stays separately authorized; nothing here
  touches the card.
