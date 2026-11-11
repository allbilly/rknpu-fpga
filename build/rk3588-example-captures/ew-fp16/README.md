# ew-fp16: device-free RK3588 FP16 elementwise capture bundles

This directory contains **prepared, device-free** capture bundles for the
RK3588 FP16 elementwise examples:

- `/home/fedora/rk3588/examples/elementwise.py`
- `/home/fedora/rk3588/examples/simple_add.py`
- donor implementation: `/home/fedora/rk3588/experimental/kernel_6_18/elementwise.py`
- reviewed local register/EW_CFG definitions: `/home/fedora/rknpu-fpga/model/profile.py`

Nothing here was produced by, or has been run on, the Orange Pi, RK3588
silicon or the FPGA. No `ssh`, `scp`, board command, submit or program/flash
was executed. The `expected.bin` files are **donor CPU oracles**, never device
outputs and never a runtime fallback.

## Status

| Item | Value |
|---|---|
| Family | `ew-fp16` |
| READY cases | **54** |
| BLOCKED cases | **0** |
| Ops | ADD, SUB, MUL, MAX, NEG, finite FDIV |
| Core lengths | 8, 9, 33 (patterns p1 and p2) |
| Optional lengths | 1, 7, 1024 (pattern p1) |
| Manifest | `manifest.json` |
| Local validator | `tools/validate.py` |

Each case is self-contained under `cases/<case>/`:

```
job.json        CAPTURE_FORMAT.md job description
regcmd.bin      22 little-endian 64-bit command QWORDs
a.bin           4096-byte input BO image (A operand)
b.bin           4096-byte input BO image (B / EW-weight operand)
expected.bin    logical-N donor CPU oracle, FP16 little-endian
```

`out.bin` is declared in `job.json` but deliberately does not exist in the
bundle: the later board worker creates it from the actual device output.

## Command derivation

The command stream is the single-task terminal path of
`/home/fedora/rk3588/examples/elementwise.py`:

- `elementwise.py:246-352` builds the 8-lane width and the 18 DPU/RDMA writes.
- `elementwise.py:199-244` appends the four terminal PC tail words and writes
  the task descriptor.
- `elementwise.py:475-478` defines the donor CPU comparison path.
- `simple_add.py:196-236` independently confirms the EW_CFG values and the
  `(n + 7)//8 - 1` width formula.
- `model/profile.py:11-37,156-170` is the reviewed local whitelist for the
  same 22-word terminal layout (ADD/SUB/MUL/MAX only; see caveats).

The resulting 22 QWORDs (indices 0..21) are:

| idx | target | offset | value |
|---:|---|---|---|
| 0 | DPU 0x1001 | 0x4004 | 0x0000000e (S_POINTER) |
| 1 | DPU | 0x400c | 0x000001e5 (FEATURE_MODE_CFG) |
| 2 | DPU | 0x4010 | 0x48000002 (fp16 in/proc/out) |
| 3 | DPU | 0x4030 | width = `(N + 7)//8 - 1` |
| 4 | DPU | 0x4034 | 0 (height) |
| 5 | DPU | 0x4038 | 0 (notch) |
| 6 | DPU | 0x403c | 0x00070007 (channels) |
| 7 | DPU | 0x4070 | EW_CFG (per op, below) |
| 8 | DPU | 0x4084 | OUT_CVT_SCALE (per op, below) |
| 9 | RDMA 0x2001 | 0x5004 | 0x0000000e (S_POINTER) |
| 10 | RDMA | 0x500c | width |
| 11 | RDMA | 0x5010 | 0 (height) |
| 12 | RDMA | 0x5014 | 7 (channels) |
| 13 | RDMA | 0x5034 | 0x40000008 (ERDMA cfg) |
| 14 | DPU | 0x4020 | **DST placeholder 0**, patched from `out` |
| 15 | RDMA | 0x5018 | **SRC placeholder 0**, patched from `a` |
| 16 | RDMA | 0x5038 | **EW placeholder 0**, patched from `b` |
| 17 | RDMA | 0x5044 | RDMA_FEATURE_MODE_CFG (per op) |
| 18 | PC_REG 0x0101 | 0x0010 | 0 (terminal next address) |
| 19 | PC_REG | 0x0014 | 0 (terminal next amount) |
| 20 | VERSION 0x0041 | 0x0000 | 0 (marker) |
| 21 | PC 0x0081 | 0x0008 | 0x18 (DPU+RDMA enable) |

`job.json` declares one task:

```json
"tasks": [{"regcmd_offset_words": 0, "regcmd_words": 22}]
```

The three address fields are zero placeholders. `job.json` contains exactly
three `value32` patches:

```json
{"regcmd_index": 14, "buffer": "out", "kind": "value32"}
{"regcmd_index": 15, "buffer": "a",   "kind": "value32"}
{"regcmd_index": 16, "buffer": "b",   "kind": "value32"}
```

`value32` replaces command bits `[47:16]`, which is the RK address layout
(`target << 48 | address32 << 16 | offset`). The worker must apply all three
before submit; an unpatched stream addresses zero and should fail visibly.

## Per-op values

| op | EW_CFG | OUT_CVT_SCALE | RDMA_FEATURE_MODE_CFG |
|---|---|---|---|
| ADD | 0x108202c0 | 0x00010001 | 0x00017849 |
| SUB | 0x108402c0 | 0x00010001 | 0x00017849 |
| MUL | 0x108003c4 | 0x00010001 | 0x00017849 |
| MAX | 0x108002c0 | 0x00010001 | 0x00017849 |
| NEG | 0x108003c4 | 0x00010001 | 0x00017849 |
| FDIV (finite) | 0x108303c0 | 0x00000001 | 0x00017841 |

NEG is the example's MUL datapath with the EW weight buffer fixed to `-1.0`
(`elementwise.py:273`). FDIV uses the donor finite configuration
(`elementwise.py:259-260,333,345-351` and donor `elementwise.py:248-249,266`):
unity output conversion and `MRDMA_FP16TOFP32_EN` off. No FDIV Inf/NaN/zero
divisor case is included; those captures remain separate work.

## 8-lane padding

For logical `N`, `width = (N + 7)//8 - 1` and the hardware processes
`padded = 8*(width+1)` FP16 lanes:

| N | width | padded lanes | padded bytes |
|---:|---:|---:|---:|
| 1 | 0 | 8 | 16 |
| 7 | 0 | 8 | 16 |
| 8 | 0 | 8 | 16 |
| 9 | 1 | 16 | 32 |
| 33 | 4 | 40 | 80 |
| 1024 | 127 | 1024 | 2048 |

Buffers are 4096 bytes, matching the CAPTURE_FORMAT.md example size. The first
`padded` lanes carry defined data; all input bytes after `2*padded` are zero.
The oracle covers only the first `N` lanes; the extra physical lanes are device
padding and are deliberately excluded from `expected.bin`. The output BO is
freshly allocated by the worker, so `out.bin` bytes beyond `2*padded` are not
oracle-checked and may be allocator residue.

Padding fill:

- `a.bin`: logical A pattern, then `+0.0` for padded lanes.
- `b.bin`: logical B pattern (or `-1.0` for NEG), then `+0.0` for padded lanes,
  except FDIV uses `+1.0` so padded lane `0/1` stays finite. This avoids a
  `0/0` special in padding while leaving the example's group count unchanged.

## Input patterns

`p1` ("ramp_desc", `a=1..N`, `b=8..1` cyclic):

```
a[i] = i + 1
b[i] = 8 - (i mod 8)          # 8,7,6,5,4,3,2,1,8,...
```

`p2` ("signed_frac", a second distinct pattern with signs and fractions):

```
a[i] = ((i mod 11) - 5) * 0.5    # -2.5,-2.0,...,2.5 cyclic
b[i] = ((i mod 7) + 1) * 0.5     # 0.5,1.0,...,3.5 cyclic (strictly positive)
```

All values are exactly representable FP16. FDIV `b` is strictly positive and
finite. For NEG the B buffer is the MUL weight and is `-1.0` in every logical
lane; the A pattern is unchanged and the `p1`/`p2` distinction still varies A.
No RNG or seed is used; all patterns are closed-form and byte-reproducible.
`p2` A includes `+0.0`, so NEG `p2` has one donor result of `-0.0` (`0x8000`).
That lane is finite but sign-sensitive; compare raw halfword bits rather than
normalizing signed zero. FDIV `p2` computes `+0.0 / positive = +0.0` there.

`p1` is prepared for all lengths. `p2` is prepared for the core lengths
8, 9 and 33.

## Oracle

`expected.bin` is the donor CPU result, marked `device_output: false` in
`manifest.json`:

```
expected = float16(op(float32(a), float32(b)))
```

This is the same path as `examples/elementwise.py:475-478` and the donor
`OPS` table at `experimental/kernel_6_18/elementwise.py:302-309`. NEG uses
`float16(-float32(a))`. The oracle is logical-N only, FP16 little-endian.

It is **not** a device output, not a substitute for a capture, and no capture
result has been fabricated. A later board run must compare the actual
`out.bin` first `N` halfwords against `expected.bin` and record the real
differences; the donor example's own comparison uses
`np.allclose(..., atol=0.1)`, which is a hint, not a device contract.

## Local validation

`tools/validate.py` is a standalone parser. It checks:

- manifest shape and summary counts;
- case directory/file set and `job.json` key set;
- buffer count, names, sizes (4096), directions and file names;
- one task with offset 0 and 22 words;
- `regcmd.bin` is exactly 176 bytes and matches the 22-QWORD target/offset/
  fixed-value template, per-op EW_CFG/out_convert/rdma_mode, width, zero
  address placeholders and final enable;
- exactly three patches at indices 14/15/16 mapping to `out`/`a`/`b`, all in
  range and all `value32`;
- input pattern bytes, 8-lane padding fill and zero bytes after the padded
  region;
- `expected.bin` size and, when NumPy is available, byte-exact recomputation
  of the donor oracle plus finite-result checks for logical and padded lanes;
- every manifest file hash and the canonical `bundle_sha256`.

Run:

```sh
/usr/bin/python3 tools/validate.py
```

Result recorded in `validation.txt`:

```
cases: 54 total, 54 READY, 0 BLOCKED
oracle recompute: numpy 2.4.6, 54 checked, 0 mismatches
structural errors: 0
result: PASS
```

The same structural checks pass under the default Python without NumPy
(oracle recompute reports `SKIP`), and `sha256sum -c SHA256SUMS` verifies all
274 entries.

This is local structural/numerical-oracle validation only. It does not
validate RK3588 silicon, SystemVerilog, timing, or the FPGA bitstream.
`make generated-check` passes, and no tracked source, test or doc was changed;
the repository's full `make test` suite was not run as evidence for these
bundles because this preparation does not alter RTL, model or generated
sources.

## Bundle hashes

`manifest.json` records, for every case:

- `bundle.<file>.bytes` and `bundle.<file>.sha256` for `a.bin`, `b.bin`,
  `expected.bin`, `job.json` and `regcmd.bin`;
- `bundle_sha256`, computed over the sorted file records as
  `name + NUL + size_decimal + NUL + sha256_hex + "\n"` (name order is
  lexicographic).

`SHA256SUMS` covers the case bundles, `manifest.json`, this README and
`tools/`. It excludes itself and `validation.txt` (which is a run log appended
after the hashes). Verify from this directory with:

```sh
sha256sum -c SHA256SUMS
```

## Reproduction

```sh
cd /home/fedora/rknpu-fpga/build/rk3588-example-captures/ew-fp16
/usr/bin/python3 tools/generate.py    # rewrites cases/ and manifest.json
/usr/bin/python3 tools/validate.py
```

The generator records the inspected source revisions and source file hashes in
`manifest.json`. Re-running it after a source change will produce different
hashes; do not copy old capture evidence to modified sources.

## Caveats and schema decisions

1. **NEG and FDIV local-profile scope.** NEG is the MUL datapath with an EW
   weight of `-1.0`; its EW_CFG is the same `0x108003c4` value as MUL, so
   `model/profile.py` would accept it as MUL (there is no distinct NEG name).
   FDIV is outside the local profile: EW_CFG `0x108303c0`, `out_convert=1` and
   `rdma_mode=0x00017841` are not in the current whitelist. Both target RK3588
   silicon via the donor/example path. This is a scope caveat, not a claim that
   either bundle is device-validated.
2. **22-word command choice.** `simple_add.py` emits a shorter 14-word command
   without S_POINTER/height/notch/OUT_CVT_SCALE. The selected
   `elementwise.py` path emits the full 18-write body plus the four PC tail
   words, and matches the reviewed 21-field profile order. All cases use the
   full 22-word form.
3. **Terminal tail.** The example's terminal task writes
   `next_address=0`, `next_amount=0`, VERSION marker 0 and enable `0x18`.
   Nonzero guard addresses used by the production tinygrad capture are not
   part of this donor example path.
4. **Placeholder convention.** `CAPTURE_FORMAT.md` does not prescribe a
   placeholder value for patched fields. This family uses zero, which is
   fail-visible if a worker forgets a patch (address zero) rather than silently
   aliasing a valid buffer.
5. **Buffer size.** `CAPTURE_FORMAT.md` uses 4096-byte buffers; the source
   examples allocate 4 MiB. These bundles use 4096 bytes with explicit zero
   fill beyond the padded lanes. Only the first `2*padded` bytes are
   meaningful.
6. **Oracle extent.** `CAPTURE_FORMAT.md` does not define `expected.bin`
   length/dtype/endianness. This family defines it as logical-N FP16
   little-endian and records that in each case's `oracle` object. Padded lanes
   are not oracle-checked.
7. **READY semantics.** READY means the bundle is complete for a later RK3588
   capture. It does not mean the local RTL supports every op (FDIV is outside
   the profile; NEG is accepted as MUL), and it is not a hardware result.
8. **NEG weight discrepancy.** `simple_add.py:247` fills `0xffff` (the FP16
   NaN bit pattern) for its `neg_op` helper, whereas
   `examples/elementwise.py:273` and the donor use `-1.0`. These bundles follow
   the elementwise/donor `-1.0` MUL path; `0xffff` would be a NaN operand, not
   a negation.
9. **Address alignment.** The worker's Rocket BO DMA addresses are assumed
   16-byte aligned (the allocator normally returns page-aligned addresses), as
   required by the `value32` register layout. The bundles cannot check the
   actual addresses.
