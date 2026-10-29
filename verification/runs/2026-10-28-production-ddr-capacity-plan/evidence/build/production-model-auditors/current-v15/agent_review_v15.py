"""Independent v15 source, native reports and complete host receipt audit."""
from pathlib import Path
import datetime
import hashlib
import json
import re
import sys

ROOT=Path('/home/fedora/rknpu-fpga')
OUT=Path(__file__).resolve().parent
WORK=OUT/'workspace'
sys.path.insert(0,str(ROOT))
from tools.evidence import source_revision
from tools.host.qualification import verify_report


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(ok,message):
    if not ok:raise RuntimeError(message)


producer=OUT/'report.json'
report=json.loads(producer.read_text())
require(report['status']=='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_V15_ONLY','Incomplete production v15 run')
require(report['source_revision_manifest']==report['source_after']==source_revision(),'Source manifest drift')
require(report['private_copy_file_count']==1098,'Wrong complete private source count')
require(report['source_inputs']==report['copied_inputs'],'Source and private manifests differ')
for name,digest in report['source_inputs'].items():
    require(sha(ROOT/name)==sha(WORK/name)==digest,'Changed actual source: '+name)
old=json.loads((OUT.parent/'current-v14/report.json').read_text())
added=sorted(set(report['source_inputs'])-set(old['source_inputs']))
removed=sorted(set(old['source_inputs'])-set(report['source_inputs']))
changed=sorted(name for name in set(report['source_inputs'])&set(old['source_inputs'])
               if report['source_inputs'][name]!=old['source_inputs'][name])
require(not removed,'Unexpected source removal')
require(not changed and added==['tests/ddr/capacity/test_pattern.py','tools/ddr/capacity_pattern.py','tools/ddr/prepare_capacity_test.py'],
    'Unexpected existing-source delta')
require(report['source_inputs']['tools/ddr/capacity_pattern.py']=='3131740f6304895e5fb5e38696a10724dcf06d8b1e14ef5549b5481632153a69',
        'Unexpected capacity pattern source hash')
require(report['source_inputs']['tools/ddr/prepare_capacity_test.py']=='cc2b5a36db4897dd9cde172a7c60318c4228c3709acbe40fc17d446908ab2e9e',
        'Unexpected capacity preparation source hash')
require(report['source_inputs']['tests/ddr/capacity/test_pattern.py']=='8b2bf034503c3bca44128fb3097325206f5fecbd27558c2f178acde7d0cf25ca',
        'Unexpected capacity test source hash')
require([c['argv'] for c in report['commands']]==[['make','generated-check'],['make','test'],
        ['python3','-m','unittest','discover','-s','tests/ddr/capacity','-p','test*.py','-v']],
    'Wrong V15 command inventory/order')
for command in report['commands']:
    require(command['status']=='PASS' and command['returncode']==0 and
            command['seconds']<command['timeout_seconds'],'Failed/deadline native command')
    require(sha(command['stdout_log'])==command['stdout_sha256'] and
            sha(command['stderr_log'])==command['stderr_sha256'],'Changed actual command logs')
required={'numeric_report.json':'PASS','rtl/report.json':'PASS','iverilog/report.json':'PASS',
          'cmac_verilator/report.json':'PASS_RAW_PRODUCT_PATH_ONLY',
          'cmac_iverilog/report.json':'PASS_RAW_PRODUCT_PATH_ONLY'}
native={}
for name,status in required.items():
    path=WORK/'build'/name;data=json.loads(path.read_text())
    require(data['status']==status and data['source_revision']['sha256']==report['source_after']['sha256'],
        'Wrong native report/source scope: '+name)
    if name=='numeric_report.json':
        require(data['cases']==1087299 and data['seed']=='0x3588','Changed numeric corpus')
    else:
        require(all(case['status']=='PASS' for case in data['tests']) and
                all(command['status']=='PASS' and command['returncode']==0 for command in data['commands']),
                'Failed native test/command: '+name)
    native[name]=dict(sha256=sha(path),status=status,tests=len(data.get('tests',[])))
host=[]
for path in sorted((WORK/'build/host-jtag').glob('*/report.json')):
    data=verify_report(path,source_root=WORK,artifact_root=WORK)
    require(len(data['tests'])==15 and all(case['status']=='PASS' for case in data['tests']),
            'Incomplete actual host suite')
    async_case=[c for c in data['commands'] if c.get('name')=='async_sub_9']
    require(len(async_case)==1 and async_case[0]['status']=='PASS' and
            async_case[0]['returncode']==0 and async_case[0]['seconds']<600,
            'Missing/failed original-deadline async host case')
    host.append(dict(path=str(path),sha256=sha(path),simulator=data['simulator'],
        tests=len(data['tests']),tool_version=data['tool_version'],seeds=data['seeds'],
        async_seconds=async_case[0]['seconds']))
require(len(host)==2 and {item['simulator'] for item in host}=={'iverilog','verilator'},
    'Both complete host suites required')
dual=list((WORK/'build/ddr-dual-controls').glob('*/report.json'))
require(len(dual)==1,'Missing fresh dual control run')
data=json.loads(dual[0].read_text())
require(data['status']=='PASS_DUAL_CONTROL_BENCHES_ONLY' and len(data['commands'])==6 and
        data['control_models_selected'] is True and data['numerical_qualified'] is False,
        'Wrong dual control scope')
for command in data['commands']:
    require(command['status']=='PASS' and command['returncode']==0,'Failed dual control native command')
    folder=dual[0].parent
    require(sha(folder/(command['name']+'.stdout.log'))==command['stdout_sha256'] and
            not (folder/(command['name']+'.stderr.log')).read_bytes(),'Changed dual control output')
test=report['commands'][1]
capacity=report['commands'][2]
require(capacity['status']=='PASS' and capacity['returncode']==0 and capacity['seconds']<capacity['timeout_seconds'],
        'Supplemental capacity-pattern controls failed/deadline')
capacity_text=Path(capacity['stdout_log']).read_text()+Path(capacity['stderr_log']).read_text()
require('Ran 7 tests' in capacity_text and 'OK' in capacity_text,
        'Supplemental seven-method capacity-control suite missing')
text=Path(test['stdout_log']).read_text()+Path(test['stderr_log']).read_text()
for count in [73,53,61,11,10,8,7,6]:require(f'Ran {count} tests' in text,'Missing actual unit corpus')
require(text.count('Ran 10 tests')>=2 and 'tests/ddr/dual_transport' in text,'Missing new dual-DDR group')
require(text.count('Ran 11 tests')>=2 and 'tests/ddr/trained_audit' in text,'Missing trained audit/default integration corpus')
require('tests/ddr/full512_image' in text and 'Ran 14 tests' in text,'Missing three additional full512 image template controls')
require('tests/ddr/model_audit' in text and 'Ran 17 tests' in text,'Missing repeated-BOS DDR model lifecycle controls')
summaries=[int(count) for count in re.findall(r'^Ran (\d+) tests? in ',Path(test['stderr_log']).read_text(),re.M)]
require(len(summaries)>=9,'Could not locate all DDR software control test group summaries')
ddr_control_count=sum(summaries[-9:])
require(ddr_control_count==89 and summaries[-1]==17,
        'DDR host controls did not execute the expected89 methods including all17 model-audit methods')
require(report['cgroup']['memory.max']=='6442450944' and report['cgroup']['memory.swap.max']=='0' and
        report['cgroup']['cpu.max']=='200000 100000' and report['cgroup']['pids.max']=='256',
        'Wrong actual resource limits')
require(report['hardware_accessed'] is False and report['vivado_executed'] is False and
        report['flash_written'] is False,'Wrong hardware scope')
result=dict(status='PASS_AGENT_V15_SOURCE_NATIVE_AND_COMPLETE_HOST_RECEIPT_REVIEW_ONLY',
    producer_sha256=sha(producer),source_sha256=report['source_after']['sha256'],
    complete_source_files=1098,recursive_source_sha256=report['private_copy_manifest_sha256'],
    v14_to_v15_added=added,v14_to_v15_changed=changed,v6_original_failure_preserved=True,
    make_test_seconds=test['seconds'],native_reports=native,host=host,
    software_ddr_control_methods=ddr_control_count,ddr_model_audit_methods=summaries[-1],
    supplemental_capacity_pattern_methods=7,supplemental_is_physical_capacity_evidence=False,
    dual_control_commands=6,dual_control_report_sha256=sha(dual[0]),
    numerical_or_ddr_composition_qualified_by_default_make=False,hardware_accessed=False,
    reviewer_sha256=sha(__file__),utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
target=OUT/'agent-review.json';require(not target.exists(),'Fresh V15 agent review receipt required')
target.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({key:value for key,value in result.items() if key not in ('native_reports','host','v11_to_v12_added','v11_to_v12_changed')}))
