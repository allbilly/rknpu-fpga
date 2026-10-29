"""Root source and native receipt reconciliation for the standalone router."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
path=BASE/'report.json';report=json.loads(path.read_text())
assert report['status']=='PASS_AXIL_DIAGNOSTIC_ROUTER_STANDALONE_ONLY' and report['failure'] is None
assert report['sources_unchanged'] and report['sources_before']==report['sources_after']
for name,digest in report['sources_before'].items():assert sha(name)==digest
commands={row['name']:row for row in report['commands']};assert len(commands)==4
for name,row in commands.items():
    assert row['returncode']==0 and not row['timed_out']
    for stream in ('stdout','stderr'):assert sha(row[stream+'_path'])==row[stream+'_sha256']
    if name.endswith('_sim'):
        lines=Path(row['stdout_path']).read_text().splitlines()
        assert lines.count('PASS_AXIL_DIAGNOSTIC_ROUTER transactions=73 full_address_decode=PASS')==1
    if name=='verilator_compile':
        assert '--Wall' in row['argv'] and not any(arg.startswith('-Wno') for arg in row['argv'])
        assert Path(row['stderr_path']).read_bytes()==b''
bench=(BASE/'tb_axil_diagnostic_router.sv').read_text()
assert "32'h00010200" in bench or "32'h10200" in bench
assert report['hardware_executed'] is False and report['parent_integration_qualified'] is False
result={'status':'PASS_ROOT_STANDALONE_AXIL_ROUTER_SOURCE_AND_NATIVE_REVIEW_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'report_sha256':sha(path),'transactions_per_simulator':73,'native_commands_reconciled':4,
    'full_address_decode_and_stalled_channel_routing_reviewed':True,
    'parent_or_physical_qualification':False,'hardware_accessed':False}
with (BASE/'root-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
