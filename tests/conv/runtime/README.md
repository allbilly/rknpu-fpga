# Runtime-decoded conv engine equivalence harness (experimental)

This directory holds the equivalence harness for the runtime-decoded conv
engine prototype (`rtl/cmac/experimental/runtime/`, task-13). It does **not**
touch the adopted image or any production core.

## Files

| File | Role |
|---|---|
| `conv_runtime_model.py` | Golden runtime decoder: consumes the raw command QWORDs, derives the geometry from the register fields using the pinned donor formulas, and cross-checks the derived BO sizes against the fixtures. `python3 tests/conv/runtime/conv_runtime_model.py` must print `13/13 cases decode consistently; 0 field-map problems`. |
| `tb_conv_runtime_equiv.sv` | Bench: instantiates the adopted per-profile core AND the runtime engine on the same clock/memory contract/raw stream; compares the complete operand-read and output-write sequences; requests one full memory-image dump from each memory model at completion (no hierarchical memory access from the bench; the Python runner compares the images and the capture); drives the decoder's fail-closed negative controls. `MODE=0` equivalence, `MODE=1` decoder rejection, `MODE=2` runtime replay-only (unpinned bundle). Emits `TB_PROGRESS cycles=...` every 20k cycles and a 400k-cycle completion timeout so a stall is localised quickly. |
| `run_runtime_equiv.py` | Runner: rebuilds each fixture's exact command stream/BOs, compiles the bench through `build/verif/host_guard/safe_run.sh`, runs the replay + negative controls, compares the written output BO against the frozen capture, and writes a source-hash-bound receipt under `build/runtime-conv-lab/`. |
| `run_decode_unit.py` + `tb_runtime_decode_unit.sv` | Fast decoder-only check (~2 s compile): replays every captured command stream through the RTL decoder and diffs the decoded config against the golden model. Use this first when the decoder changes; it isolates decode from the convolution replay. |
| `run_area_estimate.py` + `synth_runtime_core.tcl` | Synthesis-only OOC area estimate of `rk_conv_runtime_core` (Vivado; no opt/place/route, no bitstream), receipt under `build/runtime-conv-lab/area/`. Launch with `BENCH_CPUS=4-7 BENCH_CPU_QUOTA=200`; the Tcl caps Vivado at `general.maxThreads 2` for this host. |

## Usage

```sh
# offline field-map check (light, no simulator)
python3 tests/conv/runtime/conv_runtime_model.py

# equivalence for a representative subset (heavy: the runner must be launched
# through the host guard, which holds the heavy lock for the whole run)
BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=60 \
  build/verif/host_guard/safe_run.sh \
  python3 tests/conv/runtime/run_runtime_equiv.py --simulator iverilog \
  --case conv_3x3_valid_c4_h9_w9_oc4 \
  --case conv_3x3_stride2_c4_h11_w11_oc4 \
  --case conv_simple_fp16_3x3_c4_h8_w8_oc16

# fast decoder-only check (run first after decoder changes)
BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=60 \
  build/verif/host_guard/safe_run.sh \
  python3 tests/conv/runtime/run_decode_unit.py

# full 8 vendor + 4 conv-simple corpus (same guarded wrapper)
BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=60 \
  build/verif/host_guard/safe_run.sh \
  python3 tests/conv/runtime/run_runtime_equiv.py --simulator iverilog
```

The runner bakes a per-case `init.hex` (canary fill + packed operand BOs at
their word offsets), which each memory model loads with a single exactly-sized
`$readmemh`; the model dumps its own array to `mem_rt.hex`/`mem_ref.hex` on
request. There are no hierarchical memory references in the bench.

Each run writes `build/runtime-conv-lab/<case>/<simulator>-<stamp>/report.json`
with `source_hashes_before`/`source_hashes_after`, `decoded_config`,
`bo_placement`, `compare.written_output_vs_capture`, the complete-memory-image
result and every negative control's expected/actual code.

### Split legs (short submission, same single-launch protocol)

To keep each heavy window short, the runner accepts `--leg`:

```sh
# leg A: primary replay only (3 cases x compile + one mode-0 simulation)
BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=70 \
  build/verif/host_guard/safe_run.sh \
  python3 tests/conv/runtime/run_runtime_equiv.py --simulator iverilog --leg primary \
  --case conv_3x3_valid_c4_h9_w9_oc4 \
  --case conv_3x3_stride2_c4_h11_w11_oc4 \
  --case conv_simple_fp16_3x3_c4_h8_w8_oc16

# leg B: decoder fail-closed controls only (17 simulations per case)
BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=70 \
  build/verif/host_guard/safe_run.sh \
  python3 tests/conv/runtime/run_runtime_equiv.py --simulator iverilog --leg controls \
  --case conv_3x3_valid_c4_h9_w9_oc4 \
  --case conv_3x3_stride2_c4_h11_w11_oc4 \
  --case conv_simple_fp16_3x3_c4_h8_w8_oc16
```

`--leg full` (default) is the single-launch protocol above. Each leg still runs
one Icarus compile per case and executes under the caller's guard lock only.

## Evidence boundaries

* A run that produces no `PASS`/`FATAL` line is classified as *interrupted*:
  guard kills and host loss are reported as `no result`, never as a code
  failure. `build/runtime-conv-lab/PARTIAL_SIGNAL_NON_EVIDENCE.md` records the
  one interrupted attempt and its partial (non-evidence) control results.

* The 12 pinned fixtures are compared against the adopted per-profile core,
  their frozen expected/device bytes and the complete memory image.
* `conv_1x1_valid_c8_h5_w5_oc8` is an **unpinned READY capture bundle**: it has
  no `tests/conv/fixtures` entry and no adopted per-profile core, so it is
  replay-only (`MODE=2`) against its own captured bundle and is labelled
  `UNPINNED-BUNDLE` in every receipt.
* Vendor captures carry arbitrary captured values in the padded OC lanes of a
  written atom; those lanes are explicitly not a numerical oracle (see
  `docs/CONV_SPATIAL_3X3_C4.md`). The bench compares the defined NCHW values
  (and requires the engine's padded lanes to be zero) and separately records
  that the captured device BO carries the same defined values.
* No full-top, FPGA or hardware execution is claimed.
