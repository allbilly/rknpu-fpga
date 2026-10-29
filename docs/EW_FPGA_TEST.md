# First EW FPGA test

This test targets the separate `ypcb_ew_startup_top` image on
`xc7k480tffg1156-2`. The 50 MHz SYS input is AA28. Configuration-time reset
holds the design for 64 rising edges; reloading the image restarts it without
an R28 input. The full C32/K16, 512-product candidate remains a separate target.

The autonomous demo executes the unchanged production SUB(9) command chain,
including its initialization prelude: two completed tasks and 336 checked
halfwords across the mapped command/input/scratch/output region, including
padded lanes. PASS means the built-in, source-bound scoreboard reached its
terminal success state. SAMPLE observes that state through its outputs; it
does not independently read back those 336 halfwords or test external DDR.

**Physical result, 2026-10-26: PASS.** Three volatile-SRAM loads of the same
reviewed image, including two reconfigurations, pass the autonomous test.
Four captures (one extra repeat after the first load) contain 404 positive
samples and 32 heartbeat transitions. The 101-row pre-load baseline remains
an unknown application and is excluded from those totals. Flash is unchanged;
the owned test server stopped and released the cable lease.

| Evidence gate | Actual result |
|---|---|
| Target | Cable `80802026a77a01`, IDCODE `0x23751093`, exact current DNA matched before every load |
| Tool | Vivado 2026.1, build 6511674 |
| Routed resources | 3,168 LUTs, 895 registers, one RAMB36E1, one DSP48E1 |
| Routing | 4,638 / 4,638 routable nets, zero errors |
| Setup / hold / pulse slack | +1.188 / +0.067 / +9.600 ns at 20 ns clock period |
| Constraints and DRC | No unclocked or unconstrained internal endpoints; zero waivers; four DSP pipelining advice warnings |
| Startup | 64 delay registers plus registered reset, all FDRE INIT=0; exact chain reviewed |
| Actual routed functional simulation | PASS at cycle 2,178 after the testbench's startup interval, standard vendor GSR retained |
| Three SRAM loads | INIT=1, DONE=1, raw IDCODE and source-derived USR_ACCESS `d1d0e3d0` verified |
| Four physical captures | 101 samples each: PASS=1, FAIL=0, all three outputs driven, eight heartbeat transitions each |

The [preserved evidence index](../verification/runs/2026-10-26-ew-startup-fpga/index.json)
hashes selected sources, native reports, load receipts and raw boundary scans.
Its [independent physical review](../verification/runs/2026-10-26-ew-startup-fpga/receipts/physical-observation-review.json)
reports no findings. The production source manifest is
`d1d0e3d0bffd0ffadee9e9eb4b14020c985d772ce716ad2936894f2b4003f59a`;
the 18,735,216-byte bitstream is
`7250ad2e9a7c009b0fd8fa5a265dc089073f220e5c4355096453afa88bf7ef67`.
The archive omits bitstream/DCP and compiled simulator binaries; it is
observation evidence, not admission to rebuild or program a changed image.

This validates the bound autonomous BRAM workload and repeated configuration
startup. GEMM/NVDLA, host-submitted jobs, DDR, PCIe, RK3588 numerical
equivalence, optical polarity and measured clock frequency remain separate.

## Output contract

The compiled `LED_ACTIVE_LOW=0` choice gives noninverted digital output data.
Optical LED emission polarity is unknown and is not used for this test.

| Role | Package pin | BSDL output / disable / input cells | Expected output data |
|---|---|---|---|
| PASS | P30 | 852 / 851 / 853 | 1 throughout the post-load capture |
| FAIL | M30 | 846 / 845 / 847 | 0 throughout the post-load capture |
| Heartbeat | N30 | 849 / 848 / 850 | Keeps toggling |

Each disable cell must be 0 for the expected output driver to be enabled.
Input-cell values are preserved separately; these captures do not establish
optical polarity, pad voltage or an independent SYS-clock frequency.
The exact `XC7K480T_FFG1156` BSDL has a 6-bit instruction register and a
1,395-bit boundary register. Raw captures occupy 349 hexadecimal digits with
the unused top padding bit zero. This pin-role mapping differs from Tiny TPU.

## Prepare an image-bound observer

Root owns the hardware lease, server, target audit and all actual Vivado/JTAG
operations. Prepare only after the new bitstream and its immutable EW startup
source package exist. Set these paths to the exact run being tested:

```sh
export VIVADO_ROOT="$HOME/vivado/2026.1/Vivado" # adjust for the installation
EW_BSDL="$VIVADO_ROOT/data/parts/xilinx/kintex7/public/bsdl/xc7k480t_ffg1156.bsd"
# Set EW_BIT, EW_PREP, EW_OBS, EW_TARGET and EW_SERVER from the reviewed run
# and fresh target audit. EW_OBS must be a new directory for each capture.
python3 -B tools/hardware/sample_ew.py prepare \
  --bitstream "$EW_BIT" --source-report "$EW_PREP/report.json" \
  --bsdl "$EW_BSDL" --out "$EW_OBS" \
  --target "$EW_TARGET" --server "$EW_SERVER" --led-active-low 0
```

`EW_PREP` is the matching `prepare_ew_fpga.py` startup package, including its
`source/` snapshot. The observer checks all eleven hardware-source hashes,
binds the exact bitstream/source report/BSDL, and snapshots its own code and
inputs. A unique trial binding prevents substituting another trial's capture.
Preparation performs no hardware access.

Root then runs the generated `EW_OBS/capture.tcl` using native Vivado under the
shared hardware lease. The candidate requires the exact audited target, one
XC7K480T device and raw IDCODE `0x23751093`. It requests/reports 3 MHz cable
TCK and records 101 samples at nominal 50 ms spacing. TCK does not change the
FPGA SYS clock. The script selects only IDCODE (`09`), SAMPLE (`01`) and
BYPASS (`3f`), with checked cleanup. It never selects EXTEST or changes I/O
drive/configuration. TAP reset is not a design reset.

## Decode the actual capture

For a post-load capture, `EW_LOAD` must identify the matching successful
volatile-SRAM load receipt:

```sh
python3 -B tools/hardware/sample_ew.py decode \
  --plan "$EW_OBS/plan.json" --capture "$EW_OBS/capture.tsv" \
  --kind post-load --load-receipt "$EW_LOAD" \
  --out "$EW_OBS/observation.json"
```

The load receipt requires `status="PASS"`, `action="program-sram"`,
`hardware_programmed=true`, `flash_written=false`, the actual
`bitstream_sha256`, `idcode="0x23751093"`, the same full target URI, and an
aware ISO `finished_utc`. It must also supply `source_report_sha256` matching
the observer's bound preparation report and an exact integer
`compiled_led_active_low=0` matching the plan. Root obtains that compiled
parameter from the reviewed image rather than the observed outputs.
Additional command/log/image-review bindings are permitted, and the complete
receipt bytes are hashed. Capture timestamps must follow load completion.

Post-load decoding checks INIT/DONE in every captured IR, the complete raw
boundary data, all PASS/FAIL/enable values, increasing timestamps, at least
three seconds of observation, at least two heartbeat transitions, and successful
BYPASS/target/server/manager cleanup. All raw data remains available on failure.
Successful output observation is limited to the bound built-in EW scoreboard.

Use a fresh observer directory and `--kind baseline` without a load receipt
to preserve the pre-load state as application-unknown. Use `--kind repeat`
with the same load receipt for a later capture. For `--kind reconfiguration`,
root performs a second audited volatile-SRAM load and supplies that new
receipt. Repeated captures do not restart the autonomous test; reconfiguration
does. Root's combined evidence must retain distinct trials, actual load events,
bit/source hashes and their time order.

This procedure performs no flash erase/write. Neither a build nor a load alone
establishes a physical PASS. The source/RTL, routed image, target audit, SRAM
load and timed SAMPLE observation remain distinct evidence records.
