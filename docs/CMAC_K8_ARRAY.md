# C32/K8 arithmetic array increment

Status: tracked simulation-only arithmetic increment. K16 remains the default
and reference profile. No raw-command front-end, OC8 frame writer, DMA body or
tail change, profile decode change, backend packing, real-capture replay,
FPGA/board execution or bitstream is included.

## Scope

The selected arithmetic chain was already `ATOMIC_K`-parameterized:

- `rtl/ddr/framework/rk_cmac_cacc_fp16_array.sv` passes `ATOMIC_K` to the CMAC
  and CACC children.
- `rtl/ddr/framework/rk_cmac_fp16_array_dsp_prefix_pipe.sv` instantiates one
  C32 cell per kernel and concatenates `ATOMIC_K*44` groups.
- `rtl/cmac/rk_cacc_fp16_array.sv` instantiates one independent NVDLA FP48
  accumulator per kernel.
- The original `rtl/cmac/rk_cmac_fp16_array.sv` and
  `rtl/cmac/rk_cmac_cacc_fp16_array.sv` are also `ATOMIC_K`-parameterized.

No arithmetic RTL change was required. This increment makes K8 a tracked,
source-bound instantiation instead of a build-local study copy:

- `tests/cmac/tb_cmac_cacc_fp16_array.sv` admits `ATOMIC_K=8` in addition to
  the existing `1` and `16` values.
- `tools/cmac/test_cmac_cacc.py` accepts `--kernels 8` and selects either the
  original combinational chain (`--array legacy`, default) or the tracked
  framework two-stage DSP-prefix chain (`--array framework`).
- `tools/cmac/gen_cmac_array_vectors_k8.py` derives the K8 CMAC corpus from
  the unchanged 208-frame C32/K16 corpus.
- `tools/cmac/test_cmac_k8_lower_slice.py` runs the CMAC-group and
  CMAC/CACC-final lower-slice checks.
- `fpga/cmac/Makefile` adds the `ARRAY_PROFILE` switch (default `legacy`) and
  the `cmac-k8-lower-slice-test` target.

## Lower-slice contract

The K8 corpus is not a new RK capture and introduces no new numerical policy.
For every one of the 208 unchanged C32/K16 CMAC rows:

- input vector and input mask are unchanged;
- K8 weights are kernels 0..7 of the K16 weight vector;
- K8 weight masks are kernels 0..7 of the K16 weight masks;
- K8 expected groups are the low `8*44` bits of the K16 expected groups.

The connected CACC test then compares the K8 final `8*32` values with the low
`8*32` bits of the unchanged K16 CACC goldens. This is exact lower-slice
equality, not a regenerated numerical oracle and not a new layout contract.

Source corpus hashes:

- CMAC K16: `a5be0591c6262c9e6292d6a02166b435a459056810425ecc220d74341a0e15f3`
- CACC K16: `126ba21fc30b7cad9863393beaeb0858191059b8264aa14518d0ae9575f7623a`

## Icarus results

Tool: `Icarus Verilog version 13.0 (stable) (v13_0)`.

| Test | Command | Result |
|---|---|---|
| K8 CMAC groups | `python3 tools/cmac/test_cmac_k8_lower_slice.py --tool iverilog` | 208 frames, 1664 checked groups, 1656 retired, 8 reset-canceled, 520 held cycles, 1 X-rejection fault |
| K8 CMAC/CACC final | same command | 208 frames, 200 outputs, 10 resets, 3 cancels, 110 held cycles |
| K8 legacy CACC | `python3 tools/cmac/test_cmac_cacc.py --kernels 8 --array legacy` | 208 frames, 200 outputs, 10 resets, 3 cancels, 110 held cycles |
| K8 framework CACC | `python3 tools/cmac/test_cmac_cacc.py --kernels 8 --array framework` | 208 frames, 200 outputs, 10 resets, 3 cancels, 110 held cycles |
| K16 CMAC regression | `python3 tools/cmac/test_array.py --tool iverilog --kernels 16` | 208 frames, 3328 checked groups, 3312 retired, 16 reset-canceled, 520 held cycles, 1 X-rejection fault |
| K16 legacy CACC regression | `python3 tools/cmac/test_cmac_cacc.py --kernels 16 --array legacy` | 208 frames, 400 outputs, 10 resets, 3 cancels, 110 held cycles |
| K16 framework CACC regression | `python3 tools/cmac/test_cmac_cacc.py --kernels 16 --array framework` | 208 frames, 400 outputs, 10 resets, 3 cancels, 110 held cycles |
| K1 seam regression | `python3 tools/cmac/test_cmac_cacc.py --kernels 1 --array legacy` | 208 frames, 25 outputs, 10 resets, 3 cancels, 110 held cycles |

The K8 runner writes a source-bound report under
`build/rknpu-cmac-k8-lower-slice/`. The K16 and K8 connected runs write
`build/rknpu-cmac-cacc-array/c32k{16,8}/`. These are simulator results, not
RK silicon or FPGA results.

## Verilator results

Tool: `Verilator 5.048 2026-04-26 rev vUNKNOWN-built20260426`, C++ GCC
16.2.1.

| Test | Result |
|---|---|
| K8 CMAC groups | 208 frames, 1664 checked groups, 1656 retired, 8 reset-canceled, 520 held cycles, 0 faults (the X-rejection case is Icarus-only in the existing bench) |
| K8 CMAC/CACC final | 208 frames, 200 outputs, 10 resets, 3 cancels, 110 held cycles |

The Verilator compile reports 3 warnings from `NV_NVDLA_CMAC_CORE_MAC_mul.v`
for the CMAC array and 40 warnings from the donor/experimental modules plus
intentional unused upper-slice bits in the K8 bench for the connected run.
There were no `%Error` diagnostics. The unused-slice warnings are a direct
consequence of instantiating one 8-kernel slice from K16 fixtures; they are
not RTL or arithmetic faults.

## Local evidence

Preserved simulator reports/logs (build artifacts, not source-controlled):

- `build/rknpu-cmac-k8-lower-slice/iverilog-1793942192431559222/report.json`
- `build/rknpu-cmac-k8-lower-slice/verilator-1793942414658662027/report.json`
- `build/rknpu-cmac-cacc-array/c32k16/iverilog-1793942797966301109/report.json`
- `build/rknpu-cmac-cacc-array/c32k16/framework-iverilog-1793942926920170589/report.json`
- `build/rknpu-cmac-cacc-array/c32k8/iverilog-1793943074831198103/report.json`
- `build/rknpu-cmac-cacc-array/c32k8/framework-iverilog-1793943141160737821/report.json`
- `build/rknpu-cmac-cacc-array/c32k1/iverilog-1793943217523953377/report.json`
- `build/rknpu-cmac-array/c32k16/iverilog-1793943231382747925/report.json`

Regenerable simulator executables, snapshots and Verilator object directories
were pruned after the reports were written. `build/` measured `15M` at the end
of this increment.

## Build-local switch

```sh
make -f fpga/cmac/Makefile cmac-k8-lower-slice-test TOOL=iverilog
make -f fpga/cmac/Makefile cmac-cacc-test ATOMIC_K=8 ARRAY_PROFILE=framework
make -f fpga/cmac/Makefile cmac-cacc-test ATOMIC_K=16 ARRAY_PROFILE=legacy
```

`ATOMIC_K=16` and `ARRAY_PROFILE=legacy` remain the defaults. The framework
profile checker and `rtl/ddr/framework/sources.json` still declare C32/K16;
this increment does not rebind the production profile.

## Remaining work

The core-level K8 front/datapath/OC8-writer slice is documented separately in
[CMAC_K8_CORE.md](CMAC_K8_CORE.md). This arithmetic increment deliberately
leaves the following untouched:

- `rtl/cmac/rk_cmac_array_datapath.sv`, `rk_cmac_array_front.sv`,
  `rk_cmac_frame_output.sv`, `rk_cmac_array_dma.sv`, `rk_cmac_array_core.sv`,
  `rk_cmac_array_axi.sv` and the framework `rk_cmac_success_rearm` /
  `rk_cmac_async_engine` parameter plumbing;
- `rtl/rk_cmac_profile.sv` and the logical host kernel-group field
  `0x10014024=16`;
- backend `(N/8, K/32, 8, 32)` packing and OC8 output-atom placement;
- DMA amount/tail audit for the K8 frame format;
- real conv-simple/conv-fp16/conv-gemm/GEMM capture replay;
- full-top synthesis, placement, route, timing, DRC, bitstream, board and RK
  execution.
