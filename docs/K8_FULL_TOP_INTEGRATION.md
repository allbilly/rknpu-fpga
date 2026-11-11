# C32/K8 full-top source integration

Status: **source profile, post-opt synthesis, full-top routed implementation,
offline bitstream emission and read-only bitfile audit PASS**. This is a C32/K8
image artifact result only: no board access, programming, flash or FPGA execution
is claimed.

## Timing-repair merge

`3707873` (`timing-control-repair`) was merged into `a9b5d02` (the K8 backend
tip). The merge was automatic with no conflicts. The K8 CMAC front/datapath/
OC8 writer/core/DMA and AXI parameter changes from `a9b5d02` were retained. The
timing repair added:

- `rtl/ddr/rk_mig_ecc_monitor.sv` read-handshake sampling;
- `rtl/ddr/capacity/rk_ddr_capacity_owner.sv` registered diagnostic quiet
  witness;
- `tests/ddr/tb_mig_ecc_monitor.sv`, `tools/ddr/run_monitor.py` and the two
  timing-repair notes.

No timing constraint, false path, multicycle path or handshake semantic was
changed. All seven affected `rtl/ddr/*/sources.json` selections, both dual-host
frontend manifest hashes and the two hard-coded maintenance-profile manifest
hashes were rebound to the merged bytes. The seven profiles hash-check clean.

## ATOMIC_C/ATOMIC_K chain

The tracked RTL defaults remain `ATOMIC_C=32`, `ATOMIC_K=16`. The build-local
K8 top selects `ATOMIC_K=8`.

| Level | File | Default | Forwards |
|---|---|---|---|
| Top (build-local) | `build/k8-full-top-v1/source/hdl/120/top.sv` | `C=32, K=8` | platform |
| Platform (build-local) | `build/k8-full-top-v1/source/hdl/117/platform.sv` | `C=32, K=16` | endpoint |
| Endpoint (SYS-reset copy of framework top) | `hdl/150/rk_jtag_dual_ddr_async.sv` | `C=32, K=16` | layout/compute dispatch |
| Layout dispatch | `rtl/ddr/framework/rk_layout_compute_dispatch.sv` and factored copy | `C=32, K=16` | dual dispatch |
| Dual dispatch | `rtl/ddr/framework/rk_dual_async_dispatch.sv` and factored copy | `C=32, K=16` | CMAC async engine |
| CMAC async engine | `rtl/ddr/framework/rk_cmac_async_engine.sv` and factored copy | `C=32, K=16` | success rearm |
| Success rearm | `rtl/tinystories/rk_cmac_success_rearm.sv` | `C=32, K=16` | CMAC DMA |
| DMA/core/datapath/front/writer | `rtl/cmac/*` (already parameterized) | `C=32, K=16` | CACC array/writer |

The profile source tree uses the `framework_factored` async engine, dual
dispatch and layout dispatch because those are the bytes in the accepted
298,600-LUT source tree; the tracked `framework` copies were parameterized with
the same defaults for their own profiles.

## K16 default proof

- Every tracked module in the chain declares `ATOMIC_K=16` and none declares
  `ATOMIC_K=8`; `build/k8-full-top-v1/check_profile.py` enforces this.
- Only parameter declarations and explicit named parameter overrides were
  added. No tracked arithmetic, handshake, reset or constraint logic changed.
- K16 endpoint Verilator lint (`rk_jtag_dual_ddr_async`, default parameters)
  exits 0 and has the same 61 warning count as the K8 elaboration.
- The K16 raw core smoke replay passes all eight modes (0/1/2/3/4/5/7/9):
  `build/rknpu-array-core/smoke-iverilog-1793964969840294175/report.json`.

## Build-local K8 profile

`build/k8-full-top-v1/source` is derived from the accepted 185-file
`build/fdv-max-image-v1/source` snapshot. Exactly 14 files differ: the eleven
K8/timing files copied from tracked RTL plus the three build-local
top/platform/endpoint parameter patches. The full source manifest binds all
185 hashes; `check_profile.py` also verifies the tracked repository origin of
every copied file and the exact three-file patch set.

- Profile: `build/k8-full-top-v1/source-profile.json`
- Manifest: `build/k8-full-top-v1/source-manifest.json`
- Source tag: `5e0e41b3` (regenerated after the source commit)
- Top/part/ports: `ypcb_ddr_dual_top` / `xc7k480tffg1156-2` / 242
- Parameters: `ATOMIC_C=32`, `ATOMIC_K=8`

Changed profile files:

| Profile path | SHA-256 |
|---|---|
| `hdl/110/rk_mig_ecc_monitor.sv` | `d167d191fb8276e3b43dfa99b5ed2c398002071e4d1988aba8946fa127445ff7` |
| `hdl/117/platform.sv` | `a32557509d37c024f7be879262e9f4d7df98dbee569a31bd79d76a1ff63e2642` |
| `hdl/120/top.sv` | `6ed4a5699185a35cd5ddf31222a189aa8aba1d171785f9966d30dcb0e9e2188d` |
| `hdl/138/rk_cmac_frame_output.sv` | `3ae232d072451983a08d079c763a7da883380bffe460ce497361f7d211906a25` |
| `hdl/139/rk_cmac_array_datapath.sv` | `79c49f1aa1924b28d632eb4b80e910634abc3335e861cfc1532edcb721f2185d` |
| `hdl/140/rk_cmac_array_front.sv` | `6cabcf697081ba940c5a97f475d6c00f9d26126d083107c441b5f43030d483f0` |
| `hdl/142/rk_cmac_array_core.sv` | `8b5571b75719ca7013823717395bc4c211e0c1deb62d3efb891695bf1e8d45fa` |
| `hdl/143/rk_cmac_array_dma.sv` | `3a67f6ae7a10af380fddd53ce302157b1b147f03f1db0046a92c21fd0ab806e4` |
| `hdl/146/rk_cmac_success_rearm.sv` | `f030ff6e4ac6e28d3ced207de082f68e36e792eed909bcaaf66ab5660b1d7f8b` |
| `hdl/147/rk_cmac_async_engine.sv` | `23b14e8cc3749bd79e40d833e4a828adfefe7ae2f42f0b8663793a7138ec9955` |
| `hdl/148/rk_dual_async_dispatch.sv` | `f11255554c7dba9a4ae64da63ff8dc87880dd9e06f207da0343fcc34994b9ced` |
| `hdl/150/rk_jtag_dual_ddr_async.sv` | `5b5fa9606679e8eb490e42c2f31b3cba8e050aa7f98db8a0e96a343248ff5d99` |
| `hdl/152/rk_ddr_capacity_owner.sv` | `e16f275f7f21efdb1cbd14319b840525a7a4d79c4313431afe49ad58839b8536` |
| `hdl/framework/01_rk_layout_compute_dispatch.sv` | `ee09b81aff744296faab1ea34320898ad14169ed712c7018c932ea32440dbb6c` |

The synthesis recipe is the accepted `synth.tcl` with only the source prefix
rewritten. The clock periods (20.000 ns SYS, 7.500 ns UI0/UI1), XDC files,
CDC/reset constraints, DRC checks and the 298,600-LUT capacity gate are
unchanged. The only profile-specific change is the structural DSP census:
8 kernels and 256 product DSPs instead of 16/512. Up to three non-product
`rk_cmac_array_front` address-arithmetic DSPs are admitted because the K8
original-OC16 atom arithmetic does not constant-fold them away as K16 does;
the fixed four non-product DSPs (three `rk_cmac_profile`, one `rk_fp16_alu`)
are still required. The gate itself was not changed.

## Validation

| Check | Result |
|---|---|
| `make generated-check` | PASS |
| framework 68-source profile at the pre-PPU K8 source snapshot | PASS |
| framework_factored 68-source profile at the pre-PPU K8 source snapshot | PASS, per-file hashes |
| current framework 83-source C3/C8/padded-C8/minimum/average/indexed/global-MAX candidate profile | PASS, source order and hashes; no synthesis/route qualification |
| current framework_factored 83-source C3/C8/padded-C8/minimum/average/indexed/global-MAX candidate profile | PASS, source order and hashes; no synthesis/route qualification |
| previous 81-source framework_factored Verilator lint/elaboration | Historical result only; predates global-MAX source additions and is stale for current RTL; no physical qualification |
| dual_host 72-source profile | PASS |
| dual_host_factored 72-source profile | PASS |
| dual_host_shared_cacc 72-source profile | PASS |
| maintenance_fi 72-source profile | PASS |
| dual_host_maintenance_fi 82-source profile | PASS |
| K8 profile static check | PASS, 185 files, 14 changed, tag `5e0e41b3` |
| ECC monitor portable, Icarus 13.0 | PASS, 30 cases |
| ECC monitor portable, Verilator 5.048 | PASS, 24 cases |
| Capacity BIST, Icarus 13.0 | PASS |
| Capacity BIST, Verilator 5.048 | PASS |
| Capacity service unit tests | PASS, 7 tests |
| Monitor runner unit tests | PASS, 9 tests |
| K8 original-weight core+DMA, Icarus 13.0 | PASS: 24 operand frames, 6912 reads, 64 writes, 8 output frames; modes 0 and 2 |
| K8 original-weight core+DMA, Verilator 5.048 | PASS: same counts |
| K8 endpoint elaboration, Verilator 5.048 | PASS, 61 warnings (same as K16) |

The K8 replay reads the unchanged original K16/OC16 weight BO
(`sha256 97279b0f...`) and compares every read/write and gap sentinel. Its
command BO hash is `457f2d8a...`; the re-chunked K8 write list is byte-identical
to the historical repacked-weight K8 result.

## Synthesis

The accepted recipe was run with
`RK_SHARED_DATA_CONSTRAINED_ROOT_REVIEW=APPROVED` on Vivado 2026.1. It
completed elaboration, constraints, `opt_design`, DRC/CDC reports and the
298,600-LUT gate. The post-opt top row is:

| Resource | Value |
|---|---:|
| Total LUTs | 167,092 |
| Logic LUTs | 162,950 |
| LUTRAM | 3,568 |
| SRLs | 574 |
| FFs | 49,988 |
| RAMB36 | 0 |
| RAMB18 | 0 |
| DSP48E1 | 263 |

The 298,600-LUT gate **passes** with a margin of 131,508 LUTs. The pre- and
post-opt census both report 8 kernels, 256 product DSPs, 263 total DSPs
(7 auxiliary: the fixed four plus three K8 front address DSPs) and 242 ports.
The K16 accepted synthesis for comparison used 298,286 LUTs, 66,581 FFs and
516 DSPs.

Evidence:

- `build/k8-full-top-v1/impl-synth/post_opt_utilization.rpt`
  (`sha256 52d0a2f4...`);
- `build/k8-full-top-v1/impl-synth/constrained_synthesis_facts.tsv`
  (`sha256 480f5c51...`);
- `build/k8-full-top-v1/impl-synth/synth.log`
  (`sha256 b2ef0540...`);
- `build/k8-full-top-v1/impl-synth/post_opt.dcp`
  (`sha256 57be9e5b...`, 108 MB, retained for the next place/route step);
- `build/k8-full-top-v1/synthesis-report.json`.

Recipe-only corrections during the synthesis gate, with no RTL or constraint
change:

1. the first run stopped at `synth.tcl:294` because the `shared_census` Tcl
   procedure did not declare `expected_kernels` as global; the procedure now
   declares the profile globals;
2. the second run stopped at `synth.tcl:272` because the first attempt's
   `constrained_synthesis_facts.tsv` was still present and the recipe opens it
   with `CREAT EXCL`; the failed-run outputs were moved to
   `impl-synth/failed-excl-v2/` and the recipe rerun;
3. the third run reached the census and showed 8 kernels / 256 product DSPs
   but 263 total DSPs; the extra three are `rk_cmac_array_front` address
   arithmetic that K16 constant-folds away. The census now requires the four
   fixed auxiliary DSPs plus at most three front address DSPs. The final run
   passes both pre- and post-opt.

No clock, XDC, CDC, reset, DRC or electrical constraint was weakened. These
are post-opt synthesis estimates, not routed timing signoff.

## Full-top K8 place/route

The guarded place/route and final audit completed on 2026-11-06 with Vivado
2026.1. The run used the source-bound post-opt checkpoint and the accepted
place/route/corrective/final-audit scripts byte-identically; clocks, XDC,
electrical policy, CDC checks, DRC rules and timing constraints were not
weakened. All four stages returned exit code 0 and the wrapper printed
`READY_FRESH_PLACE_ROUTE_CORRECTIVE_AND_FINAL_AUDIT`.

| Result | Value |
|---|---:|
| Global setup WNS / TNS | **+0.108 ns / 0.000 ns** |
| Global hold WHS / THS | **+0.052 ns / 0.000 ns** |
| Pulse width WPWS / TPWS | **+0.264 ns / 0.000 ns** |
| Failing setup / hold / pulse endpoints | **0 / 0 / 0** |
| 133.333 MHz C1 UI (`clk_pll_i_1`) WNS / WHS | **+0.108 ns / +0.052 ns** |
| 50 MHz CMAC (`sys_clock`) WNS / WHS | **+0.790 ns / +0.054 ns** |
| Fully routed nets / routable nets | **251,328 / 251,328** |
| Routing-error nets | **0** |
| Default DRC | **0 errors; warning-only** |

The default DRC report contains 1,054 warning checks: DPIP-1 (526), DPOP-1
(263), DPOP-2 (263), and REQP-1709 (2). The timing report says all user
specified constraints are met. `check_timing` found zero unconstrained
internal endpoints, no-clock pins or combinational loops. It also reports 18
DDR DQS inputs and two DDR reset outputs without explicit I/O delays, and
three LED outputs with no output delay that are false-pathed; these are visible
and were not altered. The CDC report was generated but is not represented as an
independent CDC signoff here.

The routed checkpoint is `build/k8-full-top-v1/impl-place/post_route_aggr.dcp`
in the `k8-full-top` worktree, SHA-256
`a65d0e9195e22e927d61fe9411c8d6fc8082914b09247041c00dab1a5e99056a`. It was
derived from post-opt DCP `57be9e5b...` and source manifest
`5e0e41b3...`; the complete machine-readable result is
`build/k8-full-top-v1/implementation-report.json` in the main workspace. This
route profile is the 185-file K8 source snapshot from revision `a61b96f`; the
separately merged standalone PPU leaves, C3 raw-command DMA and RKPP bank are
**not included** in this routed image. The current main-workspace framework
candidate has a simulation-tested owned dispatch path, but the separate K8
worktree/image has not been updated or requalified with it; see
[the C3 raw-command profile evidence](PPU_C3_RAW_PROFILE.md).

## Offline image emission and audit

The emitted image is bound to K8 worktree revision `a61b96f0a60a2ccb1c8d13e99e113eb75ec097ba`, profile tag `5e0e41b3`, source manifest SHA-256 `5e0e41b3eef984d1a43d4384ee63bec5b2dcbd70a6144f92e40ec893aeeb4400` (profile JSON SHA-256 `cf277100f603cb79b0e8953d055a3ac24ba7bae88fadbd8ef445e238d9a1d9f3`). The implementation report SHA-256 is `f4c26f069f12fc528d17453b36156d8d565883a2b0ae0275f55f8868285d87e7`. Vivado was `2026.1`, SW Build `6511674`.

The complete source-bound receipt package is discoverable in the main workspace at `build/k8-full-top-v1/emission-run-k8-v1/`. It is a byte-preserving copy of the original worktree-local package; its `checksums.sha256` verifies the preserved files.

The exact final route artifacts cited by that report are:

| Artifact | SHA-256 |
|---|---|
| `final_timing.rpt` | `1552131176c039831e4dba038a206abd587de66a6a71a5ddbc2fa862c19e0685` |
| `final_default_drc.rpt` | `e8790396632bf4735c6d543d5d40ab4394501e0d2b78b75784660fdb8d4f59c0` |
| `final_route_status.rpt` | `a9ac05277e4f99601858c6a3900fa80c08e50193153ef73ad232024acb676c3f` |
| `final_pulse_width.rpt` | `e378ba550ab9053224c7afc8d63bbffa04a025c6f352ea890be76f9e66fdc986` |
| `final_check_timing.rpt` | `df6cfb918523427e0479e029c60d29e706e34e5fa61546772df18ace5f7d9464` |
| `final_cdc.rpt` | `811d776f6da5cf8f54ab63909e642cdbcf390c975bf7c397f9ccff4d6897de74` |
| `final-audit.log` | `6ab6683fcf32336494da99cd38f0824868481d8033a421850bb3c7652eab9a6d` |

Default DRC has zero errors and critical warnings. The accepted warning inventory
is exact and unchanged by the emitter: `DPIP-1` 526, `DPOP-1` 263, `DPOP-2`
263, `REQP-1709` 2 (1,054 total). The bitstream-check DRC report independently
matches the same rules, severities and counts. The design/part, all 242 ports,
configuration voltage/CFGBVS, zero waivers, zero black boxes, full-route status,
two BSCAN chains, capacity owner and startup-reset inventory were retained and
checked; setup/hold/pulse and electrical acceptance were not relaxed.

Build-local `emit_sys.tcl`, `run_emission.sh` and `audit_sys_bitfile.py` emit
only into the fresh `emission-run-k8-v1` directory and reject a pre-existing
directory. They are source-bound to the original K8 worktree revision and are
not a command to re-emit from current `main`; their revision/profile/checkpoint
gates must be satisfied by any future run. Emission used the source-manifest
tag as `USR_ACCESS`. The resulting
bitstream is 18,735,214 bytes, SHA-256
`1f9128afae59c617d5c21a5672d9a1ababae51528718d8308f4bf1c64e7e373a`; the emitted
image checkpoint SHA-256 is
`95180728ee7d23d8f77e984f6c8bc7680f45fff640c3b10726007e5951affa44`. The
independent read-only audit passes container, source tag, IDCODE `0x03751093`,
`USR_ACCESS=0x5e0e41b3`, packet bounds and no-IPROG checks (545 packets and
4,683,168 FDRI words). The preserved receipts and complete checksum list are
under `build/k8-full-top-v1/emission-run-k8-v1/`, including `emission-report.json`,
`bitfile-audit.json` and `checksums.sha256` (SHA-256
`f11bfa5ebbcfd31c2269d199745e516dbf016247c84ca415888980c2d1b16c30`).

The first post-emission receipt collectors incorrectly counted the echoed Tcl
command as a second marker substring. Vivado had returned 0, completed
`write_bitstream`, and logged exactly one standalone PASS line. The original
runner, auditor and preparations are preserved with the recovery receipt; only
the two collectors were corrected to count exact marker lines, then the
independent bitfile audit passed. Vivado was not rerun for this receipt
correction.

Audit scope remains strictly offline: software CRC validation is
`NOT_CHECKED`; programming and physical hardware are `NOT_RUN`; hardware access,
programming and flash are all false. This does not qualify FPGA behavior, timing
on hardware, or an inference release. The separately merged standalone PPU
leaves, the C3 raw-command DMA and RKPP bank are not in this image. The source-level and application limits in
[K16 control timing repair](K16_CONTROL_TIMING_REPAIR.md) and the rest of this
document remain applicable.
