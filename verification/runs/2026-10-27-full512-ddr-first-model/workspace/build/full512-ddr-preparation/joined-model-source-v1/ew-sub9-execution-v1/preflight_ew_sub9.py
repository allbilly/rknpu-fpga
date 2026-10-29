#!/usr/bin/env python3
"""Read-only hash/parameter preflight for the same-ELF EW SUB9 joined model run."""
import hashlib,json,time
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga');BASE=ROOT/'build/full512-ddr-preparation/joined-model-source-v1'
OUT=BASE/'ew-sub9-execution-v1';PREP=BASE/'preparation.json';CASE=OUT/'preparation.json'
COMPILE=BASE/'native-compile-v2/report.json';CMAC_REVIEW=BASE/'first-cmac-root-review-v1.json'
PARENT=ROOT/'build/ddr-read-snapshot-candidate/v2/workspace/build/ddr-endpoint-async/native-read-snapshot-v3'
PARENT_REPORT=PARENT/'report.json';SOURCE_FIX=PARENT/'vectors/capture_sub_9';DEST_FIX=OUT/'vectors/capture_sub_9'
PREFLIGHT=OUT/'offline-preflight-v2.json'
BIN=BASE/'native-compile-v2/obj/Vtb_jtag_dual_ddr_async';RUNNER=OUT/'run_first_ew.py';PREPARE=BASE/'prepare_ew_sub9.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
prep=json.loads(PREP.read_text());case=json.loads(CASE.read_text());compiled=json.loads(COMPILE.read_text());review=json.loads(CMAC_REVIEW.read_text());parent=json.loads(PARENT_REPORT.read_text())
if prep['status']!='PREPARED_REAL_FULL512_DUAL_AXI_UI_MC_TEST_WITH_MODELED_PHY_ONLY' or prep['top']!='tb_jtag_dual_ddr_async':raise SystemExit('joined source package changed')
if compiled['status']!='PASS_JOINED_MODEL_NATIVE_COMPILE_ONLY' or compiled['binary_sha256']!='ca017f2afc191f4a07c681e2dc4648063997ee6ac35264695554c33eb4e9bf2e':raise SystemExit('same joined ELF not compile-qualified')
if review['status']!='PASS_INDEPENDENT_FIRST_FULL512_CMAC_AXI_UI_MC_K65_MODEL_ONLY' or review['binary_sha256']!=compiled['binary_sha256']:raise SystemExit('CMAC joined model root review binding changed')
if parent['status']!='PASS_READ_SNAPSHOT_DDR_NATIVE_BUILD_ONLY':raise SystemExit('parent capture status changed')
required={'csr_base':0,'start':'0x100e0000','amount':35,'ntasks':2,'nlines':1600,'jobs':1,'negative':0,'reset_recovery':0}
if any(case['case'].get(k)!=v for k,v in required.items()):raise SystemExit('EW parameters changed')
if case['prospective_counts']['phy_user_returns']!=6920 or case['prospective_counts']['read64_packets']!=1602 or case['prospective_counts']['read64_axi_reads']!=1602:raise SystemExit('EW prospective counts changed')
inputs=dict(prep['inputs'])|dict(prep['files'])|dict(compiled['source_hashes_before'])
inputs.update({str(PREP):sha(PREP),str(CASE):sha(CASE),str(COMPILE):sha(COMPILE),str(CMAC_REVIEW):sha(CMAC_REVIEW),
    str(PARENT_REPORT):sha(PARENT_REPORT),str(BIN):sha(BIN),str(RUNNER):sha(RUNNER),str(PREPARE):sha(PREPARE),str(Path(__file__).resolve()):sha(__file__)})
for name in ('upload.txt','expected.txt'):
    src=SOURCE_FIX/name;dst=DEST_FIX/name
    original=case['vectors'][str(src)]['source_sha256']
    if sha(src)!=original or sha(dst)!=original or src.read_bytes()!=dst.read_bytes():raise SystemExit('Original/copy EW vector mismatch: '+name)
    inputs[str(src)]=sha(src);inputs[str(dst)]=sha(dst)
before={p:sha(p) for p in inputs}
if before!=inputs:raise SystemExit('EW preflight input hash mismatch')
if sum(int(line.split()[1],16)!=0 for line in (DEST_FIX/'upload.txt').read_text().splitlines())!=77:raise SystemExit('EW nonzero upload count changed')
report={'status':'PASS_OFFLINE_EW_SUB9_SAME_ELF_PREFLIGHT_ONLY','created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
 'scope':'offline source/fixture/parameter verification only; no simulator execution',
 'parent_snapshot_report':str(PARENT_REPORT),'parent_snapshot_sha256':sha(PARENT_REPORT),'joined_preparation_sha256':sha(PREP),
 'joined_compile_report_sha256':sha(COMPILE),'same_elf_sha256':sha(BIN),'same_elf_expected_sha256':compiled['binary_sha256'],
 'cmac_independent_review_sha256':sha(CMAC_REVIEW),'ew_parameters':case['case'],'prospective_counts':case['prospective_counts'],
 'fixture_copies_byte_equal':True,'source_hashes_before':before,'source_hashes_after':{p:sha(p) for p in inputs},
 'all_inputs_unchanged':before=={p:sha(p) for p in inputs},'numerical_execution_performed':False,'hardware_accessed':False}
if not report['all_inputs_unchanged']:raise SystemExit('Input changed during offline preflight')
(PREFLIGHT).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'input_count':len(inputs),'binary_sha256':report['same_elf_sha256'],'nonzero_upload':77,'read64_packets':1602,'phy_user_returns':6920},indent=2))
