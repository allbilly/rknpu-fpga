# Raw descriptor and terminal-result crossing

`rtl/ddr/rk_async_job_port.sv` is a separate source-preparation component for
keeping the accelerator at its qualified 50 MHz while a future DDR controller
and memory owner run at the generated MIG UI clock. The intended direction is
UI133 control to SYS50 accelerator; the
[halfword memory crossing](DDR_ASYNC_MEMORY.md) transports memory traffic in
the opposite direction. Neither component is connected to the running FPGA
image or the currently qualifying single-UI-clock joined DDR endpoint.

The request contains exactly the original 32-bit command byte address and
32-bit amount. It performs no address translation, amount conversion, tensor
dispatch or command rewriting. Downstream raw decoders retain their numerical,
shape, supported-field and command-framing checks. A free crossing slot is not
proof that the core has accepted the descriptor: the destination offers and
holds it until the actual destination handshake.

The response carries an error bit, original eight-bit error code and complete
32-bit task count. A successful result requires code zero; an error requires a
nonzero code. An inconsistent result is an explicit sticky protocol failure
with E5, never silent success. Ordinary valid raw error codes pass unchanged.
Counts are terminal snapshots, not continuously sampled multi-bit CDC buses.

Both payloads stay held while toggle witnesses pass through at least three
synchronizer stages. There is one outstanding job. Source admission gates new
ownership only; revocation cannot withdraw an offered start or held result.
Stopped clocks preserve ownership and cannot invent progress. This component
does not retry or cancel jobs and has no independent reset or timeout recovery.
An outer timeout must retain the outstanding transaction until a proven drain
or whole-transaction reset.

An unsolicited or early destination result latches a sticky protocol fault.
If the accepted source descriptor has not yet been offered to the core, it
fails explicitly without launching work. An already offered start remains
stable and drains. A later fault does not alter an already held result; the
containing owner must check the separate fault when qualifying completion.
The component supplies no global first-cause ordering. In particular, a
terminal result is not a DDR write-retirement/ECC fence or successful host ACK.

Both reset inputs must be part of the same audited transaction epoch as the
core, memory crossing and DDR owner. A joint reset can invalidate old requests,
results and partial writes. Unilateral reset/recovery is unsupported and no
rollback is promised. Actual reset release, readiness, memory initialization,
ownership, job seal/retire/release and health visibility remain integration
requirements.

The [Icarus](../build/async-job-port-native/iverilog-v2/report.json) and
[Verilator](../build/async-job-port-native/verilator-v2/report.json) runs each
pass eight gates: modes zero/one/two at synchronizer depths three and five,
plus exact time-zero rejection of depths zero and two. Seed is `0x3588cdc2`;
source/destination periods are 7.5/20 ns. The modes exercise:

- 256 bit-exact full-width descriptors/results, ordinary errors and stalls.
- Both stopped clocks, admission revocation, whole-epoch reset and fresh work.
- Early, stalled-start and late-held-result protocol faults, plus inconsistent
  error/code rejection without changing a held result.

The initial Verilator build rejected an unused-bit warning in the testbench
helper. Its failure is retained; the helper now accepts only its four used
status bits. No RTL, stimulus, expected result, warning severity or timeout
changed. Both final runs compile with strict warnings and share the same three
source hashes. The [independent source/log inventory](../build/async-job-port-native/root-review-v2.json)
rehashes those sources, tool receipts, exact eight-case sets and command logs.

```sh
python3 tools/ddr/run_async_job.py --simulator iverilog --out build/new-job-icarus
python3 tools/ddr/run_async_job.py --simulator verilator --out build/new-job-verilator
```

These are native protocol simulations. Held-payload max-delay/skew constraints,
synchronizer mapping, clock/reset routing and joined system tests are still
required. They supply no physical DDR, FPGA timing or metastability result.

`fpga/ddr/async_job_cdc.tcl` prepares the default three-stage mapping contract:
all 64 descriptor bits have 40 ns datapath/skew bounds into SYS50, while all
41 result bits have 15 ns bounds back into UI133. It requires the exact
7.5/20 ns clocks and checks each synchronizer's attributes, depth, fanin and
later-stage timing plus every held bit's actual clock/correspondence/path.
Only first-stage asynchronous D pins and payload hold relationships are cut;
there are no clock groups, CDC waivers or severity changes. Two mock methods
pass, including missing high bits, changed clock periods, missing/deformed
synchronizers and invalid hierarchy. These mock checks cover constraint
admission; they do not establish timing or board clock/reset coverage.

The separate [Vivado 2026.1 mapping](../build/async-job-port-mapping/constrained-v1/report.json)
now passes the native constraint audit for all 105 held bits and nine
synchronizer registers. It maps 228 FDCE registers. The unplaced estimated
minimum descriptor/result slack is +39.485/+14.485 ns under the unchanged
40/15 ns limits. The [independent input/artifact review](../build/async-job-port-mapping/constrained-v1/root-review.json)
rehashes every input and output and checks exact path/requirement coverage.
All 105 CDC-15 held-payload warnings and three CDC-3 informational findings
remain unwaived. Three synthesis warnings about lowering case equality to
logical equality also retain their severity; this mapping does not establish
four-state hardware behavior. No routing, bitstream or hardware action occurred.
