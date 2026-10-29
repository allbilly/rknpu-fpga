"""Explicit full-DDR framework profile; all data movement executes as raw jobs.

The original renderer, CMAC body emitter, final writer and submit function are
unchanged. This module adds static-gather command dispatch and an actual reset
service to the existing byte-only BO owner. No hardware connects on import.
"""
import ctypes
import struct
import time

from tools.backend import runtime as base
from tools.backend.layout import from_backend, StaticGather


def make_device_class(transport_factory, backend_path=None):
    # Reuse the established ownership, allocator, pin and EW admission contracts.
    Parent = base.make_device_class(transport_factory, backend_path, transport_profile='ew_ddr')
    rt, rr, td, receipt = base._load_backend(backend_path)
    rk = rt.rk

    def is_cmac(image):
        return any(type(op) is rr.RKCMAC for op in image.program)

    def argument(arg):
        base.require(type(arg) is rr.RKArg and type(arg.kind) is rr.RKBufferKind,
                     'Invalid CMAC/layout argument')
        base.integer(arg.index, 0, base.CAPACITY//2, 'argument index')
        base.integer(arg.addend, 0, base.CAPACITY, 'argument addend')
        base.require(arg.addend % 2 == 0, 'Unaligned halfword argument')

    def validate(image):
        base.require(type(image) is rr.RKImage and type(image.scratch) is tuple and
                     type(image.program) is tuple and image.program, 'Expected immutable RKImage')
        for size in image.scratch:
            base.integer(size, 1, base.CAPACITY, 'scratch size')
        base.require(sum(base.rounded(n) for n in image.scratch) <= base.CAPACITY,
                     'Scratch exceeds aperture')
        if not is_cmac(image):
            base.validate_image(image, rr)
            return
        for op in image.program:
            if type(op) is rr.RKGather:
                argument(op.src); argument(op.dst)
                base.require(op.index is None and type(op.values) is tuple and not op.values and
                             op.partial is False and type(op.itemsize) is int and op.itemsize == 2 and
                             type(op.index_itemsize) is int and op.index_itemsize == 4 and
                             type(op.dst_stride) is int and op.dst_stride == 1 and
                             type(op.fill_bits) is int and op.fill_bits == 0,
                             'Unsupported CMAC hardware gather profile')
                base.integer(op.count, 1, base.CAPACITY//4, 'layout count')
                # Validate immutable metadata without observing BO contents.
                StaticGather(op.count, op.base, op.axes, op.offsets).indices(base.CAPACITY//2)
            elif type(op) is rr.RKCMAC:
                for arg in (op.dst, op.lhs, op.rhs):
                    argument(arg)
                    base.require(arg.addend % 16 == 0, 'Unaligned CMAC address')
                for value in (op.m, op.n, op.k):
                    base.integer(value, 1, 65535, 'CMAC dimension')
                base.require(op.out_fp16 is True and op.relu is False,
                             'Only FP16 CMAC without activation is admitted')
            else:
                raise base.UnsupportedProfile('Mixed CMAC/EW or unknown operation class is unsupported')
            for arg in ((op.src, op.dst) if type(op) is rr.RKGather else (op.dst, op.lhs, op.rhs)):
                if arg.kind is rr.RKBufferKind.SCRATCH:
                    base.require(arg.index < len(image.scratch), 'Undeclared scratch slot')

    class FullDevice(Parent):
        def __init__(self, device=base.NAME):
            super().__init__(device)
            try:
                base.require(callable(getattr(self.transport, 'select_profile', None)) and
                             callable(getattr(self.transport, 'compute_reset', None)),
                             'Explicit layout/CMAC/reset transport is required')
                self.transport.select_profile('ew')
                self.runtime_t = FullProgram
                self._raw_kind = 'ew'
                self.layout_records, self.reset_records = [], []
                # The original device constructor resets before admitting work.
                # An idle bank alone does not establish a clean compute context.
                self.reset_npu()
            except BaseException:
                self.finalize()
                raise

        def _complete_raw(self, kind, address, amount, tasks, record):
            """Retire one raw job and copy every owned BO before acknowledging it."""
            try:
                timeout=self._submit_timeout()/1000
                for item in self._owned.values():
                    if not item.initialized:
                        self._upload(item)
                self.transport.select_profile(kind)
                self._tag = self._tag % 0xffffffff + 1
                record.update(status='SUBMITTING', profile=kind, address=address,
                              amount=amount, tag=self._tag, task_count=tasks, before=self._regions())
                self.transport.submit(address, amount, self._tag)
                result = self.transport.poll_result(timeout=timeout)
                base.require(all(type(getattr(result, field)) is int and
                                 0 <= getattr(result, field) <= 0xffffffff
                                 for field in ('tag','completed_tasks','error_code','status')) and
                             result.status & 4 and not result.status & (2|8|32|64) and
                             not result.status & ~0x77f and result.tag == self._tag and
                             result.completed_tasks == tasks and result.error_code == 0,
                             'Malformed or failed raw hardware result')
                for item in self._owned.values():
                    self._download(item)
                record.update(after=self._regions(), result=dict(tag=result.tag,
                    completed_tasks=result.completed_tasks,error_code=result.error_code,status=result.status))
                self.transport.ack_success()
                record['status'] = 'PASS'
                self._npu_clean = False
            except BaseException as error:
                record.update(status='FAIL', error=str(error))
                self._poisoned = True
                raise

        def ioctl(self, request, payload):
            if self._raw_kind == 'ew':
                self.transport.select_profile('ew')
                return super().ioctl(request, payload)
            with self._lock:
                self._check_healthy()
                base.require(self._raw_kind == 'cmac' and type(payload) is rk.struct_rknpu_submit and
                             request == (3<<30)|(ctypes.sizeof(rk.struct_rknpu_submit)<<16)|(ord('d')<<8)|0x41,
                             'Unsupported final CMAC submit ioctl')
                expected = dict(flags=5,timeout=self._submit_timeout(),task_start=0,task_number=1,
                    task_counter=0,priority=0,regcfg_obj_addr=0,task_base_addr=0,user_data=0,core_mask=1,fence_fd=-1)
                base.require(all(getattr(payload,k)==v for k,v in expected.items()) and
                             [(s.task_start,s.task_number) for s in payload.subcore_task] ==
                             [(0,1),(0,0),(0,0),(0,0),(0,0)], 'Unsupported final CMAC submit fields')
                task, cmd = self._buffers.get('task'), self._buffers.get('cmd')
                base.require(task is not None and cmd is not None, 'Missing original final encoder BOs')
                to, co = self._allocation(task), self._allocation(cmd)
                base.require(payload.task_obj_addr == task.meta.obj_addr and
                             to.flags == rk.RKNPU_MEM_KERNEL_MAPPING and co.flags == 0 and
                             task.size >= ctypes.sizeof(rk.struct_rknpu_task), 'Unowned final task BO')
                descriptor = rk.struct_rknpu_task.from_address(task.va_addr)
                fields = {name:int(getattr(descriptor,name)) for name,_ in descriptor._fields_}
                base.require(all(fields[k]==v for k,v in dict(flags=0,op_idx=0,enable_mask=0xd,
                    int_mask=0x300,int_clear=0x1ffff,int_status=0,regcfg_amount=45,regcfg_offset=0,
                    regcmd_addr=co.address).items()), 'Unsupported final CMAC task descriptor')
                base.require(cmd.size >= 400+base.PAGE and
                             ctypes.string_at(cmd.va_addr+392,8+base.PAGE)==bytes(8+base.PAGE),
                             'Missing original CMAC alignment and zero guard page')
                words = struct.unpack('<49Q',ctypes.string_at(cmd.va_addr,392))
                base.require(words[-4:]==(0x0001000000000000,0x0101000000000014,
                             0x0041000000000000,0x00810000000d0008), 'Changed original CMAC PC tail')
                base.require(tuple(words[:45]) == self._expected_cmac_body,
                             'Final CMAC command body differs from the original encoder')
                record = dict(tasks=[fields],task_bytes=bytes(descriptor),command_bytes=[struct.pack('<49Q',*words)],
                              payload=expected)
                self.records.append(record)
                self._complete_raw('cmac',co.address,45,1,record)
                return 0

        def reset_npu(self):
            with self._lock:
                self._check_healthy()
                try:
                    # No BO upload/download: the original writer has already
                    # materialized its next command in the CPU shadow here.
                    result = self.transport.compute_reset(timeout=self._submit_timeout()/1000)
                    self.reset_records.append(result)
                    self._native_int16,self._npu_clean = False,True
                except BaseException:
                    self._poisoned = True
                    raise

    # Retain the original Rockchip program implementation for EW-only images;
    # every data-dependent gather in a CMAC image takes the raw hardware path.
    class FullProgram(rt.RockchipProgram):
        def __init__(self, dev, obj):
            dev._check_healthy()
            dev.backend_receipt = base.verify_backend(receipt['root'])
            image = base._image(obj.lib,rr)
            validate(image)
            if not is_cmac(image):
                # Admission is identical to the existing EW adapter. Its
                # original inherited __call__ remains safe for literal gathers.
                base.validate_image(image,rr)
            super().__init__(dev,obj)
            base.require(self.image==image, 'Compiler image changed during admission')
            self._admitted_image,self._admitted_offsets = image,self._scratch_offsets
            self._admitted_modes = frozenset(self._ew_modes)
            self._layout_buffers = {}

        def __call__(self,*bufs,global_size=(1,1,1),local_size=(1,1,1),vals=(),wait=False,**kwargs):
            def default_grid(value):
                return value is None or type(value) is tuple and value==(1,1,1) and all(type(x) is int for x in value)
            base.require(default_grid(global_size) and default_grid(local_size) and type(vals) is tuple and not vals and
                         type(wait) is bool and set(kwargs)<={'timeout'} and kwargs.get('timeout') is None,
                         'Unsupported execution options')
            with self.dev._lock:
                self.dev._check_healthy()
                self.dev.backend_receipt = base.verify_backend(receipt['root'])
                base.require(self.image==self._admitted_image and self._scratch_offsets==self._admitted_offsets and
                             frozenset(self._ew_modes)==self._admitted_modes, 'Admitted program state changed')
                validate(self.image)
                self.dev._submit_timeout()
                if not is_cmac(self.image):
                    self.dev._validate_bindings(self.image,bufs)
                    self.dev._raw_kind='ew'
                    return super().__call__(*bufs,global_size=global_size,local_size=local_size,vals=vals,wait=wait)
                arena = self.dev._ensure_buffer('scratch',self._scratch_offsets[-1],self._scratch_offsets[-1]) if self._scratch_offsets[-1] else None
                scratch = tuple(arena.offset(offset,size) for offset,size in zip(self._scratch_offsets,self.image.scratch)) if arena else ()
                def binding(arg):
                    storage = bufs if arg.kind is rr.RKBufferKind.ARG else scratch
                    base.require(arg.index<len(storage), 'Unbound image argument')
                    buf=storage[arg.index];owner=self.dev._allocation(buf)
                    base.require(all(buf.base is not internal.base for internal in self.dev._buffers.values())
                                 if arg.kind is rr.RKBufferKind.ARG else True, 'Internal BO passed as argument')
                    base.require(arg.addend<buf.size, 'Argument addend escapes logical BO')
                    return buf,owner,owner.address+buf.va_addr-owner.buffer.va_addr+arg.addend,buf.size-arg.addend
                def address(arg):return binding(arg)[2]
                # Preflight spans, static metadata and allocation before any job.
                layouts={}
                owned_before=set(self.dev._owned)
                cached_before=set(self._layout_buffers)
                try:
                    for index,op in enumerate(self.image.program):
                        if type(op) is rr.RKGather:
                            sb,so,sa,ss=binding(op.src);db,do,da,ds=binding(op.dst)
                            pair=self._layout_buffers.get(index)
                            if pair is None:
                                pair=(self.dev._gpu_alloc(op.count*4),self.dev._gpu_alloc(72))
                                self._layout_buffers[index]=pair
                            table,command=pair
                            encoded=from_backend(op,rr,source_address=sa,destination_address=da,source_bytes=ss,
                                destination_bytes=ds,table_address=table.meta.dma_addr,command_address=command.meta.dma_addr)
                            layouts[index]=(encoded,table,command)
                        else:
                            ai,ao,unused=rr._cmac_layout(op.n,op.k)
                            spans=[binding(a) for a in (op.lhs,op.rhs,op.dst)]
                            lengths=(op.m*ai*2,ao*ai*2,op.m*ao*4)
                            for (_,owner,start,size),length in zip(spans,lengths):
                                base.require(size>=length and start%16==0, 'CMAC physical span escapes logical BO')
                            for i,(_,owner,start,size) in enumerate(spans):
                                for j in range(i):
                                    other=spans[j][2]
                                    base.require(start+lengths[i]<=other or other+lengths[j]<=start,
                                                 'Overlapping CMAC physical inputs/output')
                except BaseException:
                    # Preflight has not submitted a job. Return every newly
                    # allocated metadata BO, including a half-created pair.
                    for index in set(self._layout_buffers)-cached_before:
                        del self._layout_buffers[index]
                    for key in set(self.dev._owned)-owned_before:
                        self.dev._gpu_free(self.dev._owned[key].buffer)
                    raise
                started=time.perf_counter()
                try:
                    for item in self.dev._owned.values():
                        if not item.initialized:self.dev._upload(item)
                    for index,op in enumerate(self.image.program):
                        if type(op) is rr.RKGather:
                            encoded,table,command=layouts[index]
                            for buf,raw in ((table,encoded.index_bytes),(command,encoded.command_bytes)):
                                ctypes.memmove(buf.va_addr,raw,len(raw))
                                self.dev._upload(self.dev._allocation(buf))
                            record=dict(index=index,words=encoded.words,index_bytes=encoded.index_bytes)
                            self.dev.layout_records.append(record)
                            self.dev._complete_raw('layout',command.meta.dma_addr,9,1,record)
                        else:
                            self.dev._raw_kind='cmac'
                            self.dev._expected_cmac_body=rr.emit_cmac_stage(op,address)
                            # These inherited methods are the original pinned
                            # encoder/writer/submit, including both reset calls.
                            self._submit_bodies((self.dev._expected_cmac_body,),standalone=True,cmac=True)
                except BaseException:
                    self.dev._poisoned=True
                    raise
                return time.perf_counter()-started if wait else None

    FullDevice.__name__='RKNPUFPGADevice'
    FullDevice.backend_pin=receipt
    return FullDevice


def install(transport_factory, backend_path=None):
    """Register this explicit candidate once in a fresh process."""
    with base._OWNER_LOCK:
        base.require(not base._REGISTRATION_USED and base.MODULE not in base.sys.modules,
                     'RKNPUFPGA registration already exists; use a fresh process')
        device_class=make_device_class(transport_factory,backend_path)
        registry=base.importlib.import_module('tinygrad.device').Device
        base.require(base.NAME not in registry._devices and
                     not any(d.split(':')[0]==base.NAME for d in registry._opened_devices),
                     'RKNPUFPGA device binding already exists')
        try:registry.get_class(base.NAME)
        except ModuleNotFoundError as error:
            base.require(error.name==base.MODULE,'Unexpected runtime import failure')
        else:raise base.UnsupportedProfile('RKNPUFPGA class was already cached')
        module=base.ModuleType(base.MODULE)
        module.RKNPUFPGADevice=device_class
        base.sys.modules[base.MODULE]=module
        base._REGISTRATION_USED=True
        return base.Registration(module,device_class,registry)
