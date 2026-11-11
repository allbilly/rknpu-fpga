# Third image page: FP32 conv (`b000`)

Status: **RTL complete; endpoint and mailbox replays pass, and the page is in
an emitted bitstream.** Nothing programmed; no board run.

## Why a second conv page instead of a run-time switch

`rk_conv_simple_axi` takes the capture geometry as **elaboration parameters**
(`INPUT_H`, `KH`, `KW`, `INPUT_CHANNELS`, `KERNELS`, `C1_BLOCKS`, `ALIGN_C`,
`PACK_C2`, `CHUNK_LANES`) and a `PROFILE` id that selects the exact 52-QWORD
register template. A run-time width switch would turn a build-time contract
into a run-time one: the decoder would have to accept a set of shapes instead of
one captured shape, and the comparator and writer widths would become
data-dependent.

So the image instantiates **two** conv pages:

| Page | Address | `PROFILE` | `OUTPUT_FP16` | `DEVICE_ID` |
|---|---|---|---|---|
| conv FP16 | `0x8000` | 0 (C4 3x3) | 1 | `0x524b4353` (`RKCS`) |
| conv FP32 | `0xb000` | 3 (C4 1x1) | 0 | `0x524b4415` (`RKCS` +1) |

The identities differ by one byte so a host can prove which page answered. The
rest of the ABI is unchanged: same `rk_cmac_job_control` offsets, same
`COMMAND`/`RESULT_*` semantics, same held-until-reset fault slot.

## Arbitration

`ypcb_dual_endpoint_top` now arbitrates **four** engines plus the host window.
Each page's `memory_ready` is the complement of the other three engines and the
host, so a submit cannot start while any other engine owns the port. The owner
register is three bits (`OWN_CONV = 1` … `OWN_CONV_FP32 = 5`); a two-bit literal
silently mapped `OWN_GEMM` onto `OWN_NONE` earlier in this work, which is why a
contract test pins the width and the encoder now lists five distinct owners.

## Evidence

| Check | Result | Receipt |
|---|---|---|
| Standalone endpoint, profile 3, 8 modes | PASS both simulators | `build/conv-axi/iverilog-20261108T194552Z-3`, `.../verilator-20261108T195835Z-3` |
| Dual image, modes 0-8 (all pages) | PASS Verilator, top hash matches | `build/dual-endpoint/verilator-20261109T034423Z` (0-6), `...T031949Z` (7-8) |
| Dual image, modes 0-5 unchanged | PASS both simulators | see `docs/PROGRESS_TABLE.md` |
| Mailbox, mode 4 (FP32 conv through frames) | PASS Verilator, 175 frames | `build/jtag-dual/verilator-20261109T013805Z/mode-4` |
| Bitstream with the fourth page | **PASS, emitted** | `build/jtag-dual-image/20261109T062000Z` |

Mode 6 compares the complete 4096-byte output BO against the frozen capture
with an explicit `0.001` absolute bound: 63 of 1024 words differ at the last
bit, worst 4.77e-7. The earlier zero-tolerance comparison failed on exactly
those 63 last-bit differences, which is why the bound is explicit rather than
silently rounded away.

## Two mux bugs found while wiring it

The fourth page found two omissions that no test covered before, because they
only affect the new path:

* `dispatch_wready` and `read_dispatch_ready` were not extended to
  `T_CONV_FP32`, so a register write reached the page's `AW` but never its `W`
  and every access hung. The write-channel mux and the read-address mux are now
  complete.
* `dispatch_bvalid` and `dispatch_rvalid` had the same gap, so even a completed
  access would never have produced a response.

Both are mechanical, and the page-identity probe now reads `0x524b4415` from
`0xb000` through the full front end.

## Cost of the second page

The second `rk_conv_simple_axi` is not free. The image grew from
**55,137 to 96,749 LUTs** (+41,612, 32.4% of the device) and from 30,908 to
41,140 registers. BRAM stayed at 8 × RAMB36. Timing still closes, but the
margin is thinner than the three-page image:

| Image | WNS | WHS | LUTs |
|---|---:|---:|---:|
| three pages (`...T043000Z`) | +0.141 ns | +0.036 ns | 55,137 |
| **four pages (`...T062000Z`)** | **+0.044 ns** | **+0.058 ns** | **96,749** |

A fourth conv page for profiles 1 or 2 would cost roughly the same again and
would approach the device limit, so those profiles are not simply "more of the
same": they need either a smaller shared datapath or a run-time-select design
that this repository has so far refused on contract grounds. That trade-off is
recorded here rather than assumed.

## What is not claimed

* No board run and no programming.
* The FP32 conv page serves one capture (profile 3). The other two
  conv-simple profiles (0 and 1) are still absent from the image, and profiles
  0-2 are exercised only through the standalone endpoint.
