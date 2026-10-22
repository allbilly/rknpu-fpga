# Source review and provenance

The original delivery was inspected on 2026-09-20 through public source pages. Upstream branches were **not** cloned or commit-pinned in that environment: container network/DNS access failed. URLs below identify the reviewed paths, not an assertion that their moving branch contents will remain identical. The accelerator RTL is original local code using observed interface facts; the Fedora continuation additionally bundles licensed Xilinx primitive simulation models as described below.

The paragraph above describes the original delivery environment. On the Fedora continuation, `allbilly/rk3588` was fetched into `build/reference/rk3588` at `e13d99fa9dde64b409fed10faa38c1629ab37d54` and the local YPCB reference was checked at `8b13ecf71b7061dd43a2b1580f0caa469f64303f`. Neither source checkout is a captured RK3588 execution. The separate working tinygrad backend revision and hardware buffer/command/output captures are still needed for gate B.

Pinned EW source: https://github.com/allbilly/rk3588/blob/e13d99fa9dde64b409fed10faa38c1629ab37d54/examples/elementwise.py

Pinned board constraint: https://github.com/TiferKing/ypcb_00338_1p1_hack/blob/8b13ecf71b7061dd43a2b1580f0caa469f64303f/constraints/ypcb003381p1.xdc

The local reference XDC SHA256 is `f958a95ba4dfcd96270d36afb12683b954aca635a0af515b164a61e5948587a9`; `board.xml` is `558d4828c4eafb79c7f4d1e412c9c2923f1372855a33b31332fbc9635a318f46`.

The pinned EW example SHA256 is `bee5cd1dcce48852af475673688f210947a3e95c73b6aecb535463772e79750a`; GEMM is `df0f4b98a1fa265b549ae0be682de1b68b9e23bb8cc8cd110a06e2f4b19e6fe6`; `sim/csc_sim.py` is `e928a86510ac4e43369d1578e9156ce424c7e5795ec3ece3e7d0d3efefb536d8`. The CSC model uses a float64 reference accumulation; it supplies layout/traversal evidence, not a bit-exact FP16 CMAC/CACC contract.

`allbilly/npu` was also fetched sparsely at `e02707ca9b010372f1c506c7f3a2fa2c9f2beb8e`. Its README identifies it as the older C register driver and points at `rk3588` for the Python rewrite. This is not the tinygrad backend. No source from either reference was imported into this RTL.

The RK3588 source notes identify `allbilly/tinygrad`, branch `rockchip-2608-ew-restart`. Its public head was fetched at `c6784623afc4f116ae7dc326ab9842e6bf9a3dcf` into `build/reference/tinygrad-rockchip`. This is a source-referenced candidate backend revision, not confirmation of the user's private/current hardware checkout. The audit follows `tinygrad/renderer/rockchip.py:emit_ew_stage`, `patch_stage`, and `tinygrad/runtime/ops_rockchip.py:RockchipProgram._submit_pcchain` through the final command BO bytes.

`verification/check_backend_encoder.py` invokes those unmodified functions while replacing allocation and the final device submission with in-process test buffers. It compares the final ADD/SUB/MUL bytes with the supported profile and feeds those bytes to the existing RTL testbench. Inputs/expected outputs remain synthetic. This is encoder/RTL evidence, not an RK3588 capture, a hardware runtime hook, or evidence for backend host layout stages. The stateful direct tail and linked multi-task form remain unsupported by this core.

## Rockchip interface

`allbilly/rk3588`, `main`, `examples/elementwise.py`:

https://raw.githubusercontent.com/allbilly/rk3588/main/examples/elementwise.py

Reviewed `reg`, `E`, the EW constants, `write_regs_to_npu_task` and `run_op`. These establish the QWORD fields, the three selected operation encodings, fixed FP16 profile, group count, device addresses and terminal-tail form. `model/profile.py` records that selected profile. The source's arithmetic check uses a tolerance and does not constitute bit-exact coverage of all IEEE exceptional cases.

`allbilly/rk3588`, `examples/gemm.py` and `sim/` were also inspected to scope subsequent work:

https://github.com/allbilly/rk3588/blob/main/examples/gemm.py

https://github.com/allbilly/rk3588/tree/main/sim

These inform the need to preserve packing/CBUF semantics and to reuse existing CSC simulation knowledge. The GEMM path is not implemented here. `allbilly/npu` was identified as another user-owned reference; no claim of a complete audit of that repository or the ~1500-line backend is made.

## soDLA and Somnia

https://github.com/soDLA-publishment/soDLA/blob/soDLA_beta/src/main/scala/nvdla/cmac/NV_NVDLA_CMAC_CORE_mac.scala

The inspected CMAC leaf uses `.asSInt` multiplication and signed reduction. That is the basis for rejecting an unverified drop-in FP16 reuse claim. The review applies to that code path, not every possible soDLA configuration or future branch.

https://github.com/soDLA-publishment/soDLA

https://github.com/soDLA-publishment/somnia

Project descriptions distinguish the reusable fuller implementation from the simplified teaching design. Neither description alone proves RK numerical or register compatibility.

## YPCB board facts

https://github.com/TiferKing/ypcb_00338_1p1_hack/blob/main/constraints/ypcb003381p1.xdc

Clock/reset and the three LED pin assignments and LVCMOS18 standards were used as factual board-interface references.

https://github.com/TiferKing/ypcb_00338_1p1_hack/blob/main/ypcb003381p1/1.0/board.xml

This identifies `xc7k480tffg1156-2` and the single-ended 50 MHz oscillator. Configuration-bank voltage/CFGBVS and LED polarity were not established by this review. Those remain explicit build-time checks rather than guessed settings.

## Tool interfaces

`tests/vendor/xilinx-unisim` contains unmodified functional primitive models and the Apache-2.0 license from Xilinx's public simulation library at commit `1c8e05fd1e9a79ceb8b996a0996674122eed086f`: https://github.com/Xilinx/XilinxUnisimLibrary/tree/1c8e05fd1e9a79ceb8b996a0996674122eed086f

These are used only to simulate the Yosys-mapped board netlist. Yosys's own RAMB36E1 declaration lacks a functional memory body. The board implementation continues to infer BRAM/DSP from the original RTL; no simulation model is used in its synthesis sources.

https://verilator.org/guide/latest/exe_verilator.html

Official CLI reference for the `--binary`, `--timing`, `--assert` and top-module-based runner. The documented build flow is not evidence that it was executed here.

https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/report_drc

https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/check_timing

https://docs.amd.com/r/2023.2-English/ug908-vivado-programming-debugging/Vivado-Lab-Edition

Official references for design checks and the distinction between Lab programming/debugging and a synthesis/implementation installation.

The 2026-09-21 build-control audit also used AMD's [CFGBVS](https://docs.amd.com/r/en-US/ug912-vivado-properties/CFGBVS) and [CONFIG_VOLTAGE](https://docs.amd.com/r/en-US/ug912-vivado-properties/CONFIG_VOLTAGE) property definitions. They establish the legal 7-series voltage/strap pairs and that these settings affect implementation/DRC, not the actual values fitted to YPCB. The build now applies supplied settings before its DRC report. [get_timing_paths](https://docs.amd.com/r/en-US/ug835-vivado-tcl-commands/get_timing_paths) documents the queried worst setup/hold paths. Local Tcl control-flow tests do not replace executing these commands in full Vivado.

A read-only alternative-toolchain audit fetched [openXC7/nextpnr-xilinx](https://github.com/openXC7/nextpnr-xilinx/tree/d486d8ef6a1c756ca72b2ba495e7e18e4c24815d) at `d486d8ef6a1c756ca72b2ba495e7e18e4c24815d` into `build/reference/nextpnr-xilinx`. `xilinx/xdc.cc` uses literal target lookup, ignores `[current_design]` properties, and has no `set_false_path` handler. The implications for this project's existing XDC are documented in `FPGA.md`. This is not a claim that no openXC7 flow can ever support the board; no openXC7 implementation or bitstream was run here.

## Test provenance

All delivered vector files/ROMs are **synthetic**, produced from documented profiles and the independent Python binary16 reference. No test output in this package is a captured RK3588 output. `verification/README.md` separates the original software-only delivery logs from the Fedora continuation's source-bound RTL and mapped-netlist evidence. Build-script control-flow tests use simulated tool responses, not Vivado DRC/timing results. Do not relabel model agreement as silicon equivalence.
