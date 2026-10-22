# Current-backend FP16 EW initialization

This increment implements the explicit bypass/unity initialization writes used
by the user's current tinygrad backend. It is not PC DMA, a complete backend
port, general BS/BN/conversion support, or evidence of RK numerical equivalence.

## Source evidence

Local source pins inspected on 2026-09-21:

- `/home/fedora/tinygrad`, branch `rockchip-2608-1500`, commit
  `078eee94d8f1912bb63ce786c250d2c24984844a`.
  `tinygrad/renderer/rockchip.py:_stage_template` and `emit_ew_stage` emit
  the body. Renderer SHA256:
  `c84b70e73449a721319981334b746f79aadd095bd39cc2f576c84bd397fbcc1d`.
- Its `tinygrad/runtime/ops_rockchip.py:_run_ew_ops` promotes the first HALF
  operation to BOUNDED initialization; `_submit_bodies` writes the final PC
  tail and task descriptors. Runtime SHA256:
  `73cddbdebaf52c33a9d3cef33bbc016b78357da35a588403c23e35069e223daa`.
- `/home/fedora/npu`, commit `e02707ca9b010372f1c506c7f3a2fa2c9f2beb8e`,
  `include/rkt_registers.h` supplies the register addresses and bitfields.
  Header SHA256:
  `2159ea48c568b25c53075aca8fc3eb241d1f07384fe4aee4d2eadbfca54c202d`.
  The actual directory is `include`, not `includes`.

No implementation was copied from these repositories, and neither was edited.

## Restricted contract

The original 21 required configuration/tail fields and final enable remain
required. The following 13 extra DPU (`0x1001`) writes are either all absent or
all present in each task. A partially supplied group fails E3. Fixed values are
checked across all 32 bits, including fields inactive under bypass. Every
unsupported value fails E2 immediately and remains sticky until reset.

| Offset | Register | Accepted value and modeled restriction |
|---|---|---|
| `4040` | BS_CFG | `0x53`: BS, ALU, MUL and ReLU bypass |
| `4060` | BN_CFG | `0x53`: BN, ALU, MUL and ReLU bypass |
| `4044` | BS_ALU_CFG | `0`: exact initialized operand while bypassed |
| `4048` | BS_MUL_CFG | `0`: exact initialized operand while bypassed |
| `4050` | BS_OW_CFG | `2`: OD bypass; other controls zero |
| `4058` | WDMA_SIZE_0 | `7`: eight channels, other controls zero |
| `405c` | WDMA_SIZE_1 | Width `0..7999`; height and reserved bits zero |
| `4068` | BN_MUL_CFG | `0`: exact initialized operand while bypassed |
| `406c` | BN_RELUX_CMP_VALUE | `0`: exact initialized operand while bypassed |
| `4078` | EW_CVT_SCALE_VALUE | `1`: unity scale, zero shift/truncate |
| `4080` | OUT_CVT_OFFSET | `0`: no output offset |
| `4088` | OUT_CVT_SHIFT | `0`: exact initialized output-conversion controls |
| `40c0` | SURFACE_ADD | `0x40`: exact current single-surface profile only |

WDMA width must equal both DPU and RDMA width or the trigger fails E6. It does
not provide an independent logical count. Execution still reads/writes exactly
`8*(width+1)` binary16 elements, including padded lanes. The existing complete
FP16 format, ADD/SUB/MUL op, address, aliasing and timeout checks are unchanged.
The BS/BN paths are bypassed; no new arithmetic stage or CPU fixup is introduced.
The existing FP16 special-value policy remains candidate behavior.

Initialization presence cannot supply a missing field in a later task. A
complete initialized task followed by a lean legacy task is legal; a partially
initialized later task is not. Valid pre-trigger duplicates remain last-write-wins;
an invalid write cannot be repaired by another write.

## Production capture versus synthetic execution

Run with the pinned, clean local backend and its dependencies:

```sh
make rtl-test PYTHON=/usr/bin/python3
/usr/bin/python3 tools/capture_current_backend.py --rtl
```

The capture tool uses real tensor scheduling and production `to_program`, then
the unchanged `RockchipProgram.__call__`, encoder, task writer and ioctl wrapper.
It intercepts only allocation, synchronization and the final ioctl on host-owned
buffers. Device construction/file access is guarded. Runtime source/index
gathers, conversion operations, CMAC and unexpected resets are rejected before
submission. Compile-time constant scratch initialization is permitted.

Artifacts under `build/backend-current/{add,sub,mul}_{8,9,33}/` include full
command and task BOs, per-task raw QWORD bytes, initialized argument/scratch BOs,
the raw submission descriptor, and independent synthetic logical expected
outputs. The latter are **not hardware outputs**. Host object-pointer fields
are capture-process-specific; device addresses and raw descriptors are retained
without rewriting. The manifest records hashes and source revision.

Current ADD/MUL produce one 35-QWORD task. SUB produces a 35-QWORD MUL-by-minus-one
task and a 22-QWORD ADD task, with minus one supplied by constant initialization.
No CPU subtraction is used in this capture. The existing core now accepts the
31-word initialized body but rejects its first PC next-address write with E7.
`--rtl` verifies this rejection and zero memory transactions, not arithmetic
execution. Capture status `CAPTURED` is not compatibility status `PASS`.

The backend retains a nonzero next-address inside a zero guard page even for a
terminal task whose next amount is zero. Linked SUB additionally encodes a next
body amount of 18. **Do not zero the guard address, drop initialization writes,
or split/rewrite a chain to claim successful production replay.**

The 140-scenario regular RTL suite instead uses explicitly labeled synthetic
terminal fixtures with zero/zero tails. Its 63 additional cases exercise complete
initialization, numerical execution/tails/in-place outputs, every missing group
field, low/high-bit mutations, WDMA bounds, lifecycle and sticky errors. The old
77 scenarios and their expected errors are retained. Python additionally checks
every single-bit mutation of every new fixed field. Synthetic fixtures use
independent literal wire values, not the decoder whitelist as their oracle.

## Subsequent command-DMA increment

The separate `rk_ew_dma` top now implements bounded instruction-memory fetching,
follows encoded next addresses and adds the four tail words to the next-body
amount. It terminates on amount zero without a speculative guard read. The
legacy raw-port rejection described above is unchanged. See [PC_DMA.md](PC_DMA.md)
for the contract, portable unchanged captures and 62-case simulation suite, and
the source-bound verification index for actual results. PCIe/DDR, FP16 GEMM and
physical FPGA validation remain separate unfinished parts of the full goal.
