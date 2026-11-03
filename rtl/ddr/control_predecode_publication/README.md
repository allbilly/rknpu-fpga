# Control predecode and payload publication candidates

These three byte-exact, unselected replacements apply to source orders 4,
149 and 164 of the reviewed 201-record control-publication parent. The
[manifest](source-candidate.json) records content identities and workspace-local
component evidence. Do not compile these module definitions alongside their
baselines. Public default selectors are unchanged.

The MIG CTRL top captures the original vendor read decoder at the existing
accepted-address edge, with the original AW priority and address truncation.
Its one-hot cases select live register words, preserving selected X/Z values,
permissions, aliases and response timing. Before the first accepted address,
RDATA while RVALID is low remains outside the claim. The legal captured
one-hot invariant is required; arbitrary corrupted selector state is excluded.
The original vendor license and all write/register-bank logic are retained.

The job-control bank writes only unpublished descriptor storage. Original
accepted writes publish a field on the same edge; rejected writes cannot
change a published field. Original validity flags expose zero after reset
and successful ACK. Read snapshots retain their original pre-update order.

The layout DMA similarly publishes locally captured command metadata and
separates disjoint response-data captures. Ports, failure priorities, raw
protocols, computation and cycle timing remain unchanged for legal-reset
histories. Arbitrary corrupted selector/validity state is not claimed.

Component binary proofs and paired Icarus/Verilator tests pass independent
review. The CTRL proof is a read/address-cone proof with common symbolic
register data; it is not a whole-controller proof. Native CTRL testing also
uses the actual vendor register bank and selected physical parameters.
Standalone CTRL mapping improves the worst of all 32 read-data endpoints
from 3.071 ns/five levels to 2.309 ns/three levels in both selected modes,
with nine extra LUTs and 24 FFs per controller. Its raw collector remains
failed because the Tcl writes the completion marker to a file; a separate
artifact review qualifies the saved diagnostic results without relabeling it.

No combined full-parent model, routed timing, image or FPGA qualification is
transferred to this source set. Fresh combined synthesis and mapped-context
review, models, implementation checks and hardware gates remain required.
The unchanged compute group is FP16 C32/K16 with 512 product lanes. INT8/INT4
and unmodeled fields remain unsupported; no runtime CPU arithmetic or layout
fixup is introduced.
