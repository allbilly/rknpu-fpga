# Vendor-ABI conv/GEMM -> mainline Rocket bundles

Device-free preparation for the vendor `conv.py`, `conv_gemm.py`,
`conv_legacy.py` and `gemm.py` command streams. The RK3588 at
`192.168.192.18` exposes mainline Rocket, not the vendor `rknpu` driver, so
these bundles express each selected case as a Rocket job:

- one Rocket task descriptor per vendor task: 32-bit `regcmd` address and
  `regcmd_count`;
- the raw little-endian command QWORD stream in `regcmd.bin`;
- deterministic input BO bytes;
- `value32` patches for every DMA address field; and
- a clearly labelled host-side NumPy oracle.

No board command, vendor ioctl, SSH/SCP, FPGA programming or flash action was
performed. READY means **the command stream is expressible through Rocket's
`regcmd + regcmd_count` UAPI**, not that the RK3588 or FPGA has executed it or
that the numerical result has been accepted.

## Status

| Status | Count | Meaning |
|---|---:|---|
| READY | 10 | One single-core Rocket job per case; no vendor-only task fields needed for the command stream. |
| BLOCKED | 3 | Vendor multi-core `core_mask`/`subcore_task` split, PC-chain runtime-regcmd addressing, or an unsupported multi-task Rocket job. |

Manifest: `manifest.json` (source lines, shape, task count, oracle, hashes,
blocker evidence).

## Layout

```
conv-gemm-vendor/
  manifest.json
  README.md
  tools/prepare_bundles.py
  tools/validate_bundles.py
  cases/<case>/
    job.json
    regcmd.bin
    input.bin
    weight.bin
    expected.bin            # logical NCHW / MxN oracle, not device output
    expected_surface.bin    # GEMM only: raw Mxalign_out FP32 surface
    BLOCKED.md              # BLOCKED cases only
```

`output.bin` is written by the board-side worker after the job; it is not
present here.

## Vendor-to-Rocket crosswalk

| Vendor RKNPU | Mainline Rocket | Bundle expression |
|---|---|---|
| `DRM_IOCTL_RKNPU_MEM_CREATE` + `RKNPU_MEM_MAP` | `DRM_IOCTL_ROCKET_CREATE_BO` + `mmap(offset)` | `buffers[].size` and input files; worker allocates/maps the BOs. |
| `struct rknpu_task { flags, op_idx, enable_mask, int_mask, int_clear, regcfg_amount, regcfg_offset, regcmd_addr }` | `struct drm_rocket_task { __u32 regcmd; __u32 regcmd_count; }` | `tasks[]` only carries offset/count. The vendor `op_idx`, `enable_mask`, `int_mask`, `int_clear`, flags and `regcfg_offset` are recorded in the manifest but are not sent. |
| `DRM_IOCTL_RKNPU_SUBMIT` with `task_start/task_number/core_mask/subcore_task/flags` | `DRM_IOCTL_ROCKET_SUBMIT` with a job containing a task array | `job.json` is the job. Rocket's `drm_sched_entity` selects one core; there is no `core_mask` or `subcore_task`. |
| Vendor `npu_reset` (`RKNPU_ACT_RESET`) before submit | Rocket core reset is owned by the DRM scheduler | No vendor reset command is part of the stream. |
| `RKNPU_MEM_SYNC` / cache maintenance | `ROCKET_PREP_BO` / `ROCKET_FINI_BO` | The worker copies inputs before submit and reads outputs after completion. No READY source path calls `RKNPU_MEM_SYNC`. |
| `PC_BASE_ADDRESS` / `PC_REGISTER_AMOUNTS` PC chain | Rocket writes the first task's base/amount itself and starts the next task after the interrupt | READY cases have a **terminal** tail (`PC_BASE_ADDRESS=0`, `PC_REGISTER_AMOUNTS=0`). Blocked multi-task chains point `PC_BASE_ADDRESS` at the regcmd BO itself, which has no patch kind. |

### Count crosswalk (important)

The vendor driver programs:

```
PC_DATA_AMOUNT = (regcfg_amount + RKNPU_PC_DATA_EXTRA_AMOUNT
                  + pc_data_amount_scale - 1) / pc_data_amount_scale - 1
RKNPU_PC_DATA_EXTRA_AMOUNT = 4
pc_data_amount_scale = 2 on RK3588
```

so it fetches `2 * ceil((regcfg_amount + 4) / 2)` QWORDs: the body, the
4-QWORD terminal tail, and (when the body+tail length is odd) one zero-filled
QWORD from the vendor's zeroed regcmd BO. Rocket instead computes
`PC_DATA_AMOUNT` directly from `regcmd_count`:

```
PC_DATA_AMOUNT = (regcmd_count + 1) / 2 - 1
```

If `regcmd_count` is odd, Rocket's PC unit fetches one QWORD beyond it. Each
READY `job.json` therefore uses an **even** count:

```
regcmd_words = 2 * ceil((vendor regcfg_amount + 4) / 2)
```

and `regcmd.bin` includes the zero NOP parity pad when needed. This fetches
exactly the bytes the vendor driver would execute and never reads past the
bundle. The terminal tail follows the source:

```
conv.py / conv_gemm.py / conv_legacy.py:
  PC_BASE_ADDRESS = 0
  PC_REGISTER_AMOUNTS = 0
  VERSION = 0
  PC_OPERATION_ENABLE = 0x0000000d   # (6 << 1) | 1

gemm.py:
  target 0x0001 NOP (value 0, offset 0)
  PC_REGISTER_AMOUNTS = 0
  VERSION = 0
  PC_OPERATION_ENABLE = 0x0000000d
```

Rocket's own `PC_BASE_ADDRESS`/`PC_REGISTER_AMOUNTS`/`OPERATION_ENABLE` writes
happen before the stream; the terminal tail then clears/finishes the chain
state, as in the vendor examples. Rocket's task limit is 131,072 QWORDs; the
largest READY task is 112 QWORDs.

## READY cases

| Case | Source / table | Shape | Task QWORDs | Output | Oracle |
|---|---|---|---:|---|---|
| `gemm_m2_n2_k1` | `gemm.py` main table | M2 N2 K1 | 50 | FP32 | NumPy FP64 matmul -> FP32 |
| `gemm_m1_n16_k32` | `gemm.py` builder (not in tiny main table) | M1 N16 K32 | 50 | FP32 | NumPy FP64 matmul -> FP32 |
| `gemm_m2_n16_k32` | `gemm.py` builder | M2 N16 K32 | 50 | FP32 | NumPy FP64 matmul -> FP32 |
| `gemm_m4_n32_k64` | `gemm.py` builder | M4 N32 K64 | 50 | FP32 | NumPy FP64 matmul -> FP32 |
| `conv_1x1_c1_oc6_h4w4` | `conv_gemm.py` line 1243 | C1 H4 W4 -> OC6, 1x1 | 52 | FP16 | NumPy FP64 conv -> FP16 |
| `conv_grouped_3x3_c4_oc4_g2_h5w5` | `conv_gemm.py` line 1288 | C4/OC4/G2, H5 W5 -> H3 W3 | 52 | FP16 | NumPy FP64 conv -> FP16 |
| `conv_depthwise_3x3_c3_oc3_h11w28_task0` | `conv_legacy.py` line 861 | C3/OC3/G3, H11 W28 -> H9 W26 | 52 | FP16 | NumPy FP64 conv -> FP16 |
| `conv_depthwise_3x3_c3_oc3_h11w28_task1` | `conv_legacy.py` line 861 | C3/OC3/G3, H11 W28 -> H9 W26 | 52 | FP16 | NumPy FP64 conv -> FP16 |
| `conv_legacy_3x3_c4_oc4_h9w9` | `conv_legacy.py` line 855 | C4 H9 W9 -> OC4, 3x3 | 52 | FP16 | NumPy FP64 conv -> FP16 |
| `conv_py_3x3_c32_oc128_h14w14_fullsetup` | `conv.py` line 536 / full setup | C32 H14 W14 -> OC128 H12 W12, 3x3 | 112 | FP16 | NumPy FP64 conv -> FP16 |

The source intentionally submits the depthwise task twice
(`_direct_submit_repeat` returns 2 for depthwise spatial). The Rocket board
path executes only the first task of a two-task job, while task 1 alone passes
exactly. The executable form is therefore split into two one-task cases,
`..._task0` and `..._task1`; each has the same 52-QWORD stream at offset 0,
identical `input.bin`/`weight.bin`/`expected.bin`, and the same three address
patches at indices 18/24/32. Each split job declares a 15104-byte output BO:
the stream has `DPU_DATA_CUBE_CHANNEL=0x1f` (32 channels) and
`SURFACE_ADD=7552`, requiring two 7552-byte surface groups. The original
two-task case is retained as `BLOCKED` with code
`MULTITASK_ROCKET_JOB_UNSUPPORTED` and its two-task job and 104-QWORD stream
preserved under `cases/conv_depthwise_3x3_c3_oc3_h11w28/evidence/`.

The depthwise entry is taken from `conv_legacy.py`, not the equivalent
`conv_gemm.py` table entry. `conv_gemm.py` generates its inputs/weights with
`arange`, which makes that 3x3 depthwise output overflow FP16 (`inf` in the
host oracle). `conv_legacy.py` uses the source `seed=42, uniform(-2,2)`
generator and keeps the oracle finite.

### Why these are READY

- Each selected source task is a single setup/NONE body with a terminal,
  self-clearing PC tail. There is no linked `PC_BASE_ADDRESS`.
- Each has exactly three DMA fields: `CNA_FEATURE_DATA_ADDR`,
  `CNA_DCOMP_ADDR0`, `DPU_DST_BASE_ADDR`. No input/weight/output offsets are
  needed, so one buffer per role and `value32` patches are sufficient.
- No READY path calls `RKNPU_MEM_SYNC`, uses a compressed-weight control, or
  needs a vendor multicore split.
- The GEMM cases are single-task because the source's `m_tile` is larger than
  the selected M; no per-tile output-offset patches are needed.

## BLOCKED cases

### `conv_depthwise_3x3_c3_oc3_h11w28`

Reason code: `MULTITASK_ROCKET_JOB_UNSUPPORTED`. The source submits the same
depthwise task twice. This original case encoded both submissions as two tasks
in one Rocket job (`[0,52)` and `[52,104)`). The Rocket board path executes only
the first task of a two-task job; task 1 alone passes exactly. The runnable
split cases are `..._task0` and `..._task1`. The original two-task job, the
104-QWORD stream, inputs and expected output are preserved under
`cases/conv_depthwise_3x3_c3_oc3_h11w28/evidence/`.

### `conv_byk_c160_h14w14_oc320_k3x3`

`conv.py:1766-1797` (`run_exact11_byk_shape`) submits 11 PC-chain rows with:

```
subcores = ((0, 1), (0, 1), (0, 1), (0, 0), (0, 0))
npu_submit(..., task_count=3, core_mask=0, subcores=subcores)
```

`core_mask=0` is `RKNPU_CORE_AUTO_MASK`; the three subcore entries assign one
task each to three physical cores. Rocket has one `drm_sched_entity` per file
and no `core_mask`/`subcore_task` UAPI. The layout also writes
`PC_BASE_ADDRESS` to the regcmd BO DMA address and non-zero
`PC_REGISTER_AMOUNTS`; the bundle schema only patches named buffer addresses,
not the runtime regcmd address.

### `conv_h40_c160_h40w40_oc320_k3x3`

`conv.py:2331-2358` (`run_h40_exact17_shape`) submits 17 PC-chain rows with:

```
subcores = ((0, 2), (0, 2), (0, 2), (0, 0), (0, 0))
npu_submit(..., task_count=6, core_mask=0, subcores=subcores)
```

Two tasks are assigned to each of cores 0, 1 and 2. The same Rocket UAPI and
patch-schema limitations apply. The exact source excerpts are in each
`cases/<case>/BLOCKED.md`.

## Source main/argument handling inspected

- `gemm.py`: device opens at import; main only has `(2,2,1)` and `(2,2,2)` in
  `test_cases`. `make_gemm_regs`/`run_gemm` are public and support the requested
  `(1,16,32)`, `(2,16,32)` and `(4,32,64)`; those are built with the same
  seed-42 matrix generator pattern shown in the commented sweep, not claimed
  as main-table cases.
- `conv_gemm.py`: device opens at import; main dispatches `conv`/`gemm`
  filters and has a large hard-coded shape table at lines 1241-1361. The
  selected 1x1, grouped 3x3 and depthwise cases are exact entries.
- `conv_legacy.py`: device opens at import; main has no shape argument and runs
  its full table (including the selected 3x3 entry at line 855) with the
  `--out fp16` option.
- `conv.py`: `argparse` requires a shape unless `--list`; `validate_phase_a_shape`
  accepts only one setup/NONE descriptor for the selected 3x3 shape. The
  multi-core BY_K/H40 paths are guarded by explicit `--allow-*` flags.

## Oracle labels and limits

`expected.bin` is a **host-side NumPy oracle**, not a device output:

- Conv: FP64 accumulation over the source's NCHW input/weight arrays, cast to
  the hardware output dtype. Compare by unpacking `output.bin` with the named
  source unpack function (`_unpack_flat_1x1_output`,
  `_unpack_grouped_spatial_output`, or `conv.py:unpack_output`).
- GEMM: FP64 matmul cast to FP32; `expected.bin` is logical MxN. For GEMM,
  `expected_surface.bin` is the raw Mx`align_out` FP32 surface padded to the
  output BO size, so it can be compared directly.
- Tolerances are recorded per case in `manifest.json`. These oracles do not
  establish the RK3588/FPGA accumulation order, rounding or special-value
  behavior.

All input/weight files are deterministic raw bytes. Conv_gemm uses the source
`arange` inputs/weights; conv_legacy and conv.py use the source seed-42
`uniform(-2,2)` generator; GEMM uses seed-42 random normal values, except the
main-table `(2,2,1)` case which uses the exact `[[1],[2]]` and `[[4,5]]`
matrices from `gemm.py`.

## Local validation

```
/usr/bin/python3 tools/prepare_bundles.py
/usr/bin/python3 tools/validate_bundles.py
/usr/bin/python3 tools/check_oracles.py
```

The validator checks manifest/status counts, source hashes, job keys, buffer
files and sizes, regcmd QWORD length, even task range alignment/bounds and the
Rocket 131,072-QWORD limit, patch indices/buffers/kinds, the simulated
`value32` relocation, the terminal tail/parity pad, expected-file sizes/hashes,
and the vendor-to-Rocket count crosswalk. `check_oracles.py` independently
re-derives every READY oracle with an FP64 NumPy einsum/matmul and reports a
zero byte-level difference from `expected.bin`.

Latest local result:

```
PASS: READY=10 BLOCKED=3 cases=13 max_regcmd_words=112 rocket_max=131072
PASS: 10 READY oracles match independent NumPy derivation
```

These are host-side schema/consistency/oracle checks only. They do not
validate SystemVerilog, the actual RK3588 NPU, the FPGA, or the numerical
result on hardware.

## Board-side notes for the later worker

- Submit one case at a time under the exclusive board lock; do not assume this
  preparation can submit.
- Rocket's scheduler timeout is 500 ms (`JOB_TIMEOUT_MS`), not the
  `timeout_ns` value in `job.json`.
- Rocket chooses the core; these bundles do not pin core 0. The command streams
  are single-core and do not depend on a particular core index.
- Patch `value32` fields with the real 32-bit DMA address of the named buffer.
  All READY address fields are 16-byte-aligned placeholders.
- For depthwise, submit `..._task0` and `..._task1` as two separate one-task
  jobs. Do not submit the preserved original as a two-task job; it is blocked
  with `MULTITASK_ROCKET_JOB_UNSUPPORTED`.
- Do not copy a host-side oracle into `output.bin`. Read the real BO after
  completion and compare against `expected.bin` / `expected_surface.bin`.
