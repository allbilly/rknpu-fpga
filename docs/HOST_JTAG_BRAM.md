# USER2 host-controlled EW BRAM candidate

This separate milestone accepts raw final command BO bytes through the frozen
OpenTPU USER2 mailbox framing. The new `rk_jtag_ew_bram` connects the existing
`rk_job_control`, `rk_ew_dma` and dual-port `rk_bram`. Register transactions go
through the existing [transport ABI](HOST_CONTROL.md); bulk transfers use the
BRAM host port. The FPGA still fetches the unchanged final RK QWORDs. There is
no tensor-operation API, CPU arithmetic, host layout conversion or software
fallback in this execution path. The Python numerical model generates test
expectations only.

The capacity is 1 MiB at device byte addresses `0x10000000..0x100fffff`. This
covers the complete BO mappings of all nine existing production EW fixtures,
including their 64 KiB command BOs and 16 KiB task BOs. It is an explicit BRAM
profile, not the RK logical CBUF, DDR, PCIe, a DRM device or the full C32/K16
candidate. Unsupported raw command fields retain the existing decoder faults.

The physical candidate is `fpga/host/ypcb_jtag_ew_top.sv`, with the existing
50 MHz clock and three LEDs. It uses startup reset and consumes no R28 input.
LED bits 0/1/2 indicate pending completion IRQ, fault and heartbeat. They do
not assert that a workload passed. LED polarity and configuration-bank facts
remain subject to board review.

## Reference and transport contract

`rtl/vendor/opentpu/otpu_jtag_mailbox.sv` is an unmodified Apache-2.0 copy from
the preserved `openTPU/bitstreams/spare-dual-host-4gb-c0182800` package. Its
SHA256 is `46f4a1148419279262fd274726eba0ab1f35285b91bf58138bc1997e692aeec9`.
The adjacent license and provenance record cover that import. The transport
client and SYS backend are original adaptations. OpenTPU timing, bitstreams
and board results do not qualify this implementation, and its abandoned
runtime-clock work is not used.

There must be one XC7K480T TAP, IDCODE `0x23751093`, six-bit IR, IDCODE instruction
`0x09` and USER2 instruction `0x03`. The XVC client requests a TCK period of at
least 167 ns and rejects a server reporting a faster period. A lower requested
frequency is also enforced. The physical constraints allow at most 6 MHz.

The DR has 640 bits, shifted least-significant bit first. Requests use these
fields; the upper 36 bits are transmitted as zero and are discarded by the
frozen mailbox, rather than decoded by the SYS backend.

| Bits | Field |
|---|---|
| 511:0 | Data, little-endian bytes |
| 543:512 | Device byte address or control-register byte offset |
| 547:544 | Register write strobes; client always sends `0xf` |
| 555:548 | Opcode: 1 register read, 2 register write, 3 line read, 4 line write |
| 571:556 | Sequence; client uses 1 through 65535 and wraps |
| 603:572 | Magic `0x4f54504a` |

An all-zero frame polls. The donor mailbox discards wrong-magic and opcode-zero
frames. The client waits for its sequence before issuing another request.
Responses contain data in bits 511:0, status in 519:512, sequence in 535:520
and magic in 567:536; bits 639:568 are zero. Register reads return only the
low 32 data bits; writes return zero. All error responses return zero data.

Read requests require zero data, register writes require zero upper 480 data
bits, and read/bulk strobes must be `0xf`. Other values fail explicitly.
Register write strobes are forwarded to the unchanged controller, which rejects
anything except `0xf`. Register addresses retain all 32 bits; high addresses
do not alias low registers. Bulk operations transfer exactly 64 bytes at a
64-byte-aligned address inside the BRAM window, using 32 acknowledged halfword
transactions. A write response follows the final successful acknowledgment;
partial writes are possible on failure and are never rolled back.

| Status | Meaning |
|---|---|
| 0 | Success |
| 2, 3 | AXI-Lite SLVERR/DECERR; BRAM access/ownership rejection uses 2 |
| 4 | Alignment error |
| 5 | Unsupported opcode or payload field |
| 6 | Bulk address range error |
| 7 | AXI-Lite protocol violation |
| `0x80` | Backend timeout; completion uncertain and backend quarantined |

The memory host port is refused while an engine start is queued, the engine
is busy or the engine is faulted. Readback is legal after successful completion
while its result remains pending. One mailbox owner serializes all commands;
the mailbox does not provide an overrun queue for a second concurrent producer.
The Python client holds the same `OTPU_RUN_DIR` (default `/tmp/otpu`)
`jtag-<host>-<port>.lock` flock as the OpenTPU client, plus a thread lock.
All users must use the same hostname spelling and run directory.

Timeout and protocol faults leave asserted bus requests stable until accepted
and drain late responses; they do not permit a new transaction. The client
poisons itself after any remote error, timeout or uncertain partial transfer.
Closing or reconnecting does not reset the fabric or undo writes. Recovery
requires a joint reset of mailbox/control/backend/DMA/BRAM transaction state,
or reconfiguration. There is no new reset opcode or soft-reset doorbell.
TAP reset is not a fabric reset. The frozen mailbox retains TCK state and its
last completion across a SYS reset, so live recovery needs a quiescent owner
and an audited reset sequence; the supplied physical shell currently exposes
reconfiguration as its restart mechanism. Normal successful jobs use ACK and
can repeat without rebuilding or reprogramming.

The client shares one absolute deadline across the socket calls and fragments
of a mailbox command, and across connection/TAP/ABI initialization. Job polling
has its own total deadline. A multi-line BO transfer consists of separate
bounded mailbox commands; it has no extra whole-transfer deadline.

The SYS/TCK crossings preserve held payloads and three-stage toggle
synchronizers. The adapted constraints require 40 ns request and 333.332 ns
response max delays and bus skew, with hold-only payload exceptions. The native TCK timing model uses 166.666 ns,
the picosecond floor of the nominal 6 MHz period. This is slightly faster
than the supported cable ceiling; its two-period response budget is also
floored to 333.332 ns. No slower clock or looser payload bound is admitted. Only the
first toggle-stage D pins receive asynchronous false paths. No blanket clock
group cuts those payload checks. The checkpoint script also audits synchronizer
fanin, clocks, later-stage timing, active payload timing and both skew budgets.
The initial native run exposed fractional-nanosecond quantization and stopped
before implementation. The conservative picosecond model above fixed that
clock gate. The subsequent run routed successfully, then stopped in the
bus-skew report parser: native Vivado repeats each requirement in a constraint
header and its detailed path. The corrected auditor requires both complete
copies and exact numeric agreement. Missing/conflicting copies still fail.
The original failed runs and packages remain unchanged.

An [independent read-only native audit](../build/host-cdc-readonly-review/20261026T160942Z/root-review.json)
now passes on the exact routed checkpoint. Its RTL, XDC and entire constraint
definition match the routed source; only the auditor body changed. Setup,
hold and pulse slack are +0.747/+0.037/+9.600 ns, with zero failures. All
10,206 routable nets are routed with zero routing errors. Both three-stage
synchronizers retain the expected fanin, clocks and active later-stage timing.
The 604-bit request and 536 variable response bits have max-delay slack
+39.058/+332.344 ns; actual skew is 0.917/0.940 ns against 40.000/333.332 ns
bounds. Four factory DSP advice warnings remain. This is checkpoint/CDC
evidence; the separate exact-image review below supplies image admission.

Nine preparation/CDC controls pass under both Tcl 9.0.3 and vendor Tcl 8.6.13,
including rejection of the slower rounded period, looser response/skew
limits and incomplete report sections. The [native parser controls](../build/host-native-skew-parser-controls/audit.json)
record actual versions and source hashes. No clock, payload or skew bound was
relaxed to obtain these results.

## Reviewed image and native cable preparation, 2026-10-27 HKT

The exact routed design now has a [root-reviewed USER2 EW image](../build/fpga-bringup/host-user2-3mhz-20261026T172921Z/image-review.json).
Its implementation source is `3a0ef75f961f58fdb3469a48eb3e5320a458c42e29b6445d246ebbcb08e4d8ce`,
with source-derived USR_ACCESS `3a0ef75f`. The 18,735,213-byte bitstream SHA256
is `6e319afa2d5ca50c083a5b458a57144db90044f357df5fd24de765abc74385ba`.
The reviewed resource inventory is 5,674 LUTs, 5,657 registers, 256 BRAM tiles,
one DSP and one USER2 BSCANE2. The startup audit checks all 65 FDRE INIT=0
values and the exact delay-chain predecessors, common clock, CE=1 and R=0.
The [native image command](../build/host-image-review/20261026T171408Z/image-command/launch.json)
exited zero and rechecked all 183 inputs before and after emission. Its outer
reporting wrapper then failed at its final `sys.exit` because `sys` was not
imported. That failure is preserved separately; root independently reviewed
the native exit, marker, input hashes, actual image/header and all gates.
Neither failed historical implementation wrapper was relabeled as passing.

`tools/host/native_link.py` injects a numeric Vivado scan link into the unchanged
`JtagTransport`. Its Tcl bridge binds the exact cable URI, raw IDCODE, current
DNA, INIT/DONE and loaded USR_ACCESS before listening on loopback. It runs at
exactly 3 MHz (1000/3 ns), below the unchanged 6 MHz design ceiling. Commands are
bounded IDCODE/USER2/BYPASS scans, TAP reset and orderly bridge exit. They do
not program the FPGA/flash or reset fabric state. No retry or reconnect is
hidden in the adapter. The OpenTPU native RPC pattern is recorded in
[local references](LOCAL_REFERENCES.md); no donor image or timing result is reused.

Twelve native-link/RPC controls and four image-emission control methods pass
under both system Tcl 9.0.3 and vendor Tcl 8.6.13. The standard
`make host-jtag-preparation-test` now runs all 53 host unit methods, including
these new controls. Three separate mock hardware-harness controls verify
complete-BO readback before ACK, mismatch preservation without ACK and exact
E1 rejection expectations. These are host/control tests, not physical results.

At 17:24:26 UTC on 2026-10-26, the first authorized physical attempt stopped
at the shared JTAG lease because another session held it. Its
[failed preflight receipt](../build/fpga-bringup/host-user2-20261026T171832Z/physical-tests/report.json)
records no card access, programming or jobs. The image is ready for a fresh
target audit when the cable is available. A later fresh attempt, at
17:31:09–17:40:11 UTC, passed the complete [physical USER2 test](HOST_FPGA_TEST.md):
all nine ADD/SUB/MUL fixtures plus repeated SUB(9), complete owned-BO readback
before ACK, explicit unknown-register E1, persistence across TAP reset/reconnect,
and SUB(9) after SRAM reconfiguration. Eleven positive jobs complete sixteen
tasks and check 1,077,248 BO bytes. Both volatile loads pass. Flash is unchanged.

## Offline verification and preparation

These commands run simulation and freeze files; they do not connect to XVC,
invoke Vivado or program hardware:

```sh
make generated-check
make host-jtag-test
make host-jtag-four-state-test
make host-jtag-preparation-test
python3 tools/host/prepare.py prepare \
  --verilator-report build/host-jtag/<verilator-run>/report.json \
  --iverilog-report build/host-jtag/<iverilog-run>/report.json
python3 tools/host/prepare.py verify build/host-jtag-preparation/<package>
```

Both native reports must pass for the exact selected source, tests, generated
stimuli and compiled images. The package copies reports, binaries, logs and
stimuli and validates them independently of their original artifact locations.
It starts with an incomplete electrical/board review. Its `command` action
prints a future checkpoint invocation only after admission; it never executes
that invocation. There is no bitstream-emission or programming action.

The [current package](../build/host-jtag-preparation/1792967662198630675/report.json)
binds both final 15-scenario native suites. The
[current copy audit](../build/plan-debug-implementation/1792961083679149070/host-package-current-audit.json)
verifies it with access to both original run directories blocked and unchanged
package bytes. The [preceding same-source package's audit](../build/host-copy-audit/1792955642798984887/report.json)
also passes 11 corruption/execution-binding controls. Board review is pending.

The native profile checks independent AXI-Lite channel stalls, access errors,
32-word line ordering, timeout quarantine, late-response draining and joint
reset. It exercises the frozen mailbox with asynchronous clocks, payloads,
backpressure, polls, sequence wrap and reset retention. Through the public
frame backend it uploads and checks all mapped bytes for nine production EW
captures, repeats SUB(9) without a RAM reload, rejects an unknown raw register,
and restarts SUB(9) after 17 accepted writes while checking retained partial
RAM contents. It additionally uploads, runs and reads all SUB(9) BOs through
the asynchronous mailbox. These fixtures contain synthetic inputs and software
expectations, not RK silicon output captures.

The scan bench drives the mailbox DR interface, not a vendor TAP model.
The separate physical-wrapper startup test uses explicit BSCANE2/IBUF/BUFG
stubs. Neither validates the physical USER2 primitive, JTAG cable, electrical
facts, placed/routed design or FPGA execution. The exact donor's intentional
declaration INIT values have one file-scoped Verilator `PROCASSINIT` exception
in `tests/host/vendor.vlt`; every other Verilator warning remains fatal.

## Host use

`tools.host.transport.JtagTransport` provides byte reads/writes, raw command
uploads, descriptor submit, result polling and explicit successful ACK. Importing
the module does not connect. Constructing a transport connects to the specified
XVC endpoint and verifies both TAP identity and RKEW ABI before any write.
The reviewed native link above is an alternative to an XVC endpoint; physical
execution requires its separately owned cable lease and exact-image audit.

For a later authorized, source-audited image, the caller must upload every
complete BO and all padding bytes at its captured device address, then submit
the captured initial descriptor address and QWORD amount with an opaque tag.
The command BO's allocated length is not its descriptor amount. Linked task
tail fields and amounts stay unchanged. After polling, read the output bytes
before ACK. Partial byte transfers use ordinary edge-line byte preservation;
the client never gathers tensors or changes command, arithmetic or layout
semantics. Board measurements, matched RK captures, DDR, PCIe and integration
under the real final backend encoder remain separate acceptance gates for
physical use. The [source adapter and offline compiler-to-RTL qualification](BACKEND_RUNTIME.md)
now implement that backend route for the supported HALF EW subset, with no
runtime CPU gather or arithmetic fallback.
