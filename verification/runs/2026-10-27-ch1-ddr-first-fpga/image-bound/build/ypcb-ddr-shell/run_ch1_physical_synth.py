#!/usr/bin/python3
"""Bounded launch wrapper for the root-reviewed CH1 synthesis/opt package."""
import datetime,hashlib,json,os,re,signal,subprocess,time
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga')
OUT=ROOT/'build/ypcb-ddr-shell/ch1-physical-synth-v2'
PREP=OUT/'preparation.json'; TCL=OUT/'synth.tcl'
REPORT=OUT/'run-report.json'; LIMIT=1200
VIVADO=Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def need(ok,msg):
 if not ok:raise ValueError(msg)
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def avg(text,key):
 line=next(x for x in text.splitlines() if x.startswith(key+' '))
 return float(dict(x.split('=') for x in line.split()[1:])['avg10'])
def save(obj):
 tmp=REPORT.with_suffix('.tmp');tmp.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n');tmp.replace(REPORT)

p=json.loads(PREP.read_text())
need(p.get('status')=='READY_CH1_FRESH_SOURCE_SYNTHESIS_AND_OPT_ONLY_ROOT_TCL_REVIEW_REQUIRED','CH1 package is not in reviewed-ready state')
need(p.get('root_tcl_review_required_before_launch') is True,'root Tcl review gate missing')
need(p.get('native_tool_launched') is False and p.get('vivado_executed') is False,'prep receipt claims a native launch')
need(p.get('real_hdl_count')==122 and p.get('selected_physical_channel')==1,'wrong CH1/122-source package')
need(not REPORT.exists(),'fresh run report required')
# Verify all source inputs and every frozen copy immediately before launch.
for source,expected in p['source_inputs'].items():
 path=Path(source);need(path.is_file() and sha(path)==expected,'source input changed before launch: '+source)
for rel,expected in p['artifacts'].items():
 path=OUT/rel;need(path.is_file() and sha(path)==expected,'copied input changed before launch: '+rel)
need(sha(TCL)==p['synth_tcl_sha256'],'Tcl hash does not match prep manifest')
for output in ('post_opt_anchored.dcp','post_opt_anchored.funcsim.v','ch1_synthesis_facts.tsv','utilization.rpt','io.rpt','clocks.rpt','cdc.rpt','unplaced_timing.rpt','synthesis_drc.rpt','vivado.log','vivado.jou','stdout.log','stderr.log'):
 need(not (OUT/output).exists(),'native output path already exists: '+output)
# Exact transient cgroup admission.
line=next(x for x in Path('/proc/self/cgroup').read_text().splitlines() if x.startswith('0::'))
CG=Path('/sys/fs/cgroup')/line[3:].lstrip('/')
limits={n:(CG/n).read_text().strip() for n in ('memory.max','memory.swap.max','cpu.max','pids.max')}
need(limits=={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'},'cgroup caps must be 8GiB/no-swap/2CPU/256tasks')
mem=int(re.search(r'^MemAvailable:\s+(\d+) kB',Path('/proc/meminfo').read_text(),re.M).group(1))
cpu=avg(Path('/proc/pressure/cpu').read_text(),'some');psi=avg(Path('/proc/pressure/memory').read_text(),'full')
need(mem>=12*1024*1024 and cpu<5 and psi<1,'host admission gate requires >=12GiB available, CPU some<5, memory full<1')
version=[x for x in (ROOT/'build/ypcb-ddr-shell/snapshot-route-v3/vivado.log').read_text(errors='replace').splitlines()[:20] if x.startswith('# Vivado v') or x.startswith('# SW Build ')]
argv=[str(VIVADO),'-mode','batch','-source',str(TCL),'-log',str(OUT/'vivado.log'),'-journal',str(OUT/'vivado.jou')]
r={'schema':'ch1-physical-synth-run-v1','status':'RUNNING','scope':'Fresh selected-CH1 source synthesis plus opt_design only; no placement/routing/bitstream/hardware',
 'started_utc':utc(),'cwd':str(OUT),'argv':argv,'timeout_seconds':LIMIT,'cgroup':str(CG),'kernel_limits':limits,
 'host_admission':{'mem_available_kib':mem,'cpu_pressure_some_avg10':cpu,'memory_pressure_full_avg10':psi},
 'vivado_sha256':sha(VIVADO),'vivado_version_context':version,'preparation_sha256':sha(PREP),'synth_tcl_sha256':sha(TCL),
 'source_input_count':len(p['source_inputs']),'copied_input_count':len(p['artifacts']),
 'source_inputs_before':p['source_inputs'],'copied_inputs_before':p['artifacts'],
 'synthesis_executed':False,'optimization_executed':False,'implementation_executed':False,'implementation_scope':'not started',
 'placement_executed':False,'routing_executed':False,'bitstream_emitted':False,'hardware_accessed':False}
save(r); child=None;started=time.monotonic();termination_actions=[]
try:
 with (OUT/'stdout.log').open('x') as so,(OUT/'stderr.log').open('x') as se:
  watched={signal.SIGINT,signal.SIGTERM,signal.SIGHUP};oldmask=signal.pthread_sigmask(signal.SIG_BLOCK,watched)
  try:child=subprocess.Popen(argv,cwd=OUT,stdout=so,stderr=se,start_new_session=True,preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask))
  finally:signal.pthread_sigmask(signal.SIG_SETMASK,oldmask)
  r['vivado_pid']=child.pid;r['owned_process_group_id']=child.pid;r['start_new_session']=True;save(r)
  try:r['returncode']=child.wait(timeout=LIMIT)
  except BaseException:
   if child.poll() is None:
    termination_actions.append('SIGTERM_owned_process_group')
    os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=8)
   except subprocess.TimeoutExpired:
    termination_actions.append('SIGKILL_owned_process_group')
    os.killpg(child.pid,signal.SIGKILL);child.wait()
   r['owned_group_cleanup_actions']=termination_actions
   r['child_state_after_wait']=child.poll()
   raise
 # Re-hash all parent/original inputs and frozen package copies after exit.
 source_after={s:sha(Path(s)) for s in p['source_inputs'] if Path(s).is_file()}
 copy_after={rel:sha(OUT/rel) for rel in p['artifacts'] if (OUT/rel).is_file()}
 r['source_inputs_after']=source_after;r['copied_inputs_after']=copy_after
 need(len(source_after)==len(p['source_inputs']) and source_after==p['source_inputs'],'source input drift during native run')
 need(len(copy_after)==len(p['artifacts']) and copy_after==p['artifacts'],'frozen package drift during native run')
 need(r['returncode']==0,'Vivado source synthesis/opt returned nonzero')
 log=(OUT/'vivado.log').read_text(errors='replace')
 stdout=(OUT/'stdout.log').read_text(errors='replace')
 marker='PASS_CH1_REAL_SOURCE_SYNTHESIS_AND_OPT_ONLY_REQUIRES_ROUTE_REVIEW'
 need(marker in log or marker in stdout,'native Tcl completion marker missing')
 required=('post_opt_anchored.dcp','post_opt_anchored.funcsim.v','ch1_synthesis_facts.tsv','utilization.rpt','io.rpt','clocks.rpt','cdc.rpt','unplaced_timing.rpt','synthesis_drc.rpt')
 for name in required:need((OUT/name).is_file() and (OUT/name).stat().st_size>0,'required native synthesis artifact missing: '+name)
 r['synthesis_executed']=True;r['optimization_executed']=True;r['implementation_executed']=True
 r['implementation_scope']='Vivado synth_design plus opt_design only; no place_design, phys_opt, route, image, or hardware'
 r['completion_marker']=marker
 r['outputs']={name:{'bytes':(OUT/name).stat().st_size,'sha256':sha(OUT/name)} for name in required+('ch1_synthesis_facts.tsv','vivado.log','vivado.jou','stdout.log','stderr.log')}
 r['status']='PASS_CH1_REAL_SOURCE_SYNTHESIS_AND_OPT_ONLY_REQUIRES_ROUTE_REVIEW'
except BaseException as e:
 r.update(status='FAIL',error=repr(e))
 if child is not None and child.poll() is None:
  termination_actions.append('SIGTERM_owned_process_group')
  os.killpg(child.pid,signal.SIGTERM)
  try:child.wait(timeout=8)
  except subprocess.TimeoutExpired:
   termination_actions.append('SIGKILL_owned_process_group')
   os.killpg(child.pid,signal.SIGKILL);child.wait()
finally:
 log_text=(OUT/'vivado.log').read_text(errors='replace') if (OUT/'vivado.log').is_file() else ''
 r['synthesis_executed']='synth_design completed successfully' in log_text
 r['optimization_executed']='opt_design completed successfully' in log_text
 r['implementation_executed']=bool(r['synthesis_executed'] or r['optimization_executed'])
 r['implementation_scope']='synth_design/opt_design only; placement/routing/image not invoked' if r['implementation_executed'] else 'no successful synthesis/optimization stage observed'
 r['placement_executed']=False;r['routing_executed']=False;r['bitstream_emitted']=False;r['hardware_accessed']=False
 # Always preserve after-hash evidence, including failed commands/timeouts.
 source_after={s:sha(Path(s)) for s in p['source_inputs'] if Path(s).is_file()}
 copy_after={rel:sha(OUT/rel) for rel in p['artifacts'] if (OUT/rel).is_file()}
 r['source_inputs_after']=source_after;r['copied_inputs_after']=copy_after
 r['source_hashes_unchanged_after_exit']=(len(source_after)==len(p['source_inputs']) and source_after==p['source_inputs'])
 r['copied_hashes_unchanged_after_exit']=(len(copy_after)==len(p['artifacts']) and copy_after==p['artifacts'])
 r['owned_group_cleanup_actions']=termination_actions
 r['child_state_after_cleanup']=child.poll() if child is not None else None
 if (not r['source_hashes_unchanged_after_exit'] or not r['copied_hashes_unchanged_after_exit']) and r.get('status','').startswith('PASS'):
  r.update(status='FAIL_INPUT_DRIFT_AFTER_NATIVE_RUN',error='source or frozen package hash changed after native run')
 r['elapsed_seconds']=time.monotonic()-started;r['finished_utc']=utc()
 for n in ('memory.peak','memory.events','cpu.stat'):
  if (CG/n).exists():r[n]=(CG/n).read_text().strip()
 save(r)
print(json.dumps({'status':r['status'],'report':str(REPORT),'returncode':r.get('returncode'),'elapsed_seconds':r['elapsed_seconds'],'error':r.get('error')},indent=2),flush=True)
raise SystemExit(0 if r['status']=='PASS_CH1_REAL_SOURCE_SYNTHESIS_AND_OPT_ONLY_REQUIRES_ROUTE_REVIEW' else 1)
