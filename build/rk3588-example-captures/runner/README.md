# RK3588 capture runner

`rocket_run.py` is the single board-side executor for prepared Rocket capture
bundles. `validate_bundle.py` is the host-side checker. Both use only the Python
standard library and have no NumPy dependency. Importing or running the
validator never opens `/dev/accel/*`.

This runner is for the **mainline Rocket UAPI** (`drm_rocket_create_bo`,
`drm_rocket_prep_bo`, `drm_rocket_fini_bo`, `drm_rocket_submit`) on the
RK3588. It is not the vendor RKNPU ABI and does not program or reset the NPU.

## Required board paths

The board worker must use these paths (or stage an exact equivalent and change
only the root consistently):

| Purpose | Path |
| --- | --- |
| Exclusive board lock | `/home/opencode-agent/rk3588-npu.lock` |
| Rocket DRM node | `/dev/accel/accel0` |
| Board runner | `/home/opencode-agent/rk3588-example-captures/runner/rocket_run.py` |
| Board queue root | `/home/opencode-agent/rk3588-example-captures/` |
| Family directory | `/home/opencode-agent/rk3588-example-captures/<FAMILY>/` |
| Case directories | `/home/opencode-agent/rk3588-example-captures/<FAMILY>/cases/<CASE>/` |
| Fresh output root | `/home/opencode-agent/rk3588-example-captures/runs/<RUN_ID>/<FAMILY>/` |

`<CASE>` must contain `job.json`, `regcmd.bin`, and the declared input files.
`<RUN_ID>` must be new for every invocation; do not point `--out` at an earlier
run.

## Host preflight

The validator does not contact the board:

```sh
python3 build/rk3588-example-captures/runner/validate_bundle.py \
  build/rk3588-example-captures/<FAMILY>/cases/<CASE>
```

It returns nonzero on any invalid bundle and prints every detected error.
`--output-dir` additionally rejects an existing case/output directory:

```sh
python3 build/rk3588-example-captures/runner/validate_bundle.py \
  --output-dir build/rk3588-example-captures/runner/out \
  build/rk3588-example-captures/<FAMILY>
```

## Exact board invocation

Copy the `runner/` directory and the family bundle to the board paths above,
create a fresh run directory, then run **one** command under the mandatory
exclusive lock:

```sh
flock -x /home/opencode-agent/rk3588-npu.lock \
  python3 /home/opencode-agent/rk3588-example-captures/runner/rocket_run.py \
    --device /dev/accel/accel0 \
    --out /home/opencode-agent/rk3588-example-captures/runs/<RUN_ID>/<FAMILY> \
    /home/opencode-agent/rk3588-example-captures/<FAMILY>
```

Substitute the actual `<RUN_ID>` (for example `20261106T120000Z`) and
`<FAMILY>`. The family directory is expanded to every sorted
`cases/<CASE>/job.json`; multiple case directories may also be passed
explicitly. A single case uses the same command with the case directory as the
last argument:

```sh
flock -x /home/opencode-agent/rk3588-npu.lock \
  python3 /home/opencode-agent/rk3588-example-captures/runner/rocket_run.py \
    --device /dev/accel/accel0 \
    --out /home/opencode-agent/rk3588-example-captures/runs/<RUN_ID>/single \
    /home/opencode-agent/rk3588-example-captures/<FAMILY>/cases/<CASE>
```

Use `flock -x` (exclusive), never `-s`. The lock must enclose the whole runner
process. Do not launch a second runner, retry a timed-out case, or reset the
device inside or outside this invocation.

`--validate-only` performs the same validation as `validate_bundle.py` without
opening a device or writing output:

```sh
python3 .../runner/rocket_run.py --validate-only \
  /home/opencode-agent/rk3588-example-captures/<FAMILY>
```

## Output layout

Each case gets its own directory under the fresh output root:

```text
<OUT_ROOT>/
  <case>/
    <job.buffers[].output>       # only real bytes read back from the device
    capture.json
```

Output filenames are relative paths from `job.json`. Existing case
directories, output files and `capture.json` are never overwritten. If any
output path already exists, that case fails before a device is opened. Output
parent directories are created only as needed.

`capture.json` contains:

- `status`: `OK` or `FAIL`;
- `submit_ret`: `0` on a successful submit ioctl, `null` when no submit
  occurred or the ioctl raised (see `submit_errno`/`submit_error`). This is
  the ioctl return, not job completion; completion is confirmed by the output
  `PREP_BO` wait. A timeout or readback failure is `FAIL` even when
  `submit_ret` is `0`;
- `addresses`: command BO, every buffer BO and every task `regcmd` DMA address;
- `sizes`: command stream and buffer sizes;
- `durations`: per-phase nanosecond timings, including allocation, prep,
  submit, wait/readback, output writes and total;
- `hashes`: `job.json`, source and patched `regcmd.bin`, input and output bytes;
- `buffers`: handle, DMA address, mmap offset, direction and input/output
  hashes;
- `tasks` and `patches`: the exact descriptors and patched QWORDs used;
- `device_path`, `device` audit (major/minor, kernel, driver and, when
  available, board compatible strings), `tool_version` and `tool` identity;
- `errors` and `cleanup_errors`.

All addresses and task descriptors are the actual values used by the
submission, not placeholders.

## Per-case execution sequence

1. Validate the bundle and all output paths.
2. Create `OUT_ROOT/<case>/` exclusively.
3. Open the audited Rocket device, create the command BO and one BO per named
   buffer, then mmap each BO.
4. Apply the patch list to the command QWORDs using the actual DMA addresses.
5. Build `drm_rocket_task` descriptors at
   `regcmd_dma + 8 * regcmd_offset_words`.
6. `PREP_BO` every BO, copy inputs and the patched command stream, then
   `FINI_BO` every BO.
7. Submit exactly one job (one command BO in the input handle list; named
   buffers partitioned between input and output lists).
8. `PREP_BO` each `out`/`inout` BO; this waits for the write fence and syncs
   the mapping for CPU readback.
9. Read every output BO completely. Only after all reads succeed write the
   declared output files exclusively.
10. Write `capture.json` and close mappings/handles/fd.

The runner never calls a reset ioctl and never writes driver/register state
other than the prepared command stream. It does not retry a submission.

## Failure handling

A per-case validation, allocation, patch, submit, timeout or readback failure:

- sets `status` to `FAIL` and records the exception text in `errors`;
- writes no output file unless every output BO was successfully read back;
- is not retried and does not reset or reprogram the device;
- does not stop later cases. A fresh fd is used for each case.

All validation failures are also recorded in `capture.json` when a safe case
name and unused output directory exist. The process exit status is `0` only
when every requested case has `status: OK`; otherwise it is `1`. A case with no
`out`/`inout` buffer is rejected because Rocket has no separate completion
ioctl: `PREP_BO` on an output BO is the wait boundary.

## Schema decisions and ambiguities

The format in `../CAPTURE_FORMAT.md` is applied strictly; unknown JSON fields
are rejected rather than ignored.

- `buffers[].input` must be exactly `buffers[].size` bytes. Truncating or
  zero-padding an input file is not silently performed. Input files (and
  `regcmd.bin`) must resolve inside the case directory.
- Input and output filenames must be relative, with no empty, `.` or `..`
  components. `capture.json` is reserved as an output name (including as a
  parent path). Two output paths may not be parent and child of each other.
  Case names must be unique across one queue because each owns
  `OUT_ROOT/<case>/`.
- Task offsets must be even QWORDs because the kernel requires a 16-byte
  aligned `drm_rocket_task.regcmd`; task ranges must fit the file and must not
  overlap each other. Rocket's PC fetch amount is expressed in QWORD pairs, so
  an odd `regcmd_words` actually fetches one extra QWORD. The validator checks
  the rounded-up fetch range (and overlap) while the descriptor keeps the
  declared count.
- Patch bit ranges must not overlap on the same QWORD. `all32` and `low32` have
  the same specified mask (`[31:0]`); they are accepted and behave identically.
  `value32` and `all32` reject a DMA address above 32 bits instead of
  truncating it. `low32`/`high32` select a half of the 64-bit address.
- `inout` BOs are listed only in `out_bo_handles`. Listing one object in both
  kernel arrays would lock the same reservation twice. The output write fence
  also covers the readback wait.
- The command BO is also in `in_bo_handles` so its lifetime/dependency is
  explicit.
- Rocket's `prep_bo.timeout_ns` is interpreted by the current mainline driver
  as an absolute monotonic deadline, despite the UAPI comment wording. The
  runner passes `time.monotonic_ns() + job.timeout_ns`.
- `job.timeout_ns` bounds the runner's output wait. The kernel's internal job
  timeout is independent and may be shorter.

## Host-only tests

```sh
python3 -m unittest discover \
  -s build/rk3588-example-captures/runner/tests -v
```

These tests build synthetic bundles and exercise validation, patching,
descriptor construction and handle partitioning. They do not open a device and
do not establish any board, FPGA or numerical result.
