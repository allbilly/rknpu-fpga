"""Append completed host-model positions and dense receipts; never execute math.

Binary logits and their token/byte metadata are flushed per completed position.
These records preserve a failed prefix, never convert it into a passing run.
"""
from pathlib import Path
import datetime
import hashlib
import json
import math
import re
import struct
import time

from tools.tinystories.prepare import require


def available_memory_kib(path=Path('/proc/meminfo')):
    text=Path(path).read_text()
    matches=re.findall(r'^MemAvailable:\s+([0-9]+) kB\s*$',text,re.M)
    require(len(matches)==1,'Host memory availability is not readable')
    return int(matches[0])


def require_memory(minimum_mib,*,path=Path('/proc/meminfo')):
    require(type(minimum_mib) is int and minimum_mib>=0,'Invalid host memory threshold')
    if not minimum_mib:return None
    available=available_memory_kib(path)
    require(available>=minimum_mib*1024,
            f'Host memory resource gate: {available} KiB available, {minimum_mib*1024} KiB required')
    return available


class MemoryGate:
    """Bounded host-only waiting between fully completed raw projections.

    A zero budget retains immediate failure. No active transport deadline is
    extended, and there is no reconnection, numerical work or device retry.
    The budget is cumulative across the entire worker, not per projection.
    """
    def __init__(self,minimum_mib,budget_seconds=0,*,path=Path('/proc/meminfo'),
                 clock=time.monotonic,sleep=time.sleep,poll_seconds=5):
        require(type(minimum_mib) is int and minimum_mib>=0,'Invalid host memory threshold')
        require(type(budget_seconds) in (int,float) and math.isfinite(budget_seconds) and budget_seconds>=0,
                'Invalid cumulative host memory wait budget')
        require(minimum_mib>0 or budget_seconds==0,'A memory wait budget requires an enabled threshold')
        require(type(poll_seconds) in (int,float) and math.isfinite(poll_seconds) and poll_seconds>0,
                'Invalid host memory poll interval')
        self.minimum_mib=minimum_mib;self.budget_seconds=float(budget_seconds)
        self.path=Path(path);self.clock=clock;self.sleep=sleep;self.poll_seconds=float(poll_seconds)
        self.waited_seconds=0.0;self.wait_events=0;self.checks=0;self.minimum_available_kib=None

    def summary(self):
        return dict(minimum_mib=self.minimum_mib,budget_seconds=self.budget_seconds,
                    waited_seconds=self.waited_seconds,remaining_seconds=max(0,self.budget_seconds-self.waited_seconds),
                    wait_events=self.wait_events,checks=self.checks,minimum_available_kib=self.minimum_available_kib)

    def _sample(self):
        available=available_memory_kib(self.path);self.checks+=1
        self.minimum_available_kib=(available if self.minimum_available_kib is None else
                                    min(available,self.minimum_available_kib))
        return available

    def check(self,observer=None):
        if not self.minimum_mib:return None
        threshold=self.minimum_mib*1024;available=self._sample()
        if available>=threshold:return available
        if self.budget_seconds==0:
            require(False,f'Host memory resource gate: {available} KiB available, {threshold} KiB required')
        start=self.clock();prior=self.waited_seconds;self.wait_events+=1
        def elapsed():
            value=self.clock()-start
            require(math.isfinite(value) and value>=0,'Invalid monotonic host memory wait clock')
            return value
        def remaining():
            return self.budget_seconds-prior-elapsed()
        def state(waiting):
            return dict(self.summary(),waiting=waiting,available_kib=available,
                        waited_seconds=prior+elapsed(),remaining_seconds=max(0,remaining()))
        try:
            while available<threshold:
                require(remaining()>0,'Cumulative host memory wait budget exhausted')
                if observer is not None:observer(state(True))
                # Recording or scheduling delays also spend the same budget.
                left=remaining();require(left>0,'Cumulative host memory wait budget exhausted')
                self.sleep(min(self.poll_seconds,left))
                available=self._sample()
                require(remaining()>=0,'Cumulative host memory wait budget exhausted')
            if observer is not None:observer(state(False))
        finally:self.waited_seconds=prior+elapsed()
        require(self.waited_seconds<=self.budget_seconds,'Cumulative host memory wait budget exhausted')
        return available


class Progress:
    def __init__(self,out):
        out=Path(out)
        self.logits=(out/'logits.bin').open('xb')
        self.positions=(out/'positions.jsonl').open('x')
        self.dense_calls=(out/'projection-calls.jsonl').open('x')
        self.position_count=0;self.dense_count=0;self.text_bytes=bytearray();self.generated=[]

    def position(self,event):
        require(set(event)=={'position','input_token','next_token','forced_prompt','stop','piece_hex','logits'},
                'Unknown position record fields')
        require(type(event['position']) is int and event['position']==self.position_count,'Position sequence changed')
        require(all(type(event[k]) is int and 0<=event[k]<512 for k in ('input_token','next_token')),
                'Invalid model token')
        require(type(event['forced_prompt']) is bool and type(event['stop']) is bool,'Invalid position flags')
        values=event['logits']
        require(len(values)==512 and all(math.isfinite(float(v)) for v in values),'Invalid completed logit row')
        piece=bytes.fromhex(event['piece_hex'])
        data=struct.pack('<512f',*values)
        record={k:v for k,v in event.items() if k!='logits'}
        record.update(logits_offset=self.position_count*2048,logits_bytes=2048,
            logits_sha256=hashlib.sha256(data).hexdigest(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
        # Store logits before its completion marker. An interrupted write can
        # leave unmarked trailing data; only marked complete rows are accepted.
        self.logits.write(data);self.logits.flush()
        self.positions.write(json.dumps(record,separators=(',',':'))+'\n');self.positions.flush()
        self.position_count+=1;self.text_bytes.extend(piece)
        if not event['forced_prompt']:self.generated.append(event['next_token'])

    def dense(self,call):
        require(isinstance(call,dict) and isinstance(call.get('name'),str),'Missing completed dense identity')
        require(all(isinstance(call.get(k),str) and re.fullmatch('[0-9a-f]{64}',call[k])
                    for k in ('input_fp16_sha256','output_fp16_sha256')),'Invalid dense byte receipt')
        self.dense_calls.write(json.dumps(call,separators=(',',':'))+'\n');self.dense_calls.flush()
        self.dense_count+=1

    def summary(self):
        return dict(completed_positions=self.position_count,recorded_dense_calls=self.dense_count,
                    generated_tokens=list(self.generated),text=self.text_bytes.decode('utf-8',errors='replace'),
                    scope='Completed prefix only; producer status separately determines full-run acceptance')

    def close(self):
        self.logits.close();self.positions.close();self.dense_calls.close()
