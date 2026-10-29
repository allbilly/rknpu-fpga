#!/usr/bin/env python3
"""Explicit standalone TinyStories reference/oracle/owned-native-link runner.

No programming or fabric reset operation. A jtag caller must separately own
the audited image, target, shared cable lease, hw_server and native bridge.
There is no auto backend choice, reconnect, numerical fallback or CPU gather.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.tinystories.c_engine import CModel
from tools.tinystories.prepare import verify,require


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--backend',choices=('fp32-reference','oracle','jtag'),required=True)
    parser.add_argument('--catalog',type=Path)
    parser.add_argument('--catalog-sha256')
    parser.add_argument('--booth-helper',type=Path)
    parser.add_argument('--port',type=int,default=3741)
    parser.add_argument('--quit-bridge',action='store_true')
    parser.add_argument('--prompt',default='Once upon a time')
    parser.add_argument('--steps',type=int,default=32)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    require(not sys.flags.optimize,'Optimized Python is unsupported for model qualification')
    require(0<args.steps<=512 and '\0' not in args.prompt,'Invalid model context/prompt before connection')
    package=args.package.resolve();prepared=verify(package)
    require(args.backend=='jtag' or not args.quit_bridge,'Bridge exit applies only to an explicit native session')
    if args.backend=='jtag':
        require(args.catalog is not None and args.catalog_sha256 is not None,'An audited complete raw catalog is mandatory')
        require(sha(args.catalog)==args.catalog_sha256,'Catalog changed before connection')
    out=args.out.resolve();require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh in-workspace run directory required')
    out.mkdir(parents=True)
    record=dict(status='RUNNING',backend=args.backend,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        model_sha256=prepared['model_sha256'],tokenizer_sha256=prepared['tokenizer_sha256'],package_report_sha256=sha(package/'report.json'),
        hardware_accessed=False,hardware_access_attempted=False,flash_written=False,cpu_dense_fallback=False,
        scope='Standalone hybrid five-layer model; learned dense backend is explicit. CPU modes are reference targets only.',
        prompt=args.prompt,steps=args.steps,completed_projections=0)
    def save():(out/'report.json').write_text(json.dumps(record,indent=2)+'\n')
    save();model=backend=transport=link=trace=wire=None
    try:
        if args.backend=='fp32-reference':
            model=CModel(package,out/'host',kind='fp32-reference')
        else:
            if args.backend=='oracle':
                from tools.tinystories.oracle import C32Oracle
                backend=C32Oracle(package,out/'oracle',helper=args.booth_helper)
            else:
                from tools.tinystories.native_trace import RecordedNativeLink
                from tools.tinystories.transport import DualRawTransport
                from tools.tinystories.device import RawDenseDevice
                record['hardware_access_attempted']=True;save()
                wire=(out/'native-scans.jsonl').open('x')
                link=RecordedNativeLink(wire,'127.0.0.1',args.port)
                record['hardware_accessed']=True;save()
                transport=DualRawTransport(link.host,link.port,link=link)
                trace=(out/'raw-readback.jsonl').open('x')
                def observed(event):
                    trace.write(json.dumps(event,separators=(',',':'))+'\n');trace.flush()
                    record['last_readback_tag']=event['tag'];save()
                backend=RawDenseDevice(package,args.catalog,args.catalog_sha256,transport,observer=observed)
                backend.initialize()
                record['catalog_sha256']=args.catalog_sha256;record['model_upload_verified']=True;save()
            def dense(name,values):
                record['active_projection']=name;save()
                result=backend.projection(name,values)
                record['completed_projections']+=1;save()
                return result
            model=CModel(package,out/'host',kind='external-dense',projection=dense)
        result=model.generate(args.prompt,args.steps)
        require(result['dense_calls']==result['forward_positions']*36,'Incomplete five-layer learned projection coverage')
        flat=[v for row in result.pop('logits') for v in row]
        (out/'logits.bin').write_bytes(struct.pack('<'+'f'*len(flat),*flat))
        (out/'text.txt').write_text(result['text']+'\n')
        if args.backend!='fp32-reference':
            require(record['completed_projections']==result['dense_calls'],'Missing explicit dense dispatch')
            (out/'dense-calls.json').write_text(json.dumps(backend.calls,indent=2)+'\n')
        if args.backend=='jtag':
            require('tools.tinystories.oracle' not in sys.modules,'Arithmetic oracle imported into hardware execution process')
            require(len(backend.records)==result['forward_positions']*232,'Missing raw CMAC/EW jobs')
            (out/'raw-jobs.json').write_text(json.dumps(backend.records,indent=2)+'\n')
            record['raw_jobs']=len(backend.records);record['raw_completed_tasks']=sum(x['tasks'] for x in backend.records)
        record.update(status=('PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT' if args.backend=='jtag'
            else 'PASS_CPU_MODEL_REFERENCE_ONLY'),result=result,logit_values=len(flat),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as error:
        record.update(status='FAIL',error=repr(error));raise
    finally:
        if model is not None:model.close()
        if args.backend=='jtag' and link is not None and args.quit_bridge:
            try:link.shutdown_bridge();record['bridge_quit_ack']=True
            except BaseException as error:record.update(status='FAIL',bridge_cleanup_error=repr(error))
        if transport is not None:transport.close()
        elif link is not None:link.close()
        if trace is not None:trace.close()
        if wire is not None:wire.close()
        if args.backend=='jtag' and backend is not None and hasattr(backend,'records'):
            (out/'raw-jobs-final.json').write_text(json.dumps(backend.records,indent=2)+'\n')
        record['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(record['status'],record.get('result',{}).get('text',''),out/'report.json')
    return 0 if record['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
