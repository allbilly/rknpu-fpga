from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, signal, subprocess, sys, time

ROOT=Path('/home/fedora/rknpu-fpga')
OUT=Path(__file__).resolve().parent
WORK=OUT/'workspace'
sys.path.insert(0,str(ROOT))
from tools.evidence import source_revision, timestamp

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise ValueError(message)
def source_files(root):
    result=[]
    for folder in ('rtl','fpga','model','tools','tests'):
        base=root/folder
        for p in base.rglob('*'):
            if not p.is_file():continue
            if '__pycache__' in p.parts or p.suffix=='.pyc':continue
            result.append(p)
    result.append(root/'Makefile')
    return sorted(set(result),key=lambda p:str(p.relative_to(root)))
def manifest(root,paths):
    files={str(p.relative_to(root)):sha(p) for p in paths}
    text=''.join(f'{value}  {name}\n' for name,value in sorted(files.items()))
    return {'sha256':hashlib.sha256(text.encode()).hexdigest(),'files':files,'count':len(files)}
def cgread(path):
    try:return Path(path).read_text().strip()
    except OSError:return None
def cgroup_snapshot():
    line=next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
    rel=line.split('::',1)[1].lstrip('/');base=Path('/sys/fs/cgroup')/rel
    return {'path':rel,'memory.max':cgread(base/'memory.max'),'memory.swap.max':cgread(base/'memory.swap.max'),
            'cpu.max':cgread(base/'cpu.max'),'pids.max':cgread(base/'pids.max')}

def save():
    (OUT/'report.json').write_text(json.dumps(r,indent=2)+'\n')

def stop(sig,frame):raise InterruptedError('Private production v9 regression interrupted '+str(sig))
for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stop)
need(not WORK.exists(),'Fresh private workspace required')
admission=json.loads((OUT/'admission.json').read_text())
need(admission['status']=='RESOURCE_GATE_PASS_FOR_PRODUCTION_V9' and all(x['pass'] for x in admission['samples'][-3:]),'Host admission gate not met')
mem=int(re.search(r'MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text()).group(1))*1024
cpu_pressure=Path('/proc/pressure/cpu').read_text()
memory_pressure=Path('/proc/pressure/memory').read_text()
cpu_psi=float(re.search(r'^some avg10=([0-9.]+)',cpu_pressure,re.M).group(1))
full_psi=float(re.search(r'^full avg10=([0-9.]+)',memory_pressure,re.M).group(1))
fresh_sample={'utc':timestamp(),'memavailable_bytes':mem,'cpu_psi_some_avg10':cpu_psi,'memory_psi_full_avg10':full_psi,
              'pass':mem>=8589934592 and cpu_psi<5 and full_psi<1}
need(fresh_sample['pass'],'Fresh host admission sample failed')
source_before=source_revision()
source_list=source_files(ROOT)
full_before=manifest(ROOT,source_list)
need(full_before['count']==len(source_list),'Invalid full source manifest')
if (ROOT/'rtl/rk_ew_core.sv').is_file():core_sha=sha(ROOT/'rtl/rk_ew_core.sv')
else:core_sha=None
r={'status':'RUNNING_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_V9','started_utc':timestamp(),
   'scope':'Fresh copy of all rtl/fpga/model/tools/tests and Makefile (no .git, no pycache); generated-check then serial make test. No Vivado, FPGA or hardware action.',
   'source_revision_manifest':source_before,'full_recursive_source_manifest':full_before,'core_sha256':core_sha,
   'commands':[],'source_inputs':{},'copied_inputs':{},'resource_admission':admission,'fresh_launch_sample':fresh_sample,'hardware_accessed':False,
   'bitstream_emitted':False,'vivado_executed':False,'environment_overrides':{'PYTHONPATH':str(WORK)},
   'required_cgroup':{'memory.max':'6442450944','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},
   'individual_deadlines_seconds':{'generated_check':120,'make_test':3600},'parent_deadline_seconds':3600}
save()
child=None
try:
    for folder in ('rtl','fpga','model','tools','tests'):
        shutil_ignore=__import__('shutil').ignore_patterns('__pycache__','*.pyc')
        __import__('shutil').copytree(ROOT/folder,WORK/folder,ignore=shutil_ignore)
    __import__('shutil').copyfile(ROOT/'Makefile',WORK/'Makefile')
    need(not (WORK/'.git').exists(),'Private copy must not contain a git directory')
    copied_list=source_files(WORK)
    source_inputs={str(p.relative_to(WORK)):sha(ROOT/p.relative_to(WORK)) for p in copied_list}
    copied_inputs={str(p.relative_to(WORK)):sha(p) for p in copied_list}
    need(source_inputs==copied_inputs,'Private source copy differs from live source')
    r['source_inputs']=source_inputs;r['copied_inputs']=copied_inputs
    copy_text=''.join(f'{value}  {name}\n' for name,value in sorted(copied_inputs.items()))
    r['private_copy_manifest_sha256']=hashlib.sha256(copy_text.encode()).hexdigest()
    r['private_copy_file_count']=len(copied_inputs)
    r['cgroup']=cgroup_snapshot()
    need(r['cgroup']['memory.max']=='6442450944','MemoryMax cgroup was not enforced')
    need(r['cgroup']['memory.swap.max']=='0','MemorySwapMax cgroup was not enforced')
    need(r['cgroup']['cpu.max']=='200000 100000','CPUQuota cgroup was not enforced')
    need(r['cgroup']['pids.max']=='256','TasksMax cgroup was not enforced')
    r['versions']={}
    for name,cmd in {'python':['python3','--version'],'make':['make','--version'],
                     'iverilog':['iverilog','-V'],'verilator':['verilator','--version']}.items():
        v=subprocess.run(cmd,cwd=WORK,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30,check=True)
        r['versions'][name]={'argv':cmd,'first_lines':v.stdout.splitlines()[:3]}
    save()
    for name,argv,limit in [('generated_check',['make','generated-check'],120),('production_test',['make','test'],3600)]:
        c={'name':name,'argv':argv,'cwd':str(WORK),'status':'RUNNING','started_utc':timestamp(),
           'stdout_log':str(OUT/(name+'.stdout.log')),'stderr_log':str(OUT/(name+'.stderr.log')),'timeout_seconds':limit}
        r['commands'].append(c);save();start=time.monotonic();last=0
        with Path(c['stdout_log']).open('wb') as so,Path(c['stderr_log']).open('wb') as se:
            mask=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
            try:child=subprocess.Popen(argv,cwd=WORK,env={**os.environ,**r['environment_overrides']},stdout=so,stderr=se,start_new_session=True,
                 preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,mask))
            finally:signal.pthread_sigmask(signal.SIG_SETMASK,mask)
            c['pid']=child.pid;save();print(f'RUNNING {name} pid={child.pid} deadline={limit}s cwd={WORK}',flush=True)
            while child.poll() is None:
                elapsed=time.monotonic()-start
                if elapsed-last>=30:
                    print(f'HEARTBEAT {name} elapsed={elapsed:.1f}s',flush=True);last=elapsed
                if elapsed>=limit:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    raise TimeoutError(f'{name} exceeded {limit}s')
                time.sleep(2)
            rc=child.returncode
        c.update(returncode=rc,seconds=time.monotonic()-start,finished_utc=timestamp(),
                 stdout_sha256=sha(c['stdout_log']),stderr_sha256=sha(c['stderr_log']),
                 status='PASS' if rc==0 else 'FAIL')
        save();print(f'COMPLETE {name} status={c["status"]} rc={rc} seconds={c["seconds"]:.3f}',flush=True)
        need(rc==0,name+' failed')
    source_after=source_revision();full_after=manifest(ROOT,source_files(ROOT))
    need(source_after==source_before,'Live source_revision manifest changed during private run')
    need(full_after==full_before,'Recursive live source manifest changed during private run')
    need(all(sha(ROOT/n)==h for n,h in source_inputs.items()),'Live dependency changed during private run')
    need(all(sha(WORK/n)==h for n,h in copied_inputs.items()),'Copied source changed during private run')
    r.update(status='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_V9_ONLY',source_after=source_after,
             full_recursive_source_after=full_after,all_source_inputs_unchanged=True,
             all_copied_inputs_unchanged=True,host_accessed=False,flash_written=False)
except BaseException as error:
    r.update(status='FAIL',error=repr(error))
    if child is not None and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
finally:
    r['finished_utc']=timestamp();save()
print(OUT/'report.json',flush=True)
sys.exit(0 if r['status'].startswith('PASS_') else 1)
