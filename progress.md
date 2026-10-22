# Project progress

Updated: 2026-10-23 (Asia/Hong_Kong)

## Current preparation direction

The user selected Vivado using OpenTPU's setup as the reference and retired
openXC7 placement/routing from this continuation. Preserve all historical
artifacts and the stopped-run evidence below. Do not resume openXC7 or
OpenTPU's abandoned build. The current scope is documentation, review, fixes
and preparation only; do not start a Vivado build or program the FPGA/flash.

Keep the full C32/K16 DSP-prefix candidate with 512 parallel CMAC products.
`python3 tools/cmac/vivado_dsp_prefix_array.py prepare` is the preparation
entry point: source-profile and generated-ROM checks and source/Tcl snapshots,
without validating numerical parents or invoking Vivado. The `synth` and `run`
actions are not authorized during this pass. The small EW top remains a separate regression
target rather than a substitute for the requested full target.

The preparation-only artifacts are
[report.json](build/rknpu-dsp-prefix-array-vivado/prepare-1792696631656679983/report.json)
and its adjacent `build.tcl`, status `PREPARED_DSP_PREFIX_ARRAY_VIVADO_ONLY`.
The [read-only parent audit](build/review-all-20261022T190646Z/cmac-vivado-parents-readonly.json)
rejects the saved area/native/mapped/board prerequisites because their bound
`tools/cmac/vivado_array.py` hash predates the reviewed banner-parser fix.
Preserve that rejection; fresh source-bound prerequisites are needed before
a later build. The preparation artifact does not admit synthesis or inherit
an earlier numerical/physical pass.

Read-only inspection found the Vivado settings/launcher and a local license
file on 2026-10-23. Use OpenTPU's normal `VIVADO_ROOT`/`settings64.sh` shell
setup, documented in `docs/FPGA.md`. Current license checkout is untested;
the recorded 2026-10-09 pre-synthesis license failure remains historical.
No new synthesis, implementation, timing/DRC, bitstream or hardware pass is
claimed by this preparation.

## Current review validation

The fresh [`make -j2 test` retry](build/review-all-20261022T190646Z/final-production/production-validation.json)
completed PASS, exit 0, in 296.016 seconds at 2026-10-22 19:26:14 UTC
(2026-10-23 03:26:14 HKT). It passed 57 unit methods, 1,087,299 C++ comparisons,
both 247-entry EW suites and all three raw-product CMAC benches under each
simulator. All five reports match the unchanged before/after source manifest
`bb6a5366036d6d951b74a1c48b018b4634f9261cee02a674cee4096fc6903d2d`.
All [82 observed memory images](build/review-all-20261022T190646Z/final-production/memory-image-comparison.json)
match byte-for-byte between Verilator and Icarus.

The [first whole attempt](build/review-all-20261022T190646Z/production-validation.json)
remains FAIL at the Verilator packed-buffer parser portability issue. Its
failure evidence is preserved; the corrected parser received actual runtime
checks under both simulators before the fresh whole-suite retry. No Vivado
build, native openXC7 implementation or hardware operation ran. Production
simulation PASS does not clear the separate full C32/K16 stale-parent build
admission failure, establish RK numerical compatibility or provide physical
timing/DRC/bitstream readiness.

The sections below retain the 2026-10-10 stopped-run handoff and its evidence.

## Scope

This remains a strict FP16 elementwise slice / FPGA preparation effort, not a
complete RK3588 backend or completed soDLA fork. Raw command words remain the
execution boundary; unsupported fields and operations must continue to fail
explicitly. No board programming or flash operation has been performed.

## Verification evidence

- The source-identical production run recorded in
  `source_identical_production_opt0_preflight_actual_20261009.md` completed
  with all five fresh reports and final source/input checks passing. It reports
  both 247-entry elementwise suites, all three CMAC benches under each of two
  simulators, 49 host/model methods, and 1,087,299 C++ comparisons passing.
  This is software/simulation evidence only, not RK silicon or FPGA acceptance.
- The full-board native pack report is
  `build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791562129604551098/report.json`.
  It passed pack tool execution but explicitly classifies itself as resource
  characterization, not placement fit or signoff.
- The current full-board native analytic placement attempt is recorded at
  `build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791576906281335280/report.json`.
  Its last pre-stop state was `RUNNING` at `native_place` (started
  2026-10-09 20:15:06 UTC), with nextpnr still in the main analytical placer
  for 419,259 cells. It is a place-only run (`--no-route`). It has produced no
  route, timing/DRC signoff or bitstream. This user-requested stop is an
  interruption, not a native placement failure or a fit verdict. The runner
  now records `FAIL` with return code `-15` after SIGTERM; both runner and
  nextpnr processes are gone.

## Board electrical reference

The bounded home-project/archive/public-reference follow-up is recorded in
`build/home_configuration_reference_followup_actual_20261009.md`. No board
schematic or measured Bank 0 VCCO / CFGBVS strap was found in the inspected
scope. OpenTPU supplies a candidate `CFGBVS GND`, `CONFIG_VOLTAGE 1.8` pair,
but its own documentation labels these as assumptions; the vendor XDMA report
has both values unset. Keep the electrical gate unresolved. Do not treat the
candidate pair as signoff.

## Remaining gates

The stopped openXC7 placement is retained as historical evidence and is not
the continuation path. A future Vivado build needs a separate instruction;
prepare it without weakening constraints. A
test-ready bitstream still requires successful placement, routing, timing and
DRC review, exact source/input provenance, and resolution of the electrical
configuration gate. No board/RK3588 differential test has been established by
these offline artifacts.
