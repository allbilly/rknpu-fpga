# Native USER2/SYS host preparation

These host interfaces have offline protocol tests. A physical run still needs
an accepted routed image, exact image/target checks and the existing exclusive
board lease. The earlier `60e7abbb` application image does not qualify these
interfaces. Model tests do not establish physical reset, ECC or clock-stop
behavior.

The outer runner owns the native bridge and cable throughout the operation.
Enable USER3 explicitly in both `render_bridge(..., allow_user3=True)` and
`NativeLink(..., allow_user3=True)`. The default remains USER2 only. The
USER3 bridge uses a distinct readiness response; a mismatched client fails.
The installed XC7K480T vendor BSDL specifies six-bit USER3 instruction
`100010` (`0x22`), available after configuration.

## Normal raw jobs

For an already audited and exclusively owned `link`:

```python
from tools.host.raw_jtag_frame import RawJtagFrameExchange
from tools.host.raw_frame_session import RawFrameSession
from tools.ddr.frame_transport import FullDdrFrameTransport

carrier = RawJtagFrameExchange(link, timeout=30)
baseline_sequence = carrier.prepare()
session = RawFrameSession(carrier.exchange, close=carrier.close, source=1,
                          timeout=30, initial_sequence=baseline_sequence)
transport = FullDdrFrameTransport(session, timeout=30)
```

`prepare()` selects USER2 and captures its retained completion sequence.
Constructing the session then checks and acquires the RKHO hardware lease;
constructing the full transport checks the backend namespaces. The session
uses one completion-sequence allocator for ownership and backend requests.
The carrier forwards the exact raw frame and rejects a sequence that could
match its previous completion.

Run the original final encoder through this transport, retaining the existing
raw command, descriptor and complete-BO contracts. After full readback and job
ACK, explicitly call `transport.release()` and then `transport.close()`.
Closing the carrier leaves the borrowed native link owned by the outer runner.

## SYS inspection and whole reset

`tools.host.sys_mailbox.SysMailboxProbe` provides read-only SYS inspection.
Construction performs no I/O; `probe()` selects USER3, seeds from its captured
completion and checks RKPR, ABI and capability before reporting status and
counters. Close the probe before returning the link to another interface.

For repeated USER2/USER3 interleaving on the same borrowed link, use
`SharedSysMailboxProbe` or `SharedSysMailboxAccess` from
`tools.host.shared_sys_mailbox`. These adapters select USER3 inside every
locked SYS transaction. They retain the original completion sequence and
last response across instruction switches; they never reseed a prepared
client to hide a stale response. The original adapters above remain suitable
for a SYS-only interval followed by closing the adapter.

Selecting a mailbox does not make an old runtime valid after whole reset.
The fresh carrier/session and explicit BO reload requirements below still
apply. The interleaving regression uses a fake link that routes DR shifts by
the selected instruction; it is host protocol evidence only.

An explicit whole-reset action uses:

```python
from tools.host.sys_mailbox_access import SysMailboxAccess

sys_access = SysMailboxAccess(link, timeout=120)
receipt = sys_access.perform_reset()
sys_access.close()
```

The caller serializes access and closes the prior normal runtime context.
The reset client verifies the identity, counters and hardware deadline, sends
START once, and requires a held successful result with fresh assertion,
completion and platform-readiness witnesses. Exact attempt/epoch increments
and the result phase/error record must match before it sends ACK. It returns
after current completion, readiness and START eligibility are sampled again.

A failure after START may leave a reset in flight or a held failed result.
Keep that runtime context poisoned and use an explicit audited recovery
procedure. The client issues no automatic retry, cancellation or failure ACK.
Direct `write_register()` accepts only the documented START/CANCEL/ACK keys at
SYS offset `0x0c`; hardware operation-state checks still apply.

After a successful whole reset, create a fresh USER2 carrier/session and seed
it from the current completion. Reload the original BO bytes explicitly before
submitting new raw jobs. Check complete BOs before ACK. The host path preserves
the encoder output and performs no tensor arithmetic or layout repair.

The native bridge, these adapters and the reset client do not program the
FPGA or flash. The outer audited runner retains image loading, process cleanup
and board-lease duties. Physical PCIe execution and RK numerical equivalence
remain separate acceptance gates.
