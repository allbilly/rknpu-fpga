#!/usr/bin/env python3
"""Prepare all TinyStories raw programs with the original backend final writer.

No Tensor execution, runtime gather, device registration or hardware access.
The catalog contains complete physical BO bytes, not tensor instructions for
an FPGA service. Only the later raw descriptor/byte transport may execute it.
"""
from pathlib import Path
import argparse
import base64
import ctypes
import hashlib
import json
import pickle
import struct
import sys
from types import SimpleNamespace
from unittest.mock import patch
import zlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.dont_write_bytecode=True
from tools.backend.runtime import verify_backend
from tools.tinystories.prepare import verify, require


def blob(raw):
    return dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                zlib_base64=base64.b64encode(zlib.compress(raw)).decode())


def unpack(record):
    raw=zlib.decompress(base64.b64decode(record['zlib_base64'],validate=True))
    require(len(raw)==record['size'] and hashlib.sha256(raw).hexdigest()==record['sha256'],'Changed complete BO')
    return raw


def forbidden(*args,**kwargs):
    raise RuntimeError('Hardware access or runtime gather during raw-program preparation')


def prepare(package,backend_path,out):
    package,out=Path(package).resolve(),Path(out).resolve()
    require(not sys.flags.optimize,'Optimized Python is unsupported for original encoder assertions')
    source=verify(package);backend=verify_backend(backend_path)
    require(not out.exists(),'Fresh raw-program catalog required')
    sys.path.insert(0,backend['root'])
    from tinygrad.renderer.rockchip import RKArg,RKBufferKind,RKCMAC,RKEWOp,RKImage,emit_cmac_stage,emit_ew_stage
    from tinygrad.runtime import ops_rockchip as runtime
    from tinygrad.runtime.autogen import rockchip as rk
    from tinygrad.runtime.support.hcq import HCQBuffer,MMIOInterface
    class Capture:
        def __init__(self,kind):
            self.kind=kind;self.storage=[];self.buffers={};self.captures=[]
            self.fd_ctl=self;self._npu_clean=True;self._poisoned=False
            self.submit_count=self.task_count=self.timeout_retries=self.resets=0
        def allocate(self,address,size):
            storage=ctypes.create_string_buffer(size);self.storage.append(storage)
            va=ctypes.addressof(storage)
            result=HCQBuffer(va,size,meta=SimpleNamespace(dma_addr=address,obj_addr=va,size=size),view=MMIOInterface(va,size))
            self.buffers[address]=result;return result
        def _replace_submit_buffers(self,cmd_size,task_size):
            return self.allocate(0x100e0000,max(cmd_size,65536)),self.allocate(0x100f0000,max(task_size,4096))
        def _sync_buffers(self,bufs,flags):
            require(all(b.base in self.buffers.values() for b in bufs),'Unowned final-writer buffer')
        def reset_npu(self):
            self.resets+=1;self._npu_clean=True
        def ioctl(self,request,payload):
            require(isinstance(payload,rk.struct_rknpu_submit) and payload.core_mask==1 and payload.task_start==0,
                    'Unexpected final submission')
            command,task=self.buffers[0x100e0000],self.buffers[0x100f0000]
            require(payload.task_obj_addr==task.va_addr,'Changed task ownership')
            descriptors=(rk.struct_rknpu_task*payload.task_number).from_address(task.va_addr)
            rows=[{name:int(getattr(d,name)) for name,_ in d._fields_} for d in descriptors]
            for row in rows:
                require(all(row[name]==value for name,value in dict(flags=0,op_idx=0 if self.kind=='cmac' else 4,
                    enable_mask=0xd if self.kind=='cmac' else 0x18,int_mask=0x300,int_clear=0x1ffff,
                    int_status=0,regcfg_offset=0).items()),'Unmodeled raw task field')
            data=ctypes.string_at(command.va_addr,command.size)
            if self.kind=='cmac':
                require(len(rows)==1 and rows[0]['regcfg_amount']==45,'CMAC body must contain45words')
                words=struct.unpack_from('<49Q',data)
                require(words[45:]==(0x0001000000000000,0x0101000000000014,0x0041000000000000,0x00810000000d0008),
                        'Changed original CMAC tail')
            else:
                require(len(rows)==2,'Compaction must retain two EW tasks')
            self.captures.append(dict(profile=self.kind,address=rows[0]['regcmd_addr'],amount=rows[0]['regcfg_amount'],
                task_count=len(rows),tasks=rows,command_bo=blob(data),task_bo=blob(ctypes.string_at(task.va_addr,task.size)),
                submit_capture=blob(bytes(payload))))
            return 0
    out.mkdir(parents=True)
    records=[]
    buffers=source['candidate_buffers']
    arg_dst,arg_a,arg_b=(RKArg(RKBufferKind.ARG,i) for i in range(3))
    with patch.object(runtime.RockchipDevice,'__init__',forbidden),patch.object(runtime,'FileIOInterface',forbidden),\
         patch.object(runtime,'_apply_gathers',forbidden):
        for tile in source['tiles']:
            cmac=RKCMAC(arg_dst,arg_a,arg_b,1,32,tile['logical_inputs'])
            mapping={arg_dst:buffers['native_output']['address'],arg_a:buffers['input']['address'],arg_b:tile['address']}
            body=emit_cmac_stage(cmac,mapping.__getitem__)
            require(len(body)==45,'Changed raw CMAC emitter body')
            device=Capture('cmac')
            program=runtime.RockchipProgram(device,SimpleNamespace(name='prepared_tiny_cmac',lib=zlib.compress(pickle.dumps(RKImage(program=(cmac,))))))
            program._submit_bodies((body,),standalone=True,cmac=True)
            require(len(device.captures)==1 and device.resets==1,'Original standalone rearm callback lost')
            cmac_record=device.captures[0]
            require(struct.unpack_from('<45Q',unpack(cmac_record['command_bo']))==body,'CMAC words rewritten')
            ew=Capture('ew');bodies=[]
            for native,linear in ((0,tile['first_output']),(32,tile['first_output']+16)):
                op=RKEWOp(arg_dst,arg_a,arg_b,16,0x108003c4)
                mapping={arg_dst:buffers['linear_output']['address']+2*linear,
                         arg_a:buffers['native_output']['address']+2*native,arg_b:buffers['unity']['address']}
                bodies.append(emit_ew_stage(op,mapping.__getitem__))
            program=runtime.RockchipProgram(ew,SimpleNamespace(name='prepared_tiny_compaction',lib=zlib.compress(pickle.dumps(RKImage()))))
            program._submit_bodies(bodies)
            require(len(ew.captures)==1 and ew.resets==0,'Changed compaction grouping/reset contract')
            records.append(dict(projection=tile['projection'],first_output=tile['first_output'],
                logical_inputs=tile['logical_inputs'],logical_outputs=tile['logical_outputs'],
                cmac=cmac_record,compaction=ew.captures[0]))
    require(len(records)==116 and sum(r['cmac']['task_count']+r['compaction']['task_count'] for r in records)==348,
            'Incomplete prepared projection program set')
    require(verify_backend(backend_path)['pinned_files']==backend['pinned_files'],'Backend changed during generation')
    verify(package)
    report=dict(status='PREPARED_ALL_TINYSTORIES_RAW_PROGRAMS_ONLY',programs=records,backend=backend,
        source_model_sha256=source['model_sha256'],source_package_report_sha256=hashlib.sha256((package/'report.json').read_bytes()).hexdigest(),
        projections=36,tiles=116,raw_submissions_per_forward=232,raw_tasks_per_forward=348,
        success_rearm_callbacks_per_forward=116,hardware_accessed=False,tensor_framework_integration=False,
        scope='Original emitter/final-writer raw CMAC and EW complete BO catalog; not execution or a model inference result')
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--backend',type=Path,default=Path.home()/'tinygrad')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();r=prepare(args.package,args.backend,args.out)
    print(r['status'],r['tiles'],r['raw_tasks_per_forward'])


if __name__=='__main__':main()
