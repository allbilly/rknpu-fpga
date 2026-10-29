"""Independent source/native/resource review of the completed private OOC run."""
from pathlib import Path
import datetime
import hashlib
import json
import re

BASE=Path(__file__).resolve().parent
def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
report_path=BASE/'report.json';report=json.loads(report_path.read_text())
assert report['status']=='PASS_TEN_SOURCE_OOC_SYNTH_RESOURCE_ONLY'
assert report['vivado_executed'] is True and report['hardware_accessed'] is False
assert report['all_owned_groups_stopped'] and not any(report['owned_groups_after_cleanup'].values())
assert report['all_inputs_unchanged'] and report['input_hashes_before']==report['input_hashes_after']
for path,digest in report['input_hashes_before'].items():assert sha(path)==digest,path
assert report['kernel_limits']=={'memory.max':'8589934592','memory.swap.max':'0','cpu.max':'200000 100000','pids.max':'256'}
assert [row['name'] for row in report['commands']]==['version','synthesis']
for row in report['commands']:
    assert row['status']=='PASS' and row['returncode']==0 and not row['live_pids_after_cleanup']
    assert not (Path('/proc')/str(row['pid'])).exists()
    for stream in ('stdout','stderr'):assert sha(row[stream+'_path'])==row[stream+'_sha256']
assert report['commands'][0]['timeout_seconds']==30 and report['commands'][1]['timeout_seconds']==600
assert 'vivado v2026.1' in report['actual_tool_version'] and '6511674' in report['actual_tool_version']
for path,digest in report['outputs'].items():assert sha(path)==digest
text=(BASE/'output/utilization.rpt').read_text()
def count(label):
    match=re.search(r'^\|\s*'+re.escape(label)+r'\s*\|\s*(\d+)\s*\|',text,re.M)
    assert match,label
    return int(match.group(1))
values={key:count(label) for key,label in [('lut','Slice LUTs*'),('ff','Slice Registers'),
    ('latches','Register as Latch'),('bram','Block RAM Tile'),('dsp','DSPs')]}
assert values=={'lut':1821,'ff':2094,'latches':0,'bram':0,'dsp':0}
assert 'Design State : Synthesized' in text and 'xc7k480tffg1156-2' in text
assert not list(BASE.rglob('*.bit'))
result={'status':'PASS_ROOT_TEN_SOURCE_VIVADO_OOC_RESOURCE_ONLY',
    'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer_sha256':sha(__file__),
    'report_sha256':sha(report_path),'vivado_version':'2026.1 build6511674',
    'source_count':10,'resources':values,'synthesis_seconds':report['commands'][1]['seconds'],
    'all_inputs_rehashed':len(report['input_hashes_before']),'owned_process_groups_closed':True,
    'clock_constraints_applied':False,'full_parent_fit_timing_or_physical_qualified':False,
    'hardware_accessed':False,'bitstream_emitted':False}
with (BASE/'root-result-review.json').open('x') as stream:
    json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps(result,sort_keys=True))
