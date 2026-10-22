# Staged standalone CMAC command DMA

`build/rk_cmac_nvdla_dma.sv` joins command-buffer fetching to the staged
[donor numerical core](CMAC_NVDLA_CORE_CANDIDATE.md). It is not yet part of
the production Makefile, EW AXI endpoint, FPGA top or tinygrad runtime.
No CPU arithmetic or runtime layout repair is introduced.

## Descriptor and framing

The caller supplies a 32-bit device byte address and the actual backend's
body count, **45 QWORDs**. This is deliberately distinct from the EW DMA
descriptor, whose initial count includes its tail. The command address must
be 16-byte aligned and its 392-byte executed range must fit the 32-bit
address space. Misalignment, a different count, or range overflow fails E7.
The untouched allocation-alignment word after the 49 commands is not fetched.

The wrapper reads four little-endian halfwords per QWORD and supplies the
assembled 64-bit word unchanged to `rk_cmac_nvdla_core`. It neither replaces
the encoder nor supplies semantic tensor operations. It fetches exactly 49
words (196 halfword reads) before arithmetic memory traffic can begin.
The last four target/offset keys must be, in order:

| Word index | Target/offset key |
|---|---|
| 45 | `0001:0000` |
| 46 | `0101:0014` |
| 47 | `0041:0000` |
| 48 | `0081:0008` |

Tail keys in the body, or the wrong tail order, fail E3. The existing core
continues validating every value and all body registers, including the
terminal enable value `0x0d`. This does not implement EW chaining, nonterminal
CMAC tasks, a task-list scheduler, or the complete RK DRM descriptor ABI.

## Memory, ownership and errors

The single outstanding halfword request/response port is owned by the fetcher
until the terminal word is accepted, and by the numerical core afterward.
Requests remain stable under backpressure. Start is unavailable throughout
fetch, execution and final write acknowledgment. `done` and `acknowledged`
retain the numerical core's write-response semantics; operand/address
completion pulses are not job completion. A subsequent standalone submission
is supported after completion without reset.

Fetch bus errors produce E5, request/response timeouts E8. Four-state tests
also reject unknown fetch status as E5 and unknown command data as E6;
these simulation diagnostics are not electrical metastability detectors.
Core errors retain their original codes. Faults are sticky and suppress all
external handshakes; reset both the wrapper and transport before restarting.
Already performed writes are not rolled back.

## Evidence and current status

`build/run_cmac_nvdla_dma.py` derives a bench from the source-bound raw-core
bench, retaining all physical read-order, FP44 group/tag, output data/hole,
request stability and final-write acknowledgment checks. It additionally
checks all 196 command fetch addresses and prohibits early operand traffic.
The original raw-core bench and its passing records are unchanged.

The suite includes eight existing numerical fixtures; unknown target and
misplaced/reordered tails; invalid descriptor amount/alignment/range; command
fetch bus error and both fetch timeouts; operand/write errors and operand
response timeout; reset during command fetch and arithmetic; repeated jobs;
and five additional four-state command/operand/status fault cases. Mutation
cases are explicit negative tests; successful fixtures retain the captured
compiler words byte-for-byte. Generation/protocol seeds remain `0x3588ca15`
and `0x3588ca16` respectively.

**Verilator 5.048 passes all 23 entries** under
`build/cmac_nvdla_dma_candidate/verilator/`, with no local-source warnings.
The eight numerical fixture replays check 1,568 command halfword reads,
90,112 operand halfword reads, 1,216 group values/tags and 1,088 acknowledged
output halfwords. The two reset tests and repeated-job test complete four
additional jobs; twelve fault tests remain separate. The K=65 finite and
mixed-special-value jobs each take 84,237 simulation cycles with this bench's
stalls; these are not hardware timing measurements.

Icarus 13.0 is running its 28-entry suite. Initial descriptor/fetch and
operand/write fault tests pass, but this is not yet a complete four-state
pass. Whole-DMA XC7 primitive mapping now passes with Yosys 0.65:
6,728 flip-flops, 11,527 LUT1..6, 399 CARRY4 and three DSP48E1 primitives.
The report is `build/cmac_nvdla_dma_candidate/yosys/report.json`; these are
mapping counts, not placed utilization. No DMA mapped functional replay,
timing signoff, board execution or RK differential
result is claimed. Donor grouping and special-value policy remain the
documented NVDLA working baseline.
