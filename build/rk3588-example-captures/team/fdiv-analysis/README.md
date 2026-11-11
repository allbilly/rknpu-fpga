# Real RK3588 FDIV analysis (team `fdiv-analysis`)

**Status: analysis only. No board access, no RTL change, no bundle edit.**

This directory analyses the real RK3588 Rocket DPU EW FDIV captures under
`build/` and proposes a bit-exact behavioural contract for a future FP16
divider. The captures are device evidence; the contract is candidate behaviour,
not an RK3588 specification.

| Artifact | Purpose |
|---|---|
| [`FDIV_TABLE.json`](FDIV_TABLE.json) | Machine-readable decision table: 24 special rows, 40 finite rows (8 `fdiv8` + 32 sweep), 256-pair class table, full 256-row grid, provenance, hashes |
| [`FDIV_CONTRACT.md`](FDIV_CONTRACT.md) | Proposed RTL contract, full 24/32 tables, the 16x16 observed-result matrix, IEEE/donor comparison, unknowns |
| `tools/` | Read-only decoders, exact-rational model, hypothesis tests, table builder |
| `data/` | Derived text/JSON dumps and Markdown fragments |

---

## 1. Headline results

- **1452 real FDIV lanes** are analysed: 24 special + 32 finite sweep + 8
  `fdiv8` + 1132 `ew-fp16` + 256 class grid.
- **1278 finite-nonzero lanes** exercise quotient generation and rounding.
  The 3-guard-bit contract matches **1278/1278 (0 mismatches)**.
- Exact IEEE round-to-nearest-even matches **1258/1278** and is **1 ULP low on
  20 lane records** (19 unique operand pairs, all in the A/7 subsequence of
  `fdiv_p1_n1024`). This is not global truncation: truncate-toward-zero fails
  **198/1278**.
- The 256-pair class grid is now a real device capture: **8/8 cases
  `submit_ret=0`, 512 output bytes**, every lane read back. It settles all
  special-value cells and **corrects the pre-grid special-sign rule on
  40/256 cells**.
- **Special-value results use `sign(a)`**, not `sign(a)^sign(b)`:
  divide-by-zero, infinity numerator, infinity divisor, zero numerator and
  zero/zero. **Finite results use `sign(a)^sign(b)`**, including finite
  overflow and finite underflow.
- `+0/+0 -> 0x7c01` is the only zero/zero NaN. `+0/-0 -> 0x7c00` (positive
  infinity), `-0/+0 -> 0xfc00`, `-0/-0 -> 0xfc00`.
- `inf/inf` never raises invalid: `+inf/+inf` and `+inf/-inf -> +inf`;
  `-inf/+inf` and `-inf/-inf -> -inf`.
- qNaN and sNaN both return `0x7c01`, which has the quiet bit **clear**
  (it is the sNaN encoding). The sNaN probe is inconclusive for arbitrary
  payload pass-through because `0x7c01` is also the canonical output; see
  `FDIV_CONTRACT.md` §5.7 item 1.
- The A/7 finite-rounding exception remains separate from the class grid; the
  100 finite-finite grid pairs all match exact RNE and the 3-guard-bit model,
  and the grid's only false-tie-window lane overflows, so it cannot
  distinguish the two models.

---

## 2. What the class grid settled

The grid is `fdiv-systematic` run `20261105T204746Z`:
`build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z/`.
It is the complete 16x16 Cartesian product of the prepared operand classes,
packed as 8 cases of 32 lanes, row-major (A outer, B inner).

| Before the grid | After the grid |
|---|---|
| 32/256 class pairs directly observed in older captures | **256/256 observed** |
| 224/256 unknown, with a proposed contract | **0 unknown class cells** |
| pre-grid contract wrong on 40/256 cells (special sign) | **post-grid contract 0/256 mismatches** |
| `+0/-0`, `-0/-0`, `inf/-inf` unknown | observed |
| sNaN handling unknown | observed as `0x7c01`; payload pass-through not distinguished (input is also `0x7c01`) |
| NaN precedence over zero/inf unknown | observed: NaN wins in all 60 NaN cells |
| special sign rule guessed as `sa^sb` | observed as `sign(a)` |

The grid does **not** add finite-rounding separation: its 100 finite-finite
pairs all match both exact RNE and the 3-guard-bit model, and its only
false-tie-window lane is an overflow lane. The 1,024-lane `fdiv_p1_n1024`
capture therefore remains the finite-rounding exception evidence.

### 2.1 Class-pair coverage matrix (all 256 pairs)

`+` = observed before the grid (older captures) and confirmed by the grid;
`O` = newly observed by the grid; `.` = unknown (none remain).

| A \ B | `zero_p` | `zero_n` | `inf_p` | `inf_n` | `qnan` | `snan` | `sub_min` | `sub_max` | `norm_min` | `fin_max` | `one_p` | `one_n` | `half_p` | `half_n` | `two_p` | `two_n` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `zero_p` | + | O | + | O | O | O | O | O | O | O | O | O | O | O | O | O |
| `zero_n` | + | O | O | O | O | O | O | O | O | O | O | O | O | O | O | O |
| `inf_p` | + | O | + | O | O | O | O | O | O | O | + | O | O | O | O | O |
| `inf_n` | O | O | + | O | O | O | O | O | O | O | O | O | O | O | O | O |
| `qnan` | O | O | O | O | O | O | O | O | O | O | + | O | O | O | O | O |
| `snan` | O | O | O | O | O | O | O | O | O | O | O | O | O | O | O | O |
| `sub_min` | O | O | O | O | O | O | + | O | O | + | O | O | O | O | + | O |
| `sub_max` | O | O | O | O | O | O | O | O | O | O | O | O | O | O | O | O |
| `norm_min` | O | O | O | O | O | O | O | O | O | O | O | O | O | O | + | O |
| `fin_max` | O | O | O | O | O | O | O | O | + | + | + | O | O | O | + | O |
| `one_p` | + | O | + | O | + | O | + | O | O | O | + | O | + | O | + | O |
| `one_n` | + | O | + | O | O | O | O | O | O | O | O | O | + | O | + | O |
| `half_p` | O | O | O | O | O | O | O | O | O | O | O | O | + | O | + | O |
| `half_n` | O | O | O | O | O | O | O | O | O | O | + | O | O | O | O | O |
| `two_p` | O | O | O | O | O | O | O | O | O | O | O | O | O | O | + | O |
| `two_n` | O | O | O | O | O | O | O | O | O | O | + | O | O | O | O | O |

Counts: **32** pre-grid observed (`+`), **224** new grid observations (`O`),
**0** unknown (`.`), **256/256** total observed. The raw device output for
every cell is in `FDIV_CONTRACT.md` §4 and in `FDIV_TABLE.json` →
`systematic_grid.rows`.

### 2.2 Zero/infinity matrix (real device)

| A \ B | `+0` | `-0` | `+inf` | `-inf` |
|---|---|---|---|---|
| `+0` | `0x7c01` | `0x7c00` | `0x0000` | `0x0000` |
| `-0` | `0xfc00` | `0xfc00` | `0x8000` | `0x8000` |
| `+inf` | `0x7c00` | `0x7c00` | `0x7c00` | `0x7c00` |
| `-inf` | `0xfc00` | `0xfc00` | `0xfc00` | `0xfc00` |

This matrix rules out `sign(a)^sign(b)` for the special paths. For example,
`+1/-0 -> 0x7c00` (positive infinity, not `-inf`) and
`+1/-inf -> 0x0000` (positive zero, not `-0`).

---

## 3. Finite rounding: the A/7 exception in context

`fdiv_p1_n1024` is `A = 1..1024`, `B = 8,7,6,5,4,3,2,1` cyclic. Only the
128 lanes with `i mod 8 == 1` divide by 7.0. Of those, 109 match exact RNE and
**19 are one ULP low**. The trigger is:

```text
0.5 < frac_in_ulp < 0.625   AND   truncated 11-bit significand n is even
```

The first three fraction bits are `100`; the hardware truncates to three
guard bits, turning the value into an exact half, and ties-to-even rounds the
even `n` down instead of up. This is a **false tie from a missing sticky bit**,
not a global truncation policy:

| Model | Mismatches / 1278 |
|---|---:|
| exact RNE | 20 lane records (19 unique) |
| truncate toward zero, saturating | 198 |
| **3 guard bits, then ties-to-even** | **0** |
| 2 guard bits | 90 |
| 4 guard bits | 20 |

The 100 finite-finite grid pairs all match exact RNE. The grid's only
false-tie-window lane is `fin_max/sub_max`: `n = 1024`, `f ≈ 0.50049`, but
the quotient overflows, so exact RNE and the 3-bit rule both return `+inf`.
That is why the grid neither contradicts nor replaces the A/7 evidence.

---

## 4. Proposed contract (short form)

Full detail and pseudocode: [`FDIV_CONTRACT.md`](FDIV_CONTRACT.md) §5.

```text
1. any NaN operand                -> 0x7c01
2. a == 0x0000 and b == 0x0000     -> 0x7c01
3. b magnitude == 0               -> {sign(a), inf}
4. a magnitude == 0               -> {sign(a), zero}
5. a magnitude == inf             -> {sign(a), inf}     (inf/inf lands here)
6. b magnitude == inf             -> {sign(a), zero}
7. finite / finite                -> 3-guard-bit RNE, sign = sign(a)^sign(b)
```

Finite rounding:

```text
u = 2^max(floor(log2(Q))-10, -24)
n = floor(Q/u); m = floor(8*frac(Q/u))
round up iff m > 4 or (m == 4 and n odd)
```

This is **not** IEEE-clean. The deliberate RK quirks are the special `sign(a)`
rule, the zero/zero/infinity matrix, and the `0x7c01` NaN encoding. See
`FDIV_CONTRACT.md` §5.8 for the full IEEE/donor difference table.

---

## 5. Reproduction

All analysis tools are read-only over the captures and write only under this
directory. Run from the repository root:

```sh
cd build/rk3588-example-captures/team/fdiv-analysis

/usr/bin/python3 tools/decode.py            # old-capture lane decode
/usr/bin/python3 tools/models.py           # old-capture model scan
/usr/bin/python3 tools/models2.py          # subnormal quantum + donor
/usr/bin/python3 tools/window.py           # A/7 and false-tie window
/usr/bin/python3 tools/hypotheses.py       # A/7 detail
/usr/bin/python3 tools/systematic.py       # 256-grid audit and special rules
/usr/bin/python3 tools/contract_check.py   # proposed contract vs all 1452 lanes
/usr/bin/python3 tools/build_tables.py     # regenerate FDIV_TABLE.json
/usr/bin/python3 tools/make_md.py          # regenerate Markdown fragments
```

`tools/build_tables.py` is the authoritative generator for `FDIV_TABLE.json`.
It cross-checks the grid `output.bin` files against `class_results.json`,
`class_results.tsv` and `run_evidence.json` before using them. It does not
access the board or the network.

Environment: `/usr/bin/python3` is Python 3.14.8 with NumPy 2.4.6 on
`Linux-7.2.9-200.fc44.x86_64-x86_64-with-glibc2.43`. Plain `python3` on this
host is 3.14.5 without NumPy, so the explicit `/usr/bin/python3` matters.

### Provenance

| Capture | Path | Lanes | Run identity |
|---|---|---:|---|
| `fdiv8` | `build/rk3588-kernel-comparison-v1/real-rocket-fdiv8/` | 8 | `submit_ret=0` |
| `special` | `.../real-rocket-fdiv8-special/` | 24 | `submit_ret=0` |
| `finite-sweep` | `.../real-rocket-fdiv8-finite-sweep/` | 32 | `submit_ret=0` |
| `ew-fp16` FDIV | `build/rk3588-example-captures/results/ew-fp16-20261105T201400Z/` | 1132 | board `orangepi5`, kernel `6.18.24-current-rockchip64` |
| class grid | `build/rk3588-example-captures/results/fdiv-systematic-20261105T204746Z/` | 256 | run `20261105T204746Z`, 8/8 OK, 512 bytes |

Source revision at analysis: `f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`.
The grid run records manifest source revision
`d54d33bc8f910059b6237d54d77e173737282869` for `rknpu-fpga` and
`273d015e08af40c81d2cd9ab84198486b03a17f1` for `rk3588`; the files it hashes
are unchanged at the current HEAD. Runner hash:
`a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`.
Per-file hashes are in `FDIV_TABLE.json` → `provenance`.

### Constraints honoured

- No `ssh`, `scp` or any command against `192.168.192.18` was run by this
  analysis.
- No RTL, test, doc, family bundle or family manifest was modified.
- Nothing was committed, programmed or flashed.
- Only `build/rk3588-example-captures/team/fdiv-analysis/` was written.
- The grid `output.bin` files, `class_results.json`, `class_results.tsv` and
  `run_evidence.json` were read as immutable evidence.

---

## 6. What remains unknown

The 16x16 class cells are all observed, but these are still open. Do not guess
them; capture them.

1. Negative NaN operands (`0xfe00`, `0xfc01`, ...) and sNaN payloads other
   than `0x7c01`; the grid only has positive qNaN/sNaN, and `0x7c01` is also
   the canonical output.
2. Negative subnormal class representatives (`0x8001`, `0x83ff`, ...); only
   `0x8001`/`0x8003` appear in the finite sweep.
3. A subnormal-result false tie in `0.5 < f < 0.625` with even `n`.
4. A negative-result false tie in that window.
5. The exact overflow boundary (values in `(65504, 65536)`, including the
   `65520` tie).
6. The exact minimum-subnormal boundary (`2^-25` to `2^-24`).
7. Non-unity `OUT_CVT_SCALE` / other output-converter settings.
8. Other widths, lane counts and linked PC chains.
9. Latency, throughput and IEEE exception flags (none are captured).
10. The internal special-sign mechanism; only the external `sign(a)` behaviour
    is observed.

The independent oracle finding (`team/ew-oracle/ORACLE.md`) is consistent with
this report: its 32 sweep lanes and 11 finite special lanes match exact RNE,
and its subnormal ties match, because those lanes are outside the false-tie
window. The 19 A/7 operands are the only observed finite exceptions.

---

## 7. Change log

- **2026-11-06:** incorporated `fdiv-systematic` run `20261105T204746Z`
  (8 cases, 256 lanes, 512 bytes). All 256 class pairs observed; special-sign
  rule corrected to `sign(a)`; zero/zero and inf/inf matrices settled; NaN and
  sNaN precedence confirmed; pre-grid contract corrected on 40/256 cells.
  The 1,024-lane A/7 finite-rounding analysis is unchanged.
