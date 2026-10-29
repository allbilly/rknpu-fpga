# Compiler layout DMA contract

The ordinary pinned tinygrad CMAC lowering needs two input gathers and one
output gather around its original 45-QWORD CMAC body. Its CPU `_apply_gathers`
implementation is not admitted on the FPGA path. This source increment adds
an explicit FPGA command encoder and a standalone hardware movement engine;
the existing production runtime continues rejecting these plans until parent,
reset and transport integration are qualified.

The compiler evidence comes from tinygrad revision
`078eee94d8f1912bb63ce786c250d2c24984844a`, renderer
`tinygrad/renderer/rockchip.py` (`RKGather` and `_lower_cmac_reduce`), and
runtime `tinygrad/runtime/ops_rockchip.py` (`_apply_gathers` and
`RockchipProgram.__call__`). The six captured logical M/N/K shapes are
1/16/32, 1/32/32, 2/16/32, 1/16/65, 2/32/65 and 1/33/33. The portable
[fixtures](../tests/backend_layout/fixtures.json) retain complete immutable
plans, capture hashes, dimensions and 16,897 independently calculated indices.
The M=1 compiler operand swap, OC16/IC32 weight traversal and CMAC output atoms
are preserved. This is compiler evidence, not actual RK numerical evidence.

## Execution boundary

The [encoder](../tools/backend/layout.py) consumes already compiled immutable
gather metadata plus owned buffer bindings. It creates a static index BO and
nine final little-endian QWORDs. It never reads source/destination contents or
performs tensor arithmetic. The [DMA](../rtl/layout/rk_layout_dma.sv) fetches
those exact words, reads indices and original source halfwords, and writes
destination halfwords. CMAC commands are unchanged. This is a private FPGA
extension, not an emulation of an RK3588 register block.

QWORD format remains `(target << 48) | (value << 16) | register`. Target is
`0xff01`, amount is exactly nine, and the command BO is 16-byte aligned.
Every command must appear exactly once in this order; no extra writes or PC
tail are accepted.

| Word | Register | Required value |
|---|---|---|
| 0 | `0x0000` | ABI `0x00010002` (version 1, two-byte lanes) |
| 1 | `0x0004` | Source byte address |
| 2 | `0x0008` | Destination byte address |
| 3 | `0x000c` | Static u32 index-table byte address |
| 4 | `0x0010` | Destination halfword count |
| 5 | `0x0014` | Source halfword count |
| 6 | `0x0018` | Zero fill bits |
| 7 | `0x001c` | Zero flags |
| 8 | `0x0020` | Start, exactly one |

Each table entry is a source halfword index, or `0xffffffff` to write positive
zero. The hardware copies all other halfwords bit for bit, including signed
zeros, subnormals, infinities and NaN payloads. There is no conversion or
floating-point operation in the layout engine. Entries other than the fill
sentinel must be below the encoded source count.

Source/destination addresses are two-byte aligned; the table is four-byte
aligned. All four live spans (source, destination, table and commands) must
be pairwise disjoint and within the configured aperture. Address/end checks
use widened arithmetic. Zero/oversized counts, address wrap and overlap fail
before any destination write. A bad later table entry can follow earlier
successful writes: faults poison the epoch, and partial output is unusable.

## Supported compiler metadata

Only two-byte lanes, contiguous destination stride one, zero fill,
`index=None`, no literal values and `partial=False` are supported. Static
offsets use valid source indices or exactly `-1` for zero padding. Affine
axes expand compiler metadata only; out-of-range affine indices are rejected
because the upstream general implementation can skip those writes. A scratch
destination must overwrite its complete logical slot from offset zero, so the
upstream whole-slot zero initialization is reproduced by actual hardware
writes. Other layouts remain explicit errors.

Compiler type/pin verification and allocation ownership remain runtime
responsibilities. `from_backend` validates original renderer types and fields;
it does not create a framework/device execution path by itself.

## Completion, faults and reset

The engine has one memory transaction outstanding. Each destination write
waits for its response; completion is held until `result_ready`. Successful
result acknowledgment releases the engine for reuse without altering memory.
Fault codes are: 1 command address/amount, 2 QWORD key/value, 3 spans/counts,
4 source index, 5 memory response error, 6 unknown read data in four-state
simulation, 7 protocol/internal fault, and 8 timeout.

A timeout retains any asserted request and its payload until accepted, and
late responses drain while the fault stays sticky. Fault acknowledgment does
not rearm the engine. Only joint reset may recover the failed epoch; parent
integration must prove downstream ownership is reset coherently.

This component does not implement the final writer's `reset_npu()` call.
That separate boundary must drain all clients, reset the intended compute
state and retain DDR BO contents before ordinary standalone CMAC is admitted.

## Validation

The [independent native review](../build/backend-layout-root-review-v1/report.json)
accepts 34 positive cases and 51 negative Icarus controls, and 34 positive
cases and 50 negative Verilator controls. The extra Icarus case rejects
unknown read data. Each positive case executes twice, comparing the entire
64-KiB aperture after each execution. Native reports bind actual tool versions,
all source inputs, generated fixtures, logs and the compiled simulator image.
Verilator 5.048 and Icarus Verilog 13.0 are the recorded simulators; seed is
`0x3588`. The [original-type check](../build/backend-layout-original-types-v1/report.json)
also encodes all 18 actual pinned compiler gathers and checks all 16,897
indices; it executes no tensor arithmetic, gathers or FPGA commands.
The later complete V21 `make test` also passes with these layout suites in
the default recipe; [independent review](../build/production-model-auditors/current-v21/root-review.json)
binds all 1,133 original/copied source files and both fresh simulator images.

`make backend-layout-test` runs portable encoder controls and native raw-QWORD
execution in Icarus and Verilator. The test memory adds randomized request and
response stalls using seed `0x3588`. Positive cases compare the complete
64-KiB aperture, preserve completion until ACK, and run twice without reset.
Sixteen additional cases transport every one of the 65,536 raw halfwords.
Negative controls cover malformed command keys/constants, alignment, counts,
wrap, all six overlap pairs, bad indices, memory errors, unsolicited responses,
timeouts, late drainage and four-state unknown read data.

These tests qualify the standalone source component only. They do not prove
parent arbitration, ordinary framework matmul, quiescent reset, synthesis,
timing, bitfile generation, physical FPGA execution or RK equivalence.
