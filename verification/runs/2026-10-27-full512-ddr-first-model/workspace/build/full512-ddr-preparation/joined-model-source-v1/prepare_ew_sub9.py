#!/usr/bin/env python3
"""Copy only the original SUB9 BO pair for the joined-model EW namespace run."""
import hashlib,json,shutil,time
from pathlib import Path
ROOT=Path('/home/fedora/rknpu-fpga')
BASE=ROOT/'build/full512-ddr-preparation/joined-model-source-v1'
OUT=BASE/'ew-sub9-execution-v1'
PARENT=ROOT/'build/ddr-read-snapshot-candidate/v2/workspace/build/ddr-endpoint-async/native-read-snapshot-v3'
FIX=PARENT/'vectors/capture_sub_9'
SOURCE_REPORT=PARENT/'report.json'
EXPECTED={'upload.txt':'68cf7b0689343f22c979db0312eb718906a34d51c54e893699039f7630c885fb',
          'expected.txt':'aca0f96badf878e82a9358eb2e5405f1ff97db706220e25e712555c38f10efec'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if OUT.exists():raise SystemExit('EW output already exists')
parent_report=json.loads(SOURCE_REPORT.read_text())
if parent_report['status']!='PASS_READ_SNAPSHOT_DDR_NATIVE_BUILD_ONLY':raise SystemExit('parent native snapshot status changed')
rows={}
for name,digest in EXPECTED.items():
    src=FIX/name
    if sha(src)!=digest:raise SystemExit('original SUB9 fixture hash mismatch: '+name)
    text=src.read_text();lines=text.splitlines()
    if len(lines)!=1600 or any(len(line)!=137 or line[8]!=' ' for line in lines):raise SystemExit('original SUB9 line format/count changed')
    address=[int(line[:8],16) for line in lines]
    if address!=sorted(set(address)) or any(x%64 for x in address):raise SystemExit('original SUB9 addresses changed')
    rows[name]=(lines,address)
upload_nonzero=sum(int(line[9:],16)!=0 for line in rows['upload.txt'][0])
if upload_nonzero!=77 or rows['upload.txt'][1]!=rows['expected.txt'][1]:raise SystemExit('original EW workload rows/count changed')
OUT.mkdir()
dest=OUT/'vectors/capture_sub_9';dest.mkdir(parents=True)
for name in EXPECTED:shutil.copyfile(FIX/name,dest/name)
if any(sha(dest/name)!=EXPECTED[name] for name in EXPECTED):raise SystemExit('copied EW fixture differs from original')
prep={
 'status':'PREPARED_SAME_ELF_EW_SUB9_ORIGINAL_BO_PAIR_ONLY',
 'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
 'scope':'same joined controller binary; original captured SUB9 raw BO pair, EW CSR namespace0 only; no numerical re-encoding/PHY or hardware claim',
 'parent_snapshot_report':str(SOURCE_REPORT),'parent_snapshot_report_sha256':sha(SOURCE_REPORT),
 'parent_vector_dir':str(FIX),'ew_vector_dir':str(dest),
 'vectors':{str(FIX/name):{'source_sha256':EXPECTED[name],'source_bytes':(FIX/name).stat().st_size,
       'copy':str(dest/name),'copy_sha256':sha(dest/name),'copy_bytes':(dest/name).stat().st_size} for name in EXPECTED},
 'case':{'csr_base':0,'start':'0x100e0000','amount':35,'ntasks':2,'nlines':1600,'jobs':1,'negative':0,'reset_recovery':0,
         'uploaded_nonzero':77,'complete_bo_bytes':102400},
 'prospective_counts':{'read64_packets':1602,'read64_axi_reads':1602,
     'phy_user_returns_formula':'65 + 1602 + 77*64 + 4*(35+22) + 3*16*2 + 1',
     'phy_user_returns':65+1602+77*64+4*(35+22)+3*16*2+1},
 'golden_or_command_bytes_modified':False,'arithmetic_or_layout_repair':False,
 'numerical_execution_performed':False,'hardware_accessed':False,'physical_phy_or_ddr_qualified':False}
if prep['prospective_counts']['phy_user_returns']!=6920:raise SystemExit('prospective EW PHY count mismatch')
(OUT/'preparation.json').write_text(json.dumps(prep,indent=2)+'\n')
print(json.dumps({'status':prep['status'],'output':str(OUT),'fixture_hashes':{Path(k).name:v['copy_sha256'] for k,v in prep['vectors'].items()},'nonzero':upload_nonzero,'phy_returns':prep['prospective_counts']['phy_user_returns']},indent=2))
