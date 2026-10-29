from pathlib import Path
import hashlib,json,shutil,datetime
ROOT=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent;P=W/'physical-tests'
OUT=ROOT/'verification/runs/2026-10-27-full512-regmem-fpga'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,msg):
 if not ok:raise ValueError(msg)
r=json.loads((P/'report.json').read_text());need(r['status']=='PASS_CMAC512_PHYSICAL_STARTUP_AND_RECONFIGURATION','Incomplete hardware run')
need(not OUT.exists(),'Fresh archive required');OUT.mkdir(parents=True);files={}
def copy(src,name,role):
 src=Path(src);data=src.read_bytes();data.decode('utf-8');need(src.suffix not in ['.bit','.dcp','.vvp','.so','.pyc'],'Binary archive forbidden')
 dst=OUT/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst);need(sha(src)==sha(dst),'Copy mismatch');files[name]=dict(sha256=sha(dst),bytes=len(data),origin=str(src.relative_to(ROOT)),role=role)
for name,h in r['artifacts'].items():need(sha(P/name)==h,'Recorded physical artifact changed')
for src in W.rglob('*'):
 if src.is_file() and '__pycache__' not in src.parts:copy(src,'hardware/'+str(src.relative_to(W)),'actual source/image/load/SAMPLE evidence; source code snapshots and raw data retained')
audit=ROOT/'build/full512-regmem-physical-offline-audit-v2-20261026T163432Z.json';ar=json.loads(audit.read_text());need('PASS' in ar['status'],'Offline audit incomplete')
copy(audit,'review/offline-observation-audit-v2.json','all128 checks/292 artifact hashes; corrected storedkind use')
copy(ROOT/'build/full512-regmem-physical-offline-audit-20261026T163042Z.json','review/original-offline-audit-FAIL.json','original audit usedpost-load instead ofreconfiguration; producer unchanged')
for name in ['run.json','root-timing-review.json','root-init-drc-review.json']:
 copy(ROOT/'build/full512-regmem-implementation/20261026T111740Z'/name,'implementation/'+name,'source-bound route/native review')
copy(ROOT/'build/regmem-closed-mapped-replay/20261026T122537Z-lutproof/report.json','implementation/mapped-startup-report.json','complete proof-bound mapped startup and expectedrejection')
copy(ROOT/'build/full512-regmem-implementation/20261026T111740Z/image-command-qualified/emission-launch-20261026T160613Z/report.json','implementation/image-emission-report.json','actual native bitgen, nohardware call')
copy(ROOT/'rtl/vendor/nvdla/LICENSE','licenses/NVDLA-LICENSE','license for copied NVIDIA source files')
index=dict(schema_version=1,status='PRESERVED_FULL512_FPGA_STARTUP_AND_RECONFIGURATION',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),scope='Actual autonomous finiteK65 fullC32/K16 source-bound BRAM-scoreboard output observations and repeatedvolatileconfiguration only; no directRAM/host/DDR/PCIe/generalGEMM/RK equivalence/electrical/optical/frequency signoff',source_sha256='ac6fee7e5ebd29b85c727349c5b2def80ba8f7876ceae76ff0bc0b47750ce25d',bitstream_sha256=r['bitstream_sha256'],part='xc7k480tffg1156-2',loads=3,reconfigurations=2,positive_captures=4,positive_samples=404,heartbeat_transitions=32,baseline_samples_excluded=101,hardware_programmed=True,flash_written=False,bitstream_included=False,binary_checkpoint_or_simulator_included=False,files=files)
(OUT/'index.json').write_text(json.dumps(index,indent=2)+'\n');print(OUT/'index.json');print('files',len(files),'bytes',sum(v['bytes'] for v in files.values()))
