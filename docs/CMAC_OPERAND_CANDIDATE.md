# Staged raw-command operand path

**Current location:** these unchanged leaves are now under `rtl/` and feed
the [raw product path](CMAC_PRODUCT_PATH.md). The promoted operand bench is
included in the expanded `make test`, whose fresh run is in progress.
The results and `build/` paths below remain historical candidate evidence.

`build/rk_cmac_operand_front.sv` connects the staged raw CMAC profile decoder,
the existing address sequencer and a new `build/rk_cmac_reader.sv` leaf.
It is not connected to the production EW DMA/host endpoint or FPGA board top.

The public input is still unchanged final RK command words. The output is a
backpressured stream of raw input/weight halfwords with row, output-channel,
input-channel, destination-address and reduction-boundary tags. No tensor
operations, CPU arithmetic or runtime CPU layout repair enter this path.

## Reader and ownership contract

The reader snapshots one address/tag pair, reads the input halfword, waits for
its response, reads the weight halfword, waits for its response, then emits one
complete tagged operand pair. It accepts no further address pair until that
output is consumed. All requests and output data/tags remain stable during
backpressure. The memory interface is read-only, byte-addressed, and allows one
outstanding request, with a response no earlier than the following cycle.

A bus error prevents the incomplete operand pair from being emitted and latches
E5. A stalled request or response latches E8 on the configured timeout cycle.
The default limit is 65536 cycles; tests use 32. Waiting for the operand consumer
is not a memory timeout. Illegal internal state latches E6 and an odd address
at the internal reader boundary latches E4. Unknown response error status is
rejected in four-state simulation; this is not electrical fault detection.

Reset cancels partial reads, pending output, collected register fields and
sticky faults. The memory adapter must be reset together with this path so a
late old response cannot be mistaken for a new request. No transaction rollback
or independent memory-adapter reset is promised.

There are two deliberately different events:

- `address_done`: the final address pair entered the reader; its reads are still pending.
- `stream_done`: the final complete operand pair was accepted downstream.

Neither is job completion. There are **no output writes** here. A future enclosing
MAC/CACC/output engine must hold `downstream_busy` through its final output-write
acknowledgment. That interlock blocks the next command list even after
`stream_done`. It does not stop the current operand stream from draining.

This serial reader does not implement CBUF storage, CSC's silicon timing,
arithmetic reduction order, caching or bandwidth optimization. It retains the
profile's physical packing and capacity admission checks. Logical runtime
input/output gathers remain separate unfinished hardware work.

## Test scope

Seven unchanged compiler/final-writer command streams are replayed against
synthetic raw-lane input and weight buffers. An independently nested weight
packer and direct-index scoreboard supply expected addresses and data for
38,912 operand pairs across those seven cases. Buffers are opaque 16-bit labels,
not numerical reference results or RK3588 output captures.

The bench also specifies first/second/final read errors, request and response
timeouts on both operands, reset in each of five reader phases followed by full
restart, invalid raw commands, stale-profile rejection and downstream ownership.
Final-output stalls last forty cycles, beyond the memory timeout, to ensure the
two kinds of backpressure are not conflated. Icarus adds unknown-error-status
tests on both reads. Address issuance must precede operand completion, not act
as an early completion signal.

Current commands/results are under `build/cmac_operand_candidate/report.json`.
The corrected two-simulator run passes: Verilator 5.048 and Icarus 13.0 each
check 53,297 operand pairs across thirteen successful streams/restarts, seven
fault cases and five reset phases. Icarus additionally passes two unknown-error
cases (nine faults total). Corrected lint, compilation and simulation commands
have zero warnings. The run takes 26.396 seconds in Verilator and 315.584 seconds
in Icarus; the source, stimuli, seed and executable hashes are retained.
The [candidate archive](../verification/runs/2026-09-21-cmac-operand-candidate/index.json)
contains this evidence and the separate mapping check.

The first attempt stopped on
an Icarus warning about a testbench assertion in an `always_ff` process. A
separate run of that attempt's compiled Verilator binary passed 53,297 operand
pairs. The behavioral RAM now uses an ordinary clocked `always` process; all
assertions and stimulus are unchanged. The initial warning, sources and native
diagnostic are retained in `build/cmac_operand_initial_bench_warning.tar.gz`.

## XC7 mapping, not physical implementation

Yosys 0.65 successfully maps the unchanged staged DUT with its default timeout
65536: 1,464 FDCE, 1,986 LUT2..LUT6, three DSP48E1, 223 CARRY4, 246 MUXF7 and
87 MUXF8 cells. The DSPs implement shape/range products, **not numerical MACs**.
No CBUF BRAM is inferred because this design does not contain a CBUF.
These are primitive counts, not placed utilization or an Fmax measurement.

`build/cmac_operand_mapping/report.json` records exact versions, commands,
source hashes and exported netlist/JSON. It retains two warnings: the profile's
register array is replaced with individual registers, and ABC identifies a
combinational network. Neither is a physical DRC waiver. `check -assert` passes,
and no internal unmapped cell remains except scope metadata. The mapped netlist
has not been simulated or routed. The production source snapshot is unchanged;
its separate EW endpoint now passes all twenty functional mapped tests. That
result does not validate the operand candidate's mapped netlist.
