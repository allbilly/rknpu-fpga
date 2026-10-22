# Staged NVDLA conversion/write tail

`build/rk_cmac_output_nvdla.sv` connects the unmodified NVIDIA output converter
through [its tag adapter](NVDLA_CONVERTER_ADAPTER.md) to the unchanged
`rk_cmac_writer`. This follows the user-directed NVDLA numerical baseline.
It is not connected to an accumulator, raw command frontend, host endpoint or
board top; synthetic FP32 inputs are stand-ins, not GEMM results.

## Contract changes relative to the earlier candidate

The [earlier tail](CMAC_OUTPUT_CANDIDATE.md) and all its evidence remain
unchanged. The new converter uses signed finite saturation for overflow and
infinity, and sign plus low-ten-bit NaN payload propagation. Finite rounding
and gradual underflow follow the donor RTL. The donor is pinned to
`8e06b1b9d85aab65b40d43d08eec5ea4681ff715`, with converter SHA256
`56755f347c87a7c8b33458dbdfd2630d57f4dbc4aa1f8f3b2a4dfefedc0401cd`.
No donor arithmetic is edited and no runtime CPU correction is introduced.

The adapter owns one conversion at a time, so the joined tail holds at most
**two** unacknowledged records: one conversion and one writer record. It does
not promise one input per cycle or fixed conversion latency. The test producer
waits for actual acceptance; buffered cancellation covers depths one and two.
The remaining writer/ownership/cancellation RTL is unchanged from the earlier
tail. Thirty-three raw tag bits carry byte address and final-output flag.

`busy` spans input gaps. The last accepted input closes the stream until the
last successful write acknowledgment. Memory request acceptance is not
completion. Cancellation immediately gates external handshakes and latches a
fault; reset dominates cancellation. Writer errors, even-address/known-last
validation, exact timeout behavior and partial-write visibility are retained.
Joint tail/memory reset is mandatory after cancellation or fault.

## Verification

Generate and run the distinct donor-baseline suite with:

```sh
python3 build/gen_cmac_output_nvdla_vectors.py
python3 build/run_cmac_output_nvdla.py iverilog
python3 build/run_cmac_output_nvdla.py verilator
python3 build/run_cmac_output_nvdla.py yosys
```

Runners refuse existing tool output directories. Do not regenerate vectors
during a run. The seven layouts and 1024 FP32 inputs preserve the earlier
generator's shapes, addresses, seed `0x3588ca08` and input bits; only exceptional
expectations change under the explicitly different donor contract: 389 of the
1024 halfword expectations differ. A bit-mask comparison verifies every input,
address and final-record bit is unchanged. Existing
tests/error expectations are not modified. Tests check all memory holes,
stalls, repeated jobs, final-write acknowledgment, first/middle/last faults,
metadata rejection, cancellation, and five reset phases. The four-state suite
adds unknown response status, address, last and cancel codes.

The initial four-state run passed 16 completed streams, 15 faults, eight
cancellations and five resets: 1886 requests, 1875 successful acknowledgments,
and 10104 source-stall cycles. It also rejected zero timeout. Initial XC7
mapping passed. The first Verilator invocation failed because the new runner
omitted the donor source from that command; this was a runner error, not an
arithmetic failure. The initial runner and all three tool directories remain
under `build/cmac_output_nvdla_candidate/attempt1/`. Only that command was fixed;
RTL, bench, vectors and failure checks were unchanged. The corrected-runner
Icarus 13.0 run passes with the same results and zero-timeout rejection.
Yosys 0.65 (`aec814bdf3071f7e0fd0fbe43f7f711e99d01e24`) also passes fresh
XC7 mapping: 273 FDCE, 351 LUT1..6, 36 CARRY4, 31 MUXF7 and nine MUXF8,
no DSP or BRAM. Mapping took 128.207 seconds and retains one ABC combinational
network warning; 19 `$scopeinfo` cells are metadata. The corrected Verilator
5.048 run passes 16 completed streams, 11 faults, seven cancellations and
five resets: 1821 requests, 1812 acknowledgments and 9740 source-stall cycles.
Compilation took 426.367 seconds; the 24 inherited donor diagnostics match
the audited locations exactly. All three corrected-runner checks now pass.
`build/archive_cmac_output_nvdla.py` verifies source/stimulus/artifact hashes
and unchanged writer/adapter identity before freezing evidence.

The completed [source-bound archive](../verification/runs/2026-09-21-cmac-output-nvdla/index.json)
retains 217 members, including the original failed runner attempt and NVIDIA
source/license. Its SHA256 is
`669942d898c7d16525fcec203619e3d05abe925e46500abbda3a2f293d7999dd`.

Verilator permits exactly the 24 pre-audited donor diagnostic locations and
no adapter/writer/tail/bench diagnostics. Icarus requires its compile output to
match the donor-only inherited-timescale warning list exactly. Logs retain
the warnings. Neither simulation nor XC7 mapping establishes physical timing,
RK special-value equivalence, or a complete accumulated GEMM path.
