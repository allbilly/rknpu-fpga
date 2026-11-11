# RK3588 example capture results

Real-device captures only. `expected.bin` files are host-side oracles and are
never substituted for a device output. No FPGA programming or flash is
involved in these runs.

## Architecture decision

The full NVDLA pivot is not viable for the FP16 examples on this device:

- the physically proven `nv_small_256` core is **INT8 C32/K8**, not FP16;
- the BPE=16 FP16 PDP is 39,636 LUTs and misses 50 MHz by **−5.366 ns**
  (WNS), with an 82-level `cal2d` path;
- the current shell is 292,430 LUTs; adding the PDP would be 332,066, which
  is 33,466 over the device.

The selected path is therefore **incremental custom FP16 RTL on the existing
shell**, starting with FDIV (exact contract), then integer EW and a custom
pipelined PPU. The NVDLA PDP remains the numerical oracle and register-bridge
reference, not the integration vehicle.

FDIV implementation is in the isolated worktree
`/home/fedora/.local/share/opencode/worktree/c66387/fdv-rtl`; it is not yet
merged or FPGA-qualified. No FPGA execution is claimed.

## Capture milestone

All **122 READY cases** across the seven families have now been submitted on
the RK3588 Rocket NPU. Results:

- **107 exact + 2 tolerance-only**;
- **5 captured with a known divergence**: 2 FDIV A/7 cases (now modeled
  exactly by the three-guard-bit contract), 1 FP32-output C32 layout mismatch,
  and 2 INT8 cases with a systematic +1 LSB output-conversion difference;
- **8 FDIV truth-table characterizations** with no oracle;
- **18 BLOCKED cases** remain explicit: vendor ABI, unsupported shapes/dtypes,
  and multi-task transport parents.

No FPGA execution is claimed. All board runs were single-owner, locked, and
read back complete BOs.

## Regression status

`make test` completed on final HEAD `f9b00d8` with no make error or traceback.
The RTL reports are PASS for both simulators: 255 tests each, 146 EW engine
scenarios, 62 DMA scenarios and 17,284 ALU vectors. The model suite passed 95
tests, the C++ oracle passed 1,449,732 comparisons, and the generic runner
passed 53 tests. The earlier failures were stale live DDR profile digests and
a stale dual-host frontend binding; both were fixed by rebinding the manifests,
not by weakening checks.

## EW INT — real capture PASS

| Field | Value |
|---|---|
| Family | `ew-int` |
| Cases | 15 READY, 3 BLOCKED |
| Board | `orangepi5`, kernel `6.18.24-current-rockchip64`, Python 3.14.4 |
| Device | `/dev/accel/accel0`, mainline Rocket |
| Submit | 15/15 `submit_ret=0` |
| Oracle | 15/15 PASS, 0 masked mismatches, 0 padding differences |
| Bytes read | 61,440 (15 × 4,096) |
| Lock | one `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock` invocation |
| Results | `results/ew-int-20261105T200154Z/` |
| Evidence | `results/ew-int-20261105T200154Z-evidence/` |

Coverage: INT8/INT16/INT32 ADD, MAX, MIN, MUL; 8-lane and 9-lane C1WC2
layouts; INT16→INT32 writeback; signed-INT16 second operand.

Caveat: the prepared saturation vectors were in range, so saturation behavior
remains unexercised. The device still matches the oracle exactly. An
independent oracle audit confirmed three manifest descriptions are wrong:

- `int8_add_c8_w1` lane 7 is +105, not 127;
- `int16_add_c8_w1` lane 7 is +31000, not 32767;
- `int16_minus_c8_w1` lane 0 is -31000, not -32768.

The `expected.bin` bytes are correct; only the prose is wrong. No saturation
boundary was actually captured. The signed-INT16 operand behavior in INT32 MUL
was exercised and matches (50000 -> -15536, -50000 -> 15536).

Replay caveat: `int16_add_to_int32_c8_w1` has an odd 31-QWORD command stream.
The generic runner requires one zero QWORD of fetch padding before that bundle
can be rerun; the existing capture used the family runner and remains valid
real-device evidence.

## EW FP16 — real capture, 52/54 donor-oracle match

| Field | Value |
|---|---|
| Cases | 54 READY |
| Submit | 54/54 `submit_ret=0` |
| Transport | 54/54 OK, 221,184 bytes read |
| Logical oracle | 52 PASS / 2 FAIL |
| Mismatched halfwords | 20, all FDIV, all finite |
| Padding/tail | zero and matching |
| Lock | one `flock` invocation, 54 sequential cases |
| Results | `results/ew-fp16-20261105T201400Z/` |
| Evidence | `results/ew-fp16-20261105T201400Z/evidence/` |

ADD/SUB/MUL/MAX/NEG are 45/45 PASS across lengths 1, 7, 8, 9, 33 and 1024.

The two FDIV failures are real RK divider behavior, not transport faults:
every mismatch is `A/7.0` and the device result is exactly one FP16 ULP below
the donor CPU round-to-nearest result. Examples: `18/7` donor `0x4125`,
device `0x4124`; `50/7` donor `0x4725`, device `0x4724`. The divergence covers
20 halfwords in `fdiv_p1_n33` and `fdiv_p1_n1024`. The device therefore does
not implement donor/IEEE round-to-nearest for all finite quotients.

## FDIV operand-class truth table — real capture PASS

| Field | Value |
|---|---|
| Cases | 8 READY |
| Submit | 8/8 `submit_ret=0` |
| Lanes | 256 (16 A classes × 16 B classes) |
| Bytes read | 512 (8 × 64) |
| Lock | one `flock` invocation |
| Results | `results/fdiv-systematic-20261105T204746Z/` |
| Lane table | `class_results.tsv`, `class_results.json` |

The captured special-case rules are much simpler than the early ad-hoc
description:

- any NaN operand -> `0x7c01`;
- `+0/+0 -> 0x7c01`, but `+0/-0 -> +inf`, `-0/+0 -> -inf`, `-0/-0 -> -inf`;
- finite-nonzero / zero -> infinity with the sign of the numerator, ignoring
  the denominator sign;
- zero / finite or infinity -> zero with the sign of the numerator;
- finite / infinity -> zero with the sign of the numerator;
- infinity / zero, infinity / infinity, infinity / finite -> infinity with the
  sign of the numerator;
- finite-nonzero / finite-nonzero is correctly rounded in the 256-class table,
  but the separate 1,024-lane `A/7` capture shows 20 one-ULP-low exceptions.

The `A/7` exception remains the only observed finite-rounding deviation and is
the key open item for the RTL contract.

## FDIV capture detail

The A/7 result agrees with the earlier special/finite captures that show a
non-IEEE divider. The denominator-7 cases must be added to any future RTL
rounding contract; the current FPGA decoder still rejects FDIV explicitly.

## FDIV — captured, not implemented

Finite and special-value captures are recorded in
`rk3588-kernel-comparison-v1/`. The divisor is non-IEEE in several cases
(`0/0 -> 7c01` but `-0/+0 -> fc00`; `+inf/+inf -> 7c00` but
`-inf/+inf -> fc00`).

The 256-class truth table resolves the special-case signs: all special paths
(NaN, infinity, zero numerator/divisor) use `sign(a)`, while finite paths use
`sign(a)^sign(b)`.

The `A/7` exception is also explained. The divider is not infinite-precision
RNE; it keeps **three guard bits with ties-to-even**. A model of that form
matches **1,452/1,452 real lanes**, including all 20 `A/7` one-ULP-low
records. Exact RNE, truncation and a one-guard-bit model all fail. The full
decision tables and pseudocode are in
`team/fdiv-analysis/FDIV_CONTRACT.md`; the FPGA register decoder still rejects
FDIV explicitly.

## Pooling — real capture PASS

| Field | Value |
|---|---|
| Cases | 19 READY, 2 BLOCKED not run |
| Submit | 19/19 `submit_ret=0` |
| Full-BO exact | 19/19, no byte mismatch |
| Bytes read | 77,824 (19 × 4,096) |
| Index positions | exact |
| Padding/tail | zero |
| Lock | one `flock` invocation, 19 sequential cases |
| Results | `results/pooling-20261105T203205Z/` |
| Host analysis | `results/pooling-20261105T203205Z-host-analysis/` |

Coverage: FP16 max/avg/min, INT8/INT16 max/avg/min, 1x1/2x2/3x3/3x5 kernels,
stride 1/2/3, padding, INDEX_EN, C1HWC2 packing and C3/C4/C8/C16/C32 atom
tails. The four FP16 average cases are exact and also pass `atol=0.0625`;
`use_cnt0` and `use_cnt7` produce identical outputs as expected. The two
INT32/FP32 zero-write probes were never staged or submitted.

Runner provenance: the board run used the pooling-stage `rocket_run.py`
(`tool_version=1.0.0`). The delivered runner was subsequently updated; the
current host copy is pinned at
`runner/pinned/rocket_run-a51d.py` and passed all 53 runner tests before the
next family run.

## Conv simple — real capture, 4/7 exact

7 READY / 5 BLOCKED, all 7 submissions `submit_ret=0`, 21,888 output bytes
read under one `flock` invocation.

| Case | Result |
|---|---|
| 1x1 C4/H8/W8 → OC16 | exact full BO |
| 3x3 C4/H8/W8 → OC16 | exact full BO |
| 5x5 C4/H8/W8 → OC16 | exact full BO |
| 3x3 C16/H8/W8 → OC32 | exact full BO |
| 1x1 C32/H8/W8 → OC32, FP32 output | **structural mismatch** |
| INT8 5x5 C8/H8/W8 → OC32 | prefix differs by +1 LSB in 7/512 bytes |
| INT8 depthwise 3x3 C64 → OC64, g64 | prefix differs by +1 LSB in 13/2304 bytes |

The C32 FP32-output case is exact for the first 2,048 bytes and then shows a
chunk displacement/zero-fill pattern, not rounding. The manifest already
marked mainline-Rocket FP32-output C32 as not separately evidenced; it is not
claimed as a pass.

The two INT8 cases show a real quantization divergence from the host oracle:
every mismatching byte is exactly `expected + 1`, with zero tails. This is a
small but systematic output-conversion/rounding difference; the conversion
mode needs its own characterization before an INT8 RTL claim.

BLOCKED with source evidence: stride 2, SAME padding, C8 FP16 packing,
grouped convolution, and addition/residual.

Results: `results/conv-simple-20261105T215921Z/`; host analysis is in
`host-analysis/REPORT.md` and `comparison.json`.

## Conv FP16 — real capture, 9/9 exact

9 READY, 5 BLOCKED after the multi-task split, using the cleaned
`kernel_6_18/conv_new_clean.py` builder. All nine one-task cases returned
`submit_ret=0` under one `flock`; all nine match their defined output exactly,
with max abs diff `0.0`. Total: 35,392 output bytes, 4,756 defined oracle
bytes and 30,636 padding/tail bytes reported separately. The four promoted
grouped/split-OC tasks are exact; their raw BOs match the diagnostic evidence.

The earlier two-task run left task 1 all-zero because the mainline Rocket path
does not reliably execute a second task in one job. That evidence is preserved;
the split one-task cases are the capture contract.

BLOCKED: the vendor-only `conv_tiles.py` ABI, the true FP16 pad-register path,
split-K reduction, and the two original multi-task parents (transport
limitation).

Results: `results/conv-fp16-20261105T222300Z/`.

## Independent bundle audit

The independent parser (v1.3.0) now accepts the formal Rocket QWORD-pair parity
padding and reports **PASS: 0 INVALID, 0 provenance errors, 814/814 hashes
verified, 122 READY / 18 BLOCKED** on the current tree. It also confirmed every
case-level schema, patch, task-range, buffer-size and oracle-separation check.
Two stale `CAPTURE_FORMAT.md` pins and the conv-fp16 evidence bindings were
corrected; the audit now verifies every declared hash against actual bytes.

## Independent host-oracle verification

`team/oracle-conv/verify.py` recomputes conv/pooling/GEMM results with a
separate naive NumPy implementation; it does not import the family oracle
functions. Current result:

| Family | READY | Oracle verified | Mismatches |
|---|---:|---:|---:|
| conv-simple | 7 | 7 | 0 |
| conv-fp16 | 7 | 7 | 0 |
| conv-gemm-vendor | 9 | 9 | 0 |
| pooling | 19 | 19 | 0 |

This validates the host expected data, not the device. Pooling additionally
has the 19/19 full-BO exact real-device capture above. Conv and GEMM device
captures remain pending.

## Example gap matrix

Current census: **140 cases, 122 READY / 18 BLOCKED, 111 captured on
RK3588 Rocket, 11 prepared-not-run, 0 runner-invalid.** Full detail is in
`team/gap-matrix/GAP_MATRIX.md`.

Top FPGA RTL gaps, in order:

1. **CNA/CBUF/CSC convolution missing** — 39 cases: 15 captured, 11 prepared,
   13 blocked.
2. **PPU pooling missing** — 19 captured/verified, 2 blocked.
3. **Integer EW and DPU BS/BN/LUT missing** — 15 captured/verified,
   2 prepared, 4 blocked.
4. **FDIV captured but no RTL** — 17 captured, contract now exact.
5. **Vendor RKNPU / multi-core PC-chain ABI missing** — 3 blocked cases.

## NVDLA reference

The `~/ZYNQ-NVDLA` reference (commit `3f1bc4c3…`) contains the full NVDLA
CSC/CDMA/CBUF/CMAC/CACC/SDP/PDP RTL on the same Kintex-7 board. The first
crosswalk found:

- **PPU / PPU_RDMA** are exact PDP / PDP_RDMA register aliases;
- the strict field-level alias hypothesis is otherwise disproved: only 4 of
  62 decoded fields match exactly;
- **CNA** needs an adapter plus CVT/CBUF/stride datapath changes;
- **CORE** is a compacted CACC subset; mostly adapter but MISC/CLIP semantics
  differ;
- **DPU/RDMA** cannot be reused from the `nv_small_256` build: its SDP EW
  stage is compiled out and ERDMA is not instantiated, so RK's FP16
  elementwise path needs new RTL or a different NVDLA config;
- only MRDMA cube/source fields are a pure RDMA adapter.

The full NVDLA 1,024-MAC core cannot be imported: the reference records a
placement failure of 3,138 slices on this exact device. PDP/PDP_RDMA remains
the clean first reuse. A BPE=16/128-bit-atom PDP has now been generated under
`build/ppu-pdp-bpe16/`. After enabling the FP16 arithmetic paths,
**FP16 max, average, min, negative-padded max and global average all match the
real device BO exactly**, and the INT16 max/average/min controls also match.
Only `INDEX_EN` position metadata differs: six bytes in the index case, while
the max values match.

The OOC synthesis/fit check is the hard limit: the PDP + bridge alone is
39,636 LUTs, 21,068 FFs, 35 DSPs and 6 BRAM, but misses timing at both
100 MHz (WNS −15.068 ns) and 50 MHz (WNS −5.366 ns). The worst path is the
`cal2d` FP16 reciprocal/normalize path, 24.97 ns and 82 levels. The full
existing shell is 292,430 LUTs; adding the PDP would be 332,066, which is
33,466 over the device. The current shell cannot host the PDP alongside its
CMAC. A viable route needs a pipelined PDP plus a major shell repartition, or
a different pruned NVDLA core as the compute engine.

Detailed field proof: `team/nvdla-crosswalk/FIELD_CROSSWALK.md`; synthesis:
`build/ppu-pdp-bpe16-synth/REPORT.md`.

## Runner tooling

`runner/rocket_run.py` and `runner/validate_bundle.py` are the shared
board-side and host-side bundle tools. The runner is self-contained, has no
NumPy dependency and does not touch the device at import. It validates the
bundle, allocates one Rocket BO per named buffer plus the command BO, patches
addresses from actual DMA addresses, builds the task descriptors, submits one
job, waits on the output BO, and writes only readback bytes.

Local verification: **53 unit tests OK**, including validation, patching,
descriptor construction, queue expansion, per-case failure capture and a fake
UAPI runner. The exact board invocation and failure contract are in
`runner/README.md`; every invocation must be enclosed in the exclusive
`flock`.

## Conv/GEMM vendor ABI — real capture, 10/10 pass

10 READY and 3 BLOCKED cases under `conv-gemm-vendor/` after the depthwise
split. All 10 submissions returned `submit_ret=0`; 80,640 output bytes were
read in the first run and 30,208 in the depthwise rerun. All 10 now pass:

- GEMM `(2,2,1)`, `(1,16,32)`, `(2,16,32)`: exact.
- GEMM `(4,32,64)`: within `9.54e-7`.
- 1x1 C1/OC6, grouped 3x3 C4/OC4/G2, legacy 3x3 C4/OC4: exact.
- `conv.py` 3x3 C32/OC128/H14/W14: within `0.015625` (tolerance 0.12).

The initial depthwise split run failed because each case declared a 7,552-byte
output BO while the command stream requires 15,104 bytes (two groups × 7,552,
`DPU_DATA_CUBE_CHANNEL=0x1f`). After correcting both BOs to 15,104 bytes, the
rerun is **702/702 exact on both tasks, max abs diff 0**, with identical output
bytes. The failure was a bundle-size defect, not a datapath mismatch.

The original family description follows.

GEMM: `(2,2,1)`, `(1,16,32)`, `(2,16,32)`, `(4,32,64)` with FP32 output and
50-QWORD Rocket tasks.

Conv: 1x1 C1/H4/W4 → OC6; 3x3 C4/H9/W9 → OC4; 3x3 C32/H14/W14 → OC128/H12/W12;
grouped 3x3 C4/OC4/G2; depthwise 3x3 C3/OC3/G3, including the source's
intentional double submit as two identical tasks.

Each READY case has a single-core stream, three address patches, the vendor
four-QWORD PC tail, and an even-length parity NOP so Rocket never reads past
the command buffer. The nine host oracles match independent NumPy derivation
with zero maximum difference.

BLOCKED: two large `conv.py` paths use `core_mask=0` and multi-core
`subcore_task` assignment plus a runtime regcmd self-address in the PC chain.
Rocket has no equivalent task-descriptor UAPI and the bundle schema has no
runtime-regcmd-address patch kind. These are explicit ABI limitations, not
bundle defects.

## Capture completion

| Family | READY | Real-device state |
|---|---:|---|
| ew-int | 15 | captured, verified |
| ew-fp16 | 54 | captured; 52/54 donor-oracle, FDIV A/7 modeled by 3-guard-bit contract |
| pooling | 19 | captured, full-BO exact |
| fdiv-systematic | 8 | captured, truth table complete |
| conv-fp16 | 9 | captured, 9/9 exact |
| conv-gemm-vendor | 10 | captured, 10/10 pass; depthwise 702/702 exact |
| conv-simple | 7 | captured; 4/7 exact, 1 FP32-C32 layout, 2 INT8 +1 LSB |

Each family runs as one locked queue with only its READY cases. BLOCKED probes
are never submitted. The shared runner validates Rocket's QWORD-pair fetch
extent, which caught the conv-simple odd-word streams and the conv-gemm
duplicate task range before any board action. Both were fixed at the bundle
level and revalidated: conv-simple now carries one zero parity QWORD per READY
stream, and the conv-gemm depthwise second task has its own copied 52-QWORD
stream.
