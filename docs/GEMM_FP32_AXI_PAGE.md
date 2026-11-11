# FP32 GEMM page (`rk_cmac_gemm_axi`)

Status: **RTL complete; endpoint and mailbox replays pass, and the page is in
a real bitstream.** Nothing programmed; no board run.

## Why two new leaves were needed

The GEMM datapath was already validated (`tools/cmac/run_gemm_fp32.py`, four
frozen fixtures). It had two gaps before it could be a board image:

1. **No transport page.** `rk_cmac_nvdla_axi` existed, but every replay of it
   drove the FP16 tail. A page that admits the FP32 capture and drives the
   halfword memory port directly did not exist.
2. **No memory bridge in the board direction.** `rk_cmac_nvdla_axi` presents
   *AXI4* on its memory master (`rk_cmac_axi_mem`), while the board images expose
   a *halfword* BRAM port. Nothing converted AXI4 to halfword, so a BRAM-only
   image either had to instantiate an unused AXI round trip or could not use
   the endpoint at all.

## `rk_axi_mem_slave`

AXI4 slave -> halfword memory master, accepting only the access shape
`rk_cmac_axi_mem` emits:

| Field | Accepted value |
|---|---|
| `awlen` / `arlen` | `0` (single beat) |
| `awsize` / `arsize` | `6` (512-bit) |
| `awburst` / `arburst` | `INCR` |
| `awid` / `arid` | `0` |
| write strobe | exactly **one** full 2-bit halfword lane |
| address | 64-byte-aligned beat base, whole beat inside the aperture |

Writes take the one-set lane and commit that halfword at `base + 2*lane`. Reads
fetch all 32 halfwords of the beat and return the 512-bit value, so the
requesting adapter selects its own lane.

Anything else is `SLVERR` with **no memory access**, never a guess at a byte
mask. That matters because a mis-decoded strobe would write the wrong halfword
of a live tensor and the comparison would still pass on shape.

Two bugs were found while writing it:

* The first version used `mem_req_ready` alone as the issue gate. A memory
  model that keeps `ready` high after accepting a beat made the leaf fetch the
  same address twice. It now tracks exactly one outstanding transaction.
* `write_data_q` was driven by both a combinational decoder and the reset
  branch of the sequential block, a real multi-driver. It is now a wire off the
  latched lane and latched W beat.

Unit bench: `make axi-mem-slave-test` -> `PASS AXI_MEM_SLAVE accesses=35
writes=3`. It pins the happy path, out-of-aperture write and read, a
partial-lane write, a multi-beat read, a byte-sized read, and a misaligned beat
base; every rejection is asserted to reach memory **zero** times.

## `rk_cmac_gemm_axi`

The host page. Register ABI is exactly `rk_cmac_job_control`, so one driver
covers conv, pooling and GEMM:

| Offset | Meaning |
|---|---|
| `0x00` | `DEVICE_ID` = `0x524b434d` (`RKCM`) |
| `0x04` | `ABI_VERSION` = `0x00010000` |
| `0x08` | `STATUS` |
| `0x0c` | `COMMAND`: 1 submit, 2 acknowledge |
| `0x10` | `START_ADDRESS` (command BO base, 16-byte aligned) |
| `0x14` | `START_AMOUNT` (must be 45 body QWORDs) |
| `0x18` | `JOB_TAG` |
| `0x1c` .. `0x24` | result tag / tasks / code |

It instantiates `rk_cmac_nvdla_dma #(.OUTPUT_FP16(1'b0))` and drives the
halfword memory port directly — no AXI round trip inside a BRAM-only image.

## Evidence

| Check | Result | Receipt |
|---|---|---|
| Bridge unit bench | PASS, 35 accesses / 3 writes | `make axi-mem-slave-test` |
| Standalone AXI endpoint, 5 modes | PASS, both simulators | `tools/cmac/run_gemm_fp32_axi.py` |
| Dual image, modes 0-8 | PASS Verilator, top hash matches | `build/dual-endpoint/verilator-20261109T034423Z` (0-6), `...T031949Z` (7-8) |
| GEMM shapes through the image page | all four PASS | `--gemm-case` on mode 4: `m2_n2_k1` (byte-exact), `m1_n16_k32`, `m2_n16_k32`, `m4_n32_k64` (0.1 bound, worst 1.27e-4) |
| USER2 mailbox, GEMM job | PASS, Verilator, mode 3 | `build/jtag-dual/verilator-20261108T213238Z` |
| USER2 mailbox, contract/conv/pool | PASS, Verilator, modes 0-2 | `build/jtag-dual/verilator-20261108T220336Z` |

The standalone endpoint bench compares the **complete 4096-byte BO** and pins
the negative paths: submit before memory admission, body amount 44, ACK with no
result, and writes to read-only registers. The image bench additionally asserts
that the conv page cannot submit while a GEMM job runs and that the host memory
window stays closed.

`gemm_m2_n2_k1` is byte-exact (one product per output value). The k=32/64 cases
carry the family's declared `0.1` bound and are exercised by the standalone
runner, not by the image replay.

## Bitstream

`build/jtag-dual-image/20261109T043000Z` contains this page at `0xa000`.

| Gate | Value |
|---|---|
| Process | PASS, bitstream emitted, `hardware_accessed=false` |
| WNS / WHS | **+0.141 ns / +0.036 ns** |
| BRAM | 8 × RAMB36 |
| LUTs / registers | 55,137 / 30,908 (up from 48,833 / 24,110) |
| DRC | `CHECK-3`, `DPIP-1` x12, `DPOP-1` x6, `DPOP-2` x6, `REQP-1839` x20 — warnings only |
| Bitstream | 18,735,215 bytes, SHA-256 `f86d4d9cda6d56582c18a49adb1566acb595c75ad2f5d6d9a957ad98c7f31416` |

Every synthesis and constraint input in the receipt is byte-identical to the
files on disk (52 of 52 checked). The build was not weakened: no DRC severity
was waived and no clock was cut.

## Known inefficiency (honest, not a correctness issue)

The bridge is a **beat slave**: one AXI read returns all 32 halfwords of a
64-byte beat, and the requesting adapter (`rk_cmac_axi_mem`) reads them one
halfword at a time at 32 separate addresses. Because the bridge has no
per-beat cache, each of those 32 halfword reads re-fetches the whole beat from
memory. The k=1 replay measures **137,344 halfword reads** against the 4,292
the bare-DMA path needs — a 32× read amplification.

A one-beat cache was implemented for this and **reverted**, because it corrupted
descriptor assembly: the cached beat was served with a stale final halfword and
the profile decoder saw `key=0x00004004` instead of `0x10014000`. Correctness
was not worth the speedup, so the simple form is kept and the cost is recorded
here rather than hidden. Fixing it properly needs a bench that compares the
cached and uncached beats directly.

This does not change any numerical result: all five modes pass in both
simulators and the complete BO matches.

## A receipt defect fixed

`tools/host/run_jtag_dual.py` recorded `tool_version=simulator` — the literal
string `"verilator"` — and kept **no source hashes**. That is not evidence: a
receipt must say which tool version produced it and must fail if the RTL changed
mid-run. Both are now recorded (`source_hashes_before` / `_after`, and a real
`--version` string), matching the other runners in this tree.

## What is not claimed

* The bitstream is emitted, but its gate report is a post-route result, not a
  board measurement.
* Nothing has been programmed and no board result exists.
* The image still serves one selected profile per page, not the corpus.
