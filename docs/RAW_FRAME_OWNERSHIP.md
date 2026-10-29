# Two-transport raw-frame ownership component

`rk_raw_frame_owner_mux` sits after the JTAG and PCIe clock crossings and before
the unchanged raw backend. All ports use one retained UI clock. Source 0 is
JTAG; source 1 is PCIe. One source owns the entire backend session, including
BO uploads, descriptor staging, execution, complete readback and job ACK.
An owner request is forwarded byte-for-byte; its correlated response returns
only to the source that submitted it. One backend frame is outstanding.

The local RKHO management bank uses raw register opcodes 1/2:

| Address | Read value / write action |
|---|---|
| `0x600` | Identity `0x524b484f` |
| `0x604` | ABI `0x00010000` |
| `0x608` | Bits 1:0 owner (0 none, 1 JTAG, 2 PCIe), bit 2 fault, bit 3 release-ready |
| `0x60c` | Write 1 acquire; write 2 release |
| `0x610` | Successful-acquisition epoch |
| `0x614` | Requester's physical source identity (1 or 2) |
| `0x618` | Sticky protocol failure code |
| `0x61c` | Supported source mask `0x3` |

Both sources may query management state. Acquire requires no owner, known
backend quiescence and a healthy source. It increments the epoch exactly once;
overflow requires joint recovery. Repeated acquire never recovers an abandoned
session. Only the current owner may release, and only with `release_ready=1`.
Other backend requests from a nonowner return SLVERR without forwarding.
Management reads require zero request data and full strobes. Unknown/unaligned
registers return DECERR; unsupported write fields/actions return SLVERR.

The integrator must derive `release_ready` from the complete backend: no active
job/result, no staged descriptor or partial AXI transfer, no pending memory
request/response/fence, and no held reset, capacity or FI ownership. A software
claim of quiescence is insufficient. Existing single-client lifetime ownership
within each transport remains required.

The arbiter retains a committed request under backend backpressure. Management
traffic is round-robin when both sources request together. Owner link loss,
an unsolicited backend response, a wrong response sequence or nonzero error
payload latches faults 1, 2, 3 or 4 respectively. Faults block backend traffic
and release until joint reset; healthy sources may still read management fault
state. Reset must share the retained backend transaction epoch. Compute reset,
PCIe reset and link recovery must not independently clear a live owner.

This component does not supply clock crossings, PCIe IP, multi-host security,
or physical qualification. Integration and both native/board tests are required.

`make host-frame-owner-test` runs the component in both native simulators and
is included in default `make test`. Each simulator passes 259 deterministic
checks of arbitration, exclusive forwarding, acquire/release, epoch updates,
backpressure, correlated replies, link loss and sticky fault diagnostics.

`rk_pcie_jtag_frame_frontend` composes the packet mailbox on source 1 with the
raw JTAG input on source 0. Both use one retained clock/reset. A PCIe mailbox
protocol fault also removes that source's health witness, so an owned session
cannot survive malformed packet state. PCIe IRQ combines held packet results
and the ownership fault. This wrapper still requires external clock crossings,
PCIe IP and the hardware-derived backend release witness.

The current 72-source parent also qualifies PCIe health with
`rk_transport_epoch_guard` in this retained UI domain. Four consecutive
known-high samples are required before a PCIe source can claim the backend.
After any known-high sample, later low or unknown health latches
`pcie_epoch_fault` through link recovery. The fault contributes to PCIe IRQ and
removes only PCIe source health; a healthy JTAG source can still acquire or use
the backend. The guard does not reset the packet mailbox, gate its AXI channels,
or reassign the owner. Only the shared joint reset clears its sticky state.
The `up` level must already be synchronized; this is not a CDC implementation.

`make host-frame-frontend-test` checks that composition in both simulators,
with 2,090 checks each. It drives the PCIe mailbox through AXI-Lite
transactions while JTAG uses independent raw frames. It verifies the fresh
link arming interval, retention of a W-only packet half across link loss,
sticky epoch fault and IRQ after recovery, blocked PCIe claim/forwarding, and
continued JTAG ownership/backend access. Joint reset clears the retained packet
half and guard before a new PCIe lease. Existing offered/accepted owner-loss,
packet ACK, nonowner reset/job ACK, and backend quarantine checks remain. The
backend is scripted; this is not NPU, CDC or PCIe-IP execution evidence.

`make host-transport-epoch-test` separately checks the guard for FRESH_CYCLES=2
and 4, rejects invalid freshness parameters 0/1/65537, and exercises startup
unknown, brief-up poisoning, X/Z loss, sticky recovery, independent JTAG
progress and asynchronous joint reset. Icarus covers X/Z; Verilator is
two-state. Neither suite qualifies physical PCIe or board CDC.

The callback-only `tools.host.raw_frame_session.RawFrameSession` explicitly
acquires one RKHO session over an already exclusive raw-frame endpoint. The
caller specifies source 1 (JTAG) or 2 (PCIe), supplies `exchange(frame,
deadline=...)` and `close()` callbacks, and audits the actual transport/image.
Construction checks identity, ABI, source, capability, status and epoch before
acquiring. A busy backend fails without an acquire write. Backend frames and
valid error responses pass through unchanged, including memory accesses whose
addresses overlap management-register offsets. Only register opcodes 1/2 are
reserved on the RKHO page.

Call `release()` explicitly after the hardware release witness becomes true.
The session confirms owner/epoch/fault state; it never infers quiescence from a
software job counter. A pre-write busy result leaves the session usable so the
caller can finish and ACK its real job. A failed or ambiguous release poisons
the client. The release witness need not remain high after an accepted acquire
or release; those confirmations check the resulting owner/epoch and faults.
Competing operations fail immediately with `DeviceBusy`; lock contention
cannot extend an operation's absolute deadline. Invalid management-read
responses poison the session.
`close()` closes the supplied transport exactly once and sends no release,
reset, retry or recovery command. An abandoned hardware owner requires the
separate supported recovery procedure.

`make host-frame-owner-test` also runs 24 callback controls under normal and
optimized Python. These tests establish client protocol behavior; they do not
qualify PCIe discovery, BAR mapping, a TAP, clock crossings or hardware.
