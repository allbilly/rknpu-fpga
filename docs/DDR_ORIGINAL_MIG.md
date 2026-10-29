# Regenerated original MIG source preparation

Vivado 2026.1 successfully generated a separate controller source bundle from
the unchanged original YPCB MIG project. Both channels retain ECC, 512-bit AXI,
31-bit byte addressing, the original RZQ/7 drive selection and original pin
selections. This is source preparation; it supplies no board clock-delivery,
PHY training, routed timing or physical DDR result.

The workflow uses the standalone `create_ip` / `CONFIG.XML_INPUT_FILE` /
`generate_target` pattern inspected in OpenTPU. ZYNQ-NVDLA's staged integration
checks inform the review order. Neither project's electrical settings, reset
coverage or hardware results are inherited.

| Item | Actual evidence |
|---|---|
| Frozen original input | All six original source roles match their pinned hashes; input `mig.prj` SHA256 `adc1bcdb20b7aabb51f9359bf46eaea3c6e592819a9d88411ebf90e61e974d00` |
| Preparation controls | Five mock/profile methods and fourteen actual copied-input/tampering controls pass; the mock now detects the originally omitted IP directory |
| Native generation | Vivado 2026.1, SW Build 6511674 / IP Build 6504888; return code 0 in 214.684 seconds; twenty frozen execution inputs unchanged, 141 generated artifacts hashed |
| Actual generated interface | 169 normal-hardware wrapper ports; ECC vectors are eight bits, memory AXI is 512/31/4 data/address/ID, and control AXI is 32 bits |
| Capacity | Both generated geometries imply 2,147,483,648 data bytes: 15 row, 10 column, three bank bits, one rank and 64 payload bits with eight ECC bits |
| Clock facts | Original differential 200 MHz inputs: AH27/AH28 and G25/G26, generated `DIFF_SSTL15` constraints and 5 ns periods. Actual board delivery remains unverified |
| Calibration defaults | `SIM_BYPASS_INIT_CAL="OFF"` on both channels; normal hardware ABI requires `SKIP_CALIB` to remain undefined |
| Scope | No top implementation, bitstream, card programming or flash write |

The original input project remains byte-identical. The generator's copied
project omits only the two derived `C0_MEM_SIZE` / `C1_MEM_SIZE` tags; the audit
checks all other XML fields and derives each 2 GiB capacity independently from
the generated HDL geometry. It also checks the generated drive parameters are
`HIGH`, the vendor's documented encoding of RZQ/7.

## Binding findings

The regenerated `.veo` contains 165 ports and still omits four outputs present
in the actual wrapper: each channel's eight-bit single-ECC vector and twelve-bit
device-temperature output. Future integration must use the actual wrapper
declarations. Raw ECC vectors remain unsuitable as independently qualified
events; the control monitor's status/interrupt contract remains separate.

The new wrapper adds six one-bit inputs compared with the old template:
self-refresh, refresh and ZQ requests for each channel. They require explicit
bindings. This preparation does not introduce a runtime low-power API.

Against the archived 107-file reference, 66 generated counterparts are
byte-identical and 41 differ. The four UI module bodies are byte-identical
from their `timescale` directives onward; their license headers differ.
Other generated wrapper/PHY changes retain a separate source identity and
need their own qualification. Archive-model logs are not new generated-PHY
evidence.

The generated WIDTH=1 arbiter still has the previously identified inhibit
defect. A [separate derived definition](../build/original-mig-derived/rzq7-width1-v1/report.json)
applies the exact source-bound correction and produces the already identified
arbiter SHA256 `ae6be8a3f77170c867bf076a4291bd6b0755c1250ab32215a8b679274b88368f`.
Raw generated files remain unchanged. A later integration must select exactly
one corrected definition and exclude the original or cached unpatched
implementation. This leaf correspondence does not qualify the new complete
controller, PHY or platform.

The accelerator image is timing-qualified at 50 MHz. The generated DDR UI is
133 1/3 MHz, derived from the retained 1,875 ps memory period and 4:1 PHY ratio.
The current logical joined endpoint operates entirely in that UI domain; it
cannot be used as a physical full512 shell at that rate without new timing
evidence. Board integration must preserve the qualified accelerator clock
and add explicit memory/control crossings with reset, drain and fault-visibility
contracts. The two 200 MHz external clock deliveries also need board evidence.
These clock boundaries are preparation work, not a completed hardware shell.
The separate [serial halfword crossing leaf](DDR_ASYNC_MEMORY.md) now passes
both native suites for the memory-port protocol; full ownership/health/control
integration and physical CDC qualification remain open.

The new [source-bound port map](../build/original-mig-port-map/v2/report.json)
accounts for every169normal wrapper port and matches channel0 AXI/control
widths and directions to the SYS50/UI133 logical endpoint header. All six
self-refresh/refresh/ZQ inputs are explicitly inactive. Channel1 has no
admitted master: VALID and responseREADY inputs stay zero, and its other
unused inputs have explicit literals. Raw ECC vectors, temperature and unused
status outputs remain unqualified diagnostics. Both channel reset/clock
connections and the global active-low reset are explicit. Wrapper, MIG-core,
generated project and XDC hashes bind the 200MHz differential/7.5ns UI/RZQ7
source facts. Actual board delivery is still unverified.

Fifteen [parser/shape/binding controls](../build/original-mig-port-map/controls-v2/report.json)
pass, and copied core/project/XDC tampering is rejected. This artifact is a
proposed complete port map, without an instantiated physical shell. It does
not clear the original historical BLOCKED audit or prove reset/drain coverage.

The [pinned source-body comparison](../build/original-mig-body-comparison/v1/comparison.json)
checks all107archive counterparts. Sixty-six are raw-identical; ninety-six
bodies match from `timescale` onward after verifying the removed prefixes
contain only comments/whitespace. All compared AXI, UI, MC and ECC bodies
match. Seven bodies differ, including two PHY files; four metadata/constraint
files lack that comparison boundary. These correspondences support a source
review only. New wrapper/PHY behavior still requires its own qualification.

`tools/ddr/original_sources.py` prepares a separate
[corrected original RTL selection](../build/original-mig-rtl-selection/v4/report.json).
The generated tree contains102HDL files, including regular and simulation
wrappers with the same module name. The tool uses the actual IP-XACT synthesis
file sets (99common files plus2synthesis wrappers), rather than selecting the
directory wholesale. Raw files are preserved, the simulation wrapper is
excluded, and exactly one separately derived WIDTH1 arbiter is substituted.
The101selected HDL entries contain one corrected arbiter definition. Cached
DCP/XCI and simulation-only attribute patches are excluded.

Five [selection/identity/duplicate controls](../build/original-mig-rtl-selection/controls-v1/receipt.json)
pass. The [independent rehash](../build/original-mig-rtl-selection/v4/root-review.json)
checks110live inputs,103source copies and4metadata copies. Clock/electrical/
constraint scope, matched PHY/model, whole-platform reset/drain and full512/
DDR/host composition remain unresolved; this package performs no implementation.

`tools/ddr/original_platform.py` now emits the
[source wiring wrapper](../build/original-ddr-platform/v5/report.json) joining
the actual169-port MIG declaration to the async EW endpoint. It exports DDR
pads, original differential clock inputs, UI frame clock/reset and status,
connects all channel0 memory/control buses, and retains the explicit inactive
channel1/request bindings. The real HDL list has101corrected MIG sources,
16actual endpoint sources and the wrapper. No XCI/DCP or test stub is selected.

Seven [wiring/width/negative controls](../build/original-ddr-platform/controls-v5/receipt.json)
pass, including warning-free Icarus declaration-only elaboration and rejection
of bad-port/wrong-width variants. The
control receipt checks the frozen source closure and every actual connection
expression. Declaration
stubs for both child modules are used exclusively for this port check and are
not executed. The earlier real-endpoint Icarus attempt remains a failed strict
check because of its constant-select limitation; actual endpoint behavior
continues in the separate Verilator/MIG runtime suite. Pad clocks, full PHY,
electrical/constraint scope, host TCK/PCIe reset/ownership and full512/DDR
composition still require qualification before physical implementation.

Actual-source out-of-context synthesis now
[passes in Vivado2026.1](../build/original-ddr-real-synthesis/v2/report.json)
for all118 HDL files:101 original/derived MIG sources,16 endpoint sources and
the wiring wrapper. It uses no declaration stubs, cached checkpoints or XCI.
The first synthesis attempt exposed width1 DDR pad buses rendered as scalars:
the original XDC requires their `[0]` names. That failed receipt is preserved.
The v5 wrapper retains `[0:0]` for CK/CKE/CS/ODT, and the fresh synthesis has
zero critical warnings, errors or unresolved black boxes. The original MIG
XDC is unchanged; diagnostic severities and physical checks remain enabled.
The [independent integrity review](../build/original-ddr-real-synthesis/v2/root-synthesis-review.json)
rehashes123 frozen inputs and134 artifacts, checks the real-source/no-stub
selection and unchanged original XDC, and preserves native warning categories
and failing timing representatives. It does not accept timing or physical DDR.

This is **synthesis only**. It took1,180.919seconds, peaked at6,887,796,736bytes
inside an8GiB/no-swap cgroup and recorded zero OOM events. The unplaced timing
report has setup WNS-1.169ns and hold WHS-2.369ns. Known synchronizer first
stages still need source-bound crossing constraints; a separate same-UI
control path and vendor clock/reset paths also require review. No route,
timing signoff, bitstream or physical DDR result is claimed. The endpoint's
new21-case logical qualification also remains open after its recovery timeout.
The [actual-checkpoint job/memory proof](DDR_ASYNC_EW.md) now checks all167
dynamic held-bus bits, four constant bits and18 synchronizer stages. Its
bounded constraints cover those two handshakes only; reset/barrier/vendor
CDC findings remain visible and unresolved.

The separate [boot-only USER2 board-shell preparation](DDR_BOARD_PREPARATION.md)
now binds121 actual HDL files, preserves all238 MIG pin locations and keeps
interface-only stubs outside the real source list. No physical-shell
implementation or programming is performed by this preparation tool.

## Receipts and commands

The [preparation receipt](../build/original-mig-preparation/rzq7-v2/report.json),
[actual controls](../build/original-mig-controls/v2/report.json),
[native generation](../build/original-mig-generation/rzq7-v2/report.json) and
[root source review](../build/original-mig-generation/rzq7-v2/root-source-review-v3.json)
bind the selected source and generated files. The first
[failed generation](../build/original-mig-generation/rzq7-v1/report.json) is
preserved: the recipe initially omitted creation of its IP output directory.
The corrected recipe uses a fresh package and output. Earlier audit-parser
rejections are also retained beside the successful review.
The [48-file selected source archive](../verification/runs/2026-10-27-original-mig-source/index.json)
preserves original inputs, preparation/generation receipts, source-audit code,
selected actual wrapper/constraint files and the separately derived arbiter.
It excludes the complete generated PHY bundle and makes no matched-model or
physical qualification claim.

```sh
make -f fpga/ddr/original_mig.mk controls
python3 tools/ddr/prepare_original_mig.py prepare \
  --source-root /path/ypcb_00338_1p1_hack --out build/new-original-mig
python3 tools/ddr/prepare_original_mig.py verify --package build/new-original-mig
```

These commands prepare and verify only. The package's generation Tcl requires
a separate recorded native invocation. Its outputs still need source-matched
model, reset/retirement, board clock/electrical, synthesis, CDC and routing/timing
review before any physical DDR claim. The legacy original-reference audit
and its historical blocked reports are preserved unchanged.
