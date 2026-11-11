# FDIV_CONTRACT — candidate bit-exact RK3588 FP16 divider contract

**Status: CANDIDATE device-derived behaviour. Not an RK3588 specification and
not RTL/FPGA evidence.**

This document proposes a bit-exact behavioural contract for a future FP16 FDIV
path in `rk_fp16_alu` (or a separate divider), derived only from real RK3588
Rocket captures under `build/`. No RTL was modified, no device was accessed by
this analysis, and nothing was programmed or flashed.

Machine-readable data: [`FDIV_TABLE.json`](FDIV_TABLE.json). It contains the
24 special rows, the 32 finite-sweep rows, the 256-pair class table, the full
256-row grid capture, provenance and per-lane records.

**Update 2026-11-06:** the real 256-pair class grid
(`results/fdiv-systematic-20261105T204746Z/`) is now incorporated. It settled
every special-value cell and corrected the pre-grid special-sign rule. The
separate 1,024-lane A/7 finite-rounding evidence is unchanged and remains the
only finite-rounding exception.

---

## 0. Summary card

Special-value precedence (candidate, all 256 class cells observed):

```text
1. any NaN operand                  -> 0x7c01
2. a == 0x0000 and b == 0x0000       -> 0x7c01        (only zero/zero NaN)
3. b magnitude == 0                 -> {sa, 1_1111, 0}   (signed infinity)
4. a magnitude == 0                 -> {sa, 0_0000, 0}   (signed zero)
5. a magnitude == inf               -> {sa, 1_1111, 0}   (inf/inf lands here)
6. b magnitude == inf               -> {sa, 0_0000, 0}   (signed zero)
7. finite / finite                  -> RK_FDIV_3G_RNE, sign = sa ^ sb
```

The critical rule is **special-path results use `sign(a)`, not
`sign(a)^sign(b)`**; only the finite datapath uses sign xor. `sa` is bit 15 of
the numerator.

Finite path (candidate, 0 mismatches on 1278 real finite-nonzero lanes):

```text
Q  = exact rational |a| / |b|
e  = floor(log2(Q))
u  = 2 ** max(e - 10, -24)                  # final binary16 quantum
n  = floor(Q / u)
f  = Q/u - n                                # 0 <= f < 1
m  = floor(8*f)                             # first three fraction bits
n' = n + 1  if (m > 4) or (m == 4 and n is odd) else n
y  = pack(sign = sa ^ sb, n', exponent = e)
```

Equivalently: **deliver the quotient with 11 significand bits plus 3 extra
bits, truncate everything below those 3 bits (no sticky bit), then round the
truncated value to nearest with ties-to-even.** This is not global truncation
and not global IEEE RNE; it is exact RNE except in one narrow false-tie window
(§5).

---

## 1. Evidence inventory

| Capture | Path | Lanes | Result | Notes |
|---|---|---:|---|---|
| `real-rocket-fdiv8` | `build/rk3588-kernel-comparison-v1/real-rocket-fdiv8/` | 8 | `submit_ret=0` | A = 1..8; B = 2; all exact |
| `real-rocket-fdiv8-special` | `.../real-rocket-fdiv8-special/` | 24 | `submit_ret=0` | zeros, infinities, qNaN, subnormals, over/underflow |
| `real-rocket-fdiv8-finite-sweep` | `.../real-rocket-fdiv8-finite-sweep/` | 32 | `submit_ret=0` | rounding, ties, subnormal results, signs |
| `ew-fp16` FDIV results | `results/ew-fp16-20261105T201400Z/fdiv_*` | 1132 logical | `submit_ret=0` | nine cases, including `fdiv_p1_n1024` |
| `fdiv-systematic` | `results/fdiv-systematic-20261105T204746Z/` | **256** | **8/8 `submit_ret=0`, 512 bytes** | full 16x16 operand-class grid |

All executed families use `EW_CFG=0x108303c0`, `OUT_CVT_SCALE=1` and
`RDMA_FEATURE_MODE_CFG=0x00017841`. The `rk3588-kernel-comparison-v1`
captures and the grid were taken on `/dev/accel/accel0` (`submit_ret=0`).
The grid run host is `orangepi5`, kernel
`6.18.24-current-rockchip64`, board Python 3.14.4, runner
`a51de01f...3ab26cd`. The 8 case `output.bin` files are 64 bytes each
(512 bytes total); each hash matches `run_evidence.json`, and each halfword
matches both `class_results.json` and `class_results.tsv`.

Total real FDIV data analysed: **1452 lanes**, of which **1278** have two
finite nonzero operands and therefore exercise quotient generation and
rounding.

### What is directly observed

- All 24 special rows, all 32 finite-sweep rows, all 8 `fdiv8` rows, all 1132
  `ew-fp16` FDIV lanes, and all 256 class-grid lanes are real device outputs.
- The complete 4x4 zero/infinity matrix (§3.2).
- Special-path sign is `sign(a)` for divide-by-zero, inf numerator, inf
  divisor, zero numerator and zero/zero; finite-path sign is `sa^sb`.
- NaN precedence is total: qNaN or sNaN on either side returns `0x7c01` in all
  60 NaN-containing grid cells. **Caveat:** the grid's sNaN class is `0x7c01`,
  which is also the canonical output, so the grid does not prove that an
  arbitrary sNaN payload is canonicalized rather than passed through.
- Finite division matches exact RNE on 1258/1278 lanes and is one ULP low on
  the other 20 lane records (19 unique operand pairs, all A/7).
- Twelve exact destination-ulp ties all round to even, including subnormal
  and zero results.
- Gross overflow produces signed infinity; gross underflow produces signed
  zero; the grid gives all four sign combinations.

### What is inferred

- The 3-guard-bit truncated quotient model and the absence of a sticky bit.
- The internal mechanism of the special `sign(a)` rule (numerator sign
  register vs XOR bypass); the external behaviour is observed.
- Subnormal-result rounding at the final `2^-24` quantum (six `n>0` subnormal
  ties, six zero-result ties, and eight non-tie inexact subnormal results).
- Overflow-to-infinity at the IEEE-like threshold (only gross overflow is
  captured).
- Negative-NaN behaviour (the grid only contains positive qNaN/sNaN).

### What is still unknown

See §5.7. The important remaining items are negative NaN/subnormal class
representatives, the exact overflow and minimum-subnormal boundaries, a
subnormal-result or negative-result false tie, non-unity `OUT_CVT_SCALE`, and
latency/flags.

---

## 2. Reconciliation of the independent oracle and the A/7 exception

The independent oracle team (`team/ew-oracle/ORACLE.md`) reported that the
32-lane finite sweep and the 11 finite special lanes match exact RNE,
including eight exact subnormal ties, while the `ew-fp16` FDIV `p1` cases are
one FP16 ULP low. Both are correct.

- Exact RNE fails **20 lane records (19 unique operand pairs)** out of 1278.
- Round-toward-zero fails **198** lanes.
- The 3-guard-bit truncation plus ties-to-even fails **0** lanes.
- The 256-pair grid adds **100 finite-finite pairs**, all of which match both
  exact RNE and the 3-guard-bit model. It contains one false-tie-window lane
  (`fin_max/sub_max`) but that lane overflows: both exact RNE and the 3-bit
  rule return `+inf`, so it cannot distinguish the models.

The 256 grid therefore **does not contradict** the A/7 exception; it confirms
that ordinary finite pairs follow exact RNE, and the exception is confined to
the false-tie window.

### 2.1 The p1 sequence is not "A/7 everywhere"

`fdiv_p1_n1024` is:

```text
A[i] = i + 1                    (1 .. 1024)
B[i] = 8 - (i mod 8)            (8,7,6,5,4,3,2,1 cyclic)
```

Only lanes with `i mod 8 == 1` divide by 7.0: **128 A/7 lanes** (A = 2, 10,
18, ..., 1018), not 1024. The other 896 lanes divide by 8, 6, 5, 4, 3, 2 or 1.
The 19 unique one-ULP-low operands are all inside the 128-lane A/7
subsequence:

| divisor | lanes | inexact | exact-RNE mismatches |
|---:|---:|---:|---:|
| 8.0 | 128 | 0 | 0 |
| 7.0 | 128 | 110 | **19** |
| 6.0 | 128 | 85 | 0 |
| 5.0 | 128 | 102 | 0 |
| 4.0 | 128 | 0 | 0 |
| 3.0 | 128 | 85 | 0 |
| 2.0 | 128 | 0 | 0 |
| 1.0 | 128 | 0 | 0 |

Within the A/7 subsequence, 109 lanes match exact RNE and 19 are one ULP low
(`device = RNE - 1`). The 19 are:

| lane | A | B | device | exact RNE | delta | n | fraction in ulp | first 3 fraction bits |
|---:|---:|---|---|---|---:|---:|---|---:|
| 17 | 18 (`0x4c80`) | `0x4700` | `0x4124` | `0x4125` | -1 | 1316 | 0.571429 | 100 |
| 49 | 50 (`0x5240`) | `0x4700` | `0x4724` | `0x4725` | -1 | 1828 | 0.571429 | 100 |
| 57 | 58 (`0x5340`) | `0x4700` | `0x4824` | `0x4825` | -1 | 1060 | 0.571429 | 100 |
| 129 | 130 (`0x5810`) | `0x4700` | `0x4ca4` | `0x4ca5` | -1 | 1188 | 0.571429 | 100 |
| 185 | 186 (`0x59d0`) | `0x4700` | `0x4ea4` | `0x4ea5` | -1 | 1700 | 0.571429 | 100 |
| 273 | 274 (`0x5c48`) | `0x4700` | `0x50e4` | `0x50e5` | -1 | 1252 | 0.571429 | 100 |
| 329 | 330 (`0x5d28`) | `0x4700` | `0x51e4` | `0x51e5` | -1 | 1508 | 0.571429 | 100 |
| 385 | 386 (`0x5e08`) | `0x4700` | `0x52e4` | `0x52e5` | -1 | 1764 | 0.571429 | 100 |
| 441 | 442 (`0x5ee8`) | `0x4700` | `0x53e4` | `0x53e5` | -1 | 2020 | 0.571429 | 100 |
| 449 | 450 (`0x5f08`) | `0x4700` | `0x5404` | `0x5405` | -1 | 1028 | 0.571429 | 100 |
| 505 | 506 (`0x5fe8`) | `0x4700` | `0x5484` | `0x5485` | -1 | 1156 | 0.571429 | 100 |
| 561 | 562 (`0x6064`) | `0x4700` | `0x5504` | `0x5505` | -1 | 1284 | 0.571429 | 100 |
| 617 | 618 (`0x60d4`) | `0x4700` | `0x5584` | `0x5585` | -1 | 1412 | 0.571429 | 100 |
| 673 | 674 (`0x6144`) | `0x4700` | `0x5604` | `0x5605` | -1 | 1540 | 0.571429 | 100 |
| 729 | 730 (`0x61b4`) | `0x4700` | `0x5684` | `0x5685` | -1 | 1668 | 0.571429 | 100 |
| 785 | 786 (`0x6224`) | `0x4700` | `0x5704` | `0x5705` | -1 | 1796 | 0.571429 | 100 |
| 841 | 842 (`0x6294`) | `0x4700` | `0x5784` | `0x5785` | -1 | 1924 | 0.571429 | 100 |
| 913 | 914 (`0x6324`) | `0x4700` | `0x5814` | `0x5815` | -1 | 1044 | 0.571429 | 100 |
| 969 | 970 (`0x6394`) | `0x4700` | `0x5854` | `0x5855` | -1 | 1108 | 0.571429 | 100 |

The same operand pair `18/7` also appears in `fdiv_p1_n33` lane 17 with the
same result `0x4124`, which shows the effect is deterministic and independent
of lane position and total length.

### 2.2 The exact trigger, and why A/7 exposes it

For a finite quotient, let `n` be the truncated 11-bit significand and `f` the
fraction of the destination ULP. The observed deviations happen **exactly**
when:

```text
0.5 < f < 0.625   AND   n is even
```

- `f < 0.5` rounds down under both exact RNE and the 3-bit rule.
- `f == 0.5` is a true tie; ties-to-even is observed on all twelve ties.
- `0.5 < f < 0.625` has first three fraction bits `100`. Truncating at three
  bits turns it into an exact half. Ties-to-even then rounds an **even** `n`
  down, while exact RNE would round up.
- If `n` is odd, the same false tie rounds up, so the result accidentally
  matches exact RNE.
- `f >= 0.625` has first three bits `101`, `110` or `111`, so the 3-bit rule
  rounds up exactly as RNE does.

Across all 1278 finite nonzero device lanes there are **48** lanes with
`0.5 < f < 0.625`. Twenty-one have even `n`; twenty are observable 1-ULP-low
mismatches (19 unique operand pairs plus the n33 repeat). The twenty-first is
the grid's `fin_max/sub_max` overflow lane, where both models return `+inf`.
The other 27 have odd `n` and all match exact RNE. This is a complete,
falsifiable explanation of every finite mismatch.

For A/7 specifically, the exact quotient's fraction in ULP units is
`4/7 = 0.571428...`, binary `0.100100100...`, on 19 of the 128 lanes, and all
19 of those have even `n`. The 19 A values are
`18, 50, 58, 130, 186, 274, 330, 386, 442, 450, 506, 562, 618, 674, 730, 786,
842, 914, 970`. They are not `A ≡ 2 (mod 8)` in a simple closed form: the
fraction depends on the exponent, because powers of two rotate the repeating
`1/7` pattern. The algorithmic condition above is the correct characterisation;
the A-list is evidence, not a generator.

### 2.3 Why the sweep and grid finite lanes still match exact RNE

The sweep contains one lane in the false-tie window, `max/10` (`0x7bff/0x4900`,
lane 16): `f = 0.6`, first three bits `100`, but `n = 1637` is **odd**, so the
false tie rounds up and the result equals exact RNE (`0x6e66`). The 100 finite
grid pairs contain one window lane, `fin_max/sub_max` (`n = 1024`, even,
`f ≈ 0.50049`), but it overflows: exact RNE and the 3-bit rule both return
`+inf`, so it is unobservable. None of the other sweep, special or grid finite
lanes land in the window with even `n`. The oracle's statement was therefore
right for its finite subset; the `ew-fp16` p1 A/7 subset just happens to
contain the 19 discriminating lanes.

### 2.4 Subnormal-quantum evidence

The model uses **3 bits below the final destination quantum**, which is
`2^-24` for subnormal results. The alternative "3 bits below the normalized
significand quantum `2^(e-10)`" was tested and fails exactly two lanes:
`0x0003/2 -> 0x0002` and `0x8003/2 -> 0x8002` (sweep lanes 11 and 30). A
normalized-14-bit divider that then truncates on the subnormal shift would
produce `0x0001`/`0x8001`, which the device does not. The final-quantum rule
matches all 1278 lanes, including the twelve exact ties.

This does **not** prove how a real subnormal quotient is generated. The older
captures contribute two non-tie inexact subnormal results and four `n>0` ties;
the grid contributes six non-tie inexact true subnormal results and two `n>0`
ties. None is in the false-tie window.

### 2.5 Rejected models at a glance

| Model | Mismatches / 1278 | Verdict |
|---|---:|---|
| exact binary16 RNE | 20 lane records (19 unique) | rejected |
| truncate toward zero, saturating on overflow | 198 | rejected |
| truncate significand at final ULP, IEEE overflow | 185 | rejected |
| 1 guard bit, then RNE | 135 | rejected |
| 2 guard bits, then RNE | 90 | rejected |
| **3 guard bits, then RNE (no sticky)** | **0** | **accepted** |
| 4 guard bits, then RNE | 20 | rejected |
| round exact to 14 bits, then RNE | 20 | rejected |
| normalized 14-bit, truncate on subnormal shift | 74 (2 in the older 1178 subset) | rejected |
| reciprocal (half RNE) then multiply (half RNE) | 171 (155 in p1 alone) | rejected |

All counts are over the 1278 finite nonzero lanes unless noted. The 3-bit
model is the unique member of this family with zero mismatches, and the A/7
ties require *exactly* three guard bits.

---

## 3. Behavioral decision tables

### 3.1 Operand-class decision table (all 256 cells observed)

`O` = directly observed on a real device. There are no `U` cells left in the
16x16 class matrix; the remaining unknowns are outside the class set (§5.7).

| Case | Result | Status | Evidence |
|---|---|---|---|
| any NaN operand (q or s) | `0x7c01` | O | all 60 NaN-containing grid cells |
| `+0 / +0` | `0x7c01` | O | grid pair 0 |
| `+0 / -0` | `0x7c00` (+inf) | O | grid pair 1 |
| `-0 / +0` | `0xfc00` (-inf) | O | grid pair 16 |
| `-0 / -0` | `0xfc00` (-inf) | O | grid pair 17 |
| `±finite / +0` | `sign(a) * inf` | O | half the grid rows |
| `±finite / -0` | `sign(a) * inf` | O | half the grid rows |
| `±inf / ±0` | `sign(a) * inf` | O | inf rows |
| `+inf / +inf`, `+inf / -inf` | `0x7c00` (+inf) | O | grid pairs 34, 35 |
| `-inf / +inf`, `-inf / -inf` | `0xfc00` | O | grid pairs 50, 51 |
| `±inf / finite` | `sign(a) * inf` | O | inf rows |
| `±finite / +inf`, `±finite / -inf` | `sign(a) * 0` | O | finite rows |
| `±0 / finite nonzero` | `sign(a) * 0` | O | zero rows |
| `±0 / ±inf` | `sign(a) * 0` | O | zero rows |
| finite / finite, exact | exact | O | many |
| finite / finite, inexact | 3-guard-bit RNE, sign `sa^sb` | O | 1278 lanes, 0 model mismatches |
| finite overflow | `sa^sb * inf` | O gross; **U boundary** | grid `fin_max/half_n`, etc. |
| finite underflow | `sa^sb * 0` | O gross and ties; **U boundary** | grid `sub_min/two_n`, etc. |

The pre-grid contract used `sa^sb` for the special paths and was wrong on
**40/256** grid cells. The corrected `sign(a)` rule matches 256/256.

### 3.2 Zero/infinity matrix (real device)

| A \ B | `+0` | `-0` | `+inf` | `-inf` |
|---|---|---|---|---|
| `+0` | `0x7c01` | `0x7c00` | `0x0000` | `0x0000` |
| `-0` | `0xfc00` | `0xfc00` | `0x8000` | `0x8000` |
| `+inf` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` |
| `-inf` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` |

This matrix is the strongest single discriminator between `sign(a)` and
`sign(a)^sign(b)`: e.g. `+1/-0 -> +inf`, `+inf/-1 -> +inf`, `+1/-inf -> +0`.

### 3.3 Sign-rule probes

| Case | A class | B class | device | finite-path sign | special-path sign |
|---|---|---|---|---|---|
| finite-numerator / -0 | `one_p` | `zero_n` | `0x7c00` | sign(a)^sign(b) | sign(a) |
| negative finite / -0 | `one_n` | `zero_n` | `0xfc00` | sign(a)^sign(b) | sign(a) |
| finite-numerator / -inf | `one_p` | `inf_n` | `0x0000` | sign(a)^sign(b) | sign(a) |
| negative finite / -inf | `one_n` | `inf_n` | `0x8000` | sign(a)^sign(b) | sign(a) |
| -0 / finite-positive | `zero_n` | `one_p` | `0x8000` | sign(a)^sign(b) | sign(a) |
| -0 / finite-negative | `zero_n` | `one_n` | `0x8000` | sign(a)^sign(b) | sign(a) |
| +inf / finite-negative | `inf_p` | `one_n` | `0x7c00` | sign(a)^sign(b) | sign(a) |
| -inf / finite-negative | `inf_n` | `one_n` | `0xfc00` | sign(a)^sign(b) | sign(a) |
| finite overflow with - divisor | `fin_max` | `half_n` | `0xfc00` | sign(a)^sign(b) | sign(a) |
| finite underflow with - divisor | `sub_min` | `two_n` | `0x8000` | sign(a)^sign(b) | sign(a) |

The first eight rows are special-path results and follow `sign(a)`. The last
two are finite-path results (overflow/underflow) and follow `sign(a)^sign(b)`;
they are included to show that the special rule is not a global "ignore the
divisor sign" bug.

### 3.4 Finite rounding decision table

| Exact quotient condition | Result | Status | Observed support |
|---|---|---|---|
| `f == 0` | exact | O | many exact lanes |
| `f < 0.5` | `n` (round down) | O | sweep, p1, grid |
| `f == 0.5` | `n` if even, `n+1` if odd | O | 12 exact ties |
| `0.5 < f < 0.625`, `n` odd | `n+1` (round up) | O | 27 lanes |
| `0.5 < f < 0.625`, `n` even | `n` (round down; **1 ULP below RNE**) | O | 20 observable lane records / 19 unique |
| `f >= 0.625` | `n+1` (round up) | O | sweep, p1, grid |
| subnormal result (`u = 2^-24`) | same rule at the `2^-24` quantum | O for exact ties; I for window | 24 true subnormal + 2 min-normal |
| overflow | `sa^sb * inf` | O gross; **U boundary** | 13 lanes |
| underflow | `sa^sb * 0` | O gross and tie; **U boundary** | 11 lanes |

### 3.5 The 24 special rows (real device, `real-rocket-fdiv8-special`)

| # | A bits | A class | B bits | B class | device | IEEE class | IEEE bits | donor bits | verdict | grid | note |
|---:|---|---|---|---|---|---|---|---|---|---|---|
| 0 | `0x3c00` | norm_p | `0x0000` | zero_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 160) | IEEE divide-by-zero; special-path sign(a) |
| 1 | `0xbc00` | norm_n | `0x0000` | zero_p | `0xfc00` (inf_n) | inf | `0xfc00` | `0xfc00` | match | `0xfc00` (pair 176) | IEEE divide-by-zero; special-path sign(a) |
| 2 | `0x0000` | zero_p | `0x0000` | zero_p | `0x7c01` (snan) | nan | `qNaN (payload free)` | `0xfe00` | nan-class-match-encoding-quirk | `0x7c01` (pair 0) | **QUIRK**: IEEE requires qNaN; 0x7c01 is the sNaN encoding |
| 3 | `0x8000` | zero_n | `0x0000` | zero_p | `0xfc00` (inf_n) | nan | `qNaN (payload free)` | `0xfe00` | ieee-violation | `0xfc00` (pair 16) | **QUIRK**: IEEE requires qNaN; zero/zero non-NaN -> sign(a)*inf |
| 4 | `0x7c00` | inf_p | `0x7c00` | inf_p | `0x7c00` (inf_p) | nan | `qNaN (payload free)` | `0xfe00` | ieee-violation | `0x7c00` (pair 34) | **QUIRK**: IEEE requires qNaN; inf/inf -> sign(a)*inf |
| 5 | `0xfc00` | inf_n | `0x7c00` | inf_p | `0xfc00` (inf_n) | nan | `qNaN (payload free)` | `0xfe00` | ieee-violation | `0xfc00` (pair 50) | **QUIRK**: IEEE requires qNaN; inf/inf -> sign(a)*inf |
| 6 | `0x7c00` | inf_p | `0x3c00` | norm_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 42) | IEEE inf numerator; special-path sign(a) |
| 7 | `0x3c00` | norm_p | `0x7c00` | inf_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 162) | IEEE finite / inf -> zero; special-path sign(a) |
| 8 | `0xbc00` | norm_n | `0x7c00` | inf_p | `0x8000` (zero_n) | zero | `0x8000` | `0x8000` | match | `0x8000` (pair 178) | IEEE finite / inf -> zero; special-path sign(a) |
| 9 | `0x7c00` | inf_p | `0x0000` | zero_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 32) | IEEE inf / zero -> inf; special-path sign(a) |
| 10 | `0x0000` | zero_p | `0x7c00` | inf_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 2) | IEEE zero / inf -> zero; special-path sign(a) |
| 11 | `0x7e00` | qnan | `0x3c00` | norm_p | `0x7c01` (snan) | nan | `qNaN (payload free)` | `0x7e00` | nan-class-match-encoding-quirk | `0x7c01` (pair 74) | **QUIRK**: canonical 0x7c01, payload dropped, quiet bit clear |
| 12 | `0x3c00` | norm_p | `0x7e00` | qnan | `0x7c01` (snan) | nan | `qNaN (payload free)` | `0x7e00` | nan-class-match-encoding-quirk | `0x7c01` (pair 164) | **QUIRK**: canonical 0x7c01, payload dropped, quiet bit clear |
| 13 | `0x3c00` | norm_p | `0x4200` | norm_p | `0x3555` (norm_p) | finite | `0x3555` | `0x3555` | match | — | finite; exact 1/3; 3G model = RNE |
| 14 | `0x4000` | norm_p | `0x4200` | norm_p | `0x3955` (norm_p) | finite | `0x3955` | `0x3955` | match | — | finite; exact 2/3; 3G model = RNE |
| 15 | `0x3c00` | norm_p | `0x4900` | norm_p | `0x2e66` (norm_p) | finite | `0x2e66` | `0x2e66` | match | — | finite; exact 1/10; 3G model = RNE |
| 16 | `0x7bff` | norm_p | `0x4200` | norm_p | `0x7555` (norm_p) | finite | `0x7555` | `0x7555` | match | — | finite; exact 65504/3; 3G model = RNE |
| 17 | `0x0001` | sub_p | `0x4000` | norm_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 110) | exact tie 0.5 ulp -> +0 (ties-to-even) |
| 18 | `0x0400` | norm_p | `0x4000` | norm_p | `0x0200` (sub_p) | finite | `0x0200` | `0x0200` | match | `0x0200` (pair 142) | exact subnormal result 0x0200 |
| 19 | `0x7bff` | norm_p | `0x3c00` | norm_p | `0x7bff` (norm_p) | finite | `0x7bff` | `0x7bff` | match | `0x7bff` (pair 154) | exact quotient |
| 20 | `0x7bff` | norm_p | `0x0400` | norm_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 152) | gross overflow -> +inf |
| 21 | `0x3c00` | norm_p | `0x0001` | sub_p | `0x7c00` (inf_p) | inf | `0x7c00` | `0x7c00` | match | `0x7c00` (pair 166) | gross overflow (exact 2^24) -> +inf |
| 22 | `0x0001` | sub_p | `0x7bff` | norm_p | `0x0000` (zero_p) | zero | `0x0000` | `0x0000` | match | `0x0000` (pair 105) | gross underflow -> +0 |
| 23 | `0x8001` | sub_n | `0x4000` | norm_p | `0x8000` (zero_n) | zero | `0x8000` | `0x8000` | match | — | exact negative tie 0.5 ulp -> -0 |

IEEE comparison: 21/24 rows are class-correct; rows **3, 4, 5** return infinity
where IEEE 754 requires a quiet NaN. Rows **2, 11, 12** are NaN-class-correct
but encode the result as `0x7c01`, whose quiet bit is clear; strict IEEE 754
requires a quiet NaN. The remaining 18 rows are class- and sign-correct.
Donor comparison (`float16(float32(a)/float32(b))`, NumPy 2.4.6): 6/24
mismatches, exactly rows 2, 3, 4, 5, 11 and 12. The donor's NaN patterns
(`0xfe00` for 0/0 and inf/inf, `0x7e00` for qNaN propagation) are host-specific
and are not device evidence.

### 3.6 The 32 finite-sweep rows (real device)

| # | A | B | device | exact quotient | RNE | contract | tags | delta |
|---:|---|---|---|---|---|---|---|---:|
| 0 | `0x3c00` 1 | `0x4200` 3 | `0x3555` | 0.333333333333 (`1/3`) | `0x3555` | `0x3555` | inexact | 0 |
| 1 | `0x4000` 2 | `0x4200` 3 | `0x3955` | 0.666666666667 (`2/3`) | `0x3955` | `0x3955` | inexact | 0 |
| 2 | `0x3c00` 1 | `0x4900` 10 | `0x2e66` | 0.1 (`1/10`) | `0x2e66` | `0x2e66` | inexact | 0 |
| 3 | `0x4900` 10 | `0x3c00` 1 | `0x4900` | 10 (`10/1`) | `0x4900` | `0x4900` | exact | 0 |
| 4 | `0x7bff` 65504 | `0x4200` 3 | `0x7555` | 21834.6666667 (`65504/3`) | `0x7555` | `0x7555` | inexact | 0 |
| 5 | `0x4200` 3 | `0x7bff` 65504 | `0x0300` | 4.57987298486e-05 (`3/65504`) | `0x0300` | `0x0300` | inexact, subnormal-result | 0 |
| 6 | `0x0001` 5.96046448e-08 | `0x4000` 2 | `0x0000` | 2.98023223877e-08 (`1/33554432`) | `0x0000` | `0x0000` | inexact, true-tie, underflow-to-zero | 0 |
| 7 | `0x0400` 6.10351562e-05 | `0x4200` 3 | `0x0155` | 2.03450520833e-05 (`1/49152`) | `0x0155` | `0x0155` | inexact, subnormal-result | 0 |
| 8 | `0x3c01` 1.00097656 | `0x4001` 2.00195312 | `0x3800` | 0.5 (`1/2`) | `0x3800` | `0x3800` | exact | 0 |
| 9 | `0x7bff` 65504 | `0x7bff` 65504 | `0x3c00` | 1 (`1/1`) | `0x3c00` | `0x3c00` | exact | 0 |
| 10 | `0x0001` 5.96046448e-08 | `0x0001` 5.96046448e-08 | `0x3c00` | 1 (`1/1`) | `0x3c00` | `0x3c00` | exact | 0 |
| 11 | `0x0003` 1.78813934e-07 | `0x4000` 2 | `0x0002` | 8.94069671631e-08 (`3/33554432`) | `0x0002` | `0x0002` | inexact, true-tie, subnormal-result | 0 |
| 12 | `0x0005` 2.98023224e-07 | `0x4000` 2 | `0x0002` | 1.49011611938e-07 (`5/33554432`) | `0x0002` | `0x0002` | inexact, true-tie, subnormal-result | 0 |
| 13 | `0x0400` 6.10351562e-05 | `0x4000` 2 | `0x0200` | 3.0517578125e-05 (`1/32768`) | `0x0200` | `0x0200` | exact, subnormal-result | 0 |
| 14 | `0x0401` 6.10947609e-05 | `0x4000` 2 | `0x0200` | 3.05473804474e-05 (`1025/33554432`) | `0x0200` | `0x0200` | inexact, true-tie, subnormal-result | 0 |
| 15 | `0x7bff` 65504 | `0x4000` 2 | `0x77ff` | 32752 (`32752/1`) | `0x77ff` | `0x77ff` | exact | 0 |
| 16 | `0x7bff` 65504 | `0x4900` 10 | `0x6e66` | 6550.4 (`32752/5`) | `0x6e66` | `0x6e66` | inexact, false-tie-window | 0 |
| 17 | `0x4900` 10 | `0x4200` 3 | `0x42ab` | 3.33333333333 (`10/3`) | `0x42ab` | `0x42ab` | inexact | 0 |
| 18 | `0x4800` 8 | `0x4200` 3 | `0x4155` | 2.66666666667 (`8/3`) | `0x4155` | `0x4155` | inexact | 0 |
| 19 | `0x4200` 3 | `0x4800` 8 | `0x3600` | 0.375 (`3/8`) | `0x3600` | `0x3600` | exact | 0 |
| 20 | `0x3c00` 1 | `0x4600` 6 | `0x3155` | 0.166666666667 (`1/6`) | `0x3155` | `0x3155` | inexact | 0 |
| 21 | `0x4600` 6 | `0x4200` 3 | `0x4000` | 2 (`2/1`) | `0x4000` | `0x4000` | exact | 0 |
| 22 | `0x3c00` 1 | `0x3c01` 1.00097656 | `0x3bfe` | 0.999024390244 (`1024/1025`) | `0x3bfe` | `0x3bfe` | inexact | 0 |
| 23 | `0x3c01` 1.00097656 | `0x3c00` 1 | `0x3c01` | 1.0009765625 (`1025/1024`) | `0x3c01` | `0x3c01` | exact | 0 |
| 24 | `0x4001` 2.00195312 | `0x4200` 3 | `0x3957` | 0.667317708333 (`1025/1536`) | `0x3957` | `0x3957` | inexact | 0 |
| 25 | `0x3c00` 1 | `0x4201` 3.00195312 | `0x3554` | 0.333116460638 (`512/1537`) | `0x3554` | `0x3554` | inexact | 0 |
| 26 | `0x3555` 0.333251953 | `0x3c00` 1 | `0x3555` | 0.333251953125 (`1365/4096`) | `0x3555` | `0x3555` | exact | 0 |
| 27 | `0x3c00` 1 | `0x3555` 0.333251953 | `0x4200` | 3.00073260073 (`4096/1365`) | `0x4200` | `0x4200` | inexact | 0 |
| 28 | `0x8001` -5.96046448e-08 | `0x4000` 2 | `0x8000` | -2.98023223877e-08 (`-1/33554432`) | `0x8000` | `0x8000` | inexact, true-tie, underflow-to-zero | 0 |
| 29 | `0x8001` -5.96046448e-08 | `0x4200` 3 | `0x8000` | -1.98682149251e-08 (`-1/50331648`) | `0x8000` | `0x8000` | inexact, underflow-to-zero | 0 |
| 30 | `0x8003` -1.78813934e-07 | `0x4000` 2 | `0x8002` | -8.94069671631e-08 (`-3/33554432`) | `0x8002` | `0x8002` | inexact, true-tie, subnormal-result | 0 |
| 31 | `0xbc00` -1 | `0x4000` 2 | `0xb800` | -0.5 (`-1/2`) | `0xb800` | `0xb800` | exact | 0 |

The twelve true destination-ULP ties are sweep lanes **6, 11, 12, 14, 28, 30**,
special lanes **17, 23**, and grid cells `sub_min/two_p`, `sub_min/two_n`,
`sub_max/two_p`, `sub_max/two_n`. All twelve round to even. Sweep lane 16 is
the only false-tie-window lane in this table; `n` is odd, so it matches RNE.
That is why all 32 sweep rows agree with the independent exact-RNE oracle.

---

## 4. The 256-pair class grid (real device)

Run `20261105T204746Z`: 8 cases, 32 lanes each, 512 output bytes, every
`submit_ret=0`. The pair order is row-major, A class outer. The matrix below is
the raw device output for each cell.

| A \ B | `zero_p` | `zero_n` | `inf_p` | `inf_n` | `qnan` | `snan` | `sub_min` | `sub_max` | `norm_min` | `fin_max` | `one_p` | `one_n` | `half_p` | `half_n` | `two_p` | `two_n` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `zero_p` | `0x7c01` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x0000` | `0x0000` | `0x0000` | `0x0000` | `0x0000` | `0x0000` | `0x0000` | `0x0000` | `0x0000` | `0x0000` |
| `zero_n` | `0xfc00` | `0xfc00` | `0x8000` | `0x8000` | `0x7c01` | `0x7c01` | `0x8000` | `0x8000` | `0x8000` | `0x8000` | `0x8000` | `0x8000` | `0x8000` | `0x8000` | `0x8000` | `0x8000` |
| `inf_p` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c01` | `0x7c01` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` |
| `inf_n` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0x7c01` | `0x7c01` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` |
| `qnan` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` |
| `snan` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` | `0x7c01` |
| `sub_min` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x3c00` | `0x1401` | `0x1400` | `0x0000` | `0x0001` | `0x8001` | `0x0002` | `0x8002` | `0x0000` | `0x8000` |
| `sub_max` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x63fe` | `0x3c00` | `0x3bfe` | `0x0000` | `0x03ff` | `0x83ff` | `0x07fe` | `0x87fe` | `0x0200` | `0x8200` |
| `norm_min` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x6400` | `0x3c01` | `0x3c00` | `0x0000` | `0x0400` | `0x8400` | `0x0800` | `0x8800` | `0x0200` | `0x8200` |
| `fin_max` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x7c00` | `0x7c00` | `0x7c00` | `0x3c00` | `0x7bff` | `0xfbff` | `0x7c00` | `0xfc00` | `0x77ff` | `0xf7ff` |
| `one_p` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x7c00` | `0x7401` | `0x7400` | `0x0100` | `0x3c00` | `0xbc00` | `0x4000` | `0xc000` | `0x3800` | `0xb800` |
| `one_n` | `0xfc00` | `0xfc00` | `0x8000` | `0x8000` | `0x7c01` | `0x7c01` | `0xfc00` | `0xf401` | `0xf400` | `0x8100` | `0xbc00` | `0x3c00` | `0xc000` | `0x4000` | `0xb800` | `0x3800` |
| `half_p` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x7c00` | `0x7001` | `0x7000` | `0x0080` | `0x3800` | `0xb800` | `0x3c00` | `0xbc00` | `0x3400` | `0xb400` |
| `half_n` | `0xfc00` | `0xfc00` | `0x8000` | `0x8000` | `0x7c01` | `0x7c01` | `0xfc00` | `0xf001` | `0xf000` | `0x8080` | `0xb800` | `0x3800` | `0xbc00` | `0x3c00` | `0xb400` | `0x3400` |
| `two_p` | `0x7c00` | `0x7c00` | `0x0000` | `0x0000` | `0x7c01` | `0x7c01` | `0x7c00` | `0x7801` | `0x7800` | `0x0200` | `0x4000` | `0xc000` | `0x4400` | `0xc400` | `0x3c00` | `0xbc00` |
| `two_n` | `0xfc00` | `0xfc00` | `0x8000` | `0x8000` | `0x7c01` | `0x7c01` | `0xfc00` | `0xf801` | `0xf800` | `0x8200` | `0xc000` | `0x4000` | `0xc400` | `0x4400` | `0xbc00` | `0x3c00` |

All 256 cells are observed; there is no unknown cell in this matrix. The
proposed contract reproduces **256/256**. The pre-grid contract (which used
`sa^sb` for special results) missed **40/256** cells.

### 4.1 What the grid corrected

The 40 pre-grid failures are concentrated in the special paths:

| Rule | Pre-grid prediction | Grid result | Cells |
|---|---|---|---|
| divide-by-zero with `b = -0` | `sign(a)^sign(b) * inf` | `sign(a) * inf` | all finite/inf A rows with B=`-0` |
| finite / `-inf` | `sign(a)^sign(b) * 0` | `sign(a) * 0` | all finite A rows with B=`-inf` |
| `±0 / negative finite` | `sign(a)^sign(b) * 0` | `sign(a) * 0` | `zero_p/one_n`, `zero_p/half_n`, `zero_p/two_n`, `zero_n/...` |
| `±inf / negative finite` | `sign(a)^sign(b) * inf` | `sign(a) * inf` | `inf_p/one_n`, `inf_p/half_n`, `inf_p/two_n`, `inf_n/...` |
| `±0 / ±0` non-NaN | `sign(a)^sign(b) * inf` | `sign(a) * inf` | `zero_p/zero_n`, `zero_n/zero_n` |
| `±inf / ±inf` | `sign(a)^sign(b) * inf` | `sign(a) * inf` | `inf_p/inf_n`, `inf_n/inf_n` |

The exact per-pair before/after values are in
`FDIV_TABLE.json` → `class_pair_table[].pre_grid_contract_bits` and
`pre_grid_contract_correct`.

### 4.2 IEEE and donor comparison for the grid

| Category | Count / 256 |
|---|---:|
| bit-identical to IEEE (finite or matching inf/zero sign) | 152 |
| same class, opposite sign only (`special sign(a)` quirk) | 36 |
| NaN class but quiet bit clear (`0x7c01`) | 61 |
| infinity where IEEE requires NaN | 7 |
| donor (`numpy float16(float32(a)/float32(b))`) mismatches | 104 |

The 7 "infinity instead of NaN" cells are the three non-NaN zero/zero cells
(`+0/+0` is NaN; `+0/-0`, `-0/+0`, `-0/-0` are infinity) plus the four
inf/inf sign pairs. Strict IEEE 754 would return a quiet NaN for all eight;
the device returns NaN only for `+0/+0`.

### 4.3 Finite pairs in the grid

The 100 finite-finite pairs:

| Metric | Count |
|---|---:|
| pairs | 100 |
| exact RNE mismatches | 0 |
| 3-guard-bit contract mismatches | 0 |
| inexact | 22 |
| exact destination-ULP ties | 4 |
| subnormal results | 16 |
| min-normal results | 2 |
| underflow to zero | 5 |
| overflow to inf | 11 |
| false-tie-window lanes | 1 (overflow-moot) |

This is a strong confirmation of the finite contract on class-representative
operands, but it does not exercise a subnormal-window or negative-window
false tie. The A/7 capture remains the only discriminating finite-rounding
evidence.

Notable subnormal/overflow cells:

- `sub_min/sub_max = 0x1401` (the exact `1/1023` rounded to nearest; an
  inexact normal-range quotient that exercises subnormal operand
  normalization).
- `sub_min/two_p = 0x0000` and `sub_max/two_p = 0x0200` are exact
  subnormal-boundary ties; `sub_min/two_n = 0x8000` and `sub_max/two_n =
  0x8200` show the finite underflow/rounding sign is `sa^sb`.
- `fin_max/half_n = 0xfc00` and `fin_max/two_n = 0xf7ff` show finite overflow
  and finite rounding use `sa^sb`, unlike the special paths.
- `fin_max/sub_min`, `fin_max/sub_max`, `fin_max/norm_min` and
  `fin_max/half_p` all overflow to `+inf`, confirming gross overflow. The
  exact overflow threshold is still unmeasured.

---

## 5. Proposed bit-exact RTL contract

The contract is behavioural. It does not prescribe latency, pipelining,
resource sharing or exception flags; none of those were captured.

### 5.1 Interface and encoding

```text
input  logic [15:0] a, b
output logic [15:0] y
```

- Binary16 little-endian halfwords. `a[15]`/`b[15]` sign, `[14:10]` biased
  exponent, `[9:0]` fraction.
- Data-only result; the captured EW path exposes no IEEE exception flags.
- A future `rk_fp16_alu` opcode slot is not assigned here. `EW_CFG=0x108303c0`
  selects FDIV in the captured register stream; the ALU `in_op` encoding is a
  separate integration decision and must not silently reuse another opcode.
- No clock-enable, back-pressure or latency requirement is implied.

### 5.2 Special-value precedence (candidate, 256/256 observed)

The order matters. `a_zero`, `b_zero`, `a_inf`, `b_inf` below are **magnitude**
tests; only the zero/zero rule uses raw patterns. Special results use `sa`,
not `sa^sb`.

```text
sa = a[15]; sb = b[15]; sr = sa ^ sb;
a_nan = (a[14:10]==31) && (a[9:0]!=0);
b_nan = (b[14:10]==31) && (b[9:0]!=0);
a_inf = (a[14:10]==31) && (a[9:0]==0);
b_inf = (b[14:10]==31) && (b[9:0]==0);
a_zero = (a[14:0]==0);          // magnitude zero, covers +0 and -0
b_zero = (b[14:0]==0);

if (a_nan || b_nan)          y = 16'h7c01;
else if (a == 16'h0000 && b == 16'h0000)
                             y = 16'h7c01;          // Q1
else if (b_zero)             y = {sa, 5'h1f, 10'b0}; // Q2, Q4
else if (a_zero)             y = {sa, 5'h00, 10'b0}; // Q4
else if (a_inf)              y = {sa, 5'h1f, 10'b0}; // Q3, Q4 (inf/inf)
else if (b_inf)              y = {sa, 5'h00, 10'b0}; // Q4
else                         y = finite_div(a, b);   // sign = sr
```

Check against the captured matrix:

- `+0/+0` hits the raw zero/zero rule → `0x7c01`.
- `+0/-0` fails the raw rule; `b_zero` → `{sa=0, inf}` = `0x7c00`.
- `-0/+0` → `{sa=1, inf}` = `0xfc00`; `-0/-0` → `0xfc00`.
- `+inf/+inf` and `+inf/-inf` → `a_inf` → `0x7c00`.
- `-inf/+inf` and `-inf/-inf` → `a_inf` → `0xfc00`.
- `+1/-0` → `b_zero` → `0x7c00` (not `-inf`).
- `+1/-inf` → `b_inf` → `0x0000` (not `-0`).
- `-0/+1` → `a_zero` → `0x8000` (not `+0`).
- `+0/+inf` → `a_zero` (before `b_inf`) → `0x0000`.
- Finite overflow/underflow go through `finite_div` and use `sr`.

NaN is checked first, matching the existing `rk_fp16_alu` style. The grid
confirms NaN precedence over zero and infinity for all 60 NaN-containing class
cells.

### 5.3 Finite quotient generation

For finite nonzero operands:

```text
// 1. Unpack to a normalized integer significand and a leading-bit exponent.
if (ea != 0) begin Ma = 11'd1024 | fa; Ea = ea - 15; end
else begin
    // fa != 0 here because a_zero was handled above
    k  = 10 - msb_index(fa);        // 0..10
    Ma = fa << k;                   // 1024..2047
    Ea = -14 - k;                   // -24..-15
end
// same for Mb, Eb

// 2. Normalize the ratio to [1,2).
if (Ma >= Mb) begin e = Ea - Eb;       qn = Ma;      qd = Mb;      end
else          begin e = Ea - Eb - 1;   qn = Ma << 1; qd = Mb;      end

// 3. Destination quantum: 11-bit normal significand or 2^-24 subnormal.
ue = (e >= -14) ? e - 10 : -24;

// 4. Quotient with 3 bits below the final quantum, truncated.
//    D = floor(8 * Q/u) = floor(qn * 2^(e-ue+3) / qd)
shift = e - ue + 3;
D = (shift >= 0) ? ((qn << shift) / qd) : (qn / (qd << -shift));
n = D >> 3;                 // truncated 11-bit significand
m = D & 7;                  // first three fraction bits

// 5. Round to nearest, ties-to-even on the truncated value.
if (m > 4 || (m == 4 && n[0])) n = n + 1;

// 6. Pack with sign sr = sa ^ sb.
if (n == 2048) begin n = 1024; e = e + 1; end
if (n == 1024 && e < -14) e = -14;   // carry out of the subnormal range
if (e < -14)                  y = {sr, 5'h00, n[9:0]};   // subnormal or zero
else if (e > 15)              y = {sr, 5'h1f, 10'b0};    // overflow
else                          y = {sr, 5'(e + 15), (n - 1024)};
```

### 5.4 Rounding rule in words

- The quotient is **truncated at 3 bits below the destination ULP**; no sticky
  bit from lower bits is used.
- The truncated value is rounded to the nearest 11-bit significand; an exact
  half rounds to even.
- For normal results the destination ULP is `2^(e-10)`.
- For subnormal results the destination ULP is `2^-24`, so the three guard bits
  are at `2^-27`. This final-quantum placement is required by the captured
  `0x0003/2` and `0x8003/2` ties (§2.4).
- The finite-path sign is `sa ^ sb`; the special-path sign is `sa`.

### 5.5 Overflow, underflow and zero

- **Overflow:** after rounding, if the exponent exceeds 15, return
  `{sr, 5'h1f, 10'b0}`. The natural threshold is the IEEE-like one: exact
  values below `65520` round to `0x7bff`; values at or above `65520` carry to
  2048 and become infinity. **Only gross overflow is captured**; the exact
  threshold is inferred from the rounding rule, not measured.
- **Underflow:** `n == 0` with `ue == -24` returns signed zero with `sr`. A
  value exactly at half the minimum subnormal (`2^-25`) ties to even and
  returns zero (observed for `+` and `-`). Values in `(2^-25, 2^-24)` round up
  to `0x0001` under the same rule; **not captured**.
- **Subnormal to normal:** `n == 1024` with `ue == -24` encodes `0x0400`.
- **Signed zero:** for the finite path always `{sr, 15'b0}`; for the special
  path always `{sa, 15'b0}`.

### 5.6 Captured quirks the contract reproduces

| Quirk | Contract mechanism | Status |
|---|---|---|
| `+0/+0 -> 0x7c01` | raw `a==0 && b==0` test before divide-by-zero | observed |
| `+0/-0 -> +inf`, `-0/+0 -> -inf`, `-0/-0 -> -inf` | zero/zero non-NaN returns `sign(a)*inf` | observed |
| `+inf/+inf`, `+inf/-inf -> +inf`; `-inf/+inf`, `-inf/-inf -> -inf` | no inf/inf invalid; `a_inf` returns `sign(a)*inf` | observed |
| divide-by-zero sign | `sign(a)`, not `sa^sb` | observed |
| finite / infinity sign | `sign(a)`, not `sa^sb` | observed |
| zero numerator sign | `sign(a)`, not `sa^sb` | observed |
| qNaN/sNaN -> `0x7c01` | NaN canonicalization, payload/sign dropped | observed |
| A/7 one-ULP-low | 3-guard-bit truncation false tie, ties-to-even | observed |
| finite overflow/underflow sign | `sa^sb` (contrast with special paths) | observed |
| `max/min_norm`, `1/min_sub -> inf` | overflow after rounding | observed gross |
| `min_sub/max -> +0`, `±min_sub/2 -> ±0` | underflow / tie-to-even | observed |

### 5.7 Rules that need more device data (do not guess)

Marked **[NEEDS DEVICE]**. An implementation may encode the candidate rule, but
must label it candidate and must not present it as verified.

1. **Negative NaN operands** (`0xfe00`, `0xfc01`, ...) and **sNaN payloads
   other than `0x7c01`**. The grid only has positive qNaN (`0x7e00`) and sNaN
   (`0x7c01`); because `0x7c01` is also the canonical output, the grid cannot
   distinguish sNaN pass-through from canonicalization for arbitrary payloads.
   The sign and payload of a negative-NaN result are unmeasured.
2. **Negative subnormal class representatives** (`0x8001`, `0x83ff`, ...).
   Only `0x8001`/`0x8003` appear in the finite sweep; the grid uses positive
   subnormals. The normalisation logic is the same, but the class-level
   behaviour is not captured.
3. **Subnormal false-tie window.** No captured subnormal result has
   `0.5 < f < 0.625` with even `n`; the final-quantum rule is inferred from
   six `n>0` exact subnormal ties, six zero-result ties, and eight non-tie
   inexact subnormal results.
4. **Negative-result false tie.** All 20 observed false-tie records are
   positive; sign symmetry of the 3-bit rule is inferred.
5. **Overflow boundary.** Values in `(65504, 65536)` and the exact `65520`
   tie. The contract predicts IEEE-like behaviour, but only gross overflow is
   captured.
6. **Minimum-subnormal boundary.** Values in `(2^-25, 2^-24)` and near
   `2^-24`; only the exact tie and gross underflow are captured.
7. **Non-unity `OUT_CVT_SCALE`.** All captures use `out_convert=1`. The output
   converter is outside this contract.
8. **Other widths / lane counts / linked PC chains.** Captures cover width
   0/2/3 (8/24/32 lanes) and one terminal task; no linked chain.
9. **Latency, throughput, flags.** Not captured; no claim.
10. **Internal special-sign mechanism.** The external `sign(a)` rule is
    observed; whether it is a numerator-sign bypass or a shared result-sign
    register is not.

### 5.8 Difference from IEEE 754 and from the donor

| Aspect | IEEE 754 binary16 | Donor `float16(float32(a)/float32(b))` | Device / proposed contract |
|---|---|---|---|
| finite rounding | correct RNE | correct RNE (float32 is exact enough here) | 3-guard-bit RNE; 19 A/7 operands 1 ULP low |
| `+0/+0` | qNaN | `0xfe00` (host NaN sign) | `0x7c01` (sNaN encoding) |
| `+0/-0`, `-0/+0`, `-0/-0` | qNaN | `0xfe00` | `sign(a) * inf` |
| `inf/inf` | qNaN | `0xfe00` | `sign(a) * inf` |
| divide-by-zero sign | `sa^sb` | `sa^sb` | `sa` |
| finite / infinity sign | `sa^sb` | `sa^sb` | `sa` |
| zero numerator sign | `sa^sb` | `sa^sb` | `sa` |
| qNaN propagation | qNaN, payload free | `0x7e00` | `0x7c01` (sNaN encoding) |
| sNaN propagation | quieted qNaN | `0x7e01`/`0x7e00` | `0x7c01` |
| overflow | inf (RNE threshold) | inf | inf; boundary inferred |
| underflow | signed zero / subnormal | same | same; tie-to-even observed |

The contract is deliberately **RK-match**, not IEEE-clean. A future
implementation that wants IEEE-clean behaviour must make the difference an
explicit parameter/mode and must not silently reuse the RK quirk path.

---

## 6. Verification obligations (for whoever implements this)

This analysis does not implement or modify RTL. When an implementation exists,
it must be validated against:

1. **Capture replay.** All 1452 captured lanes (24 special + 32 sweep + 8
   `fdiv8` + 1132 `ew-fp16` + 256 grid) must match bit-for-bit, including the
   20 false-tie lane records and all special quirks.
2. **Targeted finite vectors** generated from the contract, covering:
   `f == 0`, `f < 0.5`, `f == 0.5`, `0.5 < f < 0.625` with even/odd `n`,
   `f >= 0.625`, subnormal results in and out of the window, overflow just
   below/at/above 65520, underflow just below/at/above `2^-25`.
3. **Targeted special vectors** for the remaining unknowns in §5.7:
   negative NaN, negative subnormal classes, and the exact boundaries.
4. **A fresh board run** for any new probe. The existing
   `fdiv-systematic` run is complete and must not be re-used as evidence for
   modified RTL.

Do **not** use a C++ numeric model or a Verilator simulation as evidence for RK
silicon. Do not copy these capture logs forward as evidence for modified RTL.
Record the tool version, source revision, seeds and tests for any new run.

---

## 7. Evidence record

- Analysis date: 2026-11-06.
- Repository revision at analysis: `f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`.
- Analysis environment: Python 3.14.8, NumPy 2.4.6,
  `Linux-7.2.9-200.fc44.x86_64-x86_64-with-glibc2.43`.
- Grid run: `20261105T204746Z`, host `orangepi5`, kernel
  `6.18.24-current-rockchip64`, device `/dev/accel/accel0`, runner
  `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`,
  8/8 cases OK, 512 output bytes, all hashes match `run_evidence.json`.
- Capture file hashes, capture metadata and per-lane records:
  `FDIV_TABLE.json` → `provenance`, `special_rows`, `finite_rows`,
  `p1_1024`, `systematic_grid`, `class_pair_table`.
- Analysis tools (read-only over the captures) are in `tools/`; derived dumps
  are in `data/`. `tools/contract_check.py` implements the §5 pseudocode
  literally and reports **0 mismatches on 1452/1452 captured lanes**.
- No `ssh`, `scp`, board command, submit, program or flash was performed by
  this analysis. The captures were produced by earlier board runs and are
  treated as read-only evidence.
