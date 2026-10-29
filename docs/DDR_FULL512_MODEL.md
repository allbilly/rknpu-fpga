# First full512 and EW controller-model executions

The new shared endpoint has completed separate K65 CMAC and SUB(9) EW
executions through the actual selected AXI, UI, MC and ECC logic. The
downstream PHY storage/returns and calibration inputs are modeled; these
results establish neither physical DDR nor FPGA execution.

| Fixed workload | Namespace | Tasks | Complete BO readback | PHY returns | READ64 packets / AXI reads |
|---|---|---|---|---|---|
| Original K65 CMAC | RKCD, CSR `0x100` | 1 | 20,480 bytes | 18,248 | 322 / 322 |
| Original SUB(9) | RKAD, CSR `0x000` | 2 | 102,400 bytes | 6,920 | 1,602 / 1,602 |

Both used the same native binary, SHA256
`ca017f2afc191f4a07c681e2dc4648063997ee6ac35264695554c33eb4e9bf2e`,
with separate reset epochs. The CMAC run took 753.325 seconds; the EW run
took 518.114 seconds. Their traffic targets were fixed before execution.
Every successful READ64 required exactly one real AXI read; engine reads,
masked-write RMWs and retirement fences remained uncached.

The [CMAC independent review](../build/full512-ddr-preparation/joined-model-source-v1/first-cmac-root-review-v1.json)
rehashes 277 inputs and verifies the original 49 command words, 192 input
halfwords, 3,072 weight halfwords, 64 numerical output halfwords and complete
padding/sentinels. The [EW independent review](../build/full512-ddr-preparation/joined-model-source-v1/first-ew-root-review-v1.json)
rehashes its 286 inputs and checks all 1,600 output rows against the original
capture. Both bound SV sequences compare complete buffers before ACK and
require drained writes, an exact-last-write-address fence, ECC retirement and
healthy ownership release.

The EW native execution returned zero with the exact expected marker, but its
Python postchecker mistakenly compared the printable dump's size with the raw
BO size. The original producer remains **FAIL**. Its 220,800-byte ASCII dump
contains exactly 102,400 raw BO bytes and matches the original expected file
byte-for-byte. The separate independent acceptance records that distinction;
the worker, output and failed receipt were not rewritten or relabeled.

The [portable selected archive](../verification/runs/2026-10-27-full512-ddr-first-model/index.json)
preserves the actual 111-HDL/five-header closure, raw fixtures, compiler and
runtime logs, source/input maps, captures and independent reviews. Native
tools, ELF files, generated C++ and object files are excluded and hash-listed.

## Model and source boundaries

The simulated memory window is `0x10000000..0x100fffff`, one MiB, while the
board preparation keeps its separate two-GiB physical window. The model
initializes and fences all 16,384 full zero/ECC beats before uploads. Its SYS
and UI clocks are directed test stimulus; PHY training, pads, temperature,
electrical behavior, metastability and routed timing are outside this result.

The real controller components and original golden bytes remain unchanged.
The new harness redirects only register commands into the selected CSR bank;
raw command/operand/output addresses and bytes do not move. No software
arithmetic, data gather, layout repair or hardware-execution fallback supplies
a result.

Strict Verilator lint remains failed on 628 known warnings. A separate
[source-bound review](../build/full512-ddr-preparation/joined-model-source-v1/frontend-root-review-v1.json)
matches all 574 prior controller-model diagnostic headers and 54 unchanged
numerical-source headers. The vendor ECC `ht_matrix` warning describes a
constant generate chain whose row depends only on its predecessor; it is
distinct from the new READY/fault feedback paths fixed in the handwritten
dispatcher. The missing `idle` pin is an unused vendor output. The fresh
native build retains all warnings using only `-Wno-fatal`; no diagnostic kind,
DRC rule or timing constraint was suppressed.

## Trained tile reuse in one epoch

The subsequent [independent trained-tile review](../build/full512-ddr-preparation/trained-alternation-source-v2/root-execution-review-v1.json)
passes CMAC, EW compaction and CMAC again in one controller reset epoch. It
uses the original BOS layer-0 Wq first-32-output commands, data and static
nine-line/eleven-line deltas from the earlier BRAM test.

All three complete 1,408-line BO captures match before their ACKs: 270,336
raw bytes total. The run checks 96 engine writes, three DMA launches, three
fabric claims, three fence/ECC retirements and two safe CMAC rearms. All
27,614 PHY returns and 4,226 READ64 packets/AXI reads match the prospective
contract. Wrong-bank descriptor, submit and ACK attempts fail explicitly
while the selected owner is held. Original output sentinels are restored
before the later CMAC job, so old results cannot supply its output.

This trained positive sequence took 1,606.867 seconds. It qualifies reuse of
the original shared-endpoint RTL in the controller model. Complete TinyStories
generation, the new endpoint fault/recovery matrix and physical full512/DDR
require separate qualification.

The [shared-data arithmetic candidate](DDR_AREA_CANDIDATE.md) has since passed
the unchanged trained sequence on its own fresh 112-HDL native executable.
Its [independent review](../build/full512-ddr-preparation/shared-data-trained-model-v1/root-execution-review-v1.json)
checks all 421 bound inputs, identical three full BO captures, the same
27,614/4,226 traffic counts and exact readback-before-ACK order. That separate
run took 2,125.131 seconds under the original 3,600-second sequence deadline.
It establishes positive reuse for the changed arithmetic. The separately
qualified fault matrix below does not close routed timing or physical execution.

## Shared-data controller numerical, fault and recovery matrix

The [independent 33-case union](../build/full512-ddr-preparation/shared-data-fault-model-v1/root-full33-union.json)
passes all 12 CMAC and 21 EW cases on one executable, SHA256
`120a413d661c4bc03631142c3b2b70559cbdf9b2ba121b3c2ab3f5505f3af8bf`.
Its 112-HDL/five-header closure uses the shared-data arithmetic and unchanged
raw workloads, golden BOs, error expectations and testbench deadlines. Coverage
includes numerical boundaries, repeated jobs, unknown commands, uncorrectable
RMW errors, dropped returns, stalled writes, calibration loss, control and host
timeouts, queued/late faults and joint-reset recovery.

Six completed execution groups ran in separate reset epochs; this union does
not replace the distinct same-epoch trained-reuse result above. PHY behavior
remains modeled within the one-MiB logical window. The
[portable controller archive](../verification/runs/2026-10-28-shared-data-controller-33/index.json)
preserves 662 source/evidence payloads in 3,893,933 stored bytes. Independent
root rehash verifies every stored, decompressed and source payload plus all
2,775 input-closure references. The ELF and three native tools are excluded
and identified by hash. No physical DDR, complete capacity, FPGA timing or RK
silicon result is supplied by these tests.

## First physical trained-tile preparation

The [reviewed launch preparation](../build/fpga-bringup/full512-ddr-trained-prep-v4/root-preparation-review.json)
binds 207 source, vector and tool inputs for the future full512 CH1 trial.
It binds the first emitter's reviewed preparation, control files and hardware
source manifest. Its unchanged driver will be rebound to the successful image
before execution. Its 32 offline controls pass; the image review, bitstream and root execution
approval remain unset. No hardware or cable lease was acquired. Earlier
preparation versions remain preserved with the review findings they exposed.

The planned sequence is one audited volatile load, six scratch lines in two
write orders, then the unchanged trained worker with explicit
`--memory-profile ddr`. That worker runs CMAC/EW/CMAC/EW and checks four
complete 90,112-byte BOs before their ACKs. It retains the original raw words,
data, golden buffers, 30-second transport limits and four-job lifecycle.
The wrapper retains the 4,096-MiB host admission and 1,200-second whole-trial
deadline. The final image/route/target review remains separate from the
independent actual-wire scratch and trained-buffer audits.

Scratch verification accepts only the two known namespace identities/ABIs,
initialized idle admission, the exact 24 fixed memory operations and healthy
status from both namespaces after the final read. Fourteen adversarial
scratch controls include full saved-native-trace decoding. Wrapper controls
cover pending-image rejection, strict load receipts, directory ownership,
hashing after trace closure, signal masks and owned-process cleanup. These
are preparation tests, not physical DDR qualification.

The [first physical full512 DDR trial](DDR_FULL512_FPGA_TEST.md) has now passed
independent review: actual scratch and all four original trained jobs, with
360,448 complete BO bytes before ACK and 26,204 scans checked. This is separate
from the modeled-PHY sequences above and does not qualify full-model inference.

The model-audit source now gives the repeated BOS forward its own DDR phase,
`repeated-complete-forward-position`, between the first forward and `greedy32`.
It applies the same complete raw-wire, BO, projection and logit checks to each
one-position control. DDR full32 acceptance requires both earlier controls to
have passed in order. The 17 focused DDR audit controls and 61 TinyStories
controls pass; the fresh complete V14 regression passes in 794.096 seconds
with 89 DDR software controls and both complete native host suites.
No additional physical model result is claimed by these source tests.
