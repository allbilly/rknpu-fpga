# Raw-command host endpoint: FPGA transport ABI 1.0

`rtl/rk_ew_axi.sv` connects `rk_job_control`, `rk_ew_dma` and `rk_axi_mem` in
one clock/reset domain. A host stages a command-buffer descriptor over 32-bit
AXI-Lite; the endpoint fetches unchanged final RK QWORDs and accesses data over
the 512-bit AXI RAM interface. No tensor operations, CPU arithmetic, layout
repair, or software fallback enter this execution path.

This is an **original FPGA transport ABI**, not Rockchip MMIO, the RKNPU DRM
ABI, an implemented PCIe BAR, or a complete accelerator shell. The arithmetic
and supported-register profile remain the strict FP16 EW subset. The board
top remains the separate BRAM self-test; this endpoint has no physical pins.

## Registers

Addresses are byte offsets. All accesses are aligned 32-bit transactions with
`AxPROT=0`; writes require `WSTRB=0xf`. There is one write response slot and one
independent read response slot. AW and W can arrive in either order.

| Offset | Access | Meaning |
|---|---|---|
| `0x00` | RO | ID `0x524b4557` |
| `0x04` | RO | ABI version `0x00010000` (major 1, minor 0) |
| `0x08` | RO | Status below |
| `0x0c` | WO | Exact value 1: SUBMIT; exact value 2: ACK successful result |
| `0x10` | RW | Staged command-buffer device byte address |
| `0x14` | RW | Staged initial QWORD amount, including the four tail QWORDs |
| `0x18` | RW | Staged opaque 32-bit job tag |
| `0x1c` | RO | Completed job tag, meaningful when result-valid |
| `0x20` | RO | Completed task count, meaningful when result-valid |
| `0x24` | RO | Error code in bits 7:0; upper bits zero |

Status bits:

| Bits | Meaning |
|---|---|
| 0 | Can submit now: all fields written, memory ready, engine ready, no active job/result/fault |
| 1 | Job active, including a queued descriptor waiting for the engine |
| 2 | Result valid; also drives level `irq` |
| 3 | Result is an error |
| 4 | Live `memory_ready` input |
| 5 | Live engine error |
| 6 | Live engine busy |
| 7 | Zero |
| 10:8 | Staged-field valid mask: address, amount, tag respectively |
| 31:11 | Zero |

Unmapped addresses, misalignment and high-address aliases return DECERR.
RO writes, WO reads, invalid doorbell values, wrong protection/strobes, and
disallowed lifecycle accesses return SLVERR without register side effects.
Protection/strobe rejection takes precedence over address decode. Error reads
return zero data. AXI-Lite access errors do not poison an executing job.
Unsupported **RK command fields** still fault through the existing decoder;
these bus-access errors do not replace or relax that behavior.

## Ownership, ordering and completion

One host owner must serialize descriptor programming. This block does not
arbitrate software threads or provide an atomic multi-register host transaction.
Every job requires all three staged fields to be written, even if a tag is zero
or an address/amount is unchanged. Address and amount are forwarded exactly:
alignment, framing and range errors are reported by the DMA/adapter, not repaired
by the control block. In particular address bit 31 is not silently truncated.

1. Populate and make visible all command/input/output BO bytes, including padded
   elements and the ordinary-RAM full-beat mappings required by
   [AXI_MEMORY.md](AXI_MEMORY.md). The eventual host transport must supply its
   actual DMA/coherence fences; this RTL does not provide host cache coherence.
2. Write address, initial amount and tag, waiting for each write response. See
   [PC_DMA.md](PC_DMA.md) for the exact command-memory and linked-tail contract.
3. Write SUBMIT and check its response. OKAY means the descriptor is queued,
   **not** that execution started or finished. Admission requires `memory_ready`
   and engine readiness. After admission, descriptor and start-valid remain
   stable until accepted even if readiness drops. No queued job is cancelled
   merely because `memory_ready` falls.
4. Poll result-valid or observe level IRQ. Completion snapshots the tag, task
   count and error code. Error wins over a simultaneous done pulse. Successful
   completion follows the final memory-write B acknowledgment. A fault may leave
   partial output and an outstanding AXI transaction. Snapshot fields and IRQ
   remain stable until acknowledgment or joint reset.
5. For success, consume the result/output using the platform's visibility rules,
   then write ACK. ACK clears result-valid and all staged fields/valid bits;
   another job must program every field again. Invalid old result snapshots may
   remain readable until the next SUBMIT, which clears them. Fault results cannot
   be acknowledged away; recovery requires joint reset.

While a job is active or a result is pending, descriptor writes and another
SUBMIT fail. Premature ACK fails. A queued job can finish before the host consumes
the SUBMIT B response; neither that response nor the result is lost. Reads
snapshot at the AR handshake, before a simultaneous write or completion update.
A held read response therefore intentionally can describe an earlier state.
Read and write channels progress independently; all responses remain stable
under backpressure. There is no local soft-reset doorbell.

## Platform responsibilities and source evidence

`clk`, AXI-Lite, memory AXI and `memory_ready` must already share a synchronous
domain. A real shell must implement and verify clock-domain crossings, reset
sequencing, MIG calibration admission, ECC error handling, PCIe address mapping,
host visibility and interrupt delivery. IRQ here is a level wire, not MSI/MSI-X.
`memory_ready` gates admission only; it is not a CDC or ongoing calibration-loss
recovery mechanism. The platform must handle readiness loss during a job.

On fault/timeout, reset control, engine, adapter and the affected downstream
transaction domain together. An engine timeout does not authorize withdrawing
an asserted AXI request. Reset does not roll back RAM writes. Do not attach this
block to live MIG/PCIe until that joint-reset contract has an audited implementation.

The local YPCB reference at commit
`8b13ecf71b7061dd43a2b1580f0caa469f64303f` has XDMA metadata in
`examples/YPCB_00338_1P1_systest/YPCB_00338_1P1_systest.srcs/sources_1/bd/top/ip/top_xdma_0_0/top_xdma_0_0.xci`
with `axilite_master_en=false` (line 47). Its separately enabled
`xdma_axilite_slave` is not evidence of a host-to-user AXI-Lite master. XCI SHA256:
`0a1fa4bfab3319d9e8ba2e2488545e9eb964897a9de823884a11da0f6f45efcf`.
No donor configuration was changed and no existing BAR is claimed to expose
these registers. MIG-side width evidence remains in [AXI_MEMORY.md](AXI_MEMORY.md).

The corresponding `top.bd` confirms `microblaze_0_axi_periph/M07_AXI` connects
to `xdma_0/S_AXI_LITE`, while `xdma_0/M_AXI` connects to `axi_smc/S01_AXI`.
SmartConnect outputs M00/M01 feed the two MIG AXI ports. The two MIG UI clocks
and XDMA AXI clock are distinct inputs to that fabric; directly wiring them to
this single-clock endpoint would not implement the required crossings. The
reference's existing resets are likewise not proof of this endpoint's joint
fault recovery. BD SHA256:
`2a17a5028475bfdb27c6576e8ffbac0331949e45327d1a1a34652215e6cbc02a`.

That BD's `/xdma_0/M_AXI` address space maps C0 at `0x00000000` for 2 GiB
and C1 at `0x80000000` for 2 GiB. The current 31-bit endpoint contract covers
only the former range; rejecting address bit 31 must not be replaced with
truncation that aliases C1 requests into C0. These are reference-design address
assignments, not measurements or proof of a working DDR link on this card.

## Verification scope

`tb_job_control` exercises independent AW/W ordering, read/write backpressure,
register snapshots, all unsupported strobes/protection values, explicit access
errors, ownership, queued-start stalls, completion before B consumption, error
priority, sticky IRQ/results, and reset in seven lifecycle phases. It uses a mock
engine; it is not an arithmetic test.

`tb_host_axi` drives only the endpoint's public AXI-Lite ports and independent
behavioral AXI RAM. It replays nine production-encoder EW fixtures; tests nine
bus/timeout/descriptor/raw-register negatives; repeats two SUB(9) jobs without
reloading RAM; and resets after 17 completed writes with the 18th pending in the
second task, checks retained partial writes, then restarts and checks memory.
Backpressure seed is `0x3588c510`. The fixtures' inputs are synthetic, not RK
hardware captures. Their command BOs are unchanged for positive cases.

`make host-synth-check` maps the control and complete internal endpoint to XC7
primitives, then runs the same control bench against its mapped netlist with
the default Xilinx startup model. It does not simulate the complete mapped
endpoint's arithmetic or redo the separate board implementation. `make synth-check`
includes both the existing board checks and this focused check.
The mapped wrapper holds the test clock for 200 ns through default global
startup. It drives the idle read address unknown at 1 ns; the unchanged host
master supplies a fully defined address before asserting ARVALID. This avoids
an Icarus/UNISIM time-zero initialization issue in event-sensitive LUT models
when input declarations are already constant. It does not force DUT state,
disable global startup, alter vendor models, or relax response assertions.
Actual source-bound outcomes are indexed in [verification](../verification/README.md);
test presence alone is not a pass. None establishes physical DDR, timing closure,
RK numerical equivalence, full NPU coverage or actual FPGA operation.
