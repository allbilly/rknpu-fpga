"""Independent same-ELF union of all 21 optimized logical DDR cases only."""
from pathlib import Path
import datetime
import json
import sys

ROOT = Path('/home/fedora/rknpu-fpga/build/ddr-read-snapshot-candidate/v2/workspace')
sys.path.insert(0, str(ROOT))
from tools.ddr import run_read_snapshot_endpoint as v3
from tools.ddr import run_read_snapshot_execution_v4 as v4


def require(condition, message):
    if not condition:
        raise ValueError(message)


base = Path(__file__).resolve().parent
out = base / 'all21.json'
require(not out.exists(), 'Fresh independent union required')
package = ROOT / 'build/ddr-endpoint-async/native-read-snapshot-v3'
built = v3.verify_build(package)
require(built['binary_sha256'] ==
    'd3fe23dbf517842b391ba440fb8ff8d02b2f536a2ee1d8cefe2a7c6de84b1eb5', 'Changed common ELF')
accepted = {}
evidence = {}
for name, driver in [('repeat-read-snapshot-v3', v3), ('snapshot-matrix-B-v3', v3),
                     ('snapshot-matrix-C-v3', v3), ('snapshot-matrix-A-exec4-v3', v4)]:
    path = ROOT / 'build' / name / 'report.json'
    report = driver.verify_run(path)
    require(Path(report['build']) == package and
            report['build_report_sha256'] == v3.sha(package / 'report.json'),
            'Case batch uses a different build')
    evidence[str(path)] = v3.sha(path)
    for item in report['cases']:
        require(item['name'] not in accepted, 'Duplicate union case')
        accepted[item['name']] = dict(parent_report=str(path),
            execution_contract_version=report.get('execution_contract_version', 3), result=item)

# The original A batch remains FAILED. Audit its completed first recovery
# case through the prior independent receipt, complete log/BO and fixed inputs.
prefix_path = base.parent / 'v1/recovery-prefix.json'
prefix = v3.load_json(prefix_path)
require(prefix['status'] == 'PASS_ONE_RECOVERY_CASE_FROM_PRESERVED_FAILED_BATCH_ONLY' and
        prefix['parent_status'] == 'FAIL' and prefix['accepted_cases'] == ['joint_reset_recovery'],
        'Wrong independently accepted prefix scope')
require(v3.sha(prefix_path.parent / 'review_recovery_prefix.py') == prefix['reviewer_sha256'],
        'Prefix reviewer source changed')
v3.check_inputs(prefix['inputs'])
parent_path = Path(prefix['parent_report'])
require(v3.sha(parent_path) == prefix['parent_report_sha256'] and
        v3.load_json(parent_path)['status'] == 'FAIL', 'Historical failed parent changed')
artifacts = {str(p.relative_to(parent_path.parent)): v3.sha(p)
             for p in parent_path.parent.rglob('*') if p.is_file() and p.name != 'report.json'}
require(artifacts == prefix['artifacts'], 'Historical prefix artifacts changed')
item = prefix['result']
spec, = v3.contract.selection(built['specs'], ['joint_reset_recovery'])
metrics = v3.contract.metrics(spec, package / 'vectors')
trial = parent_path.parent / 'joint_reset_recovery'
command = v3.load_json(trial / 'run.json')
require(command == item['command'] and command['status'] == 'EXITED' and
        command['argv'] == v3.run_plan(package, trial, spec) and
        command['timeout_seconds'] == v3.runtime_timeout(spec, metrics) and
        command['log_sha256'] == v3.sha(trial / 'run.log'), 'Recovery execution differs')
checked = v3.contract.check_result((trial / 'run.log').read_text(), command['returncode'],
    spec, metrics, trial / 'observed.txt', package / 'vectors' / spec['case'] / 'expected.txt')
require(item == dict(name=spec['name'], status='PASS', spec=spec, metrics=metrics,
                     command=command, **checked) == v3.load_json(trial / 'result.json'),
        'Recovery numerical/traffic result differs')
require(spec['name'] not in accepted, 'Duplicate recovery acceptance')
accepted[spec['name']] = dict(parent_report=str(parent_path), parent_status='FAIL',
    independent_prefix_report=str(prefix_path), execution_contract_version=3, result=item)
evidence[str(prefix_path)] = v3.sha(prefix_path)
evidence[str(parent_path)] = v3.sha(parent_path)

names = [spec['name'] for spec in built['specs']]
require(len(names) == 21 and len(set(names)) == 21 and set(accepted) == set(names),
        'Union has missing, extra or duplicate cases')
require(all(v['result']['status'] == 'PASS' for v in accepted.values()), 'Failed accepted case')
record = dict(status='PASS_INDEPENDENT_SAME_ELF_ALL21_READ_SNAPSHOT_LOGICAL_UNION_ONLY',
    scope=__doc__, case_count=21, binary_sha256=built['binary_sha256'],
    build_report=str(package / 'report.json'), build_report_sha256=v3.sha(package / 'report.json'),
    random_seed=built['random_seed'], cases={name: accepted[name] for name in names},
    evidence=evidence, old_matrix_A_status='FAIL', hardware_accessed=False,
    physical_integration_ready=False, fpga_or_rk_equivalence=False,
    reviewers={str(Path(__file__)): v3.sha(Path(__file__)),
               str(Path(v3.__file__)): v3.sha(Path(v3.__file__)),
               str(Path(v4.__file__)): v3.sha(Path(v4.__file__))},
    utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
out.write_text(json.dumps(record, indent=2) + '\n')
print(record['status'])
