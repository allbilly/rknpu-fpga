# Board session runbook — volatile FPGA session on the YPCB card

Operator-facing, copy-paste runbook for the last-mile FPGA session: load one
emitted image into the XC7K480T volatile SRAM, verify it, run that family's
host replay, capture evidence, and switch images safely.

Companion documents (authoritative details, keep open):

- `docs/BOARD_RUN_PREP.md` — audited procedure §5 (read-only target audit),
  §6 (volatile JTAG programming), §7 (DLC10 init), §8 (harness commands),
  §9 (evidence), §15–§17 (multi-image deployment, class-D, checklist).
- `docs/HOST_SHARED_LOCK.md` — shared heavy-job lock/thermal protocol.
- `docs/HOST_JTAG_BRAM.md` — EW BRAM ABI and the recorded 2026-10-27 physical
  EW session this runbook's EW path follows.

Status of this document: **operator draft, file-only, written 2026-11-10. No
hardware was accessed while writing it; the DLC10 cable is absent on the
authoring host.** The session may start only when every precondition in §1 is
satisfied and the user's authorization is explicit. Nothing in this runbook
may be executed before that.

Two evidence levels are kept separate (same convention as `BOARD_RUN_PREP.md`):

1. **Live RK3588 differential (P0/P1)** — real RK3588 silicon, no FPGA image
   loaded. Already complete: 38/38 READY cases (§16.1 of the prep doc).
2. **FPGA-board run (this runbook)** — one volatile image loaded on the YPCB
   card through the DLC10. It has never happened; this runbook is the plan.

## 0. Session quick facts

| Item | Six-page image (primary/ready path) | EW image (separate, currently gated) |
|---|---|---|
| Purpose | conv-simple p0–p3, one INT8 max pooling case, 4 GEMM shapes, conv FP32 p3, conv k5/C16 pages | ew-fp16 (ADD/SUB/MUL/NEG/MAX/FDIV), `simple_add`, `fdiv-systematic` |
| Bitstream | `build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit` | `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit` |
| Size | 18,735,215 bytes | 18,735,213 bytes |
| SHA-256 | `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` | `b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a` |
| Top | `ypcb_jtag_dual_top` | `ypcb_jtag_ew_top` |
| On-chip source tag | **none** (untagged) → `--source-tag none` | **`USR_ACCESS=ec9ecd41`** → `--source-tag ec9ecd41` |
| Transport / harness | `tools/host/run_jtag_dual_hardware.py` (USER2 640-bit mailbox, modes 0–6) | **pinned wrapper** `tools/host/run_jtag_ew_hardware.py` (USER2 mailbox + RKEW BRAM ABI 1 MiB at `0x10000000`; raw captured-BO replay, complete-BO compare before ACK, E1 negative; offline `--check`) |
| Admission | image receipt `PASS`; no review blocker | `SOURCE_INTACT_REVIEW_PENDING` — human board reviewer must sign (`Missing board reviewer`) |
| Current session status | **READY** once cable + user authorization exist | **BLOCKED on human board review only** (wrapper pinned; `--check` = `PASS_CHECK_PENDING_ADMISSION`); per-family authorization still separate |
| Expected first evidence | harness receipt with modes 1–6 + mode 0, complete 4096-byte BO compares | wrapper receipt with 9 per-case complete-BO receipts (872,448 bytes total) + E1 negative |

Not part of this session: the pooling-corpus image (task-10, no emitted
bitstream yet) and conv-fp16/ew-int families (no image page). Live RK3588
differentials are not repeated here.

## 1. Preconditions — do not start until every box is checked

### 1.1 User authorization (blocking)

- The user must explicitly authorize: (a) the volatile JTAG load of the
  **exact image SHA-256** for this session, (b) the host replay for that
  family, (c) each image switch as a **separate** volatile load.
- Copy the user's wording verbatim; it goes into the receipt and the program
  Tcl note. Template:
  `User authorized volatile JTAG load of <SHA> and host run on <date>: "<exact words>"`
- The permission boundary is fixed: **volatile SRAM only**. No flash, no
  boot-mode change, no persistent configuration, no card reset beyond the
  programming operation itself.
- Per-family: six-page session and EW session are two separate authorizations
  and two separate loads (no warm switching, no mixed evidence).
- If the user has not authorized yet: stop. Everything up to and including
  the read-only preflight/audit is safe, but do not program.

### 1.2 Audited board identity

The target must be the same inspected card. Expected values (prior audited
evidence, re-read in §3 step 1):

| Field | Expected |
|---|---|
| Cable URI | `localhost:3125/xilinx_tcf/Xilinx/80802026a77a01` |
| Cable | one Xilinx Platform Cable USB II (DLC10), `03fd:0008` operational |
| Raw IDCODE | `0x23751093` (XC7K480T) |
| Part | `xc7k480tffg1156-2` |
| DNA port | `004E544714C705C` |
| Device count | exactly one FPGA on the chain (Inspur CPLD `0x10931093` precedes it) |

If any value differs: **stop** — wrong target. Do not "try anyway".

### 1.3 Electrical / board facts (user decisions)

| Fact | Status | What the operator does |
|---|---|---|
| `CONFIG_VOLTAGE 1.8` / `CFGBVS GND` | donor-derived + build-owner attested for the six-page build; **not a strap measurement**; the EW emission enforces the same pair at implementation | user confirms; record in session meta. Wrong bank setting is the one failure mode that can leave the card unbootable |
| LED polarity (`LED_ACTIVE_LOW`) | six-page image built with `0` (attested/log); EW receipt does not record its value; optical polarity unmeasured | user/reviewer accepts/records; LEDs are status-only and do not assert workload PASS |
| Flash | untouched and must stay untouched | never use `-b`/`-f`/`--fpga-part`, `flash_jtag.sh program`, `boot_hw_device`, `openFPGALoader --flash` |
| Card state | prior volatile images may be in SRAM; this session replaces them by design | record what was loaded before (if known), otherwise "unknown; volatile replaced" |

### 1.4 Cable and tools

```sh
# exactly one cable; before init it enumerates as 03fd:0013, after init 03fd:0008
lsusb -d 03fd:
lsusb -d 03fd:0013
lsusb -d 03fd:0008      # expect empty before cable-init, one line after

# no cable tool may hold the device
pgrep -x hw_server; pgrep -x openFPGALoader; pgrep -x xsdb; pgrep -x fxload

# required host tools
command -v python3 lsusb ss flock sha256sum
ls -l /home/fedora/vivado/2026.1/Vivado/bin/vivado
ls -l /home/fedora/vivado/2026.1/Vivado/bin/hw_server
```

If the cable is at `03fd:0013` (pre-firmware), initialize the cable RAM only:

```sh
cd ~/ypcb && bash dlc10-init.sh
# expect: final line "PASS: DLC10 initialized and YPCB XC7K480T detected without Vivado."
#         detection log contains "idcode 0x23751093"
#         lsusb -d 03fd:0008 shows exactly one Platform Cable USB II
```

### 1.5 Lease, lock and heavy-job policy

- The **board** is protected by the shared JTAG lease
  `/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock`. Every operation
  that opens the cable (target audit, load) must hold it with a nonblocking
  exclusive `flock` for its whole duration; stop the owned `hw_server` before
  releasing. The six-page harness takes the lease itself — do not hold the
  lease in your shell while running the harness, or it will refuse.
- The **host** is protected by the heavy-job protocol in
  `docs/HOST_SHARED_LOCK.md` (`/tmp/rknpu-heavy.lock` + thermal gate). This
  FPGA session is not a heavy job and does not take that lock, but:
  **do not start synthesis/builds/simulations during the session**, and do not
  bypass the heavy gate for anything else. A thermal event or a killed host
  loses evidence. Start the session when the host is cool and no heavy job is
  queued; if the heavy queue is active, coordinate with the Lead for a quiet
  window.

### 1.6 Go/No-Go preflight (read-only)

```sh
cd /home/fedora/rknpu-fpga
mkdir -p build/board-prep
python3 tools/host/jtag_preflight.py \
  --out "build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-session-preflight"
```

GO only if **all** hold:

- exit code `0`, `status=PASS_PREFLIGHT_READY`;
- `cable_stage=initialized` (one `03fd:0008`), no ambiguity;
- no `hw_server`, no controller process; ports 3121/3122/3125/3721/3741 closed;
- shared lease `held: false`;
- `~/ypcb/dlc10-init.sh` prerequisites OK;
- catalog shows the exact image and SHA you intend to load.

Any other output: follow §9 decision tree. **Do not program on a No-Go.**

## 2. Evidence layout for the session

Use one fresh session root; never overwrite a previous session:

```sh
export SESSION="/home/fedora/rknpu-fpga/build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-board-session"
mkdir -p "$SESSION"/{preflight,target-audit,load-src,load-dst,replay}
export SESSION_META="$SESSION/session-meta.txt"
{
  echo "session_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "operator=${USER:-unknown}"
  echo "authorization=<copy the user's exact wording here>"
  echo "target=localhost:3125/xilinx_tcf/Xilinx/80802026a77a01"
  echo "lease=/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock"
  echo "expected_idcode=23751093 expected_dna=004E544714C705C"
  echo "board_config_voltage=1.8 board_cfgbvs=GND (user-confirmed: yes/no)"
  echo "led_active_low=<0 or 1, source>"
} | tee "$SESSION_META"
sha256sum "$SESSION_META" | tee "$SESSION/session-meta.sha256"
```

Keep: preflight receipt, target-audit TSV/device-properties, load TSV and
Vivado log, harness/replay receipts and complete-BO readbacks, every log, and
a final `SESSION-REPORT.md` + `session-manifest.sha256`. Do **not** delete a
failing session: a failure is evidence.

## 3. Shared load procedure (both images)

The two images use the same audited program Tcl pattern from
`docs/BOARD_RUN_PREP.md` §6A; only three variables change: bitstream path,
expected `USR_ACCESS`, and the session/load directory. The block holds the
shared lease, starts an **owned** `hw_server`, renders and runs the audited
Tcl, verifies the receipt, then stops the server and releases the lease.

Copy the whole block into one shell so `flock`/`trap` stay attached to it.

### 3.1 Six-page image variables (READY path)

```sh
export IMAGE_KIND=six-page
export BIT=/home/fedora/rknpu-fpga/build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit
export EXPECTED_ACCESS=00000000        # six-page image is untagged
export EXPECTED_BIT_SHA=81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39
```

### 3.2 EW image variables (currently blocked — see §5.1 first)

```sh
export IMAGE_KIND=ew
export BIT=/home/fedora/rknpu-fpga/build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit
export EXPECTED_ACCESS=ec9ecd41        # EW emission sets USR_ACCESS=ec9ecd41
export EXPECTED_BIT_SHA=b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a
```

### 3.3 Load block (run after setting 3.1 or 3.2)

```sh
set -euo pipefail
export LOCK=/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock
export VIVADO=/home/fedora/vivado/2026.1/Vivado/bin/vivado
export HWSERVER=/home/fedora/vivado/2026.1/Vivado/bin/hw_server
export TARGET=localhost:3125/xilinx_tcf/Xilinx/80802026a77a01
export LOAD="$SESSION/load-$IMAGE_KIND"
mkdir -p "$LOAD"

# 0) exact bitstream + authorization sanity
sha256sum "$BIT" | tee "$LOAD/bitstream.sha256"
[ "$(sha256sum "$BIT" | cut -d' ' -f1)" = "$EXPECTED_BIT_SHA" ] || { echo "REFUSED: bitstream SHA mismatch"; exit 1; }
grep -q "authorization=" "$SESSION_META" || { echo "REFUSED: no session authorization record"; exit 1; }
grep -q "authorization=<copy" "$SESSION_META" && { echo "REFUSED: replace the authorization placeholder with the user's exact wording"; exit 1; }

# 1) shared board lease for the whole load; no other cable controller
exec 9>"$LOCK"
flock -n 9 || { echo "REFUSED: shared JTAG lease busy"; exit 1; }
if pgrep -x hw_server >/dev/null; then echo "REFUSED: another hw_server is running"; exit 1; fi
if pgrep -x openFPGALoader >/dev/null; then echo "REFUSED: openFPGALoader is running"; exit 1; fi

# 2) render the audited program Tcl (same template as BOARD_RUN_PREP.md §6A)
python3 - "$LOAD" "$BIT" "$EXPECTED_ACCESS" "$TARGET" <<'PY'
from pathlib import Path
import sys
load, bit, access, target = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
template = Path('/home/fedora/rknpu-fpga/verification/runs/2026-10-27-host-user2-fpga/'
                'hardware/program-template.tcl.in').read_text()
values = {
    '@TARGET@': '{' + target + '}',
    '@BITSTREAM@': '{' + bit + '}',
    '@RECEIPT@': '{' + str(load / 'program.tsv') + '}',
    '@USR_ACCESS@': access,
}
for marker, value in values.items():
    assert template.count(marker) == 1, marker
    template = template.replace(marker, value)
(load / 'program.tcl').write_text(template)
sha = __import__('hashlib').sha256((load / 'program.tcl').read_bytes()).hexdigest()
(load / 'program-tcl.sha256').write_text(sha + '  program.tcl\n')
print('rendered', load / 'program.tcl', 'sha256', sha)
PY

# 3) owned hw_server + audited load
"$HWSERVER" -s tcp::3125 >"$LOAD/hw-server.log" 2>&1 & HW_PID=$!
trap 'kill "$HW_PID" 2>/dev/null || true; exec 9>&-' EXIT
for i in $(seq 1 300); do
  if (exec 3<>/dev/tcp/127.0.0.1/3125) 2>/dev/null; then break; fi
  sleep 0.1
done
PROGRAM_RC=0
"$VIVADO" -mode batch -nojournal -nolog -source "$LOAD/program.tcl" >"$LOAD/vivado.log" 2>&1 || PROGRAM_RC=$?

# 4) stop the owned server, release the lease
kill "$HW_PID" 2>/dev/null || true
wait "$HW_PID" 2>/dev/null || true
trap - EXIT
exec 9>&-
echo "program rc=$PROGRAM_RC (expect 0 and PASS_HOST_USER2_VOLATILE_SRAM_PROGRAM)"
cat "$LOAD/program.tsv"
```

### 3.4 Acceptance check for the load (must PASS before any replay)

```sh
python3 - "$LOAD/program.tsv" "$EXPECTED_ACCESS" "$IMAGE_KIND" <<'PY'
from pathlib import Path
import sys
rows = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if line.strip():
        key, _, value = line.partition('\t')
        rows[key] = value
expected = {
    'DNA_PORT': '004E544714C705C',
    'TCK_HZ': '3000000',
    'IDCODE_BEFORE': '23751093',
    'IDCODE_AFTER': '23751093',
    'INIT_COMPLETE': '1',
    'DONE': '1',
    'USR_ACCESS': sys.argv[2].lower(),
    'PROGRAMMED': '1',
    'CLEANUP': '1',
    'PASS': '1',
}
problems = [f'{k}: got {rows.get(k)!r} expected {v!r}'
            for k, v in expected.items() if rows.get(k, '').lower() != v.lower()]
if not rows.get('TARGET', '').startswith('localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'):
    problems.append(f"TARGET: {rows.get('TARGET')!r}")
if problems:
    print('FAIL_LOAD', sys.argv[3]); [print(' -', p) for p in problems]; raise SystemExit(1)
print('PASS_LOAD', sys.argv[3], 'INIT=1 DONE=1 USR_ACCESS=' + sys.argv[2])
print('artifacts:', Path(sys.argv[1]).parent)
PY
grep -q 'PASS_HOST_USER2_VOLATILE_SRAM_PROGRAM' "$LOAD/vivado.log" || { echo "FAIL: missing program PASS marker"; exit 1; }
sha256sum "$LOAD/program.tsv" "$LOAD/vivado.log" "$LOAD/hw-server.log" "$LOAD/program.tcl" \
  | tee "$LOAD/artifacts.sha256"
```

Only after `PASS_LOAD` may the replay step run. The load is volatile; the card
has no persistent state from it.

## 4. Six-page replay session (modes 0–6)

The load block (§3.1 + §3.3 + §3.4) has already stopped its `hw_server` and
released the lease. The harness now takes the lease itself.

### 4.1 Offline check first (no hardware)

```sh
cd /home/fedora/rknpu-fpga
python3 tools/host/run_jtag_dual_hardware.py --check \
  --image 81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock \
  --out "$SESSION/offline-check-sixpage"
# expect exit 0, "PASS YPCB_JTAG_DUAL_HARDWARE --check ...", modes 0-6
```

### 4.2 Hardware replay (modes 1–6 then mode 0)

```sh
cd /home/fedora/rknpu-fpga
python3 tools/host/run_jtag_dual_hardware.py \
  --authorized \
  --authorization-note "$(sed -n 's/^authorization=//p' "$SESSION_META")" \
  --image 81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock \
  --source-tag none \
  --mode 1 --mode 2 --mode 3 --mode 4 --mode 5 --mode 6 --mode 0 \
  --out "$SESSION/replay-sixpage"
```

Expected: one `PASS YPCB_JTAG_DUAL_HARDWARE mode=<n> frames=<f>` line per mode
(1–6 then 0), a final `PASS ... flash_written=false`, and exit 0. Mode 0 always
runs last because its unmapped-page check deliberately quarantines the
mailbox.

### 4.3 Acceptance check for the six-page session

```sh
python3 - "$SESSION/replay-sixpage/receipt.json" <<'PY'
import json, sys
from pathlib import Path
receipt = Path(sys.argv[1]); r = json.loads(receipt.read_text())
must_false = ('fabric_programmed', 'fabric_reset', 'configuration_written',
              'flash_written', 'image_loaded_by_this_tool')
problems = []
if r.get('status') != 'PASS': problems.append(f"status={r.get('status')} failure={r.get('failure')}")
if r.get('hardware_accessed') is not True: problems.append('hardware_accessed is not true')
for key in must_false:
    if r.get(key) is not False: problems.append(f'{key}={r.get(key)}')
if r.get('modes') != [1, 2, 3, 4, 5, 6, 0]: problems.append(f"modes={r.get('modes')}")
for mode in (1, 2, 3, 4, 5, 6):
    p = receipt.parent / f'mode-{mode}.json'
    mr = json.loads(p.read_text())
    if mr.get('status') != 'PASS': problems.append(f'mode {mode} status={mr.get("status")}')
    if not (mr.get('compare') or {}).get('passed'): problems.append(f'mode {mode} compare not passed')
    if (mr.get('compare') or {}).get('words') != 1024: problems.append(f'mode {mode} did not read the complete 4096-byte BO')
    if not (mr.get('ack') or {}).get('completion_cleared'): problems.append(f'mode {mode} ACK did not clear')
    if not all(load.get('readback_matches') for load in mr.get('loads', [])): problems.append(f'mode {mode} BO loadback mismatch')
m0 = json.loads((receipt.parent / 'mode-0.json').read_text())
if not m0.get('quarantine_observed'): problems.append('mode 0 did not observe the expected status-7 quarantine')
cleanup = r.get('cleanup') or {}
if not cleanup.get('bridge_quit_ack'): problems.append('bridge did not acknowledge QUIT')
if cleanup.get('owned_hw_server_exit') not in (0, -15, -9, None): problems.append('owned hw_server did not stop cleanly')
print('FAIL_SESSION' if problems else 'PASS_SESSION', 'six-page')
[print(' -', p) for p in problems]
print('receipt:', receipt)
raise SystemExit(1 if problems else 0)
PY
```

The harness receipt records per-mode frames, result tag/tasks/error code,
`compare.differing_words`/`worst_abs`, BO loadback hashes, ACK clearing, bridge
log hashes and cleanup. Keep the whole `replay-sixpage/` directory.

### 4.4 After mode 0

Mode 0 ends with the bridge in QUARANTINE by design. The fabric stays
quarantined until a new configuration: **reload the image (§3) before any
further mailbox work**, even after restarting `hw_server`. A new
`hw_server`/TAP reset wrinkle does not clear the bridge.

## 5. EW replay session (separate load; one blocker left)

The EW replay wrapper is now **pinned** at
`tools/host/run_jtag_ew_hardware.py` (Lead-approved basis: the archived audited
raw-command pattern `verification/runs/2026-10-27-host-user2-fpga/hardware/{run_sram_tests.py,run_jobs.py}`
+ `tools/host/transport.py` / `native_link.py` + `tools/dma_fixtures.py`). It
mirrors the dual harness discipline: exact EW image SHA and
`USR_ACCESS=ec9ecd41` binding, audited target/DNA/INIT/DONE checks, owned
`hw_server` + native bridge, raw captured-BO upload, complete owned-BO compare
before ACK, E1 negative, fail-closed gates, and an offline `--check`.

Remaining blockers before an EW load:

1. **Board admission (human gate, separate)**: `tools/host/prepare.py verify`
   currently returns `SOURCE_INTACT_REVIEW_PENDING`, blocker
   `Missing board reviewer`. A human board reviewer must fill
   `build/host-jtag-preparation/20261109T210015Z/board-review.json`
   (`reviewer`, the five checks, `config_voltage`, `cfgbvs`,
   `led_active_low`) and record the evidence. The wrapper refuses hardware
   while this is pending; it is a review fact, not something to work around.
2. **Per-family user authorization (separate gate)**: the user must
   explicitly authorize the EW load and replay; this is distinct from the
   board-review admission and from any six-page authorization.

### 5.1 Admission gate (run before anything else)

```sh
mkdir -p "$SESSION/replay-ew"
cd /home/fedora/rknpu-fpga
python3 tools/host/prepare.py verify build/host-jtag-preparation/20261109T210015Z \
  | tee "$SESSION/replay-ew/prepare-admission.json"
# GO only if the status is READY_FOR_SEPARATELY_AUTHORIZED_BUILD with no blockers.
# Current expected (blocked): SOURCE_INTACT_REVIEW_PENDING, blockers ["Missing board reviewer"].
```

### 5.2 Load the EW image

Re-run §3.2 + §3.3 + §3.4 with `IMAGE_KIND=ew`, `EXPECTED_ACCESS=ec9ecd41`,
and the EW bitstream path. The same acceptance check must print
`PASS_LOAD ew INIT=1 DONE=1 USR_ACCESS=ec9ecd41`.

### 5.3 EW replay — pinned wrapper (`tools/host/run_jtag_ew_hardware.py`)

Run the offline check first (no hardware), then the hardware replay:

```sh
cd /home/fedora/rknpu-fpga
mkdir -p "$SESSION/replay-ew"
# offline: validates image SHA/tag, target/lease syntax, admission, 9 captured
# replays + E1 plan; touches no USB/lease/socket/Vivado/hw_server.
python3 tools/host/run_jtag_ew_hardware.py --check \
  --image b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a \
  --source-tag ec9ecd41 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock \
  --out "$SESSION/replay-ew/offline-check"
# expect PASS_CHECK when admission is ready, or PASS_CHECK_PENDING_ADMISSION
# (exit 0, hardware_accessed=false) until the human board reviewer signs.
```

Then the hardware replay (only after §5.1 admission is READY, the user has
authorized the EW load+replay, and §3.2/§3.3/§3.4 `PASS_LOAD ew` has run):

```sh
cd /home/fedora/rknpu-fpga
python3 tools/host/run_jtag_ew_hardware.py \
  --authorized \
  --authorization-note "<copy the user's exact EW authorization wording>" \
  --image b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a \
  --source-tag ec9ecd41 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock \
  --out "$SESSION/replay-ew/hardware"
```

What the pinned wrapper does (no programming, volatile-only):

- takes the shared lease, refuses if another `hw_server`/controller or a
  listening debug/bridge port exists, requires exactly one initialized DLC10;
- starts an **owned** `hw_server` and the audited native bridge
  (`fpga/host/native_rpc.tcl.in`), which fails closed unless the loaded image
  has the exact target URI, DNA `004E544714C705C`, `INIT=1`, `DONE=1` and
  `USR_ACCESS=ec9ecd41`;
- verifies the RKEW endpoint identity (`0x524b4557` / ABI `0x00010000`);
- replays all **9** captured EW cases (`capture_add/sub/mul_{8,9,33}`):
  uploads every owned BO byte-verbatim at its captured address, submits the
  captured raw descriptor (address `0x100e0000`, amount 35), polls
  completion, reads **every owned BO byte** back (94,208 B for 1-task cases,
  102,400 B for 2-task cases; **872,448 B total**), compares it completely
  against the frozen capture expectation, and only then ACKs. No prefix
  compare, no tolerance, no CPU arithmetic/layout fixup;
- then runs the archived synthetic unknown-register **E1 negative**: expects
  error code 1 / 0 tasks, no ACK, and a poisoned owner that refuses further
  access. This is deliberately last because it faults the backend;
- writes a source-hash-bound receipt with per-case receipts, complete-BO
  hashes, `hardware_accessed: true`, `flash_written: false`,
  `fabric_programmed: false`, bridge clean-exit and cleanup fields.

Acceptance: wrapper exit 0 with `PASS EW_HARDWARE cases=9 bytes=872448
e1=PASS`, every per-case receipt `status=PASS` with
`ack_after_complete_readback=true`, and the negative receipt
`PASS_EXPECTED_E1_AND_POISONED_OWNER`. Any refusal (no `--authorized`, wrong
image SHA, wrong source tag, admission pending, cable/lease/target identity
failure) exits 2 and opens no hardware. After the E1 negative the fabric is
faulted: reload the EW image (§3.2) before any further mailbox work.

### 5.4 EW after-run state

The pinned wrapper's final E1 negative deliberately faults the EW backend (the
archived audited fault model): no soft reset opcode exists, and a TAP
reset/reconnect does not clear it. After the wrapper finishes, **reload the EW
image (§3.2) before any further mailbox work**. Any unexpected status
`7`/`0x80` earlier in a session has the same meaning: stop, preserve logs,
reload the image. Leaving the session with the last volatile image loaded is
fine; flash is never written.

## 6. Switching images / families (rules)

- One image at a time. A switch is a **new volatile load** of the next exact
  image SHA under a fresh user authorization; there is no warm switch, no
  partial load, no mixed evidence.
- Never reuse a receipt from image A as evidence for image B. Every receipt
  must bind the image SHA actually loaded.
- The six-page image and the EW image have different top-level designs,
  transports and on-chip tags (`none` vs `ec9ecd41`); only one can be in the
  fabric at once.
- Order for one session: preflight/audit → authorize+load image A → replay A →
  evidence A → authorize+load image B → replay B → evidence B. Mode 0 on the
  six-page image requires a reload before B.
- Leaving the session: the last volatile image stays loaded; that is the
  recorded baseline for the next session. Flash is never written, so the
  card's persistent state is unchanged.

## 7. Abort and rollback

Abort immediately (stop the session, do not retry programming blindly) if:

- the user authorization is absent/ambiguous or an image SHA is not the exact
  authorized one;
- target/DNA/IDCODE differ from §1.2, or more than one cable/device appears;
- the shared lease is held by someone else, or another `hw_server`/controller
  is running;
- `PASS_LOAD` fails any field (INIT/DONE/USR_ACCESS/DNA/ID/PASS);
- the bridge READY marker is not `PASS_AUDITED_NATIVE_USER2_BRIDGE_READY`;
- any replay compare fails, a mode reports engine error, or the receipt is
  missing/not `PASS`;
- status `7` or `0x80` appears (quarantine), mode 0 already ran in this
  session, or the bridge is not cleanly quit;
- a thermal event, host reboot, heavy-job kill or power event occurs.

Rollback (volatile only):

1. Stop any owned `hw_server`/Vivado bridge process; release the lease
   (`flock -u`/close fd 9).
2. Keep the failing session directory untouched; write the failure into
   `SESSION-REPORT.md`.
3. Leave the card as-is (last volatile image loaded) or, if a known-good image
   is required for the next step, perform a **new authorized volatile load** of
   that image — never a flash/boot/erase operation.
4. Re-run the read-only preflight (and a target audit if the cable state is
   unclear) before attempting anything else.
5. Report to the Lead/user: exact stage, receipt path, log tail, last
   observed values; do not "fix" expectations, timing gates or fixtures to
   obtain a pass.

## 8. Evidence checklist and handoff

Per load:

- [ ] `program.tsv` (target, DNA, TCK, IDCODE before/after, INIT, DONE,
      USR_ACCESS, PROGRAMMED, CLEANUP, PASS) + its SHA-256;
- [ ] rendered `program.tcl` + its SHA-256; `hw-server.log`; `vivado.log`
      containing `PASS_HOST_USER2_VOLATILE_SRAM_PROGRAM`;
- [ ] bitstream path and SHA-256 (`bitstream.sha256`), session meta with the
      user's authorization wording;
- [ ] no-Go/Go preflight receipt from §1.6;
- [ ] read-only target-audit TSV + device-properties (for the session).

Per replay:

- [ ] harness or EW replay receipt (`receipt.json`) with `hardware_accessed:
      true`, `flash_written: false`, `fabric_programmed: false`;
- [ ] per-mode/per-case receipts and **complete** BO readbacks
      (`mode-<n>-output.bin` for six-page; EW per-case receipts with complete
      region hashes) + `compare` results;
- [ ] per-op envelopes (`mode-<n>-ops.jsonl`) and bridge READY/clean-exit
      logs for the six-page harness; EW wrapper `scans.jsonl`,
      `cases/*.json`, `negative/synthetic_unknown_register.json` and its
      bridge/hw-server logs;
- [ ] offline check receipts: six-page `--check` receipt, EW
      `run_jtag_ew_hardware.py --check` receipt (`PASS_CHECK` or
      `PASS_CHECK_PENDING_ADMISSION`, `hardware_accessed=false`);
- [ ] negative checks (mode 0 status 4 + status 7 quarantine for six-page;
      E1 unknown-register + poisoned-owner for EW) recorded as expected, not
      as failures.

Session handoff (to the user, via the Lead):

- `SESSION-REPORT.md`: what was authorized, which image SHA(s) were loaded,
  per-image/per-mode PASS/FAIL, compare metrics, cleanup state, final loaded
  image, and every artifact path + `session-manifest.sha256`;
- one line per image: `image=<SHA> loaded=INIT/DONE=1 usr_access=<…>
  replay=PASS/FAIL evidence=<path>`;
- explicit statement: `flash_written=false`, `fabric_programmed=false`,
  volatile-only; no cold boot/PCIe/RK-equivalence claim.

## 9. If something fails — decision tree

| Stage / symptom | Check | Action |
|---|---|---|
| Preflight exit 2, cable absent | `lsusb -d 03fd:` empty | plug the DLC10 into this host; rerun preflight |
| Preflight, cable `03fd:0013` | `lsusb -d 03fd:0013` one line | run `bash ~/ypcb/dlc10-init.sh`; require `idcode 0x23751093`; rerun preflight |
| Preflight, ambiguous/unknown 03fd | `lsusb -d 03fd:` | remove extra DLC10s/stop other tools; leave exactly one; rerun preflight |
| Preflight, `hw_server`/controller present | `pgrep -x hw_server` etc.; ports | stop the other session; confirm ports closed; rerun preflight |
| Preflight, lease held | receipt `lease.held=true`, `/proc/locks` | another session owns the board; wait or ask Lead; never force |
| Load blocked: SHA mismatch / no authorization meta | `bitstream.sha256`, `session-meta.txt` | stop; correct the authorized image or wording; do not load |
| Target/DNA/IDCODE mismatch | `program.tsv`, `hw-server.log` | wrong board/cable; stop; do not retry blindly |
| `PASS_LOAD` fails `USR_ACCESS` | expected `00000000` (six-page) or `ec9ecd41` (EW) | wrong image loaded or wrong variable; preserve log, retry only with the exact authorized image; if repeated, stop |
| INIT/DONE not 1 | `program.tsv`, `vivado.log` | load failed; stop, keep logs, one clean retry of the authorized load; if persistent, abort |
| Bridge not READY / wrong marker | `bridge-stdout.log`, `ready.txt` | host/target/lease problem, not fabric damage; stop, verify preflight/audit, retry once; never edit the Tcl |
| Mode compare mismatch / engine error | `mode-<n>.json`, `compare`, `ops.jsonl` | preserve receipt (harness leaves result un-ACKed), stop; do not tweak fixtures/expectations; report |
| Status `7`/`0x80` in any op | ops log / mode receipt | backend quarantined; stop, preserve logs, reload the image (new authorized load) before further work |
| Mode 0 succeeded and quarantined | `mode-0.json` `quarantine_observed=true` | expected; reload before any further mailbox work; do not treat as failure |
| EW `--check` says `PASS_CHECK_PENDING_ADMISSION` | `admission.blockers` | expected until the human board reviewer signs; do not load/run the EW image yet; keep the six-page session separate |
| EW wrapper REFUSED: no `--authorized` / wrong image SHA / wrong source tag | wrapper receipt `status=REFUSED`, `failure` | stop; fix the authorization or the exact image/tag binding; do not bypass the wrapper |
| EW wrapper REFUSED: admission not ready | wrapper receipt `admission.blockers` | human board-review gate; do not load the EW image until `READY_FOR_SEPARATELY_AUTHORIZED_BUILD` |
| EW wrapper compare mismatch / missing E1 | `cases/*.json`, `negative/*.json` | preserve receipt (result left un-ACKed), stop, reload the image, report; never tweak fixtures/tolerance |
| Thermal guard/heavy job kills host work | `/tmp/rknpu-heavy-gate.log`, Tctl | stop, release lease, let the host cool, resume only after preflight re-passes; never bypass the gate |
| Anything unexplained | logs | STOP. Preserve the full session directory, release lease/server, report to Lead/user; do not flash/reset to "fix" it |

## 10. What NOT to do

- Do not flash, erase, or change boot mode: no `-b`/`--fpga-part`/`-f`,
  `flash_jtag.sh program`, `boot_hw_device`, `openFPGALoader --flash`.
- Do not program anything except the exact authorized image SHA, and never a
  second image without a fresh authorization.
- Do not reset the board, power-cycle, reprogram the CPLD/cable EEPROM or use
  `JPROGRAM`/`boot_hw_device`.
- Do not run two cable tools, two `hw_server`s, or a session while another
  lease holder exists.
- Do not run a second image "to compare" in the same loaded state; switch by
  reload only.
- Do not start synthesis/builds/simulations during the session; respect
  `docs/HOST_SHARED_LOCK.md` and the thermal gate for everything else.
- Do not edit gates, fixtures, expected values, Tcl bridges or the harness to
  make a check pass.
- Do not run the EW wrapper without the human board-review admission and the
  user's separate per-family authorization; do not bypass its image-SHA /
  `USR_ACCESS` / target / admission gates.
- Do not claim cold boot, PCIe, RK equivalence, or full RK3588 coverage from
  this volatile session.

## Appendix A — exact values to copy into receipts

```
SIX_PAGE_BIT_SHA=81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39
SIX_PAGE_BIT_BYTES=18735215
SIX_PAGE_TAG=none
EW_BIT_SHA=b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a
EW_BIT_BYTES=18735213
EW_USR_ACCESS=ec9ecd41
TARGET=localhost:3125/xilinx_tcf/Xilinx/80802026a77a01
LEASE=/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock
DNA=004E544714C705C
IDCODE=23751093
PART=xc7k480tffg1156-2
SIX_PAGE_PAGE_IDS=524b4353/524b5050/524b434d/524b4415/524b4416/524b4417 @ 0x8000/0x9000/0xa000/0xb000/0xc000/0xd000
EW_RKEW_ID=524b4557  EW_ABI=00010000  EW_BRAM_BASE=0x10000000
EW_WRAPPER=tools/host/run_jtag_ew_hardware.py
EW_CASE_COUNT=9  EW_CASE_BYTES=94208/102400  EW_TOTAL_BYTES=872448
EW_NEGATIVE=synthetic_unknown_register case=capture_sub_9 expected=E1
```

## Appendix B — state at this update (2026-11-10; refreshed after the pinned-wrapper follow-up)

- **Cable: absent** (`lsusb -d 03fd:` empty at authoring); no `hw_server`; no
  cable controller; shared lease empty/unheld (`stat` + `/proc/locks`).
- Preflight (latest re-run at this update): exit **2**,
  `PASS_PREFLIGHT_NOT_READY`, cable `absent`; receipt
  `build/board-prep/20261110T080821Z-preflight-runbook-appb/receipt.json` sha256
  `1d21c9669b11fb69781df7d329e97ba725711ea1325eb49cde757d6d6e18c901`
  (stdout alongside). The authoritative current-state command is
  `python3 tools/host/jtag_preflight.py`; run it immediately before the real
  session — this Appendix is a snapshot, not a live guarantee.
- Emitted-image catalog at authoring: adopted six-page
  `20261109T160627Z` (`81eef4cd…4d39`) and EW emission
  `20261109T210015Z-emission` (`b373ee70…f59a`); pooling-corpus image still
  **PENDING task-10** (no bitstream); older four-page/historical images are
  not loadable choices for this session.
- **Pinned EW replay wrapper** (added after the initial authoring):
  `tools/host/run_jtag_ew_hardware.py` sha256
  `d606d9eabd0007158564ba4dd9736dd111d447c58b5c85b0d120d172c246539a`;
  offline tests `tests/host/test_run_jtag_ew_hardware.py` sha256
  `022ff8c7a236529e7fb00d850a945429e616147a6ebcb2720f63f04d531c1617`
  (13 tests, all offline). Dry-run evidence at authoring:
  `build/board-prep/20261110T080059Z-ew-check/receipt.json`
  sha256 `bd10621b74ae52b344268e63eccd19d1c788acf170c5edaeb4f3ff4d426e67f6`
  (`PASS_CHECK_PENDING_ADMISSION`, exit 0, hardware_accessed=false);
  `build/board-prep/20261110T080059Z-ew-refused-noauth/receipt.json`
  sha256 `365ffcdbe776e7e3ef1d64dc43123840bb59850f904bda65adf7fd5f30113d01`
  (`REFUSED`, exit 2); `build/board-prep/20261110T080059Z-ew-refused-admission/receipt.json`
  sha256 `023685f5e78307de13d661d904e02b50090ae09a50a8e419db6a157940b0b1ce`
  (`REFUSED`, exit 2, admission gate).
- Companion-document versions at this update: `docs/BOARD_RUN_PREP.md`
  (the living preparation doc) sha256
  `cb6203a4094e333bb865951ff008a7a6fd79c40ac05f6426ac1d250860da6688`;
  `docs/HOST_SHARED_LOCK.md` sha256
  `96ab770dab4eda2e85b6709ee3ba11215f4ed28634196cb37387ef9f2eee6546`.
  Both files evolve: re-run `sha256sum` and re-read the relevant sections
  before relying on this snapshot.
