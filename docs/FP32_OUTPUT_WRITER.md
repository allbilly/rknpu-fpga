# FP32 output writer (`rk_cmac_fp32_writer`)

Status: **RTL written, unit-bench PASS in Icarus and Verilator, and wired into
two executing fixture families.** It is the reason the FP32 captures stopped
being data-only.

## Why it exists

Every output writer in this repository was halfword-wide and converted to FP16:

| Module | Width | Conversion | Used by |
|---|---|---|---|
| `rk_cmac_writer` | 16-bit | none (receives FP16) | `rk_cmac_output_nvdla` |
| `rk_conv_output_atom` | 16-bit | FP32→FP16 in the caller | `rk_conv_simple_core` (FP16 profiles) |
| `rk_nvdla_fp32_to_fp16` | 16-bit | donor `HLS_fp32_to_fp16` | `rk_cmac_output_nvdla` |

That is exactly why two frozen fixture groups had no execution path:

* `conv_simple_fp16_1x1_c4_h8_w8_oc16` — device output is FP32, so the existing
  writer would emit converted values instead of the captured bytes;
* the four frozen `conv-gemm-vendor` GEMM cases — all FP32 output, and their
  `OUT_CVT_SCALE` register is `0x0` (conversion explicitly disabled).

The writer is deliberately narrow in scope: it **does not convert, round or
reorder**. It takes an already-computed 32-bit value and commits it as two
halfwords over the same serialized 16-bit memory port the rest of the design
uses.

## Contract

* one outstanding value at a time;
* the low halfword is written at `result_address`, the high halfword at
  `result_address + 2`, both acknowledged before the value completes;
* `result_address` must be 4-byte aligned, otherwise error code `4` and **no
  memory write**;
* a memory error aborts with code `5` without writing the high halfword;
* a stall longer than `TIMEOUT_CYCLES` aborts with code `8`;
* `done` pulses only for a value whose `result_last` was set;
* partial writes are never retracted — the platform must reset the writer
  together with the memory after any fault, matching the existing writer
  family.

## Where it is now used

| Consumer | Purpose | Selecting parameter |
|---|---|---|
| `rk_cmac_output_fp32` | CMAC/GEMM post-accumulation tail, no conversion | `rk_nvdla_cmac_pipe #(.OUTPUT_FP16(0))` |
| `rk_cmac_frame_output` | atomic-K FP32 frame (two halfwords per 32-bit lane) | `#(.OUTPUT_FP16(0))` |
| `rk_conv_output_atom` | 4-lane FP32 atom (16 bytes) | `#(.OUTPUT_FP16(0), .ATOMIC_K(4))` |
| `rk_conv_output_c1c2_fp32` | placement into the captured `[c1][pixel][c2=4]` surface | `rk_conv_simple_core #(.OUTPUT_FP16(0))` |

Both FP32 jobs have receipts:

* GEMM: `build/cmac-gemm-fp32/{iverilog,verilator}-20261108T174335Z-*`, 4/4
  frozen fixtures, complete 4096-byte BO compared;
* conv-simple: `build/conv-simple-fp32/{iverilog,verilator}-20261108T192540Z`,
  complete 4096-byte BO, 63/1024 words differing at the last bit (worst
  4.77e-7 against an explicit 0.001 bound).

## Evidence

`tests/cmac/tb_cmac_fp32_writer.sv` (`make cmac-fp32-writer-test`) covers:

1. one value ⇒ exactly two halfwords, at `addr` and `addr+2`, in that order;
2. three values ⇒ six writes, with the correct bytes in each slot;
3. a misaligned address ⇒ error code 4 and **zero** memory writes;
4. after a joint reset, an erroring address ⇒ error code 5.

`tests/cmac/tb_cmac_output_fp32.sv` (`make cmac-output-fp32-test`) covers the
tail contract: values pass through unchanged, `done` fires once for `in_last`,
the tail stays closed afterwards, and cancellation surfaces the caller's code.

## Bugs the replay found

Three real bench/model bugs were found and fixed while wiring it, all in
benches rather than the writer:

* waiting on `acknowledged` instead of the return to idle stopped the task after
  the **low** halfword, so it looked like only one write happened;
* the model validated `mem_req_addr` one cycle after the request, when that
  signal already described the *next* beat, so an address was judged against the
  wrong value. It now latches the accepted address;
* `acknowledged` pulses **per halfword**, so a downstream walk that advanced on
  it double-counted. Every consumer now advances on the writer returning to
  idle.

## What is not claimed

* No AXI or frame wrapper of its own: it is a leaf on the serialized memory
  port, and its consumers supply the addressing.
* The FP32 values are not bit-exact against every capture: the device DPU and
  the NVDLA CACC accumulate in different orders. Byte-exactness is claimed only
  where the shape has one product per output value (GEMM k=1). Everything else
  records a measured absolute deviation and the family's declared bound.
