# Host READ64 snapshot contract

An isolated hardware prototype now exists, with a source-bound unit bench
passing both simulators. It is not qualified by the existing uncached DDR
receipts. It preserves raw final commands, BO layouts, numerical/error
expectations and the current test deadlines.

`rk_jtag_backend` services each 64-byte mailbox memory command as 32 halfword
requests. `rk_axi_mem` performs a full 512-bit AXI read for every halfword read.
Consequently one host READ64 currently transfers 2,048 DDR bytes to return
64 bytes. The adapter explicitly supports ordinary RAM, excluding MMIO.
The complete BO comparisons must remain; reducing readback is not the fix.

The candidate will retain the original adapter and wrap its host-read path.
On the first halfword of a READ64 packet, it captures the actual successful
512-bit AXI response. The remaining halfwords of that same packet may select
their unchanged little-endian lanes from that snapshot. One complete line is
still read from DDR for every READ64 command. No CPU cache, arithmetic, layout
conversion or command rewriting is involved.

The wrapper must obey these boundaries:

- Enable reuse only during the backend's active read packet. Use its latched
  response sequence, rather than the mailbox's next pending request, as the
  packet identity. A packet boundary invalidates the snapshot even when a
  sequence is reused or wraps.
- Require an exact 64-byte line match and legal, even, 31-bit addresses.
  Invalid addresses retain the original adapter's explicit error behavior.
- Preserve one outstanding request, response latency of at least one cycle,
  stable responses under backpressure and sticky errors until joint reset.
- Fill only from an actual accepted AXI read with ID0, OKAY and RLAST, while
  the matching host read is still owned. A timeout, failed response or later
  unrelated AXI response cannot populate or revive the snapshot.
- Invalidate on reset, packet/sequence change, health loss, ownership change
  or any accepted write. Known faults cannot be hidden by a snapshot hit.
- Keep engine/DMA reads, initialization, write acknowledgments, partial-write
  RMW/ECC behavior, exact-address fences and fresh ECC checks unchanged.
- Keep the snapshot data unreset; reset its validity and control state. Invalid
  data must never be returned in four-state simulation.

The memory fabric already excludes producer activity during a host packet.
Its ownership and health checks remain authoritative. The snapshot is valid
only within that existing exclusion interval, including successful result
readback before ACK. It is never reused between separate mailbox commands.

Before integration, directed tests must compare all 32 returned lanes against
the actual AXI line and prove exactly one physical read per READ64. They must
exercise backpressure, reset, sequence reuse/wrap, line changes, writes,
DMA bypass, bad addresses and all AXI response failures. The unchanged joined
21-case matrix, including repeated SUB(9) and joint recovery, must then run
against one newly built binary. No old passing case is relabeled as evidence
for the optimized source.

The first full-controller prototype executed the two-job repeated SUB(9)
scoreboard in 898.16 seconds under the original 1,800-second limit. Its final
220,800-byte text image matched the unchanged expected image exactly. Its
producer remains **failed**: the legacy checker required 108,107 PHY returns,
while the snapshot hardware performed 8,845. The difference is exactly
31 saved reads for each of 3,202 READ64 commands. That failed receipt is not
rewritten or accepted retroactively.

The prospective schema-3 contract distinguishes this architecture from the
unchanged schema-2 halfword adapter. It derives expected traffic from original
commands and BO extents, before execution:

| Workload | Legacy PHY returns | Snapshot PHY returns | Successful READ64 packets / AXI reads |
|---|---:|---:|---:|
| Repeated SUB(9), two successful jobs | 108,107 | 8,845 | 3,202 / 3,202 |
| Joint recovery, latest initialized epoch | 56,486 | 6,855 | 1,601 / 1,601 |

The new bench independently counts physical AXI address handshakes and requires
exactly one for every successful READ64. It also withdraws the input payload
after acceptance, testing that snapshot scope and sequence use latched backend
state. Legacy markers, missing/duplicate reads, wrong return counts, changed
error coverage and incomplete BOs are rejected. Eight portable contract methods
pass. This architecture requires its own schema-3 native build and workloads;
the full optimized matrix and physical DDR remain open.

Fresh schema-3 execution now passes the two-job repeated SUB(9) case in
702.87 seconds and joint reset recovery in 644.37 seconds, each under its
original 1,800-second limit. Both exact traffic inventories in the table match,
and complete unchanged BO images pass. The new-driver verifier accepts the
repeat batch. An
[independent selected-case audit](../build/ddr-read-snapshot-root-review/v1/recovery-prefix.json)
also accepts the completed recovery case from the original matrix-A batch;
that containing batch remains failed after its later unknown-command traffic
check. Neither audit accepts that failed batch as a whole.

The source stimulus for unknown-command injection performs an extra READ64
of the command line before writing its deliberately invalid target ID. The
new execution-only v4 contract accounts for that read and the completed
write/RMW traffic prospectively: three successful READ64 packets and three
AXI reads. It retains the same schema-3 ELF, numerical outputs, error
expectations and deadlines. Its nine portable controls and fresh unknown/
partial-task executions pass; the old failed receipt is unchanged.

The six-case SUB/MUL, five-case ADD/error and eight-case fault batches now
pass execution and independent verification. Together with repeat and the
independently accepted recovery prefix, the
[same-ELF union](../build/ddr-read-snapshot-root-review/v2/all21.json)
accepts all 21 cases. It rechecks the complete BO images, raw traffic counts,
unchanged deadlines, fixed inputs and exact case coverage. The original
matrix-A batch still has status FAIL; only its completed recovery case is
accepted through the separate audit. These are logical controller/encoded-PHY
results, not physical DDR qualification or full512/DDR integration.

The [portable selected-source archive](../verification/runs/2026-10-27-ddr-read-snapshot-all21/index.json)
preserves242 payloads with complete run logs/readbacks, the actual compile HDL
and all five transitive parameter/image headers. It also retains the exact
CXX/LINK wrapper text and identifies the excluded compiled ELF/tools by hash.
Independent stored/decompressed rehash passes. The original matrix-A failure
and recovery-prefix boundary remain visible. The corrected archive index
records its earlier header-classification correction separately.
