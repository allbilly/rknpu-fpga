#!/usr/bin/env python3
"""Run standalone PCIe bridge reset startup-history controls in Icarus and Verilator."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.owned_process import run_owned
RTL=ROOT/'rtl/host/rk_pcie_bridge_reset.sv'
BENCH=ROOT/'tests/host/bridge_reset/tb_pcie_bridge_reset.sv'
README=ROOT/'tests/host/bridge_reset/README.md'
OWNED=ROOT/'tools/owned_process.py'
WARNING_RE=re.compile(r'(?im)(?:%Warning(?:-|:)|\bwarning:|\bsorry:)')
FATAL='Invalid async AXI-Lite bridge reset/settling contract'
INVALID_CASES=(
    ('sync_below_minimum',{'SYNC_STAGES':2}),
    ('reset_edges_below_minimum',{'RESET_EDGES':7}),
    ('settle_edges_below_minimum',{'SETTLE_EDGES':4}),
)
PASS_MARKERS=(
    'PASS_STOPPED_SOURCE_STARTUP',
    'PASS_STAGGERED_READY',
    'PASS_READY_IS_STARTUP_HISTORY',
    'PASS_STOPPED_DESTINATION_RESET_RECOVERY',
    'PASS_STOPPED_SOURCE_RESET_RECOVERY',
)

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def utc():return datetime.now(timezone.utc).isoformat()

def resource_snapshot():
    cg={'version':'unknown','path':None,'values':{}}
    try:
        line=next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
        group=Path('/sys/fs/cgroup')/line.split('::',1)[1].lstrip('/')
        cg.update(version=2,path=str(group))
        for name in ('memory.max','memory.high','memory.swap.max','cpu.max','pids.max'):
            try:cg['values'][name]=(group/name).read_text().strip()
            except OSError:cg['values'][name]='unavailable'
    except (OSError,StopIteration):pass
    rlimits={}
    for name in ('RLIMIT_AS','RLIMIT_CPU','RLIMIT_DATA','RLIMIT_NOFILE','RLIMIT_STACK'):
        key=getattr(resource,name,None)
        if key is not None:
            try:rlimits[name]=[str(x) for x in resource.getrlimit(key)]
            except (OSError,ValueError):rlimits[name]='unavailable'
    return {'cgroup':cg,'rlimits':rlimits,'runner_changed_limits':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,help='fresh output directory; default uses a UTC timestamp')
    args=parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=(args.out if args.out else ROOT/'build/pcie-bridge-reset-v1'/stamp).resolve()
    out.mkdir(parents=True,exist_ok=False)
    sources=(RTL,BENCH,README,Path(__file__).resolve(),OWNED)
    before={str(path.relative_to(ROOT)):sha(path) for path in sources}
    revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()
    dirty=bool(subprocess.run(['git','status','--porcelain','--untracked-files=normal'],cwd=ROOT,
        check=True,capture_output=True,text=True).stdout)
    report={'status':'RUNNING','started_utc':utc(),'source_revision':revision,'workspace_dirty':dirty,
        'source_hashes_before':before,'source_hashes_after':None,
        'scope':'Standalone rk_pcie_bridge_reset startup reset/ready component only. No AMD converter implementation, PCIe integration, CDC placement, link health, Vivado, board, or RK qualification.',
        'contract':'Both domains share an asynchronously asserted retained transaction epoch; minimum fresh local reset edges and peer reset witness precede local reset release; local settle edges and synchronized peer-settled witness precede ready. Ready records startup history and does not detect later clock loss.',
        'stimulus':'Directed deterministic asynchronous clocks with stoppable source/destination domains and exact edge checks; no PRNG.',
        'seed':None,'hardware_accessed':False,'network_accessed':False,'vivado_executed':False,
        'ram_caps_imposed':False,'resource_environment':resource_snapshot(),
        'commands':[],'tools':{},'positive_runs':[],'invalid_parameter_runs':[]}
    report_path=out/'report.json'
    def save():report_path.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')

    def run(name,argv,*,timeout=120):
        log=out/(name+'.log');started=time.monotonic()
        with log.open('xb') as stream:
            try:
                result=run_owned(list(map(str,argv)),cwd=out,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
            except BaseException as error:
                cleanup=getattr(error,'owned_process_cleanup',{})
                row={'name':name,'argv':list(map(str,argv)),'returncode':None,'timed_out':False,'status':'EXCEPTION',
                    'timeout_seconds':timeout,'wall_seconds':time.monotonic()-started,'log_path':str(log),
                    'log_sha256':sha(log),'pid':cleanup.get('pid'),'pgid':cleanup.get('pgid'),
                    'live_before_cleanup':cleanup.get('live_before_cleanup'),'live_after_cleanup':cleanup.get('live_after_cleanup'),
                    'exception':repr(error)}
                report['commands'].append(row);save();raise
        text=log.read_text(errors='replace')
        row={'name':name,'argv':list(map(str,argv)),'returncode':result.returncode,'timed_out':result.timed_out,
            'status':'PASS' if result.returncode==0 and not result.timed_out else 'NONZERO_EXIT',
            'timeout_seconds':timeout,'wall_seconds':time.monotonic()-started,'log_path':str(log),
            'log_sha256':sha(log),'pid':result.pid,'pgid':result.pid,
            'live_before_cleanup':list(result.live_before_cleanup),'live_after_cleanup':list(result.live_after_cleanup)}
        report['commands'].append(row);save()
        need(not result.timed_out and not result.live_before_cleanup and not result.live_after_cleanup,
            name+' timed out or left a process-group descendant')
        return row,text

    def compile_one(sim,tool,tag,params=None):
        params=params or {}
        if sim=='iverilog':
            image=out/(tag+'.vvp')
            overrides=[f'-Ptb_pcie_bridge_reset.{name}={value}' for name,value in params.items()]
            argv=[tool,'-g2012','-Wall','-s','tb_pcie_bridge_reset',*overrides,'-o',image,RTL,BENCH]
        else:
            image_dir=out/(tag+'_obj');image= image_dir/'Vtb_pcie_bridge_reset'
            overrides=[f'-G{name}={value}' for name,value in params.items()]
            argv=[tool,'--binary','--timing','--assert','-Wall','-Wno-fatal','-j','2',
                '--top-module','tb_pcie_bridge_reset','--Mdir',image_dir,*overrides,RTL,BENCH]
        row,text=run(tag+'_compile',argv,timeout=180)
        need(row['returncode']==0 and not row['timed_out'],tag+' compile failed')
        warnings=WARNING_RE.findall(text)
        need(not warnings,tag+' compile emitted diagnostics: '+repr(warnings))
        need(image.is_file(),tag+' simulator image missing')
        row.update(image_path=str(image),image_sha256=sha(image),warning_count=len(warnings));save()
        return image,row

    def execute(sim,vvp,image,tag,timeout=30):
        argv=[vvp,str(image)] if sim=='iverilog' else [str(image)]
        row,text=run(tag+'_run',argv,timeout=timeout)
        return row,text

    save()
    try:
        for sim in ('iverilog','verilator'):
            tool=shutil.which(sim);need(tool is not None,'UNAVAILABLE: '+sim)
            version_argv=['-V'] if sim=='iverilog' else ['--version']
            version_row,version_text=run(sim+'_version',[tool,*version_argv],timeout=30)
            need(version_row['returncode']==0,sim+' version query failed')
            info={'argv0':tool,'resolved_path':str(Path(tool).resolve()),'resolved_sha256':sha(Path(tool).resolve()),
                'version_stdout':version_text}
            if sim=='iverilog':
                vvp=shutil.which('vvp');need(vvp is not None,'UNAVAILABLE: vvp')
                vr,vt=run('vvp_version',[vvp,'-V'],timeout=30);need(vr['returncode']==0,'vvp version query failed')
                info['vvp']={'argv0':vvp,'resolved_path':str(Path(vvp).resolve()),'resolved_sha256':sha(Path(vvp).resolve()),'version_stdout':vt}
            else:vvp=None
            report['tools'][sim]=info;save()
            tag=sim+'_startup_history';image,compile_row=compile_one(sim,tool,tag)
            run_row,text=execute(sim,vvp,image,tag)
            need(run_row['returncode']==0 and not run_row['timed_out'],tag+' simulation failed')
            for marker in PASS_MARKERS:need(text.count(marker)==1,tag+' missing/duplicate marker '+marker)
            matches=re.findall(r'^PASS_PCIE_BRIDGE_RESET checks=(\d+) epochs=(\d+) sync=(\d+) reset_edges=(\d+) settle_edges=(\d+) stagger=1 startup_history_only=1$',text,re.M)
            need(len(matches)==1 and matches[0] == ('105','3','3','8','5'),
                tag+' missing exact 105-check/3-epoch final marker')
            need(sha(image)==compile_row['image_sha256'],tag+' image changed during simulation')
            report['positive_runs'].append({'simulator':sim,'checks':int(matches[0][0]),'epochs':3,
                'sync_stages':3,'reset_edges':8,'settle_edges':5,'staggered_ready':True,
                'compile_log_sha256':compile_row['log_sha256'],'run_log_sha256':run_row['log_sha256'],
                'image_path':str(image),'image_sha256':compile_row['image_sha256'],
                'completion_marker':matches[0][0]+' checks, 3 epochs'});save()
            for case,params in INVALID_CASES:
                invalid_tag=f'{sim}_invalid_{case}';bad_image,compile_row=compile_one(sim,tool,invalid_tag,params)
                bad_row,bad_text=execute(sim,vvp,bad_image,invalid_tag,timeout=20)
                need(bad_row['returncode']!=0 and not bad_row['timed_out'],invalid_tag+' did not fail')
                need(FATAL in bad_text and 'INVALID_PARAMETER_DUT_DID_NOT_FAIL' not in bad_text,
                    invalid_tag+' failed for a reason other than the DUT parameter guard')
                bad_row['status']='EXPECTED_FAILURE';save()
                report['invalid_parameter_runs'].append({'simulator':sim,'case':case,'parameters':params,
                    'compile_log_sha256':compile_row['log_sha256'],'run_log_sha256':bad_row['log_sha256'],
                    'expected_diagnostic':FATAL,'returncode':bad_row['returncode'],'image_sha256':compile_row['image_sha256']});save()
        after={str(path.relative_to(ROOT)):sha(path) for path in sources}
        need(after==before,'Bound RTL/bench/runner/owned helper changed during controls')
        need(len(report['positive_runs'])==2 and len(report['invalid_parameter_runs'])==6,
            'Incomplete two-simulator startup/invalid-parameter matrix')
        report.update(status='PASS_PCIE_BRIDGE_RESET_COMPONENT_NATIVE_ONLY',source_hashes_after=after,
            inputs_unchanged=True,finished_utc=utc())
    except BaseException as error:
        report.update(status='FAIL_PCIE_BRIDGE_RESET_COMPONENT_NATIVE_ONLY',failure=repr(error),
            finished_utc=utc())
        save();raise
    save()
    print(json.dumps({'status':report['status'],'report':str(report_path),'positive_runs':len(report['positive_runs']),
        'invalid_parameter_runs':len(report['invalid_parameter_runs']),'hardware_accessed':False},sort_keys=True))

if __name__=='__main__':main()
