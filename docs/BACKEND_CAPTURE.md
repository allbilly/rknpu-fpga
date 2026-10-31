# Backend command boundary and remaining hardware captures

## Current user-supplied backend

The working local checkout is now `/home/fedora/tinygrad`, branch
`rockchip-2608-1500`, commit `078eee94d8f1912bb63ce786c250d2c24984844a`.
It supersedes the earlier candidate below as the implementation target.
`tools/capture_current_backend.py` exercises production `to_program` and the
actual final runtime writer; it saves nine cases with all BOs and descriptors.
The initialized EW body, nonzero guard address and linked SUB are implemented
through `rk_ew_dma`. The original raw-word core still rejects nonzero PC fields
with E7; the capture tool's optional `--rtl` check deliberately tests that legacy
rejection. No word is removed or rewritten. [PC_DMA.md](PC_DMA.md) describes the
separate DMA replay of all nine verbatim BO captures, integrity checks, full
memory comparisons and saved RTL-observed halfwords. See the source-bound
verification reports for results. These are synthetic-input encoder captures
and simulated outputs, not RK3588 output captures.

## Historical candidate encoder check

The earlier Fedora source audit located `allbilly/tinygrad` branch `rockchip-2608-ew-restart` through the RK3588 reference notes. The inspected public revision was `c6784623afc4f116ae7dc326ab9842e6bf9a3dcf`. It is retained only as historical evidence, not the current user's backend pin.

The optional check is runnable on this host with system Python (which has NumPy):

```sh
make rtl-test
/usr/bin/python3 verification/check_backend_encoder.py \
  --backend build/reference/tinygrad-rockchip
```

For a fresh workspace, fetch `https://github.com/allbilly/tinygrad.git`, check out that exact commit into the supplied `--backend` path, and install its Python dependencies in an isolated environment. The check requires a clean checkout and refuses another revision.

The check executes `emit_ew_stage`, `patch_stage` and `RockchipProgram._submit_pcchain` unchanged. Only device allocation and final submission are intercepted. The bytes captured from the resulting command BO are compared with the supported profile, stored verbatim as `commands.bin`, converted to QWORD hex for the existing HDL port, and executed by the compiled `tb_ew` RTL testbench. No tensor operation is passed through the FPGA interface. The test owns all intercepted in-process memory and never constructs a device or opens `/dev/dri`.

Nine cases passed: ADD, SUB and MUL, each at logical lengths 8, 9 and 33 (physical lengths 8, 16 and 40). Each has 22 final QWORDs. The synthetic input and expected-output images come from the already-verified test-vector generator. `build/backend_encoder/report.json` records the backend commit, script hash, RTL source revision, executable hash, commands and raw stream hashes. Each case contains its exact stream, memory/check images and RTL log.

This verifies the final encoder's ordinary single-terminal-task FP16 profile. It does **not** verify complete `test_ops` lowering, the backend's stateful direct-tail mode, linked PC DMA, host gathers/layout stages, or numerical agreement with RK3588. No extra register was allowed or discarded to make these cases pass. The FPGA runtime must not adopt CPU arithmetic or layout repair from the existing host runtime.

Gate B still needs a real RK3588 run with the same pinned backend. For each ADD/SUB/MUL case, retain the final command BO bytes and descriptor (including QWORD amount and device addresses), exact initialized bytes of every accessed input/output BO including padded lanes, output BO bytes after completed submission, logical and physical shapes, reset/driver/kernel state, seed and source revision. Do not export only an `allclose` result. Keep NaNs, signed zeros, subnormals and overflow as separate numerical-policy cases; the current RTL policy remains a candidate until those captures agree.

The Fedora host's `/dev/dri/card1` was identified through sysfs as `amdgpu` (`1002:1636`), so no RK3588 example was executed against that pathname. That capture performed neither YPCB programming nor Rockchip execution; later FPGA results are documented separately.

## Passive DRM capture preparation

[`tools/rk_capture.py`](../tools/rk_capture.py) now supplies recording primitives
for a future real-device case runner. Importing it opens no device and imports
no backend. `audit_device()` reads identity metadata and rejects a target that
does not identify the RK3588 board and `rknpu` driver. `observe_backend()` checks
the actual opened control descriptor against that audited device and observes
the original allocator, free and ioctl functions. Install it before constructing
the backend so the initial reset and every allocation are recorded.

The source hooks are the pinned backend's `RockchipProgram._submit`,
`RockchipDevice._gpu_alloc`, `_gpu_free` and `FileIOInterface.ioctl`. The actual
submit hook is below the final encoder and its normal TO_DEVICE sync. It saves
the unchanged submit structure and every live physical BO before the original
core-0 blocking PC ioctl. After a successful return, explicitly recorded
diagnostic FROM_DEVICE syncs precede complete post-submit snapshots. Extents
come from the actual page-rounded mapping and `meta.size`, including padded
lanes, command tails, descriptors and scratch. Logical tensor views alone are
insufficient. No command, tensor arithmetic or layout is rewritten.

The observer serializes capture and allocation/free across their original
calls. It records whether the original submit started and returned successfully;
a capture failure then poisons the device and prevents a retry. Failed allocation
registration attempts clean up through the original free function. Uncertain
free outcomes invalidate the mapping rather than permit a second unmap or a
later snapshot of its old virtual address. Cleanup failure remains explicit.

The device-free tests use owned ctypes memory and a fake ABI/driver. Run them
with `python3 -m unittest tests.test_rk_capture -v` and the corresponding
`python3 -O` command. They validate the observer and artifact behavior, not
RK silicon, SystemVerilog or an FPGA.

This is preparation, not a real-silicon fixture or a completed case runner.
The future runner must pin the backend and driver/kernel provenance, select
supported cases through the original compiler, initialize and record complete
BO contents, preserve reset boundaries, and bind source hashes, seed and shapes
before and after execution. Runtime tensor gathers remain excluded from the
FPGA path. Actual RK output capture and a source-bound FPGA comparison are
still required before numerical compatibility or special-value behavior is
accepted.
