# Q16 integer pooling average — semantics pinned from the captures

Status: **four captured profiles execute; the tie rule is still candidate
behaviour.** This document records exactly what the frozen fixtures prove and
what they do not.

## Profiles

| Case | dtype | area | lanes | output |
|---|---|---:|---:|---|
| `int8_avg_q16_k2s2_valid_c16_h2w2` | int8 | 4 | 16 | 16 bytes |
| `int8_avg_q16_k3x3_valid_c16_h3w3` | int8 | 9 | 16 | 16 bytes |
| `int16_avg_q16_k2s2_valid_c8_h2w2` | int16 | 4 | 8 | 16 bytes |
| `int16_avg_q16_k3x3_valid_c8_h3w3` | int16 | 9 | 8 | 16 bytes |

The captures write 16 bytes and leave the rest of the 4096-byte BO untouched;
the replay compares the complete BO.

## What the data rules out

Every captured lane value equals `sum(window) / area` exactly. Testing the
alternatives against all four captures:

| Formulation | k2s2 | k3x3 | Verdict |
|---|---|---|---|
| `sum * recip >> 17` | matches | **fails** (`-12` vs `-8` on channel 0) | rejected |
| two-pass `sum * recip >> 16` | matches | matches | accepted, but see below |
| `sum / area` | matches | matches | accepted |

The `PPU_RECIP_KERNEL_WIDTH`/`HEIGHT` registers hold `0x8000` for area 4 and
`0x5555` for area 9. With `0x5555`, one reciprocal multiply gives `-23.9996`
for a sum of `-72`; the device captured `-8`. So the device is **not** doing a
single Q16 multiply-shift, which is what the naive reading of the register
name suggests.

Two candidate formulations survive all four captures:

1. **Divide by the area** — `sum / area`, with area known from the kernel.
2. **Two-pass rounding reciprocal** — round-to-nearest after
   `sum * recip / 2^16` and again after `* recip / 2^16`.

They agree on all four captures because every lane sum happens to be an exact
multiple of the area. They disagree on synthetic data: for area 4,
`sum = 1`, two-pass gives `1` while `sum/area` gives `0`.

I implemented **formulation 1** (`rtl/ppu/rk_ppu_pool_int_avg.sv`) because:

* it needs no invented rounding rule, and truncation toward zero is Verilog's
  own signed `/` semantics;
* the divisor is a compile-time constant, so synthesis maps it to shifts and
  adds;
* the captures cannot refute it.

It is recorded as candidate behaviour, not established hardware semantics. A
capture whose window sum is **not** a multiple of the area would decide between
formulations 1 and 2, and no such capture exists in the corpus.

## Two signed-arithmetic bugs found while implementing

Both were real and neither would have been caught by a sign-agnostic test:

1. **Unsigned divisor.** `total / SUM_W'(AREA)` made Verilog's result unsigned
   (`SUM_W'(AREA)` is unsigned), so a sum of `-144` divided by 9 produced
   `0xB7` (= 183) instead of `-16`. Fixed by a signed `AREA_SIGNED` constant
   and documented inline.
2. **Double-counted atom.** The original bench held `in_valid` across the
   whole frame while also advancing `in_atom`; the leaf accepted the *first*
   atom `KH*KW` times. The new bench drives each atom from the inactive edge
   and checks `in_ready` before each beat.

## k1s1 C32 identity

`int8_max_k1s1_valid_c32_h1w1` is a 1×1 window: the captured device output
equals the first 32 input bytes and both BO tails are zero. A 1×1 pooling
window cannot change a value, so the leaf (`rk_ppu_pool_max_k1s1_i8_c32`) is a
two-atom pass-through. It is exact for this capture and would be wrong for any
larger kernel, which is stated in the file header.

## Evidence

`tools/ppu/run_pool_int_avg.py` replays all five in both simulators, comparing
the complete 4096-byte BO and adding two negative controls per run (one mutated
expected byte, one mutated input byte). Receipts under
`build/ppu-pool-int-avg/<sim>-<stamp>-<id>/report.json`.
