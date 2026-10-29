"""Explicit raw-program TinyStories dense runner; never a software fallback.

The caller supplies an exclusively owned, image-audited DualRawTransport.
This module neither opens a connection nor programs/resets an FPGA. Learned
weights are static prepared bytes; runtime output compaction executes as the
original raw EW chain. The arithmetic oracle is deliberately not imported.
"""
from pathlib import Path
import base64
import hashlib
import json
import math
import struct
import zlib

from tools.tinystories.prepare import require, verify


def raw(record):
    data=zlib.decompress(base64.b64decode(record['zlib_base64'],validate=True))
    require(len(data)==record['size'] and hashlib.sha256(data).hexdigest()==record['sha256'],'Changed complete program BO')
    return data


class RawDenseDevice:
    def __init__(self,package,catalog,expected_catalog_sha256,transport,*,observer=None):
        self.package=Path(package).resolve();self.prepared=verify(self.package)
        path=Path(catalog).resolve()
        require(hashlib.sha256(path.read_bytes()).hexdigest()==expected_catalog_sha256,'Raw catalog differs from audited input')
        source=json.loads(path.read_text())
        require(source['status']=='PREPARED_ALL_TINYSTORIES_RAW_PROGRAMS_ONLY' and source['hardware_accessed'] is False
                and source['source_model_sha256']==self.prepared['model_sha256'],'Wrong original program catalog')
        require(source['source_package_report_sha256']==hashlib.sha256((self.package/'report.json').read_bytes()).hexdigest(),
                'Catalog/model preparation disagreement')
        self.projections={p['name']:p for p in self.prepared['projections']}
        self.programs={}
        for program in source['programs']:
            key=(program['projection'],program['first_output'])
            require(key not in self.programs,'Duplicate raw model tile')
            for kind in ('cmac','compaction'):
                job=program[kind]
                require(job['profile']==('cmac' if kind=='cmac' else 'ew') and job['address']==0x100e0000,
                        'Changed raw job namespace/address')
                require(job['task_count']==(1 if kind=='cmac' else 2),'Changed raw task count')
                require(len(job['tasks'])==job['task_count'] and job['amount']==job['tasks'][0]['regcfg_amount']
                        and job['address']==job['tasks'][0]['regcmd_addr'],'Descriptor/launch disagreement')
                for task in job['tasks']:
                    require(all(task[k]==v for k,v in dict(flags=0,op_idx=0 if kind=='cmac' else 4,
                        enable_mask=0xd if kind=='cmac' else 0x18,int_mask=0x300,int_clear=0x1ffff,
                        int_status=0,regcfg_offset=0).items()),'Unmodeled raw descriptor field')
                raw(job['command_bo']);raw(job['task_bo'])
            self.programs[key]=program
        require(set(self.programs)=={(t['projection'],t['first_output']) for t in self.prepared['tiles']}
                and len(self.programs)==116,'Missing learned projection programs')
        self.transport=transport;self.initialized=False;self.poisoned=False;self.tag=0;self.records=[];self.calls=[]
        self.observer=observer
        self.buffers=self.prepared['candidate_buffers']
        self.shadow={name:bytearray(item['bytes']) for name,item in self.buffers.items()}
        self.shadow['native_output'][:]=b'\x5a\xa5'*(len(self.shadow['native_output'])//2)
        self.shadow['linear_output'][:]=b'\x5a\xa5'*(len(self.shadow['linear_output'])//2)
        self.shadow['unity'][:32]=struct.pack('<16H',*[0x3c00]*16)
        for tile in self.prepared['tiles']:
            offset=tile['address']-self.buffers['weights']['address']
            self.shadow['weights'][offset:offset+tile['bytes']]=(self.package/tile['file']).read_bytes()

    def _healthy(self):
        if self.poisoned:raise RuntimeError('Raw model device poisoned; audited recovery required')

    def initialize(self):
        self._healthy()
        require(not self.initialized,'Do not implicitly reinitialize an active model')
        try:
            self.transport.select_profile('ew')
            require(self.transport.reg_read(8)==0x10,'Model initialization needs an idle endpoint')
            for name,data in self.shadow.items():
                address=self.buffers[name]['address']
                self.transport.mem_write(address,data)
                require(self.transport.mem_read(address,len(data))==data,'Initial complete BO readback differs')
            self.initialized=True
        except BaseException:
            self.poisoned=True
            raise

    def _replace(self,name,data):
        require(len(data)==len(self.shadow[name]),'Physical BO extent changed')
        old=self.shadow[name];address=self.buffers[name]['address']
        # Bytes not transferred retain their verified value: the only admitted
        # raw programs write native/linear output, never constants/CMD/tasks.
        # Changed lines are ordinary byte copies of the complete original BO.
        for offset in range(0,len(data),64):
            chunk=bytes(data[offset:offset+64])
            if chunk!=old[offset:offset+64]:
                self.transport.mem_write(address+offset,chunk)
                require(self.transport.mem_read(address+offset,64)==chunk,'Changed BO line did not reach RAM')
        self.shadow[name][:]=data

    def _load(self,job):
        for name,key in (('command','command_bo'),('tasks','task_bo')):
            payload=raw(job[key]);require(len(payload)<=len(self.shadow[name]),'Prepared program exceeds allocation')
            physical=bytearray(len(self.shadow[name]));physical[:len(payload)]=payload
            self._replace(name,physical)

    def _execute(self,job,name,allowed):
        self.transport.select_profile(job['profile'])
        self._load(job)
        self.tag=self.tag%0xffffffff+1
        self.transport.submit(job['address'],job['amount'],self.tag)
        result=self.transport.poll_result(timeout=30)
        require(result.tag==self.tag and result.completed_tasks==job['task_count'] and result.error_code==0,
                'Raw model job completion differs from original descriptors')
        before=self.shadow[name];address=self.buffers[name]['address']
        actual=self.transport.mem_read(address,len(before))
        require(len(actual)==len(before),'Short complete output BO')
        for index,(old,new) in enumerate(zip(before,actual)):
            require(old==new or any(start<=index<end for start,end in allowed),'Output escaped its original destination')
        # Validation only; no result is gathered or repaired on the host.
        for start,end in allowed:
            require(all(word&0x7c00!=0x7c00 for (word,) in struct.iter_unpack('<H',actual[start:end])),
                    'Nonfinite model result; no CPU repair/fallback')
        self.shadow[name][:]=actual
        event=dict(profile=job['profile'],tag=self.tag,tasks=result.completed_tasks,output=name,
            whole_bo_bytes=len(actual),output_sha256=hashlib.sha256(actual).hexdigest(),
            output_zlib_base64=base64.b64encode(zlib.compress(actual)).decode(),allowed_ranges=allowed)
        if self.observer is not None:self.observer(event)
        self.transport.ack_success()
        self.records.append(dict(event,ack_after_readback=True))

    def projection(self,name,values):
        self._healthy();require(self.initialized,'Explicit model initialization is required')
        require(name in self.projections,'Unknown learned projection')
        p=self.projections[name];require(len(values)==p['inputs'],'Projection input dimension changed')
        try:
            before_jobs=len(self.records)
            require(all(math.isfinite(float(v)) for v in values),'Nonfinite model input')
            try:data=struct.pack('<'+'e'*len(values),*values)
            except OverflowError as error:raise ValueError('Input overflows finite FP16; no scale fallback') from error
            require(all(word&0x7c00!=0x7c00 for (word,) in struct.iter_unpack('<H',data)),'Nonfinite FP16 input')
            physical=bytearray(len(self.shadow['input']));physical[:len(data)]=data
            self._replace('input',physical)
            self._replace('linear_output',b'\x5a\xa5'*(len(self.shadow['linear_output'])//2))
            for tile in [t for t in self.prepared['tiles'] if t['projection']==name]:
                program=self.programs[name,tile['first_output']]
                self._execute(program['cmac'],'native_output',[(0,32),(64,96)])
                begin=2*tile['first_output']
                self._execute(program['compaction'],'linear_output',[(begin,begin+64)])
            logical=p['outputs']*2;padded=((p['outputs']+31)//32*32)*2
            output=self.shadow['linear_output']
            require(not any(output[logical:padded]),'Nonzero padded model output')
            # The FPGA has already produced contiguous bytes. This is a prefix
            # read and FP16 value decode, not a CPU layout transformation.
            self.calls.append(dict(name=name,input_fp16_sha256=hashlib.sha256(data).hexdigest(),
                output_fp16_sha256=hashlib.sha256(output[:logical]).hexdigest(),
                raw_jobs=len(self.records)-before_jobs,first_job=before_jobs))
            return list(struct.unpack('<'+'e'*p['outputs'],output[:logical]))
        except BaseException:
            self.poisoned=True
            raise

    def close(self):
        self.transport.close()
