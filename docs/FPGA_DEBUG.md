# Optional EW ILA preparation

The separate debug profiles prepare the ILA probes requested in gate C of
[the implementation plan](REVIEW_AND_PLAN.md). They reuse an intact,
simulation-bound functional package and copy its exact RTL and evidence.
They add a probe plan and checkpoint Tcl, without editing the default RTL,
pin constraints, decoder, numerical policy or normal implementation flow.
Preparation does not launch Vivado, create a physical ILA, emit a bitstream,
connect to hardware or arm an analyzer.

| Profile | Functional parent | Intended observation |
|---|---|---|
| `ew-startup-ila` | Qualified EW startup-reset package | Latched autonomous self-test state, commands and errors after configuration |
| `host-jtag-ew-ila` | Qualified USER2 EW BRAM package | A future analyzer can be armed before a host submits a raw job |

The autonomous SUB(9) self-test completes before a host can normally arm an
ILA after programming. This profile does not promise an initial startup trace.
The host profile leaves the engine idle until SUBMIT, so it provides the source
structure needed for an arm-before-job workflow. Actual arming, retained capture
across cable ownership changes and physical readback remain unverified.

## Prepared flow and scope

The Tcl follows AMD's documented
[netlist insertion flow](https://docs.amd.com/r/en-US/ug908-vivado-programming-debugging/Using-XDC-Commands-to-Insert-Debug-Cores).
The debug variant preserves hierarchy and disables FSM extraction, using
[`synth_design`](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/synth_design)
options only in its own script. The source state codebooks are checked against
the exact frozen controller enums. Default synthesis options are unchanged.

Each plan has 14 probes and 204 bits, sampled at 50 MHz with a depth of 1024
and no added input pipeline stages. The requested nets cover controller states,
start/completion, command words, acknowledged memory traffic and errors. Bit
lists are explicitly ordered least-significant first. The autonomous demo
selects its three normal-state bits; all named source states fit those bits,
and the declared unused fourth bit is not claimed as captured.

Clock selection comes from a synthesized controller register's clock pin,
then checks its buffered clock net and the `sys_clk` association. It does not
connect the analyzer to the input port's potentially unbuffered wire. Net
lookups must be unique and exact. Missing or optimized-away names stop the
future build; the package is not evidence that synthesis will preserve every
requested name.

The script adds one ILA and its debug hub after synthesis. The existing
`opt_design` step implements the debug cores, as described by
[UG835](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/implement_debug_core).
Functional BRAM inference is checked before insertion, so ILA storage cannot
mask a missing working RAM. All original electrical, setup/hold, unconstrained
path and blocking-DRC gates remain. No timing exceptions or DRC waivers are added.
This instrumented variant needs its own resource/timing review; it does not
inherit a physical result from an uninstrumented image.

The debug hub uses USER1. The host variant retains the existing mailbox on
the exact `u_bscan` USER2 instance. Its package-only CDC derivative narrows the
mailbox primitive lookup to that instance; all original synchronizer, held-data
max-delay, bus-skew and clock checks remain unchanged. The additional debug
audit checks both BSCAN owners. The normal mailbox CDC file is not modified.
AMD documents the need to keep
[debug-hub scan chains separate](https://docs.amd.com/r/en-US/ug908-vivado-programming-debugging/Changing-the-BSCAN-User-Scan-Chain-of-the-Debug-Core-Hub).

After a later authorized route, the script requests `ila_debug_core.rpt`,
`ew_ila.ltx`, an ordered requested-connection ledger and an object audit.
Port widths, core settings, marked nets, clock association and BSCAN ownership
are checked. The ledger records requested connections; it does not assert a
mapped per-channel connection. The actual report and LTX mapping require
inspection. No LTX file or debug-core implementation exists from preparation.

## Offline commands

Pass an existing verified functional parent directory explicitly:

```sh
python3 tools/debug/prepare.py prepare \
  --profile ew-startup-ila --parent-package "$EW_STARTUP_PACKAGE"
python3 tools/debug/prepare.py prepare \
  --profile host-jtag-ew-ila --parent-package "$HOST_EW_PACKAGE"
python3 tools/debug/prepare.py verify "$DEBUG_PACKAGE"
make debug-control-test
```

The two parent variables identify the intact startup and USER2 packages listed
in [README](../README.md), and `DEBUG_PACKAGE` is the directory printed by the
chosen preparation command. Both simulator reports and their bound artifacts
must already be present in the parent. The debug package copies only qualified
manifest entries, rejects extras and symlinks, and verifies the copies without
access to the original run. It reuses those reports only for unchanged
functional RTL; they do not simulate the new ILA or qualify instrumented timing.

Each debug package starts with an incomplete board review. `command` only
prints a future checkpoint invocation after source/evidence and board admission;
it never executes it. Bitstream emission and programming are absent. The control
tests use ordinary Tcl with all Vivado commands mocked. Passing them proves
script control flow, not Vivado API execution or a physical debug connection.

## Current source and evidence

The final [autonomous package](../build/ew-debug-preparation/1792962351826175702/report.json)
freezes 120 source files at SHA256
`820aff0fee3ab4baa5c23c3eeaa834a894373fdd10a7d698ae7453ec04b9271c`.
The [host-controlled package](../build/ew-debug-preparation/1792962351620948606/report.json)
freezes 47 source files at SHA256
`3a9e653d780247dcb65639b75f9bec4fb91f294610336dd3a2cfcd28f64c0ec9`.
Both verify as `SOURCE_INTACT_REVIEW_PENDING`; board review, instrumented
implementation and capture remain incomplete.

The [full regression](../build/plan-debug-implementation/1792961083679149070/production-validation.json)
passed in 431.453 seconds, including the initial fourteen debug controls.
Afterward, a packaging-only import dependency fix passed the final
[sixteen source/control methods](../build/plan-debug-implementation/1792961083679149070/debug-validation-final.json)
under Tcl 9.0.3 and clean vendor Tcl 8.6.13. RTL, probe Tcl and default physical
flows did not change. A Tcl interpreter that reports a version while its
standard-library initialization fails is now rejected as `UNAVAILABLE`.

All [23 final package controls](../build/ila-package-audit/1792962791198091922/report.json)
pass. Both copied validators run using isolated `python -I -B` from outside
the checkout without modifying package bytes. Verification succeeds with
original evidence paths blocked, while changed sources, copied binaries,
reports, codebooks and generated Tcl are rejected. The
[preservation audit](../build/ila-source-preservation/1792961549420157613/audit.json)
also confirms unchanged functional/default-profile sources and all 512 products
in the full candidate. Earlier diagnostic/package attempts remain historical.

## Future host-profile acquisition

This is a proposed later hardware procedure, not an executed capture:

1. Use a separately authorized and reviewed source-matched SRAM image and its
   actual generated LTX file. Keep the cable exclusively owned by one tool.
2. In the future Hardware Manager session, select the audited target and enforce
   a TCK frequency no greater than 6 MHz before debug access. OpenTPU's inspected
   native JTAG helper sets `PARAM.FREQUENCY` to 3 MHz, which is within that limit;
   read the target setting back rather than assuming a tool default.
3. Inspect the mapped probes and arm on the intended start event. Release that
   tool's cable connection without reconfiguring the FPGA, then give exclusive
   ownership to the USER2 transport and submit the unchanged raw workload.
4. Close the USER2 owner, reacquire USER1 at the same bounded TCK, and inspect
   capture/arming state before exporting data. Establish whether capture remains
   armed across this ownership/TAP sequence on the actual card; no such result
   is claimed here.

The mailbox TCK synchronizers run even when USER2 is not selected, so the 6 MHz
bound also applies during USER1 debug access. A faster debug session would
violate the existing mailbox timing assumption. The 1024 samples span only
20.48 microseconds at 50 MHz; they do not guarantee a complete long-job trace.
Neither TAP reset nor an ILA session is a fabric reset. Fault recovery still
requires the documented joint reset or reconfiguration, without rollback.
