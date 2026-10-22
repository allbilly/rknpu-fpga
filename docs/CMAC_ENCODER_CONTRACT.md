# Current CMAC encoder boundary: audited, not implemented

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

## Runtime compatibility work remains

The current backend executes `RKGather` through host raw-lane copies. The
FPGA path must not import that behavior as runtime CPU layout repair. Supporting
the full compiled tensor program requires an explicit hardware-side movement
path (and commands for it), or another evidenced end-to-end device layout
contract. Capturing an individual CMAC body does not solve those gathers.

Likewise, Vortex FP16 products with FP32 reduction and NVIDIA FP48 CACC are
candidate arithmetic designs, not proof of RK accumulation width, alignment,
reduction order, intermediate rounding or exceptional-value behavior. Keep
those questions explicit before accepting numerical GEMM results.

The report, raw final words, descriptor bytes and command BOs are under
`build/cmac_encoder_audit/`. Report status is
`COMMAND_CONTRACT_AUDITED_NOT_EXECUTED`; no hardware or RTL success is claimed.
