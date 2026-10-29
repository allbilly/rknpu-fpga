#!/usr/bin/env python3
"""Independent source/log reconciliation; no simulator or hardware execution."""
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

report_path = ROOT / 'report.json'
report = json.loads(report_path.read_text())
assert report['status'] == 'PASS_CONTROLLER_ADAPTER_CONTRACT_SIMULATION_ONLY'
assert report['failure'] is None and report['sources_unchanged']
assert report['source_hashes_before'] == report['source_hashes_after']
for path, expected in report['source_hashes_before'].items():
    assert sha(path) == expected, path
commands = {row['name']: row for row in report['commands']}
assert len(commands) == len(report['commands']) == 20
for name, command in commands.items():
    assert not command['timed_out'] and command['timeout_seconds'] == 300
    for stream in ('stdout', 'stderr'):
        assert sha(command[stream + '_path']) == command[stream + '_sha256'], name
    assert command['returncode'] == (1 if name.endswith('_reject') else 0), name
markers = [
    'PASS_SWEEP_SEED_ZERO writes=8 reads=8',
    'PASS_SWEEP_NORMAL writes=8 reads=8 fences=4',
    'PASS_SWEEP_ALIAS_MISMATCH address=00000000',
    'PASS_SWEEP_MODIFIED_READ address=00000000',
    'PASS_SWEEP_LINE_ERROR', 'PASS_SWEEP_UNSOLICITED_LINE_RESPONSE',
    'PASS_SWEEP_UNSOLICITED_RETIRE_RESPONSE', 'PASS_SWEEP_RETIREMENT_ECC_FIELDS',
    'PASS_SWEEP_HEALTH_INTERLOCKS', 'PASS_SWEEP_FINAL_HEALTH_DOMINATES_DONE',
    'PASS_SWEEP_DROPPED_RESPONSE_TIMEOUT', 'PASS_SWEEP_STALLED_REQUEST_TIMEOUT',
    'PASS_SWEEP_JOINT_RESET_NEW_RUN', 'PASS_SWEEP_CONTROLLER behavioral_cases=PASS',
]
for tool in ('icarus', 'verilator'):
    output = Path(commands[tool + '_behavior_sim']['stdout_path']).read_text()
    for marker in markers:
        assert output.splitlines().count(marker) == 1, (tool, marker)
    four_state = 'PASS_SWEEP_UNKNOWN_SEED_FOUR_STATE'
    if tool == 'verilator':
        four_state += '=NOT_APPLICABLE_TWO_STATE'
        assert Path(commands['verilator_behavior_compile']['stderr_path']).read_text() == ''
        assert Path(commands['verilator_full_window_elab_compile']['stderr_path']).read_text() == ''
    assert output.splitlines().count(four_state) == 1
    boundary = Path(commands[tool + '_full_window_elab_sim']['stdout_path']).read_text()
    assert boundary.splitlines().count(
        'PASS_SWEEP_FULL_WINDOW_ELAB_ONLY last=7fffffc0 no_span_iteration=1') == 1
assert len(report['negative_parameter_cases']) == 6
for row in report['negative_parameter_cases']:
    assert row['compile_rc'] == 0 and row['simulation_rc'] == 1 and row['expected_fatal_observed']
    output = Path(commands[row['case'] + '_reject']['stdout_path']).read_text()
    assert 'Capacity sweep needs aligned nonempty31-bit span and positive timeout' in output
facts_path = ROOT / 'independent-facts.json'
facts = json.loads(facts_path.read_text())
assert facts['producer_report_sha256'] == sha(report_path)
assert len(facts['prior_attempts']) == 3
for row in facts['prior_attempts']:
    assert sha(row['path']) == row['sha256']
    assert json.loads(Path(row['path']).read_text())['status'] == 'FAIL'
assert report['span_bytes'] == 256 and report['lines_per_pass'] == 4
assert all(report[key] is False for key in (
    'full_capacity_qualified', 'physical_ddr_qualified', 'hardware_executed', 'model_run_executed'))
result = {
    'status': 'PASS_ROOT_SWEEP_SOURCE_AND_NATIVE_RECEIPT_REVIEW_ONLY',
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'reviewer_sha256': sha(__file__), 'report_sha256': sha(report_path),
    'facts_sha256': sha(facts_path), 'source_files_rehashed': 5,
    'native_commands_reconciled': 20, 'expected_parameter_rejections': 6,
    'source_review': [
        'Both global write/read trials use the captured seed and exact final successful write address',
        'Four retirement/ECC witnesses separate the four passes',
        'Full 512-bit mismatch capture; health failure takes precedence over final done',
        'Pending request payloads survive quarantine; joint reset is the only recovery',
        '32-bit counters hold two full-window passes without overflow',
    ],
    'scope': '256-byte behavioral contract plus default 2 GiB boundary elaboration only',
    'physical_capacity_qualified': False, 'real_mig_integration_qualified': False,
    'hardware_accessed': False,
}
output = ROOT / 'root-review.json'
with output.open('x') as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps(result, sort_keys=True))
