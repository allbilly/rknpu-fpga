# Selected framework matmul on the full512 DDR FPGA

All six selected FP16 framework matmul cases passed physical USER2 JTAG testing
on 2026-10-30. The original Tensor/compiler/final-writer path issued 24 FPGA
jobs: 18 hardware layouts and six CMAC jobs. Independent wire review compared
2,375,680 complete owned BO bytes before job ACK and verified 18 actual compute
resets with epochs continuing from 0 to 18 across one volatile image load.

The [root acceptance](../build/framework-factored-full-six-physical-review-v1/root-acceptance.json),
[independent review](../build/framework-factored-full-six-physical-review-v1/review.json)
and [actual V4 trial](../build/fpga-bringup/framework-factored-jtag-prep-v4/physical-test/report.json)
are workspace-local records under ignored `build/`. A portable archive for this
milestone has not yet been published.

| GEMM `(M,N,K)` | FPGA jobs | Compute-reset epochs | Complete BO bytes before ACK | Actual JTAG scans |
|---|---:|---|---:|---:|
| `(1,16,32)` | 4 | 0 → 3 | 360,448 | 25,087 |
| `(1,16,65)` | 4 | 3 → 6 | 425,984 | 29,506 |
| `(1,32,32)` | 4 | 6 → 9 | 360,448 | 25,090 |
| `(1,33,33)` | 4 | 9 → 12 | 442,368 | 30,469 |
| `(2,16,32)` | 4 | 12 → 15 | 360,448 | 25,087 |
| `(2,32,65)` | 4 | 15 → 18 | 425,984 | 29,311 |
| Total | 24 | 18 resets | 2,375,680 | 164,550 |

Each case uses three raw layout jobs and one unchanged-writer CMAC submission.
The runtime executes gathers in hardware; CPU gather/DRM entry points and CPU
workload-program creation are blocked. Five explicitly pinned CPU queue-control
helpers initialize before the workload. Test inputs and expected outputs are
deterministic finite dyadic values; the independent test oracle is not a runtime
fallback. Complete BO checks include padding and unchanged bytes, rather than
only the returned logical tensor. Protected tensor/scratch regions receive no
host reload after the pipeline starts.

The constructor and original writer's pre/post-CMAC resets use the actual RKRS
service. They retain DDR while clearing compute context. Each new worker uploads
complete initialized BO allocations, so previous-case memory contents do not
become an implicit zero-initialization assumption.

The exact bitstream SHA-256 is
`1ca5ae19a0d95a13899a2e13fd3664668d26643cd2ae733f8f5936f6b380523a`
(18,735,214 bytes), with source-manifest tag `60e7abbb`. Its
[offline image acceptance](../build/framework-factored-bitfile-root-review-v1/root-acceptance.json)
binds the full C32/K16 group: 512 product DSPs, 516 total DSPs, both original MIG
controllers and 242 ports. The selected workload channel is physical CH1.
Routed setup/hold/pulse slacks are +0.001/+0.049/+0.264 ns. No timing, CDC, reset,
DRC or electrical constraint was relaxed to emit the image.

The volatile load audits target
`localhost:3125/xilinx_tcf/Xilinx/80802026a77a01`, DNA `004E544714C705C`, raw IDCODE
`23751093` and 3 MHz TCK before programming, and checks configuration completion,
the source tag and raw IDCODE afterwards. All owned groups close before the
existing shared board lease is released. Flash is unchanged.

Earlier V2/V3 suite failures remain preserved: a candidate-status publication
cycle and undefined epoch bookkeeping stopped their orchestration after the
first worker succeeded. The fresh V4 run fixes the caller, keeps the numerical
worker and wire/BO auditor unchanged, and qualifies all six cases independently.
Its offline full-loop controls also reject epoch discontinuity and wrong totals.

This result covers the selected six framework pipelines on this image. It does
not qualify the entire backend suite, RK silicon equivalence, physical PCIe,
ECC injection/recovery, full-capacity BIST, cold boot, or complete TinyStories on
this changed image. The earlier TinyStories/capacity images retain their own
separate acceptance records. Software bitstream CRC validation is not claimed.
