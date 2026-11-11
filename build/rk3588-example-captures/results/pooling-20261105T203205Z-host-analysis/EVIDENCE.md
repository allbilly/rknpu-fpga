# Pooling capture run evidence — RUN_ID 20261105T203205Z

## Board identity

- hostname: `orangepi5`
- kernel: `6.18.24-current-rockchip64 #2 SMP PREEMPT Wed Apr 22 11:22:34 UTC 2026 aarch64`
- OS: `Armbian 26.8.3 resolute` (`Ubuntu 26.04`)
- Python: `Python 3.14.4`
- device: `/dev/accel/accel0`, `crw-rw---- root render 261,0`
- board compatible (capture.json): `xunlong,orangepi-5`, `rockchip,rk3588s`
- sysfs device: `/sys/devices/platform/rknn`

## Runner

- board runner: `/home/opencode-agent/rk3588-example-captures/queue-pooling-20261105T203205Z/runner/rocket_run.py`
- runner version: `1.0.0`
- runner sha256 used for validation and execution:
  `824f129261a2a0337b3da6720a46d1f9cff23e5d31efff9a0fa085f72f1b43cf`
- every capture.json records the same `tool.sha256`.
- host copy staged and hash-verified before execution; board copy hash-verified again.
- NOTE: the working-tree `build/rk3588-example-captures/runner/rocket_run.py`
  changed on the host at `2026-11-06 04:32:51 +0800` (during the board run) to
  sha256 `a51de01f1b8da29e17142ec93f02995ba3a6187e6603a5a64f386d1ab3ab26cd`.
  That newer file was **not** used. The staged/board copy remained the pinned
  824f... file, which is the version validated and run. This is an external
  edit to an ignored build artifact, not a change made by this run.

## Unique paths

Board:

- queue / staged bundles:
  `/home/opencode-agent/rk3588-example-captures/queue-pooling-20261105T203205Z/`
- fresh run output root:
  `/home/opencode-agent/rk3588-example-captures/runs/20261105T203205Z/pooling/`
- run logs:
  `/home/opencode-agent/rk3588-example-captures/runs/20261105T203205Z/logs/`
- lock file: `/home/opencode-agent/rk3588-npu.lock`

Host:

- copied board run tree:
  `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/pooling-20261105T203205Z/`
- host comparison:
  `/home/fedora/rknpu-fpga/build/rk3588-example-captures/results/pooling-20261105T203205Z-host-analysis/`

Aborted preflight (no submit, no lock acquisition, no output directory) used
`RUN_ID 20261105T202953Z` and left only
`/home/opencode-agent/rk3588-example-captures/runs/20261105T202953Z/logs/pgrep-before.txt`.
Its failure was a self-match in the pgrep self-exclusion: the script path
contains `rk3588-example-captures`, so its own `bash .../run_pooling.sh`
process was flagged. It exited 99 before the lock and before opening the
device.

## Serialization

Single invocation of the generic runner, whole 19-case queue, one exclusive
lock:

```
flock -x -w 900 /home/opencode-agent/rk3588-npu.lock
```

- `lock_wait_start`: `2026-11-05T20:32:42Z`
- `lock_acquired`:  `2026-11-05T20:32:42Z` (no wait)
- `runner_exit`:    `0`
- `lock_release`:   `2026-11-05T20:32:52Z`

Strictly sequential; one submit process; no retries; no reset; no FPGA
programming or flashing.

## Race checks

External check before staging (2026-11-05T20:32:16Z):
only `/usr/bin/python3 /usr/bin/supervisord` matched the `python3` alternative;
no capture/rocket worker.

Run-script check before submit (2026-11-05T20:32:42Z), after excluding
supervisord and this run's own unique queue path:
`PGREP_CLEAN: no other capture worker`.

Final check after copy-back: only `supervisord` and an unrelated
`/snap/microk8s/.../run-lifecycle-hooks.py reconcile` process matched
`python3`; no `/dev/accel` capture worker. The board tree hash was re-checked
afterward and was unchanged.

## Results

- READY cases run: 19 / 19.
- BLOCKED probes (`int32_max_k2s2_zero_write_c4_h2w2`,
  `fp32_max_k2s2_zero_write_c4_h2w2`): not staged, not submitted, absent from
  the output tree.
- `submit_ret == 0` for all 19; `status == OK` for all 19; no runner errors or
  cleanup errors.
- 19 output BOs read back in full: 19 x 4096 = 77,824 bytes.
- Every returned `out.bin` is byte-identical to its `expected.bin` over the
  full 4096-byte BO (0 mismatching bytes in value region, declared region and
  full buffer).
- FP16 average cases (4): exact value-region equality and
  `max|diff| = 0.0`, so the manifest `atol=0.0625` comparison passes trivially.
- Index case (`fp16_max_k2s2_index_c8_h2w2`): values and uint16 positions
  exact, including the index gap at bytes 16..31 remaining zero.
- Padded cases (4): declared output region exact; padding is baked into the
  oracle values; undeclared bytes after `logical_output_bytes` are zero and
  reported separately.
- Board run tree: 40 files (19 capture.json + 19 out.bin + 2 logs), board and
  host SHA-256 lists identical.
- Tracked source/tests/docs were not modified and nothing was committed.
