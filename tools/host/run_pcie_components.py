#!/usr/bin/env python3
"""Run public PCIe source-health and DMA DECERR component controls."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from tools.owned_process import run_owned

TESTS=ROOT/'tests/host/pcie_components'
HEALTH=ROOT/'rtl/host/rk_pcie_source_health.sv'
EPOCH_GUARD=ROOT/'rtl/host/rk_transport_epoch_guard.sv'
DMA=ROOT/'rtl/host/rk_pcie_dma_decerr.sv'
HEALTH_TB=TESTS/'tb_pcie_source_health.sv'
INVALID_TB=TESTS/'tb_pcie_source_health_invalid.sv'
DMA_TB=TESTS/'tb_pcie_dma_decerr.sv'
CONTRACT=TESTS/'source-contract.json'
CROSSWALK=TESTS/'source-crosswalk.json'
README=TESTS/'README.md'
RUNNER=Path(__file__).resolve()
OWNED=ROOT/'tools/owned_process.py'

CONFIGS=(('125MHz_50MHz',4000,10000),('250MHz_50MHz',2000,10000),
         ('125MHz_133MHz',4000,3750),('250MHz_133MHz',2000,3750))
INVALID_CASES={1:'Invalid PCIe health synchronization/heartbeat/deadline parameters',
               2:'Invalid PCIe health synchronization/heartbeat/deadline parameters',
               3:'Invalid PCIe health synchronization/heartbeat/deadline parameters',
               4:'Invalid PCIe health synchronization/heartbeat/deadline parameters',
               5:'Invalid transport epoch freshness parameter'}
HEALTH_SUMMARY=re.compile(r'^PASS_SOURCE_HEALTH checks=(\d+) pcie_guard_failed=([01]) pcie_seen_up=([01]) jtag_ready=([01])$',re.M)
DMA_COUNT=re.compile(r'^CHECK_COUNT_PCIE_DMA_DECERR checks=(\d+)$',re.M)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def need(ok,message):
    if not ok:
        raise RuntimeError(message)


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def jwrite(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')


def inventory(root):
    rows=[]
    for path in sorted(Path(root).rglob('*')):
        if path.is_file() and path.name!='report.json':
            rows.append({'path':str(path),'relative_path':str(path.relative_to(root)),
                         'bytes':path.stat().st_size,'sha256':sha(path)})
    return rows


def environment_snapshot():
    result={'runner_added_resource_limits':False}
    try:
        line=next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
        group=Path('/sys/fs/cgroup')/line.split('::',1)[1].lstrip('/')
        result['cgroup_path']=str(group)
        result['cgroup_values']={name:(group/name).read_text().strip() for name in
            ('cpu.max','memory.high','memory.max','memory.swap.max','pids.max')}
    except (OSError,StopIteration):
        result['cgroup_snapshot']='unavailable'
    try:
        result['rlimits']={name:list(resource.getrlimit(getattr(resource,name))) for name in
            ('RLIMIT_CPU','RLIMIT_AS','RLIMIT_DATA','RLIMIT_STACK','RLIMIT_NPROC') if hasattr(resource,name)}
    except (OSError,ValueError):
        result['rlimits_snapshot']='unavailable'
    return result


def command(record, name, argv, cwd, log_stem, timeout, expected_returncode=0):
    stem=Path(log_stem)
    stdout=Path(str(stem)+'.stdout.log')
    stderr=Path(str(stem)+'.stderr.log')
    row={'name':name,'argv':list(map(str,argv)),'cwd':str(cwd),'timeout_seconds':timeout,
         'started_utc':utc(),'stdout_path':str(stdout),'stderr_path':str(stderr),'status':'RUNNING'}
    record['commands'].append(row)
    Path(stdout).parent.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    with stdout.open('xb') as out,stderr.open('xb') as err:
        try:
            result=run_owned(argv,timeout=timeout,cwd=cwd,stdout=out,stderr=err,env=record['_env'])
        except BaseException as exc:
            meta=getattr(exc,'owned_process_cleanup',{})
            row.update(status='EXCEPTION',error=repr(exc),pid=meta.get('pid'),pgid=meta.get('pgid'),
                live_before_cleanup=meta.get('live_before_cleanup'),live_after_cleanup=meta.get('live_after_cleanup'),
                stdout_sha256=sha(stdout),stderr_sha256=sha(stderr),elapsed_seconds=round(time.monotonic()-start,6),
                finished_utc=utc())
            record['_save']()
            raise
    row.update(returncode=result.returncode,timed_out=result.timed_out,pid=result.pid,pgid=result.pid,
        live_before_cleanup=list(result.live_before_cleanup),live_after_cleanup=list(result.live_after_cleanup),
        process_group_closed=not result.live_after_cleanup,stdout_sha256=sha(stdout),stderr_sha256=sha(stderr),
        elapsed_seconds=round(time.monotonic()-start,6),finished_utc=utc())
    row['status']='PASS' if result.returncode==expected_returncode and not result.timed_out and \
        not result.live_before_cleanup and not result.live_after_cleanup else 'FAIL'
    record['_save']()
    need(row['status']=='PASS',name+' failed, timed out, or left an owned process group alive')
    return row


def combined_log(row):
    return Path(row['stdout_path']).read_text(errors='replace')+'\n'+Path(row['stderr_path']).read_text(errors='replace')


def validate_health_log(row, config, expected_checks):
    text=combined_log(row)
    matches=HEALTH_SUMMARY.findall(text)
    need(len(matches)==1,'Missing/duplicate health PASS marker: '+row['name'])
    checks,guard_failed,seen_up,jtag_ready=matches[0]
    need(int(checks)==expected_checks,'Health check count changed: '+row['name'])
    need(seen_up=='1' and jtag_ready=='1','Health/independent JTAG guard completion flags missing')
    need('CONFIG source_half_ps=%d ui_half_ps=%d divider_bits=6 transitions=2 timeout_ui=1024 stages=3 four_state=%d' %
        (config[1],config[2],1 if '_iverilog_' in row['name'] else 0) in text,
        'Health ratio/config marker missing: '+row['name'])
    need('$finish' in text and 'CHECK_FAIL' not in text and 'FATAL:' not in text and '%Fatal' not in text,
         'Positive health simulation reported a failure or did not finish: '+row['name'])
    return {'status':'PASS','checks':int(checks),'guard_failed_at_final_sample':guard_failed=='1',
            'guard_observed_up':seen_up=='1','jtag_guard_ready':jtag_ready=='1',
            'config_name':config[0],'summary_line':matches[0]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,help='fresh unique output directory; omitted creates a timestamped directory under build/')
    parser.add_argument('--simulator',choices=('both','iverilog','verilator'),default='both')
    args=parser.parse_args()
    contract=json.loads(CONTRACT.read_text())
    crosswalk=json.loads(CROSSWALK.read_text())
    need(crosswalk.get('public_files',{}).get('health_rtl',{}).get('byte_identical') is True and
         crosswalk.get('public_files',{}).get('dma_rtl',{}).get('byte_identical') is True and
         crosswalk.get('health_functional_bench',{}).get('byte_identical') is True and
         crosswalk.get('health_invalid_bench',{}).get('byte_identical') is True and
         crosswalk.get('dma_directed_bench',{}).get('control_body_byte_identical_after_counter_removal') is True,
         'Public source-copy crosswalk is incomplete')
    need(contract.get('schema')==1 and contract.get('health_positive_checks')=={'iverilog':43,'verilator':34},
         'Unsupported source contract/health check counts')
    need(contract.get('dma_completion_marker')=='PASS_PCIE_DMA_DECERR_NATIVE',
         'Unsupported DMA source contract')
    need(contract.get('dma_positive_checks')=={'iverilog':956,'verilator':904},
         'DMA directed bench check-count contract missing or changed')
    expected_files={'rtl/host/rk_pcie_source_health.sv':HEALTH,
        'rtl/host/rk_transport_epoch_guard.sv':EPOCH_GUARD,
        'rtl/host/rk_pcie_dma_decerr.sv':DMA,
        'tests/host/pcie_components/tb_pcie_source_health.sv':HEALTH_TB,
        'tests/host/pcie_components/tb_pcie_source_health_invalid.sv':INVALID_TB,
        'tests/host/pcie_components/tb_pcie_dma_decerr.sv':DMA_TB}
    need(contract.get('public_source_hashes')=={name:sha(path) for name,path in expected_files.items()},
         'Public source bytes do not match the source contract')
    need(crosswalk['public_files']['health_rtl']['sha256']==sha(HEALTH) and
         crosswalk['public_files']['dma_rtl']['sha256']==sha(DMA) and
         crosswalk['health_functional_bench']['sha256']==sha(HEALTH_TB) and
         crosswalk['health_invalid_bench']['sha256']==sha(INVALID_TB) and
         crosswalk['dma_directed_bench']['sha256']==sha(DMA_TB),
         'Live public source bytes do not match the source crosswalk')
    if args.out:
        out=args.out if args.out.is_absolute() else (ROOT/args.out)
        out=out.resolve()
    else:
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        out=(ROOT/'build'/('pcie-components-native-'+stamp)).resolve()
    need(not out.exists(),'Fresh output directory required: '+str(out))
    tools={name:shutil.which(name) for name in ('iverilog','vvp','verilator','make','c++')}
    tools['python']=sys.executable
    need(all(tools.values()),'Required native tools unavailable on PATH')
    tools={k:(str(Path(v).absolute()) if k=='c++' else str(Path(v).resolve())) for k,v in tools.items()}
    source_paths=[HEALTH,EPOCH_GUARD,DMA,HEALTH_TB,INVALID_TB,DMA_TB,CONTRACT,CROSSWALK,README,RUNNER,OWNED]
    for path in source_paths:
        need(path.is_file(),'Missing public component source: '+str(path))
    tool_paths=list(tools.values())
    input_paths=list(dict.fromkeys([Path(p).resolve() for p in source_paths]+[Path(p) for p in tool_paths]))
    before={str(p):sha(p) for p in input_paths}
    out.mkdir(parents=True,exist_ok=False)
    record={'schema':1,'status':'RUNNING_PUBLIC_PCIE_COMPONENT_TESTS','started_utc':utc(),
        'source_revision':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip(),
        'workspace_dirty':bool(subprocess.run(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,check=True,capture_output=True,text=True).stdout),
        'scope':'Public source-health and PCIe DMA DECERR component tests; native simulation only. No vendor IP, build synthesis, hardware, or PCIe link.',
        'simulator_selection':args.simulator,'output_path':str(out),'source_hashes_before':before,'source_hashes_after':None,
        'tools':{},'tool_versions':{},'resource_environment':environment_snapshot(),
        'seed_policy':{'health':'deterministic, no PRNG or seed','dma_iverilog':'deterministic, no seed','dma_verilator':'+verilator+seed+1 (directed bench has no PRNG)'},
        'configurations':[{'name':n,'source_frequency_mhz':1000000/(2*sh),'ui_frequency_mhz':1000000/(2*uh),
           'source_half_period_ps':sh,'ui_half_period_ps':uh,'divider_bits':6,'required_transitions':2,'timeout_ui_cycles':1024,'sync_stages':3}
           for n,sh,uh in CONFIGS],
        'health_invalid_parameters':{str(k):v for k,v in INVALID_CASES.items()},
        'source_crosswalk_sha256':sha(CROSSWALK),
        'public_source_contract_sha256':sha(CONTRACT),
        'commands':[],'results':{'health':{},'health_invalid':{},'dma':{}},'runner_added_resource_limits':False}
    record['_env']=os.environ.copy()
    report_path=out/'report.json'
    def save():
        clean={k:v for k,v in record.items() if not k.startswith('_')}
        jwrite(report_path,clean)
    record['_save']=save
    save()
    try:
        # Capture actual compiler/simulator versions and exact executable hashes.
        for name,path in tools.items():
            record['tools'][name]={'path':path,'sha256':sha(path)}
        versions=(('iverilog',[tools['iverilog'],'-V']),('vvp',[tools['vvp'],'-V']),
                  ('verilator',[tools['verilator'],'--version']),('make',[tools['make'],'--version']),
                  ('cxx',[tools['c++'],'--version']),('python',[tools['python'],'--version']))
        for name,argv in versions:
            row=command(record,name+'_version',argv,out,out/'versions'/name,30)
            record['tool_versions'][name]=combined_log(row)
        save()
        simulators=('iverilog','verilator') if args.simulator=='both' else (args.simulator,)
        # Health: four nominal clock ratios per simulator.
        for sim in simulators:
            for cfg in CONFIGS:
                name,src_half,ui_half=cfg
                tag=name.lower()
                work=out/'health'/sim/tag;work.mkdir(parents=True,exist_ok=True)
                if sim=='iverilog':
                    image=work/'health.vvp'
                    argv=[tools['iverilog'],'-g2012','-Wall','-s','tb_pcie_source_health','-o',str(image),
                        f'-Ptb_pcie_source_health.SRC_HALF_PS={src_half}',f'-Ptb_pcie_source_health.UI_HALF_PS={ui_half}',
                        '-Ptb_pcie_source_health.RUN_FOUR_STATE=1',str(HEALTH),str(EPOCH_GUARD),str(HEALTH_TB)]
                    cr=command(record,f'health_{sim}_{tag}_compile',argv,work,work/'compile',180)
                    rr=command(record,f'health_{sim}_{tag}_run',[tools['vvp'],str(image)],work,work/'run',120)
                else:
                    obj=work/'obj'
                    argv=[tools['verilator'],'--binary','--timing','--assert','-Wall','--top-module','tb_pcie_source_health',
                        f'-GSRC_HALF_PS={src_half}',f'-GUI_HALF_PS={ui_half}','-GRUN_FOUR_STATE=0','--Mdir',str(obj),
                        str(HEALTH),str(EPOCH_GUARD),str(HEALTH_TB)]
                    cr=command(record,f'health_{sim}_{tag}_build',argv,work,work/'build',300)
                    need('%Warning-' not in combined_log(cr),'Verilator health authored/source warning must be reviewed: '+cr['name'])
                    image=obj/'Vtb_pcie_source_health';need(image.is_file(),'Fresh Verilator health executable missing')
                    rr=command(record,f'health_{sim}_{tag}_run',[str(image)],work,work/'run',120)
                count=contract['health_positive_checks'][sim]
                result=validate_health_log(rr,cfg,count)
                result.update(compile_command=cr['name'],run_log_path=rr['stdout_path'],run_log_sha256=rr['stdout_sha256'])
                record['results']['health'][f'{sim}:{name}']=result;save()
        # Each invalid parameter gets an independent simulator invocation and exact expected fatal.
        for sim in simulators:
            for case,expected_text in INVALID_CASES.items():
                tag=f'case-{case}';work=out/'health-invalid'/sim/tag;work.mkdir(parents=True,exist_ok=True)
                if sim=='iverilog':
                    image=work/'invalid.vvp'
                    argv=[tools['iverilog'],'-g2012','-Wall','-s','tb_pcie_source_health_invalid','-o',str(image),
                        f'-Ptb_pcie_source_health_invalid.INVALID_CASE={case}',str(HEALTH),str(EPOCH_GUARD),str(INVALID_TB)]
                    cr=command(record,f'invalid_{sim}_{case}_compile',argv,work,work/'compile',180)
                    rr=command(record,f'invalid_{sim}_{case}_expected_fatal',[tools['vvp'],str(image)],work,work/'run',120,expected_returncode=1)
                else:
                    obj=work/'obj'
                    argv=[tools['verilator'],'--binary','--timing','--assert','-Wall','--top-module','tb_pcie_source_health_invalid',
                        f'-GINVALID_CASE={case}','--Mdir',str(obj),str(HEALTH),str(EPOCH_GUARD),str(INVALID_TB)]
                    cr=command(record,f'invalid_{sim}_{case}_build',argv,work,work/'build',300)
                    need('%Warning-' not in combined_log(cr),'Verilator invalid-case source warning must be reviewed: '+cr['name'])
                    image=obj/'Vtb_pcie_source_health_invalid';need(image.is_file(),'Fresh invalid-parameter executable missing')
                    rr=command(record,f'invalid_{sim}_{case}_expected_fatal',[str(image)],work,work/'run',120,expected_returncode=1)
                text=combined_log(rr)
                need(expected_text in text,'Invalid parameter did not emit expected fatal: '+rr['name'])
                fatal_source='rk_transport_epoch_guard.sv' if case==5 else 'rk_pcie_source_health.sv'
                need(fatal_source in text and ('FATAL:' in text or '%Fatal:' in text or 'Verilog $stop' in text),
                     'Invalid parameter nonzero was not the leaf expected fatal: '+rr['name'])
                need('INVALID_TEST_DID_NOT_FAIL' not in text,'Invalid parameter unexpectedly returned normally: '+rr['name'])
                record['results']['health_invalid'][f'{sim}:case-{case}']={'status':'PASS_EXPECTED_FATAL',
                    'expected_text':expected_text,'compile_command':cr['name'],'run_log_sha256':rr['stdout_sha256']}
                save()
        # The original directed DMA DECERR controls run once in true four-state Icarus and Verilator native.
        if args.simulator in ('both','iverilog'):
            work=out/'dma/iverilog';work.mkdir(parents=True,exist_ok=True);image=work/'dma.vvp'
            cr=command(record,'dma_iverilog_compile',[tools['iverilog'],'-g2012','-Wall','-s','tb_pcie_dma_decerr','-o',str(image),str(DMA_TB),str(DMA)],work,work/'compile',180)
            rr=command(record,'dma_iverilog_four_state_run',[tools['vvp'],str(image)],work,work/'run',180)
            text=combined_log(rr);marker='PASS_PCIE_DMA_DECERR_NATIVE four_state=1'
            need(text.count(marker)==1,'Icarus DMA marker missing/duplicate')
            need('$finish' in text and 'CHECK_FAIL' not in text and 'FATAL:' not in text,'Icarus DMA positive run reported failure')
            count=DMA_COUNT.findall(text);need(len(count)==1,'Icarus DMA check count missing/duplicate')
            need(int(count[0])==contract['dma_positive_checks']['iverilog'],'Icarus DMA check count differs from contract')
            need('CHECK_FAIL' not in text and 'FATAL:' not in text,'Icarus DMA positive run reported failure')
            record['results']['dma']['iverilog']={'status':'PASS','four_state':True,'checks':int(count[0]),
                'marker':'PASS_PCIE_DMA_DECERR_NATIVE four_state=1','run_log_sha256':rr['stdout_sha256']};save()
        if args.simulator in ('both','verilator'):
            work=out/'dma/verilator';work.mkdir(parents=True,exist_ok=True);obj=work/'obj'
            cr=command(record,'dma_verilator_build',[tools['verilator'],'--binary','--timing','--assert','-Wall','-DVERILATOR_NATIVE',
                '--top-module','tb_pcie_dma_decerr','--Mdir',str(obj),str(DMA_TB),str(DMA)],work,work/'build',600)
            need('%Warning-' not in combined_log(cr),'Verilator DMA source warning must be reviewed')
            image=obj/'Vtb_pcie_dma_decerr';need(image.is_file(),'Fresh Verilator DMA executable missing')
            rr=command(record,'dma_verilator_native_run',[str(image),'+verilator+seed+1'],work,work/'run',180)
            text=combined_log(rr);marker='PASS_PCIE_DMA_DECERR_NATIVE four_state=0'
            need(text.count(marker)==1,'Verilator DMA marker missing/duplicate')
            need('$finish' in text and 'CHECK_FAIL' not in text and '%Fatal' not in text and '%Error' not in text,
                 'Verilator DMA positive run reported failure')
            count=DMA_COUNT.findall(text);need(len(count)==1,'Verilator DMA check count missing/duplicate')
            need(int(count[0])==contract['dma_positive_checks']['verilator'],'Verilator DMA check count differs from contract')
            need('CHECK_FAIL' not in text and '%Fatal' not in text and '%Error' not in text,
                 'Verilator DMA positive run reported failure')
            record['results']['dma']['verilator']={'status':'PASS','four_state':False,'checks':int(count[0]),
                'marker':'PASS_PCIE_DMA_DECERR_NATIVE four_state=0','run_log_sha256':rr['stdout_sha256'],
                'seed_argument':'+verilator+seed+1'};save()
        after={str(p):sha(p) for p in input_paths};record['source_hashes_after']=after
        record['sources_unchanged']=after==before
        record['all_owned_process_groups_closed']=all(c.get('process_group_closed') is True and
            not c.get('live_before_cleanup') and not c.get('live_after_cleanup') for c in record['commands'])
        need(record['sources_unchanged'],'Public sources changed during tests')
        need(record['all_owned_process_groups_closed'],'An owned native process group remained live')
        record['output_inventory']=inventory(out)
        record['status']='PASS_PUBLIC_PCIE_COMPONENT_TESTS';record['finished_utc']=utc();save()
        print(json.dumps({'status':record['status'],'out':str(out),'results':record['results'],
            'sources_unchanged':True,'all_owned_process_groups_closed':True},sort_keys=True))
        return 0
    except BaseException as exc:
        record['status']='FAIL_PUBLIC_PCIE_COMPONENT_TESTS';record['error']=repr(exc)
        try:
            record['source_hashes_after']={str(p):sha(p) for p in input_paths}
            record['sources_unchanged']=record['source_hashes_after']==before
        except BaseException as hash_exc:
            record['source_hash_error']=repr(hash_exc)
        record['all_owned_process_groups_closed']=all(c.get('process_group_closed') is True and
            not c.get('live_after_cleanup') for c in record['commands'])
        record['finished_utc']=utc();save()
        print(json.dumps({'status':record['status'],'out':str(out),'error':repr(exc)},sort_keys=True),file=sys.stderr)
        return 1

if __name__=='__main__':
    raise SystemExit(main())
