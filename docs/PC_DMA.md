# Raw PC command-memory execution

`rtl/rk_ew_dma.sv` adds a serial instruction-memory fetcher around the strict
EW decoder and engine. It does not replace the encoder, parse tensor operations,
or implement the RKNPU DRM ABI. The existing `rk_ew_core` raw-word port retains
its terminal-only, zero-next-fields contract and its existing error tests.

## Source evidence

The production writer is `/home/fedora/tinygrad/tinygrad/runtime/ops_rockchip.py`
at commit `078eee94d8f1912bb63ce786c250d2c24984844a`, SHA256
`73cddbdebaf52c33a9d3cef33bbc016b78357da35a588403c23e35069e223daa`.
Its `_submit_bodies` writes the body followed by exactly four tail QWORDs:

| Position | Target / offset | Value |
|---|---|---|
| -4 | PC_REG `0101 / 0010` | Next command byte address, aligned to 16 bytes |
| -3 | PC_REG `0101 / 0014` | Next body's QWORD count; zero terminates |
| -2 | VERSION `0041 / 0000` | Zero |
| -1 | PC `0081 / 0008` | DPU+RDMA enable `18` |

The first task descriptor's `regcfg_amount` includes its four tail words.
The encoded next amount excludes the next task's four tail words. Task storage
is rounded to an even QWORD count; padding is not a command. A terminal next
address can point into a nonzero, zero-filled guard page. The writer explains
this as protection from RK speculative accesses. This serial FPGA design
terminates on amount zero without issuing a guard command fetch; it does not model RK's
speculation or latency.

When connected through `rk_axi_mem`, an issued halfword read expands to its
enclosing 64-byte AXI beat. That can physically read neighboring padding/guard
bytes without interpreting them as commands. The complete beat must be mapped
ordinary RAM; see [AXI_MEMORY.md](AXI_MEMORY.md). The direct halfword-port
tests and AXI production-capture tests deliberately have distinct memory contracts.

## Start and memory interface

`start_valid && start_ready` accepts one job. `start_address[31:0]` is the first
descriptor's command byte address; `start_amount[31:0]` is its `regcfg_amount`.
The first amount must be 4..65539, the address must be 16-byte aligned, and the
exclusive command endpoint must not exceed 2^32. Each tail next amount is
0..65535; a nonterminal next address cannot be zero. Invalid address/count/chain
metadata fails E7. Missing required EW configuration still fails E3.

There is no task-descriptor DMA, interrupt controller, host address translation,
or implicit acceptance of descriptor flags. A future transport must supply these
two start fields under a separately reviewed submission contract. This wrapper
does not consume the DRM ioctl or claim its scheduling semantics.

The shared 16-bit request/response interface is described in [INTERFACE.md](INTERFACE.md).
Four little-endian halfword reads assemble each raw QWORD without changing any
bit. Only one memory request is outstanding. All command reads for the task
precede its data accesses. The next task is fetched only after the previous
task's final successful write acknowledgment. Its encoded address, not inferred
contiguity, selects the next command stream.

The last four positions must have exactly the tail keys above. Those keys in
the body, a misplaced trigger, or the wrong tail order fail E3. Other unknown
registers fail E1; existing value/shape/alignment checks are unchanged. This
finite task boundary can detect a missing trigger, unlike the unframed raw-word
port. Validation is streaming, not atomic across the job: previous task writes
remain visible if a later command is invalid. Future command memory is read
when reached, not snapshotted at submission. The memory owner must exclude
concurrent external modification during execution.

`busy` includes checking, fetching and execution. `task_done` pulses after one
task completes; `completed_tasks` counts tasks in the current job and clears at
the next accepted start. `done` pulses only on successful terminal completion.
Successful jobs can be submitted back-to-back without reset. A chain reaching
`MAX_TASKS` with a nonzero next amount fails E7 after committing the last allowed
task; it emits `task_done` but not job `done`. The parameter defaults to 4095 and
must be 1..4095. It bounds cycles in malformed linked lists, not elapsed time.

Fetch bus errors are E5 and request/response stalls reaching `TIMEOUT_CYCLES`
are E8. Data accesses retain the existing engine's error/timeout behavior.
Faults are sticky and refuse further jobs. Reset the wrapper and adapter
together; there is no rollback of partially written memory. Reset does not
initialize RAM or establish a coherent host/device memory protocol.

## Replay fixtures and evidence boundary

`tests/backend_ew_captures.json` stores nine production ADD/SUB/MUL captures at
logical lengths 8, 9 and 33. Its compressed BOs are verbatim lossless copies of
the prior production compiler/final-writer capture, with individual BO and task
SHA256 checks. These are not reconstructed command lists. Input data is
synthetic and the logical expected values are a software oracle, not silicon
goldens. The full BOs include padded elements, scratch, command and task buffers.

`tools/dma_fixtures.py` verifies integrity, replays command memory through
`model/dma.py`, checks independently saved logical outputs, and emits expected
contents of every mapped halfword. All physical padded elements execute.
SUB follows the captured B-times-minus-one task then ADD task, with no CPU
arithmetic repair. The software model is only a verification target.

`tests/tb_dma.sv` uses randomized backpressure/response delays (seed `35881234`),
timeout 128 and task limit 4. The suite contains nine production cases and 53
synthetic cases: noncontiguous chains, terminal unmapped guards, framing and
address failures, sticky faults, partial/final writes, fetch/data timeouts,
in-place output, task-limit cycles, back-to-back jobs and reset/restart. Reset
in-flight tests are RTL-only; the functional model has no cycle-level reset.
The harness compares all mapped memory, checks completion/transaction counts,
and saves observed halfwords separately under `build/{rtl,iverilog}/*_observed.hex`.

Run `make test PYTHON=/usr/bin/python3` for software, strict lint, Verilator and
Icarus. `make synth-check` additionally maps the standalone DMA top to XC7;
the board top now runs the unchanged SUB(9) trace through DMA and a bounded
BRAM aperture. See [DMA_BOARD_DEMO.md](DMA_BOARD_DEMO.md). Consult the fresh
source-bound reports for execution results. Neither
path is a physical FPGA test, timing closure, GEMM support, a full tinygrad
backend test, or an RK3588 differential comparison.
