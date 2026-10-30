# Maintenance/FI source profile

This explicitly selected, source-only profile lists 72 ordered project hardware
sources for `rk_whole_reset_fi_parent`, FP16 C32/K16. It is not selected by the
default build and does not change the qualified framework profile. Run
`python3 tools/ddr/maintenance_fi_profile.py --check` to verify its pinned order
and bytes. Vendor MIG controller and primitive sources, the encoded PHY test
model, headers, fixtures, and testbench are not in this hardware manifest.

The copies and reused sources match the project portion of the independently
reviewed V4 native run: 133 total model sources, five headers, four fixtures,
bench SHA-256 `21dbb6230d279325c7c1c5741a8d0400eb7a831f5115c165296fd4c268276ab2`,
binary SHA-256 `6fa0d9a1bd7ffe36101a4426cd7ad8c77f3915a49c4d4f6cd70764c82c575cf5`,
and [root acceptance](../../../build/whole-reset-terminal-format-results-review-v4/root-acceptance.json)
SHA-256 `23cc186e30966abc53ff0108651de9a00f69f8a8740ce8d8228d0ed6771af0f0`.
These new paths are byte-identical source publication, not a new execution.
The native test used a 1 MiB model, MAX_TASKS=4 and timeout 2048; default 2 GiB
capacity and 4095 tasks are not qualified by it. This selection does not add
RKLY `0x400`, RKRS `0x500`, or framework-profile features.

An upstream normal mailbox must retain an unaccepted request across client
reset, as required by the frame gate's SEALED contract. The existing mailbox
reset by `c0_clients_rst_n` cannot establish that recovery property. `cfg_reset`
is for configuration/startup only; the SYS 604-bit raw-frame interface has a retained
power lifetime and must not be cleared by TAP reset or PCIe PERST.

Actual physical MIG FI witness ports and retained USER2/SYS mailbox integration
remain missing. No board-wrapper, PCIe, mapped CDC, timing, physical ECC or
hardware qualification follows from this profile.
