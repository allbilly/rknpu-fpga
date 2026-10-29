"""Bind unchanged joined workload/fault bench to the private shared-data RTL."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path('/home/fedora/rknpu-fpga');BASE=ROOT/'build/full512-ddr-preparation'
PARENT=BASE/'joined-model-source-v1';CANDIDATE=BASE/'shared-data-candidate-v2';OUT=BASE/'shared-data-fault-model-v1'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert not OUT.exists()
p=json.loads((PARENT/'preparation.json').read_text());c=json.loads((CANDIDATE/'preparation.json').read_text())
assert all(sha(n)==h for n,h in p['inputs'].items())
assert all(sha(n)==h for n,h in p['files'].items())
assert all(sha(n)==h for n,h in c['files'].items())
OUT.mkdir();inputs=dict(p['inputs'])|dict(p['files'])|dict(c['files'])
for f in [PARENT/'preparation.json',CANDIDATE/'preparation.json',Path(__file__).resolve()]:inputs[str(f)]=sha(f)
files={};sources=[];deltas=[]
replace={'rk_cmac_fp16_array_dsp_prefix_pipe.sv','rk_cmac_fp16_cell_dsp_prefix_pipe.sv'}
for row in p['hdl_sources']:
 old=Path(row['path']);source=CANDIDATE/old.name if old.name in replace else old
 assert sha(old)==row['sha256']
 target=OUT/'source'/f'{len(sources):03d}'/source.name;target.parent.mkdir(parents=True);shutil.copyfile(source,target)
 sources.append(dict(path=str(target),sha256=sha(target),original=str(source),original_sha256=sha(source)));files[str(target)]=sha(target)
 if source!=old:deltas.append(dict(name=source.name,reference_sha256=sha(old),candidate_sha256=sha(source)))
source=CANDIDATE/'rk_cmac_fp16_shared_data.sv';target=OUT/'source'/f'{len(sources):03d}'/source.name;target.parent.mkdir(parents=True);shutil.copyfile(source,target)
sources.append(dict(path=str(target),sha256=sha(target),original=str(source),original_sha256=sha(source)));files[str(target)]=sha(target)
bench=OUT/'tb_jtag_dual_ddr_async.sv';shutil.copyfile(p['bench'],bench);files[str(bench)]=sha(bench)
headers={}
for macro,name in p['headers'].items():
 original=Path(name);target=OUT/'headers'/original.name;target.parent.mkdir(exist_ok=True);shutil.copyfile(original,target);files[str(target)]=sha(target);headers[macro]=str(target)
assert len(sources)==112 and len(deltas)==2 and sha(bench)==sha(p['bench'])
r=dict(p);r.update(status='PREPARED_PRIVATE_SHARED_DATA_JOINED_WORKLOAD_FAULT_MODEL',inputs=inputs,files=files,hdl_sources=sources,hdl_count=112,bench=str(bench),headers=headers,arithmetic_source_deltas=deltas,testbench_unchanged=True,execution_qualified=False,hardware_accessed=False)
(OUT/'preparation.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(dict(status=r['status'],source_count=len(sources),bench_sha256=sha(bench),parent_bench_sha256=sha(p['bench']),file_count=len(files)),indent=2))
