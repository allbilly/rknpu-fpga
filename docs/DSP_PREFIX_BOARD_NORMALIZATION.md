# Full prefix-board RAM normalization capture

This is diagnostic preparation toward the original C32/K16 FPGA target,
not an accepted board mapping or a bitstream. All sixteen kernels and 512
parallel products, raw command words, arithmetic and 20 ns clock target remain.

The original whole-board mapper completed Yosys execution but failed its
source-specific warning gate. Its [failure archive](../verification/runs/2026-10-06-dsp-prefix-whole-board-diagnostic-failure/index.json)
and [read-only inventory](../verification/runs/2026-10-06-dsp-prefix-board-diagnostic-structure-inventory/index.json)
remain unchanged. The inventory accounts for 288 early temporary-driver
diagnostics and 32 reported RAMB36E1 port-width changes. It does not prove that
discarded input/output bits are safe.

## Capture contract

[capture_dsp_prefix_board_normalization.py](../tools/cmac/capture_dsp_prefix_board_normalization.py)
revalidates the original source, compile inputs, artifacts and independent
array/board parents before running the complete original mapping script.
It adds an export at Yosys's exclusive `check` boundary, then executes the
original remaining synthesis stages. Every source and synthesis command is
retained; literal reversal checks the only script edits.

Before final hierarchy checking, vendor whitebox models still contain processes
that JSON cannot represent. The capture saves the design, blackboxes only the
temporary export view, writes JSON, and reloads the original saved design.
The actual synthesis state is restored before the original final stages run.
The post-capture circuit must match the original completed board export by
every port, primitive parameter and pin/wire incidence, not resource counts alone.

The audit uses named-wire/bit positions to reconcile export-local JSON wire
numbers. Every logged resize must match the actual before/after graph.
Silent constant-only input resizes are recorded too; they are not ignored.
It rejects changes outside RAMB36E1 port normalization, and requires:

- Retained bits and every unrelated connection remain identical.
- Added WEBWE bits are zero and all existing enable bits are retained.
- Discarded input bits are zero, or unknown constants on a write-disabled port.
- Discarded output bits have no cell or top-port consumer and do not alias
  retained outputs.
- Any named wire replaced with zero is one of those proven dead output bits.

This audit does not admit the 288 early temporary-driver notices, prove full
board numerical behavior, or establish physical capacity, timing or DRC.
The original mapper and error expectations are unchanged.

## Actual small control and retained failures

The [small memory fixture](../tests/cmac/dsp_prefix_ram_capture_control.sv)
uses actual Yosys RAM inference, not hand-assembled expected-width cells.
The [saved-view synthesis control](../build/dsp_prefix_ram_stage_saved_view_control_20261007.log)
exits zero. Its [actual wire-identity audit](../build/dsp_prefix_ram_saved_view_wire_identity_actual_audit_20261007.log)
passes all nine port resizes: six logged and three silent constant-only changes.
This is a small RAM check, not a full-board proof.

The [first JSON-export failure](../build/dsp_prefix_ram_stage_control_20261007.log)
is retained with its [original script](../build/dsp_prefix_ram_stage_control_20261007.ys).
The [first naive integer-wire audit failure](../build/dsp_prefix_ram_saved_view_actual_audit_20261007.log)
and [executed audit source](../build/dsp_prefix_ram_initial_audit_source_20261007.py)
are retained separately; export-local integers were not stable signal identities.
The current [ten negative/admission controls](../build/dsp_prefix_board_normalization_wire_identity_controls_20261007.log)
pass, including rejection of live discarded data, merged wires, nonzero padding
and unreported live rewiring. These are software controls, not FPGA tests.

## Full capture execution

The full runner completed with exit zero. Its
[own source-bound report](../build/rknpu-dsp-prefix-board-normalization/1791303221286845998/report.json)
records Yosys 0.65, source `00402839d864...` and actual full mapping execution.
The mapping took 1,785.453 seconds. Its final graph matches the original full
board circuit, retaining sixteen kernels, 512 CMAC DSPs plus three shell DSPs
and six RAMB36E1s. The actual before/after audit verifies **54** port resizes:
32 logged changes and 22 silent constant-only input changes. These comprise
six zero-extended WEBWE ports, 24 constant/disallowed-write input tails and
24 unconsumed output tails. No unrelated connection is changed.

The [independently revalidated archive](../verification/runs/2026-10-07-dsp-prefix-full-board-ram-normalization/index.json)
verifies 254 members and 24,045,247 compressed bytes, SHA256
`902f302c3db398cd524e1497e38e58ce8052af6001a3ed6fe570507f6c57426a`.
The archive repeats the actual normalization audit and original final-circuit
identity check. The original warning gate still rejects the full mapping;
this diagnostic result is not whole-board numerical or physical acceptance.
The [master log](../build/dsp_prefix_full_board_normalization_capture_20261007.log)
records this completed run separately from the original failure.

## Initial temporary-driver fanout

The separate [actual full-board frontend capture](../build/rknpu-dsp-prefix-initial-driver-fanout/1791305786269181565/report.json)
completed in 209.197 seconds with the same 288 initial warning bits and zero
post-clean CHECK problems. Its six [software controls](../build/dsp_prefix_initial_driver_fanout_controls_20261007.log)
pass. All 288 warned bits have real consumers: 122 have one, 102 have four,
and 64 have five. None can be declared unused merely from the clean final
CHECK. The capture preserves both process-lowered and post-clean graphs,
all sixteen imported kernels, and the original raw-command shell.

The corrected [source-bound connectivity audit](../build/rknpu-dsp-prefix-initial-driver-cones/1791306673247975368/report.json)
now verifies all 288 bits. Every cell input is conservatively connected to
every cell output; no selected mux arm or numerical constant is used to prune
the graph. Module outputs/inouts, outputless side-effect cells and retained
cells/nets are roots. All warning cones are disconnected from those roots,
contain only 107 pure `$mux` cells, and are entirely removed by `opt_clean`.
The [14 software controls](../build/dsp_prefix_initial_driver_cones_corrected_controls_20261007.log)
reject live outputs/future state, side-effect cells, unknown purity, kept nets,
inouts, unknown directions and a retained cone. They are not numerical HDL tests.

The initial [tuple-versus-JSON-list harness failure](../build/dsp_prefix_initial_driver_dead_cones_actual_20261007.log)
is preserved with its [executed source](../build/dsp_prefix_initial_driver_cones_initial_executed_source_20261007.py)
and [445-member source archive](../verification/runs/2026-10-07-dsp-prefix-initial-driver-cone-harness-failure/index.json)
before correction. The old failed report is not promoted by the corrected run.

A separate [diagnostic-admission runner](../tools/cmac/admit_dsp_prefix_board_diagnostics.py)
now completes [actual read-only revalidation](../build/rknpu-dsp-prefix-board-diagnostic-admission/1791306879354271482/report.json)
at source `040acb13f113...`. It recomputes both proofs against the actual
captures before accepting their exact 288/32 original warning lines.
Every other source/ABC diagnostic and CHECK result must satisfy the original
strict contract. It then repeats the original independent numerical-parent,
kernel-identity and remaining whole-board structural gates. Its
[eight controls](../build/dsp_prefix_board_diagnostic_admission_controls_20261007.log)
pass, including rejection of unknown/repeated/missing notices and changed
widths, CHECK results or parents. The independent numerical-parent and
remaining structural gates pass. Counts remain 442,838 LUT primitives,
17,310 flip-flops, 515 DSPs and six RAMB36E1s. The original failed report and
mapper are unchanged. This separate structural/diagnostic admission is not
full-board numerical replay, physical implementation or RK compatibility.

The independent archive revalidation now completes. Its two preceding counter
harness failures are retained with [implementation-only partition source](../build/dsp_prefix_board_diagnostic_archive_initial_executed_source_20261007.py)
and [raw-library source](../build/dsp_prefix_board_diagnostic_archive_raw_library_executed_source_20261007.py),
plus their [first](../build/archive_dsp_prefix_board_diagnostic_admission_20261007.log)
and [second](../build/archive_dsp_prefix_board_diagnostic_admission_corrected_20261007.log)
actual logs. The corrected builder uses the original audited timing-only
library view and its exact qualifier audit; no counter check is weakened.
No completed archive is claimed from either failed attempt. The
[completed independently revalidated archive](../verification/runs/2026-10-07-dsp-prefix-board-diagnostic-admission/index.json)
repeats the actual dead-cone, RAM, final-circuit and remaining structural audits.
Its 471 members and 39,309,330 compressed bytes are independently checksum
verified, SHA256 `3ea66c5af15d0e8ec8ed029e04bf61e86ab2c83b11225dfc3c1ccfb0c321f97f`.
Original FAIL parents and both counter failures remain preserved.

## Next mapped-board numerical preparation

The [actual original-bench binding probe](../build/dsp_prefix_mapped_board_bench_binding_actual_20261007.json)
refuses this existing mapped graph: twelve required observations are missing,
dead or recoded, including an eleven-bit state instead of the original four
bits. The original bench's assertions, force points and all nine modes are
unchanged. An error-code substitution or guessed FSM decode is not supplied.

The new [observation-retention frontend](../tools/cmac/prepare_dsp_prefix_observed_board.py)
preserves all 22 original signals and disables only state recoding before
optimization. It reuses the same complete native shell and literal imported
kernel, with all sixteen kernels/512 products. Four
[script controls](../build/dsp_prefix_observed_board_preparation_controls_20261007.log)
pass. Its [actual frontend report](../build/rknpu-dsp-prefix-observed-board-preparation/1791307426641654447/report.json)
now completes actual Yosys 0.65 execution in 174.340 seconds at source
`3cfdd9b91aaf...`. All 22 observations and the original four-bit state are
preserved, with unchanged imported-kernel circuit identity and all sixteen
kernels/512 products. This is frontend preparation only, not a remapped or
numerical PASS.
Any later remapping must establish its own exact source/circuit/diagnostic
and numerical evidence; old mapping acceptance cannot be transferred.

### Fresh remapping and model/export controls

The [fresh observed-board mapper](../tools/cmac/map_dsp_prefix_observed_board.py)
imports the completed frontend, preserves all sixteen kernels/512 products
and all original observations, and recomputes the actual RAM/diagnostic gates.
Its first attempt correctly fails before synthesis because the help probe
omits the flatten contract required by the stage parser. The
[763-member executed-source failure archive](../verification/runs/2026-10-07-dsp-prefix-observed-mapping-help-guard-failure/index.json)
is checksum-verified before correction. The corrected probe includes both
help commands; [ten controls](../build/dsp_prefix_observed_board_mapping_corrected_controls_20261007.log)
pass. The [fresh actual complete-board mapping](../build/rknpu-dsp-prefix-observed-board-mapping/1791308955335106261/report.json)
now completes in 2,634.549 seconds at source `94527de2feb6...` with Yosys 0.65.
All sixteen literal kernels/512 CMAC DSPs, 22 original observations and native
four-bit state remain. It recomputes all 54 safe RAM resizes (32 logged),
accepts no initial-driver notices, and records four zero-problem CHECK results.
Counts are 445,816 LUT primitives, 17,519 flip-flops, 515 DSPs (512 CMAC plus
three shell) and six RAMB36E1s. The 294,538 logic-cell estimate is not packed
fit or timing evidence. This is full mapping/structure acceptance only;
whole-board numerical replay and physical implementation remain unverified.
The [completed source-bound mapping archive](../verification/runs/2026-10-07-dsp-prefix-full-observed-board-mapping-pass/index.json)
verifies all 767 project input/output/snapshot members and 60,467,297 compressed
bytes, SHA256 `0e8f03bfc0d1b3026a3e70bea0e5ffcf006cbdacbe8eb358b0264b44f60cda49`.
Installed Yosys/ABC/datadir input hashes are checked before and after archival;
they are recorded, not bundled as an installable toolchain. This freezes the
actual completed mapping, not an independent synthesis or arithmetic rerun.

The separate [literal DSP exporter](../tools/cmac/export_dsp_prefix_board_netlist.py)
adds only the five actual DSP string settings, retaining the old non-DSP
exporter unchanged. Its initial real roundtrip refuses private-instance-name
conversion; the [failed executed source and graph](../verification/runs/2026-10-07-dsp-prefix-board-export-private-name-failure/index.json)
are preserved before applying the existing reversible alias helper.
The [corrected actual Yosys control](../build/rknpu-dsp-prefix-board-export-control/1791310216574124677/report.json)
passes at source `8d7ae8d96419...`, with all 32 kernel and three shell DSP
configurations, literal parameter/pin/wire identity, and no diagnostic.
[Six software controls](../build/dsp_prefix_board_export_corrected_controls_20261007.log)
pass. These extracted boundaries are control fixtures, not full-board export
or arithmetic acceptance.

The [pinned UNISIM DSP/CARRY corpus runner](../tools/cmac/check_dsp_prefix_unisim_models.py)
retains the original seed, 4,259,904 signed/mantissa DSP cases, 1,024 binary
and 1,048,576 four-state carry cases, and default global startup. The
[first actual failure](../verification/runs/2026-10-07-dsp-prefix-unisim-initial-unknown-failure/index.json)
preserves its frozen model, bench and executable: the initial zero operands
never trigger the vendor input mux, leaving P unknown. The marker-only
DSP-negative check wrongly accepted that unknown; the following carry-negative
correctly refuses it. No model or RTL arithmetic is changed. A
[read-only probe](../build/dsp_prefix_unisim_initial_unknown_probe_actual_20261007.log)
shows the exact unknown muxes and recovery after an operand transition.
The corrected harness adds only a startup settling transition before the
unchanged corpus, and requires the exact known correct first result in both
negative tests. [Seven controls](../build/dsp_prefix_unisim_model_corrected_controls_20261007.log)
pass. The [settled actual run](../build/rknpu-dsp-prefix-unisim-model-control/1791309459572522911/report.json)
now finishes FAIL in its positive: both exact known-result negatives pass,
but the unchanged old four-state oracle refuses case 1,027, `got=0/0 expected=0/X`.
Its [independently verified failure archive](../verification/runs/2026-10-07-dsp-prefix-unisim-legacy-carry-oracle-failure/index.json)
binds literal original-corpus control flow and exact simulation time to
4,259,904 completed DSP and 1,024 binary carry comparisons before the first
Z-input discrepancy (four-state index three). Both original full-corpus
reports remain FAIL. No complete old-oracle four-state PASS is claimed.

Vendor carry source also has explicit Z-input defaults and a bitwise carry
network, not the old model's ternary merge. The separate
[vendor truth-table runner](../tools/cmac/check_dsp_prefix_unisim_carry_truth.py)
checks an independent four-valued truth table and counts disagreements with
the unchanged old oracle. [Four controls](../build/dsp_prefix_unisim_carry_truth_controls_20261007.log)
pass. Its [actual complete run](../build/rknpu-dsp-prefix-unisim-carry-truth/1791309718773637131/report.json)
now passes 1,024 binary and 1,048,576 four-state comparisons against its
independent vendor truth table, with its exact known-result wrong-golden negative.
The 1,013.224-second positive records **415,001 disagreements** with the unchanged
old four-state oracle, first at case three; the entire binary corpus agrees.
Source is `1cb2df295368...`, using Icarus/vvp 13.0 and unchanged pinned models.
Its [independently verified archive](../verification/runs/2026-10-07-dsp-prefix-unisim-carry-truth-pass/index.json)
preserves the explicit non-equivalence. This is a simulation-model distinction,
not a donor arithmetic defect or whole-board numerical/physical acceptance.
The [combined 27-method preparation control suite](../build/dsp_prefix_unisim_export_combined_controls_20261007.log)
also passes without skips. No old four-state expectation, full-board assertion,
fault mode, electrical constraint or physical gate is weakened.
The [newest fresh production regression](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791310099280059265/report.json)
now completes PASS after 2,675.892 seconds in its source-identical workspace:
49 Python tests, 1,087,299 numeric comparisons, both 247-entry RTL suites,
all three product benches per simulator and 82 equal memory images.
Production source remains `09f1c3f65ba9...`; existing outputs/mapping inputs
remain intact. This actual production rerun does not validate nested prefix RTL.

## Separate full-prefix mapped-board replay

The [DSP-profile runner](../tools/cmac/test_dsp_prefix_observed_mapped_board.py)
revalidates its own completed observed-board mapping, original C32/K16 native
numerical parents, actual RAM normalization and kernel/shell circuit structure.
It uses a [separate model inventory](../tools/cmac/dsp_prefix_unisim_board_models.py):
all 32 kernel/three shell DSP configurations are checked, each vendor model
is pinned and copied unchanged, and default global startup remains enabled.
The original non-DSP model inventory/runner still refuses DSP hardware.
The completed independent vendor carry truth report is revalidated with its
real negative and its explicit four-state non-equivalence; the old failed
oracle is not promoted or changed.

[Eight fail-closed controls](../build/dsp_prefix_observed_mapped_board_controls_20261007.log)
pass. The [first full-size attempt](../build/rknpu-dsp-prefix-observed-mapped-board/1791313743637550758/report.json)
completed its own source-bound parent checks and the real Yosys
roundtrip, with exact port-bit, primitive-parameter and pin/wire incidence
identity. Its executed source is `8f1055fe4bb5...`; Yosys 0.65 exports the full
circuit in 138.954 seconds. That supervisor was interrupted during Icarus/vvp
13.0 compilation; a fresh [host-wide process observation](../build/dsp_prefix_observed_mapped_board_interruption_observation_20261007.json)
finds no remaining compiler or supervisor. Its stale RUNNING/compile report
is preserved unchanged in the [897-file interruption archive](../verification/runs/2026-10-07-dsp-prefix-observed-mapped-board-interruption/index.json),
SHA256 `b879f1c9feb02f213b6a28b52e2a50901844d5a94fbb11f933e3bf4e696b77c8`.
The 1,054,777,344-byte partial simulator file is evidence of interruption,
not an accepted compiled executable or an RTL failure. No numerical mode ran.
An [unchanged-source fresh retry](../build/dsp_prefix_observed_mapped_board_retry_launch_20261007.json)
ran under `rknpu-dsp-prefix-observed-mapped-board-retry-20261007.service`,
with a separate [master log](../build/dsp_prefix_observed_mapped_board_retry_actual_20261007.log)
and newly created output directory. Its [fresh report](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/report.json)
has executed source `340b978a3717...`; Yosys export completes in 115.705 seconds
with unchanged circuit identity. Icarus 13.0 compilation now returns zero after
3,369.436 seconds and passes its unchanged diagnostic gate. The
[immutable compile-only observation](../build/dsp_prefix_observed_mapped_board_retry_compile_pass_20261007.json)
independently hashes the accepted executable as
`b1ca3a1f5f5292bc84ec45f9986863437a033d4c4ee3627f7fe98ad9d72b01f3`.
The real same-executable first-output-golden-bit negative completes its
expected rejection with return code 1 after 6,689.497 seconds. Its
[actual log](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/negative.log)
records exactly the intended first-output mismatch; this is a comparator
negative, not a demonstrated arithmetic failure. At the 2026-10-07 11:20 UTC
live-process observation, the retry was in positive mode 0 with no completed
positive modes. It subsequently ended as FAIL at 13:44:26 UTC with
`TimeoutExpired` on that command's unchanged 14,400-second wall-time budget;
the command records 14,405.105 seconds including termination. Its positive
log is empty and its return code was not recorded, so neither a numerical
mismatch nor a positive PASS is inferred. The service exits with supervisor
status 1, and no supervisor or simulator remains.
The [903-member terminal failure archive](../verification/runs/2026-10-07-dsp-prefix-observed-mapped-board-timeout/index.json)
independently verifies all stored member hashes, source/circuit/bench bindings
and pinned model bytes. Its 326,660,967-byte archive has SHA256
`742881ea8675e7e6bd5a16088a4e9c20c6aebeed9fcb325164af83c7a0479813`.
The original report remains FAIL; zero positive modes completed. All nine
original modes remain required before numerical acceptance; the negative
does not substitute for them. A longer-budget replay would require a new
source-checked run, not a timeout edit or a relabeling of this failure.
The [initial runtime observation](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/runtime_mode0_stack_observation.json)
records simulated time advancing from 0.97 to 6.31 microseconds. Its
[independently checked follow-up](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/runtime_mode0_stack_followup_observation.json)
records 184.09 microseconds. These bounded read-only scheduler samples
establish time advance only between their recorded observations, not command,
output, mode or numerical-suite completion. Each debugger attachment detaches
cleanly and the simulator resumes; no source, fixture, timeout or acceptance
rule changes. The original observations remain separate from the execution report
and have no numerical or physical acceptance flags set.
A [scoped host memory guard](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/host_memory_guard.json)
sets this service's soft/hard limits to 26/27 GiB. Host memory recovered and
the compiler had already exited before the guard was applied; no compiler,
RTL, fixture, hardware-size or acceptance rule was changed to obtain its PASS.
The guard remains an execution-environment limit, not FPGA area or timing proof.
Only
source-evidenced wire references may change in the original bench; its
unknown-readback case, raw QWORDs, full transaction counts, reset phases,
fault codes and 20 ns/full-512-product target are preserved.
No full mapped-board numerical PASS is currently claimed.

```sh
python3 -m unittest discover -s tests/cmac \
  -p test_dsp_prefix_observed_mapped_board_control.py -v
python3 tools/cmac/test_dsp_prefix_observed_mapped_board.py
```

The recorded retry is now terminal. Before any fresh run, check actual process
and service state to avoid duplicates; a saved RUNNING report alone is not
liveness proof.

```sh
systemctl --user show rknpu-dsp-prefix-observed-mapped-board-retry-20261007.service \
  -p ActiveState -p SubState -p MainPID -p Result -p ExecMainCode -p ExecMainStatus
```

The separate [terminal-run archiver](../tools/cmac/archive_dsp_prefix_observed_mapped_board.py)
has [three passing admission controls](../build/dsp_prefix_observed_mapped_board_archive_controls_20261007.log).
It refuses live or cross-profile runs, preserves a failure as failure, and
requires exact export and all nine modes plus the real negative for a PASS.
Actual packaging additionally rechecks model bytes, literal export, wire-only
bench edits, execution/input hashes and completed logs, then independently
verifies every tar member hash. These controls are not a completed archive
or another numerical run. A terminal bundle can be made only after the
current supervisor finishes; it neither reruns HDL nor authorizes hardware.
The interruption bundle above uses a separate one-off builder and explicitly
does not satisfy or weaken this terminal-run admission gate. Fresh generated
checks and all three terminal-archive controls pass after preservation.

## Source-checked longer-budget continuation

The separate [continuation](../tools/cmac/resume_dsp_prefix_observed_mapped_board.py)
accepts only the archived full-profile mode-0 wall timeout above. It rechecks
the original source/circuit/bench/model contract and every archive member,
then reuses the exact accepted compiled executable without re-exporting,
recompiling or changing HDL. The first-output-bit negative and all nine
original board modes execute afresh. Input/executable hashes and the actual
runtime program identity are checked around every simulation. The new
24-hour per-command host wall budget does not change HDL timeouts, clock,
transaction/error expectations or physical gates; the old FAIL is preserved.
[Actual qualification](../build/dsp_prefix_observed_board_resume_qualification_20261007.json)
records Python 3.14.5, eight new continuation controls, eight original replay
controls, three original archive controls and generated checks, all returning
zero. These software fixtures, including damaged archive-member rejection,
are not HDL or physical acceptance.
The [14:15 UTC launch observation](../build/dsp_prefix_observed_board_resume_launch_20261007.json)
confirms two live supervised jobs: the [mapped continuation](../build/rknpu-dsp-prefix-observed-board-continuation/1791382468965621354/report.json)
in admission and a separate [complete production make test](../build/rknpu-dsp-prefix-pin-cone-production-regression/1791382469904905494/report.json)
in a literal source snapshot. Existing results and replay fixtures are not
overwritten. Neither running job is a PASS. No duplicate should be launched.
That launch observation is historical, not the current terminal status of
the production job. Its report now records **FAIL** at
`2026-10-07T14:57:36.700021+00:00`, with actual make exit 2 after Verilator's
product-front compilation hits its unchanged 600-second host wall budget.
Two product benches completed; the third was not numerically executed.
A subsequently linked binary does not establish successful compiler return
or repair this failure. The production source remains `09f1c3f65ba91220f`;
earlier completed native passes are not copied forward as this run's result.
The mapped continuation is independent and its replay inputs are unchanged.
The [terminal production failure archive](../verification/runs/2026-10-07-resume-production-compile-timeout/index.json)
preserves and verifies all 2,798 selected source/report/artifact members;
neither the make failure nor the compiler's unknown return is relabeled PASS.
The continuation's distinct success profile requires a fresh negative and all
nine modes; the original terminal archiver intentionally does not admit that
new profile. Its separate [continuation archiver](../tools/cmac/archive_dsp_prefix_observed_board_continuation.py)
requires a terminal admission-bound report, rechecks the original failed
parent/bundle and unchanged cached executable/model contract, and verifies
fresh own-directory logs against exact runtime argv, fixture cwd, input
identities and all original transaction/error counts. A failure stays FAIL.
The [actual archive qualification](../build/dsp_prefix_observed_board_continuation_archive_qualification_20261007.json)
records seven new archive controls plus the previous 19 controls, all passing,
and generated checks. The actual archive CLI rejects the RUNNING continuation
with status 1 and creates no bundle. These are software/gate checks only;
the running replay's source remains unchanged. No terminal continuation
bundle or full mapped-board, physical or RK-silicon PASS is inferred.

```sh
python3 -m unittest discover -s tests/cmac \
  -p test_dsp_prefix_observed_board_resume_control.py -v
systemctl --user show rknpu-dsp-prefix-observed-board-continuation-20261007.service \
  -p ActiveState -p SubState -p MainPID -p Result -p ExecMainStatus
```

To start a separate source-bound capture after confirming no existing job is live:

```sh
python3 tools/cmac/capture_dsp_prefix_board_normalization.py
python3 -m unittest discover -s tests/cmac \
  -p test_dsp_prefix_board_normalization_control.py -v
make generated-check
```

Full Vivado, confirmed configuration-bank electrical settings, placed capacity,
setup/hold timing, DRC and reviewed bitstream emission remain required.
Nothing in this capture programs the FPGA or flash.
