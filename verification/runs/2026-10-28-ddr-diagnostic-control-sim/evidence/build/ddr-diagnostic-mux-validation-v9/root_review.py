"""Root verifies routing receipts, valid-profile preservation and explicit rejects."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
report_path=BASE/'report.json';report=json.loads(report_path.read_text())
audit_path=BASE/'final-audit.json';audit=json.loads(audit_path.read_text())
assert report['status']=='PASS_PRIVATE_DIAGNOSTIC_MUX_ROUTING_SIMULATION_ONLY' and report['sources_unchanged']
manifest_path=BASE/'frozen-inputs.json';manifest=json.loads(manifest_path.read_text())
assert sha(manifest_path)==report['frozen_inputs_sha256']==audit['frozen_inputs_sha256']
assert manifest['inputs']==audit['frozen_inputs']
for name,digest in manifest['inputs'].items():assert sha(BASE/name)==digest,name
commands={row['name']:row for row in report['commands']};assert len(commands)==31
for name,row in commands.items():
    assert row['returncode']==(1 if name.endswith('_expected_fatal') else 0),name
    for stream in ('stdout','stderr'):assert sha(row[stream+'_path'])==row[stream+'_sha256']
    if name.startswith('verilator') and name.endswith('_compile'):
        assert '--Wall' in row['argv'] and not any(arg.startswith('-Wno') for arg in row['argv'])
        assert Path(row['stderr_path']).read_bytes()==b''
for tool in ('iverilog','verilator'):
    for profile,addr,data,identity in (('memory',31,512,4),('control',32,32,1)):
        lines=Path(commands[f'{tool}_{profile}_sim']['stdout_path']).read_text().splitlines()
        assert lines.count(f'PASS diagnostic_mux checks=25282 addr={addr} data={data} id={identity} seed=3588')==1
    for case in ('bad_addr','bad_id','bad_data_small','bad_data_granularity','bad_data_odd'):
        row=commands[f'{tool}_{case}_expected_fatal']
        text=Path(row['stdout_path']).read_text()+Path(row['stderr_path']).read_text()
        assert 'Diagnostic mux needs positive address/ID widths and byte-granular data' in text
old=ROOT/'build/ddr-capacity-owner-source-v1/rk_ddr_diagnostic_mux.sv'
new=ROOT/'build/ddr-capacity-mux-source-v2/rk_ddr_diagnostic_mux.sv'
derivation=json.loads((new.parent/'derivation.json').read_text())
assert sha(old)==derivation['parent_sha256'] and sha(new)==derivation['derived_sha256']
recovered=new.read_text()
for before,after in derivation['replacements'].items():recovered=recovered.replace(after,before)
recovered=recovered.replace('// Positive fallback port widths allow invalid parameters to reach the explicit\n'
    '// time-zero fatal without a frontend negative-range crash. Valid profiles keep\n'
    '// their exact original widths; no invalid profile is accepted.\n','')
assert recovered==old.read_text()
result={'status':'PASS_ROOT_MUX_VALID_ROUTING_AND_EXPLICIT_PARAMETER_REJECTION_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'report_sha256':sha(report_path),'audit_sha256':sha(audit_path),
    'derived_mux_source_sha256':sha(new),'valid_routing_body_matches_original':True,
    'main_profiles':4,'checks_per_profile':25282,'expected_parameter_fatals':10,
    'native_commands_reconciled':31,'physical_capacity_qualified':False,
    'owner_or_board_integration_qualified':False,'hardware_accessed':False}
with (BASE/'root-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
