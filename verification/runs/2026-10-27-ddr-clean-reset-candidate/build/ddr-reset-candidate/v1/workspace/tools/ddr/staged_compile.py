"""Standard Verilator translation/make plans and one shared wall-time budget."""
from pathlib import Path
import math
import re
import shlex
import time

from tools.ddr.interface import require


def plans(tool,make,cxx,top,out,definitions,sources):
    require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',top) is not None,'Unsupported Verilator top name')
    out=Path(out)
    translation=[str(tool),'--cc','--exe','--main','--timing','--assert','-Wall','-Wno-fatal',
        '--top-module',top,'-j','1','--output-groups','0',
        '--Mdir',str(out/'obj'),'-o','sim',*definitions,*map(str,sources)]
    # Verilator's generated makefile uses distinct CXX and LINK variables.
    # Bind both to the recorded driver so its flags also reach the link step.
    driver=shlex.quote(str(cxx))
    cpp=[str(make),'-C',str(out/'obj'),'-f','V'+top+'.mk','-j','1',
         'CXX='+driver,'LINK='+driver]
    return translation,cpp


def verify_record(record,plan,phases):
    finite=lambda v:type(v) in (int,float) and math.isfinite(v)
    require(record['status']=='EXITED' and record['returncode']==0 and record['timeout_seconds']==900 and
            record['argv']==list(plan) and record['phases']==list(phases),'Staged compile record differs')
    require(len(phases)==2 and all(p['status']=='EXITED' and p['returncode']==0 and
            p['argv']==argv and finite(p['timeout_seconds']) and 0<p['timeout_seconds']<=900 and
            finite(p['seconds']) and p['seconds']>=0
            for p,argv in zip(phases,plan)),'Staged compile phase failed/changed')
    require(finite(record['seconds']) and 0<=record['seconds']<=900 and sum(p['seconds'] for p in phases)<=record['seconds'] and
            phases[1]['timeout_seconds']<=900-phases[0]['seconds'],
            'Compilation phases reset/exceeded the shared900s budget')


class Budget:
    def __init__(self,seconds=900,*,clock=time.monotonic):
        require(type(seconds) in (int,float) and math.isfinite(seconds) and seconds>0,
                'Invalid shared compile budget')
        self.seconds=seconds;self.clock=clock;self.started=clock()

    def elapsed(self):
        value=self.clock()-self.started
        require(math.isfinite(value) and value>=0,'Invalid monotonic compilation clock')
        return value

    def remaining(self):
        remaining=self.seconds-self.elapsed()
        require(remaining>0,f'Shared {self.seconds:g}s compilation budget exhausted')
        return remaining

    def finish(self):
        elapsed=self.elapsed()
        require(elapsed<=self.seconds,f'Shared {self.seconds:g}s compilation budget exhausted')
        return elapsed
