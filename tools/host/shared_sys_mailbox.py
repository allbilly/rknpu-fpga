"""USER3 SYS mailbox adapters that safely share a borrowed NativeLink."""
from __future__ import annotations

from tools.host.sys_mailbox import IR_BITS, USER3_IR, SysMailboxProbe
from tools.host.sys_mailbox_access import SysMailboxAccess


class _ReselectUser3:
    """Select USER3 inside each already-locked raw SYS transaction.

    The first operation delegates to the original baseline capture. Once this
    object is prepared, switching instructions only reselects USER3; sequence
    and last-response state remain intact so an intervening USER2 operation
    cannot make a stale SYS reply look fresh.
    """
    def _prepare(self, deadline):
        if self._prepared:
            self._ensure_open()
            self._link.scan(USER3_IR, bits=IR_BITS, ir=True, deadline=deadline)
            return
        return super()._prepare(deadline)


class SharedSysMailboxProbe(_ReselectUser3, SysMailboxProbe):
    """Read-only SYS mailbox probe for an explicitly USER3-enabled shared link."""


class SharedSysMailboxAccess(_ReselectUser3, SysMailboxAccess):
    """Whitelisted SYS command adapter for a shared USER2/USER3 NativeLink."""
