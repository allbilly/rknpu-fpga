# Captured signed-integer pooling, 2×2 / stride-2

Status: **one shared signed-integer reducer covering four exact captures,
replaying in both simulators**. Two INT8 C16 and two INT16 C8 cases, not
general integer pooling, not a PPU endpoint, and not FPGA execution.

## Cases

Four successful Rocket tasks from the 2026-11-05 PPU run, all C H2 W2 → H1 W1
with a 2×2 kernel, stride 2, no padding, `USE_CNT=0`, `INDEX_EN=0`:

| Case | dtype | LANES | METHOD | `PPU_RECIP_KERNEL_WIDTH` |
|---|---|---:|---:|---:|
| `int8_max_k2s2_valid_c16_h2w2` | int8 | 16 | 0 (max) | — |
| `int8_min_k2s2_valid_c16_h2w2` | int8 | 16 | 1 (min) | — |
| `int16_max_k2s2_valid_c8_h2w2` | int16 | 8 | 0 (max) | — |
| `int16_min_k2s2_valid_c8_h2w2` | int16 | 8 | 1 (min) | — |

Each fixture is frozen under `tests/ppu_pooling/fixtures/` with its own device
BO and register dump. Comparison tolerance is **0.0** for all four and the
captured device output equals the host oracle byte for byte.

## Semantics

Sixteen INT8 channels fill one 16-byte C1HWC2 atom; eight INT16 channels fill
one atom the same way. The 2×2/stride-2 window covers the whole 2×2 surface,
so four input atoms reduce to exactly one output atom.

Comparisons are **signed two's-complement** for both widths. This was
established from the captured data, not assumed: an unsigned INT8 compare
yields `251` where the device captured `100`, while the signed compare
reproduces all sixteen lanes.

The reducer seeds its accumulator from the first atom. A zero seed would
silently bias all-positive channels for MAX and all-negative channels for MIN.

## RTL

`rtl/ppu/rk_ppu_pool_int_k2s2.sv` is one parameterized leaf:

```systemverilog
parameter integer ELEM_W = 8;    // 8 or 16
parameter integer LANES  = 16;   // must equal 128 / ELEM_W
parameter integer METHOD = 0;    // 0 = maximum, 1 = minimum
```

Invalid elaborations are fatal rather than silently defaulted: an unsupported
`ELEM_W`, a `LANES` value that does not fill one 16-byte atom, or an `METHOD`
outside {0,1}. Four thin exact-profile wrappers instantiate it
(`rk_ppu_pool_{max,min}_k2s2_i8_c16_h2w2`,
`rk_ppu_pool_{max,min}_k2s2_i16_c8_h2w2`). No register decode, RDMA/WDMA,
AXI, padding generation or special-value policy is present.

## Evidence

`make ppu-int-k2s2-test` (Verilator) and
`make ppu-int-k2s2-four-state-test` (Icarus) replay all four fixtures and
compare every byte of the complete 4,096-byte output BO:

```
int8_max_k2s2_valid_c16_h2w2   iverilog  PASS  mismatch=0
int8_max_k2s2_valid_c16_h2w2   verilator PASS  mismatch=0
int8_min_k2s2_valid_c16_h2w2   iverilog  PASS  mismatch=0
int8_min_k2s2_valid_c16_h2w2   verilator PASS  mismatch=0
int16_max_k2s2_valid_c8_h2w2   iverilog  PASS  mismatch=0
int16_max_k2s2_valid_c8_h2w2   verilator PASS  mismatch=0
int16_min_k2s2_valid_c8_h2w2   iverilog  PASS  mismatch=0
int16_min_k2s2_valid_c8_h2w2   verilator PASS  mismatch=0
```

Receipts: `build/ppu-pool-int-k2s2/<case>/{iverilog,verilator}-20261107T16*/`
(workspace-local, pruned of build products).

`make ppu-int-k2s2-contract-test` checks the core is signed-integer only,
validates all three parameters, seeds from the first atom, and that all four
fixtures are still the exact 2×2/stride-2 captures.

## Remaining integer pooling work

Five READY pooling fixtures still have no executing leaf:

- `int8_max_k1s1_valid_c32_h1w1` — C32 INT8, 1×1, two atoms;
- `int8_avg_q16_k2s2_valid_c16_h2w2` and `int8_avg_q16_k3x3_valid_c16_h3w3`
  — Q16 reciprocal averaging;
- `int16_avg_q16_k2s2_valid_c8_h2w2` and `int16_avg_q16_k3x3_valid_c8_h3w3`.

Plus the two FP16 stragglers `fp16_max_k3s2_pad1_c8_h4w4` and
`fp16_avg_k2s1_pad1_use_cnt0/use_cnt7`.

The averaging cases are **not** a simple integer divide. Measured from the
frozen fixtures:

| Case | `sum * recip >> 17` | `sum * recip >> 16`, twice | `floor(sum/area)` |
|---|---|---|---|
| `int8_avg_q16_k2s2` | match | match | match (area divides every sum) |
| `int16_avg_q16_k2s2` | match | match | match |
| `int8_avg_q16_k3x3` | **no** (−12 vs −8 on c0) | match | match |
| `int16_avg_q16_k3x3` | **no** | match | match |

Both k3x3 captures equal `floor(sum/area)` exactly for every channel, and in
these fixtures every sum is an exact multiple of the area, so the two
formulations agree on captured data only because of that. They disagree in
general (e.g. `sum=9`, `area=9`: `>>16` twice yields 0 while `sum/area` yields 1),
so the reciprocal arithmetic still needs a wider capture before any averaging
leaf is written. The execution of this image is unrelated to that question.
