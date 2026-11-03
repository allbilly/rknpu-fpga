# Fault classifier cofactor candidate

This explicit, unselected replacement applies to source order 112 of the
201-record predecode/publication profile. The [manifest](source-candidate.json)
records its content identity and workspace-local proof/test receipts. Do not
compile it alongside another definition of the same module. Default build
selection is unchanged.

The timeout tag uses the existing raw-seal control-misuse predicate in its
priority mask. Pending-fault classification uses the existing cofactored
immediate-fault Boolean instead of reducing the original event vector again.
The original event vector, priority cause encoder, registered state, ports,
latency and public failure policy remain unchanged.

The caller must connect `job_abort` to `external_block`, qualified `job_seal`
to `dma_done && !external_block`, and `job_seal_intent` to `dma_done && 1`.
If abort is not known zero, its event masks the later priority terms. When
abort is known zero, qualified and raw seals agree, so the two control-misuse
predicates agree. The cofactor does not remove or delay fault detection.

Independently reviewed extracted proofs include binary SAT, 131,072 mixed
vectors (five four-state controls and seven binary event/tag inputs), and a
real abort-mask negative witness. Fresh paired tests compile the actual
baseline and candidate fabric with the selected memory adapter/snapshot/fence
sources: 21 Icarus and 19 Verilator cases. They compare 51 outputs and 44
logical state fields and check three candidate cofactor equations. Both actual
modules have 54 output ports; the inherited fixture's old baseline-port marker
is not the current census.

These are source and component results. Fresh complete-parent models,
synthesis/mapped checks, routed timing, image audit and hardware tests remain
required. Neither this package nor donor agreement establishes RK compatibility
or numerical special-value policy. The full FP16 C32/K16 compute group retains
512 product lanes and both original DDR controllers. Raw final command words
remain the execution boundary; unsupported fields still fail, with no runtime
CPU arithmetic or layout repair in the FPGA path.
