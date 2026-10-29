"""Raw-frame protocol over explicit, already-owned 32-bit MMIO callbacks.

No PCIe discovery, BAR mapping, TAP emulation or tensor operations live here.
The caller supplies exclusive ownership; shared-transport arbitration remains
an integration requirement. Closing this owner does not reset the FPGA.
"""
import threading
import time

from tools.host.transport import DeviceBusy,ProtocolError,_Deadline,_positive_seconds,_uint

MAGIC=0x4f54504a
FULL=0xfffff


class AxilFrameMailbox:
    def __init__(self,read32,write32,*,close,timeout=30.0,clock=time.monotonic,sleep=time.sleep):
        if not all(callable(fn) for fn in (read32,write32,close,clock,sleep)):
            raise TypeError('Explicit owned MMIO and lifecycle callbacks required')
        self.timeout=_positive_seconds(timeout)
        self._read32,self._write32,self._close=read32,write32,close
        self._clock,self._sleep=clock,sleep
        self._mutex=threading.RLock()
        self.closed=self.failed=self._active=False
        try:
            deadline=_Deadline(self.timeout,self._clock)
            if (self._read(0,deadline),self._read(4,deadline))!=(0x524b5046,0x10000):
                raise ProtocolError('Unsupported RKPF identity/ABI')
            self._idle(deadline)
        except BaseException as error:
            self.failed=True
            try:
                self.close()
            except BaseException as close_error:
                # Cleanup must not replace the protocol/deadline failure that
                # caused construction to abort. Keep the cleanup failure as
                # secondary context where the runtime supports exception notes.
                if hasattr(error, 'add_note'):
                    error.add_note('Mailbox close during failed initialization also failed: ' + repr(close_error))
            raise

    def _read(self,address,deadline):
        deadline.remaining()
        result=self._read32(address,deadline=deadline)
        if type(result) is not int or not 0<=result<=0xffffffff:
            raise ProtocolError('Malformed MMIO read32 result')
        deadline.remaining()
        return result

    def _write(self,address,value,deadline):
        deadline.remaining()
        result=self._write32(address,value,deadline=deadline)
        if result is not None:raise ProtocolError('MMIO write32 must complete or raise')
        deadline.remaining()

    def _status(self,deadline):
        word=self._read(8,deadline)
        if word&~0x1f or word&8:
            raise ProtocolError('Mailbox fault or unsupported status bits')
        if word not in (1,0x11,0x12,0x14):
            raise ProtocolError('Inconsistent mailbox transaction state')
        return word

    def _idle(self,deadline):
        if self._status(deadline)!=1 or tuple(self._read(a,deadline) for a in (0x10,0x14,0x18))!=(0,0,0):
            raise DeviceBusy('Mailbox is staged, pending or retains another result')

    def exchange(self,frame,*,deadline=None):
        """Transmit one exact 640-bit request; return one exact response frame.

        Valid backend error frames are returned unchanged. ACK here releases
        the packet snapshot, not an NPU job result or hardware fault.
        """
        _uint(frame,640,'raw request frame')
        if frame>>604 or frame>>572!=MAGIC:
            raise ValueError('Unsupported raw request magic/reserved bits')
        if deadline is not None and (type(deadline) is not _Deadline or deadline.clock is not self._clock):
            raise ValueError('One absolute deadline with the owner clock is required')
        with self._mutex:
            if self.closed or self.failed:raise ProtocolError('Mailbox owner is closed or poisoned')
            if self._active:raise DeviceBusy('A packet transaction already owns this mailbox')
            self._active=True
            try:
                budget=_Deadline(self.timeout,self._clock) if deadline is None else deadline
                self._idle(budget)
                for index in range(20):self._write(0x40+4*index,frame>>(32*index)&0xffffffff,budget)
                if self._read(0x10,budget)!=FULL or self._status(budget)!=0x11:
                    raise ProtocolError('Complete raw request was not staged exactly')
                self._write(0xc,1,budget)
                while True:
                    word=self._status(budget)
                    if word==0x14:break
                    if word!=0x12:raise ProtocolError('Mailbox lost the committed packet')
                    self._sleep(min(0.001,budget.remaining()))
                response=sum(self._read(0x100+4*index,budget)<<(32*index) for index in range(20))
                if response>>568 or response>>536&0xffffffff!=MAGIC or response>>520&0xffff!=frame>>556&0xffff:
                    raise ProtocolError('Malformed or uncorrelated raw response')
                if response>>512&0xff and response&((1<<512)-1):
                    raise ProtocolError('Nonzero backend error payload')
                if self._read(0x14,budget)!=FULL or self._status(budget)!=0x14:
                    raise ProtocolError('Complete raw response was not observed and retained')
                self._write(0xc,2,budget)
                self._idle(budget)
                return response
            except BaseException:
                self.failed=True
                raise
            finally:self._active=False

    def close(self):
        with self._mutex:
            if self.closed:return
            self.closed=True
            self._close()

    def __enter__(self):return self
    def __exit__(self,*unused):self.close()
