# Board run preparation — `ypcb_jtag_dual_top` on Inspur YPCB-00338-1P1

Status: **preparation-only procedure + offline-validated harness. No board
access, no programming, no lease acquisition happened while writing this.**
The DLC10 cable is **not attached** to this machine at preparation time; every
blocker and every user-only decision is listed here rather than assumed.

- Board: Inspur YPCB-00338-1P1, `xc7k480tffg1156-2`, 50 MHz `SYS_CLK` (AA28),
  JTAG chain with an Inspur CPLD (`0x10931093`) before the FPGA.
- Cable: Xilinx Platform Cable USB II (DLC10), serial `80802026a77a01` in all
  prior receipts.
- **Adopted image (preferred):** six-page
  `build/jtag-dual-image/20261109T160627Z`, bitstream SHA-256
  `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39`,
  `PASS` WNS +3.952 ns / WHS +0.054 ns, six pages, `hardware_accessed=false`,
  sources match the adopted main tree 73/73. Modes 0–6. **Not FPGA-board-tested**
  (family RTL leaves have a live RK3588 differential; §16 P1).
- **EW image (separate volatile image):**
  `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit`,
  SHA-256 `b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a`,
  `PASS` WNS +0.670 ns / WHS +0.053 ns, **tagged** `USR_ACCESS=ec9ecd41`,
  families ew-fp16/simple_add/fdiv-systematic. Admission
  `SOURCE_INTACT_REVIEW_PENDING` (missing human board reviewer). **Not
  FPGA-board-tested**; its FDIV path has live RK3588 evidence 1,452/1,452.
  See §15.1 row 3.
- Host path: frozen OpenTPU USER2 mailbox, 640-bit frames, opcodes 1..4,
  magic `0x4f54504a` (see `tools/host/transport.py`); native Vivado scan bridge
  (`fpga/host/native_rpc.tcl.in`, `tools/host/native_link.py`).
- Harness: `tools/host/run_jtag_dual_hardware.py`; offline controls:
  `tests/host/test_run_jtag_dual_hardware.py`.
- Readiness preflight (strictly read-only): `tools/host/jtag_preflight.py`;
  offline controls: `tests/host/test_jtag_preflight.py`.
- **Multi-image deployment (§15), host tooling map (§15.4) and class-D ABI
  records (§16)**: no single bitstream carries every family; each family is a
  separate volatile load bound to its own image SHA-256.
- **Live RK3588 differential (P0/P1, §16.1) is a separate evidence level**: it
  exercises the RTL leaves/fixtures on real RK3588 silicon with no FPGA image
  loaded. It does not substitute for an FPGA-board run of a bitstream.

Date of this preparation record: **2026-11-09**, updated 2026-11-10 when the
adopted six-page bitstream landed, the EW image was emitted, and the P1
family-wide live RK3588 differential completed (UTC evidence below;
Asia/Hong_Kong local time is UTC+8).

## 1. What is and is not established

Established by prior, source-bound physical receipts (details and hashes in
§10):

- On 2026-10-26/27 the card was reachable over this DLC10 cable and this
  machine as `localhost:3125/xilinx_tcf/Xilinx/80802026a77a01`; raw JTAG
  IDCODE `0x23751093`, part `xc7k480tffg1156-2`, DNA port
  `004E544714C705C`.
- Two **volatile** SRAM loads of a *different* image (USER2 EW) succeeded, with
  `INIT=1`, `DONE=1`, `USR_ACCESS=3a0ef75f` before/after, and `flash_written:
  false`. That proves the cable/host path, not this image.
- The six-page `ypcb_jtag_dual_top` image now **closes 50 MHz**: the adopted
  build `build/jtag-dual-image/20261109T160627Z` is `PASS` at 20 ns (WNS
  +3.952 ns, WHS +0.054 ns, 0 failing setup/hold endpoints) and emitted a real
  bitstream (SHA-256 `81eef4cd…4d39`). Its recorded build inputs match the
  adopted main tree 73/73 (`source_match: true`). It is the preferred image
  for modes 0–6 and is **not yet hardware-tested**.
- The earlier four-page image `20261109T073000Z` (modes 0–4) remains an
  interim/historical host-drivable image; its recorded sources do **not**
  match the current tree.
- A separate **EW image** was rebuilt from the current tree and emitted for the
  elementwise/simple_add/FDIV families: `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit`,
  SHA-256 `b373ee70…f59a`, `PASS` WNS +0.670 ns / WHS +0.053 ns, tagged
  `USR_ACCESS=ec9ecd41`. Its `tools/host/prepare.py verify` admission is
  `SOURCE_INTACT_REVIEW_PENDING` because the human board review is missing.
- A **P1 family-wide live RK3588 differential** passed **38/38 READY cases**
  under the full race-control protocol (P1-SUMMARY.md, §16.1): conv-fp16 9/9
  on the defined lanes, conv-gemm-vendor 10/10 complete-BO exact (8 exact + 2
  documented tolerances), pooling 19/19 complete 4096-byte BO exact. This is
  RK3588 device evidence for the RTL leaves/fixtures, **not** an FPGA-board run.

Two evidence levels are kept separate throughout this document:

1. **Live RK3588 differential** (P0/P1) — real RK3588 silicon, mainline Rocket
   path; no FPGA bitstream is loaded.
2. **FPGA-board run** — one volatile image from §15 loaded on the YPCB card via
   the DLC10, then the image's host entry point.

"Not hardware-tested" / "not FPGA-board-tested" in this document means level 2.
Live RK3588 results do not replace it.

Not established (do not claim otherwise):

- Neither the six-page `ypcb_jtag_dual_top` image nor the EW image has been
  loaded or observed on the **FPGA board**: every image receipt records
  `hardware_accessed=false`. (Their RTL leaves have RK3588 live evidence,
  §16.1; that is not a bitstream test.)
- The six-page `ypcb_jtag_dual_top` images carry **no `BITSTREAM.CONFIG.USR_ACCESS`
  tag** (no USER1 primitive in `fpga/ypcb_jtag_dual_top.sv`); the audited bridge
  therefore cannot bind a 32-bit on-chip source tag for them. The harness handles
  this explicitly with `--source-tag none` and records the weaker identity basis.
  The **EW image is different**: its emission sets `USR_ACCESS=ec9ecd41`, so an EW
  load can pass `--source-tag ec9ecd41` and gets a real source-tag check.
- `LED polarity` and `CONFIG_VOLTAGE 1.8`/`CFGBVS GND` are not measured board
  facts; see §2.
- No cold boot, no flash read/write, no PCIe, no RK3588 execution.

## 2. Authorization gates — only the user can decide these

Nothing in this repository may program, reset, or flash the card without an
explicit request and an audited target. A run of the harness needs every item
below confirmed by the user **before** the commands in §5–§7 are executed.

| # | Decision | Why the user must decide | Current recorded state |
|---|---|---|---|
| A | **Authorize the volatile JTAG load** of the exact bitstream SHA-256 in §4 (and the host run that follows) | Programming replaces the card's volatile image; the repo rule is "explicit requested action and audited target" | No authorization for this image exists; prior authorization text on file is only for the 2026-10-27 EW run (`User: u can start fpga test if needed`, receipt in §10) |
| B | **Confirm the audited board identity** | Prior receipts bind DNA `004E544714C705C`, cable serial `80802026a77a01`, IDCODE `0x23751093`; the harness/program steps re-check these, but a human must confirm it is the same card and session | Prior identity audited 2026-10-26; must be re-read in the run session (§5) |
| C | **LED polarity** (`RK_LED_ACTIVE_LOW`) | Donor records polarity unverified; it is a build-time parameter. The adopted image's Vivado log shows `synth_design ... -generic LED_ACTIVE_LOW=0`, so the image was built with `0` | Optical polarity still unverified on the card. It only affects LED semantics, not the host/mailbox path or BO results |
| D | **Configuration bank**: `CONFIG_VOLTAGE 1.8` / `CFGBVS GND` | Writing an image with the wrong bank setting is the one failure mode that can make the card unbootable; donor XDC agreement is not a strap measurement | Donor XDC corroboration (`docs/BOARD_ELECTRICAL_EVIDENCE.md`) **plus** a device-side read: `REGISTER.CONFIG_STATUS.BIT30_CFGBVS_PIN = 0` (GND) in a prior read-only target audit (§10). Still not a schematic/voltmeter measurement. **Build-owner attestation:** the adopted build was launched with explicit `RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_CONFIG_VOLTAGE=1.8 RK_CFGBVS=GND RK_EMIT_BITSTREAM=1 RK_LED_ACTIVE_LOW=0`; the rendered Tcl refuses emission without a compatible pair and emission succeeded (`ADOPTION_PROVENANCE.md`, §10). The values remain donor-derived, not measured on this card: confirm the physical bank/strap in the hardware session before loading |
| E | **No-flash rule** | Flash writes are permanent and unauthorized | Confirmed rule; **do not** use `-b`/`--fpga-part`/`-f`, `flash_jtag.sh program`, `boot_hw_device`, or `openFPGALoader --flash`. Volatile JTAG SRAM load only |
| F | **Image identity for the six-page image** (it has no `USR_ACCESS` tag) vs the EW image (tagged `ec9ecd41`) | Six-page: the bridge's `USR_ACCESS` check reduces to `00000000`; on-chip identity is DNA + INIT/DONE + page-identity map, not a build tag. EW: emission set `USR_ACCESS=ec9ecd41` and the bridge can gate on it | Recommended for the six-page image: add `set_property BITSTREAM.CONFIG.USR_ACCESS <source-tag> [current_design]` at the next build (build-side only; needs a fresh emitted receipt). Use `--source-tag none` for six-page, `--source-tag ec9ecd41` for the EW image |
| G | **Whether modes 5–6 are required now** | They need the conv k5/C16 pages; the adopted six-page image contains both, so they are runnable now — decide whether they are in scope for this session | No longer blocked on timing; included in the adopted image (§4). Not hardware-tested |

## 3. Current availability (re-probed 2026-11-10T08:05:56Z)

Read-only multi-image preflight evidence (re-probed for the EW-wrapper documentation):
`build/board-prep/20261110T080556Z-preflight-ew-wrapper/receipt.json`
(SHA-256 `a8c0e1d4d9bde3bfaa735082524c90bf8ac8dd818eb02b425b922475960e6841`).
The earlier availability probe is
`build/board-prep/20261109T231800Z-availability/availability.json`
(SHA-256 `3b145bce…77fd2`). Neither probe opened a USB node, the lease, a
socket connection or a Vivado/hw_server process. The re-probe also enumerates
every multi-image catalog read-only (§8.0/§15.1): jtag-dual 12 receipt dirs
(2 emitted PASS), host-jtag-preparation 10 dirs — the emitted EW image
`20261109T210015Z-emission` with bitstream `b373ee70…f59a` plus its prepare
package and older prepared packages — pooling-image 11 work dirs (simulation /
synthesis attempts only, **no bitstream yet**, task-10 pending) and ppu-image 3
historical single-case pooling images. The preflight still reports **no
cable**, so the session state is unchanged.

| Check | Actual result |
|---|---|
| `lsusb` Xilinx device | none: no `03fd:0008` **and** no `03fd:0013` (cable not attached at all) |
| `/dev/bus/usb` | buses `001 002 003 004`; no Xilinx device node |
| `pgrep -x hw_server` | no process |
| listening `3121/3122/3125/3721/3741` | all closed |
| shared lease `/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock` | exists, empty (not held; verified from `stat` + `/proc/locks`) |
| `fxload` | `/usr/bin/fxload` (2026-01-16 development) |
| `openFPGALoader` | `/usr/bin/openFPGALoader` v1.0.0 |
| `vivado` / `hw_server` | `/home/fedora/vivado/2026.1/Vivado/bin/{vivado,hw_server}`, `vivado v2026.1 (64-bit)` |
| emitted-image catalog | **2 emitted** (adopted six-page `20261109T160627Z` preferred; four-page `20261109T073000Z` interim/historical); 10 older receipts rejected (no page gate / not emitted / failed) |
| Python | CPython 3.14.5 |

The cable is therefore **absent**, not merely uninitialized. Re-run the
read-only preflight (§8.0) whenever the cable state changes — it classifies
absent / `03fd:0013` (needs firmware) / `03fd:0008` (ready) without touching
the lease, USB nodes, servers or fabric. Before anything else, plug the DLC10
into this host (it will enumerate as `03fd:0013`) and run the cable-init step
in §7.

## 4. Image inventory — what can be loaded today

The harness refuses any `--image` that is not the bitstream of a real emitted
`PASS` build receipt under `build/jtag-dual-image/*/inputs.json`. The catalog is
keyed on each receipt's own rendered page-presence gate (`build.tcl`), not on a
hardcoded page list; two real emitted `PASS` images are catalogued now, and the
six-page one is preferred:

| Image receipt | Pages | Bitstream | Gate state |
|---|---|---|---|
| **`build/jtag-dual-image/20261109T160627Z` — preferred, adopted six-page** | 6: conv p0 `0x8000`, pooling `0x9000`, GEMM `0xa000`, conv FP32 p3 `0xb000`, conv k5 p1 `0xc000`, conv C16 p2 `0xd000` | 18,735,215 bytes, SHA-256 `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` | `PASS`, WNS **+3.952 ns**, WHS **+0.054 ns**, 0/202,615 failing setup and 0/201,475 failing hold endpoints, **231,316 LUTs (77.47%)**, 19 RAMB36, 0 routing errors, DRC warnings only, `hardware_accessed=false`; sources **match the current main tree 73/73** (`source_match: true`); six-page presence gate passed; **not FPGA-board-tested**, but its RTL families have live RK3588 differential evidence (§16.1) |
| `build/jtag-dual-image/20261109T073000Z` — interim/historical four-page | 4: conv p0 `0x8000`, pooling `0x9000`, GEMM `0xa000`, conv FP32 p3 `0xb000` | 18,735,215 bytes, SHA-256 `73dd0365…4cf7` | `PASS`, WNS +0.044 ns, WHS +0.058 ns, `hardware_accessed=false`; recorded sources do **not** match the current tree |
| `build/jtag-dual-image/20261109T180000Z` — historical failed attempt | 6 | **none** | `FAIL`, WNS −1.549 ns, timing gate refused, `bitstream_emitted=false`; not loadable |

**Adoption provenance.** The adopted receipt was produced in a separate
snapshot tree (`/home/fedora/rknpu-a-only`) while the main tree carried the
option-B experiment; the main tree was then restored to the recorded baseline,
and `build/timing-lab-share/a_only_adoption_manifest.json` records **73/73**
build inputs byte-identical between the snapshot and the adopted main tree.
The receipt itself records `source_match: true` and
`source_hashes_before == source_hashes_after`. Provenance record:
`build/jtag-dual-image/20261109T160627Z/ADOPTION_PROVENANCE.md`
(SHA-256 `c5971d8a…915b0`), which also carries the build-owner attestation of
the exact build environment (`RK_CONFIRM_BOARD=YPCB_00338_1P1`,
`RK_CONFIG_VOLTAGE=1.8`, `RK_CFGBVS=GND`, `RK_EMIT_BITSTREAM=1`,
`RK_LED_ACTIVE_LOW=0`). The receipt does not duplicate those env values; the
values are donor-derived and remain subject to the real-hardware confirmation
in §2 D/§14.

**Acceptance was already generic.** The same offline path accepted the
six-page receipt with no harness change: `--check --image 81eef4…` with the
default mode set stages modes 0–6 and exits `PASS_CHECK` — receipt
`build/board-prep/20261109T165809Z-check-6page/receipt.json`
(SHA-256 `b82484d222cd3749759297df644619e3165e53625c7046c1a84626425f1a28d7`),
modes `[0,1,2,3,4,5,6]`, `hardware_accessed=false`, sources 73/73 matched.
The synthetic six-page control from the earlier readiness task remains the
pre-landing generic proof
(`tests/host/test_run_jtag_dual_hardware.py::SixPageCatalogControls` and
`build/board-prep/20261109T153248Z-six-page-synthetic-control/check/receipt.json`,
`b6ae2552…89adfb`, software only, never loadable, never evidence).

Consequences for a run today:

- The **preferred image is the six-page adopted bitstream `81eef4…4d39`**;
  modes **0–6** are present and stage offline (mode 0 always last; modes 5/6
  write their outputs at `0x4000`/`0x5000`).
- It has **not been hardware-tested** (`hardware_accessed=false` in its
  receipt). That is the remaining technical uncertainty, not a build blocker.
- The **four-page image is interim/historical**: modes 0–4 only, and it cannot
  be regenerated from the current tree. Keep it only as a fallback; never cite
  its results as current-RTL evidence.
- Every run receipt must bind the exact image hash. The adopted image matches
  the tree at adoption time, but the tree may move again: bind the image SHA
  and its receipt, not "current tree".
- **Other families need other images:** the EW image is now emitted
  (`b373ee70…f59a`, admission pending) and the pooling-corpus image is being
  built by task-10; conv-fp16 and ew-int have no image page. The full family →
  image → transport → modes inventory, switching procedure and per-image
  evidence requirements are in **§15**; class-D ABI limitations are in §16.

## 5. Read-only target identity audit (recommended, before any load)

Run under the shared lease with an **owned** `hw_server`; reads only, no
program/reset of fabric. Do not run this while another `hw_server` or
`openFPGALoader`/`xsdb`/`fxload` process exists.

```sh
export LOCK=/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock
export VIVADO=/home/fedora/vivado/2026.1/Vivado/bin/vivado
export HWSERVER=/home/fedora/vivado/2026.1/Vivado/bin/hw_server
export OUT=/home/fedora/rknpu-fpga/build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-target-audit
mkdir -p "$OUT"
exec 9>"$LOCK"; flock -n 9 || { echo "REFUSED: lease busy"; exit 1; }
pgrep -x hw_server && { echo "REFUSED: other hw_server"; exit 1; }
"$HWSERVER" -s tcp::3125 >"$OUT/hw-server.log" 2>&1 & HW_PID=$!
for i in $(seq 1 300); do (exec 3<>/dev/tcp/127.0.0.1/3125) 2>/dev/null && break; sleep 0.1; done
cat >"$OUT/audit.tcl" <<'TCL'
open_hw_manager
connect_hw_server -url localhost:3125
set targets [get_hw_targets]
if {[llength $targets] != 1} {error "Expected exactly one cable target"}
current_hw_target [lindex $targets 0]
set_property PARAM.FREQUENCY 3000000 [current_hw_target]
open_hw_target
set devices [get_hw_devices]
if {[llength $devices] != 1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {error "Expected single XC7K480T"}
set dev [lindex $devices 0]
refresh_hw_device $dev
set out [open @OUT@/target.tsv w]; fconfigure $out -translation lf -buffering line
puts $out "TARGET\t[current_hw_target]"
puts $out "PART\t[get_property PART $dev]"
puts $out "DNA_PORT\t[get_property REGISTER.EFUSE.DNA_PORT $dev]"
puts $out "INIT_COMPLETE\t[get_property REGISTER.IR.BIT4_INIT_COMPLETE $dev]"
puts $out "DONE\t[get_property REGISTER.IR.BIT5_DONE $dev]"
puts $out "USR_ACCESS\t[get_property REGISTER.USR_ACCESS $dev]"
puts $out "CFGBVS_PIN_BIT30\t[get_property REGISTER.CONFIG_STATUS.BIT30_CFGBVS_PIN $dev]"
close $out
report_property -all -file @OUT@/device-properties.rpt $dev
close_hw_target
open_hw_target -jtag_mode 1
run_state_hw_jtag RESET
run_state_hw_jtag IDLE
scan_ir_hw_jtag 6 -tdi 09
set ident [scan_dr_hw_jtag 32 -tdi 0]
if {[expr "0x$ident"] != 0x23751093} {error "Unexpected exact raw IDCODE"}
scan_ir_hw_jtag 6 -tdi 3f
run_state_hw_jtag IDLE
close_hw_target
disconnect_hw_server
close_hw_manager
puts "PASS_READ_ONLY_TARGET_AUDIT"
exit
TCL
sed -i "s|@OUT@|$OUT|g" "$OUT/audit.tcl"
"$VIVADO" -mode batch -nojournal -nolog -source "$OUT/audit.tcl" >"$OUT/vivado.log" 2>&1
AUDIT_RC=$?
kill "$HW_PID" 2>/dev/null; wait "$HW_PID" 2>/dev/null
exec 9>&-
cat "$OUT/target.tsv"; echo "audit rc=$AUDIT_RC (expect 0 and PASS_READ_ONLY_TARGET_AUDIT in vivado.log)"
sha256sum "$OUT"/audit.tcl "$OUT"/target.tsv "$OUT"/device-properties.rpt "$OUT"/vivado.log
```

Acceptance: exactly one target, part `xc7k480t`, DNA
`004E544714C705C`, raw IDCODE `23751093`, and `CFGBVS_PIN_BIT30` = `0`. The
`INIT/DONE/USR_ACCESS` values describe whatever volatile image is currently in
the fabric (an untagged image reports `USR_ACCESS=00000000`). The reference
audited template is
`build/fpga-bringup/ew-startup-1792988881763089417/target-audit/audit.tcl`
(SHA-256 `21e1affea26b3e812e99b7fe8f2f9141582798e137780d3bce825d1fdf7b345b`);
its prior receipt records `DNA_PORT 004E544714C705C`, `USR_ACCESS 00000000`
and the `CFGBVS_PIN=0` line in `device-properties.rpt`.

## 6. Volatile JTAG programming (separate authorized step — never done by the harness)

The host harness **does not** program, reset fabric, or write flash. Load the
image in a separate step, reusing the audited program Tcl pattern
`verification/runs/2026-10-27-host-user2-fpga/hardware/program-template.tcl.in`
(SHA-256 `d7ebf86450c55de4378692f0aae20f6af20fffe7366b329a29b3972e6429a96d`),
which checks target URI, DNA, INIT/DONE and `USR_ACCESS`, and writes a TSV
receipt. The only changes here are the target values: this image is **untagged**,
so `@USR_ACCESS@` = `00000000`.

### 6A. Vivado `hw_server` native (audited route; recommended)

```sh
export LOCK=/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock
export VIVADO=/home/fedora/vivado/2026.1/Vivado/bin/vivado
export HWSERVER=/home/fedora/vivado/2026.1/Vivado/bin/hw_server
export BIT=/home/fedora/rknpu-fpga/build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit
export OUT=/home/fedora/rknpu-fpga/build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-program
mkdir -p "$OUT"
exec 9>"$LOCK"; flock -n 9 || { echo "REFUSED: lease busy"; exit 1; }
pgrep -x hw_server && { echo "REFUSED: other hw_server"; exit 1; }
pgrep -x openFPGALoader >/dev/null && { echo "REFUSED: other loader"; exit 1; }
python3 - "$OUT" "$BIT" <<'PY'
from pathlib import Path
import sys
out, bit = Path(sys.argv[1]), sys.argv[2]
template = Path('/home/fedora/rknpu-fpga/verification/runs/2026-10-27-host-user2-fpga/'
                'hardware/program-template.tcl.in').read_text()
values = {
    '@TARGET@': '{localhost:3125/xilinx_tcf/Xilinx/80802026a77a01}',
    '@BITSTREAM@': '{' + bit + '}',
    '@RECEIPT@': '{' + str(out / 'program.tsv') + '}',
    '@USR_ACCESS@': '00000000',
}
for marker, value in values.items():
    assert template.count(marker) == 1, marker
    template = template.replace(marker, value)
(out / 'program.tcl').write_text(template)
print(out / 'program.tcl')
PY
"$HWSERVER" -s tcp::3125 >"$OUT/hw-server.log" 2>&1 & HW_PID=$!
for i in $(seq 1 300); do (exec 3<>/dev/tcp/127.0.0.1/3125) 2>/dev/null && break; sleep 0.1; done
"$VIVADO" -mode batch -nojournal -nolog -source "$OUT/program.tcl" >"$OUT/vivado.log" 2>&1
PROGRAM_RC=$?
kill "$HW_PID" 2>/dev/null; wait "$HW_PID" 2>/dev/null
exec 9>&-
cat "$OUT/program.tsv" 2>/dev/null
echo "program rc=$PROGRAM_RC (expect 0 and PASS_HOST_USER2_VOLATILE_SRAM_PROGRAM)"
sha256sum "$BIT" "$OUT/program.tcl" "$OUT/program.tsv" "$OUT/vivado.log" 2>/dev/null
```

Acceptance (TSV): `DNA_PORT 004E544714C705C`, `TCK_HZ 3000000`,
`IDCODE_BEFORE 23751093`, `INIT_COMPLETE 1`, `DONE 1`,
`USR_ACCESS 00000000`, `IDCODE_AFTER 23751093`, `PROGRAMMED 1`,
`CLEANUP 1`, `PASS 1`; stdout contains
`PASS_HOST_USER2_VOLATILE_SRAM_PROGRAM`; bitstream SHA-256 must equal
`81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39`.
**No `write_bitstream`/flash command appears anywhere in this path.**

The build owner has attested the build environment in
`ADOPTION_PROVENANCE.md` (explicit `RK_CONFIG_VOLTAGE=1.8`, `RK_CFGBVS=GND`,
`RK_LED_ACTIVE_LOW=0`, board confirmation; the rendered Tcl refuses emission
without a compatible pair, and `LED_ACTIVE_LOW=0` is also visible in the
receipt's Vivado log). These values are still donor-derived, **not** measured
on this card: confirm the physical bank/strap in the authorized hardware
session before loading (§2 D).

### 6B. openFPGALoader (cable/JTAG sanity route; weaker evidence)

The proven template is `~/openTPU/boards/ypcb-00338/program.sh`
(SHA-256 `8eaaf201f6ed82876769972c2881335ada3da398f7e7ca62bb62e5518546f458`).
Its default (non-`--flash`, non-`--vivado`) mode performs exactly the volatile
SRAM load:

```sh
~/openTPU/boards/ypcb-00338/program.sh /home/fedora/rknpu-fpga/build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit
```

which expands to the template's command:

```sh
openFPGALoader --cable xilinxPlatformCableUsb \
  --misc-device 0x10931093,8,inspur_cpld --index-chain 0 \
  --probe-firmware /home/fedora/ypcb/firmware/xusb_xp2-overlay.hex \
  --freq 6000000 <bit>
```

Caveats, all real:

- Use the DLC10-proven debug build `/home/fedora/ypcb/openFPGALoader/build-xpcu-debug/openFPGALoader`
  if the installed `/usr/bin/openFPGALoader` v1.0.0 rejects the
  `xilinxPlatformCableUsb` cable. The cable must already be initialized to
  `03fd:0008` (§7).
- This route verifies neither DNA nor `USR_ACCESS`; it cannot serve as the
  audited identity gate. If used, re-run the read-only audit (§5) afterwards to
  capture IDCODE/INIT/DONE and accept a weaker evidence basis (§2 F).
- `program.sh --flash`, `flash_jtag.sh program`, `-b`, `--fpga-part`,
  `-f`, `boot_hw_device` are **forbidden**. Only the volatile SRAM load above.
- The card must be idle: no `hw_server`, no `openFPGALoader`, no holder of the
  shared lease. Hold the lease across the load and stop the loader afterwards.

### 6C. After programming

Re-read identity (repeat §5) and confirm `INIT=1`, `DONE=1`, DNA unchanged,
`USR_ACCESS=00000000` (this six-page image is untagged; the EW image expects
`USR_ACCESS=ec9ecd41` instead). Then **stop every `hw_server`** before
starting the harness: the harness owns its own `hw_server` and refuses if one
is already running.

## 7. Cable / DLC10 initialization (user-run, before §5/§6)

`~/ypcb/dlc10-init.sh` (SHA-256
`3a329687a71060bb6b1fd600a921d0d61b6ae25972f4ab7c3ac32ba81bee0f7e`)
initializes **cable RAM only** and detects the FPGA; it does not program the
FPGA or flash. Documented behavior and firmware hashes are in
`~/ypcb/DLC10_OPENFPGALOADER_DEBUG.md`
(SHA-256 `72df6ae27a1b0365d836c0689aac245662802d1880f11a4b39f61fb96a2e7f75`).

1. Plug the DLC10 into this host. Confirm it is the pre-firmware node (no
   Xilinx device before plug-in; after plug-in there should be exactly one):
   ```sh
   lsusb -d 03fd:0013
   lsusb -d 03fd:0008   # expected empty before init
   ```
2. Ensure no cable tool is running (`dlc10-init.sh` itself refuses otherwise):
   ```sh
   pgrep -x hw_server; pgrep -x openFPGALoader; pgrep -x xsdb; pgrep -x fxload
   ```
3. Initialize and detect:
   ```sh
   cd ~/ypcb && bash dlc10-init.sh
   ```
   Expected: last line `PASS: DLC10 initialized and YPCB XC7K480T detected
   without Vivado.`; detection log contains `idcode 0x23751093`. The script
   checks the staged firmware hashes, refuses multiple DLC10s, loads the boot
   image (`firmware/xusb_xp2-boot.hex`, SHA-256 `4fe1a679…527a`), loads the
   A3 helper (`ref/fxload/a3load.hex`, SHA-256 `5f27f666…a240`) plus runtime
   overlay (`firmware/xusb_xp2-overlay.hex`, SHA-256 `f551e3c…4a9cf`) and
   requires the FPGA IDCODE. Logs: `/tmp/dlc10-init.*/`.
4. Confirm the operational node:
   ```sh
   lsusb -d 03fd:0008   # exactly one line: Platform Cable USB II
   ```
   The JTAG chain is declared as `--misc-device 0x10931093,8,inspur_cpld`
   (Inspur CPLD before the FPGA); the FPGA must appear as `0x23751093`.

Failure handling: if the overlay upload or final detection fails, replug the
cable and rerun the script; do not start `hw_server` against a half-initialized
cable.

## 8. Host harness — exact commands

The harness (`tools/host/run_jtag_dual_hardware.py`, SHA-256 in §10) **refuses
hardware** unless all of `--authorized`, an `--image` matching a real emitted
bitstream, an exact local audited `--target`, a `--lease`, and a
`--source-tag` are given. It never programs, resets, or flashes: it starts an
owned `hw_server` + the audited native scan bridge, verifies the loaded image
(one target, DNA, INIT/DONE, `USR_ACCESS`, page identities), shifts mailbox
frames, and stops everything. Image loading is §6, a separate step.

### 8.0 Read-only preflight (safe at any time, even with no cable)

```sh
cd /home/fedora/rknpu-fpga
python3 tools/host/jtag_preflight.py \
  --out build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-preflight
```

Dry-run in the current **no-cable** state, re-run for the multi-image
inventory: exit **2**, `status=PASS_PREFLIGHT_NOT_READY`, cable stage `absent`,
prerequisites OK, `hw_server` none, ports closed, lease free, catalog
`emitted=2`, **preferred image six-page `20261109T160627Z` = `81eef4cd…4d39`
with modes `[0,1,2,3,4,5,6]`**, dated prior board identity printed, and next
commands generated for the pending cable states. The same receipt lists
**every image catalog read-only**: `build/jtag-dual-image` (12 receipt dirs,
2 emitted PASS), `build/host-jtag-preparation` (10 dirs; the EW emission
`20261109T210015Z-emission` shows bitstream `b373ee7000cf…` along with the
prepare packages), `build/pooling-image` (11 work dirs, simulation/synthesis
only, no bitstream yet — task-10 pending) and `build/ppu-image` (3 historical
single-case pooling images). Receipt:
`build/board-prep/20261110T080556Z-preflight-ew-wrapper/receipt.json`
(SHA-256 `a8c0e1d4d9bde3bfaa735082524c90bf8ac8dd818eb02b425b922475960e6841`);
stdout log alongside it (`9711613b…b9db035`).

What it reports (and how it stays read-only):

| Item | Source | Notes |
|---|---|---|
| USB stage | `lsusb -d 03fd:0013`, `-d 03fd:0008`, `-d 03fd:` | absent = report + exit 2; `03fd:0013` = run §7; `03fd:0008` = initialized; multiple/unknown 03fd devices = ambiguous |
| `~/ypcb/dlc10-init.sh` prerequisites | script text plus file hashes | expected firmware/helper paths and SHA-256 are **derived from the script itself**; also checks `fxload`/`lsusb`/`sha256sum`/`awk`/`pgrep`/`python3`, the cable-init script's own hash, the `build-xpcu-debug` loader and the stage-2 helper |
| `hw_server` / controllers | `/proc` read-only scan | PIDs and cmdlines; the tool never starts or signals a process |
| ports 3121/3122/3125/3721/3741 | `ss -H -ltn` | listening flags only; no socket connection is opened |
| shared lease | `stat` + `/proc/locks` | reports held/free from the kernel lock table; the lease file is **never opened or flocked** |
| tool versions | fixed `--version` commands | Python, `fxload -V`, `openFPGALoader -V`, `vivado -version`; all offline, all listed in the receipt; `--skip-version-probes` omits them |
| emitted-image catalog | `build/jtag-dual-image/*/inputs.json` + `build.tcl` | preferred image, page map and supported modes; nothing is executed |
| all image catalogs (§15.1) | `build/jtag-dual-image`, `build/host-jtag-preparation`, `build/pooling-image`, `build/ppu-image` (read-only) | multi-family inventory: receipt profile/status, **any `implementation/*.bit` or `bitstream/*.bit` + SHA-256**, page gate, `REBUILD_RECEIPT.md` emission marker; the emitted EW image appears with `b373ee70…f59a`; missing/pre-EW task-10 catalogs are reported honestly; `--image-catalog` replaces the default list |
| prior board identity | dated receipts | DNA/IDCODE/serial/CFGBVS as **prior evidence**, explicitly not a current reading |
| exact next commands | generated | one block per state, never executed; authorization wording is a placeholder |

The multi-family inventory is printed by default (the same command that
decides six-page readiness also lists the EW/pooling catalogs read-only; the
EW image now appears with its emitted bitstream, and the pooling images appear
as soon as task-10 emits one). Use `--image-catalog <dir>` (repeatable) to
inspect a different catalog set.

Exit codes: `0` = ready for an authorized session; `2` = not ready (reason
list included); `1` = internal/usage error. The receipt records
`hardware_accessed=false`, `usb_node_opened=false`, `lease_opened=false`,
`network_accessed=false`, `firmware_loaded=false`, `hw_server_started=false`,
`fabric_programmed=false`, `flash_written=false`.

### 8.1 Offline check (no hardware; run this first)

Validated result on 2026-11-09 against the **adopted six-page image** with the
default mode set (exit 0, modes 0–6):

```sh
cd /home/fedora/rknpu-fpga
python3 tools/host/run_jtag_dual_hardware.py --check \
  --image 81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock \
  --out build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-check-6page
```

(`--mode` may be repeated; omitted it defaults to every mode, and the harness
runs mode 0 last. For the adopted image the staged plan is modes
`[0,1,2,3,4,5,6]` with pages conv p0/pooling/GEMM/conv FP32 p3/conv k5/conv
C16.)

Receipt: `build/board-prep/20261109T165809Z-check-6page/receipt.json`
(SHA-256 `b82484d222cd3749759297df644619e3165e53625c7046c1a84626425f1a28d7`),
status `PASS_CHECK`, `hardware_accessed=false`, `lease_acquired=false`.
Historical four-page control: the same check against
`73dd0365…4cf7` with the default mode set returns `CHECK_BLOCKED` (exit 1) for
modes 5–6 — receipt
`build/board-prep/20261109T153248Z-check-all-modes/receipt.json`
(SHA-256 `aa3c44f681af86d0fcf18faca14fb694c20e5efe66f8f9c21600be98f4722dbf`).
That refusal is intentional; never "fix" it by dropping a mode's page
requirement. The pre-landing synthetic six-page control shows the same
acceptance path (§4/§11).

`--check` validates: argument regexes, the emitted-image catalog lookup and
bitstream SHA, the page gate parsed from that build's rendered `build.tcl`,
source freshness of the image receipt, every frozen fixture manifest, the exact
BO staging/patches/sizes (via the same loaders the simulation replay uses),
BO range/overlap/window checks, mode→page availability and descriptor fit. It
writes a receipt and exits without opening a socket, USB node, lease, Vivado or
hw_server (add `--probe-tool-versions` only if you accept the two offline
version probes).

### 8.2 Real run (only after §2 authorization, cable init §7, load §6)

The harness owns the `hw_server` on the port in `--target` (3125 here), so no
`hw_server` may be running. It holds the shared lease non-blockingly for the
whole run. It requires exactly one initialized `03fd:0008` DLC10 and no other
cable controller process.

One session, modes 1–6 then 0. The harness always runs mode 0 last (its final
negative check deliberately quarantines the bridge); with the default mode set
the order is exactly `1,2,3,4,5,6,0`:

```sh
cd /home/fedora/rknpu-fpga
python3 tools/host/run_jtag_dual_hardware.py \
  --authorized \
  --authorization-note "User authorized volatile load of <SHA> and host run on <date> (insert exact wording)" \
  --image 81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock \
  --source-tag none \
  --mode 1 --mode 2 --mode 3 --mode 4 --mode 5 --mode 6 --mode 0 \
  --out build/board-prep/$(date -u +%Y%m%dT%H%M%SZ)-hardware
```

Per-mode variants (one process per session; a mode-0 session quarantines the
bridge, so reload the image before the next session):

```sh
MODE_ARGS="--authorized --image 81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39 \
  --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 \
  --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock --source-tag none"
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 1 --out build/board-prep/<stamp>-mode1
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 2 --out build/board-prep/<stamp>-mode2
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 3 --gemm-case gemm_m2_n2_k1 --out build/board-prep/<stamp>-mode3
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 4 --out build/board-prep/<stamp>-mode4
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 5 --out build/board-prep/<stamp>-mode5
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 6 --out build/board-prep/<stamp>-mode6
# after mode 0 (or any session), reload §6 before further mailbox work:
python3 tools/host/run_jtag_dual_hardware.py $MODE_ARGS --mode 0 --out build/board-prep/<stamp>-mode0
```

Mode meanings (same suite as `tools/host/run_jtag_dual.py`, same tags, amounts
and tolerances as `tests/tb_ypcb_jtag_dual.sv`):

| Mode | Page | Job | BOs loaded | Complete readback / compare |
|---|---|---|---|---|
| 0 | all pages in image | contract: identities/ABI, word + 64-byte block round trips, misaligned block read must return status 4, unmapped `0xe000` read must return status 7 + quarantine | none | status checks only |
| 1 | `0x8000` conv p0 | `conv_simple_fp16_3x3_c4_h8_w8_oc16`, amount 52, tag `0xc0de4001` | 104/128/576/1024 words at `0x0/0x1000/0x2000/0x3000` | 4096 bytes byte-exact |
| 2 | `0x9000` pooling | `int8_max_k2s2_valid_c16_h2w2`, amount 26, tag `0xc0de4002` | 52/1024/1024 words at `0x0/0x1000/0x2000` | 4096 bytes byte-exact |
| 3 | `0xa000` GEMM | frozen GEMM capture (default `gemm_m2_n2_k1`), amount 45, tag `0xc0de4003` | 98/1024/1024/1024 words at `0x0/0x1000/0x2000/0x3000` | 4096 bytes; abs tolerance 0.0 for `gemm_m2_n2_k1`, 0.1 for the deeper shapes |
| 4 | `0xb000` conv FP32 p3 | `conv_simple_fp16_1x1_c4_h8_w8_oc16`, amount 52, tag `0xc0de6001` | 104/256/128/1024 words | 4096 bytes; abs tolerance 0.001 (capture oracle is float64→float32) |
| 5 | `0xc000` conv k5 p1 | `conv_simple_fp16_5x5_c4_h8_w8_oc16`, amount 52, tag `0xc0de7001` | 104/128/1600/1024 words, output at `0x4000` | six-page image only (adopted; not hardware-tested) |
| 6 | `0xd000` conv C16 p2 | `conv_simple_fp16_3x3_c16_h8_w8_oc32`, amount 52, tag `0xc0de8001` | 104/512/2304/1024 words, output at `0x5000` | six-page image only (adopted; not hardware-tested) |

Per job mode the harness: loads every BO through 64-byte block writes (the
final partial block zero-padded exactly as the bench does), reads every BO
back and compares, writes the descriptor, polls `can_submit`, submits
`COMMAND=1`, polls completion, checks result tag/tasks/error code, reads the
**complete 4096-byte output BO** and compares it, and only then writes
`COMMAND=2` (ACK) and verifies the completion slot cleared. A mismatch leaves
the result un-ACKed and the evidence in place.

Refusal / exit codes: `0` PASS; `1` CHECK_BLOCKED/FAIL (plan, fixture, compare,
bridge or cleanup problem); `2` REFUSED (no `--authorized`; cable absent or
`03fd:0013`; lease busy; another `hw_server`/controller process; debug port
listening; plan blocked). The authorization refusal (missing
`--authorized`) is decided before the lease, USB, sockets or any process
launch. Precondition refusals (absent/`03fd:0013` cable, another server or
controller, a busy debug port) happen after the nonblocking lease acquisition
is attempted; the lease is released on the way out, and no server, USB node or
fabric store is touched. Neither class programs or resets anything. Dry-run
refusal receipt: `build/board-prep/20261109T153248Z-hardware-refusal/receipt.json`
(SHA-256 `368941d9632cc96dafe2cac4e928ccd3e21050f79daf087834f70ad394b2e606`),
status `REFUSED`, `hardware_accessed=false`, `lease_acquired=false`.

## 9. Evidence to capture during the real run

The harness writes a fresh receipt directory per invocation. Keep it (no
copy-forward of old receipts for a new load).

| Evidence | Where | Acceptance |
|---|---|---|
| Run receipt with the world-readable flags | `<out>/receipt.json` | `status=PASS`, `hardware_accessed=true`, `fabric_programmed=false`, `fabric_reset=false`, `configuration_written=false`, `flash_written=false`, `image_loaded_by_this_tool=false`, `lease_acquired=true` then `lease_released=true` |
| Loaded-image identity | program TSV (§6) + target TSV (§5) + `<out>/receipt.json` `image`/`page_identities`/`bridge.ready_marker` | bitstream SHA matches `--image` (`81eef4cd…4d39` for the adopted image); DNA `004E544714C705C`; `INIT=1 DONE=1`; `USR_ACCESS` equals `--source-tag` expectation (`00000000` for this untagged image); one target with URI `localhost:3125/xilinx_tcf/Xilinx/80802026a77a01`; TCK 3 MHz; page identities `524b4353/524b5050/524b434d/524b4415/524b4416/524b4417` at `0x8000/0x9000/0xa000/0xb000/0xc000/0xd000` |
| Per-mode receipts | `<out>/mode-<n>.json` | `status=PASS`; descriptor status, result tag/tasks/error code; `loads[]` readback matches; `compare.passed=true` with `differing_words`/`worst_abs` ≤ tolerance; `ack.completion_cleared=true` |
| Image provenance binding | adopted receipt + `ADOPTION_PROVENANCE.md` + adoption manifest (hashes in §10) | image SHA `81eef4…4d39`; receipt `source_match: true`; 73/73 build inputs equal between snapshot and adopted tree; no hardware access in the build |
| Complete BO readbacks | `<out>/mode-<n>-output.bin` (+ `expected_sha256`/`observed_sha256` in the mode receipt) | 4096 bytes each; SHA-256 recorded; file kept as evidence |
| Per-op mailbox envelopes | `<out>/mode-<n>-ops.jsonl` | one JSON line per request: opcode, address, sequence, status, expected_status, polls, data/response SHA-256; evidence for status 4 and status 7 in mode 0 |
| Bridge audit trail | `<out>/bridge/bridge.tcl`, `bridge-stdout.log`, `ready.txt`, and its SHA-256s in `receipt.json` | rendered from `fpga/host/native_rpc.tcl.in`; READY marker `PASS_AUDITED_NATIVE_USER2_BRIDGE_READY`; clean exit marker `PASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT`; exact-cable/DNA/INIT/DONE/`USR_ACCESS` checks are in that Tcl and it fails closed |
| Owned-server log/exit | `<out>/bridge/hw-server.log`, `receipt.json.cleanup` | owned `hw_server` stopped by the run; no controller left |
| Mode 0 negative evidence | `<out>/mode-0.json` | status 4 for the misaligned block read, status 7 + `quarantine_observed=true` for `0xe000`; local refusal after quarantine; this is why a reload is required for later sessions |
| Lease discipline | `receipt.json.lease*` | acquired non-blocking, released at end; no other holder |
| Read-only preflight state | `<preflight-out>/receipt.json` (separate read-only command) | cable stage, prerequisites, processes/ports, lease, tools, preferred image + modes; all read-only flags false |
| LED observation (optional) | photograph/notes | LEDs are status only (conv/pool/GEMM completion/fault, heartbeat); they do not assert workload PASS and polarity is unverified (§2 C) |

Acceptance = all six job modes (modes 1–6) PASS with complete 4096-byte BO
comparison, mode 0 contract PASS, target identity as above, and no
flash/configuration write. A partial run or a single mode is not a board
qualification.

## 10. Reference hashes (facts used in this document)

All hashes below were recomputed on this host on 2026-11-09/10 (the EW rows on
2026-11-10) and are recorded in
`build/board-prep/20261109T231800Z-availability/availability.json`
(`3b145bce…77fd2`) plus the EW rebuild receipt. Paths are absolute; `~/` is
`/home/fedora`.

| File / receipt | SHA-256 | What it establishes |
|---|---|---|
| `~/ypcb/dlc10-init.sh` | `3a329687a71060bb6b1fd600a921d0d61b6ae25972f4ab7c3ac32ba81bee0f7e` | cable init procedure: firmware hash checks, CPLD chain, IDCODE gate |
| `~/ypcb/DLC10_OPENFPGALOADER_DEBUG.md` | `72df6ae27a1b0365d836c0689aac245662802d1880f11a4b39f61fb96a2e7f75` | DLC10 staged-firmware findings and exact non-Vivado cold-start procedure |
| `~/ypcb/firmware/xusb_xp2-boot.hex` | `4fe1a679efcc7ed7c01e738beaf29d8a1f1201731780dfc026f724a88aee527a` | boot image; 03fd:0013→0008 transition |
| `~/ypcb/firmware/xusb_xp2-overlay.hex` | `f551e3c71efee0556b465dc9975d528115f9849ea143f51b5c44d6f3f4f4a9cf` | runtime overlay for a working JTAG scan |
| `~/ypcb/ref/fxload/a3load.hex` | `5f27f666e408512b4e7ba6d53bee89410b31e4cb9f7c27930dfa3db65ab2a240` | A3 helper for the overlay stage |
| `~/openTPU/boards/ypcb-00338/program.sh` | `8eaaf201f6ed82876769972c2881335ada3da398f7e7ca62bb62e5518546f458` | proven volatile JTAG load template (`--flash` mode is forbidden here) |
| `~/openTPU/boards/ypcb-00338/flash_jtag.sh` | `128d6832f66158bfa0ba10d489cc756bc5217f9bd127398a634a4864ea8d2a49` | reference only; **flash writes forbidden** |
| `verification/runs/2026-10-27-host-user2-fpga/hardware/program-template.tcl.in` | `d7ebf86450c55de4378692f0aae20f6af20fffe7366b329a29b3972e6429a96d` | audited program Tcl pattern (target/DNA/INIT/DONE/USR_ACCESS gates) |
| `verification/runs/2026-10-27-host-user2-fpga/hardware/image-review.json` | `62a64153120d6f6255d904f3d8def693cdde347b5333a18e5140ef83e5ad0ee2` | prior reviewed EW image: USR_ACCESS `3a0ef75f`, volatile scope, flash not authorized |
| `verification/runs/2026-10-27-host-user2-fpga/hardware/physical-tests/report.json` | `a34f9cf8a0bb8811905155a53c5235c9781837119ac8ed2da610c226706681e3` | prior physical run: target URI, one `03fd:0008` DLC10, lease, two volatile loads PASS, `flash_written=false` |
| `build/fpga-bringup/ew-startup-1792988881763089417/target-audit/audit.tcl` | `21e1affea26b3e812e99b7fe8f2f9141582798e137780d3bce825d1fdf7b345b` | audited read-only target-audit Tcl pattern used in §5 |
| `build/fpga-bringup/ew-startup-1792988881763089417/target-audit/report.json` | `0c9ec622c3ee649ed3f1dd56a4863d396f3f73fbe36ec3b70cb27a3f760fbbc7` | read-only target audit PASS, no programming |
| `build/fpga-bringup/ew-startup-1792988881763089417/target-audit/device-properties.rpt` | `e14f0b80e5dbb87c87822b4b623d5f4265a8964ef46bfa622b2ab087653afc08` | `DNA_PORT 004E544714C705C`, `USR_ACCESS 00000000` (unconfigured/untagged), `CFGBVS_PIN=0` |
| `~/ZYNQ-NVDLA/boards/ypcb/JTAG_RESULT_20261026.md` | `86fde75f9ef569588ba0dcbfe19b9d2c0dcab44e3cedd851705555dab700a96d` | independent physical YPCB JTAG result: cable `80802026a77a01`, IDCODE, INIT/DONE, volatile SRAM, no flash |
| `~/ZYNQ-NVDLA/boards/ypcb/jtag-result-v17.json` | `79ac8a87137b4b4f1d3c328276e1bde8fe7f19b03aa4205d91b62199d30fd0ed` | machine-readable board identity: cable serial, IDCODE `0x23751093`, `03fd:0008` |
| `fpga/host/native_rpc.tcl.in` | `1c66a921de29c08767b578ff41eb349d3d05392bea9c2bb3ec1895df8116b42e` | native bridge: exact target/DNA/INIT/DONE/USR_ACCESS gates before raw scans; whitelisted scans only |
| `tools/host/transport.py` | `ad65b88676f21b751348cb7e0de051f88c3a50bcb41444bb15e28ba3eb15103d` | frozen USER2 frame mechanics (640-bit, magic, opcodes 1..4, status/quarantine rules) |
| `tools/host/native_link.py` | `7f78db0d4f50d72a4a249e434adfe68d6b4e04b7e8fc42cf7bacf90be9f5b93b` | native scan link used by the harness |
| `tools/host/run_jtag_dual.py` | `f5c4e2864d61fe78aa233a7b6c82698395811638c7168b3df85c07093d7c91cd` | simulation replay: fixture loaders, mode suite, BO sizes reused verbatim by the hardware harness |
| `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit` | `b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a` | **EW image bitstream** (host-user2-ew), 18,735,213 B; tagged `USR_ACCESS=ec9ecd41`; emitted only, never hardware-tested |
| `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/image.dcp` | `75fe964a6f6c29830a82f4635fd8ee44ed9fa1830e4db49d617bfcf2942689c5` | EW routed image checkpoint |
| `build/host-jtag-preparation/20261109T210015Z-emission/REBUILD_RECEIPT.md` | `1d35159595ffd07f41190e23567183eff4bef32a000a2b6f7db861451debf018` | EW rebuild receipt: exact commands, gates (WNS +0.670/WHS +0.053, 10,829/10,829 nets), admission `SOURCE_INTACT_REVIEW_PENDING` |
| `build/host-jtag-preparation/20261109T210015Z/report.json` | `65095e5273cce0467b31189f5ffe7d3111d4f95653e97365cfce89d3653ca625` | prepared EW package (`PREPARED_HOST_JTAG_EW_ONLY`), source sha256 `ec9ecd41…4d88` |
| `build/host-jtag-preparation/20261109T210015Z/board-review.json` | `15de5cdb89c56e6ceec5aa1c8e11120d54288abfe27bfb6a9354eda89fff1c36` | incomplete human board review (the admission blocker) |
| `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/startup_facts.tsv` | `91312b926bbfb1b29466cdfa39746415358c1ac9274d25b0976cf5a7fabe20d3` | EW startup audit facts |
| `build/rtl/report.json` | `59a45e6d811b255e1be07c3b72ca63de873f965685edc09d2aa85e6e5a3777e4` | Verilator host qualification PASS, source sha `4347ab81…` (267 tests incl. FDIV) |
| `build/iverilog/report.json` | `3e2019cd2d9613e526562cb3cc710d018b68361103f52ecf8c0a276984baed6a` | Icarus four-state host qualification PASS, same source sha |
| `docs/HOST_JTAG_BRAM.md` | `c4f15da5bb602b5a2c215f7bc5cd87aaf6ef074181106710f6c0a72ff2d59f9f` | timing's "Current image rebuild, 2026-11-10 (source tag ec9ecd41)" section with the same gates/bitstream SHA |
| `docs/PROGRESS_TABLE.md` | `051966813d7da6f84e9877e998612c532274dbe964073316a7f9834aba97c6f8` | image calendar row for the EW image |
| `tools/host/run_jtag_dual_hardware.py` | `a1a4b56b54be7bc4a78986baabb7b1a902a34c679fa1d451921786c30f3b7007` | hardware harness; catalog/page-gate path is unchanged and already admits any future six-page PASS receipt |
| `tests/host/test_run_jtag_dual_hardware.py` | `a2d7de48f0d91b3edf26ee147edc53f3915099891352a3f7ca172b91ea85fefa` | offline controls, 47 tests: 39 wire/mode/catalog + 8 synthetic six-page admission/refusal controls (software only, never hardware evidence) |
| `tools/host/run_jtag_ew_hardware.py` | `d606d9eabd0007158564ba4dd9736dd111d447c58b5c85b0d120d172c246539a` | **pinned EW physical replay wrapper**: exact EW image/tag binding, admission+authorization gates, raw captured-BO replay with complete owned-BO compare before ACK, E1 negative, never programs; offline `--check` |
| `tests/host/test_run_jtag_ew_hardware.py` | `022ff8c7a236529e7fb00d850a945429e616147a6ebcb2720f63f04d531c1617` | offline controls, 13 tests: 9-case plan exactness, complete-BO-before-ACK, no ACK on mismatch, E1+poisoned-owner, offline check, authorization/admission/cable refusals (no hardware/network) |
| `build/board-prep/20261110T080059Z-ew-check/receipt.json` | `bd10621b74ae52b344268e63eccd19d1c788acf170c5edaeb4f3ff4d426e67f6` | EW wrapper `--check` dry-run: `PASS_CHECK_PENDING_ADMISSION`, exit 0, 9 cases/872,448 B, `hardware_accessed=false` (admission pending) |
| `build/board-prep/20261110T080059Z-ew-refused-noauth/receipt.json` | `365ffcdbe776e7e3ef1d64dc43123840bb59850f904bda65adf7fd5f30113d01` | EW wrapper hardware refusal: no `--authorized`, exit 2 `REFUSED`, nothing opened |
| `build/board-prep/20261110T080059Z-ew-refused-admission/receipt.json` | `023685f5e78307de13d661d904e02b50090ae09a50a8e419db6a157940b0b1ce` | EW wrapper hardware refusal: admission pending, exit 2 `REFUSED`, nothing opened |
| `tests/host/test_board_image_inventory.py` | `715085611f21eb4a5ba1a16b93bbdfac501346335d1507a004125bca46f34eff` | offline checker for the §15/§16 tables: family inventory, real bitstream SHA-256 match (adopted/historical/EW), EW gates+`USR_ACCESS`+admission assertions, PENDING task-10 placeholder, tooling entry points, class-D items and evidence paths |
| `tools/host/jtag_preflight.py` | `8ff1a2371a7e8451f7ca80882e9b6e995d5b7404cff4babd06cb002a1407127b` | strictly read-only readiness preflight (no lease/USB/server/socket/programming); multi-family image inventory (§15.1) including `bitstream/*.bit` emission dirs; receipt binds its own source hashes |
| `tests/host/test_jtag_preflight.py` | `e43f7d793d17c67466e1adbdd10d266d5087d07de7ccb9dffef0f5d93f08e3cb` | offline controls, 19 tests: cable-stage classification, prerequisites derivation, lease `/proc/locks` parse, six-page preference, CLI state matrix, multi-family catalog inventory (missing/PENDING catalogs and the EW emission `bitstream/` layout) |
| `build/jtag-dual-image/20261109T160627Z/inputs.json` | `574c727ca0a8ebe4940bb8f1401e8316ac6903abc932e753415281e6d48c3f9f` | adopted six-page image receipt: `PASS`, WNS +3.952 / WHS +0.054, six-page gate, `hardware_accessed=false`, `source_match: true` |
| `build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit` | `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` | **adopted six-page bitstream**, 18,735,215 bytes; never hardware-tested |
| `build/jtag-dual-image/20261109T160627Z/ADOPTION_PROVENANCE.md` | `c5971d8a11e1b297da332658f1f36585b9e95a0992939c97c3e710f8d0b915b0` | provenance: option-A snapshot build, main tree restored, 73/73 input equality, and build-owner attestation of the exact build environment (`RK_CONFIG_VOLTAGE=1.8`, `RK_CFGBVS=GND`, `RK_LED_ACTIVE_LOW=0`, board confirm) |
| `build/jtag-dual-image/20261109T160627Z/build.tcl` | `39be1aa074d849de39ee01b1457393d86b57ecc16a66c1d9aff784c0c7e0df05` | rendered build; six-page presence gate lists all six pages |
| `build/timing-lab-share/a_only_adoption_manifest.json` | `0e1647cccc8683177fd1266e148df8f2cb93cf8391424e04cfea21a4cf98aea7` | 73/73 byte-identical build inputs: snapshot vs adopted main tree |

| `build/rk3588-live-verify/P1-SUMMARY.md` | `89f9b4facc17669901c4bc06490ed4f110c2f4a762b1eb74eae7bf17e1d765a9` | P1 family-wide live RK3588 differential: 38/38 READY PASS, race control, padding class-D documentation |
| `build/rk3588-live-verify/P1-INDEX.json` | `433c39b2b5277255b9d197fb1eed3218ac67c45721a5f5732c519e2f49b15727` | machine-readable P1 index (J10/J10b/J11/J12 cases, oracle results, padding analysis) |
| `build/rk3588-live-verify/20261109T213515Z-j10/job-receipt.json` | `c7121856ddf6f90e595ea8987109856221ab396ba17e6a2ad2a93df2ff0670ea` | J10 conv-fp16 run receipt (9/9 defined-lane exact; full-BO 5/9 padding-limited) |
| `build/rk3588-live-verify/20261109T213515Z-j10/J10-PADDING-ANALYSIS.json` | `8125edab01663e658f559bc48b1a69c04ce356f0c7c52581bf152311c97a88ad` | padding-lane analysis: undefined, non-deterministic aligned channel-plane padding (class-D) |
| `build/rk3588-live-verify/20261109T213515Z-j10/oracle-check-conv-fp16.json` | `487f136ce40dd577ecd3f850102cdc734a269e7dbb5bfdb3e96d4a0f7b4146d3` | conv-fp16 family logical oracle re-check: 9 PASS at atol 0 |
| `build/rk3588-live-verify/20261109T213906Z-j10b/job-receipt.json` | `f8d266e8e19a3d514b779e6f6d83a19f3c32e9b1af5340159b48e237ff76afc9` | J10b repeat probe: runA==runB in-context; padding differs across allocation contexts |
| `build/rk3588-live-verify/20261109T213726Z-j11/job-receipt.json` | `bac38396056abb65ed2c77cadc382d46ca21a014c9e45849e9d00e1e69cba011` | J11 conv-gemm-vendor run receipt (10/10 live complete-BO exact) |
| `build/rk3588-live-verify/20261109T213726Z-j11/oracle-check-conv-gemm.json` | `d0ee4a9eaa7a06591004180ccca10964e3769e613d6e2dea2b39de0eac659330` | J11 logical oracle re-check: 8 exact + 2 tolerance PASS |
| `build/rk3588-live-verify/20261109T213755Z-j12/job-receipt.json` | `5d66c473ea41da95de99c22144b7c1e2b170017bb44869f151189c677bd88bd0` | J12 pooling run receipt (19/19 complete 4096-byte BO exact) |
| `build/rk3588-live-verify/tools/live_job.py` | `b34bd2a461fb0300ace15a3f1ad179486bb7e3ddbf51f89da3747ac5e43ebe0e` | P1 race-controlled live job harness (flock, preflight/postrun, stage/fetch hashes) |
| `build/rk3588-live-verify/tools/p1_analysis.py` | `1a071fb951c5a2b5cc4c9eca6db4ebdaf0aa2878e3716448b517a70fa396a0a9` | P1 comparison/analysis tool |
| `build/rk3588-live-verify/tools/make_p1_specs.py` | `ec7c8337184cff4e853a8f0584423db249c67f5bb277a98e64a4303c785e9cb2` | P1 spec generator |
| `build/rk3588-live-verify/tools/specs/J10.json` | `23db87b70b35a74ade06156f5e293f9141cb49a0b60d405924ec3773b67ad8af` | J10 conv-fp16 spec |
| `build/rk3588-live-verify/tools/specs/J10b.json` | `83048e4e139f15138e28dfede07ce500e4f73211df76aebbd9726f9741a82c8c` | J10b repeat-probe spec |
| `build/rk3588-live-verify/tools/specs/J11.json` | `197ee306d891b4aa998726dc6f1761c9b604983461e53f8b6130b3c758c11707` | J11 conv-gemm-vendor spec |
| `build/rk3588-live-verify/tools/specs/J12.json` | `f6ea535c56b5ca72a90291adbfdfaced19d6d9a5aa923bbd0bc34a05d97ba88d` | J12 pooling spec |

The harness, preflight and their test files change with edits; recompute their
hashes with `sha256sum` if the tree has moved. Harness run receipts record
their inputs in `source_hashes_before`/`source_hashes_after` and fail closed if
they change on disk during the run; the preflight receipt records its own
source hashes.

## 11. Verification performed for this deliverable (no hardware)

| Command | Observed result |
|---|---|
| `python3 -m py_compile tools/host/run_jtag_dual_hardware.py tools/host/run_jtag_ew_hardware.py tools/host/jtag_preflight.py tests/host/test_run_jtag_dual_hardware.py tests/host/test_run_jtag_ew_hardware.py tests/host/test_jtag_preflight.py` | exit 0 |
| `python3 -m unittest tests.host.test_run_jtag_dual_hardware tests.host.test_jtag_preflight tests.host.test_board_image_inventory tests.host.test_run_jtag_ew_hardware` | **Ran 85 tests in 0.84 s — OK** (47 dual harness + 19 preflight + 6 multi-image inventory + 13 EW wrapper; no hardware/network). Covers: wire-identical frames/payloads/polling vs `transport.JtagTransport._command`; sequence wrap; status 4/7/0x80 and response-magic/payload rules; quarantine refusing further scans; BO helpers; FP32 compare model; all seven fixture plans and BO windows; mode 5/6 page refusal; emitted-image catalog/page-gate parsing; `--check` offline with sockets/subprocesses asserted unused; hardware refusal without `--authorized`; argument validation; fake-device end-to-end orchestration; multi-family catalog inventory (missing/PENDING catalogs report as absent; the EW emission bitstream is listed); doc §15/§16 inventory checker (family rows, real bitstream SHA-256 match for the adopted/historical/EW images, remaining PENDING task-10 placeholder, tooling entry points, class-D required items) |
| `python3 tools/host/run_jtag_dual_hardware.py --check --image 81eef4…4d39` (default mode set) | exit 0, **`PASS_CHECK` six-page receipt `b82484d2…1a28d7`**, modes `[0,1,2,3,4,5,6]`, `hardware_accessed=false`, sources 73/73 matched |
| same `--check` against the historical four-page `73dd…4cf7` (default modes) | exit 1, `CHECK_BLOCKED` for modes 5/6 — receipt `aa3c44f6…722dbf` (intentional; superseded by the adopted six-page image) |
| hardware invocation without `--authorized` | exit 2, `REFUSED` receipt `368941d9…b2e606`, nothing opened |
| synthetic six-page PASS catalog (software control, not evidence) | `--check` exit 0, modes 0–6, `PASS_CHECK` receipt `build/board-prep/20261109T153248Z-six-page-synthetic-control/check/receipt.json` (`b6ae2552…89adfb`), `hardware_accessed=false` |
| `python3 tools/host/jtag_preflight.py` in the current no-cable state (multi-image inventory, EW-wrapper re-run) | exit 2, `PASS_PREFLIGHT_NOT_READY`, receipt `build/board-prep/20261110T080556Z-preflight-ew-wrapper/receipt.json` (`a8c0e1d4…60e6841`); cable `absent`, prerequisites OK, lease free, preferred six-page `81eef4…4d39` modes 0–6; inventory lists jtag-dual 12 dirs (2 emitted PASS), 10 host-jtag-preparation dirs including the **EW emission bitstream `b373ee70…f59a`**, 11 pooling-image work dirs with **no bitstream yet (task-10 pending)**, 3 historical ppu images; all read-only flags false |
| adopted-image source audit | receipt `source_match: true`; 73/73 recorded sources byte-identical to the adopted main tree (adoption manifest `0e1647cc…`, provenance `c5971d8a…`) |
| EW image emission/admission (task-9) | bitstream `b373ee70…f59a` (18,735,213 B) + image.dcp `75fe964a…89c5` verified by SHA-256; `REBUILD_RECEIPT.md` gates: WNS +0.670/WHS +0.053, 0/23,204 failing setup, 10,829/10,829 routed nets, 0 `no_clock`/unconstrained endpoints, 6,157 LUTs/256 BRAM, DRC warnings only, marker `PASS_SOURCE_REVIEWED_USER2_EW_BITSTREAM_EMISSION`; `python3 tools/host/prepare.py verify build/host-jtag-preparation/20261109T210015Z` -> `SOURCE_INTACT_REVIEW_PENDING`, blocker `Missing board reviewer`; no hardware accessed |
| P1 family-wide live RK3588 differential (rkref; **no FPGA load**) | **38/38 READY PASS**: conv-fp16 9/9 defined-lane exact (full-BO 5/9 due to the class-D padding record), conv-gemm-vendor 10/10 complete-BO exact (8 exact + 2 documented tolerance), pooling 19/19 complete 4096-byte BO exact; one board runner under flock with J00 preflight / `NO-SUBMIT-PROCS` post-run and stage/fetch hash verification; receipts `build/rk3588-live-verify/{P1-SUMMARY.md,P1-INDEX.json,20261109T213515Z-j10,20261109T213906Z-j10b,20261109T213726Z-j11,20261109T213755Z-j12}`, hashes in §10; no RTL edit, no FPGA programming/flash |
| EW pinned replay wrapper (task-20, offline) | `tools/host/run_jtag_ew_hardware.py` (sha in §10) + 13 offline tests: 9-case plan exactness (872,448 B), complete-BO-before-ACK, **no ACK on any byte mismatch**, E1+poisoned-owner expected/silent-accept failure, offline `--check` with sockets/subprocesses asserted unused, wrong-SHA/tag and no-authorization/pending-admission/absent-cable refusals; dry-run: `--check` exit 0 `PASS_CHECK_PENDING_ADMISSION` (`bd10621b…`), hardware no-auth exit 2 `REFUSED` (`365ffcdb…`), admission-pending exit 2 `REFUSED` (`023685f5…`); `hardware_accessed=false` throughout |
| `python3 -m unittest tests.host.test_board_image_inventory` | **Ran 6 tests — OK**: §15.1 inventory rows (6 columns, families covered), real bitstream files exist and SHA-256 fields match (adopted `81eef4…4d39`, historical `73dd…4cf7`, emitted EW `b373ee70…f59a`; image.dcp `75fe964a…89c5`), the EW row carries its gates/`USR_ACCESS=ec9ecd41`/`SOURCE_INTACT_REVIEW_PENDING`, PENDING task-10 row carries no real SHA and says unloadable, §15.4 tooling entry points exist, §15.2 switching rule and §16 class-D items present with existing evidence paths. Software control only — it validates documentation/inventory consistency, never hardware |

All FPGA-side receipts above were produced without a cable, without opening
the lease, and without starting `hw_server`/Vivado; they record
`hardware_accessed=false`. The P0/P1 live rows are RK3588-board evidence
produced under the user's explicit live-NPU authorization and the board
`rk3588-npu.lock` flock; they programmed no FPGA and are not FPGA-board runs.

## 12. Ordered checklist for the real run

0. `python3 tools/host/jtag_preflight.py` — read-only state check; exit 2
   until the cable is initialized and all prerequisites are in place, then
   exit 0 with the exact next commands (including the preferred image hash and
   its mode list). See §8.0 and the one-screen §13.
1. **User decisions A–F in §2 recorded** (authorization + board identity +
   LED polarity + configuration bank + no-flash + source-tag acceptance).
2. Plug in the DLC10; `lsusb -d 03fd:0013` shows exactly one pre-init node.
3. Run `bash ~/ypcb/dlc10-init.sh`; PASS with IDCODE `0x23751093`; node
   `03fd:0008`; no cable tool running during init.
4. Read-only target audit (§5) under the lease: DNA `004E544714C705C`, one
   exact target URI, IDCODE `23751093`, `CFGBVS_PIN=0`; save TSV/properties.
   Stop the owned server and release the lease.
5. Load the adopted six-page bitstream in §6A (audited) or §6B (weaker);
   confirm `INIT=1 DONE=1`, IDCODE before/after, `USR_ACCESS=00000000`, DNA
   unchanged, bitstream SHA-256 `81eef4…4d39`; no flash command used. Stop
   `hw_server`.
6. Run the offline check (§8.1) against the adopted image hash with the default
   mode set (modes 0–6); keep the receipt. Expect `PASS_CHECK` exit 0.
7. Run the harness (§8.2) with `--authorized --source-tag none`, the adopted
   image hash and modes 1–6 then 0 (the default mode set), and authorization
   wording copied verbatim from the user.
8. Collect the evidence table in §9; archive the receipt directory; do not
   delete or relabel a failing receipt.
9. Cleanup: harness already stopped its `hw_server`/bridge and released the
   lease; confirm `pgrep -x hw_server` empty and the lease file empty; flash
   untouched. If mode 0 ran, the bridge is quarantined — reload the volatile
   image (§6) before any further mailbox work; a new server/reconnect alone
   does not clear it.
10. Report: image SHA `81eef4…4d39`, board identity values, per-mode
    PASS/compare numbers for modes 1–6 plus the mode 0 contract,
    `hardware_accessed=true`, `flash_written=false`, and every receipt hash.

## 13. When the cable appears — one-screen sequence

Run in this order; every hardware step needs the user's explicit authorization
first (§2). The preflight and offline check never touch the card.

1. **Read-only preflight** (repeat after each state change):
   `python3 tools/host/jtag_preflight.py`
   Expect exit 2 with `cable_stage=absent` before the cable; after plug-in
   expect `pre_firmware` (`03fd:0013`); after cable init expect exit **0**,
   `cable_stage=initialized` (one `03fd:0008`), no `hw_server`, no controller
   process, debug ports closed, lease free, prerequisites OK, preferred image
   and its supported modes printed.
2. **Plug in the DLC10** (single cable): `lsusb -d 03fd:0013` shows exactly one
   pre-firmware node.
3. **Cable init** (§7): `bash ~/ypcb/dlc10-init.sh` → PASS with
   `idcode 0x23751093`; node becomes `03fd:0008`. No cable tool may be running.
4. **Read-only target audit** (§5): owned `hw_server` under the lease; expect
   DNA `004E544714C705C`, IDCODE `23751093`, INIT/DONE, `USR_ACCESS`,
   `CFGBVS_PIN=0`; stop the server, release the lease.
5. **Offline check** (§8.1) with the adopted image hash
   `81eef4cd…4d39` and the default mode set (0–6):
   `python3 tools/host/run_jtag_dual_hardware.py --check …`; expect
   `PASS_CHECK` exit 0 (no hardware opened).
6. **Volatile load** of that exact image only — adopted six-page
   `81eef4cd…4d39` (§6A audited route, or §6B with its weaker evidence):
   expect `INIT=1 DONE=1`, IDCODE before/after, DNA unchanged, `USR_ACCESS`
   equal to the source-tag expectation; stop any `hw_server`; **never flash**.
7. **Harness run** (§8.2) with `--authorized --source-tag none` (or the real
   8-hex tag), image `81eef4cd…4d39`, modes 1–6 then 0 (the default set), and
   the user's exact authorization wording; mode 0 runs last automatically.
8. **Evidence capture** (§9): receipt directory, per-mode receipts/readbacks,
   bridge/hw-server logs, target/program TSVs, all hashes. Keep failures too.
9. **Cleanup** (§8.2/§12): harness stops its own server and releases the lease;
   confirm `pgrep -x hw_server` empty and the lease unheld; after mode 0 the
   bridge is quarantined — reload the volatile image before any further
   mailbox work.

Image selection when a new emission lands:

| Catalog state | Preferred image | Modes | Rule |
|---|---|---|---|
| **Current catalog:** adopted six-page `81eef4cd…4d39` | `build/jtag-dual-image/20261109T160627Z` | 0–6 | **preferred image to load** once the user authorizes; sources match the adopted tree 73/73; **not hardware-tested yet** |
| Four-page `73dd0365…4cf7` | `build/jtag-dual-image/20261109T073000Z` | 0–4 | interim/**historical** fallback only; its sources no longer match the current tree; never cite its results as current-RTL evidence |
| A newer six-page PASS receipt replaces the adopted one | newest six-page receipt (catalog sorts by page count, then timestamp) | 0–6 | accepted automatically by `--check`/harness (page-gate driven, no code change); re-run `--check`/preflight and bind the new hash; do not mix image hashes across a session |
| The EW image `b373ee70…f59a` (separate volatile image) | `build/host-jtag-preparation/20261109T210015Z-emission/` | USER2 mailbox frames, EW families only | needs admission `SOURCE_INTACT_REVIEW_PENDING` → reviewed before load; each EW load is a separate per-family authorization (§15) |
| Live RK3588 differential (P0/P1, **no FPGA load**) | — | conv-fp16 9/9 defined-lane, conv-gemm-vendor 10/10, pooling 19/19 (receipts §10/§16.1) | family RTL/fixture evidence only; it does **not** replace the FPGA-bitstream run above and needs no cable |
| A six-page receipt exists but is `FAIL`/`bitstream_emitted=false` | unchanged: last adopted PASS image | — | refused explicitly; never edit a status to obtain a bitstream |

## 14. Known blockers and open facts at preparation time

1. **Cable not attached** (§3): no `03fd:0008` or `03fd:0013` device at all.
2. **No fresh user authorization** for loading the adopted image or running the
   host tests (§2 A–G). Prior authorization text on file is only for the
   2026-10-27 EW image.
3. **Six-page image has no `USR_ACCESS` tag** (the EW image is tagged
   `ec9ecd41`): the audited bridge's source-tag check for the six-page image is
   the "untagged" value `00000000` (§2 F); pass `--source-tag none` there and
   `--source-tag ec9ecd41` for the EW image. Recommended fix for the six-page
   flow is a build-side tag at its next emission (no RTL semantics change).
4. **The adopted FPGA image is not board-tested** (`hardware_accessed=false`
   in its receipt). Six-page timing and bitstream emission are closed (WNS
   +3.952 ns / WHS +0.054 ns), and its RTL families now have live RK3588
   differential evidence (P0/P1: conv-simple 4/4, GEMM 4/4, pooling 19/19,
   conv-fp16 9/9 defined-lane, §16.1), but **no bitstream has been loaded on
   the YPCB card**. That remains gated on the cable plus user authorization;
   live RK3588 evidence does not replace the board run.
5. **Board electrical facts** LED polarity and configuration-strap remain not
   measured (§2 C/D). The build-owner attestation in `ADOPTION_PROVENANCE.md`
   records the explicit build environment (`RK_CONFIRM_BOARD=YPCB_00338_1P1`,
   `RK_CONFIG_VOLTAGE=1.8`, `RK_CFGBVS=GND`, `RK_EMIT_BITSTREAM=1`,
   `RK_LED_ACTIVE_LOW=0`; the Tcl refuses emission without a compatible pair)
   and `LED_ACTIVE_LOW=0` is visible in the receipt log. These remain
   donor-derived values, **not** a strap measurement: confirm them on the real
   card in the authorized session before loading.
6. **Source binding**: the adopted image matches the current tree 73/73 at
   adoption time (`source_match: true`, adoption manifest); the historical
   four-page image does not. Bind the exact image SHA in every receipt; later
   tree edits do not invalidate the image but are not covered by its results.
7. **Other families are separate images**, not covered by the six-page image:
   the EW image is **emitted** (`b373ee70…f59a`) but its admission is
   `SOURCE_INTACT_REVIEW_PENDING` (missing human board reviewer), and the
   pooling-corpus image is **PENDING task-10** (no bitstream yet); conv-fp16 and
   ew-int have no image page. The multi-image deployment procedure is §15;
   vendor-ABI, multi-task and dtype/shape limitations are recorded in §16.

## 15. Multi-image deployment (families → image → transport)

No single volatile image carries every example family today. Each family is
deployed by loading its own image over JTAG and then running that image's host
entry point. **Flash is never written**; every volatile load and every replay
receipt binds the exact image SHA-256 from the table below. There is no warm
switch between families: switching images is a new volatile load.

### 15.1 Image inventory

Rows 1–3 are real emitted bitstreams catalogued under `build/` (the EW image
landed in task-9); row 4 is the pooling-corpus image still being built by
task-10; rows 5–6 are the remaining families with no host-drivable image page.
The offline preflight lists all catalogs read-only (§8.0) and prints the same
SHA prefixes.

| Family / example cases | Image / receipt | Bitstream (path + SHA-256) | Host transport / entry point | Coverage / modes | Status |
|---|---|---|---|---|---|
| conv-simple profiles p0–p3 (3x3 C4, 5x5 C4, C16, FP32 p3) + one signed-INT8 max k2s2 C16 pooling case + four frozen GEMM shapes; `conv_simple.py`, GEMM part of `gemm.py`/`conv_gemm.py`, one `pooling.py` case | `build/jtag-dual-image/20261109T160627Z` (adopted) | `build/jtag-dual-image/20261109T160627Z/implementation/rk_jtag_dual.bit` — SHA-256 `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` | `tools/host/run_jtag_dual_hardware.py` (USER2 mailbox, modes 0–6; offline `--check`) | job modes 1–4 + mode 0 contract; 1–4 include the 5x5/C16/FP32 pages | PASS emitted, not FPGA-board-tested; family live RK3588 differential: conv-simple 4/4 exact (P0 J01/J05), GEMM 4/4 (P1 J11), pooling 19/19 (P1 J12) |
| historical four-page subset (conv p0, pooling, GEMM, conv FP32 p3); no k5/C16 pages | `build/jtag-dual-image/20261109T073000Z` (interim/historical) | `build/jtag-dual-image/20261109T073000Z/implementation/rk_jtag_dual.bit` — SHA-256 `73dd0365055b4664c2d8d05af634d05a754cc333808fd2ed1c5d974706c94cf7` | `tools/host/run_jtag_dual_hardware.py` with explicit `--mode` 0–4 | modes 1–4 + mode 0 contract | historical fallback; sources no longer match tree; same RTL families carry the P0/P1 live evidence |
| ew-fp16 54 cases (ADD/SUB/MUL/MAX/NEG/FDIV, widths 1/7/8/9/33/1024), `simple_add.py`, `fdiv-systematic` 8 cases; FDIV end-to-end (regs→engine→ALU) | `build/host-jtag-preparation/20261109T210015Z` (prepare package) + `build/host-jtag-preparation/20261109T210015Z-emission/` | `build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit` — SHA-256 `b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a`, 18,735,213 B | USER2 mailbox frames (RKEW BRAM ABI, 1 MiB at `0x10000000`) via `tools/host/transport.py` + `tools/host/native_link.py`; raw final command BOs from the captured fixtures via `tools/dma_fixtures.py`; prep/admission `tools/host/prepare.py` | ew-fp16 54 + simple_add + fdiv-systematic 8 through one image; USER2 frames only | PASS emitted, marker `PASS_SOURCE_REVIEWED_USER2_EW_BITSTREAM_EMISSION`; gates WNS +0.670 / WHS +0.053, 6,157 LUTs, 256 BRAM, 10,829/10,829 routed nets, image.dcp SHA `75fe964a…89c5`; tagged `USR_ACCESS=ec9ecd41`; **admission SOURCE_INTACT_REVIEW_PENDING (Missing board reviewer)**; not FPGA-board-tested; FDIV path live 1,452/1,452 (P0 J06/task-11) |
| pooling corpus: 19 READY + 1 source-derived fixture (max/min/avg/index, INT8/INT16/FP16, k2s2/k3s3, pad/tail/global) | PENDING task-10 (design frozen; `build/pooling-image/` has simulation/synthesis artifacts, no bitstream yet) | PENDING task-10 (no bitstream yet) | transport selected by task-10; current `fpga/ypcb_ppu_i8_top.sv` is AXI-Lite/BRAM only, so a host transport (candidate: the six-page USER2 page pattern) is part of task-10 | all-fixture complete 4096-byte BO replays | PENDING task-10; 19/19 Icarus replay PASS, bitstream pending; RTL leaves live-verified 19/19 on RK3588 (P1 J12) |
| conv-fp16 9 captured cases / 8 vendor-profile cores; conv part of `conv.py`/`conv_gemm.py`/`conv_legacy.py` | not planned (too large for the six-page image) | not planned (no image page) | simulation only: `tools/conv/run_3x3_valid_c4.py` and `tools/conv/run_conv_simple_axi.py` | simulation replays only | class-C gap, no FPGA deployment; RTL leaves live-verified 9/9 on defined lanes (P1 J10, §16) |
| ew-int 15 captured cases; `expt/elementwise_int.py`, `kernel_6_18/elementwise_int.py` | not planned (no integer EW RTL) | not planned (no image page) | simulation only (no integer-EW entry point exists) | none | class-C gap, no FPGA deployment |

Historical note: `build/ppu-image/20261108T170500Z` is a single-case
INT8 max k2s2 C16 self-test image (AXI-Lite/BRAM only, no host transport, no
physical run); it is not part of the deployment inventory. Older two/three-page
`jtag-dual-image` receipts are likewise historical and not loadable choices.

### 15.2 Volatile-load-only rule and switching between families

Every row in §15.1 is deployed the same way, one image at a time:

1. **User authorization for that image** (§2 A) and a recorded authorization
   wording; that row's image SHA is copied from §15.1, never inferred. Rows
   still marked PENDING cannot be loaded at all.
2. Read-only preflight (§8.0) and read-only target audit (§5) under the shared
   lease: one DLC10, exact target URI, DNA `004E544714C705C`, IDCODE
   `0x23751093`.
3. **Volatile JTAG load of exactly that image** (§6A audited route, or §6B with
   its weaker evidence). Confirm `INIT=1`, `DONE=1`, IDCODE before/after, DNA
   unchanged, the image's `USR_ACCESS` expectation, and the loaded image's page
   identities (per §9). **Never write flash**; no `-b`/`-f`/`--fpga-part`,
   `flash_jtag.sh program`, `boot_hw_device` or `openFPGALoader --flash`.
4. Stop the loader's `hw_server`; the family's host entry point then starts its
   own server/bridge (six-page harness does this itself).
5. Run that image's replay; capture the complete BO readbacks and compare
   against the frozen fixtures. Save the receipt directory undedited.
6. **To switch families, repeat steps 1–5 with the other image SHA.** Volatile
   SRAM is replaced by the new load; nothing persists across the switch and no
   result may be attributed to the other image. A mode-0 run quarantines the
   six-page mailbox, so a reload is required before any further mailbox work on
   that image (§8.2).
7. Cleanup after the last image: owned `hw_server` stopped, lease released,
   `pgrep -x hw_server` empty, flash untouched; record it in the receipt.

Permission boundary: **every** image here is volatile-SRAM only. There is no
image in this table authorized to write/erase flash, change boot mode, or
persist configuration; the JTAG cable may only load configuration SRAM and
scan the mailbox.

### 15.3 Per-image evidence requirements

| Evidence | six-page adopted (§15.1 row 1) | four-page historical (row 2) | EW image (row 3, emitted) | pooling image (task-10) |
|---|---|---|---|---|
| Image identity bound | bitstream SHA `81eef4…4d39` + receipt SHA in the harness receipt | bitstream SHA `73dd…4cf7`; never cite as current-RTL evidence | bitstream SHA `b373ee…f59a` + prepare-package source sha256 `ec9ecd41…4d88`; **tagged** `USR_ACCESS=ec9ecd41`; admission `SOURCE_INTACT_REVIEW_PENDING` | `PENDING task-10`; bind once emitted |
| Program/instrument receipt | §6A program TSV: target, DNA, IDCODE before/after, INIT=1, DONE=1, USR_ACCESS, clean exit | same | same §6A flow with the EW bitstream path and expected `USR_ACCESS=ec9ecd41`; admission must leave `SOURCE_INTACT_REVIEW_PENDING` first | same, pooling image path |
| Read-only target audit | §5 TSV + device-properties | same | same | same |
| Loaded-image identity | page identities `524b4353`/`524b5050`/`524b434d`/`524b4415`/`524b4416`/`524b4417` at `0x8000`/`0x9000`/`0xa000`/`0xb000`/`0xc000`/`0xd000` | four page identities at `0x8000`–`0xb000` | RKEW identity `0x524b4557` + ABI `0x00010000` after load (no page map) + `USR_ACCESS=ec9ecd41` | page identities chosen by task-10 |
| Replay evidence | harness mode receipts + `mode-<n>-output.bin` (4096 bytes each) + `mode-<n>-ops.jsonl` + bridge log/READY | same harness receipt fields | pinned `tools/host/run_jtag_ew_hardware.py`: 9-case raw-BO replay, complete owned-BO readback/compare before ACK (872,448 B total), E1 negative last, wrapper receipt + per-case receipts | per-fixture complete 4096-byte BO compare receipts |
| Negative/refusal evidence | mode 0 status 4 and status 7 + quarantine | mode 0 status checks | explicit synthetic unknown-register E1 expectation (prior EW physical pattern) | unsupported-write SLVERR expectation |
| RK3588 live differential (no FPGA load) | conv-simple 4/4 exact + class-A divergences (P0), GEMM 4/4 and pooling 19/19 (P1), receipts §16.1 | same families (historical image) — live evidence is RTL-family level | conv-fp16 9/9 defined-lane (P1 J10); FDIV 1,452/1,452 (P0 J06/task-11); no EW-family live queue yet | pooling 19/19 (P1 J12); no image yet |
| Non-claims | `hardware_accessed=true`, `flash_written=false`, image not current-RTL for rows 1–2 sources; no cold boot/PCIe/RK equivalence | | EW admission is still REVIEW_PENDING (human board gate); no FPGA-board run yet; raw-command path only, no tensor API | |

Every receipt records `hardware_accessed`, the exact image SHA-256, the target
identity, and `firmware_loaded`/`flash_written` flags; a missing field is a
failure, not a pass.

### 15.4 Host tooling map

| Family / stage | Entry point | Prerequisites | Offline check / dry-run | Status |
|---|---|---|---|---|
| six-page/dual image, real board | `tools/host/run_jtag_dual_hardware.py` (with `tools/host/native_link.py` and `tools/host/transport.py`) | initialized DLC10 `03fd:0008`, exact `--target`, `--lease`, `--authorized`, catalogued emitted `--image`, `--source-tag` | `python3 tools/host/run_jtag_dual_hardware.py --check` (fixtures, plan, image SHA, page map; no hardware) | READY offline; hardware pending user authorization |
| six-page/dual image, simulation | `tools/host/run_jtag_dual.py` | Icarus/Verilator, frozen fixtures | `python3 tools/host/run_jtag_dual.py --simulator verilator` | READY |
| board readiness | `tools/host/jtag_preflight.py` | `/proc`, `lsusb`, `ss`, `~/ypcb` tooling; then cable/lease for a real session | `python3 tools/host/jtag_preflight.py` (strictly read-only; exit 2 until ready) | READY offline |
| EW image preparation | `tools/host/prepare.py` (`prepare`/`verify`/`command`) + `tools/host/image_template.py` + `tools/host/qualification.py` | two source-bound simulator reports; `fpga/host/sources.json`; no Vivado until `command` is run by the authorized builder; human board review required for admission | `python3 tools/host/prepare.py verify build/host-jtag-preparation/20261109T210015Z` (expect `SOURCE_INTACT_REVIEW_PENDING` until a board reviewer signs); `make host-jtag-preparation-test` | **DONE — image emitted** (`b373ee70…f59a`); admission `SOURCE_INTACT_REVIEW_PENDING` (Missing board reviewer) |
| EW image physical replay | **pinned wrapper** `tools/host/run_jtag_ew_hardware.py` (Lead-approved basis: archived `verification/runs/2026-10-27-host-user2-fpga/hardware/run_sram_tests.py` + `verification/runs/2026-10-27-host-user2-fpga/hardware/run_jobs.py` + `tools/host/transport.py`/`native_link.py` + `tools/dma_fixtures.py`): USER2 mailbox / RKEW ABI, raw captured-BO replay, complete owned-BO compare before ACK, E1 negative, owned `hw_server`+audited bridge, never programs | EW image emitted (`b373ee70…f59a`, `USR_ACCESS=ec9ecd41`); human board-review admission must be `READY_FOR_SEPARATELY_AUTHORIZED_BUILD`; initialized DLC10; lease; **per-family user authorization** (separate from admission) | `python3 tools/host/run_jtag_ew_hardware.py --check --image b373ee70…f59a --source-tag ec9ecd41 --target localhost:3125/xilinx_tcf/Xilinx/80802026a77a01 --lease /home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock` → `PASS_CHECK` when admission is ready, or `PASS_CHECK_PENDING_ADMISSION` (exit 0, `hardware_accessed=false`) while the human board reviewer is pending; hardware runs REFUSE (exit 2) without `--authorized`/admission | wrapper pinned + offline-tested (13 tests); hardware replay blocked only on admission + per-family authorization |
| pooling image transport/replay | selected by task-10; current simulation runners are `tools/ppu/run_pool_*.py`, build tool `tools/ppu/vivado_ppu.py` | pooling image receipt and host transport from task-10; initialized DLC10; lease; authorization | offline today: `python3 -m unittest discover -s tests/ppu_pooling -p 'test_*contract.py'` | PENDING task-10 |
| conv-fp16 / ew-int | none (no image page) | — | simulation runners only (`tools/conv/run_3x3_valid_c4.py`; no integer EW path) | class-C gap |

The tooling map is deliberately explicit about what does **not** exist yet:
the EW replay wrapper is now pinned and offline-tested, but the EW image's
human board-review admission (`SOURCE_INTACT_REVIEW_PENDING`, missing board
reviewer) and the user's separate per-family authorization must both clear
before a load; the pooling row is still PENDING task-10. Re-read this table
when task-10 lands and replace its §15.1 placeholder with the emitted
bitstream SHA-256 before any hardware load.

## 16. Class-D items (ABI / device limitations): evidence and lift conditions

Class definitions and the fix-and-rebuild policy are in
`docs/RK3588_LIVE_VERIFICATION_JOBS.md` §7: class **D** is an ABI/device
limitation to record, with no RTL change unless a supported decomposition
exists. Class A items (capture/oracle defects) were reconciled on 2026-11-10;
class C items are increments outside the current images. Nothing below needs a
change to the adopted six-page image.

| Class-D item | Blocked cases and exact evidence | Where documented | What would lift it |
|---|---|---|---|
| Vendor-RKNPU ABI: `core_mask`/`subcore_task` multi-core dispatch | `conv_byk_c160_h14w14_oc320_k3x3`: BY_K path calls `np_submit(... task_count=3, core_mask=0, subcores=((0,1),(0,1),(0,1),(0,0),(0,0)))` and needs an 11-row PC chain; `conv_h40_c160_h40w40_oc320_k3x3`: six-task BY_Y over three cores, 17 PC rows. Rocket has no `core_mask`/`subcore_task` UAPI fields, so no faithful submission exists | `handoff.md` §10; `docs/RK3588_LIVE_VERIFICATION_JOBS.md` J20/§4 and §7; `build/rk3588-example-captures/conv-gemm-vendor/manifest.json` `blocked_reason`; `build/rk3588-example-captures/team/gap-matrix/GAP_MATRIX.md` §5 item 5 and §6 | A Rocket/board submission ABI that can express per-core masks and subcore task splits, or a device-free proof that a single-task decomposition produces the identical captured BO. Not possible with the current UAPI |
| Vendor-RKNPU ABI: self-referential `PC_BASE_ADDRESS` patch | The BY_K 11-row layout patches `PC_BASE_ADDRESS` to the regcmd BO's own DMA address; the bundle schema has no patch kind for a runtime self-referential address. `conv_tiles_vendor_abi_blocked` is the related vendor-ABI case with no Rocket route | `handoff.md` §10; `docs/RK3588_LIVE_VERIFICATION_JOBS.md` J24/§4; `docs/CONV_CAPTURE_INDEX.md`; `build/rk3588-example-captures/conv-fp16/manifest.json` and `build/rk3588-example-captures/conv-gemm-vendor/manifest.json` blocked entries | Bundle schema support for two-pass self-referential patching (place the BO, then patch its own base), or a capture whose `PC_BASE_ADDRESS` is relocatable without self-reference |
| Multi-task transport: Rocket executes only task 0 | Combined parents `conv_grouped_3x3_c4_h5_w5_oc8_g2`, `conv_splitoc_3x3_c16_h9_w9_oc16`, `conv_depthwise_3x3_c3_oc3_h11w28` complete only task 0 on Rocket. The split single-task capture is the contract everywhere else: conv-fp16 is 9/9 exact only as promoted one-task cases, and depthwise task0/task1 are 702/702 exact when frozen individually | `handoff.md` §10; `docs/CONV_CAPTURE_INDEX.md` blocked table; `docs/CONV_GEMM_VENDOR_FIXTURES.md` depthwise resolution; `docs/RK3588_LIVE_VERIFICATION_JOBS.md` J22/§4 | Multi-task submission support in the Rocket/board ABI with task-ordering evidence (then a combined-stage capture can be re-attempted). Until then the promoted single-task captures remain the runnable contract, not a workaround |
| Unsupported dtype/shape (12 manifest cases) | conv-fp16: `conv_3x3_pad_register_fp16_blocked` (no Rocket-capable FP16 builder emits `CNA_PAD_CON0`), `conv_split_k_reduction_blocked` (no accumulation contract; tile offsets zero). conv-simple: `conv_simple_fp16_3x3_c8_h8_w8_oc16_stride2`, `..._samepad`, `..._unpadded_pack`, `conv_simple_fp16_grouped_3x3_c8_h8_w8_oc8_g2`, `simple_conv_int8_addition_c8_h8_w8_oc32`. ew-int: `int32_div_c8_w2` (DIV/FLOOR/CEIL are float semantics, no integer oracle), `fp16_four_input_sum_c8_w1` (FP16 multi-input sum with FP32 BRDMA/NRDMA), `fp16_bs_bn_relu_prelu_c8_w1` (FP16 BS/BN auxiliary stages). pooling: `fp32_max_k2s2_zero_write_c4_h2w2`, `int32_max_k2s2_zero_write_c4_h2w2` (PROC_PRECISION probes with `expect_unsupported=True`) | `build/rk3588-example-captures/team/gap-matrix/GAP_MATRIX.md` §6; per-family manifests `build/rk3588-example-captures/conv-fp16/manifest.json`, `build/rk3588-example-captures/conv-simple/manifest.json`, `build/rk3588-example-captures/ew-int/manifest.json` and `build/rk3588-example-captures/pooling/manifest.json`; `docs/RK3588_LIVE_VERIFICATION_JOBS.md` J21/§4 and §7 class C/D | Per-block contracts and RTL: FP16 pad-register semantics, stride-2/SAME-pad and C8 unpadded packing, grouped FP16, split-K accumulation, INT32 DIV oracle, FP16/FP32 mixed BS/BN, INT32/FP32 PPU precision. Most need capture evidence plus RTL/tests and are outside the strict FP16-EW slice |
| conv-fp16 aligned channel-plane padding is **undefined device output** | For the `align_out_c=32` BO, four spatial single-task cases are non-deterministic in padding: `conv_1x1_valid_c8_h5_w5_oc8`, `conv_3x3_valid_c4_h9_w9_oc4`, `conv_3x3_stride2_c4_h11_w11_oc4`, `conv_3x3_pad1_zero_frame_c4_h9_w9_oc4` show live `0xfc00` vs frozen-capture `0x7c00` NaN variants; the two frozen capture runs also differ from each other and from live. J10b repeat probe: full BO identical runA==runB within one allocation context, but padding differs across allocation contexts (stable across contexts: 0/4). Defined lanes are bit-exact (0 mismatched lanes, atol=0; family logical oracle 9/9 PASS); only complete-BO equality is affected | `build/rk3588-live-verify/P1-SUMMARY.md`; `build/rk3588-live-verify/20261109T213515Z-j10/J10-PADDING-ANALYSIS.json`; `build/rk3588-live-verify/20261109T213906Z-j10b/job-receipt.json`; `build/rk3588-example-captures/conv-fp16/manifest.json` (declares only `out_c` lanes as oracle) | **Comparison-domain limitation — no RTL change and no fixture defect**: use the defined-lane / family logical oracle (or the defined region of `expected.bin`), never full-BO equality, for these padded cases. Byte-stable padding would require a device fill contract that does not exist; none is planned |
| Residual-capture classification (resolved class A, recorded for completeness) | The three conv-simple "rejected" cases are host-oracle defects, not device faults: `conv_simple_fp16_1x1_c32_h8_w8_oc32` (FP32-C32 structural layout, slots 6–7 zero-filled), `simple_conv_int8_5x5_c8_h8_w8_oc32` (7 bytes `expected+1`), `simple_conv_int8_depthwise_3x3_c64_h8_h8_oc64_g64` (13 bytes `expected+1`); conv-gemm-vendor depthwise BO size was 7,552 vs the required 15,104 bytes, and `conv_py_3x3_c32_oc128_h14w14_fullsetup` matched the device surface within the documented 0.12 tolerance. Live device is deterministic and equals the frozen captures | `docs/CONV_SIMPLE_FIXTURES.md` "Device/host-oracle divergences"; `docs/CONV_GEMM_VENDOR_FIXTURES.md` rejection-resolution table; `build/rk3588-live-verify/J05-device-oracles/README.md` + `manifest.json`; `build/rk3588-live-verify/P0-SUMMARY.md`; `docs/RK3588_LIVE_VERIFICATION_JOBS.md` §1b | No lift needed for the classification. Future fixtures must use the device surface; the C32 case still needs a new image page (class C) and the INT8 `+1` device-conversion behaviour needs an explicit contract before RTL use |
| Remaining class-C image/RTL gaps (not class D) | FP32-C32 page absent; INT8 output-conversion contract absent; residual 64 FDIV lanes without prepared bundles (RTL model covers all 1,452 lanes; task-11 closes the live capture); integer EW RTL absent; conv-fp16 pages absent; DPU BS/BN/LUT absent | `docs/RK3588_LIVE_VERIFICATION_JOBS.md` §7 class C and §8 workstreams; `build/rk3588-example-captures/team/gap-matrix/GAP_MATRIX.md` §4–§6; `docs/RK3588_LIVE_VERIFICATION_JOBS.md` J11/J12/J14/J15 | Increment tasks: C32 page + conversion contract RTL; task-11 FDIV capture; integer-EW RTL; a separate conv-fp16 compact/per-profile image; BS/BN/LUT RTL. Each needs its own image SHA and evidence, not a modification of an existing image |

### 16.1 P1 family-wide live differential (2026-11-10)

`rkref` ran the full P1 live differential on the RK3588 target under the
race-control protocol (one board runner at a time under
`flock -x -w 900 /home/opencode-agent/rk3588-npu.lock`, J00-style preflight and
`NO-SUBMIT-PROCS` post-run, fresh remote stage and `--out`, staged/fetched
hashes verified on both sides). **No FPGA was programmed or flashed and no RTL
was edited**; this is RK3588 device evidence for the RTL leaves/fixtures, not
an FPGA-board run.

| family | READY | job run dir | result | criterion |
|---|---:|---|---|---|
| conv-fp16 | 9 | `build/rk3588-live-verify/20261109T213515Z-j10` (+ `20261109T213906Z-j10b` repeat) | **9/9 PASS** on defined lanes/family logical comparison, bit-exact atol 0 (full-BO equality 5/9 only because 4 spatial cases carry undefined aligned padding — class-D row above) | defined-lane / family-logical oracle; not full-BO for those 4 cases |
| conv-gemm-vendor | 10 | `build/rk3588-live-verify/20261109T213726Z-j11` | **10/10 PASS**; every live complete BO == frozen capture exactly; logical 8 exact + 2 documented tolerance-only (`gemm_m4_n32_k64` max abs 9.54e-7; `conv.py` C32/OC128 max abs 0.015625 within the 0.12 bound) | complete BO exact + documented tolerances |
| pooling | 19 | `build/rk3588-live-verify/20261109T213755Z-j12` | **19/19 PASS**; complete 4096-byte BO exact against both frozen capture and raw-BO `expected.bin` | complete-BO exact |
| **total** | **38** | — | **38/38 PASS, 0 unexplained anomalies** | — |

Machine-readable results: `P1-INDEX.json` (jobs J10/J10b/J11/J12, oracle
checks, padding analysis). Per-case logical-oracle re-checks:
`20261109T213515Z-j10/oracle-check-conv-fp16.json`,
`20261109T213726Z-j11/oracle-check-conv-gemm.json`. Integration note: P0
(J01–J06: conv-simple 4/4 exact, pooling smoke, GEMM, determinism, J05
device-oracle class-A reconciliation, FDIV) plus P1 now cover the READY set on
live RK3588; the remaining FPGA-side gate is loading a bitstream on the YPCB
card, not the RTL/fixture behaviour.

Reference hashes for the evidence above (recompute with `sha256sum` if the tree
moves):

| Reference | SHA-256 |
|---|---|
| `handoff.md` | `5cf25d53df372646395599721c003d6c35ce2eb62df1eb2291a4ce483668e6bb` |
| `progress.md` | `cda65436fc2b85beb560422a3436cb5d128927eb80bf897bfdc062978d603c50` |
| `docs/RK3588_LIVE_VERIFICATION_JOBS.md` | `4f436ee7ad36620d818dd7666862ae011c9a523f3efa3e2b37128332f468fef0` |
| `docs/CONV_CAPTURE_INDEX.md` | `9267c5396d033931fb7d56545b2a1d9febbb53b333fa58e6e838e0abb835e4b3` |
| `docs/CONV_GEMM_VENDOR_FIXTURES.md` | `18f0f763bcf7e38d1c9fedd1d89358bf57feef187a174b42266acec3d41ac257` |
| `docs/CONV_SIMPLE_FIXTURES.md` | `7c5d29acdb46f042daa6edbce617cf53e6fe3470c820c8b9d67dc687a661d216` |
| `build/rk3588-example-captures/team/gap-matrix/GAP_MATRIX.md` | `3e06f8013512c3305c422b0857f250fd180125766067a622702c96ead3c66100` |
| `build/rk3588-example-captures/team/gap-matrix/EXAMPLE_MATRIX.json` | `9c1ae67ff3ad235d760815fcec5b7f1a70147cf976689cbc8a2ad5c4b6dc1417` |
| `build/rk3588-example-captures/conv-fp16/manifest.json` | `792930d0ec813b92147b74c109d226042acba80abb78e40725f26f17988c98c7` |
| `build/rk3588-example-captures/conv-gemm-vendor/manifest.json` | `2ad7501c16a7cdb17971c4374b2b06aba5bdc2cfc587bc307dfb9ae1756ff9aa` |
| `build/rk3588-example-captures/conv-simple/manifest.json` | `649ef4eb5f01e4ed46698e5005a2662e6e88cae6feb5a9e72e6b99ad2fc8ea39` |
| `build/rk3588-example-captures/ew-int/manifest.json` | `a67136d463c7f15c97afec929b9d55b8986a33c4cbe5377c64cd7dd502d46340` |
| `build/rk3588-example-captures/pooling/manifest.json` | `42b7ae1c9cbe80d48b9f59ed2f675bdc280d6daa7b22e720a7eee8794db0afd7` |
| `build/rk3588-live-verify/P0-SUMMARY.md` | `8522e876b19c2b493f09b4dcd1a6583017d61b1cc5d88babfacad312ac0d3bec` |
| `build/rk3588-live-verify/J05-device-oracles/README.md` | `6661e9d069584f35cccbdeea8916e90749ada4ce84f09b23a7aa119ab469be06` |
| `build/rk3588-live-verify/J05-device-oracles/manifest.json` | `bf15d9b9cdfd5a53e505a7e96fc361da71d8df27b769f6d84f8690c22c411c2d` |

## 17. Multi-image checklist (one line per image)

0. Distinguish the evidence level first: live RK3588 P0/P1 results (§16.1)
   cover RTL leaves/fixtures only; they do not authorize or replace a load.
1. Pick the family row in §15.1 and copy its exact image SHA-256. The
   pooling-corpus row is still PENDING task-10 and cannot be loaded yet; the EW row
   is emitted but needs its admission to leave `SOURCE_INTACT_REVIEW_PENDING`
   (human board reviewer) before a load.
2. Preflight (§8.0) and read-only target audit (§5); user authorization for
   that exact image (§2 A).
3. Volatile load only (§6), verify INIT/DONE/DNA/USR_ACCESS + that image's
   page/first-frame identity (six-page: page map, untagged; EW: RKEW identity +
   `USR_ACCESS=ec9ecd41`); never flash.
4. Run the row's host entry point; capture the per-image evidence in §15.3.
5. Switch family only by repeating 1–4 with the other SHA; a mode-0 run
   requires a reload before further mailbox work.
6. Cleanup and record: server stopped, lease released, flash untouched, image
   SHA + all receipt hashes in the final report.
