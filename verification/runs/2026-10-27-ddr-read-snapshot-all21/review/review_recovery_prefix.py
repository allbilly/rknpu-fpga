"""Audit one completed recovery case; its containing batch remains failed."""
from pathlib import Path
import datetime
import hashlib
import json
import sys

ROOT = Path('/home/fedora/rknpu-fpga/build/ddr-read-snapshot-candidate/v2/workspace')
sys.path.insert(0, str(ROOT))
from tools.ddr import run_read_snapshot_endpoint as driver


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    out = Path(__file__).resolve().parent / 'recovery-prefix.json'
    require(not out.exists(), 'Fresh independent audit required')
    parent_path = ROOT / 'build/snapshot-matrix-A-v3/report.json'
    parent_hash = driver.sha(parent_path)
    parent = driver.load_json(parent_path)
    require(parent['status'] == 'FAIL', 'Historical parent failure must remain visible')
    require(parent['schema'] == driver.contract.SCHEMA and parent['scope'] == driver.contract.SCOPE,
            'Wrong historical schema or scope')
    require(all(parent[k] is False for k in
                ('hardware_accessed', 'vivado_executed', 'physical_integration_ready')),
            'Invalid physical claim')
    package = Path(parent['build'])
    built = driver.verify_build(package)
    require(driver.sha(package / 'report.json') == parent['build_report_sha256'],
            'Native build report changed')
    inputs = driver.runtime_inputs(package, built)
    execution = {str(ROOT / n): driver.sha(ROOT / n) for n in driver.LOCAL
                 if n.endswith('.py') or n == 'tests/backend_ew_captures.json'}
    require(execution == parent['execution_inputs'], 'Historical execution contract changed')
    inputs.update(execution)
    require(inputs == parent['inputs'], 'Historical input inventory changed')
    driver.check_inputs(inputs)
    directory = parent_path.parent
    artifacts = {str(p.relative_to(directory)): driver.sha(p) for p in directory.rglob('*')
                 if p.is_file() and p.name != 'report.json'}
    require(artifacts == parent['artifacts'], 'Historical batch artifacts changed')
    name = 'joint_reset_recovery'
    require(len(parent['cases']) == 1 and parent['cases'][0]['name'] == name,
            'This audit covers only the completed first recovery case')
    item = parent['cases'][0]
    require(item['status'] == 'PASS', 'Recovery case itself did not pass')
    spec, = driver.contract.selection(built['specs'], [name])
    trial = directory / name
    metrics = driver.contract.metrics(spec, package / 'vectors')
    command = driver.load_json(trial / 'run.json')
    require(command == item['command'] and command['status'] == 'EXITED' and
            command['argv'] == driver.run_plan(package, trial, spec) and
            command['timeout_seconds'] == driver.runtime_timeout(spec, metrics) and
            command['log_sha256'] == driver.sha(trial / 'run.log'),
            'Recovery command, deadline or actual log differs')
    checked = driver.contract.check_result((trial / 'run.log').read_text(),
        command['returncode'], spec, metrics, trial / 'observed.txt',
        package / 'vectors' / spec['case'] / 'expected.txt')
    expected = dict(name=name, status='PASS', spec=spec, metrics=metrics,
                    command=command, **checked)
    require(item == expected == driver.load_json(trial / 'result.json'),
            'Recovery result differs from actual complete readback and traffic')
    require(driver.sha(parent_path) == parent_hash and
            driver.load_json(parent_path)['status'] == 'FAIL', 'Parent failure changed')
    record = dict(status='PASS_ONE_RECOVERY_CASE_FROM_PRESERVED_FAILED_BATCH_ONLY',
        parent_status='FAIL', parent_report=str(parent_path), parent_report_sha256=parent_hash,
        accepted_cases=[name], rejected_or_unexecuted_parent_cases=parent['selected'][1:],
        build_report_sha256=driver.sha(package / 'report.json'), binary_sha256=built.get('binary_sha256'),
        inputs=inputs, artifacts=artifacts, result=expected, hardware_accessed=False,
        physical_integration_ready=False,
        scope=__doc__, reviewer_sha256=driver.sha(Path(__file__)),
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    out.write_text(json.dumps(record, indent=2) + '\n')
    print(record['status'])


if __name__ == '__main__':
    main()
