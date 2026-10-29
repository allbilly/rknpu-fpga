from __future__ import annotations
import hashlib,json,pathlib,sys,shutil
ROOT=pathlib.Path('/home/fedora/rknpu-fpga'); PKG=ROOT/'build/fpga-bringup/full512-ddr-trained-prep-v6'
def sha(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
prep_path=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/image-preparation.json'
review_path=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/root-emission-review.json'
bindings_path=ROOT/'build/full512-ddr-preparation/full512-image-prep-v12/root-bindings.json'
source=json.loads(prep_path.read_text()); manifest=source['hardware_source_manifest']
vectors=ROOT/'build/full512-ddr-preparation/trained-alternation-source-v2/vectors'
vector_report=json.loads((vectors/'report.json').read_text())
runtime=[
 'tools/tinystories/run_projection.py','tools/ddr/audit_trained_tile.py',
 'tools/ddr/dual_transport.py','tools/ddr/raw_test.py','tools/ddr/transport.py',
 'tools/ddr/interface.py','tools/host/native_link.py','tools/host/transport.py',
 'tools/tinystories/native_trace.py','tools/tinystories/prepare.py',
 'tools/tinystories/audit_scans.py','tools/hardware/sample_ew.py','fpga/host/native_rpc.tcl.in',
 'tools/tinystories/progress.py','tools/tinystories/transport.py',
 'tools/host/__init__.py','tools/ddr/__init__.py','tools/tinystories/__init__.py',
]
private=['run_sram_test.py','program-template.tcl.in','audit_scratch.py',
         'test_scratch_audit.py','test_scratch_native.py','test_preflight.py','test_process_controls.py',
         'test_runtime_import_path.py']
tools=['/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/vivado_lab',
       '/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/hw_server',
       shutil.which('python3'),shutil.which('lsusb'),shutil.which('fuser')]
lease=pathlib.Path('/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock')
digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
assert digest=='5e99f881eea21ff01bdf02f02435c7722a5ef78b820308727ac84f39edf0981f'
d={
 'schema':'full512-ddr-trained-volatile-preparation-v2',
 'preparation_revision':'v6',
 'status':'UNLAUNCHABLE_FULL512_DDR_TRAINED_TRIAL_PREPARATION',
 'scope':'Private preparation only. Offline preflight is the only currently admissible operation; image emission is still pending. Hardware execution requires a separately reviewed exact emitted image and a distinct root approval bound into this package.',
 'top':manifest['top'],'part':manifest['part'],'source_manifest':manifest,
 'source_manifest_sha256':digest,'source_tag':digest[:8],
 'expected_image_review_status':'PASS_REVIEWED_FULL512_CH1_DDR_DUAL_IMAGE',
 'expected_resource_contract':{'memory_profile':'ddr','selected_physical_channel':1,
                               'product_dsps':512,'total_dsps':516,'bram_blocks':0},
 'expected_target':'localhost:3125/xilinx_tcf/Xilinx/80802026a77a01',
 'expected_dna_port':'004E544714C705C','expected_raw_idcode':'23751093',
 'programming_scope':'volatile-sram','flash_authorized':False,
 'full512_image_preparation_path':prep_path.relative_to(ROOT).as_posix(),
 'full512_image_preparation_sha256':sha(prep_path),
 'full512_root_preparation_review_path':review_path.relative_to(ROOT).as_posix(),
 'full512_root_preparation_review_sha256':sha(review_path),
 'full512_root_bindings_path':bindings_path.relative_to(ROOT).as_posix(),
 'full512_root_bindings_sha256':sha(bindings_path),
 'preparation_generator_path':(PKG/'create_preparation.py').relative_to(ROOT).as_posix(),
 'preparation_generator_sha256':sha(PKG/'create_preparation.py'),
 'adapted_from':{
  'runner_path':'build/fpga-bringup/ddr-ch1-first-v1/run_sram_test.py',
  'runner_sha256':sha(ROOT/'build/fpga-bringup/ddr-ch1-first-v1/run_sram_test.py'),
  'program_template_path':'build/fpga-bringup/ddr-ch1-first-v1/program-template.tcl.in',
  'program_template_sha256':sha(ROOT/'build/fpga-bringup/ddr-ch1-first-v1/program-template.tcl.in')},
 'hardware_source_file_count':len(manifest['files']),
 'trained_vectors_path':vectors.relative_to(ROOT).as_posix(),
 'trained_vectors_report_sha256':sha(vectors/'report.json'),
 'trained_vectors_files':vector_report['files'],
 'trained_vectors_contract':{'status':vector_report['status'],'lines':vector_report['lines'],
                             'cmac_amount':vector_report['cmac_amount'],'ew_amount':vector_report['ew_amount']},
 'runtime_source_hashes':{p:sha(ROOT/p) for p in runtime},
 'private_source_hashes':{p:sha(PKG/p) for p in private},
 'scratch_auditor_sha256':sha(PKG/'audit_scratch.py'),
 'tool_hashes':{p:sha(p) for p in tools},
 'tool_version_policy':{'vivado_lab':'2026.1.1 binary hash bound; version command deliberately not run during offline preparation',
                        'python3':sys.version.splitlines()[0]},
 'lease_path':str(lease),'lease_inode':lease.stat().st_ino,'lease_bytes':lease.stat().st_size,
 'image_review_path':'image-review.json','image_review_sha256':None,
 'bitstream_path':None,'bitstream_sha256':None,
 'execution_approval_path':'execution-approval.json','execution_approval_sha256':None,
 'final_execution_approval':False,'hardware_accessed':False,'flash_written':False,
 'future_execution_order':['exact image review + separate root approval gate','existing lease and USB/port/controller admission',
  'hash checks before hardware and before PROGRAM.FILE','volatile SRAM load only','fixed six-line/two-order scratch via DualDdrRawTransport with independent raw-wire audit',
  'close scratch transport','unchanged run_projection.py --memory-profile ddr --port 3721 --quit-bridge with bound trained vectors',
  'independent audit_trained_tile.py over complete worker bytes and trace'],
 'constraints':['no CPU arithmetic/layout fixups','no source/vector regeneration','unsupported controller writes remain failures',
  'no flash/program-file write','physical DDR capacity/ECC/recovery/full512/PCIe/electrical qualification remain false until separately evidenced']
}
(PKG/'preparation.json').write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':d['status'],'manifest_sha256':digest,'source_files':len(manifest['files']),
                  'vectors_report_sha256':d['trained_vectors_report_sha256'],'private_hashes':len(private),
                  'runtime_hashes':len(runtime),'tool_hashes':len(tools),'lease_inode':d['lease_inode']},indent=2))
