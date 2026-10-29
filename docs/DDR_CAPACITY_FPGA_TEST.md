# Full512 CH1 two-GiB capacity and recovery test

Passed on 2026-10-29 HKT. The
[independent physical review](../build/fpga-bringup/full512-capacity-retire-prep-v2/root-result-review.json)
binds the exact source, routed image, two audited SRAM loads and all six
complete native USER2 traces. It checks the complete two-GiB window and
original numerical jobs before and after deliberate volatile reconfiguration.

The [portable archive](../verification/runs/2026-10-29-full512-capacity-fpga/index.json)
contains 426 exact source/evidence payloads, including every current trace,
all 171 hardware sources, all 60 physical artifacts, 234 preparation bindings
and four original numerical fixtures. The
[independent byte-closure receipt](../verification/runs/2026-10-29-full512-capacity-fpga/root-byte-review.json)
rehashes every source, stored and decompressed byte. The 52,956,402 source bytes
occupy 4,170,517 stored payload bytes; bitfiles, checkpoints, native tools and
compiled objects are hash-identified exclusions.

| Check | Observed result |
|---|---|
| Physical memory window | CH1, byte addresses `0..0x7fffffff` |
| Distinct 64-byte lines per trial | 33,554,432 |
| Global trials | Ascending writes/readback; descending complemented writes/ascending readback |
| Completed writes / reads | 67,108,864 / 67,108,864 |
| Final RKMT status | `0x68`, zero fault codes and sources |
| Normal jobs before/after reconfiguration | K65 CMAC and SUB(9) in both epochs: four jobs, six tasks |
| Complete numerical BO readback before ACK | 245,760 bytes, exact original goldens |
| Scratch controls | Six landmarks, two write orders, 768 readback bytes |
| Independent wire review | Six traces, 19,702 commands, 59,130 actual JTAG scans |
| Target / raw IDCODE | `localhost:3125/xilinx_tcf/Xilinx/80802026a77a01` / `23751093` |
| DNA / TCK | `004E544714C705C` / 3 MHz |
| Ownership | Existing lease inode 9121364; all owned groups stopped before release |
| Flash | Unchanged |

The qualified source tag is `2c8f17dd`, from the complete 171-file manifest
SHA-256 `2c8f17ddfbd2b5da1ad2125af22be6a03418227a5a4aab5ce68352abde6a6667`.
The tested bitfile SHA-256 is
`de982cd7e6c41d13de8e1f047c92fd515ab590e6958339a1dd37135642bef2a4`.
It retains sixteen C32 kernels, all 512 product DSPs, 516 total DSPs and both
original DDR controllers; this workload uses physical CH1 with ECC enabled.
The separate FI test permission remains disabled in this image.

[Routed acceptance](../build/full512-capacity-retire-route-run-v1/root-route-review.json)
checks setup +0.027 ns, hold +0.052 ns and pulse width +0.264 ns with zero
failures, 425,959 fully routed nets and no route errors. The exact 2,066-warning
DRC inventory and all 232 reported pulse rows pass. The routed LUT count is
290,266. The independent IO review checks all 242 ports and 1,936 properties
against the original pin specification. Build/emission used Vivado 2026.1,
SW Build 6511674. The actual configuration and USER2 tools were Vivado Lab
2026.1.1, SW Build 6605303.

The [independent bitfile audit](../build/full512-capacity-retire-image-prep-v2/bitfile-audit.json)
checks the source/route/emitter closure, both DRC ruledecks, container part,
configuration IDCODE `03751093`, source-derived USR_ACCESS and packet bounds.
It rejects IPROG. Software CRC validation is explicitly not performed;
each actual load records configuration INIT/DONE, exact DNA, raw IDCODE,
USR_ACCESS, bitfile hash and successful cleanup.

The BIST performs complete global writes before readback, rather than adjacent
write/read pairs. Its qualified mapped controller requires four retirement/ECC
snapshot handshakes before success. The independent external trace contains
the management witnesses, monotonic counters and final health; it does not
dump every internally compared DDR payload or count fence events independently.
The source/model/route/image closure is therefore part of the capacity result.

Recovery here is a second explicitly audited load of the same bitfile, full
hardware initialization, original BO uploads and repeated K65/SUB(9) execution.
It is not evidence of a live reset command or a cold power cycle. Both numerical
epochs use original command words and complete BO comparisons, with no CPU
arithmetic/layout repair or execution fallback.

The earlier failed emission is preserved: two constant-audit calls omitted
their required trailing-slash prefixes. The successful retry changes only those
arguments and retains all checks. The first physical trial also remains failed:
its software wire auditor expected an incorrect descriptor-status encoding.
The corrected auditor derives bits 10:8 from observed staging, requires active
ownership and keeps error/reserved-bit failures. Sixteen mutation controls pass;
the successful physical trial uses fresh traces and the same unchanged RTL/bitfile.

Physical ECC injection, PCIe, RK silicon equivalence and full TinyStories on
this particular diagnostic image remain separate gates. The earlier complete
[TinyStories DDR result](DDR_FULL512_FPGA_TEST.md) retains its own image scope.
