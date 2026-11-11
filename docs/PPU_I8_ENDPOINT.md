# Signed-INT8 pooling descriptor endpoint

`rtl/ppu/rk_ppu_pool_i8_k2s2_dma.sv` is the first PPU command path in this
repository that consumes the raw 26-QWORD Rockchip command stream end to end
and produces the captured output BO without any host-side repair.

## Boundaries

| Layer | Module | Rule |
|---|---|---|
| raw fetch | this module | QWORDs copied byte for byte from memory |
| gate | `rk_ppu_pool_i8_k2s2_profile.sv` | every non-relocated field compared exactly |
| relocations | this module | only QWORDs 13 and 20 may vary |
| execution | `rk_ppu_pool_int_k2s2.sv` | signed INT8 2×2/stride-2 max/min |
| writes | this module | the leaf's 16-byte atom, halfword by halfword |

`start_amount` must be exactly 26. An unaligned command address, a command
block that does not fit the aperture, or any operand/command overlap is
rejected before a single operand byte is read. The profile and the leaf are
held in reset from launch until the whole stream is accepted, so a second job
always starts from a defined single-frame state.

## Error codes

| Code | Cause |
|---:|---|
| 1 | `start_amount` not 26, or a non-relocated command field differs |
| 2 | a relocated address word is all-`x` or zero |
| 3 | command/operand window outside the aperture, or overlapping |
| 5 | memory response error |
| 6 | `x` in read data, or a profile published without collecting |
| 7 | unexpected response / unreachable state |
| 8 | memory never responded within `TIMEOUT_CYCLES` |

## Replay

`tools/ppu/run_pool_i8_k2s2_dma.py` runs nine modes in both simulators:

| Mode | Scenario | Expected |
|---:|---|---|
| 0 | captured job | complete 4096-byte BO exact, 144 transactions |
| 1 | amount 25 | error 1, zero traffic |
| 2 | unaligned base | error 3, zero traffic |
| 3 | corrupted QWORD 9 | error 1 after 104 command reads |
| 4 | input base aliases command | error 3, no operand read |
| 5 | output base outside aperture | error 3, no operand read |
| 6 | memory error on first operand read | error 5, output BO untouched |
| 7 | two sequential jobs | 288 transactions, complete BO after each |
| 8 | memory never ready | error 8, zero traffic |

Receipts live under `build/ppu-pool-i8-k2s2-dma/<sim>-<stamp>-<case>/report.json`
and record simulator version, source revision, hashes before/after, and that no
hardware, Vivado or bitstream was involved.

## Not established

No FPGA execution, no board observation, no silicon special-value policy, and
no claim that the endpoint generalises beyond the two captured INT8 C16 tasks
(max and min). The `MINIMUM` parameter selects between those two captures only.
