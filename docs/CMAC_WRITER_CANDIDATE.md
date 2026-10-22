# Staged result-write controller

`build/rk_cmac_writer.sv` is an original halfword-write leaf, now also used by
the separate [staged output tail](CMAC_OUTPUT_CANDIDATE.md).
It consumes already converted 16-bit results, not raw commands or tensor
operations. It is not in the production source manifest, not instantiated by
`rk_cmac_product_front`, and does not itself implement GEMM or output conversion.

## Contract

The producer holds `result_valid`, byte address, data and `result_last` stable
until `result_ready`. The leaf snapshots that record and owns at most one
memory transaction. It holds the write request through backpressure, then
waits for a response. Requests and responses use the existing halfword memory
contract; a response cannot arrive before the cycle after request acceptance.

`acknowledged` pulses on each successful response. `done` pulses only when
that response also belongs to a record with `result_last=1`. Neither input
acceptance nor request acceptance completes a write. A failed final response
must not produce either pulse. `busy` covers this one outstanding transaction,
not the entire reduction/job lifetime. A future integration controller must
retain command ownership between results and until the last write response;
connecting `downstream_busy` to this leaf's `busy` alone is insufficient.

Addresses must be even. The last legal halfword starts at `0xfffffffe` and
ends exactly at 2^32. Four-state simulation rejects an unknown address or
last flag. This leaf trusts the enclosing controller's destination bounds,
result count and last tag; it does not replace the raw profile validator.

Faults are sticky until reset: E4 invalid address, E6 invalid last flag/state,
E5 failed or unknown response status, E8 memory timeout. Timeout applies only
to stalled memory request/response phases, not gaps between input results.
The default is 65536 cycles; zero is an elaboration/time-zero error. Once
faulted, no further result, request or response handshake is allowed.

Reset the leaf and memory adapter together to cancel outstanding work.
Previously accepted writes may already have committed, even if the response
later fails. No rollback, atomic job commit or isolated reset is promised.

## Test target and current evidence

`build/make_cmac_writer_vectors.py` verifies the seven portable compiler
command hashes and independently traverses output rows, 16-channel atoms and
lanes. It supplies 1024 synthetic result records with the compiler's physical
gaps. The writer does not execute those raw commands: these are layout tests,
not captured RK outputs or accumulated products.

`build/tb_cmac_writer.sv` checks every output address/data pair and all untouched
sentinel halfwords. It randomizes request stalls and response delays, delays
the final acknowledgment, injects first/middle/final bus errors and both
timeout phases, exercises invalid addresses and unknown status/last flags,
resets after partial writes in both memory phases, restarts, and checks the
zero/2^32 address boundaries. Memory commits at request acceptance in this
test, ensuring fault/reset checks do not accidentally assume rollback.

The seed is `0x3588ca06`, the test timeout is exactly 32 stalled cycles and
the idle-gap test lasts 80 cycles. The source-bound Icarus run passes eleven
complete streams, fifteen faults, two resets and four unknown-value cases:
1541 requests and 1532 successful acknowledgments. Compile/run logs have no
warnings. Reports record tool versions, staged-source fingerprints, vectors,
commands and executable hashes under `build/cmac_writer_candidate/`.

Verilator 5.048 also passes eleven complete streams, eleven faults and two
resets: 1476 requests and 1469 acknowledgments. Icarus 13.0's extra unknown
response cases add 65 requests and 63 acknowledgments; the invalid-address
and invalid-last cases issue no writes. Both native compile/run paths have
zero warnings. Coverage totals include 1218 writes from completed streams,
82/79/82 requests from bus/request-timeout/response-timeout fault streams,
and 15 requests/14 acknowledgments before the two reset cancellations.

Default-parameter XC7 mapping passes against the final runner fingerprint.
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) maps to 91 FDCE,
70 LUT2..6, 12 CARRY4 and one MUXF7 in 95.268 seconds. There are no DSP or
BRAM cells. One ABC combinational-network warning is retained. Source-bound
reports, vectors, executables, exported netlist/JSON and logs are retained in
the [candidate archive](../verification/runs/2026-09-21-cmac-writer-candidate/index.json).
No mapped-netlist simulation, routed timing, FPGA test, numerical GEMM or RK
compatibility result is claimed for this leaf.
