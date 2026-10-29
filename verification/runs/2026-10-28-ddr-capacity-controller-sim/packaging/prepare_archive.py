#!/usr/bin/env python3
"""Build a source/evidence selection plan for the private DDR pattern and sweep leaf tests."""
from __future__ import annotations
import hashlib,json,pathlib,shutil
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');BUILD=ROOT/'build/ddr-capacity-controller-sim-archive-v1'
LEAF=ROOT/'build/ddr-capacity-bist-source-v1'
def sha(p):
 h=hashlib.sha256()
 with pathlib.Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def add(files,src,arc,role):
 src=pathlib.Path(src);assert src.is_file(),src
 files.append({'source_path':str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src),
  'archive_path':arc,'source_sha256':sha(src),'source_bytes':src.stat().st_size,'role':role})
def main():
 files=[];reports=[];attempts=[]
 add(files,LEAF/'rk_ddr_capacity_pattern.sv','sources/rk_ddr_capacity_pattern.sv','root-owned private combinational pattern leaf; hash-bound input to leaf and sweep runs')
 add(files,LEAF/'rk_ddr_capacity_sweep.sv','sources/rk_ddr_capacity_sweep.sv','root-owned private single-outstanding sweep/controller-fence test RTL; source-review only')
 add(files,ROOT/'tools/ddr/capacity_pattern.py','reference/tools/ddr/capacity_pattern.py','contextual software pattern reference; leaf vector generator is independent and does not import it')
 add(files,ROOT/'tests/ddr/capacity/test_pattern.py','reference/tests/ddr/capacity/test_pattern.py','contextual software pattern tests; not an RTL or physical qualification')
 add(files,ROOT/'build/ddr-capacity-bist-leaf-validation-v6/root-review.json','reviews/pattern-leaf-root-review.json','root accepted corpus/mapped equivalence review; private pattern leaf only')
 add(files,ROOT/'build/ddr-capacity-sweep-validation-v4/root-review.json','reviews/sweep-source-native-root-review.json','root source/native receipt review only; no MIG or physical qualification')
 add(files,ROOT/'build/ddr-capacity-sweep-validation-v4/root_review.py','review-tools/sweep-root-review.py','exact reviewer used for root sweep source/native receipt review')
 add(files,BUILD/'prepare_archive.py','packaging/prepare_archive.py','archive input-selection plan generator')
 add(files,BUILD/'archive.py','packaging/archive.py','deterministic archive packer')
 leafroot=ROOT/'build'
 for version in range(1,7):
  directory=leafroot/f'ddr-capacity-bist-leaf-validation-v{version}'
  names=['tb_capacity_pattern.sv','make_vectors.py','run_validation.py','vectors.txt','vectors-manifest.json','report.json']
  for name in names:
   p=directory/name
   if p.is_file():add(files,p,f'evidence/pattern-leaf/v{version}/{name}',f'pattern leaf v{version} exact input/producer receipt')
  for name in ('independent-facts.json','root-review.json','mapped.json','mapped.v'):
   p=directory/name
   if p.is_file():
    role=('root review' if name=='root-review.json' else 'source-bound mapped synthesis evidence' if name.startswith('mapped.') else 'independent post-run facts')
    add(files,p,f'evidence/pattern-leaf/v{version}/{name}',f'pattern leaf v{version} {role}')
  for p in sorted(directory.glob('*.stdout.log'))+sorted(directory.glob('*.stderr.log')):
   add(files,p,f'evidence/pattern-leaf/v{version}/logs/{p.name}',f'pattern leaf v{version} actual native stdout/stderr')
  r=directory/'report.json'
  report=json.loads(r.read_text())
  attempts.append({'component':'pattern_leaf','version':version,'report_path':str(r.relative_to(ROOT)),
    'report_sha256':sha(r),'producer_status':report['status'],'failure':report.get('failure'),
    'root_review_path':str((directory/'root-review.json').relative_to(ROOT)) if (directory/'root-review.json').is_file() else None,
    'root_review_status':json.loads((directory/'root-review.json').read_text())['status'] if (directory/'root-review.json').is_file() else None})
 for version in range(1,5):
  directory=leafroot/f'ddr-capacity-sweep-validation-v{version}'
  for name in ['tb_capacity_sweep.sv','tb_capacity_sweep_full_elab.sv','tb_capacity_sweep_invalid.sv','run_validation.py','report.json']:
   p=directory/name
   if p.is_file():add(files,p,f'evidence/sweep-controller/v{version}/{name}',f'sweep controller v{version} exact source/producer receipt')
  for name in ('independent-facts.json','root-review.json','root_review.py'):
   p=directory/name
   if p.is_file():add(files,p,f'evidence/sweep-controller/v{version}/{name}',
      'sweep controller root reviewer/facts; source/native review only' if name!='independent-facts.json' else 'sweep controller independent facts')
  for p in sorted(directory.glob('*.stdout.log'))+sorted(directory.glob('*.stderr.log')):
   add(files,p,f'evidence/sweep-controller/v{version}/logs/{p.name}',f'sweep controller v{version} actual native stdout/stderr')
  r=directory/'report.json';report=json.loads(r.read_text())
  root_review=directory/'root-review.json'
  attempts.append({'component':'sweep_controller','version':version,'report_path':str(r.relative_to(ROOT)),
    'report_sha256':sha(r),'producer_status':report['status'],'failure':report.get('failure'),
    'root_review_path':str(root_review.relative_to(ROOT)) if root_review.is_file() else None,
    'root_review_status':json.loads(root_review.read_text())['status'] if root_review.is_file() else None})
 # Enumerate compiled artifacts/objects and native executables that are intentionally not payloads.
 excluded=[]
 for component,pattern in [('pattern_leaf','ddr-capacity-bist-leaf-validation-v*'),('sweep_controller','ddr-capacity-sweep-validation-v*')]:
  for directory in sorted(leafroot.glob(pattern)):
   for p in sorted(directory.rglob('*')):
    if not p.is_file():continue
    rel=p.relative_to(directory)
    is_binary=(p.suffix in {'.vvp','.o','.a','.so','.pyc'} or p.name in {'Vtb_capacity_pattern','Vtb_capacity_sweep','Vtb_capacity_sweep_full_elab'}
       or any(part in {'verilator_obj','verilator_full_elab_obj','__pycache__'} for part in rel.parts))
    if is_binary:excluded.append({'source_path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size,
       'reason':'compiled simulator binary/object/cache; native execution is bound by text receipts and tool versions'})
 # Native tools are identified but never copied into the source/evidence payload.
 tool_paths=set()
 for report_path in [ROOT/f'build/ddr-capacity-bist-leaf-validation-v{v}/report.json' for v in range(1,7)]+[ROOT/f'build/ddr-capacity-sweep-validation-v{v}/report.json' for v in range(1,5)]:
  if not report_path.is_file():continue
  report=json.loads(report_path.read_text())
  for row in report.get('tool_versions',{}).values():
   if row.get('path'):tool_paths.add(row['path'])
 for name in ('systemd-run','make','c++'):
  path=shutil.which(name)
  if path:tool_paths.add(path)
 for value in sorted(tool_paths):
  p=pathlib.Path(value)
  if p.is_file():excluded.append({'source_path':str(p),'sha256':sha(p),'bytes':p.stat().st_size,
      'reason':'native tool executable; version/hash retained in source-bound evidence but tool binary excluded'})
 files.sort(key=lambda x:x['archive_path']);excluded.sort(key=lambda x:x['source_path'])
 leaf_review=json.loads((leafroot/'ddr-capacity-bist-leaf-validation-v6/root-review.json').read_text())
 sweep_review=json.loads((leafroot/'ddr-capacity-sweep-validation-v4/root-review.json').read_text())
 plan={'schema':'ddr-capacity-controller-source-evidence-archive-plan-v1','archive_path':'verification/runs/2026-10-28-ddr-capacity-controller-sim',
  'scope':'Portable source and text evidence for private pattern-leaf simulation/mapping and bounded sweep-adapter contract simulation. No real MIG integration, physical DDR, or capacity qualification.',
  'files':files,'file_count':len(files),'excluded_files':excluded,'excluded_file_count':len(excluded),'attempts':attempts,
  'leaf_root_review':{'path':'build/ddr-capacity-bist-leaf-validation-v6/root-review.json','sha256':sha(leafroot/'ddr-capacity-bist-leaf-validation-v6/root-review.json'),'status':leaf_review['status'],'scope':'private combinational pattern leaf only'},
  'sweep_root_review':{'path':'build/ddr-capacity-sweep-validation-v4/root-review.json','sha256':sha(leafroot/'ddr-capacity-sweep-validation-v4/root-review.json'),'status':sweep_review['status'],'scope':sweep_review['scope'],'real_mig_integration_qualified':sweep_review['real_mig_integration_qualified'],'physical_capacity_qualified':sweep_review['physical_capacity_qualified']},
  'compression_policy':'gzip level 9 and mtime=0 only for payloads over 16384 bytes; smaller files are byte-identical',
  'index_policy':'JSON index is the only unindexed archive file. No SHA256SUMS file is emitted.',
  'hardware_executed':False,'physical_capacity_qualified':False,'migrated_controller_qualified':False}
 out=BUILD/'archive-plan.json';out.write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'plan':str(out),'plan_sha256':sha(out),'included':len(files),'excluded':len(excluded),'attempts':len(attempts)},indent=2))
if __name__=='__main__':main()
