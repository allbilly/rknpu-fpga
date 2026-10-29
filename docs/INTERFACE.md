# Interface and numerical contract

This document defines the implemented EW endpoint. The separate, incomplete
raw CMAC product path has its own [contract](CMAC_PRODUCT_PATH.md); it is not
connected to this endpoint and must not be treated as completed GEMM support.

The internal `rk_ew_axi` endpoint adds AXI-Lite descriptor submission and sticky
completion/IRQ around the unchanged raw-command DMA and AXI-memory path. Its
original FPGA transport registers are documented in [HOST_CONTROL.md](HOST_CONTROL.md).
They are not RK MMIO registers or an implemented PCIe BAR. The endpoint is
single-clock and requires a platform-wide transaction reset on faults; the
board self-test remains a separate BRAM-only top.

The separate [USER2 BRAM candidate](HOST_JTAG_BRAM.md) composes the same
controller and raw DMA with `rk_bram` and the reference mailbox. It has a
physical wrapper and a [source-bound raw-BO hardware result](HOST_FPGA_TEST.md).
It retains the
original descriptor/control ABI and does not substitute for the AXI/MIG path.
The [RKNPUFPGA source adapter](BACKEND_RUNTIME.md) puts that byte transport
under the pinned backend's unchanged final encoder for the tested HALF EW
subset; its offline compiler-to-RTL result is not physical FPGA validation.
Its explicit `ew_ddr` software profile also admits the RKAD EW namespace;
the same command whitelist and BO/ACK contract apply. This admission adds
no CMAC or runtime-gather support and does not establish live DDR framework
execution. See the adapter contract for the separate current test results.

The separate [full-DDR framework profile](FRAMEWORK_FULL_PROFILE.md) adds
explicit CMAC/layout/reset dispatch. Its preparation candidate passes six
native compiler-to-RTL shapes; actual-controller and physical qualification
remain pending. These additional banks do not extend this original EW ABI.

## Commands

`rk_ew_core` accepts `cmd_valid`, `cmd_ready` and `cmd_data[63:0]`. A command transfers only on a rising edge where both valid and ready are high. The sender holds the word and valid stable while stalled, and holds valid low during reset. Do not pulse valid regardless of ready.

```
63                 48 47                              16 15             0
+--------------------+----------------------------------+----------------+
| target ID (16 bits)|  register value (32 bits)         | byte offset    |
+--------------------+----------------------------------+----------------+
```

The byte-stream representation is little-endian QWORDs. The hardware port carries the corresponding 64-bit integer; do not byte-swap it twice. Encoding is `(target<<48) | (value<<16) | offset`.

Supported IDs are DPU=0x1001, RDMA=0x2001, PC=0x0081, PC_REG=0x0101 and VERSION=0x0041. `model/profile.py` is the complete reviewed whitelist. Fixed fields are checked exactly, rather than ignored. The generated RTL and Python decoder share the factual whitelist, but do not share the tinygrad compiler's semantic plans.

The `rk_ew_core` profile requires all 21 configuration/tail fields, followed by target PC, offset 0x0008, value 0x18. A VERSION marker and zero next-address/next-amount are part of this terminal-task profile. Concatenating multiple *independently terminal* tasks is allowed; the input stalls while the prior task executes. Nonzero linked PC fields remain rejected on this port. The separate `rk_ew_dma` top fetches raw command memory and executes linked EW tasks; its start fields, finite framing and completion contract are specified in [PC_DMA.md](PC_DMA.md).

The current backend's 13-write FP16 bypass/unity initialization group is also
supported, all-or-none per task. Every fixed field is checked exactly; WDMA width
must match DPU/RDMA width. Partial initialization fails E3, unsupported values
E2, and a valid but mismatched WDMA width E6. See [EW_INITIALIZATION.md](EW_INITIALIZATION.md)
for the complete register contract and source pins. Nonzero aligned guard
addresses and linked tasks are accepted only through the separate DMA top.

Both width registers hold count-minus-one in groups of eight. `width=0` means eight halfwords, not zero or one. Height/notch/channel fields are fixed by this first profile. There is no logical-unpadded length register; the sender must map and initialize enough bytes for the entire physical group count. Runtime arithmetic or layout repair by the host is not an acceptable way to extend the accelerator.

`EW_CFG` supports ADD=0x108202c0, SUB=0x108402c0 and MUL=0x108003c4. SUB is A-B. Unsupported op fields, additional registers or precision configurations latch a fault; they never turn into an implicit no-op or CPU fallback.

A new task must reprogram the complete profile. Values are last-write-wins before a trigger, but any invalid write is sticky and requires reset even if followed by a valid value. This deliberately narrow lifecycle is not a complete model of Rockchip's hardware register banking.

## Memory

Memory requests are `mem_req_valid/ready`, `mem_req_write`, `mem_req_addr[31:0]`, `mem_req_wdata[15:0]`. Addresses are device **byte** addresses, not halfword indexes or host virtual pointers. Every request accesses one little-endian halfword. Base addresses must be 16-byte aligned; accesses within a vector advance by two bytes.

The response is `mem_rsp_valid/ready`, `mem_rsp_rdata[15:0]`, `mem_rsp_error`. Both reads **and writes** require exactly one response. A successful write acknowledgment means the write is complete to the adapter's visibility contract, not merely queued indefinitely. Read data is meaningful only for a successful read. Responses cannot arrive earlier than the cycle after request acceptance. There is one outstanding request, no transaction ID, no reordering and no burst mode.

An adapter must hold a response stable under backpressure. The engine holds requests stable under backpressure. `rk_axi_mem` separately handles AXI address/data handshakes and waits for the final B-channel response. Its 512-bit, full-beat RAM access and joint-reset requirements are specified in [AXI_MEMORY.md](AXI_MEMORY.md); it is not yet connected to MIG or the board top.

The engine reads A, reads B, computes, writes the destination, waits for acknowledgment, and advances. Exact output==A or output==B is therefore supported. Other overlapping output/input ranges are rejected because a forward scalar traversal would otherwise change the input stream. A/B overlap alone is harmless while both are read-only.

Endpoint calculations use 33 bits. An exclusive endpoint equal to 2^32 is allowed; a larger endpoint is rejected before execution. The memory adapter independently rejects unmapped addresses. No automatic wraparound is allowed.

`rk_bram` has a second initialization/readback port. The demo uses it only before/after core work. It is not a coherent concurrent host port: cross-port collisions are undefined by this project. Legal parameters are a power-of-two BYTES >=4, an even BASE, and a range fitting the 32-bit address space. Both ports use the same clock. RAM contents are not reset.

Invalid BRAM parameters and a zero `TIMEOUT_CYCLES` are elaboration/time-zero failures. The demo treats unknown output data as a mismatch in four-state simulation, preventing an uninitialized readback from passing its comparison. This simulation check is not a detector for electrical metastability on a physical FPGA.

## Completion, faults and reset

`done` is a one-cycle pulse after the final successful output-write acknowledgment. `busy` includes pending validated configuration and execution, but not receipt of an incomplete register list. `error` and `error_code` remain latched until reset. Commands are refused while faulted. Output buffers may contain a partial result after a mid-task memory fault; no rollback is promised.

| Code | Meaning |
|---:|---|
| 1 | Unknown target/register |
| 2 | Unsupported value, dtype, mode, op or profile width |
| 3 | Incomplete configuration at trigger; invalid finite framing on DMA top |
| 4 | Alignment, address overflow or partial output/input overlap |
| 5 | Memory bus error |
| 6 | Inconsistent dimensions or invalid internal execution configuration |
| 7 | Unsupported PC fields on raw-word port; invalid PC metadata or task limit on DMA top |
| 8 | Memory request/response timeout |

`TIMEOUT_CYCLES` must be positive and fit a 32-bit counter. Timeout counts stalled memory cycles, not the total task runtime. The default is 65536; tests shorten it. Reset the core **and its memory adapter together** after a fault so that an old response cannot be mistaken for a new transaction. Reset does not restore partially modified buffers.

The hardware command port has no end-of-packet input. A missing trigger leaves a partial configuration idle, rather than generating an automatic framing fault. The software `submit` API has a finite byte-string boundary and therefore additionally rejects truncated QWORDs and end-of-stream partial configurations. This distinction is intentional and must not be confused with tested packet-DMA behavior.

## FP16 arithmetic

For finite operands, each mantissa is an integer of up to 11 bits. MUL forms the exact 22-bit mantissa product and rounds once on binary16 output. ADD/SUB first align finite values on the exact 2^-24 grid, use a signed integer sum, then normalize and round once. This favors reviewability over area and maximum clock frequency; it is not an optimized production FPU.

The policy is round-to-nearest-even and gradual underflow. Exact cancellation gives +0 except the same-sign negative-zero case. Multiplication zero sign is the operand-sign XOR. Overflow yields signed infinity. NaN operands and invalid infinity combinations produce canonical quiet NaN 0x7e00; payloads and exception flags are not preserved/exposed.

`model/half.py` uses Python binary64 arithmetic followed by binary16 packing. Binary16 multiplication is exactly representable at binary64 precision; finite half addition fits the chosen reference precision as well. `model/half_datapath.cpp` uses integer alignment/rounding like the RTL and is checked against that independent oracle. C++ agreement does not prove correct SystemVerilog widths, handshake behavior or synthesis.

Do not use this rounded half-output multiplier as a CMAC substitute. A wider product/accumulator and its reduction/rounding order need a separate RK-evidenced contract.
