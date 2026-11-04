# Parent pending-cause invariant candidate

This explicit replacement for source order 148 is byte-identical to the parent
used by the current source-bound diagnostics. The [manifest](source-candidate.json)
records its hash and required order-112 [classifier fabric](../fault_classifier_cofactor/README.md).
The remaining 200 selected records are unchanged. Default selectors are unchanged;
do not compile this parent alongside another definition of the same module.

The parent already reserves a pending monitor cause through `monitor_early_fault`.
Two common-reset invariants make the child `fabric_cause_pending` alternative
redundant in that same branch: active fabric service implies the parent's sticky
`monitor_seen`, and a latched fabric fault with zero saved cause implies its
pending monitor gap. The actual caller must preserve the documented raw/qualified
seal relation and shared monitor-health wiring. The replacement retains monitor
reservation, first-fault priority, error codes, all other causes, state, ports and
latency. Its `ASSERT_ON` witness checks the original branch equivalence.

Independent review binds actual-fabric binary reset/induction proofs, conditioned
extracted composition, 2,097,152 selected mixed-state vectors and real negative
counterexamples. This is not whole-parent equivalence or four-state reachability.
Fresh full-parent warm simulation passes sixteen jobs, twelve compute resets,
one SYS reset and 1,441,792 complete BO bytes. Controller replay and routed timing
remain separate gates. Full synthesis resource review is conditional on the
explicitly disclosed metadata-restoration incident; exact restored checksums do
not establish uninterrupted metadata presence. See the active
[plan](../../../docs/REVIEW_AND_PLAN.md) for current route and hardware status.

The full FP16 C32/K16 group keeps all 512 product lanes, sixteen output kernels,
both DDR controllers, PCIe and BSCAN2/3. Raw final command words remain the
execution boundary. Unsupported fields fail; no runtime CPU arithmetic/layout
repair or learned-projection fallback is introduced. This publication does not
qualify a new image, physical FPGA execution or RK silicon compatibility.
