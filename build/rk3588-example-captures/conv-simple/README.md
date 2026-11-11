# conv-simple capture bundles (device-free preparation)

Status: **7 READY, 5 BLOCKED**.  This directory was prepared without opening a
DRM device, without `ssh`/`scp`, and without touching `192.168.192.18` or any
FPGA.  The later single board worker owns execution; no `out.bin` is shipped
here.  `expected.bin` is a host-side NumPy oracle, not a device capture.

## Sources and derivation

The command streams are built by the named example builders; this preparation
does not invent registers.

| Path | Used for |
|---|---|
| `/home/fedora/rk3588/examples/expt/conv_simple.py` | FP16 `_conv_params`, `pack_input`, `pack_weights`, `make_regs`, `compute_expected`, output-precision policy, Rocket terminal tail |
| `/home/fedora/rk3588/examples/conv_simple.py` | cross-reference; same generic FP16 `make_regs` |
| `/home/fedora/rk3588/examples/kernel_6_18/simple_conv.py` | INT8 `use_shape`, `pack_input`, `pack_weights`, `pack_biases`, `build_conv_regs`, `split_tasks`, `expected_output` |
| `/home/fedora/rk3588/examples/kernel_6_18/conv_legacy.py` | shape-table analogues for 5x5 and depthwise |

The FP16 module is imported directly.  The INT8 module has module-level DRM
setup (`fd = open_rocket_device()` and several `mem_allocate` calls); exactly
that setup block is removed before executing the module in memory so its pure
functions can be reused verbatim.  No source file is modified.

For each READY case the generator:

1. selects a single `NONE/setup` planner row and runs the source's generic
   command builder with zero address placeholders;
2. packs the deterministic input/weight (and INT8 bias) bytes with the source
   packers;
3. appends the source's four-word **terminal** PC tail
   (`PC_BASE_ADDRESS=0`, `PC_REGISTER_AMOUNTS=0`, `VERSION=0`, and the
   source-specific `OPERATION_ENABLE`: `0x0d` for FP16, `0x1d` for INT8);
4. appends exactly one trailing zero QWORD of **fetch padding** when the
   declared task count is odd (Rocket's PC fetch amount is in QWORD pairs);
5. emits one `value32` patch per address register, bound to the named buffer;
6. computes `expected.bin` with the source's NumPy oracle and documents the
   raw output layout below.

All READY cases are single-task, terminal PC records.  No multi-task PC chain
is used: a chain would require `PC_BASE_ADDRESS = regcmd_addr + task_offset`,
and the bundle patch schema can only bind named buffer addresses, not the
regcmd self-address.  Grouped convolution is blocked for that reason (plus the
source's per-group resubmit/BO-overwrite model).

### Parity fetch padding

Rocket's PC fetch amount is expressed in **QWORD pairs**: an odd declared
`regcmd_words` fetches one extra QWORD.  Every READY `regcmd.bin` therefore has
exactly one trailing zero QWORD that is fetched but **not executed** as a
command:

| Cases | Declared task words | `regcmd.bin` words | `regcmd.bin` bytes |
|---|---:|---:|---:|
| 5 FP16 cases | 51 | 52 | 416 |
| 2 INT8 cases | 69 | 70 | 560 |

The job descriptor keeps the declared 51/69 count.  The manifest records the
declared, file, fetch, padding and byte counts separately
(`regcmd_words`, `regcmd_file_words`, `regcmd_fetch_words`,
`regcmd_padding_words`, `regcmd_size_bytes`).  The shared runner validator
checks the rounded-up fetch extent, so the file must be at least 52/70 QWORDs.

Task-descriptor masks are not part of `job.json`; the worker should use the
source's standard values (`op_idx=1`, `enable_mask=0xD`, `int_mask=0x300`,
`int_clear=0x1FFFF`).  Output channel counts are chosen as OC16/OC32 (and
depthwise OC64) so `align_out_c == out_c`; an OC8 case would add eight channel
lanes of allocator padding that the device may fill arbitrarily, so it is not
used for the full-buffer oracle here.

### Case list

| Case | Status | Shape / path | Output |
|---|---|---|---|
| `conv_simple_fp16_1x1_c4_h8_w8_oc16` | READY | FP16 1x1 valid, C4 H8 W8 -> OC16 | FP32, 4096 B |
| `conv_simple_fp16_3x3_c4_h8_w8_oc16` | READY | FP16 3x3 valid, C4 H8 W8 -> OC16 | FP16, 1152 B |
| `conv_simple_fp16_5x5_c4_h8_w8_oc16` | READY | FP16 5x5 valid, C4 H8 W8 -> OC16 | FP16, 512 B |
| `conv_simple_fp16_1x1_c32_h8_w8_oc32` | READY | FP16 1x1 valid, C32 H8 W8 -> OC32 | FP32, 8192 B |
| `conv_simple_fp16_3x3_c16_h8_w8_oc32` | READY | FP16 3x3 valid, C16 H8 W8 -> OC32 | FP16, 2304 B |
| `simple_conv_int8_5x5_c8_h8_w8_oc32` | READY | INT8 5x5 valid, C8 H8 W8 -> OC32 | uint8, 512 B oracle prefix (1024 B BO) |
| `simple_conv_int8_depthwise_3x3_c64_h8_w8_oc64_g64` | READY | INT8 depthwise 3x3 valid, C64 -> OC64, g64 | uint8, 2304 B oracle prefix (4608 B BO) |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2` | BLOCKED | stride 2 | see `BLOCKED.md` |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_samepad` | BLOCKED | SAME padding | see `BLOCKED.md` |
| `conv_simple_fp16_3x3_c8_h8_w8_oc16_unpadded_pack` | BLOCKED | C8 FP16 packing/align mismatch | see `BLOCKED.md` |
| `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2` | BLOCKED | grouped C8/OC8, g2 | see `BLOCKED.md` |
| `simple_conv_int8_addition_c8_h8_w8_oc32` | BLOCKED | residual/addition input | see `BLOCKED.md` |

The 1x1 cases exercise the source's non-spatial policy (`out_fp16 = False`, so
FP32 output; `expt/conv_simple.py:695`).  The 3x3/5x5 cases exercise FP16 output.
The C4 cases use the source's `<=4`-channel NHWC path (the same packing class as
its validated RGB probe); C32/1x1 and C16/3x3 exercise channel slicing (`c1=4`
and `c1=2`).  The INT8 depthwise case exercises `CORE DW_EN` and the depthwise
weight layout.  The INT8 5x5 case exercises the direct 5x5 spatial path.

The example-style C8 FP16 shape is **BLOCKED**, not silently substituted: for
`in_c=8` the source's `_conv_align_c` returns 16 while `_conv_input_pack_c2`
returns 8, so `pack_input()` writes 8 channels per pixel against a
`CNA_DATA_SIZE1` field that declares a 16-channel aligned layout.  The source
has no supported C8 entry and no packing path that fills the gap.  C4 uses
`align_c=8 == pack 8` (NHWC) and C16/C32 have packed count equal to the aligned
count, so those are the READY small/large cases.

`conv_simple_fp16_5x5_c4_h8_w8_oc16` is **not** in the example's `LIST_SHAPES`;
it is derived from the generic `kh/kw` builder with a planner `NONE/setup` row.
It is READY as a register-stream case but there is no source-device evidence
for this exact 5x5 shape yet.

## Raw data and oracle layouts

All files are raw little-endian bytes.  `job.json` declares each BO size and
the patches.  The worker allocates the BO, copies the input file at offset 0,
patches the address fields, submits, and writes the output BO to `out.bin`.

### FP16 cases

* Input: `pack_input()` output.  The C4 cases use the source's `use_nhwc=True`
  layout `[H][width_stride][in_c]` (the same as the validated RGB probe); the
  C16/C32 cases use `[c1][H][width_stride][c2]` with `c2=8` FP16 atoms.  For
  these shapes `width_stride == in_w == 8`.
* Weight: `pack_weights()` output, chunks of 16 output channels:
  `[oc_chunk][kh][kw][oc_lane][aligned_in_c]`, containing `(w)` in FP16.
* Output: `unpack_output()` order, `[c1_out][out_width_stride][c2_out]` where
  `c2_out = 8` for FP16 and `4` for FP32, `c1_out = align_out_c / c2_out`.
  These shapes have `align_out_c == out_c` and
  `out_width_stride == out_h * out_w`, so every raw element is meaningful and
  `expected.bin` covers the whole output BO.
* Logical oracle: `out[oc,y,x] = sum_{ic,ky,kx}
  input[ic,y+ky,x+kx] * weight[oc,ic,ky,kx]`, valid cross-correlation,
  float64 accumulation in `compute_expected`, then cast to the device output
  dtype.  Tolerances: `atol=0.12` for FP16, `atol=0.1` for FP32 (`rtol=1e-5`),
  copied from the source's `run_shape` comparison.

### INT8 cases

* Input: `pack_input()` layout `[channel_group][x][y][16]`, bytes
  `(u - 0x80) & 0xff`; `calc_input_size()` over-allocates 2x and the suffix is
  zero.
* Weight: `pack_weights()` layout, bytes `(w - 0x80) & 0xff`, with the
  source's oc/ic group order; the allocated file may be larger than the
  meaningful prefix read by `CNA_WEIGHT_SIZE0`.
* Bias: `pack_biases()` int32 little-endian; stored value is
  `bias + 128 * sum(raw weight bytes)` for these zero points.
* Logical oracle: the source's `expected_output`, i.e. integer/raw-uint8
  accumulation, `clip(round(acc * (1/255)), 0, 255)` plus output zero point.
  The raw output layout is `read_output()` order
  `[channel_group][x][y][16]`, byte `(logical - 0x80) & 0xff`.
* `calc_raw_output_size()` over-allocates output channels by 2x
  (`oc1 = ceil(oc/16)*2`).  `expected.bin` is the meaningful **prefix**:
  `out_c * out_h * out_w` bytes.  Compare the first `len(expected.bin)` bytes
  of `out.bin`; the remaining bytes are the source's allocation padding and
  are not part of the oracle.  This is why the two INT8 out BOs are 2x their
  expected files.
* The INT8 data bytes use lower ranges than the example's `randint(0, 256)`
  (5x5: `[0,32)`, depthwise: `[0,96)`) so the donor oracle does not clip at
  255.  The source oracle formula and register stream are unchanged; this is a
  data-preparation choice recorded in `manifest.json`.

## Blocked cases

Each blocked case has a `cases/<name>/BLOCKED.md` with the full reason and the
manifest carries the same text.  Summary:

* **stride 2**: both builders hardcode `CNA_CONV_CON3 = (1<<3)|1` (stride 1).
* **SAME padding**: the FP16 builder never writes the pad registers and both
  builders compute valid-only output geometry; the INT8 pad registers are a
  zero-point fill, not a SAME-padding recipe.
* **C8 FP16**: the source computes `align_c=16` but packs only 8 channels per
  pixel for `5 <= in_c <= 8`, so `CNA_DATA_SIZE1` and the packed input
  disagree.  C4 (NHWC, align 8 == pack 8) and C16/C32 are used instead.
* **grouped**: only the INT8 source has a grouped path, and it slices channels
  into independent `run_conv2d_shape` calls with shared-BO overwrites and
  separate `npu_submit`s.  A single bundle would need per-group BOs plus a
  PC chain whose base address is the regcmd self-address, which the patch
  schema cannot express.
* **addition input / residual**: the INT8 shape accepts the knobs, but they
  only change `CNA_PAD_CON1`/CVT fields; no addition-tensor BO or address is
  ever constructed.  A residual case needs a vendor-only second feature
  stream, not available from these sources.

## Reproduce and validate

Generation needs NumPy; on this host the default `python3` is Homebrew 3.14
without NumPy, so use `/usr/bin/python3`:

```sh
cd build/rk3588-example-captures/conv-simple
/usr/bin/python3 generate.py
python3 validate.py          # stdlib-only schema/bounds validator
/usr/bin/python3 check_numeric.py

# shared board-runner preflight, one READY case at a time
cd /home/fedora/rknpu-fpga
for c in $(python3 - <<'PY'
import json
m=json.load(open('build/rk3588-example-captures/conv-simple/manifest.json'))
print(' '.join(x['case'] for x in m['cases'] if x['status']=='READY'))
PY
); do
  PYTHONDONTWRITEBYTECODE=1 python3 \
    build/rk3588-example-captures/runner/validate_bundle.py \
    build/rk3588-example-captures/conv-simple/cases/$c || exit 1
done
```

Seeds are recorded in `manifest.json` (`fp16=42`, matching
`expt/conv_simple.py::run_shape`; `int8=1234`, a preparation choice), together
with the source SHA-256 values and the Python/NumPy versions.

Actual local results at preparation time (Python 3.14.8, NumPy 2.4.6):

```
validation PASS: 7 READY, 5 BLOCKED
numeric check PASS: 7 READY cases
shared validator OK: 7/7 READY cases (52 file words FP16, 70 file words INT8)
```

`validate.py` checks JSON shape, buffer sizes/file existence, the declared and
QWORD-pair fetch extents of `regcmd.bin`, zero trailing fetch padding, task
ranges, patch indices/buffers/values, every address-register occurrence
covered exactly once, terminal PC tails, expected-size/layout consistency, and
manifest hashes; it writes `validation.json`.  `check_numeric.py`
independently reconstructs logical tensors from the packed files, runs a naive
convolution, repacks the raw output and compares it byte-for-byte with
`expected.bin`; it writes `numeric_check.json`.  Both are host-side checks;
neither validates RK3588 hardware or the actual capture.

## Caveats

* These are prepared command streams, not captures.  The worker must patch the
  real BO DMA addresses; do not submit a bundle with placeholder zero addresses.
* The FP16 generic `make_regs` does not write `CNA_PAD_CON0`/`CNA_PAD_CON1`.
  All FP16 cases are valid-only convolutions, so the kernel window never
  crosses the input boundary and those fields are don't-care for this
  geometry; the source's `run_shape` uses the same builder.  This is not a
  SAME-padding recipe (see the blocked SAME case).
* The FP16 1x1 cases follow `run_shape`'s shape policy (`is_spatial == False`,
  `out_c < 128`, `out_width_stride <= 992`), which selects FP32 output.  The
  separate `run_shape_rocket` probe helper hardcodes `out_fp16=True`; the
  source does not separately evidence mainline Rocket execution of this
  FP32-output stream.  The register builder supports the parameter, and the
  vendor-path `run_shape` uses it, but this remains a caveat.
* Most exact shapes here are generic builder derivations rather than entries
  in the examples' known-supported tables.  The source's explicit small FP16
  evidence is the C4/OC4 3x3 table entry and the C3/H5/W5/OC16 3x3 Rocket
  probe; the C4/OC16, C16/C32, and INT8 C8/OC32 choices extend those code
  paths.  Treat a device failure as informative, not as a regression of this
  preparation.
* The INT8 cases exist because the INT8 source is the only one with a
  depthwise path (and an explicit 5x5 table analogue).  They are quantized
  convolutions, not FP16 EW-slice evidence.
* `expected.bin` for FP16 is the oracle rounded to the device output dtype; for
  INT8 it is the source's donor CPU result.  Neither establishes RK3588
  numerical behavior.  Only a real capture can do that.
* No board, FPGA, `ssh`, `scp`, flash or programming operation was performed
  during preparation.
