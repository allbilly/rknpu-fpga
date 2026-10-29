from __future__ import annotations
import ast,hashlib,json,pathlib,shutil,sys
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=ROOT/'build/fpga-bringup/full512-ddr-model-prep-v5'
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def resolve_module(name):
    base=name.replace('.','/');module=ROOT/(base+'.py');package=ROOT/base/'__init__.py'
    return module if module.is_file() else package if package.is_file() else None
def imported_tools(path):
    tree=ast.parse(pathlib.Path(path).read_text(),filename=str(path));out=set()
    for n in ast.walk(tree):
        if isinstance(n,ast.Import):out.update(x.name for x in n.names if x.name.startswith('tools.'))
        elif isinstance(n,ast.ImportFrom) and n.module and n.module.startswith('tools.'):out.add(n.module)
    return out
def closure(starts):
    files={pathlib.Path(p) for p in starts};modules=set();queue=list(files)
    while queue:
        p=queue.pop()
        for name in imported_tools(ROOT/p):
            modules.add(name);f=resolve_module(name)
            if f is not None:
                rel=f.relative_to(ROOT)
                if rel not in files:files.add(rel);queue.append(rel)
    return {p.as_posix():sha(ROOT/p) for p in sorted(files)},sorted(modules)

prep_path=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/image-preparation.json'
review_path=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/root-emission-review.json'
bindings_path=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/root-bindings.json'
image_review_path=ROOT/'build/full512-ddr-preparation/full512-bitfile-audit-v2/v12-image-review.json'
image_audit_path=ROOT/'build/full512-ddr-preparation/full512-bitfile-audit-v2/v12-image-audit.json'
image=json.loads(prep_path.read_text());manifest=image['hardware_source_manifest']
model=ROOT/'build/tinystories-preparation/260k-first-v2';model_report=json.loads((model/'report.json').read_text())
catalog=ROOT/'build/tinystories-programs/all-v1/report.json';catalog_report=json.loads(catalog.read_text())
reference=ROOT/'build/tinystories-full-oracle/v1';reference_report=json.loads((reference/'report.json').read_text())
trained_vectors=ROOT/'build/full512-ddr-preparation/trained-alternation-source-v2/vectors'
trained_vectors_report=json.loads((trained_vectors/'report.json').read_text())
trained6=ROOT/'build/fpga-bringup/full512-ddr-trained-prep-v6'
trained_run=trained6/'physical-test/report.json';trained_worker=trained6/'physical-test/trained-tile/report.json'
trained_audit=trained6/'physical-test/trained-audit.json';trained_root=trained6/'root-trained-tile-review.json'
trained_wire=trained6/'root-independent-trained-wire-review.json';trained_execution=trained6/'root-execution-review.json'
trained_report=json.loads(trained_run.read_text());trained_root_review=json.loads(trained_root.read_text())
canonical_review=json.loads(image_review_path.read_text());canonical_audit=json.loads(image_audit_path.read_text())
assert canonical_review['status']=='PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE'
assert canonical_review['bitstream']['sha256']=='d627b7155c4a4ad6b948424fbd28240a666ea6071bfe8c5d5b19f7da051b0031'
assert canonical_audit['status']=='PASS_FULL512_DDR_BITFILE_AND_EMISSION_AUDIT_ONLY'
assert trained_root_review['status']=='ROOT_REVIEWED_FULL512_CH1_DDR_TRAINED_TILE' and trained_root_review['accepted'] is True
assert trained_root_review['source_sha256']=='5e99f881eea21ff01bdf02f02435c7722a5ef78b820308727ac84f39edf0981f'
digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
assert digest=='5e99f881eea21ff01bdf02f02435c7722a5ef78b820308727ac84f39edf0981f'
starts=['tools/tinystories/run_model.py','tools/tinystories/audit_model.py','tools/ddr/raw_test.py',
        'tools/host/native_link.py','tools/tinystories/prepare.py','tools/tinystories/progress.py']
runtime,modules=closure(starts);runtime['fpga/host/native_rpc.tcl.in']=sha(ROOT/'fpga/host/native_rpc.tcl.in')
private=['run_full_model.py','program-template.tcl.in','test_preflight.py','test_process_controls.py','test_runner_global_bindings.py','v4-prior-run-preservation.json']
tool_paths=['/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/vivado_lab','/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/hw_server',
            shutil.which('python3'),sys.executable,shutil.which('lsusb'),shutil.which('fuser'),shutil.which('cc')]
lease=pathlib.Path('/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock')
d={'schema':'full512-ddr-tinystories-model-preparation-v1','status':'UNLAUNCHABLE_FULL512_DDR_TINYSTORIES_MODEL_PREPARATION',
 'scope':'Offline-only preparation for exactly one volatile image load and three same-epoch DDR model phases. Physical execution requires a separately reviewed trained-tile prerequisite, an exact image review, and distinct root execution approval.',
 'source_manifest':manifest,'source_manifest_sha256':digest,'source_tag':digest[:8],
 'full512_image_preparation_path':prep_path.relative_to(ROOT).as_posix(),'full512_image_preparation_sha256':sha(prep_path),
 'full512_root_emission_review_path':review_path.relative_to(ROOT).as_posix(),'full512_root_emission_review_sha256':sha(review_path),
 'full512_root_bindings_path':bindings_path.relative_to(ROOT).as_posix(),'full512_root_bindings_sha256':sha(bindings_path),
 'canonical_v12_image_review_path':image_review_path.relative_to(ROOT).as_posix(),
 'canonical_v12_image_review_sha256':sha(image_review_path),
 'canonical_v12_bitfile_audit_path':image_audit_path.relative_to(ROOT).as_posix(),
 'canonical_v12_bitfile_audit_sha256':sha(image_audit_path),
 'candidate_emitted_bitstream_path':canonical_review['bitstream']['path'],
 'candidate_emitted_bitstream_sha256':canonical_review['bitstream']['sha256'],
 'candidate_software_crc_validation':canonical_review['software_crc_validation'],
 'model_package_path':model.relative_to(ROOT).as_posix(),'model_package_report_sha256':sha(model/'report.json'),
 'model_package_files':model_report['files'],'model_sha256':model_report['model_sha256'],'tokenizer_sha256':model_report['tokenizer_sha256'],
 'catalog_report_path':catalog.relative_to(ROOT).as_posix(),'catalog_report_sha256':sha(catalog),
 'oracle_reference_path':reference.relative_to(ROOT).as_posix(),'oracle_reference_report_sha256':sha(reference/'report.json'),
 'oracle_reference_artifacts':reference_report['artifacts'],
 'trained_vectors_path':trained_vectors.relative_to(ROOT).as_posix(),
 'trained_vectors_report_sha256':sha(trained_vectors/'report.json'),
 'trained_vectors_files':trained_vectors_report['files'],
 'trained_tile_candidate':{'status':trained_root_review['status'],'accepted':trained_root_review['accepted'],
  'scope':trained_root_review['scope'],'source_sha256':trained_root_review['source_sha256'],
  'source_tag':trained_root_review['source_tag'],'image_review_sha256':trained_root_review['image_review_sha256'],
  'bitstream_sha256':trained_root_review['bitstream_sha256'],
  'run_report_path':trained_run.relative_to(ROOT).as_posix(),'run_report_sha256':sha(trained_run),
  'worker_report_path':trained_worker.relative_to(ROOT).as_posix(),'worker_report_sha256':sha(trained_worker),
  'independent_audit_path':trained_audit.relative_to(ROOT).as_posix(),'independent_audit_sha256':sha(trained_audit),
  'root_review_path':trained_root.relative_to(ROOT).as_posix(),'root_review_sha256':sha(trained_root),
  'independent_wire_review_path':trained_wire.relative_to(ROOT).as_posix(),'independent_wire_review_sha256':sha(trained_wire),
  'trained_trial_execution_review_path':trained_execution.relative_to(ROOT).as_posix(),
  'trained_trial_execution_review_sha256':sha(trained_execution),
  'physical_artifacts':{str(trained6/'physical-test'/name):digest for name,digest in trained_report['artifacts'].items()}},
 'runtime_source_hashes':runtime,'runtime_import_modules':modules,
 'private_source_hashes':{n:sha(PKG/n) for n in private},
 'tool_hashes':{n:sha(n) for n in tool_paths},
 'tool_version_policy':{'vivado_lab':'2026.1.1 path/hash bound; offline preparation did not launch it',
                       'python':sys.version.splitlines()[0]},
 'expected_image_review_status':'PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE',
 'expected_profile':{'top':'ypcb_ddr_dual_top','part':'xc7k480tffg1156-2','memory_profile':'ddr',
  'selected_physical_channel':1,'product_dsps':512,'total_dsps':516,'bram_blocks':0,
  'target':'localhost:3125/xilinx_tcf/Xilinx/80802026a77a01','expected_dna_port':'004E544714C705C','expected_raw_idcode':'23751093',
  'source_sha256':digest,'usr_access':digest[:8],'programming_scope':'volatile-sram','flash_authorized':False},
 'trained_tile_prerequisite_path':'trained-tile-prerequisite.json','trained_tile_prerequisite_sha256':None,
 'image_review_path':'image-review.json','image_review_sha256':None,'bitstream_path':None,'bitstream_sha256':None,
 'execution_approval_path':'execution-approval.json','execution_approval_sha256':None,
 'phase_contract':[{'name':'one-complete-forward-position','steps':1,'prompt':''},
                   {'name':'repeated-complete-forward-position','steps':1,'prompt':''},
                   {'name':'greedy32','steps':32,'prompt':'Once upon a time'}],
 'worker_contract':{'backend':'jtag','memory_profile':'ddr','port':3721,'min_mem_available_mib':2048,
  'memory_wait_budget_seconds':900,'per_worker_timeout_seconds':14400,'quit_bridge':True,
  'cpu_dense_fallback':False,'learned_dense_cpu_fallback':False,'fabric_reset_between_phases':False,'volatile_load_count':1,
  'idle_wait_only_between_completed_projections':True},
 'audit_contract':{'script':'tools/tinystories/audit_model.py','memory_profile':'ddr','audit_after_each_phase':True,
  'complete_raw_dense_and_logit_bytes_before_next_phase':True,'phase_order':[x['name'] for x in [
      {'name':'one-complete-forward-position'},{'name':'repeated-complete-forward-position'},{'name':'greedy32'}]]},
 'resource_policy':{'preload_mem_available_mib':4096,'phase_psi_memory_full_avg10_max_exclusive':1.0,
  'worker_mem_available_mib':2048,'worker_cumulative_idle_wait_budget_seconds':900,
  'worker_timeout_seconds':14400,'whole_trial_timeout_seconds':None},
 'lease_path':str(lease),'lease_inode':lease.stat().st_ino,'lease_bytes':lease.stat().st_size,
 'hardware_accessed':False,'flash_written':False,'vivado_executed':False,'model_run_executed':False,
 'prior_v4_run_preservation_path':(PKG/'v4-prior-run-preservation.json').relative_to(ROOT).as_posix(),
 'prior_v4_run_preservation_sha256':sha(PKG/'v4-prior-run-preservation.json'),
 'preparation_generator_path':(PKG/'create_preparation.py').relative_to(ROOT).as_posix(),
 'preparation_generator_sha256':sha(PKG/'create_preparation.py')}
(PKG/'preparation.json').write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':d['status'],'manifest_sha256':digest,'source_files':len(manifest['files']),
 'model_package_files':len(d['model_package_files']),'runtime_source_files':len(runtime),'runtime_import_modules':len(modules),
 'catalog_sha256':d['catalog_report_sha256'],'oracle_reference_report_sha256':d['oracle_reference_report_sha256'],
 'oracle_reference_artifacts':len(d['oracle_reference_artifacts']),'lease_inode':d['lease_inode']},indent=2))
