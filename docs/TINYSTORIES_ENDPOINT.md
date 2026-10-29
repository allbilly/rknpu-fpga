# Shared raw CMAC/EW BRAM endpoint

`rk_jtag_dual_bram` is a new experimental composition beneath the unchanged
640-bit USER2 mailbox. It joins the full C32/K16 pipeline, EW DMA and one
registered 1 MiB BRAM. It accepts original command BO bytes and descriptors;
there is no tensor-operation transport, CPU dense fallback or host gather.
The board wrapper is `ypcb_tinystories_top`, retaining SYS_CLK/LED pins,
the 50 MHz target, startup reset and USER2. No DDR or PCIe is included.

The new endpoint now passes its [first physical trained tile and complete model forward](TINYSTORIES_FPGA_TEST.md),
including all 36 learned projections, raw CMAC/EW execution and complete
mutable-output BO readback. Longer autoregressive generation remains pending.
The former state-decoded reset
revision passed simulation but was rejected for physical admission because
its multi-bit decode could glitch. Its original reports and source snapshot
remain preserved. The corrected revision uses a dedicated registered reset
release and requires fresh native/implementation/image evidence.

## Register windows

Each namespace has the existing job-control layout relative to its base.
All addresses are byte offsets. Only the exact `0x100..0x1ff` window is
translated to CMAC; high addresses cannot alias a low register.

| Namespace | Base | ID | ABI | Descriptor amount |
|---|---:|---:|---:|---|
| EW | `0x000` | `0x524b4557` (RKEW) | `0x00010000` | Existing EW amount, including four PC-tail QWORDs |
| Terminal CMAC | `0x100` | `0x524b434d` (RKCM) | `0x00010000` | Exactly45 body QWORDs; engine fetches all49 final words |

| Relative offset | Meaning |
|---:|---|
| `0x00`, `0x04` | Read-only identity and ABI |
| `0x08` | Existing status bits: submit-ready, active, result, result-error, memory-ready, core-error, core-busy and descriptor-field validity |
| `0x0c` | Write1 to submit; write2 to ACK a successful consumed result |
| `0x10`, `0x14`, `0x18` | Original command address, amount and opaque job tag |
| `0x1c`, `0x20`, `0x24` | Result tag, completed tasks and error code |

Read/write access, protection/strobe requirements and unsupported-register
errors retain the original control contract. In particular, reading a
doorbell or writing an ID fails; unknown offsets return DECERR. A successful
CMAC job reports one task. An EW chain reports its actual completed count.
Raw field/precision/framing failures are still handled by their original
strict decoders; no CNA/CORE/DPU write is ignored.

The Python `DualRawTransport` verifies both IDs and ABIs before any write.
It retains the existing TAP check, lifetime flock, deadlines, byte-only BO
operations, completion checks and poison behavior. `select_profile` changes
only the CSR window; it cannot discard an active job, staged descriptor or
pending result. A switch is allowed after successful readback/ACK with both
namespaces idle. CMAC45 and EW amounts pass through unchanged.
Unknown profile names and register offsets fail locally. The original
`JtagTransport` and its EW namespace remain available.

## One memory owner through result ACK

The first accepted doorbell owns admission until its result is consumed and
successfully ACKed. The peer may stage its descriptor registers, but its
doorbell returns SLVERR while that owner remains. A failed doorbell does not
launch either engine or cancel an existing job. Backend mailbox framing still
permits only one request at a time.

Engine memory responses route only to the selected owner. The host RAM port
is refused while either engine is launching, running or rearming, or any
fault is present. After successful drain, host readback is legal while the
result remains pending. Application software must preserve the result and
read every required output/guard byte before ACK.

The backing RAM accepts a request at edgeA, registers its physical controls,
executes RAM at edgeB and presents a held response for later consumption.
One transaction per port may be outstanding. Enables, addresses, data and
RAM read registers have no asynchronous reset branch. RAM contents are not
reset. A write accepted before global reset may still commit at its following
RAM edge; reset flushes response ownership without promising rollback.
Only global reset owns RAM/backend/controller transaction state.

## Successful standalone CMAC rearm

The original writer's successful-standalone reset callback is represented by
an explicit hardware sequence:

1. Observe the final successful CMAC write response and child completion.
2. Require two stable drained observations: no RAM ownership, response,
   request or busy child. External/backend/peer faults prohibit rearm.
3. Assert only the CMAC engine reset through a dedicated release flip-flop
   for two SYS edges. No combinational FSM decode drives that reset.
4. Release it through that same flip-flop, observe fresh ready/quiet state,
   then publish the original job's completion and task count.

RAM contents, USER2 TCK state, host control and result records remain intact.
The local reset cannot recover a fault. Child errors or drain/release timeout
latch a failure; new jobs and host memory are refused until a global joint
reset or separately audited reconfiguration. Partial writes may remain.
The failure code is preserved even if an already asserted success reset must
stay held after a later fault. The successful count is not a general NPU-reset
API and does not establish Rockchip banking/reset equivalence.

## Current qualification boundary

The registered RAM passes both simulators, including stable stalled responses,
range/alignment failures and accepted-write effects across reset. Existing EW
job-control tests pass in both simulators after adding identity/ABI parameters
whose defaults remain unchanged; all53 legacy host controls pass. Seven new
dual-transport controls cover identity checks, raw payloads, ACK-bound profile
switching, combined initialization deadlines and explicit failure paths.

The trained-tile joined bench exercises CMAC→EW→CMAC on the same RAM, peer
doorbell rejection through ACK, complete BO/sentinel readback, local rearm
counts, raw-field/amount/address failures and global reset during fetch.
The corrected-source native suites are distinct from the earlier rejected
state-decoded revision. Native success does not qualify BSCANE2, timing or
the card. A new source snapshot, full512 retention, routed reset/CDC/timing
review and exact-image admission are required before hardware use.

The optional compiler warning inventories admit only exact source-bound
frozen arithmetic notices. New control/RAM/bench warnings are not waived.
The one Verilator mixed-reset notice refers to the existing CACC reset style
under the registered SYS-clock reset. The fresh source `1e01179c` now passes
the actual synthesized and routed reset-cone checks: only the registered
CMAC release and global startup release drive the child reset. Routed setup,
hold and pulse-width slack are +0.640 ns, +0.056 ns and +9.600 ns at 50 MHz,
with zero failing endpoints, clean routing and passing mailbox CDC checks.
All 512 products remain. No DRC severity, electrical constraint or timing
bound changed. The [preserved source/native/route evidence](../verification/runs/2026-10-27-tinystories-dual-route/index.json)
includes this checkpoint's reports; it makes no physical acceptance claim.
