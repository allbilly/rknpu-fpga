# FP16 FDIV: captured candidate contract

**Status: candidate device-derived behaviour.** This is the implemented RK3588
Rocket EW FDIV slice, not an RK3588 specification, an IEEE-clean divider, or
physical FPGA qualification. The behavioural contract, machine-readable table
and raw captures live under the workspace-local
`build/rk3588-example-captures/` tree and are not part of a source checkout.
`tests/fdiv_capture_vectors.json` preserves the 1,452 real device lanes used by
the regression.

## Encoding and profile

FDIV uses `EW_CFG = 0x108303c0`; the ALU operation field is 4. The captured
FDIV profile differs from ADD/SUB/MUL/MAX in two fixed fields:

| Field | ADD/SUB/MUL/MAX | FDIV |
|---|---|---|
| `OUT_CVT_SCALE` (DPU `0x4084`) | `0x00010001` | `0x00000001` |
| `RDMA_MODE` (RDMA `0x5044`) | `0x00017849` | `0x00017841` |

Both the generated register decoder and `model/profile.py` accept only the
matching pair for the selected operation. A field from the other profile, or an
unknown value, latches error code 2; it does not become an implicit no-op.
Unsupported operation fields remain errors.

## Special values

The precedence below is observed in all 256 class-grid cells. `a_zero`,
`b_zero`, `a_inf` and `b_inf` are magnitude tests. Special results use
`sign(a)`; only the finite datapath uses `sign(a) ^ sign(b)`.

```text
1. any NaN operand                 -> 0x7c01
2. a == 0x0000 and b == 0x0000     -> 0x7c01
3. b magnitude == 0                -> {sign(a), 1_1111, 0}
4. a magnitude == 0                -> {sign(a), 0_0000, 0}
5. a magnitude == infinity         -> {sign(a), 1_1111, 0}   (inf/inf lands here)
6. b magnitude == infinity         -> {sign(a), 0_0000, 0}
7. finite / finite                 -> three-guard-bit RNE, sign(a) ^ sign(b)
```

Consequences captured on the device include `+0/+0 -> 0x7c01` but
`+0/-0 -> +inf`, `-0/+0 -> -inf`, `-0/-0 -> -inf`, `inf/inf -> sign(a)*inf`,
`1/-0 -> +inf` and `1/-inf -> +0`. NaN results are the canonical `0x7c01`, so
negative NaN and arbitrary payloads are not established.

## Finite quotient: three guard bits, ties-to-even

For finite nonzero operands, let `Q` be the exact positive rational quotient,
`e = floor(log2 Q)`, and `u = 2**max(e-10, -24)` the final binary16 quantum.
Then:

```text
n = floor(Q / u)
f = Q/u - n
m = floor(8*f)                  # first three fraction bits
n' = n + 1  if (m > 4) or (m == 4 and n is odd) else n
result = pack(sign(a)^sign(b), n', e)
```

Equivalently, the quotient is truncated three bits below the destination ULP
(no sticky bit) and then rounded to nearest with ties-to-even. This is not
infinite-precision RNE: in the window `0.5 < f < 0.625` with even `n`, truncation
turns a non-tie into an exact half and ties-to-even rounds down. All 20 captured
A/7 one-ULP-low lane records are reproduced by that rule. Four guard bits or an
untruncated quotient round them up and are rejected by the capture set.

The final quantum is `2^-24` for subnormal results, so their guard bits are at
`2^-27`. This is required by the captured `0x0003/2 -> 0x0002` and
`0x8003/2 -> 0x8002` lanes; truncating a normalized 14-bit quotient on the
subnormal shift gives `0x0001`/`0x8001` instead.

Overflow after rounding returns `sign(a)^sign(b) * infinity`. Underflow returns
the signed zero or subnormal encoded from the same rule. Only gross overflow and
the captured underflow ties are observed; the exact `65520` and `2^-25`
boundaries remain inferred, as do negative-NaN, negative-subnormal-class,
subnormal false-tie and negative false-tie behaviour.

## RTL and model shape

`rtl/rk_fp16_alu.sv` keeps ADD/SUB/MUL/MAX at one accepted input cycle. FDIV
special cases also complete in one cycle; finite FDIV uses a 14-step restoring
long division plus one pack cycle. `in_ready` is low while the divider is busy,
and the existing `in_valid`/`in_ready`/`out_valid`/`out_ready` hold-under-
backpressure contract is unchanged.

`model/half.py` implements the same rule with Python integers.
`model/half_datapath.cpp` implements it independently with integer arithmetic.
`tests/test_fdiv.py` also contains an exact-rational RNE reference to show that
the model differs from infinite-precision RNE only on the 20 captured false-tie
records.

## Verification

`tests/fdiv_capture_vectors.json` contains all 1,452 captured lanes:

| Source | Lanes |
|---|---:|
| `real-rocket-fdiv8-special` | 24 |
| `real-rocket-fdiv8` and `real-rocket-fdiv8-finite-sweep` | 40 |
| `fdiv-systematic-20261105T204746Z` 16x16 class grid | 256 |
| `ew-fp16-20261105T201400Z` nine FDIV cases | 1,132 |

Every lane matches `model/half.py`, `model/half_datapath.cpp` and the RTL
simulation bit-for-bit. Of the 1,278 finite-nonzero lanes, 1,258 also match
exact RNE and 20 (19 unique A/7 operand pairs plus the `p1_n33` repeat) are one
ULP low as described above.

The capture fixture records source SHA-256 values. Key inputs:

- `FDIV_CONTRACT.md` `d3ae559644d0dc9b7620974e639f00f7439ed23f5b9146f288c7250eaa5177bf`
- `FDIV_TABLE.json` `d97b24232131980c4c0962fe625ed0e81abca62c12a98438b1a1323796beca58`
- class-grid `class_results.json` `9b6415744c2baa7d7cf75306402164ba277eb1879a44c11c7e787923cfdc8edc`
- A/7-bearing `fdiv_p1_n1024/out.bin` `7bf0a8e72bd673185a7c4c2114c935343fa76e45703930e9b1e890a5875bcf2f`

These are real RK3588 Rocket device outputs, but the source checkout contains
only the extracted fixture. Replaying a capture is not new device evidence.
C++ agreement is not SystemVerilog simulation; RTL simulation is not an FPGA or
RK silicon result. A new board run is required for any new probe.

The current DDR source selections under `rtl/ddr/*/sources.json` and the two
dual-host frontend manifests were rebound to the new hashes of
`rk_fp16_alu.sv`, `rk_ew_regs.sv` and `rk_ew_engine.sv`. That is a source
identity update, not new physical qualification; earlier physical receipts
remain bound to their original source revisions.

## Recorded validation run

On 2026-11-06 in worktree `fdv-rtl` (base commit
`f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`, source manifest
`8dc7d3fa61ba7ff970f70f7bca00333bd86fb3e57897cd002eeb8c522d6a20f3`),
full `make test` exited 0 (`build/make_test3.log`, `build/make_test3.exit`).

| Tool | Version | Result |
|---|---|---|
| Python | 3.14.5 | unit suite and C++ datapath model PASS |
| GCC | 16.2.1 | `numeric_report.json`: 1,813,617 comparisons PASS, including 1,452 capture lanes |
| Verilator | 5.048 | `build/rtl/report.json` PASS: 267 tests, 21,605 ALU vectors, 1,452 FDIV capture vectors, 156 engine scenarios, 63 DMA scenarios |
| Icarus Verilog | 13.0 | `build/iverilog/report.json` PASS: same test/vector/scenario counts in four-state simulation |

The FDIV capture run is `PASS ALU: 1452 vectors, 21118 cycles` under both
simulators. Seeds remain `0x3588` for vectors, `0x12345678` for ALU
backpressure and `0x35881234` for memory backpressure. No lane mismatch remains
against the 1,452 captured records. The inferred/unmeasured items in the
previous section remain unmeasured.

## Live-device closure (2026-11-10)

The FDIV differential is now closed against the real NPU: **1,452 / 1,452
captured lanes live-verified** on the authorized RK3588 target under the
exclusive board lock, against both the frozen capture and the three-guard-bit
model implemented in `rtl/rk_fp16_alu.sv`:

- 256-lane operand-class truth table: 8/8 cases live == capture exactly;
- 1,132 finite lanes: 9 prepared cases live == capture exactly, with exactly
  the 20 documented one-ULP-low `A/7` lanes against donor-RNE;
- 64 residual lanes (24 special + 40 finite/sweep): reconstructed from the
  original captured probe artifacts (command QWORDs/operands/output BOs
  verbatim; only captured DMA-address fields re-patched) and live-verified
  64/64 live == capture == model.

Evidence: `build/rk3588-live-verify/FDIV-RESIDUAL.md`,
`build/rk3588-live-verify/20261109T201838Z-j07/`, plus the P0 job trees and
`build/rtl/report.json` (RTL 1,452-vector PASS). No lane was dropped or
synthesized; one documented evidence caveat: the 8-lane probe's `capture.json`
predates the `dma` field, so its addresses were verified directly from the
captured command QWORDs.
