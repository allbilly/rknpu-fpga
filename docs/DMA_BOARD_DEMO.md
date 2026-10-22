# Captured-command DMA board self-test

`ypcb_top` now instantiates `rk_ew_dma_demo`. Its ROM comes from the saved
production `capture_sub_9` fixture, not a substitute operation encoder. The
first 35-QWORD task multiplies B by a preinitialized minus-one constant; the
second 22-QWORD task adds A to that scratch result. Logical length nine occupies
sixteen FP16 lanes. Both command sequences, including their addresses, padding,
initialization group and nonzero guard pointer, are unchanged.

The backend pin remains `078eee94d8f1912bb63ce786c250d2c24984844a`.
The command hashes are:

- First task: `5befec46dab05a67b92e1bf13ae1e3e76f7762d76d776dac98f8f4c200e8d7e1`.
- Second task: `e8262d7f6c7a6a8ba61b068b66e8605f94e5ea066f5009cf24baf6fcc706ff93`.

`tools/gen_demo.py` uses `tools/dma_demo_fixture.py` to generate
`rtl/rk_dma_demo_rom.sv` and `tests/dma_demo_fixture.json`. The loader verifies
the full original BO hashes before selecting the prefixes needed by this trace.
The legacy ROM and its three-operation fixture remain unchanged and tested.
Software-generated expected values are test oracles, not RK silicon goldens.

## Explicit trace-only memory aperture

The six windows below are backed by one 4 KiB `rk_bram` through
`rk_demo_memory`. Both accelerator and initialization/readback ports use the
same checked translation. This is address translation, not tensor repacking:
no command, input, scratch or output byte is transformed.

| Original device byte range (end exclusive) | BRAM offset | Meaning |
|---|---:|---|
| `10001000..10001020` | `000` | A, sixteen FP16 elements |
| `10020000..10020020` | `020` | B, sixteen FP16 elements |
| `10040000..10040020` | `040` | Destination, including seven padded elements |
| `10060000..10060020` | `060` | Captured compile-time constant |
| `10061000..10061020` | `080` | Intermediate scratch output |
| `100e0000..100e0200` | `100` | Raw command image, alignment pad and guard prefix |

All other addresses, including odd addresses, fail through the RAM bus-error
response. The unused physical BRAM space is not exposed through aliases. The
full captured 4 KiB/8 KiB/64 KiB allocations are **not** all mapped by this demo;
it advertises only these 672 bytes. Task-descriptor DMA is not implemented, so
the task BO is not mapped. The first descriptor's address/count are fixed ROM
outputs for this autonomous test. This aperture is not a general allocator,
DDR controller, PCIe transport, reduced CBUF, or replacement runtime ABI.

## Sequencing and failure contract

After reset, the controller writes all 336 mapped halfwords through the RAM's
host port and waits for every acknowledgment. It then starts the DMA job and
does not use the host port while DMA is busy. The job must complete two tasks.
Only then does the controller read and compare every mapped halfword, including
unchanged inputs, constants, command words and padding as well as both output
buffers. `pass` is latched only after all 336 comparisons succeed.

The expected accelerator traffic is 228 command halfword reads plus 96 data
transactions, including 32 writes. A zero next amount terminates without a
speculative guard read. The software model is used only to build/check the
fixture; no CPU arithmetic or layout fixup participates in hardware execution.

DMA faults retain codes 1..8. Demo-local E1 is any readback mismatch, E2 a
host-port RAM fault, E3 the existing one-million-cycle watchdog, E4 an invalid
completion count/busy indication, and EF an invalid controller state. Failure
is sticky. Reset clears the controller, DMA and RAM responses together; the
next initialization overwrites all mapped words rather than relying on stale
RAM contents. Four-state comparisons reject unknown readback data.

Clock, pins, reset synchronizer, LED polarity option, watchdog limit, FPGA
electrical requirements and timing/DRC gates are unchanged. No new external
ports or programming operations are introduced.

## Verification scope

`tb_dma_demo` checks the fixed traffic/completion/readback counts, interrupted
command fetch and data execution, initialization and command bus errors,
completion-count mismatch, known/unknown readback corruption, watchdog failure
and recovery. `tb_demo_memory` independently tests both ends of every window,
gaps, odd/unmapped addresses, cross-window nonaliasing, response backpressure,
adjacent requests and reset cancellation. The existing board-port test checks
startup, asynchronous reset, synchronized release and both LED polarities.

`make test` runs the entire prior suite plus these two benches. `make synth-check`
now maps this DMA-based board top and tests its resulting Xilinx primitive
netlist through board ports only. The larger ROM initialization/readback
workload has a larger host simulator wall-clock allowance; the unchanged HDL
board timeout and physical timing gates are not relaxed. Consult the fresh
source-bound verification index for actual results, not old demo logs.

This is still an autonomous FP16 EW test. A simulated or even physical LED pass
would not establish full tinygrad coverage, GEMM, RK special-value equivalence,
DDR/PCIe operation, or timing closure. No board or flash was programmed.
