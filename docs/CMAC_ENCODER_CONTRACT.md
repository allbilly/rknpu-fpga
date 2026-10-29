# CMAC final encoder and framework layout boundary

The original audit below is historical. The selected raw full512 CMAC and
[TinyStories workload now pass physically](DDR_FULL512_FPGA_TEST.md).
Full compiled-tensor CMAC integration remains unsupported because its layouts
and standalone reset require additional hardware/runtime contracts.

## Precision and compute-group terminology

The selected FPGA FP16 configuration remains `ATOMIC_C=32`, `ATOMIC_K=16`:
32 input/reduction channels and sixteen output kernels, giving 512 parallel
product lanes. The [selected pipeline](../rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix_pipe.sv)
broadcasts one input vector to sixteen kernel instances. This is our concrete
parallel dot-product implementation, not evidence of RK3588's physical topology.
Kernel K in C32/K16 means GEMM output N; GEMM K instead names the reduction
dimension. Matrix shapes larger than the group are traversed in groups.

Rockchip's [official matmul header](https://raw.githubusercontent.com/airockchip/rknn-toolkit2/master/rknpu2/runtime/Linux/librknn_api/include/rknn_matmul_api.h),
checked 2026-10-29, documents RK3588/3576 native B blocks as
`(N/16, K/32, 16, 32)` for FP16 and `(N/32, K/32, 32, 32)` for INT8.
These establish precision-specific packing contracts; they do not by themselves
prove physical multiplier counts or a square systolic arrangement.

| Precision | Functional weight group | Current FPGA support |
|---|---|---|
| FP16 | C32/K16, 512 products | Selected implemented profile; source/image-specific qualification applies |
| INT8 | C32/K32, 1,024 products | Unsupported; separate arithmetic, accumulation, packing and command contracts required |
| INT4 / INT16 | Separate precision profiles | Unsupported |

Do not raise the FP16 kernel count to 32 to imitate INT8's block dimensions.
Supporting doubled INT8 arithmetic requires an actual integer datapath and its
numerical/shape tests; FP16 lanes do not provide that capability automatically.
NVDLA's [documented configurable INT8 MAC resources](https://nvdla.org/hw/v1/ias/unit_description.html)
are an architectural reference, not implemented capability or RK equivalence
for this project. MAC clock-gating/register modes beyond the modeled profile
remain explicit failures. Product count per accepted arithmetic frame must
also remain separate from measured sustained throughput through DMA and memory.

Offline audit on 2026-09-21 of clean `/home/fedora/tinygrad` revision
`078eee94d8f1912bb63ce786c250d2c24984844a`. The existing EW RTL still explicitly
rejects this profile. This document does not add GEMM support or establish RK
numerical equivalence.

`build/audit_cmac_encoder.py` compiles actual HALF tensor matmuls through
`to_program` and `RockchipRenderer`, extracts their compiled CMAC stages, and
passes each unchanged `emit_cmac_stage` result through the production
`RockchipProgram._submit_bodies(..., standalone=True, cmac=True)` final writer.
Allocation/sync/ioctl/reset are offline recording substitutes. Hardware opens
and `_apply_gathers` are forbidden. `RockchipProgram.__call__` is not invoked.
No operand BOs or numerical expectations are supplied; these are final-command
contract artifacts, **not full tensor replays or silicon captures**.

## Observed framing

| Field | Captured value |
|---|---|
| Register body | 45 QWORDs |
| Task `regcfg_amount` | 45: excludes the tail, unlike this project's EW descriptor |
| Task `enable_mask` | `0x0d`, not EW `0x18` |
| Final tail | `0001000000000000`, `0101000000000014`, `0041000000000000`, `00810000000d0008` |
| Body plus tail | 49 QWORDs, followed by an untouched zero alignment word |
| Lifecycle | Standalone submission; one recorded reset after it |

The first tail word has target `0x0001`, not the EW PC base-address write.
The current DMA parser must not treat these words as an EW chain or silently
ignore CNA/CORE registers. A future profile needs its own explicit framing,
complete field validation, memory contract and failure tests.

## Shapes and packing boundaries

Seven compiler cases were audited: logical `(M,N,K)` of `(1,8,7/8/9)` and
`(2,17,31/32/33/65)`. Every case produced two input gathers, one CMAC and one
output gather. The compiler chooses stage `(8,1,K)` for the one-row logical
cases; it retains `(2,17,K)` for the others. An initial audit assumption that
logical and encoded orientation always match failed; the corrected audit
preserves and explicitly checks the pinned compiler's orientation choice.

For the encoded stage, the source defines:

- `ak = max(32, round_up(K,32))`, `ao = max(32, round_up(N,32))`;
  `ai = max(ak,ao)`.
- Input tile `(M,ai)`, padded input channels.
- Weight tile `(ao/16, ai/32, 16, 32)` in increasing physical address order.
- Scratch sizes `M*ai*2`, `ao*ai*2`, `M*ao*4` bytes.
- FP16 output's logical `(m,n)` lane is read at halfword offset
  `m*ao*2 + n + floor(n/16)*16`. Do not assume dense FP16 output.

These are facts about the pinned backend, not an independently validated RK
packing/numerical specification. `sim/csc_sim.py` in `~/rk3588` supplies a
separate OC16/IC32 traversal reference for future cross-checks.

The fresh 2026-10-29 compiler-only capture extends this with six shapes. Root
[independently checks every one of the 16,897 gather indices](../build/backend-cmac-layout-capture-v1/root-layout-contract.json)
against dense input coordinates, blocked OC16/IC32 weights and output atom
placement. All runtime gather, device/program execution and submission guards
remain at zero; no numerical or hardware execution is claimed by this capture.

| Logical M,N,K | Encoded M,N,K | Scratch bytes: input, weight, output | Zero-fill lanes: input, weight |
|---|---|---|---|
| 1,16,32 | 16,1,32 | 1,024 / 2,048 / 2,048 | 0 / 992 |
| 1,32,32 | 32,1,32 | 2,048 / 2,048 / 4,096 | 0 / 992 |
| 2,16,32 | 2,16,32 | 128 / 2,048 / 256 | 0 / 512 |
| 1,16,65 | 16,1,65 | 3,072 / 6,144 / 2,048 | 496 / 3,007 |
| 2,32,65 | 2,32,65 | 384 / 6,144 / 256 | 62 / 992 |
| 1,33,33 | 33,1,33 | 4,224 / 4,096 / 4,224 | 1,023 / 2,015 |

These captures use raw halfword movement, zero fill, no runtime index buffer,
no partial updates and unit destination stride. Other gather modes remain
unsupported. Original logical operand BOs and raw CMAC words must remain
unchanged when a hardware movement path is introduced.

## Runtime compatibility work remains

The current backend executes `RKGather` through host raw-lane copies. The
FPGA path must not import that behavior as runtime CPU layout repair. Supporting
the full compiled tensor program requires an explicit hardware-side movement
path (and commands for it), or another evidenced end-to-end device layout
contract. Capturing an individual CMAC body does not solve those gathers.

The original `_submit_bodies(..., standalone=True, cmac=True)` also requests
`reset_npu()` after success, plus a reset before submission when the context
is not clean. The current FPGA adapter rejects runtime reset explicitly.
Implement a supported quiescent reset with a precise BO-retention/reload
contract; do not suppress that call or falsify the clean-context flag.

Likewise, Vortex FP16 products with FP32 reduction and NVIDIA FP48 CACC are
candidate arithmetic designs, not proof of RK accumulation width, alignment,
reduction order, intermediate rounding or exceptional-value behavior. Keep
those questions explicit before accepting numerical GEMM results.

The original framing report, raw final words, descriptor bytes and command BOs are under
`build/cmac_encoder_audit/`. Report status is
`COMMAND_CONTRACT_AUDITED_NOT_EXECUTED`; no hardware or RTL success is claimed.
