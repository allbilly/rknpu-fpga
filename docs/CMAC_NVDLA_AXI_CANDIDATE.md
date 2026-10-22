# Staged CMAC AXI host endpoint

`build/rk_cmac_nvdla_axi.sv` connects public AXI-Lite job control to the
[standalone CMAC command DMA](CMAC_NVDLA_DMA_CANDIDATE.md), the donor numerical
pipeline, and a 512-bit AXI memory adapter. This is a single-clock internal
endpoint, not a PCIe/MIG shell, a board top or an installed tinygrad device.
The production EW endpoint and its source-bound regression are unchanged.

## Host contract

The register layout and one-job/one-result ownership follow
[HOST_CONTROL.md](HOST_CONTROL.md), but this is a separate CMAC endpoint:

| Register | CMAC meaning |
|---|---|
| `0x00` | Identity `0x524b434d` (`RKCM`), not `RKEW` |
| `0x04` | Transport version `0x00010000` |
| `0x10` | Device byte address of the final command BO |
| `0x14` | Body QWORD count: exactly 45, excluding the four-word tail |
| `0x18` | Opaque submission tag returned with the result |
| `0x20` | One completed task on successful completion; zero on failure |

Control/status, result code/tag, AXI-Lite access errors and level-held IRQ
otherwise retain the documented control contract. A successful result must
be acknowledged before another descriptor can be staged. Fault recovery
requires joint reset. The identifier distinguishes the count semantics;
the existing EW descriptor must not be submitted unchanged to this endpoint.
No high-level tensor operation interface is added: the engine fetches and
executes the original final RK words.

The completed-task input is one only when the standalone DMA's successful
completion pulse is present. The controller samples it with that pulse;
partial output writes do not count as a completed task. Final success can
become visible only after the final AXI B response has propagated through
the memory adapter and numerical writer.

## Memory and reset contract

`build/rk_cmac_axi_mem.sv` is a staged copy of `rtl/rk_axi_mem.sv` with
asynchronous reset assertion. Its addressing, single-outstanding transaction,
full 64-byte read beat, two-byte write strobe, response checking and
non-cancellation of exposed AXI requests are otherwise unchanged. It rejects
high-bit and odd halfword addresses rather than truncating them. The backend
BOs must live in ordinary RAM, not side-effecting MMIO.

`build/rk_cmac_job_control.sv` similarly retains the original controller's
behavior, changing only the endpoint identity and reset assertion style.
All endpoint components require the same reset. The platform must synchronize
deassertion to `clk` and reset the downstream fabric/RAM interface jointly
after faults. Reset does not roll back completed memory writes.

`memory_ready` is admission control, not an implemented DDR calibration/ECC
recovery mechanism. There is no CDC, PCIe BAR, calibrated DDR controller,
interrupt delivery bridge, runtime gather engine, or host allocation driver.

## Verification

`build/gen_cmac_axi_vectors.py` packages the eight existing raw-core fixtures
as sparse behavioral AXI RAM images. Command words, physical input/weight BOs
and numerical output expectations are unchanged and source-hash checked.
This is test preparation, not runtime CPU arithmetic or layout repair.
Memory checks include the original command/input/weight buffers, output
values, output holes and guard halfwords. Successful tests save observed
images and require exact text equality with the expected address/value list.

`build/run_cmac_nvdla_axi.py` derives its public-port bench from
`tests/tb_host_axi.sv`. It retains independent AXI address/data stalls,
held responses, access-error checks, descriptor ownership, memory admission,
result/tag/count/IRQ checks and joint reset. CMAC-specific adjustments are
explicit: final-write fault at the last output of the standalone task, zero
completed tasks for that fault, CMAC identity, and a longer simulation/poll
budget for the actual numerical path. Fault expectations are not relaxed.
The protocol seed remains `0x3588c510`.

The suite has 19 entries per simulator: eight numerical replays, ten fault/
partial-reset scenarios, and a repeated successful submission. It covers
read/write errors, read-address/response and write-response timeouts,
descriptor alignment, unknown command target, high-address rejection,
failure on the final write response, and joint reset after 17 acknowledged
outputs while the next write response is held.

The first Verilator attempt stopped on mixed synchronous/asynchronous reset
usage. Its concurrent Icarus attempt was explicitly terminated before any
source edit; partial results are not a completed pass. Initial sources and
runner are retained under `build/cmac_nvdla_axi_candidate/reset_style_attempt1_sources/`.
The corrected staged control/adapter and behavioral slave use consistent
asynchronous reset assertion. No original EW source, arithmetic source,
primitive, numerical expected value or fault expectation was modified.

The corrected **Verilator 5.048 run passes all 19 entries** under
`build/cmac_nvdla_axi_candidate/verilator_reset_fix/`, with no local-source
warnings. Its ten saved successful memory images (eight fixtures, partial
reset/restart, and repeated submission) each match the expected address/value
list byte-for-byte. The eight numerical fixture jobs alone exercise 92,768
AXI transactions: 1,568 command halfword reads, 90,112 operand halfword reads,
and 1,088 acknowledged halfword writes. This validates behavioral AXI RAM,
not a calibrated DDR controller or physical timing.

The corrected Icarus 13.0 suite remains running under `iverilog_reset_fix/`.
Endpoint mapping and physical hardware behavior are not yet claimed.

`build/check_cmac_axi_leaves.py` independently verifies that the reused
control/adapter sources differ only in the documented module names, reset
assertion style and CMAC identity (ignoring comments). It also runs the
existing standalone protocol benches against the staged copies without
changing their error/reset expectations. The control bench is directed;
the adapter's stall seed is `0x3588a512`. These leaf tests are separate from
the numerical integration suite. Both Icarus leaf tests pass, including
seven control-reset scenarios and six memory-adapter reset scenarios.

The source-bound [native evidence archive](../verification/runs/2026-09-21-cmac-axi-native/index.json)
contains 330 hash-verified members, including the preserved first reset-style
attempts, source resolutions, unmodified donor snapshots/licenses and ten
observed memory images. Archive SHA256:
`1b9bc6edbd3da64fd7d8de7ee4511c9d4361c47b20e8e49fb9ba5d9c6fbd2b2e`.
Its scope is explicitly Verilator endpoint plus Icarus host leaves, not a
completed four-state numerical endpoint or FPGA validation.
