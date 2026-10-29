"""Licensed llama2.c host operators with an explicit learned-dense callback.

The external-dense library contains no original learned matrix loop. A callback
failure poisons the forward pass and returns no output. The separately built
FP32 library is a software reference target, never a runtime fallback.
"""
from pathlib import Path
import ctypes
import hashlib
import json
import math
import subprocess

from tools.tinystories.prepare import RUN_C_SHA, require, verify

DENSE=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_uint64,ctypes.POINTER(ctypes.c_float),
                     ctypes.POINTER(ctypes.c_float),ctypes.c_int,ctypes.c_int)

DECLARATIONS=r'''
#include <setjmp.h>
#include <stdint.h>
typedef int (*rknpu_dense_fn)(uint64_t,const float*,float*,int,int);
static rknpu_dense_fn rknpu_callback = NULL;
static uintptr_t rknpu_blob_base = 0;
static jmp_buf rknpu_forward_failure;
static unsigned rknpu_dense_calls = 0;
'''
EXTERNAL=r'''
void matmul(float* xout,float* x,float* w,int n,int d) {
    rknpu_dense_calls++;
    if(!rknpu_callback || rknpu_callback((uint64_t)((uintptr_t)w-rknpu_blob_base),x,xout,n,d)!=0)
        longjmp(rknpu_forward_failure,1);
}
'''
API=r'''
static Transformer rknpu_transformer;
static Tokenizer rknpu_tokenizer;
static Sampler rknpu_sampler;
static int rknpu_loaded=0,rknpu_position=0,rknpu_poisoned=0;
int rknpu_create(char* model,char* tokenizer) {
    if(rknpu_loaded)return 1;
    build_transformer(&rknpu_transformer,model);
    Config* c=&rknpu_transformer.config;
    if(c->dim!=64||c->hidden_dim!=172||c->n_layers!=5||c->n_heads!=8||c->n_kv_heads!=4||c->vocab_size!=512||c->seq_len!=512) {
        free_transformer(&rknpu_transformer);return 2;
    }
    build_tokenizer(&rknpu_tokenizer,tokenizer,512);
    build_sampler(&rknpu_sampler,512,0.0f,0.9f,1);
    rknpu_blob_base=(uintptr_t)rknpu_transformer.data;
    rknpu_loaded=1;rknpu_position=0;rknpu_poisoned=0;rknpu_dense_calls=0;return 0;
}
void rknpu_destroy(void) {
    if(rknpu_loaded){free_sampler(&rknpu_sampler);free_tokenizer(&rknpu_tokenizer);free_transformer(&rknpu_transformer);}
    rknpu_loaded=0;rknpu_callback=NULL;
}
int rknpu_encode(char* prompt,int* tokens,int capacity) {
    if(!rknpu_loaded||capacity<(int)strlen(prompt)+3)return -1;
    int count=0;encode(&rknpu_tokenizer,prompt,1,0,tokens,&count);return count;
}
int rknpu_forward(int token,int position,float* result,rknpu_dense_fn callback) {
    if(!rknpu_loaded||rknpu_poisoned||position!=rknpu_position||position<0||position>=512||token<0||token>=512)return 1;
    rknpu_callback=callback;
    if(setjmp(rknpu_forward_failure)){rknpu_poisoned=1;rknpu_callback=NULL;return 2;}
    unsigned before=rknpu_dense_calls;
    float* logits=forward(&rknpu_transformer,token,position);
    rknpu_callback=NULL;
    if(rknpu_dense_calls-before!=36){rknpu_poisoned=1;return 3;}
    memcpy(result,logits,512*sizeof(float));rknpu_position++;return 0;
}
int rknpu_sample(float* logits) {return sample(&rknpu_sampler,logits);}
const char* rknpu_decode(int previous,int token) {return decode(&rknpu_tokenizer,previous,token);}
unsigned rknpu_calls(void) {return rknpu_dense_calls;}
'''


def source_text(original,external):
    declaration='void matmul(float* xout, float* x, float* w, int n, int d) {'
    require(original.count(declaration)==1,'Changed original dense boundary')
    start=original.index(declaration);opening=original.index('{',start);depth=1;end=opening+1
    while depth:
        require(end<len(original),'Unclosed original dense body')
        depth += int(original[end]=='{')-int(original[end]=='}');end+=1
    body=EXTERNAL if external else original[start:opening+1]+'\n    rknpu_dense_calls++;'+original[opening+1:end]
    result='#define TESTING\n'+original[:start]+DECLARATIONS+body+original[end:]+API
    if external:
        require('val += w[i * n + j] * x[j]' not in result,'CPU learned dense loop remains in external backend')
    return result


class CModel:
    def __init__(self,package,output,*,kind,projection=None):
        require(kind in ('fp32-reference','external-dense'),'Choose an explicit model execution kind')
        require((kind=='external-dense') == (projection is not None),'Dense callback/reference mode mismatch')
        self.package=Path(package).resolve();self.prepared=verify(self.package)
        self.output=Path(output).resolve();require(not self.output.exists(),'Fresh C engine build directory required')
        self.output.mkdir(parents=True)
        original=(self.package/'reference/run.c').read_bytes()
        require(hashlib.sha256(original).hexdigest()==RUN_C_SHA,'Changed official C model source')
        self.external=kind=='external-dense';self.projection=projection;self.failure=None;self.calls=[]
        text=source_text(original.decode(),self.external)
        (self.output/'engine.c').write_text(text)
        (self.output/'LICENSE').write_bytes((self.package/'reference/LICENSE').read_bytes())
        argv=['gcc','-O3','-fPIC','-shared',str(self.output/'engine.c'),'-lm','-o',str(self.output/'engine.so')]
        process=subprocess.run(argv,capture_output=True,check=False)
        (self.output/'compile.log').write_bytes(process.stdout+process.stderr)
        require(process.returncode==0,'C host engine compilation failed')
        self.library=ctypes.CDLL(str(self.output/'engine.so'))
        lib=self.library
        lib.rknpu_create.argtypes=[ctypes.c_char_p,ctypes.c_char_p];lib.rknpu_create.restype=ctypes.c_int
        lib.rknpu_encode.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_int),ctypes.c_int];lib.rknpu_encode.restype=ctypes.c_int
        lib.rknpu_forward.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_float),DENSE];lib.rknpu_forward.restype=ctypes.c_int
        lib.rknpu_sample.argtypes=[ctypes.POINTER(ctypes.c_float)];lib.rknpu_sample.restype=ctypes.c_int
        lib.rknpu_decode.argtypes=[ctypes.c_int,ctypes.c_int];lib.rknpu_decode.restype=ctypes.c_char_p
        lib.rknpu_calls.restype=ctypes.c_uint
        self.by_offset={(p['source_offset'],p['inputs'],p['outputs']):p['name'] for p in self.prepared['projections']}
        require(len(self.by_offset)==36,'Ambiguous learned projection identity')
        def dense(offset,inputs,outputs,n,d):
            try:
                require(self.external and self.failure is None,'Unexpected/poisoned learned dense callback')
                name=self.by_offset.get((offset,n,d));require(name is not None,'Unknown learned matrix or dimensions')
                values=[float(inputs[i]) for i in range(n)]
                result=self.projection(name,values)
                require(len(result)==d,'Dense callback output extent changed')
                require(all(math.isfinite(float(value)) for value in result),'Nonfinite learned dense output; no repair')
                for i,value in enumerate(result):outputs[i]=value
                self.calls.append(name)
                return 0
            except BaseException as error:
                self.failure=error
                return 1
        self.callback=DENSE(dense)
        rc=lib.rknpu_create(str(self.package/'assets/stories260K.bin').encode(),str(self.package/'assets/tok512.bin').encode())
        require(rc==0,'C host engine rejected model/tokenizer')
        self.closed=False
        (self.output/'compile.json').write_text(json.dumps(dict(status='COMPILED_C_HOST_ENGINE_ONLY',
            kind='external-dense-only' if self.external else 'separate-fp32-reference',
            original_c_sha256=RUN_C_SHA,derived_c_sha256=hashlib.sha256(text.encode()).hexdigest(),argv=argv,
            returncode=process.returncode,binary_sha256=hashlib.sha256((self.output/'engine.so').read_bytes()).hexdigest(),
            compiler_version=subprocess.check_output(['gcc','--version'],text=True).splitlines()[0],hardware_accessed=False),indent=2)+'\n')

    def generate(self,prompt,steps,*,on_position=None):
        require(not self.closed and self.failure is None,'C host model is closed/poisoned')
        require(isinstance(prompt,str) and '\0' not in prompt,'Prompt must be text without embedded NUL')
        require(type(steps) is int and 0<steps<=512,'Invalid model position limit')
        require(on_position is None or callable(on_position),'Position observer must be callable')
        encoded=prompt.encode();tokens=(ctypes.c_int*(len(encoded)+3))()
        count=self.library.rknpu_encode(encoded,tokens,len(tokens));require(0<count<=steps,'Prompt outside context/step budget')
        prompt_ids=list(tokens[:count]);token=prompt_ids[0];generated=[];pieces=[];logits_trace=[];input_tokens=[]
        logits=(ctypes.c_float*512)()
        order=[f'layers.{layer}.{kind}' for layer in range(5) for kind in ('wq','wk','wv','wo','w1','w3','w2')]+['output']
        for position in range(steps):
            before=len(self.calls);input_tokens.append(token)
            rc=self.library.rknpu_forward(token,position,logits,self.callback)
            if rc!=0:
                if self.failure is not None:raise self.failure
                raise RuntimeError('C forward failed; partial KV state poisoned')
            if self.external:require(self.calls[before:]==order,'Missing/reordered learned projection')
            logits_trace.append(list(logits))
            require(all(math.isfinite(float(v)) for v in logits),'Nonfinite model logits')
            if position<count-1:next_token=prompt_ids[position+1]
            else:
                next_token=int(self.library.rknpu_sample(logits));generated.append(next_token)
            stop=next_token==1
            piece=None if stop else self.library.rknpu_decode(token,next_token)
            if piece:pieces.append(piece)
            if on_position is not None:
                try:
                    # Observer receives a copy after actual forward/sampling;
                    # its return value never supplies a token, logit or result.
                    on_position(dict(position=position,input_token=token,next_token=next_token,
                        forced_prompt=position<count-1,stop=stop,piece_hex=piece.hex() if piece else '',
                        logits=list(logits_trace[-1])))
                except BaseException as error:
                    self.failure=error
                    raise
            if stop:break
            token=next_token
        return dict(prompt_tokens=prompt_ids,generated_tokens=generated,text=b''.join(pieces).decode('utf-8',errors='replace'),
            forward_positions=len(logits_trace),dense_calls=int(self.library.rknpu_calls()),input_tokens=input_tokens,logits=logits_trace)

    def close(self):
        if not self.closed:self.library.rknpu_destroy();self.closed=True
