# CMAC address-sequencer candidate (not connected)

The original SystemVerilog address-only leaf is now checked in as
`rtl/rk_cmac_address.sv`, with `tests/tb_cmac_address.sv`. Its bytes are identical
to the staged candidate that passed both simulators. It is included in normal
lint and both RTL suites, but remains **unconnected** to the EW decoder, DMA,
host endpoint and board top. Fresh combined-revision native verification passes
at source `f927a501cec9`: 247 entries in each simulator, zero warnings, with
82 matching cross-simulator memory images. All twenty full mapped-endpoint
checks also pass separately; that endpoint does not contain this CMAC leaf.
There is no new executable tensor/configuration interface on the FPGA. The
public execution boundary remains unchanged raw RK command words.

## Internal contract

A future complete raw CMAC profile decoder must provide physical rows `M`,
input channels `ai`, output channels `ao`, and three device byte addresses.
Logical K/N are not substitutes for physical padded dimensions. The leaf emits
address triples and row/channel/reduction tags, held under backpressure:

```
A = input_base  + 2 * (row*ai + ic)
W = weight_base + 2 * ((oc/16)*(ai/32)*16*32
                      + (ic/32)*16*32 + (oc%16)*32 + ic%32)
D = output_base + 2 * (row*ao*2 + oc + (oc/16)*16)
```

Only FP16-output layout is described. Counter updates implement those formulas
without per-product variable multiplication. IC32 panel boundaries advance the
weight address by 962 bytes from the preceding lane; OC16 boundaries advance
the weight block by `ai*32` bytes and the output by 34 bytes. Row transitions
restore the original weight base and advance feature/output row bases.

`first_product`/`last_product` bracket one physical reduction; `last_output`
identifies the final physical output. `walk_done` means the final address token
was accepted, **not** that arithmetic, memory writes or a submitted job finished.
There are no memory requests, numerical operations, CBUF storage or completion
interrupts in this leaf.

Configuration is captured only while idle. A rejected configuration latches an
error until reset, with no token emitted. Busy-time configuration changes are
ignored because `config_ready` is low. Reset cancels a walk. Full physical BO
ranges, including output holes, must fit the 32-bit byte address space. Bases
must be 16-byte aligned. Read-only input/weight aliasing is allowed; output
overlap with either full input range is rejected. This leaf does not bypass the
production memory adapter's separate 31-bit restriction.

Shape checks follow the pinned encoder's admission bounds: rows 1..2047,
physical channel multiples of 32, `ai<=4096`, `ao<=16383`, `ai<=384` for
multiple rows, feature bytes <=10*32768 and weight bytes <=11*32768. These are
checks against a proposed profile, not a CBUF implementation or a claim that
each admitted shape matches hardware.

## Evidence and remaining work

`build/check_cmac_layout.py` checks eight physical layouts against the existing
`~/rk3588/sim/csc_sim.py` packer and CSC trace, using two raw 16-bit labels per
weight to avoid losing index uniqueness to floating-point rounding. It also
recompiles the seven audited tensor cases and checks 11,616 static input,
weight and output gather-lane mappings. Hardware access and runtime gathers
are forbidden. This is address/reference evidence, not numerical execution.

The expanded Verilator and Icarus test executions pass 375,895 accepted tokens
each, eleven complete walks, and 22 rejected configurations (24 in Icarus,
including unknown configuration inputs). Tests include the maximum single-row
input-channel count, the weight-capacity boundary, forced final-token stalls,
row/panel boundaries, output holes, exact-end-of-address-space mapping,
overlap/overflow failures, sticky errors and reset during a walk.

The first aggregate runner incorrectly expected 377,895 tokens and therefore
failed after both simulators passed. Its report and original driver are retained
under `build/cmac_address_candidate/`. The corrected driver derives the expected
count from all complete shapes plus three interrupted prefixes. Its fresh run
under `build/cmac_address_candidate_checked/` passes strict lint and both
simulators with zero warnings (Verilator 5.048, Icarus 13.0). The revised
aggregate records the candidate source hashes separately from the unchanged
production source manifest. HDL/error assertions were not changed to correct
the report counter.

That standalone evidence, including the earlier reporting failure, is retained
in [the supplement archive](../verification/runs/2026-09-21-060fe287ecda-supplement/index.json).
The normal runner gives this new benchmark a 600-second process allowance
because its measured Icarus execution took 201 seconds. Its 10 ms HDL timeout
and all existing tests' process/HDL timeouts remain unchanged.

No arithmetic ordering is established by traversing addresses. In particular,
serial K tokens must not be turned into a rounded FP16 or arbitrary FP32 serial
sum and called RK-compatible. The future product, group reduction, accumulation
and conversion pipeline still needs numerical contracts and differential tests.
The full raw-command decoder, CBUF/traversal integration, hardware-side runtime
layout handling, and physical execution also remain unfinished.
