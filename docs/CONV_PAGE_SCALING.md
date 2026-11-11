# Why page-per-profile scaling stops at four

Status: **two measured round trips.** Synthesis failure on the many-port array
is fixed by a streaming single-port-RAM redesign. The rebuild then **routed
cleanly and failed the 20 ns timing gate** at WNS -1.549 ns. This document
records both, with the exact failing path.

## The failure

```
ERROR: [Synth 8-3391] Unable to infer a block/distributed RAM for
       'weight_store_reg' because the memory pattern used is not supported.
       Failed to dissolve the memory into bits because the number of bits
       (73728) is too large.
WARNING: [Synth 8-4767] Trying to implement RAM 'weight_store_reg' in registers.
        Block RAM or DRAM implementation is not possible ...
        RAM has too many ports (16). Maximum supported = 16.
```

`rtl/cmac/rk_conv_3x3_valid_c4_front.sv` keeps the whole packed weight BO in
`weight_store` and reads it **combinationally at many indices at once** - one
read per kernel lane per input channel - to assemble the 8192-bit
`frame_weight` bus for each tap frame. That is a many-port array, so Vivado
will not map it to block RAM (block RAM has two ports). It therefore falls back
to flip-flops, and then refuses because the bit count exceeds the
`dissolveMemorySizeLimit` of 65,536.

Measured store sizes, from the module's own
`TAPS * WEIGHT_LANES * CHUNKS` localparams:

| Page | Capture | Halfwords | Bits | Synthesis |
|---|---|---:|---:|---|
| profile 0 | 3x3 C4 OC16 | 1,152 | 18,432 | builds (four-page image) |
| profile 3 | 1x1 C4 OC16 | 128 | 2,048 | builds (four-page image) |
| profile 1 | 5x5 C4 OC16 | 3,200 | 51,200 | under the limit; ~51k LUTs alone |
| profile 2 | 3x3 C16 OC32 | 4,608 | **73,728** | **refused** |

The four-page images (`...T062000Z`, `...T073000Z`) are valid because both of
their conv pages hold small stores. Adding profiles 1 and 2 the same way is
what fails.

## Why raising the limit is not the fix

Vivado suggests `dissolveMemorySizeLimit 73728`. We do **not** do that. It would
turn 73,728 bits of weight into flip-flops - roughly 73,728 LUTs on top of the
96,749 the four-page image already spends - and the device has 298,600 LUTs
total. Timing would degrade next to the built path even if it routed. Raising a
tool limit to get a green run is exactly the kind of change this repository
refuses.

## The fix that was implemented

`rk_conv_3x3_valid_c4_front` no longer holds a many-port array. Both operands
now live in **single-port block RAMs** and a frame is assembled into a register
bus over several cycles:

| Store | Before | After |
|---|---|---|
| weights | many-port array, `KERNELS*ALIGN_C*TAPS` halfwords | single-port RAM, same depth, **one read per cycle** |
| input window | many-port array read at up to 32 indices per cycle | single-port RAM, `PIXELS*32` halfwords, **one read per cycle** |
| `frame_weight` / `frame_data` | combinational mux tree | registered bus filled one halfword per cycle |

Vivado now reports both as block RAM:

```
rk_conv_3x3_valid_c4_front__GB5                 weight_store_reg 1 K x 16
rk_conv_3x3_valid_c4_front__parameterized0__GB5 weight_store_reg 128 x 16
rk_conv_3x3_valid_c4_front__parameterized1__GB5 weight_store_reg 3 K x 16
rk_conv_3x3_valid_c4_front__parameterized2__GB4 weight_store_reg 4 K x 16
```

That is 7 RAMB36 + 1 RAMB18 for all four conv pages (1 + 1 + 2 + 4 blocks),
instead of ~200k flip-flops. The cost is latency: a frame now takes
`KERNELS*INPUT_CHANNELS + INPUT_CHANNELS` cycles to assemble (24 for C4, 144
for C16) instead of one. Every replay still compares the complete output BO -
byte-exact where the capture is byte-exact, and within the stated bound for the
FP32 capture. The frame *sequence* is unchanged, only the spacing between
frames.

## Round two: the six-page build does not close 50 MHz

`build/jtag-dual-image/20261109T180000Z`, on the streaming-RAM RTL plus one
`rk_frame_stage` register stage:

| Gate | Value |
|---|---|
| Status | **FAIL** (`bitstream_emitted=false`, `hardware_accessed=false`) |
| WNS / TNS | **-1.549 ns** / -160.574 ns |
| Failing endpoints | **244 / 115,597** |
| WHS / THS | +0.016 ns / 0 |
| WHS-colon failing | 0 |
| Slice LUTs | **228,817 (76.63%)** |
| Block RAM | 19 (RAMB36), 19.5 tiles (2.04%) |
| Routed nets | 324,049 fully routed, 0 errors |
| Worst path | `image/conv_c16_page/engine/core/stage/data_q_reg[21]_replica/C`
              -> `image/conv_c16_page/engine/core/arithmetic/cmac/out_groups_reg[121]/D` |
| Path delay | 21.538 ns, logic 4.325 ns (20.1%), **route 17.213 ns (79.9%)**, 52 levels |

Source-match caveat: this build recorded `rk_conv_simple_core.sv` =
`7ed427c9…`; the file on disk is `9da3dac4…`, a later declaration move. The
front, stage, cell and top match. The path and utilisation are the useful
evidence; regenerate the WNS before quoting it as the current tree's number.

The stage did its job - the worst path now *starts* at the stage output instead
of at the front's 8704-bit bus - but the destination is the CMAC cell's own
combinational cloud: a 32-lane exponent maximum, the donor multiplier, row
sums, eight per-tag compensation muxes and a 32-way serial accumulate, all in
one cycle before `out_groups` registers. At 76.6% LUT utilisation the placer
has no slack to legalise that route.

244 failing endpoints is not a seed/placement outlier; it is the design.

## What would close it, and what each costs

| Option | Effect | Cost |
|---|---|---|
| Pipeline `rk_cmac_fp16_cell` | splits the 21.5 ns path into register + logic + register legs | changes cell latency, so **every** conv and GEMM replay must be re-proven byte-for-byte |
| Share one CMAC array across the conv pages | removes three of the four 512-lane arrays, relieving both LUT pressure and route congestion | needs a time-multiplexed scheduler; one job at a time across all conv pages |
| Ship five pages (drop C16) | fewer failing endpoints simply because less logic | concedes profile 2 to simulation only |
| Lower the clock below 50 MHz | trivially removes the violation | changes a documented contract; not done |

None of these was implemented in this turn. The honest state is: **four-page
image closes at +0.044 ns and is emitted; six-page image routes, is DRC-clean,
and is refused by the timing gate.**

## Why the original reasoning still matters

The weights are consumed **tap-major, then kernel-lane, then channel**. A
streaming feed can load one tap's weight group, emit its frame, and move on,
which needs `WEIGHT_LANES * ALIGN_C` halfwords instead of `TAPS * ...`:

| Geometry | Current store | Per-tap store | Reduction |
|---|---:|---:|---:|
| 3x3 C4 OC16 | 1,152 | 128 | 9x |
| 5x5 C4 OC16 | 3,200 | 128 | 25x |
| 3x3 C16 OC32 | 4,608 | 256 | 18x |
| 1x1 C4 OC16 | 128 | 128 | 1x |

That is a real architectural change: the command BO is read once, so the front
would have to re-read weight addresses for each tap (or keep a small prefetch
buffer), and every page would have to re-verify its replay byte-for-byte. It is
not a copy-paste edit, and it has not been attempted.

## The other option, stated plainly

A build parameterised to one profile can produce one bitstream per profile and
the host picks the image to load. That is honest but it moves the problem from
RTL to deployment: the card would need re-flashing between profiles. It is
listed here as an option, not as a recommendation, and nothing implements it.

## What this means for the objective

In **simulation**, all four conv-simple profiles now replay end-to-end through
the six-page top. In **hardware**, only the four-page image exists. The blocker
for profiles 1 and 2 in one bitstream is the weight-store structure above, and
it is a datapath redesign, not another instantiation.

## Round three (2026-11-09/10): the CMAC cell pipeline closes 50 MHz

The two failing rounds above are superseded. The failing endpoint cluster was
the C16 page's single-cycle CMAC cell cloud (frame stage -> 32-lane exponent
maximum, donor Booth/CSA multiply, row sums, nine per-tag compensation muxes,
32-way accumulate, NaN mux -> the array's `out_groups` register; 52 levels,
21.538 ns with 80% route delay). `rk_cmac_fp16_cell` is now a three-leg
registered pipeline and `rk_cmac_fp16_array` owns a matching elastic
valid/tag pipe; the CACC chain is unchanged and the cell arithmetic is
bit-identical (balanced max tree and balanced modulo-2^38 adder tree are
associative reassociations of the original integer operations).

Result, `build/jtag-dual-image/20261109T160627Z`, Vivado 2026.1, 2,908 s:

| Gate | Round two (20261109T180000Z) | Round three (20261109T160627Z) |
|---|---|---|
| Status | FAIL, no bitstream | **PASS, bitstream emitted** |
| WNS / TNS | -1.549 ns / -160.574 ns | **+3.952 ns / 0.000 ns** |
| Failing endpoints | 244 / 115,597 | **0 / 202,615** |
| WHS / THS | +0.016 / 0 | +0.054 / 0 |
| Slice LUTs | 228,817 (76.63%) | 231,316 (77.47%) |
| Slice regs | 41,730 | 71,058 |
| Block RAM | 19.5 tiles (19 RAMB36) | 19.5 tiles (19 RAMB36) |
| Routed nets | 324,049 | 331,098 / 331,098, 0 errors |
| DRC | 0 errors, warnings only | 0 errors, warnings only |
| Bitstream | none (gate refused) | 18,735,215 B, SHA-256 `81eef4cdcf97c3c86f34b4cce64ba3f436c4da22982950ea11e4b31fff674d39` |

The worst setup path is no longer in the CMAC arithmetic; it is a cross-page
core-to-core route (`conv_page/engine/state_q_reg[0]` ->
`gemm_page/engine/core/frontend/reader/error_code_reg[2]/CE`, 15.549 ns data
delay of which 91.6% is route). The design still has ~4 ns of margin, so no
further timing work is required for this image.

Evidence and adoption: the build ran in a separate snapshot tree while the
option-B experiment held the working tree; the working tree was then restored
to the same pre-B sources and all 73 build inputs compare byte-identical
(`build/timing-lab-share/a_only_adoption_manifest.json`,
`build/jtag-dual-image/20261109T160627Z/ADOPTION_PROVENANCE.md`). The option-B
(one shared CMAC array across the four conv pages) implementation is archived
but not integrated (`build/timing-lab-share/option-b-v2/`,
`option_b_v2.patch`); it was not needed once option A closed with margin.
