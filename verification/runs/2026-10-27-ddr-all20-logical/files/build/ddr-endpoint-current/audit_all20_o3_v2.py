"""Read-only twenty-case union; original failed positive shard remains failed."""
from pathlib import Path
import datetime,hashlib,json,sys
ROOT=Path('/home/fedora/rknpu-fpga');OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from tools.ddr import endpoint_contract as contract
from tools.ddr.run_endpoint import verify_run,verify_build,runtime_inputs,check_inputs,LOCAL,run_plan,runtime_timeout
from tools.ddr.mig_logic_sources import verify_inputs
from tools.ddr.interface import require,load_json
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
record=dict(status='FAIL',hardware_accessed=False,physical_ddr_verified=False,
    original_positive_shard_remains_failed=True,scope=__doc__)
target=OUT/'independent-all20-o3-union-v2.json'
require(not target.exists(),'Fresh matrix union review required')
try:
    package=OUT/'native-o3-v1';built=verify_build(package)
    verify_inputs(load_json(package/'logic-plan.json'))
    positive_path=OUT/'positives-o3-v1/report.json';positive=load_json(positive_path)
    require(positive['status']=='FAIL' and positive['schema']==contract.SCHEMA and
            positive['scope']==contract.SCOPE,'Wrong preserved positive shard')
    require(all(positive[k] is False for k in ('hardware_accessed','vivado_executed','physical_integration_ready')),
            'Wrong positive-shard physical scope')
    require(Path(positive['build'])==package and positive['build_report_sha256']==sha(package/'report.json'),
            'Mixed native positive build')
    execution={str(ROOT/n):sha(ROOT/n) for n in LOCAL if n.endswith('.py') or n=='tests/backend_ew_captures.json'}
    inputs=runtime_inputs(package,built);inputs.update(execution)
    require(execution==positive['execution_inputs'] and inputs==positive['inputs'],'Changed positive execution inputs')
    check_inputs(inputs)
    directory=positive_path.parent
    artifacts={str(p.relative_to(directory)):sha(p) for p in directory.rglob('*') if p.is_file() and p.name!='report.json'}
    require(artifacts==positive['artifacts'],'Changed preserved shard artifacts')
    specs=contract.selection(built['specs'],positive['selected'])
    require(len(specs)==10 and specs[-1]['name']=='repeat_sub_9' and len(positive['cases'])==9 and
            all(spec['name'].startswith('capture_') for spec in specs[:-1]),'Unexpected failed-prefix scenario selection')
    completed=[]
    for item,spec in zip(positive['cases'],specs[:-1]):
        trial=directory/spec['name'];data=contract.metrics(spec,package/'vectors')
        command=load_json(trial/'run.json')
        require(command==item['command'] and command['status']=='EXITED' and
                command['argv']==run_plan(package,trial,spec) and
                command['timeout_seconds']==runtime_timeout(spec,data) and command['log_sha256']==sha(trial/'run.log'),
                'Completed positive execution command/log differs')
        checked=contract.check_result((trial/'run.log').read_text(),command['returncode'],spec,data,
            trial/'observed.txt',package/'vectors'/spec['case']/'expected.txt')
        expected=dict(name=spec['name'],status='PASS',spec=spec,metrics=data,command=command,**checked)
        require(item==expected==load_json(trial/'result.json'),'Completed positive actual result differs')
        completed.append(item)
    failed_spec=specs[-1];trial=directory/failed_spec['name'];failed=load_json(trial/'run.json')
    require(failed['status']=='FAIL' and failed['argv']==run_plan(package,trial,failed_spec) and
            failed['timeout_seconds']==1800 and failed['seconds']>=1800 and
            failed.get('returncode') is None and failed['error'].startswith('TimeoutExpired(') and
            failed['log_sha256']==sha(trial/'run.log'),'Preserved repeat timeout differs')
    require(not (trial/'result.json').exists(),'Failed repeat unexpectedly has a successful result')
    faults_path=OUT/'faults-o3-v1/report.json';repeat_path=OUT/'repeat-o3-v2/report.json'
    faults=verify_run(faults_path);repeat=verify_run(repeat_path)
    require(repeat['selected']==['repeat_sub_9'] and len(repeat['cases'])==1,'Wrong repeat-only retry')
    require(all(r['build_report_sha256']==sha(package/'report.json') and r['execution_inputs']==execution
                for r in (faults,repeat)),'Mixed native builds or execution drivers')
    cases=completed+faults['cases']+repeat['cases'];names=[c['name'] for c in cases]
    require(len(names)==len(set(names))==20 and set(names)=={s['name'] for s in built['specs']},
            'Missing/extra/duplicate logical matrix case')
    require(all(sha(ROOT/n)==h for n,h in built['local_source'].items() if n.endswith(('.sv','.svh'))),
            'Current RTL/bench differs from the frozen qualified source')
    record.update(status='PASS_INDEPENDENT_ALL20_LOGICAL_CASES_SAME_BINARY_ACROSS_RUNS_ONLY',
        cases=20,positive_captures=9,successful_jobs=sum(c['successful_jobs'] for c in cases),
        physical_bo_bytes_compared_by_bench=sum(c['metrics']['physical_bytes']*c['successful_jobs'] for c in cases),
        physical_bytes_in_persisted_images=sum(c['readback_physical_bytes'] for c in cases),
        binary_sha256=built['binary_sha256'],build_report_sha256=sha(package/'report.json'),
        frozen_input_count=len(built['inputs']),modeled_window_bytes=1048576,
        default_full2GiB_contents_verified=False,
        source_reports={str(p):sha(p) for p in (positive_path,faults_path,repeat_path)},
        preserved_timeout=dict(case='repeat_sub_9',seconds=failed['seconds'],partial_output_sha256=sha(trial/'observed.txt'),
            partial_output_bytes=(trial/'observed.txt').stat().st_size,accepted=False),
        results=[dict(name=c['name'],jobs=c['successful_jobs'],phy_user_returns=c['phy_user_returns'],
            seconds=c['command']['seconds'],observed_sha256=c['observed_sha256']) for c in cases],
        limitation='Twenty source-identical logical cases from validated executions, not a passing original whole shard; encoded PHY model only, no pads/training/board DDR/PCIe/RK acceptance')
except BaseException as error:record['error']=repr(error);raise
finally:
    record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();record['auditor_sha256']=sha(__file__)
    target.write_text(json.dumps(record,indent=2)+'\n')
print(record['status'])
