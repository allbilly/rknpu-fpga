#!/usr/bin/env python3
"""Real RK3588 NPU (mainline Rocket) FP16 ADD capture; no numpy, no FPGA."""
import ctypes, glob, hashlib, json, mmap, os, struct, sys, time
from fcntl import ioctl
DRM_COMMAND_BASE=0x40
class create_bo(ctypes.Structure):
    _fields_=[('size',ctypes.c_uint32),('handle',ctypes.c_uint32),('dma_address',ctypes.c_uint64),('offset',ctypes.c_uint64)]
class prep_bo_s(ctypes.Structure):
    _fields_=[('handle',ctypes.c_uint32),('reserved',ctypes.c_uint32),('timeout_ns',ctypes.c_int64)]
class fini_bo_s(ctypes.Structure):
    _fields_=[('handle',ctypes.c_uint32),('reserved',ctypes.c_uint32)]
class task_s(ctypes.Structure):
    _fields_=[('regcmd',ctypes.c_uint32),('regcmd_count',ctypes.c_uint32)]
class job_s(ctypes.Structure):
    _fields_=[('tasks',ctypes.c_uint64),('in_bo_handles',ctypes.c_uint64),('out_bo_handles',ctypes.c_uint64),
              ('task_count',ctypes.c_uint32),('task_struct_size',ctypes.c_uint32),
              ('in_bo_handle_count',ctypes.c_uint32),('out_bo_handle_count',ctypes.c_uint32)]
class submit_s(ctypes.Structure):
    _fields_=[('jobs',ctypes.c_uint64),('job_count',ctypes.c_uint32),('job_struct_size',ctypes.c_uint32),('reserved',ctypes.c_uint64)]
def iowr(t,nr,size): return (3<<30)|(ord(t)<<8)|nr|(size<<16)
def iow(t,nr,size): return (1<<30)|(ord(t)<<8)|nr|(size<<16)
CREATE=iowr('d',DRM_COMMAND_BASE+0,ctypes.sizeof(create_bo))
SUBMIT=iow('d',DRM_COMMAND_BASE+1,ctypes.sizeof(submit_s))
PREP=iow('d',DRM_COMMAND_BASE+2,ctypes.sizeof(prep_bo_s))
FINI=iow('d',DRM_COMMAND_BASE+3,ctypes.sizeof(fini_bo_s))
TARGET_DPU=0x1001; TARGET_RDMA=0x2001; TARGET_PC=0x0081
OP=os.environ.get('EW_OP','ADD').upper()
CFG={'ADD':0x108202c0,'SUB':0x108402c0,'MUL':0x108003c4,'NEG':0x108003c4,
     'MAX':0x108002c0}[OP]
def open_dev():
    for p in sorted(glob.glob('/dev/accel/accel*'))+sorted(glob.glob('/dev/dri/renderD*')):
        try: return os.open(p,os.O_RDWR),p
        except OSError: pass
    raise SystemExit('no Rocket device')
def alloc(fd,size):
    bo=create_bo(size=size); ioctl(fd,CREATE,bo)
    buf=mmap.mmap(fd,bo.size,mmap.MAP_SHARED,mmap.PROT_READ|mmap.PROT_WRITE,offset=bo.offset)
    return buf,bo
def prep(fd,bo):
    ioctl(fd,PREP,prep_bo_s(handle=bo.handle,timeout_ns=time.monotonic_ns()+6_000_000_000))
def fini(fd,bo): ioctl(fd,FINI,fini_bo_s(handle=bo.handle))
def submit(fd,regcmd_bo,count,in_bos,out_bos):
    tasks=(task_s*1)(task_s(regcmd=regcmd_bo.dma_address&0xffffffff,regcmd_count=count))
    ih=(ctypes.c_uint32*len(in_bos))(*(b.handle for b in in_bos)); oh=(ctypes.c_uint32*len(out_bos))(*(b.handle for b in out_bos))
    jobs=(job_s*1)(job_s(tasks=ctypes.addressof(tasks),in_bo_handles=ctypes.addressof(ih),out_bo_handles=ctypes.addressof(oh),
        task_count=1,task_struct_size=ctypes.sizeof(task_s),in_bo_handle_count=len(in_bos),out_bo_handle_count=len(out_bos)))
    s=submit_s(jobs=ctypes.addressof(jobs),job_count=1,job_struct_size=ctypes.sizeof(job_s))
    return ioctl(fd,SUBMIT,s)
def h16(x): return struct.unpack('<H',struct.pack('<e',float(x)))[0]
def f16(x): return struct.unpack('<e',struct.pack('<H',x))[0]
def main():
    fd,path=open_dev(); print('DEVICE',path)
    regcmd_map,regcmd_bo=alloc(fd,4096); a_map,a_bo=alloc(fd,4096); b_map,b_bo=alloc(fd,4096); o_map,o_bo=alloc(fd,4096)
    n=8; a=[1,2,3,4,5,6,7,8]
    b=([-1.0]*8 if OP=='NEG' else ([2.0]*8 if OP=='MAX' else [8,7,6,5,4,3,2,1]))
    dataout_width=(n+7)//8-1
    regs=[
      (TARGET_DPU<<48)|(0x0000000e<<16)|0x4004,
      (TARGET_DPU<<48)|(0x000001e5<<16)|0x400c,
      (TARGET_DPU<<48)|(0x48000002<<16)|0x4010,
      (TARGET_DPU<<48)|(dataout_width<<16)|0x4030,
      (TARGET_DPU<<48)|(0x00070007<<16)|0x403c,
      (TARGET_DPU<<48)|(CFG<<16)|0x4070,
      (TARGET_DPU<<48)|(0x00010001<<16)|0x4084,
      (TARGET_RDMA<<48)|(0x0000000e<<16)|0x5004,
      (TARGET_RDMA<<48)|(dataout_width<<16)|0x500c,
      (TARGET_RDMA<<48)|(0<<16)|0x5010,
      (TARGET_RDMA<<48)|(7<<16)|0x5014,
      (TARGET_RDMA<<48)|(0x40000008<<16)|0x5034,
      (TARGET_DPU<<48)|((o_bo.dma_address&0xffffffff)<<16)|0x4020,
      (TARGET_RDMA<<48)|((a_bo.dma_address&0xffffffff)<<16)|0x5018,
      (TARGET_RDMA<<48)|((b_bo.dma_address&0xffffffff)<<16)|0x5038,
      (TARGET_RDMA<<48)|(0x00017849<<16)|0x5044,
      (TARGET_PC<<48)|(0x00000018<<16)|0x0008,
    ]
    ctypes.memset(ctypes.addressof(ctypes.c_char.from_buffer(regcmd_map)),0,4096)
    q=(ctypes.c_uint64*len(regs)).from_buffer(regcmd_map); q[:]=regs
    ai=(ctypes.c_uint16*n).from_buffer(a_map); ai[:]=[h16(x) for x in a]
    bi=(ctypes.c_uint16*n).from_buffer(b_map); bi[:]=[h16(x) for x in b]
    oi=(ctypes.c_uint16*n).from_buffer(o_map); oi[:]=[0]*n
    for bo in (regcmd_bo,a_bo,b_bo,o_bo): prep(fd,bo)
    for bo in (regcmd_bo,a_bo,b_bo,o_bo): fini(fd,bo)
    ret=submit(fd,regcmd_bo,len(regs),(regcmd_bo,a_bo,b_bo),(o_bo,)); print('SUBMIT_RET',ret)
    prep(fd,o_bo)
    out=[oi[i] for i in range(n)]; out_f=[f16(x) for x in out]
    raw=bytes(o_map[:4096])
    print('DMA regcmd=%#x a=%#x b=%#x out=%#x'%(regcmd_bo.dma_address,a_bo.dma_address,b_bo.dma_address,o_bo.dma_address))
    print('A',a); print('B',b); print('OUT_BITS',out); print('OUT_FP16',out_f)
    def cpu(x,y):
        if OP=='ADD': return x+y
        if OP=='SUB': return x-y
        if OP=='MUL': return x*y
        if OP=='MAX': return max(x,y)
        return -x
    exp=[struct.unpack('<e',struct.pack('<e',cpu(float(x),float(y))))[0] for x,y in zip(a,b)]
    print('CPU_FP16_'+OP,exp)
    print('PASS',out_f==exp)
    d='/home/opencode-agent/rk3588-ew-capture/'+OP.lower(); os.makedirs(d,exist_ok=True)
    open(d+'/input-a.fp16','wb').write(struct.pack('<8e',*map(float,a)))
    open(d+'/input-b.fp16','wb').write(struct.pack('<8e',*map(float,b)))
    open(d+'/output-raw.fp16','wb').write(struct.pack('<8H',*out))
    open(d+'/output-full-bo.bin','wb').write(raw)
    open(d+'/commands.bin','wb').write(b''.join(x.to_bytes(8,'little') for x in regs))
    meta={'device':path,'dma':{'regcmd':regcmd_bo.dma_address,'a':a_bo.dma_address,'b':b_bo.dma_address,'out':o_bo.dma_address},
          'op':OP,'ew_cfg':CFG,'n':n,'a':a,'b':b,'out_bits':out,'out_fp16':out_f,'cpu_fp16':exp,'submit_ret':ret,
          'commands_sha256':hashlib.sha256(b''.join(x.to_bytes(8,'little') for x in regs)).hexdigest(),
          'output_full_sha256':hashlib.sha256(raw).hexdigest(),'scope':'real RK3588 Rocket DPU EW ADD; no FPGA'}
    open(d+'/capture.json','w').write(json.dumps(meta,indent=2,sort_keys=True)+'\n')
    print('CAPTURE_DIR',d)
if __name__=='__main__': main()
