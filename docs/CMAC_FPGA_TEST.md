# Full512 FPGA startup test

**Physical result, 2026-10-27 HKT: PASS.** The exact full C32/K16 candidate,
retaining 512 parallel CMAC products, passed three volatile-SRAM loads on the
YPCB XC7K480T, including two reconfigurations. Four positive passive JTAG
captures contain 404 samples of PASS=1 / FAIL=0 with enabled drivers and
32 heartbeat transitions. The 101-row pre-load baseline remains application
UNKNOWN and is excluded. Flash was not written. The owned server stopped and
the shared cable lease was released.

This is the autonomous finite `m2_n17_k65_finite` BRAM fixture. Its physical
layout has two rows, aligned input/output dimensions 96/32, twelve C32/K16
frames and 64 numerical writes/acknowledgments, including physical padding.
The FPGA fetches 49 raw RK QWORDs (45 body words plus the four-word terminal
tail), then checks all 4,096 halfwords against the bound ROM. Software supplies
test inputs and expectations; it does not repair arithmetic/layout or replace
hardware execution. These are synthetic finite operands, not RK silicon
output captures.

SAMPLE observes the source-bound built-in scoreboard's terminal outputs.
It does not independently read the RAM or its 64 numerical values. Successful
reset/reconfiguration does not measure the physical reset-release edge.

| Evidence gate | Actual result |
|---|---|
| Target | DLC10 `80802026a77a01`, raw IDCODE `0x23751093`, current DNA matched before every load |
| Tool | Vivado 2026.1, build 6511674 |
| Routed target | `xc7k480tffg1156-2`, SYS_CLK AA28, 20 ns constraint |
| Resources | 267,240 LUTs (89.50%), 35,822 registers, six BRAM tiles, 515 DSPs including all 512 CMAC products |
| Setup / hold / pulse slack | +0.987 / +0.057 / +9.600 ns, zero failing endpoints |
| Route / constraints | Zero failed, unrouted or partially routed nets and overlaps; no unclocked/unconstrained internal endpoints; zero waivers |
| DRC | No RAM async-control findings; 2,060 reviewed DSP pipelining advisories retained at factory severity |
| Startup | 64 delay FDREs plus registered release, all INIT=0, exact predecessor chain reviewed |
| Mapped startup | Positive test and deliberately inverted expected-rejection control pass under the proved LUT-model profile; 59,973 observed positive cycles |
| Three actual SRAM loads | INIT=1, DONE=1, raw identity and source USR_ACCESS `ac6fee7e` verified |
| Four actual captures | Each has 101 valid rows and eight heartbeat transitions; PASS=1 / FAIL=0 throughout |

The run took place at 16:20:43–16:27:33 UTC on 2026-10-26
(00:20:43–00:27:33 HKT on 2026-10-27).
The source manifest is
`ac6fee7e5ebd29b85c727349c5b2def80ba8f7876ceae76ff0bc0b47750ce25d`;
the 18,735,223-byte bitstream SHA256 is
`205c4c058861b18e9c6d7a292cb5bb9f566571625e5a88a21743256e5e677227`.
The bit header contains the family/package; the speed grade is bound by the
reviewed routed design, not separately encoded in that header.

The [physical evidence archive](../verification/runs/2026-10-27-full512-regmem-fpga/index.json)
preserves raw scans, load receipts, image/source bindings and original logs.
The [independent offline audit](../verification/runs/2026-10-27-full512-regmem-fpga/review/offline-observation-audit-v2.json)
passes all 128 checks and verifies all 292 producer artifacts. Its first
attempt incorrectly labeled reconfiguration captures as ordinary post-load
captures; that failed auditor remains preserved. Correct stored kinds and
exact matching load receipts reproduce all five observation objects unchanged.
The separate [timing/source archive](../verification/runs/2026-10-26-full512-regmem-timing/index.json)
preserves all 125 frozen source files and selected implementation reports.
Bitstreams, DCPs and compiled simulator images remain local; these text
archives do not authorize rebuilding/programming changed source.

## Observation and remaining scope

Logical `LED_ACTIVE_LOW=0` is compiled into this image. P30/M30/N30 represent
PASS/fail/heartbeat. Their BSDL output cells are 852/846/849; disable cells
851/845/848 must each be zero. INIT/DONE and the complete 1,395-bit scan are
checked at the requested/reported 3 MHz cable TCK. Only IDCODE, SAMPLE and
BYPASS are used for observation; TAP reset is not a fabric reset.

`tools/hardware/sample_cmac512.py` prepares and decodes this separate profile
without accessing hardware. It binds the exact image, source/ROM inputs,
compiled generic, target, BSDL and successful volatile-load receipt. Root
owned the actual server, exclusive shared lease, fresh target audits and
programming. The three loads use the reviewed image/source; four positive
captures have distinct trial bindings and post-load timestamps.

This establishes the bound autonomous finite K65 workload and repeated
configuration startup. It does not establish general GEMM/RK3588 numerical
equivalence, exceptional-value policy, compiler-to-card transport, DDR, PCIe,
optical LED polarity, pad voltage, supply measurements or measured operating
frequency. The production endpoint remains the strict FP16 EW slice. The
candidate is not a completed soDLA/RK3588 fork.
