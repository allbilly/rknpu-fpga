# Channel-0 ECC control monitor

`rtl/ddr/rk_mig_ecc_monitor.sv` owns the archived MIG channel-0 ECC control
interface. It configures interrupt reporting, checks ECC configuration and
returns fresh register snapshots. The existing EW decoder, raw final command
QWORDs, DMA, arithmetic, memory adapter and full 512-product candidate remain
unchanged. No CPU arithmetic or layout operation is added.

The [source contract](../fpga/ddr/xdma_lifecycle_contract.json) records the
generated wrapper, the control path and its exact parameter bindings. The
tests pin all six control modules through the archive catalog.
The archive is a separate logical reference with an RZQ/6 output-drive setting;
the original RZQ/7 physical preparation is preserved. No vendor source is
imported into the repository. Optional control-leaf tests extract pinned
source bytes into their fresh local build directory.

## Bound interface and ownership

The monitor connects to `c0_s_axi_ctrl_*` and `c0_interrupt` in the
`c0_ui_clk` domain. The control interface has 32-bit address/data channels and
AW, W, B, AR and R handshakes. It exposes no WSTRB, protection or transaction-ID
ports. The monitor owns this interface exclusively and serializes transactions.
Other masters require a separately audited arbitration and ownership protocol.

The exported `c0_app_ecc_single_err` and `c0_app_ecc_multiple_err` vectors are
not used. Their UI-reordered values lack matching external valid qualification,
and the UI path filters RMW reads. The control register bank receives qualified
raw decoder events, including RMW, through a different path. Source/member
and line bindings for both paths are retained in the contract.

After calibration, startup performs exactly these transactions:

1. Write `ECC_EN_IRQ` at `0x4` with value `3`.
2. Read back `ECC_EN_IRQ` and require exactly `3`.
3. Read `ECC_ON_OFF` at `0x8` and require exactly `1`.
4. Read `ECC_STATUS` at `0x0` and require exactly `0`.

The status bits are UE at bit 0 and CE at bit 1. This monitor uses a strict
zero-event policy: either interrupt or a nonzero status quarantines it.
It never writes status-clear, ECC enable/disable or fault-injection registers.
Existing errors therefore remain visible. In the vendor register primitive,
a software clear wins over a simultaneous hardware event; using W1C during
memory activity could lose that event.

## Checks, snapshots and faults

`monitor_healthy` indicates that this monitor's configuration/status checks
passed. Allocation initialization, memory ownership and job admission need
their own evidence. The monitor has no successful-job output.

A `check_valid && check_ready` handshake requests three fresh reads in the
same mask/onoff/status order. A successful result asserts `snapshot_valid`
with the three 32-bit words. They remain stable until `snapshot_ready` accepts
them. The reads are sequential, rather than an atomic memory-health sample.
The actual vendor control slave exposes live register data while RVALID is
pending; the monitor keeps RREADY asserted and captures the response handshake.

A fault during a check terminates it through the sticky `fault` output.
An already presented snapshot remains stable and can still be accepted after
a later fault; accepting it does not clear quarantine. Consumers must observe
the fault output independently of a pending or earlier clean snapshot.

| Monitor-local code | Cause |
|---:|---|
| 1 | Interrupt high or unresolved |
| 2 | Calibration lost or unresolved after service begins |
| 3 | Control transaction timeout |
| 4 | Non-OKAY or unresolved control response |
| 5 | Unsolicited or premature response |
| 6 | Interrupt mask readback differs from 3 |
| 7 | ECC on/off readback differs from 1 |
| 8 | Nonzero or unresolved ECC status |

These diagnostics are separate from RK command error codes. The first cause
is retained. Current IRQ and fault conditions suppress healthy/check admission
immediately. Startup waits through unresolved calibration; service-time
calibration loss and unresolved IRQ quarantine instead of recovering silently.

Faults preserve already asserted AW/W/AR requests and payloads. Their pending
handshakes and B/R responses continue to drain, including after timeout.
No further control transactions are issued after the pending transaction ends.
Only `joint_rst_n` clears quarantine. Its platform contract must reset/drain
all affected transaction domains; calibration returning or asserting only
`c0_aresetn` does not establish that recovery.

## Verification and remaining integration

Run portable tests without an external archive:

```sh
make -f fpga/ddr/monitor.mk test
```

Run the portable and actual archived control tests in both simulators:

```sh
make -f fpga/ddr/monitor.mk vendor-test \
  MIG_ARCHIVE="$YPCB_REFERENCE_ARCHIVES/XC7K480T_XDMA_Test.zip"
```

Set `YPCB_REFERENCE_ARCHIVES` to the directory containing the pinned existing
ZIP. Each run creates a fresh output directory. The profile checks selected
source/member hashes and the exact 15 control-leaf parameter overrides.
Verilator checks the monitor and benches with `-Wall`. One directive-local
`INCABSPATH` style exception permits the intentionally absolute generated
parameter include, whose path and contents the runner binds exactly. The unchanged
control leaf has an exact source/version-bound inventory of 102 diagnostics;
Icarus has five vendor diagnostics/padding notes and two separate portable
bench synthesis notices. Unknown diagnostics fail the runner. These checks
do not alter electrical, DRC or timing requirements.

Nine runner regressions also check exact commands, tool versions, execution
images, input changes, parameter-header binding and copied verification. A
private Icarus test confirms that conflicting headers in the working/source
directories cannot override the bound header, including paths with spaces.

The [reviewed Make target](../build/plan-ddr-monitor-implementation/1792971553929950788/monitor-validation-reviewed.json)
passes with these exact [Icarus](../build/ddr-ecc-monitor/iverilog-1792974248612177316/report.json)
and [Verilator](../build/ddr-ecc-monitor/verilator-1792974248070182288/report.json)
runs. Their selected source manifest is
`1cd48787fbd0fba639ef6654e9afcf8f70b380f759a9194aefba72d0e51f590e`.
The [copied-evidence audit](../build/ddr-monitor-copy-audit/1792974487715872025/report.json)
passes 23 checks with all 74 selected files and original evidence unchanged,
including verification without original-input reads or tool execution.
The earlier report-verifier and header-binding failures remain preserved.

Verify a completed run without executing tools:

```sh
python3 -B tools/ddr/run_monitor.py --verify path/to/report.json
```

The copied snapshot preserves the report's relative source/artifact tree, so
its own `tools/ddr/run_monitor.py` can verify the included reports without the
original workspace, archive or installed simulators.

The portable bench covers 23 known-bit scenarios in both simulators; Icarus
adds six X/Z controls. The actual-control bench covers 21 scenarios, including
all eight UE and CE event bits, existing errors, disabled ECC, stable snapshots
across faults and calibration loss. Its raw-event stimulus models the already
qualified decoder input. It does not simulate a DDR PHY, ECC decoding, an RMW
transaction or actual memory contents.

The archive emits its memory B response when the last application command is
accepted. An ECC status read uses an independent control path. Consequently,
final B followed by clean status does not prove RMW retirement. A full DDR
lifecycle composite still needs a source-bound retirement/quiescence witness,
initialization coverage, descriptor/request ownership and whole-domain reset
coordination before it can publish successful job completion. No fixed wait,
clean monitor snapshot or renamed readiness flag supplies that witness.
