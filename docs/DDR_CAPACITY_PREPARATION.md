# Full-span DDR pattern preparation

The active CH1 image exposes the 31-bit byte window `0..0x7fffffff`.
Its scratch and trained-tile results do not establish complete capacity.
The new [offline plan generator](../tools/ddr/prepare_capacity_test.py) and
[streaming byte verifier](../tools/ddr/capacity_pattern.py) prepare a full
two-GiB test without connecting to hardware or materializing millions of rows.

```sh
python3 tools/ddr/prepare_capacity_test.py \
  --out build/ddr-capacity-preparation/full-2gib-plan.json
python3 -m unittest discover -s tests/ddr/capacity -p 'test*.py' -v
make ddr-capacity-controls
```

The plan contains 33,554,432 aligned 64-byte lines and 134,217,728 operations.
It requires two global trials:

1. Write every address in ascending order, then read every address ascending.
2. Write every address descending with complemented data, then read ascending.

All write responses in a trial precede its reads. Immediate write/read pairs
are insufficient for this contract: an aliased address can return its most
recent local pattern while hiding a collision elsewhere in the window.

Each line contains sixteen little-endian uint32 words. Word `lane` is
`(address / 64) XOR seed XOR ((lane * 0x9e3779b9) mod 2^32)`; trial one
complements every bit. The default seed is `0x3588c350`. Word zero uniquely
identifies every line in the selected window; lane constants exercise byte
and word positions. The verifier consumes one completed operation at a time
with bounded memory and requires exact order, address, complete bytes and
successful response status. Corrupt, missing, extra or reordered operations
fail, and a failed or prematurely ended stream cannot resume into acceptance.

The CLI writes metadata, source hash and scope only. It refuses existing
output files. `--base`/`--size` select an explicitly partial window for local
controls; partial results never imply full capacity. Seven offline controls
cover known word/byte values, complements, full-range boundaries, aliasing,
malformed streams, sticky failure and output-file preservation.

The isolated V15 [source/native regression](../build/production-model-auditors/current-v15/root-review.json)
passes the full default recipe in 822.046 seconds and the separate seven
capacity-pattern controls. Its 1,098-file source snapshot adds only this
software plan/verifier/CLI test increment to V14. None of these results
qualifies physical capacity.

The [RTL pattern leaf](../rtl/ddr/rk_ddr_capacity_pattern.sv)
now passes independent [source, simulator and mapped-netlist review](../build/ddr-capacity-bist-leaf-validation-v6/root-review.json).
Both simulators pass 4,162 known-value vectors; four-state Icarus additionally
checks X/Z rejection. Verilator's two-state limit is explicit in its marker.
Root independently evaluates all vectors against the XC7 mapped logic and
checks all 64 low-address alignment patterns. The leaf uses 65 LUTs and no
DSP/RAM. It is not integrated with a memory controller or the running image.

The [sweep sequencer source](../rtl/ddr/rk_ddr_capacity_sweep.sv)
now joins that pattern to a single-outstanding 64-byte request/response
contract. It performs both global write/read trials and requests an exact
final-write-address retirement/ECC witness after each write and read pass.
It preserves stalled transactions through faults and requires joint reset
for recovery. Its [bounded protocol tests](../build/ddr-capacity-sweep-validation-v4/root-review.json)
now pass independent source/log review: Icarus and strict Verilator cover
the 256-byte two-trial sequence, four retirement witnesses, alias/corruption
detection, admission/health faults, timeout quarantine and late-response
drain. Six invalid parameter sets fail as expected. The separate default
two-GiB elaboration checks the final address `0x7fffffc0`; it performs no
full-span iteration. Earlier failed testbench attempts remain preserved.

The [portable controller-simulation archive](../verification/runs/2026-10-28-ddr-capacity-controller-sim/index.json)
contains 235 source/evidence payloads, including the pattern and sweep tests,
mapped pattern logic, failed attempts and both root reviews. An independent
[root rehash](../build/ddr-capacity-controller-sim-archive-v1/root-rehash.json)
checks every original/stored/decompressed payload and all 309 hash-only binary
exclusions. This archive supplies no actual MIG or physical-capacity result.

The [AXI adapter source](../rtl/ddr/rk_ddr_capacity_axi.sv)
records actual AW/W/B handshakes and the
last successfully acknowledged write address, then connects the sequencer's
retirement requests to the existing write fence and ECC snapshot link.
It requires exclusive ownership of the data/control paths and whole-domain
reset; it cannot share those paths with the ordinary fabric during a sweep.
The [BIST composition](../rtl/ddr/rk_ddr_capacity_bist.sv)
joins the sequencer, adapter, existing fence and existing ECC monitor. Its
[strict lint receipt](../build/ddr-capacity-composition-lint-v1/report.json)
binds the six original inputs and Verilator 5.048 with zero diagnostics.
Their unchanged bytes are now in `rtl/ddr`, with two benches and a portable
[simulation runner](../tools/ddr/run_capacity.py). The new Make target is
included in default `make test`. Its [independent source/native review](../build/ddr-capacity-public-root-review-v1.json)
passes six configurations in each simulator: direct 256/512-byte windows,
nonzero base, the final line `0x7fffffc0`, and two joined-wrapper windows.
The directed tests cover invalid requests, retirement witnesses, ownership
and health loss, response backpressure, premature/unsolicited responses,
timeout quarantine, late drain and joint-reset restart. All eighteen
nonzero-address pattern fixtures match the separate software oracle in every
case. Strict Verilator has no diagnostics; Icarus diagnostics are preserved.

The private v15 bench was extended after its completed producer receipt.
Its [forensic record](../build/ddr-capacity-axi-validation-v15/postrun-mutation-forensic-v1.json)
preserves that mutation and the original bytes remain separately saved.
The expanded private v16 and fresh public runs bind the actual expanded
bench; no old result is reused as evidence for modified tests. The fresh
[full V16 production regression](../build/production-model-auditors/current-v16/root-review.json)
passes in 876.048 seconds with all 1,105 original/copied source hashes and
both complete host receipts independently checked. Capacity controls now run
inside default Make.

Its [independently recounted XC7 mapping](../build/ddr-capacity-composition-mapping-v1/root-review.json)
uses 1,642 LUTs, 1,958 FFs and no DSP/RAM; 2,692 interface IO cells and five
metadata cells are counted separately. This is subsystem mapping, not a
combined full512 fit or timing result. At that increment no physical top had
been changed or programmed for capacity testing; the later parent integration
and full-design synthesis are recorded below. No capacity image has been programmed.

That component-only increment supplied no physical executor or complete
FPGA BIST. The later parent profile and host client below prepare execution;
physical capacity remains unqualified.
Even complete byte-verifier acceptance reports physical capacity unqualified.
A future runner must additionally bind the exact image/target/actual wire
or controller witness, write retirement/fence, calibration/ECC health and
recovery behavior. The completed model-inference session held the board lease;
no capacity operation ran during that session.

## Ownership integration in preparation

The private [ownership-control leaf](../build/ddr-capacity-owner-source-v1/rk_ddr_capacity_owner.sv)
prepares the next integration step. It observes the final memory and ECC-control
AXI handshakes, including independently accepted AW/W and held responses. It
also requires explicit fabric/host/job/readback quiescence; an idle AXI bus
alone cannot prove that a completed result has been read and acknowledged.
Two consecutive quiet UI cycles precede diagnostic ownership.

The selector and diagnostic reset release remain latched after success or
failure, so pending traffic keeps its owner until coordinated whole-domain
reset. `busy` and `done` must never select the physical bus. Existing owned
job readback/ACK and accepted responses must drain while new work is blocked.
The diagnostic's monitor must become healthy before its held start request
can execute. Only handoff/monitor/start waiting has an owner timeout; the
complete sweep retains its own bounded per-transaction checks and has no
65,536-cycle whole-sweep deadline.

Its [standalone source/native review](../build/ddr-capacity-owner-validation-v12/root-review.json)
now passes both simulators, including legal held requests/responses, late
drain and a RUN interval longer than the test timeout. Invalid QUIET=1 is
rejected during strict Verilator compilation; Icarus reaches the intended
runtime fatal. The ordinary profile compiles without Verilator diagnostics.
This leaf supplies no bus mux, diagnostic CSR bank or board integration.
Its single-outstanding observer matches the selected fabric/monitor bubble
between transactions; it is not a general zero-bubble AXI arbiter.

The separate private [diagnostic-register leaf](../build/ddr-capacity-owner-source-v1/rk_ddr_capacity_regs.sv)
prepares an explicit FPGA-management bank at `0x200..0x2ff`. It identifies
itself as `RKMT`, exposes fixed source-bound window metadata and complete
mismatch words, and accepts only a full-word seed write followed by a single
start per reset epoch. Unknown, unaligned, protected, partial or read-only
writes return AXI-Lite errors. Requests and read/write responses retain their
payloads under backpressure. Its [independent standalone review](../build/ddr-capacity-regs-validation-v8/root-review.json)
passes 488 Icarus checks and 433 strict-Verilator checks; four-state inputs
are tested only with Icarus. Both reject the invalid metadata parameters.
This bank
is not connected to the current image or exposed by the existing raw-job
transport, whose unsupported-address failures remain unchanged.

The private [data/control routing leaf](../build/ddr-capacity-mux-source-v2/rk_ddr_diagnostic_mux.sv)
also [passes independent review](../build/ddr-diagnostic-mux-validation-v9/root-review.json):
25,282 checks per memory/control profile in each simulator verify complete
data, IDs, strobes, attributes and response isolation. Guarded declaration
widths let invalid zero/sub-byte parameters reach the explicit fatal rather
than a frontend range error; valid-profile widths and routing remain exact.
Only the qualified ownership controller may drive its selector.

The [private integrated service](../build/ddr-capacity-service-source-v3/rk_ddr_capacity_service.sv)
now joins these three leaves with the existing BIST/fence/monitor. Its
[ten-module strict lint](../build/ddr-capacity-service-lint-v1/report.json)
passes, preserving the earlier lint failures beside the corrected renderer.
Its [modeled integration review](../build/ddr-capacity-service-validation-v17/root-review.json)
passes both simulators at base0/span256 and base`0x1000`/span512. Cases cover
normal traffic, job-owned/host-busy START rejection, pending memory-B/control-R
drain, ECC-monitor startup, full pattern contents, four fences, mismatch
capture, late-request quarantine, whole-domain reset and final-edge health
loss. Real MIG/PHY, electrical behavior and physical capacity are not modeled.
The [fresh Vivado OOC synthesis](../build/ddr-capacity-service-vivado-ooc-v3/root-result-review.json)
passes with 1,821 LUTs, 2,094 registers and no RAM/DSP/latches using Vivado
2026.1 build6511674. All 36 inputs retain their hashes and native groups close.
It applies no clock constraints and supplies nominal subsystem resources
only, not a combined full512 fit or timing result. The first two OOC recipes
were rejected before native launch; the corrected root runner validates every
approved input before running the version query or synthesis.

The service expects separately
decoded management traffic and true parent fabric/job/readback witnesses;
it supplies no JTAG decode, board top, CDC or reset coordinator. Existing
full512/DDR physical evidence does not qualify this changed composition.

A private [AXI-Lite control router](../build/ddr-capacity-owner-source-v1/rk_axil_diagnostic_router.sv)
also [passes standalone source/native review](../build/axil-diagnostic-router-validation-v7/root-review.json).
Only full addresses `0x200..0x2ff` select the diagnostic bank; all other
addresses reach the existing normal decoder unchanged. Its 73 transactions
per simulator check W-before-AW buffering, exact data/strobes/protection,
AR-time snapshots, channel stalls, response isolation and high-address aliases.
The [integrated parent candidate](../build/full512-capacity-parent-v2/rk_jtag_dual_ddr_async.sv)
now connects the router, diagnostic service, normal DDR fabric and ordinary
ECC-control master. Its fabric exports registered transaction quiescence;
this avoids a combinational admission/fault cycle detected in the first
candidate. The original raw DMA, selected full512 arithmetic, reset
coordinator and physical interface remain byte-identical dependencies.

The [fresh root simulation replay](../build/full512-capacity-parent-root-replay-v1/report.json)
passes the original K65 and SUB(9) jobs with complete readback before ACK,
a full modeled one-MiB sweep (32,768 writes and reads), blocked normal memory
access during diagnostic ownership, and reset/reinitialization with exact
vector reloads. Its output directory is isolated because earlier mechanical
benches reused observation filenames; those overwritten historical outputs
are not treated as immutable evidence. The independent real controller-model
checks are still running separately.

[Fresh full-design Vivado synthesis](../build/full512-capacity-vivado-run-v2/root-synth-review.json)
passes from 161 HDL inputs, both original XDC files and six unchanged audit
helpers. Both mapped censuses confirm all 512 product DSPs, 516 total DSPs,
242 IOs and the original 20 ns SYS / 7.5 ns UI clocks. Optimized utilization
is 295,755 total LUTs. All 363 source/tool/approval bindings retain their
hashes. The [fresh route](../build/full512-capacity-route-run-v1/report.json)
completed at 290,178 LUTs but failed setup by 0.052 ns; hold and pulse passed
at +0.039/+0.264 ns. The complete 395-input closure and failed routed DCP are
preserved. A [targeted physical repair](../build/full512-capacity-targeted-repair-run-v2/report.json)
now works from that source-identical checkpoint, with all clock, DRC, CDC,
resource and pulse checks retained. No capacity image has been programmed.

The exact validated source bytes are now published as an
[alternate capacity profile](../rtl/ddr/capacity/README.md), preserving the
ordinary qualified parent. The [host management client](../tools/ddr/capacity_client.py)
uses an existing raw USER2 owner and provides no connection, programming,
reset, retry or CPU execution fallback. Its twelve mock controls pass; a
successful device BIST receipt still requires independent image/wire review.

The published profile now has a portable `make ddr-capacity-parent-controls`
target inside default `make test`. It exercises both service windows and the
router/actual EW-CMAC register-bank composition in Icarus and strict Verilator,
plus twelve client mocks, twelve capacity-wire controls and ten raw-job wire
controls. The runner derives the copied workspace from its own location and
records the actual source/import closure and tool identities. The
[independent native-matrix review](../build/ddr-capacity-parent-controls/iverilog-verilator-1793189796440935519/root-native-review.json)
checks all 24 executed commands, eleven result groups and eight simulator
images. Its historical producer/failed verifier are preserved: root corrected
only the verifier's duplicate artifact-order calculation. The fresh V17 default
regression now [passes independent review](../build/production-model-auditors/current-v17/root-review.json)
in 1,086.240 seconds from a 1,123-file source copy. The corrected verifier also
passes directly on that copied run: all 24 commands, eleven result groups,
eight simulator images and 34 input bindings. The older verifier failure is
not rewritten or substituted for this fresh execution.

The real controller-model normal K65 and SUB(9) cases pass independently for
the unchanged parent RTL. Its first capacity case stopped at an arbitrary
10,000-CSR-poll bench limit while status was `0x64`, fault was zero and writes
were pending. That is a failed capacity case, not a BIST pass. The
[fresh observer-only model retry](../build/full512-capacity-parent-validation-v4/root-review-v2.json)
retains the full one-MiB/two-trial/four-fence predicates, original 100-million
UI-cycle watchdog and 1,800-second host deadline. It observes actual completion
and logs progress rather than exhausting a serial CSR-poll count. Its standalone
capacity case avoids repeating the already checked K65 prelude; the earlier
normal cases remain separate receipts rather than a new same-binary union.

That standalone controller-model case now [passes independent review](../build/full512-capacity-parent-validation-v4/root-result-review.json):
all 146 bound inputs retain their hashes, all 121 HDL sources match the prior
parent, and the unchanged 628-warning inventory contains no new diagnostic.
It completes in 1,315.211 seconds within the original 1,800-second limit.
Eight actual progress snapshots show both global trials, followed by exactly
32,768 writes, 32,768 reads, final status `0x68` and global-reset return.
The four-fence count follows the checked sweep contract; this bench does not
provide an independent fence-event counter. This is actual AXI/UI/MC with a
modeled encoded PHY, not a physical two-GiB result.

The [capacity physical runner preparation](../build/fpga-bringup/full512-capacity-prep-v1/run_capacity_test.py)
now stages scratch checks, complete original K65/SUB(9) BO execution, the full
two-GiB BIST, audited same-image volatile reconfiguration and repeated normal
jobs. Its seven offline admission controls pass; pending route/bitfile/image
review prevents execution before utilities, sockets, processes or lease use.
The [BIST management-wire auditor](../tools/ddr/audit_capacity.py) verifies
actual decoded metadata, seed/START, counters and final health. The
[raw-job auditor](../tools/ddr/audit_raw_case.py) separately verifies unchanged
uploads/descriptors and complete output bytes before ACK, including rejection
of completion regressing before ACK. Management traces expose device witnesses,
not every DDR byte compared inside BIST; image/source review remains required.

The [current image preparation](../build/full512-capacity-image-prep-v3/prepare_image.py)
is also pending the fresh qualification bindings. It retains the existing
IO/clock/DRC/DSP/MIG/CDC/reset gates and adds strict all-row pulse checks,
capacity-hierarchy checks and the 35-row/101-observation/three-anchor constant
proof. Its candidate source tag is `1891a1ac`; no image or hardware acceptance
is implied. Both preparation commands are offline by default:

```sh
python3 build/full512-capacity-image-prep-v3/prepare_image.py
python3 build/fpga-bringup/full512-capacity-prep-v1/run_capacity_test.py
```

## Physical capacity acceptance

The exact retirement-capacity image, source tag `2c8f17dd`, now passes its
[physical two-GiB BIST and reconfiguration-recovery review](DDR_CAPACITY_FPGA_TEST.md).
Two global trials complete 67,108,864 writes and reads with status `0x68` and
zero faults. Original K65/SUB9 jobs pass in both loaded epochs, with 245,760
whole-BO bytes before ACK. The review consumes six complete scan traces and
checks the exact image, DNA/IDCODE/TCK and lease/process cleanup. Live reset,
physical FI and PCIe remain separate gates. Earlier model/preparation and
failed-attempt receipts retain their original scope.

## ECC injection boundary

The follow-up source map separates FI control access from the full ECC-test
payload mode. The [MC instantiates the FI-XOR leaf whenever ECC is ON](../build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/048/mig_7series_v4_2_mc.v:931),
including the current ECC_TEST=OFF profile. The
[control block gates FI-register write permissions with C_ECC_TEST](../build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/004/mig_7series_v4_2_axi_ctrl_top.v:204),
while the [UI wrapper separately selects payload adaptation](../build/full512-ddr-preparation/shared-data-constrained-prep-v4/source/hdl/058/mig_7series_v4_2_memc_ui_top_axi.v:870).
The control register bank's remaining C_ECC_TEST references are commented-out
conditions, so these are separate source decisions rather than one indivisible
data-path change.

For the later diagnostic profile, first evaluate a separately pinned FI-control
access variant that retains the normal 64-bit payload and AXI layout. This is
a separately prepared source candidate, not an admitted API. The
[private one-line variant](../build/ddr-fi-control-source-v1/derivation.json)
changes only the UI wrapper's control-leaf `C_ECC_TEST` argument to `"ON"`;
all other references to the parent's `ECC_TEST` remain unchanged. It is not
part of the current capacity route or an emitted image. It still requires
explicit field/ownership contracts, normal numerical/controller regression,
valid CE/UE observation, disarm and recovery tests, fresh implementation and
physical qualification. The current image's FI writes remain unsupported.
Vendor control writes can begin after delayed MIG calibration, before the
project's full-span initialization; any new startup disarm sequence must own
that interval and finish before ordinary memory writes are admitted.

The [fresh control/mask component review](../build/ddr-fi-control-permission-test-v1/root-component-review.json)
passes in Icarus 13.0 and Verilator 5.048 using seven unchanged vendor files.
Each simulator checks 19 writes and 23 reads across OFF/ON control instances,
the actual nine-byte FI-XOR mask, controller-only reset retention, explicit
zero-write disarm and memory-write-clear priority. Verilator's exact 102
existing vendor diagnostics match; there are no new project diagnostics.
This is not full UI/MC integration, CE/UE validity, memory retirement or
physical fault-injection evidence.

The source/bench also establish a required API guard. Vendor B/R responses
are hardwired OKAY; denied or unmapped accesses decode to DUMMY index zero.
Although its top-level metadata marks DUMMY writable, the register bank ties
its write enables off, so those reads remain `0xDEADDEAD`. Neither an OKAY
response nor a FI-register readback proves that the mask was armed. The
future project wrapper must reject unsupported accesses before forwarding:
check the complete address/alignment, write-only FI access, full write strobes,
reserved ECC-data bits, diagnostic ownership, calibration and quiescence.
Keep unknown/read-only/invalid-field project requests as explicit failures;
do not expose the vendor's silent-ignore behavior as the project ABI.

The separate [internal FI write guard candidate](../build/ddr-fi-write-guard-v1/CONTRACT.md)
now implements that validation for its sequencer request interface. Its
[coupled native review](../build/ddr-fi-write-guard-test-v1/root-result-review.json)
passes 54 Icarus and 47 Verilator transactions, including seven Icarus-only
unknown-field checks. It requires actual FI byte/data witnesses in addition
to B completion, invalidates its known-mask ledger on reset, and keeps timed-out
AXI requests stable until they drain under sticky quarantine. Tests also check
ownership through successful response acceptance, stable responses under
backpressure, and orphan B/FI events without a fabricated request/response.
All seven fault codes are exercised; there are no new project diagnostics.

This guard is not a host register bank, port arbiter, startup disarm sequencer,
memory-retirement witness or CE/UE diagnostic implementation. Those integrations
remain required, and it is absent from the current capacity route/image. Its
joint reset is not an implementation of the standalone CMAC runtime reset.

The separate [startup/control composition](../build/ddr-fi-startup-control-v1/CONTRACT.md)
now passes its [independent coupled review](../build/ddr-fi-startup-control-test-v1/root-result-review.json)
in both simulators. An exclusive control-port mux and bootstrap sequencer
compose the unchanged strict ECC monitor with the validated guard and actual
vendor control/FI leaves. Bootstrap writes and witnesses all nine zero mask
bytes before monitor configuration. Runtime ownership waits for complete
control transactions and parent eligibility; an early diagnostic request
cannot block the memory initialization needed to become eligible.
Any nonzero witnessed arm requires joint-reset recovery even after mask clear.
The tests include nine runtime requests, two positive reset epochs, bootstrap
timeout and missing-witness failures, stalls, response backpressure and raw
IRQ quarantine. There are no new project diagnostics. This remains a private
control-only candidate: actual UI/MC witness exports, parent data arbitration,
initialization/reload, valid CE/UE events, retirement and physical tests are
still required. It is absent from the current capacity synthesis source set.

The [explicit vendor-port candidate](../build/ddr-fi-parent-witness-source-v1/derivation.json)
now exports FI write/data and the exact leaf clear enable, MC status-valid,
CE/UE vectors/address and read-data-valid through the generated wrappers.
Only physical C1 overrides the new FI-control-permission parameter; C0 keeps
the original default, and both ECC_TEST payload modes remain OFF/64-bit.
The exports add observations without changing the vendor data pipeline.
Icarus wrapper elaboration stops at retained vendor attribute syntax; the
[failed attempt](../build/ddr-fi-parent-witness-syntax-v1/report.json) is
preserved. It does not qualify named-port binding or full wrapper behavior.

The separate [actual-MC FI service model review](../build/ddr-fi-mc-service-test-v1/root-result-review.json)
passes in Verilator 5.048 using the real AXI/UI/MC/control/FI logic and encoded
PHY RAM. Actual FI writes corrupt exactly the first codeword's one or two
selected bits, with no artificial read-return corruption. The model checks
one valid-qualified corrected CE, one valid-qualified UE with SLVERR and
uncorrected bytes, strict ordinary-monitor quarantine, dirty ownership after
mask clear, and joint reset/disarm plus explicit line rewrite recovery.
Twenty complete line reads total 1,280 bytes; 13 mask writes and 20 actual
leaf-clear observations are checked. Root rehashes all 76 native inputs.
The 572 inherited vendor diagnostics and one inherited calibration-boundary
diagnostic remain explicit; there are no new project diagnostics. The first
attempt's bench/frontend failures are preserved separately. This is not full
parent integration, full-span initialization, physical PHY or hardware proof.

The later [full-parent fast composition](../build/full512-fi-parent-fast-model-v1/root-result-review.json)
now passes normal raw K65/SUB9, modeled capacity BIST and full initialization,
with 122,880 complete numerical BO bytes unchanged. It adds a separate new-work
admission block so original readback and ACK can drain before FI acquisition,
rejects capacity START while FI owns, and retains ownership after any effectful
diagnostic line request until joint reset. The tested actual control/FI leaves
also establish disarm before initialization when the no-reset leaf retains an
armed mask across the reset. The fast RAM rejects writes with a nonzero mask;
it provides no CE/UE corruption model. The diagnostic line source has its own
[24/19-control two-simulator review](../build/ddr-fi-line-access-test-v2/root-result-review.json).
The [fresh full-parent actual-controller matrix](../build/full512-fi-parent-controller-model-v1/root-result-review.json)
now passes its independent review: six cases, 128 HDL sources and all 142
inputs rehashed unchanged. It checks 327,680 complete numerical BO bytes,
including original K65/SUB9 and raw SUB(9) after both CE and UE joint-reset
recovery. The actual vendor MC/FI logic produces the valid error observations;
the PHY remains an encoded RAM model. New RKFI page integration and physical
wrapper/image/hardware qualification remain separate gates.

The [source inventory](../build/full512-ddr-preparation/capacity-ecc-source-inventory-v1.json)
confirms ECC enabled on physical C1, but `C1_ECC_TEST` is off in this image.
The vendor's conditional FI-XOR registers are not an enabled diagnostic API.
The existing monitor exclusively owns the control interface and quarantines
on any reported event; exported UI error vectors are not valid-qualified raw
events. A future test profile needs explicit source-bound enablement,
arbitration, event/retirement observation and joint-reset recovery. Unknown
CSR writes on the current raw-job ABI remain failures.

The [source-level injection review](../build/full512-ddr-preparation/ecc-injection-contract-source-review-v1.json)
adds three concrete constraints for that future profile. The FI registers
are write-only, so register readback cannot prove an armed mask. The vendor
leaf XORs only the first 72-bit codeword and clears its mask on a controller
write event; that clear wins over a simultaneous arm. Its mask has no reset
port, so an aborted armed injection needs explicit zero-mask writes before
recovery admission. Finally, enabling `ECC_TEST` changes the generated payload
width from 64 to 72 bits and selects additional AXI/UI width adaptation. That
profile needs new composition/numerical qualification; toggling one parameter
does not qualify injection or preserve the existing image's proof.

The actual vendor FI leaf now has an independent [native-behavior review](../build/ddr-ecc-fi-leaf-root-review-v1.json)
covering 38 vector scenarios in each simulator, including all nine byte
lanes, mask hold/disarm, write-clear priority and unchanged upper codewords.
Strict Verilator passes without diagnostics. Icarus compile/run return zero
with its vendor generate-style warning preserved. The Icarus v10 wrapper
remains FAIL because its footer parser rejected the filename-prefixed
`$finish` message; root separately checks the exact native marker, footer,
source hashes and logs without rewriting that failed receipt. These tests
instantiate no memory controller, ECC decoder, memory or PHY.
The [portable FI-leaf archive v2](../verification/runs/2026-10-28-ddr-ecc-fi-leaf-sim-v2/index.json)
preserves 89 source/evidence payloads and all six vendor sources referenced
by the injection-obligations review. Root independently rehashes all payloads,
85 coverage references and 226 hash-only exclusions. The first archive lacks
five obligation sources and remains preserved separately.
