# YPCB bring-up notes

## Current status and electrical scope

As directed on 2026-10-23, Vivado is the implementation path, using the OpenTPU
Vivado workflow as a reference. OpenXC7 placement/routing is retired from the
continuation. The current scope is documentation, review, fixes and preparation;
do not start a Vivado build or any openXC7 job during this pass. Keep previous
artifacts and failure evidence intact. No hardware programming is authorized.
Retain the full C32/K16 DSP-prefix candidate and all 512 parallel CMAC products
for preparation; the small EW top described below is not its replacement.

The OpenTPU reference discovers Vivado through `VIVADO_ROOT` or
`XILINX_VIVADO`, then `PATH` and installations under `$HOME/vivado`. Its normal
shell setup is:

```sh
export VIVADO_ROOT="$HOME/vivado/2026.1/Vivado"
source "$VIVADO_ROOT/settings64.sh"
```

Read-only inspection on 2026-10-23 found the settings file, Vivado launcher and
a local `~/.Xilinx/Xilinx.lic` file. File presence is not a successful license
checkout; Vivado was not invoked for this inspection. Use OpenTPU as a setup
reference only, preserving its abandoned implementation handoff.

For this project's full target, the preparation action is
`python3 tools/cmac/vivado_dsp_prefix_array.py prepare`. It checks the source
profile and generated ROM and writes source/Tcl snapshots without
validating numerical parents or starting Vivado. Its `synth` and `run` actions
remain outside the current scope. Any
rejected or stale parent must be reported explicitly, not relabelled or waived.

This pass produced the full-target [preparation report and Tcl snapshot](../build/rknpu-dsp-prefix-array-vivado/prepare-1792696631656679983/report.json),
with status `PREPARED_DSP_PREFIX_ARRAY_VIVADO_ONLY` and all 512 products retained.
The separate [read-only prerequisite audit](../build/review-all-20261022T190646Z/cmac-vivado-parents-readonly.json)
rejects the saved area/native/mapped/board parents because their recorded
`tools/cmac/vivado_array.py` hash predates the reviewed banner-parser fix.
Fresh source-bound prerequisites are required before a later build. No
previous pass is relabelled, and the preparation report is not build admission.

The Fedora continuation adds `make synth-check` for Yosys XC7 mapping and simulation of the resulting primitive netlist. This is separate from Vivado implementation, timing closure and physical-board testing, which remain unrun. The source top is intended for the YPCB_00338_1P1 board. Its public board files identify `xc7k480tffg1156-2` and a single-ended 50 MHz oscillator; the referenced XDC supplies the following pins. References are in `SOURCES.md`.

| Port | Package pin | Standard |
|---|---|---|
| SYS_CLK | AA28 | LVCMOS18 |
| SYS_RSTN | R28 | LVCMOS18 |
| led_3bits_tri_o[0] | P30 | LVCMOS18 |
| led_3bits_tri_o[1] | M30 | LVCMOS18 |
| led_3bits_tri_o[2] | N30 | LVCMOS18 |

These entries and the part/clock were cross-checked against the clean local reference checkout `/home/fedora/ypcb/ref/ypcb_00338_1p1_hack` at commit `8b13ecf71b7061dd43a2b1580f0caa469f64303f`. The actual PCB revision, oscillator and configuration-bank supplies still require physical confirmation; a public board file is not a measurement of this card. SYS_RSTN is used as an active-low reset with asynchronous assertion and synchronized deassertion. No DDR, PCIe, flash or fan interfaces are instantiated or constrained; board power and cooling still need to be provided by the normal proven setup.

The top uses the 50 MHz clock directly, not a fabric-divided clock. The initial wide exact FP16 datapath is not optimized for that frequency and has **no measured timing result**. A timing failure must be addressed by pipelining or a proper clocking-resource design; do not remove timing checks or false-path the arithmetic. LED paths and the external asynchronous reset are intentionally excepted; internal datapath timing is not.

## Build gates

The existing `make fpga` target uses a full Vivado installation with synthesis/implementation and XC7K480T support. Vivado Lab is for programming/debugging an existing image, not building this RTL. Tool licensing/device coverage must be checked in the actual installed version; no license availability is asserted here. The earlier [openXC7 route](OPENXC7.md) is historical and retired from the continuation. It does not replace the Vivado implementation or physical signoff gates.

### Full-toolchain download, checked 2026-10-08

AMD's [current licensing table](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vivado/vivado-licensing-options.html) lists **all 7-series devices** in the free, annually renewed BASIC tier. This includes the target's device family; actual installed XC7K480T support and successful license checkout still require verification. The [2026.1 download page](https://www.amd.com/en/support/downloads/adaptive-socs-and-fpgas/development-tools/2026-1.html) explicitly excludes **2026.1.1** from BASIC. Select the **2026.1 main release**, not the installed Lab version's update number.

The Linux web installer is `FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700_Lin64.bin` (listed as 394.17 MB), rather than the 98.28 GB all-tools single-file image. Its [official download entry](https://account.amd.com/en/forms/downloads/xef.html?filename=FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700_Lin64.bin) requires an AMD account: this host's unauthenticated request reached a logout page, not an installer. No authenticated payload URL is available or invented here. After logging in yourself, copy the actual installer download URL and run:

```sh
read -r -p 'Paste the authenticated AMD installer download URL: ' rk_vivado_download_url
wget -c -O /home/fedora/vivado/FPGAs_AdaptiveSoCs_Unified_SDI_2026.1_0616_1700_Lin64.bin "$rk_vivado_download_url"
unset rk_vivado_download_url
```

Select Vivado Design Suite and Kintex-7 device support in the installer, not Vivado Lab alone. AMD login, license generation and agreement acceptance remain the user's actions. No full installer/download completion, installation, usable license, native Vivado implementation or FPGA acceptance is claimed by this check. Existing open-source jobs continue independently. No new `SHA256SUMS` manifest is needed or written; existing evidence is preserved.

The same continuation freshly reads the current exact-device Himbaechel v6 database: it still contains only the `DEFAULT` speed-grade table, twelve cell timing types and no DSP timing type. This is a live table-presence check, not speed-grade/circuit timing validation. Completing open-source placement/routing or frame conversion cannot by itself close the missing exact -2/DSP timing gate. Neither that gate nor electrical/DRC checks are waived while awaiting the full toolchain.

An [actual read-only Lab probe](../build/openxc7/lab-capabilities-20261008-1315/probe.tcl), executed at **21:14 HKT on 2026-10-08**, confirms this distinction from the running tool, not merely its filename. The [unaltered tool log](../build/openxc7/lab-capabilities-20261008-1315/vivado_lab.log) identifies **Vivado Lab 2026.1.1, build 6605303, Tcl 8.6.13**. All ten queried design/timing commands are absent: `get_parts`, `get_speed_models`, `get_timing_arcs`, `report_timing_summary`, `read_checkpoint`, `link_design`, `synth_design`, `place_design`, `route_design` and `write_bitstream`. Bundled timing documentation/shared libraries therefore do not expose a usable implementation or timing-query flow through this executable. `open_hw_manager` is present but was **never invoked**; no hardware connection, project, implementation or programming occurred. The probe exited zero after reporting capabilities; this is not a timing or FPGA PASS.

### Implementation checks

These are the existing build commands for a separately authorized future run;
the current preparation pass must not execute the Vivado build command.

```sh
make test
make synth-check
RK_CONFIRM_BOARD=YPCB_00338_1P1 make fpga
```

The default Tcl run writes post-synthesis/routed checkpoints and reports under `build/vivado`. Inspect synthesis warnings, RAM inference, utilization, clock/reset routing, setup and hold slack, unconstrained paths and DRC. The script requires inferred block RAM, rejects missing timing paths and negative/nonfinite/unavailable setup or hold slack, and blocks DRC errors, critical warnings and unrecognized severity values. It also requires explicit zero counts from the internal `no_clock` and `unconstrained_internal_endpoints` checks; missing, malformed or nonzero reports stop emission. The full timing report and the intentional external reset/LED exceptions remain unchanged. These checks use the documented [`check_timing -override_defaults ... -return_string` interface](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/check_timing), with each returned report saved separately. Human review of all reports, including exceptions and pulse-width checks, is still required. No timing exceptions or DRC severities were relaxed. This EW implementation flow remains unrun.

`tests/test_fpga_build.py` executes the actual build Tcl in a temporary directory with mocked tool commands. Its control-flow methods exercise board confirmation, strict boolean settings, legal/illegal electrical pairs, property assignment before checkpoint/DRC, the BRAM requirement, timing failures, missing-clock/unconstrained-endpoint rejection, unknown report formats, and DRC rejection. Mocked successful calls create no checkpoint or bitstream. These are control-flow tests, not evidence that Vivado accepts the commands or that the design meets physical constraints.

`make synth-check` instead writes `build/yosys/ypcb_netlist.v`, `ypcb.json`, logs and `report.json`. It requires an inferred RAMB18E1/RAMB36E1, rejects remaining unmapped circuit cells, and runs the board self-test twice through Xilinx's functional RAM/DSP/LUT primitive models. The models are pinned under `tests/vendor/xilinx-unisim` with their Apache-2.0 license. No routed delays or SDF are supplied; the models' internal functional delays prove no operating frequency. This does not replace the Vivado gates above.

The recorded 2026-10-09 installation follow-up found full Vivado 2026.1 and obtained its native version banner. The separate full C32/K16 synthesis-only [attempt](../build/rknpu-dsp-prefix-array-vivado/synth-1791552618590027876/report.json) then exited 42 before synthesis because no valid license was found. This supersedes the earlier Lab-only installation observation; it does not establish current license availability or successful synthesis, implementation, timing or DRC. The dated download and Lab capability checks above remain historical evidence for their own scope.

Bitstream emission is deliberately opt-in. The actual configuration-bank supply and CFGBVS strap were not established by this review. Obtain their values from the board's verified existing build/schematic; **do not infer them solely from LED-bank I/O voltage**. Export `RK_CONFIG_VOLTAGE` and `RK_CFGBVS` with those established values, then:

```sh
RK_CONFIRM_BOARD=YPCB_00338_1P1 RK_EMIT_BITSTREAM=1 make fpga
```

The script requires both electrical variables whenever either is supplied, and always for bitstream emission. Legal 7-series pairs are `1.5/GND`, `1.8/GND`, `2.5/VCCO` and `3.3/VCCO`, following [AMD's CFGBVS property definition](https://docs.amd.com/r/en-US/ug912-vivado-properties/CFGBVS). They are validated before synthesis and applied to the design before checkpoints, implementation and DRC. A legal pair is not proof of this board's actual supply/strap. The script never chooses a pair or lowers DRC severity. `RK_EMIT_BITSTREAM` and `RK_LED_ACTIVE_LOW` accept only `0` or `1` when set.

A generated file would be `build/vivado/rk_ew_demo.bit`. No .bit file exists in this source delivery. The script neither opens a hardware target nor changes the FPGA or flash. For a first run use the user's already-working JTAG flow to program volatile configuration only, after reviewing the resulting build.

### Alternative-toolchain audit

The `nextpnr-xilinx` source audit at `d486d8ef6a1c756ca72b2ba495e7e18e4c24815d` found that its [XDC parser](https://github.com/openXC7/nextpnr-xilinx/blob/d486d8ef6a1c756ca72b2ba495e7e18e4c24815d/xilinx/xdc.cc) ignores design-level properties targeting `[current_design]` and does not implement `set_false_path`. Its port selector uses literal name lookup, not Vivado's list/glob expansion. The new [openXC7 characterization runner](OPENXC7.md) handles the exact reviewed profile explicitly and rejects any unknown or changed constraints. The exact -2 database and all five package pins have been checked. This advances beyond the earlier read-only audit, without claiming that partial nextpnr timing/DRC coverage closes the physical gate. No alternative bitstream flow is enabled and no electrical/timing gate has been removed.

## Self-test interpretation

The board now runs `rk_ew_dma_demo`: it initializes 336 halfwords in a fixed sparse aperture backed by 4 KiB BRAM, executes the unchanged production SUB(9) command chain through DMA, and verifies every mapped halfword before latching pass. This includes two tasks, intermediate scratch, padded output, inputs and command memory. Only the six documented windows are exposed; this is not a general host memory allocator. See [DMA_BOARD_DEMO.md](DMA_BOARD_DEMO.md) for the exact map, command hashes and verification contract. The original raw-port ADD/SUB/MUL demo remains a separate regression test.

Logical LED0 is pass, LED1 is fail and LED2 is a heartbeat. Actual illuminated polarity is not verified. Use `RK_LED_ACTIVE_LOW=1` at build time only when appropriate for the physical LED circuit; default is logical active-high. The heartbeat continues after pass/fail. The error code is marked for debug as `unused_error_code` at the board top; there is not yet an external status register interface.

Demo error codes E1/E2/E3/E4/EF mean memory mismatch, host-port RAM fault, demo watchdog, invalid DMA completion and invalid demo state respectively. Core error codes 1..8 retain the definitions in `INTERFACE.md`.

A passing LED pattern is evidence of this small autonomous test only. It is not evidence of a PCIe interface, DDR memory, GEMM, the complete Rockchip ISA, hardware-accurate special-value handling or passing tinygrad test_ops.
