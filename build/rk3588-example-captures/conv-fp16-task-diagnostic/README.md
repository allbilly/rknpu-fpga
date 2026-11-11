# conv-fp16 task diagnostic

Derived one-task bundles for the `conv-fp16` two-task zero-output diagnosis.

- `bundles/` – four derived one-task bundles (grouped task0/task1, split-OC
  task0/task1), generated from the originals by `tools/make_derived.py`.
- `tools/run_locked.sh` – the single `flock` invocation that ran all four
  derived cases plus the original grouped two-task control.
- `stage/20261105T211500Z/` – exact host staging tree copied to the board.
- `host-analysis/` – host validation logs, staging hash lists and hashes.

Board results and the full report are in:

`build/rk3588-example-captures/results/conv-fp16-task-diagnostic-20261105T211500Z/`

Result: every derived one-task case (including both task-1 cases) matched the
oracle exactly; the grouped two-task control reproduced the all-zero task-1
output. The Rocket multi-task job path is the issue; multi-task bundles must be
split into separate one-task jobs. This is RK3588 mainline Rocket NPU data, not
FPGA execution.
