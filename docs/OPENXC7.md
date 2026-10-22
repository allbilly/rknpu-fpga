# Historical OpenXC7 YPCB implementation work

**Retired from continuation on 2026-10-23:** use Vivado with the OpenTPU workflow
as a reference. Preserve the scripts, source snapshots, reports and failures
below as historical evidence; do not restart openXC7 compilation, packing,
placement or routing. The current authorized scope is documentation, review,
fixes and preparation, with no Vivado build or hardware programming.

The historical work used the `xc7k480tffg1156-2` device/package entry in
openXC7's Project X-Ray database. Its `make openxc7-check` target performs
**placement/routing characterization only**, without a bitstream or programming
operation. The existing electrical, timing and DRC requirements remain intact.
Commands below describe historical reproduction, not the current work plan.

Useful primary references:

- [openXC7 toolchain](https://github.com/openXC7/toolchain-installer): Yosys,
  nextpnr-xilinx and Project X-Ray.
- [YPCB LED example](https://github.com/openXC7/demo-projects/tree/main/blinky-ypcb003381p1):
  same package and clock/LED pins, but its Makefile selects speed grade **-1**.
  This project does not substitute that grade for **-2**.
- [YPCB PCIe build recipe](https://github.com/regymm/pcie_7x/blob/main/Makefile.ypcb_k480t.openxc7):
  selects the exact **-2** part. It is a candidate for future transport work,
  not an integrated or tested PCIe shell in this project.

## Pinned native tools

The local build uses these unmodified checkouts, all under `build/`:

| Component | Revision |
|---|---|
| openXC7 nextpnr-xilinx | `d486d8ef6a1c756ca72b2ba495e7e18e4c24815d` |
| Its prjxray-db submodule | `1768fb35d68468eac2f4319ff66d0c27863267b6` |
| Its nextpnr-xilinx-meta submodule | `a4af910cac907f2cbd3a545f26f8e26573e860de` |
| Eigen 3.4.0 | `3147391d946bb4b6c68edd901f2add6ac1f31f8c` |

No sudo/system install, shell-profile changes, Docker, Vivado or programming
cable is needed for this build. Fedora's C++ compiler, CMake, Boost development
libraries and Python are used. Eigen is installed to the project-local
`build/openxc7/prefix`. GUI and Python bindings are disabled; the analytic
placer remains enabled. Full upstream compiler warnings remain in the logs.
This does not disable the project's strict RTL lint checks.

Reproduction, after obtaining the pinned sources at the paths above:

```sh
cmake -S build/openxc7/eigen -B build/openxc7/eigen-build \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/openxc7/prefix" \
  -DBUILD_TESTING=OFF -DEIGEN_BUILD_DOC=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --install build/openxc7/eigen-build
PKG_CONFIG_PATH="$PWD/build/openxc7/prefix/share/pkgconfig" \
  cmake -S build/reference/nextpnr-xilinx -B build/openxc7/nextpnr-build \
  -DARCH=xilinx -DBUILD_PYTHON=OFF -DBUILD_GUI=OFF -DBUILD_HEAP=ON \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/openxc7/prefix"
cmake --build build/openxc7/nextpnr-build -j4
python3 -u build/reference/nextpnr-xilinx/xilinx/python/bbaexport.py \
  --device xc7k480tffg1156-2 --bba build/openxc7/xc7k480tffg1156-2.bba
build/openxc7/nextpnr-build/bbasm -l \
  build/openxc7/xc7k480tffg1156-2.bba build/openxc7/xc7k480tffg1156-2.bin
make openxc7-check
```

The original installer is Ubuntu-oriented and includes destructive checkout
cleanup; it was inspected, **not executed**. The initial nextpnr configure ran
before the local Eigen install finished and failed to find `eigen3`; the
second configure found 3.4.0. This dependency-order failure is not RTL evidence.

## Constraint translation and retained gates

`tools/run_openxc7.py` validates the complete reviewed `fpga/ypcb.xdc` profile
before emitting a nextpnr-compatible literal-port XDC. It rejects changed,
missing, duplicated or additional constraints, rather than evaluating arbitrary
Tcl or dropping unrecognized commands. Five pin assignments and five explicit
LVCMOS18 settings replace the grouped selector. The clock remains **20 ns**.
The database independently supplies the package pin/site/bank mapping:

| Port | Pin | Bank | Site |
|---|---|---|---|
| SYS_CLK | AA28 | 14 | IOB_X0Y174, MRCC |
| SYS_RSTN | R28 | 15 | IOB_X0Y226 |
| LED0 | P30 | 15 | IOB_X0Y222 |
| LED1 | M30 | 15 | IOB_X0Y220 |
| LED2 | N30 | 15 | IOB_X0Y221 |

The two existing **external** reset/LED false paths are explicitly recorded as
not applied by nextpnr. No internal datapath exception is introduced. Unknown
constraints fail before synthesis. The runner also checks the synthesized port
set, block RAM inference and absence of unmapped logic. nextpnr runs with seed
3588 and no timing-failure, unrouted-net or undriven-constant waiver. Its final
clock report must contain the single SYS_CLK domain, the unchanged 50 MHz
constraint and finite achieved frequency at least 50 MHz.

Each attempt creates a new output directory; an existing attempt is never
overwritten. Reports retain source hashes, tool/database revisions, binary and
chipdb hashes, commands, complete logs, warnings, synthesis counts and generated
artifacts. Failed runs remain failures. A zero runner exit means only
`PNR_CHARACTERIZED_NOT_SIGNOFF`.

## Remaining physical-signoff work

Inspection of this pinned backend's `xilinx/arch.cc` finds no hold analysis,
generic FF timing constants, missing BRAM timing classification, and ignored
timing for registered DSP configurations. Its chipdb importer looks for
family-level timing files rather than proving all -2 speed-grade corners; this
pinned database has **no `kintex7/timings/` SDF directory**. Thus a reported
50 MHz pass would **not** prove the entire board design meets setup/hold.
nextpnr's routing/placement checks are also not a replacement for all electrical
and configuration DRCs. Actual configuration-bank voltage/CFGBVS remains
unconfirmed. These are explicit signoff gaps, not unsupported constraints we
have silently discarded to make a bitstream.

The runner does not call FASM/frames/bitstream generation, open a cable, program
SRAM or write flash. Future bitstream work requires a justified open-source
signoff path or other reviewed implementation evidence, plus the existing
board-electrical confirmation. Full NPU/GEMM, PCIe/DDR and real-device tests
remain separate unfinished work.

## Current execution status

Five constraint/report unit tests and `make generated-check` pass. These tests
are control-flow/data-validation evidence only. Native nextpnr compilation
completed successfully on 2026-09-21; the built binary reports Version
`d486d8e`, matching the pinned source. The fresh full production regression
also exits zero: 49 Python tests, 1,087,299 C++ comparisons, and 247 original
entries plus three CMAC benches per native simulator. The exact-part BBA
export and `bbasm -l` have now both completed with exit status zero. The
684 MiB `build/openxc7/xc7k480tffg1156-2.bin` has SHA256
`98f43994365b465b70f33b17ba9a9e2489f17f3eee4c2be332bea0cbbbe17bf2`.

However, the subsequent unmodified nextpnr architecture-integrity test
**failed**, exit 255:

```sh
build/openxc7/nextpnr-build/nextpnr-xilinx \
  --chipdb build/openxc7/xc7k480tffg1156-2.bin --test
```

`build/openxc7/chipdb_integrity.log` reports a failed `bel == bel2` assertion
in `common/archcheck.cc:41`, during BEL-name checks. This compares each
enumerated BEL with the result of looking its name back up. A diagnostic-only
binary identifies `ILOGIC_X0Y399/CE1USED`: enumeration returns `(328,24)` while
name lookup returns `(328,4)`. The exporter retains ILOGICE2/ILOGICE3 site
variants with identical BEL names, but the original lookup picks the first
name match without distinguishing its variant. The source-bound reproduction
is `build/openxc7/name-diagnostic-1789992207538105884/report.json` and uses
`tools/openxc7/diagnose_chipdb.py`. It retains every original assertion.
The pinned checkout is unchanged. No assertion, timing gate
or electrical constraint has been relaxed. The database is **not validated**,
and no P&R or hardware pass is claimed. The tested nextpnr binary SHA256 is
`369df036b39a4a37af40a6047d1f6608e1966a3521ce107b7ebf9dde8132f7e8`;
the assembler SHA256 is
`85a4c6d30daeee66ec78a79d875f7fa0433058c24f301efb114cd8dd4d7d1bb8`.

An isolated detached worktree, `build/reference/nextpnr-xilinx-variantfix`,
tests a naming-only correction. It preserves the first legacy BEL name and
qualifies later colliding site variants with `@<variant>`; explicit malformed
qualifiers fail rather than selecting another BEL. No physical resource,
database entry or architecture assertion is removed. The complete experimental
patch is `tools/openxc7/variant-bels.patch`, against the pinned revision above.
The qualifier parser passes 13 C++ cases under `-Wall -Wextra -Werror`.
`tools/openxc7/build_variantfix.py` snapshots that source, builds a separate
binary and then runs the unchanged integrity assertions on the same chipdb.
The build completed, but its full integrity test **failed** at the next
category: `WIRE_NAME_MISMATCH name=INT_L_X0Y399/ER1BEG_S0` and the unchanged
`wire == wire2` assertion. Report:
`build/openxc7/variantfix-1789993004478901845/report.json`. BEL name checking
completed; this is not a full architecture pass or production adoption.

A separate partial diagnostic, `tools/openxc7/audit_chipdb_names.py`, links
`name_audit.cc` against the original completed build objects and always exits
unsuccessfully. It independently stops at the first problem in each category,
without producing a place/route artifact. Its report is
`build/openxc7/name-audit-1789998629328651106/report.json`. In addition to the
BEL-name collision, it finds a global wire node looked up as a local tile wire,
a generated arrow-form PIP name rejected by the lookup parser, and a BRAM BEL
location collision at `(19,5,10)`. This is explicitly a partial diagnostic,
not a bypassed integrity pass.

The read-only binary audit `tools/openxc7/audit_bel_locations.py` checks all
97 tile types and cross-checks the two observed BEL entries against the C++
diagnostic. It finds eight z-coordinate collision groups, all in BRAM_L/R,
with no group containing two placeable BELs. Report:
`build/openxc7/bel-location-audit-1789999007831891409.json`.

`tools/openxc7/repair_routing_z.py`, using `chipdb_layout.py`, generated a
separate experimental database at
`build/openxc7/routing-z-repair-1789999188717257025/xc7k480tffg1156-2.bin`.
It changes only eight hidden routing BEL z fields to unused values within the
existing 0..255 range. All placeable coordinates, site/variant associations,
pins, wires, timing and other bytes remain unchanged. The source-bound report
records every change and a whole-file comparison after normalizing those
eight fields back to their original values. The original database is intact.
This is a **generated repair candidate**, not an accepted chipdb: complete
integrity checks, routing behavior and physical signoff remain unproven.

`tools/openxc7/build_lookupfix.py` now builds an isolated wire/PIP lookup
candidate from the completed BEL-variant build. It canonicalizes wire IDs with
the architecture's existing `canonicalWireId` helper and uses
`PIP/<tile-name>/<record-index>` to name each exact PIP, including site variants
and parallel edges. The existing fixed-route serializer/parser and legacy
lookup forms are unchanged. The new names are specific to the pinned chipdb;
they are not portable constraints. Malformed, unknown-tile and out-of-range
canonical names return an invalid PIP instead of indexing arbitrary data.

The new strict parser passes 23 directed cases (including overflow, empty,
negative and trailing-junk rejection) plus 100,000 integer-name round trips.
The runner generates and records its exact `arch.cc` diff and compiles just
that object, then links against the unchanged completed variant-build objects.
Original sources, object files, binary and database are left intact. No
architecture assertion is changed. It then requests the full `--test` against
the separate routing-z candidate, with an explicit 8 GiB address-space ceiling
and a 7,200-second timeout; hitting either is a failure, not a skipped check.
The initial run completed at
`build/openxc7/lookupfix-1790000053728435896/report.json`: parser, compilation
and linking passed, but full integrity **failed** after 1,641.704 seconds with
`std::bad_alloc` under the 8 GiB address-space ceiling. BEL and wire name
checking completed before the failure during PIP name checking. This is not
an assertion-free architecture pass: remaining categories were not verified.
No limit or assertion was removed to convert this into a pass. This candidate
is not adopted by the placement runner and no P&R or physical result is claimed.

```sh
python3 tools/openxc7/build_lookupfix.py \
  --base-report build/openxc7/variantfix-1789993004478901845/report.json \
  --repair-report build/openxc7/routing-z-repair-1789999188717257025/report.json
```

## Newer local Himbaechel candidate: actual timing inventory

The legacy backend findings above are not automatically findings about newer
tools in other projects. A separate soDLA candidate now has an exact-part
qualification for a distinct-input LUT-pair legality correction and three
small native placements, with 1,024 LUT output comparisons. That qualification
does not establish full RKNPU placement, routing or timing. No tool in this
project has been replaced, and no running replay was changed.

The [read-only binary inventory](../build/openxc7/himbaechel-timing-inventory-1791385751625357013/report.json)
checks all 1,739 recorded candidate dependencies against their saved hashes.
It then decodes the selected database's actual version-6 packed timing tables,
with selected input hashes checked before and after parsing. The database
SHA256 is `790e05a88e8406b4da69d4fb6a158317e2621c85aa8452973edc85a8a4be1492`.
It contains one speed grade, named **DEFAULT**, and twelve cell timing types:
LUT, FF, carry, mux and eight BRAM variants. **There is no DSP48E1 cell timing
type.** This matters to the full observed board, whose completed mapping
retains 512 CMAC DSPs plus three shell DSPs; an Fmax report from that database
cannot establish coverage of those DSP paths or the required -2 corners.

The inspected qualified source differs materially from the old backend:
it imports BRAM sequential arcs and has an opt-in post-route hold-repair pass.
However, its generic timing lookup returns `TMG_IGNORE` for a cell with no
timing index. Its generator still supplies stub LUT/FF timings and substitutes
Artix-7 SDF for Kintex-7 carry/mux/BRAM timings. The actual binary inventory,
not those source comments alone, establishes the missing DSP type and DEFAULT
grade above. Hold-repair availability does not establish complete model,
port/clock, pulse-width, electrical or configuration coverage.

The [inventory implementation](../tools/openxc7/audit_himbaechel_timing.py)
does not execute donor scripts or place/route, emit bits or program hardware.
Four [synthetic parser controls](../tests/cmac/test_himbaechel_timing_inventory_control.py)
pass in the [fresh source-bound control record](../build/himbaechel_timing_inventory_controls_20261007.json),
including invalid ranges, schema/ID mismatches and an explicitly empty
model. These controls are not timing tests. The first inventory attempt
failed its own overly narrow dependency-path admission; its FAIL report is
retained separately. The fresh inventory explicitly admits only the observed
compiler/Yosys/Boost dependencies in addition to the two source trees.
No missing model, timing check or electrical constraint is waived.

```sh
python3 tools/openxc7/audit_himbaechel_timing.py \
  --qualification /home/fedora/soDLA/build/ypcb/lut-pair-engine-1791377260734986151/qualification.json \
  --database /home/fedora/tiny-gpu/build/ypcb/nextpnr-build/share/himbaechel/xilinx/chipdb-xc7k480t.bin \
  --constids /home/fedora/tiny-gpu/build/ypcb/nextpnr-himbaechel/himbaechel/uarch/xilinx/constids.inc
python3 -m unittest discover -s tests/cmac \
  -p test_himbaechel_timing_inventory_control.py -v
```

Current dependency hashes do not rerun historical native probes, and this is
not an atomic donor-checkout snapshot or full architecture qualification.
Candidate reuse for physical characterization remains distinct from accepting
a test-ready bitstream; full-circuit timing coverage and the original physical
and electrical gates remain outstanding.

## Full C32/K16 packing preparation (2026-10-08)

The separate [input preparer](../tools/openxc7/prepare_prefix_pack_input.py)
expands all sixteen admitted C32 kernels literally. It adds only two input
buffers, three output buffers and one global clock buffer. It verifies the
source/parent manifests, reversible module/instance aliases and an exact
endpoint-preserving wire bijection, including primitive parameters and pin
directions. Removing just those six buffers must restore the same circuit.
This is build-time structural preparation, not runtime arithmetic or layout
repair, and it does not change the raw-command execution boundary.

The original failed mapped-board replay remains FAIL. Only its completed
structural export is reused; no full-board numerical acceptance is inherited.
The first actual preparation fails at debug-scope cell membership. The second
fails at absent pin-direction annotations in the definition-free Verilog
roundtrip. Both terminal reports and executed preparer snapshots are retained.
The corrected admission excludes only unconnected `$scopeinfo` debug records
and restores only missing direction annotations from the hash-verified mapped
source. Explicit annotation differences, connected debug pseudo-cells,
changed primitive parameters, split/merged wires and missing cells still fail.
The subsequent library-loaded Yosys export must also pass the strict identity
comparison; annotation restoration is not itself circuit acceptance.

The [third actual preparation](../build/openxc7/full-prefix-pack-input-1791389592714656588/report.json)
passes the strict original-mapping/export circuit identity in both modules,
then fails at a duplicated formal output wire during literal expansion. This
is a terminal FAIL, not full-input acceptance. The kernel's `result[38]` and
`result[39]` share one wire in the source graph; their two distinct parent
fanout wires therefore need the same structural join performed by HDL
flattening. The fresh preparer records exactly this join for each of sixteen
kernels, and rejects conflicting input aliases, unexpected constant actual connections
and independently driven output nets. It neither changes arithmetic nor
removes a lane. All primitive counts and per-kernel DSP guards remain.

The [fourth actual preparation](../build/openxc7/full-prefix-pack-input-1791391415645948583/report.json)
is also terminal FAIL, at a constant formal output. The exact admitted
[mapped Verilog](../build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/mapped_board.v)
already assigns `invalid = 1'b0` in the kernel; the strict two-module
mapping/export identity still passes before this expansion failure. The new
preparer records and propagates exactly sixteen source-proven `invalid=0`
connections, without adding/removing a primitive. Unknown/high-impedance
formal constants, constant input formals and independently driven ties fail.
This preserves the mapped source, not a change to the RTL fault policy.

The [fresh control record](../build/openxc7/prefix-pack-controls-1791391764095854712/report.json)
passes eighteen methods and `make generated-check`, with frozen executed
sources and actual logs. Two methods run real Yosys 0.65: a small five-port
buffer control, and an independent `flatten -noscopeinfo` comparison for the
duplicated-output/constant-output fixture. The other methods test hierarchy expansion,
collision and unsafe-alias rejection, wire bijection, buffers, metadata and
native-pack admission/constraints.
These controls do not validate full-board HDL, native packing, placed fit,
timing or hardware. The production source manifest remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`;
the latest actual production `make test` remains the archived compile-limit
failure described in [verification status](../verification/README.md).

The alias-fix host service was confirmed live at 00:43 HKT on 2026-10-08,
then its own report records the constant-output failure at 00:46:39 HKT.
A fresh constant-output preparation was launched at 00:50 HKT using the
qualified source under a 4 GiB per-process address-space limit and a 7,200-second
outer runtime limit. Its
[terminal report](../build/openxc7/full-prefix-pack-input-1791391821565889099/report.json)
is FAIL: expansion retains all 503,122 mapped primitives, sixteen kernels,
512 CMAC plus three shell DSPs and six BRAMs, with exactly sixteen output-wire
joins and sixteen constant outputs. The complete 342 MiB literal JSON is
written. The subsequent real Yosys JSON load reports `std::bad_alloc` and exits
with return code -6. No buffer roundtrip, full-input or native-pack acceptance
is inferred from these structural results.

After the terminal failure and an actual host-memory observation of about
20 GiB available, an unchanged-source fresh attempt was launched at 01:04 HKT
with an 8 GiB per-process address-space limit and the same outer time limit.
Its [completed report](../build/openxc7/full-prefix-pack-input-1791392677842220299/report.json)
and [actual launch record](../build/openxc7/full-prefix-pack-input-1791392677842220299/launch.json)
identify that attempt, not a restart or reclassification of the failed run.
It finishes at 01:20:26 HKT with
`PREPARED_FULL_C32K16_LITERAL_PACK_INPUT_NOT_NATIVE_PACKING_OR_SIGNOFF`.
Actual Yosys 0.65 returns zero for all three commands; the physical-I/O command
takes 227.206 seconds and `check -assert` reports zero problems. Removing only
two IBUFs, three OBUFs and one BUFG restores exact identity across 503,122
primitives, 2,425,113 port/pin endpoints and 587,329 bijective wires. All
sixteen kernels/512 CMAC DSPs remain. Input hashes are revalidated before
completion. The outer process exits zero in 15:56.71, with a measured maximum
RSS of 5,746,520 KiB. This completes full-input preparation only, not native
packing, placement, timing, electrical or numerical acceptance.

At the 00:43 HKT host observation, the separate full mapped-board replay has completed
its fresh wrong-golden negative with the exact expected return code 1 and
first-output rejection; its mode-0 simulator PID 1251786 is confirmed live.
None of the nine positive modes has completed. The subsequent restricted
process namespace cannot observe those host PIDs or the user-service bus.
That observation limit is not evidence that either job stopped and does not
authorize restarting the numerical replay. These are dated observations, not
positive numerical or physical results.

The [native pack-only runner](../tools/openxc7/pack_prefix_board.py) requires
a completed source-matching full-size preparation and rechecks all recorded
newer-tool dependencies and the actual timing inventory. It uses seed 3588,
the exact -2 part, unchanged 20 ns target and `--Werror`. It explicitly
accounts for the original five pin assignments, five LVCMOS18 properties,
clock-label metadata and the two unapplied external timing exceptions.
Unknown or changed constraints fail. The profile is not a signoff constraint
profile. The runner has no placement, routing, FASM, bitstream or programming
action. A completed native pack would still not prove placed fit or close
the missing DSP/-2 timing, electrical and DRC gates.

The [first full-size native-pack attempt](../build/openxc7/full-prefix-native-pack-1791393786264406533/report.json)
is terminal FAIL. All three actual native commands exit zero, including
234.748 seconds for packing, but the result validator rejects the exported
module label. The qualified source's `json/jsonwrite.cc::write_module` emits
the context's `module` attribute, or the literal `top` when absent; `--top`
selects the input module without setting that attribute. Both the actual
full-size output and the earlier qualified small placement show the default
label. This is a validator/producer-contract mismatch, not a demonstrated
RTL or native-packing numerical defect. The failed report, logs, native
output and frozen executed source remain unchanged.

The corrected validator records this source-bound context-label translation
without changing any graph data. It checks the producer/version, the exact
single-module convention and all five grouped board port bits/directions.
Unexpected labels, module attributes, producers, port shapes/offsets or
merged external endpoints fail. The
[fresh control report](../build/openxc7/prefix-pack-controls-1791394542540920062/report.json)
passes 21 methods and `make generated-check`, including a
[real small Yosys/native-pack exporter control](../build/openxc7/prefix-native-export-small-control-1791394543738635665/report.json)
under the same exact-part, 50 MHz, seed-3588, strict-diagnostic profile.
The production source remains unchanged. These small controls do not
establish full-size native-pack or physical acceptance. The subsequent
[scope-corrected control record](../build/openxc7/prefix-pack-controls-1791395113705032368/report.json)
also passes all 21 methods and `make generated-check`. It explicitly records
small-native execution separately from full-board native packing, and binds
the completed small-native report/artifacts rather than using an unqualified
false execution flag. The older control record is preserved unchanged; its
`native_packing_executed=false` field was intended as full-board scope, although
the added small control did perform native packing.

The fresh full-size pack-only attempt launched at 01:37 HKT now completes at
01:44:30 HKT. Its
[completed report](../build/openxc7/full-prefix-native-pack-1791394643587130253/report.json)
and [launch record](../build/openxc7/full-prefix-native-pack-1791394643587130253/launch.json)
bind it to the same completed preparation, with the same 8 GiB per-process
address-space and 7,200-second outer runtime limits. Status is
`PACKED_FULL_C32K16_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF`.
All actual commands return zero, with 219.626 seconds for native packing.
The outer process exits zero in 7:21.26, with maximum RSS 4,493,436 KiB.
Source/artifact/dependency checks and the source-proven native exporter
contract complete. The packed graph contains 538,118 cells: 502,795
SLICE_LUTX output slots, 17,519 flip-flops, 8,630 carries, 8,640 SELMUXes,
515 DSPs, six BRAMs, one BUFGCTRL and the pad/constant cells. Every one of
sixteen retained kernel namespaces contains exactly 32 DSPs, preserving all
512 CMAC products plus three shell DSPs. No full-board numerical acceptance
is inherited. No placement, route or bitstream action is executed.

The native utilization table counts O5/O6 output slots, not independently
usable LUT sites; its displayed 84% is not fit. The next full-size gate is
native placement legality under the same part, seed, pin/clock profile and
strict diagnostics, retaining all 512 products. The available tool exposes
`--no-route`, not `--place-only`; the qualified small placement's exported
cells have explicit `NEXTPNR_BEL` bindings. A full-size placement attempt must
verify all retained DSP groups and unique complete cell/BEL assignment, not
infer legality from the pack counts. Even successful native placement would not close routed fit,
missing DSP/-2 timing coverage, electrical or DRC signoff.

The independent `tools/openxc7/place_prefix_board.py` now prepares that gate
without editing the admitted packing/preparation helpers. It revalidates both
completed parents and their source/artifact bindings, repacks the unchanged
original physical input in a fresh context, and runs the qualified static
placer with its normal refinement and final BEL validity check. It retains
the exact part, 50 MHz, seed 3588 and fatal warnings. It has no route, FASM,
bitstream or programming action. Its result gate requires native pack/place
settings, no route setting, unchanged primitive counts, all-cell unique BEL
bindings and the original sixteen groups of 32 DSPs. A positive result would
still be native-legality characterization, not complete architecture signoff
or numerical validation of the placed graph.

The [placement-control report](../build/openxc7/prefix-place-controls-1791396689590760130/report.json)
passes seven methods and `make generated-check`, preserving the production
source. It includes a
[fresh real small native placement](../build/openxc7/prefix-native-place-small-control-1791396691135662289/report.json)
with all 18 cells uniquely bound, completed normal refinement and strict
diagnostics; native placement exits zero in 44.236 seconds. Corrupt geometry,
part/clock/seed, unsupported acceptance flags, missing/duplicate BELs,
changed cells, DSP-group membership and unintended routing fail the controls.
The small control is not full-board placement acceptance.

The [full-size placement attempt](../build/openxc7/full-prefix-native-place-1791396866085235676/report.json)
launched at 02:14:25 HKT on 2026-10-08 under
`rknpu-full-prefix-native-place-20261008.service`. Its
[launch record](../build/openxc7/full-prefix-native-place-1791396866085235676/launch.json)
records the invocation, exact parent, 12 GiB per-process address-space limit,
12/14 GiB unit memory high/max, 4 GiB swap ceiling, six-hour native command
budget and seven-hour outer budget. These are build-host resource limits,
not DUT clock/test or acceptance changes. It is now terminal **FAIL**:
the native command aborted with SIGABRT (`-6`) after 4,080.530 seconds,
at iteration 395, at `std::isfinite(port.max_exp.at(axis))` in the static
placer. The service exited at 03:24:53 HKT on 2026-10-08. This is not a
completed placement or a demonstrated capacity failure. Its report, log and
frozen sources are preserved; no full placed-fit result or bitstream exists.

```sh
python3 tools/openxc7/run_prefix_pack_controls.py
python3 tools/openxc7/prepare_prefix_pack_input.py
# Only after that attempt reports PREPARED_FULL_C32K16_LITERAL_PACK_INPUT_NOT_NATIVE_PACKING_OR_SIGNOFF:
python3 tools/openxc7/pack_prefix_board.py --prepared build/openxc7/full-prefix-pack-input-<attempt>/report.json
python3 tools/openxc7/run_prefix_place_controls.py
# Only after that attempt reports PACKED_FULL_C32K16_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF:
python3 tools/openxc7/place_prefix_board.py --packed build/openxc7/full-prefix-native-pack-<attempt>/report.json \
  --precision-qualification /home/fedora/soDLA/build/ypcb/static-exp-qualification-<attempt>/qualification.json
```

### Placed-checkpoint reload and small routing qualification

`tools/openxc7/probe_prefix_route_resume.py` independently qualifies the next
stage using the completed small placement, never the failed full-size input.
The pinned frontend restores `NEXTPNR_BEL`/`BEL_STRENGTH` and the Xilinx
`preRoute` explicitly initializes tags for pre-placed checkpoints. This permits
`--no-pack --no-place` with the producer's actual emitted module label; it is
not a reason to guess that any JSON can be resumed.

The [first control attempt](../build/openxc7/prefix-route-resume-small-control-1791397661944843000/report.json)
is terminal FAIL after successful native reload because its validator expected
the initial export's port annotations. `frontend_base.h::create_iobuf` returns
early for synth-marked checkpoints, before populating `ctx->ports`; the pad
cells, their exact properties and named external nets survive, but a subsequent
export has no top-level port annotations. The corrected comparison explicitly
requires that exact all-ports-omitted producer case. It reconstructs annotations
only in a comparison view using the original named nets and pad endpoints,
checks every pad property/BEL and then requires whole-primitive parameter and
wire-bijection identity. It does not edit the native artifact or circuit, and
partial annotations or changed pad settings still fail.

The [second control attempt](../build/openxc7/prefix-route-resume-small-control-1791397860252759061/report.json)
is also terminal FAIL. Its exact reload identity passes, and the deliberately
duplicated BEL triggers the intended `BaseArch::bindBel` assertion, but the
harness incorrectly expects handled-error exit 125. The primary source shows
that `assertion_failure` is not the `log_execution_error_exception` caught by
`CommandHandler::exec`; this frontend assertion escapes and aborts with SIGABRT.
The fresh negative requires that exact signal and source-specific assertion
diagnostic, not an arbitrary nonzero return. Both failed reports, logs and
executed sources remain unchanged. Core files are disabled in subsequent
control children only.

The [fresh completed control](../build/openxc7/prefix-route-resume-small-control-1791398005736380470/report.json)
now passes six software methods and `make generated-check`, real native reload
with all 18 cells/49 endpoint bits/15 bijective wires unchanged, exact all-cell
BEL identity, the real duplicate-BEL rejection and small native routing. Routing
exits zero in 112.056 seconds with normal router2/router1 completion, all 18
cells retained and fifteen nonempty routing records. The full production source
remains `09f1c3f65ba9`; its latest full regression still records the earlier
600-second compile timeout, not a newly inferred production PASS.

This control also audits the actual linked `router1` function and binds its
router object. The linked function calls `Context::checkRoutedDesign` despite
the CMake cache's Release label; the actual compilation flags omit `NDEBUG`.
The cache alone was insufficient evidence for a disabled check. This is a
small actual routing control, not full-board connectivity/fit or timing/DRC
signoff. Missing DSP/-2 timing and electrical coverage remain explicit.

`postRouteArchInfo` changes exported BELs to global site/BEL names and site
wires to `SITEWIRE/site/pin`. Those names are not the generic checkpoint import
format. This control therefore does **not** admit the routed JSON for another
generic reload. A full-size routing runner must bind its own completed full
placement, retain all sixteen 32-DSP groups and validate the real full routing;
the small result cannot authorize bitstream emission.

```sh
python3 tools/openxc7/probe_prefix_route_resume.py \
  --parent build/openxc7/prefix-native-place-small-control-<attempt>/report.json \
  --precision-qualification /home/fedora/soDLA/build/ypcb/static-exp-qualification-<attempt>/qualification.json
```

### Full-routing admission and export-identity gate

`tools/openxc7/route_prefix_board.py` requires the completed, source-bound
full C32/K16 placement, not a RUNNING report or the small control. It binds
the full placement/packing/preparation parents and qualified native sources,
rechecks the actual linked connectivity-check call and routes the unchanged
original placed checkpoint with `--no-pack --no-place --router router2`,
the exact `xc7k480tffg1156-2`, 50 MHz, seed 3588 and fatal warnings. It has no
FASM, bitstream or programming action, and no timing/DRC waiver.

The read-only `himbaechel_site_bels.py` parser implements the pinned v6
chipdb structures and primary `Arch::init_tiles/getBelName`,
`get_site_bel_name` and `postRouteArchInfo` rules. It translates every
original tile-local BEL into the producer's global site/BEL spelling;
post-route cells must retain exactly those physical slots and all sixteen
32-DSP groups. This is not a heuristic coordinate conversion. No-site
pseudo-resources retain the original generic spelling.

The original primitive parameters and logical pin/wire incidence must also
survive. The pinned `fixup_routing` moves LUT physical input pins using
permutation pips and updates `X_ORIG_PORT_A1..A6`; `fasm.cc::get_lut_init`
uses those mappings to index the unchanged logical INIT. The checker permits
only source-defined LUT1..6 permutations and aliased logical inputs. It
compares every original logical pin, full literal INIT and wire bijection
in a comparison-only view, never an execution input or host arithmetic
fallback. All other LUT/resource attributes are retained exactly. Unknown
logical LUT kinds, parameters or pin mappings still fail.

The native packer also retains 32-bit integer INIT representations on some
LUT1/LUT2 cells. Its non-chain XORCY-to-LUT2-to-SLICE_LUTX transformations
retain the exact intermediate `I0=CI`, `I1=LI`, `O=O` annotations; the FASM
writer reads the physical A-pin mappings, not these intermediate keys.
The checker admits only that evidenced legacy triplet with the exact XORCY
INIT and requires it to remain unchanged. Declared disconnected outputs
remain empty logical output pins; their cells cannot disappear.

The [first gate-control attempt](../build/openxc7/prefix-route-gate-controls-1791399347218304750/report.json)
is terminal FAIL despite eleven passing software methods and a passing
`make generated-check`: its full packed inventory rejected the intermediate
XORCY annotations. That failure and its frozen sources remain unchanged.
A [fresh corrected attempt](../build/openxc7/prefix-route-gate-controls-1791399518373644844/report.json)
completes at 03:07:18 HKT on 2026-10-08 with twelve passing methods,
including all 1,956 injective LUT1..6 physical input permutations and explicit
corruption/admission negatives. The controls command exits zero in 8.073
seconds; `make generated-check` exits zero in 2.064 seconds with Python
3.14.5. Fresh read-only checks of the saved small exports prove all 18
physical BELs and the whole original logical circuit (49 endpoint bits,
15 bijective wires) unchanged. The full packed inventory validates all
502,795 logical LUTs and exact 538,118 primitive counts, including all 515
DSPs and six BRAMs. All 3,334 source/artifact bindings are revalidated and
the production source remains `09f1c3f65ba9`. Its latest full regression is
still the recorded 600-second compile-limit FAIL, not a new production PASS.
This control does **not** execute another native small route or any full
route; historical small-route execution is kept separate from fresh
read-only validation. Frozen failed/passing sources and per-run JSON
bindings are retained; no standalone `SHA256SUMS` file is created or updated.

The first full 512-product placement is terminal FAIL as of 03:24:53 HKT on
2026-10-08. The full route is not launched before completed full placement.
Even a completed route would be native connectivity characterization, not
DSP/-2 timing, electrical or DRC signoff. Bitstream emission remains gated.

```sh
python3 tools/openxc7/run_prefix_route_controls.py \
  --small-route build/openxc7/prefix-route-resume-small-control-<attempt>/report.json
# Only after the full placement reports PLACED_FULL_C32K16_NATIVE_LEGALITY_CHARACTERIZATION_NOT_ROUTED_FIT_OR_SIGNOFF:
python3 tools/openxc7/route_prefix_board.py --placed build/openxc7/full-prefix-native-place-<attempt>/report.json \
  --small-route build/openxc7/prefix-route-resume-small-control-<attempt>/report.json
```

### Full primitive configuration inventory and static-placer precision control

The [completed configuration inventory](../build/openxc7/prefix-config-contract-1791401020849392343/report.json)
revalidates the actual full input's 503,128 cells, all 515 DSPs and six BRAMs,
including all sixteen 32-DSP groups. Nine software methods and
`make generated-check` pass; the production source remains `09f1c3f65ba9`.
This is a source-defined parameter inventory, **not native FASM validation**.
The primary FASM writer has no `USE_MULT` branch for the actual `MULTIPLY`
configuration, so an independent DSP mode/feature check is still needed.
The actual BRAM parameters contain 432 unknown output-reset symbols and
90,112 unknown memory INIT bits. The source writer hardcodes zero output/reset
values and emits zero for unknown memory bits. The comparison-only half-INIT
reconstruction preserves every known memory bit. Observable startup/reset
independence remains unproven; these unknowns do not by themselves establish
an RTL or hardware defect. No comparison view is an execution input.

The [actual host precision control](../build/openxc7/static-exp-precision-probe-1791401782822101529/report.json)
reproduces `std::exp(float)` overflow with coordinates spanning the actual
327-by-417 device grid. At coefficient 0.5, a centered Y span of 0..416
produces exponent 104: the float overload overflows before assignment to
the placer's existing `double` storage. The old-overload negative exits 1
with its expected diagnostic. Widened overloads pass 1,028 extreme/random
cases and 1,024 finite-range cases (seed `0x3588e001`), with finite gradients
and a long-double objective reference. `make generated-check` also passes.
The failing native net was not captured, so correspondence to the native
assertion is a mechanism-based inference, not an observed native recovery.

The [isolated backend build](/home/fedora/soDLA/build/ypcb/static-exp-engine-1791401936054675202/report.json)
is complete. It changes only the two calls to
`std::exp(static_cast<double>(emin/emax))`, retaining all assertions,
wirelength objectives, coefficients, refinement and the earlier legality fix.
Relinking the old objects first reproduces the old executable byte for byte;
the candidate replaces only the static-placer object using the actual parent
compile/link commands. No global donor-engine pointer was updated. This is
host placement math, not FP16 RTL arithmetic, and does not change the target,
clock or acceptance requirements. Per-run JSON
bindings are retained without creating or updating standalone checksum files.

The full-placement runner now requires `--precision-qualification`; it does
not silently retry the old float-overload executable. It revalidates all fresh
native qualification inputs and outputs, checks the copied source differs
only at those two calls, and compares the actual link commands to require
only the static-placer object replacement. The earlier packed counts remain
an expectation, not inherited placement acceptance: the unchanged original
full input is repacked by the selected executable and all final primitive
counts, DSP group membership and unique BEL bindings must still pass.

The [fresh native qualification](/home/fedora/soDLA/build/ypcb/static-exp-qualification-1791402583316994514/qualification.json)
now completes with the candidate executable, the unchanged original fixtures,
normal refinement (no iteration cap), fatal warnings and the exact part at
50 MHz, seed 12350. Five admission/log/command software methods and
`make generated-check` pass. The forced illegal pair exits 125 in 46.689
seconds with the original validity/refinement errors, no assertion abort,
no postPlace continuation and no output checkpoint. The legal forced pair,
free illegal-pair separation and counter placements exit zero in 45.506,
51.408 and 59.307 seconds; all 49/49/47 cells have unique BELs. The two
LUT cases pass 1,024 fresh truth-table comparisons. All 1,771 qualified
native inputs/artifacts are revalidated; ROOT orchestration inputs retain
bindings in the report and byte-identical frozen copies inside the native
qualification's original dependency scope. The existing auditor's dependency
whitelist is unchanged. This qualifies small native legality only, not the
full placement, routing, DSP/-2 timing, electrical/DRC or numerical graph.

The [fresh full-placement controls](../build/openxc7/prefix-place-controls-1791402730325544053/report.json)
pass seven placement methods, four exact precision-transition methods and
`make generated-check`. They retain a fresh real small native placement on
the earlier qualified engine, separately from the above candidate's three
fresh native placements. The transition controls reject partial fixes,
assertion removal, coefficient or other source changes; the full retry's
command remains original-input repacking, normal refinement, fatal warnings,
seed 3588 and 50 MHz. The production source is unchanged and its latest full
regression remains the recorded compile-limit FAIL, not a new suite PASS.

The [fresh full-size retry](../build/openxc7/full-prefix-native-place-1791403059242726617/report.json)
launches at 03:57:37 HKT on 2026-10-08 under
`rknpu-full-prefix-native-place-precision-20261008.service`, invocation
`106cbf42d5dd477693abf2863e8ded4d`. Its
[launch record](../build/openxc7/full-prefix-native-place-1791403059242726617/launch.json)
binds the selected qualification, control report, unchanged packed parent,
full command and original resource bounds: process AS 12 GiB, unit high/max
12/14 GiB, swap max 4 GiB, native timeout six hours, outer timeout seven hours,
core dumps disabled, CPU weight 25 and nice 5. This is a RUNNING attempt,
not completed placement or fit; read the current report and unit state.
The earlier failed attempt remains untouched. No full route, bitstream or
programming action has been launched. The separate full mapped numerical
replay remains live on mode 0 with no completed positive mode as observed
at 03:58 HKT; no numerical pass is inherited by the physical preparation.

The earlier saved small routing control remains historical evidence for the
earlier engine. Fresh precision-engine qualification and full-route selection
are now complete as preparation, described below; full placement must still
complete before invoking the full router.

### Fresh precision-engine routing qualification and full-route selection

The [fresh small routing control](../build/openxc7/prefix-route-resume-small-control-1791403326838799733/report.json)
completes at 04:06:42 HKT on 2026-10-08. It uses the precision-fixed executable
and the [fresh actual small placement](../build/openxc7/prefix-native-place-small-control-1791402732077883039/report.json),
keeping the exact part, 50 MHz, seed 3588, fatal warnings and original placed
checkpoint. Six software methods and `make generated-check` pass. The actual
reload exits zero in 3.032 seconds with all 18 BELs, 49 logical endpoint bits
and 15 bijective wires unchanged. A duplicate-BEL input aborts with the original
source-specific SIGABRT in 3.053 seconds and writes no accepted output. The
actual router exits zero in 154.334 seconds with native connectivity checks
and all 18 resources retained. The final linked `router1` connectivity-check
call is independently inspected in the selected executable. All 1,840 bound
inputs are revalidated; no full-board numerical or physical signoff is claimed.

The full routing runner now selects the same freshly qualified executable
recorded by the completed full placement, not the old default float engine.
It requires an explicit `--small-route` report using that identical transition
and executable. Incomplete small/full results, changed tool bindings, missing
execution/negative evidence, timing or physical claims borrowed from a small
control, and unsupported engine transitions fail admission. The original
checkpoint, physical footprint, literal primitive parameters, logical pin/wire
identity and full sixteen-by-32 DSP membership gates remain.

The [fresh source-bound full-routing controls](../build/openxc7/prefix-route-gate-controls-1791403806918797356/report.json)
complete at 04:20:22 HKT on 2026-10-08: fourteen methods pass in 7.040 seconds,
and `make generated-check` passes in 2.135 seconds. The controls retain all
1,956 LUT1..6 input permutations and prior corruption/error expectations,
adding mandatory precision-engine and completed small-route metadata checks.
Read-only validation of the new small exports checks every physical BEL and
the complete original logical circuit. The actual full packed inventory
checks all 502,795 LUTs and 538,118 cells, including all 515 DSPs and six BRAMs.
All 3,367 source/artifact bindings are revalidated and the production source
remains `09f1c3f65ba9`. This run does not rerun a native router; its fresh
saved-export checks and the earlier same-turn native execution above are
separate evidence levels. No standalone checksum manifest is written.

The [actual pending-full-placement CLI rejection](../build/openxc7/full-prefix-native-route-1791403841892983100/report.json)
is deliberately terminal FAIL at the placement-completion assertion, in
admission, with an empty native-command list and `native_routing_executed=false`.
It demonstrates that the real entrypoint refuses the currently RUNNING full
placement; it is not a failed physical routing run. Its frozen source and
report are retained. No full router or bitstream action occurred.

As observed at 04:21 HKT, the full placement retry is live in static placement
(iteration 72 was observed), and full mapped numerical replay is still live
on mode 0 with no completed positive mode. The original finite-assertion
failure occurred at iteration 395, so no full recovery/fit claim follows from
the current progress. DSP/-2 timing, electrical/DRC, actual native FASM
configuration comparison and observable BRAM startup/reset independence
remain open before reviewed bitstream emission.

### Literal native DSP/BRAM configuration control

The new [literal encoder fixture](../tools/openxc7/probe_prefix_native_config.py)
selects all six actual BRAM configurations and four DSP representatives
(the three shell cells plus one of the 512 CMAC cells). It copies every
primitive parameter, pin width and literal input bit exactly. Variable wires
are explicitly remapped into a small test-only circuit. This is an encoder
control, **not the original circuit, an NPU execution image or a smaller
replacement for the full 512-product target**. Comparison vectors are never
used as execution inputs. No bitstream is generated from this fixture.

The [first actual native attempt](../build/openxc7/prefix-native-config-control-1791405301618545303/report.json)
finishes FAIL at 04:46:53 HKT on 2026-10-08: its unchanged native command
is killed at the 600-second host wall limit (600.264 seconds, return code -9)
during normal static placement. Four fixture/parser methods, generation
checks and the native version query pass, but no completed route or FASM
comparison is accepted. Its actual log, input, frozen executed source and
terminal report remain in their original directory; this is not a numerical
mismatch or a completed placement result.

The [fresh feature-corruption controls](../build/openxc7/prefix-native-feature-controls-1791406115670927321/report.json)
complete at 04:48:45 HKT with Python 3.14.5, four software methods in 6.168
seconds, and `make generated-check` in 2.604 seconds. All 65 selected
source/artifact bindings are revalidated, with production revision
`09f1c3f65ba9` unchanged. Synthetic tests cover the four literal DSP
representatives on both tile sides/slots and all six BRAM contracts. They
reject missing/extra register or SIMD bits, wrong inversions, conflicting
constant ties, changed multiplier parameters, INIT corruption, wrong widths,
extra write modes, registered outputs and wrong reset-output vectors. These
are software controls, not native FASM execution or a physical-mode proof.

The [strict comparator](../tools/openxc7/check_prefix_native_features.py)
derives DSP pin inversions and 31 dedicated constant ties from the pinned
`pack.cc`, `pins.cc`, `pack_dsp_xc7.cc` and `fasm.cc`, retaining the shell's
different C/OPMODE literals. BRAM comparisons cover both physical halves'
INIT/INITP, width/write-mode and unregistered output/reset features. The
native runner now invokes both fixture and corruption controls and requires
the actual placement dump, routed primitive census and feature comparisons.
Ordinary constant-net routing, observable BRAM startup/reset independence,
physical multiplier-mode acceptance and full-board signoff remain separate
requirements.

The independent local X-Ray fuzzer requests `USE_MULT` tags, but neither
exact local Kintex-7 DSP segbits database contains them, and the native writer
has no branch for that parameter. [AMD's DSP48E1 attribute documentation](https://docs.amd.com/r/en-US/ug953-vivado-7series-libraries/DSP48E1)
defines `MULTIPLY` as the attribute default; it does not establish the actual
physical interpretation of this tool's emitted configuration. The comparator
therefore explicitly retains `USE_MULT_physical_default_verified=false`.
The 90,112 unknown memory bits are still reported, not silently accepted as
unobservable padding.

To retry the native control with a longer host-only budget:

```sh
python3 tools/openxc7/probe_prefix_native_config.py --native-timeout 3600
```

The budget is bounded to 600..7200 seconds and does not cap placer iterations,
relax the 20 ns target, disable refinement, suppress fatal warnings or remove
legality checks. Each invocation creates its own report and inputs; the old
timeout is not relabeled. No standalone checksum manifest is written.

The [second actual attempt](../build/openxc7/prefix-native-config-control-1791406235840013595/report.json)
finishes FAIL at 05:09:34 HKT on 2026-10-08: routing and FASM emission finish,
but the native tool returns 1 because the fixture's missing `SYS_CLK` net alias
prevents the literal 20 ns `get_ports` constraint from being applied. This is
not an accepted route or timing result, and the report remains unchanged.
The preceding
22-method targeted native preparation suite passes in 169.694 seconds,
including fresh actual small export and placement controls on the earlier
qualified engine; those small results are not transferred to the full target
or counted as execution by a new configuration-control attempt.

The fixture now includes standard public-port net aliases, with exact bit
binding checks. Before PNR, a separate actual native pack-only command must
report application of the `SYS_CLK` clock constraint exactly once; unmatched
targets, warnings and errors still fail. No constraint or native parser is
changed. Eight fixture/parser/budget methods and four feature-corruption
methods pass, followed by `make generated-check`.

The pinned native writer emits each enabled I/O `STEPDOWN` flag twice: once
under the IOB context and again after popping it. The F4PGA FASM merger treats
repeated identical assignments as a set and rejects conflicting assignments.
The native comparator records only this exact source-defined pair explicitly;
other duplicates, conflicting values and a third repetition remain errors.
The original strict-parser duplicate test is retained. Read-only comparisons
of the rejected attempt's four DSPs and six BRAMs match, but do not promote its
clock FAIL to acceptance.

The [clock-bound fresh attempt](../build/openxc7/prefix-native-config-control-1791407940428316242/report.json)
completes at 05:42:25 HKT on 2026-10-08 with actual native routing/FASM and
source-defined feature comparisons passing. It uses the same part, 50 MHz,
seed 3588 and strict legality gates. Early native clock admission takes
4.471 seconds; actual PNR/FASM takes 1,251.940 seconds with return code 0.
The tool is `nextpnr-himbaechel` version `c68c135`, bound to the precision
engine and 1,888 source/artifact inputs. Production source stays `09f1c3f65ba9`.

All 286 native cells have unique BELs. The four DSP representatives match
17/17/17/19 source-defined configuration flags and 31 dedicated constant-pin
features each. All six BRAMs match their 144 memory vectors each, widths,
read-first modes, output-register policy and source-defined reset vectors.
All 7,663 parsed features retain the five explicitly recorded repeated I/O
`STEPDOWN` pairs. The old timeout and unmatched-clock attempts remain FAIL.

This is a completed **test-only encoder control**, not the full C32/K16 image,
numerical acceptance or physical signoff. The native log explicitly reports
no interior timing paths/Fmax. Physical `USE_MULT` defaults, ordinary constant
net routes, BRAM startup independence, exact -2 DSP timing and electrical/DRC
remain open; neither the control nor its comparison authorizes a bitstream.

### Full routed DSP/BRAM FASM gate preparation

The full routing runner now additionally requires that completed actual
encoder control for the identical qualified engine, with all original
placement/reload, legality, logical-circuit identity and physical-footprint
gates retained. It requests `full-board.fasm` and `native-placement.json`
alongside the routed JSON. No full route has run and no full FASM result is
claimed from preparation.

[The full feature checker](../tools/openxc7/check_full_native_features.py)
requires all 515 actual DSP names, three shell DSPs, sixteen 32-DSP kernels
and all six actual BRAMs. Complete selected native JSON records and placement
records must exist with unique BELs. The exact pinned v6 database translates
tile-relative placement labels to the post-route global site labels; it does
not infer coordinates or erase a label mismatch. All source-defined DSP
configuration/dedicated-tie features and BRAM memory/width/mode/output features
are compared against the literal inventory. Unknown syntax, conflicting or
unsupported duplicate features still fail.

Five new full-inventory/reader/corruption methods pass in 24.711 seconds. They
also revalidate all ten saved actual small-control records while explicitly
rejecting them as full-target evidence. The fourteen original routing methods
pass in 8.065 seconds without changing their error expectations. A fresh
[source-bound gate-control run](../build/openxc7/prefix-route-gate-controls-1791410107157641073/report.json)
now passes: the fourteen routing methods take 12.087 seconds, the five full
feature methods 18.801 seconds and `make generated-check` 2.952 seconds.
It revalidates saved native artifacts and all 502,795 packed logical LUTs,
alongside the exact 515-DSP/six-BRAM census and sixteen 32-DSP kernels. It is
not new native routing or full FASM acceptance. No standalone checksum
manifest is written.

A [fresh real CLI admission negative](../build/openxc7/full-prefix-native-route-1791410568957469603/report.json)
returns 1 at the unchanged placement-completion assertion when given the live,
unfinished full-placement report. It has no native commands and both routing
and FASM-emission flags false. That is an expected admission rejection, not a
physical routing failure and not permission to bypass the pending full build.

At the 06:12 HKT observation on 2026-10-08, the full precision-engine native
placement process is still live and has reached strict legalization of
433,249 cells after iteration 629. It has passed the old iteration-395
exponential assertion point without removing that check. The full resource
inventory and 512-product target are unchanged. Legalization has no terminal
result yet; it is not completed placed fit, routing or bitstream acceptance.

### Actual full BRAM output and unknown-INIT classification

The [read-only full-input audit](../build/openxc7/prefix-bram-output-audit-1791406793437962391/report.json)
completes at 05:04:02 HKT on 2026-10-08. Its actual scan parses all 503,128
primitive cells, including all 515 DSPs and six BRAMs, in 197.225 seconds. All
432 BRAM output pin bits have their exact driver and every primitive/top-level
consumer checked. Selected BRAM records must match the prior literal
inventory; missing drivers, aliases, unsupported bidirectional consumers,
changed records and incomplete primitive counts fail.

The resulting [actual consumer bindings](../build/openxc7/prefix-bram-output-audit-1791406793437962391/actual-BRAM-output-consumers.json)
give this classification for the 9-bit memories. A lane count refers to bits
with direct consumers, not a physical-capacity reduction or liveness proof of
every downstream computation.

| Actual cell suffix | Role | Consumed data/parity lanes | Known INIT bits with consumers | Unknown INIT bits with consumers | Unknown INIT bits without consumers |
|---|---|---:|---:|---:|---:|
| 86684 | Working RAM | 9 | 0 | 36,864 | 0 |
| 86685 | Working RAM | 7 | 0 | 28,672 | 8,192 |
| 86686 | ROM | 9 | 36,864 | 0 | 0 |
| 86687 | ROM | 9 | 36,864 | 0 | 0 |
| 86688 | ROM | 9 | 36,864 | 0 | 0 |
| 86689 | ROM | 5 | 20,480 | 0 | 16,384 |

Parity output 0 really has consumers in RAM 86684 and ROMs 86686..86688;
it is not generally unused padding. Only the graph-proven unconnected lanes
account for the 24,576 unknown bits without consumers. The remaining 65,536
unknown bits are on consumed working-RAM lanes. This refines, rather than
discards, the prior 90,112-unknown-bit inventory. Unknown initial/reset-output
symbols remain a separate requirement.

Using the pinned UNISIM widest-width=9 memory decomposition (eight data bits,
one parity bit, 4,096 words), all 131,072 consumed ROM bits match complete
source-image slices at offsets 0, 9, 18 and 27. Every bank compares all 4,096
addresses. This is exact INIT-content evidence; it does not yet prove the
full ROM logical-output/address wiring, routed configuration or startup
ownership. The report explicitly keeps those acceptance flags false.

Six synthetic graph/INIT corruption methods pass in 10.731 seconds with
Python 3.14.5; `make generated-check` passes in 3.991 seconds, and the actual
packaged-ROM read-only consistency check passes in 1.383 seconds. This work
does not rewrite fixtures consumed by the live mapped simulation, substitute
CPU arithmetic, alter RTL, or relabel an unknown as a hardware golden. The
production source remains `09f1c3f65ba9`. Full-board numerical, write-before-
read/reset, DSP/-2 timing, electrical/DRC and full native PNR/FASM gates remain.

Separately, the full [mapped-board continuation](../build/rknpu-dsp-prefix-observed-board-continuation/1791382468965621354/report.json)
now passes positive mode 0 in 15,350.996 seconds, after its real wrong-golden
negative: 4,096 initialized/checked words, 196 command reads, 6,528 operand
reads, 64 writes/acknowledgements and 44,915 simulated cycles. As observed at
05:59 HKT, mode 1 also passes its expected command-response fault case in
4,223.511 seconds: all 4,096 words initialized, one command read, no operand
reads or output writes. Mode 2 is RUNNING; two of nine suite modes are complete,
including one successful numerical workload and one expected-fault case.
This is mapped simulation, not all-nine-mode acceptance or an FPGA test.
The full precision-engine placement remains RUNNING; neither control path
launches a full router, emits a bitstream or programs the board.

### Actual ROM and working-RAM logical address/data wiring

The [separate read-only wiring audit](../build/openxc7/prefix-memory-wiring-audit-1791408308815007879/report.json)
completes at 05:28:52 HKT on 2026-10-08 with 105 literal wire aliases and 66
source/artifact bindings. It checks the original mapped hierarchy's named signal bits against their exact
`n_<mapped-wire-id>` physical aliases and the six selected BRAMs. The completed
all-cell consumer/INIT audit, selected records, original hierarchy and
physical input are explicitly bound; this is not a second numerical test or
a new full-graph scan. The [actual wire bindings](../build/openxc7/prefix-memory-wiring-audit-1791408308815007879/actual-memory-wire-bindings.json)
record the literal translation and checked buses.

All 32 ROM output bits, including real parity outputs, match the logical ROM
word at offsets 0, 9, 18 and 27. Its low/high 16-bit halves match
`initial_value`/`expected_value`. All twelve address bits match the controller
index; ROMs remain read-only with their literal enables and write masks.
Both working-RAM banks match the host and core's full sixteen-bit input/output
buses, twelve-bit addresses and clock pins. The eight-data-plus-parity first
bank and seven-data-bit second bank are not reordered or repaired in software.

The four corruption methods cover ROM bit/half/parity ordering, clocks,
address order and constant bits, ROM write activation, duplicate content
slices, all four working-RAM data channels, missing resources, unmodeled
signals, non-scalar or non-bijective physical aliases and net offsets.
The four methods pass in 6.330 seconds on Python 3.14.5; `make generated-check`
passes in 2.140 seconds and the packaged-ROM read-only consistency check in
2.251 seconds. Production source remains `09f1c3f65ba9`.
The original consumer audit's logical-wiring flag remains unchanged;
this new, separately bound result closes that address/data gap only.

Write-before-read, host/core enable/write ownership and observable reset or
startup independence remain explicitly unproven. There is no FASM, timing,
electrical/DRC, numerical or physical-board acceptance from this audit. RTL,
execution fixtures and the full 512-product target remain unchanged.

### Actual small native FASM frame-database control

The [new local probe](../tools/openxc7/probe_prefix_frame_database.py) consumes
only the completed four-DSP/six-BRAM native configuration control's actual
`control.fasm`. It does not generate another smaller NPU or substitute for the
full C32/K16 placement. It revalidates the native control and reuses the
strict [soDLA converter](../../soDLA/tools/ypcb_frames/convert_fasm.py) and
[frame validator](../../soDLA/tools/ypcb_frames/validate_frames.py), with
VeriGPU's immutable-grid cache and single-line syntax profile. No donor file
is changed. The source-pinned Project X-Ray revision is
`ed3331c6200f421164101388759fc2860b0f5634`; its database revision is
`517d66a383676cb971177ea92b0ff3b6ea6e8690`. Both checkouts must be clean.

The first direct adapter control exposed the donor's trailing blank-line
trimming. The local bounded adapter now preserves every complete source line,
including whitespace and repeated statements, and still parses each chunk
with the installed FASM grammar. Fresh real-grammar equivalence and
unsupported-syntax controls execute before actual conversion. The installed
Python 3.13.13 parser uses its slow textX fallback; that runtime warning is
retained in the actual log, not presented as a native PNR warning or suppressed.
Missing-feature overrides are disabled. The strict converter rejects lookup
failures, invalid frame bit locations, skipped bank STEPDOWN injection and
unfulfilled observed clock-activity requests. This input has no BUFR-clock
activity requests, so those injection branches are not exercised here.

The [fresh source-bound run](../build/openxc7/prefix-frame-database-control-1791412166359639486/report.json)
completes at 06:33:20 HKT on 2026-10-08 with 2,342 input bindings, including
the newly imported admission helper and both interpreter binaries. Four
software control methods pass in 2.068 seconds, `make generated-check` in
1.874 seconds, actual strict conversion in 116.778 seconds and exact-part
frame geometry validation in 72.706 seconds. Every command returns zero;
the final input/artifact recheck also completes.

Actual conversion processes 7,668 native input statements (including the five
source-defined duplicate STEPDOWN pairs) and 97 source-defined default/injected
statements. No lookup failure is suppressed. The 51,490,824-byte frame payload
contains all 45,892 tilegrid frames, each unique and containing 101 unsigned
32-bit words; 7,975 words are nonzero. The exact `xc7k480tffg1156-2` part has
46,336 legal frame addresses. The 444 addresses outside tilegrid coverage
remain a later native-assembly requirement, not 444 frames validated in this
payload. No packet/bitstream assembler is called and no `.bit` is emitted.

The [earlier successful conversion](../build/openxc7/prefix-frame-database-control-1791411852765894620/report.json)
remains unchanged. It predates adding the new admission-helper/interpreter
bindings; the fresh run executes conversion again, rather than copying its
logs forward. No standalone checksum manifest is created. Production RTL,
mapped fixtures, full 512-product target and live job dependencies are unchanged.

This is a small source-defined encoder-chain control. Full-board native
placement/routing/FASM, physical multiplier defaults, ordinary constant-net
routes, BRAM startup/write ownership, DSP/-2 timing and electrical/DRC
acceptance remain separate open gates. It does not authorize bitstream
emission or board/flash programming.

```sh
python3 tools/openxc7/probe_prefix_frame_database.py
```

### Upstream DSP tile-constant encoding gap confirmed in actual artifacts

A live upstream check on 2026-10-08 finds openXC7 head
`26f5e17a5b956cd742a739f23d049e229114fdb8`, ahead of the selected engine's
`c68c13582e972292c86a5025140d52e713384cbc` base. Its inspected generator adds
BRAM write-mode-specific timing variants, but still supplies generic speed
grades, stub LUT/FF timing and Artix SDF fallback for Kintex. The public
[generator at that exact revision](https://github.com/openXC7/nextpnr/blob/26f5e17a5b956cd742a739f23d049e229114fdb8/himbaechel/uarch/xilinx/gen/xilinx_gen.py)
does not supply a DSP timing model. This scoped source check is not evidence
that every possible external timing source has been exhausted, nor a reason
to waive the existing exact-part/full-circuit timing requirement.

More importantly, upstream [DSP constant-pin correction](https://github.com/openXC7/nextpnr/commit/a662c08d25d7d2524ab341a387f120521c8a5d08)
includes all five INMODE bits, ALUMODE2/3 and OPMODE6 in dedicated tile ties.
Its prerequisite [logical-value/inversion correction](https://github.com/openXC7/nextpnr/commit/915d376e35f37b1b8c6e959dbe46999a1eaa321b)
composes bus and packer inversion correctly, emits the requested logical
constant and disables the physical inverter for a tile-tied pin. The old
packer comments these pins out, while the old FASM writer relies only on the
declared DSP tie attributes. Upstream documents that leaving these pins to
ordinary routing can produce wrong products despite a correct logical netlist.
That reported external silicon result is not a test of this board.

The [new read-only audit](../tools/openxc7/audit_upstream_dsp_constants.py)
checks the actual full packed inventory and completed small native output,
not a hypothetical multiplier. The [fresh audit record](../build/openxc7/upstream-dsp-constant-gap-audit-1791413435055802734/report.json)
finishes at 06:51:36 HKT with 70 direct input/source bindings. All sixteen C32
kernels, 512 CMAC DSPs, three shell DSPs and six BRAMs remain present. On all
515 DSPs the eight affected logical pins are zero, with the old packer's
per-bit inversion set to one, but absent from its dedicated-tie declarations:
**4,120 missing declarations**. Both levels of all eight pins in both DSP
slots on both tile sides are present in the local segbits database (64 keys).

The saved four-DSP actual native FASM differs from the required corrected
encoding at 64 features: 32 dedicated GND ties and 32 physical-inverter-disable
flags. The full native FASM has not been emitted, so these are four actual
FASM comparisons plus the complete 515-DSP packed-attribute census, not 515
actual FASM comparisons. Exact upstream source snapshots are saved inside
the audit attempt and were comparison data, not executed by that audit.
Five software controls pass in 1.604
seconds; they reject unsupported profiles, conflicting ties, lost required
features and a status that would hide one remaining gap. They are not new
native or physical tests. The earlier audit attempt is retained unchanged.

The audit's terminal status is a **confirmed encoding gap, not PASS or a
fix**. The old native configuration and frame-database controls retain their
original source-defined PASS statuses; the new evidence establishes that
old-source consistency/database lookup alone does not prove physical DSP
configuration completeness. No RTL, arithmetic, raw-command fixtures,
running placement/simulation input or global engine pointer is changed.
No checksum manifest, bitstream or programming action is produced.

The next corrective build must be isolated: port the DSP FASM/tile-constant
changes into the already qualified precision engine, preserve the static
placer, LUT-pair legality, unchanged chipdb, all sixteen C32 kernels and
every timing/electrical/DRC gate, and perform fresh native qualification.
Do not silently update all unrelated upstream changes or reuse old logs as
evidence for a modified encoder. The old 31-tie source comparator must not
be relabeled to admit a 39-tie corrected encoding; a separately source-defined
policy and controls are needed. Any reuse of the full placement needs complete
BEL/resource and effective-constant/wiring identity checks and native legality,
not an assumption that a checkpoint transfers to a different packer.

The current full placer and mapped simulation continue unchanged. A completed
old-engine placement would remain useful native legality characterization, not
authorization for reviewed bits from its defective encoder. The ordinary
constant-route, startup, exact -2/DSP timing and electrical/DRC requirements
remain open in addition to this concrete correction.

```sh
python3 tools/openxc7/audit_upstream_dsp_constants.py
```

### Isolated DSP constant encoder correction: built and native controls passed

The [new builder](../tools/openxc7/build_dsp_constant_candidate.py) creates its
own source, objects and executable under this project's build tree. The
[actual build record](../build/openxc7/dsp-constant-engine-1791414105309267504/report.json)
completes at **07:09:34 HKT on 2026-10-08** with terminal
`BUILT_ISOLATED_DSP_TILE_CONSTANT_CORRECTION_NOT_NATIVE_QUALIFIED_OR_PNR`,
not a corrected native qualification. It binds 3,287 inputs and preserves the
precision/static placer, LUT-pair legality objects, chipdb and all other
compiled objects. Exact upstream `a662c08` bytes are accepted only after
checking the DSP-writer and dedicated-tie source boundaries. No unrelated
upstream update, donor edit or global engine-pointer change is made.

The fresh parent relink is byte-identical (9.421 seconds); GCC is
`16.2.1 20260819 (Red Hat 16.2.1-2)`. Six build-boundary controls pass in
1.845 seconds and the recorded generated check in 1.756 seconds. Only
`fasm.cc.o` and `pack_dsp_xc7.cc.o` are replaced. Their actual clean compilations
take 283.349 and 64.322 seconds, and linking takes 11.087 seconds. The build
service exits zero; the production source remains unchanged. This proves a
completed modified engine build, not new native acceptance.

The [separate corrected comparator](../tools/openxc7/check_corrected_dsp_features.py)
requires 39 declared ties and the eight added logical-GND/physical-inverter-off
features for each supported DSP. It retains the exact literal parameters and
packer inversion parameters. The old 31-tie comparator and its errors are
unchanged. Six new feature-corruption controls pass, including rejection by
the old comparator of the new encoding and rejection of unsupported nonzero
tile-pin profiles. Five qualification-admission controls also pass. These
eleven software controls are not fresh native or physical results.

The [new qualification runner](../tools/openxc7/qualify_dsp_constant_candidate.py)
now [passes in its own fresh attempt](../build/openxc7/dsp-constant-qualification-1791414657664905509/report.json)
at **07:34:11 HKT on 2026-10-08**, with 3,328 source/input bindings. The original
forced-illegal pair still rejects with code 125 before postPlace (52.557
seconds). Three fresh native positive placements pass in 51.521, 51.819 and
53.762 seconds, with all 1,024 original LUT truth comparisons. The fresh
full-size native pack passes in 250.998 seconds and checks all 515 actual DSPs,
including every one of the 4,120 added tile-only declarations.

Fresh literal clock admission passes in 3.094 seconds. Actual four-DSP/
six-BRAM native P&R/FASM completes in 812.177 seconds with normal refinement,
fatal warnings, the same exact part, 50 MHz and seed. The 286-cell circuit
retains four DSPs and six BRAMs. The four DSP comparisons require 39 dedicated
ties each and respectively 25, 25, 25 and 27 configuration flags, including
the added logical-GND/physical-inverter-disable features. All six unchanged
BRAM feature comparisons pass. The native output has 7,682 unique features;
the exact source-defined repeated STEPDOWN handling is retained. Native logs
still report no Fmax/interior timing paths: this is encoder/legality control,
not proof of the full board's 50 MHz physical timing.

Its full packed census
does not establish complete changed-wire equivalence. No old full placement
transfer, full route, complete numerical suite, startup, timing, electrical,
DRC or bitstream acceptance is inferred. The two older live jobs keep their
unchanged inputs. No new standalone `SHA256SUMS` manifest is produced.

The completed native qualification was launched with:

```sh
python3 tools/openxc7/qualify_dsp_constant_candidate.py \
  --build build/openxc7/dsp-constant-engine-1791414105309267504/report.json
```

### Corrected full packed circuit identity: actual complete comparison passed

The [new read-only auditor](../tools/openxc7/audit_corrected_full_pack_identity.py)
compares the complete original and corrected packed circuits, not just their
resource totals. Its first [actual attempt](../build/openxc7/corrected-full-pack-identity-1791415396100917123/report.json)
fails before circuit comparison because the new adapter expected two newlines
at the cells/netnames boundary. The pinned `jsonwrite.cc` emits one. That FAIL,
executed source and matching original control-source snapshot are preserved.
The corrected reader requires the exact source-defined delimiter; a new
control explicitly rejects the earlier wrong format. No old failure or log
is relabeled as a PASS.

The [fresh complete attempt](../build/openxc7/corrected-full-pack-identity-1791415739115873319/report.json)
passes at **07:33:48 HKT on 2026-10-08**, with 3,340 source/input bindings.
Nine software controls pass in 3.267 seconds, including direct comparison of
the saved real native packed reader output against a full JSON parser. The
actual full circuit comparison takes 189.376 seconds. It checks **538,118
cells**: all **537,603 non-DSP cell records are byte-identical**. All 515 DSPs
retain their literal parameters, ordinary pin wiring, pin directions and
non-tie attributes. Only the eight source-defined VCC-plus-inversion control
pins per DSP become empty scalar connections with the corrected dedicated
tile declarations: **4,120 exact disconnections**. Every resulting logical
constant remains zero. No dummy/disconnected-net normalization is used.

The public ports/packing settings and complete named-wire table are
byte-identical. All 502,795 LUTX cells, 17,519 flip-flops, 515 DSPs, six BRAMs
and other native resources remain; the sixteen groups still contain 32 CMAC
DSPs each. The audit snapshots the qualification report's already completed
pack stage because its small P&R was live at audit launch. It does not claim
that snapshot was a terminal native qualification. Both jobs have now exited
zero independently.

This establishes full **packed logical preservation**, not physical DSP
configuration for all 515 placed sites. Full corrected-engine placement/
reload legality, full routing/FASM, complete mapped numerical acceptance,
startup independence, exact -2/DSP timing, electrical/DRC and frame/bitstream
assembly remain open before a reviewed test image. Board programming/testing
would additionally require an explicitly requested action and audited target;
it is not authorized by this preparation goal.
The older full placement and mode-2 mapped replay remain live with unchanged
inputs. Production RTL/arithmetic/fixtures are unchanged, and no bitstream,
programming action or new standalone `SHA256SUMS` file is produced.

```sh
python3 tools/openxc7/audit_corrected_full_pack_identity.py
```

### Corrected native checkpoint FAIL preserved; actual corrected frame chain passed

The [read-only completed-evidence admission helper](../tools/openxc7/verify_corrected_native_evidence.py)
revalidates the independently completed native qualification and packed logical
identity reports. It checks content bindings, the exact two-object native
engine change, original legality probes, full DSP census and actual small
native FASM comparisons. It does not edit either completed report or admit an
old full placement transfer.

The [fresh corrected checkpoint runner](../tools/openxc7/probe_corrected_dsp_checkpoint.py)
was launched at **07:52:51 HKT on 2026-10-08** under
`rknpu-corrected-dsp-checkpoint-control-20261008.service`, invocation
`4858dd632e8e43bda02e9702e258db7f`. Its
[own report](../build/openxc7/corrected-dsp-checkpoint-control-1791417172851071744/report.json)
now records **FAIL/reload at 08:08:10 HKT**. Five admission controls and four
checkpoint controls pass, as do `make generated-check`, version verification
and an `objdump` check of the actual corrected executable's native
router-to-connectivity-check call. Actual fresh four-DSP/six-BRAM placement
completes in **763.376 seconds**, with normal static/refinement placement,
fatal warnings, the exact part, 50 MHz and seed 3588. Actual native reload
also exits zero in **3.575 seconds**. The subsequent strict comparison fails
on `Changed pin direction`; duplicate-DSP-BEL rejection and routing never
execute in this failed run. The report, executed source, original controls
and logs remain unchanged. The matching control-source backup is retained;
no verification log is copied forward as evidence for a new run.

The actual exports differ only by **1,108 missing empty input declarations**:
540 DSP, 372 BRAM and 196 LUT inputs. Every missing connection is `[]`; no
connected pin is omitted, no present direction changes, and every parameter
and cell attribute is unchanged. The pinned
`frontend/frontend_base.h::import_leaf_cell` collects direction metadata but
creates `ci->ports` only inside its loop over existing connection-vector
bits. The JSON frontend reports vector length zero for `[]`, and the writer
exports only actual `c->ports`. This explains the missing declarations; it is
not evidence of lost connected wiring. The original exact comparison gate
and its failure expectations are not weakened.

The [separate continuation](../tools/openxc7/resume_corrected_dsp_checkpoint.py)
has seven passing controls in **1.438 seconds**, including an actual-export
positive and a test that the original gate still rejects without the new
view. It permits only missing declared empty **inputs** of these exact native
DSP/BRAM/LUT types to be represented in an in-memory comparison view. Missing
connected inputs, explicit direction changes, extra pins and even missing
empty outputs remain failures. No endpoint is added/removed/rewritten in an
execution file. Native routing executes the original source-bound placed
checkpoint, never this comparison view; the existing logical-LUT permutation
comparison remains separate and mandatory.

Its [fresh report](../build/openxc7/corrected-dsp-checkpoint-resume-1791418453459203706/report.json)
now **passes at 08:19:59 HKT**. The service
`rknpu-corrected-dsp-checkpoint-resume-20261008.service` started at **08:14:12
HKT**, invocation `2feadfed4d554df3978938ae1fda209c`, and is now inactive/success
with exit zero. It revalidates completed corrected qualification and packed
identity, the failed parent's content bindings and exact successful native
placement command before reuse. It binds **3,386 source/input files**. Seven
fresh controls pass in **3.742 seconds** and `make generated-check` in **1.772
seconds**. Version verification and the actual linked native connectivity
check both pass.

Fresh native reload completes in **2.859 seconds**, preserving all **286 BELs**
and exact DSP/BRAM attributes. The comparison view represents precisely the
1,108 empty input declarations; the unchanged strict whole-circuit comparison
then checks 2,740 endpoint bits and 897 bijective wires. The fresh duplicate
DSP BEL correctly rejects with **SIGABRT / -6 in 2.642 seconds**, at the exact
native assertion, with no output artifact. Fresh routing/FASM completes in
**153.602 seconds**, including native routed-connectivity checking. All 286
physical BEL assignments and non-permutation resource attributes survive.
The mandatory original-logical-pin comparison checks all 286 cells, 2,642
endpoint bits and 897 wires. Only comparison metadata for 540 DSP and 372
BRAM empty inputs is represented after routing; logical LUT input permutation
checks remain unchanged. No comparison view is ever an execution input.

All four corrected DSP comparisons pass with 39 dedicated ties each and
25/25/25/27 configuration flags. Each of the six BRAM comparisons checks all
144 memory vectors and exact width/mode/output features. Unknown INIT values
still total 90,112 bits coerced to zero; startup independence remains open.
The new native FASM has **7,655 unique features** plus the same five allowed
idempotent STEPDOWN repetitions. Its routing differs from the earlier native
qualification's FASM, so neither the feature-count difference nor the earlier
frame conversion is claimed as a conversion result for this new artifact.
Native logs still report no Fmax/interior timing paths. Final source bindings
and production fingerprints are unchanged. Reused placement is explicitly
not a newly executed placement, and the failed parent is never relabeled.
This uses the literal native encoder fixture and does not launch full-board
placement or routing.

The [corrected frame-chain runner](../tools/openxc7/probe_corrected_frame_database.py)
was launched at **07:58:41 HKT** under
`rknpu-corrected-frame-database-control-20261008.service`, invocation
`645df328d2b4496fb68b54652c63589e`. Its
[own report](../build/openxc7/corrected-frame-database-control-1791417523073936205/report.json)
now **passes at 08:06:16 HKT**, with all six actual commands returning zero and
the service inactive/success. It binds 3,807 source/input files. Its five fresh
software controls pass in 3.171 seconds, `make generated-check` in 1.449
seconds, and the actual parser runtime is Python 3.13.13. The runtime's pure
Python FASM-parser fallback warning is retained in its fresh log.

The unchanged strict converter/cache/grammar adapter processes the already
completed corrected native qualification's raw `control.fasm` in **129.961
seconds**: **7,687 native input statements plus 97 source-defined
default/injected statements**, with no missing features or clock-activity
requests. All **64 added DSP tie/inverter features** are present exactly once
as native input requests, not supplied by injected defaults. Exact-part frame
geometry validation passes in **78.947 seconds**: all **45,892 tilegrid frames**
are supplied, with legal unique addresses, 101 words each and 7,989 nonzero
words. The exact part defines 46,336 legal frames; the remaining **444 outside
the tilegrid** are reported for later assembler zero-fill. No assembly is run.

Actual secondary frame readback passes in **27.191 seconds**. All **64 distinct
physical DB bits for the 64 added features**, across two frame addresses,
match their required values. These particular features all have set-bit
requirements; software controls additionally reject wrong clear-bit values.
The corruption negative flips an actual generated bit only in an in-memory
comparison view and correctly rejects it. Expected feature targets are never
converter inputs. Final source/input revalidation and unchanged production
source fingerprints pass. This is database consistency, not independent
silicon or electrical/timing/DRC evidence. No old conversion result is reused
as corrected-encoder evidence.

These jobs preserve the accepted engine and previous reports. At the 08:20 HKT
observation the old full-size placement and mode-2 mapped numerical replay
remain live with unchanged
inputs. No new standalone `SHA256SUMS` manifest, bitstream or programming action
is produced. Fresh results will be recorded in their own reports, not copied
from older verification logs.

```sh
python3 tools/openxc7/probe_corrected_dsp_checkpoint.py
python3 tools/openxc7/probe_corrected_frame_database.py
python3 tools/openxc7/resume_corrected_dsp_checkpoint.py
```

### Corrected full-feature comparator preparation, not full-route acceptance

The separate [comparator](../tools/openxc7/check_full_corrected_native_features.py)
retains the existing exact native readers and full-target census, while using
the separately qualified 39-tie DSP policy. The old 31-tie comparator and its
error expectations are unchanged. Actual full comparison requires all **515
DSPs and six BRAMs**, including sixteen kernels with 32 DSPs each, and all
**4,120 additional DSP tile-only pins**. A caller must independently admit the
corrected native route and prove unchanged full logical wiring and BELs; this
helper does not authorize transfer of the pending old-engine placement.

The first [control attempt](../build/openxc7/corrected-full-feature-controls-1791419689803046275/report.json)
remains **FAIL**, with its executed test source and real log preserved. Two new
harness assumptions were wrong: the native parser returns a dictionary of
repeated STEPDOWN line numbers, not an integer count; RAMB36 INIT vectors are
emitted under two `RAMB18_Y` halves, not `RAMB36_Y`. Only those new harness
assumptions were corrected. Neither a prior test expectation nor native/RTL
behavior changed.

The [fresh attempt](../build/openxc7/corrected-full-feature-controls-1791419723411135879/report.json)
passes at **08:35:35 HKT on 2026-10-08**, binding 69 source/input files with
Python **3.14.5**. All twelve software methods pass in **7.057 seconds**
(8.628-second subprocess), and `make generated-check` passes in **1.294
seconds**. Read-only saved native readers compare four DSP/six BRAM records,
all 7,655 unique features and five exact repeated STEPDOWN declarations.
Negatives reject a missing/wrong logical DSP tie, missing inverter-disable
bit, changed/duplicate BEL, missing primitive, an unsupported DSP profile and
a one-bit corruption of an actual 256-bit BRAM INIT vector. The small artifact
is explicitly rejected by the full census, and the old actual 31-tie gate still
rejects this corrected encoding. The full original source inventory separately
tests the sixteen-by-32 plus three-shell-DSP census; no full routed artifact is
substituted by that metadata control.

The report states `fresh_native_execution=false`, `full_board_features_compared=false`
and all transfer/full-route/numerical/physical acceptance fields false. These
are fresh software tests of saved native artifacts, **not fresh native P&R**.
Production sources remain unchanged at `09f1c3f65ba9…`; the latest full
production regression remains its recorded Verilator compile-timeout FAIL.
The full suite was not restarted against live mapped fixtures. No standalone
`SHA256SUMS` manifest is created.

```sh
python3 tools/openxc7/run_corrected_full_feature_controls.py
```

### Read-only observation of the pending full legalizer

At approximately **08:31–08:32 HKT on 2026-10-08**, PID 1291418 remains the
same full-size, seed-3588, 50 MHz precision-engine placement. GNU gdb **17.2-4.fc44**
is used with auto-loading, debuginfod, target-memory writes, register writes
and inferior function calls disabled. Each attach is bounded to 25 seconds
and detached afterward; the native process is independently observed running
again. No breakpoint, target state modification or restart is performed.

The [main stack observation](../build/openxc7/full-place-main-stack-20261008T002600Z.log)
finds `xc7_logic_tile_valid` called from `legalise_placement_strict` at the
compiled precision source's line 1525. A [partial locals observation](../build/openxc7/full-place-legaliser-locals-20261008T003500Z.log)
reads **170,261 queue entries**; several counters are optimized out, and a
trailing debugger-Python `end` token produces a diagnostic NameError after
the reads. That diagnostic failure is not a native placement failure. The
following [completed observation](../build/openxc7/full-place-queue-sample-20261008T003800Z.log)
reads **170,257 entries** and a different active `SLICE_LUTX` cell. The latter
two filenames are probe labels, not accurate sample timestamps; the actual
observation interval is given above.

These samples establish active legalization and some queue progress, not a
rate forecast, completed fit or impossibility finding. The inner search can
rip up/requeue other cells, so the queue is not a monotonically decreasing
completion counter. At **08:35:53 HKT**, full placement and mapped mode 2 remain
live; only modes 0 and 1 of the nine-mode suite have completed. No full native
route, corrected placement transfer, bitstream or physical board test is
accepted from these observations.

### Exact DSP placement-copy correction: structural and small native controls pass

The [new correction helper](../tools/openxc7/correct_placed_dsp_constants.py)
accepts only an **unrouted, fully bound** native placement with the exact old
31-tie DSP representation. It checks the named GND/VCC nets against their
single pseudo-drivers. Each of the eight additional pins must be an input
connected to that VCC net, with the qualified literal parameters and inversion
policy. It disconnects only those eight pins and records the source-defined
39-tie policy in a **new placement copy**, preserving every BEL, parameter,
ordinary connection, non-tie attribute, other cell and complete named-net
table. This is offline encoding correction, not runtime CPU arithmetic/layout
repair or expected-feature injection. The original command streams and RTL
remain unchanged.

Twelve [structural software methods](../tests/cmac/test_corrected_placement_transfer_control.py)
pass in **1.605 seconds** in the initial direct run. Their old-representation
fixture is explicitly constructed from the saved corrected native placement;
it is **not called an old-engine native placement**. Controls reject a routed
or already-corrected input, missing DSP inventory or constant driver, a wrong
tile wire, changed parameters, changed BEL/ordinary connection/non-tie
attribute/non-DSP cell/named nets. `make generated-check` also passes.

The [separate native runner](../tools/openxc7/probe_corrected_placement_transfer.py)
will use a **fresh old-engine placement of the literal four-DSP/six-BRAM
fixture**, then the exact correction, fresh corrected reload, duplicate-BEL
negative, corrected routing and saved full-feature readers. Its new hardware
execution input is the corrected placement copy; comparison-only empty-input
and original-logical-LUT views are never executed. Every cell's physical BEL
and original logical incidence must survive routing, and all four corrected
DSP/six-BRAM feature configurations must match.

[The actual attempt](../build/openxc7/corrected-placement-transfer-control-1791420228939723426/report.json)
is supervised by `rknpu-corrected-placement-transfer-control-20261008.service`,
invocation `2210b031101d42e3909d2815cd8050a8`, launched at **08:43:45 HKT on
2026-10-08**. Initial limits are MemoryHigh/Max 4/6 GiB, swap 2 GiB, CPU quota 20%,
nice 10, 75-minute unit runtime, OOM stop and no core dumps. At **08:45:40 HKT**
the same supervisor PID 1325676 is confirmed live in **admission**, consuming
CPU while revalidating its completed native parents; its command list is still
empty. There is **no new native placement, reload or route result yet**.

The runner binds its literal native execution input, but omits the separate
saved-placement fixture read by its structural software tests from its own
source table. An independent [read-only fixture observation](../build/openxc7/transfer-software-fixture-observation-20261008T004909Z/report.json)
at **08:49:09 HKT**, while the live attempt still has no commands, records that
fixture, its original report and the current test-source hashes. The fixture
matches its original report's artifact hash. This is explicitly a manual
record of actual read-only output, not native acceptance. After-run
revalidation remains required; the running source is not edited to repair
the omission, and its original source table will not be relabeled as complete.

Source review further distinguishes the checks: the pinned command runner
calls `ctx->check()` after import, but a plain no-place/no-route reload does
not run `XilinxImpl::preRoute` or initialize its cell tags. The compiled
`heap-beta-engine-1791307049291727187/.../xilinx.cc:1005` initializes tags and
BEL status before real routing. Thus reload identity is not an independent
architecture-validity rescan. `fixup_routing`'s “post-routing legalisation”
message describes LUT pin-permutation fixup, not a new all-BEL placement
validity scan. The native test records these limits explicitly. Source-defined
DSP/LUT/BRAM behavior, complete physical identity and real routing still need
their own checks; neither these software controls nor an eventual small
transfer result admit the pending full placement or physical signoff.

```sh
python3 tools/openxc7/probe_corrected_placement_transfer.py
```

### Fixed LUT sharing versus post-placement A6 and post-route export metadata

The [read-only pair auditor](../tools/openxc7/audit_postplace_lut_pairs.py)
examines actual saved outputs against the pinned compiled sources. In
`xilinx_place.cc:680`, `fixup_placement` merges each logic pair onto five shared
physical pins, moves the lower output to O5, and ties the upper LUT's A6 to
VCC **without a logical `X_ORIG_PORT_A6` mapping**. The physical shared-input
budget is A1–A5; A6 selects the upper half of the paired LUT INIT. The earlier
`assign_cell_tags` input count includes connected A6 when a checkpoint is
reloaded. A naive reapplication of the pre-placement shared-input guard can
therefore reject this source-defined legal fixed representation. This is a
source inference, **not an executed new native validity result**.

The actual saved 49-cell forced-positive placement has nine logic pairs.
`captured_pair_lut0`/`captured_pair_lut1` uses **five shared physical wires**,
plus the distinct VCC A6 mode wire: the naive all-input union is six. Literal
logical annotations and per-pin incidence remain checked. This prevents
implementing a new validator with the wrong stage contract; the existing
pre-placement native checks are not changed or weakened.

The first [audit attempt](../build/openxc7/postplace-LUT-pair-audit-1791421025029697685/report.json)
remains **FAIL**, preserving its executed auditor, test source and real log.
Nine methods pass, but its new raw routed-export positive fails at “5LUT has
a connected A6.” Source review of `fixup_routing` at lines 835–918 shows that
every selected permutation connection is mirrored onto both LUT cell records,
even when one record has no logical mapping for it. The actual saved routed
control contains **98 paired 5LUT A6 records**, all unannotated mirrors of the
partner's VCC mode tie. They are post-route metadata, not generic checkpoint
inputs. No old failure or routed report is relabeled.

A **separate `audit_export` comparison adapter** now supports only this exact
source-defined post-route case. It requires route-stage metadata, the existing
paired 6LUT, both A6 input directions, no logical A6 mapping and both connections
to the actual single VCC driver. It omits only the 5LUT mirror in a temporary
comparison view, then calls the **unchanged strict `audit_pairs` core**.
Non-VCC/mismatched ties, logical A6 mappings, missing partners and unsupported
memory/SRL pair modes remain failures. It checks each shared physical pin's
net identity, not only the count of distinct inputs. No native input, tag table,
connection, parameter, BEL, FASM or expected vector is edited or executed from
this comparison view.

The [fresh audit](../build/openxc7/postplace-LUT-pair-audit-1791421199482239714/report.json)
completes at **09:00:05 HKT on 2026-10-08**, binding **78** files. Thirteen
software methods pass in **1.142 seconds** (3.044-second subprocess), and
generated checks pass in **1.438 seconds**. It checks all nine pairs in the
49-cell placement and all **98 pairs** in each saved 286-cell corrected
placement/routed control. The old raw auditor still rejects that same routed
export; the new tests additionally reject wrong or logically mapped mirrors.
Original failed-source snapshots and artifact hashes are revalidated. Production
sources remain `09f1c3f65ba9…`.

This is a saved-output structural/metadata audit, **not native all-BEL
requalification, fresh routing, full-array acceptance, timing/electrical/DRC
signoff or a bitstream**. A new native checkpoint-validity scanner must respect
the source-defined post-placement representation while retaining all real
physical/resource constraints. It has not been built or admitted yet.

At **09:01:58 HKT**, the managed transfer control is live in fresh old-engine
placement (PID 1327886), after five completed admission/control/version steps;
the twelve managed controls took 13.087 seconds under the 20% quota. The full
placement (PID 1291418) and mapped mode-2 replay (PID 1308050) are still live.
The full service's currently verified CPU quota is **unlimited**, not 25%; its
12/14-GiB memory high/max, 4-GiB swap cap, nice 5 and seven-hour unit runtime
remain set. No service setting or live input is changed here. The latest full
production test remains its archived compile-timeout FAIL, and no standalone
`SHA256SUMS` file is written.

```sh
python3 tools/openxc7/audit_postplace_lut_pairs.py
```

### Full physical-input BRAM enable and local write-control audit

The [read-only control auditor](../tools/openxc7/audit_prefix_bram_control_wiring.py)
extends the completed address/data alias audit without editing its sources,
the execution circuit or any earlier expectation. It revalidates the original
physical input, selected primitives, hierarchy aliases, consumer classification
and memory/controller RTL. All **503,128 physical-input primitive records**
must match the inventory, including **six BRAMs**. The four ROMs remain
read-only with their original constant enables. Both working RAMs must retain
their source-defined host/core fire wires, repeated active write lanes,
zero unused write lanes and zero reset/register-enable pins.

The actual six selected control drivers are four LUT2s, a LUT5 and a LUT6.
Their literal binary INIT/pin functions are evaluated over **all 1,024
assignments of ten explicit cut wires**, making **8,192 assertions**. The
ready signals equal reset-and-no-response; fire requires ready (and a valid
request on the core side). Each effective physical write, **EN && WE**, equals
that port's declared fire-and-write condition on both working RAMs. Checking
the effective write avoids imposing an incorrect ungated-WE expectation: the
actual host WE is ready-and-write, while its enable also supplies the host
selection. Opaque address/selection cut wires are treated independently; their
upstream logic and sequential reachability are not accepted by this check.

[The fresh actual audit](../build/openxc7/prefix-bram-control-wiring-1791422081130315089/report.json)
completes at **09:17:48 HKT on 2026-10-08**, with **73 source bindings** and
59 own artifacts. Python 3.14.5 executes eight corruption-control methods
in an 11.642-second subprocess; generated checks pass in 1.745 seconds. The
actual alias/census/local-truth audit takes 152.029 seconds. Controls reject
wrong truth tables, ready/fire policies, enable/reset/register-enable pins,
mixed or unused write lanes, writable ROMs, missing/extra primitive census,
duplicate drivers, unknown/unmodeled LUT fields, cycles and corrupt aliases.
No new HDL or native P&R is run. Production source remains `09f1c3f65ba9…`.

This is **local binary control evidence**, not an address-decoder proof,
temporal port-ownership or write-before-read proof, observable startup/reset
independence, all-nine-mode acceptance, full-array placement/routing,
timing/electrical/DRC signoff or bitstream authorization. No comparison result
is inserted into an execution input, and no `SHA256SUMS` manifest is written.

```sh
python3 tools/openxc7/audit_prefix_bram_control_wiring.py
```

### Completed small native placement transfer and actual checkpoint-checker provenance

The [small transfer attempt](../build/openxc7/corrected-placement-transfer-control-1791420228939723426/report.json)
completes at **09:26:34 HKT on 2026-10-08**. Fresh old-engine placement takes
1,739.666 seconds, corrected reload 2.566 seconds, the expected duplicate-DSP
BEL rejection 2.542 seconds (SIGABRT), and actual corrected routing/FASM
112.951 seconds. The unchanged 1,800-second placement limit is respected;
the earlier recorded CPU-quota change affects only this small control.
The corrected input changes exactly **32 tile-pin connections on four DSPs**,
preserving all **286 BELs**, parameters, ordinary wires, other attributes,
other cells and named nets. Routing preserves the original 286-cell logical
graph with **897 bijective wires and 2,642 endpoint bits**, and compares all
four corrected DSP/six-BRAM configurations against **7,655 native FASM
features**. The source-defined empty-input/LUT comparison views are not
executed as hardware inputs.

All **3,444 own source bindings** and **19 artifacts** are independently
rechecked after completion. The separately observed software fixture, original
report and test source also still match their pre-test hashes; the
[after-run observation](../build/openxc7/transfer-software-fixture-after-run-observation-20261008T012953Z.json)
records those actual read-only checks. Neither the old observation nor the
runner is edited to relabel its own source-table omission. This small native
result **does not provide an all-BEL architecture-validity rescan, full-size
transfer, physical fit or timing/electrical/DRC signoff**.

The [isolated native-checker builder](../tools/openxc7/build_imported_placement_checker.py)
and [fixed-stage check template](../tools/openxc7/native/check_imported_placement.inc)
add an opt-in `rknpu-check-imported-placement=fixed-lut-v1` check to `preRoute`,
after tags/BEL status are initialized and before clock/general routing. A
verification-only tag copy excludes **only** a fully evidenced paired upper
LUT's synthetic A6 mode pin. Logical input/output annotations, actual VCC
driver, same shared physical pin incidence and output roles remain strict.
Every bound cell then receives the existing native `isBelLocationValid`
check. RAII restores every original tag and invalidates validity caches on
success or exception. No port, parameter, attribute, net, BEL, old assertion,
placer or routing/FASM implementation is changed by the check. Routed exports,
unsupported pair profiles, wrong mode ties and missing mappings remain failures.
This is additional verification, not runtime arithmetic/layout repair.

Two admission failures are preserved unchanged. The
[first build attempt](../build/openxc7/imported-placement-checker-engine-1791422992757135704/report.json)
mistakes the historical compiler step's **log hash** for its object hash. The
donor's `ypcb_heap_engine.py` shows that its source/object hashes are separate
`inputs` entries. The
[second attempt](../build/openxc7/imported-placement-checker-engine-1791423256968854860/report.json)
then correctly refuses to replace a HeAP probe object which is **not in the
actual qualified link command**. Neither attempt executes compilation or native
checks, and neither failure is changed to PASS.

The authoritative corrected link actually uses the CMake object
`.../nextpnr-cli-build/himbaechel/CMakeFiles/nextpnr-himbaechel.dir/uarch/xilinx/xilinx.cc.o`
(SHA `f731a5a8b344…`). Its dependency file and DWARF name/compilation directory
identify the global `.../nextpnr-himbaechel/himbaechel/uarch/xilinx/xilinx.cc`
(SHA `a8a4f1f0e74…`), compiled with GCC **16.2.1 20260819**. The HeAP probe object
is different (`7745cf68b6e0…`) and is not substituted. Source comparison shows
that the HeAP/global C++ files differ **only in the HeAP beta configuration**;
their tag initialization and `preRoute` bodies are byte-identical. Thus earlier
references to the HeAP path document equivalent stage logic, not the actual
linked C++ object. The global source's `preRoute` starts at line 1000 rather
than the HeAP clone's line 1005. This corrects source-path attribution; old
saved audit reports are not relabeled or claimed to be fresh native checks.

The [CMake-targeted retry](../build/openxc7/imported-placement-checker-engine-1791423720339568801/report.json)
has passed nine build-control methods, generated checks and a **byte-identical
corrected-parent relink** in 8.769 seconds. As observed at **09:45:07 HKT**, it
is compiling the isolated single replacement object. A first direct control
failure comparing a changed dependency-output path as an unchanged flag is
also preserved with [its exact executed source and log](../build/openxc7/imported-checker-direct-controls-fail-20261008/software_controls.log).
Only that new test's prefix indexing is corrected; all old gates/expectations
remain untouched.

The [new native qualification runner](../tools/openxc7/probe_imported_placement_checker.py)
is prepared, with **eight passing software controls**. It will rerun the
unchanged illegal/three-positive pre-placement fixtures and test the actual
49-cell fixed placement plus the completed 286-cell corrected transfer.
Wrong A6 mode, logical A6, shared-pin mismatch, missing annotation, connected
5LUT A6 and a latch in a physical 5FF must be rejected **before routing**, with
no published invalid output. Positive routes must retain all physical BELs,
original logical incidence and the actual four-DSP/six-BRAM feature contract.
No native qualification or full transfer is accepted yet; building and mocked
log/admission controls cannot establish that result.

Mapped-board **mode 2 now passes** its expected readback-fault case: 4,096
initializations, one checked word, 196 command reads, 6,528 operand reads,
64 acknowledged writes and 32,630 cycles. The original simulator process exits
zero after 12,505.649 seconds. **Mode 3 is live** under the unchanged supervisor;
three of nine modes are complete, not all-nine-mode or physical FPGA acceptance.
Full-size strict legalization remains live. No bitstream is emitted, no hardware
is programmed, and no standalone `SHA256SUMS` file is created.

### Strict compile warning preserved; source/API-matched loop-index correction

The CMake-targeted checker attempt above subsequently remains **FAIL** at its
strict diagnostic gate. GCC completes compilation with zero exit status after
195.879 seconds but reports an existing `-Wsign-compare` in
`apply_prerouted`: its index is `int`, while `getNetinfoSinkWireCount` returns
`size_t`. The executed source, actual warning log and successful byte-identical
parent relink are retained in that failed attempt. No executable is linked or
native acceptance inferred from it.

A read-only syntax-only compile of the **original global source**, with the
same CMake flags but dependency/output generation removed, independently
reproduces the same warning at original line 1152 and exits zero. This is
warning attribution, not a clean compile or native qualification.
`common/kernel/context.h:50–51` and the implementations in `context.cc:74–84`
show that **both the count and physical index are `size_t`**. A separate,
explicit one-line correction changes only the loop index from `int` to
`size_t` in the isolated source copy, leaving bounds and body unchanged.
For the original nonnegative, nonoverflowing integer range the index sequence
is unchanged; the new type also matches the API's full representable range.
This is a source correction, **not a warning suppression or altered warning
expectation**. Existing compiler flags and emitted-warning refusal are retained.

The reversible source gate now permits only the option/check hook and this
API-matched loop-index correction; reversing those exact edits restores the
original source byte-for-byte, including every old assertion. Ten build-control
methods pass, including explicit API-signature, loop-body and changed-source
negative checks. The eight probe-control methods also still pass. No donor,
live input, default engine pointer, old report, old gate or RTL is modified.

The [fresh typed-index build](../build/openxc7/imported-placement-checker-engine-1791424380429306004/report.json)
is supervised by `rknpu-imported-placement-checker-build-size-index-20261008.service`,
invocation `77a02902e2d84e328f148ebc853ec57b`, launched at **09:53:00 HKT**.
Its limits remain one CPU core, memory high/max 4/6 GiB, swap 2 GiB, nice 10,
40-minute unit runtime, OOM stop and no core dumps. At **09:56:04 HKT**, ten
managed controls and generated checks pass, the corrected parent relinks
byte-identically in 8.729 seconds, and the isolated object is compiling.
Native qualification remains pending. Full-size placement and mapped mode 3
remain live; only three of nine mapped modes have completed.

At **09:15:38 HKT**, only the live small transfer control's CPU quota is raised
from 20% to **100% (one core)**. Its unchanged runner has a 1,800-second
native-placement timeout: a 20% quota provides at most 360 CPU seconds within
that interval, risking a throttling-induced failure unrelated to placement.
The [separate live resource observation](../build/openxc7/transfer-control-cpu-quota-observation-20261008T011538Z.json)
records the actual command, zero exit status and verified properties. The
75-minute unit runtime, 4/6-GiB memory high/max, 2-GiB swap cap, input,
executables, timeout and source remain unchanged; selected live runner/helper/
control hashes are rechecked. This is not a complete source-table revalidation
or native acceptance. No other job's properties are changed.

At **09:18:04 HKT**, the small control is still in old-engine placement
(PID 1327886, iteration 187). Full-size strict legalization (PID 1291418) and
mapped mode-2 replay (PID 1308050) remain live. No full routed checkpoint,
bitstream or hardware result is claimed. The latest complete production
regression remains its archived compile-timeout FAIL; it is not rerun or
relabeled for these separate checker/documentation changes.

### Terminal full-placement timeout; clean checker build and fresh qualification

The [precision-fixed full-size placement retry](../build/openxc7/full-prefix-native-place-1791403059242726617/report.json)
is now terminal **FAIL**, finishing at **10:01:31 HKT on 2026-10-08**. Its
native command reaches the unchanged **21,600-second** limit and is killed
(return code **-9**, recorded duration **21,603.005 seconds**). The last native
log remains strict legalization of **433,249 cells**, after static iteration
629 with 10% COMB overlap. No completed `placed.json`, full native route or
fit result is accepted. Earlier read-only queue samples show some progress,
not a measured convergence rate. This is a host timeout, **not a proof of
physical impossibility**, and it is not relabeled or immediately restarted
with the same conditions. The exact C32/K16, 512-product target and every
legality/physical gate remain unchanged.

The [typed-index native checker build](../build/openxc7/imported-placement-checker-engine-1791424380429306004/report.json)
completes cleanly at **09:59:41 HKT**. All seven commands pass the unchanged
diagnostic gate: ten software methods, generated checks, GCC version, the
byte-identical corrected-parent relink (**8.729 seconds**), isolated compilation
(**197.271 seconds**), link (**8.853 seconds**) and native version. The executable
hash is `1982160301499fa916b023db7efbe2e24625fc74a7ed2bead1c7120fd9d38011`;
the native version remains `c68c135`. Only the actual linked CMake `xilinx.cc.o`
changes relative to the corrected encoder. Build completion alone does not
qualify the checker, transfer a full placement or authorize a bitstream.

The [fresh native qualification](../build/openxc7/imported-placement-checker-qualification-1791425095627576316/report.json)
is launched under `rknpu-imported-placement-checker-qualification-20261008.service`,
invocation `51666d6280b2445aaf7fdedffcf68cb2`. It first revalidates the build,
completed small transfer, separately observed software fixture and actual
bound dependencies. Its independent limits are one CPU core, memory high/max
**4/6 GiB**, swap **2 GiB**, nice **10**, outer runtime **4,500 seconds**, OOM
stop and no core dumps. Native controls retain their own **600/1,800-second**
limits. Six corrupted imported checkpoints must fail before routing; fresh
49-cell and 286-cell positive routes must preserve the original circuit/BELs.
This run is live, not yet qualified. The mapped-board continuation remains
live on mode 3 with three of nine modes complete. Production RTL, existing
reports, other projects and the live mapped input/executable remain untouched.
No standalone `SHA256SUMS` manifest, bitstream or programming action is made.

### Imported-positive failure preserved; separate local-carry-tag candidate

The [first checker qualification](../build/openxc7/imported-placement-checker-qualification-1791425095627576316/report.json)
is now terminal **FAIL**, not qualified. Eight software methods and generated
checks pass. Its unchanged pre-placement illegal fixture rejects with code
125 in **50.310 seconds**; all three original positive placements finish
normally in **47.352**, **47.696** and **51.062 seconds**, with the original
truth/placement checks. All six deliberate imported corruptions reject with
code 125 before routing, each in 2–3 seconds. However, the actual 49-cell
saved positive rejects in **2.625 seconds** at the new all-BEL scan, naming
the carry-associated `...$$S[3]` LUT at `X161Y204/SLICE_X0Y0.D6LUT`.
No successful imported route or checker qualification is accepted, and the
failed runner/template, logs and expectations stay unchanged.

Actual source and saved topology indicate a second lost tag dependency,
not demonstrated invalid placement. `assign_cell_tags` in the actual linked
global `xilinx.cc:1368–1373` sets `only_drives_carry` only when the LUT still
has cluster membership and its sole output user is a carry. The JSON writer's
cell block (`json/jsonwrite.cc:163–195`) exports parameters, attributes and
ports, not `cluster`; the frontend creates/imports leaf cells without restoring
those carry clusters. `pack_carry.cc:390–407` originally clusters DI LUTs at
the corresponding 5LUT positions. The unchanged legality code at
`xilinx_place.cc:425–448` uses that tag to avoid counting a local DI feed as a
fabric OUTMUX claimant. The actual saved 49-cell input has **eight** sole-user
O5-to-DI feeds in the exact same physical carry site/letter positions; the
286-cell DSP/BRAM control has **zero** such roles. This is source/topology
diagnosis, not a new native branch trace or physical-validity proof.

The [separate supplemental builder](../tools/openxc7/build_imported_carry_checker.py)
generates a new template by an exactly reversible addition to the frozen first
template. Only verification tags change: a paired lower LUT receives
`only_drives_carry=true` **only** when its output has one user, that user is
the carry bound in the same half/site, and its port/net is the exact local
`DI(z%4)`. Wrong local DI positions fail explicitly. An extra user prevents
restoration and retains ordinary OUTMUX checks. The existing RAII restores
all original tags/caches; no actual port, cluster, cell, net or BEL changes.
All old assertions and legality guards remain. Twelve build-control methods
pass, including the inherited ten controls and actual eight-role/wrong-DI/
extra-user comparisons.

The [new build attempt](../build/openxc7/imported-placement-checker-engine-1791426019403042439/report.json)
runs under `rknpu-imported-carry-checker-build-20261008.service`, invocation
`20342e904f994c55bf39425c67366165`, with the same one-core, 4/6-GiB memory,
2-GiB swap, nice-10, OOM/core-dump limits and 40-minute outer runtime. As
observed at **10:23:44 HKT**, managed controls/generated checks pass, the
corrected parent relinks byte-identically in **7.632 seconds**, and the
replacement object is compiling. It is not yet a completed or qualified build.

The [supplemental qualification runner](../tools/openxc7/probe_imported_carry_checker.py)
has ten passing software methods, retains every old placement/log/identity/
feature gate, adds wrong-local-DI and extra-carry-user native corruptions, and
requires explicit native role counts of **8/0** in the two positive profiles.
The inherited builder binds the generated supplemental template, not its
original generator-reference template. Qualification therefore independently
binds/rechecks that original and the first completed build's identical saved
template before native execution; it does not edit or relabel the builder's
source table. The actual generated input remains fully bound. No native
supplemental qualification is launched yet. No full-array placement, route,
timing/electrical/DRC signoff or bitstream follows from these software controls.

A fresh read-only toolchain check finds `/home/fedora/vivado/v.tar` is the
4,080,148,480-byte **Vivado Lab 2026.1.1** archive, not full Vivado. No `wget`,
`curl` or `aria2c` process is observed. A broader filename scan finds only
2026.1 installer signatures/digests, with permission errors in container
storage; it is not an exhaustive proof that no installer exists elsewhere.
No installer, license acceptance, other-project changes, bitstream, hardware
programming or standalone `SHA256SUMS` manifest is performed.

The supplemental build subsequently completes cleanly at **10:26:18 HKT**:
all seven commands pass the strict diagnostic gate, including compilation in
**176.469 seconds** and link in **7.316 seconds**. Its executable hash is
`2aadad656dc9bf9189a22c15795a0f61329ad1cc315fdfc4af09807b81a5e083`;
the report binds **3,373 inputs and 19 own artifacts**, including the generated
supplemental template and actual extension-builder source. Production source
remains `09f1c3f65ba9`. This is still build-only evidence.

The [fresh supplemental native qualification](../build/openxc7/imported-placement-checker-qualification-1791426415757842131/report.json)
is live under `rknpu-imported-carry-checker-qualification-20261008.service`,
invocation `27d3ed72677e4c989cbc8abd15daba79`, supervisor PID **1337235**.
The independently verified limits remain one CPU core, 4/6-GiB memory high/max,
2-GiB swap, nice 10, 75-minute outer runtime, OOM stop, control-group cleanup
and no core dumps. Its original 600/1,800-second native limits remain.
Admission revalidates the actual compiled template and independently bound
generator reference before running the unchanged placement controls, all
eight native corruptions and both fresh positive routes. It has not completed
or qualified the checker yet; full-array placement/physical gates remain.

The first failed qualification's **3,495 bindings and 25 artifacts** are also
independently rechecked unchanged after completion: all **1,024** original
pre-placement truth comparisons and six expected imported rejections remain
recorded, while the positive still has code **125** and no published routed
output. Neither its FAIL nor its source table is relabeled. Fresh
`make generated-check` passes; the whole production regression remains its
archived compile-timeout FAIL, not a new HDL or hardware PASS.

### 2026-10-08: small carry-checker qualification and bounded strict search

The supplemental qualification above is now terminal **FAIL**, not live.
All four unchanged native placement controls pass their original expectations
(three positives, 1,024 LUT-output comparisons); all **eight** imported
corruptions reject with code 125 before routing. The actual 49-cell import
then passes the native scan of nine logic pairs/eight local carry roles and
normal routing/export in **99.997 seconds**, but the subsequent logical export
comparison fails with `Unmodeled empty-input primitive`. The original
[failed report](../build/openxc7/imported-placement-checker-qualification-1791426415757842131/report.json)
and its executed sources/logs remain unchanged. Its 286-cell route was not run.

The actual generic frontend (`frontend/frontend_base.h:475–504`) creates ports
inside the vector-bit loop, so empty `[]` input **and output** declarations
disappear on import. The saved 49-cell CARRY4 export loses two empty input and
six empty output declarations, with original-port annotations unchanged.
[A separate comparison helper](../tools/openxc7/compare_imported_carry_export.py)
permits only those source-defined scalar CARRY4 port/direction/mapping entries,
only when the original vector is empty. Connected pins, changed mappings,
parameters/types, unknown pins and extra export ports remain failures; existing
ports are not repaired. The original unsupported-CARRY gate remains unchanged.
LUT permutations still use the original full logical proof, and no comparison
view is supplied to native execution. All **12** new controls pass.

An initial direct control invocation failed because its new harness read the
wrong result key (`cells_compared` instead of `logical_board.cells`). That
actual 12-method invocation, including its one error, is preserved under
`build/openxc7/imported-carry-export-direct-controls-fail-20261008/` with the
executed source. Only the new harness key changed; the required 49-cell result
and old failure expectations did not.

The [separate continuation](../tools/openxc7/resume_imported_carry_checker.py)
completes at **10:51:46 HKT** with status
`QUALIFIED_SMALL_NATIVE_IMPORTED_CHECKPOINT_SCAN_AND_ROUTES_WITH_EXACT_CARRY_EMPTY_PORT_VIEW_NOT_FULL_TRANSFER_OR_SIGNOFF`.
Its [actual report](../build/openxc7/imported-carry-checker-resume-1791427613948665478/report.json)
binds **3,537 sources and 10 own artifacts**. It rechecks every original native
invocation/input, all eight actual corruptions and their logs, and the unchanged
saved 49-cell route before comparing it. Fresh 286-cell scan/routing completes
in **114.376 seconds**, scanning **98** pairs/**zero** local carry roles.
Every BEL is unchanged; full logical comparison checks **286 cells, 2,642
endpoint bits and 897 bijective wires**. Literal four-DSP/six-BRAM feature
checks pass with **7,655 unique FASM features/five repeated STEPDOWN lines**.
Both 12-method export and four-method continuation controls and generated checks
pass inside the managed run. Unit
`rknpu-imported-carry-checker-resume-20261008.service`, invocation
`ef4a1677fdc5467395595dc412c05ba4`, finishes normally. This qualifies only these
small native inputs, not full-array transfer/fit or physical/numerical signoff.

The full-size timeout remains FAIL with no `placed.json`. The actual static
placer computes physical dimensions as `max(BEL coordinate + 1)` in `init_grid`,
and `FastBels` indexes entries at those physical coordinates. Its old strict
random search instead uses unclamped upper bounds `cx + rx`, `cy + ry`, then
discards out-of-grid samples. The [separate bounded-search source generator](../tools/openxc7/strict_search_candidate.py)
clamps only those two upper bounds to `bel_width - 1`, `bel_height - 1` and
adds progress counters/30-second heartbeats, clock-checked every 4,096 samples.
It does not remove native plain/cluster validity, region/strength checks,
queue/rip-up limits, assertions or normal refinement. The RNG calls remain,
but their coordinate ranges change: **the search trajectory changes**, and no
full-size speed/fit improvement is claimed. Eight host source/sampler controls
pass; host controls alone do not qualify the native algorithm.

The [isolated build](../build/openxc7/strict-search-engine-1791427828339461924/report.json)
completes at **10:55:35 HKT**, binding **3,382 sources/18 artifacts**. The
corrected-DSP parent relinks byte-identically in **7.678 seconds**; only its
static-placer object changes, compiling in **108.030 seconds** and linking in
**7.791 seconds**, with strict diagnostic checks and unchanged compile flags.
Executable hash: `81481d44f65da7685c96fcf0d5b7c1cfcabe3ddf271c37997ec6191e4ae1bb7d`;
native version remains `c68c135`. Unit
`rknpu-strict-search-build-20261008.service`, invocation
`b5fb803cc33c492cae9905d2ac3b61d6`, finishes normally. No donor/default pointer
or RTL source changes. This is build-only evidence.

[Fresh native qualification](../tools/openxc7/qualify_strict_search_candidate.py)
is now running under `rknpu-strict-search-qualification-20261008.service`,
invocation `cd9da64d828e4d58a1d3a2c0d3c84bcd`, with one CPU core, 4/6-GiB
memory high/max, 2-GiB swap, nice 10, OOM stop/control-group cleanup, no core
dumps and two-hour outer runtime. It executes all four original placement
inputs and the original four-DSP/six-BRAM P&R input with normal refinement,
fatal warnings, unchanged 50 MHz clock and seeds, plus native search-completion
counters and literal feature checks. Six admission/log controls pass. There
is no completed qualification or new full-size placement yet.

The [full-size runner](../tools/openxc7/place_strict_search_board.py) is prepared
with three passing admission controls but **not launched**. It requires that
new native qualification, revalidates the old terminal timeout and all bound
inputs, repacks the exact original C32/K16 input with the corrected DSP engine,
and retains all 512 CMAC/three shell DSPs and six BRAMs. A new attempt allows
**12 hours of host computation**, versus the failed attempt's six hours;
this is not FPGA clock relaxation. The part remains `xc7k480tffg1156-2`, clock
**20 ns/50 MHz**, seed **3588**, and every native validity/refinement and later
timing/electrical/DRC gate remains. No bitstream is ready or supplied.

Production source remains `09f1c3f65ba9`; the latest whole HDL regression is
still the archived compile-timeout FAIL, while the pinned nine-mode mapped
replay remains three completed modes/mode 3 live. No whole-suite rerun or
fixture regeneration is performed during that replay. Fresh generated checks
pass. Per the user, no new standalone `SHA256SUMS` manifest is written; old
manifests are untouched and per-run JSON content bindings remain.

### 2026-10-08: two native legalizer passes qualified; full retry launched

The first bounded-search qualification above finishes **FAIL at 11:00:05 HKT**.
Its actual illegal-pair command correctly returns **125** in **47.326 seconds**,
with the unchanged final-validity diagnostic and no placed output. The failure
is in the added log harness: it requires one begin/completion pair, while the
actual frozen `StaticPlacer::place` source calls `legalise_step(true)` for
DSP/BRAM and then `legalise_step(false)` for logic, each calling strict
legalization with validity enabled. Both native passes actually complete (13
and 28 queue pops). The [terminal failed report](../build/openxc7/strict-search-qualification-1791428189705464078/report.json)
binds 3,402 sources/six artifacts; its code, controls, logs and FAIL remain
unchanged. No native source, algorithm, expectation or executable is corrected
to address this harness failure.

The [separate two-pass qualifier](../tools/openxc7/qualify_strict_search_rounds.py)
extends the frozen procedure only in its own process. It revalidates that
failed report/input/log, confirms the old parser still rejects it, and binds
its new entrypoint/parser/control. It requires exactly two ordered completed
rounds, no nested/extra/missing pass, every marker's validity enabled, no
out-of-grid samples, empty completed queues, nonregressing counters/times and
all original queue entries processed. Thirteen controls pass, including all
six original admission controls unchanged.

The [new actual qualification](../build/openxc7/strict-search-qualification-1791428735139099414/report.json)
completes at **11:27:14 HKT** with status
`QUALIFIED_SMALL_NATIVE_BOUNDED_STRICT_SEARCH_TWO_PASSES_AND_DSP_BRAM_PNR_NOT_FULL_FIT_OR_SIGNOFF`,
binding **3,411 sources/16 artifacts**. The original illegal case returns 125
in **48.727 seconds**; the three original positive placements pass in
**48.302/46.671/49.617 seconds**, retaining their 49/49/47 cells and **1,024**
original LUT-output comparisons. The unchanged four-DSP/six-BRAM input completes
normal placement, refinement, routing, connectivity check and FASM export in
**844.658 seconds**. All source-defined DSP/BRAM features compare, with
**7,682 unique features/five repeated STEPDOWN lines**. Every native command has
two completed strict-search rounds; the executable remains
`81481d44f65da7685c96fcf0d5b7c1cfcabe3ddf271c37997ec6191e4ae1bb7d`.
Unit `rknpu-strict-search-rounds-qualification-20261008.service`, invocation
`7d97c9657f0247aeabece26164d54e74`, finishes normally. These are small native
controls, not full circuit numerical/physical acceptance.

The [fresh full-size retry](../build/openxc7/full-prefix-bounded-search-place-1791430153316326483/report.json)
now runs under `rknpu-full-prefix-bounded-search-place-20261008.service`,
invocation `cb250e1333ed4d8eab67a74da5170d98`, supervisor **1344055/native
1344200**. Admission independently rechecks the completed qualification and
every bound original preparation/pack/failed-placement input: **4,945 bindings**.
Its three admission controls, generated checks and executable version pass.
It repacks the actual unchanged physical input before placement; no old
checkpoint/macro state is reloaded. The target remains **C32/K16, 512 CMAC plus
three shell DSPs, six BRAMs, xc7k480tffg1156-2, 20 ns/50 MHz, seed 3588**.
The native host timeout is 12 hours/outer runtime 13 hours; CPU quota is
**unlimited**, memory high/max **12/14 GiB**, swap max **4 GiB**, nice 5,
child address-space max **12 GiB**, OOM stop/control-group cleanup/no core dumps.
No FPGA timing/validity/electrical check is relaxed. There is still no completed
full placement, routed circuit or bitstream.

### Prepared corrected full-route handoff and empty plain-LUT output contract

The old full-route runner admits only the old precision engine/31-tie policy;
its expectations are unchanged. The [separate full corrected runner](../tools/openxc7/route_strict_search_board.py)
requires the completed new full placement, exact full-target primitive/kernel
census, independently revalidated small imported-checker qualification, and a
shared corrected-DSP base between placement and route engines. It must execute
the native all-BEL scan before normal routing, with exactly the pair/carry-role
counts read from that full literal placement. Every BEL, primitive parameter,
original logical endpoint/wire bijection and **all 515 DSP/six-BRAM features**
must then compare. The imported-checker engine is used with no pack/no place;
the bounded-search placer is not re-executed during routing. Complete physical
footprint/logical proof files and memory-bounded empty-declaration contracts
are comparison artifacts only. No tensor bypass, arithmetic/layout repair,
comparison view as execution input, full numerical acceptance or physical
signoff is permitted. This runner is prepared **but not launched**.

A read-only census of the actual corrected full pack rehashes it before/after
and inspects all **538,118** records. It finds **24** empty plain-LUT outputs,
**9,078/26,601** empty CARRY4 input/output declarations, **69,525** empty DSP
inputs and **372** empty BRAM inputs; no empty FF/mux/I/O declarations occur.
The actual example `rk_mapped_cell_85079$split$xorcy0` is a packed LUT2 with
`O6=[]` and `X_ORIG_PORT_O6=O`. The pinned generic frontend's empty-vector
omission also applies to this declared, disconnected output. The old plain-LUT
logical proof still rejects the missing output; it is not modified.

[The separate full-export comparison helper](../tools/openxc7/compare_full_imported_export.py)
represents only an absent `[]` O5/O6 output with unchanged plain LUT1–6 kind,
literal INIT and original logical-O annotation. Memory/SRL modes, unknown or
multiple outputs, changed function/mapping, existing direction corruption and
missing connected outputs cannot be repaired. Complete original LUT logic
and physical-footprint checks remain mandatory. No source/native input is
changed or comparison view executed. Eight new export controls and seven
full-route admission/comparison controls now pass (**15 total**), including
the actual full-pack LUT2, saved 49/286 logical proofs, and an explicitly
synthetic 50-cell disconnected-output proof. These are software comparison
controls, not a full native route or numerical/FPGA pass.

Two new control-harness failures are preserved with fresh actual reruns and
executed sources: a wrong parent directory at
`build/openxc7/full-export-direct-control-path-fail-1791430003164626915/`
(14 methods/one error), then pre-route wire IDs copied into the routed half
of a new synthetic fixture at
`build/openxc7/full-export-direct-control-wire-fixture-fail-1791430152684136978/`
(15 methods/one split-wire failure). Only the new artifact path and synthetic
fixture's routed-side copy were corrected. The fixture now preserves the
actual native wire renumbering and LUT input permutation; the original split-
wire checker and required 50-cell comparison remain unchanged. Neither FAIL
is relabeled, and neither is an RTL/numerical execution result.

Production source stays `09f1c3f65ba9`. The pinned mapped replay remains live
in mode 3 with three of nine modes complete; no fixture regeneration or whole
`make test` rerun is performed during it. The latest whole production regression
remains its archived compile-timeout FAIL. Fresh generated checks pass; no new
`SHA256SUMS` manifest, bitstream or hardware programming is performed.

### 2026-10-08: native disconnected-output diagnostic and isolated v2 build

The full pack's 24 disconnected plain-LUT outputs are not themselves evidence
of a native import-checker pass. The actual qualified checker requires a
connected O5/O6 for each member of a pair. Its pinned frontend creates port
metadata only inside the connection-vector loop, so a literal `[]` output is
dropped. An absent output and a declared empty output then look identical.
The existing checker/gates are not changed to accept an absent connected output.

The [new diagnostic](../tools/openxc7/probe_imported_empty_lut.py) copies all
49 cells and their BELs from the qualified checkpoint and adds one test-only
unused LUT2 to a free A5LUT slot. Its exact INIT and XORCY transformation
annotations come from the actual full packed record. Its two logical inputs
alias the existing upper LUT's single input; no live output/net is added.
The upper receives the existing source-defined A6/VCC mode while retaining
the identical original logical circuit. This is a **test-only 50-cell fixed
checkpoint**, not a new native placement or a change to the full execution
input. It does not establish how the 24 full-design records will be placed.

The [actual diagnostic report](../build/openxc7/imported-empty-lut-diagnostic-1791432126438912643/report.json)
completes at **12:03:49 HKT**, binding **3,557 sources/seven artifacts**.
Three fresh software controls and generated checks pass. The unchanged native
checker returns **125 in 2.191 seconds** with its exact
`changed logical output mapping` diagnostic, before routing and without
publishing an output checkpoint. The unit completes normally because this
specific unsupported rejection is the diagnostic's expected result, **not a
positive checker qualification**. Source, seed 3588, exact part and 50 MHz
are recorded; numerical/full placement/full route/physical flags remain false.

The first direct diagnostic host control fails at a wrong Python import:
`probe_corrected_dsp_checkpoint` does not export `logical_lut`. Its actual
completed output and pre-edit sources are retained at
`build/openxc7/imported-empty-lut-direct-control-fail-20261008-0400/`.
Only the new diagnostic import is corrected to the existing strict
`route_prefix_board.logical_lut`; the old failure, logical proof and native
checker remain unchanged. No rejection expectation is changed.

The separate [source-bounded v2 candidate](../tools/openxc7/empty_output_candidate.py)
uses the reader's existing JSON DOM, not a second full-file parse. Only the
explicit opt-in `fixed-lut-v2` flat exact-target profile preserves a plain
LUT's literal annotated `[]` O5/O6 as null-net `PORT_OUT` metadata. Missing,
unknown, constant, malformed/non-array, multi-bit, wrong-direction,
unannotated live or duplicate logical outputs fail. Memory/SRL and unsupported
logical resources are not admitted. Every connected port, net, driver/sink,
INIT/parameter, attribute, cell and BEL remains unchanged. Default/v1 import
behavior remains the old behavior. No arithmetic/layout repair is performed.
The v2 checker accepts only this retained null-port declaration; it keeps all
other native guards and adds the necessary null-net guard to the existing
sole-user carry-DI predicate. A disconnected output is never a carry feed.
Original tags are still restored and validity caches invalidated.

The [isolated build](../tools/openxc7/build_empty_output_checker.py) completes
at **12:18:15 HKT** under `rknpu-empty-output-checker-build-20261008.service`, invocation
`bc9ece0cca19473f940128db1b42b8ba`, supervisor **1349487**,
[report](../build/openxc7/empty-output-checker-engine-1791432510377723138/report.json).
It rechecks the completed small qualification and exact native diagnostic,
byte-relinks the qualified parent, and compiles only two replacement objects:
`json_frontend.cc.o` and `xilinx.cc.o`. No donor/live executable or default
engine is overwritten. CPU quota is one core, memory high/max 4/6 GiB, swap
max 2 GiB, nice 10, outer runtime 40 minutes, OOM stop/control-group cleanup
and core dumps disabled. Five source/declaration controls pass, as do fresh
generated checks. Parent relink is byte-identical; actual architecture/frontend
compiles pass in **252.983/161.750 seconds**, link in **13.249 seconds**, without
warning suppression. The completed report binds **3,569 sources/25 artifacts**,
with executable `4c8133af04bc6e950a046f37e64949aaee4a2623f7dd6a7be69d93ea82377a4b`.
The unit completes with exit zero. This is **build completion, not native qualification**.

The [prepared fresh qualifier](../tools/openxc7/probe_empty_output_checker.py)
has four passing host controls and must independently bind the completed
candidate before any native run. It requires a fresh v1 49-cell positive and
the unchanged v1 50-cell rejection; all eight existing carry/pair corruption
rejections; eight new literal-output/input-mapping rejections; and fresh v2
49/50/286-cell native scans, normal routes, exact BEL/logical identity and
four-DSP/six-BRAM feature comparisons. The 50th output must remain `[]` in the
actual native export with **zero comparison-only output restorations**.
The earlier pair auditor must still reject the 50-cell empty-output fixture.
The prepared full-route runner is not modified or admitted by these host tests.
The first qualifier ran under
`rknpu-empty-output-checker-qualification-20261008.service`, invocation
`2ad1ef3265e24765b95ac9fc47d88b4f`, supervisor **1353050**. Its terminal result
is **FAIL**, not native qualification; see the separate continuation below.
It retained one-core CPU quota,
4/6 GiB memory high/max, 2 GiB swap max, nice 10, a two-hour outer limit,
30-minute per-native-command limit, OOM stop/control-group cleanup and no
core dumps. Its actual source-bound report/logs are separate from the old
checker and diagnostic evidence; the full input and live jobs are unchanged.

Full C32/K16 placement and the pinned mapped replay remain running. The full
target is unchanged at 512 products/515 total DSPs/six BRAMs, exact part,
20 ns and seed 3588. Production source remains `09f1c3f65ba9`; the latest
whole HDL regression remains its archived compile-timeout FAIL. No fixture
regeneration or whole `make test` rerun is performed during the pinned replay.
No new standalone `SHA256SUMS` file, bitstream or FPGA/flash programming occurs.

### 2026-10-08: explicit test strength, completed small v2 qualification and prepared handoff

The [first actual v2 qualification](../build/openxc7/empty-output-checker-qualification-1791433199135092252/report.json)
fails at **12:30:45 HKT** after all seventeen expected native rejections and
successful 49/49/50-cell native routes. The unchanged strict footprint gate
reports `Changed resource properties: test_only_declared_empty_XORCY_LUT2`.
The native 50-cell scan itself checks ten pairs/eight carry roles and routes
normally, retaining the actual `O5=[]` output. However, the manually added test
LUT had no input `BEL_STRENGTH`; native export adds its effective value **6**.
The 286-cell command was not executed. The original input, source, failed
comparison, report and **3,597 sources/51 artifacts** are preserved unchanged.
Successful native tool execution is not qualification when a later gate fails.

The pinned primary `common/kernel/basectx.cc` reader uses
`PlaceStrength::STRENGTH_USER` when this attribute is absent, and its writer
exports the effective binding strength. `common/kernel/nextpnr_base_types.h`
defines USER as **6**. The [separate test-fixture helper](../tools/openxc7/fixed_empty_output_fixture.py)
therefore declares exactly that existing effective default on the new unused
50th LUT; it changes no original 49-cell resource, BEL, net, INIT or full input.
The strict resource-property comparator is not altered. Eight host controls
include all four old controls, verify the exact primary-source default and
confirm that the old gate still rejects the original actual failed export.
An in-memory comparison annotation of that older export is explicitly a
diagnostic, never fresh qualification or a modified execution input.

The [fresh continuation](../tools/openxc7/resume_empty_output_qualification.py)
rechecks that source-bound FAIL and re-executes the entire native suite under
`rknpu-empty-output-fixed-strength-qualification-20261008.service`, invocation
`1e20cd58ee2f438990c61a98d95585d8`, supervisor **1357077**. Its
[actual report](../build/openxc7/empty-output-checker-qualification-1791434347351474071/report.json)
completes **PASS at 12:49:18 HKT**, with **3,652 sources/55 artifacts** and all
24 actual commands complete. All seventeen expected rejections return 125
before routing. Fresh v1-49/v2-49/v2-50/v2-286 native scans/routes finish in
**105.039/102.737/103.617/106.766 seconds** respectively. Every BEL, primitive
parameter and original logical endpoint/wire relationship compares. The
50-cell export retains its literal empty output with **zero** comparison-only
output restorations. The 286-cell output also compares all four DSP/six-BRAM
configuration sets and **7,655 unique FASM features**, retaining five known
STEPDOWN repetitions. The compiled engine is unchanged from the isolated v2
build, with no default/donor executable replacement. CPU/memory/clock/seed,
normal router checks and all numerical/physical exclusions remain unchanged.
This is **small native v2 qualification, not full placement, route or signoff**.

[Separate read-only pair/carry auditors](../tools/openxc7/audit_empty_output_pairs.py)
derive the old functions with exact reversible changes for fully validated
literal empty LUT output declarations. Every other guard remains. They do not
modify original modules, native inputs or tags. Five host controls pass;
actual 49/286 results equal the old auditors, and the test-only 50-cell input
has ten pairs/eight original carry roles. The old auditors still reject it.
All eight literal/input corruptions and wrong shared-pin/A6 cases remain errors.
The actual first host attempt, five methods with one FAIL/one ERROR, is retained
at `build/openxc7/empty-output-pair-direct-control-fail-20261008-0425/`.
Only the new helper's upfront output-declaration validation was corrected;
old guards and rejection expectations are not changed.

The [completed-evidence admission helper](../tools/openxc7/verify_empty_output_evidence.py)
requires this distinct completed qualification, exact native argv/rejections,
source/engine hashes, scans, all physical/logical comparisons and DSP/BRAM FASM.
Its five metadata tests are software-only and cannot qualify an actual run.
The [separate full v2 handoff](../tools/openxc7/route_empty_output_board.py)
has **19 passing host controls**, including all fifteen original full-route/
export controls. It retains the exact full placement admission, 538,118 cells,
515 DSPs/six BRAMs/sixteen kernels, literal no-pack/no-place execution input,
normal connectivity, every BEL/parameter/logical wire and all full primitive
features. An exact native literal-output import census must precede the full
all-BEL scan. Only the opt-in profile, new evidence/auditors and distinct
output/status are changed; the original full procedure is source-reversibly
derived in an independent namespace. No comparison view is an execution input.
The full handoff is **prepared, not launched or admitted**.

[Actual read-only evidence revalidation](../tools/openxc7/revalidate_empty_output_evidence.py)
completes **PASS at 12:53:21 HKT** under `rknpu-empty-output-evidence-revalidation-20261008.service`,
invocation `53710c91d45a48f2927d585be24b8874`, supervisor **1359939**,
[report](../build/openxc7/empty-output-evidence-revalidation-1791435045061004777/report.json).
It passes all **37** relevant host controls and generated checks, then rehashes
and recomputes the actual completed native evidence and pair/carry inputs,
binding **3,822 sources/seven artifacts**. Actual 49/50/286 inputs yield
**9/10/98** pairs and **8/8/0** carry roles. All 24 native commands, seventeen
rejections, four routes and selected primitive features are revalidated. It does
not rerun native placement/routing or accept a full-board result. Full-size
placement and mapped-board mode 3 remain active and unchanged. Production
source is still `09f1c3f65ba9`; the latest whole HDL regression remains its
archived compile-timeout FAIL. No new standalone `SHA256SUMS` file is written.

### 2026-10-08: actual mapped BRAM address-cone preparation and completed binary proof

The prior BRAM audits check all address/data pins and local effective write
gating, but leave the address-decoder function and temporal startup gaps
explicit. The [separate address-cone prover](../tools/openxc7/prove_prefix_bram_address.py)
uses literal mapped signal/physical `n_<wire>` aliases and an offset-backed
complete primitive-driver census. It traces the actual twelve translated
address bits, request-ready and mapped core-fire, rejecting missing/multiple
drivers, cycles, unknown pins/INITs and unsupported or sequential cone cells.
All **35 binary cut inputs** (32 address bits, request-valid, response-valid
and reset) are unconstrained. The independent reference retains the four
unchanged raw byte-address apertures, even alignment, exact flat-halfword
offsets and invalid-address request gating. No address is rewritten for hardware.

The miter instantiates unchanged pinned UNISIM LUT/CARRY4/MUX/INV sources;
the positive and real one-bit wrong-golden negative must pass their distinct
SAT result gates. Six fresh cone/rejection/software controls pass, and
generated-source checks pass. The actual source-bound run is now active under
`rknpu-prefix-bram-address-proof-20261008.service`, invocation
`1cf5d45a050a469ab3348b62e9a58e11`, supervisor **1362626**,
[report](../build/openxc7/prefix-bram-address-proof-1791435787314873410/report.json).
The attempt terminates **FAIL at 13:06:00 HKT**, before either SAT command, at
`Unmodeled primitive pin`. **No completed actual address proof is claimed**.
Runtime was bounded to thirty minutes, with one-core
CPU quota, 4/6 GiB memory high/max, 2 GiB swap max, nice 10 and OOM/control-group
cleanup. This is a read-only combinational cut proof, not temporal ownership,
write-before-read/startup independence, whole-board numerical or physical
signoff. Full C32/K16 placement and the unchanged mapped replay remain live;
no old source/gate, execution input, `SHA256SUMS` file or FPGA is changed.

The actual full-input record `rk_mapped_cell_85044` is a CARRY4 with complete
CI/CYINIT/DI/S inputs and CO output, but no O connection or direction record.
The pinned primary model declares O as a sum output; its CO-feedback and CO
equations do not depend on O. This is an omitted unused output, not a missing
input. The original validator and its actual FAIL/source/logs remain unchanged.

The [separate sparse-output prover](../tools/openxc7/prove_sparse_prefix_bram_address.py)
rechecks that failure, hashes, actual record and exact primary equations.
It derives the original validator with one reversible change: only CARRY4's
absent O output may be omitted from the required pin set. Every required input
and CO, all present output widths/directions, unknown bits, unsupported cells,
driver/cycle/census checks, complete address reference, unchanged primitive
models and SAT/real-negative gates remain. No physical pin/net/input is added
or modified; the original model's unused output is simply not connected.
All **nine** fresh host controls pass, including all six original methods.

Its fresh actual full-census/proof attempt ran under
`rknpu-prefix-bram-sparse-address-proof-20261008.service`, invocation
`415fa587f77648fbbcba655251f391cc`, supervisor **1363354**. It retains the same
bounded CPU/memory/runtime settings. The attempt terminates **FAIL at
13:14:58 HKT**, before SAT, with
`Unsupported/sequential address-cone primitive: FDCE`; its
[report](../build/openxc7/prefix-bram-address-sparse-output-proof-1791436318614640675/report.json)
binds 166 sources. The old failures are not relabeled. The
35-input/14-output binary cut remains the proof target; temporal response
errors, write-before-read/startup independence, full numerical and physical
signoff remain excluded. The full-size placer is progressing through strict
legalization; the unchanged mapped-board replay remains in mode 3. Neither
has a completed full placement or nine-mode acceptance yet.

The second failure establishes that the proposed free address/control signal
cut is not closed in the actual optimized mapped circuit: upstream logic is
shared across that boundary. It is not evidence of an RTL address error.
The [separate coherent prover](../tools/openxc7/prove_coherent_prefix_bram_address.py)
therefore traces **all** compared semantic signals together and keeps their
shared combinational logic. It stops only at explicitly validated actual
registered Q outputs or P bits of the audited zero-register DSP configuration.
Those producer bits are unconstrained binary inputs, not assumed initialized,
reachable or numerically correct. In particular, unknown register INIT values
remain unchanged; no startup value is supplied. The reference address/control
values are derived from that same actual shared cone, while the independent
four-aperture/alignment/offset/accepted-request contract remains literal.
All connected primitive ports stay strict; either unused CARRY4 output may
be absent without connecting, repairing or substituting a physical pin/model.

All **13** host controls pass, including all nine previous methods. The first
two source-bound failures remain exact. The fresh run is active under
`rknpu-prefix-bram-coherent-address-proof-20261008.service`, invocation
`d60f01fe850042788ddbf82ec4791139`, supervisor **1364988**,
[report](../build/openxc7/prefix-bram-address-coherent-proof-1791437025464486188/report.json).
It revalidates the pinned producer-interface models and complete driver census,
actual cone, normal unchanged combinational models, positive SAT and exact
wrong-golden negative. All missing/unknown/unsupported drivers remain errors;
there is no generic unknown-leaf-as-free-input fallback. Native execution
inputs and production RTL are unchanged. The attempt terminates **FAIL at
13:26:54 HKT**, before SAT, at its explicit
`Missing/unbounded coherent producer cut` software capacity check. Its
512-input/20,000-cell probe capacity does not establish that the complete
shared cone is invalid. The original capacity check and failed evidence
remain exact; no completed address/startup/numerical/physical result follows.

The [separate full-census-budget prover](../tools/openxc7/prove_full_budget_prefix_bram_address.py)
rechecks all three actual failures and changes only the read-only proof
harness's capacity and new output directory/status. Its limits come from the
complete admitted **503,128-cell** physical-input census: **17,519** register
Q bits plus **24,720** P bits of all 515 DSPs give at most **42,239** supported
binary producer inputs. No node is skipped, no unknown producer is made free,
and no primitive, address contract, comparison output, SAT/negative gate or
input assumption changes. This is a larger proof workload, not a smaller
FPGA, transformed execution path or resource/timing/electrical/DRC waiver.
The native **120-second SAT**, 180-second command, 30-minute outer and 4/6 GiB
memory limits remain unchanged. All **15** host controls pass, including all
thirteen earlier methods. The complete actual cone/input counts will be
recorded by the fresh run; they were not published by the earlier budget FAIL.

The fresh full-census attempt ran under
`rknpu-prefix-bram-full-budget-address-proof-20261008.service`, invocation
`e4f2169d9e0d4799bfc587571883abe4`, supervisor **1365542**. It must still execute
the actual census, unchanged-model positive SAT and exact real wrong-golden
negative, and rehash its sources before acceptance. It instead terminates
**FAIL at 13:33:20 HKT** before tracing/SAT: the derived function's independent
namespace lacks its frozen `base` module binding. The
[actual report](../build/openxc7/prefix-bram-address-full-budget-proof-1791437421979606743/report.json)
preserves this exact `NameError`, source, host controls and generated/version
results. No cone count or proof is inferred from that failed harness run.
Preparation and software
controls are **not an actual address proof**; all startup/full numerical and
physical gates remain open. Full placement and mapped replay continue with
unchanged source, clock, part and C32/K16 target.

[The distinct namespace continuation](../tools/openxc7/resume_full_budget_prefix_bram_address.py)
rechecks that actual FAIL and every prior source-bound failure, adds only the
missing frozen module binding in a new independent namespace, and retains the
identical derived trace function, full census capacity, primitive/address/model
contracts and native SAT/negative/time/memory gates. It changes no old module
namespace or report. Seventeen host controls pass, including all fifteen old
methods and a direct synthetic producer-cone execution that reproduces the
old NameError and verifies the new function against the original coherent
implementation. That synthetic cone is not actual mapped evidence.

The actual fresh run completed with **FAIL** at **13:39:04 HKT on 2026-10-08** under
`rknpu-prefix-bram-full-address-resume-20261008.service`, invocation
`257ef893ec3c4e1e9f7e27236d1853d5`, supervisor **1365859**, with the same bounded
host and native limits. Its [terminal report](../build/openxc7/prefix-bram-address-full-budget-resume-1791437760192160498/report.json)
records a complete 557-cell shared cone and 624 unconstrained FDCE Q bits:
28 CARRY4, five INV, 169 LUT2, 35 LUT3, 43 LUT4, 37 LUT5, 210 LUT6, 27 MUXF7
and three MUXF8. The negative Yosys invocation exits 1 in 0.106 seconds at
`LUT1.v:60`, rejecting the vendor simulation UDP syntax. The exact real-SAT
negative gate correctly refuses this frontend error; positive SAT never runs.
The 198 source bindings, ten artifacts and all earlier failures are preserved.
This is **not a completed address or startup proof**.

[The distinct binary-library continuation](../tools/openxc7/resume_binary_library_prefix_bram_address.py)
revalidates all five source-bound failures and the unchanged hardware input,
independently retraces the serialized cone and regenerates the exact saved
miter. It reuses the bound completed full-driver census rather than rescanning
the half-million-cell input. No missing primitive becomes an opaque input.
It uses the unchanged installed Yosys `xilinx/cells_sim.v` only after fresh
binary simulation compares all 557 actual primitive instances, with their
original parameters, to unchanged pinned UNISIM. The ten independent input
bits enumerate all 1,024 CARRY4 combinations and all combinations of every
retained LUT, MUX and INV. Both libraries retain vendor default global startup;
no vendor function is rewritten. A separately executed one-bit first-vector
wrong-golden corpus must be rejected. This qualification deliberately makes
**no four-state equivalence claim** and does not override known carry X/Z
differences. Only successful qualification admits the original actual address
miter to the unchanged SAT-positive and exact real-SAT-negative gates.

Twenty-three host controls pass, including all seventeen previous controls.
The actual new run completed with **FAIL** during vendor Icarus elaboration under
`rknpu-prefix-bram-binary-library-resume-20261008.service`, invocation
`693c58ac9da54c488855d9159ecda11f`. Its
[terminal report](../build/openxc7/prefix-bram-address-binary-library-resume-1791438584044546240/report.json)
records the unchanged vendor bench rejecting a use of `observed` before its
later declaration. No binary comparison or SAT result is produced. This sixth
failure, source and generated bench remain unchanged; neither a return code
nor the library model was waived.

[The separate declaration-order continuation](../tools/openxc7/resume_declared_binary_prefix_bram_address.py)
moves only the original testbench initial block after its output declarations
and requires an exact inverse reconstruction. It preserves every actual
primitive instance, INIT parameter, input combination, default global startup,
wrong-golden and SAT gate. Twenty-five controls pass with Python warnings
treated as errors, including actual Icarus compilation of the same small bench
against each unchanged library. Those small compile controls are not actual
full-cone qualification. The fresh run completed with **FAIL at 13:53:12 HKT** under
`rknpu-prefix-bram-declared-binary-resume-20261008.service`, invocation
`2a346b1702744bd39a9c69210773e448`. Both unchanged-library compilations and both
full binary simulations exit 0, but the literal 1,024-line parser rejects
Icarus's additional native `$finish` informational record. Its
[terminal report](../build/openxc7/prefix-bram-address-declared-binary-resume-1791438732760601100/report.json)
retains all 1,024 actual vectors and the notification, with no library/SAT PASS.
This seventh actual failure is preserved, not relabelled.

[The separate native-result continuation](../tools/openxc7/resume_binary_result_prefix_bram_address.py)
requires the exact generated testbench path and `$finish` line, completion time
`1125000 (1ps)` after unchanged default global startup and all 1,024 stimuli,
and exactly 1,024 preceding vectors. It then uses the unchanged strict original
binary comparator. Warnings, errors, X/Z, missing/reordered results, changed
footer/time/source or wrong output still fail. No message is suppressed and no
bench/model is edited. Twenty-seven controls pass with warnings treated as
errors, including actual compilation/execution of a small unchanged native
bench to verify this completion record. The fresh full run completed with
**FAIL at 13:57:00 HKT** under
`rknpu-prefix-bram-binary-result-resume-20261008.service`, invocation
`3f16629492ec42e8affc51b74ba48741`. Its
[terminal report](../build/openxc7/prefix-bram-address-binary-result-resume-1791438937254216944/report.json)
records **570,368** successful binary instance comparisons across all 557 actual
cells and 753 observed output bits, and rejection of the separately executed
one-bit first-vector wrong-golden corpus. The actual negative SAT solver imports
2,375 lowered cells and finds a counterexample, but the unchanged no-warning
gate refuses two library frontend warnings at lines 84 and 102: unused
tri-state I/O models in the full installed library. Positive SAT never runs.
All 277 source bindings and 31 artifacts remain frozen; this eighth FAIL is
not changed to address acceptance.

[The separate selected-definition continuation](../tools/openxc7/resume_selected_binary_prefix_bram_address.py)
selects only the nine actual combinational primitive types from the unchanged
installed library. Every complete definition is a byte-identical source
substring with its original attached/pin attributes, parameters, logic and
specify blocks; the original license/header and complete library are retained.
Per-definition offsets, lengths and hashes bind this selection. No unrelated
I/O type is used by the actual cone and no function is rewritten. The fresh
full 557-instance vendor-versus-selected-library binary qualification and real
wrong-golden corpus must pass before the same exact actual address miter runs.
The original strict SAT positive/real-negative, warning and limit gates remain
unchanged. Thirty host controls pass, including all 27 old controls and an
actual Yosys selected-library frontend/check run without any diagnostic waiver.
The fresh full run completed with **PASS at 14:01:32 HKT on 2026-10-08** under
`rknpu-prefix-bram-selected-binary-resume-20261008.service`, invocation
`00de365722ba4071a71aeaf15428c640`, with unchanged CPU/memory and 120-second SAT /
180-second command limits. Its
[completed actual report](../build/openxc7/prefix-bram-address-selected-binary-resume-1791439177232717008/report.json)
records 311 source bindings and 34 artifacts. Thirty controls pass in 3.052
seconds and generated checks in 1.544 seconds. Fresh vendor/selected-library
binary simulations match all **570,368** instance comparisons across the 557
actual primitives, 1,024 stimuli and 753 output bits. The separately executed
one-bit first-vector wrong-golden corpus is rejected. The original strict
native negative exits 1 in **14.461 seconds** with its exact real counterexample
and sole expected error; the positive exits 0 in **14.832 seconds**, with
`SAT proof finished - no model found: SUCCESS!`. Neither log has a warning,
timeout or unknown-cell diagnostic. The positive uses 16,553 SAT variables
and 42,965 clauses; no input assumptions or register initialization values are
inserted.

Actual tools are **Yosys 0.65**, revision
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`, built by g++ 12.3.0 with `-fPIC -O3`,
and **Icarus Verilog 13.0 stable (`v13_0`)**. The pinned UNISIM commit remains
`1c8e05fd1e9a79ceb8b996a0996674122eed086f`. This exhaustive binary proof uses no
random seed. The production source fingerprint is identical before and after:
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
The eight old failures, source-bound full-census cache and exact hardware input
remain unchanged. No old failed run is promoted to PASS.

A separate read-only check at **14:04:37 HKT** rebinds all 345 source/report/
artifact paths, retraces the serialized actual cone, regenerates the exact
miter and byte-identical selected definitions, re-evaluates both actual binary
corpora and the executed wrong-golden corpus, and applies the original native
SAT-positive/real-negative validators to their actual logs. It confirms the
unchanged production source and absent startup/numerical/physical acceptance
flags. It does not rerun native SAT or promote any old failure. To run a fresh
bounded native qualification/proof attempt from these unchanged sources:

```sh
python3 tools/openxc7/resume_selected_binary_prefix_bram_address.py
```

The command creates a separate report directory, not a `SHA256SUMS` manifest,
and does not launch P&R, relax any gate or program hardware.

This closes the **binary twelve-bit translated address, ready and mapped
core-fire property over the complete coherent 624-FDCE-Q-output boundary**.
It is not a state-transition or independently initialized/reachable-state
claim. In particular, the asynchronous response-error behavior, temporal port
ownership and observable startup/write-before-read independence are not proved.
Full placement is live in strict legalization;
the source-pinned nine-mode mapped-board replay has since completed mode 3
and entered mode 4; four of nine modes are complete. Temporal
ownership, write-before-read/startup, full numerical/physical signoff,
bitstream emission and hardware programming remain unproved. No standalone
`SHA256SUMS` file is generated.

### 2026-10-08: actual working-BRAM overwrite qualification preparation

[The separate primitive qualifier](../tools/openxc7/test_prefix_working_bram_overwrite.py)
targets the two actual working `RAMB36E1` records
`rk_mapped_cell_86684` / `rk_mapped_cell_86685`, rather than an arbitrary RAM
fixture. It rebinds the completed source-bound address, full memory wiring,
consumer/INIT and enable/write-gating reports. It recomputes the complete local
1,024-assignment write-control contract and requires the full 503,128-cell,
515-DSP/six-BRAM physical input and 512-product target. No hardware input or
live native job is modified.

The exact nine-bit READ_FIRST/no-output-register parameters, all twelve
address bits, host/core clock pins, 9+7 consumed data/parity lanes, write-lane
replication, tied-low reset/register-enable pins and unconsumed X inputs are
preserved at an explicit **primitive input-pin unit-test boundary**. This
boundary is not an alternative hardware command interface. The three
test-only startup views are the unchanged mapped-X parameters, the audited
encoder's zero INIT/initial-output policy, and a counterfactual assignment of
one to only unknown INIT/initial-output/SRVAL symbols. Mode, width, clock,
ordinary data/control incidence and known parameter bits do not change.
No runtime CPU operation or layout fixup enters the FPGA path.

The [native bench](../tests/cmac/tb_prefix_working_bram_overwrite.sv) uses six
instances of the unchanged pinned vendor model, default 100 ns GSR and the
unchanged packaged source ROM. It must observe all 4,096 cold words as
X/zero/one before initialization, perform 12,288 writes, 20,480 known-data read
checks, 12,288 READ_FIRST old-data checks and 34 disabled-port retention
checks, including full host initialization, core writes, both-port
different-address reads and a second complete initialization. The separately
executed wrong-golden negative must see the correct finite first word in all
three views and reject a one-bit golden mutation. Unknown data cannot satisfy
that negative gate; warnings, errors and changed native completion records
remain failures.

Seven host controls pass, including actual compilation of the complete
six-instance corpus without warning waivers. The actual first run fails during
admission at **14:20:30 HKT**
under `rknpu-prefix-working-bram-overwrite-20261008.service`, invocation
`032cdd70a3b94a029b45a76237d3b87b`, with CPU quota 100%, memory high/max 4/6 GiB,
swap limit 2 GiB, nice 10, 180-second native command and 1,800-second job limits.
Its [terminal report](../build/openxc7/prefix-working-bram-overwrite-1791440422211967208/report.json)
records `KeyError('9')`: the wiring checker creates integer width keys, but the
new qualifier looks up string `"9"`. No native command runs. This report has
**no input bindings or executed source snapshots**, because the failure occurs
before they are recorded. That limitation is not hidden or retroactively
filled in. The original report, helper, testbench and controls stay unchanged.

[The separate exact-key continuation](../tools/openxc7/resume_prefix_working_bram_overwrite.py)
changes only that string lookup to the actual checker-created integer 9, with
an exact reversible source check. Nine controls pass in 22.178 seconds,
including direct read-only reproduction of the original failure and admission
of the exact completed full-size inputs using the corrected key. The new run
captures its own source/control/derived-main snapshots before admission and
labels the original unchanged helper snapshot explicitly as a **post-failure
observation**, not an old executed-source binding. Parameter/alias contracts,
the whole six-instance native corpus, default GSR, strict warning and real
negative checks and native limits are unchanged.

The fresh run terminates with **FAIL at 14:27:59 HKT** under
`rknpu-prefix-working-bram-overwrite-resume-20261008.service`, invocation
`db597c0730c844439d76b26282a0e101`, with identical limits. Its
[source-bound terminal report](../build/openxc7/prefix-working-bram-overwrite-resume-1791440837448998352/report.json)
records 471 source bindings and 18 artifacts. Nine controls pass in 22.449
seconds, generated checks in 1.462 seconds, and actual compilation in 1.740
seconds without diagnostic waivers. The negative invocation exits 1 in 1.326
seconds, but does **not** reach the intended finite wrong-golden check:

```text
working BRAM cold-state mismatch index=0 got=xX00/0000/ffff
Time: 132000
```

The unchanged bench requires all sixteen mapped-X output bits to be X. Known
low-byte zeros do not satisfy that expectation. The original strict negative
validator therefore rejects this unexpected cold-state failure; the positive
sweep does not execute. The helper, bench, source-bound failure and expectations
remain frozen. This is not overwrite acceptance. A separate diagnostic uses
the exact failed attempt's wrapper and unchanged pinned vendor models to trace
internal memory, read/output buffers and exposed ports without force, model
repair, or hardware-input changes. Observations alone cannot establish the
original property or retrospectively accept either failed attempt.

Even a completed unit replay would not prove the actual board controller initializes
every address before engine use, temporal port ownership, full numerical or
physical signoff. Full C32/K16 placement and mapped replay remain live;
bitstream and programming flags remain false. No standalone `SHA256SUMS` is
written.

### 2026-10-08: cold-state diagnosis and isolated primitive qualification

The separate
[read-only native trace](../build/openxc7/prefix-working-bram-cold-diagnostic-1791441446410034638/report.json)
completes at **14:37:45 HKT**, with 492 source bindings and 13 artifacts.
It copies the failed attempt's wrapper and vendor models byte-for-byte and
uses unchanged default GSR. At 1 ns the outer mapped-X INIT parameters and
initial outputs are X, but the first actual working primitive's internal
memory/parity already contain zero; the second contains X. The 132 ns read
then returns `xX00`. The output buffers and exposed pins agree with the memory
contents: this is not evidence of a stale output event or incorrect pin
binding. A single host write gives `3bb5` through core readback in all views;
a subsequent core write gives `9eef` through host readback. This short trace
is observation only, not the full overwrite test.

The first parameter-table reader fails at **14:41:19 HKT** because it expects
two source locations on a VVP root-scope record. Its
[source-bound failure](../build/openxc7/bram-parameter-forwarding-diagnostic-1791441669153784348/report.json)
is retained; compilation completes but its native minimal bench does not run.
The distinct
[root/unsigned-width continuation](../build/openxc7/bram-parameter-forwarding-resume-1791441885268583217/report.json)
completes at **14:45:01 HKT**, with four controls, 496 source bindings and 19
artifacts. It correctly accounts for the unchanged model's unsigned 36-to-72
bit INIT/SRVAL extension. The actual failed binary has **all 144 memory INIT
parameters changed from outer X to internal zero in mapped instance 0**.
The other five instances preserve all 148 INIT/initial-output/SRVAL values.
The independent minimal untyped constant-forwarding example passes, so this
does not establish a universal forwarding bug or its exact compiler cause.

An initial isolation preparation fails its reversible-source control at
**14:49:27 HKT**: an empty replacement cannot be reversed uniquely. Its
[failed report](../build/openxc7/isolated-working-bram-views-diagnostic-1791442155745317173/report.json)
contains no native execution. The distinct nonempty-comment isolation runner
then [completes actual diagnosis](../build/openxc7/isolated-working-bram-views-resume-1791442263393374080/report.json)
at **14:51:28 HKT**, with five controls, 520 source bindings and 30 artifacts.
Each startup view is compiled independently with its two exact working RAMs.
All **148 parameters in each instance** retain their expected values. Cold
addresses 0, 1 and 4,095 return X / zero / one in their respective executions.
The independent typed outer-parameter example also passes. The evidence
therefore establishes a **context-dependent elaboration discrepancy in the
combined six-instance fixture**, not a physical RAM startup result. The exact
compiler mechanism remains unresolved. No model, compiled input or running
board simulation is repaired or regenerated.

[The new isolated full-corpus qualifier](../tools/openxc7/qualify_isolated_working_bram_overwrite.py)
executes each startup view in a separate, parameter-audited two-RAM context.
The original combined bench and its failure stay frozen. Each view retains
its original sixteen-bit X / zero / one cold expectation; all ordinary
known-data goldens and the complete original transaction sequence remain
unchanged. No fake data aliases or forced state are inserted. Five controls
check exact preservation of the stimulus tail, all corpus counts, strict
positive completion and finite wrong-golden negatives, and bind the completed
isolation evidence. These control checks are not native overwrite acceptance.

The [actual isolated full run](../build/openxc7/isolated-working-bram-overwrite-1791442579674052605/report.json)
completes with **PASS at 14:58:29 HKT**, under
`rknpu-isolated-working-bram-overwrite-20261008.service`, invocation
`38dc414c027a4bafb2603a7302210aab`. The same CPU quota 100%, memory high/max
4/6 GiB, swap limit 2 GiB, nice 10, 180-second command and 1,800-second job
limits remain. Five controls pass in 2.651 seconds and generated checks in
1.529 seconds. The report records 553 source bindings and 30 artifacts.
Actual tools are Icarus Verilog 13.0 stable (`v13_0`), with the same pinned
UNISIM commit `1c8e05fd1e9a79ceb8b996a0996674122eed086f`; this exhaustive corpus
has no random seed.

| Independent startup view | Compile seconds | Real-negative seconds | Full-positive seconds |
| --- | ---: | ---: | ---: |
| Mapped X | 0.973 | 4.668 | 17.785 |
| Encoder zero | 0.861 | 4.445 | 17.315 |
| Counterfactual one | 1.153 | 5.039 | 18.932 |

Each executed negative exits 1 at 163,972 ns with the actual finite `3bb5`
and the one-bit incorrect golden `3bb4`, not an unknown value or unrelated
failure. Each positive exits 0 with its exact per-view marker and native
655,812 ns completion. No warnings or timing/diagnostic waivers are accepted.
**Each view** checks all 4,096 cold words, 12,288 writes, 20,480 known-data
reads, 12,288 READ_FIRST old-data observations and 34 disabled-port retention
checks. The mapped-X execution exercises all 65,536 unknown consumed source
memory bits before complete overwrite. These are separate fresh executions;
the old combined failure is not relabelled or reused as a pass.

The production source fingerprint remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6` before/after.
No hardware input, original model/bench, live placement/replay or source RTL
is modified. The qualifier establishes only the two **actual primitive
configurations' complete overwrite corpus in the three separately compiled
startup views**. Full-board startup independence, temporal ownership,
write-before-read, full numerical/physical/electrical/timing/DRC acceptance,
bitstream emission and programming flags remain false.

To rerun this bounded qualification from the same saved exact inputs:

```sh
python3 tools/openxc7/qualify_isolated_working_bram_overwrite.py
```

A separate read-only verification at **15:01:19 HKT** rebinds all **584**
source/report/artifact paths, reproduces each exact generated full bench,
checks all 148 forwarded parameters per actual instance and applies the
strict validators to all six executed native logs. It verifies the unchanged
production source, original failed reports, per-view complete corpus counts,
all absent board/physical acceptance flags and no new `SHA256SUMS` file.
This is revalidation of the same completed unit evidence, not a new native
simulation, board result or acceptance of the original combined fixture.

The fresh-run command creates a report directory and no `SHA256SUMS` manifest. It does
not rebuild or modify the live board executable and does not invoke P&R or
program a board. The latest whole-production regression remains the archived
600-second Verilator compilation-timeout failure; focused diagnostic and
generated checks do not turn it into a whole-suite pass.

The original full C32/K16 mapped-board replay has also completed mode 3's
reset/reinitialization case in **18,600.413 seconds**: success 1, resets 1,
faults 0, 4,096 initialization/check words, 196 command reads, 6,528 operand
reads, 64 writes/acknowledgments and 44,915 cycles. Mode 4 is live; four of
nine modes are complete. Strict full-size placement remains live, with queue
170,109 at its 6,932-second search sample, legality 1 and zero out-of-bounds
samples. No completed placed circuit, route or test-ready bitstream exists.

### 2026-10-08: actual initialization-state cone and conditional one-step proof

The [actual cone extraction](../build/openxc7/prefix-initialization-state-cone-1791443814047584119/report.json)
completes at **15:20:22 HKT**, under
`rknpu-prefix-initialization-state-cone-20261008.service`, invocation
`87797ac824d0448cbbad4a0c89ea5190`. Four controls, generated checks and the
actual paired-miter frontend check pass. Its fresh complete **503,128-cell**
driver census retains all 515 DSPs, six RAMs and the full 512 simultaneous
products. The report binds 586 sources and ten artifacts. This extraction
alone is not a SAT or startup proof.

Tracing the actual four state registers' D, CE, CLR and Q cones, and the exact
host-read-data aliases, retains **497 combinational cells**: four INV, 197
LUT2, 36 LUT3, 43 LUT4, 27 LUT5, 184 LUT6, four MUXF7 and two MUXF8.
There are **695 producer bits**, comprising 663 exact register Q bits and
32 fully audited RAM output bits. No DSP or unknown producer is replaced
with an opaque cut. The two copies share 679 producer bits and independently
vary the sixteen host-read-data bits: **711 symbolic binary input bits** in
total. The original state encoding and bit order are preserved.

The [separate actual FDCE fold qualification](../build/openxc7/prefix-state-fdce-fold-1791444111003194131/report.json)
passes at **15:22:05 HKT**, under
`rknpu-prefix-state-fdce-fold-20261008.service`, invocation
`3c15b1392ea3478faf7ec366782f67cb`. It binds 354 sources and sixteen
artifacts; three controls and generated checks pass. Each of the four
actual FDCE instances retains its literal unknown INIT and unchanged pinned
vendor model. Ordinary clocked writes seed old Q after default 100 ns GSR;
no forced state, substituted INIT or disabled GSR is used. All sixteen binary
old-Q/D/CE/CLR tuples per instance pass: **64 seed, 64 asynchronous clear/hold
and 64 next-edge checks**. The actual finite one-bit wrong-golden execution
is rejected in 0.099 seconds; the positive completes in 0.079 seconds at
752 ns. This qualifies only the binary post-GSR fold
`CLR ? 0 : CE ? D : Q`, not reachable startup or general four-state behavior.

The [actual conditional single-step proof](../build/openxc7/prefix-initialization-state-independence-1791444759482712816/report.json)
passes at **15:35:17 HKT**, under
`rknpu-prefix-initialization-state-independence-20261008.service`, invocation
`5b0a74e8263542e1a7421614d46ff118`. It rebinds the extraction and fold runs,
independently retraces every cached cell and producer record, regenerates the
exact miter and checks that all four register configurations match the actual
qualified FDCEs. Its 619 source bindings, 33 artifacts and twelve executed
commands are recorded separately; old failure evidence is not copied forward
as a new native pass.

The run freshly compares every actual combinational instance against unchanged
pinned vendor models and complete byte-identical selected synthesis-library
definitions. All **497 × 1,024 = 508,928** binary comparisons match, exhausting
each instance's binary input combinations. The separately executed first-vector
one-bit wrong-golden corpus is rejected. Fresh native SAT then rejects the
one-bit next-state-golden negative in **26.670 seconds** and proves the positive
in **27.499 seconds**, with no accepted warnings. The positive has 15,220 SAT
variables and 39,047 clauses. The real negative's counterexample is current
state `0010`, initialization phase true, and both actual next states `0000`;
only the deliberate one-bit golden mutation makes its `ok` false. It is not
an unrelated frontend failure. The original 120-second SAT and 180-second
command limits remain. Four software controls pass in 24.086 seconds and
generated checks in 3.098 seconds.

Tools are Icarus Verilog 13.0 stable (`v13_0`) and Yosys 0.65
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`; pinned UNISIM remains commit
`1c8e05fd1e9a79ceb8b996a0996674122eed086f`. These exhaustive binary corpora and
the SAT proof have no random seed. Resource limits are CPU quota 100%, memory
high/max 4/6 GiB, swap 2 GiB, nice 10 and a 1,800-second outer job limit.

The proved property is precise: **at one positive clock edge after GSR, when
the shared current actual four-bit state is 0, 1 or 2, independently arbitrary
sixteen-bit host read data cannot change the four next-state bits, with every
other current producer value shared between copies**. It does not establish
reachable producer values, subsequent state equality, initialization completion,
other controller storage, arbitrary differences in the complete RAM contents,
write-before-read, temporal port ownership, full-board startup independence,
four-state library equivalence, full numerical acceptance or physical signoff.
Those acceptance flags remain false. The production source fingerprint stays
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`
before and after. No RTL, model, hardware input, live placement/replay or
existing failed gate is modified, and no new `SHA256SUMS` file is created.

To rerun this bounded proof from the same saved exact inputs:

```sh
python3 tools/openxc7/prove_prefix_initialization_state_independence.py
```

A separate read-only revalidation at **15:44 HKT** passes all **653** bound
source/report/artifact paths and sixteen execution inputs. It independently
recreates the exact cone, miter and complete 497-instance binary bench, reparses
both vendor/library corpora and their executed wrong-golden corpus, reapplies
the strict actual SAT and FDCE fold validators, and checks the genuine negative
counterexample. The production source is unchanged, all thirteen excluded
board/physical acceptance flags remain false, and the three new run directories
contain no `SHA256SUMS`. This checks the same completed evidence; it is not a
fresh native execution or broader proof.

The fresh-run command creates new native evidence, not a full-board pass, P&R
result or board programming action. The latest whole-production `make test` evidence remains
the archived 600-second Verilator compile-timeout failure. Full-size placement
and mode 4 replay remain live at the **15:45 HKT** recheck, with their original
invocations and native processes intact. Placement queue is 168,532 at its
9,694-second search sample, legality 1 and zero out-of-bounds samples. Four
of nine replay modes are complete. A completed placed circuit, routed circuit
and test-ready bitstream remain unavailable.

### 2026-10-08: complete demo/response controller cone and 47-register folds

The [new complete controller extraction](../build/openxc7/prefix-initialization-controller-cone-1791446127029039711/report.json)
completes at **15:59:59 HKT**, under
`rknpu-prefix-initialization-controller-cone-20261008.service`, invocation
`aebe090718a04ce38347ac81bcacc967`. It includes all **44 demo storage bits**
(four state, twelve index, twenty watchdog and eight error-code bits), the
three memory-response ownership/error bits, and nine literal retained control
signals. Those controls are host valid/write, engine reset, pass/fail, host/core
ready and host/core fire. Inlined launch and response-ready expressions are
not invented as missing aliases or claimed as additional observed outputs.
Their actual uses remain traced through retained next-state roots.

The actual complete **503,128-cell** driver census is freshly rebuilt, retaining
the full C32/K16 target, **512 simultaneous products**, 515 total DSPs and all
six BRAMs. Logical-to-physical aliases are bijective; state encoding and bit
order remain unchanged. All 47 next-state D/CE/CLR/Q roots and nine controls
trace to **1,245 actual combinational cells** and **954 producer bits**, with
no opaque DSP or unknown-primitive shortcut. The producers are 922 exact
FDCE Q bits and 32 fully audited RAM output bits. The conditional paired
miter shares 938 producers, independently varies sixteen host-data bits per
copy and compares 56 outputs, giving 970 symbolic binary inputs.

| Actual retained primitive | Instances |
| --- | ---: |
| CARRY4 | 24 |
| INV | 49 |
| LUT1 / LUT2 / LUT3 | 30 / 365 / 114 |
| LUT4 / LUT5 / LUT6 | 86 / 97 / 339 |
| MUXF7 / MUXF8 | 110 / 31 |

This cone includes LUT1, absent from the earlier four-bit state cone. The new
selector explicitly admits only the ten known combinational classes and retains
their **complete byte-identical primary-library definitions**, attributes,
specify blocks and original license header. No library expression is repaired
or warning waived. The actual paired-miter frontend check passes in 36.889
seconds. Six managed controls pass in 20.293 seconds and generated checks in
1.359 seconds. There are 656 source bindings and ten artifacts. An initial
local software-only check caught an invalid library-import path; it was fixed
before this managed native attempt, without changing any earlier helper, gate
or hardware input. Frontend success alone does not prove independence or any
temporal/startup property.

The [separate 47-register qualification](../build/openxc7/prefix-controller-fdce-fold-1791446444581356133/report.json)
then passes at **16:01:05 HKT**, under
`rknpu-prefix-controller-fdce-fold-20261008.service`, invocation
`0074c35eb7574ce28f59b01bc4f5de52`. Its 668 sources and sixteen artifacts bind
all actual register records. Every register is FDCE with literal unknown INIT
and the same positive clock; no inversion or unmodeled register kind is admitted.
The generated wrapper preserves every actual parameter. The original four-bit
testbench stimulus and goldens are reversibly retained, expanding only to the
47 configurations and **752 seed, 752 asynchronous clear/hold, and 752 next-edge
checks**. All sixteen binary old-Q/D/CE/CLR tuples are tested per configuration.
Old Q comes only from ordinary writes after default 100 ns GSR, never forcing
or a substituted INIT.

Three managed controls pass in 2.118 seconds; generated checks in 1.295 seconds.
Actual vendor compilation completes in 0.194 seconds. The executed finite
one-bit wrong golden is rejected in 0.144 seconds at 152 ns; the positive
completes in 0.210 seconds at 752 ns with its exact full-corpus marker. Icarus
remains 13.0 stable (`v13_0`) and the pinned UNISIM source remains commit
`1c8e05fd1e9a79ceb8b996a0996674122eed086f`. The binary exhaustive test has no
random seed. The 47-register fold is **not** an actual controller independence,
reachable initialization, ownership, write-before-read, full-board startup or
physical proof. Those flags remain false; the old four-register qualification
is unchanged.

Both runs preserve the full production fingerprint
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`
before/after, the 180-second native command limit, and the 1,800-second outer
limit with CPU quota 100%, memory high/max 4/6 GiB, swap 2 GiB, nice 10,
OOM stop and whole-control-group cleanup. No live placement/replay, RTL,
original model, old evidence/gate or execution input is altered. No new
`SHA256SUMS` manifest is written.

### 2026-10-08: actual 47-bit controller/nine-control single-step proof

The [complete actual controller proof](../build/openxc7/prefix-initialization-controller-independence-1791446683425337841/report.json)
passes at **16:07:49 HKT**, under
`rknpu-prefix-initialization-controller-independence-20261008.service`, invocation
`43903b2d652c4238b13acc18610dd3bf`. It binds 688 sources and 35 artifacts,
including both completed new parents. Admission independently retraces all
**1,245 cells and 954 producers**, rejects extra/unreachable or missing records,
regenerates the exact paired miter, checks every actual register against the
47-register vendor qualification, revalidates its executed positive/negative
logs and reproduces the byte-identical selected primary-library definitions.
The complete physical input still contains 503,128 cells, all 515 DSPs and
six RAMs, with sixteen 32-product kernels. No target is shrunk or serialized.

Fresh native library qualification includes every actual LUT1/LUT2–6, carry,
INV and MUX instance, with **1,413 observed primitive output bits** per vector.
All **1,245 × 1,024 = 1,274,880 binary instance comparisons** match between
unchanged pinned vendor models and byte-identical selected synthesis models.
Every instance's binary input combinations are exhausted. The separately
executed first-vector, one-bit wrong-golden corpus is rejected; the other
1,023 vectors must remain identical. Missing/reordered vectors, X/Z, nonzero
hex padding, changed normal-finish records and diagnostic waivers are not
accepted. This is not four-state library equivalence.

| Fresh native step | Seconds |
| --- | ---: |
| Vendor compile / full corpus | 5.070 / 20.809 |
| Synthesis-library compile / full corpus | 2.744 / 7.749 |
| Executed wrong-golden corpus | 8.033 |
| Real SAT negative / positive | 44.361 / 44.204 |

The actual negative exits 1 with the exact proof-failure marker and sole
expected `-verify` error; the positive exits 0 with the exact SUCCESS marker
and no warnings. The positive SAT instance has **26,014 variables and 67,254
clauses**, and the negative 26,018 variables and 67,264 clauses. The negative
counterexample has current state `0000`, initialization phase true and equal
actual compared vectors; only the deliberate one-bit golden mutation makes
`ok` false. It is a genuine negative, not a frontend error or timeout. Both
use the original 120-second SAT and 180-second native command limits.
Four managed controls pass in 18.642 seconds and generated checks in 1.249
seconds. Actual tool revisions, pinned source and bounded unit resources are
unchanged from the completed controller parents; these exhaustive tests and
SAT have no random seed. All twelve executed commands are saved separately.

The property covers **all 47 next controller/response storage bits plus nine
actual observed controls** at one positive edge after GSR, conditional on the
shared current native four-bit state being 0, 1 or 2. The 938 other producers
are shared by construction, while the two sixteen-bit host read-data values
are independent: 970 symbolic binary inputs. No `assume`, forced state or
opaque DSP cut is inserted. This proves a larger one-step independence
property than the earlier four-bit state proof, but **does not prove a temporal
initialization sequence**, reachable producer values, future equality of the
remaining 922 register-Q producers, complete-RAM startup independence,
write-before-read, temporal port ownership or initialization completion.
Full numerical, physical/electrical/timing/DRC, bitstream and programming gates
remain open. None of those flags is promoted by this result.

A read-only revalidation at **16:10 HKT** passes all **724 source/report/artifact
bindings** and eighteen execution inputs. It independently regenerates the
complete cone, miter, selected library and 1,245-instance bench; reparses both
native corpora and the actual wrong-golden corpus; reapplies strict FDCE and
SAT validators and checks the real counterexample. All thirteen excluded
board/physical acceptance flags stay false, the production fingerprint remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`,
and no new `SHA256SUMS` exists in the three actual run directories. This is
revalidation of completed evidence, not a new native run or temporal proof.

To generate new source-bound native evidence from these same saved inputs:

```sh
python3 tools/openxc7/prove_prefix_initialization_controller_independence.py
```

This does not rebuild the live board executable, invoke P&R or program a board.
The latest whole-production `make test` result remains the archived 600-second
Verilator compile-timeout failure, not a fresh complete-suite PASS. The next
logical gate is temporal initialization/write-before-read and ownership, with
actual engine/response transitions accounted for; the one-step shared-producer
boundary cannot silently substitute for it. The original full-size placement
and mode 4 replay remain live, with four of nine replay modes complete.
No completed placed circuit, full route or test-ready bitstream exists.

The final combined new-helper control regression passes all **thirteen methods
in 33.727 seconds** with Python warnings treated as errors; the actual completed
parent bindings/native gates are checked again. Generated checks and changed
documentation local-link/whitespace checks also pass. These controls do not
replace the archived whole-production failure or supply temporal/physical
acceptance.

### 2026-10-08: actual DMA-inclusive temporal-model extraction

The [50-bit extraction and frontend checks](../build/openxc7/prefix-temporal-controller-cone-1791448312463936386/report.json)
complete at **16:38:15 HKT**, under
`rknpu-prefix-temporal-controller-cone-20261008.service`, invocation
`553601a9bd264e58b234d8aecb506156`. The source-bound report retains 728 source
entries and thirteen artifacts. A fresh complete 503,128-cell driver census
retains all 515 DSPs, six RAMs and sixteen 32-product kernels. The actual cone
now has **1,325 cells, 1,019 producer bits and fifty FDCE configurations**:
the complete earlier 47-bit demo/response controller plus the three original
DMA state bits. The actual DMA enum and translated outer reset alias are
checked against their original sources and mapped records, not inferred from
software intent. Request-valid is the tenth observed control.

The paired miter has sixty compared outputs, 1,003 shared producer values and
two independently variable sixteen-bit host-data buses. Its native frontend
check takes 45.060 seconds. The separate clocked model retains all fifty actual
FDCE D/CE/CLR/Q folds and actual combinational instances. Actual state has **no
initial assignment**; only a ghost reset observer is initialized zero. The
other **969 producer bits remain free each cycle**. Ghost logic counts actual
accepted host initialization writes and samples an arbitrary twelve-bit probe
address on reset, tracking its prefix coverage. Checking starts only after an
observed binary reset. It prepares ownership, count/index, state-bound,
prefix-coverage and write-before-core-request invariants. A second exact cone
copy recomputes clear roots after clocked Q changes. This model's native
frontend check takes 41.939 seconds; it is **not a temporal proof**.

Four preparation controls pass in 31.093 seconds in the managed run; generated
checks take 2.272 seconds. Native Yosys is 0.65, source revision
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`. Both frontends finish with no
warnings and zero reported structural problems. Each command has a 180-second
limit; the unit uses 1,800 seconds, one CPU, 4/6 GiB high/max memory, 2 GiB swap,
nice 10, OOM stop and whole-control-group cleanup. No native SAT, P&R, completed
initialization, four-state startup, numerical or physical acceptance follows
from extraction. No original live input, RTL or helper/model is changed.

To reproduce this preparation from the same completed 47-bit parent:

```sh
python3 tools/openxc7/audit_prefix_temporal_controller_cone.py
```

### 2026-10-08: actual fifty-register/cell/clear qualification

The [new actual primitive qualification](../build/openxc7/prefix-temporal-controller-primitives-1791449421248666952/report.json)
passes at **16:51:56 HKT**, under
`rknpu-prefix-temporal-controller-primitives-20261008.service`, invocation
`88a3ee10db994acb841a0395556d74d3`. It binds 743 source paths and 36 artifacts,
independently retraces the complete extracted cone and reproduces the paired
miter, clocked model and complete byte-identical selected synthesis definitions.
All fifty actual controller FDCEs retain their literal `INIT=x`, common
un-inverted clock and original parameters. The original four-bit seed/async/
next stimulus is expanded reversibly to fifty instances, preserving its
unchanged default GSR, sixteen binary tuples and finite wrong-golden negative.
The native positive checks **800 seeded Q values, 800 async results and 800
next-edge results**, finishing at exactly 752 ns. The genuine negative exits
1 at 152 ns with finite `got=0 expected=1`, not an X, timeout or frontend error.

The combinational corpus includes **all 1,325 actual instances** and observes
1,535 output bits per vector. Every instance's binary input combinations are
exhausted; all **1,325 × 1,024 = 1,356,800 vendor-versus-synthesis comparisons**
match. A separately executed first-vector, one-bit wrong-golden mutation is
rejected, with the other 1,023 vectors required to remain identical. Original
whole vendor sources, license and `glbl` are pinned to UNISIM revision
`1c8e05fd1e9a79ceb8b996a0996674122eed086f`; native Icarus/VVP is 13.0 stable.
No primitive function, INIT, missing vector, diagnostic or display padding is
repaired or waived. This is explicitly **binary**, not four-state library
equivalence.

The saved [actual clear-root certificate](../build/openxc7/prefix-temporal-controller-primitives-1791449421248666952/actual-async-clear-fixed-point.json)
traces every actual CLR driver, rejects unknown/cyclic dependencies and
exhausts **32 reset/demo-state combinations across all fifty roots**: 1,600
comparisons. All 44 demo clears depend only on reset and equal `!reset_n`.
The six response/DMA clears depend only on reset and the four demo state bits,
equaling `!reset_n || demo_state==10`. Clearing the demo state cannot trigger
another demo-state-dependent clear cycle, and the remaining six registers
cannot change their own clear conditions. Thus one post-edge clear application
is a fixed point in this binary edge abstraction. Between-edge reset pulses
and four-state clear behavior remain outside this certificate.

Native FDCE compile/negative/positive take 0.251/0.199/0.415 seconds. Vendor
compile/corpus take 5.792/24.362 seconds; synthesis-library compile/corpus
3.252/8.588 seconds; the executed wrong-golden corpus takes 9.252 seconds.
Six managed controls pass in 15.775 seconds and generated checks in 1.475
seconds. Native and unit resource limits are the same as the preparation
above. The production fingerprint stays
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
Temporal/full-board/physical acceptance flags remain false; no old failure
or old gate is relabeled and no standalone `SHA256SUMS` is created.

Before native execution, two draft controls incorrectly counted source paths
without resolving a duplicated Yosys library symlink. The final control now
requires the exact resolved source/artifact/report path union used by the
unchanged admission function; no digest, model or acceptance gate is removed.
The final six local controls pass in 14.375 seconds before the managed run.

To reproduce the actual native qualification from its saved extraction:

```sh
python3 tools/openxc7/qualify_prefix_temporal_controller_primitives.py
```

No temporal SAT is claimed by this qualification. The original full-size
strict placement and mode 4 full mapped replay continue independently; four
of nine replay modes are complete. There is still no completed placement,
route, physical signoff or bitstream ready to test.

### 2026-10-08: preserve first temporal WaveJSON parser failure

The [first actual temporal attempt](../build/openxc7/prefix-binary-temporal-ownership-1791449841446876666/report.json)
finishes **FAIL at 16:59:24 HKT**, under
`rknpu-prefix-binary-temporal-ownership-20261008.service`, invocation
`f8ca961f7f0f4f9193ad3e5035ce8d58`. It binds 782 sources and eleven artifacts.
The native wrong-golden base case completes in 59.820 seconds with the exact
expected failure marker and sole `-verify` error. Its finite table shows a
sampled reset at step 1, followed by `seen_reset=1`, `reset_n=1`, actual `safe=1`
and wrong-golden `ok=0` at step 2. No source-level safety failure, frontend
failure, timeout or native warning caused this negative.

The outer validator then raises
`AssertionError('Changed native WaveJSON trace signals')`: it incorrectly
expected only explicitly shown signals and a trailing fourth frame. Native
Yosys emits the literal initial actual `storage_state` too, with **three
frames: initial, step 1 and step 2**. Vector data includes explicit empty
initial frames and sparse repeats. The overall report stays FAIL, and the
positive never runs in this attempt. No temporal flag is promoted.

The separate
[WaveJSON continuation source](../tools/openxc7/resume_wavejson_prefix_binary_temporal_ownership.py)
reproduces and binds that exact failed report. It preserves the original
clocked model, native script, sixteen-tuple FDCE goldens, limits and all
numeric negative/diagnostic requirements. It decodes every native vector,
scalar, blank frame and repeat strictly, rejects unknown/wrong-width/unused
data or extra signals, and cross-checks every step and initial value against
the native table. Only the ghost reset observer may have an initial-value
constraint; the actual fifty-bit initial state remains arbitrary binary data.
Four local controls pass in 67.208 seconds. A pre-native draft control in the
first helper had guessed whitespace in a fabricated trace row; its final
control constructs exact row formatting and passes in 24.742 seconds. Neither
control fix changes actual state, a property, native failure expectations or
hardware execution input.

The fresh managed continuation is
`rknpu-prefix-binary-temporal-ownership-wavejson-20261008.service`, invocation
`6d647ad6b5224155873865848cf66e5a`. It uses the same one-CPU, 4/6 GiB high/max
memory, 2 GiB swap, nice 10, OOM-stop, control-group cleanup and 1,800-second
outer limit. Each native command retains 180 seconds and the SAT instance
120 seconds. No original executed helper or artifact is edited.

### 2026-10-08: fresh isolated whole-production regression

The [new source-identical production run](../build/source-identical-production-regression/1791450268992775192/report.json)
starts at **17:04:28 HKT**, under
`rknpu-source-identical-production-regression-20261008.service`, invocation
`53d5ac7dfd37431bb50792d05d28d915`. Its reusable
[isolated runner](../tools/openxc7/run_source_identical_production_regression.py)
copies all **101 declared production source files** and all four complete
existing stimulus directories, without modifying live replay/mapping input.
It binds 756 original source/tool/stimulus paths and 749 private execution
inputs. Every copied source and fixture digest must match before and after.
The production fingerprint is unchanged.

The literal command in the fresh private workspace is:

```sh
make -j2 -o vectors -o cmac-vectors test
```

Only regeneration prerequisites are held because the complete stimuli are
frozen; **all original model, lint, native RTL, four-state RTL and product test
targets execute**. Their goldens, seeds, warning policies and per-command
timeouts are unchanged. The outer command has 7,200 seconds and the managed
unit 7,800 seconds, two CPUs, 6/8 GiB high/max memory, 2 GiB swap, nice 10,
OOM stop and whole-control-group cleanup. Exit status alone cannot establish
a PASS: the runner also requires the exact source-bound C++ numeric, Verilator
RTL, Icarus RTL and two product reports, with all native commands and tests
complete. No experimental full CMAC/mapped board or physical FPGA pass follows
from this production suite.

At **17:07 HKT**, 49 model controls and **1,087,299 C++ numerical comparisons**
pass; native/four-state RTL simulations are still running. That is partial
progress, not a whole-suite PASS. The archived previous 600-second Verilator
compile-timeout report remains FAIL and is not overwritten or copied forward.
No standalone `SHA256SUMS` is created.

To launch another isolated source-bound complete production attempt:

```sh
python3 tools/openxc7/run_source_identical_production_regression.py
```

### 2026-10-08: actual binary sampled-reset temporal safety proof

The [fresh source-bound temporal continuation](../build/openxc7/prefix-binary-temporal-ownership-wavejson-1791450218791135300/report.json)
passes at **17:09:41 HKT**, binding **796 source paths and thirteen artifacts**.
It uses the unchanged actual fifty-bit clocked model and independently
revalidates every completed actual-cell/FDCE/clear parent, both native library
corpora and their real negatives. The first WaveJSON-parser attempt remains
FAIL; this report neither edits nor relabels it. The native positive has no
warnings, exits 0, emits no counterexample and proves both the base case and
**induction at length 1**. The native base and induction SAT instances each
have **204,275 variables and 547,253 clauses**, importing 6,309 lowered cells
per step. Full original target/source identity is unchanged.

The native negative exits 1 with the exact expected base-case failure and sole
`-verify` error, importing 6,310 lowered cells; it has 204,299 variables and
547,313 clauses. The independently cross-checked finite table and WaveJSON
show actual reset at step 1, followed at step 2 by `seen_reset=1`, `reset_n=1`,
actual `safe=1` and wrong-golden `ok=0`. The actual demo/DMA states, write count
and probe-written flag are zero, with no accepted host/core/request fire.
The arbitrary probe changes from initial zero to reset-sampled address 2,567.
Only the property golden is deliberately inverted; this is not a frontend
error, timeout or failure of actual safety. The native initial actual storage
value is retained, not replaced by zero.

Four managed controls pass in **88.152 seconds**, generated checks take
1.888 seconds and fresh native negative/positive **80.523/103.057 seconds**.
Actual Yosys is 0.65, revision
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`, with its native MiniSAT solver.
The exact script uses `-seq 1 -tempinduct-def -maxsteps 4 -set-def-inputs
-set-init-def -verify -prove ok 1 -timeout 120`; all base and induction steps
execute with no skip, `assume`, value forcing, unknown-cell ignore or X-match
proof. `dffunmap` lowers synchronous reset/enable into exact input muxes,
without introducing a new async-reset model or changing transition functions.
These exhaustive/formal runs have no random seed. Native and unit limits
remain those recorded above.

The proved strengthened conjunction establishes, **after an observed sampled
binary reset**, the following properties of the actual-controller abstraction:

- The count is at most 4,096; initialization address/response phases have the
  exact count/index relation and post-initialization normal states have 4,096
  accepted host writes.
- The arbitrary reset-sampled probe is marked written exactly when its address
  is below that count, proving prefix coverage for any of the 4,096 addresses.
- Demo/DMA state bounds hold, and the DMA owns no active state outside demo RUN.
- Host/core accepted fires never overlap, and an actual core request-valid
  requires the complete 4,096-write initialization prefix.

All 969 other producer bits are free at every step; no shared arithmetic-state
reachability premise or future producer equality is inserted. Actual initial
controller state is arbitrary **binary** data, and only ghost `seen_reset`
starts zero. These are unbounded discrete-positive-edge safety properties
of the admitted binary model, not merely finite simulation traces.

This result **does not prove four-state startup**, between-edge reset pulses,
initialization liveness/completion under all arbitrary producer values,
physical RAM data retention, full mapped numerical acceptance, FPGA fit,
electrical/timing/DRC signoff or RK3588 silicon behavior. The broader temporal
port/write-before-read/full-startup flags deliberately remain false; only the
explicitly scoped binary-model ownership, prefix-write-before-core-request
and arbitrary-probe coverage flags become true. No emitter gate is waived,
no hardware execution input is modified and no standalone `SHA256SUMS` is
created. The unchanged production fingerprint is
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.

To run fresh actual evidence while preserving the first failed attempt:

```sh
python3 tools/openxc7/resume_wavejson_prefix_binary_temporal_ownership.py
```

At completion, full-size strict placement and mode 4 mapped numerical replay
remain live, with four of nine replay modes complete. The fresh isolated
production regression is also running; no whole-suite PASS is inferred from
its partial controls/model/RTL results. No completed placement, full route
or bitstream ready to test exists.

A read-only completed-proof revalidation at **17:13 HKT** passes all **810
source/report/artifact bindings and five execution inputs**. It independently
recreates the actual cone/model/library/clear certificate, reparses the native
FDCE and combinational corpora and their negatives, checks both literal SAT
scripts, reapplies the strict induction validators and cross-checks the real
negative waveform/table. The four scoped binary safety flags remain true and
all fifteen broader excluded flags false. Production identity stays unchanged.
This is revalidation, not another native proof or physical acceptance.
Changed-source syntax, documentation links/whitespace and generated checks
pass. No standalone `SHA256SUMS` exists in any of the five new actual run
directories, including the isolated production workspace.

### 2026-10-08: unchanged fresh production suite ends FAIL

The [isolated whole-production attempt](../build/source-identical-production-regression/1791450268992775192/report.json)
finishes **FAIL at 17:44:51 HKT**, after the literal make command returns 2
in **2,416.208 seconds**. The source fingerprint and all 749 private execution
inputs remain identical. A read-only revalidation checks all **2,800 bound
source/report/artifact paths**, not merely the runner's exit status.

Both the [fresh Verilator EW suite](../build/source-identical-production-regression/1791450268992775192/source_identical_workspace/build/rtl/report.json)
and [fresh Icarus EW suite](../build/source-identical-production-regression/1791450268992775192/source_identical_workspace/build/iverilog/report.json)
complete **247 tests and 261 native commands each**, with every command and
test passing. The numeric reference completes **1,087,299 comparisons** with
seed `0x3588`. These are their own completed results, not a whole-suite PASS.

The [fresh Verilator product report](../build/source-identical-production-regression/1791450268992775192/source_identical_workspace/build/cmac_verilator/report.json)
remains FAIL: `tb_fp16_product` passes 230,433 comparisons, four reset cases
and seed `3588ca04`; `tb_cmac_operand_front` passes 53,297 operands with seed
`3588ca03`. The `tb_cmac_product_front` native build hits its original
**600-second limit in 600.068 seconds**. Actual tool is Verilator 5.048,
2026-04-26, revision `vUNKNOWN-built20260426`. Its warning policy, golden,
sources, `-j 2` build flags and per-command limit are unchanged. The make
failure prevents the CMAC Icarus target from starting; it has no report.
Neither this failure nor the archived earlier compile-timeout failure is
relabelled. C++ and these HDL tests do not validate the experimental mapped
C32/K16 full board, physical FPGA or RK silicon. No new `SHA256SUMS` is created.

### 2026-10-08: exact-board archive cannot supply configuration signoff

The [source-bound historical reference audit](../build/openxc7/ypcb-configuration-reference-archive-1791453077631362251/report.json)
reads only four exact text members of the existing
`/home/fedora/ypcb/ref/LC480T/YPCB-00338-1P1/XC7K480T_XDMA_Test.zip`, preserving
the original archive. Its [reusable read-only extractor](../tools/openxc7/audit_ypcb_configuration_reference_archive.py)
binds the archive, source and native extraction executable in JSON, saves the
literal extracted texts and verifies their contracts. Four software controls
pass; they test the checker and are not board evidence. Native extraction
uses `7z e -so`, returns 0 with empty stderr for each selected member and has
a 60-second per-command limit. The actual extractor reports **7-Zip 26.03
(x64), 2026-09-03**; its executable is digest-bound. No whole reference project is extracted,
no archived binary is executed and no card/JTAG/flash access occurs.

The historical log identifies **Vivado 2022.1.2** and the exact part
**xc7k480tffg1156-2**. Both its log and routed DRC report explicitly record
`CFGBVS-1`: neither CFGBVS nor CONFIG_VOLTAGE is set. Its placed I/O report
lists Bank 0 VCCO as **`any**`**, not a measured board supply, on package pins
G14/H13; CFGBVS is package pin AL15, with no recorded physical strap value.
The user XDC has no configuration-property assignment. This is evidence of
missing reference information, not authority to choose a voltage or strap.

The same archived log records a **Timing 38-282 critical warning** that its
design failed timing, followed by a successful historical bitgen. Consequently
the old reference bitstream cannot be treated as electrical/timing signoff for
this design, and successful historical emission is not a gate waiver here.
Actual Bank 0 voltage and CFGBVS strap remain unverified; the nonblocking
request for a schematic/photo/documentation remains outstanding. Full-size
placement and mapped replay continue without changing their inputs. All
electrical, timing, DRC, emission and hardware-programming flags remain false.
Generated checks pass; no standalone `SHA256SUMS` is created.

To reproduce only this bounded reference inspection:

```sh
python3 tools/openxc7/audit_ypcb_configuration_reference_archive.py
```

### 2026-10-08: expanded actual BRAM pin cone and preserved frontend failure

The [fresh actual BRAM barrier attempt](../build/openxc7/prefix-actual-bram-barrier-1791452093147189951/report.json)
finishes **FAIL at 17:49:52 HKT**, with **812 source bindings, 38 artifacts
and 21 execution inputs**. It independently revalidates the completed binary
controller and literal six-BRAM wiring/control parents, then freshly censuses
the full 503,128-cell input. The cone adds exactly three actual cells:
`rk_mapped_cell_49970` (request-write LUT3), `rk_mapped_cell_50664` (host-write
LUT2) and `rk_mapped_cell_50665` (core-write LUT6). All original 1,325 cells,
fifty controller registers and 1,019 producer cuts remain unchanged; no new
free producer is introduced. Actual census/extraction takes **439.117 seconds**.

Fresh qualification completes **1,328 × 1,024 = 1,359,872 binary comparisons**
over 1,538 consumed combinational output bits, using unchanged pinned vendor
models and complete synthesis definitions. The actual executed one-bit wrong
corpus is rejected with all other 1,023 vectors unchanged. The actual
initialization miter compares **all fifty next-register bits plus fourteen
controls**, including physical BRAM enable/write pins. Its native negative
and positive complete in **50.518/49.025 seconds**. The real negative has
finite equal compared vectors in initialization state zero, with only the
property golden inverted. Thus this *completed subproof* establishes binary
one-step host-data independence in states 0–2; it is not temporal acceptance
of the whole failed attempt.

The clocked attempt counts initialization writes from physical A enable/WE,
with the literal actual index as word address. It adds physical accepted-write
equivalence, port exclusivity and a read barrier to the unchanged fifty-bit
controller model. Its native temporal negative exits 1 in **65.097 seconds**
with only `Failed to parse show expression bram_core_we`: the core-write alias
is not yet used in a property and is removed by native optimization. There is
**no safety counterexample or successful temporal negative**. The unchanged
strict validator rejects this frontend error, and no positive executes. The
run, model, scripts and logs remain unchanged and FAIL; all temporal/barrier
acceptance flags remain false. Four managed software controls pass in
107.804 seconds and generated checks in 2.412 seconds; neither overrides the
actual failure. The complete original C32/K16, 512-product target is retained.

The [separate core-write continuation](../tools/openxc7/resume_prefix_actual_bram_barrier_core_write.py)
revalidates this frozen failure and the completed actual library/initialization
subproofs. A new test-only model adds the *stronger* conjunction that effective
physical port B writes equal actual core-fire AND actual request-write. It
does not keep a dummy wire or ignore the missing trace. All fifty actual
register folds, asynchronous-clear rules, producer cuts and ghost updates
are unchanged. The exact native SAT flags, strict negative/induction/waveform
validators, 120-second SAT and 180-second command limits remain unchanged.
Four preflight controls pass in **123.562 seconds** and generated checks pass.
Fresh native negative/positive execution is started in a separately bounded
managed unit; no continuation PASS is inferred from these controls.

The [actual managed continuation report](../build/openxc7/prefix-actual-bram-core-write-1791453537307521260/report.json)
starts **17:58:57 HKT** in
`rknpu-prefix-actual-bram-core-write-20261008.service`, invocation
`d0b24e53655f440dbeb3421f0882122f`. The unit retains one CPU, 4/6 GiB high/max
memory, 2 GiB swap, nice 10, OOM stop, whole-control-group cleanup, zero core
size and a 1,800-second outer limit. Its own four controls pass in **121.409
seconds** and generated checks in **2.014 seconds** before fresh native proof.
The report records no random seed because these are exhaustive/formal tests.
No model qualifier log is copied forward as a new run: completed native
initialization/library results are explicitly inherited through the bound
failed-parent report, and the temporal commands execute freshly.

To execute fresh continuation evidence while preserving the first failure:

```sh
python3 tools/openxc7/resume_prefix_actual_bram_barrier_core_write.py
```

The read barrier concerns *sensitive reads*: READ_FIRST old-data output on
initialization host writes still exists, and the binary initialization miter
checks its lack of effect on the compared controller outputs. These results
do not prove four-state full-board startup, RAM data-value independence,
between-edge reset pulses, liveness, full mapped numerical acceptance,
electrical/timing/DRC signoff or a test-ready bitstream. No original input,
model or hardware gate is repaired, no FPGA/flash is programmed and no new
standalone `SHA256SUMS` is created.

### 2026-10-08: strengthened actual BRAM pin proof completes

The [actual core-write continuation](../build/openxc7/prefix-actual-bram-core-write-1791453537307521260/report.json)
passes at **18:05:37 HKT**, with **853 source bindings, twelve artifacts and
five execution inputs**. Its native positive exits 0 without warnings,
proving both the base case and **induction at length 1**. The base and
induction instances each have **205,169 variables, 549,691 clauses and 6,339
lowered cells per step**. No positive counterexample exists. The managed
unit finishes successfully; no native proof limit, strict validator, old
failure, production source or actual hardware input is changed.

The fresh native negative exits 1 with the sole expected `-verify` failure,
6,340 lowered cells, 205,193 variables and 549,751 clauses. Its finite table
and native three-frame WaveJSON agree on every shown value and the actual
fifty-bit initial storage value **65,520**, which is not forced to zero.
At step 1, sampled reset is asserted; at step 2, `seen_reset=1`, reset is
released, actual `safe=1` and deliberately inverted `ok=0`. Demo/DMA states,
write count and accepted enables/writes are zero; the arbitrary probe is
address **4,095**. The previously missing core-write signal is now a genuine
property dependency and appears in the finite trace. Native negative/positive
take **59.794/69.189 seconds**, with actual Yosys 0.65, revision
`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`, and its native MiniSAT solver.

All fifty actual state transitions, post-edge clear folds, 1,019 producer
cuts, original ghost updates and full C32/K16 512-product target are retained.
The unchanged 969 unowned producer bits remain free at every step. The
stronger conjunction proves, **only after an observed sampled binary reset**:

- Accepted physical port A writes match actual host-fire/write events; the
  counter and arbitrary probe track physical A writes at the literal index.
- Physical port A and B enables never overlap.
- A sensitive A read or any B access requires all 4,096 initialization writes
  and arbitrary-probe coverage. READ_FIRST old data on A writes is not called
  a sensitive read; the bound completed initialization miter proves one-step
  binary controller independence from that host read data in states 0–2.
- Effective physical B writes equal actual core-fire AND actual request-write.

The four explicitly scoped binary physical-pin/initialization flags become
true. All sixteen broader excluded flags remain false, including four-state
startup, between-edge reset pulses, liveness, RAM data-value independence,
full numerical acceptance, physical fit, electrical/timing/DRC signoff,
bitstream emission, input modification and hardware programming. The first
BRAM attempt remains FAIL and its completed qualification/initialization
subproofs are inherited by binding, not copied as newly executed evidence.
Full-size placement and mode 4 mapped replay remain live; no placement,
full route or test-ready bitstream exists. No standalone `SHA256SUMS` is created.

At **18:09:55 HKT**, read-only completed-proof revalidation passes all **866
source/report/artifact bindings and five execution inputs**. It independently
recreates the strengthened model/library, rechecks the completed actual
primitive and initialization parents, checks both literal native SAT scripts,
reapplies the unchanged strict validators and cross-checks the finite negative
WaveJSON/table. All four scoped flags are true and all sixteen excluded flags
false. The original production fingerprint remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
Four changed Python files pass syntax/whitespace checks, changed documentation
links pass and generated sources match. This revalidation is not another
native proof or physical acceptance. The fresh whole-production make attempt
remains FAIL at its unchanged compile limit, and no new standalone checksum
manifest is created.

### 2026-10-08: actual reset/controller startup fixture starts

The [new selected-controller vendor fixture](../build/openxc7/prefix-actual-reset-startup-1791455659250174969/report.json)
starts at **18:34 HKT** in
`rknpu-prefix-actual-reset-startup-20261008.service`, invocation
`2864500a584f4af3b4adaff8a24e5b38`. All four preflight host controls pass in
158.125 seconds, including revalidation of the completed physical-pin binary
proof. Generated checks and Python syntax/whitespace checks pass. This is
launch evidence, not a completed native qualification.

The new helper preserves every original 1,328 combinational controller cell
and all fifty literal unknown-INIT FDCEs. Read-only full-input inspection finds
three additional zero-INIT FDCEs at physical Q wires 91,958, 91,957 and 15,190,
and three distinct clear inverters, all driven by the same buffered external
reset wire 9. The helper freshly censuses and traces the full 503,128-cell
input before emitting a test-only controller fixture. It does not change
the full C32/K16, sixteen-kernel, 512-product physical target.

The fixture uses literal vendor primitives and default 100 ns GSR, with the
remaining producer inputs held X. It targets cold startup, two complete
4,096-write prefixes, and asynchronous resets after a complete prefix, after
one accepted write and after 2,048 accepted writes. It must first reject a
finite wrong reset-chain golden before the positive may pass. The clock/reset
fixture boundary is the mapped buffer output, not an IO/electrical model.
The write monitor compares the accepted physical enable/WE wires with the
logical demo index, not RAM contents or physical address translation with X
producers. No physical RAM, core arithmetic or full-board startup independence
follows.

The managed run retains 180-second native command limits, an 1,800-second
outer limit, one CPU, 4/6 GiB memory-high/max, 2 GiB swap maximum, nice 10,
OOM stop, whole-control-group termination and disabled core dumps. The live
full placement and mode 4 replay are unchanged. No new standalone
`SHA256SUMS` is written. All startup/physical acceptance flags remain false
while the native run is pending.

### 2026-10-08: local openTPU configuration corroboration is not strap proof

At **18:40 HKT**, read-only inspection of
`/home/fedora/ypcb_ref/openTPU` at revision
`5b1e646cdec9de449ba416952ec854b0b2d973d7` finds clean versions of
`boards/ypcb-00338/constraints/otpu_top_ld.xdc` and `docs/board.md`.
The XDC lines 82–83 select `CFGBVS GND` and `CONFIG_VOLTAGE 1.8`.
Git blame attributes that configuration to `1494dccd` on 2026-09-29.
The board checklist line 1345 repeats GND/1.8 V; its section is explicitly
headed “assumptions made without Vivado” and the claim originated in
`65a65706` on 2026-09-23. Neither file supplies a Bank 0 measurement,
CFGBVS strap photograph or schematic connection. These donor choices
corroborate a candidate setting, but do not satisfy this design's physical
electrical gate. No donor file, current constraint, live job or emission
requirement is modified.

### 2026-10-08: actual startup fixture FAIL and read-only failure replay

The [startup fixture](../build/openxc7/prefix-actual-reset-startup-1791455659250174969/report.json)
finishes **FAIL at 18:43:18 HKT**, with 870 source bindings, 27 artifacts and
fifteen execution inputs. Its fresh full 503,128-cell census and strict trace
take 210.626 seconds and retain **1,331 combinational cells, 53 actual FDCEs
and 968 unknown producers**. Managed host controls pass in 147.542 seconds;
generated checks and actual Icarus compiler/runtime 13.0 versions are recorded.
The actual vendor compile exits 0 without warnings in 6.302 seconds.

The deliberately wrong reset golden is genuinely rejected at **102 ns**:
actual reset chain `000`, wrong expected `100`. This finite native negative
takes 5.151 seconds. The positive exits 1 in 4.412 seconds, at **172 ns**:
`unknown actual controller state after default GSR state=1010 index=000000000000`.
No complete initialization prefix is reached, and every startup/physical
acceptance flag remains false. The managed unit terminates with exit status 1.
No source, model, original expectation or native limit is repaired for green.

The separately compiled
[read-only observer replay](../build/openxc7/failed-reset-readonly-trace-1791456691562076912/report.json)
finishes at **18:51:41 HKT**. It binds 32 immediate failed-bundle/tool/source
paths, seventeen execution inputs and five artifacts. It uses all the frozen
original module, bench and vendor-model inputs and adds only a supplementary
root which reads/prints at clock+1 ns. It has no assignment, force, deposit,
initialization, replacement golden or acceptance bypass. Native compile/replay
take **4.718/4.046 seconds**. The replay returns the same original sole fatal,
unchanged final native text and **172 ns** failure time, with nine trace rows.

At 111/131/151 ns the reset chain is `001/011/111` and selected controller
storage is zero. At 151 ns, demo state is `0000` but its next-state pins are
`1010`; at 171 ns it is in FAILED (`1010`) and its eight error-code storage
bits are X. The remaining tracked storage is known. The fixture's engine fault
cut is X and eight saved-code cuts are X in every trace row. Literal alias
inspection identifies fault Q wire 50,677 (`rk_mapped_cell_65539`, unknown-INIT
FDCE) as free producer bit 778; the actual DMA RTL resets that fault and its
saved code, but this selected fixture does not instantiate their transitions.
The trace supports a boundary/reachability investigation, not a claim that
the production RTL is faulty or that reset alone establishes independence
from arbitrary unknown engine state.

Immediate original inputs, native logs and report artifacts are revalidated;
the full upstream proof chain is explicitly **not** revalidated by this
observer. The current production fingerprint equals the original recorded
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
The original startup failure remains unchanged, and observer startup,
electrical/timing/DRC, bitstream and programming flags stay false. Further
startup work needs the actual relevant error/reset control paths, not forced
zero values for unowned producers. Full-size placement and mode 4 replay
remain live. No standalone `SHA256SUMS` is created.

### 2026-10-08: qualify HeAP as a full-target placement alternative

At **19:08 HKT**, the
[native HeAP procedure qualifier](../build/openxc7/native-heap-qualification-1791457692353795739/report.json)
starts in `rknpu-native-heap-qualification-20261008.service`, invocation
`ffef9a7fc1c54c2396d1d7cd29aaa4df`. Its four host controls pass in 0.012 seconds.
This is only launch/preflight evidence. No native HeAP result or full-size
HeAP placement is yet claimed.

The helper first revalidates the completed bounded-static qualification and
frozen corrected engine. Fresh small commands change only `--placer static`
to `--placer heap`, preserving the original illegal pair, positive LUT/carry
fixtures, counter fixture and four-DSP/six-BRAM P&R/FASM input. Part, clock,
seeds, warning policy and normal refinement remain unchanged. The source-defined
architecture default HeAP beta is 0.5, not an explicit capacity/clock override.
The invalid forced pair must return a genuine native validity rejection before
postPlace; crashes, unrelated errors and unsafe continuation are not accepted.
Three positive placements, all 1,024 LUT comparisons and the same four-DSP/
six-BRAM feature expectations are required before qualification may pass.

The original full-size static placement and mode 4 replay remain running with
their original handles and inputs. This alternative does not reduce C32/K16,
sixteen kernels or 512 simultaneous products, nor does it substitute a smaller
hardware design. The native qualification has 600-second control limits and
a 3,600-second small P&R limit; its managed outer limit is 5,000 seconds, with
one CPU, 4/6 GiB memory-high/max, 2 GiB swap maximum, nice 10, OOM stop and
disabled core dumps. No original engine, fixture, check, constraint, global
tool pointer or live job is altered, and no checksum manifest is written.

Fresh source inspection also confirms that the frozen engine selects the
`DEFAULT` timing grade regardless of the part's -2 suffix. Its inherited
generic port classifier returns `TMG_IGNORE` for a missing timing index; the
bound binary database still has no DSP timing type. HeAP qualification or a
future routed Fmax therefore cannot close exact -2/DSP timing signoff.

At **19:11:04 HKT**, the first HeAP procedure is actually **FAIL**, not qualified.
The original illegal pair returns native code 125 in 50.597 seconds, with the
sole error naming `captured_pair_lut1` at
`X160Y206/SLICE_X0Y0.A6LUT`, followed by `0 warnings, 1 error`. No placed output,
analytic-placement banner, refinement or postPlace follows. The harness instead
fails its expectation of a newer beta log message, which the frozen executable
does not contain. Its helper, control, logs and report are preserved unchanged;
no positive native placement or DSP/BRAM routing ran in this first procedure.

The bound `HeAP::place_constraints` source validates constrained BELs and throws
that exact error **before** creating initial analytic placement. Read-only native
symbol/disassembly inspection also finds a direct binary32 `0x3f000000` store at
offset four of the configuration reference, whose unchanged ABI header begins
`float alpha, beta;`. This is an observed literal beta=0.5 setter, not proof of
all compiled semantics, a runtime timing measurement or physical signoff.

At **19:24 HKT**, the
[early-constraint continuation](../build/openxc7/native-heap-early-constraints-1791458660562002118/report.json)
starts in `rknpu-native-heap-early-constraints-20261008.service`, invocation
`dda2358dcb7448ef89aa88e706794134`. Four new host controls pass in 0.153 seconds.
It first revalidates the frozen parent and original failure, then records
versioned `nm -S -C` and complete getter `objdump` evidence. It requires the
exact sole early native rejection, rejects crashes and any continuation, and
retains all original positive placement, refinement, 1,024 LUT-comparison and
four-DSP/six-BRAM P&R/FASM gates and time limits. The failed original checker
must still reject its own saved log. This continuation changes neither the
original fixture nor the engine and is not yet a qualification result. Full
static placement and the original mapped replay remain running; no standalone
checksum manifest or bitstream is created.

At **19:27:36 HKT**, that first early-constraint continuation is actually
**FAIL** before any fresh native placement. Parent/source admission succeeds;
GNU `nm` and `objdump` version commands pass. The 5,270-line `nm -S -C` census
returns zero in 0.745 seconds, but the generic diagnostic regex matches three
valid `W boost::program_options::error::~error()` symbol entries. The complete
getter disassembly has not yet run in this procedure. Its source, test, saved
symbol table and FAIL report are frozen unchanged, with all broad flags false.

At **19:30 HKT**, a
[typed-inspection procedure](../build/openxc7/native-heap-typed-inspection-1791459029556778888/report.json)
starts in `rknpu-native-heap-typed-inspection-20261008.service`, invocation
`827176e3a3c84a6fba18c04ddb8f4d17`. Four host controls pass in 1.844 seconds.
This separate procedure admits that exact failure and parses **every** symbol
line as address/optional size/type/name data; any diagnostic, unknown line,
missing getter or nonzero tool exit remains a failure. Only the symbol-census
data parser and output directory differ from the frozen previous procedure.
All actual native warning/error, early illegal-pair, positive placement,
refinement, truth-table, DSP/BRAM feature and original time/resource gates remain
literal. Qualification is still pending, not native or physical acceptance.

Two full-target handoffs are now prepared, not executed:

- `tools/openxc7/place_native_heap_board.py` passes six host controls (0.097 s).
  It admits only the completed typed native qualification, repacks the same
  original physical input and keeps C32/K16, sixteen kernels, 512 parallel
  products, exact -2 part, 50 MHz, seed 3588, 43,200-second native limit,
  normal refinement, unique BELs and all 538,118 primitive-membership checks.
  Its source is exactly reversible to the bounded-static runner except for
  the algorithm, native completion evidence and distinct output/status fields.
- `tools/openxc7/route_native_heap_board.py` passes twenty-four host controls
  (3.309 s), including every original v2/static route error/identity control.
  It requires a completed full HeAP placement and independently reads its
  actual native completion/argv/input evidence. It preserves the v2 literal
  checkpoint, imported BEL/pair/carry scan, normal router connectivity, complete
  physical/logical identity and all 515-DSP/six-BRAM feature checks. The shared
  corrected-DSP base build is read from its already-bound static parent; no
  engine metadata or failed report is rewritten. Native replacement/repacking
  during checkpoint routing remains forbidden. No full route is claimed.

Fresh `make generated-check` passes. The source-identical production regression
remains the earlier actual FAIL on its unchanged 600-second Verilator compilation
limit, not an all-green regression. Production identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
No RTL, encoder, target, live original job or standalone `SHA256SUMS` is changed.

At **19:44:07 HKT**, the typed-inspection procedure is actually **FAIL** at
`small_heap_native_PNR_FASM`. All twelve command executions finish with their
expected codes. The exact early native rejection passes in 54.543 seconds;
forced-valid, free and counter placements pass in 77.498, 90.463 and 89.890
seconds, including normal refinement/postPlace and all 1,024 LUT comparisons.
The unchanged 286-cell four-DSP/six-BRAM native P&R command returns zero in
259.754 seconds, runs the router1 legality check and finishes normally.
GNU nm/objdump are **2.46.1-1.fc44**; the frozen native executable reports
`Version c68c135`. The complete 946-byte getter records the literal beta=0.5
store, not full binary semantics or physical timing proof.

The strict feature comparison then rejects
`HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0`, repeated at FASM lines
**9060 and 9061**. Its 7,875 nonempty feature lines have 7,869 distinct strings:
five already-modeled two-line I/O STEPDOWN repetitions and this single new
two-line clock repetition. DSP/BRAM feature comparison has **not** passed, so
the qualification remains FAIL with 3,455 source bindings and twenty artifacts;
no full HeAP placement or route is admitted. The original parser and this
failed procedure/report are not changed to accept the unexpected feature.

Read-only source diagnosis identifies the actual compiled corrected emitter
at `dsp-constant-engine-1791414105309267504/himbaechel/uarch/xilinx/fasm.cc`.
`used_wires_starting_with` appends one source wire per routed PIP to a vector;
`write_clocking` emits an ENABLE_BUFFER flag for every returned regional source
without deduplicating that vector. Thus shared clock fanout can repeat a feature.
The current Kintex database has the matching
`HCLK_R.ENABLE_BUFFER.HCLK_CK_BUFHCLK0 00_14` row. These are source/format clues,
not clock, electrical or physical-bitstream acceptance: the row and routed
source/fanout evidence still need binding and a narrowly scoped repetition
contract with conflict/unknown-feature tests before support is added.

Fresh combined `test_native_heap_*control.py` runs **42 controls in 5.343 s**,
all PASS. AST parsing and whitespace checks pass for the eight new/continuation
Python files. This does not turn the native qualification's feature failure
green or supersede the earlier production `make test` failure. At **19:48 HKT**,
original full static placement PID 1344200 and mode 4 replay PID 1373401 remain
live (8h16m and 5h15m elapsed). Production identity is unchanged; timing,
electrical/DRC, bitstream and programming gates remain open. No new checksum
manifest or bitstream is created.

### 2026-10-08: source-bound clock fanout qualification and full HeAP launch

At **20:11:38 HKT**, the separate
[read-only clock-feature qualification](../build/openxc7/native-heap-clock-features-1791461172554993544/report.json)
completes with status
`QUALIFIED_SOURCE_BOUND_SAVED_NATIVE_HEAP_AND_CLOCK_FANOUT_DSP_BRAM_FEATURES_NOT_FULL_FIT_OR_SIGNOFF`.
It runs in `rknpu-native-heap-clock-features-20261008.service`, invocation
`43ac51e033564841ab9a2d372c645324`, supervisor PID 1416686. It **does not rerun
native P&R** or copy its old logs forward as new execution. It freshly rebinds
the preserved typed-inspection FAIL, all twelve completed original commands,
actual outputs, native executable and source parents. The old FAIL and original
strict parser must still reject their original repeated-clock input.

`clock_bound_native_features.py` now binds the actual compiled corrected emitter,
48-byte wire and 24-byte PIP database ABI, native PIP/physical-tile naming and
routing-property serialization, exact XC7K480T database/constant IDs, both Kintex
HCLK segbits files, and the actual F4PGA FASM merge function and model types.
The supported profile is ordinary HCLK_R BUFHCLK0..7 and HCLK_L BUFHCLK8..11.
Every enable must be a bare positive Boolean flag and have exactly the number
of emissions justified by distinct actual source PIPs owned by one routed net.
Unknown tiles/indices/PIPs, inversion, multiple owners, duplicated PIPs, missing
or extra emissions, conflicting values and unmodeled repetitions remain errors.
Existing I/O STEPDOWN cardinality is unchanged. This is not generic deduplication
and never rewrites FASM, the routed graph, a hardware input or the old parser.

For the actual repeated `HCLK_R_X22Y234` BUF HCLK0 flag, the database resolves
generic tile `X22Y182` and two distinct PIPs, indices 1 and 7, to BOT0 and TOP0
clock leaves. The one owner is `$frontend$22`; the positive enable row is
`00_14`. The other actual HCLK flag has one source PIP. The real consumer's
unchanged merge function accepts equal positive assignments and rejects a
positive/zero conflict; no FASM parser, frame converter or bitstream is executed
by this consumer-function test.

Fresh clock-contract controls pass **8 tests in 17.607 seconds** (command wall
19.828 seconds), qualification controls pass **4 tests in 6.18 seconds command
wall time**, and `make generated-check` passes in 2.150 seconds. The complete
unchanged four-DSP/six-BRAM comparison body runs in an independent namespace
with only the source-bound read-only parser substituted. All four DSP and six
BRAM configuration checks now pass against the actual saved 286-cell output,
with 7,869 feature names. Three native positive placements and 1,024 LUT
comparisons remain reused and freshly verified, not new native executions.
All full-fit/timing/electrical/DRC/numerical/bitstream/programming flags stay false.

The not-yet-executed full HeAP runners are updated before execution:

- Placement admits only this completed clock-feature qualification. Six fresh
  host controls pass in 0.066 seconds; source-shape/resource/target/unique-BEL
  checks remain exactly reversible to the original full static runner.
- Route binds these clock sources before native execution and derives clock
  contracts directly from its actual routed module, before any comparison-only
  export view. `check_full_heap_clock_features.py` executes the entire unchanged
  515-DSP/six-BRAM comparator body in an independent namespace, with the same
  sixteen C32 kernels, all 39 DSP constant ties, 4,120 extra tile pins and BEL/
  wiring gates. Twenty-seven fresh host controls pass in 5.848 seconds,
  including every original v2/static control, literal comparator-source identity,
  strict parser failures and rejection of the real small control at the full
  515-DSP census. No old route/parser admission is weakened or overwritten.

At **20:12:35 HKT**, the
[full C32/K16 HeAP attempt](../build/openxc7/full-prefix-native-heap-place-1791461555717052444/report.json)
is launched in `rknpu-full-prefix-native-heap-place-20261008.service`, invocation
`8ee59c7e6cb44f7bbc746a3d1ff1c526`, supervisor PID **1416947**. Its first stage
is source/artifact admission, not completed native packing or placement. It
reuses the exact original prepared input, retains sixteen kernels/512 parallel
products/515 DSPs/six BRAMs and the whole 538,118-cell packed-membership gate,
part `xc7k480tffg1156-2`, 50 MHz, seed 3588, `--Werror` and normal refinement.
The native limit remains 43,200 seconds and address-space limit 12 GiB; the
managed limit is 46,800 seconds, memory-high/max 12/14 GiB, swap maximum 4 GiB,
nice 5, OOM stop, control-group termination and disabled core dumps. It does
not restart, alter or terminate either original live job.

At **20:12 HKT**, original full static placement PID **1344200** and mapped
mode-4 replay PID **1373401** are still live (8h41m and 5h40m elapsed). Neither
has a newly completed result. A fresh `make generated-check` passes after the
handoff edits. The existing source-identical production regression's unchanged
600-second Verilator compile-limit FAIL remains an actual FAIL; these selected
host tests do not make a new all-green `make test` claim. Production RTL/model/
encoder/input/golden/constraints identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
No standalone `SHA256SUMS`, circuit repair, physical acceptance or bitstream is
created. Exact -2/DSP timing coverage and board electrical/DRC gates stay open.

At **20:15 HKT**, a fresh combined `test_native_heap_*control.py` run passes
**49 tests in 12.134 seconds**. All nine current clock/HeAP handoff and control
Python sources parse, and their/doc edits have no trailing whitespace. The
completed clock qualification records **3,484 source bindings and six own
artifacts**, two actual HCLK contracts, four DSP comparisons and six BRAM
comparisons. The full HeAP report is still `RUNNING/admission`, with no native
command yet executed. The original mapped replay is still `RUNNING/mode4`.
An explicit check finds no `SHA256SUMS*` file in either new run directory and
confirms the unchanged production identity above. Fresh installation discovery
still finds no full `bin/vivado`; `~/vivado/v.tar` is the unchanged 3.8 GiB
September 12 archive, not evidence of a newly downloaded full installation.

### 2026-10-08: actual full HeAP execution, fifth mapped mode and frame control

At **20:21 HKT**, the existing full HeAP service has passed source-bound
admission, its six fresh software controls, generated checks and native version
checks. The actual native command is PID **1417350**, using the unchanged
corrected executable, exact original prepared input, `--placer heap`,
`--no-route --freq 50 --seed 3588 --Werror --verbose` and part
`xc7k480tffg1156-2`. Native packing retains 502,795 SLICE_LUTX cells, 17,519
SLICE_FFX cells, 8,640 SELMUX2_1 cells, all **515 DSPs and six BRAMs**, and
constrains 12,278 LUTFF pairs. At **20:26 HKT**, it reports 14,128 indexed
control sets, five constraint-based placements and initial analytic placement
for 433,757 cells. These are progress markers, not complete placement,
architecture validity, route, full physical fit or timing/electrical signoff.
The original static placement remains live, with approximately 23,700 queue
entries and its original native time limit; neither job is restarted.

The original unchanged mapped-board supervisor also advances automatically:
**mode 4 passes** in **20,754.567 seconds**, return code zero. Its literal log
checks all 4,096 initialized/readback words, 196 command reads, 6,528 operand
reads, 64 output writes/acknowledgments and 44,915 cycles, with success=1,
resets=1, faults=0. The supervisor report is now `RUNNING/mode5`; its new native
child is PID **1418264**. Five of nine required modes are complete. No old
simulator log is copied forward, no timeout/reset/golden is changed, and
all-nine-mode numerical or physical acceptance remains incomplete.

At **20:22:36 HKT**, the separate
[saved-native HeAP frame control](../build/openxc7/native-heap-frame-control-1791462156684206950/report.json)
starts in `rknpu-native-heap-frames-20261008.service`, invocation
`5091878fa1a7442ea628ef44471baa9e`, supervisor PID **1418394**. Its helper is
`tools/openxc7/probe_native_heap_frames.py`; eleven fresh host controls pass in
**4.792 seconds**, including every original five corrected-DSP frame control.
Fresh `make generated-check` also passes. This is launch/preflight evidence;
the managed procedure is still `RUNNING/admission`, not a completed converter
or frame-readback result.

The new helper revalidates the completed clock-feature qualification and its
unchanged saved native artifacts. Its prepared main is exactly reversible to
the existing corrected-frame control except for HeAP parent/output admission,
clock multiplicity accounting, additional clock-only comparison targets and
clock readback. The original four-DSP/64-feature requirement body, strict
converter, exact-part geometry, full original DSP readback and real single-bit
comparison-corruption rejection stay unchanged. Origin metadata comes only
from the already-bound corrected source; no stored qualification or FAIL is
rewritten or relabelled.

Conversion takes the original `control.fasm` directly through the same pinned
F4PGA grammar and Project X-Ray converter, with no missing-feature override,
filtering or duplicate folding. It must account for all 7,875 input statements,
including the two-line clock enable, and verify that every HCLK request comes
from the actual native input at its distinct-PIP fanout count. Missing, extra,
unknown, injected, non-Boolean or vector clock requests remain failures. A
separate readback worker must find exactly one positive nonaliased physical DB
bit per clock feature and reject a mutated actual frame in a comparison-only
copy. The 64 DSP targets and clock targets never enter conversion or hardware
execution. Complete 45,892-tilegrid/46,336-legal-part frame coverage and full
101-word records remain required by the unchanged validator.

The pinned conversion sources currently remain clean at Project X-Ray
`ed3331c6200f421164101388759fc2860b0f5634` and database
`517d66a383676cb971177ea92b0ff3b6ea6e8690`. Managed limits are 4,500 seconds,
memory-high/max 2/4 GiB, swap maximum 1 GiB, one CPU, nice 10, OOM stop,
control-group termination and disabled core dumps. Individual conversion and
readback limits remain 1,800 and 120 seconds. No full-board frame conversion,
native P&R rerun, bitstream assembly/emission or programming is authorized by
this control. Production identity remains `09f1c3f65ba9...`; all physical,
electrical/timing/DRC and bitstream gates stay open. No new `SHA256SUMS` exists.

At **20:35:41 HKT**, that actual HeAP frame procedure completes **PASS**, with
status
`PASS_SAVED_NATIVE_HEAP_FASM_EXACT_PART_FRAMES_64_DSP_AND_SOURCE_BOUND_CLOCK_BITS_NOT_BITSTREAM_OR_SIGNOFF`.
The managed service is terminal with `Result=success`, `ExecMainStatus=0`;
the original small native HeAP FAIL remains unchanged. All seven fresh command
executions return zero: eleven software controls (3.497 s test time, 7.508 s
command wall), generated check (3.060 s), Python version (0.348 s), actual raw
FASM conversion (141.665 s), exact-part geometry (91.416 s), DSP readback
(28.952 s) and clock readback (31.572 s). The parser runtime is **Python 3.13.13**.
The conversion log retains its actual unavailable-fast-ANTLR RuntimeWarning
and pure-Python textX fallback; this is not a warning-free parser installation.
No parser/environment patch, suppressed warning, missing-feature override or
native warning-policy change is used to obtain this result.

The actual strict converter consumes **7,875 native statements** and **97
source-defined required/default statements**, with no missing feature or skipped
clock-activity request. It preserves three input-only HCLK requests: two for
`HCLK_R_X22Y234.ENABLE_BUFFER.HCLK_CK_BUFHCLK0`, one for the corresponding
`HCLK_R_X22Y286` flag. The unmodified assembler's bit-setting behavior accepts
the identical repeated positive bit. This is real converter/frame evidence,
not merely the separately tested FASM merge function or a deduplicated input.

Geometry validation checks all **45,892 supplied/tilegrid frames** against the
**46,336 legal exact-part frames**, each with 101 unsigned32 words; 444 legal
addresses outside tilegrid coverage remain the assembler's zero-fill scope.
There are 8,223 nonzero words. Both independent readback workers read the same
actual generated frame file: all **64 required DSP features/bits** match, and
both **HCLK features/bits** match at nonaliased positive DB locations. Each worker
rejects its own actual-frame single-bit corruption in a comparison-only copy.
These are database-consistency checks, not independent silicon/board readback.

Fresh post-completion checks verify every own artifact, unchanged production
identity and all false full-board/physical/signoff/programming claims. No new
native P&R execution or full-board frame conversion/bitstream follows from this
small control. At **20:37 HKT**, full HeAP placement PID **1417350** is still live
and has reached initial analytic iterations 0–2. Original static placement PID
**1344200** and mapped mode-5 PID **1418264** also remain live. No original job
has been restarted, and none has a newly completed full result. Full numerical,
placed/routed, exact -2/DSP timing, electrical/DRC and reviewed emission gates
remain required. No standalone `SHA256SUMS` is created.

### 2026-10-08: prepared full-target frame conversion, not execution

At **20:53 HKT**, the full-frame handoff is prepared in
`tools/openxc7/convert_full_heap_frames.py`, with read-only route admission in
`tools/openxc7/verify_full_heap_route.py`. Fresh
`test_full_heap_frame_control.py` passes **19 tests in 9.988 seconds** under
**Python 3.14.5 / GCC 12.3.0**, with Python warnings fatal for those controls.
This includes eight new full-route/frame guards and all eleven original small
clock/corrected-DSP controls; no expected failure is removed. The actual CLI
rejects the currently incomplete full placement report with an assertion
before creating an attempt or invoking conversion. `--help`, generated-source
checks, AST parsing and whitespace checks also pass. These are host guard and
saved-small-data checks, not a full native route or frame-conversion result.

The full reader admits only the exact completed HeAP v2 full-route status,
source/parent bindings, C32/K16/512 products, exact -2 part, 50 MHz and seed 3588.
It requires all 538,118 bound/unique-BEL/circuit instances, sixteen 32-DSP
kernels, all 521 selected DSP/BRAM configurations and 4,120 corrected DSP tile
pins. It freshly rechecks actual placement/native-qualification parents,
shared corrected base, original checkpoint input, complete exact native argv,
v2 import and BEL/pair/carry/router scans, native warnings/errors, physical
footprint, producer/module/port contract, full endpoint-preserving circuit
identity, all 515-DSP/six-BRAM feature comparisons and actual routed clock PIPs.
Comparison-only views remain comparison-only. A PASS label, small control,
prepared or RUNNING report is insufficient to invoke conversion.

Only that source-bound full route's raw `native_FASM` can enter the unchanged
strict converter. All **8,240** corrected DSP features (515 times sixteen)
must come from native input requests and be read back from actual frames;
every HCLK request must retain its actual one-owner distinct-PIP multiplicity,
and all clock bits require positive nonaliased DB locations. The DSP readback
body changes only its 64-to-8,240 count and completion message; original bit,
geometry and actual-frame corruption-rejection logic remain unchanged.
Clock readback reuses the already-qualified small worker. Both sets of
expected features remain secondary comparison targets, never converter or
hardware inputs. Native repacking/replacement, CPU tensor/layout repair,
bitstream assembly/emission and FPGA/flash access are not performed.

The request reader streams every unchanged converter JSONL record in order,
rather than retaining a full-route-sized list. It rejects unknown or duplicate
fields. Fresh comparison against **all actual** saved small requests reproduces
the converter's 7,875/97 input/default census and exact three clock requests;
no line filtering, folding or order change is used. Full-target admission,
primitive census, identity and bitstream/physical gates are not substituted
with this small-data check.

The future full conversion has a 43,200-second host limit, not a relaxed FPGA
period. The same exact-part geometry validator retains its 120-second limit;
full-sized DSP/clock readback workers have 1,800-second limits. Those new full
operation bounds do not change any executed small control, original native
placement/route limit or physical acceptance requirement. The completed small
frame parent's original source/artifacts must also remain unchanged.

Only after a full route completes, the guarded handoff command is:

```sh
python3 -B tools/openxc7/convert_full_heap_frames.py \
  --routed /absolute/path/to/completed/full-HeAP-route/report.json
```

This command has **not** been run with a full routed report; none exists yet.
The full HeAP and original static placement services and mapped mode-5 replay
remain live. Production RTL/model/encoder/constraints identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
The earlier unchanged-source production `make test` compile-limit FAIL is
preserved and is not superseded by host-tool tests. No full numerical/placed/
routed/timing/electrical/DRC/bitstream or FPGA pass, nor standalone `SHA256SUMS`,
is created by this preparation.

### 2026-10-08: full packed LUT necessary-bound census, not placed fit

A read-only census inspects every cell in the unchanged corrected-DSP
`full-packed.json`: **538,118 cells**, including **502,795 plain LUTs**, all
**515 DSPs**, six BRAMs and sixteen kernels with 32 DSP products each. The
source-bound backend counts connected input pins and rejects a six-input
logic LUT sharing its physical position; plain paired LUTs must have at most
five distinct input nets in their union. This diagnostic does not alter a
cell, binding, net, native input, timing check or running placement.

The [first 180-second attempt](../build/openxc7/lut-capacity-census-20261008-1326/timeout-observation.json)
times out without a result. The
[separate unchanged-body 600-second attempt](../build/openxc7/lut-capacity-census-retry-20261008-1331/report.json)
also remains **FAIL**, with `SystemExit(143)` at **21:42:00 HKT**. It had
completed the full census and bound calculations, but not final input/source
verification. Neither timeout is renamed PASS or used as a capacity failure.

The [separate revalidation](../build/openxc7/lut-capacity-revalidation-20261008-1346/report.json)
rechecks those exact original input hashes before and after, the unchanged
frozen census body, full native packing census/kernel membership and current
production source. It freshly runs all nine arithmetic controls, including
200 seeded exhaustive relaxed-matching comparisons with seed 3588. This is
source/input revalidation of completed computations, **not a full census or
native placement rerun**. The original failed report and both host budgets
remain unchanged. Python is **3.14.5**; generated-source checks also pass.

There are **58,857 six-connected-input LUTs** and **8,869 five-distinct-input
LUTs without any eligible subset-input partner**. These 67,726 cells require
whole physical LUT positions. Even pairing every remaining cell optimistically
requires another `ceil(435069 / 2) = 217535` positions, for a necessary lower
bound of **285,261 / 298,600 positions (95.533%)**. This lower bound does not
exceed device capacity and is **not evidence of impossibility or fit**. It
ignores global matching competition, cluster/BEL restrictions, OUTMUX claims,
FF controls, routing and timing; actual resource use can be higher. No
placement assignment is generated or executed from this diagnostic.

The next physical action therefore remains the actual completed full-target
placement/route handoff, not a reduced or serialized target. Both original
placement services and mapped replay remain live. Production RTL/model/encoder/
constraints identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
Full numerical, placed/routed, exact -2/DSP timing, electrical/DRC and reviewed
bitstream emission gates remain open. No new `SHA256SUMS` file is written.

### 2026-10-08: full matching bound establishes a packed-graph capacity conflict

The [fresh whole-census/cache run](../build/openxc7/full-lut-sharing-groups-20261008-1403/wrapper_report.json)
now completes the original unchanged census body and every final source/input
check. It retains all 538,118 cells, 515 DSPs, six BRAMs and sixteen 32-DSP
kernels. The census finishes at **22:13:54 HKT** in **594.778 seconds**;
the completed cache contains all 443,938 eligible LUT cells in 316,578 distinct
input-set groups. The earlier 180/600-second failures remain unchanged.

The [actual full matching measurement](../build/openxc7/full-lut-sharing-bound-1791469159980053569/report.json)
completes at **22:20:19 HKT**, using Python **3.14.5**, nine fresh software
controls and **250 seed-3588 exhaustive small relaxed-matching comparisons**.
Its capacitated bipartite graph contains every five-distinct-input group and
every smaller-input group, with 83,925 eligible subset arcs. The maximum
five-to-smaller matching and residual minimum-cut capacity are both **18,140**.
This is not a maximum matching or placement of the entire circuit.

There are 66,340 five-input cells and 377,598 smaller-input cells. To remain
optimistic, the bound independently allows all **1,928 identical-five internal
pairs**, even though their cells can also be counted in the external matching,
and allows every remaining smaller cell to pair regardless of actual inputs.
Thus at most `floor((377598 + 18140) / 2) + 1928 = 199797` eligible pairs are
possible under this relaxation. Including the 58,857 whole-position LUTs,
the necessary position count is **502795 - 199797 = 302998**, exceeding the
device's **298,600** positions by **4,398**.

Unlike the earlier isolated-neighbor bound, this establishes a **capacity
conflict for this exact packed graph under the bound native LUT rules**.
It does not establish that C32/K16 cannot fit with another logically equivalent
mapping, nor a physical placement, numerical RTL or RK-silicon result. Cluster,
OUTMUX, FF, routing and timing constraints were ignored, not relaxed in the
execution path. Neither the input-group cache nor a matching assignment enters
the FPGA path. Source/input digests before and after agree; production identity
remains `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.

The next implementation priority is a separate, independently validated
full-size area/mapping optimization retaining **C32/K16 and all 512 simultaneous
products**, not a serialized or reduced target. Both original placement
services and the mapped numerical replay retain their original inputs,
constraints, warning/legality gates and host limits. No full route, timing/
electrical/DRC acceptance or bitstream emission follows from this diagnostic.

A subsequent read-only opportunity census of the actual
[observation-preserving prefix mapping](../build/rknpu-dsp-prefix-observed-board-mapping/1791308955335106261/report.json)
finds **974 input-identical combinational LUTs per C32 kernel**: 230 LUT2,
608 LUT3, three LUT4, 62 LUT5 and 71 LUT6, plus seven MUXF7s. Sharing one copy
across the sixteen callers would remove **14,610 LUT primitives and 105 MUXF7s**,
conditionally reducing the mapped LUT count from 445,816 to 431,206. These
are mapped primitives, not physical positions or a recomputed packed bound.
The actual mapped JSON digest is checked before and after the census; every
caller remains present with 32 DSPs. No circuit is transformed or executed.

The older fixed-variant sharing analyzer explicitly rejects this prefix graph
first at DSP timing-declaration qualifiers and then at omitted DSP pins; its
checks are not weakened. The separate exploratory census requires complete
pin declarations and recognized timing-only blackbox contents for every
eligible combinational primitive. All DSPs and state outputs are barriers;
the 32 DSP instances' omitted pins are recorded, not defaulted or inferred.
The full combinational dependency closure must resolve before computing the
input-identical subset. An actual shared-cone implementation still needs its
own reversible circuit checks, numerical/fault/reset evidence, fresh native
packing, placement/routing and all physical emission gates.

### 2026-10-08: separate full-size prefix shared-cone implementation

[prefix_shared_cones.py](../tools/cmac/prefix_shared_cones.py) now implements
that lift as a separate mapped-circuit candidate. It records omitted DSP pins
as explicit barriers, requires complete eligible combinational declarations,
and checks every caller's identical shared inputs. Reverse expansion must
restore every original module, cell, parameter, wire, port and shell field.
DSPs, state and private weight inputs are never shared. All **28 fresh host
controls** pass, including the twelve unchanged original dependency controls
and corruption rejections for shared/private functions, DSP loss, changed
callers/buses, wire collisions and namespace changes.

The [first actual preparation](../build/rknpu-dsp-prefix-shared-board/1791470175035752151/report.json)
finishes **FAIL at 22:41:48 HKT**: the unchanged generic exporter refuses the
actual DSP string parameters. Its full-candidate lift check and real one-bit
shared-LUT corruption/DSP-removal negatives had passed, and its saved candidate
contains **431,206 LUT primitives, 17,519 FFs, 515 DSPs and six BRAMs**. No
actual export or numerical/physical acceptance is claimed by that failure.
The failed report, source, expectation and artifacts remain unchanged.

The [separate export continuation](../build/rknpu-dsp-prefix-shared-export/1791470852571972438/report.json)
uses the existing five-setting DSP-specific exporter, not changed parameter
values or defaults. Its fresh **28 sharing, six DSP-export and nine continuation
controls** pass, as does `make generated-check`. It rechecks all old input and
artifact digests, the full saved lift and all actual 32 kernel/three shell DSP
string configurations. It now completes at **22:56:40 HKT**, with fresh real
Yosys export (**131.544 seconds**), exact roundtrip primitive/parameter/pin-wire
identity and warning-free hierarchy checks (**137.226 seconds**). Tool version
is **Yosys 0.65, aec814bdf3071f7e0fd0fbe43f7f711e99d01e24**. All bound inputs
agree before and after, and production identity remains unchanged. This is
completed full-circuit structural/export preparation, not numerical replay,
native packing, placed fit, physical signoff or bitstream emission.

[prefix_shared_flatten.py](../tools/cmac/prefix_shared_flatten.py) prepares
literal two-stage private/shared hierarchy expansion, with six passing small
controls. Its first synthetic run failed because its fixture lacked top-level
ports; an explicit complete fixture fixes that preparation without changing
the flattening guards. At that preparation point the helper had **not expanded
or packed the full candidate**. Complete export, exact full-circuit identity after expansion and
physical IO insertion, retained sixteen 32-DSP kernels, fresh native packing,
numerical/fault/reset evidence and all physical gates remain required.

### 2026-10-08: full shared-prefix packing-input preparation and guarded handoff

The [actual full preparation](../build/openxc7/full-prefix-shared-pack-input-1791471918232843068/report.json)
is running from the completed shared-prefix export. It has freshly passed six
literal-flatten controls, nine full-export admission controls and generated
checks. Literal two-stage expansion retains **488,407 primitive cells**, all
sixteen private kernels with **32 DSPs each**, and one shared combinational
instance. It independently runs Yosys flattening of the original exported
Verilog and requires exact full-circuit identity, then inserts only the original
two IBUFs, three OBUFs and one BUFG. Removing those six physical buffers must
again restore the whole circuit. At **23:23 HKT**, the actual Yosys flatten/check
command has exited successfully with zero reported problems; its full exported
graph comparison is still running. No completed packing-input acceptance or
native packing is inferred from that command alone.

At **23:31 HKT**, the independent full flatten identity now passes: **488,407
cells, 572,614 bijective wires and 2,364,603 endpoint bits**, with no scope
metadata in either comparison graph. The actual Yosys command took **459.174
seconds**, using the same bound 0.65/aec814bdf307 tool. Physical IO export and
the complete pad-removal identity are now running, not accepted yet.

The separate [shared-prefix native packing handoff](../tools/openxc7/pack_prefix_shared_board.py)
now passes **15 fresh host controls**, including complete saved-small-export
reader checks and corruption rejections. `make generated-check` also passes.
The combined `test_prefix_shared*.py` suite passes **67 methods** on the current
helper sources; this is a host preparation/reader suite, not HDL numerical
replay or a new complete production `make test` result.
It rejects unfinished preparation, smaller targets, wrong part/clock/seed,
changed circuit identities/resources, missing/duplicate kernels and inferred
numerical or physical acceptance. It also requires the completed isolated
corrected-DSP encoder qualification, rechecks all bound inputs before and
after execution, and uses the actual new candidate's DSP/BRAM input inventory.
The pinned complete native-cell reader rejects unknown types, truncated or
extra data, duplicate cells and missing/extra selected resources. Its tiny
header-only view is comparison-only, never an execution input.

The full native action is **pack-only**, with the unchanged exact part, 50 MHz,
seed 3588 and `--Werror`. It requires all **515 actual DSP configurations**,
their **4,120 source-defined extra tile ties**, all six BRAM instances and
sixteen groups of 32 products. Resources will be measured from the new packed
graph, not projected or copied from the original graph. This handoff has not
yet executed native packing. Its controls do not prove full ordinary-wire
identity, numerical replay, placement/routing, physical timing/electrical/DRC
signoff or bitstream readiness. Production RTL and all original long-running
jobs remain unchanged. No new standalone `SHA256SUMS` manifest is written.

The explicit handoff command is below. It rejects any running parent before
creating an execution directory or starting the native tool; the completed
parent must pass all its identity/source checks before this action is admitted.

```sh
python3 -B tools/openxc7/pack_prefix_shared_board.py \
  --prepared build/openxc7/full-prefix-shared-pack-input-1791471918232843068/report.json
```

The [original bounded static placement retry](../build/openxc7/full-prefix-bounded-search-place-1791430153316326483/report.json)
finishes **FAIL at 23:31:46 HKT** at its unchanged **43,200-second** native host
limit (43,205.996 seconds observed including termination). Its native child
returns -9 after the supervisor terminates that timed-out command. There is
**no `placed.json`**. The report, all seven recorded artifacts, original source,
physical input and 512-product target are retained; no retry, limit extension
or result relabeling is performed. The last progress record has 21,983 queued
cells and no out-of-bounds sampled coordinates. This timeout is not itself a
capacity proof; the separate 302,998-position necessary bound above establishes
the current mapping's conflict. The original HeAP job and mapped mode-5 replay
remain running under their unchanged supervisors.

### 2026-10-08: one-pass shared packed capacity characterization

The shared packing handoff now optionally observes every native LUT while the
unchanged complete cell-table reader walks the actual new export. The separate
[packed_lut_bound.py](../tools/openxc7/packed_lut_bound.py) retains the existing
`logical_lut` INIT/pin/annotation checks and exact matching implementation. It
requires the two already-qualified physical-rule source digests; memories,
SRLs, dual-output or unknown logical modes/disconnected logical inputs remain explicit
failures. Six **connected** inputs consume a full position even when their
net IDs repeat. All other ordinary LUTs enter only the existing deliberately
optimistic sharing relaxation. Device positions are derived from the new
actual native resource log, requiring 597,200 paired BEL slots, not a copied
84-percent utilization string or an old LUT count.

Fresh verification passes **nine census controls**, including complete saved
small-native observation, and the **nine unchanged matching controls** with
250 exhaustive comparisons at seed 3588. The modified handoff's fifteen
admission/reader controls, six corrected-DSP controls, all 67 combined
shared-prefix controls and generated checks also pass. No HDL/FPGA numerical
acceptance is inferred from these host checks. Actual full shared packing and
its new full-group census/matching remain unexecuted until the independently
expanded IO-preparation report completes. The original 302,998-position
conflict report and all old assertions are unchanged. The new input-group
cache will be diagnostic only, never a placement assignment or hardware input.

The full IO-only Yosys export has now exited zero in **504.971 seconds** with
zero reported structural problems. Its complete buffer-removal circuit check
is still running; this command result is not final preparation acceptance.

The [full IO-preparation report](../build/openxc7/full-prefix-shared-pack-input-1791471918232843068/report.json)
now completes **PREPARED at 23:49:46 HKT**, without a numerical or physical
acceptance claim. Exact independent flatten and buffer-removal identities each
compare **488,407 cells, 572,614 bijective wires and 2,364,603 endpoint bits**.
All **1,146 bound source/input paths** agree before and after; twelve actual
artifacts are recorded. The unchanged production identity is still
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
All sixteen kernels, 512 CMAC/three shell DSPs and six BRAMs remain. Six flatten
controls, nine admission controls and generated checks passed freshly in that
actual worker, not copied from an earlier run.

The [new actual full packing/capacity worker](../build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json)
is now launched from that completed report, initially **RUNNING/source_admission**.
It uses the already-qualified corrected-DSP native executable, not the old
uncorrected packer or a rewritten execution input. Its source-bound native
command has an **1,800-second host limit**, with a separate **7,200-second outer
worker limit** covering admission and complete graph/matching diagnostics.
These are new worker budgets, not extensions of any original placement or
numeric job. `--pack-only`, the exact part, 50 MHz, seed 3588 and `--Werror`
remain required. Its full circuit/numerical, placement/routing and physical
signoff/emission flags stay false. This live supervisor is not yet a completed
native pack, full LUT bound or a test-ready bitstream.

At **23:55 HKT**, this actual worker completes source admission with **4,474
bound paths**. Its fresh **15 admission/reader, six corrected-DSP, nine census
and nine matching controls**, generated checks and exact native-version check
all pass. It is **RUNNING/literal_input_inventory**, with the actual native
packing-executed flag still false. These controls/read-only checks are not a
new native packing result; the complete physical-input resource inventory
must pass before the tool command starts. The bound helper/test sources are
frozen while this worker is live.

### 2026-10-09: completed shared full packing and capacity-bound admission

The [actual shared full packing report](../build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json)
completes **PACKED at 00:22:43 HKT**, not placed fit or physical signoff. The
real native `--pack-only` command returns zero in **650.607 seconds**, with
normal completion and no warning/error admission. The complete independent
native-cell census measures **523,410 cells**: 488,080 SLICE_LUTX, 17,519
SLICE_FFX, 8,630 CARRY4, 8,647 SELMUX2_1, all 515 DSPs, six BRAMs and the
unchanged clock/IO/constant resources. All sixteen private kernels retain
32 DSPs each. All 515 actual DSP configurations and their 4,120 extra tile
ties compare successfully. Fresh actual worker controls and generated checks
pass; all 4,474 admitted source/input paths agree before and after. Production
source identity remains `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.

The bound is calculated from this **new actual packed graph**, not an old
cache, projected sharing count or assignment. Its maximum five-to-smaller
matching and independent minimum cut both equal **17,660**. The deliberately
optimistic pair upper bound is 192,941; the resulting necessary physical
LUT-position lower bound is **295,139**, below **298,600** available. The
3,461-position difference is **not measured placement headroom**. This removes
the earlier original mapping's proven LUT-capacity obstruction for this new
graph, but does not prove that legal placement/routing can achieve the bound.
The original 302,998-position conflict evidence is unchanged. No complete
ordinary-wire identity through native packing, full-board numerical replay,
placed fit, routing, timing/electrical/DRC signoff or bitstream is inferred.

The separate [shared full-size HeAP handoff](../tools/openxc7/place_prefix_shared_board.py)
passes **13 new controls**, the **six unchanged native-HeAP board controls**,
all **80 combined shared-prefix controls** and `make generated-check`. These
are host guard/checker tests, not new HDL or native placement results. The
handoff refuses RUNNING/failed packing, shrunk targets, changed part/clock/seed,
incomplete inventories, capacity conflicts, tool waivers and inferred physical
acceptance before creating execution output. It requires the complete actual
pack inventory, exact whole cell-name membership, all unique BELs and the
unchanged 515-DSP/six-BRAM/16-kernel configuration checks after placement.

Its [new actual worker](../build/openxc7/full-prefix-shared-native-heap-place-1791476631447626227/report.json)
starts **00:23:51 HKT**, initially **RUNNING/source_admission**, supervised by
`rknpu-full-prefix-shared-native-heap-place-20261009.service` (invocation
`46deb00563eb4f269bb099b987cd6fce`). It revalidates the completed source-bound
HeAP/clock qualification and freshly repacks the exact new literal physical
input. It does not execute the diagnostic matching cache, reload an old packed
context or reuse a placement. Normal HeAP refinement, native legality,
`--Werror`, seed 3588, the exact -2 part and 50 MHz remain mandatory.
This new worker has the same **43,200-second native / 46,800-second outer**
budgets and **12 GiB address-space / 12 GiB memory-high / 14 GiB memory-max /
4 GiB swap-max** limits, with nice 10. No original job is modified or restarted.
The original HeAP placement and mode-5 mapped replay remain running. No new
standalone `SHA256SUMS` file is written; existing evidence remains untouched.

The exact guarded command is:

```sh
python3 -B tools/openxc7/place_prefix_shared_board.py \
  --packed build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json
```

This command has already been launched by the worker above; do not launch a
duplicate while that worker is live. Shared numerical, full native routing
and all physical acceptance gates remain required before emission or testing.

At **00:33 HKT**, the shared placement worker completes source admission with
**4,625 bound paths** and passes its fresh thirteen shared-placement controls
(5.494 seconds), six unchanged HeAP guards (3.911 seconds), generated checks
(2.197 seconds) and exact native-version check (0.150 seconds). It is now
**RUNNING/native_place**, child **1446598**, freshly repacking the same prepared
shared physical input using the qualified `c68c135` HeAP engine. This is a
live native command, not completed packing/placement, fit or routing evidence.

### 2026-10-09: guarded shared full-routing preparation

The separate [shared full-route handoff](../tools/openxc7/route_prefix_shared_board.py)
passes **38 host controls** (eleven new and all 27 unchanged v2/HeAP guards).
The combined `test_prefix_shared*.py` suite passes **118 methods in 20.006
seconds**, and `make generated-check` passes. Its source-shaped derivation is
exactly reversible to the original HeAP route procedure; the old helpers,
tests, source/report bindings and resource/error expectations remain unchanged.
These host tests are not actual full native scan/routing or an HDL/FPGA PASS.

Admission requires this candidate's **own completed full placement** and the
actual 523,410-cell packing report above, including the exact measured counts,
all 515 DSPs, six BRAMs, sixteen 32-product groups, whole cell-name membership
and unique BELs. The original 538,118-cell graph cannot pass this new profile.
RUNNING/failed placement is rejected **before output creation or tool launch**;
an executed negative confirms this. No full shared route has been launched.

The only artifact-path adaptation is an in-memory metadata view normalizing
the new producers' absolute artifact paths for the **unchanged** relative-path
binder. Every artifact must stay within its own actual attempt, duplicate/path
escapes and invalid/changed digests remain failures, and the original report
bytes are what the report binding hashes. This view is neither saved nor a
hardware execution input. The selected 515-DSP/six-BRAM input comes from the
new actual packed attempt and is source-bound; no old selection or group cache
is substituted.

The native action still imports the literal completed placed checkpoint,
executes the qualified **v2 all-BEL/pair/carry scan before routing**, retains
router connectivity checks, verifies every unchanged physical BEL and complete
logical circuit, and compares every actual DSP/BRAM configuration plus
source-bound clock features. No placement rerun, input repair, warning waiver,
clock reduction or physical/numerical acceptance is added. The guarded future
command is below; its current RUNNING parent cannot authorize execution:

```sh
python3 -B tools/openxc7/route_prefix_shared_board.py \
  --placed build/openxc7/full-prefix-shared-native-heap-place-1791476631447626227/report.json
```

A new [isolated unchanged production regression](../build/source-identical-production-regression/1791477276316998599/report.json)
also starts at **00:34:36 HKT**, supervised by
`rknpu-source-identical-production-regression-20261009.service` (invocation
`9a0c36b7279c43fe8443d04db0682d78`). It copies the complete byte-identical
production source and all four frozen stimulus directories into its own
workspace, then executes the unchanged `make test` target; only vector
regeneration prerequisites are held to protect the live fixtures. All original
simulation/error/warning gates and per-command limits, including the prior
600-second Verilator compile limit, remain unchanged. The new worker's make
command has a 7,200-second budget with a 7,800-second outer service budget,
nice 15 and 8 GiB memory-high/10 GiB memory-max/2 GiB swap-max. It is **RUNNING**,
not a new production regression PASS, shared-board numerical acceptance or
FPGA evidence. The earlier terminal compile-timeout failure is preserved.
No new standalone `SHA256SUMS` file is created by either handoff.

### 2026-10-09: this shared candidate's own numerical-replay input preparation

The separate [replay-input producer](../tools/cmac/prepare_prefix_shared_replay.py)
prepares the completed shared candidate's own literal Verilog and the unchanged
nine-mode raw-board bench, rather than inheriting another candidate's numerical
result/executable. Fifteen host controls pass, including all eight unchanged
DSP replay guards, and generated checks pass. The combined shared suite at
that point passes 133 methods; these are host controls, not numerical replay.

Its [first actual preparation](../build/rknpu-dsp-prefix-shared-replay-input/1791477912941138574/report.json)
finishes **FAIL at 00:47:17 HKT**, before bench binding, hardware export copying
or full-board compilation. Source admission binds 1,166 paths; all seven actual
control/generated/version/model checks pass. The failure is the unchanged
`physical_counts` guard rejecting non-`$specify` cells in the DSP blackbox
declaration. It was called without the already-existing qualified counting
view. The failure/helper, its original guard, source and logs are preserved;
this is not a numerical mismatch, candidate RTL diagnosis or signoff failure.

The separate [counter-qualified continuation](../tools/cmac/continue_prefix_shared_replay.py)
uses the existing `lane_dsp_library.timing_only_view` only for that census.
It recognizes exactly four one-bit `$logic_and` CEP qualifiers, with the fixed
zero/one roles feeding only the P/PCOUT CLK timing-enable records. Unknown
logic, primitive-port drivers, extra sinks, changed widths/clocks/destinations
and nonblackbox declarations remain failures. The resulting audit must equal
this candidate's own completed export audit. The counting view is never saved
as a hardware source or passed to export, compilation or simulation. All three
actual hardware modules remain unchanged.

Nineteen fresh controls pass: the original fifteen, both unchanged qualifier
guards and two continuation/admission checks. The original source-shaped
procedure is exactly restored by reversing the four explicit replacements.
The combined `test_prefix_shared*.py` suite now passes **152 methods in 26.097
seconds**, with generated checks passing. The executed continuation revalidates
the original failed source/artifacts as well as its own parents; no old log is
copied forward or described as a new numerical/native result.

Its [actual new worker](../build/rknpu-dsp-prefix-shared-replay-qualified-input/1791478332907270075/report.json)
starts **00:52:12 HKT** with a separate 2,400-second outer budget, 8 GiB
address-space/core-zero limits and nice 15. At **00:54 HKT**, it is
**RUNNING/actual_full_hierarchy_and_wire_binding**, after admission of **1,200
paths** and fresh nineteen-method controls, generated checks, Yosys/Icarus/vvp
versions and vendor model commit/clean checks. Full preparation is not accepted
yet. It must retain all 488,407 actual primitives, 515 DSPs/six BRAMs, sixteen
private kernels and the one 981-cell shared combinational module; match every
byte of the completed literal export; preserve all 22 exact live observation
wires and all original fault/numerical/reset checks; freeze unchanged pinned
vendor models/default GSR; and retain the complete original input/oracle files
plus the isolated first-output-bit wrong-golden negative. All bound paths must
still agree afterward. Full compilation and all nine modes remain unexecuted
for this new graph and are mandatory before numerical acceptance. No runtime
CPU arithmetic/layout fixups, physical waivers or standalone checksum manifest
are introduced.

At **00:53 HKT**, the new full shared HeAP worker remains live and advances
through initial analytic iterations 0 and 1 (wire lengths 149,273 and 133,629).
This is genuine native progress, not completed/legal placement or a route.
The isolated production `make test` remains live; its fresh 49 software methods
and 1,087,299 C++ comparisons pass, while both RTL simulator reports are still
incomplete. C++ tests are not SystemVerilog acceptance. The original placement
and mapped mode-5 replay remain unchanged and live. A targeted installer check
finds only the existing Vivado Lab `xsetup`, with no full `vivado` binary,
2026.1 Linux installer payload or live wget/curl/xsetup process. Timing,
electrical/DRC and bitstream gates remain open.

### 2026-10-09: own replay inputs complete; actual shared HeAP failure

The [counter-qualified input preparation](../build/rknpu-dsp-prefix-shared-replay-qualified-input/1791478332907270075/report.json)
now finishes **PREPARED at 01:04:23 HKT**. It binds **1,215 source paths and
thirty own artifacts**, checks all 488,407 expanded primitives and every
32-private/three-shell DSP configuration, and preserves all sixteen private
kernels and the one 981-cell shared combinational module. The actual exported
Verilog is byte-identical to the completed structural export; the unchanged
bench receives only its 22 exact live-wire reference substitutions. All raw
input/oracle bytes and the isolated first-output-bit wrong golden are checked,
along with the complete pinned vendor models, glbl and default startup.
The existing four timing-enable qualifiers affect only the resource counting
view. The original preparation FAIL, source and error gate remain unchanged.
This is completed input preparation, not numerical simulation or FPGA evidence.

The separate [own full numerical runner](../tools/cmac/test_prefix_shared_observed_board.py)
adds seven guards and retains all eight unchanged original DSP replay guards;
all fifteen pass. It refuses incomplete preparation before output/tools,
verifies every own input and complete vendor-model inventory, and freshly
compiles all three hardware modules. It cannot accept compilation alone or
inherit another candidate's binary/modes. The same source-bound new executable
must reject the real wrong first-output golden and pass modes 0–8 under the
unchanged numerical/address/fault/reset oracle, including the unknown-readback
case. Input/binary bytes are checked before and after every executed mode.

Its [actual worker](../build/rknpu-dsp-prefix-shared-observed-board/1791479366724278074/report.json)
starts **01:09:26 HKT**, with **1,248 admitted paths**. Fresh controls take
3.149 seconds and generated checks 1.630 seconds. Actual Icarus and vvp are
**13.0 stable (v13_0)**; the unchanged vendor commit and clean-tree checks pass.
It is **RUNNING/compile**, not an accepted numerical run. The user service is
`rknpu-full-prefix-shared-own-numerical-20261009.service`, invocation
`275274ba92754ea48c90d3063a2ea85a`, with nice 15, memory-high 10 GiB/max 14 GiB,
swap-max 2 GiB, OOM stop/core-zero, an explicit 21,600-second compile budget,
86,400 seconds per simulation mode and a 900,000-second outer budget. These
are this new job's budgets; no old running job or test limit is extended.
At approximately **01:26 HKT**, compilation is live at about 5.5 GiB RSS,
with no completed executable/mode result. The production source is still
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.

The [actual new full shared HeAP attempt](../build/openxc7/full-prefix-shared-native-heap-place-1791476631447626227/report.json)
finishes **FAIL at 01:07:51 HKT**. Fresh native packing retains 488,080 LUTs,
17,519 FFs, 515 DSPs and six BRAMs; its packed checksum `0x0f489b2b` equals the
completed own packing run. Initial analytic iterations 0–3 reach wire lengths
149,273, 133,629, 144,810 and 128,863. At the normal main-placer stage it reports
**10,000 maximum attempts per cell**, then fails to place
`rk_mapped_cell_86668.rk_mapped_cell_22977` (`SELMUX2_1`) after **10,001 attempts**.
Native execution returns **125 in 2,088.468 seconds**, with zero warnings and
one error. No `placed.json` is produced; the service is terminal exit-code
failure, not a memory/outer-timeout termination. Its peak charged memory is
5,779,161,088 bytes with no swap. The 295,139 optimistic necessary-position
bound remains only a bound; it did not prove this placement would complete.

### 2026-10-09: actual HeAP default-limit signed-overflow reproduction

The bound linked `common/place/placer_heap.cc` computes its default search
limit as `max(10000, int(cell_count) * int(cell_count) / 8)`. This exact source
expression multiplies signed 32-bit integers before division. At **523,410
actual packed cells**, the mathematical quotient is **34,244,753,512**, while
the real failed native log reports 10,000. This source arithmetic is outside
the signed-int range; the native failure alone does not establish its exact
machine-level overflow path or prove the failed mux intrinsically unplaceable.

The [first isolated arithmetic audit](../build/openxc7/shared-heap-attempt-limit-audit-1791479701447349503/report.json)
remains **FAIL**: four host controls pass, but GCC cannot link because
`/usr/lib64/libubsan.so.1.0.0` is missing. No overflow runtime test executes.
The separate [Clang selection](../build/openxc7/shared-heap-attempt-limit-clang-audit-1791479949964695628/report.json)
also remains **FAIL**: six guards pass, but resolving `clang++` to `clang-22`
drops C++ driver selection and linking fails on `std::cout`/C++ runtime symbols.
An initial continuation namespace collision was rejected before any attempt
directory/native execution; the subsequent saved Clang failure is retained.
No compiler/runtime package or global tool pointer is changed to hide a failure.

The [explicit C++ driver replay](../build/openxc7/shared-heap-arithmetic-cxx-driver-1791480180109061866/report.json)
now **passes at 01:23:39 HKT**. It admits both failed sources/artifacts and the
available pinned Clang UBSan archives. It changes only the compile invocation
to add `--driver-mode=g++` and a new output path; the fixture bytes, exact
original HeAP expression, warning checks and sanitizer/oracle remain unchanged.
Six fresh controls and generated checks pass; actual compilation takes
21.124 seconds. Counts **7 and 46,340** pass their exact in-range expected
limits. Counts **46,341 and the actual 523,410** both terminate with the
required signed-integer-overflow diagnostic and exit code 1. The actual-size
diagnostic explicitly identifies `523410 * 523410` not representable in `int`.
All input/source/executable bytes agree afterward. This is executed host
arithmetic reproduction, not new nextpnr placement or SystemVerilog validation.

The combined `test_prefix_shared*.py` suite now passes **183 methods in
56.043 seconds**, and generated checks pass. No native engine source/object
is modified yet. The next tool step is an isolated, finite, counter-safe wide
calculation with byte-reproduced parent linkage and fresh native qualification;
legality predicates, normal refinement, resource/clock/part checks and physical
gates must remain unchanged. Correcting this arithmetic alone is **not** a
claim that the mux or complete design will place/route/meet timing.

The [isolated production make worker](../build/source-identical-production-regression/1791477276316998599/report.json)
now finishes **FAIL at 01:25:30 HKT**, with make exit code 2 after 3,043.971
seconds. Its new Icarus report passes all **247 EW entries**, but Verilator
is **FAIL** after 220 passing entries: the unchanged **600-second**
`tb_job_control` compilation limit expires. The CMAC Verilator report also
fails its unchanged 600-second `tb_cmac_operand_front` compilation limit after
the first product bench passes; CMAC Icarus never executes. The earlier fresh
49 software methods and 1,087,299 C++ comparisons pass, but they do not validate
the unexecuted HDL cases. No numerical/protocol expectation or original limit
is changed. The report preserves 756 bound source paths and 1,743 own artifact
paths; its peak charged memory is 1,907,429,376 bytes, with no swap. This is
not a whole-production PASS. The original full
placement and mapped mode-5 supervisor remain live and unchanged. No new
standalone `SHA256SUMS`, FPGA bitstream, programming, physical/RK acceptance,
runtime CPU arithmetic/layout fixup or electrical/timing/DRC waiver is created.

### 2026-10-09: isolated finite HeAP correction built; fresh native qualification live

The [counter-safe source candidate](../tools/openxc7/heap_attempt_limit_candidate.py)
changes exactly the default limit expression in an own copy of the linked
`common/place/placer_heap.cc`. It calculates the square in unsigned 64 bits,
bounds the count before that square, and saturates to **2,147,483,646**. The
existing signed 32-bit attempt counter can increment once beyond that finite
limit and reject safely. The original nonpositive-divisor branch remains
unchanged; no no-timeout command argument is used. Whole-file reverse comparison
requires every other byte, including all legality, normal refinement, RNG,
objective and coefficient logic, to match the original. Eight source/arithmetic
controls pass, including 5,000 seed-3588 independent mathematical comparisons.

The [isolated actual build](../build/openxc7/counter-safe-heap-engine-1791481639500508440/report.json)
now finishes **BUILT at 01:54:46 HKT**, with **3,711 source paths and 28 own
artifacts**, not native qualification or full P&R. Eleven fresh build controls
and generated checks pass. Relinking all unchanged parent objects reproduces
the qualified parent executable byte-for-byte in 12.029 seconds. Actual Clang
22 C++-driver compilation with signed/unsigned-overflow sanitizers succeeds;
all nine real fixture executions pass exact finite-limit and next-counter
rejection results. Cases include counts 7, 46,340, 46,341, the shared 523,410 and
original 538,118 graphs, `INT_MAX`, `UINT64_MAX`, the largest positive divisor,
and the unchanged zero-divisor branch. These are host arithmetic checks, not
SystemVerilog or FPGA evidence.

The one changed HeAP object compiles with the original actual CMake flags and
GCC **16.2.1 20260819 (Red Hat 16.2.1-2)** in **316.906 seconds**, without new
warning suppression. Linking replaces only that object and takes 16.526
seconds. The actual new executable reports the unchanged `c68c135` native
version. All original dependency bytes and production revision
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`
still agree afterward. The default tool, original live jobs, first failed full
shared placement, RTL, raw commands/input buffers and expectations are untouched.

The [fresh native qualification procedure](../tools/openxc7/qualify_counter_safe_heap.py)
passes ten host guards, including four unchanged compiled-beta/early-rejection
guards. Saved feature data is used only as a parser-control fixture; these tests
do not claim new native execution. Controls reject incomplete builds before
admission/tools, missing DSP membership, wrong route/clock/stage, an actual BRAM
initialization-bit corruption, unknown or conflicting clock enables, and clock
repetition beyond actual bound fanout. Its native procedure is reversible to
the original except for explicit new build admission, output path and the
existing source-bound clock decoder. The original illegal-pair fixture, three
positive placements, 1,024 LUT comparisons, compiled beta=0.5 inspection,
normal refinement/legalization and four-DSP/six-BRAM route/FASM checks remain
mandatory, with their original 600/3,600-second native limits.

The actual user service is now live:
`rknpu-counter-safe-heap-qualification-20261009.service`, invocation
`d3192c769f99485c899db6298c579d94`, supervisor PID **1456651**. Its
[master log](../build/counter_safe_heap_qualification_actual_20261009.log) will
identify the own report directory once completed source admission finishes.
Nice 15, memory-high 1.5 GiB/max 2.5 GiB, swap-max zero, core-zero/OOM stop and
a separate 10,800-second outer budget bound this fresh small qualification.
No live original job or native test limit is extended. **No native qualification
PASS is claimed yet.**

The [counter-safe full placement handoff](../tools/openxc7/place_counter_safe_prefix_shared_board.py)
passes **24 host guards**: five new controls, all thirteen unchanged shared
full-target/BEL/capacity controls and all six unchanged native HeAP controls.
It rejects incomplete fresh qualification before output/native execution, uses
the same full literal physical input, and preserves the original 43,200-second
native full-placement limit, exact -2 part, 50 MHz, seed 3588 and all 515 DSPs.
In addition to unchanged placement checks, it requires the actual initial native
packing checksum to match the completed own packing run (`0x0f489b2b`) and the
actual full native log to report the corrected finite limit 2,147,483,646.
Missing, old 10,000, zero/unlimited, out-of-range or ambiguous limits remain
explicit failures. The handoff has **not executed full placement**. The earlier
route/frame handoffs are not automatically admitted for this new executable;
they still require their own source-bound continuation and actual full placement.

No standalone `SHA256SUMS` file is created. Source/artifact bindings remain in
the existing JSON evidence format. There is still no accepted full shared
numerical result, routed fit, complete timing/electrical/DRC signoff, FPGA
bitstream or programming action.

At **02:00 HKT**, the fresh native qualification's
[own report](../build/openxc7/counter-safe-heap-qualification-1791482371308735092/report.json)
exists after the initial fail-closed admission. The same supervisor is still
live in its original source-admission stage; no native qualification result
is accepted yet. The combined shared-prefix suite has passed **236 methods in
44.345 seconds** after adding the placement handoff and additional qualification
guards. Generated checks pass.

The separate [counter-safe full-route handoff](../tools/openxc7/route_counter_safe_prefix_shared_board.py)
now passes **42 host controls in 16.295 seconds**, including all 38 unchanged
shared/native/v2/export route guards. It derives the original procedure with
reversible output-path/parent-chain-record changes only. Admission retains all
full-size metadata requirements, but now requires this own placement enumeration,
fresh counter-safe qualification, unchanged packed checksum and exact logged
finite limit. It rechecks the actual completed one-expression build/source and
returns its exact unchanged qualified parent only for comparison with the
independently qualified corrected-DSP v2 route base. Actual routing still uses
that same separately qualified imported-checkpoint scanner, never executes
placement, and retains full scan/connectivity, all BEL/logical endpoints, clock
fanout, 515-DSP/six-BRAM feature comparisons and the unchanged 43,200-second
native route limit. Report path normalization remains confined to own artifacts
and binds the original report bytes, never an execution-input projection.
No full placement, scan, route or frames are executed by these controls.

The [fresh combined host-control log](../build/counter_safe_heap_shared_controls_actual_20261009.log)
now records **278 methods PASS in 56.601 seconds** with
`python3 -B -W error -m unittest discover -s tests/cmac -p 'test_prefix_shared*.py' -v`.
Generated checks pass again. The actual new engine/qualification directories
contain no `SHA256SUMS*` files. At **02:02 HKT**, the same native qualification
supervisor remains live in source admission (no native commands accepted yet),
and the own full numerical compiler plus original placement/mapped mode-5 jobs
remain live. No old result is promoted, restarted or copied forward. The latest
whole production `make test` result remains the separate unchanged-source FAIL
at the original Verilator compilation limits described above; host controls do
not replace those pending HDL/numerical or physical gates.

### 2026-10-09: shared frame admission prepared; exact old-capacity job retired

The [own full shared-route verifier](../tools/openxc7/verify_counter_safe_shared_route.py)
and [strict frame-conversion handoff](../tools/openxc7/convert_counter_safe_shared_frames.py)
now pass **25 host controls in 16.365 seconds**, including all nineteen unchanged
full-frame/small-clock/corrected-database guards. The verifier derives the complete
original actual-route verification body with reversible path/namespace/current
census changes. It requires this producer's own completed full-route enumeration,
**523,410** complete cells/BELs/logical-cell identity, fresh counter-safe engine
qualification, actual full native scan/connectivity and the unchanged complete
515-DSP/six-BRAM/clock comparisons. The older 538,118-cell route and all small,
RUNNING or build-only reports are refused.

The frame procedure changes only admission/profile/output and its own selected
DSP/BRAM input path. It still converts the actual unchanged raw FASM, never a
comparison target; requires all **8,240 corrected DSP features**, every actual
source-bound HCLK bit, complete exact-part tilegrid/frame coverage and both actual
frame-corruption negatives; and preserves the original **43,200-second** converter
limit. These controls perform no full native route, full frame conversion,
bitstream assembly, physical signoff or FPGA access.

The [fresh combined shared/frame/audit control log](../build/counter_safe_heap_shared_and_frame_controls_actual_20261009.log)
records **306 methods PASS in 87.755 seconds**. Three new read-only original-job
audit guards pass, and generated checks pass. No production RTL, raw encoder,
input/oracle bytes, numerical expectation or native legality/clock check changes.

The [actual read-only original capacity audit](../build/openxc7/original-capacity-supersession-audit-1791483476679187066/report.json)
revalidates every original bound source and recomputes the complete group matching
and minimum cut. It confirms the **original unshared 538,118-cell graph** needs at
least **302,998 LUT positions versus 298,600 available** under the exact bound
native LUT policy. It matches the one actual running worker's unit/invocation,
supervisor/child PIDs, complete argv, executable bytes, physical input bytes,
linked LUT-policy evidence and actual packing checksum `0x68a070d4` to that
capacity proof. This is not the shared graph; the complete C32/K16 shared target
retains all 512 products and has a different checksum/bound.

After a second immediate live check, **only** the original supervisor **1416947**
was sent SIGTERM. Its own handler killed/waited for native child **1417350** and
wrote the actual terminal report at **02:19:24 HKT**: **FAIL**, `SystemExit(143)`,
native return code **-9**, **21,586.775 seconds**. The unit is terminal failed/
exit-code, main PID zero and supervisor exit status 143; both old handles are
gone. This is deliberate retirement after a proven capacity conflict, **not** a
native rejection or expiration of its original 43,200-second budget. No checkpoint
existed or was discarded. [Retirement evidence](../build/openxc7/original-capacity-supersession-audit-1791483476679187066/RETIREMENT.md)
preserves the pre-signal report/log/unit snapshot separately from the producer's
own final report. No original source, artifact or error expectation is removed,
changed or promoted.

The retired unit used about **1.4 GiB RAM and 3.5 GiB swap**; the following host
sample showed about 4.2 GiB available RAM and 3.5 GiB free swap. The actual new
qualification, shared numerical compiler and original mapped mode-5 numerical
replay remain live. No other project/job, FPGA/flash or host-wide setting is touched.

### 2026-10-09: measured private-job soft-memory throttling relieved

At about **02:25 HKT**, current cgroup telemetry shows both new jobs above their
soft memory thresholds, with zero file cache, positive `memory.events:high` and
no OOM/OOM-kill events. The native qualification has **1,696,198,656 bytes anon**
versus a 1,610,612,736-byte soft threshold, **109,448** high events and full memory
PSI avg10 **67.55%**. The shared numerical compiler's cgroup has **10,850,467,840
bytes anon**, 11,981,238,272 bytes total charged memory, **120,274** high events,
and full memory PSI avg10 **81.04%**. Its soft threshold is 10,737,418,240 bytes.
Both native/compiler process handles are live; this is scheduling pressure,
not a terminal compile/test failure or numerical result.

Only the private transient services' **soft** `MemoryHigh` properties are updated
at runtime: qualification **1.5→2.25 GiB**, numerical compilation **10→12 GiB**.
Their same main PIDs/invocations continue; neither is restarted. Qualification
hard memory **2.5 GiB**, swap **zero**, three-hour outer runtime and original
600/3,600-second native limits are unchanged. Numerical hard memory **14 GiB**,
swap **2 GiB**, 900,000-second outer runtime and original 21,600-second compile/
86,400-second per-mode limits are unchanged. Nice/core-zero/OOM policy, source,
input/model/oracle bytes and all FPGA/physical gates are unchanged. The original
mapped numerical job is not altered. Subsequent process states are running rather
than the preceding persistent I/O-wait states; completion still requires actual
native/numerical evidence. No standalone `SHA256SUMS` is produced.

### 2026-10-09: actual qualification OOM retained; fresh unchanged 4 GiB attempt

The first counter-safe qualification actually passes the compiled getter/census,
ten software guards and generated checks. The forced illegal-pair control returns
the required 125 in 66.593 seconds; fresh valid-forced, invalid-free and counter
placements return zero in 96.020, 92.103 and 91.973 seconds. Their original
complete placement/refinement/legality checks and 1,024 LUT-output comparisons
pass. These are small placement results, not the qualification's routing result.

At about **02:49:43 HKT**, subsequent private-job telemetry still shows substantial
soft-limit reclaim. Only `MemoryHigh` is raised to each existing hard cap:
qualification **2.25→2.5 GiB**, own numerical compilation **12→14 GiB**. The same
PIDs/invocations, hard memory/swap limits and all tool deadlines remain unchanged.
No source, input, expectation, native guard or original mapped-numerical setting
changes. This exposes the qualification's actual working-set limit: at
**02:49:48 HKT** systemd records a kernel OOM kill, and its supervisor writes the
[terminal FAIL](../build/openxc7/counter-safe-heap-qualification-1791482371308735092/report.json)
at **02:49:50.785855 HKT** with `SystemExit(143)`, small native return **-9** and
**2,362.012 seconds**, before its unchanged 3,600-second deadline. The service
result is `oom-kill`, main PID zero, exit status 143 and peak charged memory
**2,684,354,560 bytes**. No routed/FASM completion or qualification PASS is claimed.
The complete attempt and every accepted/rejected control remain preserved.

A **new**, bounded transient unit
`rknpu-counter-safe-heap-qualification-memory4g-20261009.service` starts at
**02:51:44 HKT**, invocation `c8a5eb7512bb43079823d13b1d335e18`, supervisor
**1461528**. Its [own actual master log](../build/counter_safe_heap_qualification_memory4g_actual_20261009.log)
records the same frozen qualification CLI, same completed isolated engine and
same byte-bound fixtures. It repeats source admission, all software/native
controls and small route from scratch; no previous success is copied forward.
This new attempt uses soft/hard **4 GiB**, swap zero, Nice 15, core zero,
OOM-stop, three-hour outer limit and 30-second stop limit. Original 600-second
placement and 3,600-second route budgets stay unchanged. The measured host sample
before launch has approximately 4.4 GiB available RAM; no full-placement worker
is added concurrently. The own full numerical compilation and original mapped
mode-5 replay keep their existing handles and tests. Full placement/route,
numerical, timing/electrical/DRC, frame and bitstream gates remain open.

At **02:55:25 HKT**, the new qualification creates its
[own report](../build/openxc7/counter-safe-heap-qualification-1791485725278039585/report.json)
after the first fail-closed admission. It is **RUNNING** in the second source
admission, not QUALIFIED; no native command is accepted yet. The same supervisor
1461528 and original own numerical compiler 1451483 remain live. Generated
checks pass after these documentation updates; no executed helper or production
RTL is edited.

### 2026-10-09: 4 GiB route OOM preserved; successful donor resource profile checked

The [separate 4 GiB qualification](../build/openxc7/counter-safe-heap-qualification-1791485725278039585/report.json)
actually binds all **3,742** sources, passes the compiled getter/census and ten
software guards/generated checks, rejects the forced illegal pair with native
125 in **65.819 seconds**, and passes valid-forced/invalid-free/counter in
**94.703/97.853/86.808 seconds**. All three positive placement/refinement/legality
checks and **1,024** LUT comparisons complete. It then runs the unchanged small
native P&R command under the original 3,600-second deadline.

At **03:09:59 HKT**, systemd records a kernel OOM kill during routing-resource
setup. The producer saves **FAIL** at **03:10:02.390835 HKT**,
`SystemExit(143)`, native **-9**, **222.428 seconds**. Its same invocation
`c8a5eb7512bb43079823d13b1d335e18` is terminal `oom-kill`, main PID zero,
exit status 143 and peak memory **4,294,967,296 bytes**. No routed/FASM result,
qualification PASS or timeout is inferred. Both insufficient-cap attempts and
their actual logs/reports remain preserved; no native result is inherited.

The still-available actual donor service
`rknpu-native-heap-typed-inspection-20261008.service`, invocation
`827176e3a3c84a6fba18c04ddb8f4d17`, establishes the appropriate resource profile.
It had a **6 GiB hard memory cap**, 4 GiB soft threshold and 2 GiB swap cap;
recorded peak charged memory **4,295,229,440 bytes** and peak swap
**648,708,096 bytes**. Those are separate recorded peaks, not a simultaneous
working-set sum. Its [actual native route](../build/openxc7/native-heap-typed-inspection-1791459029556778888/report.json)
returned zero in **259.754 seconds** under the same 3,600-second limit.
The donor's later parser-gate failure is unchanged, not promoted into whole
qualification acceptance. This resource evidence explains why the fresh
no-swap 4 GiB profile was inadequate; it does not prove a new route.

After rechecking that the preceding attempt is terminal and the production
revision/executable still match the completed isolated build, a new transient
unit `rknpu-counter-safe-heap-qualification-memory6g-20261009.service` starts at
**03:13:10 HKT**, invocation `840f56752c6d411e9554ef52f6e623ed`, supervisor
**1462964**. The measured host has **10,774,120 KiB available RAM** and
**2,426,736 KiB free swap** before launch. Its
[own master log](../build/counter_safe_heap_qualification_memory6g_actual_20261009.log)
uses the same frozen CLI/executable/fixtures and repeats every source, software
and native control. Soft/hard memory is now **6 GiB**, swap max **2 GiB**, with
the same Nice 15/core-zero/OOM-stop/three-hour outer/30-second stop profile.
All original 600/3,600-second native deadlines, legality/refinement/LUT/DSP/BRAM/
clock gates and the full C32/K16 target remain unchanged. No full placement is
launched without actual qualification. The existing own numerical compiler and
original mapped mode-5 replay keep their handles. No standalone `SHA256SUMS`,
bitstream or FPGA/flash access occurs. The [new own report](../build/openxc7/counter-safe-heap-qualification-1791486974423403401/report.json)
is created at **03:16:14 HKT** after the first admission; it remains RUNNING in
source admission, not native qualification acceptance. Generated checks pass.

### 2026-10-09: fresh small engine QUALIFIED; full target launched; numeric OOM retained

The [fresh 6 GiB qualification](../build/openxc7/counter-safe-heap-qualification-1791486974423403401/report.json)
completes **QUALIFIED at 03:33:00.281672 HKT**. It repeats all controls from
scratch: required illegal-pair native 125 in 62.706 seconds; positive
valid-forced/invalid-free/counter in 93.580/94.034/91.389 seconds; all 1,024
LUT comparisons; and actual four-DSP/six-BRAM P&R/FASM in **329.493 seconds**,
return zero. All **7,869** parsed native features, four DSP configurations,
six BRAM configurations and both source-defined HCLK fanout contracts pass the
unchanged feature checks. Its 3,742 source bindings and twenty own artifacts are
checked, with identical before/after/current production revision. A separate
current `verify_metadata` call also passes. Earlier OOM reports stay FAIL; no
native result is inherited. Small qualification is not full fit or signoff.

After checking that complete qualification, the unchanged whole 523,410-cell
packed target and current host memory, the actual full-size handoff starts at
**03:39:43 HKT** in
`rknpu-full-prefix-shared-counter-safe-heap-place-20261009.service`, invocation
`161c3085c51f41a78e33953d97979a3e`, supervisor **1466282**. Its
[own report](../build/openxc7/full-prefix-shared-counter-safe-heap-place-1791488628202327384/report.json)
and [actual master log](../build/full_prefix_shared_counter_safe_heap_place_actual_20261009.log)
retain C32/K16, sixteen kernels, **512 CMAC plus three shell DSPs**, exact
XC7K480T FFG1156-2, 20 ns/50 MHz and seed 3588. It revalidates the completed new
qualification before any output/native tool, then repeats full input/source
admission. Full native execution retains **43,200 seconds**, normal refinement,
all native guards and required actual packing-checksum/counter-limit evidence.
It uses the same 12 GiB address-space bound, private memory-high/max **8/10 GiB**,
swap max **2 GiB**, Nice 15, core zero, OOM stop, 30-second stop and **54,000-second**
outer limit. Before launch the host has **24,432,780 KiB available RAM** and
**3,633,172 KiB free swap**. The report remains **RUNNING/source admission**;
no full placement or route is accepted yet.

The [own numerical compiler](../build/rknpu-dsp-prefix-shared-observed-board/1791479366724278074/report.json)
has independently finished **FAIL at 03:32:44.223346 HKT**. Its service records
a kernel OOM kill at 03:32:43, terminal `oom-kill`, main PID zero, supervisor
exit status 143, peak memory **15,032,385,536 bytes** and 2 GiB peak swap.
The original compile step records **8,590.275 seconds**, shell return **-15**,
`SystemExit(143)`; its unchanged 21,600-second deadline is not reached. No
compiled executable, negative or positive mode is accepted. Sources, raw inputs,
vendor models, expected data, partial artifacts and logs stay unchanged.

The completed baseline compile's still-available retry service used a **27 GiB
hard cap** and recorded aggregate service peak **29,046,767,616 bytes** plus
**1,618,735,104 bytes peak swap**. Those service peaks include its other phases
and cache, not isolated compiler RSS; its later mode-0 failure remains FAIL.
This evidence and the fresh 14 GiB OOM justify serializing the next substantial
numeric compile behind physical placement rather than repeating the insufficient
profile or adding simultaneous memory demand. The original mapped mode-5 replay
remains live with its unchanged handle. Full numerical/physical/timing/electrical/
DRC/frame/bitstream gates remain open; no standalone `SHA256SUMS` or programming
occurs.

### 2026-10-09: full native packing and corrected main search limit observed

The same full-target unit/supervisor **1466282** is now running actual native
child **1467616**; all 4,887 admitted source bindings remain in its
[own report](../build/openxc7/full-prefix-shared-counter-safe-heap-place-1791488628202327384/report.json).
Its fresh 24 placement controls, six unchanged HeAP guard controls, generated
checks and native version commands return zero. Native packing retains
**488,080 logical LUTs, 515 DSPs and six RAMB36E1s**, and logs the unchanged
packing checksum **`0x0f489b2b`**. Logical-LUT/virtual-slot utilization is not
physical-position fit.

At **04:11 HKT**, the actual native log has completed initial analytic iterations
0–3, with wire lengths **149,273 / 133,629 / 144,810 / 128,863**, then enters
the main analytical placer with the exact finite logged limit
**2,147,483,646 attempts per cell**. The 419,252 initial movable-cell count is
not the whole 523,410-cell census. A fresh read-only call to the prepared full
`full_log_checks` verifies the actual unchanged packing checksum, full census,
unique main-limit statement and preserved finite rejection rule. This confirms
the one-expression correction is applied in the actual full-size worker,
not a completed placement or proof that it fits. The job is still
**RUNNING/native_place** under its original 43,200-second deadline. The original
mapped numerical mode-5 worker is also live; no new full numerical, physical
signoff, route, frames, bitstream or programming result is accepted.

### 2026-10-09: actual small native packet encoding and full-device data/ECC roundtrip

The separate [encoding control](../tools/openxc7/probe_native_heap_bit_encoding.py)
admits only the completed, source-bound four-DSP/six-BRAM small native frame
report. It does not change or substitute for the live full C32/K16 circuit.
It rechecks the donor's existing exact-part assembler/decoder qualification,
actual tool source revisions, binary bindings, original seed 3588 and every
source/artifact before and after execution. Its four wrapper control methods
and generated checks pass; these are host controls, not RTL/FPGA evidence.

The [actual own report](../build/openxc7/small-native-heap-bit-encoding-1791491349869461344/report.json)
finishes **PASS_SMALL_NATIVE_HEAP_PACKET_DATA_AND_FRAME_ECC_NOT_FULL_BITSTREAM_OR_SIGNOFF**
at **04:33:39.672630 HKT**, with 4,052 source bindings and unchanged production
revision. Its transient unit
`rknpu-small-native-heap-bit-encoding-20261009.service`, invocation
`3a744994a5ad4aa995eed574009b770f`, supervisor **1471146**, is terminal
inactive/success, actual exit zero. It used Nice 15, a 1/2 GiB memory-high/max
profile, no swap, 2 GiB address-space bound, core zero, OOM-stop and 7,200-second
outer limit. Each native/control command retains its 600-second deadline.
The [actual master log](../build/small_native_heap_bit_encoding_actual_20261009.log)
and executed helper/control snapshots are retained.

Native `xc7frames2bit` assembly returns zero in **7.170 seconds**, qualified
native decoding in **7.277 seconds**. The full data/ECC comparison returns zero
in **51.838 seconds**: all **46,336** legal frames/**4,679,936** words equal the
validated 45,892 source frames plus exactly 444 zero-filled frames, with **8,621**
nonzero words including calculated frame ECC. Actual decoded comparison-only
copies flip frame `0x0` word 0 and word 50 independently. Both comparison
commands return the required one and reject the exact changed word; these
negatives never modify original frames, assembled packets or routing inputs.

The small packet header names `xc7k480tffg1156-2`, payload **18,735,004 bytes**.
Its filename explicitly contains `small-control.NOT_FOR_PROGRAMMING.unverified`.
It is an offline encoder sample, not a full-array/test-ready image. Configuration
CRC, full-target numerical acceptance, timing/electrical/DRC signoff and hardware
programming remain false. No standalone checksum manifest, global tool change,
constraint relaxation, FPGA/JTAG/flash access or full native P&R rerun occurs.

### 2026-10-09: observed mux-cluster geometry conflict; exact attempt retired; own replay restarted

The same full native PID1467616 remained CPU-active without another main
iteration. Three brief read-only GNU gdb17.2-4.fc44 attachments, with auto-load/
debuginfod/inferior function calls disabled, locate strict cluster legalization.
The actual counter snapshots show **168,590,974** then **203,406,596** attempts,
radius **415** (device max309x415), **2,335** legalization entries, and unchanged
root `rk_mapped_cell_86668.rk_mapped_cell_22977`. All attachments detach normally;
no inferior value or live helper is changed. The nine observed members include
five `SELMUX2_1` roles at relative z **0/31/47/-1/15**, plus four LUT roles.

The [actual read-only binary geometry audit](../build/openxc7/observed-native-mux-geometry-1791492921043041558/report.json)
binds the exact native executable, argv, source layout, constids, database and
observed debugger snapshot. Its four host controls pass, including valid-F8
geometry and rejected extra-mux/aliased/changed-snapshot negatives. It enumerates
**all 52 root-BEL/tile-type cases**, including optimistic non-slice mux roots,
and finds **zero compatible candidates**. No occupancy, control-set or timing
restriction is needed for this conflict: the required relative child roles
do not exist. The actual source uses the BaseArch relative cluster placement
API. This establishes an intrinsic conflict for this observed packed cluster,
not whole-target infeasibility or a corrected implementation PASS.

Source inspection of the executed engine's bound `pack.cc` identifies the
feed-through path to investigate: `feed_through_muxf` connects the existing
driver directly into a new mux; `legalise_muxf_tree` then continues without
recursively legalizing that newly created mux. The observed tree contains
foreign original muxes below those new muxes at the incompatible offsets.
An isolated correction and actual native reproduction/qualification are still
required; no global source/tool or legality gate is changed here.

After rechecking audit bindings/artifacts, current service invocation, executable,
argv and PPID, only supervisor **1466282** receives SIGTERM at **04:58:13.391750 HKT**.
Its own [placement producer](../build/openxc7/full-prefix-shared-counter-safe-heap-place-1791488628202327384/report.json)
finishes **FAIL at 04:58:16.233350 HKT**, `SystemExit(143)`, native **-9**,
**3,982.258 seconds**. The unit is terminal failed/exit-code143 and both selected
PIDs are gone. Its 43,200-second native deadline is not exhausted; no native
rejection is claimed. The [separate retirement record](../build/openxc7/observed-native-mux-geometry-1791492921043041558/RETIREMENT.md)
preserves this distinction. All sources/logs/artifacts stay intact. The original
mapped mode-5 PID1418264 remains running; the redundant private streaming-JSON
inspection is stopped after the same exact cell attributes are obtained by
read-only text inspection. No unrelated worker is stopped.

Freed placement memory permits a fresh own shared numerical attempt. Admission
observes **25,527,108 KiB available RAM** and **4,016,896 KiB free swap**, requiring
at least 24 GiB RAM/3.5 GiB swap and 28 GiB combined capacity (2 GiB headroom
beyond the private 24 GiB RAM/2 GiB swap hard bounds). The new unit
`rknpu-full-prefix-shared-own-numerical-memory24g-20261009.service` starts
**05:01:12 HKT**, invocation `d07305686ff1449da256e30a8ba8af33`, supervisor
**1474248**. It uses memory-high/max **22/24 GiB**, swap max **2 GiB**, Nice15,
core-zero/OOM-stop/30-second stop. The original outer **900,000 seconds**, compile
**21,600 seconds**, every mode **86,400 seconds**, 24 GiB address-space bound,
literal hardware/bench/vendor/raw inputs/expected data and mandatory wrong-golden
negative/all nine positives are unchanged. The previous 14 GiB OOM stays FAIL.

Its [actual own report](../build/rknpu-dsp-prefix-shared-observed-board/1791493285871405865/report.json)
admits **1,248** source bindings, repeats all software/generation/tool/model
checks successfully, and is **RUNNING/compile**, shell PID1474281. It does not
reuse an old executable or numerical result. No full placement, corrected pack,
numerical acceptance, physical/timing/electrical/DRC/CRC signoff or test-ready
bitstream is claimed; no `SHA256SUMS` is created or card programmed.

### 2026-10-09: isolated recursive mux candidate prepared; actual build/probe in admission

The [new isolated builder](../tools/openxc7/build_mux_feedthrough_candidate.py)
changes only the feed-through insertion branch in a private `pack.cc` copy:
save the newly created mux pointer, call `legalise_muxf_tree` on that mux, and
retain the original `continue`. Whole-source reversal proves no other change;
all assertion/legality/warning gates and default/global tools remain intact.
Only `pack.cc.o` is selected for replacement relative to the qualified
counter-safe engine. The old engine must first relink byte-identically.

Five new source/admission methods pass and `make generated-check` passes.
These are host controls, not native or HDL results. The separate test-only
primitive fixture exports both original MUXF7 outputs as well as the MUXF8
output, forcing shared-root feed-through insertion. The new vendor-model bench
enumerates 16,384 four-state vectors and both floating/ground inactive wrapper
input cases, with a mandatory actual wrong-output negative. The builder must
execute that bench and both old/new native pack-only probes afresh; none has
completed at this status snapshot.

Unit `rknpu-recursive-mux-feedthrough-build-20261009.service` starts at
**05:18:28 HKT**, invocation `eaacaceac800482a84a1b2e678d0a7e9`, supervisor
**1475051**. Admission observes 13,395,708 KiB available RAM and 3,061,724 KiB
free swap. Subtracting the running numerical unit's remaining RAM/swap caps
leaves 2,180,364 KiB, exceeding the required 2 GiB for this 1 GiB job plus
1 GiB headroom. The new unit uses memory-high/max 1 GiB, no swap, Nice15,
core-zero/OOM-stop/30-second stop and a two-hour outer limit. Native/compiler
steps retain 1,800 seconds, with shorter limits for software/version/HDL controls.
The [actual master log](../build/recursive_mux_feedthrough_build_actual_20261009.log)
is separate. At 05:21:03 HKT the supervisor is CPU-active in inherited source
revalidation, with about 39 MB current cgroup memory; no native result is
claimed. Both full numerical jobs remain live and unchanged.

This is not a qualified replacement for the old full placement/route helpers:
fresh mux placement, all original illegal-pair/positive/refinement/LUT/DSP/BRAM/
clock/FASM gates, a newly characterized full packed graph and physical signoff
remain required. No old expectation is changed to accept the new graph, no
full native job is restarted, no checksum manifest is written and no FPGA or
flash is accessed.

### 2026-10-09: first mux bench elaboration failure retained; explicit equivalent bench passes smoke check

The [first actual candidate attempt](../build/openxc7/recursive-mux-feedthrough-engine-1791494566705295223/report.json)
finishes **FAIL at 05:22:54.146970 HKT**. Five software controls, generated check
and recorded compiler/Icarus/vvp versions return zero. `compile_mux_equivalence`
returns **12 in 0.270 seconds**: Icarus13.0 rejects generated-index output
connections in the test-only mux instances. The unit ends exit-code1 with
86,659,072-byte peak memory, not OOM. No old/new native pack probe, byte-parent
relink or candidate object/ELF build occurs. Failed source/report/logs are kept;
this does not establish a production RTL/numerical or mux-correction failure.

The [new explicit-instance runner](../tools/openxc7/build_explicit_mux_feedthrough_candidate.py)
keeps the original procedure byte-reversible except its output namespace.
Its namespace selects a new test-only bench/control file. Two extra controls
prove unchanged exhaustive expectations/negative body and native build/guard
functions; all five original controls remain, **seven passing in total**.
The four-state enumeration and original/candidate logic are unchanged. Only
the six test mux instances are written explicitly with indices0/1, rather
than referencing the generated index. Production RTL and vendor models are
not edited. `make generated-check` passes.

A separate [actual smoke check](../build/mux-explicit-smoke.sdHZjF/positive.log)
compiles this bench successfully with Icarus13.0. Its
[wrong-output negative](../build/mux-explicit-smoke.sdHZjF/negative.log) returns
exactly **1**, `MUX_EQ_MISMATCH vector=0 inactive=0`. The positive returns
**0**, `PASS_MUX_FEEDTHROUGH_FOUR_STATE vectors=16384 comparisons=32768`.
This is narrow combinational vendor-model equivalence, not full mapped CMAC,
timing, FPGA or RK-silicon proof. These smoke logs are not reused by the fresh
source-bound build, which must repeat compilation and both actual simulations.

Unit `rknpu-recursive-mux-feedthrough-explicit-build-20261009.service` starts
**05:25:38 HKT**, invocation `d3035a0b2078490799ceac74138b68c6`, supervisor
**1476336**. Fresh admission observes 11,314,408 KiB available RAM/3,056,640 KiB
free swap; after reserving the running numerical unit's remaining caps,
2,148,672 KiB exceeds the unchanged 2 GiB private-job-plus-headroom gate.
The retry retains 1 GiB high/max, zero swap, Nice15, core-zero/OOM-stop/30-second
stop, two-hour outer/1,800-second native/compiler limits and all old error,
source, parent-byte-identity, clock/seed and probe expectations. The new
[actual master log](../build/recursive_mux_feedthrough_explicit_build_actual_20261009.log)
is separate. Both full numerical jobs continue without restart. Native
replacement qualification, new full packing/placement/routing and test-ready
bitstream remain unachieved; no standalone checksum file or card access occurs.

### 2026-10-09: actual old mux tree reproduced; I/O-name probe corrected; fresh qualification harness prepared

The [actual explicit-instance attempt](../build/openxc7/recursive-mux-feedthrough-explicit-engine-1791495022548762731/report.json)
finishes **FAIL at 05:30:51.513589 HKT**, `KeyError('output_pad0')`. Its seven
controls/generation/tool-version checks pass; HDL compilation returns zero
in 0.232 seconds, the exact wrong-output negative returns one in 0.254,
and 16,384 four-state vectors/32,768 comparisons pass in **4.315 seconds**.
Parent relink returns zero in **11.294 seconds** and is byte-identical to
the qualified counter-safe ELF. The actual old native pack returns zero in
**3.143 seconds**. This failed overall attempt is not a qualified replacement.
No candidate object/ELF is compiled or full placement executed.

Reading that actual saved parent graph shows both inserted MUXF7 wrappers
driven immediately by the original shared `left`/`right` MUXF7s, reproducing
the extra mux level. Its primitive counts are five SELMUX2_1, four SLICE_LUTX,
four pads, three output/one input buffer and one each pseudo-GND/VCC. Original
shared outputs are still exported. This is the actual native old pack, not
a synthetic expected packed circuit or a new placement result.

The source-bound XC7 I/O decomposition names each fixture OBUF
`output_padN$intcell$OBUF`: `is_se_obuf` is true, `is_hierarchy` false, and
`int_name` inserts `$intcell$`. The original failed checker assumed the old
name survived. The [new comparison-only checker](../tools/openxc7/mux_native_io_probe.py)
changes exactly that lookup, reversibly; all root/wrapper/identity truth,
original output connectivity and pack-only stage guards remain literal.
Four extra controls retain every old control, **11 passing**, including
wrong export, identity, foreign driver, stage and old-name rejection.
No execution input or old expected-error policy changes. The original helper,
bench, failed source/logs and graph stay intact.

At the first launch observation, the unchanged private-job/headroom gate refuses
admission: available-plus-free-swap minus the numerical unit's remaining caps
is 2,077,232 KiB, below 2,097,152 KiB. No unit/tool is launched and no threshold
is relaxed. Later fresh admission sees available RAM **11,276,724 KiB**,
free swap **3,064,220 KiB**, remaining numerical caps **12,222,420 KiB** and
remainder **2,118,524 KiB**. Unit
`rknpu-recursive-mux-feedthrough-native-io-build-20261009.service` starts
**05:33:31 HKT**, invocation `771a607b244f4ceea758315ab560f233`, supervisor
**1476955**. It retains the same 1 GiB memory-high/max, zero swap, Nice15,
core-zero/OOM-stop/30-second stop, two-hour outer and native/compiler step
limits. The [separate actual master log](../build/recursive_mux_feedthrough_native_io_build_actual_20261009.log)
does not inherit an old result. At 05:35:21 HKT it remains CPU-active in input
revalidation, about 304 MB current cgroup memory. Both numerical jobs are live.

The [new qualification procedure](../tools/openxc7/qualify_recursive_mux_feedthrough.py)
has **13 passing host methods** plus `make generated-check`. It admits only
a completed source-bound, byte-parent-reproduced native-I/O-name candidate,
revalidates actual old/new packed probe artifacts, and preserves all original
exact illegal-pair rejection, three positives, normal refinement, 1,024 LUT
truth comparisons, compiled beta certificate and four-DSP/six-BRAM native
route/clock/FASM checks. It adds a separate corrected-mux native placement
at the same part/50 MHz/seed3588, checking actual cell census, all unique BELs,
two identity LUTs/four truth comparisons, grounded wrapper selects and all
original output exports. Missing/aliased BEL, wrong clock/placer/stage/route,
truth/connectivity/select/census corruption remain errors.

That procedure has not been launched: the candidate ELF is not yet complete,
and the known adequate six-GiB native qualification profile is not concurrently
admitted against the large numerical compiler. Host controls and old-artifact
parser comparisons are not new native qualification. Full updated packing,
placement/routing, numerical/timing/electrical/DRC/CRC acceptance and a test-ready
bitstream remain pending. No standalone checksums or FPGA/flash access occurs.

At **05:39:01 HKT**, the same native-I/O-name unit has admitted **3,775**
source bindings and created its [actual producer report](../build/openxc7/recursive-mux-feedthrough-native-io-engine-1791495496575181522/report.json).
All 11 controls/generation/version commands pass; fresh HDL compilation returns
zero in 0.268 seconds, the exact wrong-output negative returns one in 0.167,
and 16,384 vectors/32,768 comparisons return zero in **5.556 seconds**.
Parent relink returns zero in **11.745 seconds** and is byte-identical;
the old native pack returns zero in **2.674 seconds**, and its actual graph
passes the source-evidenced I/O-name checker while reproducing the missing
identity LUTs. The isolated original-flags `pack.cc` compile is now RUNNING,
compiler PID1477237/cc1plus1477238. No new ELF/candidate packed graph or fresh
placement qualification has been accepted. The same numerical compiler
PID1474284 and baseline mode-5 PID1418264 remain live. No old evidence is copied
forward as a result for the new engine.

The same isolated engine finishes **BUILT at 05:42:16.309012 HKT**, unit
inactive/success/exit0 with supervisor/compiler gone. The original-flags
one-object compile returns zero in **133.523 seconds**, link in **12.930**,
native version in 0.191 and actual new pack in **4.277**. All 14 mandatory
commands pass their exact codes, including the genuine negative code1.
The executable remains local to this attempt, with embedded report fingerprint
`c48a0226838228e7ac9a3f467115b6ec92ef5b6cc0026cb638ef5ced4900d15e`.
There is no global/default engine replacement or checksum manifest.

The actual new fixture contains **six** LUTs rather than four, with otherwise
unchanged primitive census. Each root input now passes through its existing
inserted MUXF7, whose I0 is driven by an identity LUT rather than the foreign
original MUXF7 directly. The two original shared mux outputs and root output
remain exported. Actual old/new graphs pass the strict source-evidenced
comparison; this is a native pack result, not a synthetic corrected graph or
native placement. All inherited/current source bindings revalidate, and
production ROOT remains `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.

The [separate small native placement probe](../tools/openxc7/probe_recursive_mux_native_placement.py)
has **14 passing host methods** and a passing generated check. It revalidates
the completed build/actual old-new probes and keeps native part/50 MHz/seed3588,
fatal warnings and normal HeAP refinement; its placement checker is the same
prepared qualification checker. It explicitly cannot count as all-original-
gates backend qualification or full C32/K16 fit. The latest prospective launch
observes available11,211,100/free-swap3,100,604/remaining-numerical-caps12,221,112
KiB, remainder **2,090,592 KiB**, below the unchanged **2,097,152 KiB** gate.
The command exits75 before unit creation; no native process, master log or
placement attempt is started, and no threshold is relaxed. Both full numerical
jobs remain live. The full six-GiB backend qualification is still not launched.

Later fresh admission sees available **8,104,848 KiB**/free swap **3,064,636 KiB**,
remaining numerical caps **9,058,912 KiB**, remainder **2,110,572 KiB**. It passes
the same 2,097,152-KiB gate without relaxation. Unit
`rknpu-recursive-mux-native-placement-probe-20261009.service` starts
**05:47:56 HKT**, invocation `17cadad7b94c48449f4b269931684a40`, supervisor
**1477690**, with 1 GiB high/max, no swap, Nice15, core-zero/OOM-stop/30-second
stop and two-hour outer limit. Native placement retains its 3,600-second
deadline and all normal refinement/warning/part/clock/seed guards. The
[actual master log](../build/recursive_mux_native_placement_probe_actual_20261009.log)
is separate. It starts in source/build admission, before native placement;
there is not yet a new placed artifact or placement PASS. This bounded single
mux probe does not replace the full original-gates six-GiB native qualification,
which still has not been launched, or the required full C32/K16 physical build.

### 2026-10-09: small mux placement PASS; full qualification launched; numerical allocation FAIL

The [actual small mux probe](../build/openxc7/recursive-mux-native-placement-probe-1791496225072484294/report.json)
finishes **PASS_SMALL_RECURSIVE_MUX_NATIVE_PLACEMENT_NOT_FULL_BACKEND_QUALIFICATION_OR_FIT**
at **05:53:29.072016 HKT**, on the same unit/invocation, now inactive/success.
The actual native placement returns zero in **75.657 seconds**; fresh controls,
generation and version commands also return zero. All **21 cells/21 unique BELs**,
two inserted identity LUTs, four truth comparisons, grounded wrapper selectors
and three original mux output exports are checked. The native tool logs
16.50-second HeAP placement, normal simulated-annealing refinement and final
legality; its placed checksum is `0xefd245b1`. There are no interior timing paths
or reported Fmax in this small fixture. No routing, full backend qualification,
full-array fit or50 MHz timing signoff is inferred.

The new [full pack handoff](../tools/openxc7/pack_recursive_mux_prefix_shared_board.py)
and [full placement handoff](../tools/openxc7/place_recursive_mux_prefix_shared_board.py)
pass **18/21 host methods**, respectively, plus generated checks. They require
the complete fresh original-gates qualification, not this small probe or a
BUILT record. The full pack must repeat all515 DSP configurations/4120 ties,
16 kernels of32 products, six BRAMs and complete native resource/clock gates.
The full placement must use the same qualified executable and the actual new
full pack's census/checksum, retaining the finite2147483646 search limit,
normal refinement and43200-second deadline. Neither runner has executed native
full packing/placement. Old523410-cell/0f489b2b evidence is not rewritten or
claimed for the corrected mux graph.

The numerical unit records267441 soft-limit events without hard-limit/OOM
events at06:04:44 HKT. A guarded runtime action at approximately06:06:03 raises
only its MemoryHigh22→24 GiB, equal to the unchanged hard MemoryMax. The same
invocation/PIDs,24 GiB address bound,2 GiB swap, tests, inputs and deadlines
are rechecked. The [independent adjustment record](../build/numerical_memoryhigh_control_actual_20261009.md)
does not modify the old producer. Its [actual numerical report](../build/rknpu-dsp-prefix-shared-observed-board/1791493285871405865/report.json)
then finishes **FAIL at06:07:28.876972 HKT**: actual Icarus compile returns one
in3957.642 seconds with `t-dll-expr.cc:624: Error: calloc() ran out of memory.`
This is before the21600-second compile deadline and before the genuine
wrong-golden negative or any of nine positives. The unit records exit-code1,
not OOM-kill; separate memory/swap peaks are25578729472/2147483648 bytes.
Allocation failure alone does not isolate a specific cap. No numerical pass or
soft-threshold performance cure is claimed. The original mapped mode-5 worker
PID1418264 continues on its unchanged unit; old failures and inputs stay intact.

After that own compiler terminates, fresh admission observes availableRAM
**26534820 KiB** and free swap**2750784 KiB**, sufficient for the previously
successful6 GiB RAM/2 GiB swap qualification profile with RAM headroom.
Unit `rknpu-recursive-mux-feedthrough-qualification-memory6g-20261009.service`
starts **06:09:20 HKT**, invocation`6f7c6ba9ed9e4cd7b3a2b1ebe9c2a6fb`,
supervisor**1479845**. Its [separate master log](../build/recursive_mux_feedthrough_qualification_memory6g_actual_20261009.log)
runs the frozen fresh qualification harness against the completed isolated
native-I/O engine. High/max6 GiB, swap2 GiB, Nice15/core-zero/OOM-stop,
three-hour outer/30-second stop and every original600/3600-second native
deadline remain explicit. It begins in source admission, not qualification
acceptance. No full pack/placement is launched before this result; no production
RTL/default tool, physical/electrical/timing gate, checksum manifest or FPGA/flash
is changed.

The new [corrected-mux full route handoff](../tools/openxc7/route_recursive_mux_prefix_shared_board.py)
passes **48 host methods in16.194 seconds**, including every original shared,
HeAP, empty-output, logical-export and counter-safe error expectation. Its
own full-pack path/status/executable/qualification and actual census/checksum
replace only the old fixed profile. Both isolated changed-object transitions
are rechecked back to the independently qualified v2 scanner/router's unchanged
corrected-DSP base. The complete placed-cell membership, every BEL, original
logical identity, normal router connectivity, all515 DSPs/six BRAMs and actual
clock contracts remain mandatory. Actual placement-log checks are required
separately from metadata admission; no synthetic native log is manufactured.
It has not imported or routed the full corrected graph.

The [new read-only route verifier](../tools/openxc7/verify_recursive_mux_shared_route.py)
revalidates that exact completed new route/placement/pack chain. Its full count
comes from the bound completed new pack, never a small fixture or retired
523410-cell constant. The [new frame handoff](../tools/openxc7/convert_recursive_mux_shared_frames.py)
passes **29 host methods in22.669 seconds**, retaining every original raw-FASM,
strict-converter, complete exact-part geometry,8240-DSP-bit, actual-clock-bit
readback and genuine comparison-corruption gate. A small probe, old qualification
or incomplete producer is rejected before any output/converter invocation.
It has not converted a full new route or produced a bitstream.

A fresh combined run with **Python3.14.5** executes all six corrected-mux
qualification/probe/pack/place/route/frame control modules:
**143 methods PASS in70.896 seconds**. The
[actual combined output](../build/recursive_mux_handoffs_host_controls_actual_20261009.log)
is newly executed, not copied from an old producer. `make generated-check`
also passes. The live production identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`
(101 bound production files; no Git commit). These host results do not replace
the retained latest whole `make test` compile-limit failure, native qualification,
full numerical/physical acceptance or timing/electrical/DRC/CRC signoff.

The same fresh qualification creates its
[own report](../build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json)
at06:13:28 HKT and remains in source admission on supervisor1479845. At06:16:11,
its CPU/read counters have advanced to5:36 and48,181,663,650 logical read bytes;
the open descriptor points to a bound original full packing input. This is
live input revalidation, not a native result, a reason to restart it or authority
to weaken any guard. No checksum manifest or FPGA/flash access occurs.

### 2026-10-09: fresh native qualification advances; host-AS-only numerical continuation prepared

The same live qualification admits **3,807 source bindings**, executes fresh
compiler-symbol/getter inspection,13 host controls, generated check and native
version, then runs actual native tests. The deliberately illegal pair is
rejected with the exact expected **125 in37.629 seconds**, before placement.
The three positive placements return zero in **55.296/57.068/58.368 seconds**,
including normal refinement, complete BEL checks and **1,024 LUT truth comparisons**.
It now runs actual four-DSP/six-BRAM P&R/FASM, child1481469, under its unchanged
3,600-second deadline. Corrected-mux placement, final source revalidation and
whole qualification acceptance remain required; no full new pack is launched.

The numerical failure's allocation site is checked against the installed
package's SBOM-pinned [Icarus v13_0 source](https://github.com/steveicarus/iverilog/blob/v13_0/t-dll-expr.cc#L624),
retrieved read-only from upstream. It allocates a signal-expression structure;
this is not an observed arithmetic-output mismatch. The exact resource bound
that exhausted allocation is not established. The earlier unit retains its
24 GiB address-space and RAM cap,2 GiB swap and terminal allocation FAIL.

The [new isolated host-AS runner](../tools/cmac/test_prefix_shared_observed_board_as32.py)
derives the entire frozen numerical runner reversibly. Only a new private
virtual-address ceiling24→32 GiB and own output/control/status metadata change;
the old failed report/compile log/source/artifacts must revalidate before any
new output. All literal hardware modules,515 DSPs/six BRAMs, unmodified vendor
models/default glbl, raw BOs/goldens, strict warning checks, actual first-output
negative, all nine modes and21,600/86,400-second deadlines are unchanged.
There is no old executable/mode reuse, CPU arithmetic/layout fallback, physical
waiver or hard RAM/swap-cap increase in this helper. It cannot grant compile-only
or partial numerical acceptance. This is a new resource experiment, not a claim
that changing the virtual ceiling cures compilation.

Its [18 host controls](../build/shared_numeric_as32_host_controls_actual_20261009.log)
pass in **0.904 seconds** with Python3.14.5, retaining all15 original/shared
mode/oracle/admission controls. Generated checks pass. The new runner is
**prepared, not launched**; headroom admission and serialization with other
substantial jobs remain required. No full numerical or physical PASS or
test-ready bitstream follows. Production RTL and all frozen old helpers/results
stay unchanged; no standalone SHA256SUMS or FPGA/flash access occurs.

### 2026-10-09: corrected-mux small native qualification complete; fresh full pack launched

The [actual fresh qualification](../build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json)
completes **QUALIFIED_SMALL_RECURSIVE_MUX_HEAP_LUT_DSP_BRAM_CLOCK_FEATURES_NOT_FULL_FIT_OR_SIGNOFF**
at **06:26:34.602610 HKT**. All13 commands have their exact required return code,
including the real illegal-pair rejection125. Actual four-DSP/six-BRAM P&R/FASM
returns zero in **180.903 seconds**, with7,869 source-compared native features
and the original clock-fanout/consumer-merge contracts. The corrected-mux
placement returns zero in **53.587 seconds**; all21 unique BELs, both identity
LUTs/four truth comparisons and every original exported mux output are retained.
The three positive placements and1,024 LUT comparisons pass as recorded above.
Compiled beta0.5/symbol/getter checks and all original normal-refinement,
warning/legality/feature gates remain intact. Every one of3,807 source bindings
and22 own artifacts is revalidated; production identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
The same unit is terminal with supervisor gone; its journal records
17:14.618 wall/14:24.451 CPU and6 GiB peak memory. This is completed small native
qualification, not a full packed/placed graph, calibrated timing or physical pass.

Fresh admission rechecks completed qualification metadata/source identity,
no duplicate unit/log, availableRAM **26,466,820 KiB** and free swap
**2,772,976 KiB**. It requires12 GiB available RAM,2 GiB free swap and14 GiB
combined capacity for a private10 GiB RAM/2 GiB swap cap plus2 GiB headroom.
The new unit `rknpu-recursive-mux-full-pack-20261009.service` starts
**06:28:14 HKT**, invocation`42480e9a992f4ff59168ef8595d892d7`, supervisor
**1481990**. High/max10 GiB, swap2 GiB, Nice15/core-zero/OOM-stop/30-second stop
and7,200-second outer limit are explicit. The frozen pack runner retains its
original8 GiB per-process address-space and1,800-second native pack deadlines.

Its [own master log](../build/recursive_mux_full_pack_actual_20261009.log)
executes `pack_recursive_mux_prefix_shared_board.py` using the unchanged completed
full literal input and the newly completed qualification. It starts in fresh
source/qualification admission, before creating its pack producer or launching
native full packing. The helper must itself revalidate all original/new bindings,
repeat full515-DSP/4120-tie/six-BRAM comparisons, characterize the whole new
native graph and recompute the strict source-bound LUT matching bound. It cannot
reuse the old523410-cell/0f489b2b result as a new pack or relax a failed capacity
gate. The full C32/K16/512-product/50 MHz/seed3588 target is unchanged.
No full placement or numerical retry runs concurrently; baseline mapped mode-5
PID1418264 continues with its original handle. No physical/STA/electrical/DRC/
configuration-CRC acceptance, reviewed bitstream, checksum manifest or FPGA/flash
access occurs.

### 2026-10-09: full corrected-mux native pack executing; packet roundtrip handoff prepared

The same full-pack unit/supervisor1481990 creates its
[own report](../build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json)
after admission. It binds **4,943 source paths** and freshly passes the full
pack/DSP-feature/LUT-census/LUT-matching controls, generated check and native
version. The actual native `--pack-only` child **1482471** is now running with
the unchanged full literal input, exact part,50 MHz,seed3588,`--Werror`/debug and
1,800-second deadline. At06:37:04 HKT, its elapsed/CPU are46/38 seconds,
RSS2,380,548 KiB; the private unit charges5,621,608,448 bytes and zero swap.
This is actual native execution, not complete pack/census/capacity acceptance.
The old pack/checksum remains unchanged and is not a result for this engine.

The [new full packet handoff](../tools/openxc7/assemble_recursive_mux_shared_unreviewed_bits.py)
derives the frozen qualified small packet procedure reversibly, retaining exact
native assembler/decoder/source pins, complete46,336-frame/4,679,936-word/ECC
comparison and both genuine decoded-data/ECC-bit corruption negatives. It
requires a completed own full corrected-mux frame report and revalidates its
whole source-bound full route/placement/pack/qualification chain, actual raw
FASM requests, geometry and8,240 DSP/actual-clock bits before assembly. Fresh
readbacks/actual-frame-bit negatives write only this new attempt's comparison
outputs, never alter old evidence or become assembler input. The assembler
consumes only the original validated `configuration.frames` payload.

Its whole-chain revalidation retains the full route's12 GiB address-space
budget instead of the small encoder's2 GiB. This is a prepared host-resource
profile, not a timing/electrical/DRC/legality relaxation. An incomplete or small
profile fails before creating an attempt. All full-target512 products/515 DSPs/
six BRAMs and exact-part/clock/seed contracts remain mandatory.

The prospective full artifact is explicitly
`full-C32K16.NOT_FOR_PROGRAMMING.unverified.bit`. Actual packet emission, if
later executed, is recorded honestly as full-target emission, separately from
the still-false reviewed/test-ready/numerical/timing/electrical/DRC/configuration-
CRC/hardware gates. All-frame/ECC agreement is not CRC or physical signoff and
cannot complete the test-ready goal by itself. No full packet is assembled now.
The [nine host controls](../build/recursive_mux_full_bit_host_controls_actual_20261009.log)
pass in **15.545 seconds**, including every original packet/corruption control,
strict full-profile admission and before-output rejection. Generated checks
pass. These are host preparation controls, not native assembly or FPGA/RK proof.
Production source/constraints and every frozen old helper/result remain intact;
no standalone SHA256SUMS or FPGA/flash access occurs.

The fresh expanded suite now executes all seven corrected-mux handoff/control
modules, including the new packet handoff: **152 methods PASS in85.459 seconds**
with Python3.14.5. Its [actual combined output](../build/recursive_mux_all_handoffs_host_controls_actual_20261009.log)
is separate from the prior143-method run. No old test output is copied forward.
Production identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`;
generated checks pass. None is a full numerical/physical or whole `make test` pass.

The same full native pack returns **zero in255.749 seconds**, within its
unchanged1,800-second deadline, with normal completion. Its actual log reports
**488,192 LUTs,17,519 FFs,515 DSPs** and checksum`0x77f1fde0`; the LUT count is
112 greater than the old488080 profile. These are actual new native log values,
not projected old evidence. Native child1482471 is gone; supervisor1481990 is
now alive in **RUNNING/complete_actual_native_census**. Independent whole-graph
schema/census/DSP/tie/clock comparisons and the source-bound matching bound
must finish before pack acceptance and any full placement launch. No old
523410/0f489b2b expectation is edited; no full fit or timing signoff is inferred.

### 2026-10-09: corrected-mux full pack accepted; fresh full placement launched

The [own full corrected-mux pack](../build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json)
completes **PACKED_FULL_C32K16_SHARED_PREFIX_RECURSIVE_MUX_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF**
at **06:48:48.446627 HKT**. The independent full census confirms **523,522 cells**:
488192 LUTs,17519 FFs,8630 CARRY4,8647 selectors,515 DSPs,six BRAMs and unchanged
clock/IO/constants. Every one of515 DSP configurations/4120 extra tile ties
compares; all16 kernels retain32 DSPs. The actual new checksum remains77f1fde0.
The source-bound necessary LUT-position bound is **295,195 versus298,600 available**,
with17660 maximum matching/min-cut certificate,304079 input groups and83925
subset arcs. It is optimistic, not a placement assignment or physically proven fit.

All4943 source bindings/11 own artifacts revalidate; production identity remains
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.
The native pack command completes in255.749 seconds; the successful unit later
records20:40.065 wall/17:58.006 CPU and7.7 GiB peak memory. Supervisor1481990 is
gone. Numerical/whole ordinary-wire/placement/route/timing/electrical/DRC/CRC/
reviewed-bitstream/physical gates are not established by this pack.

Fresh full-placement admission rechecks completed pack/qualification metadata,
the same actual executable/source identity, no duplicate unit/log, availableRAM
**26322600 KiB** and free swap**2797716 KiB**. It retains the unchanged12 GiB RAM/
2 GiB swap/14 GiB combined admission gate for the private10 GiB hard RAM/2 GiB
swap envelope and2 GiB headroom. The new unit
`rknpu-recursive-mux-full-place-20261009.service` starts **06:50:19 HKT**,
invocation`7ec8232119034ab98ebb6ee10b56b87d`, supervisor**1483940**. It preserves
the prior full-placement high/max8/10 GiB, swap2 GiB, Nice15/core-zero/OOM-stop,
30-second stop and15-hour outer profile. The frozen runner's12 GiB address-space
and43,200-second native deadline are unchanged.

Its [actual master log](../build/recursive_mux_full_place_actual_20261009.log)
uses the accepted new full pack and completed fresh qualification. It begins
in source/input admission, before native full placement. The original full
literal input must be repacked by this same engine; actual checksum77f1fde0,
complete523522-cell census and finite2147483646 counter limit must match in the
native log. All full-cell/BEL,515-DSP/tie/six-BRAM,clock,warning,legality and
normal-refinement guards remain mandatory. No forced/reduced/serialized target,
old geometry retry, default-tool replacement or constraint relaxation occurs.
The original mapped mode-5 worker1418264 keeps its original handle. The host-AS32
numerical continuation is not launched concurrently. No full placed/routed fit,
numerical/timing/electrical/DRC/CRC/test-ready bitstream or FPGA/RK pass is claimed;
no SHA256SUMS manifest or FPGA/flash access occurs.

The same supervisor now creates its [own actual placement producer report](../build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json)
at **06:55:09.799020 HKT**, after the initial qualification preflight. At
**06:57:18 HKT** it remains **RUNNING/source_admission**, with no native commands
launched and no placement result. The original invocation and supervisor are
unchanged; CPU advances to6:11 and memory is48660480 bytes with zero swap.
This is a fresh same-handle observation, not a timeout, restart or fabricated
completed stage. The report/source/artifacts and frozen helpers are untouched.

### 2026-10-09: actual full corrected-mux native placement starts

The same [actual producer report](../build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json)
now advances to **RUNNING/native_place**, with **4959 source bindings** after
fresh source/input validation and complete packed-name enumeration. Its own
fresh logs record **21 placement host controls PASS in2.074 seconds** and
**six unchanged native guard host controls PASS in0.052 seconds**; generated
checks and exact native version admission also pass. These are host controls,
not full numerical/placement or physical acceptance.

Actual child **1485021**, parent1483940, starts **07:02:43 HKT** with engine
version`c68c135`. It consumes the original full literal `pack_input.json`,
exact`xc7k480tffg1156-2`,50 MHz,seed3588,`--placer heap --no-route`,
`--Werror --verbose`; its own fresh output is `placed.json` in this attempt.
The observed child retains address-space12 GiB/core-zero and43,200-second
native budget, within the same invocation/8G-high/10G-max/2G-swap service.
At this launch observation the native log reports only device initialization;
new full repacking checksum/census/finite-counter, normal refinement and full
unique-BEL/DSP/tie/clock comparisons are still required. No old result or
geometry is inherited and no completed placement/route/test-ready bitstream,
timing/electrical/DRC/CRC/numerical/FPGA/RK acceptance is claimed. Original
mapped mode5 keeps worker1418264; no heavy numerical retry or checksum manifest
is launched and no FPGA/flash access occurs.

### 2026-10-09: source-bound analytic population audit; baseline mode5 passes

The same full native worker1485021 freshly repacks checksum`0x77f1fde0`, with
488192 LUTs/515 DSPs/six BRAMs. It then logs **419259 initial analytic cells**,
not523522. The actual inherited compiled `common/place/placer_heap.cc:188`
prints `place_cells.size()`. Its `seed_placement` excludes pseudo/already-bound
cells and cluster children, and only adds meaningful connected non-IO roots.
Its final binding checks still iterate every nonpseudo cell in`ctx->cells`.
Thus the frozen full wrapper's comparison of this marker with the complete
packed population is an incorrect host-verifier scope assumption. Its existing
artificial-log host checks did not establish that native population contract.
No running helper, native source/input, original test/error expectation or
full-target acceptance gate is changed here.

The [first diagnostic rejection](../build/recursive_mux_analytic_scope_first_rejection_actual_20261009.md)
returns1 before output: it expects the old linker-status schema, whereas the
actual mux builder uses `PASS_TOOL_OR_EXPECTED_NEGATIVE_ONLY`. The link has
both expected/actual return codes zero; the builder's source enforces that
typed contract. Its first helper/eleven controls/failure are preserved. A
separate [typed-link diagnostic](../tools/openxc7/audit_typed_recursive_mux_analytic_scope.py)
keeps all original source/object/live-worker/full-target/checksum guards and
requires this exact zero-code link; negatives/failures remain rejected.
Its **13 fresh host methods PASS in0.284 seconds** with Python3.14.5, in the
[own fresh log](../build/typed_recursive_mux_analytic_scope_host_controls_actual_20261009.log).
Generated checks pass; this is not a new whole `make test` or HDL pass.

The [actual typed audit](../build/openxc7/recursive-mux-analytic-scope-typed-1791501546954868842/report.json)
completes **07:19:06.962025 HKT**, observing the same live child at07:19:04.680819.
All14 bound sources/four own snapshots revalidate, including the exact compiled
HeAP source/object inherited by the live mux engine. It records523522 full
packed cells separately from419259 logged analytic roots. The104263 difference
is arithmetic, **not an independently reconstructed exclusion/omission census**.
The exact active population, full placed cell/BEL membership, numerical and
physical acceptance are explicitly unproved. The first rejection is not
relabeled PASS and no native placement is rerun for this diagnosis.

The actual native run completes initial analytic iterations0–3 and enters the
main loop with its **2147483646 finite attempt limit**. Placement remains RUNNING,
not accepted. The current frozen wrapper will still encounter its incorrect
count assertion if native completion reaches that post-check; any subsequent
acceptance needs a separate source-bound complete-output verification, retaining
all original full-cell/unique-BEL/515-DSP/tie/six-BRAM/clock/refinement guards.
This diagnostic is not that replacement and cannot admit routing/frames/bits.

Separately, the original [mapped numerical continuation](../build/rknpu-dsp-prefix-observed-board-continuation/1791382468965621354/report.json)
passes mode5 in**38903.382 seconds**, native return0. Its actual log reports all
4096 initialized/checked halfwords,196 command reads,6528 operand reads and64
acknowledged writes, with the expected reset. Original worker1418264 is gone;
the same supervisor1231660/invocation00f0f4bb62d945e9bf49bee84056d95f advances
to mode6, worker**1485425**, starting **07:10:22 HKT**. The real negative and
modes0–5 pass;6–8 remain incomplete. This is original-baseline evidence, not
the shared candidate's numerical acceptance, a whole nine-mode/ordinary HDL
PASS, FPGA/RK silicon or bitstream readiness. The separate AS32 shared compile
remains unlaunched. No standalone SHA256SUMS or FPGA/flash access occurs.

### 2026-10-09: separate complete-output review prepared, not executed

The [complete-output reviewer](../tools/openxc7/review_recursive_mux_completed_placement.py)
admits only a terminal original wrapper rejection of
`AssertionError('Changed complete full analytic cell census')`, with all five
actual original commands PASS/return0, normal native refinement/completion,
the exact C32/K16/512 target/part/clock/seed/budget, and stopped original
supervisor/native workers. Native errors, warnings, signals, timeouts, wrong
failure causes and reduced targets remain explicit rejections. It preserves
the original failed producer and actual native output, and launches no P&R.

Its complete post-native verification block is reversibly derived from the
frozen full placement procedure. Every original full packed-name/placed-cell
membership, unique-BEL,515-DSP/4120-tie/six-BRAM/kernel, clock, normal-refinement
and before/after-source guard remains unchanged. Only the source-disproved
analytic-marker/full-census comparison is replaced by source-bound prefix/
checksum/finite-counter characterization; the complete census must actually
match the emitted graph. This is not an in-range subset-count shortcut or a
physical/numerical/whole-wire acceptance. A future completed review has its
own status/source/logs and explicitly records no newly executed native P&R;
it does not rewrite the original wrapper failure or invent a native command.

The [first host-control failure](../build/recursive_mux_completed_review_first_host_failure_actual_20261009.md)
records14 methods in3.731 seconds, with an empty-pack test fixture hitting
pack admission before its intended refinement-negative check. That helper/
fixture/log remain unchanged. The separate [valid-pack control reviewer](../tools/openxc7/review_valid_pack_recursive_mux_completed_placement.py)
changes only control selection/output archival. Its fixture supplies valid
pack metadata to the same missing-refinement negative and separately proves
invalid-pack rejection before native checking. All runtime guards are identical.
Its [fresh sixteen-method output](../build/recursive_mux_completed_review_valid_pack_host_controls_actual_20261009.log)
passes in**3.928 seconds** with Python3.14.5; generated checks pass. This is not
native full-output verification, numerical HDL/FPGA or a whole `make test` PASS.

The [actual current-producer admission check](../build/recursive_mux_completed_review_preflight_actual_20261009.md)
returns the required rejection before output/tools because the real full run
is still RUNNING. No full review report is produced. Routing still requires
completed audited placement; this preparation cannot admit route/frames/bits.

A fresh direct invocation on the live report again exits at the
`RUNNING`-metadata rejection, before reviewer output or native tools. The
separate valid-pack reviewer passes all16 current host controls. The full
placement report digest remains
`f9558b0b2f0159710ce1d2c7a864c5e18784b3e6595b29710c1f0270c9026f6f`, no
review-output directory is created, and nativePID1485021 remains under its
original running service/invocation. This is refreshed fail-closed handoff
evidence, not placement acceptance.

The same record preserves a brief actual GNU gdb17.2-4.fc44 read-only stack
snapshot of native1485021. It shows control-set tests inside strict legalization
and explicitly detaches, after which StateR/TracerPid0 and the original service
invocation/limits are reverified. The native run is not restarted or edited.
This observation establishes where the worker was executing, not convergence
or full fit. Original mapped mode6 at1485425 remains live. No numerical/full
placed/routed/timing/electrical/DRC/CRC/bitstream/FPGA/RK acceptance is inferred,
and no standalone SHA256SUMS or FPGA/flash access occurs.

### 2026-10-09: reviewed-full-placement route admission prepared only

The separate [review-aware route handoff](../tools/openxc7/route_reviewed_recursive_mux_full_board.py)
requires the future completed valid-pack full-placement review, not the
source-scope diagnostic or the original failed wrapper. Its two fresh review
commands remain software-only; all five actual native execution commands
are independently pinned to the unchanged original producer. Only the
source-proven analytic-subset/full-census wrapper failure with zero native
return code, stopped original workers and normal completion is admissible.
Every original source/artifact must remain bound through the review, including
the compiled HeAP source, scope audit and original native output/log.

Reversible metadata and checkpoint-owner changes preserve all full C32/K16,
512+3 DSP/six-BRAM, 523522-cell membership/unique-BEL, 16x32 kernel, 4120 tie,
clock and source guards. The original v2 literal imported-checkpoint scanner,
router connectivity, logical/physical identity and complete feature checks
are unchanged. Its native input must be the original producer's `placed.json`,
not a comparison artifact or a newly written checkpoint. The existing 12GiB
address-space and 43200-second native budgets remain unchanged; no native
placement, timing/electrical/DRC check or legality guard is weakened.

Its [fresh host-control log](../build/reviewed_recursive_mux_full_route_host_controls_actual_20261009.log)
reports **57 methods PASS in19.944 seconds** with Python3.14.5: all48 previous
router controls plus nine review-aware methods. Generated checks pass in
[their separate actual log](../build/reviewed_recursive_mux_full_route_generated_check_actual_20261009.log).
These are host controls, not full native placement/routing, numeric HDL/FPGA,
RK3588 or a new whole `make test` PASS. The unchanged-source latest whole
regression still fails its existing600-second Verilator compile limits.

The [actual admission/preparation record](../build/reviewed_recursive_mux_full_route_preflight_actual_20261009.md)
records CLI return1 against the real RUNNING native producer, before output
creation or tool launch. Neither completed review nor new route report exists.
At **07:56:37 HKT** the same placement child1485021/invocation
7ec8232119034ab98ebb6ee10b56b87d remains active; its log still ends at the main
analytic placer's2147483646 finite attempt limit. Original numerical mode6
at1485425/supervisor1231660 remains active. No restart or deadline/cap change
occurs. Production identity remains09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6
(101 files, no Git commit). No full routed/FASM/frames/bits or physical signoff
is claimed, no standalone checksum manifest is stored, and no FPGA/flash
detection or programming occurs.

### 2026-10-09: reviewed-route frame and unreviewed-packet handoffs prepared

The new [read-only complete-route verifier](../tools/openxc7/verify_reviewed_recursive_mux_full_route.py)
admits only the independently reviewed complete original checkpoint and the
new completed full v2 scan/route. The previous entire metadata/native command/
source/physical-logical identity/DSP/BRAM/clock-feature verification body is
unchanged apart from reversible qualification/producer-owner access. It
additionally pins actual executed route/control/prepared-main snapshots and
requires stopped native route/supervisor workers, without rewriting any
original failed placement or actual output. The full523522-cell census still
comes from the actual full pack and complete reviewed membership.

The [frame handoff](../tools/openxc7/convert_reviewed_recursive_mux_full_frames.py)
keeps the exact qualified strict raw-FASM converter, source-defined8240 DSP
feature/frame-bit checks, every actual clock bit, exact-part frame geometry,
set/clear requirements and comparison-only corruption negatives. Only the
completed reviewed-route admission and archival identity differ. Expected
features/comparison views never become conversion inputs, and missing-feature
relaxation remains prohibited. Native full-route revalidation precedes any
converter launch; the old43200-second converter budget remains unchanged.

The first frame developer run passes36 methods in31.168s. Its separately
logged rerun fails an unchanged before/after directory-census assertion when
concurrent packet controls create/remove an inert fixture. This
[actual failed log](../build/reviewed_recursive_mux_full_frame_host_controls_actual_20261009.log)
is retained; no rejection test is weakened. The
[fresh serial rerun](../build/reviewed_recursive_mux_full_frame_serial_host_controls_actual_20261009.log)
passes **36 methods in32.677s**, Python3.14.5.

The first prepared packet helper/control finds a missing `physical_fit_verified`
entry in the inherited packet flag tuple:13 methods,12 successes/one failure.
Its helper/control remain unchanged. Upstream full-frame admission already
requires that flag false. The separate
[explicit-physical-scope packet handoff](../tools/openxc7/assemble_physical_scope_reviewed_recursive_mux_unreviewed_bits.py)
adds this false output/final gate while preserving every original packet flag,
qualified assembler/decoder/source binding,46336-frame/4679936-word/ECC check
and decoded-data/ECC-bit corruption negative. Nothing grants physical-fit or
test-ready acceptance; the filename remains
`full-C32K16.NOT_FOR_PROGRAMMING.unverified.bit`.
Its [fresh selected controls](../build/physical_scope_reviewed_recursive_mux_full_bit_host_controls_actual_20261009.log)
pass **14 methods in29.620s**, including original packet negatives and all full
reviewed-frame requirements. The
[failure/scheduling record](../build/reviewed_recursive_mux_frame_packet_first_failures_actual_20261009.md)
preserves both initial failures and an interrupted record-only replay.

The [single-process aggregate](../build/reviewed_recursive_mux_all_handoffs_serial_host_controls_actual_20261009.log)
selects exactly the prepared reviewed route, reviewed frame and physical-scope
packet controls; its suites run serially and **107 methods PASS in89.306s**.
Generated checks also pass. This is host preparation, not actual full native
placement/routing/conversion/packet execution, a new whole `make test` or HDL,
FPGA/RK acceptance. Original deprecated missing-gate controls remain a failure
against their original helper and are not silently reported green.

The [actual handoff preflight record](../build/reviewed_recursive_mux_frames_packets_preflight_actual_20261009.md)
records real CLI refusals before output/tools for the current RUNNING native
producer, with no new full route/frame/packet report. At **08:09:35 HKT** the
same placement1485021/supervisor1483940/invocation
7ec8232119034ab98ebb6ee10b56b87d and original mapped mode6 at1485425/
supervisor1231660/invocation00f0f4bb62d945e9bf49bee84056d95f remain live.
Placement still ends at the main analytic placer marker, with unchanged
12GiB address-space/CORE0 and finite2147483646-attempt contract. No original
worker, budget, cap, hardware input or golden is changed. Production remains
09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6,
101 files, no Git commit. No standalone checksum manifest or FPGA/flash
detection/programming occurs; no test-ready full-size bitstream is available.

### 2026-10-09: bounded live legalizer samples establish changing queue work

The new [read-only debugger script](../tools/openxc7/read_recursive_mux_heap_state.gdb)
reads only the current strict-legalizer cell, at most64 constrained children,
bounded native identifier strings and scalar search/queue state. Inferior
function calls are disabled; detach occurs in `finally`, including read errors.
The same worker1485021/start-ticks40061214/full argv/c48a0226 executable/private
compiled HeAP source are verified before capture. GNU gdb17.2-4.fc44 returns0
for both actual captures. Post-detach checks confirm StateR/TracerPid0 and the
same original supervisor/invocation/limits; no native function/data/input edit,
restart, kill, deadline/cap change, FPGA/JTAG detection or programming occurs.

The [first actual snapshot](../build/recursive_mux_full_heap_state_actual_20261009.log)
shows unclustered `SLICE_LUTX` cell
`rk_mapped_cell_86682.rk_mapped_cell_4643`, no children, radius11,
240 attempts for that cell and290432 queued entries. Its post-detach observation
is **08:16:51 HKT**. The [second actual snapshot](../build/recursive_mux_full_heap_state_second_actual_20261009.log)
shows a different unclustered LUT,
`rk_mapped_cell_86678.rk_mapped_cell_2857`, no children, radius7,
90 current-cell attempts and279179 queued entries; its post-detach observation
is **08:19:18 HKT**. The total-no-reset search counter changes1330989→1355196.
These observations are ordinary single-cell searches, not the previously
retired malformed mux cluster. They do not audit all full-design clusters.

The [new sample auditor](../tools/openxc7/audit_recursive_mux_heap_samples.py)
accepts only bounded, schema-exact, duplicate-free actual state with explicit
detach. Unknown/malformed fields, mismatched worker/PID, unsupported offsets,
absolute-z/cluster-singleton forms and aliased member locations fail explicitly.
Its [six fresh host methods](../build/recursive_mux_heap_samples_host_controls_actual_20261009.log)
PASS in**0.050s**, Python3.14.5; generated checks pass separately. The auditor
itself never attaches or launches native P&R. Its host address space is capped
at2GiB/CORE0; original12GiB native and service profiles are unchanged.

The [actual source-bound audit](../build/openxc7/recursive-mux-observed-heap-samples-1791505404695579980/report.json)
completes **08:23:24.698700 HKT**, binding115 sources/two own observation artifacts
and the same live worker. It retains the full523522-cell packed census and
reports11253 fewer queued entries between the two observations, with changed
current cell. The compiled source explicitly populates the queue from
`solve_cells`, skips already-bound entries and requeues ripped-up cells.
**Queue entries are not an independent unplaced-cell census or placed percentage.**
This supports preserving the verified live run, not a convergence, ETA or fit
claim. Temporary native trial bindings in these snapshots also do not prove
completed cell placement.

The existing strict version6 database/ConstID reader and optimistic same-tile/
relative-z role checker find64/64 compatible individual root-role cases for
each observed singleton LUT. This excludes a zero-role geometric conflict
only for those two observed simple forms. Occupancy, paired-LUT inputs, control
sets, ports, all macros/clusters, native global legality and full fit are not
verified by this diagnostic; every complete-output/route/feature guard remains.
The [actual capture/audit record](../build/recursive_mux_heap_samples_preflight_actual_20261009.md)
retains tool/source/command/evidence boundaries. Original mapped mode6 at1485425
continues; no completed full review/route or test-ready bitstream is inferred,
no old verification is relabeled, and no standalone checksum manifest is stored.

### 2026-10-09: fresh live heap snapshot shows continued search

A third bounded GDB capture started at **07:14:49 UTC** and returned zero in
22.001 seconds. Its [raw log](../build/recursive_mux_full_heap_state_third_actual_20261009.log)
and [capture record](../build/recursive_mux_full_heap_state_third_actual_20261009.json)
bind nativePID1485021, start ticks40061214, its original supervisor/invocation,
the unchanged production source and the GDB script. GDB detached; the process
returned to stateR with `TracerPid=0`. The existing [source-bound audit](../build/openxc7/recursive-mux-observed-heap-samples-1791530167442058310/report.json)
rechecks this snapshot alongside the two earlier captures and the same complete
523522-cell packed source graph.

Across the second and third captures, the native legalizer queue count fell
from279179 to68076 and `total_iters_noreset` rose from1355196 to2868835. The
active unclustered `SLICE_LUTX` root also changed. Source inspection confirms
that this queue holds pending priority entries: the solver skips already-bound
cells and may requeue ripped-up cells. These changing values show that native
search continued between observations. They do not count completed placements,
establish a placed percentage, prove convergence or give an ETA.

The fresh audit leaves full placement, all-cell binding review, routing,
physical fit, timing, electrical and DRC signoff, bitstream emission and hardware
programming false. At audit time the same placement and baseline mapped mode6
workers remained live. The fresh results preserve the active full-size run;
they do not make the candidate ready to test.

### 2026-10-09: fourth live heap sample continues search

A fourth bounded GDB capture completed at **15:49 HKT** in about 33 seconds.
Its [raw log](../build/recursive_mux_full_heap_state_fourth_actual_20261009.log)
binds the same native PID 1485021, start ticks 40061214, parent 1483940,
systemd invocation `7ec8232119034ab98ebb6ee10b56b87d`, native executable digest,
source identity and full-placement report. The capture reported an unclustered
`SLICE_LUTX` root `rk_mapped_cell_86670.rk_mapped_cell_10611`, 152 attempts,
no children, no best BEL and `currently_placed=false`. Its queue is 66904 and
`total_iters_noreset` is 2921452. The prior sample observed queue 68076 and
counter 2868835; this sample therefore records another changed active root,
1172 fewer queued entries and 52617 more iterations, not a placement percentage,
convergence or ETA.

All [four saved states](../build/openxc7/recursive-mux-observed-heap-samples-1791532179521796957/report.json)
revalidate against the same 523522-cell packed graph; all six snapshot host
controls pass. GDB returned zero and detached explicitly; after detach the
worker remained state R with `TracerPid=0`. The raw log retains repeated RPM
transaction-lock warnings from debugger startup; they did not prevent the
bounded state read or zero exit. Full placement, complete binding review,
routing, timing, electrical/DRC signoff and bitstream emission remain false.

## Actual saved-small-packet configuration-CRC census, 2026-10-09

The [fresh read-only packet observation](../build/small_packet_crc_scope_actual_20261009.md)
checks the unchanged four-DSP/six-BRAM sample's literal fingerprint, exact part,
header, supported packet grammar and complete payload traversal. With Perl
v5.42.2/1GiB-AS/CORE0/Nice15, its source-corrected probe and saved-source replay
return zero: 546 packets, one type-2 FDRI write, **zero CRC-register writes** and
three RCRC commands. The observed absence matches the inspected clean pinned
Series-7 builder source. This is not a reproduced assembler link, whole original
source-binding audit, CRC computation, full-target acceptance or physical test.

The first probe's actual wrong-IDCODE FAIL remains recorded; the separate replay
uses the exact part database's literal0x03751093, not the separate physical-chain
0x23751093. Existing hardware input and error expectations are unchanged. Fresh
generated checks pass; no new whole production regression PASS is claimed.
Actual packet/source/evidence and runnable replay are saved without SHA256SUMS.

The original packet's configuration-CRC flag stays false. Full preparation
needs separately qualified CRC emission and independent actual packet positives/
corruption negatives; frame-ECC comparison or CRC-reset commands alone cannot
close that gate. Native placement1485021 and original numerical mode6/1485425
remain running. The full target and every numerical/timing/electrical/DRC guard
are preserved; no test-ready full-size bitstream follows from this diagnostic.

## Independent offline packet-CRC reader, 2026-10-09

The [new reader qualification record](../build/packet_crc_reader_qualification_actual_20261009.md)
retains actual source/version/seed/input identities and execution evidence.
The reader passes12 host controls and10,000 comparisons against the compiled
unchanged Project X-Ray C++ CRC header. An unchanged source-distributed normal
bitstream (header declares Vivado2016.3/Artix50T) matches both literal CRC checks;
this is an offline algorithm corpus, not the K480 board or RK3588 evidence.
Four actual-corpus controls pass in339.600s with600s/1GiB-AS/CORE0/Nice15:
both real one-bit data/CRC corruptions fail, the positive's full547420-word
FDRI CRC coverage matches, and the old K480 sample correctly fails its
unchecked-reset guard. Original inputs are not modified. The completed reader
and qualification inputs are now frozen.

Fresh generated checks pass. A separate immutable-copy production `make test`
starts at09:15:10HKT under `rknpu-crc-production-regression-20261009t0115.service`,
with3GiB RAM/1GiB swap cap, lower CPU weight and unchanged original test limits.
Its [actual source-identical report](../build/source-identical-production-regression/1791508511941204286/report.json)
is RUNNING, not a whole regression PASS. The old failed whole run stays failed.
Neither original full placement nor mapped numerical worker is restarted,
signaled or given changed input/constraints/limits.

No CRC-enabled packet is emitted by this read-only step. Separate exact-frame/
startup-preserving CRC emission and independent CRC/native frame/ECC checks
are still required. All numerical, physical/configuration-CRC, timing,
electrical/DRC and test-ready gates remain false. This advances the full target's
CRC preparation, without substituting the small corpus for full C32/K16 evidence
or creating a checksum manifest or hardware action.

## CRC-only small emission and prepared full handoffs, 2026-10-09

The [new actual emission/readback record](../build/packet_crc_emission_readback_preflight_actual_20261009.md)
preserves exact helpers, source/tool versions, commands and evidence boundaries.
The new small emitter completes at09:41:42HKT, exit0, after revalidating4,061
source/input bindings. It inserts exactly two CRC writes before existing resets;
removing only those16 bytes recovers the original native packet/frame payload.
The header is unchanged except payload length, and the fresh frozen CRC reader
matches both checks. Original encoder, packet, frame input and expectations
are untouched; the candidate remains NOT_FOR_PROGRAMMING.

The separate actual fresh native readback starts at09:42:24HKT. Host/generated
controls, native decoding, unchanged original decoded-byte comparison, all
46,336 frames/4,679,936 data/ECC words and fresh packet CRC checking pass.
Actual new-candidate one-bit data/CRC negatives and final source revalidation
now also pass; the actual producer completes at10:01:40HKT, original execution
exit0, with4,067 source bindings/13 own artifacts and unchanged production.
This qualifies only the offline small CRC encoding/readback control. It checks
only the four-DSP/six-BRAM sample, not a completed full-target route or bitstream.

Two matching full-target handoffs are prepared, with15/11 first host controls
and the separate combined26-method selection passing. They require genuine
complete reviewed-full encoding and small native
CRC qualification, exact C32/K16/515DSP/sixBRAM/part/clock/seed, frozen execution
snapshots and all original native guards. Every CRC, native frame/ECC and real
one-bit negative step remains mandatory. Neither full handoff has run on a full
packet; RUNNING/other-profile inputs are rejected before output/tools. All
physical/numerical/timing/electrical/DRC/test-ready gates remain false. Original
full placement and mapped numerical workers continue unchanged. No SHA256SUMS
or FPGA/JTAG/flash action occurs.

The fresh private whole production regression also completes at10:05:53HKT,
FAIL/actualmake2/3030.576s, source and frozen inputs unchanged. Its247-entry
Icarus EW suite passes; job-control/operand Verilator compilations again hit
the original600s limits. No completed model/numeric or CMAC Icarus result is
available in this new run, and no old result is inherited. Original production
expectations/deadlines stay intact. The failed private supervisor/make/cgroup
are gone; the full native placement and original mapped mode6 stay live.

## Source-identical whole production generated-C++ OPT0 retry, 2026-10-09

The [new source-evidenced private retry record](../build/source_identical_production_opt0_preflight_actual_20261009.md)
retains actual compiler logs showing that both default builds finish only after
their original600s deadlines. Original TIMEOUT/whole FAIL results remain intact.
An isolated helper passes six host controls and uses documented private
`OPT_FAST=-O0 OPT_SLOW=-O0` make variables. It reversibly preserves the entire
original whole-test body,101-source/four-stimulus byte-identity checks, all five
mandatory numeric/native reports, warning/assertion/golden/seed/deadline guards
and false physical/full-board acceptance flags. Reference-model CXX-O2 and
production/default tools/RTL/constraints are unchanged; no smaller test target
or cached numerical result substitutes for the whole requested regression.

Actual bounded lower-weight worker starts at10:24:02HKT, own3GiB RAM/1GiB swap
profile under`rknpu-production-opt0-20261009t0230.service`. Its actual logs confirm
generated C++ uses-O0 and the reference model remains-O2. The first12,963-vector
ALU benchmark passes; the complete whole run and final source verification are
still RUNNING, not PASS. The existing full placement1485021 and original mapped
mode6/1485425 continue unchanged. No numerical full-array/route/timing/electrical/
DRC/FPGA/RK acceptance or test-ready bitstream is inferred; no SHA256SUMS or
hardware action occurs.

The same private retry now completes the actual Icarus247-entry EW suite and
passes the formerly deadline-blocked Verilator job-control build/test:
exit0/441.753s and exit0/.121s, respectively, with the original600s build limit.
Its221-entry partial Verilator report is still RUNNING at host-AXI compilation;
all remaining original reports/final source checks are mandatory. This is not
a whole regression or full-array/physical acceptance, and original failures
remain failed. A nonblocking request for board configuration-bank schematic/
VCCO/CFGBVS evidence receives the user's reply `check other ~`; the
[fresh read-only home follow-up](../build/home_configuration_reference_followup_actual_20261009.md)
corroborates the OpenTPU1.8/GND candidate but not physical supply/strap proof.
No electrical value/constraint is guessed or gate waived.

At11:09:45HKT the same source-identical retry also records actual Verilator
CMAC operand build0/483.132s and run0/72.086s:53,297 pairs with unchanged fault/
reset checks and seed0x3588ca03. The exact-product bench passes230,433 comparisons,
seed0x3588ca04. Product-front compilation and the whole run remain RUNNING;
the243-entry partial EW report is at demo-fault compilation. Original default
TIMEOUT results remain FAIL, not relabeled. These are current partial native
checks, not full-array numerical, placement/route or physical acceptance.

The actual three-bench Verilator CMAC suite now completes at11:13:34.686HKT,
PASS_RAW_PRODUCT_PATH_ONLY, all eight commands passing on the same source.
The final product-front build0/506.083s meets its unchanged600s limit and its
run0/57.621s checks53,247 products with the original fault/reset/stall assertions,
seed0x3588ca05. Icarus CMAC then starts fresh and remains RUNNING; the whole
producer still requires all five reports and final source/input identity.
No accumulated GEMM, full mapped-board numerical, placement/route or physical
acceptance follows, and earlier failed default runs stay failed.

The actual source-identical OPT0 whole producer now completes at11:23:11.900HKT,
PASS_SOURCE_IDENTICAL_COMPLETE_PRODUCTION_OPT0_REGRESSION_NOT_SHARED_BOARD_OR_FPGA,
actualmake0/3540.766s within its original7200s limit. Both247-entry EW suites,
all three raw-product CMAC benches per simulator,49 host/model methods and
1,087,299 C++ comparisons/seed0x3588 pass; all five actual reports and final101-
source/760-binding/749-input checks complete. Owners1504807/1504856 are gone.
Fresh independent complete admission and82-image cross-simulator comparisons
also return0. The [execution record](../build/source_identical_production_opt0_preflight_actual_20261009.md)
retains real logs and original default-profile failures. This closes the current
production simulation gate, not shared full-board numerical, native placement/
route, timing/electrical/DRC or bitstream acceptance. Original full placement
and baseline mapped mode6 continue; shared AS32 replay still lacks its required
headroom. No checksum manifest or hardware action occurs.

### 2026-10-09: live shared-host memory pressure

The [read-only host snapshot](../build/live_host_memory_competition_actual_20261009.json)
records MemTotal 36.92 GiB, MemAvailable 9.37 GiB and SwapFree 10.40 GiB. The
RKNPU numerical retry's RAM and combined-capacity floors both fail in this
snapshot. Memory PSI after the five-second sample shows `some avg10=6.97` and
`full avg10=6.33`; its last four `vmstat` rows show 90–92% user CPU, 7–9% system
CPU and at most 2% idle. This is evidence of current host pressure, not a complete
accounting of every process using memory.

The captured process 1542271 belongs to an active OpenTPU static-route worker
from `/home/fedora/ypcb_ref/bonetto-soc`. Its command line names the same
`xc7k480tffg1156-2`, with `--placer static --router router2` at 100 MHz using two
threads. Its process RSS was 6.22 GiB; its service accounted for 7.47 GiB and
reported no hard memory limit. This is a separate FPGA build on the same host;
the observation establishes neither its outcome nor sole responsibility for
the pressure. The RKNPU workers and their profiles remained unchanged; no
process was stopped.

At **15:49:55 HKT**, the separate OpenTPU route unit later exits with status1
while invoking its `full-ddr800-route` stage; its process is gone. The saved
unit journal records the stage failure, not its underlying cause. A fresh
post-exit `/proc/meminfo` sample gives MemAvailable 16.02 GiB, SwapFree 6.20 GiB
and 22.22 GiB combined. The prepared RKNPU shared-numerical retry still fails
its unchanged24 GiB available-RAM and28 GiB combined admission floors (the
3.5 GiB free-swap floor passes), so it is not launched. The full-placement
service/invocation and mapped mode6 replay remain active. No unrelated process
is restarted or stopped, no resource cap is changed, and this host sample does
not establish why the OpenTPU stage failed.

At **15:56 HKT**, a read-only process/path census records the user's separate
Xilinx `xsetup` process (PID 1542179, with installer JVM PID 1542203 at about
9.21 GiB RSS) running from its `/tmp/selfgz...` extraction. Under
`/home/fedora/vivado`, the executable inventory still finds only
`2026.1.1/Vivado_Lab/bin/vivado_lab`; no full `Vivado/bin/vivado` is present.
The installation's eventual selection/completion is unknown, and the process
was not inspected beyond its command/path or altered. A separate Vortex native
route process (PID 1450777, about 0.88 GiB RSS) is also actively targeting
`xc7k480tffg1156-2`; it was not stopped. The contemporaneous MemAvailable is
13.05 GiB and SwapFree 6.46 GiB (19.51 GiB combined), still below the RKNPU
retry's 24/28 GiB RAM/combined admission floors. These process observations do
not attribute the total host pressure to one job or change any job cap.

### 2026-10-09: source-bound live heap sample after GDB output correction

The fifth raw capture, `build/recursive_mux_full_heap_state_fifth_actual_20261009.log`,
was retained but rejected by the unchanged sample auditor because GDB printed
`optimized out` in an ordinary selected-frame annotation. The parser continues
to reject that text and real debugger errors. The bounded GDB script now selects
the frame with `to_string=True`, suppressing only the normal frame banner; a
host-control assertion checks that behavior and confirms the auditor still
rejects `optimized out`. Seven focused controls pass and `make generated-check`
passes. The first retry log (`..._sixth_...log`) preserves the noninteractive
debuginfod confirmation that prevented a snapshot. The successful guarded
retry disables debuginfod before attaching, writes one JSON state record to
`build/recursive_mux_full_heap_state_seventh_actual_20261009.log`, and detaches.
The exact placer PID, parent, process start ticks and executable hash were
rechecked; afterward the same worker was running with `TracerPid: 0`. No
placer input or native algorithm was changed by this diagnostic.

The [fresh five-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791533251205962527/report.json)
uses the four prior accepted captures plus the seventh; it preserves and
excludes both failed raw attempts. At 16:07:31 HKT it observes the same native
worker (PID 1485021, start ticks `40061214`) and the unchanged 523,522-cell
packed input. The priority queue changes from 290,432 to 66,272 entries across
those observations; the final current cell is `SLICE_LUTX` and remains
unplaced. This queue is not an independent count of all unplaced cells, so its
arithmetic decline is not a placed percentage, convergence estimate or fit
result. The native placement report remains `RUNNING`; placement, route,
timing, electrical, DRC and bitstream flags remain false. The audit records
nextpnr-himbaechel c68c135, seed 3588, source-manifest identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`, and GNU
GDB 17.2-4.fc44. No board/JTAG/flash action occurred.

### 2026-10-09: live snapshot with attach-time arguments suppressed

The eighth raw log is also retained and intentionally excluded: GDB's initial
attach banner printed an optimized-out argument before the script's settings
ran. The parser rejects that banner as designed, now with a direct host-control
negative. The ninth capture used early GDB initialization
(`set debuginfod enabled off` and `set print frame-arguments none`) before
attaching; it emitted exactly one bounded state record and detached. The
[re-audited five-snapshot report](../build/openxc7/recursive-mux-observed-heap-samples-1791533802311122272/report.json)
uses the first four accepted logs and the ninth, not the rejected fifth,
sixth or eighth. At 16:15:05 HKT, the same placer identity has queue size
64,926 versus the earlier 290,432 sample. Its current LUT cell remains
unplaced, so this is evidence of changing search state—not a full unplaced-cell
census, placement percentage, completed fit or timing estimate. The original
native report remains `native_place/RUNNING`, and the current full design still
has no accepted placement, route, physical signoff or bitstream. Seven focused
controls and `make generated-check` pass; seed, tool and source-manifest
identity remain unchanged from the preceding sample record.

### 2026-10-09: current mapped replay is intentionally a two-run mode

The active user service `rknpu-dsp-prefix-observed-board-continuation-20261007.service`
and its current supervisor (PID 1231660, invocation
`00f0f4bb62d945e9bf49bee84056d95f`) remain RUNNING at `mode6`, child PID
1485425. Fresh report inspection confirms modes 0–5 have PASS results; mode 6
has no return code or result yet, and modes 7–8 have not started. This is the
separate continuation, not the archived original mode-0 timeout report.

The exact archived testbench mode-6 branch runs `success()`, resets the board,
then runs `success()` again. The PASS display is emitted only after the whole
mode case finishes, so the still-empty `mode6.log` is not itself a failure or
progress indicator. The continuation uses an unchanged 86,400-second
`process.wait(timeout=...)` per native command; the live mode-6 child remains
within that bound. It is simulator-only evidence: no full-board numerical
acceptance is claimed until modes 6–8 and final source/input revalidation pass.
No process, test limit, source fixture or output expectation was changed.

### 2026-10-09: tenth live native-placement sample

The same guarded GDB capture and source-bound audit were repeated at 16:21 HKT
against native PID 1485021, with the same start ticks, executable, 523,522-cell
pack, source-manifest identity, nextpnr-himbaechel c68c135 and seed 3588. The
[new five-snapshot report](../build/openxc7/recursive-mux-observed-heap-samples-1791534096637224585/report.json)
uses the first four accepted logs plus the tenth capture; all checks pass. Its
priority queue has 64,413 entries, 513 fewer than the 16:15 sample. The
currently explored `SLICE_LUTX` is still unplaced. This confirms changing
search state only; the queue is not a full unplaced-cell count, percent placed,
fit or ETA. The native producer remains `native_place/RUNNING`, with no
`placed.json`; route, timing, electrical, DRC and bitstream gates remain open.

### 2026-10-09: eleventh live native-placement sample

At 16:25:18 HKT, a new bounded GDB snapshot detached cleanly from the same
native worker and the unchanged full packed input. Its source-bound five-snapshot
audit passes in
[this report](../build/openxc7/recursive-mux-observed-heap-samples-1791534332102373692/report.json).
The observed priority queue is 64,223 entries, 190 fewer than at 16:21:19;
the active `SLICE_LUTX` remains unplaced. The unchanged source identity,
nextpnr-himbaechel c68c135 and seed 3588 are retained. This is search-state
movement, not a complete unplaced-cell census, fit percentage or ETA. The full
placement producer remains `RUNNING`; no placement, route, timing, electrical,
DRC or bitstream acceptance has been added.

### 2026-10-09: thirteenth live native-placement sample

At 16:32:29 HKT, the guarded read-only GDB capture again matched the native
worker identity and detached. The
[source-bound five-snapshot report](../build/openxc7/recursive-mux-observed-heap-samples-1791534762806465892/report.json)
passes; the queue is 64,050 entries, 83 fewer than at 16:29:05. The current
`SLICE_LUTX` remains unplaced. The sample preserves the same source identity,
full packed design, nextpnr-himbaechel c68c135 and seed 3588. Search-state
movement does not establish placed percentage, complete fit or ETA. The full
native-placement report is still `RUNNING`; no downstream route or bitstream
acceptance has occurred.

### 2026-10-09: fourteenth live native-placement sample

At 16:35:53 HKT, the read-only GDB capture matched PID 1485021/start ticks
`40061214`, read one bounded state and explicitly detached. Its
[fresh five-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791534968194939693/report.json)
passes with the same full pack, source identity, nextpnr-himbaechel c68c135
and seed 3588. The queue is 63,962 entries, 88 fewer than at 16:32:29; the
current LUT remains unplaced. This is not an unplaced-cell census, fit fraction
or ETA. Native placement remains `RUNNING`; no route, physical signoff or
bitstream acceptance is inferred.

### 2026-10-09: twelfth live native-placement sample

At 16:29:05 HKT, the exact same source-bound GDB procedure sampled PID 1485021
and explicitly detached. The
[fresh five-snapshot report](../build/openxc7/recursive-mux-observed-heap-samples-1791534560361753786/report.json)
passes against the unchanged 523,522-cell pack, source-manifest identity,
nextpnr-himbaechel c68c135 and seed 3588. It observes 64,133 priority-queue
entries, 90 fewer than at 16:25:18. The selected LUT is still unplaced; this
queue is not a full unplaced-cell census or placement fraction. The full
placement stage remains running and no route/bitstream acceptance follows.

### 2026-10-09: Vivado installer is unpacking full-suite payloads

At 16:37 HKT, read-only inspection finds the user's `xsetup` and Java installer
still active on `pts/6`. Its open files include changing Vivado 2026.1 payloads
`vivado_0106_...xz`, `vivado_0029_...xz`, `data_0002_...xz` and
`ip_clibs_0005_...xz`; their observed sizes/mtimes are in the process capture,
and the payload directory is being populated. However, a fresh executable
search still finds no `/home/fedora/vivado/**/bin/vivado`, so the full
installation is not ready to invoke. This is active installer work, not
Vivado availability. The terminal/session was not interacted with and the
installer was not stopped or altered; the existing Vivado Lab remains distinct.

### 2026-10-09: fifteenth live native-placement sample and audit repair

At 16:44 HKT, the guarded GDB capture matched PID 1485021/start ticks
`40061214`, the admitted executable SHA-256, and production source-manifest
identity `09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`;
GDB detached and the worker returned to `TracerPid=0`. The
[source-bound five-snapshot report](../build/openxc7/recursive-mux-observed-heap-samples-1791535456061560586/report.json)
uses the first four accepted captures plus the fifteenth. With nextpnr-himbaechel
c68c135 and seed 3588, the sampled queue went from 63,962 to 63,852 entries
since 16:35:53; the current `SLICE_LUTX` is still unplaced. The separate
[analytic-scope report](../build/openxc7/recursive-mux-analytic-scope-1791535571768240092/report.json)
confirms the native analytic marker counts 419,259 active roots while the
packed census remains 523,522 cells. That difference is not an omission
census, placement percentage, or fit result.

The first rerun of the analytic-scope audit exposed a stale link-status
assumption. Its verifier now accepts the recorded successful tool-status forms
only for the unique final `link_recursive_mux_feedthrough` command, and still
requires the exact compiled HeAP object once and the admitted executable as
output. The typed scope audit and its
[source-bound report](../build/openxc7/recursive-mux-analytic-scope-typed-1791535885286165889/report.json)
now bind that same final-link record. Fourteen scope controls and
`make generated-check` pass. The prepared full-route admission, frame, packet,
and physical-scope controls pass (48, 29, 9, and 14 checks respectively); these
are gates only, and no route, frame conversion, or packet assembly was launched
because this placer has not produced its own completed checkpoint. No P&R
input, RTL, constraint, error expectation, or active process was changed. The
full native placement remains `RUNNING`; its `placed.json` is absent, and
route, timing, electrical, DRC, and bitstream acceptance remain false. The
mapped-board continuation remains at mode 6 (modes 0-5 passed); Vivado's
installer is active but no full `bin/vivado` executable is present. Bank-0
voltage/CFGBVS remains a candidate-only board reference, not physical
electrical signoff.

### 2026-10-09: sixteenth live native-placement sample

At 16:52:38 HKT, a new bounded capture again matched PID 1485021/start ticks
`40061214` and detached cleanly. The
[two-snapshot source-bound audit](../build/openxc7/recursive-mux-observed-heap-samples-1791535958706879119/report.json)
observes the queue change from 63,852 at 16:44 to 63,648, with a different
current `SLICE_LUTX`, still unplaced. This establishes ongoing search-state
movement only: the queue is not a full unplaced-cell census, placed percentage,
fit, or ETA. The native report remains `RUNNING`, and `placed.json` is still
absent; no route, frame conversion, packet assembly, or bitstream has started.
The mapped-board mode-6 replay and Vivado installer are also still active; no
full Vivado executable or physical Bank-0 electrical evidence has appeared.

### 2026-10-09: seventeenth accepted live native-placement sample

At 17:14:50 HKT, a bounded GNU gdb 17.2-4.fc44 capture again matched PID
1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588 and the
unchanged production-source manifest
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. The
[source-bound report](../build/openxc7/recursive-mux-observed-heap-samples-1791537290524027033/report.json)
compares the accepted 16:52 snapshot with this one: 63,648 to 63,222 queued
entries, and a changed current cell. The current `SLICE_LUTX` remains
unplaced. The queue is not a complete unplaced-cell census, placement
percentage, convergence proof or ETA. An earlier raw capture is preserved but
excluded because GDB emitted `optimized out` in diagnostic text; this accepted
capture suppressed argument printing and passed the unchanged source-bound
auditor. GDB detached and `TracerPid` returned to zero. The native report still
has no `placed.json`; route, frame conversion, packet assembly, timing,
electrical, DRC and bitstream acceptance remain false.

### 2026-10-09: full RTL/model test target completed

The low-priority `nice -n 15 make test` invocation completed with exit status
0. The independent C++ FP16 model report passes 1,087,299 cases at seed
`0x3588`; both Verilator and Icarus reports pass all 247 RTL cases, including
the YPCB startup/reset test. Both CMAC simulator reports pass the exact-product
and operand/product-front benches (`PASS_RAW_PRODUCT_PATH_ONLY`); the
four-state front benches report their expected X runs and do not establish an
accumulated GEMM. `make generated-check` also passes after this log update.
The protected board-capture files retain their pre/post-run SHA-256 values
(`reads.hex` `975ef067253785dce6f9c60807bb92cf997d6ed044ea5276ac3c2491f4e5cdd6`,
`writes.hex` `8ed44735a1c9271cf0b83c24d20d317ba517497b5c59b07bb0a0f43cbeae4dbf`).
These are C++/RTL simulation results, not FPGA or RK3588 validation; they do
not alter the still-running full native placement or mapped-board mode-6 run.

### 2026-10-09: eighteenth accepted live native-placement sample

At 17:27:36 HKT, a bounded GNU gdb 17.2-4.fc44 capture again matched PID
1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588 and the
unchanged production-source manifest
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. The
[source-bound report](../build/openxc7/recursive-mux-observed-heap-samples-1791538056644086926/report.json)
compares the accepted 17:14 snapshot with this one: 63,222 to 62,665 queued
entries, and a changed current cell. The current `SLICE_LUTX` remains
unplaced. This is live search-state movement only; queue entries are not a
complete unplaced-cell census, placement percentage, convergence proof or ETA.
GDB detached and `TracerPid` returned to zero. The native report still lacks
`placed.json`; no full route, frame conversion, packet assembly, timing,
electrical, DRC or bitstream acceptance exists.

### 2026-10-09: placement timeout handoff audited

The current native child PID 1485021 remains active at 17:31 HKT, about
10h29m into its 43,200-second native budget. The wrapper source
`tools/openxc7/place_prefix_shared_board.py` starts the child in its own process
group; when `wait(timeout=...)` expires it sends SIGKILL to that group, records
the nonzero return and terminal failure, and does not enter the post-placement
full-cell/BEL/DSP guards. The candidate `placed.json` is currently absent.
No deadline, source, input or live process is changed. If this run terminates by
timeout without a placement output, retain its failure as such; any larger-budget
attempt must be a fresh source/input-admitted run with the original target,
seed, refinement, timing and electrical/DRC gates unchanged.

### 2026-10-09: full pack resource headroom observed during placement

At 17:39 HKT, the original native-placement child PID 1485021 is still live
(`ps` elapsed 10h36m; GDB is detached), and its producer report remains
`native_place/RUNNING` with the 43,200-second native timeout. The
[producer report](../build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json)
and [native log](../build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/native_place.log)
record the run and its existing nextpnr packing/resource table, which reports
488,192/597,200 `SLICE_LUTX` cells
(81%), 17,519/597,200 `SLICE_FFX` (2%), 8,630/74,650 `CARRY4` (11%),
515/1,920 `DSP48E1` (26%), and 6/955 `RAMB36E1`. These counts are below the
database's headline capacities and are useful resource-headroom evidence for
this packed input. They are not placed-site counts or a proof of a legal
full-device fit: the placer still reports 419,259 active analytic roots,
`placed.json` is absent, routing has not started, and timing, electrical, DRC,
bitstream and hardware gates remain open. No live worker, target, source or
input was changed.

### 2026-10-09: fail-closed longer-timeout retry prepared

At 17:43 HKT, PID 1485021 and its supervisor PID 1483940 are still active; the
original report is still `RUNNING` and has no `placed.json`. Do not start a
duplicate or modify the live source-bound run. The current wrapper's default
native timeout is 43,200 seconds. A read-only `python3 -B` import check
confirmed that the full guarded main function reads `NATIVE_TIMEOUT` from its
runtime namespace, so a future fresh attempt can extend only that timeout
without editing any production source. The same recursive-mux qualification,
full packed input, software controls, 50 MHz target, seed 3588, native legality
guards and placement post-checks remain in use.

Only after the current supervisor and child are gone, inspect the terminal
report manually. If and only if it is
`FAIL_PREFIX_SHARED_RECURSIVE_MUX_HEAP_PLACE` at `native_place`, records a
`TimeoutExpired`/timeout with native return code -9, and still has no
`placed.json`, this guarded 24-hour fresh retry is available. It checks those
conditions plus the original process handles before invoking the same wrapper;
it refuses to run while the prior attempt is live or if that attempt succeeded
or failed for another reason. It has not been launched.

```sh
python3 -B -c '
import json, sys
from pathlib import Path
rpath = Path("build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json")
r = json.loads(rpath.read_text())
assert r.get("status") == "FAIL_PREFIX_SHARED_RECURSIVE_MUX_HEAP_PLACE"
assert r.get("stage") == "native_place" and "timeout" in r.get("error", "").lower()
steps = [s for s in r.get("commands", []) if s.get("label") == "native_place"]
assert len(steps) == 1 and steps[0].get("timeout_seconds") == 43200 and steps[0].get("returncode") == -9
assert not Path("build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/placed.json").exists()
for pid, token in ((r["supervisor_pid"], b"place_recursive_mux_prefix_shared_board.py"),
                   (steps[0]["pid"], b"nextpnr-himbaechel")):
    cmd = Path(f"/proc/{pid}/cmdline")
    if cmd.exists() and token in cmd.read_bytes():
        raise SystemExit(f"prior process {pid} is still active")
sys.path.insert(0, "tools/openxc7")
import place_recursive_mux_prefix_shared_board as p
assert p.NAMESPACE["NATIVE_TIMEOUT"] == 43200
p.NAMESPACE["NATIVE_TIMEOUT"] = 86400
sys.argv = ["place_recursive_mux_prefix_shared_board.py", "--packed",
            "build/openxc7/full-prefix-shared-recursive-mux-native-pack-1791498819257677272/report.json",
            "--qualification", "build/openxc7/recursive-mux-feedthrough-qualification-1791497608027018932/report.json"]
p.main()
'
```

### 2026-10-09: twenty-first accepted live native-placement sample

The first two bounded debugger launches stalled during attach-time symbol
loading; both were stopped, and post-detach checks confirmed the placer resumed
with `TracerPid: 0`. The accepted capture used GNU gdb 17.2-4.fc44 with
debuginfod disabled before attach (`-iex`) and a bounded kill-after timeout.
Its [raw snapshot](../build/recursive_mux_full_heap_state_twentyfirst_retry_actual_20261009.log)
contains one bounded state record and an explicit detach. The
[source-bound audit](../build/openxc7/recursive-mux-observed-heap-samples-1791539470902317430/report.json)
completed at 17:51:10 HKT against the same PID 1485021/start ticks `40061214`,
nextpnr-himbaechel c68c135, seed 3588 and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`.

Compared with the accepted 17:36:47 capture, the priority queue changed from
62,422 to 61,492 entries (decline 930), and the current root changed to
unplaced `SLICE_LUTX` cell `rk_mapped_cell_86679.rk_mapped_cell_14925`. This is
changing search state only, not a complete unplaced-cell census, placement
percentage, convergence proof, fit or ETA. GDB detached and `TracerPid` is zero;
the native report remains `RUNNING`, `placed.json` is absent, and routing,
timing, electrical/DRC signoff and bitstream gates remain open. Failed raw
debugger logs are preserved but are not used as snapshots.

### 2026-10-09: mapped-board continuation passes mode 6 and advances to mode 7

At 17:51 HKT, the source-identical mapped-board continuation report records
modes 0–6 as `PASS`. Mode 6 specifically reports two successful runs with one
reset, 4,096 initialization/check words, 64 writes and acknowledgments, and
explicitly says `no physical FPGA test`. Its Icarus child PID 1485425 has
finished; the same supervisor PID 1231660 has launched mode 7 as child PID
1572833, confirmed live at 17:51 with no return code yet. The
[continuation report](../build/rknpu-dsp-prefix-observed-board-continuation/1791382468965621354/report.json)
remains `RUNNING/mode7` and preserves `parent_status=FAIL`; modes 7–8 and final
continuation checks are not complete. This is mapped-netlist simulation only,
not accumulated FPGA/RK or bitstream acceptance.

### 2026-10-09: twenty-second accepted live native-placement sample

At 18:01:18 HKT, the bounded GNU gdb 17.2-4.fc44 capture and source-bound
[two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791540078650866088/report.json)
again match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135,
seed 3588 and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. The
[raw snapshot](../build/recursive_mux_full_heap_state_twentysecond_retry_actual_20261009.log)
was captured with debuginfod disabled before attach and explicitly detached;
the worker is running with `TracerPid: 0`.

Compared with the accepted 17:50:39 sample, the priority queue changed from
61,492 to 61,307 entries (decline 185), with a different current unplaced
`SLICE_LUTX` root, `rk_mapped_cell_86675.rk_mapped_cell_12521`. This is ongoing
legalizer search only, not a complete unplaced-cell census, placement
percentage, convergence proof, fit or ETA. The full placement producer remains
`RUNNING`, no `placed.json` exists, and routing, timing, electrical/DRC
signoff and bitstream gates remain open.

### 2026-10-09: twenty-third accepted live native-placement sample

At 18:13:39 HKT, GNU gdb 17.2-4.fc44 captured the live legalizer with
debuginfod and automatic frame-argument printing disabled before attach. The
[source-bound two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791540819505837645/report.json)
and [raw snapshot](../build/recursive_mux_full_heap_state_twentyfourth_retry_actual_20261009.log)
match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588
and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. GDB
explicitly detached and a post-capture check observed `TracerPid: 0`. The
preceding attempt log `recursive_mux_full_heap_state_twentythird_retry_actual_20261009.log`
is preserved but excluded: an incidental debugger backtrace contained
`optimized out`, which the unchanged strict auditor correctly rejects.

Compared with the accepted 18:01:18 sample, the pending-priority queue changed
from 61,307 to 61,193 entries (decline 114), and the current unplaced
`SLICE_LUTX` root changed to `rk_mapped_cell_86682.rk_mapped_cell_1304`. This
remains live strict-legalizer search, not a complete unplaced-cell census,
placement percentage, convergence proof, fit or ETA. At 18:14 HKT the same
native worker and supervisor remain live, `placed.json` is absent, and the
producer still reports `RUNNING/native_place` under its original 43,200-second
limit. Routing, timing, electrical/DRC signoff and bitstream gates remain open.

### 2026-10-09: twenty-fourth accepted live native-placement sample

At 18:24:19 HKT, GNU gdb 17.2-4.fc44 captured the worker using the same
read-only script, with debuginfod and automatic frame-argument printing disabled
before attach. The [source-bound two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791541459085914985/report.json)
and [raw snapshot](../build/recursive_mux_full_heap_state_twentyfifth_retry_actual_20261009.log)
match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588
and the unchanged production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. The
debugger explicitly detached; the worker remains live with `TracerPid: 0`.

Compared with the accepted 18:13:39 sample, the pending-priority queue changed
from 61,193 to 60,782 entries (decline 411), and the current unplaced
`SLICE_LUTX` root changed to `rk_mapped_cell_86673.rk_mapped_cell_19299`. The
no-reset iteration counter increased from 3,135,120 to 3,155,113. These are
changing legalizer-search observations only, not a complete unplaced-cell
census, placement percentage, convergence proof, fit or ETA. At 18:24 HKT the
native child and supervisor remain live, the producer is `RUNNING/native_place`
under its original 43,200-second timeout, and `placed.json` is absent. Routing,
timing, electrical/DRC signoff and bitstream gates remain open.

### 2026-10-09: twenty-fifth accepted live native-placement sample

At 18:35:00 HKT, GNU gdb 17.2-4.fc44 captured the worker with the read-only
script, debuginfod disabled and automatic frame-argument printing suppressed
before attach. The [source-bound two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791542100086080005/report.json)
and [raw snapshot](../build/recursive_mux_full_heap_state_twentysixth_retry_actual_20261009.log)
match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588
and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. GDB
explicitly detached and the post-capture check observed `TracerPid: 0`.

Compared with the accepted 18:24:19 sample, the pending-priority queue changed
from 60,782 to 60,515 entries (decline 267), and the current unplaced
`SLICE_LUTX` root changed to `rk_mapped_cell_86676.rk_mapped_cell_12589`. The
no-reset iteration counter increased from 3,155,113 to 3,172,857. This remains
live strict-legalizer search, not a complete unplaced-cell census, placement
percentage, convergence proof, fit or ETA. At 18:35 HKT the native child and
supervisor remain live with the original 43,200-second timeout, no `placed.json`
exists, and route/timing/electrical/DRC/bitstream gates remain open.

At the same observation time, the separate full Vivado 2026.1 installer is
actively extracting into `/home/fedora/vivado/2026.1`. Its native log
`/home/fedora/.Xilinx/xinstall/xinstall-2026-10-09_15-33-24.log` reports
35,962/549,699 files processed, and `~/vivado` occupies about 41 GB; the
`Vivado/bin/vivado` entry point is not present yet. This is installation
progress, not a usable Vivado toolchain, so the already-running openXC7 path is
preserved unchanged.

### 2026-10-09: twenty-sixth accepted live native-placement sample

At 18:45:28 HKT, GNU gdb 17.2-4.fc44 captured the worker with the read-only
script, debuginfod disabled and automatic frame-argument printing suppressed
before attach. The [source-bound two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791542811413058006/report.json)
and [raw snapshot](../build/recursive_mux_full_heap_state_twentyseventh_retry_actual_20261009.log)
match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588
and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. GDB
explicitly detached and the post-capture check observed `TracerPid: 0`.

Compared with the accepted 18:35:00 sample, the pending-priority queue changed
from 60,515 to 60,345 entries (decline 170), the current unplaced `SLICE_LUTX`
root changed to `rk_mapped_cell_86677.rk_mapped_cell_16865`, and the no-reset
iteration counter increased from 3,172,857 to 3,187,764. This remains live
strict-legalizer search, not a complete unplaced-cell census, placement
percentage, convergence proof, fit or ETA. At 18:49 HKT the native child and
supervisor remain live under their original 43,200-second timeout, no
`placed.json` exists, and route/timing/electrical/DRC/bitstream gates remain
open. The separate mapped-board Icarus continuation is still running mode 7;
it is simulation only and not board evidence.

At 18:48:46 HKT, the separate full Vivado 2026.1 installer log reported
84,155/549,699 files processed under `/home/fedora/vivado/2026.1`. At 18:49 HKT
the installer processes remained live, but the `Vivado/bin/vivado` entry point
was still absent. This is extraction progress, not a usable Vivado installation.

### 2026-10-09: twenty-seventh accepted live native-placement sample

At 18:55:08 HKT, GNU gdb 17.2-4.fc44 captured the worker with the read-only
script, debuginfod disabled and automatic frame-argument printing suppressed
before attach. The [source-bound two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791543337826212553/report.json)
and [raw snapshot](../build/recursive_mux_full_heap_state_twentyeighth_retry_actual_20261009.log)
match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588
and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. GDB
explicitly detached and the post-capture check observed `TracerPid: 0`.

Compared with the accepted 18:45:28 sample, the pending-priority queue changed
from 60,345 to 60,116 entries (decline 229), the current unplaced `SLICE_LUTX`
root changed to `rk_mapped_cell_86680.rk_mapped_cell_1639`, and the no-reset
iteration counter increased from 3,187,764 to 3,203,108. This remains live
strict-legalizer search, not a complete unplaced-cell census, placement
percentage, convergence proof, fit or ETA. At 18:55 HKT the native child and
supervisor remain live under their original 43,200-second timeout, no
`placed.json` exists, and route/timing/electrical/DRC/bitstream gates remain
open. The separate mapped-board Icarus continuation is still running mode 7;
it is simulation only and not board evidence.

At 18:55:40 HKT, the separate full Vivado 2026.1 installer log reported
119,150/549,699 files processed under `/home/fedora/vivado/2026.1`. At 18:55 HKT
the installer processes remained live, but the `Vivado/bin/vivado` entry point
was still absent. This is extraction progress, not a usable Vivado installation.

### 2026-10-09: twenty-eighth accepted live native-placement sample

At 19:00:33 HKT, GNU gdb 17.2-4.fc44 captured the worker with the read-only
script, debuginfod disabled and automatic frame-argument printing suppressed
before attach. The [source-bound two-snapshot audit](../build/openxc7/recursive-mux-observed-heap-samples-1791543672115849118/report.json)
and [raw snapshot](../build/recursive_mux_full_heap_state_twentyninth_retry_actual_20261009.log)
match PID 1485021/start ticks `40061214`, nextpnr-himbaechel c68c135, seed 3588
and production-source identity
`09f1c3f65ba91220fda55bc06364e5d571da9d808ffd27804474d1c9cd0f2dd6`. GDB
explicitly detached and the post-capture check observed `TracerPid: 0`.

Compared with the accepted 18:55:08 sample, the pending-priority queue changed
from 60,116 to 60,000 entries (decline 116), the current unplaced `SLICE_LUTX`
root changed to `rk_mapped_cell_86678.rk_mapped_cell_12583`, and the no-reset
iteration counter increased from 3,203,108 to 3,210,753. This remains live
strict-legalizer search, not a complete unplaced-cell census, placement
percentage, convergence proof, fit or ETA. At 19:01 HKT the native child and
supervisor remain live under their original 43,200-second timeout, no
`placed.json` exists, and route/timing/electrical/DRC/bitstream gates remain
open. No timeout or retry outcome is inferred from this pre-deadline sample.

The focused snapshot-auditor controls pass all seven tests under Python 3.14.5;
this tests the bounded parser and fail-closed evidence semantics, not native
placement. At 19:00:34 HKT, the separate Vivado installer log reported
128,089/549,699 files processed. Extraction is not a usable Vivado toolchain.

### 2026-10-09: full-size placement timeout and guarded retry refusal

The original full-size attempt
[`1791500109797789442`](../build/openxc7/full-prefix-shared-recursive-mux-heap-place-1791500109797789442/report.json)
finishes at **19:02:48.929 HKT** as
`FAIL_PREFIX_SHARED_RECURSIVE_MUX_HEAP_PLACE` at `native_place`. The recorded
native command reaches the main analytical placer for 419,259 roots, then
expires at its unchanged 43,200-second host timeout; nextpnr returns `-9`.
The original child (1485021) and supervisor (1483940) are now absent, and
`placed.json` does not exist. No route, full-fit result, timing signoff,
electrical/DRC signoff, bitstream or hardware result follows. This is a host
timeout; it does not establish an inherent device-fit failure.

The documented guarded retry was then attempted with its 86,400-second outer
native limit, but source admission rejects it before creating retry output or
starting nextpnr: `AssertionError: Changed placement input:
/usr/bin/python3.14`. The original report binds that path to SHA256
`0d64bd6d66d68dac91cdadafc46e22d4f09f22bdc997aaae870f42865b024a3e`; the
current path is SHA256
`df5a95e6119c051c43ab78993af48f8a53c54a25a475dacd1428c322251eb8b0` and
reports Python 3.14.8. Read-only DNF transaction 62 records the Fedora Python
upgrade from 3.14.7 to 3.14.8 between 07:31 and 07:54 HKT, while the original
placement process was live. The retry interpreter itself was Homebrew Python
3.14.5; the guarded input mismatch is specifically the changed Fedora Python
path in the bound source/tool manifest. No hash or source guard is waived.

The old qualification and pack remain historical evidence for their original
environment, not permission to bypass this change. A fresh current-environment
qualification and pack chain, followed by a newly admitted native placement,
is required before placement can resume. The RTL, device, packed input, seed,
50 MHz target and native legality checks were not edited to disguise the
timeout.

At **19:16 HKT**, the unrelated mapped-board Icarus continuation remains
`RUNNING/mode7` with parent status `FAIL`; its VVP worker is a simulation, not
FPGA or RK hardware evidence. The separate Vivado 2026.1 installer remains
active and its log reports 184,951/549,699 files processed; the full
`Vivado/bin/vivado` entrypoint is absent. The local home-project electrical
search is recorded in the [configuration reference follow-up](../build/home_configuration_reference_followup_actual_20261009.md):
it found a candidate `CONFIG_VOLTAGE 1.8` / `CFGBVS GND` XDC, explicitly an
assumption, but no board schematic or measured Bank 0 supply/strap. All
electrical, timing, DRC, fit and physical-use gates remain open.
A fresh top-level folder comparison against the prior 49-folder inventory
found only one added non-hidden folder, `~/NewFolder`; it is empty and adds no
new board or electrical-reference material.

### 2026-10-09: post-update native mux-fixture re-probe

At **19:29 HKT**, the existing c68c135 `nextpnr-himbaechel` executable
(`SHA256 c48a0226838228e7ac9a3f467115b6ec92ef5b6cc0026cb638ef5ced4900d15e`)
was freshly run on the existing five-mux fixture for part
`xc7k480tffg1156-2`, heap placer, no route, 50 MHz, seed 3588, `--Werror`.
It exits zero with checksum `0xefd245b1`. The fresh
[placed output](../build/openxc7/current-env-mux-probe.wQSJby/mux-feedthrough-placed.json)
and [raw log](../build/openxc7/current-env-mux-probe.wQSJby/native-place.log)
are preserved under `build/openxc7/current-env-mux-probe.wQSJby/`.
A new invocation of `qualify_recursive_mux_feedthrough.validate_mux_placed`
accepts the generated file: 21 placed cells have 21 unique BELs; the expected
two identity LUTs, four truth comparisons and original shared-mux exports are
all confirmed. The output SHA256 is
`000812d31ecefb327ed227189206b4b45db67bec268b12335b3167471af89e7a` and the
raw log SHA256 is
`5362eafc441ad0c9984d96d531b19fb101dfe712a4fec261bdf956170177631e`.

The checker used Python 3.14.5 from the existing Homebrew installation and
the old build report only as fixture-schema metadata; it did not call the old
source-bound qualification verifier or inherit its native result. This is a
fresh small native execution after the Fedora Python update, not a refresh of
the full 3,807/4,943/4,959-input qualification/pack/placement chain. The
original full-placement retry remains rejected by its source guard, and no
full pack, full placement, route, timing/DRC signoff, bitstream or hardware
result is implied by this probe.

At **19:30 HKT**, the separate mapped-board simulator is still
`RUNNING/mode7` with the preserved parent failure; its VVP process is active,
not a board test. Vivado installation is also still active: the installer log
reports 220,998/549,699 files processed, and the full Vivado entrypoint is
absent. Host CPU pressure remains high and only 2.4 GiB swap is free, so no
second full-size placement or pack job is started alongside these jobs.
