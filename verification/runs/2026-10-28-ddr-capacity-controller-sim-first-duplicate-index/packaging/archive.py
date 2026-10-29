#!/usr/bin/env python3
"""Create a deterministic selected source/text archive with full hash verification."""
from __future__ import annotations
import datetime,gzip,hashlib,json,pathlib,shutil,sys
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');BUILD=ROOT/'build/ddr-capacity-controller-sim-archive-v1'
DEFAULT_OUT=ROOT/'verification/runs/2026-10-28-ddr-capacity-controller-sim'
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write_json(path,obj):path.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
def store_payload(src,out,archive_root):
 src=pathlib.Path(src);raw=src.read_bytes();source_hash=hashlib.sha256(raw).hexdigest()
 if len(raw)>16384:
  stored=out.with_name(out.name+'.gz')
  with stored.open('xb') as raw_file:
   with gzip.GzipFile(filename='',mode='wb',fileobj=raw_file,compresslevel=9,mtime=0) as stream:stream.write(raw)
  encoding='gzip-mtime0-level9'
 else:
  stored=out;stored.write_bytes(raw);encoding='identity'
 return {'archive_path':str(stored.relative_to(archive_root)),'encoding':encoding,
  'source_sha256':source_hash,'source_bytes':len(raw),'archive_sha256':sha(stored),'archive_bytes':stored.stat().st_size}
def main():
 start=utc();plan_path=BUILD/'archive-plan.json';plan=json.loads(plan_path.read_text())
 out=DEFAULT_OUT
 if len(sys.argv)>1:out=pathlib.Path(sys.argv[1]);out=out if out.is_absolute() else ROOT/out
 if out.exists():raise SystemExit(f'refusing existing archive output: {out}')
 require=plan['files'];before={x['source_path']:sha(ROOT/x['source_path']) for x in require}
 for row in require:
  if before[row['source_path']]!=row['source_sha256']:raise RuntimeError('source changed before archive: '+row['source_path'])
 out.mkdir(parents=True)
 archived=[]
 for row in require:
  source=ROOT/row['source_path'];target=out/row['archive_path'];target.parent.mkdir(parents=True,exist_ok=True)
  actual=store_payload(source,target,out)
  if actual['source_sha256']!=row['source_sha256'] or actual['source_bytes']!=row['source_bytes']:
   raise RuntimeError('source drift during archive: '+row['source_path'])
  archived.append({**row,**actual})
 # Include the exact plan and both packer scripts for review/repacking; the plan does not self-hash.
 extras=[('archive-plan.json','provenance/archive-plan.json','source-selection plan'),
         ('prepare_archive.py','packaging/prepare_archive.py','archive plan generator'),
         ('archive.py','packaging/archive.py','deterministic archive packer')]
 for source_rel,archive_rel,role in extras:
  source=BUILD/source_rel;target=out/archive_rel;target.parent.mkdir(parents=True,exist_ok=True)
  actual=store_payload(source,target,out)
  archived.append({'source_path':str(source.relative_to(ROOT)),'role':role,**actual})
 after={x['source_path']:sha(ROOT/x['source_path']) for x in require}
 if before!=after:raise RuntimeError('source changed while archiving')
 index={'schema':'ddr-capacity-controller-sim-selected-archive-v1','status':'PASS_ARCHIVE_SOURCE_AND_TEXT_EVIDENCE_ONLY',
  'created_utc':utc(),'scope':plan['scope'],'file_count':len(archived),'payload_source_bytes':sum(x['source_bytes'] for x in archived),
  'payload_archive_bytes':sum(x['archive_bytes'] for x in archived),'compression_policy':plan['compression_policy'],
  'files':archived,'attempts':plan['attempts'],'leaf_root_review':plan['leaf_root_review'],
  'sweep_root_review':plan['sweep_root_review'],'excluded_files':plan['excluded_files'],
  'excluded_file_count':len(plan['excluded_files']),'excluded_bytes':sum(x['bytes'] for x in plan['excluded_files']),
  'plan_sha256':sha(plan_path),'source_hashes_before':before,'source_hashes_after':after,
  'hardware_executed':False,'physical_capacity_qualified':False,'real_mig_integration_qualified':False,
  'sweep_source_native_review_status':plan['sweep_root_review']['status'],
  'sweep_mig_physical_review_status':'PENDING_NOT_QUALIFIED',
  'sweep_root_review_scope':plan['sweep_root_review']['scope'],
  'no_sha256sums':True}
 index_path=out/'index.json';write_json(index_path,index)
 # Full offline integrity audit: source bytes, stored bytes, decompressed bytes, and file coverage.
 expected={x['archive_path'] for x in archived};actual_files={str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p!=index_path}
 if expected!=actual_files:raise RuntimeError(f'archive coverage mismatch missing={sorted(expected-actual_files)} extra={sorted(actual_files-expected)}')
 for row in archived:
  stored=out/row['archive_path']
  if sha(stored)!=row['archive_sha256'] or stored.stat().st_size!=row['archive_bytes']:raise RuntimeError('stored payload mismatch '+row['archive_path'])
  if row['encoding']=='gzip-mtime0-level9':
   with gzip.open(stored,'rb') as f:
    digest=hashlib.sha256();size=0
    for block in iter(lambda:f.read(1<<20),b''):digest.update(block);size+=len(block)
    payload_hash=digest.hexdigest()
  else:payload_hash=sha(stored);size=stored.stat().st_size
  if payload_hash!=row['source_sha256'] or size!=row['source_bytes']:raise RuntimeError('decompressed payload mismatch '+row['archive_path'])
 run={'schema':'ddr-capacity-controller-sim-archive-run-v1','status':'PASS',
  'started_utc':start,'finished_utc':utc(),'argv':sys.argv,'cwd':str(pathlib.Path.cwd()),
  'plan_path':str(plan_path),'plan_sha256':sha(plan_path),'packer_path':str(pathlib.Path(__file__).resolve()),
  'packer_sha256':sha(__file__),'archive_path':str(out),'index_path':str(index_path),'index_sha256':sha(index_path),
  'payload_files':len(archived),'payload_source_bytes':index['payload_source_bytes'],'payload_archive_bytes':index['payload_archive_bytes'],
  'excluded_files':len(plan['excluded_files']),'source_stable':before==after,'offline_integrity':'PASS',
  'hardware_executed':False,'physical_capacity_qualified':False,'real_mig_integration_qualified':False}
 write_json(BUILD/'archive-run.json',run)
 audit={'schema':'ddr-capacity-controller-sim-archive-audit-v1','status':'PASS',
  'index_sha256':sha(index_path),'index_file_count':len(index['files']),
  'indexed_payload_paths':len(expected),'actual_payload_paths':len(actual_files),'unindexed_payloads':0,
  'source_hashes_stable':before==after,'all_stored_and_decompressed_hashes_match':True,
  'excluded_files_hash_identified':True,'sha256sums_present':False,
  'leaf_root_review_status':index['leaf_root_review']['status'],
  'sweep_root_review_status':index['sweep_root_review']['status'],
  'sweep_review_scope':index['sweep_root_review']['scope'],
  'physical_or_MIG_qualification_claimed':False}
 write_json(BUILD/'archive-audit.json',audit)
 print(json.dumps({'status':run['status'],'archive':str(out),'index_sha256':sha(index_path),
  'files':len(archived),'source_bytes':index['payload_source_bytes'],'archive_bytes':index['payload_archive_bytes'],
  'excluded_files':len(plan['excluded_files']),'run_receipt':str(BUILD/'archive-run.json'),'audit_receipt':str(BUILD/'archive-audit.json')},indent=2))
 return 0
if __name__=='__main__':raise SystemExit(main())
