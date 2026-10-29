"""Compute-reset client for already-audited raw register callbacks.

No connection, recovery or BO access is performed here. A caller may mark its
NPU context clean only after this function returns successfully. Any failure
after starting a reset must poison the containing runtime owner.
"""
from dataclasses import dataclass
import time
from tools.host.transport import ProtocolError,_Deadline,_positive_seconds

@dataclass(frozen=True)
class ResetReceipt:
    epoch_before:int
    epoch_after:int
    status_reads:tuple[int,...]
    action_writes:tuple[tuple[int,int],...]

def perform_reset(read_register,write_register,*,timeout,clock=time.monotonic,_deadline=None):
    """Callbacks accept full byte addresses and keyword ``deadline``.

    The owner must hold its existing transport/runtime lock and have no active
    submitted job/result. Waiting for quiescence does not ACK another result.
    """
    if not callable(read_register) or not callable(write_register):
        raise TypeError('Explicit already-owned raw register callbacks required')
    seconds=_positive_seconds(timeout)
    if _deadline is not None and (type(_deadline) is not _Deadline or _deadline.clock is not clock):
        raise ValueError('Reset must share the owner clock and absolute deadline')
    budget=_Deadline(seconds,clock) if _deadline is None else _deadline
    budget.remaining();statuses=[];writes=[]
    def read(address):
        budget.remaining();value=read_register(address,deadline=budget)
        if type(value) is not int or not 0<=value<=0xffffffff:
            raise ProtocolError('Malformed reset register response')
        return value
    def write(value):
        budget.remaining();write_register(0x50c,value,deadline=budget);writes.append((0x50c,value))
    def status():
        value=read(0x508);statuses.append(value)
        if value&~0x3f or value&8 or not value&16 or (value&1 and (value&2 or value&4 or not value&32)):
            raise ProtocolError('Reset status is reserved, failed, unhealthy or inconsistent')
        return value
    if (read(0x500),read(0x504),read(0x518))!=(0x524b5253,0x10000,0x10004):
        raise ProtocolError('Unsupported reset namespace identity/ABI/capabilities')
    before=read(0x510)
    if before==0xffffffff:raise ProtocolError('Reset epoch overflow requires explicit joint recovery')
    while True:
        word=status()
        if word&4:raise ProtocolError('An unconsumed reset result already exists')
        if read(0x510)!=before:raise ProtocolError('Reset epoch changed before this owner issued a command')
        if word==0x31:break
        if word not in (0x10,0x12,0x30,0x32):raise ProtocolError('Unsupported reset admission state')
    write(1)
    while True:
        word=status()
        if word not in (0x32,0x36):raise ProtocolError('Reset lost ownership or quiescence before completion')
        if word==0x36:break
    after=read(0x510)
    if after!=before+1 or read(0x514)!=0:raise ProtocolError('Reset result epoch/error does not match this action')
    if status()!=0x36:raise ProtocolError('Successful reset result was not retained until ACK')
    write(2)
    while True:
        word=status()
        if word==0x31:break
        if word!=0x32:raise ProtocolError('Reset ACK did not release the owned result cleanly')
    if read(0x510)!=after:raise ProtocolError('Reset epoch changed after acknowledgment')
    return ResetReceipt(before,after,tuple(statuses),tuple(writes))
