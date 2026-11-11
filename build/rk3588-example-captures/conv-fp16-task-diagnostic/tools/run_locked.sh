#!/bin/bash
# Diagnostic wrapper: one exclusive flock encloses all five submits.
set -u
RUN_ID=20261105T211500Z
B=/home/opencode-agent/rk3588-example-captures
BASE="$B/runs/$RUN_ID/conv-fp16-task-diagnostic"
RUNNER="$BASE/rocket_run-a51d.py"
OUT="$BASE/out"
LOCK=/home/opencode-agent/rk3588-npu.lock
LOG="$BASE/runner.log"

CASES=(
  "$BASE/bundles/diag_grouped_task0"
  "$BASE/bundles/diag_grouped_task1"
  "$BASE/bundles/diag_splitoc_task0"
  "$BASE/bundles/diag_splitoc_task1"
  "$BASE/bundles/control_conv_grouped_3x3_c4_h5_w5_oc8_g2"
)

mkdir -p "$BASE"
export LOCK_INO
LOCK_INO=$(stat -c %i "$LOCK")

{
  echo "run_id=$RUN_ID"
  echo "wrap_start_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "runner=$RUNNER"
  echo "runner_sha256=$(sha256sum "$RUNNER" | cut -d' ' -f1)"
  echo "out=$OUT"
  echo "lock=$LOCK inode=$LOCK_INO"
  echo "case_order:"
  printf '  %s\n' "${CASES[@]}"
  echo "pre_lock_pgrep:"
  pgrep -af 'rk3588|rocket|capture|python3' || true
} > "$LOG" 2>&1

start_epoch=$(date +%s)
flock -x -w 900 "$LOCK" bash -c '
  echo "lock_acquired_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
  echo "lock_holder_inner_pid=$$" >&2
  grep -F ":$LOCK_INO " /proc/locks >&2 || echo "lock_line_not_found" >&2
  echo "in_lock_pre_submit_pgrep:" >&2
  pgrep -af "rk3588|rocket|capture|python3" >&2 || true
  exec python3 "$1" --device /dev/accel/accel0 --out "$2" "${@:3}"
' bash "$RUNNER" "$OUT" "${CASES[@]}" >> "$LOG" 2>&1
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
