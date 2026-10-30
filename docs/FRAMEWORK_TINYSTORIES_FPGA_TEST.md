# TinyStories full32 on the current factored FPGA image

The current full32 TinyStories-260K run is root-accepted and independently
audited on the exact source-tag `60e7abbb`, bitstream SHA-256
`1ca5ae19a0d95a13899a2e13fd3664668d26643cd2ae733f8f5936f6b380523a` (18,735,214
bytes). This is the current factored full512, dual-MIG, DDR image. One volatile
load covered all three phases: a first complete BOS position, a repeated BOS
position, and the 32-position prompt/workload. The 32 forward positions include
prompt processing.

The complete run executes all 1,152 learned FPGA projections and compares all
16,384 logits exactly with the donor-policy oracle. Greedy decoding produces
the same 28 token IDs and text as the separate CPU reference:

> Once upon a time, there was a little girl named Lily. She loved to play outside in the park. One

The token IDs are `432, 383, 286, 261, 376, 298, 315, 421, 395, 317, 426, 338,
401, 396, 267, 337, 410, 408, 419, 292, 411, 322, 265, 282, 295, 433, 426,
385`. The complete logit buffer SHA-256 is
`c35b2be9a48e7fdc49c9b513ee1e0977766caf1ca442f9756aa2ec877a473e0c`.

## Three accepted phases

| Phase | Positions | FPGA projections | Jobs / tasks | Complete output BO bytes before ACK | JTAG scans |
|---|---:|---:|---:|---:|---:|
| First complete BOS forward | 1 | 36 | 232 / 348 | 950,272 | 152,671 |
| Repeated complete BOS forward | 1 | 36 | 232 / 348 | 950,272 | 152,671 |
| Greedy32 full model | 32 | 1,152 | 7,424 / 11,136 | 30,408,704 | 2,984,893 |
| Total | 34 | 1,224 | 7,888 / 11,832 | 32,309,248 | 3,290,235 |

The independent phase audits check the complete output buffers before each
ACK, the raw command stream, actual scan sequence, projection pairs and result
bytes. The full32 phase records 994,963 raw commands. Its 30,408,704 complete
output-buffer bytes include padding and guards, not just logical tensor data.

The image was audited against target `localhost:3125/xilinx_tcf/Xilinx/80802026a77a01`,
DNA `004E544714C705C`, raw IDCODE `23751093` and 3 MHz TCK. The run used DDR
memory profile, selected physical channel CH1, and one audited volatile image
load. All ten owned process groups were absent before the final audit; the outer
execution exited zero and the exclusive lease was released. Flash was not
written.

The native loader and scan bridges use Vivado Lab Edition 2026.1.1,
SW build 6605303, as recorded in the actual load/bridge logs.

## Model and source references

The static model package is [260k-first-v2](../build/tinystories-preparation/260k-first-v2/report.json)
(report SHA-256 `5229ead1933dc9fd4f7c364f1bfa42f2f43a5e2621900e37e072c78993c161d0`):
model SHA-256 `b0a507e7ad0f626624f17112325e66691f9076d622e1d3274d103d00299f2696`,
tokenizer SHA-256 `037cb335abb25d1fa9e8ecae30ed2a3a8ace9302862ebcdc05d51a6bbb10c312`,
260,032 learned parameters and 520,064 learned FP16 bytes. The raw program
catalog is [all-v1](../build/tinystories-programs/all-v1/report.json)
(SHA-256 `eaf4555a59a4e98770f93f773a39487df3d180c28d59d3b51f9bc589ae3948c1`).
The donor-policy CPU reference is
[full-oracle/v1](../build/tinystories-full-oracle/v1/report.json)
(SHA-256 `d3460c0211d399dea549c71e505bfb806e0f0e8f71e9d5df7f35ec1aaeea1939`).
The package report binds model revision `0bd21da7698eaf29a0d7de3992de8a46ef624add`
from `karpathy/tinyllamas/stories260K` and the separate `llama2.c` reference
revision `350e04fe35433e6d2941dce5a1f53308f87058eb`.

The [root acceptance](../build/framework-factored-fullmodel-physical-review-v1/root-acceptance.json)
(SHA-256 `45dc336492ecba5e941ea3c4c16a4d4d654b1bf84f359a63ad6a160caf26bb26`)
binds the producer, image identity, model/catalog/oracle records, three phase
audits and outer completion. The [independent review](../build/framework-factored-fullmodel-physical-review-v1/review.json)
(SHA-256 `92c4f3811d004972fd9117d0068f8405e72e31f1bae8ffe4366a845daef0edee`)
replays the saved artifacts. The [phase index](../build/fpga-bringup/framework-factored-fullmodel-prep-v2/phase-audit-index.json)
(SHA-256 `e9e1d33e0798b6876110c9f2c56be4406f2ce44dfbfa5989b0b01b2c6d553973`)
links each phase report and audit. The [outer completion receipt](../build/framework-factored-fullmodel-physical-review-v1/outer-completion.json)
(SHA-256 `c22c06adba505f0a9ebc3651dab5099eb169924bcf88c06268ce37241265c74a`)
records exit code zero, ten groups absent and lease release.

Image identity is separately bound by the
[offline bitfile acceptance](../build/framework-factored-bitfile-root-review-v1/root-acceptance.json):
source-manifest tag `60e7abbb` and manifest SHA-256
`60e7abbb885abe8d05b9a01cf688668e494aea152d8b5880b29437447e11ad95`. The public
dual-host source publication `c26acab` postdates image preparation. This result
remains tied to the
recorded `1ca5...` bitstream and `60e7abbb` image source. The producer checked
the frozen inputs throughout execution. Root/independent rehashes are
review-time observations; no separate historical end-of-run source snapshot
is claimed.

Embedding, normalization, RoPE, attention, SwiGLU, residuals, KV storage and
greedy sampling remain explicit CPU operators. There is no learned-dense CPU
fallback or runtime CPU layout repair.

This is one fixed-prompt, 32-position workload with prompt `Once upon a time`.
Full-capacity qualification, physical ECC injection/recovery and warm-reset
coverage, PCIe execution, cold-boot behavior, RK numerical equivalence and flash
writes remain outside this result.

The [portable current-image archive](../verification/runs/2026-10-30-framework-factored-full32-fpga/index.json)
now preserves 1,357 source/evidence payloads and all three actual traces, totaling
1,086,699,649 uncompressed bytes in a 60,971,795-byte compressed archive.
Independent review streamed every payload and rehashed all 27 hash-only
exclusions. Native executables/libraries, bitstreams, checkpoints and installed
tools are excluded; their recorded identities remain. The adjacent
[portable verifier](../verification/runs/2026-10-30-framework-factored-full32-fpga/verify_archive.py)
checks archive/member hashes and the saved acceptance/image scope using only
Python. This adds preservation/integrity evidence, not a new physical execution
or numerical/raw-wire audit. The original workspace receipts remain linked above.
