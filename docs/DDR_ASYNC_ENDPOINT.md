# SYS50 engine with a UI-clock DDR owner

`rtl/ddr/rk_jtag_ew_ddr_async.sv` is a new experimental composition of the
unchanged raw job/host control, DDR owner, ECC monitor and reset coordinator
with the [two-clock EW engine](DDR_ASYNC_EW.md). The original single-UI-clock
`rk_jtag_ew_ddr` remains a separately qualified source snapshot. Its twenty
logical cases do not qualify this new composition.

Frames, AXI-Lite control, host memory access, initialization, AXI/MC traffic,
ECC and retirement stay in `c0_ui_clk`. The actual EW DMA runs on `sys_clk`,
with intended 20 ns SYS and 7.5 ns UI periods. Only original command addresses/
amounts, halfword memory transactions and terminal status cross the boundary.
Final QWORDs and complete BOs retain their existing meaning; no tensor
operation, arithmetic/layout repair, address truncation or CPU fallback is added.

The transport ID is **RKAD**, `0x524b4144`, with ABI `0x00010000` and unchanged
register offsets. It distinguishes the new clock and terminal-task-snapshot
contract from RKED and BRAM RKEW. Clients must explicitly admit this ID.
Register, decoder, shape, precision and framing failures retain their rejection
behavior. Timeout parameters count each component's local clock cycles.

A UI start handshake also claims the DDR job owner. The core receives the
descriptor later, so producer memory traffic follows ownership. Its final
write response returns through the crossing before the core can finish.
A terminal success seals production; the UI owner still checks actual AW
history, its exact-address fence, a fresh ECC snapshot and retirement before
successful controller completion. Readback, ACK and release retain ownership.

Terminal task count crosses as one held snapshot. A raw core error forwards
its code/count on the same UI edge, before local shadow registers update.
A UI platform fault immediately blocks new work, success and ACK, retaining
its first observed cause. If a core is owned, error-result publication waits
for its terminal snapshot. Unknown partial counts are never replaced by zero.
A stopped core remains pending until completion/error or a joint epoch reset.
Queued descriptors that never launched keep the existing zero-result-count
rule through `epoch_started`; the prior DMA snapshot stays separately recorded.
First-cause classification belongs to the UI observation domain, rather than
a global timestamp order across clocks.

Local registers forward the coordinator's reset levels to the crossing reset
pins. Existing UI clients keep their synchronous reset. The coordinator must
retain its fresh-edge/release barrier: stopped clocks cannot permit new packet/
job admission before local reset copies are observed. Health faults cannot
clear quarantine or independently reset the core. Partial writes and offered
requests remain owned until drain or a verified joint epoch; no rollback occurs.

`tools/ddr/run_async_endpoint.py` and `async_endpoint_contract.py` use schema2
and a separate completion marker. The bench retains all twenty original raw
BO/fault/recovery scenarios and numerical/error expectations, changing only
top, identity and marker. A twenty-first case observes the actual SYS counter
after the first linked SUB(9) task, then drops only the external calibration
input. It requires terminal count1 and preserves the earlier UI cause E5 over
a later core timeout. No DUT state is forced. The warning inventory retains the original 574
diagnostics after the explicit bench-name change, with new reset-context
hashes. New warnings fail. Wall limits remain 900 seconds for compilation,
300 for fault-only cases and 1,800 for numerical/reset cases.

The first bounded compile matched all 574 elaboration diagnostics, then its
own 2 GiB cgroup reached its hard limit and stopped. That failed attempt is
preserved at `build/ddr-endpoint-async/native-o3-v1`; no model case ran.
Separating Verilator translation from C++ compilation alone also reached the
2 GiB cap. Inspection found `-j1` had grouped seventeen generated C++ files
into one large compiler input. The next source-identical build explicitly
uses `--output-groups 0` while retaining serial `make -j1`, `-O3`, assertions,
all diagnostics and the same clocks/goldens. This changes C++ build grouping,
not the RTL. Twenty-six generated C++/header bodies match the prior attempt
byte-for-byte after package-path normalization; only the grouping container
is excluded. The installed5.048 alias probe and source comparison are recorded.

The [split build](../build/ddr-endpoint-async/native-o3-split-v4/report.json)
and [independent build review](../build/ddr-endpoint-async/native-o3-split-v4/root-build-review.json)
pass within one shared 900-second budget: 5.344 seconds for translation and
255.931 seconds for C++, 261.267 seconds including gates. Its own kernel
2 GiB cap/no-swap/one-CPU scope peaks at 1,257,578,496 bytes with zero OOM
events. The translation process exits before C++ starts; warning admission
also runs before C++. Compile-record controls reject a reset second-phase
budget, changed flags, missing/failed phases and nonfinite/over-budget timing.
This is the supported
[Verilator output-grouping control](https://verilator.org/guide/latest/exe_verilator.html#cmdoption-output-groups),
without a simulation-design reduction.

The unchanged unknown-command case passes with E1, and the new
[partial-task fault](../build/ddr-endpoint-async/partial-o3-split-v4/report.json)
passes with an actual count1/UI E5 in 176.975 seconds under its 300-second
limit. Both receipts pass `verify-run`. ADD(8), ADD(9) and ADD(33) also pass
complete numerical BO readback on that binary. Eight further fault cases pass,
but the [fault/recovery batch](../build/ddr-endpoint-async/faults-o3-split-v4/report.json)
is **failed**: joint reset recovery exceeded its unchanged 1,800-second limit.
Its [preserved partial output](../build/ddr-endpoint-async/reset-timeout-preservation-v1/preservation.json)
matches the expected prefix through 1,395 complete lines and an incomplete
tail; this is not an accepted recovery result. The remaining numerical cases
continue separately. Complete21-case qualification remains open. A separately
recorded C++ LTO experiment will test build performance without changing RTL,
clocks, assertions, BO comparisons or deadlines; a new binary requires its own
case results. The 36-case engine boundary and mapped CDC proof retain separate
scopes.

The first two LTO experiments are preserved as failed builds: compiler options
reached `CXX`, while Verilator's separate `LINK` driver retained its default.
The private linker candidate explicitly binds both drivers and passes native
build verification, but its reset-recovery test still exceeds1,800seconds.
It remains failed; partial readback is not accepted. Compiler optimization
alone has therefore not closed recovery qualification.

The separate [reset CDC candidate](DDR_LIFECYCLE.md#mapped-reset-findings-and-private-candidate)
passes the original32/23 native reset cases and five new public-status cases
in both simulators. Expected stale-status and delayed-timeout mutants fail,
and the unchanged-source baseline passes. Its new native endpoint build
passes with the identical574-diagnostic multiset, after reviewing only the
two changed reset-source context hashes. The new unknown-command and partial-
task fault cases also pass under their original300-second limits. Actual-MIG
status/job/memory mapped audits pass their scoped checks; twelve reset/vendor
findings, full joined numerical/recovery qualification and physical timing
remain open. The main source and earlier running matrix stay unchanged until
promotion is justified.

```sh
python3 tools/ddr/run_async_endpoint.py build --archive /path/XC7K480T_XDMA_Test.zip \
  --primitive-library /path/Vivado/data/verilog/src/xeclib \
  --cxx /path/compiler-o3.sh --out build/new-async-ddr-model
python3 tools/ddr/run_async_endpoint.py run --package build/new-async-ddr-model \
  --out build/new-async-ddr-cases
python3 tools/ddr/run_async_endpoint.py verify-run --report build/new-async-ddr-cases/report.json
```

The selected compiler wrapper appends only `-O3` to the original C++ arguments;
its exact script and compiler identity are preserved with the native profile.
No fast-math or assertion changes are used.

This source has no physical BSCAN/TCK shell, PCIe interface, MIG pad/training
model, routed clock/reset proof or board image. The original RZQ/7 controller/
PHY and eventual full512/DDR/platform integration retain separate gates.
