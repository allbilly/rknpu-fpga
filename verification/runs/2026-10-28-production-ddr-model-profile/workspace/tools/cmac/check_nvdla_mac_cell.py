#!/usr/bin/env python3
"""Cross-check sized vectors with NVIDIA's complete NvdlaMacCell class.

Executes original SystemC arithmetic methods, not the TLM/CSB NPU model or
upstream nvdla_utb. C32 is represented by zero/masked upper lanes in C64.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from evidence import ROOT,fingerprint,timestamp
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--channels',type=int,choices=(8,32,64),default=32)
p.add_argument('--kernels',type=int,choices=(1,8,16,32),default=16)
a=p.parse_args();C,K=a.channels,a.kernels
base=ROOT/'build/rknpu-cmac-array'/f'c{C}k{K}'
vr=json.loads((base/'vectors_report.json').read_text())
header=Path('/home/fedora/hw/cmod/cmac/NV_NVDLA_cmac.h')
assert hashlib.sha256(header.read_bytes()).hexdigest()=='c188324560888dacd858c396dba3155cf7e9124dda8405984db8cc1018baa58a'
original=header.read_text()
mac_class=original[original.index('class NvdlaMacCell {'):original.index('class NV_NVDLA_cmac:')]
defines=original[original.index('#define DATA_OPERAND_BIT_WIDTH_INT8'):original.index('#ifdef DEBUG_ERROR_CHECK')]
out=base/('nvdla-mac-cell-'+str(time.time_ns()));out.mkdir(exist_ok=False)
driver=out/'driver.cpp'
driver.write_text('''// NVIDIA NvdlaMacCell class below is copied without arithmetic edits.
// Original license: /home/fedora/hw/LICENSE, pinned nvdlav1 revision.
#include <systemc.h>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <cmath>
#include <cstdarg>
#include <cstdio>
[[noreturn]] static void donor_fail(const char* format, ...) {
    char buffer[1024];va_list args;va_start(args,format);
    vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);
    throw std::runtime_error(buffer);
}
#define cslDebug(args) ((void)0)
#define FAIL(args) donor_fail args
#define NVDLA_CMAC_A_D_MISC_CFG_0_PROC_PRECISION_INT8 0
#define NVDLA_CMAC_A_D_MISC_CFG_0_PROC_PRECISION_INT16 1
#define NVDLA_CMAC_A_D_MISC_CFG_0_PROC_PRECISION_FP16 2
'''+defines+mac_class+'''
int sc_main(int, char**) {
    unsigned channels;
    uint64_t data_present, weight_present;
    while (std::cin >> channels >> data_present >> weight_present) {
        if (channels>64) return 2;
        sc_int<8> data[128],weight[128];
        sc_int<22> result[8];
        uint64_t dm[2]={0,0},wm[2]={0,0};
        for(unsigned i=0;i<128;i++) {data[i]=0;weight[i]=0;}
        for(unsigned bank=0;bank<2;bank++) for(unsigned i=0;i<channels;i++) {
            uint32_t value;if(!(std::cin>>value)) return 3;
            // Our presence-mask interface suppresses inactive lanes. Translate
            // to NVDLA's zero-data/nonzero-mask convention at this test seam.
            if(!(((bank ? weight_present:data_present)>>i)&1)) value=0;
            sc_int<8>* operand=bank ? weight:data;
            uint64_t* mask=bank ? wm:dm;
            operand[i*2]=value&255;operand[i*2+1]=(value>>8)&255;
            if(value&0x7fff) mask[1-i/32]|=uint64_t(3)<<((i%32)*2);
        }
        NvdlaMacCell cell;cell.mac_cell_enable_=true;cell.winograd_op_=false;
        cell.calculation_fp16(wm,dm,data,weight,result);
        std::cout << (result[1],result[0]).to_uint64() << "\\n";
    }
    return std::cin.eof() ? 0:4;
}
''')
flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','systemc'],text=True))
libdir=subprocess.check_output(['pkg-config','--variable=libdir','systemc'],text=True).strip()
if not libdir:
    libdir=next(flag[2:] for flag in flags if flag.startswith('-L') and (Path(flag[2:])/'libsystemc.so').is_file())
assert (Path(libdir)/'libsystemc.so').is_file(),libdir
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint([Path(__file__).resolve(),base/'vectors_report.json',base/'vectors.hex']),
            donor_header=str(header),donor_header_sha256=hashlib.sha256(header.read_bytes()).hexdigest(),
            unchanged_class_sha256=hashlib.sha256(mac_class.encode()).hexdigest(),channels=C,kernels=K,
            systemc_version=subprocess.check_output(['pkg-config','--modversion','systemc'],text=True).strip(),
            scope='Unchanged complete NvdlaMacCell arithmetic class executed with SystemC types. Masked/zero-padded C64 embedding of C32/C8. Not full TLM model, upstream UTB or RK silicon evidence.')
def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
save()
try:
    command=['c++','-std=c++17','-O2','-Wall','-Wextra','-Wno-unknown-pragmas',str(driver),*flags,f'-Wl,-rpath,{libdir}','-o',str(out/'model')]
    report['compile_command']=command
    r=subprocess.run(command,capture_output=True,text=True);(out/'compile.log').write_text(r.stdout+r.stderr)
    assert r.returncode==0,r.stderr[-4000:]
    requests=[];expected=[]
    mask=lambda n:(1<<n)-1
    for token in (base/'vectors.hex').read_text().split():
        word=int(token,16);gold=word&mask(K*44);word>>=K*44
        wm=word&mask(K*C);word>>=K*C;dm=word&mask(C);word>>=C
        w=word&mask(K*C*16);word>>=K*C*16;data=word
        assert data<=mask(C*16)
        for k in range(K):
            values=[C,dm,(wm>>(k*C))&mask(C)]
            values += [(data>>(i*16))&65535 for i in range(C)]
            values += [(w>>((k*C+i)*16))&65535 for i in range(C)]
            requests.append(' '.join(map(str,values))+'\n');expected.append((gold>>(k*44))&mask(44))
    r=subprocess.run([out/'model'],input=''.join(requests),capture_output=True,text=True,timeout=300)
    (out/'run.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
    actual=list(map(int,r.stdout.split()));assert len(actual)==len(expected)
    mismatches=[{'output':i,'frame':i//K,'kernel':i%K,'nvdla':f'{x:011x}','expected':f'{y:011x}'}
                for i,(x,y) in enumerate(zip(actual,expected)) if x!=y]
    report.update(compared_outputs=len(actual),mismatch_count=len(mismatches),mismatches=mismatches[:32])
    assert not mismatches,mismatches[:8]
    assert fingerprint([Path(__file__).resolve(),base/'vectors_report.json',base/'vectors.hex'])==report['source']
    report['status']='PASS_ORIGINAL_NVDLA_MAC_CELL_ARITHMETIC'
except Exception as exc:report.update(status='FAIL',reason=str(exc));raise
finally:
    report.update(finished_utc=timestamp(),artifacts=fingerprint([f for f in out.iterdir() if f.is_file() and f.name!='report.json']))
    save();print(out/'report.json')
print(report['status'],report['compared_outputs'])
