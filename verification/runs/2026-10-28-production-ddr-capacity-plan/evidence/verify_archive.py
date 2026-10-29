from pathlib import Path
import datetime,gzip,hashlib,json
ROOT=Path('/home/fedora/rknpu-fpga');DEST=ROOT/'verification/runs/2026-10-28-production-ddr-capacity-plan'
INDEX=DEST/'index.json';OUT=Path(__file__).resolve().parent/'archive-audit.json';BLOCK=1<<20
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(BLOCK),b''):h.update(b)
 return h.hexdigest()
def origin(path):
 p=Path(path);return p if p.is_absolute() else ROOT/p
def decode(path,encoding):
 h=hashlib.sha256();n=0
 with Path(path).open('rb') as raw:
  stream=gzip.GzipFile(fileobj=raw,mode='rb') if encoding=='gzip-mtime0-level9' else raw
  for b in iter(lambda:stream.read(BLOCK),b''):h.update(b);n+=len(b)
 return h.hexdigest(),n
assert DEST.is_dir() and INDEX.is_file() and not OUT.exists()
d=json.loads(INDEX.read_text());assert d['status']=='PASS_PRODUCTION_DDR_CAPACITY_PLAN_V15_SOURCE_AND_TEXT_ARCHIVE'
rows=d['files'];assert len(rows)==d['file_count'];paths=[x['archive_path'] for x in rows];assert len(set(paths))==len(paths)
actual={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()};assert actual==set(paths)|{'index.json'}
by_path={x['archive_path']:x for x in rows};source_bytes=stored_bytes=gzip_count=identity_count=0;errors=[]
for row in rows:
 target=DEST/row['archive_path'];src=origin(row['source_path'])
 if not target.is_file() or sha(target)!=row['stored_sha256']:errors.append('stored:'+row['archive_path']);continue
 digest,size=decode(target,row['encoding'])
 if digest!=row['source_sha256'] or size!=row['source_bytes']:errors.append('decode:'+row['archive_path'])
 if not src.is_file() or sha(src)!=row['source_sha256']:errors.append('origin:'+row['source_path'])
 source_bytes+=row['source_bytes'];stored_bytes+=row['stored_bytes']
 if row['encoding']=='gzip-mtime0-level9':gzip_count+=1;assert row['archive_path'].endswith('.gz')
 elif row['encoding']=='identity':identity_count+=1
 else:raise AssertionError(row['encoding'])
assert not errors,errors[:10]
assert source_bytes==d['source_bytes'] and stored_bytes==d['stored_bytes']
for ref in d['coverage_references']:
 row=by_path.get(ref['archive_path']);assert row is not None
 assert row['stored_sha256']==ref['archive_sha256'] and row['source_sha256']==ref['source_sha256']
 assert sha(DEST/ref['archive_path'])==ref['archive_sha256'] and sha(origin(ref['source_path']))==ref['source_sha256']
excluded=0
for entry in d['excluded_workspace_build_outputs']:
 p=ROOT/'build/production-model-auditors/current-v15/workspace'/entry['source_path']
 assert p.is_file() and sha(p)==entry['sha256'] and entry['reason'];excluded+=1
for entry in d['excluded_host_tool_binaries']:
 p=origin(entry['source_path']);assert p.is_file() and sha(p)==entry['sha256'] and entry['reason'];excluded+=1
assert d['scope']['v15_source_files']==1098 and d['scope']['v14_parent_source_files_copied'] is False
assert d['scope']['default_software_ddr_control_methods']==89 and d['scope']['supplemental_capacity_pattern_methods']==7
contract=d['scope']['capacity_plan_contract']
assert contract['plan_only'] and contract['physical_capacity_qualified'] is False and contract['operation_records_materialized'] is False
assert contract['controller_retirement_and_ecc_witness_required_separately'] is True and contract['operations']==134217728
assert d['scope']['capacity_plan_physical_capacity_qualified'] is False
assert d['scope']['hardware_accessed'] is False and d['scope']['vivado_executed'] is False and d['scope']['flash_written'] is False
assert 'capacity-plan-contract.json' in [Path(x['source_path']).name for x in rows]
v15=ROOT/'build/production-model-auditors/current-v15';v14=ROOT/'build/production-model-auditors/current-v14'
assert sha(v15/'report.json')==d['producer_report_sha256']
assert sha(v15/'root-review.json')==d['root_review_sha256'] and sha(v15/'agent-review.json')==d['agent_review_sha256']
assert sha(v14/'report.json')==d['parent_v14_report_sha256'] and sha(v14/'root-review.json')==d['parent_v14_root_review_sha256']
parent=json.loads((v14/'report.json').read_text());assert len(parent['source_inputs'])==1095
assert sha(ROOT/'verification/runs/2026-10-28-production-ddr-repeat-control/index.json')==d['parent_v14_archive_index_sha256']
result={'schema':'production-v15-capacity-plan-archive-independent-rehash-v1','status':'PASS_INDEPENDENT_V15_CAPACITY_ARCHIVE_REHASH',
 'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'archive_path':str(DEST),'index_sha256':sha(INDEX),
 'payload_count':len(rows),'coverage_reference_count':len(d['coverage_references']),'source_bytes':source_bytes,'stored_bytes':stored_bytes,
 'gzip_payload_count':gzip_count,'identity_payload_count':identity_count,'excluded_entries_reverified':excluded,
 'origin_mismatches':0,'stored_mismatches':0,'coverage_mismatches':0,'archive_extras':0,
 'current_v15_source_files':1098,'parent_v14_source_inputs':1095,'supplemental_capacity_methods':7,
 'physical_capacity_qualified':False,'hardware_accessed':False,'vivado_executed':False}
OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result,indent=2,sort_keys=True))
