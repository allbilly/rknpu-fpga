# Staged post-accumulation conversion/write tail

`build/rk_cmac_output.sv` joins the independently checked
[FP32-to-FP16 converter](FP32_TO_FP16_CANDIDATE.md) and
[halfword writer](CMAC_WRITER_CANDIDATE.md), without changing either leaf.
This is an internal datapath, not a tensor-operation API or a new raw-command
execution profile. It is not connected to the raw CMAC product frontend,
accumulator, EW endpoint, PCIe/MIG or board top. No accumulator is supplied by
this increment and no GEMM output is claimed.

## Numerical and metadata boundary

Input records contain an already accumulated FP32-encoded value, destination
byte address and final-output flag. The future accumulator must produce these
records in the required output order. Do not connect individual products to
this input: rounding each product to FP16 before accumulation would change
the numerical operation.

The converter's RNE/gradual-underflow/infinity/canonical-NaN contract remains
a candidate pending RK observations. Thirty-three tag bits carry address and
last through all three elastic stages; the writer snapshots the resulting
halfword and its metadata. The wrapper neither changes layout nor adds host
arithmetic. The writer retains its even-address and known-last checks,
including the legal last halfword at `0xfffffffe`.

## Ownership and completion

There are at most three buffered conversions and one outstanding writer
record. A two-bit counter covers all converter slots, not just output-valid.
`busy` starts at the first accepted input and spans gaps between subsequent
inputs, even when the pipeline and writer have drained temporarily. It ends
on the final successful write acknowledgment or a fault. This is not full raw
job ownership: the enclosing controller must also own the job before its
first accumulated result becomes available.

Accepting `in_last=1` closes the input stream. A producer may offer the next
stream immediately but must hold it while stalled; the tail will not accept
it until the previous final write acknowledgment has completed. There is a
one-cycle input reopening bubble following `done`. Streams can then repeat
without reset. An omitted final flag leaves ownership active, without an
input-gap timeout or fabricated completion.

`acknowledged` pulses only for successful memory responses; `done` additionally
requires the acknowledged record's last flag. Neither converter output nor
write-request acceptance completes the stream. The standard memory contract
requires a response no earlier than the cycle after request acceptance, one
response per write and a joint memory/consumer reset after cancellation.

## Faults, cancellation and reset

Writer E4/E5/E6/E8 faults immediately suppress further input, converted-result
and memory handshakes. Buffered results are cancelled, not drained as writes.
An upstream `cancel` assertion has the same effect and must span a clock edge
to latch. Codes 1..8 are preserved; zero, out-of-range and four-state unknown
codes become E6. An already visible writer fault takes priority over a newly
asserted cancellation. The first latched fault/code remains stable even if
the stalled inner writer later times out.

Cancellation suppresses acknowledgment and completion if it coincides with
an otherwise available final response. Reset dominates cancellation and
clears all ownership, buffering, fault state and completion signals. This
does not undo previously accepted writes. The bench deliberately commits RAM
at request acceptance to exercise this lack of rollback. Reset the entire
tail and the memory adapter together; late responses cannot be reused after
an isolated leaf reset.

Default memory timeout is 65536 cycles, while tests use exactly 32 stalled
request or response cycles. Gaps in accumulated-value delivery do not count
against that timeout. The zero timeout must remain an explicit failure.

## Verification target

`build/gen_cmac_output_vectors.py` verifies the seven portable compiler
command hashes and uses their physical output shape/packing for 1024 records.
It does not execute those commands. Inputs are synthetic FP32 stand-ins for
future accumulated values, including rounding boundaries, overflow, signed
zero, infinities and NaNs. Python `struct` conversion supplies the independent
halfword expectation. Every RAM location, including untouched packing holes,
is checked after writes, faults and resets.

The bench covers sixteen completed streams, including immediate repeated
streams without reset and an eighty-cycle gap after a nonfinal acknowledged
write. It tests first/middle/final response errors and both timeout phases,
invalid metadata, buffered fault cancellation, upstream cancellation with
one/two/three converter slots and a full four-record tail, cancellation after
partial writes, cancellation coincident with final response, and five joint
reset phases. Reset is also checked while upstream cancellation is asserted.
Four-state tests add unknown response status, address, last and cancel code.

The seed is `0x3588ca08`. Expected normal totals are 1821 requests and 1812
successful acknowledgments: 1538 completed-stream writes, 259 fault-prefix
writes, 15 reset-prefix writes and nine cancel-prefix writes. Icarus adds 65
requests and 63 acknowledgments in unknown-response tests. These are synthetic
protocol/conversion observations, not accumulated GEMM or RK captures.

The final-source Icarus 13.0 run passes sixteen completed streams, fifteen
faults, ten cancellations and five reset phases, with 1886 requests/1875
acknowledgments, 10,155 source-stall cycles and zero compile/run warnings.
The zero-timeout elaboration/time-zero test also rejects the invalid parameter
with the intended message and nonzero exit status.

Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) maps the default
65536-cycle-timeout wrapper to 274 FDCE, five FDPE, 304 LUT2..6, 27 CARRY4,
21 MUXF7 and two MUXF8 in 109.834 seconds. It uses no DSP or BRAM. One ABC
combinational-network warning and two scope-metadata cells are retained;
structural checks pass with no other unlowered internal cells. These counts
use 33-bit conversion tags, not the standalone converter's 97-bit default.

Verilator 5.048 also passes the final-source integration bench through
`build/run_cmac_output.py`: sixteen completed streams, eleven faults, nine
cancellations and five resets, with 1821 requests/1812 acknowledgments and
9812 source-stall cycles. Strict compilation took 398.010 seconds and the
simulation 0.531 seconds, with zero warnings. Both simulators now pass.

The [candidate archive](../verification/runs/2026-09-21-cmac-output-candidate/index.json)
retains exact sources, stimuli, executable/log hashes and mapped JSON/netlist.
The two leaf source hashes are checked against their earlier independent
archives; only the new wrapper and its tests are new logic. Production source
remains unchanged at `db97404570f5`, with the existing baseline regression
still running. No mapped simulation, physical timing or RK/FPGA test is
implied by these native/synthesis results.
