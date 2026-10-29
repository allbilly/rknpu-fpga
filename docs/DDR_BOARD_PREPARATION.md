# Boot-only USER2/DDR board preparation

`tools/ddr/prepare_ypcb_shell.py` prepares a separate strict EW/DDR board shell
for XC7K480T-FFG1156-2. It invokes no Vivado tool and never programs hardware.
The full512 BRAM/TinyStories images retain their separate qualification; this
shell is neither full512/DDR integration nor a PCIe implementation.

The real source list contains 121 HDL files: the actual original-MIG/async EW
platform plus startup reset, the preserved USER2 mailbox and a board wrapper.
All real inputs are hash-bound. Declaration-only stubs are isolated in a
different list for port elaboration and must never enter synthesis or execute.

The generator retains all 238 original MIG pin locations and the original XDC
bytes. The 50 MHz SYS clock and three status LEDs use the existing EW board
pins, with no overlap with the DDR pins. All ten one-bit CK/CKE/CS/ODT buses
retain `[0:0]`, matching the original constraint names. Source/pin checks do
not establish board voltages, PHY training or timing signoff.

The SYS startup reset is registered. Recovery requests are tied inactive in
this boot-only profile; recovery requires an independently audited volatile
SRAM reconfiguration of the whole card. TAP reset and health changes never
initiate recovery. The mailbox runs on the actual C0 UI clock and UI client
reset, not SYS50. Init/fault/heartbeat LEDs are status, never workload PASS.

`fpga/ddr/mailbox_ui_cdc.tcl` retains the conservative 166.666 ns modeled TCK
and 333.332 ns response bound. Its request bound is two UI cycles, 15 ns.
Skew reports are scoped to the mailbox, since status/job/memory crossings
coexist. Portable mocks pass, but actual shell mapping and routed audits remain
required. The selected helper is copied and hash-bound in each new preparation
package. The existing SYS50 mailbox helper is unchanged. Four portable mock
methods also reject extra false-path forms, including source-clock-only cuts.

The software transport must explicitly admit RKAD (`0x524b4144`), ABI1.0.
It must poll status bit4 for initialized, healthy memory before uploads;
`can_submit` bit0 also requires staged descriptor fields and is not a boot
readiness flag. Successful pending-result readback remains legal before ACK,
even when ownership clears the general memory-ready bit. Writes must remain
blocked until release. A failed result remains failed even while its cause
code is still pending at zero. The existing RKEW-only transport must not be
made to ignore identity checks to operate this image.

Run from the repository root:

```sh
python3 tools/ddr/prepare_ypcb_shell.py \
  --platform /path/to/reviewed-original-mig-platform \
  --mig-xdc /path/to/unchanged-original-mig.xdc \
  --out build/new-ddr-board-preparation
make -f fpga/ddr/board_shell.mk controls
```

The [actual preparation controls](../build/ypcb-ddr-shell/controls-v4/report.json)
pass strict declaration-only Icarus elaboration and reject bad ports, widths,
scalarized DDR buses, altered constraints and unbound real sources. No compiled
image was executed.

A separate 122-source read-snapshot candidate has now completed actual
in-context board synthesis with Vivado 2026.1. Its
[source-bound review](../build/ypcb-ddr-shell/snapshot-physical-synth-v1-review.json)
verifies all 255 inputs, no unresolved black boxes and the 242 original DDR/
board IOs. It is a separate candidate, rather than qualification of the
121-source package above. Unplaced setup is -1.368 ns and hold is -1.283 ns;
neither is timing acceptance. No placement, routing, image or hardware test
was performed by that run.

`fpga/ddr/reset_status_cdc.tcl` describes the reviewed nine clean level/status
crossings. `fpga/ddr/reset_bridge_board_cdc.tcl` adds an explicit physical
boot-only profile: 64 initialized startup stages plus their registered output,
the actual reset inverter, and four three-register UI reset-release banks.
It admits only 18 directed SYS-register-clock-pin to asynchronous-CLR
exceptions. Later data stages and the local UI reset into permit banks remain
timed. Eight portable mailbox/reset control methods pass, including exact
exception scope, structural rejection before mutations and rejection of a
-0.006 ns local data hold path.

The [read-only mapped query](../build/ypcb-ddr-shell/cfg-producer-query-v1-root-review.json)
confirms all 65 startup registers plus Vivado's two local GND/VCC primitives,
the registered SYS20 source and inverter, and all four UI reset banks.
The [fresh native constraint review](../build/physical-reset-qualification/v2-root-review.json)
passes the physical bank inventory and status/job/memory crossing audits.
Its strict reset audit remains **failed** at the unchanged local data hold
path: requirement 0 ns, slack -0.006 ns. Its unplaced global setup/hold are
-1.368/-0.638 ns. The failed receipt and constrained checkpoint are preserved;
no full reset/timing signoff is claimed.

A separate [fresh route attempt](../build/ypcb-ddr-shell/snapshot-route-v1/preparation.json)
binds 272 inputs and runs normal optimization, placement and routing with
strict post-route checks. It adds no timing exceptions or electrical changes,
emits no bitstream and accesses no hardware.

This attempt has now completed routing. Its native timing report records
setup +0.105 ns, hold +0.039 ns and pulse width +0.264 ns, with zero failing
endpoints. The strict four-bank reset audit passes all 36 max/min asynchronous
objects, 16 local data checks and 12 local-clear checks; the old -0.006 ns
data hold path is now timed and passing. Normal routing resolved that failure.

The containing route receipt remains **failed** at the later job-crossing
constant-bit observer. A
[read-only query](../build/ypcb-ddr-shell/routed-constant-query-v1/report.json)
finds the expected hierarchy pins but no attached nets or fan-in for bits4..7.
Absence is not constant-zero proof. Further mapped observation and the
remaining job/memory/mailbox, internal timing, CDC-warning, IO and electrical
reviews are required before accepting an image candidate. No bitstream or
hardware test is qualified by this route result.

Actual mailbox/reset-producer binding, the full logical matrix, board
IO/configuration review and complete routing/setup/hold/pulse/DRC checks remain
before any image or hardware test.
The earlier unplaced reset-bank hold receipt remains failed at -0.006 ns;
the new routed result has its own evidence and does not rewrite that receipt.

## Fresh route with preserved constant witnesses

The [opt-only experiment](../build/ypcb-ddr-shell/constant-anchor-opt-v2/report.json)
identifies one already-proved GROUND net, `platform/endpoint/engine/<const0>`,
serving all eight source/output observations for code bits4..7. Applying KEEP
and DONT_TOUCH to that net before optimization preserves all four strict
constant proofs. No observer, numerical field, clock/timing exception or
electrical setting is relaxed.

The [fresh routed checkpoint review](../build/ypcb-ddr-shell/snapshot-route-v3-root-review.json)
now passes the complete native route script: setup +0.105 ns, hold +0.039 ns,
pulse width +0.264 ns and zero failing endpoints. The reset-bank, nine status
chains, job and memory payload/synchronizer checks, all four constant-code
witnesses, mailbox timing/skew, no-clock and unconstrained-internal checks pass.
All284 run inputs remain unchanged. The earlier route failure and failed
preparation attempt retain their own receipts.

This qualifies the EW/DDR checkpoint and its project timing/CDC audits. Vendor
and reset CDC-warning disposition, IO/electrical review, exact-image admission
and physical DDR/ECC/workload tests remain open. It is not full512/DDR
integration; no bitstream was emitted and no hardware was accessed.

## Explicit CH1 profile for the first physical trial

OpenTPU's `docs/ddr_calibration_review.md` records CH0 errors with MIG as well
as LiteDRAM, and its CH1 memory release. ZYNQ-NVDLA's board README records a
physical CH1 DDR3-1066/ECC scratch result. These references favor CH1 for the
first trial; they do not prove failure of this project's untested CH0 image
or qualify its CH1 wiring.

`tools/ddr/prepare_channel_profile.py` prepares the explicit physical-channel
binding. Both original controllers, all238 MIG pads, original XDC bytes,
72-bit ECC data lanes and2GiB active window remain. Logical endpoint channel0
is bound to physicalCH1; logical channel1 is the inactive physicalCH0. Clock,
reset, calibration, interrupt, AXI and ECC-control roles move together. Internal
`c0`/`c1` endpoint/diagnostic names describe these logical roles. Physical pad
and reference-clock names retain their original board meaning. Raw addresses
stay in0..0x7fffffff, with no host offset or data/layout conversion.

Six source-bound channel-selection controls pass. A
[fresh 122-HDL synthesis/optimization package](../build/ypcb-ddr-shell/ch1-physical-synth-v2/preparation.json)
binds the actual selected inputs and checks the physical/logical clock identity
in the mapped design. Its separate [CH1 route](../build/ypcb-ddr-shell/ch1-route-v1/report.json)
completed, and the [routed review](../build/ypcb-ddr-shell/ch1-routed-root-review-v1.json)
reports setup +0.006 ns (6 ps), hold +0.035 ns and pulse width +0.264 ns, with
all internal timing count checks at zero. The earlier C0 timing receipt remains
bound to its own wiring.

A separate [CH1 image-emission report](../build/ypcb-ddr-shell/ch1-image-v2/report.json)
records successful offline bitstream emission. The independent
[read-only bitfile structure review](../build/ypcb-ddr-shell/ch1-image-bitfile-review-v1/root-review-facts.json)
passes the container, device/package, IDCODE and packet/configuration checks
for IDCODE `0x03751093`; no IPROG packet was seen. Its bitstream DRC reports six
ordinary warnings, zero critical warnings and zero errors. Software CRC checking
was **NOT CHECKED** and **NOT PERFORMED**. These offline receipts accessed no
hardware and establish neither DDR operation nor electrical acceptance. A
later, separate [physical CH1 trial](DDR_FPGA_TEST.md) now passes one audited
SRAM load, six scratch addresses in two write orders and raw SUB(9), including
all 102,400 owned BO bytes before ACK. Its independent audit covers 24,238
actual scans. Flash is unchanged; full capacity, ECC fault injection/recovery,
full512/DDR, PCIe and production electrical signoff remain unqualified.

`tools/ddr/transport.py` adds explicit RKAD ABI1.0 admission while retaining
the original RKEW implementation. It waits for status bit4 before uploads,
permits only owned successful readback before ACK, blocks writes during that
ownership interval, and treats a code0 pending fault as an error. Ten DDR
transport controls and53 unchanged host controls pass with mocked links;
they make no network/hardware connection. The containing application must
still compare complete output BOs before ACK and hold the shared board lease.
