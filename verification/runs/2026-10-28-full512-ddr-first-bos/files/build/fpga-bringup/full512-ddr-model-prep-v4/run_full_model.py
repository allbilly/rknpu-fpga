#!/usr/bin/env python3
"""Offline-only preparation gate for the three-phase full512 DDR TinyStories trial.

Default mode only verifies frozen inputs and reports pending gates. Hardware
imports, lease acquisition and process/network operations occur only after the
trained-tile prerequisite, exact image review and separate root approval are
all bound in preparation.json.
"""
from __future__ import annotations
import argparse,datetime,fcntl,hashlib,json,os,pathlib,re,signal,socket,subprocess,sys,time

ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
PREP=PKG/'preparation.json';REVIEW=PKG/'image-review.json'
PREREQ=PKG/'trained-tile-prerequisite.json';APPROVAL=PKG/'execution-approval.json'
TEMPLATE=PKG/'program-template.tcl.in'
LEASE=pathlib.Path('/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock')
TARGET='localhost:3125/xilinx_tcf/Xilinx/80802026a77a01';DNA='004E544714C705C';IDCODE='23751093';SOURCE_TAG='5e99f881';SOURCE_SHA256='5e99f881eea21ff01bdf02f02435c7722a5ef78b820308727ac84f39edf0981f'
IMAGE_STATUS='PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE'
PREREQ_STATUS='ROOT_ACCEPTED_FULL512_CH1_DDR_TRAINED_TILE_FOR_MODEL'
APPROVAL_STATUS='ROOT_APPROVED_FULL512_DDR_TINYSTORIES_FULLMODEL_VOLATILE_TRIAL'
PHASES=(('one-complete-forward-position',1,''),('repeated-complete-forward-position',1,''),
        ('greedy32',32,'Once upon a time'))
VIVADO=pathlib.Path('/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/vivado_lab');HWSERVER=VIVADO.with_name('hw_server')
OWNED=[];QUIESCING=False

def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def need(ok,msg):
    if not ok:raise RuntimeError(msg)
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def load(path):return json.loads(pathlib.Path(path).read_text())
def write(path,value):pathlib.Path(path).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def literal(value):
    value=str(value);need(not any(c in value for c in '{}\\\r\n'),'Unsafe Tcl literal');return '{'+value+'}'
def interrupted(sig,frame):
    if not QUIESCING:raise InterruptedError('Full-model volatile trial interrupted by signal '+str(sig))

def check_frozen_inputs(prep):
    image=load(ROOT/prep['full512_image_preparation_path'])
    emission=load(ROOT/prep['full512_root_emission_review_path'])
    bindings=load(ROOT/prep['full512_root_bindings_path'])
    for key in ('full512_image_preparation','full512_root_emission_review','full512_root_bindings'):
        path=ROOT/prep[key+'_path'];expected=prep[key+'_sha256']
        need(path.is_file() and sha(path)==expected,key+' changed')
    manifest=image['hardware_source_manifest'];digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    need(digest==prep['source_manifest_sha256']==image['hardware_source_sha256'],'frozen full512 manifest changed')
    need(image['source_tag']==SOURCE_TAG==digest[:8] and bindings['source_tag']==SOURCE_TAG and emission['source_tag']==SOURCE_TAG,'source tag changed')
    need(image['expected_image_review_status']==IMAGE_STATUS and manifest['top']=='ypcb_ddr_dual_top' and
         manifest['part']=='xc7k480tffg1156-2','full512 image contract changed')
    for name,expected in manifest['files'].items():
        p=ROOT/name;need(p.is_file() and sha(p)==expected,'full512 source input changed: '+name)
    canonical_review_path=ROOT/prep['canonical_v12_image_review_path']
    canonical_audit_path=ROOT/prep['canonical_v12_bitfile_audit_path']
    canonical_review=load(canonical_review_path);canonical_audit=load(canonical_audit_path)
    need(sha(canonical_review_path)==prep['canonical_v12_image_review_sha256'] and
         sha(canonical_audit_path)==prep['canonical_v12_bitfile_audit_sha256'],'v12 canonical image review/audit changed')
    need(canonical_review['status']=='PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE' and
         canonical_audit['status']=='PASS_FULL512_DDR_BITFILE_AND_EMISSION_AUDIT_ONLY' and
         canonical_review['source_sha256']==digest and canonical_review['source_tag']==SOURCE_TAG and
         canonical_review['software_crc_validation']=='NOT_CHECKED' and canonical_audit['image_programming_admitted'] is False,
         'v12 candidate image facts/scope changed')
    need((prep['candidate_emitted_bitstream_path'],prep['candidate_emitted_bitstream_sha256'])==
         (canonical_review['bitstream']['path'],canonical_review['bitstream']['sha256']),
         'v12 candidate image path/hash differs from reviewed bitfile')
    candidate=prep['trained_tile_candidate']
    need(candidate['status']=='ROOT_REVIEWED_FULL512_CH1_DDR_TRAINED_TILE' and candidate['accepted'] is True and
         candidate['source_sha256']==digest and candidate['source_tag']==SOURCE_TAG and
         candidate['image_review_sha256']==prep['canonical_v12_image_review_sha256'] and
         candidate['bitstream_sha256']==prep['candidate_emitted_bitstream_sha256'],
         'actual trained-tile candidate review is not pinned to the v12 full512 image')
    candidate_receipts=[('run_report_path','run_report_sha256'),('worker_report_path','worker_report_sha256'),
        ('independent_audit_path','independent_audit_sha256'),('root_review_path','root_review_sha256'),
        ('independent_wire_review_path','independent_wire_review_sha256'),
        ('trained_trial_execution_review_path','trained_trial_execution_review_sha256')]
    for path_key,sha_key in candidate_receipts:
        path=ROOT/candidate[path_key];need(path.is_file() and sha(path)==candidate[sha_key],'trained-tile candidate receipt changed: '+path_key)
    candidate_run=load(ROOT/candidate['run_report_path']);candidate_worker=load(ROOT/candidate['worker_report_path'])
    candidate_audit=load(ROOT/candidate['independent_audit_path']);candidate_root=load(ROOT/candidate['root_review_path'])
    candidate_wire=load(ROOT/candidate['independent_wire_review_path']);candidate_exec=load(ROOT/candidate['trained_trial_execution_review_path'])
    need(candidate_run['status']=='PASS_FULL512_CH1_SCRATCH_AND_TRAINED_TILE_REQUIRES_ROOT_AUDIT' and
         candidate_run['flash_written'] is False and candidate_run['bitstream_sha256']==prep['candidate_emitted_bitstream_sha256'] and
         candidate_worker['status']=='PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT' and
         candidate_worker['memory_profile']=='ddr' and candidate_worker['hardware_accessed'] is True and
         candidate_worker['cpu_dense_fallback'] is False and
         candidate_audit['status']=='PASS_INDEPENDENT_DDR_TRAINED_TILE_RAW_WIRE_AUDIT_ONLY' and
         candidate_wire['status']=='PASS_INDEPENDENT_DDR_TRAINED_TILE_RAW_WIRE_AUDIT_ONLY' and
         candidate_root['accepted'] is True and candidate_root['source_sha256']==digest and
         candidate_root['image_review_sha256']==prep['canonical_v12_image_review_sha256'] and
         candidate_root['bitstream_sha256']==prep['candidate_emitted_bitstream_sha256'] and
         candidate_exec['status']=='ROOT_APPROVED_EXACT_FULL512_DDR_TRAINED_TRIAL_WITH_STANDALONE_IMPORT_CHECK',
         'actual v6 trained-tile candidate receipt/review changed')
    for name,expected in candidate['physical_artifacts'].items():
        path=pathlib.Path(name);need(path.is_file() and sha(path)==expected,'trained-tile candidate physical artifact changed: '+name)

    package=ROOT/prep['model_package_path'];package_report=load(package/'report.json')
    need(sha(package/'report.json')==prep['model_package_report_sha256'],'model package report changed')
    need(package_report['status']=='PREPARED_TINYSTORIES260K_STATIC_DENSE_LAYOUT_ONLY',
         'wrong frozen TinyStories package status')
    for name,row in package_report['files'].items():
        path=package/name;digest=row['sha256'] if isinstance(row,dict) else row
        need(path.is_file() and sha(path)==digest,'model package file changed: '+name)
    catalog=ROOT/prep['catalog_report_path']
    need(catalog.is_file() and sha(catalog)==prep['catalog_report_sha256'],'raw program catalog changed')
    catalog_report=load(catalog)
    need(catalog_report['status']=='PREPARED_ALL_TINYSTORIES_RAW_PROGRAMS_ONLY' and
         catalog_report['source_package_report_sha256']==prep['model_package_report_sha256'],
         'catalog no longer matches frozen model package')
    reference=ROOT/prep['oracle_reference_path'];reference_report=load(reference/'report.json')
    need(sha(reference/'report.json')==prep['oracle_reference_report_sha256'] and
         reference_report['status']=='PASS_CPU_FULL_TINYSTORIES_DONOR_POLICY_REFERENCE_ONLY' and
         reference_report['hardware_accessed'] is False,'CPU oracle reference report changed/scope changed')
    need(reference_report['positions_each']==32 and reference_report['dense_calls_each']==1152 and
         reference_report['logit_values_each']==16384,'original full oracle corpus changed')
    for name,digest in reference_report['artifacts'].items():
        path=reference/name;need(path.is_file() and sha(path)==digest,'full oracle artifact changed: '+name)
    for name,digest in prep['runtime_source_hashes'].items():
        path=ROOT/name;need(path.is_file() and sha(path)==digest,'runtime source changed: '+name)
    trained_vectors=ROOT/prep['trained_vectors_path']
    need(sha(trained_vectors/'report.json')==prep['trained_vectors_report_sha256'],'trained-tile vector report changed')
    for name,digest in prep['trained_vectors_files'].items():
        path=trained_vectors/name;need(path.is_file() and sha(path)==digest,'trained-tile vector changed: '+name)
    for name,digest in prep['private_source_hashes'].items():
        path=PKG/name;need(path.is_file() and sha(path)==digest,'private source changed: '+name)
    for name,digest in prep['tool_hashes'].items():
        path=pathlib.Path(name);need(path.is_file() and sha(path)==digest,'native tool binary changed: '+name)
    return image,emission,bindings,package_report,catalog_report,reference_report

def pending_gates(prep):
    review=load(REVIEW);prereq=load(PREREQ);approval=load(APPROVAL);g=[]
    if review.get('status')!=IMAGE_STATUS or prep.get('image_review_sha256') is None or sha(REVIEW)!=prep.get('image_review_sha256'):
        g.append('reviewed exact full512 CH1 DDR dual image and bound review hash')
    if review.get('bitstream',{}).get('path') is None or review.get('bitstream',{}).get('sha256') is None:
        g.append('reviewed emitted bitstream path and SHA-256')
    if prereq.get('status')!=PREREQ_STATUS or prereq.get('accepted') is not True or prep.get('trained_tile_prerequisite_sha256') is None or sha(PREREQ)!=prep.get('trained_tile_prerequisite_sha256'):
        g.append('qualified trained-tile physical receipt plus independent audit/root acceptance')
    if approval.get('status')!=APPROVAL_STATUS or approval.get('approved') is not True or prep.get('execution_approval_sha256') is None or sha(APPROVAL)!=prep.get('execution_approval_sha256'):
        g.append('separate root approval for the exact image and three-phase full-model trial')
    return g

def resource_sample():
    mem_text=pathlib.Path('/proc/meminfo').read_text();memory_psi=pathlib.Path('/proc/pressure/memory').read_text()
    cpu_psi=pathlib.Path('/proc/pressure/cpu').read_text()
    mem_kib=int(re.search(r'^MemAvailable:\s+(\d+)',mem_text,re.M).group(1))
    full=float(re.search(r'^full avg10=([0-9.]+)',memory_psi,re.M).group(1))
    some=float(re.search(r'^some avg10=([0-9.]+)',cpu_psi,re.M).group(1))
    return {'utc':utc(),'memavailable_kib':mem_kib,'memory_psi_full_avg10':full,'cpu_psi_some_avg10':some}

def offline_preflight():
    prep=load(PREP);need(prep['status']=='UNLAUNCHABLE_FULL512_DDR_TINYSTORIES_MODEL_PREPARATION','unexpected package state')
    check_frozen_inputs(prep);pending=pending_gates(prep)
    print(json.dumps({'status':'BLOCKED_PENDING_PREREQUISITES_AND_ROOT_APPROVAL' if pending else 'READY_REQUIRES_EXPLICIT_EXECUTION',
      'pending_gates':pending,'image_review_sha256':prep['image_review_sha256'],'bitstream_sha256':None,
      'trained_tile_prerequisite_sha256':prep['trained_tile_prerequisite_sha256'],
      'execution_approval_sha256':prep['execution_approval_sha256'],'hardware_accessed':False,'flash_written':False,
      'phase_order':[x[0] for x in PHASES],'scope':'offline-only preflight'} ,sort_keys=True));return 0

def recheck_model_bindings(prep,review_sha,bit_sha,prereq_sha):
    check_frozen_inputs(prep)
    review,prereq,approval,bit,current_review,current_bit,current_prereq=validate_admission(prep)
    need((current_review,current_bit,current_prereq)==(review_sha,bit_sha,prereq_sha),
         'image, trained prerequisite or root approval changed during the trial')
    return review,prereq,approval,bit

def physical_artifact_map(physical):
    return {str(p.relative_to(physical)):sha(p) for p in sorted(physical.rglob('*'))
            if p.is_file() and p != physical/'report.json'}

def process_group_members(pgid):
    rows=[]
    for entry in pathlib.Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            stat=(entry/'stat').read_text();fields=stat[stat.rfind(')')+2:].split()
            if len(fields)>=3 and int(fields[2])==pgid:rows.append({'pid':int(entry.name),'state':fields[0]})
        except (FileNotFoundError,PermissionError,ProcessLookupError,ValueError,IndexError):pass
    return rows
def live_group_members(pgid):return [x for x in process_group_members(pgid) if x['state'] not in {'Z','X'}]
def start_owned(argv,stdout,cwd,stderr=subprocess.STDOUT):
    mask={signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGALRM};old=signal.pthread_sigmask(signal.SIG_BLOCK,mask)
    try:
        child=subprocess.Popen(argv,cwd=cwd,stdout=stdout,stderr=stderr,start_new_session=True,
            preexec_fn=lambda:signal.pthread_sigmask(signal.SIG_SETMASK,old));OWNED.append(child);return child
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,old)
def stop_owned(child):
    if child is None:return {'pid':None,'returncode':None,'live_after':[],'zombies_after':[]}
    pgid=child.pid
    if live_group_members(pgid):
        try:os.killpg(pgid,signal.SIGTERM)
        except ProcessLookupError:pass
    deadline=time.monotonic()+10
    while live_group_members(pgid) and time.monotonic()<deadline:child.poll();time.sleep(.05)
    if live_group_members(pgid):
        try:os.killpg(pgid,signal.SIGKILL)
        except ProcessLookupError:pass
    while live_group_members(pgid):child.poll();time.sleep(.05)
    if child.poll() is None:
        try:child.wait(timeout=.2)
        except subprocess.TimeoutExpired:pass
    live=live_group_members(pgid);z=[x for x in process_group_members(pgid) if x['state'] in {'Z','X'}]
    need(not live,'owned worker process group remains live: '+repr(live))
    return {'pid':child.pid,'returncode':child.poll(),'live_after':live,'zombies_after':z}
def wait_owned_natural(child,timeout):
    code=child.wait(timeout=timeout);live=live_group_members(child.pid)
    if live:raise RuntimeError('owned bridge leader exited but descendants remain: '+repr(stop_owned(child)))
    need(code==0,'owned process exited nonzero: '+str(code))
    return {'pid':child.pid,'returncode':code,'live_after':[],'zombies_after':[x for x in process_group_members(child.pid) if x['state'] in {'Z','X'}]}
def cleanup_owned():
    out=[];seen=set()
    for child in reversed(OWNED):
        if child.pid not in seen:seen.add(child.pid);out.append(stop_owned(child))
    need(all(not x['live_after'] for x in out),'owned processes remain before releasing lease')
    return out

def hardware_admission(prep):
    lease=LEASE.open('r+b')
    try:
        need(os.fstat(lease.fileno()).st_ino==prep['lease_inode'],'shared lease inode changed')
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BaseException:lease.close();raise
    try:
        names={'hw_server','openocd','xsdb','openFPGALoader','fxload','xvcserver','xvc-server','xvc_server','vivado_lab'}
        controllers=[]
        for proc in pathlib.Path('/proc').iterdir():
            if proc.name.isdigit():
                try:
                    n=(proc/'comm').read_text().strip()
                    if n in names:controllers.append({'pid':int(proc.name),'name':n})
                except (FileNotFoundError,PermissionError,ProcessLookupError):pass
        need(not controllers,'other board controller present: '+repr(controllers))
        for port in (3121,3125,3721,3741,2542):
            with socket.socket() as s:s.settimeout(.2);need(s.connect_ex(('127.0.0.1',port))!=0,'debug port already active '+str(port))
        usb=subprocess.run(['lsusb','-d','03fd:0008'],capture_output=True,text=True,timeout=10)
        need(usb.returncode==0 and len(usb.stdout.strip().splitlines())==1,'expected one initialized DLC10')
        m=re.fullmatch(r'Bus (\d{3}) Device (\d{3}):.*',usb.stdout.strip());need(m,'cannot resolve DLC10 USB node')
        node='/dev/bus/usb/'+m[1]+'/'+m[2]
        owner=subprocess.run(['fuser',node],capture_output=True,text=True,timeout=10)
        need(owner.returncode==1 and not owner.stdout.strip(),'USB cable already owned')
        return lease,{'controllers':controllers,'usb':usb.stdout.strip(),'usb_node':node,'lease_inode':os.fstat(lease.fileno()).st_ino}
    except BaseException:
        try:fcntl.flock(lease,fcntl.LOCK_UN)
        finally:lease.close()
        raise

def parse_receipt(text):
    rows=text.splitlines();need(rows,'empty programmer receipt');pairs=[]
    for row in rows:
        f=row.split('\t');need(len(f)==2 and f[0] and f[1],'malformed programmer receipt row '+repr(row));pairs.append(f)
    keys=[x[0] for x in pairs];need(len(keys)==len(set(keys)),'duplicate programmer receipt key');return dict(pairs)

def validate_model_image_review(prep,review,canonical,canonical_path,review_sha):
    """Bind the model-specific catalog review to the canonical audited hardware image."""
    need(review['status']==IMAGE_STATUS and prep['image_review_sha256']==review_sha,'model-specific image review is not admitted/bound')
    need(review.get('canonical_hardware_review_path')==prep['canonical_v12_image_review_path'] and
         review.get('canonical_hardware_review_sha256')==sha(canonical_path),'model review canonical image binding changed')
    need(canonical['status']=='PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE' and
         prep['canonical_v12_image_review_sha256']==sha(canonical_path),'canonical hardware image review is not accepted')
    for key in ('source_sha256','source_manifest_sha256','source_tag','usr_access','top','part','target','expected_dna_port','expected_raw_idcode',
                'memory_profile','selected_physical_channel','product_dsps','total_dsps','bram_blocks','programming_scope','flash_authorized'):
        need(review.get(key)==canonical.get(key),'model review differs from canonical hardware review: '+key)
    need(review['source_sha256']==SOURCE_SHA256 and review['usr_access']==SOURCE_TAG and
         review.get('catalog_sha256')==prep['catalog_report_sha256'],'model-specific source/catalog binding changed')
    need(review['bitstream']==canonical['bitstream'],'model-specific bitstream differs from canonical image')
    bit=pathlib.Path(review['bitstream']['path']);bit_sha=review['bitstream']['sha256']
    need(bit.is_absolute() and bit.is_file() and sha(bit)==bit_sha==prep['candidate_emitted_bitstream_sha256'],
         'reviewed bitstream bytes differ from the canonical image')
    need(review.get('flash_authorized') is False and review.get('bound_files'),'model image review has invalid scope/empty file closure')
    for name,digest in review['bound_files'].items():need(pathlib.Path(name).is_file() and sha(name)==digest,'model-reviewed file changed: '+name)
    canonical_key=str(canonical_path)
    need(review['bound_files'].get(canonical_key)==sha(canonical_path),
         'model-specific review does not bind the canonical hardware review file')
    return bit,bit_sha

def validate_admission(prep):
    gates=pending_gates(prep);need(not gates,'model hardware gates remain pending: '+', '.join(gates))
    review=load(REVIEW);prereq=load(PREREQ);approval=load(APPROVAL)
    review_sha=sha(REVIEW);canonical_path=ROOT/prep['canonical_v12_image_review_path'];canonical=load(canonical_path)
    bit,bit_sha=validate_model_image_review(prep,review,canonical,canonical_path,review_sha)
    prereq_sha=sha(PREREQ)
    validate_trained_tile_prerequisite(prep,prereq,sha(canonical_path),bit_sha,prereq_sha)
    need(approval['status']==APPROVAL_STATUS and approval['approved'] is True and prep['execution_approval_sha256']==sha(APPROVAL),'separate root approval not bound')
    for k,v in {'trained_tile_prerequisite_sha256':prereq_sha,'image_review_sha256':review_sha,'bitstream_sha256':bit_sha,
      'source_sha256':SOURCE_SHA256,'usr_access':SOURCE_TAG,'target':TARGET,'expected_dna_port':DNA,'expected_raw_idcode':IDCODE,
      'memory_profile':'ddr','selected_physical_channel':1,'programming_scope':'volatile-sram'}.items():need(approval.get(k)==v,'execution approval binding changed '+k)
    need(approval.get('flash_authorized') is False,'execution approval allows flash')
    return review,prereq,approval,bit,review_sha,bit_sha,prereq_sha

def validate_trained_tile_prerequisite(prep,prereq,canonical_review_sha,bit_sha,prereq_sha):
    """Require wrapper plus each original physical, wire-audit, and root-review receipt."""
    need(prereq['status']==PREREQ_STATUS and prereq['accepted'] is True and
         prep['trained_tile_prerequisite_sha256']==prereq_sha,'trained prerequisite wrapper not root accepted')
    need(prereq['image_review_sha256']==canonical_review_sha and prereq['bitstream_sha256']==bit_sha and
         prereq['source_sha256']==SOURCE_SHA256,'trained tile prerequisite bound to another source/image')
    paths={key:pathlib.Path(prereq[key]) for key in
        ('trained_tile_run_report_path','trained_tile_worker_report_path','trained_tile_independent_audit_path','root_prerequisite_review_path')}
    hashes={'trained_tile_run_report_path':'trained_tile_run_report_sha256',
            'trained_tile_worker_report_path':'trained_tile_worker_report_sha256',
            'trained_tile_independent_audit_path':'trained_tile_independent_audit_sha256',
            'root_prerequisite_review_path':'root_prerequisite_review_sha256'}
    receipts={}
    for field,path in paths.items():
        need(path.is_absolute() and path.is_file(),'required trained-tile prerequisite receipt missing: '+field)
        expected=prereq[hashes[field]]
        need(expected is not None and sha(path)==expected,'trained-tile prerequisite hash mismatch: '+field)
        receipts[field]=load(path)
    run=receipts['trained_tile_run_report_path']
    worker=receipts['trained_tile_worker_report_path']
    audit=receipts['trained_tile_independent_audit_path']
    root_review=receipts['root_prerequisite_review_path']
    need(run.get('status')=='PASS_FULL512_CH1_SCRATCH_AND_TRAINED_TILE_REQUIRES_ROOT_AUDIT' and
         run.get('hardware_programmed') is True and run.get('flash_written') is False and
         run.get('bitstream_sha256')==bit_sha and run.get('image_review_sha256')==canonical_review_sha and
         run.get('source_manifest_sha256')==SOURCE_SHA256 and
         run.get('trained_worker_report_sha256')==prereq['trained_tile_worker_report_sha256'],
         'underlying trained-tile physical receipt is missing, incomplete or bound to another image')
    need(worker.get('status')=='PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT' and
         worker.get('memory_profile')=='ddr' and worker.get('hardware_accessed') is True and
         worker.get('flash_written') is False and worker.get('cpu_dense_fallback') is False and
         worker.get('vectors_report_sha256')==prep['trained_vectors_report_sha256'],
         'underlying trained-tile worker report is missing/incomplete')
    audit_hardware_accessed=audit.get('hardware_accessed')
    need(audit.get('status')=='PASS_INDEPENDENT_DDR_TRAINED_TILE_RAW_WIRE_AUDIT_ONLY' and
         ('hardware_accessed' not in audit or audit_hardware_accessed is False) and
         audit.get('image_target_route_qualified_by_this_audit') is False and
         audit.get('worker_report_sha256')==prereq['trained_tile_worker_report_sha256'] and
         audit.get('vector_report_sha256')==prep['trained_vectors_report_sha256'],
         'underlying trained-tile raw-wire audit is missing, incomplete or bound to different bytes')
    need(root_review.get('status')=='ROOT_REVIEWED_FULL512_CH1_DDR_TRAINED_TILE' and
         root_review.get('trained_tile_run_report_sha256')==prereq['trained_tile_run_report_sha256'] and
         root_review.get('trained_tile_worker_report_sha256')==prereq['trained_tile_worker_report_sha256'] and
         root_review.get('trained_tile_independent_audit_sha256')==prereq['trained_tile_independent_audit_sha256'] and
         root_review.get('image_review_sha256')==canonical_review_sha and root_review.get('bitstream_sha256')==bit_sha and
         root_review.get('source_sha256')==SOURCE_SHA256 and root_review.get('accepted') is True,
         'underlying trained-tile root review is missing or not bound to actual receipts/image')
    return receipts

def phase_specs():return [dict(name=n,steps=s,prompt=p) for n,s,p in PHASES]
def worker_argv(prep,phase,out):
    return [sys.executable,str(ROOT/'tools/tinystories/run_model.py'),'--package',str(ROOT/prep['model_package_path']),
      '--backend','jtag','--memory-profile','ddr','--port','3721','--catalog',str(ROOT/prep['catalog_report_path']),
      '--catalog-sha256',prep['catalog_report_sha256'],'--min-mem-available-mib','2048','--memory-wait-budget-seconds','900',
      '--steps',str(phase['steps']),'--prompt',phase['prompt'],'--quit-bridge','--out',str(out)]
def audit_argv(phase,physical,audit_path,prep):
    return [sys.executable,str(ROOT/'tools/tinystories/audit_model.py'),'--run',str(physical.parent),'--package',str(ROOT/prep['model_package_path']),
      '--catalog',str(ROOT/prep['catalog_report_path']),'--reference',str(ROOT/prep['oracle_reference_path']),
      '--phase',phase['name'],'--memory-profile','ddr','--out',str(audit_path)]

def run_public_phase_audit(index,phase,physical,prep,logs):
    audit_dir=PKG/'phase-audits'/phase['name'];audit_dir.mkdir(parents=True,exist_ok=False)
    audit_path=audit_dir/'audit.json'
    snapshot_dir=PKG/'phase-report-snapshots';snapshot_dir.mkdir(exist_ok=True)
    snapshot=snapshot_dir/(phase['name']+'.report.json')
    snapshot.write_bytes((physical/'report.json').read_bytes())
    argv=audit_argv(phase,physical,audit_path,prep)
    command={'phase':phase['name'],'argv':argv,'started_utc':utc(),
             'parent_report_snapshot_path':str(snapshot),'parent_report_sha256_at_audit':sha(snapshot)}
    write(audit_dir/'command.json',command)
    with (audit_dir/'stdout.log').open('x') as out,(audit_dir/'stderr.log').open('x') as err:
        child=start_owned(argv,out,ROOT,err);command['pid']=child.pid;command['pgid']=child.pid
        write(audit_dir/'command.json',command)
        code=child.wait(timeout=300)
    process_result=wait_owned_natural(child,10)
    need(code==0,'independent public audit_model failed: '+phase['name'])
    result=load(audit_path)
    expected=('PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_BOS_CONTROL_ONLY' if index==0 else
              'PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_REPEATED_BOS_CONTROL_ONLY' if index==1 else
              'PASS_INDEPENDENT_PHYSICAL_DDR_TINYSTORIES_32_POSITION_RAW_WIRE_MODEL_AUDIT')
    need(result['status']==expected and result['memory_profile']=='ddr' and result['phase']==phase['name'] and
         result['positions']==phase['steps'] and result['hardware_accessed'] is False and result['flash_written'] is False,
         'audit_model rejected exact phase contract: '+phase['name'])
    command.update(status='PASS',returncode=code,finished_utc=utc(),audit_sha256=sha(audit_path),
                   audited_parent_report_sha256=result['physical_report_sha256'],process_group=process_result)
    write(audit_dir/'command.json',command)
    return result,command

def main(argv=None):
    global QUIESCING
    parser=argparse.ArgumentParser();parser.add_argument('--execute-volatile-sram',action='store_true');args=parser.parse_args(argv)
    prep=load(PREP);need(prep['status']=='UNLAUNCHABLE_FULL512_DDR_TINYSTORIES_MODEL_PREPARATION','package not in unlaunchable state')
    check_frozen_inputs(prep)
    if not args.execute_volatile_sram:return offline_preflight()
    review,prereq,approval,bit,review_sha,bit_sha,prereq_sha=validate_admission(prep)
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP,signal.SIGALRM):signal.signal(sig,interrupted)
    from tools.host.native_link import render_bridge
    # The unchanged jtag worker owns the raw transport and all learned dense jobs.
    from tools.tinystories.progress import require_memory
    require_memory(4096)
    run=PKG/'physical-test';need(not run.exists(),'fresh physical-test path required');run.mkdir()
    (run/'image-review.json').write_bytes(REVIEW.read_bytes())
    need(sha(run/'image-review.json')==review_sha,'physical-run image-review copy differs from admitted review')
    record={'status':'RUNNING_AUTHORIZED_VOLATILE_USER2_TEST','started_utc':utc(),
      'image_review_sha256':review_sha,'bitstream_sha256':bit_sha,'part':review['part'],'top':review['top'],'target':TARGET,
      'memory_profile':'ddr','selected_physical_channel':1,'lease':str(LEASE),'hardware_programmed':False,'flash_written':False,
      'loads':[],'tests':[],'hardware_accessed':False,'cpu_dense_fallback':False,'full32_positions_accepted':False,
      'trained_tile_prerequisite_sha256':prereq_sha,'model_package_report_sha256':prep['model_package_report_sha256'],
      'catalog_sha256':prep['catalog_report_sha256'],'oracle_reference_report_sha256':prep['oracle_reference_report_sha256']}
    physical=run/'physical-tests';physical.mkdir();write(physical/'report.json',record)
    lease=server=program=bridge=worker=auditor=None;logs=[];load_dir=physical/'load-1';
    parent_finalized=False
    try:
        lease,admission=hardware_admission(prep);record['admission']=admission
        check_frozen_inputs(prep);review,prereq,approval,bit,review_sha,bit_sha,prereq_sha=validate_admission(prep)
        sample=resource_sample();need(sample['memory_psi_full_avg10']<1.0,'memory PSI gate failed before hw_server')
        record['resource_samples']=[{'stage':'before-hw-server','sample':sample}]
        server_log=(physical/'hw-server.log').open('x');logs.append(server_log)
        server=start_owned([str(HWSERVER),'-s','tcp::3125'],server_log,physical)
        record.update(hardware_accessed=True,hw_server_pid=server.pid);write(physical/'report.json',record)
        deadline=time.monotonic()+20
        while True:
            need(server.poll() is None,'owned hw_server exited')
            with socket.socket() as s:s.settimeout(.2);connected=s.connect_ex(('127.0.0.1',3125))==0
            if connected:break
            need(time.monotonic()<deadline,'hw_server startup timeout');time.sleep(.1)

        # Exactly one volatile load, before any model phase.
        load_dir.mkdir();text=TEMPLATE.read_text()
        vals={'TARGET':TARGET,'BITSTREAM':bit,'RECEIPT':load_dir/'program.tsv','USR_ACCESS':SOURCE_TAG,'BITSTREAM_SHA':bit_sha}
        for k,v in vals.items():
            marker='@'+k+'@';need(text.count(marker)==1,'program template marker changed '+k);text=text.replace(marker,literal(v))
        require_memory(4096);tcl=load_dir/'program.tcl';tcl.write_text(text)
        check_frozen_inputs(prep);review,prereq,approval,bit,review_sha,bit_sha,prereq_sha=validate_admission(prep)
        native_argv=[str(VIVADO),'-mode','batch','-source',str(tcl),'-log',str(load_dir/'vivado.log'),'-journal',str(load_dir/'vivado.jou')]
        command={'argv':native_argv,'started_utc':utc(),'program_tcl_sha256':sha(tcl),'bitstream_sha256_before':sha(bit),'flash_written':False}
        write(load_dir/'command.json',command)
        program_log=(load_dir/'stdout.log').open('x');logs.append(program_log);record['hardware_programming_may_have_occurred']=True;write(physical/'report.json',record)
        program=start_owned(native_argv,program_log,load_dir);command.update(pid=program.pid,pgid=program.pid);write(load_dir/'command.json',command)
        try:code=program.wait(timeout=180)
        except subprocess.TimeoutExpired:
            stop=stop_owned(program);command.update(returncode=program.returncode,finished_utc=utc(),timeout=True,cleanup=stop);write(load_dir/'command.json',command);raise
        command.update(returncode=code,finished_utc=utc(),timeout=False);write(load_dir/'command.json',command);need(code==0,'volatile image load command failed')
        rows=(load_dir/'program.tsv').read_text().splitlines();pairs=[]
        for line in rows:
            f=line.split('\t');need(len(f)==2 and f[0] and f[1],'malformed native programming receipt');pairs.append(f)
        keys=[x[0] for x in pairs];need(len(keys)==len(set(keys)),'duplicate native programming receipt key');native=dict(pairs)
        expected={'TARGET':TARGET,'DNA_PORT':DNA,'IDCODE_BEFORE':IDCODE,'IDCODE_AFTER':IDCODE,'INIT_COMPLETE':'1','DONE':'1',
          'TCK_HZ':'3000000','PROGRAM_RETURNED':'1','PROGRAMMED':'1','CLEANUP':'1','PASS':'1','PROGRAM_FILE':str(bit),'BITSTREAM_SHA256':bit_sha}
        need(set(native)==set(expected)|{'USR_ACCESS'} and all(native.get(k)==v for k,v in expected.items()) and native.get('USR_ACCESS','').lower()==SOURCE_TAG,
             'program receipt identity/INIT/DONE/source tag mismatch')
        load_record={'status':'PASS','started_utc':command['started_utc'],'finished_utc':command['finished_utc'],
          'hardware_programmed':True,'flash_written':False,'bitstream_sha256':bit_sha,'source_sha256':SOURCE_SHA256,
          'image_review_sha256':review_sha,'trained_tile_prerequisite_sha256':prereq_sha,'native':native,
          'command':command}
        write(load_dir/'load.json',load_record);record.update(hardware_programmed=True,loads=[{'name':'load-1','status':'PASS','receipt_sha256':sha(load_dir/'load.json')}])
        sample=resource_sample();need(sample['memory_psi_full_avg10']<1.0,'memory PSI gate failed after load')
        record['resource_samples'].append({'stage':'after-load','sample':sample})
        write(physical/'report.json',record);recheck_model_bindings(prep,review_sha,bit_sha,prereq_sha)

        for index,phase in enumerate(phase_specs()):
            sample=resource_sample();record.setdefault('resource_samples',[]).append({'phase':phase['name'],'sample':sample})
            need(sample['memory_psi_full_avg10']<1.0,'memory PSI gate failed before phase '+phase['name'])
            recheck_model_bindings(prep,review_sha,bit_sha,prereq_sha)
            phase_dir=physical/phase['name'];phase_dir.mkdir();jobs=phase_dir/'jobs';ready=phase_dir/'bridge'/'ready.txt'
            bridge,bridge_ready=launch_phase_bridge(phase_dir,render_bridge,record,physical,logs)
            cmd=worker_argv(prep,phase,jobs);cmdrec={'phase':phase['name'],'argv':cmd,'started_utc':utc(),
              'model_package_report_sha256':prep['model_package_report_sha256'],'catalog_sha256':prep['catalog_report_sha256'],
              'reference_report_sha256':prep['oracle_reference_report_sha256'],'bridge_ready_sha256':sha(bridge_ready)}
            write(phase_dir/'command.json',cmdrec)
            with (phase_dir/'worker.stdout.log').open('x') as out,(phase_dir/'worker.stderr.log').open('x') as err:
                worker=start_owned(cmd,out,ROOT,err);cmdrec['worker_pid']=worker.pid;cmdrec['worker_pgid']=worker.pid;write(phase_dir/'command.json',cmdrec)
                code=worker.wait(timeout=14400)
            worker_exit=worker.returncode;worker=None
            # run_model's --quit-bridge must stop this phase's bridge naturally before the next phase starts.
            bridge_result=wait_owned_natural(bridge,20);bridge_exit=bridge_result['returncode'];bridge=None
            need(code==0 and bridge_exit==0,'phase worker or bridge failed: '+phase['name'])
            child=load(jobs/'report.json')
            need(child['status']=='PASS_PHYSICAL_HYBRID_MODEL_EXECUTION_REQUIRES_INDEPENDENT_AUDIT' and
                 child['bridge_quit_ack'] is True and child['memory_profile']=='ddr' and child['hardware_accessed'] is True and
                 child['flash_written'] is False and child['cpu_dense_fallback'] is False,
                 'phase worker status/scope failed: '+phase['name'])
            need(child['steps']==phase['steps'] and child['prompt']==phase['prompt'] and
                 child['completed_positions']==phase['steps'] and child['completed_projections']==phase['steps']*36 and
                 child['raw_jobs']==phase['steps']*232 and child['raw_completed_tasks']==phase['steps']*348,
                 'phase workload contract changed: '+phase['name'])
            cmdrec.update(status='PASS',returncode=code,worker_exit=worker_exit,bridge_exit=bridge_exit,finished_utc=utc(),
                worker_report_sha256=sha(jobs/'report.json'),owned_bridge_exit=bridge_result)
            write(phase_dir/'command.json',cmdrec)
            summary={'name':phase['name'],'status':'PASS','forward_positions':phase['steps'],
                     'raw_jobs':child['raw_jobs'],'report_sha256':sha(jobs/'report.json'),
                     'worker_exit':worker_exit,'bridge_exit':bridge_exit}
            record['tests'].append(summary);record['owned_worker_exit']=worker_exit;record['owned_bridge_exit']=bridge_exit
            if phase['name']==PHASES[-1][0]:
                # The full-model audit requires final PASS status and every owned hardware process exited.
                server_result=stop_owned(server);server=None;record['owned_hw_server_exit']=server_result['returncode']
                record['owned_hw_server_cleanup']=server_result
                record.update(status='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT',
                    forward_positions=32,full32_positions_accepted=False,full512_ddr_integrated=False,
                    trained_tile_prerequisite_sha256=prereq_sha,image_review_sha256=review_sha,bitstream_sha256=bit_sha,
                    flash_written=False,pcie_tested=False,finished_utc=utc())
                record['artifacts']=physical_artifact_map(physical)
                record['owned_process_groups']=cleanup_owned()
                record['owned_process_groups_absent_before_final_audit']=True
                write(physical/'report.json',record);parent_finalized=True
            else:
                record['artifacts']=physical_artifact_map(physical)
                write(physical/'report.json',record)

            audit_result,audit_command=run_public_phase_audit(index,phase,physical,prep,logs)
            audit_index_path=PKG/'phase-audit-index.json'
            audit_index=load(audit_index_path) if audit_index_path.exists() else {'schema':'full512-ddr-tinystories-phase-audits-v1','phases':[]}
            audit_index['phases'].append({'phase':phase['name'],'status':audit_result['status'],
                'audit_path':str(PKG/'phase-audits'/phase['name']/'audit.json'),'audit_sha256':sha(PKG/'phase-audits'/phase['name']/'audit.json'),
                'audit_command_path':str(PKG/'phase-audits'/phase['name']/'command.json'),
                'audit_command_sha256':sha(PKG/'phase-audits'/phase['name']/'command.json'),
                'parent_report_snapshot_path':audit_command['parent_report_snapshot_path'],
                'parent_report_snapshot_sha256':sha(audit_command['parent_report_snapshot_path']),
                'worker_report_sha256':sha(jobs/'report.json')})
            write(audit_index_path,audit_index)
            if index<2:
                summary.update(audit_status=audit_result['status'],audit_sha256=sha(physical/phase['name']/'audit.json'),
                    audit_parent_report_sha256=audit_result['physical_report_sha256'],
                    parent_report_snapshot_path=audit_command['parent_report_snapshot_path'],
                    parent_report_snapshot_sha256=sha(audit_command['parent_report_snapshot_path']))
                write(physical/'report.json',record)
            recheck_model_bindings(prep,review_sha,bit_sha,prereq_sha)

        # Root report/artifact map is finalized only after all three audit_model phases pass.
        final_artifacts=physical_artifact_map(physical)
        persisted=load(physical/'report.json')
        need(final_artifacts==persisted.get('artifacts'),
             'physical artifact map changed after greedy32 audit; parent report remains immutable after acceptance')
        need(len(record['tests'])==3 and [x['name'] for x in record['tests']]==[x[0] for x in PHASES],
             'physical phase sequence incomplete/reordered')
        need(record['status']=='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT',
             'three phase audits did not all pass')
    except BaseException as error:
        failed_at=utc()
        record.update(status='FAIL_USER2_PHYSICAL_TEST',error=repr(error),failure_utc=failed_at,finished_utc=failed_at)
        parent_finalized=False
        raise
    finally:
        QUIESCING=True
        final_owned_groups=cleanup_owned()
        if not parent_finalized:
            record['final_owned_process_groups']=final_owned_groups
            record['owned_process_groups_absent_before_lease_release']=True
        for log in logs:
            try:log.close()
            except BaseException:pass
        record['finished_utc']=record.get('finished_utc',utc())
        if run.exists() and not parent_finalized:
            record['artifacts']=physical_artifact_map(physical)
            write(physical/'report.json',record)
        if lease is not None:fcntl.flock(lease,fcntl.LOCK_UN);lease.close()
    return record

def launch_phase_bridge(phase_dir,render_bridge,record,physical,logs):
    bridge_dir=phase_dir/'bridge';bridge_dir.mkdir()
    ready=bridge_dir/'ready.txt';script=bridge_dir/'bridge.tcl'
    script.write_text(render_bridge(TARGET,'localhost:3125',SOURCE_TAG,ready,3721))
    argv=[str(VIVADO),'-mode','batch','-source',str(script),'-log',str(bridge_dir/'vivado.log'),'-journal',str(bridge_dir/'vivado.jou')]
    log=(bridge_dir/'bridge-stdout.log').open('x');logs.append(log);child=start_owned(argv,log,bridge_dir)
    record.setdefault('phase_bridges',[]).append({'pid':child.pid,'phase':phase_dir.name,'argv':argv,'script_sha256':sha(script)})
    write(physical/'report.json',record)
    deadline=time.monotonic()+90
    while not ready.exists():
        need(child.poll() is None,'owned bridge exited before READY: '+phase_dir.name)
        need(time.monotonic()<deadline,'native bridge READY timeout: '+phase_dir.name);time.sleep(.1)
    need(ready.read_text().strip()=='PASS_AUDITED_NATIVE_USER2_BRIDGE_READY','wrong phase bridge READY')
    return child,ready

def main_entry():
    try:
        result=main()
        if type(result) is int:return result
        status=result.get('status','') if isinstance(result,dict) else ''
        print(json.dumps({'status':status,'report':str(PKG/'physical-test'/'physical-tests'/'report.json'),
                          'flash_written':False,'hardware_accessed':bool(result.get('hardware_accessed',False))}),flush=True)
        return 0 if status=='PASS_PHYSICAL_TINYSTORIES_FULL_MODEL_REQUIRES_INDEPENDENT_AUDIT' else 1
    except RuntimeError as e:
        run=PKG/'physical-test';physical=run/'physical-tests';report_path=physical/'report.json'
        summary={'status':'BLOCKED_OR_FAILED','error':str(e),'report':str(report_path)}
        if not run.exists():
            summary.update(hardware_accessed=False,hardware_programmed=False,
                           hardware_programming_may_have_occurred=False,flash_written=False,
                           physical_receipt_state='NO_PHYSICAL_RUN_DIRECTORY')
        elif report_path.is_file():
            try:
                receipt=load(report_path)
                summary['status']=receipt.get('status','BLOCKED_OR_FAILED')
                summary['physical_receipt_state']='READABLE'
                for key in ('hardware_accessed','hardware_programmed','hardware_programming_may_have_occurred','flash_written'):
                    summary[key]=receipt.get(key) if type(receipt.get(key)) is bool else None
                summary['physical_failure_utc']=receipt.get('failure_utc')
                summary['physical_error']=receipt.get('error')
            except (OSError,ValueError,TypeError) as receipt_error:
                summary.update(hardware_accessed=None,hardware_programmed=None,
                    hardware_programming_may_have_occurred=None,flash_written=None,
                    physical_receipt_state='UNREADABLE',physical_receipt_error=repr(receipt_error))
        else:
            summary.update(hardware_accessed=None,hardware_programmed=None,
                hardware_programming_may_have_occurred=None,flash_written=None,
                physical_receipt_state='MISSING_AFTER_RUN_DIRECTORY_CREATED')
        print(json.dumps(summary,sort_keys=True),file=sys.stderr,flush=True);return 2

if __name__=='__main__':raise SystemExit(main_entry())
