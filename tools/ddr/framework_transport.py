"""Three-job/reset transport profile; requires an explicit audited link.

This adds no tensor API, BO transformation, programming or fallback. The caller
must audit the image/target and own the existing shared board lease.
"""
import time
from tools.ddr.dual_transport import DualDdrRawTransport
from tools.host.transport import (ABI_VERSION,MAX_TCK_HZ,READ_REGISTERS,WRITE_REGISTERS,
    DeviceBusy,ProtocolError,_Deadline,_positive_seconds,_uint)
from .compute_reset import perform_reset

PROFILES={'ew':(0x000,0x524b4144),'cmac':(0x100,0x524b4344),'layout':(0x400,0x524b4c59)}

class FullDdrRawTransport(DualDdrRawTransport):
    def __init__(self,host='localhost',port=3721,timeout=30.0,*,frequency_hz=MAX_TCK_HZ,
                 link=None,clock=time.monotonic,sleep=time.sleep):
        if link is None:raise ValueError('An explicit already-audited raw link is required')
        self.reset_receipts=[]
        startup=_Deadline(_positive_seconds(timeout),clock)
        super().__init__(host,port,timeout,frequency_hz=frequency_hz,link=link,clock=clock,sleep=sleep)
        try:
            self._check_identity('layout',startup)
            if tuple(self._command(1,a,deadline=startup) for a in (0x500,0x504,0x518))!=(0x524b5253,0x10000,0x10004):
                raise ProtocolError('Unsupported compute-reset identity/ABI/capability')
        except BaseException:
            self._failed=True;self.close();raise

    def _check_identity(self,profile,deadline):
        base,identity=PROFILES[profile]
        if (self._command(1,base,deadline=deadline),self._command(1,base+4,deadline=deadline))!=(identity,ABI_VERSION):
            raise ProtocolError('Unsupported full-DDR raw namespace identity/ABI')

    def _all_idle(self,deadline):
        for base,unused_identity in PROFILES.values():
            if self._command(1,base+8,deadline=deadline)!=0x10:
                raise DeviceBusy('All job namespaces must be idle, unstaged and memory-ready')

    def select_profile(self,profile):
        if type(profile) is not str or profile not in PROFILES:raise ValueError('Unsupported full-DDR raw namespace')
        with self._mutex:
            self._usable()
            if self._active_tag is not None or self._result is not None:
                raise DeviceBusy('Read and ACK the owned job before selecting a namespace')
            budget=_Deadline(self.timeout,self._clock)
            try:
                self._all_idle(budget);self._check_identity(profile,budget);self._profile=profile
            except BaseException:
                self._failed=True;raise

    def reg_read(self,offset,*,_deadline=None):
        _uint(offset,32,'register offset')
        if offset not in READ_REGISTERS:raise ValueError('Unsupported raw-job read register')
        return self._command(1,PROFILES[self._profile][0]+offset,deadline=_deadline)

    def reg_write(self,offset,value):
        _uint(offset,32,'register offset');_uint(value,32,'register value')
        if offset not in WRITE_REGISTERS or offset==0xc and value not in (1,2):
            raise ValueError('Unsupported raw-job write register/value')
        with self._mutex:
            self._usable()
            if offset!=0xc and (self._active_tag is not None or self._result is not None):
                raise DeviceBusy('An owned job retains its descriptor until successful ACK')
            self._command(2,PROFILES[self._profile][0]+offset,value)

    def compute_reset(self,*,timeout=None):
        with self._mutex:
            self._usable()
            if self._active_tag is not None or self._result is not None:
                raise DeviceBusy('Compute reset cannot cancel an owned job/result')
            seconds=self.timeout if timeout is None else _positive_seconds(timeout)
            try:
                budget=_Deadline(seconds,self._clock);self._all_idle(budget)
                # Namespace checks, actions and release share one absolute
                # budget and the same deadline object; no timeout is restarted.
                def read(address,*,deadline):return self._command(1,address,deadline=deadline)
                def write(address,value,*,deadline):self._command(2,address,value,deadline=deadline)
                receipt=perform_reset(read,write,timeout=seconds,clock=self._clock,_deadline=budget)
                self._all_idle(budget)
                self.reset_receipts.append(receipt)
                return receipt
            except BaseException:
                self._failed=True;raise
