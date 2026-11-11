#!/bin/bash
set -u
RUN_ID=20261105T205900Z
B=/home/opencode-agent/rk3588-example-captures
RUNNER="$B/tools-conv-fp16-$RUN_ID/rocket_run-a51d.py"
QUEUE="$B/queue-conv-fp16-$RUN_ID/conv-fp16"
OUT="$B/runs/$RUN_ID/conv-fp16"
LOCK=/home/opencode-agent/rk3588-npu.lock
LOG="$B/runs/$RUN_ID/runner.log"
mkdir -p "$B/runs/$RUN_ID"
export LOCK_INO
LOCK_INO=$(stat -c %i "$LOCK")

{
  echo "run_id=$RUN_ID"
  echo "wrap_start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "runner=$RUNNER"
  echo "queue=$QUEUE"
  echo "out=$OUT"
  echo "lock=$LOCK inode=$LOCK_INO"
  echo "pre_lock_pgrep:"
  pgrep -af 'rk3588|rocket|capture|python3' || true
} > "$LOG" 2>&1

start_epoch=$(date +%s)
flock -x -w 900 "$LOCK" bash -c '
  echo "lock_acquired_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
  echo "lock_holder_inner_pid=$$" >&2
  grep -F ":$LOCK_INO " /proc/locks >&2 || echo "lock_line_not_found" >&2
  exec python3 "$1" --device /dev/accel/accel0 --out "$2" "$3"
' bash "$RUNNER" "$OUT" "$QUEUE" >> "$LOG" 2>&1
rc=$?
end_epoch=$(date +%s)

{
  echo "lock_released_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "runner_exit=$rc"
  echo "elapsed_s=$((end_epoch - start_epoch))"
  echo "post_run_pgrep:"
  pgrep -af 'rk3588|rocket|capture|python3' || true
} >> "$LOG" 2>&1

cat "$LOG"
exit "$rc"
