# conv-fp16 two-task zero-output diagnosis

Run ID: `20261105T211500Z` (board UTC)
Board: `orangepi5`, kernel `6.18.24-current-rockchip64 #2 SMP PREEMPT Wed Apr 22 11:22:34 UTC 2026 aarch64`
Device: `/dev/accel/accel0` (mainline Rocket UAPI; no vendor `rknpu`)
Owner: single authorized board worker. No FPGA programming/flashing, no `sudo`,
no device reset, no retry beyond the single requested control re-run.

## Question

In `conv_grouped_3x3_c4_h5_w5_oc8_g2` and
`conv_splitoc_3x3_c16_h9_w9_oc16`, task 0 is correct and task 1 reads back an
all-zero output BO. Is the task-1 command stream itself wrong, or does the
Rocket multi-task job path fail to execute task 1?

## Method

Four one-task bundles were derived under
`build/rk3588-example-captures/conv-fp16-task-diagnostic/bundles/`:

| derived case | source task | input files | output |
|---|---|---|---|
| `diag_grouped_task0` | grouped task 0 | `a0.bin`, `w0.bin` | `out0`, 768 B |
| `diag_grouped_task1` | grouped task 1 | `a1.bin`, `w1.bin` | `out1`, 768 B |
| `diag_splitoc_task0` | split-OC task 0 | `a0.bin`, `w0.bin` | `out0`, 3328 B |
| `diag_splitoc_task1` | split-OC task 1 | `a0.bin`, `w1.bin` | `out1`, 3328 B |

For every derived bundle:

- `regcmd.bin` is the byte-identical 54-QWORD slice of the original task,
  copied to offset 0 (sha256 `29b60f0b…` grouped, `a60a4448…` split-OC);
- every address patch is rebound to the named buffer at the local index
  (task-1 indices 75/81/89 became 21/27/35);
- the task declares `regcmd_offset_words=0`, `regcmd_words=54` and preserves
  the source terminal PC tail
  (`PC_BASE_ADDRESS=0`, `PC_REGISTER_AMOUNTS=0`, `VERSION=0`,
  `OPERATION_ENABLE=0xd`);
- the input files are byte-identical copies and the output sizes are preserved.

The original bundles were opened read-only. Their file hashes were unchanged
after the run. The original grouped two-task bundle was copied unmodified into
the board run directory as the control.

## Validation

- Host `validate_bundle.py`: 4/4 `OK` (`tasks=1 buffers=3 patches=3`).
- Host `--validate-only` (same pinned bytes): 4/4 `OK`.
- Board `--validate-only` (same staged runner): 4/4 OK plus the control
  `tasks=2 buffers=6 patches=6`.
- Staged files: 40/40 sha256-identical on host and board.
- Runner sha256 on host and board:
  `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`
  (`rocket_run.py`; `runner/pinned/` was empty).

## Execution

One `flock -x -w 900 /home/opencode-agent/rk3588-npu.lock` invocation enclosed
all five submits, strictly sequential:

1. `diag_grouped_task0`
2. `diag_grouped_task1`
3. `diag_splitoc_task0`
4. `diag_splitoc_task1`
5. control: original grouped two-task job

Lock acquired `2026-11-05T21:14:24Z`, released `21:14:27Z`, holder PID
3643420, inner PID 3643421, `/proc/locks` inode `134534`, runner exit 0.
Pre-lock and in-lock `pgrep -af 'rk3588|rocket|capture|python3'` showed only
`supervisord` and the wrapper/flock itself. No other capture worker was
present. No retries and no reset.

## Results

All five `submit_ret` values were `0`; all captures have `status: OK`,
`errors: []`, `cleanup_errors: []`.

Comparison applies the manifest NC1HWC2 unpack to the readback BO and compares
the defined `out_c * out_h * out_w` elements bitwise with the original
`expected_out0.bin` / `expected_out1.bin` oracle. Bytes outside the defined
layout are not pass/fail data.

| case | buffer | submit_ret | BO bytes | BO all zero | defined elems | exact bit mismatches | over atol 0.2 | max abs diff |
|---|---|---:|---:|---|---:|---:|---:|---:|
| `diag_grouped_task0` | out0 | 0 | 768 | no | 36 | 0/36 | 0/36 | 0.0 |
| `diag_grouped_task1` | out1 | 0 | 768 | no | 36 | 0/36 | 0/36 | 0.0 |
| `diag_splitoc_task0` | out0 | 0 | 3328 | no | 392 | 0/392 | 0/392 | 0.0 |
| `diag_splitoc_task1` | out1 | 0 | 3328 | no | 392 | 0/392 | 0/392 | 0.0 |
| control grouped, task 0 | out0 | 0 | 768 | no | 36 | 0/36 | 0/36 | 0.0 |
| control grouped, task 1 | out1 | 0 | 768 | **yes** | 36 | **36/36** | **34/36** | **11.9375** |

- Every single-task output, including both task-1 derivations, is an exact
  bit-for-bit match of its oracle and passes `atol=0.2`.
- The control reproduces the original failure exactly: `out1` is 768 zero
  bytes, sha256
  `ef115a0e0c15cdc41958ca46b5b14b456115f4baec5e3ca68599d2a8f435e3b8`,
  identical to the original `conv-fp16` run's zero `out1`; the control
  `out0` remains exact.
- The control capture has both task descriptors (`regcmd_dma` 0 and 432),
  54 words each, and both patches applied to `a1/w1/out1`, yet the second
  output BO remains entirely zero; no task-1 writes are visible.
- Board and host copies of the complete output tree re-hash identically;
  staged bundles are unchanged after execution.

## Root cause

The task-1 command stream, inputs, patches and terminal tail are valid: the
identical 54-QWORD slice run as a one-task job at offset 0 produces the exact
expected output for both multi-task cases. The failure is therefore in the
Rocket multi-task job path: when the same task is submitted as task index 1 in
a two-task job, its output BO remains zero and no task-1 writes are visible.

The pinned runner's two-task descriptor array is consistent with the UAPI
(`regcmd_dma` 0/432, 54 QWORDs each, both outputs in the out-handle list), and
the patched command BO contains the task-1 commands. The v6.18 UAPI in fact
documents that "All tasks in the same job will be executed sequentially on the
same core"; this board does not honor that for the second task. The failure is
downstream of bundle encoding, in the kernel driver's multi-task
execution/chaining.

A timing observation is consistent with the mainline driver's 500 ms job
timeout: the output `PREP_BO` wait was ~508–516 ms for every case in this run,
close to `JOB_TIMEOUT_MS = 500`. In Linux v6.18 `rocket_job.c`
(`https://raw.githubusercontent.com/torvalds/linux/v6.18/drivers/accel/rocket/rocket_job.c`),
the next task is only submitted from the completion IRQ handler
(`rocket_job_handle_irq()` calls `rocket_job_hw_submit()`); if that
IRQ/chaining does not occur and the job is completed by the scheduler
timeout/reset path instead, task 1 is never submitted and its fresh output BO
stays zero. This mechanism is inferred from the timing and the v6.18 source
path; it is not proven on this board because `dmesg`/journal access is
restricted (no `sudo` was used). The empirical result does not depend on that
inference: multi-task jobs fail, one-task jobs pass.

**Conclusion: the Rocket multi-task job path is the issue. Multi-task bundles
must be split into separate one-task jobs; the task streams themselves are
correct. No FPGA execution is claimed.**

## Evidence

- `board-out/` – raw board readbacks and `capture.json` for all five cases
- `host-analysis/comparison_summary.json` – per-buffer exact/atol comparison
- `hash-board-out.sha256`, `hash-board-out-final.sha256` – readback hashes
- `hash-board-bundles-after.sha256`, `hash-host-bundles-after.sha256` – staged
  bundle integrity after the run
- `board-runner.log` – lock/pgrep/runner console log
- `build/rk3588-example-captures/conv-fp16-task-diagnostic/host-analysis/` –
  host validation logs, derivation hashes, staging hash lists
- `build/rk3588-example-captures/conv-fp16-task-diagnostic/tools/make_derived.py`
  – reproducible derivation script (read-only over the originals)
- `build/rk3588-example-captures/conv-fp16-task-diagnostic/tools/run_locked.sh`
  – the single locked invocation

Tool/source identity: host revision
`f9b00d8f9a48ab4dea20cb30148890cd9f1443ee`; no tracked source, test or doc was
modified. This is an RK3588 mainline Rocket capture result, not FPGA execution.
