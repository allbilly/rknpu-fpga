#!/usr/bin/env python3
"""Root review of native private/public capacity controls and exact promotion."""
import datetime
import hashlib
import json
from pathlib import Path

ROOT=Path('/home/fedora/rknpu-fpga')
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
private_path=ROOT/'build/ddr-capacity-axi-validation-v16/report.json'
private=json.loads(private_path.read_text())
assert private['status']=='PASS_AXI_ADAPTER_AND_JOINED_BIST_SIMULATION_ONLY'
assert private['failure'] is None and private['sources_unchanged']
assert private['source_hashes_before']==private['source_hashes_after']
assert len(private['commands'])==21
for path,expected in private['source_hashes_before'].items():
    assert sha(path)==expected,path
for command in private['commands']:
    assert command['returncode']==0 and not command['timed_out']
    for stream in ('stdout','stderr'):
        assert sha(command[stream+'_path'])==command[stream+'_sha256']
facts_path=private_path.parent/'independent-facts.json'
facts=json.loads(facts_path.read_text())
assert facts['producer_report_sha256']==sha(private_path)
promotion=json.loads((ROOT/'build/ddr-capacity-public-source-promotion-v1.json').read_text())
for row in promotion['files']:
    assert sha(row['private_source'])==row['sha256']==sha(row['public_source'])
for name in ('tb_capacity_axi.sv','tb_capacity_bist_joined.sv'):
    assert sha(private_path.parent/name)==sha(ROOT/'tests/ddr/capacity'/name)
public=[]
for simulator in ('iverilog','verilator'):
    candidates=[]
    for candidate in (ROOT/'build/ddr-capacity').glob(simulator+'-*/report.json'):
        data=json.loads(candidate.read_text())
        if data['status']=='PASS_BOUNDED_CAPACITY_MODEL_SIMULATION_ONLY' and all(
            sha(ROOT/name)==expected for name,expected in data['source_hashes_before'].items()):
            candidates.append(candidate)
    assert candidates, 'No completed passing '+simulator+' run for current exact sources'
    path=max(candidates,key=lambda p:p.parent.name)
    report=json.loads(path.read_text())
    assert report['status']=='PASS_BOUNDED_CAPACITY_MODEL_SIMULATION_ONLY'
    assert report['source_hashes_before']==report['source_hashes_after']
    for name,expected in report['source_hashes_before'].items():
        assert sha(ROOT/name)==expected,name
    assert sha(report['golden_fixture']['path'])==report['golden_fixture']['sha256']
    assert report['golden_fixture']['sha256']==private['source_hashes_before'][str(private_path.parent/'nonzero-public-goldens.txt')]
    runs=[command for command in report['commands'] if command['name'].endswith('_run')]
    assert len(runs)==6
    for command in report['commands']:
        assert command['returncode']==0
        for stream in ('stdout','stderr'):
            assert sha(command[stream+'_path'])==command[stream+'_sha256']
        if simulator=='verilator' and command['name'].endswith('_compile'):
            assert Path(command['stderr_path']).read_text()==''
            assert '--Wall' in command['argv']
            assert not any(arg.startswith('-Wno') for arg in command['argv'])
    public.append({'simulator':simulator,'report_path':str(path),'report_sha256':sha(path),
        'cases':6,'complete_native_commands':len(report['commands'])})
result={
    'status':'PASS_ROOT_PUBLIC_CAPACITY_SOURCE_AND_BOUNDED_NATIVE_CONTROLS_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'private_adapter_v16_report_sha256':sha(private_path),'private_adapter_v16_native_commands':21,
    'private_facts_sha256':sha(facts_path),'public_native_runs':public,
    'exact_promoted_rtl_sources':4,'exact_promoted_benches':2,
    'earlier_v15_postrun_mutation_forensic_sha256':sha(ROOT/'build/ddr-capacity-axi-validation-v15/postrun-mutation-forensic-v1.json'),
    'earlier_v15_source_bytes_preserved_at':'build/ddr-capacity-public-prior-candidate-v1/tb_capacity_axi.sv',
    'scope':'Bounded AXI/control models and software pattern goldens; no real MIG/PHY/full capacity',
    'physical_capacity_qualified':False,'hardware_accessed':False,
}
with (ROOT/'build/ddr-capacity-public-root-review-v1.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
