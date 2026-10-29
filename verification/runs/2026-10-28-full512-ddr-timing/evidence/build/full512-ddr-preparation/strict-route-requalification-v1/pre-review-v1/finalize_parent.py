#!/usr/bin/env python3
"""Freeze a terminal repair-v3 report into the unlaunchable requalification package."""
from pathlib import Path
import hashlib,json,re
BASE=Path(__file__).resolve().parent
ROOT=Path('/home/fedora/rknpu-fpga')
PARENT=ROOT/'build/full512-ddr-preparation/postroute-repair-v3'
PREP=BASE/'preparation.json'
MARKER='PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW'
ALLOWED_DRIFT=ROOT/'fpga/ddr/emit_full512_ch1.tcl.in'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def group_members(pgid):
 out=[]
 for ent in Path('/proc').iterdir():
  if not ent.name.isdigit():continue
  try:
   fields=(ent/'stat').read_text().rsplit(')',1)[1].split()
   if int(fields[2])==pgid and fields[0] not in {'Z','X'}:out.append(int(ent.name))
  except (FileNotFoundError,ProcessLookupError,ValueError,IndexError):pass
 return sorted(out)
prep=json.loads(PREP.read_text()); report_path=PARENT/'report.json'; report=json.loads(report_path.read_text())
assert report.get('finished_utc') and report.get('returncode')==0, 'Parent repair is not terminal rc0'
assert report.get('status') in (MARKER,'FAIL_REPAIR_INPUT_MUTATION'), 'Parent repair has unrelated failure status'
assert (PARENT/'output/stdout.log').read_text(errors='replace').splitlines().count(MARKER)==1, 'Parent native PASS marker missing/duplicated'
assert isinstance(report.get('pgid'),int) and not group_members(report['pgid']), 'Parent owned process group remains active'
before=report.get('input_hashes_before',{}); after=report.get('input_hashes_after',{})
assert before==prep['parent_source_input_hashes_at_prep'], 'Parent source closure differs from captured launch input map'
assert set(before)==set(after), 'Parent final source map is incomplete'
changed=[p for p in before if before[p]!=after[p]]
assert changed==[str(ALLOWED_DRIFT)], f'Unexpected parent provenance drift: {changed}'
assert before[changed[0]]==prep['only_allowed_parent_input_drift']['prior_expected_sha256']
assert after[changed[0]]==sha(ALLOWED_DRIFT)==prep['only_allowed_parent_input_drift']['current_sha256']
for p,h in after.items():assert Path(p).is_file() and sha(p)==h, 'Parent dependency changed: '+p
if report.get('status')=='FAIL_REPAIR_INPUT_MUTATION':
 assert 'input changed' in str(report.get('error','')).lower() or 'input mutation' in str(report.get('error','')).lower(), 'Parent producer failure is unrelated to the single drift'
parent_dcp=PARENT/'output/post_route.dcp'
assert report.get('repaired_post_route_dcp_path')==str(parent_dcp) and parent_dcp.is_file()
assert report.get('repaired_post_route_dcp_sha256')==sha(parent_dcp)
assert report.get('source_post_opt_dcp_sha256')==prep['source_post_opt_dcp_sha256']
# Freeze every actual parent input and output, including logs and checkpoint, by path and digest.
bound=dict(after)
bound[str(report_path)]=sha(report_path)
for key in ('stdout.log','stderr.log'):
 p=PARENT/'output'/key;assert p.is_file();bound[str(p)]=sha(p)
for rel,h in report.get('output_hashes',{}).items():
 p=PARENT/'output'/rel
 assert p.is_file() and sha(p)==h, 'Parent output hash mismatch: '+rel
 bound[str(p)]=h
for p in (BASE/'qualification.tcl',BASE/'run_qualification.py',BASE/'expected-anchor-names.txt',
          BASE/'provenance/template-v12-original.tcl.in',BASE/'provenance/template-current-fixed.tcl.in'):
 bound[str(p)]=sha(p)
for p in sorted((BASE/'helpers').glob('*.tcl')):bound[str(p)]=sha(p)
assert bound[str(parent_dcp)]==sha(parent_dcp)
prep.update(status='PREPARED_AWAITING_ROOT_REVIEW',launchable=False,
             parent_final_status=report.get('status'),parent_report_sha256=sha(report_path),
             parent_stdout_sha256=sha(PARENT/'output/stdout.log'),parent_stderr_sha256=sha(PARENT/'output/stderr.log'),
             parent_routed_dcp_sha256=sha(parent_dcp),parent_source_input_hashes_final=after,
             parent_input_hashes_at_launch=before,
             parent_provenance_drift_paths=changed,parent_native_marker_count=1,
             parent_process_group_absent=True,bound_input_hashes=bound,
             parent_finalization_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat())
PREP.write_text(json.dumps(prep,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':prep['status'],'launchable':False,'parent_status':report['status'],
 'parent_report_sha256':prep['parent_report_sha256'],'parent_dcp_sha256':prep['parent_routed_dcp_sha256'],
 'sole_drift':changed,'bound_input_count':len(bound),'prep_sha256':sha(PREP)},indent=2))
