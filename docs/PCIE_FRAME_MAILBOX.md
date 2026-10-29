# AXI-Lite raw-frame mailbox component

`rk_axil_frame_mailbox` is a single-clock staging/result endpoint for a future
PCIe BAR path. It carries the existing raw 604-bit backend request and forms
the existing 640-bit response. It never receives tensor operations or changes
command/BO bytes. XDMA, PCIe clock crossing, cross-transport ownership and
physical PCIe execution remain separate work.

| Byte address | Access | Meaning |
|---|---|---|
| `0x000` | R | Identity `0x524b5046` (RKPF) |
| `0x004` | R | ABI `0x00010000` |
| `0x008` | R | Bits 0 idle, 1 pending, 2 held response, 3 protocol fault, 4 all request words staged |
| `0x00c` | W | 1 commit request; 2 acknowledge fully observed response |
| `0x010` | R | Twenty request-word valid bits |
| `0x014` | R | Twenty consumed response-word bits |
| `0x018` | R | Sticky protocol failure code |
| `0x040..0x08c` | RW | Twenty little-endian request DWORDs |
| `0x100..0x14c` | R | Twenty little-endian response DWORDs |

Every request word must be written before commit, including zero reserved
bits 639:604. The request magic is `0x4f54504a` at bits 603:572. Other raw
request fields pass unchanged to the backend, which rejects unsupported
operations/fields. AW and W are independent. Only aligned full-strobe writes
and protection value zero are supported. Unknown/unaligned registers return
DECERR; unsupported protection/strobes/control values or unmet transaction
conditions return SLVERR without changing the staging/result state.

A committed request remains stable under backend backpressure. Staging writes
and another commit are refused until the correlated backend response has been
read completely and acknowledged. A response word counts as observed only
when its AXI R-channel handshake completes. ACK before all twenty handshakes
fails. Read and write actions at the same edge observe prior register state.
Read/B responses remain stable under backpressure.

Backend response codes/data are preserved. A same-edge request acceptance and
response is permitted. An unsolicited, duplicated or wrong-sequence response,
or a nonzero error payload, latches a protocol fault. Codes are respectively
1, 3, 2 and 4. Faults refuse new work/ACK until joint reset. The component reset
must belong to the retained transaction epoch, not a software compute reset or
an independently disappearing PCIe link. Link-loss policy and multi-interface
leases require explicit integration before this can serve a shared card.

This source component does not establish a complete PCIe runtime interface or
qualify the existing JTAG-only images for PCIe.

Run `make host-frame-mailbox-test` for the standalone component. Icarus runs
1,151 deterministic checks including unknown-value controls; Verilator runs
1,142 checks with four-state-only cases excluded. The runner binds source,
simulator versions, executable images and complete logs to a fresh receipt.
No RAM limits, PCIe connection or hardware programming are performed.

`tools.host.axil_frame_mailbox.AxilFrameMailbox` provides the callback-only
host side. Supply owned `read32`, `write32` and `close` callbacks; each MMIO
operation shares one absolute deadline. It stages all twenty DWORDs, commits,
reads and validates all twenty response DWORDs, verifies their observation
mask, then ACKs the packet snapshot. Valid backend error frames pass unchanged.
This packet ACK does not acknowledge an NPU job. Partial protocol failures
poison the owner; closing never resets or recovers hardware. Seventeen scripted
callback controls pass in normal and optimized Python, and run in the same
Make target. BAR mapping and device ownership are not implemented here.

## Retained link-epoch admission

The public mailbox has an explicit `admission_enable` input. It does not gate
AXI ready/valid handshakes: AW and W can each be accepted while disabled, and
each accepted half snapshots whether admission was known high. The mailbox
returns SLVERR without changing staging, commit, or ACK state when either half
was disqualified or current admission is not known high when the pair fires.
Reads accepted while disabled return SLVERR with zero data. Existing B/R
responses remain stable if admission drops while they are held. A recovered
link cannot validate a stale AW/W half; callers need a new fully admitted pair.

The frontend drives this input from the retained PCIe epoch guard. This adds no
PCIe IP, CDC, or channel reset. The unchanged healthy-mode component suite
remains `make host-frame-mailbox-test` (1,151 Icarus/1,142 Verilator checks).
`make host-frame-mailbox-admission-test` runs the new isolated admission cases
(83 Icarus checks, including X admission; 71 Verilator two-state checks). These
are single-clock control results, not PCIe or hardware qualification.

Constructor cleanup preserves the original probe exception if the close
callback also fails. The client still marks itself failed and closed and
attempts cleanup only once. The focused Python controls cover this combined
failure in both normal and optimized Python.
