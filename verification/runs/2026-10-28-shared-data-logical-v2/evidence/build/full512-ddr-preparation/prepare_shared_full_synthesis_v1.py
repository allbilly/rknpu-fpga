"""Freeze the full dual-DDR design with the unqualified shared-data candidate."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path('/home/fedora/rknpu-fpga')
PARENT=ROOT/'build/full512-ddr-preparation/combined-source-v6'
CANDIDATE=ROOT/'build/full512-ddr-preparation/shared-data-candidate-v2'
OUT=ROOT/'build/full512-ddr-preparation/combined-shared-data-source-v1'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise RuntimeError(message)
def literal(value):
    value=str(value);require(not any(c in value for c in '{}\\\r\n'),'Unsafe tool path')
    return '{'+value+'}'


require(not OUT.exists(),'Fresh shared full-source preparation required')
parent=json.loads((PARENT/'preparation.json').read_text())
candidate=json.loads((CANDIDATE/'preparation.json').read_text())
for name,digest in parent['inputs'].items():require(sha(name)==digest,'Changed qualified parent input')
for name,digest in parent['files'].items():require(sha(name)==digest,'Changed frozen parent source')
for name,digest in candidate['files'].items():require(sha(name)==digest,'Changed experimental RTL')
OUT.mkdir()
inputs=dict(parent['inputs'])
for path in (PARENT/'preparation.json',CANDIDATE/'preparation.json',Path(__file__)):
    inputs[str(path)]=sha(path)
inputs.update(candidate['files'])
replaced={'rk_cmac_fp16_array_dsp_prefix_pipe.sv','rk_cmac_fp16_cell_dsp_prefix_pipe.sv'}
sources=[];files={};changes=[]
for entry in parent['hdl_sources']:
    old=Path(entry['path']);path=CANDIDATE/old.name if old.name in replaced else old
    digest=sha(path)
    target=OUT/'source/hdl'/f'{len(sources):03d}'/old.name;target.parent.mkdir(parents=True)
    shutil.copyfile(path,target)
    row=dict(path=str(target),sha256=digest,original_path=str(path),original_sha256=digest)
    sources.append(row);files[str(target)]=digest
    if path!=old:changes.append(dict(name=old.name,parent_path=str(old),parent_sha256=sha(old),candidate_sha256=digest))
path=CANDIDATE/'rk_cmac_fp16_shared_data.sv';target=OUT/'source/hdl'/f'{len(sources):03d}'/path.name
target.parent.mkdir(parents=True);shutil.copyfile(path,target)
sources.append(dict(path=str(target),sha256=sha(target),original_path=str(path),original_sha256=sha(path)))
files[str(target)]=sha(target)
clocks=[]
for original in parent['xdc']:
    original=Path(original);target=OUT/'source'/original.name;shutil.copyfile(original,target)
    files[str(target)]=sha(target);clocks.append(str(target))
text=(PARENT/'synth.tcl').read_text()
old_read=next(line for line in text.splitlines() if line.startswith('read_verilog -sv '))
new_read='read_verilog -sv [list '+' '.join(literal(row['path']) for row in sources)+']'
text=text.replace(old_read,new_read)
for old,new in zip(parent['xdc'],clocks):text=text.replace(literal(old),literal(new))
require('-flatten_hierarchy none' in text and 'PRODUCT_DSPS' in text,'Changed full-census synthesis policy')
script=OUT/'synth.tcl';script.write_text(text);files[str(script)]=sha(script)
report=dict(parent)
report.update(status='PREPARED_UNQUALIFIED_SHARED_DATA_FULL512_DUAL_DDR_RESOURCE_EXPERIMENT',
    inputs=inputs,files=files,hdl_sources=sources,hdl_count=len(sources),xdc=clocks,
    source_changes=changes,added_source='rk_cmac_fp16_shared_data.sv',
    numerical_or_fault_composition_qualified=False,resource_fit_qualified=False,
    timing_or_cdc_qualified=False,hardware_accessed=False,
    experimental_scope='Candidate internal data preparation sharing only; all512 products and bothMIG retained; no image/route approval')
report.pop('module_definitions',None)
report['frontend_sources']=[row['path'] for row in sources if 'mig_7series' not in Path(row['path']).name
                          and Path(row['path']).name not in ('platform.sv','top.sv')]
(OUT/'preparation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(status=report['status'],hdl_count=len(sources),source_changes=changes)))
