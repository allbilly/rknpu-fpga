# tools/merged — Image-A (conv+GEMM) scaffolding tools

File-only tooling for the adopted two-image split described in
`docs/MERGED_IMAGE_PLAN.md` and `docs/MERGED_INTEGRATION_NOTES.md`:

* **Image A** — runtime conv engine + FP32 GEMM + USER2 transport
  (`fpga/ypcb_merged_top.sv`), profile `fpga/merged/merged_sources.json`;
* **Image B** — pooling corpus band + EW FP16/FDIV aperture + ew-int
  (`fpga/ypcb_image_b_top.sv`), profile `fpga/image_b/image_b_sources.json`.

Both images are SCAFFOLDING: page slaves are placeholders and no bitstream
exists. Builds are gated on their replays and a Lead-scheduled cool window. The page
slaves are `merged_page_stub` placeholders; **no engine is attached and no merged
bitstream exists yet**. Nothing here programs, resets or flashes the card.

## vivado_merged_image.py — render / verify / check / synth

Renders `fpga/merged/build_merged.tcl.in` from
`fpga/merged/merged_sources.json` with the documented token contract
(`ROOT OUT PART TOP CONSTRAINTS CDC INCLUDE_DIRS READ_SOURCES SOURCE_SHA
SOURCE_TAG PAGE_LIST PAGE_MASK PAGE_GATES`). `PAGE_GATES` renders the
per-page REF_NAME-checked presence block, so a placeholder stub cannot satisfy a
real page slot once the profile expects the real page.

```sh
# dry-run: render a fresh package and verify it, without invoking Vivado
python3 tools/merged/vivado_merged_image.py check \
    --out build/merged-image/check-$(date -u +%Y%m%dT%H%M%SZ)

# Image B uses the same tool with its own fail-closed profile
python3 tools/merged/vivado_merged_image.py check --profile image-b \
    --out build/merged-image/check-b-$(date -u +%Y%m%dT%H%M%SZ)

# render only (fresh dir below build/merged-image/)
python3 tools/merged/vivado_merged_image.py render --out build/merged-image/<stamp>

# re-verify a rendered package against the live tree
python3 tools/merged/vivado_merged_image.py verify --out build/merged-image/<stamp>

# explicitly authorized build (refuses without --execute; heavy; see below)
python3 tools/merged/vivado_merged_image.py synth --execute \
    --out build/merged-image/<stamp>
```

Properties:

* **fail closed**: `load_spec(profile=...)` refuses a changed top/part/clock/
  JTAG chain/memory window/constraints/CDC/page table/page mask/required-page
  list/`verilog_define`, unsafe or missing sources, and a profile that stops
  requiring its S-minimum pages (Image A: `memory + conv_runtime_page`; Image B:
  `memory + pool_band_page`). Image A also refuses to drop the
  `{DESIGNWARE_NOEXIST SYNTHESIS}` define required by the runtime engine.
* **source binding**: every build input is hashed before/after; the rendered Tcl
  binds the manifest sha256 (`RK_MERGED_SOURCE_SHA`) and its first 8 hex digits
  are the `BITSTREAM.CONFIG.USR_ACCESS` tag. A mid-run change fails the receipt.
* **fresh output directories only**, below `build/merged-image/`; an existing
  package is never overwritten.
* **gates unchanged**: the rendered Tcl carries the same fresh-dir, board/voltage,
  20.000 ns clock, BRAM-inference, page-presence, BSCANE2 chain-2,
  timing/DRC/route/CDC and reviewed-emission gates as the adopted images. The
  renderer refuses to write Tcl that lost any of them or that contains a
  hardware-manager/programming command.
* **`synth` is not to be run without an explicitly authorized, thermally gated
  build window.** It requires `--execute` and the caller must wrap it in
  `build/verif/host_guard/safe_run.sh` (`BENCH_CPUS`, `BENCH_CPU_QUOTA`) and
  export `RK_CONFIRM_BOARD`, `RK_CONFIG_VOLTAGE`, `RK_CFGBVS`,
  `RK_LED_ACTIVE_LOW` exactly as the rendered Tcl requires. The tool never
  touches hardware; `RK_EMIT_BITSTREAM=1` is left to the build-window owner.
* Image A defines `{DESIGNWARE_NOEXIST SYNTHESIS}`: the runtime engine's
  explicit SDP-BRAM mapping is under `` `ifdef SYNTHESIS `` (same define set as
  the D1 area receipt). A profile without it is refused.
* The **`-generic PAGE_MASK=7'b…` vector override** has not been validated
  against Vivado yet; that is a recorded build-window verification item
  (`docs/MERGED_INTEGRATION_NOTES.md` §6).

## ew_aperture_audit.py — offline EW aperture feasibility

Reads only the frozen capture bundles and reports whether the merged sparse EW
aperture covers the families intended for the EW endpoint:

```sh
python3 tools/merged/ew_aperture_audit.py
python3 tools/merged/ew_aperture_audit.py --json
```

It decodes every command BO, proves each address-bearing register field is
host-patched (or zero), computes buffer/command/staging bounds, and compares them
with the six measured banks. Verdict and full numbers:
`docs/EW_APERTURE_AUDIT.md`.

## Replay scaffolding — `run_image_a_replay.py`

```sh
python3 tools/merged/run_image_a_replay.py --mode fixtures   # complete-BO plan
python3 tools/merged/run_image_a_replay.py --mode abi        # ABI bench (Icarus)
python3 tools/merged/run_image_a_replay.py --mode full       # refuses until wrapper
```

`fixtures` discovers the frozen `tests/conv/fixtures` cases (7 conv-simple + 8
vendor conv-fp16), validates command-QWORD counts/address-patch indices/buffer
sizes, computes a non-overlapping in-window staging layout, and records the
complete-BO comparison + engine negative-control list. `abi` runs
`tests/tb_image_a_job_abi.sv` (page ABI: ID/STATUS/submit/ack/re-arm plus
unaligned/out-of-window/zero/oversized START, submit-while-pending, recovery).
`full` exits non-zero with `REFUSED_UNTIL_WRAPPER` until the profile's
`conv_runtime_page.ref` is `rk_conv_runtime_axi`; this keeps a green full mode
as proof that the real page (and only the wrapper/hashes) is pinned.

## Image-B S3/S4 replay plan — `run_image_b_replay.py`

```sh
python3 tools/merged/run_image_b_replay.py --mode fixtures   # offline plan ONLY
python3 tools/merged/run_image_b_replay.py --mode full       # refuses until real pages + Lead window
```

Inventories the frozen families and binds every file by sha256: pooling corpus
19 (complete `device_out.bin` BO oracle), EW FP16 54 (Lead decision: **logical
`expected.bin` comparison only**; complete-BO leg reserved for the 9 production
captures), FDIV 8 (Lead decision: **three-guard-bit RTL model from `docs/FDIV.md`
as the device-confirmed model/contract oracle**, logical float compare with the
documented 20 `A/7` one-ULP-low exception set — a value outside that set fails;
not a capture-derived expected BO, special values remain candidate), ew-int 15
(masked complete-BO oracle, already both-sim PASS via ewint's page replay). Records staging addresses, negative
controls and the heavy-window policy (`full` never runs without `--execute` in a
Lead-scheduled window).

## Bench

`tests/tb_ypcb_merged_top.sv` is the mailbox→AXI scaffold bench for the Image-A S1 top
(runtime-conv + GEMM page IDs, scratch isolation, 64 KiB window,
`memory_ready`, SLVERR holes, quarantine, unwritten-page control). It uses
`tests/merged/merged_primitive_stubs.sv` (simulation-only IBUF/BUFG/BSCANE2
models) and the shared `tests/host/mailbox_scan.svh` driver. Run it through:

```sh
python3 -m unittest tests.merged.test_merged_scaffold_bench -v
```

## Tests

```sh
python3 -m unittest discover -s tests/merged -p 'test_*.py' -v
```

Current state: 49 offline tests (two-image map/plan contracts, Image-B profile
and renderer tests, renderer refusals/gates, scaffold bench, page-ABI bench,
Image-A replay plan, aperture audit) — all pass, no Vivado, no hardware.
