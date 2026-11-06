# Capture-bounded FP16 minimum-pooling leaf

Status: **one fixed standalone candidate, simulation-only**. The leaf supports
only the captured `fp16_min_k2s1_valid_c8_h4w4` datapath. It does not connect to
the PPU register decoder, DMA/RDMA, AXI, a full top or the FPGA. The saved RK
capture is fixture evidence; this RTL increment did not access a board.

## Captured contract

The pinned source is `/home/fedora/rk3588/examples/expt/pooling.py`, SHA-256
`2ba6c5ae06ffac0daeb0d64d13320ada4c4f26593b86248da7ea1e24e20e4f6e`.
`pool_reference()` at lines 731–758 applies `np.min` to each spatial window;
the case at lines 799–818 is FP16 C8, H4 W4 → H3 W3, 2x2 kernel, stride 1,
valid padding, `INDEX_EN=0`, `USE_CNT=0`. The source requires exact comparison
(tolerance 0.0) for minimum pooling.

The captured device result is bound by
`tests/ppu_pooling/fixtures/fp16_min_k2s1_valid_c8_h4w4/manifest.json`:

- capture status `OK`, `submit_ret=0`, `/dev/accel/accel0`, kernel
  `6.18.24-current-rockchip64`, runner `rocket_run.py 1.0.0`;
- input BO SHA-256
  `8035f829849d56a1a91332b6153c1bef9f1a56ea59470da42689c63a2ec910b2`;
- exact device output and source expected BO SHA-256
  `bca82f92970dbcd7ad4a31a89d3f1e0868276c16b25185b8081e8e3234bd4d6a`;
- original command stream is retained byte-for-byte (26 QWORDs), SHA-256
  `0a917feade18038ec8e1cfb244b9116193d4f4f6d75c5819ffa83b55ec82e013`;
  capture metadata separately binds the address-patched device stream. Neither
  stream is decoded or executed by this standalone datapath.

The input contract has 128 finite FP16 lanes, 32 negative values, one positive
zero, no negative zero, NaNs or infinities, and range [−4, 11.875]. A standalone
finite comparator implements the four-input minimum for this captured data.
The RTL emits unknown simulation values for non-finite encodings or an
opposite-signed-zero comparison. These are explicit unqualified cases, not an
inferred RK PPU policy. No other special-value, shape, precision, padding,
index, kernel or stride behavior is claimed.

## Layout and leaf behavior

Input and output use 16-byte C1HWC2 atoms, little-endian FP16, and one surface.
The input has a 64-byte line stride and 256 logical bytes in its 4096-byte BO.
The output has a 48-byte line stride, 144 value bytes (72 FP16 lanes) in the
original 4096-byte BO. The leaf emits nine row-major output atoms. It buffers
one 4x4 frame, maintains the previous input row and current-row atom, and
refuses another input atom after the sixteenth accepted atom until reset.
Output data and `out_last` are held stable under backpressure. The unused output
tail remains initialized and unwritten.

The implementation is deliberately a separate fixed-case leaf. It does not
admit pooling fields or silently ignore unsupported modes. PPU register
classification, explicit mode failures, DMA, AXI integration and full-top
qualification remain separate work.

## Verification

`tools/ppu/run_pool_min.py` hash-checks every fixture file, validates the exact
mode/shape/layout and capture provenance, and independently evaluates the
finite source minimum from the captured input before simulation. The Icarus and
Verilator testbenches each run always-ready and deterministic backpressure
(seeds `0x3588` and `0x600d`). They check 16 input handshakes, nine output
handshakes, `out_last`, stalled-output stability, rejection of a second frame,
all 4096 output BO bytes and the untouched tail. The contract unit test rejects
shape/mode/layout/numerical drift and refuses non-finite or negative-zero input.

Latest focused run (2026-11-06): Icarus Verilog 13.0 and Verilator 5.048
(2026-04-26 build), two modes each. Each run accepted 16 input atoms and emitted
nine output atoms; all 4096 BO bytes match the device capture, all 72 value
lanes match exactly, the tail is preserved, output stability and second-frame
rejection pass, and the source-oracle bytes equal the captured device bytes.
There were no simulator warnings. Reports are
`build/ppu-pooling/min-iverilog-20261106T191145Z/report.json` and
`build/ppu-pooling/min-verilator-20261106T191145Z/report.json`; both record
`hardware_accessed=false` and source hashes matching before and after the run.

Commands:

```sh
make ppu-min-contract-test
make ppu-min-four-state-test # Icarus Verilog
make ppu-min-test            # Verilator
verilator --lint-only -Wall --top-module rk_ppu_pool_min2x2s1_fp16_capture \
  rtl/ppu/rk_ppu_pool_min2x2s1_fp16_capture.sv
```

These tests are standalone simulation only; they do not validate SystemVerilog
on the actual FPGA or RK silicon. Reports record simulator versions, source and
fixture hashes, seeds, and `hardware_accessed=false`. Build artifacts are
pruned by default.
