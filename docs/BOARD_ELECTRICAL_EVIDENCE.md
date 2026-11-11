# Board configuration-bank evidence (donor corroboration)

Status: **corroborating donor evidence, not a measurement of this card.**
This record exists because `bitsream` emission is blocked on
`CFGBVS-1`, whose only fix is a board-verified `CONFIG_VOLTAGE`/`CFGBVS` pair.

Checked 2026-11-08 against the local `~/openTPU` checkout at
`ca05e24f94f119d75981d3edd9219e73cfc83a32`. Nothing here was inferred; every
claim below is tied to a file hash that can be re-verified.

## Claimed pair

| Property | Value | Source |
|---|---|---|
| `CFGBVS` | `GND` | `boards/ypcb-00338/constraints/otpu_top_ld.xdc:82` |
| `CONFIG_VOLTAGE` | `1.8` | same file, line 83 |
| Part | `xc7k480tffg1156-2` | bitstream header `7k480tffg1156` |

## Independent corroborations

1. **Primary build constraints.** `boards/ypcb-00338/constraints/otpu_top_ld.xdc`
   sha256 `b70db3b943d074776dc053f6c622316b84dddf98206f83181f4cfd4961880a13`,
   with the comment "Configuration banks at 1.8 V (the board's flash and IO are
   LVCMOS18)". This is the constraint set for the shipped LiteDRAM design.
2. **A second, independent build.** `boards/ypcb-00338/ramtest/ramtest.xdc`
   sha256 `ae1c4b0084363bca4633664fa61c025e25737343ae1797df2c00c07d5a5127ea`
   selects the same `GND`/`1.8` pair for a separate RAM-test image.
3. **Prose record.** `docs/board.md:1466` ("CFGBVS GND / 1.8 V")
   sha256 `9e21448bca3389b669e99a143ceb425fd974147fc63ead871863e203a6da6870`,
   and `docs/flash.md:15` ("banks at 1.8 V")
   sha256 `fee9e4af2fa8e60ab97ab51387c8927d3f92c729876752e339985ef43a6daae5`.
4. **A built image with those settings actually configured this board model.**
   `bitstreams/ch1-pcie-2gb/otpu.bit`
   sha256 `c7d3891b58d65ba72a3fc67c27c63c8dca3246db55d6504f7a63b636c876d1cf`
   (Vivado 2026.1, compressed, part `7k480tffg1156`), with its audit
   `bitstreams/ch1-pcie-2gb/evidence/flash-programming-audit.json`
   sha256 `a9665b2415128904cd6563cb1d116ade1d1251fc6671a948f6fb8e2b05fe5a01`:
   `flash_written: true`, `flash_verified: true`,
   `jtag_boot_from_flash_verified: true`.

This is stronger than the XDC-only corroboration recorded in
`docs/OPENXC7.md` ("donor choices corroborate a candidate setting, but do not
satisfy this design's physical electrical gate"): an image built with that pair
was written to the flash and booted from it.

## What this still does not establish

The audit that records the successful boot also records:

| Field | Value |
|---|---|
| `cold_boot_verified` | `false` |
| `physical_pcie_verified` | `false` |
| `backup_policy` | `SKIPPED_BY_USER` |
| LED polarity | "unverified" (`docs/board.md:1467`) |

So:

* **No physical strap measurement exists.** `CFGBVS GND` and `1.8 V` are a
  build-time assertion that has been shown to produce a configuring image, not a
  voltmeter reading or a schematic trace of the strap pin. A 1.8 V-configured
  image can configure even if the strap differs; configuration success is not a
  strap measurement.
* **No cold boot.** Only a JTAG-requested boot out of flash was verified.
* **No PCIe link observation** is recorded as verified.
* **LED polarity** is unverified in the donor as well, so our
  `LED_ACTIVE_LOW` remains an explicit build parameter that must be observed on
  the board.

## Outcome: the pair was supplied and both images emitted

With this evidence recorded, the pair was supplied explicitly and the pooling
image produced a real bitstream:

| Field | Value |
|---|---|
| Image | `build/ppu-image/20261108T170500Z/implementation/rk_ppu_i8.bit` |
| Bytes | 18,735,212 |
| SHA-256 | `1908003f62ac4e22d2f48470fb204208311ebeced540d926f71a451ae77836a5` |
| Header design | `ypcb_ppu_i8_top` |
| Header part | `7k480tffg1156` |
| WNS / WHS | +14.633 ns / +0.037 ns |
| DRC | 0 checks (CFGBVS-1 gone once the pair was applied) |

The pair is still never defaulted: it is supplied per build and validated by
`tools/ppu/vivado_ppu.py` and `tools/conv/vivado_conv.py`. Writing an image with
the wrong configuration-bank setting is the one failure mode that can leave the
card unbootable, so the values are asserted, not inferred. The pair to supply is:

```sh
export RK_CONFIG_VOLTAGE=1.8
export RK_CFGBVS=GND
export RK_CONFIRM_BOARD=YPCB_00338_1P1
export RK_EMIT_BITSTREAM=1
```

`tests/test_board_electrical_evidence.py` re-hashes the four donor files above
when `~/openTPU` is present and **skips with a recorded reason** when it is not,
rather than passing on absence.
