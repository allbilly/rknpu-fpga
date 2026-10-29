# DDR reset and write-fence components

These components advance the plan's DDR source work beneath the unchanged raw
command endpoint. They add reset sequencing and a bounded readback-fence
protocol. They are separate components, with no joined DDR/PCIe shell, buffer
initialization engine or hardware result. The full C32/K16 array remains the
512-product target; no arithmetic, backend encoder or runtime layout path changes.

## Owned reset sequence

`rtl/ddr/rk_mig_reset_coordinator.sv` owns a new boundary comprising SYS50 and
both MIG UI clock domains. The archived controller's shared active-low
`sys_rst` reaches both controllers' PLL/MC/PHY/UI reset paths; the separate
`c0_aresetn` and `c1_aresetn` inputs cover their AXI/control interfaces. A reset
request therefore affects both channels even when application data uses C0.
The [source contract](../fpga/ddr/xdma_lifecycle_contract.json) binds those paths.

Assert `cfg_reset` at bootstrap and release it synchronously to SYS, such as
from the existing registered startup reset. No R28 input is consumed. Later
`reset_req_valid && reset_req_ready` handshakes explicitly request another
sequence. Calibration loss never initiates an automatic reset.

The coordinator holds shared MIG reset and all owned clients for 64 SYS cycles,
then releases MIG reset independently of UI status. Each epoch clears both
clock-domain witnesses asynchronously. Actual UI-reset assertion must be
observed afresh, followed by four fresh local edges with UI reset low in each
domain. Both witnesses cross back to SYS before a registered release permit
crosses into each UI domain. Local reset bridges assert asynchronously and
release synchronously. Completion waits for the actual client-release
acknowledgments, including the SYS branch.

`admission_blocked` remains high through this sequence. All clients must stay
transaction-passive until the barrier completes; reset release can precede
its acknowledgment. This signal gates new admission and must not cancel an
already asserted AXI request. SYS-domain completion/admission signals require
proper synchronization before local UI-domain use. Deasserted admission
blocking supplies only the reset condition; calibration, initialized allocation
contents, ECC health and ownership still govern memory/job admission.

A later UI-reset reassertion or unknown status latches a sequence fault and
blocks admission. Once release was published, released client resets and MIG
reset remain unchanged until another explicit request. Unreleased branches
stay held, including when a stopped clock resumes with an old permit in its
pipeline. Earlier qualification failures keep resets asserted. Recovery is
explicit, with no rollback of memory writes.

| Reset-local code | Meaning |
|---:|---|
| 1 | Missing fresh assertion/clock qualification |
| 2 | Missing client-release acknowledgment |
| 3 / 4 | UI0 / UI1 reset reasserted after release observation |
| 5 / 6 | UI0 / UI1 reset status unresolved |
| 7 | Invalid internal sequence state |

This boundary does not cover the reference BD's MicroBlaze/XDMA clocks or the
USER2 TCK state. Every additional master, adapter or CDC endpoint needs an
audited reset/isolation branch before a joined platform can use shared reset.
The cycle counts are source policy, with physical pulse width, startup,
recovery/removal and routed timing still pending.

### Mapped reset findings and private candidate

The [actual-MIG checkpoint inventory](../build/original-ddr-reset-query/v1/report.json)
and [independent classification](../build/original-ddr-reset-query/v1/root-findings.json)
confirm restart control in all three data stages of six SYS synchronizers.
The UI admission synchronizer also receives a combinational SYS barrier
with multiple state/counter sources. These findings remain visible; they
are not resolved by blanket clock cuts or CDC waivers.

A private source candidate in `build/ddr-reset-candidate/v1/workspace` separates
the six data pipelines from restart qualification. A separate local validity
pipeline prevents samples from a previous epoch from supplying either reset
assertion, fresh-clock or release acknowledgment. Fault timeouts remain
independent of sample validity. The endpoint registers the SYS barrier before
UI synchronization, adding one SYS edge to remote barrier visibility while
retaining immediate local fault/request gating. No arithmetic, command,
ownership, drain or error-code contract changes.

The [fresh boundary controls](../build/ddr-reset-candidate/v1/epoch-controls-v2/report.json)
pass five public-status cases in both simulators, with hold1 and synchronizer
depth5, plus an independent timeout2/depth8 check. A stale-status guard mutant
and a timeout-gated draft both fail for their specified reasons; the original
main source passes the same bench. The original lifecycle matrices also pass:
32 Icarus and23 Verilator cases, plus five parameter rejections per simulator.
The count1 compiler warning was fixed with equivalent33-bit count-plus-one
predicates, retaining all test parameters and warning checks. Initial failed
drafts and tool-launch records remain preserved.

The [new status helper](../build/ddr-reset-candidate/v1/workspace/fpga/ddr/reset_status_cdc.tcl)
requires nine clean chains, exactly27 registers and a registered SYS barrier.
It constrains only one asynchronous source-to-first-D path per chain, retaining
later-stage timing and leaving reset-pin constraints unchanged. Its
[actual original-checkpoint control](../build/reset-status-negative/v1/report.json)
correctly rejects the old restart-mux circuit before applying exceptions.
Fresh [actual-MIG synthesis](../build/original-ddr-real-synthesis/reset-v3/root-synthesis-review.json)
now passes for all118 real HDL sources in1,042.077seconds, without cached
checkpoints or stubs. Its [native CDC comparison](../build/ddr-reset-candidate/v1/mapped-cdc-comparison-v1.json)
shows all six CDC-1 unknown-level findings removed and CDC-10 reduced from13
to12, with no waivers. The six clean status pipelines and registered barrier
account for the seven additional recognized single-bit synchronizers.

The new native endpoint also passes unknown-command and partial-task fault
cases, including the required task count1/UI E5 result. Its
[actual-checkpoint audit](../build/async-ew-clock-mapping/reset-v3-status-v6/root-review.json)
now verifies all nine status chains/27 registers and18 later-stage timing
paths, together with167 job/memory payload bits, four constant error-code
bits and18 job/memory synchronizer stages. Both original-circuit and changed-
clock controls reject as required. The audit queries real clock objects and
checks Vivado's explicit false-path properties for the first D inputs; later
stages retain finite, nonnegative slack and their original20/7.5ns periods.

The candidate remains unpromoted and physically unqualified. The complete
joined matrix, twelve remaining reset/vendor findings and platform timing
are still open. A fresh same-deadline recovery case is running on this new
source; older recovery timeouts retain failed status. Earlier receipts remain
evidence for their original snapshots.

## Same-address fence protocol

`rtl/ddr/rk_mig_write_fence.sv` accepts an epoch's final acknowledged AW byte
address and requests one ordinary aligned 64-byte read at that exact address.
It then requests a fresh snapshot from the [ECC monitor](DDR_ECC_MONITOR.md).
The [source ordering argument](../fpga/ddr/xdma_retirement_contract.json)
requires exclusive C0 ownership, NORM ordering, one rank and the pinned
single-beat profile. An unrelated scratch address does not establish the same
ordering condition.

The caller must capture the real final AW address from the same epoch and
establish all these preconditions before transferring a fence descriptor:

- At least one write was issued; every producer B and R response completed.
- The epoch is sealed, its memory owner is exclusive, and producer traffic is
  quiescent. These conditions remain true through receipt consumption.
- The final beat remains mapped, initialized ordinary RAM with exclusive ownership.
- Calibration and ECC monitor health remain valid; no reset, clock loss, status
  clear or ECC-disable operation intervenes.

Producer quiescence excludes the fence's own read and monitor transactions.
`writes_complete` describes received producer B responses, rather than physical
write retirement. This leaf does not establish these caller obligations or
observe the original AW/B history; the later descriptor/request owner must do so.

The read uses ID 0, LEN 0, SIZE 6, INCR and zero attributes. Address bit 31,
misalignment and unresolved address bits fail before issuing AR. A response
requires a prior AR handshake, ID 0, OKAY and RLAST. Only then can a separately
accepted monitor request produce a fresh zero-status/onoff-1/mask-3 snapshot.
Read data is discarded; no arithmetic or output repair is performed.

The receipt remains valid under backpressure. `fence_done` qualifies its
acceptance with current health, ownership and first-fault state, so a
simultaneous fault wins. A later fault can accompany an older held receipt;
accepting it then produces no done pulse. Pending AR/check requests remain
stable after faults/timeouts; late read/snapshot responses drain until joint
reset. No fixed delay or generic PHY-idle/drain acknowledgment is supplied.

| Fence-local code | Meaning |
|---:|---|
| 1 | Seal, ownership, prior-response or quiescence precondition failed |
| 2 | Invalid final-write address |
| 3 | Calibration or ECC monitor health failed |
| 4 | Read response/protocol failure |
| 5 | Monitor freshness, snapshot or protocol failure |
| 6 | Read/check transaction timeout |

These codes are component diagnostics, not new RK command fields. Actual
controller ordering qualification and integration with unchanged job control,
DMA and the AXI adapter remain separate from this protocol test.

## Reproduce the component checks

```sh
make -f fpga/ddr/lifecycle.mk test
python3 -B tools/ddr/run_lifecycle.py --verify path/to/report.json
```

The target runs nine verifier regressions, both simulators, and six specific
time-zero parameter rejections per simulator. Reset cases total 32 Icarus/23
Verilator; fence protocol cases total 71 Icarus/54 Verilator. Those component
RTL/bench builds use `-Wall` with zero admitted diagnostics. No original archive,
Vivado process or hardware transport is needed for these component tests.

The native MC ordering test has a separate pinned source/primitive/model scope.
Its evidence must be reviewed before using a fence receipt to delay successful
job completion. Neither component establishes initialized data/ECC, physical
DRAM correctness, original-BD reset coverage or RK numerical equivalence.

The [reviewed component target](../build/plan-ddr-lifecycle-implementation/1792976927285576710/protocol-validation.json)
passes with the exact [Icarus](../build/ddr-lifecycle/iverilog-1792979812455054321/report.json)
and [Verilator](../build/ddr-lifecycle/verilator-1792979812042663268/report.json)
runs. The selected source manifest is
`7294d384a98a6231b2463743bce29fd33cd7d58195229bf18b35b3ec806d8e8e`.
[Twenty-three copied-evidence checks](../build/ddr-lifecycle-copy-audit/1792980569267619617/report.json)
pass with all 68 selected files and originals unchanged, including verification
without original-source reads or tool execution.

## Directed MC ordering qualification

The [source ordering argument](../fpga/ddr/xdma_retirement_contract.json) now
has separately scoped native evidence against the actual archived MC, including
bank queues/comparators, column arbitration, rank timing and ECC/RMW logic.
An independent model returns data only for actual issued PHY read columns,
including periodic reads. Official pinned XECLIB RAM32M/SRLC32E functional
models supply the primitive dependencies. The model does not implement DDR
memory, training or pad timing, and the AXI/UI bridge is not simulated here.

Review found a real single-requestor arbiter defect in the original archive:
`inh_group` has an undriven ascending range at WIDTH=1 and is consumed by the
active periodic-read grant. The six initial matching simulator runs did not
resolve that defect. The original controller remains unqualified.

The [source variant descriptor](../fpga/ddr/patches/round_robin_width_one.json)
defines `rknpu-mig42-round-robin-width-one-v1`. Extraction verifies original
arbiter hash `a4b107a17899ee17b42c76e91f8789737d74b65d37c1be6f895bbe24b8b614ef`,
applies one replacement in a separate copy, and requires derived hash
`ae6be8a3f77170c867bf076a4291bd6b0755c1250ab32215a8b679274b88368f`.
The single-requestor inhibit input becomes explicitly zero; WIDTH>=2 retains
the original logic. Original sources, archive, periodic reads, timings and
electrical settings are preserved. The variant changes source logic only and
does not adopt the archive's different RZQ/6 physical profile.

Both [Icarus](../build/ddr-fence-order/iverilog-1792981263689692708/report.json)
and [Verilator](../build/ddr-fence-order/verilator-1792981263691132245/report.json)
pass all six MC cases with identical summaries and trace rows. Each includes
512 derived-arbiter truth/timing rows and 384 larger-width rows matching the
original; Icarus also reproduces the original WIDTH=1 failure. The exact
source/model-bound diagnostic inventory was independently reviewed: 20
Icarus notes and 215 Verilator diagnostics for MC, plus 0/2 for arbiter controls.
No remaining undriven WIDTH=1 warning is admitted.

| Directed case | Write-column cycles | Fence read-return cycle | Observation |
|---|---|---:|---|
| Same last address, cross-bank writes | 116, 190 | 204 | Final RMW return precedes the final write and dependent read |
| Unrelated-bank negative control | 191, 192 | 188 | Wrong-address read completes while both writes remain pending |
| Same bank, different row | 116, 212 | 226 | Dependent read follows the final write |
| Repeated address | 116, 205 | 219 | Both writes precede the dependent read |
| PHY write-data backpressure | 261, 262 | 276 | Same-address read remains blocked until write progress |
| Real RMW decoder UE injection | 116, 190 | 204 | Actual MC emits the uncorrectable-error event |

These cycle numbers describe the directed model, rather than measured board
latency or a fixed fence wait. The evidence supports the source argument for
the selected variant/profile; caller ownership, real AW capture, the complete
AXI/UI path and successful-job publication still need integrated verification.
It supplies no global idle/reset-drain acknowledgment or physical DDR result.

Reproduce with the pinned existing archive and functional model directory:

```sh
python3 -m unittest discover -s tests/ddr/fence_mc -v
python3 -B tools/ddr/qualify_fence_order.py --simulator iverilog \
  --archive "$YPCB_REFERENCE_ARCHIVES/XC7K480T_XDMA_Test.zip" \
  --primitive-library "$VIVADO_ROOT/data/verilog/src/xeclib"
python3 -B tools/ddr/qualify_fence_order.py --simulator verilator \
  --archive "$YPCB_REFERENCE_ARCHIVES/XC7K480T_XDMA_Test.zip" \
  --primitive-library "$VIVADO_ROOT/data/verilog/src/xeclib"
python3 -B tools/ddr/qualify_fence_order.py --verify path/to/report.json
```

These commands read installed functional model sources; they do not invoke
Vivado or generate IP. The [25 copied-evidence checks](../build/ddr-mc-copy-audit/1792981883884855148/report.json)
pass with all 272 selected files and originals unchanged. Copied verification
requires no original archive, model installation or tool execution.
