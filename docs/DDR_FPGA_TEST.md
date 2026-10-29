# First physical CH1 DDR and raw EW test

On 2026-10-28 HKT (2026-10-27 UTC), one audited volatile-SRAM load and the
fixed USER2/DDR trial passed on the YPCB XC7K480T. CH1 initialization reached
healthy memory-ready status. Six scratch lines passed in two write orders,
then the unchanged captured SUB(9) program completed two tasks. All 102,400
owned BO bytes matched the original expected image before ACK. Flash was
unchanged.

The [independent audit](../build/fpga-bringup/ddr-ch1-first-v1/independent-wire-audit-v2.json)
decodes all 24,238 actual JTAG scans and 8,078 completed mailbox commands. It
checks the exact upload, descriptor, completion, complete readback and ACK
order, rather than accepting a producer PASS marker alone. The
[portable archive](../verification/runs/2026-10-27-ch1-ddr-first-fpga/index.json)
preserves the frozen sources, original fixtures, actual scan trace, load
receipt and failed first audit. Compiled images/checkpoints and native tools
remain excluded and hash-identified.

| Item | Measured or bound result |
|---|---|
| Device | XC7K480T, raw IDCODE `0x23751093`, DNA `004E544714C705C` |
| Cable | DLC10 target `80802026a77a01`, actual TCK 3 MHz |
| Programming tool | Vivado Lab Edition 2026.1.1, SW build 6605303 |
| Hardware source manifest | `a2dfec2162c2df789e3510bd547429592341d8bebd59c835eb4cec1f5af451b7` |
| Bitstream SHA256 | `45bd540cfaf7327ad8db5ba4e3a7548a209db1aeba4423f37159a72287296339` |
| Loaded source tag | `a2dfec21`; INIT_COMPLETE=1 and DONE=1 |
| Routed timing | Setup +0.006 ns, hold +0.035 ns, pulse +0.264 ns |
| Endpoint | RKAD, ABI 1.0; strict raw final-word EW |
| Physical memory | Active CH1, original DDR3-1066/ECC source; both controllers retained |
| Host address view | Unchanged 31-bit window `0..0x7fffffff` |
| Scratch | Six 64-byte addresses, two patterns/orders, 768 bytes compared |
| Raw program | Original `capture_sub_9`, address `0x100e0000`, amount 35, two tasks |
| Complete owned readback | 1,600 lines, 102,400 bytes, all compared before ACK |
| Final state | Healthy idle status `0x10`; native bridge exited successfully |

The scratch addresses are `0x40`, `0x1000`, `0x1800`, `0x200040`,
`0x1000040` and `0x7fffffc0`. Each trial writes all six lines before reading
them; the second reverses write order and changes every pattern. These
landmarks do not establish full capacity or physical row/bank mapping.

The load held the existing shared YPCB cable lease through cleanup, verified
the exact cable, DNA and raw IDCODE before programming, and checked the
bitstream SHA256 both before opening hardware and immediately before setting
PROGRAM.FILE. The source tag and INIT/DONE were verified after programming.
All 511 admitted inputs were rehashed before and after execution. Only owned
processes were stopped. There was no reset/retry or CPU arithmetic/layout
repair in the application path.

## Evidence boundaries and remaining work

This is physical CH1 scratch plus one captured EW workload. It does not
qualify full512/DDR integration, TinyStories with DDR, PCIe execution, general
backend coverage, RK3588 numerical equivalence, full DDR capacity, error
injection, live-reset recovery or production electrical operation. The ECC
enabled source and normal retirement path were exercised; no injected ECC
error was tested. This boot-only image requires audited whole-card SRAM
reconfiguration for recovery; TAP reset does not recover fabric state.

The setup margin is only 6 ps for this exact routed image. No clock,
electrical, DRC or timing requirement was weakened. The existing scoped
vendor CDC dispositions and external timing/electrical limits remain in the
[board preparation](DDR_BOARD_PREPARATION.md). Bitfile software CRC validation
was not performed; its container/packet checks, encoded CRC inventory and
hardware INIT/DONE observations retain their separate meanings.

The first independent audit failed because its reconstruction used brace
literals while the admitted scan bridge uses UTF-8 hex Tcl literals. Its
failed receipt and original auditor source are preserved. The corrected
auditor requires an exact match to the existing hex renderer; no scan, BO,
descriptor or numerical expectation changed. The physical producer remained
passed. Six synthetic auditor controls separately reject premature ACK,
missing output, changed upload/output, wrong completion, missing identity and
unmodeled CSR/reset traffic. Those controls are not hardware evidence.

Next, retain all 512 products while joining the qualified CMAC clock bridge,
shared EW/CMAC job control and the DDR owner. Run combined synthesis early,
then qualify numerical/fault ownership in simulation and a fresh routed
image. Physical trained-tile, one-position and complete TinyStories/DDR
tests follow that composition's own acceptance gates.
