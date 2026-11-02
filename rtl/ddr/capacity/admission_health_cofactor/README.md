# Capacity admission health cofactor candidate

This is the byte-identical owner leaf used by the current capacity-admission
full-source candidate: HDL order 154 and model project index 53. It is an
explicit alternative to `../rk_ddr_capacity_owner.sv`, not an additional module
to compile alongside it. Default source lists and Makefile targets are unchanged.
`source-candidate.json` pins both source versions and the selected full manifest.

Admission requires known-good health and no pending diagnostic request. In that
context, the health and accepted-request/invalid-seed fault branches are
redundant. This leaf preserves the public fault priority encoder and every
registered update, while retaining a combinational non-health predicate so
health joins at the last admission gate. It adds no state, cycle, command field,
arithmetic mode, host fixup or clock/timing exception.

Workspace receipts under `build/` separately record fresh source/native review,
126 matched-state binary RTL equivalence points, a reset-reachable faulty-mutant
counterexample, and 8,192 four-state equation cases. Paired native service tests
include Icarus X/Z controls; the binary proof does not establish arbitrary
forced-X RTL equivalence. Isolated Vivado mapping measures health paths from
four levels/2.492 ns to one level/1.117 ns with 66 FFs and 123 ports retained.
Full synthesis and both warm/controller model suites pass their source-bound
reviews. Its first route fails setup at −1.109 ns across 3,422 endpoints;
hold passes at +0.014 ns. These results do not qualify an FPGA image,
physical DDR/ECC/PCIe operation or RK silicon equivalence.

The preceding owner versions, native-harness failures and OOC report-table
failure remain preserved in their original workspace packages. No historical
log is included here as a new execution result.
