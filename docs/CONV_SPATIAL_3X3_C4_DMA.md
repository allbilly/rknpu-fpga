# Strict 3×3 C4 descriptor-fetch wrapper

Status: **all three exact profiles pass Icarus and Verilator descriptor-fetch
replays; rearm and AXI/top endpoint integration pending**. This wrapper is not
connected to an AXI/top endpoint or FPGA image.

`rk_conv_3x3_c4_dma` accepts one descriptor whose amount is exactly 54 QWORDs,
fetches those 54 words as 216 ordered halfword reads, and forwards every raw
QWORD unchanged to the selected valid, stride-2, or explicit-zero-frame core.
The task-end indication is asserted only for QWORD 54. The only relocatable
fields remain QWORDs 21, 27 and 35, as checked by each strict raw profile.
The explicit-zero-frame profile reads the captured 11×11 zero BO; the wrapper
does not synthesize padding or modify tensor layout.

The descriptor address must be 8-byte aligned and its 432-byte range must fit
the 32-bit address space. It is rejected if it intersects any relocated input,
weight or output allocation. The selected raw profile remains responsible for
the operand/output range, alignment and exact-register checks. Read bus errors
and stalled-response timeouts are failures, before any operand access or output
write when they occur while fetching commands.

The wrapper and profile are deliberately **one-shot until joint reset**. The
strict raw profile enters a terminal lock after the task, so the wrapper holds
`start_ready` low after completion rather than pretending another descriptor
can run. The adapter and core must be reset together after completion or error;
this module does not implement a safe multi-job rearm protocol.

The 2026-11-07 runs used source revision
`8011ff662f6a6877d0eac4e2e4a03ab3aededc0c`, Python 3.14.5, seed `0x3c4c9a31`
and Icarus Verilog 13.0 / Verilator 5.048. Each profile passed the successful
job plus six negative controls: wrong amount, command-address overflow,
command/operand overlap, command read error, command read timeout and an
invalid raw register. The successful runs checked command-read order, operand
traffic, every defined output halfword, untouched output-BO tails and
post-completion admission holdoff. The pad-1 profile needs the command BO placed
outside the captured 3,872-byte input allocation; an earlier runner used an
overlapping test address, which the wrapper correctly rejected with code 4.
Receipts are under
`build/convolution-3x3-c4-dma/<case>/{iverilog,verilator}-20261107T085*/`.

Passing these simulations does not validate an AXI adapter, multi-job rearm,
top-level integration, FPGA execution or RK3588 compatibility.
