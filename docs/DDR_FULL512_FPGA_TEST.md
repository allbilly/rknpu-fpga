# Physical full512 CH1 DDR inference and trained-tile tests

On 2026-10-28, the complete32-position TinyStories-260K workload
[passes independent root acceptance](../build/fpga-bringup/full512-ddr-model-prep-v5/root-full32-review.json)
on full512/CH1 DDR. Every learned projection runs on FPGA. All 16,384 logits
and all 28 generated token IDs/text match the donor-policy reference and the
prior BRAM result exactly. CPU attention, normalization and the other stated
host operators remain explicit, with no learned-dense fallback or runtime
layout repair.

| Complete DDR model result | Independently verified value |
|---|---|
| Forward positions / learned FPGA projections | 32 / 1,152 |
| Raw jobs / completed tasks | 7,424 / 11,136 |
| Complete output-BO bytes before ACK | 30,408,704 |
| Actual JTAG scans / commands | 2,984,893 / 994,963 |
| Exact logits / generated token IDs | 16,384 / 28 |
| Full logits SHA256 | `c35b2be9a48e7fdc49c9b513ee1e0977766caf1ca442f9756aa2ec877a473e0c` |
| Image/model/runtime bindings / physical artifacts | 479 / 77, all rehashed |
| Epoch and cleanup | One reviewed volatile load; first/repeated BOS and full32; all owned groups closed |

The [fresh root raw-wire replay](../build/fpga-bringup/full512-ddr-model-prep-v5/root-independent-full32-raw-audit.json)
matches the original public audit. The original producer receipts retain
their conservative `REQUIRES_INDEPENDENT_AUDIT` statuses and false broad
qualification flags; root acceptance is a separate, workload-scoped receipt.
No captured report was rewritten after the audit. Flash was untouched.
Full capacity, ECC injection/recovery, PCIe, RK equivalence and production
electrical qualification remain separate gates.

The [portable full32 DDR archive](../verification/runs/2026-10-28-full512-ddr-full32-fpga/index.json)
preserves 678 payloads, including all actual captures and binary output/logit
data, in 61,613,646 stored bytes. Root independently streams and rehashes all
1,056,803,510 source/decompressed bytes, all 77 physical artifact references
and all 479 image/model/runtime references. Nineteen hash-only exclusion
references identify bitstreams, checkpoints, compiled objects and native
tools; two Python paths resolve to the same executable. The prior v4 failure
and conservative producer flags are preserved without relabeling.

## First trained tile

On 2026-10-28, the qualified full512/EW DDR image passed one audited
volatile-SRAM load, a fixed DDR scratch test and the original trained
CMAC/EW/CMAC/EW sequence. The independent root review accepts **360,448
complete BO bytes before the four ACKs**, across four raw jobs and six tasks.
Flash was untouched.

The [portable physical archive](../verification/runs/2026-10-28-full512-ddr-trained-fpga/index.json)
preserves 397 source/evidence payloads in 4,106,430 stored bytes, including
both actual scan traces and all four binary BO readbacks. Independent root
rehash checks every stored/decompressed/original payload and all 527 coverage
references. Bitstream/checkpoints/tools remain hash-identified exclusions.

The [root review](../build/fpga-bringup/full512-ddr-trained-prep-v6/root-trained-tile-review.json)
independently verifies the actual load receipt, all 306 image-bound files,
all 33 physical artifacts and both saved USER2 traces. Those traces contain
26,204 JTAG scans and 8,732 completed commands. The trained audit recomputes
every complete buffer comparison from actual responses, without computing
the expected products or using a CPU dense fallback.

| Item | Actual or source-bound result |
|---|---|
| FPGA / raw IDCODE | XC7K480T, `0x23751093` |
| Target DNA | `004E544714C705C` |
| Cable / TCK | DLC10 `80802026a77a01`, 3 MHz |
| Source tag | `5e99f881` |
| Bitstream SHA256 | `d627b7155c4a4ad6b948424fbd28240a666ea6071bfe8c5d5b19f7da051b0031` |
| Configuration receipt | INIT=1, DONE=1, source tag and before/after IDCODE match |
| Compute / memory profile | 512 product DSPs, 516 total DSPs, no BRAM; CH1 DDR with both original controllers retained |
| Routed setup / hold / pulse | +0.004 / +0.048 / +0.264 ns |
| Scratch | Six lines, two write orders, 768 bytes compared |
| Trained workload | BOS/layer-0 Wq first 32 outputs; CMAC/EW/CMAC/EW |
| Complete readback | Four 90,112-byte buffers, 360,448 bytes before ACK |
| Ownership and reuse | Two CMAC jobs and two linked EW compactions in one loaded controller epoch |
| Cleanup | All owned live process groups absent before shared cable lease release |

The [scratch audit](../build/fpga-bringup/full512-ddr-trained-prep-v6/physical-test/scratch/independent-wire-audit.json)
checks the exact 24 fixed memory operations and both healthy namespace
statuses before and after memory traffic. Its six addresses are `0x40`,
`0x1000`, `0x1800`, `0x200040`, `0x1000040` and `0x7fffffc0`.

The [trained raw-wire audit](../build/fpga-bringup/full512-ddr-trained-prep-v6/physical-test/trained-audit.json)
checks all original final command words, static input/delta bytes, completion
tags/tasks, owned output-buffer contents and readback-before-ACK order. All
four complete buffers match the frozen reference. The independent root rerun
matches that audit's byte/job/task results. These are actual FPGA responses.

The earlier standalone launch failed on its Python import path before any
lease or hardware operation. That failed attempt is preserved separately;
the corrected runner passes a fresh-directory subprocess import regression
and 33 offline controls before the physical load.

This qualifies the finite trained tile and normal ECC-backed DDR path.
Full capacity, injected ECC errors, live-reset recovery,
PCIe execution, RK silicon equivalence and production electrical operation
remain separate gates. Software bitstream CRC validation was not performed;
container/packet checks and actual INIT/DONE retain their distinct scopes.

## First complete model forward

The subsequent [BOS forward control](../build/fpga-bringup/full512-ddr-model-prep-v4/root-first-bos-review.json)
passes an independent root replay of actual DDR/JTAG data: 36 learned
projections, 232 jobs, 348 tasks and 950,272 complete output-BO bytes before
ACK. All 512 logits equal the fixed donor-policy reference; generated token
403 is `Once`. Attention, normalization and the other explicit host operators
remain on CPU; no learned-dense fallback or runtime layout repair was added.

The parent v4 run remains FAIL. After its public BOS audit passed, an obsolete
observer-file path stopped orchestration before the repeat trial. Root's
read-only replay uses the actual pre-audit parent snapshot and links to the
unchanged capture; it does not relabel the failed parent or rerun hardware.
The corrected [v5 session](../build/fpga-bringup/full512-ddr-model-prep-v5/root-execution-review.json)
restarts all three phases under one new load. Its first and repeated BOS
controls now [pass independent root replay](../build/fpga-bringup/full512-ddr-model-prep-v5/root-bos-controls-review.json)
in the same controller epoch. Each checks 232 jobs, 348 tasks, 950,272 BO
bytes and all 512 logits; both logits hashes are
`da84021345aa0521e0ed1c37344b91e93ef077d964a56bd876fdd4326ae8a893`.
Both generate token 403, `Once`. The subsequent full32 DDR execution and
its independent root audit now pass as recorded above.
