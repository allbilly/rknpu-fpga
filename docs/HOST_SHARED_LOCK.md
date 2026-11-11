# Shared heavy-job lock protocol (FPGA verification + TPU/openTPU/ladder work)

This laptop hosts at least two active projects: the `rknpu-fpga` verification
queue and the TPU/OpenTPU/ladder workstreams. Its cooling is marginal, so only
one heavy job can run at a time, with a sustained cool-down gate.

## The contract

1. **One lock file**: `/tmp/rknpu-heavy.lock` (kernel `flock`, FIFO fairness).
   Every heavy job from **every** project takes it for its whole duration.
2. **One shared gate wrapper**: `/tmp/rknpu-heavy-gate.sh`
   (symlink to `build/verif/host_guard/heavy_gate.sh` in this repo).
   It takes the lock, waits until **5 consecutive Tctl samples < 72 °C**, pins
   the job to a small CPU set, applies an optional CPU quota, logs to
   `/tmp/rknpu-heavy-gate.log`, runs the command, and logs the exit status.
3. **Thermal guard**: `host_guard.py` (v4.3 for now: sustained median 97 °C,
   instant 104 °C, streak 2×≥101 °C) is the last-resort protector. It kills
   only *active CPU burners*; a queued waiter is never killed.
4. **No pausing/killing of the other project's jobs** when both sides use the
   lock — exclusivity and cooling are enforced by the lock + gate. The
   `foreign_hold.sh` wrapper (SIGSTOP of known foreign trees during a
   verification window and resume on exit) remains only as a fallback for
   loads that bypass the lock; it is never used when the other project is
   queueing through the shared gate.
5. Run **short jobs** where possible; long jobs should be started only when the
   host is cool and the other project has no queued job. The gate logs
   `/tmp/rknpu-heavy-gate.log` is the shared record.

## Recommended usage

TPU/openTPU/ladder (and any other project):

```sh
/tmp/rknpu-heavy-gate.sh <command> [args...]
# e.g.
GRATE_CPUS=4-7 GRATE_QUOTA=200 /tmp/rknpu-heavy-gate.sh make -C build synth
```

rknpu-fpga verification shortcuts (already integrated):

```sh
BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=50 \
  build/verif/host_guard/safe_run.sh <command>
```

`safe_run.sh` uses the same `/tmp/rknpu-heavy.lock` and the same sustained
cool-down gate, so the two wrappers interoperate directly.

## Environment knobs (shared gate)

| Variable | Default | Meaning |
|---|---|---|
| `GRATE_LOCK` | `/tmp/rknpu-heavy.lock` | lock path |
| `GRATE_CPUS` | `0-1` | `taskset` CPU set |
| `GRATE_QUOTA` | unset | systemd `CPUQuota` percent (total per scope) |
| `GRATE_LAUNCH_C` | `72` | cool-down threshold (°C), 5 consecutive samples |
| `GRATE_LOCK_WAIT` | `9000` | seconds to wait for the lock |
| `GRATE_WAIT_MAX` | `1800` | seconds to wait for cooldown |

## Fairness / conflict resolution

- The lock is FIFO: whoever queued first runs next.
- If a project bypasses the gate, the thermal guard may kill its active
  processes at the emergency thresholds, and the verification side may fall
  back to `foreign_hold.sh` (SIGSTOP/resume) for its windows.
- Both projects should prefer many short jobs to one long one on this host,
  because sustained one-core work is already near the thermal limit.
