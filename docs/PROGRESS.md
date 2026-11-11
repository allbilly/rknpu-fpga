# Progress state, 2026-11-07 (updated)

Snapshot of the "run the RK3588 examples on FPGA" objective. Nothing here
claims FPGA execution: every row is RTL simulation or data-contract evidence.

## No subagent work is in flight

All review subagents were either completed (two, whose notes are preserved in
`docs/analysis/`) or rejected at launch by the membership concurrency cap
(`tier_limit_exceeded`). Nothing is being waited on.

## Corpus scale

Source: 22 Python files under `~/rk3588/examples` and
`~/rk3588/examples/kernel_6_18`.

| Capture family | READY | BLOCKED | Total |
|---|---:|---:|---:|
| `ew-fp16` | 54 | 0 | 54 |
| `ew-int` | 15 | 3 | 18 |
| `pooling` | 19 | 2 | 21 |
| `fdiv-systematic` | 8 | 0 | 8 |
| `conv-fp16` | 9 | 5 | 14 |
| `conv-gemm-vendor` | 10 | 3 | 13 |
| `conv-simple` | 7 | 5 | 12 |

## Convolution: all 9 `conv-fp16` READY cases covered, dual-simulator

| # | Profile | Traffic (reads/writes/frames) | Icarus | Verilator | AXI/top |
|---|---|---|---|---|---|
| 1 | 1×1 C8 | 400-B plane schedule | PASS | PASS | no |
| 2 | `VALID` | 900 / 392 / 441 | PASS | PASS | DMA only |
| 3 | `STRIDE2` | 1060 / 200 / 225 | PASS | PASS | DMA only |
| 4 | `PAD1_ZERO_FRAME` | 1060 / 648 / 729 | PASS | PASS | DMA only |
| 5 | `GROUPED_C2` t0 | 626 / 72 / 81 | PASS | PASS | no |
| 6 | `GROUPED_C2` t1 | 626 / 72 / 81 | PASS | PASS | no |
| 7 | `SPLIT_OC_C16` t0 | 2448 / 392 / 441 | PASS | PASS | no |
| 8 | `SPLIT_OC_C16` t1 | 2448 / 392 / 441 | PASS | PASS | no |
| 9 | `DEPTHWISE_C3` | 996 / 1872 / 2106 | PASS | PASS | no |

Receipts: `docs/CONV_REPLAY_RECEIPTS.md`.

## Pooling: fixtures now complete

**19 of 19 READY pooling cases have a pinned fixture** (plus the source-derived
16×16 global-MAX candidate), written by
`tools/ppu/freeze_pool_fixture.py` and verified by
`tests/ppu_pooling/test_pool_fixture_set_contract.py` (6 tests, PASS).

| dtype | method | fixtures |
|---|---|---:|
| float16 | average | 4 |
| float16 | maximum | 6 |
| float16 | minimum | 1 |
| int16 | average | 2 |
| int16 | maximum | 1 |
| int16 | minimum | 1 |
| int8 | average | 2 |
| int8 | maximum | 2 |
| int8 | minimum | 1 |

The freeze tool refuses a case unless the device BO equals the host oracle
byte for byte and the register dump agrees with the manifest geometry. It also
found and fixed a real bitfield error: `PPU_POOLING_KERNEL_CFG` packs
`KERNEL_WIDTH` at bits 0-3 and `KERNEL_HEIGHT` at bits 8-11 (per
`~/rk3588/experimental/rockchip.py`), not bits 0-3 / 4-7.

**Pooling RTL coverage:** the shared `rk_ppu_pool_raw_dma` currently selects
eight strict FP16 profiles (C3 tail, valid C8 max, padded max, minimum,
average, indexed max, global max, global average). The newly frozen INT8/INT16,
k3x3 and k3s2-pad1 fixtures have **no executing leaf** yet: their cells are
captured and verified but unimplemented. Two `BLOCKED` probes (FP32 and INT32
max) are retained as explicit non-support evidence, not scored as numerical
cases.

All 72 pooling contract tests pass
(`python3 -m unittest discover -s tests/ppu_pooling -p 'test_pool_*contract.py'`),
including the new fixture-set contract. Two pre-existing assertions had drifted
from the source after the global/global-average buffered profiles were added;
they were corrected to the current predicate rather than deleting the check.

## EW: already qualified on both sides

`ew-fp16` has real RK3588 differential evidence (ADD/SUB/MUL/MAX/NEG exact at
eight lanes; FDIV reproduces all 1,452 captured lanes). `ew-int` and
`fdiv-systematic` have captured vectors and passing model/RTL suites.

## Endpoint / board status

| Layer | State |
|---|---|
| Raw-command conv cores | 9 exact profiles, dual-simulator |
| Descriptor-fetch DMA | 3 C4 profiles, dual-simulator, rearm-after-reset |
| Pooling fixtures | 19/19 READY frozen and verified |
| Pooling RTL for INT8/INT16/k3x3/k3s2 | **does not exist** |
| Conv on AXI/top | **not wired** |
| Bitstream / board run | **none** |

## Open work, in order

1. Pooling RTL: integer (INT8/INT16) max/min/avg leaves, k3x3 windows and the
   `k3s2 pad1` geometry; each needs its own leaf + contract test + replay.
2. Wire the conv descriptor wrapper into an AXI-Lite endpoint, then a top.
3. `conv-gemm-vendor` GEMM/FP32 surfaces and `conv-simple` 1×1/5×5/NHWC paths.
4. Synthesis, timing, bitstream, audited board run.
