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
import os
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.tinystories.c_engine import CModel
from tools.tinystories.prepare import verify,require
from tools.tinystories.progress import Progress,MemoryGate

DEFAULT_MEMORY_PORTS={'bram':3741,'ddr':3721}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transport_class(memory_profile):
    """Choose the requested raw wire contract explicitly; never probe/fallback."""
    if memory_profile=='bram':
        from tools.tinystories.transport import DualRawTransport
        return DualRawTransport
    if memory_profile=='ddr':
        from tools.ddr.dual_transport import DualDdrRawTransport
        return DualDdrRawTransport
    raise ValueError('Unsupported explicit memory profile')


def namespace_profiles(memory_profile):
    if memory_profile=='bram':
        from tools.tinystories.transport import PROFILES
        return PROFILES
    if memory_profile=='ddr':
        from tools.ddr.dual_transport import PROFILES
        return PROFILES
    raise ValueError('Unsupported explicit memory profile')


def effective_port(memory_profile,requested):
    if memory_profile not in DEFAULT_MEMORY_PORTS:raise ValueError('Unsupported explicit memory profile')
    return DEFAULT_MEMORY_PORTS[memory_profile] if requested is None else requested


def build_parser():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    parser.add_argument('--backend',choices=('fp32-reference','oracle','jtag'),required=True)
    parser.add_argument('--memory-profile',choices=('bram','ddr'),default='bram')
    parser.add_argument('--catalog',type=Path)
    parser.add_argument('--catalog-sha256')
    parser.add_argument('--booth-helper',type=Path)
    parser.add_argument('--port',type=int,help='Bridge port (default: 3741 for BRAM, 3721 for DDR)')
    parser.add_argument('--quit-bridge',action='store_true')
    parser.add_argument('--prompt',default='Once upon a time')
    parser.add_argument('--steps',type=int,default=32)
    parser.add_argument('--min-mem-available-mib',type=int,default=0)
    parser.add_argument('--memory-wait-budget-seconds',type=float,default=0)
    parser.add_argument('--out',type=Path,required=True)
    return parser


def namespace_identity_metadata(memory_profile):
    # Both transport constructors read and validate every namespace identity
    # and ABI before they return. These IDs describe those successful reads.
    from tools.host.transport import ABI_VERSION
    profiles=namespace_profiles(memory_profile)
    return {name:dict(base=f'0x{base:03x}',id=f'0x{ident:08x}',abi_version=ABI_VERSION,
                      constructor_readback_verified=True)
            for name,(base,ident) in profiles.items()}


def preflight_memory_transport(transport,memory_profile):
    """Require an already initialized, healthy DDR namespace pair before uploads."""
    if memory_profile=='bram':return {}
    if memory_profile!='ddr':raise ValueError('Unsupported explicit memory profile')
    from tools.host.transport import ABI_VERSION
    profiles=namespace_profiles(memory_profile)
    checks={}
    for profile in ('ew','cmac'):
        transport.select_profile(profile)
        identity=transport.reg_read(0);abi=transport.reg_read(4);status=transport.reg_read(8)
        require(identity==profiles[profile][1] and abi==ABI_VERSION,
                'DDR namespace identity/ABI changed')
        require(status==0x10,
                'DDR transport requires already-initialized healthy idle memory')
        checks[profile]=dict(id=f'0x{identity:08x}',abi=abi,status=f'0x{status:03x}')
    transport.select_profile('ew')
    return checks


def main(argv=None):
    args=build_parser().parse_args(argv)
    require(args.memory_profile=='bram' or args.backend=='jtag',
            'The DDR memory profile requires the explicit jtag backend')
    selected_transport_class=transport_class(args.memory_profile) if args.backend=='jtag' else None
    port=effective_port(args.memory_profile,args.port)
    require(not sys.flags.optimize,'Optimized Python is unsupported for model qualification')
    require(0<args.steps<=512 and '\0' not in args.prompt,'Invalid model context/prompt before connection')
    package=args.package.resolve();prepared=verify(package)
    require(args.backend=='jtag' or not args.quit_bridge,'Bridge exit applies only to an explicit native session')
    require(args.min_mem_available_mib>=0 and (args.backend=='jtag' or args.min_mem_available_mib==0),
            'Host memory guard applies only to an explicit hardware worker')
    require(args.backend=='jtag' or args.memory_wait_budget_seconds==0,
            'Host memory waiting applies only to an explicit hardware worker')
    memory_gate=MemoryGate(args.min_mem_available_mib,args.memory_wait_budget_seconds)
    if args.backend=='jtag':
        require(args.catalog is not None and args.catalog_sha256 is not None,'An audited complete raw catalog is mandatory')
        require(sha(args.catalog)==args.catalog_sha256,'Catalog changed before connection')
    out=args.out.resolve();require(out.is_relative_to(ROOT/'build') and not out.exists(),'Fresh in-workspace run directory required')
    out.mkdir(parents=True)
    record=dict(status='RUNNING',backend=args.backend,started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        model_sha256=prepared['model_sha256'],tokenizer_sha256=prepared['tokenizer_sha256'],package_report_sha256=sha(package/'report.json'),
        hardware_accessed=False,hardware_access_attempted=False,flash_written=False,cpu_dense_fallback=False,
        scope='Standalone hybrid five-layer model; learned dense backend is explicit. CPU modes are reference targets only. DDR transport selection is not DDR hardware qualification.',
        prompt=args.prompt,steps=args.steps,completed_projections=0,completed_positions=0,
        min_mem_available_mib=args.min_mem_available_mib,memory_wait_budget_seconds=args.memory_wait_budget_seconds,
        memory_profile=args.memory_profile,bridge_port=port,memory_transport_class=None,
        memory_namespace_identities={},ddr_physical_qualification_claim=False)
    def save():
        temporary=out/'report.next'
        temporary.write_text(json.dumps(record,indent=2)+'\n')
        os.replace(temporary,out/'report.json')
    def memory_state(state):
        prior=record.get('resource_gate',{}).get('waiting',False)
        record['resource_gate']=state;save()
        if state['waiting']!=prior:
            print(json.dumps(dict(event='WAIT_HOST_MEMORY' if state['waiting'] else 'RESUME_AFTER_HOST_MEMORY',
                available_kib=state['available_kib'],remaining_seconds=state['remaining_seconds'])),flush=True)
    save();model=backend=transport=link=trace=wire=progress=None
    try:
        progress=Progress(out)
        if args.backend=='fp32-reference':
            model=CModel(package,out/'host',kind='fp32-reference')
        else:
            if args.backend=='oracle':
                from tools.tinystories.oracle import C32Oracle
                backend=C32Oracle(package,out/'oracle',helper=args.booth_helper)
            else:
                from tools.tinystories.native_trace import RecordedNativeLink
                from tools.tinystories.device import RawDenseDevice
                record['host_mem_available_kib']=memory_gate.check(memory_state);save()
                record['hardware_access_attempted']=True;save()
                wire=(out/'native-scans.jsonl').open('x')
                link=RecordedNativeLink(wire,'127.0.0.1',port)
                record['hardware_accessed']=True;save()
                transport=selected_transport_class(link.host,link.port,link=link)
                record['memory_transport_class']=type(transport).__name__
                record['memory_namespace_identities']=namespace_identity_metadata(args.memory_profile)
                if args.memory_profile=='ddr':
                    # Both statuses must already be idle/memory-ready before
                    # RawDenseDevice uploads any program or model BO bytes.
                    record['memory_namespace_status_checks']=preflight_memory_transport(
                        transport,args.memory_profile)
                    save()
                trace=(out/'raw-readback.jsonl').open('x')
                def observed(event):
                    trace.write(json.dumps(event,separators=(',',':'))+'\n');trace.flush()
                    record['last_readback_tag']=event['tag'];save()
                backend=RawDenseDevice(package,args.catalog,args.catalog_sha256,transport,observer=observed)
                backend.initialize()
                record['catalog_sha256']=args.catalog_sha256;record['model_upload_verified']=True;save()
            def dense(name,values):
                record['active_projection']=name;save()
                if args.backend=='jtag':
                    # The preceding projection has completed every raw output
                    # readback and ACK; no scan/request deadline is active here.
                    record['host_mem_available_kib']=memory_gate.check(memory_state)
                result=backend.projection(name,values)
                progress.dense(backend.calls[-1])
                record['completed_projections']+=1;save()
                return result
            model=CModel(package,out/'host',kind='external-dense',projection=dense)
        def position(event):
            progress.position(event)
            record['completed_positions']=progress.position_count;record['prefix']=progress.summary();save()
        result=model.generate(args.prompt,args.steps,on_position=position)
        require(result['dense_calls']==result['forward_positions']*36,'Incomplete five-layer learned projection coverage')
        flat=[v for row in result.pop('logits') for v in row]
        require((out/'logits.bin').read_bytes()==struct.pack('<'+'f'*len(flat),*flat),
                'Incremental completed logits differ from final model result')
        require(progress.position_count==result['forward_positions'] and progress.summary()['text']==result['text'],
                'Incremental token/text record differs from final model result')
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
        record['resource_gate']=dict(memory_gate.summary(),waiting=False)
        if model is not None:model.close()
        if args.backend=='jtag' and link is not None and args.quit_bridge:
            try:link.shutdown_bridge();record['bridge_quit_ack']=True
            except BaseException as error:record.update(status='FAIL',bridge_cleanup_error=repr(error))
        if transport is not None:transport.close()
        elif link is not None:link.close()
        if trace is not None:trace.close()
        if wire is not None:wire.close()
        if progress is not None:
            record['prefix']=progress.summary();record['completed_positions']=progress.position_count;progress.close()
        if args.backend=='jtag' and backend is not None and hasattr(backend,'records'):
            (out/'raw-jobs-final.json').write_text(json.dumps(backend.records,indent=2)+'\n')
        record['artifacts']={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p.name!='report.json'}
        record['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(record['status'],record.get('result',{}).get('text',''),out/'report.json')
    return 0 if record['status'].startswith('PASS_') else 1


if __name__=='__main__':raise SystemExit(main())
