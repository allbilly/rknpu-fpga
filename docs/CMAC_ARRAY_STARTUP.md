# Full C32/K16 startup-reset candidate

The separate `full512-startup` profile removes the external R28 dependency
from a candidate full-size board wrapper. It instantiates the unchanged
`rk_cmac_array_bram_demo` and the existing registered `rk_startup_reset`.
The selected arithmetic remains the qualified DSP-prefix composition:
one array, sixteen kernels, 512 lanes/products and 512 carry helpers.
The baseline array from `array_sources.json` alone is not this composition.

The original R28 top, constraints, manifest and nine-mode external-reset
qualification remain unchanged. OpenTPU's board notes describe R28 as unwired;
that is a reference observation, not a measurement of this card. Preparing a
clock/LED-only alternative does not establish the board's electrical facts.
The primary production endpoint remains the strict EW slice.

**Current physical milestone, 2026-10-27:** the separate registered-RAM
pipeline candidate passes three actual SRAM loads and four passive captures
(404 positive samples, 32 heartbeat transitions). Its finite K65 scoreboard
and scope are documented in [CMAC_FPGA_TEST.md](CMAC_FPGA_TEST.md).

**Earlier builds, 2026-10-26:** the authorized
[full512 Vivado checkpoint run](../build/full512-vivado-implementation/1792992222236656161/run.json)
retained all 512 CMAC products but failed setup at WNS -13.249 ns. The separate
balanced-selector route also failed: WNS -2.350 ns after routing and -1.686 ns
after post-route physical optimization. Neither produced a bitstream. The new
registered-preparation-stage candidate has now routed at the unchanged 20 ns
clock. The timing report records setup +0.045 ns (45 ps), hold +0.075 ns and
pulse width +9.600 ns, with zero failing endpoints in all three groups. The
no-clock and unconstrained-internal checks each report zero. Routed utilization
is 267,210 LUTs (89.49%), 35,776 registers, six BRAM tiles and 515 DSPs,
including all 512 CMAC products. The DRC report contains 2,081 warning-level
findings: DSP pipelining advice, 20 RAM async-control findings and one
rule-limit warning. No source constraint or DRC waiver changed. The source-bound
pad/electrical review selects logical generic 0; optical polarity remains
unknown and the legacy optical review form is unchanged. See the
[pipeline timing notes](CMAC_PIPELINE_TIMING.md),
[frozen source package](../build/full512-pipeline-preparation/1793008000/report.json),
[routed timing report](../build/full512-pipeline-preparation/1793008000/implementation/timing.rpt),
[DRC report](../build/full512-pipeline-preparation/1793008000/implementation/drc.rpt), and
[current build receipt](../build/full512-pipeline-implementation/1793007479542120029/run.json).
Startup/image/electrical review, DRC-warning review and mapped validation remain
before bitstream; the vendor mapped replay exceeded its license instance limit.
The registered-BRAM-control candidate passes both complete native board suites
and now passes routed 50 MHz timing: setup +0.987 ns, hold +0.057 ns and pulse
width +9.600 ns, all with zero failures. Its routed DRC has no RAM async-control
findings; the 2,060 remaining DSP advisories and routed INIT/IO evidence are
reviewed. The exact newer image passes three volatile-SRAM loads and four
positive physical captures; see [the scoped report](CMAC_FPGA_TEST.md). See the pipeline timing notes for its
contract, export-boundary diagnosis and current evidence. Earlier variants
remain separate from that newer source-bound physical result.

## Reset and raw workload

`fpga/cmac/startup/ypcb_cmac_array_startup_top.sv` exposes `SYS_CLK` and three
LEDs. The registered reset is held through 64 rising edges and released on
edge 65. Its synchronous reset-request input is tied low. There is no runtime
reset pin, soft-reset opcode or promise of rollback. Restart the actual image
through separately authorized reconfiguration.

The candidate retains the 50 MHz AA28 input and existing LED pins, LVCMOS18
settings and LED exceptions. It consumes no R28 input and adds no reset false
path. LED polarity remains an explicit reviewed setting. The raw K=65 BRAM
workload, source/weight packing, grouping, CACC, conversion and output writer
are unchanged. This CMAC descriptor counts 45 body QWORDs; the FPGA fetches
all 49 words, including its distinct four-word terminal tail. It does not
reinterpret the EW initial-amount convention.

Each successful directed run must initialize and check all 4,096 halfwords,
read 196 command halfwords and 6,528 operand halfwords, accept twelve full
array frames, and compare all 64 numerical writes and acknowledgments. The
existing expected read/write vectors are used unchanged. The software oracle
is not a runtime fallback and does not supply DUT outputs.

## Native qualification

`tools/cmac/startup/run.py` selects the actual prefix source list and the
original literal JOIN from the current full-size preflight. It replaces only
the old board wrapper and adds the startup-reset module. Native hierarchy
inspection rejects a baseline/fixed array fallback or a reduced lane count.
Icarus uses its compiled VVP hierarchy; Verilator uses the elaborated JSON
module-instance graph, including instance multiplicities.

Both LED polarities receive successful cold-start runs, command-bus error,
known readback corruption and watchdog cases. Icarus additionally checks
unknown readback rejection. Partial-stop cases end during command fetch, after
the first complete frame is accepted, and during readback. Each partial-stop
case is followed by a fresh invocation of the same compiled image that must
complete the entire workload again.

Those fresh processes model configuration initialization only. They do not
test a runtime reset, retained RAM after a fabric-only reset, cable programming
or physical reconfiguration. The old bench's asynchronous assertion and
three-edge release tests cannot be relabelled as startup evidence.

The native runner records source, fixtures, actual tools, complete command
history, simulator images, pre/post execution hashes and exact result counters.
Existing donor diagnostics and the intentional prefix wiring/truncation
diagnostics require a closed source/location review; unknown design/bench
warnings fail admission. No numerical or fault expectation is weakened.

## Source preparation and remaining gates

The source-only preparer accepts the existing current own-parent-validated
full-prefix preflight and both fresh startup-native reports:

```sh
python3 tools/cmac/startup/run.py \
  --parent-preflight "$FULL_PREFIX_PREFLIGHT" --simulator iverilog
python3 tools/cmac/startup/run.py \
  --parent-preflight "$FULL_PREFIX_PREFLIGHT" --simulator verilator
python3 tools/cmac/startup/prepare.py prepare \
  --parent-preflight "$FULL_PREFIX_PREFLIGHT" \
  --iverilog-report "$STARTUP_ICARUS_REPORT" \
  --verilator-report "$STARTUP_VERILATOR_REPORT"
```

The preflight parameter identifies the completed full C32/K16 DSP-prefix
preflight listed in [README](../README.md), rather than a smaller design or
the baseline array. Each report parameter identifies the corresponding fresh
startup report printed by the runner.

The prepared Tcl retains the exact part, 20 ns clock, functional BRAM assertion,
the sixteen-kernel/32-DSP-per-kernel guard after synthesis and route, setup/hold,
unconstrained-path and DRC checks. All reviewed voltage/CFGBVS/polarity inputs
are required. No bitstream emission, programming action or automatic signoff
exists. `verify` checks the snapshot; `command` only prints a later separately
authorized checkpoint invocation after every prerequisite passes.

Copied startup-native sources and execution artifacts are independently
verifiable. The original arithmetic qualification DAG remains an explicit
external dependency: source snapshots and parent report labels do not replace
its current source/area/native/mapped/raw-board checks. If that DAG is missing
or changed, source integrity can still be inspected but build admission is
blocked.

No mapped startup-board result, INIT/FF implementation proof, physical fit,
timing/DRC/electrical signoff, SRAM programming, observed workload or RK3588
equivalence follows from native simulation or preparation. This full-size
candidate preserves all 512 products; the EW and serialized profiles do not
substitute for its acceptance gates.

## Current source-bound result

The [fresh startup-native summary](../build/plan-full512-startup-implementation/1792966979950932621/startup-native-summary.json)
records 22 Icarus and 20 Verilator cases. Both tools pass eight complete
cold-start workloads, including both LED polarities and fresh invocations
following the partial-stop cases. The shared 108-file source manifest is
`dc250720fee290859232b2a7f255084eb9ecdd755b92670ba10459f8cf77ecef`.
All successful runs have the exact counters above. The previous interrupted
attempts remain failed records; they do not supply this acceptance.

The [current checkpoint preparation](../build/full512-startup-preparation/1792967676447887367/report.json)
freezes 113 source/preparation files at SHA256
`e6da99945ee063189fb685536560dbe7b232ae574c39975ab630fbcdf9d0281f`.
Its external arithmetic-DAG requirement is explicit; snapshots alone cannot
authorize a build. The actual [full regression](../build/plan-full512-startup-implementation/1792966979950932621/production-validation.json)
also passes, including all eight admission and eight preparation controls.
No actual mapped startup-board or physical result is supplied.

All [eleven actual package-audit controls](../build/full512-startup-package-audit/1792967676447887367/report.json)
pass. Verification works with original startup-run artifact paths blocked,
and a copied-source validator runs in isolated Python outside the checkout.
That isolated copy remains blocked on the external arithmetic DAG; even a
mocked board-review check cannot turn report snapshots alone into build
admission. Copied binary, log, fixture, Tcl and startup-source changes are
rejected and restored exactly. All 184 package files and 275 original
qualified files remain byte-identical. The real board-review fields remain
empty/false and all physical-acceptance flags remain false.
