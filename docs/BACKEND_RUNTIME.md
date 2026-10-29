# Production backend to EW byte transports

`tools/backend/runtime.py` adds an explicit `RKNPUFPGA` tinygrad device alias.
It uses the clean, pinned tinygrad checkout at
`078eee94d8f1912bb63ce786c250d2c24984844a`, without modifying that checkout or
constructing its DRM device. The adapter imports the original Rockchip
renderer, program, final command writer and task structures. The compilation
target remains `ROCKCHIP`, preserving its production optimization rules;
execution uses the separate `RKNPUFPGA` device and the
[USER2 byte transport](HOST_JTAG_BRAM.md).

This is a strict FP16 EW integration candidate. It is not a complete tinygrad
backend, a Linux DRM driver, a new FPGA arithmetic interface, full GEMM support
or an RK compatibility claim. The full C32/K16 candidate remains separate.

The adapter now accepts an explicit `transport_profile`: `ew_bram` is the
existing default and requires RKEW ABI 1.0; `ew_ddr` requires RKAD ABI 1.0.
Both require exact idle/memory-ready status at construction. There is no
identity probing or fallback between profiles. A caller using the reviewed
DDR transport supplies its existing owner in the EW namespace and selects
`install(factory, backend_path=path, transport_profile='ew_ddr')`.
The encoder, admitted HALF EW images, complete BO transfers and ACK lifecycle
remain shared. This software profile does not enable CMAC or runtime gathers.

The [fresh public-source review](../build/backend-ddr-runtime-prep-v1/root-public-backend-review.json)
passes 23 runtime controls, including explicit DDR admission and fresh-process
registration, plus nine trace and two runner controls. All eleven existing
compiler-to-RTL scenarios also pass: eleven raw jobs, sixteen tasks and
1,081,344 complete BO bytes. Those numerical executions use the default RKEW
frame RTL; those DDR-profile controls use byte-only mocks. The
[V19 complete default regression](../build/production-model-auditors/current-v19/root-review.json)
also passes after this two-file runtime/test increment; preceding snapshots
are preserved separately.

**Physical EW framework milestone, 2026-10-29 HKT:** all eleven selected cases
pass [independent complete-trial review](../build/fpga-bringup/full512-ddr-framework-prep-v1/root-result-review.json)
on the qualified full512 CH1 DDR TinyStories image, tag `5e99f881`.
ADD/SUB/MUL at lengths 8, 9 and 33, repeated SUB(9), and explicit runtime-gather
rejection produce 11 FPGA jobs, 16 tasks, 1,081,344 complete BO bytes checked
before ACK, 39,178 native commands and 117,578 actual JTAG scans. The
[actual physical receipt](../build/fpga-bringup/full512-ddr-framework-prep-v1/physical-test/report.json)
records one volatile reload, exact DNA/IDCODE/TCK/source identity and complete
owned-process cleanup before lease release; flash is unchanged.
The original compiler/final writer and explicit `ew_ddr` adapter execute each
case with no numeric fallback or runtime layout fixup. This qualifies selected
EW framework jobs; CMAC framework execution, the full backend suite and the
new capacity-enabled image retain their separate gates.

CMAC needs a separate layout step. In the pinned backend,
`tinygrad/renderer/rockchip.py::_lower_cmac_reduce` constructs two
input-dependent gathers for its source/blocked-weight tiles, then an `RKCMAC`
and an output gather. `RockchipProgram.__call__` implements those gathers on
the CPU around `emit_cmac_stage`; they are not part of the 45-QWORD CMAC body.
Accepting `RKCMAC` in this adapter would therefore also admit CPU layout work.
Keep the rejection until those compiler-required layouts have an explicit
hardware/raw-command contract; preserve the original input/output BOs and
final encoder boundary when adding that support.

The original final writer also calls `reset_npu()` after a successful standalone
CMAC submission, and before it when its context is not clean. The current
adapter explicitly rejects runtime reset. CMAC integration must implement and
qualify that reset/BO-retention contract as well as the layouts; changing a
clean flag or silently ignoring the reset is not support.

The prepared injected-owner worker has eleven fresh compiler/frame-RTL fixture
cases, three ownership/admission controls and eight wire-auditor mutation
controls. These remain software/native-fixture evidence. The physical parent
holds the existing shared board lease and passes its descriptor to each fresh
case process; a temporary-file control verifies that the parent must hold the
exclusive flock. The new approval also binds the complete preparation metadata,
including the programmer template and case/runtime selection.

## Execution boundary and supported profile

The real Tensor pipeline calls the original `to_program`, renderer and
`RockchipProgram._submit_bodies`. The latter still allocates and writes the
final command/task BOs, including initialized fields, even-QWORD task spacing,
all four PC tail words and the zero guard page. The adapter receives its final
Python ioctl call, validates the complete supported submission/descriptor
profile, uploads the original BO bytes and submits the first descriptor's
unchanged command address and initial amount. The FPGA follows the encoded
chain. No tensor operation is sent directly to the FPGA.

The image admission contract permits only immutable `RKImage` programs with
HALF EW ADD/SUB/MUL configuration values. A leading source-free, index-free
literal initializer may populate declared scratch storage, for example the
compiler's minus-one constant used by SUB. This is constant BO initialization,
not arithmetic on tensor data or a layout repair. All input-dependent gathers,
post-EW gathers, other precision modes, CMAC plans and unmodeled fields fail
explicitly before the program executes. Compiled images must be trusted local
compiler output; there is no external pickle-loading interface.

The FPGA decoder remains responsible for unsupported raw register fields.
The adapter does not remove register writes, zero terminal guard addresses,
rewrite tails, split a linked SUB into independent submissions, or execute a
software reference when hardware fails. The inherited `_run_ew_ops` and final
writer remain unchanged, including the first HALF stage's initialized profile.

The descriptor bridge checks every modeled submit and task field. One admitted
upstream submit becomes one RKEW job. Its tag, successful task count and error
code must agree with the original submission. All owned BOs are read back
before ACK. The task BO is uploaded unchanged for preservation of the original
writer output; this FPGA profile still fetches command memory rather than DMA
fetching DRM descriptors.

## Buffer ownership and failure behavior

Allocations use the explicit 1 MiB aperture at `0x10000000`, backed by the
selected BRAM or DDR namespace, with isolated
4 KiB pages and owned zero-initialized host shadows. Host pointers and FPGA
device addresses are distinct. Synchronization copies complete physical BOs,
including padding, command guards and scratch. It performs no tensor arithmetic
or layout conversion.

The allocator deliberately has no `_as_buffer` hook: tinygrad's generic COPY
must invoke `_copyin` and upload changed input bytes. Exposing a CPU shadow as
zero-copy memory would allow a later FROM_DEVICE synchronization to overwrite
unsent input data. The original program still sees bounded HCQ CPU views for
literal scratch initialization.

Logical argument extents and physical padded EW accesses are checked separately.
A full BO may use its private page padding; a short output subview cannot spill
into neighboring logical data. Each scratch slot likewise owns its rounded
page interval: the 68-byte SUB(33) scratch slot can support an 80-byte physical
EW access without touching the next slot. Literal writes remain bounded by
the declared logical scratch size. Misaligned views, partial output/input
overlap, foreign/freed buffers, altered ownership metadata and capacity overflow
fail explicitly. No address truncation or automatic repair is performed.

The transport is supplied by an explicit factory; importing or registering
this module does not choose a network endpoint. Opening the device calls that
factory and requires the selected idle, memory-ready ABI 1.0 endpoint. Registration
is single-use within a process because tinygrad caches device classes and
instances. Closing removes only this alias's registration and owner entry.
The original `ROCKCHIP` device and other backend entries are preserved.

Execution dimensions must be the backend's default non-grid metadata (`None`
or `(1,1,1)`). Runtime scalars, nondefault dimensions and unimplemented launch
options fail. `ROCKCHIP_SUBMIT_TIMEOUT_MS` retains its positive submission
timeout meaning. Remote errors, unexpected completion and uncertain transfers
poison the owner; there is no retry, numeric fallback or automatic reset.
`reset_npu` is explicitly unsupported. Closing does not recover hardware or
roll back RAM; joint platform reset or reconfiguration remains required.

## Offline qualification

With the pinned checkout and Verilator installed:

```sh
TINYGRAD_ROOT="$HOME/tinygrad" make backend-test
```

The [workflow](../.github/workflows/test.yml) now has a separate backend job
that checks out `allbilly/tinygrad` at the exact pinned revision and runs this
target. Its local equivalent passes all eleven scenarios in the
[fresh receipt](../build/backend-rtl/1793204452150069276/report.json). The main
CI job also runs the portable trace and runner fixtures without a Tinygrad
checkout. The YAML parses locally; this session has not triggered remote CI.

The portable checks can also be run directly:

```sh
python3 -m unittest discover -s tests/backend -p test_trace_contract.py -v
python3 -m unittest discover -s tests/backend -p test_runner.py -v
```

This command opens no TCP socket or DRM device and does not invoke Vivado. It
builds a local RTL process and injects it into the existing `JtagTransport`.
The actual `rk_jtag_ew_bram` control, raw-command DMA, RAM and FP16 arithmetic
execute every nonzero frame. The test IR/IDCODE selection is a software shim;
it is not a BSCANE2 model or physical JTAG proof. The separate USER2 suite
continues to test the frozen mailbox crossing in both simulators.

Fresh Tensor inputs exercise tinygrad's real CPU-to-device COPY path. The
positive cases compile and run ADD/SUB/MUL at logical lengths 8, 9 and 33,
plus repeated SUB(9) jobs. A negative case compiles `a.flip(0)+b` through the
production renderer and requires explicit rejection of its runtime gather,
with no final-writer call or descriptor submission.

A noninvasive Python profiler records original code-object calls to
`to_program`, its decorated implementation, the renderer and final writer.
Actual local compiler images, command bytes, submit records, transmitted frames,
compiled RTL binary and complete BO readbacks are bound to the source manifest.
The verifier rejects missing per-task receipts, altered descriptor bytes, host
writes between SUBMIT and ACK, and ACK before every BO byte has been read.
The software DMA model checks complete memory only after execution; it never
supplies outputs to the runtime or native RTL process.

The numerical oracle and synthetic inputs do not establish RK silicon
equivalence. This test does not pass the full tinygrad `test_ops` census, qualify
physical USER2 operation, or integrate DDR/PCIe. A live invocation still requires
a separately audited target/image and an explicit later hardware action.

The [earlier reviewed execution](../build/backend-rtl/1792958040917797032/report.json)
binds source SHA256 `f38a9c0bf870857565721aca440de6e823c81d811ffe5f551687c399dcdb88ca`,
Verilator 5.048 and GCC 16.2.1. Ten numerical cases execute 11 submissions and
16 tasks and check 1,081,344 complete BO bytes; the eleventh scenario rejects
the runtime gather. Fifteen runtime, nine trace and two runner controls pass.

The [frozen package](../build/backend-copy-audit/1792958403533425061/package)
contains all 27 selected sources, 61 artifacts and its byte-identical report.
All [14 copy controls](../build/backend-copy-audit/1792958403533425061/audit.json)
pass, including report verification with the original run and tinygrad checkout
blocked. Source/binary/frame corruption, missing compiled programs and altered
compiler/writer evidence are rejected. This is independent verification of
saved execution evidence, not a fresh execution without the pinned dependency.
