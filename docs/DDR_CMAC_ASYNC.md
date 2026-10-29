# CMAC bridge for full512/DDR preparation

`rtl/ddr/rk_cmac_async_engine.sv` carries raw CMAC descriptors from UI133 to
SYS50 and returns halfword memory requests through the existing opposite-
direction crossing. It composes the unchanged job crossing, memory crossing
and successful-CMAC rearm controller. It does not implement a DDR controller,
dual-engine CSR scheduler, board shell or complete TinyStories/DDR execution.

Select the same generated CACC wrapper and pipelined DSP-prefix arithmetic as
the passing full512 BRAM image. The
[source inventory](../build/full512-ddr-preparation/source-inventory-v1.json)
identifies that selection; the default similarly named arithmetic module is
not an interchangeable physical implementation. The new bridge changes no
raw command words, FP16 data, numerical policy or BO layouts.

## Ownership and permission

The descriptor contains the original 32-bit address and amount. The unchanged
CMAC DMA requires amount45 and fetches all49 final QWORDs. Unsupported fields
and invalid descriptors retain explicit errors. There is one owned descriptor,
one held result and one outstanding halfword request.

`ui_admission_enable` controls new submissions. `ui_rearm_permit` is a separate
healthy-platform permission that remains asserted during a healthy owned job;
it must not be wired to a memory-ready flag that falls during ownership. This
level is registered in UI and synchronized through at least three SYS stages.
A descriptor accepted before permission is revoked still receives one error
result. If revocation reaches SYS before launch, it returns E5/tasks0 without
starting the DMA or accessing memory.

Successful numerical-child rearming requires synchronized permission, no known
core-side crossing fault, and drained source memory ownership. It resets only
the CMAC numerical child. The job/memory crossings and DDR/ECC/fence owner are
never reset by this operation. A failed result remains quarantined after
consumption and needs the coordinated transaction reset.

The containing UI owner must still reject success on immediate health loss and
complete its exact-address fence, fresh ECC check and result ownership through
readback/ACK. A synchronized permission level has propagation latency. A later
UI fault can therefore invalidate a job after the numerical child has completed
and rearmed; rearming is not global recovery or proof of DDR retirement.

## Current verification boundary

The actual selected full512 arithmetic and new bridge compile with Icarus13.0.
The [specific frontend review](../build/full512-ddr-preparation/cmac-async-diagnostics-root-review-v1.json)
binds all43 source inputs, the compiled bench and its complete diagnostic set.
Its7363 reachable module scopes all use1ns/1ps, and the compute census retains
one array,16 cells and512 product lanes. The earlier strict diagnostic receipts
remain separate, including the Verilator failure before its reviewed warnings
were classified. These frontend facts are not numerical or FPGA validation.

`tests/ddr/tb_cmac_async_engine.sv` uses the unchanged packaged K65 raw program,
6528 expected operand reads and64 expected writes per successful job. It checks
every fetched command word, operand request, output and output-padding sentinel.
Its nine modes cover repeated jobs, memory errors, invalid amount/target,
timeout with a late return, queued and active permission loss, stopped clocks
and a joint reset with outstanding traffic. All nine now pass in both Icarus
and Verilator, with
[independent exact-marker/source/log review](../build/full512-ddr-preparation/cmac-async-both-simulators-root-review-v1.json).
The repeat mode checks98 command words,13056 operand reads,128 writes,
13576 responses and two safe rearms. The permission-loss/error cases retain
their original expected errors and require zero successful rearms.

The first native Verilator build hit its4GiB cap. A fresh build with split C++
translation units passed under the same cap and deadline, retaining all512
products and exactly the reviewed diagnostics. The failed compile is preserved.
The original Icarus mode0 launcher also misclassified systemd metadata as native
stderr failure; its failure and the documented receipt-restoration limitation
remain visible. A separate audit accepts the actual rc0 execution and bound
raw outputs; later cases use a worker that separates launcher and native logs.

These results qualify the direct-bridge component simulations. The new
[shared EW/CMAC DDR candidate](DDR_DUAL_ENDPOINT.md) has separate control
bench and frontend evidence. Its numerical composition, combined resource/
timing fit, physical crossings, DDR and FPGA execution remain separate gates.
Existing DDR/BRAM receipts do not qualify that joined composition.
