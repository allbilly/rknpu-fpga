# Drained whole-transaction reset component

`rk_whole_reset_control` is a separate SYS-clock maintenance component. It is
not selected by an existing board source profile. The current board still
ties `reset_req_valid` low. This component alone supplies no accessible JTAG
chain, board CDC/reset qualification or physical recovery result.

Its `power_rst_n` belongs only to FPGA configuration/startup. Client, MIG,
PCIe and TAP resets must not clear its operation/result counters. Its intended
transport is a separate retained maintenance mailbox; the original USER2 NPU
encoder, commands, BOs and fault policy remain separate.

The [joined native parent acceptance](../build/whole-reset-terminal-format-results-review-v4/root-acceptance.json)
now binds a fresh 133-source actual-controller/encoded-PHY-model executable,
its separate coordinator-fault precheck and all twelve scenarios. Seven
successful SYS resets, actual valid CE/UE quarantine/recovery, capacity BIST,
held results, cancellation, sealed requests, expected coordinator failure and
late-response drainage pass the original marker/BO validators. Six complete
numerical images total 532,480 bytes checked before ACK; the modeled capacity
BIST writes and reads 32,768 lines. All source/binary hashes remain stable and
all owned groups close. The earlier V3 dual-completion-marker failure remains
preserved; V4 uses a mutually exclusive terminal branch without changing any
assertion or expected result.

The separate [published project-core selection](../rtl/ddr/maintenance_fi/README.md)
reuses 57 public files and copies fifteen exact source files in the native
order. Its checker verifies 72 source paths/hashes; public source lint passes
with no missing pins, latches, multiple drivers, combinational loops or errors.
This is byte-identical publication, not a new execution or a physical MIG
closure. Native limits are one MiB, four tasks and a 2048-cycle backend timeout;
full two-GiB, 4095-task defaults need their own applicable qualification.

An upstream normal mailbox must hold an unaccepted frame across client reset
for the SEALED denial contract. The existing client-reset mailbox cannot
establish that property. Configuration-lifetime normal/SYS mailboxes, actual
physical FI witness ports, mapped CDC/RDC and FPGA tests remain required.

The request is the existing 604-bit raw frame: magic `0x4f54504a`, sequence,
opcode, strobes, byte address and 512 data bits. Only register read/write
opcodes 1/2 are admitted, with all four strobes. Reads require zero data;
writes require zero upper 480 bits. Status 5 rejects malformed/unknown fields,
4 rejects unaligned addresses, and 2 rejects unsupported addresses, access,
values or operation state. Error responses have zero payload. A write response
acknowledges command acceptance, not reset completion.

| Address | Access | Value |
|---|---|---|
| `0x00` | R | `RKPR` (`0x524b5052`) |
| `0x04` | R | ABI `0x00010000` |
| `0x08` | R | Status below |
| `0x0c` | W | `0x53545254` START, `0x43414e43` CANCEL, `0x41434b21` ACK |
| `0x10` | R | Accepted attempt count |
| `0x14` | R | Successful completion epoch |
| `0x18` | R | Last local result error |
| `0x1c` | R | Capability `0x00010001`: drained whole-reset control |
| `0x20` | R | Result phase: idle 0, quiesce 1, assertion 2, completion 3, initialization 4, held result 5 |
| `0x24` | R | Captured coordinator error code for local error 3 |
| `0x28`, `0x2c` | R | Configured 64-bit SYS-edge deadline, low word first |

Status bits are: 0 START eligible, 1 active, 2 held result, 3 held result error,
4 quiesce requested, 5 coordinator request sent, 6 reset assertion witnessed,
7 quiesce acknowledgment, 8 quiescent, 9 coordinator complete, 10 coordinator
fault and 11 platform ready. All upper bits are zero. Live witness bits do not
turn a cached successful result into a later failure or prove continued health.

START requires idle state, no unconsumed result, a known-ready coordinator and
both quiescence witnesses low. Attempt and success counters never wrap. The
component requests quiescence and waits for fresh acknowledgment plus actual
quiet for `STABLE_SAMPLES` SYS edges. It issues one atomic request on a SYS
edge with the coordinator already ready. There is no pending request VALID
that a local timeout could withdraw or later accidentally issue.

After that request, success requires actual reset assertion with coordinator
completion and platform readiness both low, followed by new coordinator
completion and stable platform readiness. `platform_ready` must represent
fresh initialization, ECC bootstrap disarm and normal admission for this
transaction epoch; coordinator completion alone proves neither. The qualified
witness provider must hold these levels low across the actual reset so old
completion/readiness samples cannot satisfy the request.

CANCEL is admitted only before the coordinator request and wins a simultaneous
quiescence-ready edge. It immediately releases the barrier because no reset
was issued, but leaves a cancelled result that must be ACKed before another
START. For other outcomes ACK consumes the held result and explicitly releases
the barrier. After an issued reset, ACK requires either a new coordinator fault
after an observed clear, or transaction-fresh assertion, low-to-high completion
and stable initialized readiness. Stale pre-request COMPLETE/READY or FAULT
levels cannot release the barrier. These observations continue after a local
timeout without upgrading the failed result or incrementing the success epoch.
A timeout never cancels an already accepted reset. A permanently unresolved
issued operation needs explicit configuration recovery; there is no automatic
retry.

Local errors are 1 deadline, 2 explicit cancellation, 3 coordinator fault,
4 regressed completion, 7 unknown active witness and 8 invalid controller
state. The default deadline is 5,000,000,000 SYS edges (100 seconds at 50 MHz);
it is a component parameter, not a measured board initialization bound.
Invalid zero/unknown deadlines or unknown freshness counts and counts outside
1..65,536 fail at time zero.

Integration must first block new frontend admission while allowing every
already accepted AXI transaction and held response to drain. It must return
fresh SYS-qualified quiescence and initialization witnesses, keep the mailbox
and this controller outside the reset boundary, and connect only the audited
whole-transaction coordinator. Quiescence witnesses must drop when the request
is released. Stopped clocks, stale acknowledgments, late completions, held
results, ownership and complete reset scope need joined-model and routed CDC
qualification before this can be selected for an FPGA image. This is not a
reuse of the abandoned OpenTPU runtime-clock implementation.

`make ddr-whole-reset-control-test` runs the directed component controls in
Icarus 13.0 and Verilator 5.048 with a fresh output directory. The
[independent source/tool review](../build/whole-reset-control-root-review-v1/v4-final-review.json)
verifies 369 Icarus/329 Verilator checks and eight expected invalid-parameter
failures, including stale completion/fault rejection after an issued timeout.
The [full default regression](../build/whole-reset-full-regression-v1/independent-review.json)
also passes `make -j2 test` in 574.557 seconds with all source hashes unchanged.
Actual compiler and linker are pinned to `/usr/bin/g++` (GCC 16.2.1); RAM,
memory-high and swap limits are uncapped. These are component/software tests,
not board, timing or physical recovery qualification.
