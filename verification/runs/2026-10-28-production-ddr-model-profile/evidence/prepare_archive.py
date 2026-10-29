#!/usr/bin/env python3
"""Preserve selected source/text evidence for production dual-DDR profile v9."""
from __future__ import annotations
import datetime, gzip, hashlib, json, pathlib, shutil, sys

ROOT=pathlib.Path('/home/fedora/rknpu-fpga')
AUDITORS=ROOT/'build/production-model-auditors'
V9=AUDITORS/'current-v9'; WS=V9/'workspace'; V8=AUDITORS/'current-v8'
DEST=ROOT/'verification/runs/2026-10-28-production-ddr-model-profile'
PACKER=pathlib.Path(__file__).resolve(); BLOCK=1024*1024
TEXT_SUFFIXES={'.log','.json','.txt','.hex','.jsonl','.partial'}

def need(ok,msg):
    if not ok: raise RuntimeError(msg)
def sha(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(BLOCK),b''):h.update(b)
    return h.hexdigest()
def load(path):return json.loads(pathlib.Path(path).read_text())
def repo_rel(path):
    p=pathlib.Path(path).resolve()
    try:return p.relative_to(ROOT).as_posix()
    except ValueError:return str(p)
def is_text(path):
    with pathlib.Path(path).open('rb') as f:
        for b in iter(lambda:f.read(BLOCK),b''):
            if b'\0' in b or any(x<32 and x not in (9,10,12,13) for x in b):return False
    return True
def copy_payload(src,dst,compress):
    src=pathlib.Path(src);dst=pathlib.Path(dst);dst.parent.mkdir(parents=True,exist_ok=True)
    hs=hashlib.sha256();source_bytes=0
    with src.open('rb') as inf,dst.open('wb') as rawout:
        if compress:
            with gzip.GzipFile(filename='',mode='wb',fileobj=rawout,compresslevel=9,mtime=0) as zout:
                for block in iter(lambda:inf.read(BLOCK),b''):
                    hs.update(block);source_bytes+=len(block);zout.write(block)
        else:
            for block in iter(lambda:inf.read(BLOCK),b''):
                hs.update(block);source_bytes+=len(block);rawout.write(block)
    return hs.hexdigest(),source_bytes,sha(dst),dst.stat().st_size

def hash_payload(path,encoding):
    h=hashlib.sha256();size=0
    with pathlib.Path(path).open('rb') as inf:
        if encoding=='gzip-mtime0-level9':
            with gzip.GzipFile(fileobj=inf,mode='rb') as source:
                for block in iter(lambda:source.read(BLOCK),b''):h.update(block);size+=len(block)
        else:
            for block in iter(lambda:inf.read(BLOCK),b''):h.update(block);size+=len(block)
    return h.hexdigest(),size

need(not DEST.exists(),f'archive destination must be fresh: {DEST}')
prod=load(V9/'report.json'); review=load(V9/'root-review.json'); launch=load(V9/'launch.json')
need(prod['status']=='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_V9_ONLY','v9 producer is not terminal PASS')
need(review['status']=='PASS_INDEPENDENT_V9_SOURCE_NATIVE_AND_COMPLETE_HOST_RECEIPT_REVIEW_ONLY','independent v9 review is not PASS')
need(prod['source_inputs']==prod['copied_inputs'] and len(prod['source_inputs'])==1090,'v9 source/copy closure changed')
need(review['source_sha256']==prod['source_revision_manifest']['sha256'] and
     review['recursive_source_sha256']==prod['private_copy_manifest_sha256'] and
     review['complete_source_files']==1090,'v9 source review binding mismatch')
need(review['producer_sha256']==sha(V9/'report.json') and
     launch['worker_report_sha256']==sha(V9/'report.json'),'v9 producer report hash not bound by review/launch')
need(review['software_ddr_control_methods']==58 and review['dual_control_commands']==6,'v9 DDR/dual-control coverage changed')
need(review['numerical_or_ddr_composition_qualified_by_default_make'] is False and review['hardware_accessed'] is False,'v9 scope widened')
need(launch['systemd_scope_show']==['ActiveState=inactive','Result=success'],'v9 scope not terminal-success')
need(all(c['status']=='PASS' and c['returncode']==0 for c in prod['commands']),'v9 command failure not preserved')

sources={}
def add(path,role,expected=None,dest_hint=None,compress=True):
    p=pathlib.Path(path).resolve();need(p.is_file(),f'missing selected file: {p}')
    actual=sha(p)
    if expected is not None:need(actual==expected,f'hash mismatch: {p}')
    need(is_text(p),f'refusing non-text archive payload: {p}')
    key=str(p)
    if key in sources:
        need(sources[key]['sha256']==actual,'same source changed during selection')
        if role not in sources[key]['roles']:sources[key]['roles'].append(role)
        return
    if dest_hint is None:
        try:dest_hint='workspace/'+p.relative_to(WS).as_posix()
        except ValueError:dest_hint='evidence/'+repo_rel(p)
    sources[key]={'path':p,'sha256':actual,'bytes':p.stat().st_size,'roles':[role],
                  'archive_path':dest_hint,'compress':bool(compress and p.stat().st_size>16384)}

# Preserve the exact 1,090-file source copy that the PASS v9 runner hashed.
for relpath,expected in sorted(prod['source_inputs'].items()):
    add(WS/relpath,'exact private v9 workspace input from source_inputs/copy_inputs',expected)

# Producer, independent review, launch metadata and actual build logs.
for p,role in [
    (V9/'report.json','v9 private complete make-test producer report'),
    (V9/'root-review.json','independent v9 source/native/receipt review'),
    (V9/'root_review.py','independent v9 reviewer implementation'),
    (V9/'run.py','v9 private production runner'),
    (V9/'launch.json','v9 argv/PIDs/cgroup/admission/terminal metadata'),
    (V9/'admission.json','three actual v9 resource admission samples'),
    (V9/'generated_check.stdout.log','generated-check stdout'),
    (V9/'generated_check.stderr.log','generated-check stderr'),
    (V9/'production_test.stdout.log','serial make test stdout'),
    (V9/'production_test.stderr.log','serial make test stderr')]:add(p,role)

# Keep the previous reviewed v8 parent reports as history only; v9 remains the
# sole current PASS. Preserve its launch record for provenance as well.
for p,role in [(V8/'report.json','parent v8 producer history'),
                (V8/'root-review.json','parent v8 independent review history'),
                (V8/'launch.json','parent v8 launch history')]:add(p,role,dest_hint='history/current-v8/'+p.name)

# Exact five native/core reports and all textual logs/readbacks from their
# suites. Generated compiler trees, simulators and object files are excluded.
core=[('build/numeric_report.json','numeric model test report'),('build/rtl/report.json','RTL simulation report'),
      ('build/iverilog/report.json','Icarus integration report'),('build/cmac_iverilog/report.json','CMAC Icarus raw-path report'),
      ('build/cmac_verilator/report.json','CMAC Verilator raw-path report')]
for relpath,role in core:add(WS/relpath,role)
for rel_dir in ('build/rtl','build/iverilog','build/cmac_iverilog','build/cmac_verilator'):
    base=WS/rel_dir
    if not base.exists():continue
    for p in sorted(base.rglob('*')):
        if not p.is_file() or any(part.startswith('obj') for part in p.relative_to(base).parts):continue
        if p.suffix.lower() in TEXT_SUFFIXES:add(p,f'{rel_dir} textual native report/log/readback')

# Full host JTAG simulator reports and artifact-mapped textual logs/captures.
for h in review['host']:
    report=pathlib.Path(h['path']).resolve()
    need(sha(report)==h['sha256'],f'host report hash differs from root review: {report}')
    d=load(report);need(d['status']=='PASS' and len(d.get('tests',[]))==15,'host report is not a 15-case PASS')
    add(report,f"complete {h['simulator']} 15-case host-JTAG report",h['sha256'])
    for relpath,expected in d.get('artifacts',{}).get('files',{}).items():
        p=WS/relpath
        if p.suffix.lower() in TEXT_SUFFIXES:add(p,f"{h['simulator']} 15-case host-JTAG observed capture/log",expected)

# Shared registered memory report plus all text-only logs/reports from it.
stdout=(V9/'production_test.stdout.log').read_text(errors='replace')
registered=WS/'build/tinystories-registered-memory/20261027T233128Z'
for p in sorted(registered.rglob('*')):
    if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:add(p,'TinyStories shared registered-memory native report/log')
# Dual CSR/dispatcher six-command report and its text logs.
dual=WS/'build/ddr-dual-controls/20261027T233137191972Z'
dual_report=load(dual/'report.json')
need(dual_report['status']=='PASS_DUAL_CONTROL_BENCHES_ONLY' and len(dual_report['commands'])==6,'dual-control report changed')
for p in sorted(dual.rglob('*')):
    if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:add(p,'six-command dual CSR/dispatcher control report/log')

# Preserve generated textual vector inputs and expected data used by the native
# suites. They are deterministic test data, not source RTL or binary images.
for rel_dir in ('build/vectors','build/dma_vectors','build/cmac_vectors','build/fp16_product_vectors'):
    base=WS/rel_dir
    if not base.exists():continue
    for p in sorted(base.rglob('*')):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:add(p,'generated textual native test vector/expected data')

# Include this exact archive producer as evidence; its copy lives inside the
# archive while the executable packer itself remains outside the destination.
add(PACKER,'archive producer source',dest_hint='evidence/prepare_archive.py')

# Inventory every unselected private workspace build file, with exact hash and
# a concrete exclusion reason. No compiled artifact is copied into verification.
selected_paths={str(e['path'].resolve()) for e in sources.values()}
excluded=[]
for p in sorted((WS/'build').rglob('*')):
    if not p.is_file() or str(p.resolve()) in selected_paths:continue
    relp=p.relative_to(WS).as_posix();parts=set(p.relative_to(WS/'build').parts);suf=p.suffix.lower()
    if suf in {'.so','.vvp','.o','.a','.gch','.dcp','.bit','.elf','.exe','.dll','.bin'} or p.name in {'sim','csr.vvp','dispatch.vvp'}:
        reason='compiled object, simulator, image/checkpoint or binary fixture excluded; source reports retain invocation and hash coverage'
    elif any(x.startswith('obj') for x in parts) or suf in {'.cpp','.h','.mk','.d'}:
        reason='generated native compiler intermediates excluded; exact RTL source and compiler versions are archived'
    else:
        reason='generated build output outside selected native/core/host/dual report and text-vector scope'
    excluded.append({'source_path':relp,'bytes':p.stat().st_size,'sha256':sha(p),'reason':reason})

# Record host tool executables without bundling them.
excluded_tools=[]
for name in ('python3','make','iverilog','vvp','verilator','c++','g++','tclsh'):
    found=shutil.which(name);need(found is not None,'host tool missing for exclusion inventory: '+name)
    p=pathlib.Path(found).resolve();need(p.is_file(),'tool executable missing: '+str(p))
    excluded_tools.append({'name':name,'source_path':str(p),'bytes':p.stat().st_size,'sha256':sha(p),
                           'reason':'host tool binary excluded; exact version is preserved in run/version reports'})
vivado=pathlib.Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado')
if vivado.is_file():
    excluded_tools.append({'name':'vivado','source_path':str(vivado.resolve()),'bytes':vivado.stat().st_size,'sha256':sha(vivado),
                           'reason':'Vivado binary excluded; v9 did not invoke Vivado'})

# Recheck every selected source after inventory, then deterministic copy.
for key,e in sources.items():need(sha(e['path'])==e['sha256'],'selected source drift before archive: '+key)
DEST.mkdir(parents=True)
files=[]
for key,e in sorted(sources.items(),key=lambda kv:kv[1]['archive_path']):
    src=e['path'];relout=e['archive_path'];compress=e['compress']
    if compress:relout += '.gz'
    dst=DEST/relout
    actual,source_bytes,stored_hash,stored_bytes=copy_payload(src,dst,compress)
    need(actual==e['sha256'] and source_bytes==e['bytes'],'source changed during archive copy: '+key)
    files.append({'source_path':repo_rel(src),'archive_path':relout,'roles':e['roles'],
                  'source_sha256':actual,'source_bytes':source_bytes,'stored_sha256':stored_hash,
                  'stored_bytes':stored_bytes,'encoding':'gzip-mtime0-level9' if compress else 'identity'})
# Re-read/decompress every copied payload and compare source hash/size.
for item in files:
    stored=DEST/item['archive_path']
    need(sha(stored)==item['stored_sha256'],'stored archive hash mismatch')
    encoding=item['encoding']
    observed,raw_bytes=hash_payload(stored,encoding)
    need(observed==item['source_sha256'] and raw_bytes==item['source_bytes'],'archive decode mismatch: '+item['archive_path'])
# All selected original source hashes must still match after the copy.
for key,e in sources.items():need(sha(e['path'])==e['sha256'],'selected source changed after archive copy: '+key)

index={'schema':1,'status':'PASS_SELECTED_PRODUCTION_DDR_MODEL_PROFILE_V9_EVIDENCE_ARCHIVE',
       'scope':{'evidence_scope':'Exact current-v9 private source closure, native/core/host/dual reports/logs/text vectors, launch/resource receipts and independent root review; prior current-v8 retained only as parent history.',
                'source_revision_sha256':prod['source_revision_manifest']['sha256'],
                'full_recursive_source_sha256':prod['full_recursive_source_manifest']['sha256'],
                'source_inputs':1090,'private_make_test':'PASS; generated-check PASS; serial make test PASS under 6GiB/2CPU/no-swap/256-task scope',
                'tinystories_test_methods':61,'software_ddr_control_methods':58,'dual_control_commands':6,
                'hardware_accessed':False,'vivado_executed':False,'bitstream_emitted':False,'flash_written':False,
                'no_ddr_or_full512_hardware_qualification_claim':True,
                'preserved_parent_history':'current-v8 report/root-review/launch; current-v6 failure and v8 failure history are not overwritten'},
       'file_count':len(files),'source_bytes':sum(x['source_bytes'] for x in files),
       'stored_bytes':sum(x['stored_bytes'] for x in files),'files':files,
       'excluded_workspace_build_outputs':excluded,'excluded_workspace_file_count':len(excluded),
       'excluded_workspace_bytes':sum(x['bytes'] for x in excluded),'excluded_host_tool_binaries':excluded_tools,
       'packer_path':repo_rel(PACKER),'packer_sha256':sha(PACKER),
       'producer_report_sha256':sha(V9/'report.json'),'independent_review_sha256':sha(V9/'root-review.json'),
       'launch_sha256':sha(V9/'launch.json'),'parent_v8_report_sha256':sha(V8/'report.json'),
       'parent_v8_review_sha256':sha(V8/'root-review.json')}
index_path=DEST/'index.json';index_path.write_text(json.dumps(index,indent=2,sort_keys=True)+'\n')
# Exact archive inventory after index exists; index is the sole metadata sidecar.
actual_files={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()}
expected_files={x['archive_path'] for x in files}|{'index.json'}
need(actual_files==expected_files,'archive contains extras or omits selected evidence')
print(json.dumps({'status':index['status'],'archive':repo_rel(DEST),'file_count':len(files),
                  'source_bytes':index['source_bytes'],'stored_bytes':index['stored_bytes'],
                  'excluded_workspace_file_count':len(excluded),'excluded_workspace_bytes':index['excluded_workspace_bytes'],
                  'index_sha256':sha(index_path),'packer_sha256':sha(PACKER)},indent=2))
