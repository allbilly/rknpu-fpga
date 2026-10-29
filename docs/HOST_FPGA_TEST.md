# USER2 host-controlled FPGA test

**Physical result, 2026-10-27 HKT: PASS.** The exact reviewed USER2 EW image
executed all nine captured ADD/SUB/MUL workloads, repeated SUB(9) without
rebuilding, and passed SUB(9) again after SRAM reconfiguration. Eleven
successful submissions completed sixteen linked tasks. Complete readback
matched all 1,077,248 owned BO bytes, including input, command, output,
scratch and padding bytes, before each successful ACK.

An explicitly synthetic unknown-register command returned E1 with zero
completed tasks. The poisoned owner refused further work without another
scan. A new bridge/owner and TAP reset still observed the fabric's E1 fault
and refused memory access. Only the second explicit SRAM load recovered it.
There were two volatile loads; flash was not written. The owned server
stopped, and the shared JTAG lease was released. Other sessions may later
replace the volatile image; these observations are dated.

| Evidence gate | Actual result |
|---|---|
| Target | DLC10 `80802026a77a01`, raw IDCODE `0x23751093`, current DNA matched before each load |
| Tool | Vivado 2026.1, build 6511674; Python 3.14.5 native scan client |
| Routed target | `xc7k480tffg1156-2`, SYS_CLK AA28, unchanged 20 ns constraint |
| Resources | 5,674 LUTs, 5,657 registers, 256 BRAM tiles, one DSP, one USER2 BSCANE2 |
| Setup / hold / pulse slack | +0.747 / +0.037 / +9.600 ns, zero failures |
| Route / constraints | All 10,206 routable nets routed, no routing errors or unconstrained internal endpoints; zero waivers |
| Mailbox CDC | Three toggle stages in each direction; 40.000 ns request and 333.332 ns response bounds/skew checks pass |
| Startup / DRC | Exact 65-FDRE INIT=0 chain reviewed; four DSP pipeline advisories retained at factory severity |
| Actual load checks | Both loads: INIT=1, DONE=1, before/after raw identity and source USR_ACCESS `3a0ef75f` pass |
| Actual host link | Reported 3 MHz, exact 1000/3 ns period, existing 6 MHz transport ceiling; RKEW ID `0x524b4557`, ABI `0x00010000` |
| Numerical jobs | ADD/SUB/MUL at logical counts 8, 9 and 33; repeated SUB(9), then SUB(9) after reconfiguration |
| Fault / recovery | Unknown raw register gives E1/task0; persists across TAP reset/reconnect; explicit reconfiguration recovers |

The run took place at 17:31:09–17:40:11 UTC on 2026-10-26
(01:31:09–01:40:11 HKT on 2026-10-27).
The implementation source is
`3a0ef75f961f58fdb3469a48eb3e5320a458c42e29b6445d246ebbcb08e4d8ce`;
the functional mailbox/EW source remains
`980adc4825924530625d9e270f727fd9a91e10b901e76ef244bb276b72aed9f7`.
The 18,735,213-byte bitstream SHA256 is
`6e319afa2d5ca50c083a5b458a57144db90044f357df5fd24de765abc74385ba`.
Its header binds family/package; the routed checkpoint binds speed grade.
USR_ACCESS is separate from the header's unchanged UserID field.

## Execution and independent evidence

The [228-file text archive](../verification/runs/2026-10-27-host-user2-fpga/index.json)
preserves the complete 40-file implementation snapshot, current scan/image
controls, raw scan traces, all captured BO inputs/expectations/readbacks,
load receipts and actual command/log hashes. It also preserves the earlier
lock refusal, which accessed no card, and the image/report wrapper failures.
Their underlying native command results are recorded separately. Bitstreams,
checkpoints and compiled simulator binaries stay local.

The [independent raw-scan audit](../verification/runs/2026-10-27-host-user2-fpga/hardware/independent-physical-audit.json)
decodes all 106,662 scans and 35,550 completed mailbox commands. It checks
instruction/width/magic/sequence rules, descriptors, verbatim input uploads,
wire readback against the test oracle, completion fields, ACK order and E1
persistence. It rechecks all 210 reviewed inputs and 51 physical artifacts.
Root independently rechecked every archived file and the sixteen successful
task completions in the [physical review](../build/fpga-bringup/host-user2-3mhz-20261026T172921Z/root-physical-review.json).

The numerical reference is a test expectation only. The actual path uploads
captured final command BOs unchanged, submits their initial raw descriptor,
and lets the FPGA fetch/execute the QWORDs. Neither bridge nor runtime performs
CPU arithmetic, layout conversion or fallback. Closing a client does not
repair a fault. The bridge permits only bounded IDCODE/USER2/BYPASS scans,
TAP reset and orderly exit; programming remains a separately reviewed action.

Current scan/image controls pass all 53 host unit methods under system
Tcl 9.0.3 and vendor Tcl 8.6.13. The separate fresh production
`make -j2 test` returned zero in 452.074 seconds. Its private snapshot used
52 controls before the final 3 MHz adapter revision; that later revision has
its own 53-method receipts. These simulation/control results are separate
from the physical result above.

## Scope

This establishes host-controlled raw-word FP16 EW execution and the tested
fault/reconfiguration lifecycle in 1 MiB BRAM. It does not establish a live
compiler-to-card run, full C32/K16 host execution, DDR, PCIe, broader backend
coverage, general GEMM or RK3588 equivalence/special-value policy.
The [full512 autonomous test](CMAC_FPGA_TEST.md) has its own image and evidence.

The LEDs indicate IRQ, fault and heartbeat; none indicates workload PASS.
These results use memory readback, not SAMPLE decoding of a built-in
scoreboard. Optical LED polarity, pad voltage, supply margins and actual
clock frequency were not independently measured. This remains a strict
FP16 EW slice with a separate experimental CMAC path, not a completed NPU.
