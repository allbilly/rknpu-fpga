# RKFI callback client preparation

`tools/ddr/fi_client.py` is a passive Python client for the private RKFI
management register bank. It accepts caller-owned raw register callbacks; it
does not open a transport, acquire a board lease, reset or program a device, or
connect to a tensor/runtime path. The caller must hold the exclusive audited
image and target lease throughout one claim epoch.

The callbacks have this contract:

```python
read_register(address, *, deadline=budget) -> uint32
write_register(address, value, *, deadline=budget) -> None
```

The write callback returns only after the register write has completed. Any
malformed response or uncertain callback/transaction failure poisons that
client instance. Do not retry, ACK automatically, release ownership, reconnect
or continue normal jobs after such an error. Recovery requires an external,
explicitly audited whole-domain action.
The caller must also poison any containing runtime owner; the callback client
cannot invalidate another object's transport or application state.

## Supported operations

- `claim()` checks the exact identity (`0x524b4649`), ABI (`0x00010000`),
  64-byte line contract (`0x00010040`), configured address window, claim-ready
  status and known-zero/disarmed nine-byte FI mask. A claim is retained until
  joint reset; there is no release operation.
- `control_write()` accepts only vendor addresses `0x300`, `0x304` and `0x380`.
  The `0x380` value must fit in eight bits. The client checks the corresponding
  byte-lane knowledge and observed-mask witness before returning a result.
- `write_line()` accepts one 64-byte aligned line inside the reported window
  and exactly sixteen original uint32 words. The expected write response is
  fixed to OKAY (`0`).
- `read_line()` accepts the same address range and requires an explicit expected
  response of OKAY (`0`) or SLVERR (`2`). Before returning, it reads all sixteen
  raw result words. `FiResult.raw_bytes` emits those original words in
  little-endian order without arithmetic or layout repair.
- Every completed command result remains held until the caller invokes
  `acknowledge(result)`. ACK checks the held command/ordinal, clears staged-field
  validity, and retains the diagnostic claim.

The client checks status and ordinal fields and records the raw mask and MC
observations at `0x324..0x354`. These register observations are sequential reads,
not an atomic snapshot. A response match is not CE/UE or numerical
qualification; inspect the full result and event observations before ACK.
Expected parent ECC faults remain visible in the result status.

This client rejects images without the RKFI identity, ABI and line markers. The
current capacity image does not contain this bank. The management leaf and its
line/write guards are documented in the [maintenance/FI source profile](../rtl/ddr/maintenance_fi/README.md):
[management registers](../rtl/ddr/maintenance_fi/rk_mig_fi_management_regs.sv),
[FI write guard](../rtl/ddr/maintenance_fi/rk_mig_fi_write_guard.sv) and
[line access](../rtl/ddr/maintenance_fi/rk_mig_fi_line_access.sv). Full-span
memory test planning is separate in [capacity preparation](DDR_CAPACITY_PREPARATION.md).

Run the focused callback controls with `make ddr-fi-client-controls`; this
target is also part of the default `make test`. The tests use fake register
callbacks under normal and optimized Python. They do not exercise SystemVerilog,
MIG, an FPGA, RK silicon, physical ECC injection or numerical equivalence.
Coupled RTL/host tests and physical qualification remain separate gates.
