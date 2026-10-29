# Local reuse candidates — source audit, not execution evidence

The user supplied these repositories for continuing the FPGA implementation.
The 2026-09-21 home-directory inventory was read-only and excluded credential
contents. That inventory did not integrate these candidates. Subsequent source
imports are identified below; old test logs do not establish success against
modified RTL.

## OpenTPU board and transport reference, 2026-10-26

The requested follow-up checked `~/openTPU` with HEAD
`98286b6a4e0806aa80de680845cb33e0a299075b`. Some reference helpers are
untracked working files, so HEAD alone does not identify their contents. The
audit records each selected file's hash and whether it matches a HEAD blob;
it did not modify the donor checkout. Use `OPENTPU_ROOT` for a different local
checkout.
The preserved `bitstreams/spare-dual-host-4gb-c0182800` package supplies the
fixed-clock reference. Its later `c01848` runtime-clock effort is abandoned
according to `HANDOFF.md`; reading that history does not resume it.

Paths in the following table are relative to `OPENTPU_ROOT`:

| Reference | Application here | Boundary |
|---|---|---|
| `docs/vivado_bitstream_guide.md` | Fresh source snapshots, recorded stage exits, strict timing/DRC and image-specific reviews | Its old implementation entrypoints are retired. Do not run its preparers: some generate vendor IP. No OpenTPU build or programming authorization transfers here. |
| `bitstreams/spare-dual-host-4gb-c0182800/evidence/dual-host/otpu_host_reset.sv` | Registered reset output and bounded hold, already used to inform the separate startup wrappers | OpenTPU additionally synchronizes clock lock and PCIe transitions. Our configuration-time reset does not implement its platform recovery protocol. |
| `bitstreams/spare-dual-host-4gb-c0182800/evidence/dual-host/otpu_jtag_mailbox.sv` and `otpu_dual_host.tcl` in the same directory | Exact mailbox import, USER2 ownership, held-payload bounds and first-stage synchronizer exceptions | [Our CDC script](../fpga/host/mailbox_cdc.tcl) binds our hierarchy and 50 MHz clock. OpenTPU routed receipts cannot qualify those new paths. |
| `tools/dual_host_source.py` and the fixed package's `evidence/dual-host/otpu_fpga_top_ld.sv` | Independent host clock, arbitration, explicit reset ownership and retained PCIe/JTAG interfaces | This is a different DDR shell, with a 128-bit host path. It is not a drop-in connection for our 512-bit AXI master. |
| `tools/fedora_run_vivado_native_jtag.py` and `tools/fedora_benchmark_ch1_jtag_rpc.py` | Numeric loopback Vivado scan RPC pattern for the existing raw-byte USER2 transport | Our bridge separately verifies target/DNA/source tag and uses the previously verified DLC10 3 MHz setting. It contains no programming or fabric-reset command. No donor execution result is inherited. |

The imported mailbox still matches the fixed package byte-for-byte at SHA256
`46f4a1148419279262fd274726eba0ab1f35285b91bf58138bc1997e692aeec9`.
The fixed reset reference is
`517b7c49b2755aa2150b1dfaadca74a4af0efcb3117e6a5b9aad4839b1a53538`;
the fixed CDC Tcl is
`ad6d98db73104ded02c2bec864b2cd68d77ab787d05bd8276b98ddea9888e80c`.
The [local reference audit](../build/opentpu-reference-audit/1792969129918921835/report.json)
records selected file hashes separately from this project's simulation evidence.

The additional [native RPC reference audit](../build/opentpu-native-rpc-reference/report.json)
preserves both read-only source copies. Their SHA256 values are
`fdfe1256d10b759e0839f94723e6a857bb2cf78423cb01d44440615435f3bf12`
and `97b52efc7a52b076fc2e869e6114215e389daaca9f27b57110fb14fd10f8c450`,
respectively. The foreign scripts were read, not executed.

Do not inherit the fixed image's spare-lane DDR configuration: its package
README specifies CH0 lanes `[0,1,2,3,4,5,8,7]` without ECC, CH1 with ECC,
and an independent 250 MHz host DMA clock. Our existing
[MIG-shaped adapter](AXI_MEMORY.md) instead has 31-bit byte addresses,
512-bit data, four-bit IDs and a single transaction clock; the inspected MIG
configuration uses a 72-bit physical interface with ECC. Source review must
resolve the selected controller, address windows, width/ID conversion, all
transaction clocks, calibration/ECC signaling and joint reset before wiring
them together. Neither truncating the channel-select address bit nor tying
unrelated reset domains together establishes a valid integration.

OpenTPU's calibration status is not a complete memory-health recovery contract.
`rtl/boards/ypcb-00338/otpu_board.sv` synchronizes calibration status, and
`otpu_ctrl.sv` exposes it; the `n_err` flag in `otpu_mem_ch.sv` denotes a native
protocol violation, not an ECC syndrome. Its request/hold/drain reset pattern
and `boards/ypcb-00338/constraints/otpu_mem_ch.tcl` provide useful transaction
and CDC references. They do not establish what this project should do on
calibration loss or an uncorrectable ECC event with an outstanding write.

## ZYNQ-NVDLA integration reference, 2026-10-27

The requested `~/ZYNQ-NVDLA` review read its YPCB integration RTL, BD script,
JTAG runtime and dated board report. The
[read-only source audit](../build/zynq-nvdla-reference-review.json) records exact
file hashes independently of Git HEAD, since another session is actively
working in that checkout. No foreign script was executed or source modified,
and its reported hardware results were not reproduced here. Use
`ZYNQ_NVDLA_ROOT` when referring to another local checkout.

| Reference, relative to that checkout | Useful preparation pattern | Required boundary here |
|---|---|---|
| `boards/ypcb/vivado/system.tcl` | A separate core/host clock keeps JTAG and control alive without PCIe; clock converters isolate the XDMA side, and address windows decode before narrowing | Audit every reset/CDC/ownership branch for our clocks and masters. Its board reset and CDC/methodology dispositions do not transfer. |
| `boards/ypcb/rtl/nvdla_mem64.sv` and `nvdla_ypcb_top.sv` | Explicit aperture/alignment/burst rejection, held native requests, masked writes and completion accounting | This is 64-bit AXI to a 512-bit OpenTPU/LiteDRAM native CH1 path. Our 512-bit AXI/MIG ordering and write-retirement proof are different; its `n_wdone` cannot replace them. |
| `tools/ypcb/jtag.tcl` and `boards/ypcb/JTAG_RESULT_20261026.md` | Reserved scratch ranges, upload readback, output/sentinel comparisons and bank-aware repeated jobs | Its `0x80000000..0xffffffff` aperture is outside our current 31-bit host contract. Do not copy those physical addresses or run its destructive scratch commands against this image. |

That accelerator is `nv_small` INT8, initially 64 MACs, with separate larger
variants. Its arithmetic, APB register plans and numerical results do not
qualify this project's FP16/raw-RK path or full 512-product performance target.
The useful next work is our live compiler-to-USER2 test, followed by closing
the existing joined DDR numerical timeout and preparing separately audited
memory/PCIe integration. Retain the source-level contracts and explicit faults;
no CPU arithmetic/layout repair or timing/electrical exception is inherited.

## Vortex floating-point paths

`/home/fedora/vortex` finished its user-started clone during this continuation.
Inspected revision: `5ce5a1a915b06c42c60393a7ea24168e0e01078f`.

The strongest FP16 candidates are under **`hw/rtl/tcu`**, not the selected scalar
FPU configuration:

- `tfr/VX_tcu_tfr_mul_f16.sv` extracts FP16 sign/exponent/mantissa and implements
  an 11-by-11 mantissa product, optionally using DSP48 inference via `USE_DSP`.
  SHA256: `41c58778019b44355e533a19c7283326f74b74fef2f70bdecce386057b1d82ea`.
- `tfr/VX_tcu_fedp_tfr.sv` supplies multiply, exponent alignment, accumulation
  and normalization stages, with explicit pipeline enables and lane metadata.
  Its accumulator-width assertion permits only 27..32 bits; this is not the
  NVIDIA CACC 48-bit format. SHA256:
  `62dbf8bb7b41cad3f67723fdc65778579f40ebf801b4e4910f37a7de2a4ac908`.
  The configured pipeline is explicitly restricted to four or five stages and
  advances under a shared `enable`; it is not a ready/valid elastic leaf. Any
  reuse needs to preserve stall-aligned operands, classification and reduction
  metadata rather than only delaying the output data.
- `tfr/VX_tcu_tfr_norm_round.sv` contains RNE logic and outputs FP32. Its
  `exp_underflow` branch selects zero, not a general gradual-underflow result.
  That is a compatibility question, not a reason to change this project's
  candidate FP16 policy without silicon evidence.
- `fpnew/VX_tcu_fpnew_mulfp32.sv` wraps `fpnew_fma_multi` with FP16 source,
  FP32 destination and RNE. The enclosing `VX_tcu_fedp_fpnew.sv` reduces via a
  tree of FP32 adders then adds C. That rounding/reduction order cannot simply
  replace RK CMAC/CACC. Wrapper SHA256:
  `2e52b11376528f80ceecf099540fa88352f48c76800d78debbf9340a80f46d2d`.

`hw/rtl/fpu/VX_fpu_fpnew.sv` enables FP32, or FP32+FP64 in its 64-bit
configuration, not FP16 in its present format mask. `VX_fma_unit_rtl.sv` is
parameterized but advertises F32/F64; parameterization alone is not FP16 proof.
The `third_party/cvfpu` and `third_party/hardfloat` directories were empty at
inspection. No Vortex configure, build, simulation or FPGA test was run. Any
future Vortex test must use its documented generated out-of-tree build flow.
Keep Apache-2.0 notices and audit transitive licenses before importing leaves.

## Other useful inputs

| Location | Useful material | Compatibility boundary |
|---|---|---|
| `/home/fedora/hw`, `8e06b1b9d85aab65b40d43d08eec5ea4681ff715` | NVIDIA nvdlav1 FP16 CMAC, CACC fp48 and C models | Strong arithmetic reference; not proven RK equivalence |
| `/home/fedora/soDLA`, `66d9b2683aea6fe787fbde5b8ca19abb825d1247` | Chisel control/storage and generated RTL | Selected CMAC is signed integer, not FP16 |
| `/home/fedora/ypcb/ref/LC480T/YPCB-00338-1P1` | XDMA, MEMTest, platform Vivado project ZIPs | Board-reference candidates; audit pins/clock/reset/electrical and generated IP first |
| `/home/fedora/ypcb/ref/ypcb_00338_1p1_hack/examples/YPCB_00338_1P1_systest` | Unpacked XDMA and MIG IP/constraints | XDMA metadata requests X8, 5.0 GT/s and 128-bit AXI-MM; not a verified active link |
| `/home/fedora/nvdla/examples/vp` | Capture parsers, register logs, buffer dumps, output.dimg | NVDLA VP, not RK silicon; do not pair a stale output with another run |
| `/home/fedora/hw/verif/traces/traceplayer` | Transactions plus input/weight/expected output files | Official NVDLA test vectors, primarily inspected INT16 cases |
| `/home/fedora/tinynvdla` | CBUF ownership/CSC sequencing, trace adapters and educational RTL | INT8 convolution and separate software FP16 SDP, not FP16 GEMM RTL |
| `/home/fedora/tinygrad_nvdla` | Direct-register native SDP ADD/MUL reference | CPU SUB negation and dtype conversion paths cannot enter this FPGA runtime |
| `/home/fedora/verigpu/src/float` | Pipelined floating add/multiply and tests | Selected parameters are FP32; source/test presence is not RK validation |

`/home/fedora/nvdla/ref/test_result.md` explicitly reports historical false
positives (CRC failures despite exit zero), address-offset errors and unverified
outputs. Reuse its raw inputs and infrastructure only with fresh, independent
result checks. No matched raw-command/input/output **RK3588 silicon** replay
bundle was identified in the inspected directories. A subsequent Git-history
audit found deleted raw GEM dumps in `/home/fedora/npu` at `2cd0173`, including
input and output bytes matching a printed RKNN convolution run. Their task,
command and log address bindings conflict, so they are not yet a matched
replay bundle. See [HISTORICAL_CAPTURES.md](HISTORICAL_CAPTURES.md).

The current working Rockchip encoder remains `/home/fedora/tinygrad` at
`078eee94d8f1912bb63ce786c250d2c24984844a`; these donors do not replace it.
See [EW_INITIALIZATION.md](EW_INITIALIZATION.md) for this increment's actual
implementation and captured final command boundary.

## NVIDIA arithmetic seam: preserve the distinction

Follow-up read-only inspection of the same `~/hw` commit locates the FP16
calculation in `cmod/cmac/NV_NVDLA_cmac.h`, not just the transport `.cpp`.
Its `cal_fp16_exp`, `cal_fp16_mul` and `calculation_fp16` routines choose a
group maximum from exponent portions, align signed products to that scale,
and reduce the group. The shown implementation uses 64 parallel channels and
emits a six-bit exponent plus 38-bit signed significand. This is not an IEEE
FP32 sum or an independently rounded FP16 product stream.

`cmod/cacc/NV_NVDLA_cacc.cpp::cacc_fp16_add` explicitly extracts those 44 bits.
The default header selects an eight-bit exponent and 40-bit significand (48
bits total); `NVDLA_GENERIC_CACC_USE_39_BIT_FP_ADDER` selects a different 39-bit
configuration. `cacc_fp48_to_fp32` is a separate conversion seam. A module name
containing FP16 or FP48 alone is not a complete numerical contract.

The CMAC header also has channel-priority NaN payload handling. Its debug
comparison explicitly substitutes signed 65536 for infinity encodings, while
the multiplier preparation uses a hidden one for nonzero encoded exponents.
These are reasons to audit the actual exception/alignment paths, not assume
IEEE multiplication semantics from the format name or use this donor as an RK
oracle. No NVIDIA C-model execution or RK equivalence was established here.
In particular, the user's RK IC32 packing does not prove a 64-channel numerical
reduction group identical to this donor.

The donor RTL `vmod/nvdla/cacc/NV_NVDLA_CACC_CALC_fp_48b.v` further shows that
the final FP32 conversion rounds the absolute mantissa by adding its guard
bit (`fp32_mant_cut[14]`), without an even-LSB tie test. This source expression
implies nearest/ties-away behavior at that seam, not the Vortex RNE rule.
Its partial-sum rounding separately uses
`mant_sum_guard & (~mant_sum_sign | mant_sum_stick)` on a signed mantissa.
The module exposes input/output valid signals but no ready/backpressure port;
an elastic integration would need bounded buffering or controlled issue.
These are source observations only: this CACC RTL has not been simulated in
this audit, and neither its rounding nor its reduction group is an RK oracle.

Inspected SHA256 pins:

- `cmod/cmac/NV_NVDLA_cmac.h`: `c188324560888dacd858c396dba3155cf7e9124dda8405984db8cc1018baa58a`
- `cmod/cacc/NV_NVDLA_cacc.cpp`: `e2142ba2076b40628cf900832136153007e71d256973cc7c449cbff459512a52`
- `cmod/cacc/NV_NVDLA_cacc.h`: `673cb3dab7d7904b1d10501c9ad564d04e2da7acf7fa63b9913a2a65dbfb50a1`
- `vmod/nvdla/cacc/NV_NVDLA_CACC_CALC_fp_48b.v`: `ef3dbfb8b56f4359f6554af9e3c07e3b47b87423b255c17aaedeeb0dc94b7028`

## Output conversion: a donor name is not an IEEE/RK contract

A subsequent [direct conversion audit](NVDLA_CONVERSION_AUDIT.md) compiled the
unmodified NVIDIA `HLS_fp32_to_fp16.v` with Icarus. Forty directed observations
confirmed the inspected C++ source's finite saturation and low-bit NaN payload
truncation, including `7f800000 -> 7bff` and `7fc00000 -> 7c00`. Sixteen cases
differ from the project's infinity/canonical-NaN reference. No RK output was
captured and no NVIDIA RTL was integrated. This rules out treating that donor
as an interchangeable IEEE converter without an explicit policy decision and
hardware differential evidence.
