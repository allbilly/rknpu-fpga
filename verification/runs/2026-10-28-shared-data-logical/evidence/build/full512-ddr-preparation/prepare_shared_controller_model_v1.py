"""Replace only the shared-data arithmetic sources in the trained MC test."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path('/home/fedora/rknpu-fpga')
PARENT=ROOT/'build/full512-ddr-preparation/trained-alternation-source-v2'
CANDIDATE=ROOT/'build/full512-ddr-preparation/shared-data-candidate-v2'
OUT=ROOT/'build/full512-ddr-preparation/shared-data-trained-model-v1'
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()

def require(ok,message):
    if not ok:raise RuntimeError(message)


require(not OUT.exists(),'Fresh candidate controller model required')
prep=json.loads((PARENT/'preparation.json').read_text())
candidate=json.loads((CANDIDATE/'preparation.json').read_text())
for name,digest in prep['files'].items():require(sha(name)==digest,'Changed trained bench/vector')
for name,digest in candidate['files'].items():require(sha(name)==digest,'Changed arithmetic candidate')
OUT.mkdir()
inputs=dict(prep['inputs'])|dict(prep['files'])|dict(candidate['files'])
for path in (PARENT/'preparation.json',CANDIDATE/'preparation.json',Path(__file__)):
    inputs[str(path)]=sha(path)
sources=[];files={};deltas=[]
replace={'rk_cmac_fp16_array_dsp_prefix_pipe.sv','rk_cmac_fp16_cell_dsp_prefix_pipe.sv'}
for row in prep['hdl_sources']:
    old=Path(row['path']);source=CANDIDATE/old.name if old.name in replace else old
    require(sha(old)==row['sha256'],'Changed actual model source')
    target=OUT/'source'/f'{len(sources):03d}'/source.name;target.parent.mkdir(parents=True)
    shutil.copyfile(source,target)
    sources.append(dict(path=str(target),sha256=sha(target),original=str(source),original_sha256=sha(source)))
    files[str(target)]=sha(target)
    if source!=old:deltas.append(dict(name=source.name,reference_sha256=sha(old),candidate_sha256=sha(source)))
source=CANDIDATE/'rk_cmac_fp16_shared_data.sv';target=OUT/'source'/f'{len(sources):03d}'/source.name
target.parent.mkdir(parents=True);shutil.copyfile(source,target)
sources.append(dict(path=str(target),sha256=sha(target),original=str(source),original_sha256=sha(source)))
files[str(target)]=sha(target)
bench=OUT/'tb_jtag_dual_ddr_async.sv';shutil.copyfile(Path(prep['bench']),bench);files[str(bench)]=sha(bench)
shutil.copytree(Path(prep['vectors']),OUT/'vectors')
for path in (OUT/'vectors').iterdir():
    if path.is_file():files[str(path)]=sha(path)
headers={}
for macro,name in prep['headers'].items():
    original=Path(name);target=OUT/'headers'/original.name;target.parent.mkdir(exist_ok=True)
    shutil.copyfile(original,target);files[str(target)]=sha(target);headers[macro]=str(target)
require(len(sources)==112 and len(deltas)==2 and sha(bench)==sha(prep['bench']),
        'Unexpected candidate test/source delta')
report=dict(prep)
report.update(status='PREPARED_UNQUALIFIED_SHARED_DATA_TRAINED_CONTROLLER_MODEL',inputs=inputs,files=files,
    hdl_sources=sources,hdl_count=112,bench=str(bench),headers=headers,vectors=str(OUT/'vectors'),
    arithmetic_source_deltas=deltas,added_arithmetic_module='rk_cmac_fp16_shared_data.sv',
    testbench_and_original_trained_vectors_unchanged=True,execution_qualified=False,hardware_accessed=False)
(OUT/'preparation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(status=report['status'],hdl_count=112,source_deltas=deltas,expected=report['expected'])))
