# Capture-bounded FP16 maximum pooling with indices

Status: **one fixed standalone candidate, simulation-only**. The leaf covers
only `fp16_max_k2s2_index_c8_h2w2`; it is separate from the unindexed max,
minimum and average leaves. There is no PPU register decoder, DMA/RDMA, AXI,
full-top integration or FPGA execution.

## Captured contract

The source is `/home/fedora/rk3588/examples/expt/pooling.py`, SHA-256
`2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`.
`maximum_with_index_reference()` at lines 761–793 uses row-major `np.argmax`
and encodes each local position as `(row << 3) | column`. The case at lines
837–856 is FP16 C8, H2 W2 → H1 W1, maximum, 2x2 kernel, stride 2, no padding,
`INDEX_EN=1`, `USE_CNT=0`.

The pinned fixture is
`tests/ppu_pooling/fixtures/fp16_max_k2s2_index_c8_h2w2/manifest.json`:

- device capture status `OK`, `submit_ret=0`, `/dev/accel/accel0`, kernel
  `6.18.24-current-rockchip64`, runner `rocket_run.py 1.0.0`;
- input BO SHA-256
  `ffceeac7421c945addac9bbf0d30a2f6a2cb83487a33357bed5ebbdeab545f2a`;
- source expected and device output BO SHA-256
  `011231103b526b363a612647ff1825583fee0a52f375366de1fbf16e0bb89f35`;
- original raw command stream is preserved (26 QWORDs), SHA-256
  `d5463e486464246469833cc394ae15260bba53d1fbaed8bbb8316771b97eb77b`; capture
  metadata separately binds its address-patched version. This datapath leaf
  does not decode or execute either stream.

The captured 32 FP16 values are finite: 24 positive zeros and eight distinct
positive values. Each channel has exactly one maximum, values 100–107, at
positions `[0,1,8,9,0,1,8,9]`. The candidate therefore does not depend on a
tie-break for the observed winners. The RTL uses first-input tie selection to
match the source `argmax` order, but NaN, infinity, signed-zero and other
special-value policies are not qualified. Inputs outside the pinned capture
are not admitted by the runner contract.

## Output layout and interface

Four raster-order 16-byte C1HWC2 input atoms (64 logical bytes, 32-byte line
stride) produce one paired value/index transfer. The value atom occupies output
bytes 0–15. The captured index atom is eight little-endian uint16 positions at
bytes 32–47. Bytes 16–31 are a gap, and bytes 48–4095 are the untouched tail.
The pair shares one valid/ready handshake and is held stable under backpressure.
After the one result is accepted, another input frame is refused until reset.

## Verification

`tools/ppu/run_pool_index.py` pins every fixture hash and mode/layout field,
checks the source argmax values and positions, then runs Icarus and Verilator in
always-ready and forced-stall modes (seeds `0x3588` and `0x600d`). It compares
all 4096 output BO bytes to the device capture, including the gap and untouched
tail; it also checks eight value and eight index lanes, output stability,
`out_last`, and post-frame input rejection. Negative contract controls reject
other methods, shapes, stride, index layouts, non-finite/negative-zero data and
ties.

Focused results: Icarus Verilog 13.0 and Verilator 5.048 (2026-04-26 build),
two modes each, no warnings. Each run consumed four inputs and emitted one
value/index pair; all 4096 bytes and all value/index lanes matched exactly, the
gap and tail remained unchanged, and the forced-stall mode observed one stall
cycle. Reports are
`build/ppu-pooling/index-iverilog-20261106T192733Z/report.json` and
`build/ppu-pooling/index-verilator-20261106T192733Z/report.json`. Both record
`hardware_accessed=false` and unchanged source hashes during replay.

Commands:

```sh
make ppu-index-contract-test
make ppu-index-four-state-test # Icarus Verilog
make ppu-index-test            # Verilator
verilator --lint-only -Wall --top-module rk_ppu_pool_max2x2s2_index_c8_h2w2 \
  rtl/ppu/rk_ppu_pool_max2x2s2_index_c8_h2w2.sv
```

This is standalone simulation evidence, not FPGA, RK silicon, register/DMA or
full-top qualification. Other `INDEX_EN` shapes, tie and special-value cases
remain unsupported.
