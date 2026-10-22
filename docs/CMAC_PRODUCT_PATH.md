# Raw command to exact-product path

`rtl/rk_cmac_product_front.sv` connects unchanged terminal RK CMAC words to
packed memory reads and tagged FP32-encoded products. This is an internal
increment toward GEMM, not a completed GEMM engine or a tensor-operation API.
The EW DMA/host endpoint and board top do not instantiate it.

The decoder, reader, operand front and product leaf have been promoted from
the reviewed candidates into `rtl/` without logic changes. Their earlier
archives retain the original staged paths. Fresh combined verification now
passes for the promoted sources and the new wrapper.

## Boundary and numerical contract

The input is the complete 49-QWORD terminal FP16/no-ReLU CMAC profile in
[CMAC_PROFILE_CANDIDATE.md](CMAC_PROFILE_CANDIDATE.md). All fixed fields,
redundant shapes, strides, capacities and address ranges remain checked.
Unsupported modes and incomplete triggers remain errors. There is no finite
DMA framing here; a missing trigger leaves partial configuration pending.

Reads follow the physical packing in
[CMAC_OPERAND_CANDIDATE.md](CMAC_OPERAND_CANDIDATE.md). They do not execute the
compiler's separate runtime gather operations. Test buffers are synthetic
physical BOs, not a host layout workaround in the hardware execution path.

Each finite half-precision pair produces its exact FP32-encoded product,
without rounding to FP16 first. The numerical proof and provisional special
values are in [FP16_PRODUCT_CANDIDATE.md](FP16_PRODUCT_CANDIDATE.md).
Products carry destination byte address, row, output channel, input channel,
first-product, last-product and last-output flags (131 tag bits).
There is no accumulation, output conversion or memory write. The format is
not the NVIDIA donor's 44-bit grouped CMAC result. No RK-compatible reduction
order or exceptional-value policy is established by this increment.

## Ownership, stalls, faults and reset

The three multiplier slots have independent valid/backpressure control. A
two-bit outstanding-product counter covers every slot, not just output-valid.
It blocks new commands during pipeline fill and drain, even when the reader
has finished. Full slots backpressure the operand reader, then the address
walker. Stalling a product consumer is not a memory timeout.

Three events remain distinct:

- `address_done`: final address pair entered the reader.
- `operand_done`: final operand pair entered the multiplier.
- `product_done`: final tagged product was accepted by its consumer.

None is task/job completion. A future accumulator/writer must hold
`downstream_busy` until the final acknowledged write. That signal holds command
ownership without preventing the current product stream from draining.

Memory faults and exact request/response timeouts retain their E5/E8 meanings.
On a sticky fault, the wrapper suppresses buffered product-valid and freezes
the multiplier handshakes until reset. A previously stalled product may be
cancelled by a fault; the consumer must honor the shared error indication.
Products accepted before the fault are not rolled back. Reset this entire path
and its memory adapter together; independent reset with a late old response
is not supported. Reset clears buffered values/tags, ownership and decoder state.

## Reproducible verification

`tests/backend_cmac_captures.json` retains seven unchanged command byte streams,
their SHA256 hashes, compiler/final-writer metadata and the pinned backend
revision. It does not contain RK output captures. `tools/gen_cmac_vectors.py`
validates the command hashes, packs synthetic weights with independent nested
loops and emits both address/lane expectations and Python binary64/struct
product references. No local tinygrad or donor checkout is needed to replay.

`make cmac-test` and `make cmac-four-state-test` run the promoted operand bench,
the exhaustive-encoding product sample bench and the new integration bench.
Both targets are dependencies of `make test`; missing tools are failures.
The new bench checks seven raw streams, repeat submission without reset,
request/response delays, full-buffer stalls and drain, downstream ownership,
read faults with buffered products, exact memory timeouts, reset of one/two/
three buffered products, unsupported commands and stale-profile rejection.
Icarus adds unknown read-error status while products are buffered. The seed
is `0x3588ca05`; test memory timeout is 32 cycles, default RTL is 65536.

Reports record source fingerprints, stimuli, versions, commands and logs under
`build/cmac_verilator` and `build/cmac_iverilog`. The initial lint warning about
testbench clock declaration initialization was corrected by using a separate
initial process; no lint suppression or arithmetic expectation changed.
The expanded regression passes at the source snapshot below. No mapped simulation, routed
timing, CBUF, PCIe/MIG integration or FPGA/RK hardware result is claimed.

The corrected integration-only Icarus run has now passed 53,247 product/tag
comparisons across thirteen successful streams, thirteen fault cases (including
two unknown-status cases), three reset/cancellation cases and an eighty-cycle
full-buffer stall. This is recorded separately in
`build/cmac_product_corrected_preflight_report.json`. The subsequently completed
`make -j4 test` also exits zero: 44 Python methods, 1,087,299 C++ reference
comparisons, strict lint, generated checks and both full native RTL suites.
Each simulator passes 247 original entries and all three extra benches:
230,433 leaf products, 53,297 operand pairs and 53,247 integrated products/tags.
All 82 saved EW memory images agree across simulators, including eleven
host/direct comparisons each. The 610 original stimuli remain byte-identical.
The [fresh archive](../verification/runs/2026-09-21-db97404570f5/index.json)
retains these results separately from the initial failed attempt.

The first integration preflight reached all 8,192 products and 16,384 reads
with one address/operand completion each and no DUT error, but failed its exact
forty-cycle final-stall assertion: random readiness inserted a forty-first
cycle. The corrected bench makes that final handshake deterministic after
forty stalls; the assertion is unchanged. Icarus separately found a time-zero
unknown-address callback in the behavioral RAM, corrected by capturing read
data on a request handshake. The DUT and expected products are unchanged.
Both findings and the deliberately stopped first regression are retained in
the [failure archive](../verification/runs/2026-09-21-product-path-preflight-failure/index.json).
The new source snapshot is `db97404570f55ffc3ca603816b3fc797953333ff4fac6e352f82a18970188765`.
Full regression passes at that snapshot. A fresh mapping run also
completed at that revision, with the results below; the earlier run remains
in the failure archive and is not relabeled as this new check.

## XC7 mapping

The fresh full-path mapping passes with default timeout 65536 at source
`db97404570f55ffc3ca603816b3fc797953333ff4fac6e352f82a18970188765`.
Yosys 0.65 maps the wrapper and all its leaves to four DSP48E1, 1,959 FDCE,
2,053 LUT1..6, 219 CARRY4, 286 MUXF7 and 80 MUXF8 cells in 251.325 seconds.
The earlier operand-only map used three DSPs for shape/range calculations;
the exact multiplier adds one numerical product DSP. No CBUF is implemented.

The report and exported JSON/netlist are under `build/cmac_product_mapping`.
The register-array replacement and ABC combinational-network warnings are
retained. Structural checks pass with no unlowered internal cells other than
scope metadata. This does not test the new mapped netlist, establish placed
utilization/Fmax, or validate the physical board.
