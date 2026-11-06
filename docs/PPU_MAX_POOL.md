# Standalone PPU FP16 max-pooling increment

Status: **two unindexed max-pool, one average, one minimum-pool, one indexed
max-pool and one C3-tail capture candidate, simulation-only**. See the separate
[capture-bounded FP16 minimum leaf](PPU_MIN_POOL.md). The pre-existing RK3588 capture is only fixture evidence:
no board was accessed for this RTL
increment, no bitstream was built, no Vivado full-top implementation was run
and no FPGA execution is claimed.

The first two leaves implement only FP16 maximum pooling with a 2x2 kernel,
stride 1, valid padding, eight channels per 16-byte C1HWC2 atom. The next isolated leaf
replays exactly one separate capture with a 2x2 kernel, stride 1, one-cell
padding, C8 H2 W2 negative input and captured `-infinity` padding. They are
independent of the NVDLA PDP. No mode/register decoder, DMA, AXI memory path or
full-top integration connects these leaves; unsupported pooling modes are not
admitted. A separate [capture-bounded FP16 average leaf](PPU_AVERAGE.md) covers
only `fp16_avg_k2s1_valid_c8_h4w4`; it does not generalize to another average
mode, shape, rounding policy or PPU integration. These unindexed max leaves do
not implement `INDEX_EN`; one separate capture-bounded indexed case is documented
in [PPU_MAX_INDEX.md](PPU_MAX_INDEX.md). No leaf here implements convolution or
any CMAC/K8 change.

## Evidence and scope

The replayed case is the real captured RK3588 task
`fp16_max_k2s1_valid_c8_h4w4`:

- input C8 H4 W4, output C8 H3 W3; kernel 2x2, stride 1, no padding,
  `INDEX_EN=0`, `use_cnt=0`.
- device capture directory (workspace-local):
  `build/rk3588-example-captures/results/pooling-20261105T203205Z/pooling/fp16_max_k2s1_valid_c8_h4w4`
- device `/dev/accel/accel0` (`rockchip,rk3588s`, `xunlong,orangepi-5`),
  kernel `6.18.24-current-rockchip64`, mainline Rocket runner
  `rocket_run.py 1.0.0`.
- input BO SHA256 `8035f829849d56a1a91332b6153c1bef9f1a56ea59470da42689c63a2ec910b2`
- initialized output BO SHA256
  `ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7`
- device output BO SHA256
  `39d178de3e4a7dd020c66d23437b18082ec2c00541efbc979b773f8bee45ce60`
- unpatched source command stream SHA256
  `75f7c70eb3eafc8345a634633f9c45df231dad1195f79ad1f9a2ea7038a4cebf`
  and device-patched SHA256
  `32a8fe3772f79dd74bc1ed6952055d5b2720ccdfbb4bdd11c516ada15142f649`.

The device output BO SHA256 is identical to the bundle's host
`expected.bin` for this case, but the testbench and independent checker use
the **device** `out.bin` bytes. Fixture provenance is recorded in
`tests/ppu_pooling/fixtures/fp16_max_k2s1_valid_c8_h4w4/manifest.json`.

Verified result in both simulators, with always-ready and deterministic
backpressure:

| Simulator | Runs | Input atoms/frame | Output atoms/frame | Value bytes | FP16 lanes | Full BO bytes | Byte mismatch | Lane mismatch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Icarus Verilog 13.0 | 2 | 16 | 9 | 144 | 72 | 4096 | 0 | 0 |
| Verilator 5.048 | 2 | 16 | 9 | 144 | 72 | 4096 | 0 | 0 |

The full 4096-byte output BO matches, not just the 144-byte value surface.
The untouched tail (bytes `0x90..0xfff`) remains equal to `out_init.bin`.
No tolerance is used for max: all 72 output halfwords are exact.

## Second increment: one captured padded negative case

`rtl/ppu/rk_ppu_pool_max2x2s1_pad1_neg_c8_h2w2.sv` is a separate fixed-case
leaf for `fp16_max_k2s1_pad1_neg_c8_h2w2`. It buffers exactly four row-major
input atoms and emits the 3x3 surface. Out-of-range window positions are
explicitly the captured FP16 `-infinity` value `0xfc00`; captured input lanes
are finite negative half values. The comparison is intentionally limited to
those finite-negative inputs and that observed padding value. It does not
define or promote a general PPU MAX policy for NaNs, signed zero, infinities in
the input, subnormals or other special values. It is a single-frame leaf: after
the four atoms are accepted and nine outputs emitted, reset is required before
another frame.

Capture provenance is bound in
`tests/ppu_pooling/fixtures/fp16_max_k2s1_pad1_neg_c8_h2w2/manifest.json`:

- device capture `build/rk3588-example-captures/results/pooling-20261105T203205Z/pooling/fp16_max_k2s1_pad1_neg_c8_h2w2`, status `OK`, device `/dev/accel/accel0`, Rocket `rocket_run.py 1.0.0`, kernel `6.18.24-current-rockchip64`;
- PPU method maximum, FP16 C8, kernel `[2,2]`, stride `[1,1]`, padding `[1,1,1,1]`, input `[2,2]`, output `[3,3]`, `INDEX_EN=0`, `use_cnt=0`; the capture description and command stream identify padding bits `0xfc00`;
- input BO SHA256 `c3a1ca7552e9f762be8c2f037f9313fd0681ec76aa3b8567d5fed477f311b834` and initialized output BO SHA256 `ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7`;
- exact device `out.bin` SHA256 `a18647840e9e8c3abb2f004ee47e6d629d735755b8dbdd5e5b340e314f03411e`; the fixture does not substitute the bundle's `expected.bin` for device output.

The captured input is four 16-byte atoms with 32-byte input line stride and 64
logical bytes. The output is nine atoms at 48-byte line stride: 144 value bytes
and 72 FP16 lanes in a 4096-byte output BO. Both simulators run always-ready
and deterministic output-backpressure modes, assert output stability while
stalled, compare every output byte and lane against device `out.bin`, and check
the entire tail (`0x90..0xfff`) remains equal to `out_init.bin`.

Verified with Icarus Verilog 13.0 and Verilator 5.048 (2026-04-26 build):

| Simulator | Runs | Input atoms | Output atoms | Full BO mismatches | Lane mismatches | Stall cycles (always / backpressure) |
|---|---:|---:|---:|---:|---:|---:|
| Icarus Verilog | 2 | 4 | 9 | 0 | 0 | 0 / 1 |
| Verilator | 2 | 4 | 9 | 0 | 0 | 0 / 1 |

Both runs produce the device BO SHA256
`a18647840e9e8c3abb2f004ee47e6d629d735755b8dbdd5e5b340e314f03411e` with zero
tail differences. Reports, compile/run logs and observed BOs are in
`build/ppu-pooling/iverilog-pad1-commit-a60e864/` and
`build/ppu-pooling/verilator-pad1-commit-a60e864/`; each report records
source/fixture hashes, tool version, seeds `0x3588` / `0x600d` and
`hardware_accessed=false`.

Each max leaf is an isolated datapath candidate, not PPU mode admission. No other
padding configuration, shape, stride, kernel, data class, index mode, minimum
or global pooling operation is connected to or admitted by these unindexed max
leaves. Separate single-capture candidates cover one indexed C8 case
([PPU_MAX_INDEX.md](PPU_MAX_INDEX.md)) and one C3 physical-tail case
([PPU_C3_TAIL.md](PPU_C3_TAIL.md)); neither broadens these leaves.
There is no register decode or silent-ignore path: those interfaces do not
exist here and must be separately designed with source evidence, explicit
unsupported-field failures and tests before integration.

## Interface

`rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv`:

| Port | Direction | Meaning |
|---|---|---|
| `clk` | input | Single clock. |
| `rst_n` | input | Active-low synchronous reset. Reset both the core and its producer/consumer in a future integration. |
| `in_valid` / `in_ready` | input / output | Input atom handshake. Transfer occurs on a rising edge with both high. `in_valid` and `in_atom` must remain stable while `in_valid=1` and `in_ready=0`. |
| `in_atom[127:0]` | input | One C1HWC2 pixel atom: eight little-endian FP16 channels, 16 bytes. |
| `out_valid` / `out_ready` | output / input | Output atom handshake. `out_atom` and `out_last` remain stable while `out_valid=1` and `out_ready=0`. |
| `out_atom[127:0]` | output | One 16-byte output pixel atom in the same channel order. |
| `out_last` | output | Asserted with the final output atom of a frame, otherwise low. |

Parameters `IN_H` and `IN_W` set the input surface. Output dimensions are
`OUT_H=IN_H-1`, `OUT_W=IN_W-1`; the retained instance is `IN_H=4, IN_W=4`.

A frame is exactly `IN_H*IN_W` accepted input atoms in raster order
(surface, y, x, atom). Counters and ping-pong row-buffer roles wrap
automatically, so the interface is intended to permit consecutive frames
without reset; only a single frame is verified by this increment. `out_last`
is high only on output atom `(OUT_H-1, OUT_W-1)`. Input and output atoms are
accepted one
per clock; after the first input row, each accepted input produces at most one
output, and an output-stall cycle backpressures the input. `out_valid` is
registered; there is no combinational path from `in_valid` to `out_valid`.

Future register/DMA integration must supply the dimensions, source/destination
addresses, line/surface strides and atom count explicitly. This core has no
CSB, PPU register map, descriptor parsing, memory request port or interrupt.

## Layout contract

The captured layout is reproduced directly:

- input: 16-byte atom, line stride `IN_W*16` = 64 bytes, surface stride
  `IN_H*IN_W*16` = 256 bytes, one surface, 256 logical bytes in a 4096-byte BO;
- output: 16-byte atom, line stride `OUT_W*16` = 48 bytes, surface stride
  `OUT_H*OUT_W*16` = 144 bytes, one surface, 144 value bytes in a 4096-byte
  BO; no index region and no output padding/tail write.

Output atoms are emitted in row-major order: output `(y,x)` is the lane-wise
maximum of input pixels `(y,x)`, `(y,x+1)`, `(y+1,x)` and `(y+1,x+1)`. Because
the kernel is 2x2, stride 1 and padding is zero, every output window is fully
inside the input and there is no logical padding value. Unused BO bytes are
not written by hardware; the testbench checks they remain at their initialized
values.

## Numerical behavior

The core compares the 16-bit FP16 encodings lane by lane. It performs no
addition, multiplication, reciprocal, conversion, accumulation or channel
mixing. The implemented maximum policy is:

- finite and infinite values use the IEEE encoded ordering (nonnegative wins
  across signs; for negatives the smaller magnitude wins);
- `+0` wins over `-0`;
- any NaN operand produces `0x7c01`, matching the project's captured RK
  elementwise FP16 MAX result constant.

The retained PPU capture contains finite values, including negative inputs in
the first row; its outputs are positive after the max. No NaN, infinity,
signed-zero or subnormal payload is present, so only the finite-ordering path
is device-observed for this mode. The signed-zero and NaN choices are
**candidate PPU behavior** until a PPU special-value capture exists. This
increment does not establish subnormal, NaN-payload, exception flag or
infinity behavior for the RK PPU. This valid-padding max leaf does not implement
`INDEX_EN`; see [PPU_MAX_INDEX.md](PPU_MAX_INDEX.md) for the separate one-case
indexed candidate and its narrower scope.

## Architecture and estimated area

The core uses two ping-pong line buffers of `IN_W` 128-bit atoms and one
current-row history atom. For every accepted atom it forms the four-input
maximum for each of eight lanes (three 16-bit comparisons per lane, 24
comparators total) and registers one output atom. There are no multipliers,
adders, DSPs or block RAMs.

A local Yosys 0.65 `synth_xilinx -family xc7` estimate for the standalone
module (not a Vivado build and not timing signoff) reports 1,364 LUT2..LUT6
cells, 263 FDREs, 44 RAM32M, 96 CARRY4, 235 MUXF7 and 15 MUXF8, with 1,284
estimated LCs. This is a small leaf, not the 39.6K-LUT NVDLA PDP prototype.
The estimate has no placement, routing, clock constraint or physical-fit
meaning. The report command is retained under `build/ppu-pooling/area/`; it
does not emit a bitstream:

```sh
yosys -p 'read_verilog -sv rtl/ppu/rk_ppu_pool_max2x2s1_c8.sv; synth_xilinx -family xc7 -top rk_ppu_pool_max2x2s1_c8; stat'
```

## Verification method

`tests/ppu_pooling/tb_ppu_pool_max2x2s1_c8.sv`:

1. `$fread()`s the raw captured input BO, initialized output BO and device
   output BO (4096 bytes each).
2. Initializes the observed BO with `out_init.bin`.
3. Drives 16 input atoms at the captured 64-byte line stride using the
   valid/ready contract. It runs once with `out_ready=1` and once with
   deterministic LFSR backpressure, checking that stalled `out_atom` and
   `out_last` do not change.
4. Places the nine output atoms at the captured 48-byte output line stride.
5. Compares all 4096 observed bytes and each of the 72 value-region FP16 lanes
   with the device BO, then writes the observed BO for independent recheck.

`tools/ppu/run_pool_max.py` verifies the fixture hashes before compiling,
records the simulator/tool versions, source hashes and git revision, runs both
backpressure modes, independently compares the observed BO against the device
BO, checks the tail against `out_init.bin`, and records a JSON report and logs
under `build/ppu-pooling/`.

The first passing pre-commit run used source base `a9b5d02` plus the hashes
recorded in each report. Icarus and Verilator results are separate; the
C++/Python check does not validate SystemVerilog, and neither simulator
validates the RK silicon or an FPGA.

Full-regression context: `make -j4 test` was also run on this worktree. The
PPU targets in that run passed both simulators, but the overall target exited
with status 2 at the unrelated `ddr-dual-host-npu-test` target. That target
rejects the pre-existing base `a9b5d02` binding:
`rtl/ddr/dual_host/sources.json` hashes to
`77f0fdea5c7009bbc701d5495a045ca341929d3ff1c33556b535abc498852ae9`, while
`rtl/ddr/dual_host/frontend-sources.json` still records
`aec38d144a398f0d1c92570e75c4726669c92eee4a8b2574a9e8d0e50fcf1d21`.
Both files are unchanged in this increment and the mismatch is present in the
base commit. The exact log is `build/regression/make-test.log` with exit code
`build/regression/make-test.rc`. This increment does not change or relax that
dual-host pin.

## Reproduction

```sh
make generated-check
make ppu-max-four-state-test   # Icarus Verilog
make ppu-max-test              # Verilator
make ppu-max-pad1-four-state-test # Icarus Verilog, exact padded device capture
make ppu-max-pad1-test            # Verilator, exact padded device capture
make ppu-avg-contract-test         # strict shape/mode rejection controls
make ppu-avg-test                  # Verilator, one capture-bounded FP16 average case
make ppu-avg-four-state-test       # Icarus, same FP16 average case
make ppu-min-contract-test         # strict captured minimum case controls
make ppu-min-test                  # Verilator, one capture-bounded FP16 minimum case
make ppu-min-four-state-test       # Icarus, same FP16 minimum case
make ppu-index-contract-test       # strict captured indexed-max case controls
make ppu-index-test                # Verilator, one capture-bounded max+index case
make ppu-index-four-state-test     # Icarus, same max+index case
make ppu-c3-tail-contract-test     # strict captured C3 physical-tail controls
make ppu-c3-tail-test              # Verilator, one capture-bounded C3 tail case
make ppu-c3-tail-four-state-test   # Icarus, same C3 tail case
make ppu-max-lint
```

Or directly:

```sh
python3 tools/ppu/run_pool_max.py --simulator iverilog
python3 tools/ppu/run_pool_max.py --simulator verilator
python3 tools/ppu/run_pool_pad1.py --simulator iverilog
python3 tools/ppu/run_pool_pad1.py --simulator verilator
python3 tools/ppu/run_pool_avg.py --simulator iverilog
python3 tools/ppu/run_pool_avg.py --simulator verilator
python3 tools/ppu/run_pool_c3_tail.py --simulator iverilog
python3 tools/ppu/run_pool_c3_tail.py --simulator verilator
```

Each run writes `report.json`, compile/run logs and observed BOs. Reports are
scoped to simulation; they set `hardware_accessed=false`,
`vivado_executed=false` and `bitstream_emitted=false`.

## Remaining work

Not implemented or not qualified by this increment:

- average outside the one source- and capture-bounded case documented in
  [PPU_AVERAGE.md](PPU_AVERAGE.md), minimum outside the case in
  [PPU_MIN_POOL.md](PPU_MIN_POOL.md), and global pooling; other
  reciprocals, `use_cnt` values and rounding policies;
- `INDEX_EN` outside the one fixed case in
  [PPU_MAX_INDEX.md](PPU_MAX_INDEX.md), including other index layouts and
  position-tracking rules;
- padding modes other than the one captured pad-1 case above, non-unit/other
  strides, kernels other than 2x2, output upsampling, notches and arbitrary
  dimensions;
- channel tails outside the one fixed C3 case in
  [PPU_C3_TAIL.md](PPU_C3_TAIL.md), more than one surface, other C3 shapes,
  C16 and INT8/INT16 data;
- PPU register decode, completion/error status, `PPU_MISC_CTRL` classification,
  CSB readback and explicit unsupported-field failures;
- DMA/PPU_RDMA, AXI/DDR memory access, line/surface stride generation,
  descriptor/task handling and backpressure across memory faults;
- full-top integration, clock/reset domain integration, CDC and interrupt
  wiring;
- PPU special-value captures beyond the observed `-infinity` padding (NaN,
  input infinity, signed zero, subnormal), INT8/INT16 arithmetic and index
  aliasing;
- synthesis, placement, routing, timing, DRC, area signoff and bitstream;
- actual FPGA replay and RK3588 differential testing for this core.

## Artifact retention

The tracked increment contains separate standalone cores and testbenches,
fixture BOs/manifests, runners, Makefile targets and this document. Build
reports/logs/observed BOs are under
`build/ppu-pooling/`; simulator object trees and executables are pruned after
each passing run. No multi-GB compiler or simulator byproduct is retained.
