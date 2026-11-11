# Independent EW oracle validation: `ew-fp16` and `ew-int`

**Status: PASS (host-oracle validation only).**

| Family | READY cases | Checked | Compared extent | Oracle mismatches |
|---|---:|---:|---|---:|
| `ew-fp16` | 54 | 54 | 6,792 logical FP16 lanes | **0** |
| `ew-int` | 15 | 15 | 289 asserted output bytes | **0** |

- No case/lane/bit mismatch was found between the prepared `expected.bin`
  files and this team's independent recomputation.
- Three **documentation claims are false**: the manifest/README says three
  INT lanes saturate, but all three values are inside their dtype range. The
  bytes are arithmetically correct; the text is not. This also means the
  family contains **no saturation test at all**.
- 15 coverage gaps are recorded below (special values, saturation/signed
  overflow, subnormals, padding, INT32 MUL operand, etc.).
- No device, board, RTL, Verilator, FPGA or `192.168.192.18` access was used.
  The `expected.bin` files remain host oracles, never device captures.

## Constraints honoured

- Only files under `build/rk3588-example-captures/team/ew-oracle/` were written.
- No family bundle, tracked source, test or doc was edited; nothing was
  committed; nothing was programmed or flashed.
- No `ssh`, `scp` or any command against `192.168.192.18`.
- The local RTL was not run as a substitute for the device.
- No tracked or generated source was modified, so `make generated-check` and
  `make test` were not run; neither would validate a capture bundle.
- `expected.bin` was not trusted: the command stream and input BOs were
  decoded, the arithmetic was recomputed independently, and only then compared.

## Exact commands and versions

Run from `build/rk3588-example-captures/team/ew-oracle/`:

```sh
/usr/bin/python3 oracle_check.py
/usr/bin/python3 analyze_fdiv_sweep.py > fdiv_sweep_analysis.txt
```

`/usr/bin/python3` is **Python 3.14.8** (`GCC 16.2.1 20260819`) with **NumPy
2.4.6**; platform `Linux-7.2.9-200.fc44.x86_64-x86_64-with-glibc2.43`.
The default `python3` on this host is 3.14.5 **without** NumPy, so it was not
used. NumPy is only used for a secondary donor-path cross-check; the primary
FP16 oracle is `model/half.py` and the primary INT oracle is pure Python.

Source revisions at validation time:

| Tree | HEAD |
|---|---|
| `/home/fedora/rknpu-fpga` | `f9b00d8f9a48ab4dea20cb30148890cd9f1443ee` |
| `/home/fedora/rk3588` | `273d015e08af40c81d2cd9ab84198486b03a17f1` |

The `ew-fp16` manifest records `rknpu-fpga` revision `d54d33b`; that is older
than the current HEAD, but every source file the bundle hashes is unchanged
(`model/half.py` and `model/profile.py` are unchanged between `d54d33b` and
HEAD; the manifest's own source hashes were re-verified). The repo HEAD moved
once more during this validation (`6aa8e7a` → `f9b00d8`); no validated bundle
or numerics source changed.

Tool hashes:

```
bcad7d4652c572b83a291b1f8d970d52ba198808eea03f508abd54ab9b5bda35  oracle_check.py
3d3dad59f63561962d29be52baf773822f2784124771982e326aef1c726ebd08  analyze_fdiv_sweep.py
44c5a63180375ba60efe5dab434e4a21729cd4b5a8721a2bf887bc1fbc9697aa  ORACLE.json
c083ffdfe0ccfc38fe356d23e2206e6a48f8d84e7840e3f32e87e91648242152  fdiv_sweep_analysis.txt
```

## Method

### Command-stream decoding

Both families are decoded from `regcmd.bin`, not from the manifests:

- QWORD layout `(target << 48) | (value32 << 16) | offset` is decoded directly.
  Conflicting duplicate writes would be reported; the four repeated re-arm
  writes in the 44-QWORD INT layout stream are identical, so no conflict.
- FP16: `EW_CFG` bit 2 selects the separate MUL lane; otherwise ALU bits
  `[18:16]` are `0=MAX, 2=ADD, 3=FDIV, 4=SUB`. `DATA_CUBE_WIDTH` gives
  `padded = 8*(width+1)`. NEG decodes as MUL with the B weight `-1.0`, which is
  the source's own NEG datapath.
- INT: `DATA_FORMAT[28:26]`/`[31:29]` give input/output dtype,
  `DATA_CUBE_CHANNEL[12:0]+1` gives channels, `DATA_CUBE_WIDTH+1` gives width,
  `EW_CFG` gives op (MUL/MAX/MIN/ADD/DIV/MINUS), and
  `DST_SURF_STRIDE`/`SURFACE_ADD` select the C1WC2 layout path.

### FP16 oracle

- `ADD`, `SUB`, `MUL`, `MAX`: `model/half.py::alu`, which is a bit-exact
  binary16 model and also encodes the captured RK quirks (NaN `0x7c01`,
  ADD/SUB exact zero → `+0`, SUB infinity rule, MAX signed-zero ordering).
- `NEG`: the same `MUL` path with `b = 0xbc00` (`-1.0`), exactly as the source
  substitutes `-1.0` for the EW weight.
- `FDIV`: exact rational `a/b` rounded to binary16 **nearest-even**. The rule
  is validated against the real captured data, not assumed (see below).
- Inputs are decoded from `a.bin`/`b.bin`. The logical `N` is not encoded in
  the command stream, so it comes from `manifest.logical_count` and is
  cross-checked against the `expected.bin` length (`2*N`).
- Padded lanes (`N..padded-1`) and trailing BO bytes are checked for the
  documented fill, but are **not** part of the value comparison.

### FDIV rule evidence

`build/rk3588-kernel-comparison-v1/real-rocket-fdiv8-finite-sweep/` contains a
real 32-lane finite capture. Exact-rational nearest-even reproduces **32/32**
lanes; the 11 finite lanes with a nonzero divisor in
`real-rocket-fdiv8-special/` reproduce **11/11**.

- Six finite-sweep lanes explicitly reject truncate-toward-zero, e.g.
  `max/3`: captured `0x7555`, truncation would be `0x7554`;
  `3*2^-24 / 2`: captured `0x0002`, truncation `0x0001`;
  `2.0009765625/3`: captured `0x3957`, truncation `0x3956`.
- Eight exact subnormal-range ties (six in the sweep, two in the special
  capture) confirm **ties-to-even**, e.g. `0x0003/2` → `0x0002` and
  `0x8003/2` → `0x8002`.

The FDIV README calls four quotients "RK-specific rounding", but all four are
in fact correctly rounded nearest-even (`1/3→0x3555`, `2/3→0x3955`,
`1/10→0x2e66`, `max/3→0x7555`). The capture does not support a non-IEEE
rounding claim. Caveat: only 32 finite-sweep lanes plus 8 exact-tie
observations exist; the full rounding space is not proven.

### INT oracle

The source semantics are the two examples' `integer_expected()` plus
`run_operation()` / `run_integer_layout()`:

```
MAX   : max(a, b)
MIN   : min(a, b)
ADD   : clip(a + b, dtype)
MINUS : clip(a - b, dtype)
MUL   : clip(a * b, dtype)
```

Inputs are decoded from the actual `a.bin`/`b.bin`, either contiguous native
dtype little-endian (simple cases and INT16→INT32) or C1WC2 16-byte channel
surfaces (layout cases), using the source's own packing rule. Results are
repacked with the same rule and compared against `expected.bin`; the asserted
byte set is derived independently from the logical lanes and compared against
`expected.mask.bin`.

`INT32 MUL` applies the source-captured limitation: the separate MUL operand
is **signed INT16**, i.e. `s16(b & 0xffff)`, then `clip(a * s16, INT32)`.
This is candidate behavior, not a documented ABI.

## Results

### `ew-fp16` per op

| Op | Cases | Logical lanes | Inexact results | Mismatches |
|---|---:|---:|---:|---:|
| ADD | 9 | 1,132 | 0 | 0 |
| SUB | 9 | 1,132 | 0 | 0 |
| MUL (incl. NEG) | 18 | 2,264 | 98 | 0 |
| MAX | 9 | 1,132 | n/a | 0 |
| FDIV | 9 | 1,132 | 413 | 0 |
| **Total** | **54** | **6,792** | — | **0** |

All 54 per-op register configurations decode to the source table
(`ADD 0x108202c0`, `SUB 0x108402c0`, `MUL/NEG 0x108003c4`,
`MAX 0x108002c0`, `FDIV 0x108303c0`, with the matching
`OUT_CVT_SCALE`/`RDMA_FEATURE_MODE_CFG`). All 54 bundles carry the documented
`a`/`b` patterns and padded fill, zero bytes after the padded region, and an
`expected.bin` of exactly `2*N` bytes.

Notable exact results: ADD p2 has `+0` at lanes 2/11; SUB p2 n33 cancels
exactly at lanes 28–32; NEG p2 produces `-0.0` (`0x8000`) at lanes 5/16/27;
MAX p2 n33 has an equal pair at lane 28 (`0x3800`). All values agree bit-for-bit.

### `ew-int` per case

| Case | Dtype | Op | Shape | Layout | Asserted bytes | Mismatches |
|---|---|---|---|---:|---:|---:|
| `int8_add_c8_w1` | INT8 | ADD | 1×8 | contiguous | 8/8 | 0 |
| `int8_max_c8_w1` | INT8 | MAX | 1×8 | contiguous | 8/8 | 0 |
| `int8_min_c8_w1` | INT8 | MIN | 1×8 | contiguous | 8/8 | 0 |
| `int8_mul_c8_w1` | INT8 | MUL | 1×8 | contiguous | 8/8 | 0 |
| `int16_add_c8_w1` | INT16 | ADD | 1×8 | contiguous | 16/16 | 0 |
| `int16_minus_c8_w1` | INT16 | MINUS | 1×8 | contiguous | 16/16 | 0 |
| `int16_mul_c8_w1` | INT16 | MUL | 1×8 | contiguous | 16/16 | 0 |
| `int32_add_c8_w2` | INT32 | ADD | 2×4 | contiguous | 32/32 | 0 |
| `int32_max_c8_w2` | INT32 | MAX | 2×4 | contiguous | 32/32 | 0 |
| `int32_mul_int16_operand_c8_w2` | INT32 | MUL | 2×4 | contiguous | 32/32 | 0 |
| `int8_add_c9_w1_layout` | INT8 | ADD | 1×9 | C1WC2 | 9/16 | 0 |
| `int16_add_c9_w1_layout` | INT16 | ADD | 1×9 | C1WC2 | 18/32 | 0 |
| `int16_minus_c9_w1_layout` | INT16 | MINUS | 1×9 | C1WC2 | 18/32 | 0 |
| `int32_add_c9_w1_layout` | INT32 | ADD | 1×9 | C1WC2 | 36/48 | 0 |
| `int16_add_to_int32_c8_w1` | INT16→INT32 | ADD | 1×8 | contiguous | 32/32 | 0 |

The INT32 MUL case does exercise the signed-INT16 operand: lanes 0, 1, 6, 7
carry `b = 50000, -50000, -50000, 50000`, which decode as
`-15536, +15536, +15536, -15536`; the resulting products are
`+15,536,000 / -31,072,000 / +31,072,000 / -15,536,000`, all different from a
full-INT32 multiply. This is correctly reflected in `expected.bin` and is
marked candidate behavior.

The INT16→INT32 case keeps `31000` as an INT32 value (not INT16-saturated):
`expected.bin` bytes are `18 79 00 00` at the last lane.

## Mismatches

**None.** No case, lane, byte or bit differs between the independent oracle
and the prepared `expected.bin` files. `ORACLE.json` contains an empty
top-level `mismatches` array and a zero mismatch count for every case, so
there is no (case, lane, bits) row to enumerate.

- FP16: 54/54 cases, 6,792/6,792 logical lanes match.
- INT: 15/15 cases, 289/289 asserted bytes match; every unasserted byte
  (including the 47 surface-padding bytes inside the packed output regions)
  is zero in `expected.bin` as documented.
- `expected.mask.bin` asserted sets match the independently derived lane byte
  positions, and every mask byte is `0x00` or `0xFF`.
- All 270 `ew-fp16` bundle hashes and all 90 `ew-int` bundle hashes match the
  manifests.

## Structural and documentation findings

### 1. Three "saturating" INT lanes do not saturate (false text; bytes correct)

| Case | Lane | Operands | Actual pre-saturation value | Dtype range | `expected.bin` | Manifest/README claim |
|---|---:|---|---:|---|---:|---|
| `int8_add_c8_w1` | 7 | 100 + 5 | **105** | [-128, 127] | 105 (`0x69`) | “105 -> 127” |
| `int16_add_c8_w1` | 7 | 30000 + 1000 | **31000** | [-32768, 32767] | 31000 (`0x7918`) | “31000 -> 32767” |
| `int16_minus_c8_w1` | 0 | -30000 - 1000 | **-31000** | [-32768, 32767] | -31000 (`0x86E8`) | “-31000 -> -32768” |

All three values are already inside the destination range. The `expected.bin`
bytes are correct plain integer results; only the manifest/README description
is wrong. Consequently the family contains **zero saturation lanes** and no
signed-overflow lane. A real probe would need values such as
`100+100=200→127`, `30000+30000=60000→32767`, or
`-30000-30000=-60000→-32768`; none are present.

This is reported, not changed: the family bundles were not edited.

### 2. Hashes and availability

- 270/270 `ew-fp16` manifest-pinned files and 90/90 `ew-int` files verify.
- No missing case files, no size mismatch, no conflicting duplicate register
  write in either family.
- The three `ew-int` BLOCKED cases have no `expected.bin` and were not checked;
  their blocking reasons (DIV/FLOOR/CEIL are floating-point, FP16 four-input
  sum, FP16 ReLU/PReLU) remain coherent and were not re-litigated.

### 3. Minor wording

- The `ew-fp16` README says NEG p2 has “one donor result of `-0.0`”. For
  `n=33` there are three (`lanes 5, 16, 27`); for `n=8/9` there is one. The
  bytes are correct.
- The `ew-fp16` README says the “8-lane padded tail” is excluded; `N=1024`
  has no tail (`padded = N`). The oracle extent statement is unaffected.

## Coverage gaps (likely to expose RK quirks)

### Special values

- No Inf or NaN operand/result in either family. NaN canonicalization
  (`0x7c01`), the captured SUB same-sign/opposite-sign infinity quirk, and
  `MAX` NaN behavior are untested.
- No `-0.0` operand. Only `+0` appears as an operand (p2 A and padded lanes).
  `MAX(+0,-0)`, `ADD(-0,-0)`, and sign-of-zero behavior are untested.
- No overflow to infinity and no underflow/flush case in the bundle values.

### Saturation boundaries and signed overflow

- **No saturation lane exists** (see finding 1). The three claimed overflow
  lanes are in range.
- No exact boundary values (`127/128/-128/-129`, `32767/32768/-32768/-32769`,
  `2^31-1/2^31`) and no double-overflow lane (`100+100`, `30000+30000`).
- INT32 ADD/MAX use small values; INT32 MUL products are at most
  `100,000,000` full-width or `31,072,000` under the s16 model, far below
  `2^31`. No `INT32_MIN` operand or `INT32_MIN` unary edge.
- INT8/INT16 MUL deliberately use the shared small vector
  (`MUL_A_8/MUL_B_8`), so MUL saturation and signed-product boundaries are
  not tested for those dtypes.

### Subnormals

- No FP16 subnormal input or subnormal/underflow result in any case. The
  smallest nonzero operand magnitude is `0.5` (p2) and the smallest quotient
  is `1/8 = 0.125`.
- The captured FDIV sweep does include subnormal quotients and ties, but those
  lanes are not part of the `ew-fp16` bundles; they only validate the oracle.

### Padding lanes

- FP16 physical lanes beyond `N` are never asserted:
  `N=1/7` process 8 lanes, `N=9` 16, `N=33` 40. A tail lane-shift or a
  padded-lane write bug would be invisible. Recommended check: padded lanes
  are `+0` for non-FDIV and `+0` for FDIV `0/1`.
- INT surface/BO padding is unasserted: INT8 simple 8 of 16 bytes, INT8
  layout 9 of 16, INT16 layout 18 of 32, INT32 layout 36 of 48. A surface
  stride/padding corruption is invisible by design.
- The output BO is freshly allocated by the worker; bytes beyond the padded
  region are not oracle-checked and may be allocator residue.

### INT32 MUL signed-INT16 operand

- Covered, not a gap: lanes 0/1/6/7 distinguish the s16 model from full INT32
  (values above `0x7fff` in `b`). The expected products are listed above.
- Remaining sub-gaps: no `b = 0x8000` (`32768` full INT32, `-32768` as
  `s16`), no `b = 65535` (`0x0000ffff`, full INT32 `65535` but `s16 -1`), and
  no product exactly on the INT32 saturation boundary. A device mismatch is
  information about candidate behavior, not a bundle bug.

### Other

- ADD and SUB never round in this family (all 1,132+1,132 results exactly
  representable); only 98/2,264 MUL lanes and 413/1,132 FDIV lanes are
  inexact. Add/sub rounding hardware is effectively untested.
- FDIV evidence is 32 finite sweep lanes plus 11 finite special lanes; eight
  exact subnormal ties, but no normal-range exact tie and no flush-to-zero
  policy test.
- The logical `N` is metadata only; the command stream encodes only
  `padded = 8*(width+1)`. A board worker cannot infer `N` from `regcmd.bin`.
- INT32 9-channel layout is offline-validated only in the source; the source
  never claims a device pass for that exact combination.
- Missing operations/dtypes: no INT32 MIN/MINUS, no INT8 MINUS, no
  ABS/NEG/FLOOR/CEIL; DIV/FLOOR/CEIL are correctly BLOCKED as
  floating-point.

## Caveats

1. This is **host oracle validation only**. Matching `expected.bin` does not
   validate RK3588 silicon, the Rocket/DRM driver, DMA, the FPGA, the RTL, or
   timing. It only says the prepared oracle is arithmetically consistent with
   an independent recomputation.
2. `model/half.py` encodes **captured** RK special-value policies; those
   policies remain candidate behavior until hardware differential tests. This
   family does not exercise them (no Inf/NaN/-0).
3. The FP16 `p1`/`p2` inputs are deterministic preparation-time closed forms,
   **not** the source examples' seeded `np.random.uniform` data. The
   arithmetic formula is the source donor formula; the operands are not.
4. INT saturation is the source's `integer_expected` clip; no bundled lane
   actually overflows, so the capture cannot establish the device policy.
5. INT32 MUL signed-INT16 is a source-captured limitation and candidate
   behavior, not a documented ABI.
6. The FDIV nearest-even rule is supported by 32 sweep lanes and 11 finite
   special lanes, including eight subnormal ties. Normal-range ties and the
   full quotient space are not covered.
7. The `ew-fp16` manifest records an older `rknpu-fpga` revision; the files it
   hashes are unchanged at current HEAD. The repo HEAD moved during this run;
   all final hashes are recorded above and in `ORACLE.json`.
8. No `ssh`/`scp`/`192.168.192.18`, no submit, no program/flash, no RTL or
   FPGA run was performed. There is no device evidence here.

## Recommended follow-ups (no bundle edits were made)

- Correct or annotate the three false saturation claims in `ew-int`; if
  saturation policy is a target, add **new** cases with true overflow rather
  than reinterpreting the existing bundles.
- In the board comparison, assert the FP16 padded lanes (`+0`, or `+0` for
  FDIV `0/1`) and the INT surface-padding bytes where the hardware contract is
  known. The current masks deliberately exclude them.
- Keep special-value/subnormal FP16 probes in a separate family; do not fold
  them into this finite family. Treat any INT32 MUL mismatch as candidate
  behavior until a full-width INT32 probe is captured.

## Artifacts

- `ORACLE.json` — machine-readable per-case results, mismatches, coverage,
  FDIV lane evidence, hashes and versions.
- `ORACLE.md` — this report.
- `oracle_check.py` — independent oracle/comparator.
- `analyze_fdiv_sweep.py` — FDIV rule classifier.
- `fdiv_sweep_analysis.txt` — captured sweep classification output.
