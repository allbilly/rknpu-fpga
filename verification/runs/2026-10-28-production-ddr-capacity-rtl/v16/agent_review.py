#!/usr/bin/env python3
"""Independent, read-only hash and receipt review for the V16 private run."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path('/home/fedora/rknpu-fpga')
OUT=ROOT/'build/production-model-auditors/current-v16'
WORK=OUT/'workspace'
V15=ROOT/'build/production-model-auditors/current-v15'
sys.path.insert(0,str(ROOT))
from tools.evidence import source_revision
from tools.host.qualification import verify_report

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def need(ok,message):
    if not ok:raise RuntimeError(message)

def source_files(root):
    result=[]
    for folder in ('rtl','fpga','model','tools','tests'):
        for p in (root/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':result.append(p)
    result.append(root/'Makefile')
    return sorted(set(result),key=lambda p:str(p.relative_to(root)))

def manifest(root,paths):
    files={str(p.relative_to(root)):sha(p) for p in paths}
    text=''.join(f'{value}  {name}\n' for name,value in sorted(files.items()))
    return {'sha256':hashlib.sha256(text.encode()).hexdigest(),'files':files,'count':len(files)}

def verify_artifact_map(report,root,where):
    files=report.get('artifacts',{}).get('files',{})
    need(isinstance(files,dict) and files,where+' artifact file map missing')
    for name,digest in files.items():
        p=root/name
        need(p.is_file() and sha(p)==digest,where+' artifact hash mismatch: '+name)
    return len(files)

def verify_native_rtl(relative,status,simulator,count):
    p=WORK/relative;d=json.loads(p.read_text())
    need(d['status']==status and d['simulator']==simulator,relative+' status/simulator mismatch')
    need(len(d['tests'])==count and all(t.get('status')=='PASS' for t in d['tests']),relative+' test census mismatch')
    need(d['source_revision']['sha256']==R['source_revision_manifest']['sha256'],relative+' source revision mismatch')
    artifacts=verify_artifact_map(d,WORK,relative)
    for cmd in d['commands']:
        log=WORK/cmd['log'];expected_log=cmd.get('log_sha256',d['artifacts']['files'].get(cmd['log']))
        label=cmd.get('name',Path(cmd['log']).stem)
        need(expected_log is not None and log.is_file() and sha(log)==expected_log,relative+' command log mismatch '+label)
        need(cmd.get('returncode')==0 and cmd.get('status')=='PASS',relative+' command failed '+label)
    return {'report':relative,'sha256':sha(p),'status':d['status'],'simulator':simulator,'tests':count,
            'seed_map':d.get('seeds'),'verified_artifact_files':artifacts,'tool_version':d.get('tool_version')}

def main():
    global R
    report_path=OUT/'report.json';R=json.loads(report_path.read_text())
    need(R['status']=='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_V16_ONLY','V16 runner not terminal PASS')
    need(R['hardware_accessed'] is False and R['vivado_executed'] is False and R['bitstream_emitted'] is False,'V16 claimed hardware/Vivado')
    need(len(R['commands'])==2 and [c['argv'] for c in R['commands']]==[['make','generated-check'],['make','test']],
         'V16 did not run generated-check then serial make test only')
    need(all(c['status']=='PASS' and c['returncode']==0 for c in R['commands']),'V16 command return status mismatch')
    for c in R['commands']:
        for pathkey,hashkey in [('stdout_log','stdout_sha256'),('stderr_log','stderr_sha256')]:
            p=Path(c[pathkey]);need(p.is_file() and sha(p)==c[hashkey],'V16 command log hash mismatch '+str(p))
    command_summary=[{'name':c['name'],'argv':c['argv'],'returncode':c['returncode'],'seconds':c['seconds'],
                      'stdout_sha256':c['stdout_sha256'],'stderr_sha256':c['stderr_sha256']} for c in R['commands']]
    paths=source_files(ROOT);current=manifest(ROOT,paths)
    need(current==R['full_recursive_source_manifest']==R['full_recursive_source_after'],'V16 live full source manifest changed')
    need(source_revision()==R['source_revision_manifest']==R['source_after'],'V16 source revision changed')
    need(current['count']==R['private_copy_file_count']==1105,'V16 source/copy count mismatch')
    need(R['all_source_inputs_unchanged'] is True and R['all_copied_inputs_unchanged'] is True,'runner rehash gates did not pass')
    need(R['source_inputs']==R['copied_inputs'],'V16 source and copy inventories differ')
    for name,digest in R['source_inputs'].items():
        need(sha(ROOT/name)==digest,'V16 live source changed: '+name)
        need(sha(WORK/name)==digest,'V16 private source changed: '+name)
    need(not (WORK/'.git').exists(),'V16 private workspace contains .git')
    need(not any('__pycache__' in Path(p).parts or Path(p).suffix=='.pyc' for p in R['source_inputs']),'V16 source inventory includes cache')
    v15=json.loads((V15/'report.json').read_text());lineage=json.loads((OUT/'v15-lineage.json').read_text())
    old=v15['full_recursive_source_manifest']['files'];new=current['files']
    delta={'added':sorted(set(new)-set(old)),'removed':sorted(set(old)-set(new)),
           'changed':sorted(n for n in set(old)&set(new) if old[n]!=new[n])}
    need(delta==lineage['delta_from_v15'],'V15-to-V16 source delta mismatch')
    expected_added=['rtl/ddr/rk_ddr_capacity_axi.sv','rtl/ddr/rk_ddr_capacity_bist.sv','rtl/ddr/rk_ddr_capacity_pattern.sv',
      'rtl/ddr/rk_ddr_capacity_sweep.sv','tests/ddr/capacity/tb_capacity_axi.sv','tests/ddr/capacity/tb_capacity_bist_joined.sv','tools/ddr/run_capacity.py']
    need(delta=={'added':expected_added,'removed':[],'changed':['Makefile']},'V16 source delta differs from requested scope')
    need(R['cgroup']['memory.max']=='6442450944' and R['cgroup']['memory.swap.max']=='0' and
         R['cgroup']['cpu.max']=='200000 100000' and R['cgroup']['pids.max']=='256','actual cgroup does not match requested limits')
    need(R['resource_admission']['status']=='RESOURCE_GATE_PASS_FOR_PRODUCTION_V16' and len(R['resource_admission']['samples'])>=3 and
         all(s['pass'] for s in R['resource_admission']['samples'][-3:]) and R['fresh_launch_sample']['pass'],'V16 admission gate not proven')
    # The Make target must own the DDR capacity tests; no second capacity command is allowed.
    make_text=(WORK/'Makefile').read_text();testline=next(x for x in make_text.splitlines() if x.startswith('test:'))
    need('ddr-capacity-controls' in testline,'default Make test lacks DDR capacity controls')
    make_stdout=Path(R['commands'][1]['stdout_log']).read_text(errors='replace')
    need('tools/ddr/run_capacity.py --simulator iverilog' in make_stdout and
         'tools/ddr/run_capacity.py --simulator verilator' in make_stdout,'Make test did not execute both capacity simulators')
    need(not any(c['name']=='capacity_controls' for c in R['commands']),'separate capacity command recorded')
    native=[]
    native.append(verify_native_rtl('build/rtl/report.json','PASS','verilator',249))
    native.append(verify_native_rtl('build/iverilog/report.json','PASS','iverilog',249))
    native.append(verify_native_rtl('build/cmac_verilator/report.json','PASS_RAW_PRODUCT_PATH_ONLY','verilator',3))
    native.append(verify_native_rtl('build/cmac_iverilog/report.json','PASS_RAW_PRODUCT_PATH_ONLY','iverilog',3))
    for entry in native:
        if entry['report'].startswith('build/cmac_'):
            need(entry['seed_map']==['0x3588ca03','0x3588ca04','0x3588ca05'],'CMAC numeric seed inventory mismatch')
        else:
            need(entry['seed_map']=={'vectors':'0x3588','alu_backpressure':'0x12345678','memory_backpressure':'0x35881234',
              'axi_backpressure':'0x3588a512','host_axi_backpressure':'0x3588c510','cmac_address_backpressure':'0x3588ca01'},'RTL numeric seed inventory mismatch')
    # Verify both complete host suites through the repository's canonical verifier.
    hosts=[]
    for p in sorted((WORK/'build/host-jtag').glob('*/report.json')):
        verified=verify_report(p,source_root=WORK,artifact_root=WORK);d=json.loads(p.read_text())
        need(d['status']=='PASS' and len(d['tests'])==15 and all(t['status']=='PASS' for t in d['tests']),
             'host report incomplete '+str(p))
        need(d['seeds']=={'mailbox':'0x3588c640'},'host mailbox seed mismatch '+str(p))
        hosts.append({'report':str(p.relative_to(WORK)),'sha256':sha(p),'verified_by':'tools.host.qualification.verify_report',
          'status':d['status'],'simulator':d['simulator'],'test_count':len(d['tests']),'seed':d['seeds'],'tool_version':d['tool_version']})
    need(len(hosts)==2 and {h['simulator'] for h in hosts}=={'iverilog','verilator'},'both host suites not present')
    # Validate both capacity matrices, their exact six scenario names, source/golden/tool hashes, and native run markers.
    cases=['small256','small512','offset256','last512','joined256','joined_offset256'];capacity=[]
    for p in sorted((WORK/'build/ddr-capacity').glob('*/report.json')):
        d=json.loads(p.read_text());sim=d['simulator'];need(d['status']=='PASS_BOUNDED_CAPACITY_MODEL_SIMULATION_ONLY' and d['hardware_accessed'] is False and d['physical_capacity_qualified'] is False,'capacity scope/status mismatch')
        src=d['source_hashes_before'];need(src==d['source_hashes_after'] and len(src)==10,'capacity source closure mismatch')
        for n,h in src.items():need(sha(WORK/n)==h,'capacity source changed '+n)
        gf=d['golden_fixture'];golden=Path(gf['path']);need(golden.is_file() and sha(golden)==gf['sha256'] and gf['rows']==18,'capacity golden mismatch')
        rows=[line.split() for line in golden.read_text().splitlines()]
        need(len(rows)==18 and {int(x[0],16) for x in rows}=={0x1000,0x1040,0x10c0} and
             {int(x[1],16) for x in rows}=={0,0x3588c350,0xffffffff} and {int(x[2]) for x in rows}=={0,1},'capacity golden seed/address rows mismatch')
        commands=d['commands'];names=[c['name'] for c in commands]
        expected=[sim+'_version']+(['vvp_version'] if sim=='iverilog' else [])+sum(([c+'_compile',c+'_run'] for c in cases),[])
        need(names==expected and all(c['returncode']==0 for c in commands),'capacity command matrix/returncode mismatch '+sim)
        bins=[]
        for name in cases:
            rc=next(c for c in commands if c['name']==name+'_run');log=Path(rc['stdout_path'])
            need(log.is_file() and sha(log)==rc['stdout_sha256'],'capacity run log hash mismatch '+name)
            output=log.read_text();prefix='PASS_JOINED_BIST' if name.startswith('joined') else 'PASS_AXI_INTEGRATED'
            need(sum(line.startswith(prefix) for line in output.splitlines())==1 and
              output.splitlines().count('PASS_PUBLIC_PATTERN_GOLDENS rows=18 base=00001000 software_oracle=tools/ddr/capacity_pattern.py')==1,
              'capacity completion marker mismatch '+sim+':'+name)
            binary=Path(rc['argv'][1] if sim=='iverilog' else rc['argv'][0]);need(binary.is_file(),'capacity run binary missing '+str(binary))
            bins.append({'case':name,'binary':str(binary.relative_to(WORK)),'sha256':sha(binary),'run_log_sha256':sha(log)})
        for c in commands:
            for k,hk in [('stdout_path','stdout_sha256'),('stderr_path','stderr_sha256')]:
                q=Path(c[k]);need(q.is_file() and sha(q)==c[hk],'capacity command stream hash mismatch '+c['name'])
        for tool,v in d['tool_versions'].items():need(sha(v['path'])==v['sha256'],'capacity tool hash mismatch '+tool)
        capacity.append({'report':str(p.relative_to(WORK)),'sha256':sha(p),'status':d['status'],'simulator':sim,'cases':bins,
          'golden_sha256':gf['sha256'],'golden_rows':18,'tool_versions':{k:{'path':v['path'],'sha256':v['sha256'],'version':v['stdout'] or v['stderr']} for k,v in d['tool_versions'].items()}})
    need(len(capacity)==2 and {x['simulator'] for x in capacity}=={'iverilog','verilator'},'both capacity simulator reports absent')
    more=[]
    for rel in ['build/ddr-dual-controls/20261028T071923065586Z/report.json','build/tinystories-registered-memory/20261028T071915Z/report.json']:
        p=WORK/rel;d=json.loads(p.read_text());need(d['status'].startswith('PASS_'),'additional native receipt failed '+rel)
        for path,h in d.get('inputs',{}).items():need(sha(path)==h,'native input changed '+path)
        for c in d.get('commands',[]):
            need(c['returncode']==0 and c.get('status','PASS')=='PASS','native control command failure '+rel)
            if 'stdout_sha256' in c:
                so=WORK/Path(rel).parent/(c['name']+'.stdout.log');se=WORK/Path(rel).parent/(c['name']+'.stderr.log')
                need(so.is_file() and sha(so)==c['stdout_sha256'] and se.is_file() and sha(se)==c['stderr_sha256'],
                     'DDR dual-control stream hash mismatch '+c['name'])
            elif c.get('log_sha256'):
                log=WORK/Path(rel).parent/(c['name']+'.log')
                need(log.is_file() and sha(log)==c['log_sha256'],'registered-memory log hash mismatch '+c['name'])
        more.append({'report':rel,'sha256':sha(p),'status':d['status'],'scope':d['scope'],'command_count':len(d['commands'])})
    capreview=ROOT/'build/ddr-capacity-public-root-review-v1.json';cd=json.loads(capreview.read_text())
    need(cd['status']=='PASS_ROOT_PUBLIC_CAPACITY_SOURCE_AND_BOUNDED_NATIVE_CONTROLS_ONLY' and cd['hardware_accessed'] is False and cd['physical_capacity_qualified'] is False,'public capacity review mismatch')
    review={'schema':'production-v16-agent-independent-review-v1','status':'PASS_INDEPENDENT_V16_SOURCE_NATIVE_AND_COMPLETE_HOST_RECEIPT_REVIEW_ONLY',
      'scope':'Read-only review of V16 source/copy hashes, commands/logs, native inventories, host receipt verifiers, and default capacity controls; no tests or native runs launched by this review.',
      'v16_report_path':str(OUT/'report.json'),'v16_report_sha256':sha(OUT/'report.json'),'v16_status':R['status'],
      'launch_path':str(OUT/'launch.json'),'launch_sha256':sha(OUT/'launch.json'),'launch_status':json.loads((OUT/'launch.json').read_text())['status'],
      'v15_parent':{'report_path':str(V15/'report.json'),'report_sha256':sha(V15/'report.json'),'root_review_path':str(V15/'root-review.json'),
       'root_review_sha256':sha(V15/'root-review.json'),'root_review_status':v15['status']},
      'source_verification':{'source_revision_sha256':current['sha256'],'source_count':current['count'],'copy_count':R['private_copy_file_count'],
       'all_live_and_copy_hashes_verified':True,'v15_delta':delta,'git_absent_from_private_copy':not (WORK/'.git').exists()},
      'commands':command_summary,'host_suites':hosts,'native_inventory':native,'capacity_runs':capacity,'additional_controls':more,
      'public_capacity_review':{'path':str(capreview),'sha256':sha(capreview),'status':cd['status']},
      'defaults_include_capacity_controls':True,'separate_capacity_command_in_runner':False,
      'vivado_executed':False,'hardware_accessed':False,'flash_written':False}
    path=OUT/'agent-review.json';path.write_text(json.dumps(review,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':review['status'],'agent_review_path':str(path),'agent_review_sha256':sha(path),
      'source_count':current['count'],'host_suites':len(hosts),'native_reports':len(native),'capacity_runs':len(capacity),
      'v15_delta':delta},indent=2))

if __name__=='__main__':main()
