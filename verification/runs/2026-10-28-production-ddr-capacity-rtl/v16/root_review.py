"""Root independently reconciles V16 sources, native and complete host receipts."""
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

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def check(ok,message):
    if not ok:raise RuntimeError(message)
def manifest(files):
    text=''.join(f'{value}  {name}\n' for name,value in sorted(files.items()))
    return hashlib.sha256(text.encode()).hexdigest()

producer=OUT/'report.json'
report=json.loads(producer.read_text())
check(report['status']=='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_V16_ONLY','Incomplete V16')
check(report['source_revision_manifest']==report['source_after']==source_revision(),'Core source drift')
check(report['private_copy_file_count']==len(report['source_inputs'])==1105,'Incomplete source count')
check(report['source_inputs']==report['copied_inputs'],'Unequal source/copy manifests')
for name,digest in report['source_inputs'].items():
    check(sha(ROOT/name)==sha(WORK/name)==digest,'Changed original/copy '+name)
check(report['full_recursive_source_manifest']==report['full_recursive_source_after'],'Recursive source drift')
check(manifest(report['source_inputs'])==report['private_copy_manifest_sha256']==
      report['full_recursive_source_manifest']['sha256'],'Recursive digest mismatch')
old=json.loads((OUT.parent/'current-v15/report.json').read_text())
added=sorted(report['source_inputs'].keys()-old['source_inputs'].keys())
removed=sorted(old['source_inputs'].keys()-report['source_inputs'].keys())
changed=sorted(name for name in report['source_inputs'].keys()&old['source_inputs'].keys()
               if report['source_inputs'][name]!=old['source_inputs'][name])
check(added==['rtl/ddr/rk_ddr_capacity_axi.sv','rtl/ddr/rk_ddr_capacity_bist.sv',
    'rtl/ddr/rk_ddr_capacity_pattern.sv','rtl/ddr/rk_ddr_capacity_sweep.sv',
    'tests/ddr/capacity/tb_capacity_axi.sv','tests/ddr/capacity/tb_capacity_bist_joined.sv',
    'tools/ddr/run_capacity.py'] and not removed and changed==['Makefile'],'Unexpected V15-to-V16 delta')
check([c['argv'] for c in report['commands']]==[['make','generated-check'],['make','test']],
      'Wrong command inventory')
for command in report['commands']:
    check(command['status']=='PASS' and command['returncode']==0 and
          command['seconds']<command['timeout_seconds'],'Failed/late Make command')
    for stream in ('stdout','stderr'):
        check(sha(command[stream+'_log'])==command[stream+'_sha256'],'Changed Make '+stream)
native={}
for name,status,count in [('numeric_report.json','PASS',0),('rtl/report.json','PASS',249),
    ('iverilog/report.json','PASS',249),('cmac_verilator/report.json','PASS_RAW_PRODUCT_PATH_ONLY',3),
    ('cmac_iverilog/report.json','PASS_RAW_PRODUCT_PATH_ONLY',3)]:
    path=WORK/'build'/name;data=json.loads(path.read_text())
    check(data['status']==status and data['source_revision']['sha256']==report['source_after']['sha256'],
          'Wrong source/native status '+name)
    check(len(data.get('tests',[]))==count,'Wrong native inventory '+name)
    if count:
        check(all(row['status']=='PASS' for row in data['tests']) and
              all(row['status']=='PASS' and row['returncode']==0 for row in data['commands']),
              'Failed native case '+name)
    else:check(data['cases']==1087299 and data['seed']=='0x3588','Changed numeric corpus')
    native[name]={'sha256':sha(path),'status':status,'cases':count}
host=[]
for path in sorted((WORK/'build/host-jtag').glob('*/report.json')):
    data=verify_report(path,source_root=WORK,artifact_root=WORK)
    check(len(data['tests'])==15 and all(row['status']=='PASS' for row in data['tests']),
          'Incomplete complete-host receipt')
    asynchronous=[row for row in data['commands'] if row.get('name')=='async_sub_9']
    check(len(asynchronous)==1 and asynchronous[0]['status']=='PASS' and
          asynchronous[0]['returncode']==0 and asynchronous[0]['seconds']<600,
          'Failed async host case/original deadline')
    host.append({'path':str(path),'sha256':sha(path),'simulator':data['simulator'],
                 'tests':15,'tool_version':data['tool_version'],'seeds':data['seeds']})
check(len(host)==2 and {row['simulator'] for row in host}=={'iverilog','verilator'},'Both hosts required')
dual=list((WORK/'build/ddr-dual-controls').glob('*/report.json'))
check(len(dual)==1,'Missing dual control receipt')
data=json.loads(dual[0].read_text())
check(data['status']=='PASS_DUAL_CONTROL_BENCHES_ONLY' and len(data['commands'])==6 and
      data['numerical_qualified'] is False,'Incorrect dual control scope')
for row in data['commands']:
    check(row['status']=='PASS' and row['returncode']==0,'Failed dual command')
    check(sha(dual[0].parent/(row['name']+'.stdout.log'))==row['stdout_sha256'],'Changed dual log')
capacity=[]
for path in sorted((WORK/'build/ddr-capacity').glob('*/report.json')):
    data=json.loads(path.read_text())
    check(data['status']=='PASS_BOUNDED_CAPACITY_MODEL_SIMULATION_ONLY','Failed capacity suite')
    check(data['source_hashes_before']==data['source_hashes_after'],'Capacity source drift')
    for name,digest in data['source_hashes_before'].items():
        check(sha(WORK/name)==digest==report['source_inputs'][name],'Capacity input not V16 bound')
    check(sha(data['golden_fixture']['path'])==data['golden_fixture']['sha256'] and
          data['golden_fixture']['rows']==18,'Changed software golden fixture')
    commands={row['name']:row for row in data['commands']}
    for row in commands.values():
        check(row['returncode']==0,'Failed capacity command')
        for stream in ('stdout','stderr'):
            check(sha(row[stream+'_path'])==row[stream+'_sha256'],'Changed capacity native log')
    for label,base,span,joined,faults in [('small256',0,256,False,True),('small512',0,512,False,False),
        ('offset256',0x1000,256,False,True),('last512',0x7ffffe00,512,False,False),
        ('joined256',0,256,True,False),('joined_offset256',0x1000,256,True,False)]:
        lines=Path(commands[label+'_run']['stdout_path']).read_text().splitlines()
        n=2*(span//64)
        marker=(f'PASS_JOINED_BIST span={span} base={base:08x} writes={n} reads={n} fences=4 snapshots=4'
                if joined else f'PASS_AXI_INTEGRATED span={span} base={base:08x} writes={n} reads={n+4} fences=4')
        check(lines.count(marker)==1,'Wrong capacity completion '+label)
        check(lines.count('PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py')==1,
              'Software golden check missing')
        if faults:
            check(lines.count('PASS_AXI_FAULT_DIRECTED')==1 and lines.count('PASS_AXI_PREMATURE_RESPONSES')==1,
                  'Incomplete directed capacity faults')
        if data['simulator']=='verilator':
            row=commands[label+'_compile']
            check(Path(row['stderr_path']).read_bytes()==b'' and '--Wall' in row['argv'] and
                  not any(arg.startswith('-Wno') for arg in row['argv']),'Weakened strict Verilator compile')
    check(data['hardware_accessed'] is False and data['physical_capacity_qualified'] is False,
          'Wrong capacity qualification scope')
    capacity.append({'path':str(path),'sha256':sha(path),'simulator':data['simulator'],'cases':6})
check(len(capacity)==2 and {row['simulator'] for row in capacity}=={'iverilog','verilator'},'Both capacity simulators required')
test=report['commands'][1]
text=Path(test['stdout_log']).read_text()+Path(test['stderr_log']).read_text()
summaries=[int(n) for n in re.findall(r'^Ran (\d+) tests? in ',Path(test['stderr_log']).read_text(),re.M)]
check(sum(summaries[-10:-1])==89 and summaries[-2:]==[17,7],'Wrong DDR/capacity software inventories')
for count in (73,53,61,11,10,8,7,14,6):check(f'Ran {count} tests' in text,'Missing unit corpus')
check('tests/ddr/capacity' in text and 'tools/ddr/run_capacity.py --simulator iverilog' in text and
      'tools/ddr/run_capacity.py --simulator verilator' in text,'Capacity not in default Make')
check(all(report['cgroup'][key]==value for key,value in {'memory.max':'6442450944',
    'memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}.items()),'Wrong kernel resource limits')
check(not report['hardware_accessed'] and not report['vivado_executed'] and not report['flash_written'],
      'Unexpected hardware scope')
result={'status':'PASS_ROOT_V16_SOURCE_NATIVE_AND_COMPLETE_HOST_RECEIPT_REVIEW_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'producer_sha256':sha(producer),'complete_source_files':1105,
    'recursive_source_sha256':report['private_copy_manifest_sha256'],'source_sha256':report['source_after']['sha256'],
    'v15_to_v16_added':added,'v15_to_v16_changed':changed,'make_test_seconds':test['seconds'],
    'native_reports':native,'complete_host_receipts':host,'capacity_receipts':capacity,
    'ddr_software_controls':89,'capacity_software_controls':7,'capacity_native_cases':12,
    'tinystories_software_controls':61,'dual_control_commands':6,'hardware_accessed':False,
    'physical_capacity_qualified':False}
with (OUT/'root-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('native_reports','complete_host_receipts','capacity_receipts')},sort_keys=True))
