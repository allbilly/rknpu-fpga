# Parent timeout-tag trial candidate

Replace full-source orders 112 and 148 together with the byte-exact files in
[the manifest](source-candidate.json). Other 199 selected records remain
unchanged. Default selectors are unchanged; do not compile these module
definitions alongside their baselines. This pair is selected for a fresh full
trial, with no new routed timing, image or hardware acceptance.

The fabric keeps its original fault/code/timeout outputs and adds two private
Boolean tags: an exact saved-timeout tag and a timeout cofactor without the
parent abort or instantaneous monitor-gap terms. The parent consumes the
saved tag for an already-pending monitor cause. In its late fabric branch it
uses the second tag only with its remaining raw abort sources known zero;
otherwise it uses the saved tag. Earlier fault priorities remain unchanged.
The shared-reset active-implies-seen invariant is required. Unknown saved
selectors retain the original diagnostic comparison fallback.

The fabric also factors five qualified health gates, and the parent factors
launch admission through the existing fault-free readiness and child cofactor.
Strict abort rejection and unknown latched-fault behavior remain. All changes
are combinational: no state, external top ports, clock/reset policy, precision,
reduction order, numerical output layout or transaction latency is added.
The full FP16 C32/K16 group retains all 512 product lanes and sixteen kernels.
Both DDR controllers, PCIe and BSCAN2/3 remain required.

Fresh source reviews bind both actual child binary reset/induction proofs,
conditioned extracted parent composition and selected four-state vectors with
real negative controls. Fresh paired component tests retain 21 Icarus and 19
Verilator cases, original output/state comparisons and scoped tag checks.
They do not compile the complete parent. Matched OOC diagnostics measure launch
5.221 to 4.687 ns (11 to 10 levels) and all three result-code D cones 5.459 to
5.173 ns (14 to 13). That launch endpoint is an output-port source cut, not the
real descriptor CE; complete-parent models and full implementation remain
required. See the [active plan](../../../docs/REVIEW_AND_PLAN.md).

Raw final command words remain the execution boundary. Unsupported fields
fail explicitly; no learned dense CPU fallback or runtime arithmetic/layout
repair is introduced. Numerical special-value behavior remains candidate
behavior until actual RK differential tests establish it.
