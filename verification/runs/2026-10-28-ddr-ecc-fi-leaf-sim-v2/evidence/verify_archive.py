from pathlib import Path
import datetime,gzip,hashlib,json
ROOT=Path('/home/fedora/rknpu-fpga');DEST=ROOT/'verification/runs/2026-10-28-ddr-ecc-fi-leaf-sim';INDEX=DEST/'index.json'
OUT=Path(__file__).resolve().parent/'archive-audit.json';BLOCK=1<<20
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(BLOCK),b''):h.update(b)
 return h.hexdigest()
def origin(p):
 p=Path(p);return p if p.is_absolute() else ROOT/p
def decode(p,enc):
 h=hashlib.sha256();n=0
 with Path(p).open('rb') as raw:
  f=gzip.GzipFile(fileobj=raw,mode='rb') if enc=='gzip-mtime0-level9' else raw
  for b in iter(lambda:f.read(BLOCK),b''):h.update(b);n+=len(b)
 return h.hexdigest(),n
assert DEST.is_dir() and INDEX.is_file() and not OUT.exists();idx=json.loads(INDEX.read_text())
assert idx['status']=='PASS_DDR_FI_XOR_LEAF_SIMULATION_EVIDENCE_ARCHIVE'
rows=idx['files'];paths=[x['archive_path'] for x in rows];assert len(paths)==len(set(paths))==idx['file_count']
actual={p.relative_to(DEST).as_posix() for p in DEST.rglob('*') if p.is_file()};assert actual==set(paths)|{'index.json'}
by_path={x['archive_path']:x for x in rows};stored=source=gzip_count=identity_count=0;errors=[]
for row in rows:
 p=DEST/row['archive_path'];o=origin(row['source_path'])
 if not p.is_file() or sha(p)!=row['stored_sha256']:errors.append('stored '+row['archive_path']);continue
 d,n=decode(p,row['encoding'])
 if d!=row['source_sha256'] or n!=row['source_bytes']:errors.append('decode '+row['archive_path'])
 if not o.is_file() or sha(o)!=row['source_sha256']:errors.append('origin '+row['source_path'])
 source+=row['source_bytes'];stored+=row['stored_bytes']
 if row['encoding']=='gzip-mtime0-level9':gzip_count+=1;assert row['archive_path'].endswith('.gz')
 elif row['encoding']=='identity':identity_count+=1
 else:raise AssertionError(row['encoding'])
assert not errors,errors[:10]
assert source==idx['source_bytes'] and stored==idx['stored_bytes']
for ref in idx['coverage_references']:
 row=by_path.get(ref['archive_path']);assert row and row['source_sha256']==ref['source_sha256'] and row['stored_sha256']==ref['archive_sha256']
 assert sha(DEST/ref['archive_path'])==ref['archive_sha256'] and sha(origin(ref['source_path']))==ref['source_sha256']
for x in idx['hash_only_excluded_binaries']:
 p=origin(x['source_path']);assert p.is_file() and sha(p)==x['sha256'] and x['reason']
for x in idx['hash_only_excluded_tools']:
 p=origin(x['path']);assert p.is_file() and sha(p)==x['sha256'] and x['reason']
root_review=json.loads((ROOT/'build/ddr-ecc-fi-leaf-root-review-v1.json').read_text())
obligation=json.loads((ROOT/'build/full512-ddr-preparation/ecc-injection-contract-source-review-v1.json').read_text())
assert root_review['status']=='PASS_ROOT_FI_LEAF_NATIVE_BEHAVIOR_ONLY_WITH_RECORDED_ICARUS_VENDOR_WARNING'
assert root_review['failed_v10_receipt_relabelled'] is False and root_review['hardware_accessed'] is False
assert obligation['status']=='SOURCE_REVIEW_ONLY_NOT_INJECTION_QUALIFICATION'
assert obligation['physical_ecc_injection_qualified'] is False and obligation['recovery_qualified'] is False
assert idx['scope']['physical_capacity_qualified'] is False and idx['scope']['physical_ecc_injection_qualified'] is False
assert idx['scope']['controller_or_decoder_simulated'] is False and idx['scope']['memory_simulated'] is False and idx['scope']['phy_simulated'] is False
assert len(idx['attempt_producer_statuses'])==10 and idx['attempt_producer_statuses']['10']=='FAIL'
assert idx['root_reviewed_native_results']['verilator']['producer_status_preserved']=='PASS_FI_XOR_LEAF_VERILATOR_ONLY'
assert idx['root_reviewed_native_results']['icarus']['producer_status_preserved']=='FAIL'
assert len(idx['root_reviewed_native_results']['icarus']['compile_warning'])>0
assert idx['root_reviewed_native_results']['icarus']['native_compile_rc']==0 and idx['root_reviewed_native_results']['icarus']['native_run_rc']==0
assert len([x for x in rows if x['kind']!='text'])==0
result={'schema':'ddr-fi-leaf-archive-independent-rehash-v1','status':'PASS_INDEPENDENT_FI_LEAF_ARCHIVE_REHASH',
 'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'archive_path':str(DEST),'index_sha256':sha(INDEX),
 'payload_count':len(rows),'coverage_count':len(idx['coverage_references']),'source_bytes':source,'stored_bytes':stored,
 'gzip_payloads':gzip_count,'identity_payloads':identity_count,'binary_payloads':0,
 'excluded_binary_and_tool_hashes_verified':len(idx['hash_only_excluded_binaries'])+len(idx['hash_only_excluded_tools']),
 'origin_mismatches':0,'stored_mismatches':0,'coverage_mismatches':0,'extras':0,
 'attempts_preserved':10,'root_reviewed_native_results':['verilator_v7_pass','icarus_v10_native_pass_producer_fail_preserved'],
 'hardware_accessed':False,'physical_injection_qualified':False}
OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result,indent=2,sort_keys=True))
