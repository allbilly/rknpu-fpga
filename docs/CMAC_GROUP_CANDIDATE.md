# Serialized NVDLA FP16 group candidate

`build/rk_nvdla_cmac_group.sv` is a staged direct-convolution group former.
It is now reused by the staged raw numerical core, but is not connected to
the production host endpoint or board. It does not extend the accepted
production profile. The numerical grouping is the
NVDLA donor's 64 FP16 pairs; RK's 32-channel storage atom alone does not prove
that its arithmetic grouping is identical. This remains a donor-based working
contract, not a Rockchip hardware observation.

## Arithmetic and ownership

One transaction supplies two 1024-bit vectors, with channel zero in the low
16 bits, and an opaque tag (35 bits by default). The module stores the frame,
scans 64 channels for the common exponent and NaN priority, then reuses one
unmodified NVIDIA Booth multiplier for 64 cycles. It returns a held 44-bit
group suitable for the [CACC candidate](CACC_REDUCTION_CANDIDATE.md).

Only one frame is owned at a time. Inputs may change after acceptance; they
cannot overwrite the stored frame during scanning, multiplication or output
backpressure. Cancellation immediately gates handshakes and latches a fault;
codes 1..8 survive and other codes normalize to E6. Joint reset clears frame
ownership and output. Unknown input data/weight/tag is rejected in four-state
simulation, with those X/Z checks excluded from synthesis. These checks do
not detect electrical metastability. `TAG_WIDTH=0` is rejected by an initial
check; its dedicated parameter test is not yet run.

For each nonzero pair, the exponent block is the sum of the high three bits
of the two encoded half exponents. The group's block is the maximum across
the 64 pairs. Each mantissa includes the hidden bit for nonzero exponents
and shifts by the low two exponent bits (by one for subnormals). Signed zero
pairs are masked. The donor aligns two carry-save rows separately by four
times the block gap, then applies its sign compensation. Gaps at least eight
blocks discard the lane. A simple product followed by an arithmetic shift
is not generally equivalent.

The signed 38-bit group mantissa sums the compensated signed 32-bit lanes.
Its six-bit exponent is four times the maximum block; the represented value
is `mantissa * 2**(exponent-50)`, not an IEEE FP32 bit pattern. There is no
per-product FP16 rounding. Half infinity encodings follow the donor's
exponent/mantissa preparation, not generic IEEE infinity multiplication.

NaNs select the lowest weight channel first, ahead of every data NaN; absent
weight NaNs, the lowest data NaN wins. The sign and ten payload bits are
preserved in the donor FP44 layout. The group exponent becomes 63 and the
low 27 mantissa bits are zero. No canonical quiet-NaN substitution is added.

## Source pins and tests

NVIDIA checkout: `8e06b1b9d85aab65b40d43d08eec5ea4681ff715`.

- `vmod/nvdla/cmac/NV_NVDLA_CMAC_CORE_MAC_mul.v`:
  `e3863ee66376dab62f7a07ec4cb86dc32084bc00999748cd65083342654394f6`.
- `vmod/vlibs/NV_DW02_tree.v`:
  `9c82f73fa7d7cfaed742a23b280b281bf2e1e965fa95600a0e9aa07f0f85a33e`.
- `cmod/cmac/NV_NVDLA_cmac.h`:
  `c188324560888dacd858c396dba3155cf7e9124dda8405984db8cc1018baa58a`.

`build/gen_cmac_group_vectors.py` extracts and compiles the unchanged
`cal_fp16_booth` integer helper, replacing only its surrounding SystemC class
infrastructure with a standalone driver. This is actual execution of that
helper, **not execution of the full NVIDIA SystemC model**. Independently
expressed group exponent, masking and NaN selection generate 1,438 synthetic
frames, seed `0x3588ca13`. The 84,155 lane checks additionally compare to
exact integer multiply/shift: 73,312 match, 5,527 differ by -1 and 5,316 by +1.
The extracted source, compiler command/version, input/output text, license
and hashes are in `build/cmac_group_candidate/`.

The native bench uses seed `0x3588ca14` and retains full output/tag checks,
backpressure, reset during scan/MAC/held output, fresh work after reset,
cancellation including simultaneous ready, and four-state input rejection.
The first Verilator attempt stopped at a clock-initialization warning in the
bench. The concurrent Icarus attempt was explicitly terminated before that
shared bench was edited; neither is a pass. Their sources and records are
retained. The clock-only correction changes no numerical/protocol expectation.

Final-source **Verilator 5.048 passes** 1,438 vectors, 1,441 completed outputs,
three resets, six cancellations and 6,483 held-output cycles. Its donor-only
warning baseline is retained; no local wrapper/bench warning is accepted.
The original donor procedural assertions are enabled in the Icarus test,
but are not enabled in this two-state Verilator run; numerical
and protocol checks in the HDL bench remain enabled in both.

**Yosys 0.65 mapping passes** with 2,210 FDCE, 1,935 LUT1..6, 22 CARRY4,
659 MUXF7 and 192 MUXF8. Arithmetic/state-presence gates supplement structural
checks. This does not validate mapped arithmetic or physical timing. The
first four-state native run reached its 1,800-second wall limit without a
reported mismatch. That terminal failure is retained under `iverilog/`.
`build/retry_cmac_group_iverilog.py` retried the identical executable and
vectors with a 7,200-second limit under `iverilog_retry_7200/`. That attempt
also terminated at its wall limit without a reported mismatch; its report
is `FAIL` with a `TIMEOUT` test, not a four-state pass. The prior report,
executable, stimuli and unchanged HDL remain pinned. The user-directed C32/K16
parallel implementation and its separate unit results are documented in
[RKNPU_SIZED_CMAC.md](RKNPU_SIZED_CMAC.md); they do not relabel this old C64 test.
No standalone mapped-netlist, physical,
RK differential or integrated GEMM result is claimed. Runners are
`build/run_cmac_group.py` and
`build/run_cmac_group_mapping.py`; the latter maps an internal leaf without
I/O pads and does not establish pin feasibility or timing.
