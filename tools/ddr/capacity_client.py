"""RKMT management over an existing audited raw USER2 owner.

No connection or hardware access on import/construction. The caller owns the
image/target review and board lease. No programming, reset, retries, tensor
execution, CPU fallback or data/layout repair is provided here.
"""
from dataclasses import dataclass
from tools.host.transport import ProtocolError, DeviceBusy, _Deadline, _uint, _positive_seconds

ID=0x524b4d54
ABI=0x00010000
TERMINAL_SUCCESS=0x68

@dataclass(frozen=True)
class CapacityMetadata:
    base:int
    size:int
    line_bytes:int=64
    trials:int=2

    @property
    def full_window(self):return self.base==0 and self.size==(1<<31)

    @property
    def expected_operations_per_direction(self):return self.trials*(self.size//self.line_bytes)

class CapacityFault(RuntimeError):
    def __init__(self,snapshot):
        self.snapshot=snapshot
        super().__init__(f"RKMT fault status={snapshot['status']:#x} codes={snapshot['fault_codes']:#x}; whole-domain recovery required")

class CapacityClient:
    def __init__(self,owner):
        self.owner=owner
        self.started=False
        self.last_snapshot=None

    def _read(self,address,deadline):
        value=self.owner._command(1,address,deadline=deadline)
        _uint(value,32,'diagnostic CSR value')
        return value

    def _metadata(self,deadline,require_full_window):
        if (self._read(0x200,deadline),self._read(0x204,deadline))!=(ID,ABI):
            raise ProtocolError('Image lacks the exact RKMT identity/ABI')
        size=self._read(0x214,deadline);base=self._read(0x218,deadline)
        if self._read(0x21c,deadline)!=0x00020040:
            raise ProtocolError('Unsupported diagnostic line/trial contract')
        if base%64 or size<64 or size%64 or base+size>1<<31:
            raise ProtocolError('Unsupported diagnostic address window')
        metadata=CapacityMetadata(base,size)
        if require_full_window and not metadata.full_window:
            raise ProtocolError('Physical capacity run requires the complete two-GiB image window')
        return metadata

    def _snapshot(self,deadline):
        result={'status':self._read(0x208,deadline),'completed_writes':self._read(0x220,deadline),
            'completed_reads':self._read(0x224,deadline),'fault_codes':self._read(0x228,deadline),
            'fault_sources':self._read(0x22c,deadline)}
        if result['status']&~0x7f or result['fault_sources']&~7:
            raise ProtocolError('Unmodeled RKMT status/source bits')
        if result['status']&0x10 or result['fault_codes'] or result['fault_sources']:
            result['mismatch_address']=self._read(0x230,deadline)
            result['mismatch_expected_words']=[self._read(0x240+4*i,deadline) for i in range(16)]
            result['mismatch_actual_words']=[self._read(0x280+4*i,deadline) for i in range(16)]
        self.last_snapshot=result
        return result

    def run(self,seed=0x3588c350,*,timeout=600.0,poll_seconds=0.25,require_full_window=True,on_progress=None):
        _uint(seed,32,'diagnostic seed');_positive_seconds(timeout);_positive_seconds(poll_seconds)
        if type(require_full_window) is not bool:raise ValueError('Explicit boolean window policy required')
        if on_progress is not None and not callable(on_progress):raise ValueError('Progress callback must be callable')
        owner=self.owner
        with owner._mutex:
            owner._usable()
            if self.started:raise DeviceBusy('One destructive capacity start per owner/reset epoch')
            if owner._active_tag is not None or owner._result is not None:
                raise DeviceBusy('Complete raw-job readback and ACK before the memory sweep')
            deadline=_Deadline(timeout,owner._clock)
            try:
                metadata=self._metadata(deadline,require_full_window)
                # Both original job namespaces must be healthy, unstaged and idle.
                if self._read(0x008,deadline)!=0x10 or self._read(0x108,deadline)!=0x10:
                    raise DeviceBusy('Both raw job namespaces must be initialized and idle')
                if self._read(0x208,deadline)!=1:
                    raise DeviceBusy('Diagnostic owner is not ready for a fresh start')
                owner._command(2,0x210,seed,deadline=deadline)
                if self._read(0x210,deadline)!=seed:raise ProtocolError('Seed readback mismatch')
                # Mark before submission: an uncertain response never permits a retry.
                self.started=True
                owner._command(2,0x20c,1,deadline=deadline)
                previous=(0,0)
                while True:
                    deadline.remaining()
                    result=self._snapshot(deadline)
                    counters=(result['completed_writes'],result['completed_reads'])
                    expected=metadata.expected_operations_per_direction
                    if any(now<old or now>expected for now,old in zip(counters,previous)):
                        raise ProtocolError('Diagnostic counters regressed or exceeded the source-bound scope')
                    previous=counters
                    if result['status']&0x10 or result['fault_codes'] or result['fault_sources']:
                        raise CapacityFault(result)
                    if on_progress is not None:on_progress(dict(result))
                    if result['status']&8:
                        if result['status']!=TERMINAL_SUCCESS or counters!=(expected,expected):
                            raise ProtocolError('Diagnostic completion lacks exact ownership/counts')
                        if self._read(0x208,deadline)!=TERMINAL_SUCCESS:
                            raise ProtocolError('Health/ownership changed during final receipt')
                        return {**result,'device_status':result['status'],
                            'status':'PASS_DEVICE_BIST_REQUIRES_IMAGE_AND_WIRE_AUDIT','seed':seed,'base':metadata.base,'size':metadata.size,
                            'full_window_executed':metadata.full_window,'physical_capacity_qualified':False,
                            'cpu_fallback':False,'reset_or_programming_performed':False}
                    if not result['status']&0x40:
                        raise ProtocolError('Accepted start lost its reset-epoch ownership')
                    owner._sleep(min(poll_seconds,deadline.remaining()))
            except DeviceBusy:
                # Pre-start software admission failures do not poison a healthy owner.
                if self.started:owner._failed=True
                raise
            except BaseException:
                owner._failed=True
                raise
