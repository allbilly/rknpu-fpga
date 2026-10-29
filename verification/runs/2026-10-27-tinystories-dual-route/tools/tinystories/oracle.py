"""Test-only C32 grouping/FP48 accumulation model for trained dense projections.

Never a hardware execution backend or recovery path. Hardware transport must
not import this module to generate results. The original donor Booth function
is compiled unchanged; its batch ABI only avoids per-product process launches.
"""
from pathlib import Path
import ctypes
import hashlib
import json
import math
import struct
import subprocess

from tools.cmac.cacc_reference import add, final
from tools.tinystories.prepare import verify, require

HELPER_SHA='f7c53e8e4d0d12db0c9d62e2c0b2fac3fe95458b3af85328b6f0b3bf9036d2f0'
ROOT=Path(__file__).resolve().parents[2]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_half(value):
    require(math.isfinite(value),'Nonfinite model input is outside the finite application profile')
    try:
        result,=struct.unpack('<H',struct.pack('<e',value))
    except OverflowError as error:
        raise ValueError('Model input overflows FP16; no scale/repair fallback') from error
    require(result&0x7c00 != 0x7c00,'Model input became nonfinite FP16')
    return result


def output_half(bits):
    """Selected finite donor output policy, separate from IEEE/RK claims."""
    value,=struct.unpack('<f',struct.pack('<I',bits))
    require(math.isfinite(value),'Nonfinite dense result is outside the application profile')
    try:
        result,=struct.unpack('<H',struct.pack('<e',value))
        if result&0x7fff==0x7c00:result=(result&0x8000)|0x7bff
    except OverflowError:
        result=((bits>>16)&0x8000)|0x7bff
    return result


def mantissa(word):
    exponent=(word>>10)&31
    return ((word&1023)|(1024 if exponent else 0)) << (exponent&3 if exponent else 1)


class C32Oracle:
    def __init__(self,package,output,helper=None):
        self.package=Path(package).resolve();self.record=verify(self.package)
        helper=Path(helper) if helper is not None else ROOT/'build/cmac_group_candidate/donor_booth_helper.cpp'
        require(sha(helper)==HELPER_SHA,'Changed reviewed donor grouping helper')
        self.output=Path(output).resolve();require(not self.output.exists(),'Fresh oracle compilation directory required')
        self.output.mkdir(parents=True)
        original=helper.read_bytes()
        marker=b'\nint main() {'
        require(original.count(marker)==1,'Changed donor helper boundary')
        # Extract the unchanged reviewed function, excluding only the CLI
        # driver. Renaming main would change its implicit-return semantics.
        (self.output/'donor.cpp').write_bytes(original[:original.index(marker)])
        (self.output/'LICENSE.NVDLA').write_bytes((ROOT/'rtl/vendor/nvdla/LICENSE').read_bytes())
        wrapper=r'''
#include "donor.cpp"
extern "C" int rknpu_booth_batch(const uint32_t* tuples,uint32_t count,int32_t* output) {
    try {
        for(uint32_t i=0;i<count;i++) {
            const uint32_t* t=tuples+4*i;
            if(t[0]>1 || (t[3]<32 && t[3]%4!=0)) return 1;
            cal_fp16_booth(t[0],t[1],t[2],t[3],output+i);
        }
    } catch(...) {return 2;}
    return 0;
}
'''
        (self.output/'batch.cpp').write_text(wrapper)
        argv=['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',str(self.output/'batch.cpp'),'-o',str(self.output/'oracle.so')]
        process=subprocess.run(argv,capture_output=True,check=False)
        (self.output/'compile.log').write_bytes(process.stdout+process.stderr)
        require(process.returncode==0,'Donor oracle batch compilation failed')
        self.library=ctypes.CDLL(str(self.output/'oracle.so'))
        self.library.rknpu_booth_batch.argtypes=[ctypes.POINTER(ctypes.c_uint32),ctypes.c_uint32,ctypes.POINTER(ctypes.c_int32)]
        self.library.rknpu_booth_batch.restype=ctypes.c_int
        self.source_manifest={str(p):sha(p) for p in [helper,Path(__file__).resolve(),ROOT/'tools/cmac/cacc_reference.py',
            self.output/'donor.cpp',self.output/'batch.cpp',self.output/'oracle.so']}
        self.projections={p['name']:p for p in self.record['projections']}
        self.tiles={}
        for tile in self.record['tiles']:
            raw=(self.package/tile['file']).read_bytes()
            self.tiles.setdefault(tile['projection'],[]).append((tile,struct.unpack('<'+'H'*(len(raw)//2),raw)))
        self.calls=[]
        (self.output/'compile.json').write_text(json.dumps(dict(status='COMPILED_TEST_ORACLE_ONLY',argv=argv,returncode=process.returncode,
            sources=self.source_manifest,compiler_version=subprocess.check_output(['c++','--version'],text=True).splitlines()[0],
            hardware_accessed=False,cpu_fallback=False),indent=2)+'\n')

    def tile(self,inputs,weights,ai):
        require(len(inputs)==ai and len(weights)==32*ai,'Oracle tile shape mismatch')
        requests=[];metadata=[]
        for oc in (0,16):
            for ic in range(0,ai,32):
                data=inputs[ic:ic+32];base=oc*ai+ic*16
                for kernel in range(16):
                    weight=weights[base+kernel*32:base+(kernel+1)*32]
                    active=[bool(x&0x7fff) and bool(w&0x7fff) for x,w in zip(data,weight)]
                    exponents=[((x>>12)&7)+((w>>12)&7) if valid else 0 for x,w,valid in zip(data,weight,active)]
                    maximum=max(exponents);start=len(requests)//4
                    for x,w,valid,exponent in zip(data,weight,active,exponents):
                        if valid:requests.extend(((x^w)>>15,mantissa(w),mantissa(x),(maximum-exponent)*4))
                    metadata.append((oc,ic,kernel,maximum,start,len(requests)//4))
        count=len(requests)//4
        arguments=(ctypes.c_uint32*len(requests))(*requests)
        products=(ctypes.c_int32*count)()
        require(self.library.rknpu_booth_batch(arguments,count,products)==0,'Original donor oracle failed')
        partials=list(products);accumulators=[0]*16;outputs=[];groups=[]
        for oc,ic,kernel,maximum,start,end in metadata:
            group=(maximum<<40)|(sum(partials[start:end])&((1<<38)-1));groups.append(group)
            accumulators[kernel]=add(group,accumulators[kernel],ic!=0)
            if ic==ai-32:outputs.append(output_half(final(accumulators[kernel])))
        require(len(outputs)==32,'Incomplete oracle output tile')
        return outputs,groups

    def projection(self,name,values):
        require(name in self.projections,'Unknown learned projection')
        p=self.projections[name]
        require(len(values)==p['inputs'],'Projection input dimension mismatch')
        logical=[finite_half(float(value)) for value in values]
        result=[];tiles=[]
        for tile,weights in self.tiles[name]:
            physical=logical+[0]*(tile['ai']-len(logical))
            outputs,groups=self.tile(physical,weights,tile['ai'])
            # This gather is a TEST oracle only. Live hardware uses its two
            # raw EW compaction tasks and returns an already contiguous BO.
            result.extend(outputs[:tile['logical_outputs']])
            tiles.append(dict(first_output=tile['first_output'],groups=len(groups),outputs=32))
        require(len(result)==p['outputs'],'Incomplete full learned projection')
        floats=struct.unpack('<'+'e'*len(result),struct.pack('<'+'H'*len(result),*result))
        self.calls.append(dict(name=name,input_fp16_sha256=hashlib.sha256(struct.pack('<'+'H'*len(logical),*logical)).hexdigest(),
            output_fp16_sha256=hashlib.sha256(struct.pack('<'+'H'*len(result),*result)).hexdigest(),tiles=tiles))
        return list(floats)
