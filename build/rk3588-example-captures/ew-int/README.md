# ew-int: device-free RK3588 integer elementwise captures

This directory contains **prepared, not executed** capture bundles for the
integer elementwise paths of the two RK3588 examples:

- `/home/fedora/rk3588/examples/kernel_6_18/elementwise_int.py`
- `/home/fedora/rk3588/examples/expt/elementwise_int.py`

Nothing here was run against the Orange Pi. No `ssh`, `scp`, `/dev/accel*`
access, NPU submit, or FPGA program/flash was performed. The board-side worker
owns that step later, one case at a time under the queue lock.

**Status: 15 READY, 3 BLOCKED.**
Manifest: `manifest.json` (counts, source line references, oracles, hashes).
Validation evidence: `validation/local_validation.{txt,json}` and
`validation/source_crosscheck.{txt,json}`.

## Layout

```
ew-int/
  manifest.json                 # every case, status, oracle, SHA-256 hashes
  README.md                     # this file
  cases/<case>/
    job.json                    # CAPTURE_FORMAT.md schema
    regcmd.bin                  # little-endian 64-bit command QWORDs
    a.bin, b.bin                # 4096-byte input BO images (zero padded)
    expected.bin                # host oracle, 4096 bytes, NEVER device output
    expected.mask.bin           # 0xFF = asserted byte, 0x00 = unasserted padding
  tools/
    gen_bundles.py              # pure-Python generator (deterministic)
    validate.py                 # local schema/buffer/patch/hash validator
    crosscheck_source.py        # NumPy cross-check against the real examples
    decode_regcmd.py            # human-readable QWORD table for one case
  validation/                   # generated evidence, not device evidence
```

Every bundle file is raw bytes; the board-side worker needs no NumPy.

## Source inspection

Both examples are single-file DRM/Rocket probes. Device access is confined to
`__main__`; the register builders and oracles are pure functions.

### Hardcoded modes

- Target/stream IDs are shifted into QWORD bits 48-63:
  `TARGET_DPU=0x1001`, `TARGET_RDMA=0x2001`, `TARGET_PC=0x0081`,
  `TARGET_PC_REG=0x0101`, `TARGET_VERSION=0x0041`.
- `emit(target, offset, value)` packs
  `(target << 48) | ((value & 0xffffffff) << 16) | offset`. The `value32`
  patch in `CAPTURE_FORMAT.md` replaces exactly bits [47:16], so it maps
  one-to-one onto an RK DMA address write.
- Precision codes: INT8=0, INT16=1, FP16=2, INT32=4.
- ERDMA element sizes: INT8=1, INT16=2, INT32=3.
- EW ALU codes: MAX=0, MIN=1, ADD=2, DIV=3, MINUS=4, ABS=5, NEG=6,
  FLOOR=7, CEIL=8. MUL is a separate `EW_OP_TYPE_MUL` lane, not an ALU code.
- MAX and MIN additionally set `EW_EQUAL_EN` (bit 21), matching the RKNN
  min/max captures.
- INT32 sets the EW converter bypass (bit 8) because the integer converter
  would otherwise rescale. INT8/INT16 keep the converter enabled with scale 1.
- Simple-path shapes: INT8/INT16 use `channels=8`, `width=elements/8`;
  INT32 uses `channels=4`, `width=elements/4`. The script's INT32 sample is
  8 elements, i.e. `width=2, channels=4`.
- The simple path writes the logical tensor contiguously with
  `ndarray.tobytes()` and reads back `count=len(a)` elements. It is **not**
  the 16-byte-surface packing.
- The layout path (`expt --probe-layout`) packs each logical `width x channels`
  tensor into contiguous 16-byte channel surfaces: 16 INT8 / 8 INT16 / 4 INT32
  lanes per surface, with a tail surface when `channels` is not a multiple of
  the atom. `DST_SURF_STRIDE`, `SURFACE_ADD` and `RDMA_EW_SURF_STRIDE` are all
  `width << 4` (16 for the width=1 cases here).
- The INT16-to-INT32 writeback path (`run_int16_add_to_int32`) is a distinct
  16-to-32 regroup: `DST_SURF_STRIDE=16`, `SURFACE_ADD=32`,
  `BS_OW_CFG=0x126` (SIZE_E_0/1/2), INT32 output precision.

### Argument parsing

`kernel_6_18/elementwise_int.py` (lines 714-731):

```
python elementwise_int.py [DTYPE] [OPERATION]
DTYPE     = ALL | INT8 | INT16 | INT32
OPERATION = ALL | MAX | MIN | ADD | DIV | MINUS | ABS | NEG | FLOOR | CEIL | MUL
```

`ALL ALL` additionally runs `run_fp16_compare_to_int16` and
`run_int16_add_to_int32` (lines 739-745).

`expt/elementwise_int.py` accepts the same positional arguments and adds
main-guarded probe flags (lines 2245-2356), including:

```
--validate-probes
--validate-layout-probes
--probe-layout [--probe-layout-edge] DTYPE OP WIDTH CHANNELS
--probe-external-mul-layout STAGE WIDTH CHANNELS
--probe-external-alu-mul STAGE
--probe-bs-bn-minus / --probe-bs-minus / --probe-bn-minus
--probe-brdma-mul / --probe-nrdma-mul
--probe-regroup-stride2
```

This family uses the kernel_6_18 simple stream and the expt layout stream.
The two files are not byte-identical:

- `expt.make_regcmds` prepends four `S_POINTER` / `BRDMA_CFG` / `NRDMA_CFG`
  re-arm writes; kernel_6_18's `make_regcmds` does not.
- `expt.prepare_and_run` adds those four re-arm writes in front of every
  stream; the layout bundles therefore contain the same four writes twice
  (once from the prefix, once from `make_layout_regcmds`). This is the exact
  source behavior, not a bundle artifact.
- `expt.run_int16_add_to_int32` adds `(3 << 30)` to `EW_CFG` (alternate
  converter type/round mode); kernel_6_18 does not. The bundled
  `int16_add_to_int32_c8_w1` intentionally captures the kernel_6_18 stream.

## READY cases

All cases use 4096-byte BOs, zero padded. `expected.mask.bin` selects exactly
the asserted output bytes; surface/BO padding is not asserted.

| case | dtype | op | shape | layout | QWORDs |
|---|---|---|---|---|---|
| `int8_add_c8_w1` | INT8 | ADD | w1 c8 | contiguous | 18 |
| `int8_max_c8_w1` | INT8 | MAX | w1 c8 | contiguous | 18 |
| `int8_min_c8_w1` | INT8 | MIN | w1 c8 | contiguous | 18 |
| `int8_mul_c8_w1` | INT8 | MUL | w1 c8 | contiguous | 18 |
| `int16_add_c8_w1` | INT16 | ADD | w1 c8 | contiguous | 18 |
| `int16_minus_c8_w1` | INT16 | MINUS/SUB | w1 c8 | contiguous | 18 |
| `int16_mul_c8_w1` | INT16 | MUL | w1 c8 | contiguous | 18 |
| `int32_add_c8_w2` | INT32 | ADD | w2 c4 | contiguous | 18 |
| `int32_max_c8_w2` | INT32 | MAX | w2 c4 | contiguous | 18 |
| `int32_mul_int16_operand_c8_w2` | INT32 | MUL | w2 c4 | contiguous | 18 |
| `int8_add_c9_w1_layout` | INT8 | ADD | w1 c9 | C1WC2 16B surfaces | 44 |
| `int16_add_c9_w1_layout` | INT16 | ADD | w1 c9 | C1WC2 16B surfaces | 44 |
| `int16_minus_c9_w1_layout` | INT16 | MINUS/SUB | w1 c9 | C1WC2 16B surfaces | 44 |
| `int32_add_c9_w1_layout` | INT32 | ADD | w1 c9 | C1WC2 16B surfaces | 44 |
| `int16_add_to_int32_c8_w1` | INT16→INT32 | ADD | w1 c8 | INT16 in, INT32 out | 31 |

Notable values:

- `int8_add_c8_w1`: lane 7 is `100 + 5 = 105`, expected saturates to `127`.
- `int16_add_c8_w1`: lane 7 is `30000 + 1000 = 31000`, expected saturates to `32767`.
- `int16_minus_c8_w1`: lane 0 is `-30000 - 1000 = -31000`, expected saturates to `-32768`.
- These three overflow lanes deliberately probe the **candidate** saturation
  policy. They mirror the source's `integer_expected()` and its asserted
  hardware results, but they are not a TRM guarantee.
- `int32_mul_int16_operand_c8_w2`: the main cube is full INT32, but the separate
  MUL operand decodes as **signed INT16**. `50000` becomes `-15536`,
  `-50000` becomes `15536`. The oracle applies
  `s16(b & 0xffff)` per lane. This is a captured hardware limitation from the
  source, not a documented ABI; the capture is designed to confirm or reject it.
- The MUL cases use small values that stay inside the destination range, so
  they test multiply semantics rather than saturation policy.

## Oracle

`expected.bin` is a **host-side pure-Python formula**, never device data and
never written to `out.bin`. It is little-endian, signed dtype bytes, matching
the input encoding. It mirrors the source `integer_expected()`:

```
MAX   : max(a[i], b[i])
MIN   : min(a[i], b[i])
ADD   : saturate_dtype(a[i] + b[i])
MINUS : saturate_dtype(a[i] - b[i])
MUL   : saturate_dtype(a[i] * b[i]), except INT32 MUL uses s16(b[i] & 0xffff)
```

`expected.mask.bin` is 4096 bytes. `0xFF` marks an asserted byte and `0x00`
marks unasserted surface/BO padding. Compare:

```
(actual[i] & mask[i]) == (expected[i] & mask[i])   for i in 0..4095
```

Asserted bytes: 8 (INT8), 16 (INT16), 32 (INT32 simple), 8/16/32 for the
INT16→INT32 result, and 9/18/36 for the 9-lane INT8/INT16/INT32 layout cases.
The zero padding in `expected.bin` outside the mask is a convenience only.

For the 9-lane layout cases the oracle is computed on logical lanes and then
packed with the source's own `pack_c1wc2` rule, so the asserted bytes include
the tail surface. Padding bytes in a surface are excluded by the mask.

## Copied register facts

`regcmd.bin` is a concatenation of little-endian 64-bit QWORDs. Use
`tools/decode_regcmd.py` to print the decoded table.

### Simple 18-QWORD stream

Order (kernel_6_18 `make_regcmds`):

```
DPU.FEATURE_MODE_CFG, DPU.DATA_FORMAT, DPU.DATA_CUBE_CHANNEL,
DPU.DATA_CUBE_WIDTH, DPU.EW_CFG, DPU.EW_CVT_SCALE_VALUE,
RDMA.DATA_CUBE_WIDTH, RDMA.DATA_CUBE_HEIGHT, RDMA.DATA_CUBE_CHANNEL,
RDMA.ERDMA_CFG, DPU.DST_BASE_ADDR, RDMA.SRC_BASE_ADDR,
RDMA.EW_BASE_ADDR, RDMA.FEATURE_MODE_CFG, PC_REG.BASE_ADDRESS,
PC_REG.REGISTER_AMOUNTS, VERSION, PC.OPERATION_ENABLE
```

Common values:

| field | value |
|---|---|
| `FEATURE_MODE_CFG` | `0x000001E5` (burst_len=15, output_mode=2, flying_mode=1) |
| `EW_CVT_SCALE_VALUE` | `1` |
| `PC.OPERATION_ENABLE` | `0x18` |
| `PC_REG.*` | `0` |
| `VERSION` | `0` |

Per dtype/op:

| case | `DATA_FORMAT` | `EW_CFG` | `RDMA_ERDMA_CFG` | `RDMA_FEATURE_MODE_CFG` |
|---|---|---|---|---|
| INT8 ADD | `0x00000000` | `0x104202C0` | `0x40000004` | `0x00007801` |
| INT8 MAX | `0x00000000` | `0x106002C0` | `0x40000004` | `0x00007801` |
| INT8 MIN | `0x00000000` | `0x106102C0` | `0x40000004` | `0x00007801` |
| INT8 MUL | `0x00000000` | `0x104002C4` | `0x40000004` | `0x00007801` |
| INT16 ADD | `0x24000001` | `0x108202C0` | `0x40000008` | `0x0000F821` |
| INT16 MINUS | `0x24000001` | `0x108402C0` | `0x40000008` | `0x0000F821` |
| INT16 MUL | `0x24000001` | `0x108002C4` | `0x40000008` | `0x0000F821` |
| INT32 ADD | `0x90000004` | `0x10C203C0` | `0x4000000C` | `0x00027881` |
| INT32 MAX | `0x90000004` | `0x10E003C0` | `0x4000000C` | `0x00027881` |
| INT32 MUL | `0x90000004` | `0x10C003C4` | `0x4000000C` | `0x00027881` |

`DATA_CUBE_CHANNEL` is `channels-1` in both the ORIG_CHANNEL and CHANNEL
fields: `0x00070007` for c8, `0x00030003` for c4. `DATA_CUBE_WIDTH` is
`width-1`: `0` for the 8-lane simple cases, `1` for the INT32 w2 case.

### 44-QWORD layout stream

The first four QWORDs are the expt `prepare_and_run` re-arm prefix
(`DPU.S_POINTER=0xE`, `RDMA.S_POINTER=0xE`, `RDMA.BRDMA_CFG=1`,
`RDMA.NRDMA_CFG=1`). The following 40 are `make_layout_regcmds`, which begins
with the same four writes again, then:

```
DPU.FEATURE_MODE_CFG, DPU.DATA_FORMAT, DPU.DST_SURF_STRIDE,
DPU.DATA_CUBE_WIDTH, DPU.DATA_CUBE_HEIGHT, DPU.DATA_CUBE_NOTCH,
DPU.DATA_CUBE_CHANNEL, DPU.BS_CFG=0x53, DPU.BS_ALU_CFG=0,
DPU.BS_MUL_CFG=0, DPU.BS_OW_CFG=2, DPU.WDMA_SIZE_0,
DPU.WDMA_SIZE_1, DPU.BN_CFG=0x53, DPU.BN_ALU_CFG=0,
DPU.BN_MUL_CFG=0, DPU.EW_CFG, DPU.EW_CVT_SCALE_VALUE=1,
DPU.SURFACE_ADD, RDMA.DATA_CUBE_WIDTH, RDMA.DATA_CUBE_HEIGHT,
RDMA.DATA_CUBE_CHANNEL, RDMA.ERDMA_CFG, RDMA.EW_SURF_STRIDE,
RDMA.SRC_DMA_CFG=0, RDMA.SURF_NOTCH=0, RDMA.EW_SURF_NOTCH=0,
DPU.DST_BASE_ADDR, RDMA.SRC_BASE_ADDR, RDMA.EW_BASE_ADDR,
RDMA.FEATURE_MODE_CFG, RDMA.WEIGHT=0x01010101,
PC_REG.BASE_ADDRESS, PC_REG.REGISTER_AMOUNTS, VERSION,
PC.OPERATION_ENABLE=0x18
```

For width=1, c9: `DST_SURF_STRIDE = SURFACE_ADD = RDMA_EW_SURF_STRIDE = 0x10`,
`WDMA_SIZE_0 = 8`, `WDMA_SIZE_1 = 0`, `DATA_CUBE_CHANNEL = 0x00080008`.
The layout EW_CFG values are the same per dtype/op as the table above.

### 31-QWORD INT16→INT32 stream

`int16_add_to_int32_c8_w1` is the distinct 16-to-32 writeback path:

```
DPU.FEATURE_MODE_CFG=0x1E5, DPU.DATA_FORMAT=0x84000001,
DPU.DST_SURF_STRIDE=0x10, DPU.DATA_CUBE_WIDTH=0, HEIGHT=0, NOTCH=0,
DPU.DATA_CUBE_CHANNEL=0x00070007, DPU.BS_CFG=0x53, DPU.BS_OW_CFG=0x126,
DPU.WDMA_SIZE_0=7, WDMA_SIZE_1=0, DPU.BN_CFG=0x53,
DPU.EW_CFG=0x108202C0, EW_CVT_OFFSET=0, EW_CVT_SCALE=1,
OUT_CVT_OFFSET=0, OUT_CVT_SCALE=1, OUT_CVT_SHIFT=0,
DPU.SURFACE_ADD=0x20, RDMA...WIDTH=0, HEIGHT=0, CHANNEL=7,
RDMA.ERDMA_CFG=0x40000008, DST/SRC/EW_BASE_ADDR,
RDMA.FEATURE_MODE_CFG=0x0000F821, PC_REG.*=0, VERSION=0,
PC.OPERATION_ENABLE=0x18
```

The inputs stay plain INT16 (`-30000...30000`); the output is eight INT32
values (`-29000...31000`). `31000` is outside INT16 but must remain `31000`
in the INT32 output; this is the point of the case.

## Patches and job schema

`job.json` follows `CAPTURE_FORMAT.md` exactly:

- one task at `regcmd_offset_words=0`, `regcmd_words = len(regcmd.bin)/8`;
- three 4096-byte buffers `a`, `b` (direction `in`) and `out` (direction
  `out`, output `out.bin`);
- three `value32` patches per case:
  - `out` → `DPU.DST_BASE_ADDR` (`0x4020`)
  - `a` → `RDMA.SRC_BASE_ADDR` (`0x5018`)
  - `b` → `RDMA.EW_BASE_ADDR` (`0x5038`)

Placeholder addresses are deliberately distinct (`out=0x20000000`,
`a=0x10000000`, `b=0x10010000`) so a missed patch is visible.

The schema does not encode task-descriptor fields. The worker must use the
source examples' known-safe descriptor:

```
flags=0, op_idx=4, enable_mask=0x18, int_mask=0x300,
int_clear=0x1FFFF, int_status=0, regcfg_offset=0,
regcfg_amount=regcmd_words, regcmd_addr=<regcmd BO DMA address>
```

Do not run these as CPU fallbacks and do not write `expected.bin` to the
output BO. The worker's `out.bin` must be the real device readback, with the
actual addresses, `submit_ret`, duration, hashes and board identity recorded in
`capture.json`.

## BLOCKED cases

| case | reason |
|---|---|
| `int32_div_c8_w2` | DIV/FLOOR/CEIL are proven by the source to use floating-point semantics and are not integer ops; no trustworthy integer oracle. |
| `fp16_four_input_sum_c8_w1` | The only multi-input sum in either source is FP16 with FP32 BRDMA/NRDMA operands. This is an integer family; the mixed case needs an ew-fp16 family. |
| `fp16_bs_bn_relu_prelu_c8_w1` | ReLU-X/PReLU are emitted only in the FP16 BS/BN stages. ReLU6 and batchnorm are never emitted by either script. No integer activation path exists. |

FP32 is not a usable case either: neither example defines an FP32 EW dtype or
submits FP32 input. The expt FP16 pipelines use configured FP32 constants, but
those are non-integer probes (see `coverage.not_bundled_streams` in the
manifest).

## Local validation

Run from this directory:

```sh
/usr/bin/python3 tools/gen_bundles.py       # regenerate (deterministic)
/usr/bin/python3 tools/validate.py          # schema, sizes, patches, hashes
/usr/bin/python3 tools/crosscheck_source.py # compare against the real examples
python3 tools/decode_regcmd.py cases/int8_add_c8_w1
```

Recorded result on 2026-11-06:

- `tools/validate.py`: **READY 15, BLOCKED 3, FAILED 0**. It checks
  `job.json` key sets, one-task/word counts, buffer sizes and input file sizes,
  4096-byte output/expected/mask sizes, hash and bundle-hash equality, mask
  bytes in `{0x00,0xFF}`, asserted-byte counts, zero bytes outside the mask,
  patch indices in range, unique placeholders, and that every address-register
  QWORD has exactly one patch and vice versa.
- `tools/crosscheck_source.py`: **15 cases, 0 failed, 2312 function/constant
  comparisons** using Python 3.14.8 and NumPy 2.4.6. It imports the actual
  source modules, compares every generated QWORD stream for all dtype ×
  operation × width × channel combinations used by the source validators,
  decodes the input files with the source packers, and reproduces the oracle
  with the source `integer_expected`/`pack_c1wc2`. The INT16→INT32 case is
  captured by monkeypatching the source `prepare_and_run`, so its 31 QWORDs and
  payloads are compared directly.
- Source revision: `273d015e08af40c81d2cd9ab84198486b03a17f1`.
  Source SHA-256:
  - kernel_6_18 `elementwise_int.py`: `825c7c2166eed48fd73fc1d31655238928b0fd5677df539d17f7301dc671d329`
  - expt `elementwise_int.py`: `1c6a43b0d928b744420f4db1762527f5bbb52c7cc92dc2d1ef0aba2ff94b95f8`

These checks establish bundle consistency and source fidelity only. They do
**not** validate RK3588 silicon, the DRM/Rocket driver, DMA, or any output
value. Only the later board capture can do that.

## Caveats

1. **Saturation is candidate behavior.** The source asserts it for INT8/INT16
   ADD/MINUS and the oracle follows the source, but no TRM section is cited
   here. The overflow lanes are intentionally differential.
2. **INT32 MUL is a captured limitation, not a spec.** The signed-INT16 second
   operand model comes from the source's own experiment. Treat a mismatch as
   information, not as a bundle bug.
3. **INT32 9-channel layout is offline-validated only in the source.** The
   layout stream is register-legal and the source's
   `validate_integer_layout_streams` covers it, but the source's device probes
   do not claim that exact combination. The capture answers it.
4. **The simple cases use the kernel_6_18 stream without the S_POINTER re-arm
   prefix.** That is what the kernel_6_18 example submits. The layout cases use
   the expt prefix and therefore contain two copies of the four re-arm writes.
   Do not "clean up" either stream.
5. **Padding bytes are not asserted.** A surface tail or BO tail may contain
   anything; the mask excludes it. Do not compare `expected.bin` and `out.bin`
   byte-for-byte without the mask.
6. **No task-descriptor fields in `job.json`.** The documented schema does not
   carry `op_idx`/`enable_mask`/`int_mask`/`int_clear`; use the contract above.
7. No bitstream, FPGA image, or board state was touched. Preparation only.
