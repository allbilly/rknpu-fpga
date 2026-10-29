from pathlib import Path
import datetime,hashlib,json,os,platform,shutil,subprocess,sys,time
ROOT=Path('/home/fedora/rknpu-fpga');OUT=ROOT/'build/ypcb-ddr-shell/channel-profile-controls-v2'
FROZEN_PACKAGE=ROOT/'build/ypcb-ddr-shell/ch1-source-v1'
V6=ROOT/'build/production-model-auditors/current-v6/report.json'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def all_source_files(root):
 files=[]
 for folder in ('rtl','fpga','model','tools','tests'):
  for p in (root/folder).rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':files.append(p)
 files.append(root/'Makefile')
 return sorted(set(files),key=lambda p:str(p.relative_to(root)))
def manifest(root,paths):
 files={str(p.relative_to(root)):sha(p) for p in paths}
 h=hashlib.sha256(''.join(v+'  '+k+'\n' for k,v in sorted(files.items())).encode()).hexdigest()
 return {'sha256':h,'count':len(files),'files':files}

# Guard the immutable frozen package and current source contract before running.
package_report=json.load(open(FROZEN_PACKAGE/'report.json'))
assert package_report['status']=='PREPARED_EXPLICIT_PHYSICAL_CHANNEL_SNAPSHOT_SOURCE_ONLY'
assert package_report['selected_physical_channel']==1 and len(package_report['real_hdl_sources'])==122
real_hdl=[Path(p).resolve() for p in package_report['real_hdl_sources']]
package_source_hashes={}
for src in real_hdl:
 assert src.is_file(),src
 try:rel=src.relative_to(FROZEN_PACKAGE.resolve()).as_posix();expected=package_report['artifacts'][rel]
 except ValueError:expected=package_report['source_inputs'][str(src)]
 assert sha(src)==expected,src
 package_source_hashes[str(src)]=expected
package_input_hashes={}
for name,h in package_report['source_inputs'].items():
 p=Path(name);p=(p if p.is_absolute() else ROOT/p).resolve();assert p.is_file(),p;assert sha(p)==h,p;package_input_hashes[str(p)]=h
sources=all_source_files(ROOT);before=manifest(ROOT,sources)
test=ROOT/'tests/ddr/channel_profile/test_profile.py';fixture=ROOT/'tests/ddr/channel_profile/channel_profile_contract.json';frozen_test=ROOT/'tests/ddr/channel_profile_frozen/test_profile.py';makefile=ROOT/'Makefile'
# Check the five direct channel-transform tests remain byte-identical to the frozen full-package tests.
def methods(path,names):
 lines=path.read_text().splitlines(keepends=True);out={}
 for name in names:
  i=next(i for i,x in enumerate(lines) if x.startswith('    def '+name+'('))
  j=next((j for j in range(i+1,len(lines)) if lines[j].startswith('    def ') or lines[j].startswith("if __name__ == '__main__'")),len(lines))
  out[name]=''.join(lines[i:j])
 return out
first5=['test_channel_zero_is_an_independent_unchanged_deep_copy','test_channel_one_preserves_physical_buses_and_swaps_only_paired_logical_bindings','test_channel_one_routes_axi_and_control_to_physical_controller_one','test_address_data_strobe_and_ecc_width_contract_is_unchanged','test_rejects_unsupported_channel_and_malformed_pairs_without_mutating_input']
portable_methods=methods(test,first5);frozen_methods=methods(frozen_test,first5);assert portable_methods==frozen_methods
assert len(json.load(open(fixture))['canonical_bindings'])==169
assert 'ddr-channel-frozen-controls' in makefile.read_text() and 'ddr-channel-frozen-controls' not in makefile.read_text().split('test:',1)[1].splitlines()[0]

# Fresh private source-only copy for the default controls.
COPY=OUT/'source-copy-v1/workspace';assert not COPY.exists();COPY.parent.mkdir(parents=True,exist_ok=True)
for folder in ('rtl','fpga','model','tools','tests'):
 shutil.copytree(ROOT/folder,COPY/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(makefile,COPY/'Makefile')
assert not (COPY/'build').exists() and not (COPY/'.git').exists()
copy_files=all_source_files(COPY);copy_before=manifest(COPY,copy_files)
assert before['files']==copy_before['files'], 'Private source-only copy differs from main checkout'

versions={}
for name,cmd in {'python':['python3','--version'],'make':['make','--version'],'iverilog':['iverilog','-V'],'verilator':['verilator','--version']}.items():
 v=subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30,check=True)
 versions[name]={'argv':cmd,'first_lines':v.stdout.splitlines()[:3]}
record={'status':'RUNNING_CHANNEL_PROFILE_CONTROL_TARGETS','started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scope':'Focused DDR host controls; separate frozen CH1 package audit; default controls repeated from private source-only copy without build/ or .git. No source synthesis, Vivado, FPGA, hardware or DDR operation.',
 'versions':versions,'main_source_manifest':before,'package_report_sha256':sha(FROZEN_PACKAGE/'report.json'),
 'package_input_count':len(package_input_hashes),'package_input_hashes':package_input_hashes,
 'package_real_hdl_count':len(package_source_hashes),'package_real_hdl_hashes':package_source_hashes,
 'portable_channel_profile_test_sha256':sha(test),'fixture_sha256':sha(fixture),'frozen_original_test_sha256':sha(frozen_test),
 'five_channel_transform_methods_byte_identical':True,'private_copy_initial_build_absent':True,'private_copy_initial_git_absent':True,
 'private_copy_manifest':copy_before,'commands':[],'hardware_accessed':False,'vivado_executed':False}
def save(): (OUT/'controls-audit.json').write_text(json.dumps(record,indent=2)+'\n')
def run(name,argv,cwd,timeout=600):
 log=OUT/(name+'.log');entry={'name':name,'argv':argv,'cwd':str(cwd),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'RUNNING','timeout_seconds':timeout};record['commands'].append(entry);save();t0=time.monotonic();
 print('BEGIN',name,argv,flush=True)
 with log.open('wb') as f:
  p=subprocess.Popen(argv,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  lines=0
  for line in iter(p.stdout.readline,b''):
   f.write(line);f.flush();lines+=1
   if lines%100==0:print('PROGRESS',name,'lines',lines,'elapsed',round(time.monotonic()-t0,1),flush=True)
  rc=p.wait()
 entry.update(returncode=rc,seconds=time.monotonic()-t0,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),log_path=str(log),log_sha256=sha(log),log_bytes=log.stat().st_size,status='PASS' if rc==0 else 'FAIL');save();print('END',name,entry['status'],'rc',rc,'seconds',round(entry['seconds'],3),flush=True)
 if rc!=0:raise RuntimeError(name+' failed; see '+str(log))

try:
 run('make-ddr-host-controls-main',['make','ddr-host-controls'],ROOT,timeout=900)
 run('make-ddr-channel-frozen-controls',['make','ddr-channel-frozen-controls'],ROOT,timeout=900)
 run('make-ddr-host-controls-source-copy',['make','ddr-host-controls'],COPY,timeout=900)
 copy_after=manifest(COPY,all_source_files(COPY));assert copy_after==copy_before
 # Rehash main source inputs and the frozen package immediately after all controls.
 source_after=manifest(ROOT,all_source_files(ROOT));assert source_after==before
 for p,h in package_input_hashes.items():assert sha(p)==h,p
 for p,h in package_source_hashes.items():assert sha(p)==h,p
 record.update(status='PASS_CHANNEL_PROFILE_CONTROL_TARGETS',finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
   main_source_manifest_after=source_after,private_copy_manifest_after=copy_after,
   main_sources_unchanged=True,private_sources_unchanged=True,package_inputs_unchanged=True,
   package_real_hdl_unchanged=True,private_copy_build_directory_after_exists=(COPY/'build').exists())
except BaseException as error:
 record.update(status='FAIL',error=repr(error),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
 if COPY.exists():
  record['private_copy_build_directory_after_exists']=(COPY/'build').exists()
  try:record['private_copy_manifest_after']=manifest(COPY,all_source_files(COPY))
  except Exception as e:record['private_copy_rehash_error']=repr(e)
 try:
  record['main_source_manifest_after']=manifest(ROOT,all_source_files(ROOT))
  record['main_sources_unchanged']=record['main_source_manifest_after']==before
 except Exception as e:record['main_source_rehash_error']=repr(e)
 finally:save()
 raise
save()
print(json.dumps({'status':record['status'],'audit':str(OUT/'controls-audit.json'),'commands':[(c['name'],c['status'],c['returncode'],c['seconds']) for c in record['commands']],'source_inputs':before['count'],'package_inputs':len(package_input_hashes),'real_hdl':len(package_source_hashes),'private_build_absent_after':not record['private_copy_build_directory_after_exists']},indent=2),flush=True)
