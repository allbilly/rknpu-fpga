#!/usr/bin/env python3
"""Run the standalone whole-reset maintenance controller controls only."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import resource
import shlex
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
RTL=ROOT/'rtl/ddr/maintenance/rk_whole_reset_control.sv'
TEST_DIR=ROOT/'tests/ddr/whole_reset'
BENCH=TEST_DIR/'tb_whole_reset_control.sv'
INVALID=TEST_DIR/'tb_whole_reset_invalid_v6.sv'
RUNNER=Path(__file__).resolve()
OWNED=ROOT/'tools/owned_process.py'
sys.path.insert(0,str(ROOT))
from tools.owned_process import run_owned

result={}
output_dir=None
report_path=None

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save():
    temporary=report_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    temporary.replace(report_path)
def resource_snapshot():
    entry=next((line for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')),None)
    need(entry is not None,'Unified cgroup-v2 membership is unavailable')
    group=Path('/sys/fs/cgroup')/entry.split('::',1)[1].lstrip('/')
    cgroup={name:(group/name).read_text().strip() for name in
        ('cpu.max','memory.max','memory.high','memory.swap.max','pids.max')}
    limits={}
    for name in ('RLIMIT_AS','RLIMIT_CPU','RLIMIT_DATA','RLIMIT_NOFILE','RLIMIT_STACK'):
        key=getattr(resource,name,None)
        if key is not None:
            soft,hard=resource.getrlimit(key);limits[name]=[str(soft),str(hard)]
    return {'cgroup_path':str(group),'cgroup_values':cgroup,'rlimits':limits,'runner_changed_limits':False}
def run(name,argv,timeout,*,expected_rc=0):
    row={'name':name,'argv':list(map(str,argv)),'timeout_seconds':timeout,'started_utc':utc(),'status':'RUNNING'}
    result['commands'].append(row);save()
    logfile=output_dir/(name+'.log');started=time.monotonic()
    with logfile.open('xb') as stream:
        try:
            completed=run_owned(argv,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=timeout)
        except BaseException as error:
            owned=getattr(error,'owned_process_cleanup',{})
            row.update(status='EXCEPTION',error=repr(error),pid=owned.get('pid'),pgid=owned.get('pgid'),
                       live_before_cleanup=owned.get('live_before_cleanup'),live_after_cleanup=owned.get('live_after_cleanup'),
                       log_path=str(logfile),log_sha256=sha(logfile))
            save();raise
    row.update(returncode=completed.returncode,timed_out=completed.timed_out,pid=completed.pid,pgid=completed.pid,
        live_before_cleanup=list(completed.live_before_cleanup),live_after_cleanup=list(completed.live_after_cleanup),
        process_group_closed=not completed.live_after_cleanup,log_path=str(logfile),log_sha256=sha(logfile),
        seconds=round(time.monotonic()-started,3))
    row['status']='PASS' if completed.returncode==expected_rc and not completed.timed_out and \
        not completed.live_before_cleanup and not completed.live_after_cleanup else 'FAIL'
    save()
    need(row['status']=='PASS',name+' exit/timeout/owned-group result differs')
    return row,logfile.read_text(errors='replace')
def tool(name,version_args):
    path=name if os.path.sep in name else shutil.which(name)
    need(path is not None,'Required native tool is unavailable: '+str(name))
    invocation=os.path.abspath(path)
    resolved=str(Path(invocation).resolve())
    need(Path(invocation).is_file() and os.access(invocation,os.X_OK),'Resolved native tool is not executable: '+invocation)
    row,output=run('version_'+Path(invocation).name,[invocation,*version_args],30)
    line=next((line.strip() for line in output.splitlines() if line.strip()),'')
    need(line!='','Version output is empty: '+str(name))
    return {'path':invocation,'sha256':sha(invocation),'resolved_target':resolved,
            'resolved_target_sha256':sha(resolved),'version':line,'version_log_path':row['log_path'],
            'version_log_sha256':row['log_sha256']}
def compiler_launcher(name):
    found=shutil.which(name)
    need(found is not None,'Compiler launcher not found: '+name)
    invocation=os.path.abspath(found);target=str(Path(invocation).resolve())
    return {'invocation_path':invocation,'invocation_sha256':sha(invocation),
            'resolved_target':target,'resolved_target_sha256':sha(target)}
def find_unwrapped_cxx():
    path_dirs=os.environ.get('PATH','').split(os.pathsep)
    for name in ('g++','c++','clang++'):
        for directory in path_dirs:
            if Path(directory).name in ('ccache','sccache'):
                continue
            candidate=Path(directory or '.')/name
            if not candidate.is_file() or not os.access(candidate,os.X_OK):
                continue
            resolved=candidate.resolve()
            if Path(str(resolved)).name in ('ccache','sccache') or any(
                    part in ('ccache','sccache') for part in resolved.parts):
                continue
            return str(candidate.absolute())
    raise RuntimeError('No unwrapped C++ compiler was found on PATH')
def build_icarus(tool_path,top,name,parameters=()):
    image=output_dir/(name+'.vvp')
    argv=[tool_path,'-g2012','-Wall','-s',top,'-o',str(image)]
    for key,value in parameters:argv.append('-P'+top+'.'+key+'='+str(value))
    argv += [str(RTL),str(INVALID if top=='tb_whole_reset_invalid_v6' else BENCH)]
    row,log=run(name+'_compile',argv,180)
    need(image.is_file(),'Icarus image missing: '+name)
    return image,row,log
def build_verilator(tool_path,top,name,compiler_path,parameters=()):
    obj=output_dir/(name+'_obj');image=obj/('V'+top)
    argv=[tool_path,'--binary','--timing','--assert','-Wall','--top-module',top,
          '-MAKEFLAGS','CXX='+shlex.quote(compiler_path),'--Mdir',str(obj)]
    for key,value in parameters:argv.append('-G'+key+'='+str(value))
    argv += [str(RTL),str(INVALID if top=='tb_whole_reset_invalid_v6' else BENCH)]
    row,log=run(name+'_compile',argv,300)
    need(image.is_file(),'Verilator binary missing: '+name)
    need(not any(line.startswith('%Warning') for line in log.splitlines()),
         'Strict Verilator warning gate failed: '+name)
    need(any(line.lstrip().startswith(compiler_path+' ') for line in log.splitlines()),
         'Verilator build log does not show the pinned C++ compiler: '+name)
    return image,row,log
def check_suite(name,log,expected_x):
    scenarios=['frame_validation','start_admission_invariants','cancel_before_fire','cancel_wins_exact_fire_edge',
        'fresh_reset_assert_complete_ready_ack','timeout_before_reset_fire_ack','timeout_after_fire_waits_for_terminal_reset',
        'reset_fault_ack_after_fire','stale_fault_requires_fresh_terminal_fault']
    if expected_x:scenarios.append('unknown_active_witness_4state')
    for scenario in scenarios:
        marker='PASS_WHOLE_RESET_SCENARIO name='+scenario
        need(log.splitlines().count(marker)==1,name+' missing/duplicated scenario marker '+scenario)
    matches=re.findall(r'(?m)^PASS_RK_WHOLE_RESET_CONTROL checks=(\d+) reset_fires=(\d+) x_tests=(\d+) scope=control_only_nonphysical$',log)
    need(len(matches)==1,name+' completion marker missing or duplicated')
    checks,fires,x_tests=map(int,matches[0])
    need(checks>0 and fires==4 and x_tests==int(expected_x),name+' completion counts differ '+repr(matches[0]))
    need('FATAL' not in log and 'CHECK_FAILED' not in log,name+' emitted a failure marker')
    return {'checks':checks,'reset_request_edges':fires,'four_state_x_cases':x_tests,'scenario_markers':scenarios}
def check_invalid(name,log,parameter,value):
    need('Invalid whole-reset control deadline/freshness' in log and 'INVALID_PARAMETER_ACCEPTED' not in log,
         name+' invalid parameter did not fail at the controller time-zero guard')
    need('Time: 0' in log or 'time 0' in log.lower() or log.lstrip().startswith('[0]'),
         name+' invalid parameter did not fail at time zero')
    return {'name':name,'parameter':parameter,'value':value,'expected_fatal':'Invalid whole-reset control deadline/freshness'}

def main():
    global output_dir,report_path,result
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if args.out is None:
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        args.out=ROOT/'build'/('ddr-whole-reset-control-native-'+stamp)
    output_dir=args.out.resolve()
    need(output_dir.is_relative_to(ROOT/'build') and not output_dir.exists(),'Fresh workspace build output directory required')
    inputs=[RTL,BENCH,INVALID,RUNNER,OWNED]
    for path in inputs:need(path.is_file(),'Missing source/input: '+str(path))
    source_before={str(path.resolve()):sha(path) for path in inputs}
    environment=resource_snapshot()
    caps=environment['cgroup_values']
    need(all(caps.get(name)=='max' for name in ('memory.max','memory.high','memory.swap.max')),
         'Inherited memory.max/high/swap.max must be uncapped before native simulation')
    output_dir.mkdir(parents=True)
    report_path=output_dir/'report.json'
    result={'schema':1,'status':'RUNNING_WHOLE_RESET_CONTROL_NATIVE','scope':
        'Standalone SYS-clock maintenance-control protocol only; no UI clocks, MIG, DDR, transport, board integration or hardware qualification.',
        'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_revision_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
        'source_hashes_before':source_before,'source_hashes_after':None,'resource_environment':environment,
        'resource_caps_imposed':False,'runner_changed_resource_limits':False,
        'stimulus':{'random':False,'seed':None,'kind':'directed deterministic protocol and invalid-parameter controls'},
        'commands':[],'simulators':{},'invalid_parameter_controls':[],
        'hardware_accessed':False,'physical_qualified':False,'started_utc':utc()}
    save()
    tools={
        'iverilog':tool('iverilog',['-V']),
        'vvp':tool('vvp',['-V']),
        'verilator':tool('verilator',['--version']),
        'make':tool('make',['--version']),
        'cxx_launcher':compiler_launcher('c++'),
        'cxx':tool(find_unwrapped_cxx(),['--version'])}
    result['tools']=tools;save()
    for simulator in ('iverilog','verilator'):
        if simulator=='iverilog':
            image,compile_row,_=build_icarus(tools['iverilog']['path'],'tb_whole_reset_control','iverilog_main')
            runrow,log=run('iverilog_main_run',[tools['vvp']['path'],str(image)],60)
            suite=check_suite(simulator,log,expected_x=True)
            result['simulators'][simulator]={'status':'PASS','compile_command':compile_row['name'],
                'run_command':runrow['name'],'image_path':str(image),'image_sha256':sha(image),**suite}
        else:
            image,compile_row,compile_log=build_verilator(tools['verilator']['path'],'tb_whole_reset_control',
                'verilator_main',tools['cxx']['path'])
            runrow,log=run('verilator_main_run',[str(image)],60)
            suite=check_suite(simulator,log,expected_x=False)
            result['simulators'][simulator]={'status':'PASS','compile_command':compile_row['name'],
                'run_command':runrow['name'],'image_path':str(image),'image_sha256':sha(image),**suite}
        save()
    invalid=[('zero_timeout','TIMEOUT_CYCLES',0,('iverilog','verilator')),
        ('zero_stable_samples','STABLE_SAMPLES',0,('iverilog','verilator')),
        ('too_many_stable_samples','STABLE_SAMPLES',65537,('iverilog','verilator')),
        ('x_stable_samples','STABLE_SAMPLES',"32'hx",('iverilog',)),
        ('z_stable_samples','STABLE_SAMPLES',"32'hz",('iverilog',))]
    for name,parameter,value,simulators in invalid:
        image,compile_row,_=build_icarus(tools['iverilog']['path'],'tb_whole_reset_invalid_v6','iverilog_invalid_'+name,((parameter,value),))
        runrow,log=run('iverilog_invalid_'+name+'_run',[tools['vvp']['path'],str(image)],30,expected_rc=1)
        check_invalid('iverilog:'+name,log,parameter,value)
        result['invalid_parameter_controls'].append({'simulator':'iverilog','compile_command':compile_row['name'],
            'run_command':runrow['name'],**check_invalid(name,log,parameter,value)})
        if 'verilator' in simulators:
            obj, vlt_compile, _=build_verilator(tools['verilator']['path'],'tb_whole_reset_invalid_v6',
                'verilator_invalid_'+name,tools['cxx']['path'],((parameter,value),))
            vlt_run,log=run('verilator_invalid_'+name+'_run',[str(obj)],30,expected_rc=1)
            result['invalid_parameter_controls'].append({'simulator':'verilator','compile_command':vlt_compile['name'],
                'run_command':vlt_run['name'],**check_invalid(name,log,parameter,value)})
        save()
    result['status']='PASS_WHOLE_RESET_CONTROL_ICARUS_VERILATOR_REQUIRES_INTEGRATION_REVIEW'
    return 0

if __name__=='__main__':
    exit_code=1
    result={'schema':1,'status':'PREFLIGHT','commands':[],'hardware_accessed':False,'physical_qualified':False}
    try:
        exit_code=main()
    except BaseException as error:
        result.update(status='FAIL_WHOLE_RESET_CONTROL_NATIVE',failure=repr(error))
        if report_path is not None:
            try:save()
            except BaseException:pass
    finally:
        if report_path is not None:
            after={str(path.resolve()):sha(path) for path in (RTL,BENCH,INVALID,RUNNER,OWNED)}
            result['source_hashes_after']=after
            result['sources_unchanged']=result.get('source_hashes_before')==after
            result['owned_groups_after_cleanup']={str(row['pid']):row.get('live_after_cleanup',[])
                for row in result.get('commands',[]) if row.get('pid') is not None}
            result['all_owned_groups_stopped']=all(row.get('process_group_closed') is True and
                not row.get('live_before_cleanup') and not row.get('live_after_cleanup')
                for row in result.get('commands',[]) if row.get('pid') is not None)
            if result.get('status','').startswith('PASS_') and not(
                result.get('sources_unchanged') is True and result.get('all_owned_groups_stopped') is True):
                result['status']='FAIL_PROVENANCE_OR_CLEANUP'
            result['finished_utc']=utc()
            try:save()
            except BaseException:exit_code=1
            if not result.get('sources_unchanged') or not result.get('all_owned_groups_stopped'):exit_code=1
    print(json.dumps({'status':result.get('status'),'failure':result.get('failure'),
        'simulators':result.get('simulators'),'invalid_parameter_control_count':len(result.get('invalid_parameter_controls',[])),
        'sources_unchanged':result.get('sources_unchanged'),'all_owned_groups_stopped':result.get('all_owned_groups_stopped')},sort_keys=True))
    raise SystemExit(exit_code)
