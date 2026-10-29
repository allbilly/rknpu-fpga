"""Independent owner source/native review; no mux or board qualification."""
from pathlib import Path
import datetime
import hashlib
import json

BASE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
path=BASE/'report.json';report=json.loads(path.read_text())
assert report['status']=='PASS_OWNER_OBSERVER_CONTRACT_SIMULATION_ONLY' and report['failure'] is None
assert report['sources_unchanged'] and report['source_hashes_before']==report['source_hashes_after']
for name,digest in report['source_hashes_before'].items():assert sha(name)==digest,name
commands={row['name']:row for row in report['commands']}
assert len(commands)==len(report['commands'])==15
for name,row in commands.items():
    expected=1 if name.endswith('_reject') or name=='quiet_below_min_verilator_compile' else 0
    assert row['returncode']==expected and not row['timed_out'] and row['timeout_seconds']==300,name
    for stream in ('stdout','stderr'):assert sha(row[stream+'_path'])==row[stream+'_sha256']
markers=['PASS_OWNER_QUIET_DRAIN_HELD_START_STICKY_DONE','PASS_OWNER_BOUNDED_PRE_RUN_TIMEOUTS',
    'PASS_OWNER_HEALTH_AND_LOGICAL_QUIET_FAULTS','PASS_OWNER_DIAGNOSTIC_FAULT_PRIORITY',
    'PASS_OWNER_SAME_CYCLE_REISSUE_REJECT','PASS_OWNER_PROTOCOL_FAULTS_AND_LATE_DRAIN',
    'PASS_OWNER_LEAF_CASES=PASS']
for tool in ('icarus','verilator'):
    row=commands[tool+'_behavior_compile']
    assert any('TIMEOUT_CYCLES=32' in arg for arg in row['argv'])
    if tool=='verilator':
        assert Path(row['stderr_path']).read_bytes()==b'' and '--Wall' in row['argv']
        assert not any(arg.startswith('-Wno') for arg in row['argv'])
    lines=Path(commands[tool+'_behavior_sim']['stdout_path']).read_text().splitlines()
    for marker in markers:assert lines.count(marker)==1,(tool,marker)
    unknown='PASS_OWNER_UNKNOWN_INPUTS_FOUR_STATE' if tool=='icarus' else 'PASS_OWNER_UNKNOWN_INPUTS=NOT_APPLICABLE_TWO_STATE'
    assert lines.count(unknown)==1
fatal='Capacity owner requires at least two quiet cycles and a longer positive timeout'
for case in ('quiet_below_min','timeout_equal_quiet','timeout_shorter_than_quiet'):
    assert fatal in Path(commands[case+'_icarus_reject']['stdout_path']).read_text()
    if case=='quiet_below_min':
        diagnostic=Path(commands[case+'_verilator_compile']['stderr_path']).read_text()
        assert '%Warning-UNSIGNED' in diagnostic and 'quiet_count >= QUIET_CYCLES-1' in diagnostic
        assert case+'_verilator_reject' not in commands
    else:assert fatal in Path(commands[case+'_verilator_reject']['stdout_path']).read_text()
facts_path=BASE/'independent-facts.json';facts=json.loads(facts_path.read_text())
assert facts['producer_report_sha256']==sha(path)
assert facts['testbench_behavior_timeout_cycles']==32 and facts['RTL_default_timeout_cycles']==65536
assert sha(BASE.parents[1]/facts['prior_attempt_history_path'])==facts['prior_attempt_history_sha256']
for entry in facts['prior_attempt_timeline']:
    if 'path' in entry and 'sha256' in entry:assert sha(entry['path'])==entry['sha256']
bench=(BASE/'tb_capacity_owner.sv').read_text()
assert 'repeat(TIMEOUT_CYCLES*3)' in bench
assert 'normal_pending_response' in bench and 'bus_rready=2\'b00' in bench
assert report['hardware_executed'] is False and report['physical_capacity_qualified'] is False
result={'status':'PASS_ROOT_OWNER_SOURCE_AND_LEGAL_HANDSHAKE_NATIVE_REVIEW_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'report_sha256':sha(path),'facts_sha256':sha(facts_path),'source_files_rehashed':4,
    'native_commands_reconciled':15,'valid_profile_simulators':['Icarus13','strictVerilator5.048'],
    'invalid_quiet_verilator_rejection':'compile-time fatal warning, not runtime fatal',
    'legal_backpressure_stimulus_reviewed':True,'run_longer_than_bench_timeout_checked':True,
    'rtl_default_timeout_cycles':65536,'physical_capacity_qualified':False,
    'mux_csr_or_board_integration_qualified':False,'hardware_accessed':False}
with (BASE/'root-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
