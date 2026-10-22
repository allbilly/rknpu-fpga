# Tagged NVDLA output-conversion adapter

`build/rk_nvdla_fp32_to_fp16.sv` is a staged, synthesizable tag/handshake
adapter around the **unmodified** `HLS_fp32_to_fp16` in `/home/fedora/hw`.
It advances the user-directed NVIDIA numerical baseline. A new
[staged output tail](CMAC_OUTPUT_NVDLA.md) now connects it to the result writer;
that tail has its own verification record. Neither is connected to an
accumulator, raw-command execution or the FPGA top. The earlier original converter/output-tail archives remain
separate evidence for their earlier IEEE-style candidate policy.

## Arithmetic and provenance

Donor revision: `8e06b1b9d85aab65b40d43d08eec5ea4681ff715`.
File: `vmod/vlibs/HLS_fp32_to_fp16.v`.
SHA256: `56755f347c87a7c8b33458dbdfd2630d57f4dbc4aa1f8f3b2a4dfefedc0401cd`.
The donor retains its NVIDIA Open NVDLA license and embedded Mentor notices;
the new adapter/bench use MIT notices. No donor checkout is edited.

The adapter performs no arithmetic. The donor supplies finite RNE conversion,
gradual half underflow, signed finite saturation on overflow/infinity, and
NaN output `{input_sign, 5'b11111, input_mantissa[9:0]}`. That last rule can
turn a zero low payload into infinity. These are donor rules, not asserted
RK silicon facts. See [NVDLA_CONVERSION_AUDIT.md](NVDLA_CONVERSION_AUDIT.md).
The corresponding C-model source was inspected but not executed.

## Transport contract

Inputs are `in_valid/ready`, FP32 `in_value` and `TAG_WIDTH` raw tag bits;
outputs are `out_valid/ready`, half `out_value` and the unchanged tag.
`TAG_WIDTH` defaults to 97 and has an explicit zero-width failure check;
the installed Icarus crashes while elaborating that invalid configuration,
so a clean zero-width rejection is not yet validated. The adapter stores **one
in-flight tag/value ownership**, accepting only when no prior value is pending
and the donor is ready. It deliberately has no simultaneous consume/refill
optimization. There is no assumed fixed donor latency and no numerical
operation on tags. Output backpressure stops donor acceptance at its output;
the tag remains held. An accepted input produces exactly one output unless
reset cancels it.

Active-low reset resets both donor and ownership and suppresses both external
handshakes. Unaccepted input data/tag and invalid output data are not meaningful.
Enclosing job/transport state must be reset together; reset does not undo
already acknowledged memory writes. This leaf belongs **after accumulation**,
not after each CMAC product. No CPU arithmetic/layout fallback is introduced.

## Verification scope

The runner `build/run_nvdla_converter.py` reuses the exact 330,760 FP32 inputs
from the original converter suite. Finite expectations use the independently
generated Python `struct` oracle; exceptional expectations follow the audited
donor rules above. **37,233 expected results differ** from the earlier
infinity/canonical-NaN candidate. This is a new explicitly labeled donor test,
not a rewrite of old expectations to make old tests pass. All prior source,
stimulus and archive files remain unchanged.

Coverage includes every finite-half rounding boundary and both neighbors,
signed zeros, subnormal/normal transitions, overflow ties, exponent extremes,
NaN payloads and 65,536 seeded raw FP32 inputs. The bench additionally checks
raw tags, 64 forced output-stall cycles with a second input held pending,
random source/output stalls, no extra outputs, and cancellation at 13 pipeline
ages followed by successful fresh transactions. Seed: `0x3588ca09`.

Verilator 5.048 passes **330,799 comparisons**, 13 reset cases, 88,323
output-stall cycles, 1,080,648 source-blocked observations and 1,411,912 HDL
cycles. This is a simulation cycle count, not a measured board frequency.

The unsuppressed standalone donor preflight reports 24 inherited Verilator
diagnostics: one multi-module filename, three width truncations, one width
expansion, 17 unused signals and two unused parameters. The test runner keeps
those diagnostics visible and requires exactly the same category/file/line
set and count. Any new donor diagnostic or any adapter/bench diagnostic fails.
The width cases concern generated parameter conditions and generated expression
sizing; donor expressions were not edited. The second simulator checks the
same numerical observations independently. Icarus retains the donor's inherited
missing-time-unit warning; the new SV adapter/bench have explicit time units.

Yosys 0.65 XC7 mapping passes at default tag width: 233 FDCE, 288 LUT1..6,
24 CARRY4, 31 MUXF7 and 10 MUXF8; no DSP or block RAM. Seventeen `$scopeinfo`
cells are metadata, not unmapped logic. Mapping took 151.376 seconds on this
run and is not placement, calibrated timing or physical validation.

The first full four-state simulation hit its 1800-second wall-clock limit
without a reported mismatch. The terminal failed report, executable and logs
are retained under `build/nvdla_converter_candidate/iverilog_timeout_1800`.
`build/retry_nvdla_converter_iverilog.py` reran the **identical executable
and vector bytes**, with unchanged RTL/bench and a 7200-second wall limit.
That simulation passed all **330,799 comparisons** with exactly the Verilator
reset/stall/block/cycle counts above, in 2855.257 seconds. Its subsequent
zero-tag-width compilation exited 139 without a diagnostic, leaving the
overall retry report **failed**. A separately connected parameter harness also
crashes for width zero but compiles/runs for width 97. This is a parameter-test
tool failure, not an arithmetic mismatch or a passing rejection test.
The numerical pass and parameter failure are both retained; no full-pass
archive has been manufactured from this partial result.
The shorter joined-tail four-state suite has independently passed. Only
completed source-matching reports may be
archived by `build/archive_nvdla_converter.py`; it refuses a running/failed
report and requires both simulators' complete result lines to agree.
