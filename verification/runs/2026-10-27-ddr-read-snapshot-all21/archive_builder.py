#!/usr/bin/python3
"""Preserve selected all-21 same-ELF logical DDR read-snapshot evidence."""
from __future__ import annotations
import datetime, gzip, hashlib, json, os, pathlib, shutil, sys, tempfile

ROOT = pathlib.Path('/home/fedora/rknpu-fpga')
WS = ROOT / 'build/ddr-read-snapshot-candidate/v2/workspace'
NATIVE = WS / 'build/ddr-endpoint-async/native-read-snapshot-v3'
UNION = ROOT / 'build/ddr-read-snapshot-root-review/v2/all21.json'
REVIEWER = ROOT / 'build/ddr-read-snapshot-root-review/v2/review_all21.py'
RECOVERY = ROOT / 'build/ddr-read-snapshot-root-review/v1/recovery-prefix.json'
RECOVERY_REVIEWER = ROOT / 'build/ddr-read-snapshot-root-review/v1/review_recovery_prefix.py'
DEST = ROOT / 'verification/runs/2026-10-27-ddr-read-snapshot-all21'
BUILDER = ROOT / 'build/archive_ddr_read_snapshot_all21.py'
BINARY_SHA = 'd3fe23dbf517842b391ba440fb8ff8d02b2f536a2ee1d8cefe2a7c6de84b1eb5'
REPORTS = {
  'build': NATIVE / 'report.json',
  'matrix-a-original-failed': WS / 'build/snapshot-matrix-A-v3/report.json',
  'matrix-a-exec-v4': WS / 'build/snapshot-matrix-A-exec4-v3/report.json',
  'matrix-b': WS / 'build/snapshot-matrix-B-v3/report.json',
  'matrix-c': WS / 'build/snapshot-matrix-C-v3/report.json',
  'repeat-sub-9': WS / 'build/repeat-read-snapshot-v3/report.json',
}

class ArchiveError(RuntimeError): pass

def sha(path: pathlib.Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def relroot(path: pathlib.Path) -> str:
    try: return path.resolve().relative_to(ROOT).as_posix()
    except ValueError: return str(path.resolve())

def load_json(path: pathlib.Path):
    try: return json.loads(path.read_text())
    except Exception as e: raise ArchiveError(f'cannot parse JSON {path}: {e}')

def require(ok, message):
    if not ok: raise ArchiveError(message)

def verify_declared(path: pathlib.Path, declared: str, label: str, verified: dict):
    require(path.is_file(), f'missing reported input: {label}: {path}')
    actual=sha(path)
    require(actual==declared, f'reported hash drift for {label}: {path}: expected {declared}, got {actual}')
    verified[str(path.resolve())]={'sha256':actual,'bytes':path.stat().st_size}
    return actual

# Full pre-copy audit first. Nothing in verification/runs is created until this
# closes over every root-union report, its declared source/input hashes, and
# every artifact hash declared by those reports.
require(not DEST.exists(), f'destination must be new: {DEST}')
union=load_json(UNION)
require(union.get('status')=='PASS_INDEPENDENT_SAME_ELF_ALL21_READ_SNAPSHOT_LOGICAL_UNION_ONLY', 'unexpected union status')
require(union.get('case_count')==21 and len(union.get('cases',{}))==21, 'union is not exactly 21 cases')
require(union.get('binary_sha256')==BINARY_SHA, 'union ELF SHA differs from pinned candidate')
require(union.get('hardware_accessed') is False and union.get('physical_integration_ready') is False and union.get('fpga_or_rk_equivalence') is False, 'union evidence scope flags changed')
require(union.get('old_matrix_A_status')=='FAIL', 'original matrix A failure status not preserved')
for case, entry in union['cases'].items():
    result=entry.get('result',{})
    require(result.get('status')=='PASS', f'case is not PASS in union: {case}')
    require(entry.get('execution_contract_version') in (3,4), f'unknown execution contract in {case}')

verified_inputs={}
root_union_sha=sha(UNION)
verified_inputs[str(UNION.resolve())]={'sha256':root_union_sha,'bytes':UNION.stat().st_size}

# Verify union's directly pinned evidence and reviewer files.
for path, expected in union.get('evidence',{}).items():
    verify_declared(pathlib.Path(path), expected, 'union evidence', verified_inputs)
for path, expected in union.get('reviewers',{}).items():
    verify_declared(pathlib.Path(path), expected, 'union reviewer', verified_inputs)
verify_declared(REVIEWER, union['reviewers'][str(REVIEWER)], 'all21 reviewer', verified_inputs)

# Validate every actual report and every hash map it carries. This includes
# source files and external MIG inputs that are intentionally not copied.
report_data={}
for label, path in REPORTS.items():
    d=load_json(path); report_data[label]=d
    if label=='build':
        require(d.get('status')=='PASS_READ_SNAPSHOT_DDR_NATIVE_BUILD_ONLY', 'native build report status changed')
        require(d.get('binary_sha256')==BINARY_SHA, 'native build report ELF hash changed')
        require(sha(path)==union['build_report_sha256'], 'root union build report hash mismatch')
    for mapname in ('inputs','execution_inputs'):
        for source, expected in d.get(mapname,{}).items():
            verify_declared(pathlib.Path(source),expected,f'{label}.{mapname}',verified_inputs)
    if label=='build':
        for source, expected in d.get('local_source',{}).items():
            verify_declared(WS/source,expected,'build.local_source',verified_inputs)
        binary=pathlib.Path(d['binary_path'])
        verify_declared(binary,BINARY_SHA,'compiled ELF (excluded from archive)',verified_inputs)
        for tool, metadata in d.get('tools',{}).items():
            path=pathlib.Path(metadata['path'])
            verify_declared(path,metadata['sha256'],f'excluded tool {tool}',verified_inputs)
    for artifact, expected in d.get('artifacts',{}).items():
        verify_declared(path.parent/artifact,expected,f'{label}.artifacts',verified_inputs)

# Ensure each union parent is exactly one of the pinned reports.
parent_report_paths={label:str(path) for label,path in REPORTS.items() if label!='build'}
known_parents=set(parent_report_paths.values())
for case, entry in union['cases'].items():
    parent=entry.get('parent_report')
    require(parent in known_parents, f'union case parent report not in selected set: {case}: {parent}')
    d=next(v for k,v in report_data.items() if k!='build' and str(REPORTS[k])==parent)
    match=[c for c in d.get('cases',[]) if c.get('name')==case]
    require(len(match)==1 and match[0].get('status')=='PASS', f'parent case mismatch for {case}')

# Verify the independent recovery-only audit and its pinned parent/artifacts.
rec=load_json(RECOVERY)
require(rec.get('status')=='PASS_ONE_RECOVERY_CASE_FROM_PRESERVED_FAILED_BATCH_ONLY','recovery audit status changed')
verify_declared(RECOVERY_REVIEWER,rec['reviewer_sha256'],'recovery audit reviewer',verified_inputs)
verify_declared(pathlib.Path(rec['parent_report']),rec['parent_report_sha256'],'recovery parent report',verified_inputs)
for p,h in rec.get('inputs',{}).items(): verify_declared(pathlib.Path(p),h,'recovery audit input',verified_inputs)
recovery_parent=pathlib.Path(rec['parent_report'])
for p,h in rec.get('artifacts',{}).items(): verify_declared(recovery_parent.parent/p,h,'recovery audit artifact',verified_inputs)

# Verify the explicit schema-4 prospective adapter and its nine controls.
control_dir=WS/'build/execution-v4-controls-v1'
control=load_json(control_dir/'receipt.json')
require(control.get('status')=='PASS' and 'Ran 9 tests' in str(control.get('tests_summary','')), 'execution-v4 nine-control receipt changed')
for source, expected in control.get('input_hashes_before',{}).items(): verify_declared(pathlib.Path(source),expected,'execution-v4 controls input',verified_inputs)
for source, expected in control.get('input_hashes_after',{}).items(): verify_declared(pathlib.Path(source),expected,'execution-v4 controls after input',verified_inputs)
for key in ('stdout_path','stderr_path'):
    p=control_dir/pathlib.Path(control['command'][key]).name
    verify_declared(p,control['command'][key.replace('_path','_sha256')],f'execution-v4 {key}',verified_inputs)
contract_control_dir=WS/'build/contract-controls-v1'
contract_control=load_json(contract_control_dir/'receipt.json')
require(contract_control.get('status')=='PASS','base contract-controls status changed')
for key in ('stdout_path','stderr_path'):
    p=contract_control_dir/pathlib.Path(contract_control['command'][key]).name
    verify_declared(p,contract_control['command'][key.replace('_path','_sha256')],f'contract {key}',verified_inputs)

# Build a deterministic selected set. Raw reports/logs/observations are copied
# byte-for-byte before optional deterministic gzip; no compiled artifacts.
selected=[]
def add(src: pathlib.Path, archive_path: str, role: str, expected_sha: str|None=None):
    src=src.resolve(); archive_path=pathlib.PurePosixPath(archive_path).as_posix()
    require(src.is_file(),f'missing selected source: {src}')
    actual=sha(src)
    if expected_sha is not None: require(actual==expected_sha,f'selected artifact hash mismatch {src}: {actual} != {expected_sha}')
    selected.append({'src':src,'source_path':relroot(src),'archive_path':archive_path,'role':role,'source_sha256':actual,'source_bytes':src.stat().st_size})

# Bound handwritten/project source snapshot: preserve exact 48 local-source
# files compiled by the candidate; root Makefile/license/provenance are added.
local_source=report_data['build'].get('local_source',{})
source_dir=NATIVE/'source'
actual_source_files={p.relative_to(source_dir).as_posix():p for p in source_dir.rglob('*') if p.is_file()}
require(set(actual_source_files)==set(local_source),f'compiled source-tree path set differs: {len(actual_source_files)} files vs {len(local_source)} pins')
for rel, expected in sorted(local_source.items()):
    p=actual_source_files[rel]
    require(sha(p)==expected,f'compiled local source drift: {p}')
    require(sha(WS/rel)==expected,f'workspace source pin drift: {WS/rel}')
    add(p,'source/'+rel,'compiler-bound handwritten source',expected)
for path, dest, role in [
    (WS/'Makefile','source/Makefile','build entrypoint'),
    (ROOT/'LICENSE','source/LICENSE','project license'),
    (WS/'fpga/ddr/mig_c0_reference.json','source/fpga/ddr/mig_c0_reference.json','MIG source provenance'),
]: add(path,dest,role)
# Schema-4 execution-only contract/runner/tests and their nine-control receipt.
for rel in ('tools/ddr/run_read_snapshot_execution_v4.py','tools/ddr/read_snapshot_contract_v4.py','tests/ddr/read_snapshot/test_execution_v4.py'):
    add(WS/rel,'source/'+rel,'prospective schema-4 execution source')

# Build provenance and compile diagnostics, plus only the generated small
# parameter headers required to understand/replay the pinned source plan.
for name in ('report.json','compile.json','compile.log','compile_cpp.json','compile_cpp.log',
             'compile_translation.json','compile_translation.log','logic-plan.json'):
    add(NATIVE/name,'build/native/'+name,'native source-bound build receipt')
for name in ('logic_axi_parameters.svh','logic_ctrl_parameters.svh','logic_ui_parameters.svh','mc_parameters.svh'):
    add(NATIVE/'logic'/name,'build/native/logic/'+name,'generated source parameter header')
# Preserve every actual Verilator translation input, including only the MIG
# and primitive HDL files referenced by this accepted compile. Unused files in
# the vendor template/archive remain excluded.
declared_build_inputs={str(pathlib.Path(p).resolve()):h for p,h in report_data['build'].get('inputs',{}).items()}
source_prefix=(NATIVE/'source').resolve()
for source in report_data['build'].get('compiler_sources',[]):
    p=pathlib.Path(source).resolve()
    expected=declared_build_inputs.get(str(p))
    require(expected is not None,f'compiler source missing from build input hash manifest: {p}')
    require(sha(p)==expected,f'compiler source hash mismatch: {p}')
    try:
        rel=p.relative_to(source_prefix)
        require((DEST/'source'/rel).is_file() or rel.as_posix() in actual_source_files,
                f'handwritten compiler input is not in preserved source set: {rel}')
    except ValueError:
        rel=p.relative_to(NATIVE.resolve())
        add(p,'model-hdl/'+rel.as_posix(),'actual compiled MIG/primitive/model HDL input',expected)
for case_dir in sorted((NATIVE/'vectors').iterdir()):
    for name in ('expected.txt','upload.txt'):
        p=case_dir/name
        if p.is_file(): add(p,f'vectors/{case_dir.name}/{name}','raw backend vector/golden')

# Parent execution reports, and every declared textual artifact in their
# artifact maps (including the original failing A shard and its failed log).
stage_dirs={
  'matrix-a-original-failed':'evidence/matrix-a-original-failed',
  'matrix-a-exec-v4':'evidence/matrix-a-exec-v4',
  'matrix-b':'evidence/matrix-b',
  'matrix-c':'evidence/matrix-c',
  'repeat-sub-9':'evidence/repeat-sub-9',
}
for label, destdir in stage_dirs.items():
    report_path=REPORTS[label]; d=report_data[label]
    add(report_path,destdir+'/report.json',f'{label} parent report')
    for rel, expected in sorted(d.get('artifacts',{}).items()):
        src=report_path.parent/rel
        suffix=''.join(src.suffixes).lower()
        require(suffix.endswith(('.json','.log','.txt','.jsonl','.tsv','.csv','.md')),
                f'unexpected non-text selected run artifact: {src}')
        add(src,destdir+'/'+rel,f'{label} run receipt/log/full output',expected)

# Root review inputs and immutable union; the root-v1 recovery audit explicitly
# separates one accepted recovery case from its failed parent batch.
add(UNION,'review/all21.json','independent all21 union receipt',root_union_sha)
add(REVIEWER,'review/review_all21.py','independent all21 reviewer',union['reviewers'][str(REVIEWER)])
add(RECOVERY,'review/recovery-prefix.json','independent recovery-prefix audit',sha(RECOVERY))
add(RECOVERY_REVIEWER,'review/review_recovery_prefix.py','independent recovery-prefix reviewer',sha(RECOVERY_REVIEWER))
for d, label in ((control_dir,'execution-v4-controls'),(contract_control_dir,'base-contract-controls')):
    for name in ('receipt.json','stdout.log','stderr.log'):
        add(d/name,f'controls/{label}/{name}',f'{label} control receipt/log')

# Preserve an auditable input list for files verified but not copied, including
# vendor MIG body and tool binaries. Their full contents are intentionally out.
excluded_inputs=[]
for abs_path, info in sorted(verified_inputs.items()):
    p=pathlib.Path(abs_path)
    if p==pathlib.Path(report_data['build']['binary_path']).resolve(): reason='compiled native ELF excluded'
    elif '/logic/source/' in str(p) and str(p.resolve()) not in {str(pathlib.Path(x).resolve()) for x in report_data['build'].get('compiler_sources',[])}: reason='unused vendor MIG template/source bulk excluded; exact file hash retained'
    elif any(part in {'logic','obj'} for part in p.parts) and '/logic/' in str(p) and str(p.resolve()) not in {str(pathlib.Path(x).resolve()) for x in report_data['build'].get('compiler_sources',[])}: reason='unused generated vendor/model file excluded; exact file hash retained'
    elif p in [pathlib.Path(v['path']).resolve() for v in report_data['build'].get('tools',{}).values()]: reason='external compiler/tool excluded'
    else: continue
    excluded_inputs.append({'source_path':relroot(p),'bytes':info['bytes'],'sha256':info['sha256'],'reason':reason})

# Inputs outside hashed maps but explicitly represented by the accepted proof.
for tool, metadata in report_data['build'].get('tools',{}).items():
    excluded_inputs.append({'source_path':metadata['path'],'bytes':pathlib.Path(metadata['path']).stat().st_size,'sha256':metadata['sha256'],'version':metadata.get('version'),'reason':f'external {tool} binary/wrapper excluded'})

# Reject duplicate archive names before writing.
archives=[item['archive_path'] for item in selected]
require(len(archives)==len(set(archives)),'duplicate archive path in selected file set')

# Create destination only after all pre-copy validation succeeds.
DEST.mkdir(parents=True)
readme=(
"Selected evidence archive: optimized same-ELF all-21 logical DDR read-snapshot cases.\n"
"The accepted union is bound to one compiled native ELF and preserves all reports, logs, full observed BO text, vectors/goldens, source pins, and independent review receipts. The original matrix-A parent remains FAIL; its failed unknown-command run is preserved, while joint-reset recovery is admitted only by the separate successful per-case evidence and recovery-prefix audit.\n\n"
"Scope: selected frozen-local-source and actual logical 21-case text receipts, including every generated MIG/primitive/model HDL input used by the accepted compile. Unused vendor template/archive bulk and the native ELF/objects are excluded; this is not a full binary DAG or physical DDR proof. The scope is actual AXI/UI/MC with a modeled PHY. No physical DDR, FPGA/RK equivalence, or current CMAC-async qualification is claimed.\n"
).encode()
(DEST/'README.txt').write_bytes(readme)
file_index={}
file_index['README.txt']={
  'source_path':'generated from the accepted root union and explicit evidence-scope limits',
  'role':'archive scope and evidence boundary',
  'source_bytes':len(readme),'source_sha256':hashlib.sha256(readme).hexdigest(),
  'archive_path':'README.txt','archive_bytes':len(readme),
  'archive_sha256':sha(DEST/'README.txt'),'compression':'none'}

# Copy and verify every selected payload. Large text files use deterministic
# gzip mtime=0; index records source and stored byte/hash values.
for item in selected:
    src=item['src']; rel=item['archive_path']; dst=DEST/rel
    dst.parent.mkdir(parents=True,exist_ok=True)
    require(sha(src)==item['source_sha256'],f'source changed after preflight: {src}')
    raw=src.read_bytes()
    if len(raw)>16384:
        archive_rel=rel+'.gz'; dst=DEST/archive_rel; dst.parent.mkdir(parents=True,exist_ok=True)
        with dst.open('wb') as out:
            with gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0,compresslevel=9) as gz: gz.write(raw)
        compression='gzip_mtime0_level9'
    else:
        archive_rel=rel; dst.write_bytes(raw); compression='none'
    stored_sha=sha(dst)
    if compression!='none':
        with gzip.open(dst,'rb') as f: restored=f.read()
    else: restored=dst.read_bytes()
    require(len(restored)==len(raw) and hashlib.sha256(restored).hexdigest()==item['source_sha256'],f'copy/decompression mismatch: {rel}')
    require(sha(src)==item['source_sha256'],f'source drift during copy: {src}')
    file_index[rel]={
      'source_path':item['source_path'],'role':item['role'],
      'source_bytes':len(raw),'source_sha256':item['source_sha256'],
      'archive_path':archive_rel,'archive_bytes':dst.stat().st_size,'archive_sha256':stored_sha,
      'compression':compression,
    }

# Generated audit file: every declared input was rehashed before copying.
precopy={
 'status':'PASS_PRECOPY_HASH_AUDIT','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'root_union_path':relroot(UNION),'root_union_sha256':root_union_sha,
 'verified_unique_paths':len(verified_inputs),'verified_bytes':sum(x['bytes'] for x in verified_inputs.values()),
 'verified_inputs':{relroot(pathlib.Path(k)):v for k,v in sorted(verified_inputs.items())},
 'excluded_inputs':excluded_inputs,
}
precopy_bytes=(json.dumps(precopy,indent=2,sort_keys=True)+'\n').encode()
if len(precopy_bytes)>16384:
    with (DEST/'precopy-audit.json.gz').open('wb') as out:
        with gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0,compresslevel=9) as gz: gz.write(precopy_bytes)
    precopy_archive='precopy-audit.json.gz';precopy_compression='gzip_mtime0_level9'
else:
    (DEST/'precopy-audit.json').write_bytes(precopy_bytes)
    precopy_archive='precopy-audit.json';precopy_compression='none'
file_index['precopy-audit.json']={
 'source_path':'generated by build/archive_ddr_read_snapshot_all21.py','role':'full declared-input hash audit including excluded vendor/tool inputs',
 'source_bytes':len(precopy_bytes),'source_sha256':hashlib.sha256(precopy_bytes).hexdigest(),
 'archive_path':precopy_archive,'archive_bytes':(DEST/precopy_archive).stat().st_size,'archive_sha256':sha(DEST/precopy_archive),'compression':precopy_compression}

# Include a copy of the builder to make the selection recipe reviewable.
builder_bytes=BUILDER.read_bytes(); builder_hash=hashlib.sha256(builder_bytes).hexdigest()
(DEST/'archive_builder.py').write_bytes(builder_bytes)
file_index['archive_builder.py']={
 'source_path':relroot(BUILDER),'role':'archive construction and verification script',
 'source_bytes':len(builder_bytes),'source_sha256':builder_hash,
 'archive_path':'archive_builder.py','archive_bytes':len(builder_bytes),'archive_sha256':sha(DEST/'archive_builder.py'),'compression':'none'}

source_bytes=sum(v['source_bytes'] for v in file_index.values())
stored_bytes=sum(v['archive_bytes'] for v in file_index.values())
index={
 'schema':'selected-ddr-read-snapshot-all21-evidence-v1',
 'status':'PRESERVED_ACCEPTED_21_OF_21_SAME_ELF_LOGICAL_CASES_ONLY',
 'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'root_union_source_path':relroot(UNION),'root_union_sha256':root_union_sha,
 'case_count':21,'binary_sha256_excluded':BINARY_SHA,
 'scope':'selected frozen-local-source and actual logical 21-case text receipts, including all generated MIG/primitive/model HDL inputs used by accepted compile; unused vendor template/archive bulk and native ELF/objects excluded; not full binary DAG or physical DDR proof',
 'accepted_cases':sorted(union['cases']),
 'preserved_failure':'Original matrix A parent remains FAIL. The historical unknown_command failure/run log is included. joint_reset_recovery is accepted only by its successful per-case receipt and separate recovery-prefix audit; parent failure is not relabeled.',
 'evidence_boundary':{'hardware_accessed':False,'vivado_executed_for_these_cases':False,'physical_integration_ready':False,'fpga_or_rk_equivalence':False,'physical_ddr_proof':False,'cmac_async_qualification':False,'scope_detail':'actual_AXI_UI_MC_modeled_PHY; test/model evidence only'},
 'exec_v4_prospective_controls':{'status':control['status'],'passed_tests':9,'schema_version':4,'receipt_path':'controls/execution-v4-controls/receipt.json'},
 'file_count':len(file_index),'source_bytes_total':source_bytes,'stored_bytes_total':stored_bytes,
 'compression_policy':'files larger than 16384 bytes use deterministic gzip mtime=0 level 9; all decompressed payloads rehashed and byte-count checked',
 'excluded_bound_artifacts':excluded_inputs,
 'files':file_index,
}
(DEST/'index.json').write_text(json.dumps(index,indent=2,sort_keys=True)+'\n')
# Secondary simple checksum manifest covers index plus each stored file.
lines=[]
for rel,entry in sorted(file_index.items()): lines.append(f"{entry['archive_sha256']}  {entry['archive_path']}")
lines.append(f"{sha(DEST/'index.json')}  index.json")
(DEST/'archive_SHA256SUMS').write_text('\n'.join(lines)+'\n')
# Final audit of every indexed stored file and decompressed source hash.
for rel,entry in file_index.items():
    p=DEST/entry['archive_path']; require(sha(p)==entry['archive_sha256'],f'final stored hash mismatch {p}')
    if entry['compression'].startswith('gzip'):
        with gzip.open(p,'rb') as f: rawhash=hashlib.sha256(f.read()).hexdigest()
    else: rawhash=sha(p)
    require(rawhash==entry['source_sha256'],f'final logical payload hash mismatch {rel}')
print(json.dumps({'status':index['status'],'archive':str(DEST),'index_sha256':sha(DEST/'index.json'),
 'files':index['file_count'],'source_bytes':source_bytes,'stored_bytes':stored_bytes,
 'verified_reported_paths':len(verified_inputs),'excluded_compiled_and_vendor_items':len(excluded_inputs)},indent=2))
