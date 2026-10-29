"""Root checks private diagnostic bank sources and native protocol receipts."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
report_path=BASE/'report.json';report=json.loads(report_path.read_text())
audit_path=BASE/'final-audit.json';audit=json.loads(audit_path.read_text())
assert report['status']=='PASS_PRIVATE_AXI_LITE_REGISTER_CONTRACT_SIMULATION'
assert report['sources_unchanged'] and audit['runner_sources_unchanged']
assert audit['runner_report_sha256']==sha(report_path)
manifest_path=BASE/'frozen-inputs.json';manifest=json.loads(manifest_path.read_text())
assert sha(manifest_path)==audit['frozen_manifest_sha256']==report['frozen_inputs_sha256']
assert manifest['inputs']==audit['frozen_inputs']==audit['postrun_input_sha256']
for name,digest in manifest['inputs'].items():assert sha(BASE/name)==digest,name
assert sha(audit['original_private_rtl_path'])==audit['original_private_rtl_sha256']==manifest['inputs']['source/rk_ddr_capacity_regs.sv']
commands={row['name']:row for row in report['commands']}
assert len(commands)==len(report['commands'])==15
for name,row in commands.items():
    expected=1 if name in ('iverilog_bad_base','iverilog_bad_span','verilator_bad_base','verilator_bad_span') else 0
    assert row['returncode']==expected,name
    for stream in ('stdout','stderr'):assert sha(row[stream+'_path'])==row[stream+'_sha256']
    if name.startswith('verilator_compile'):
        assert '--Wall' in row['argv'] and not any(arg.startswith('-Wno') for arg in row['argv'])
        assert Path(row['stderr_path']).read_bytes()==b''
for simulator,count in (('iverilog',488),('verilator',433)):
    output=Path(commands[simulator+'_main']['stdout_path']).read_text().splitlines()
    assert output.count(f'PASS capacity_regs checks={count}')==1
    for case in ('base','span'):
        row=commands[simulator+'_bad_'+case]
        text=Path(row['stdout_path']).read_text()+Path(row['stderr_path']).read_text()
        assert 'Capacity CSR metadata needs aligned nonempty31-bit span' in text
bench=(BASE/'source/tb_capacity_regs.sv').read_text()
assert "if (ok !== 1'b1)" in bench or "if (ok!==1'b1)" in bench
assert "rd(32'h20c" in bench and 'for(i=0;i<16;i=i+1)' in bench
assert report['hardware_executed'] is False and report['physical_capacity_qualified'] is False
result={'status':'PASS_ROOT_PRIVATE_CAPACITY_REGS_SOURCE_AND_NATIVE_PROTOCOL_REVIEW_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'report_sha256':sha(report_path),'audit_sha256':sha(audit_path),'source_files_rehashed':4,
    'native_commands_reconciled':15,'icarus_checks':488,'strict_verilator_checks':433,
    'four_state_checks_scope':'Icarus only; omitted under Verilator',
    'whole_parent_or_transport_integration_qualified':False,'physical_capacity_qualified':False,
    'hardware_accessed':False}
with (BASE/'root-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
