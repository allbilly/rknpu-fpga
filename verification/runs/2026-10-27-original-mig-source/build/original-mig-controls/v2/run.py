from pathlib import Path
import datetime,hashlib,json,sys,tempfile,unittest,subprocess
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent
sys.path.insert(0,str(R))
from tools.ddr import prepare_original_mig as p
source=Path('/home/fedora/ypcb/ref/ypcb_00338_1p1_hack')
sha=lambda f:hashlib.sha256(Path(f).read_bytes()).hexdigest()
record=dict(status='RUNNING',scope='Actual unchanged-source preparation, copied-input tampering and mocked Tcl guards only; no Vivado generation or hardware',hardware_accessed=False,vivado_executed=False,controls=[])
try:
 log=W/'unit.log'
 with log.open('x') as stream:
  rc=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/ddr/original_mig','-v'],cwd=R,stdout=stream,stderr=subprocess.STDOUT,timeout=60).returncode
 assert rc==0
 record['unit_methods']=5;record['unit_log_sha256']=sha(log)
 for name in ('good','xml','script','extra','origin','input_inventory','scope','existing','flag_vivado','flag_controller','flag_clock','flag_ready','flag_hardware','flag_flash'):
  with tempfile.TemporaryDirectory(dir=R/'build',prefix='original-mig-control-') as temp:
   out=Path(temp)/'package';p.prepare(source,out)
   report=out/'report.json';d=json.loads(report.read_text())
   if name=='xml':
    q=out/'source/original/project/mig.prj';q.write_bytes(q.read_bytes().replace(b'RZQ/7',b'RZQ/6',1))
   elif name=='script':(out/'generate.tcl').write_text((out/'generate.tcl').read_text()+'\nsynth_design\n')
   elif name=='extra':(out/'source/extra.v').write_text('unreviewed module')
   elif name=='origin':d['original_sources']['project']['sha256']='0'*64
   elif name=='input_inventory':d['frozen_inputs'].pop(next(iter(d['frozen_inputs'])))
   elif name=='scope':d['scope']='Hardware ready'
   elif name.startswith('flag_'):
    flag={'vivado':'vivado_executed','controller':'generated_controller_present','clock':'board_clock_delivery_verified','ready':'physical_integration_ready','hardware':'hardware_accessed','flash':'flash_written'}[name[5:]];d[flag]=True
   report.write_text(json.dumps(d,indent=2)+'\n')
   failed=False
   try:
    if name=='existing':p.prepare(source,out)
    else:p.verify(out)
   except ValueError:failed=True
   assert failed==(name!='good'),name
   record['controls'].append(dict(name=name,status='PASS',expected_rejection=name!='good'))
 record.update(status='PASS_ORIGINAL_MIG_PREPARATION_AND_MOCK_GENERATION_CONTROLS_ONLY',tool_sources={n:sha(R/n) for n in p.LOCAL},prepared_package='build/original-mig-preparation/rzq7-v2',prepared_report_sha256=sha(R/'build/original-mig-preparation/rzq7-v2/report.json'))
finally:
 record['utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();record['runner_sha256']=sha(__file__);(W/'report.json').write_text(json.dumps(record,indent=2)+'\n')
print(record['status'],len(record['controls']))
