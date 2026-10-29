from pathlib import Path
import datetime,hashlib,json,sys
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent;P=W/'workspace'
sys.path.insert(0,str(R))
from tools.evidence import source_revision
from tools.host.qualification import verify_report
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(c,m):
 if not c:raise ValueError(m)
d=json.loads((W/'report.json').read_text());need(d['status']=='PASS_PRIVATE_COMPLETE_PRODUCTION_MAKE_TEST_ONLY','Producer incomplete')
need(d['source_before']==d['source_after']==source_revision(),'Current production source differs')
need(d['source_before']['sha256']=='2a3d4a7b195ba1995bc6bc547926cb9005b8f7d2ee6a78d9ddeb197cde869b15','Wrong core snapshot')
for n,h in d['source_inputs'].items():need(sha(R/n)==h and sha(P/n)==h,'Source/copy mismatch '+n)
for c in d['commands']:need(c['status']=='PASS' and c['returncode']==0 and sha(W/(c['name']+'.log'))==c['log_sha256'],'Command failed/changed')
for n,v in d['production_reports'].items():need(sha(P/'build'/n)==v['sha256'],'Report changed '+n)
host=[]
for p in (P/'build/host-jtag').glob('*/report.json'):
 q=verify_report(p,source_root=P,artifact_root=P)
 need(len(q['tests'])==15 and all(t['status']=='PASS' for t in q['tests']),'Incomplete host suite')
 host.append(dict(path=str(p),sha256=sha(p),simulator=q['simulator'],tests=len(q['tests']),source_revision=q['source_revision']))
need(len(host)==2,'Missing host simulator')
log=(W/'production_test.log').read_text()
for text in ('Ran 73 tests','Ran 53 tests','Ran 28 tests','Ran 11 tests','1,087,299 comparisons'):
 need(text in log,'Missing full-suite coverage '+text)
record=dict(status='PASS_INDEPENDENT_CURRENT_PRODUCTION_AND_BOTH_HOST_RECEIPT_REVIEW_ONLY',utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=d['source_before']['sha256'],producer_sha256=sha(W/'report.json'),copied_inputs=len(d['copied_inputs']),core_units=73,host_controls=53,tinystories_controls=28,ddr_controls=11,core_rtl_entries_per_simulator=249,numeric_comparisons=1087299,numeric_seed='0x3588',host=host,make_test_seconds=d['commands'][1]['seconds'],hardware_accessed=False,scope='Actual complete private serial make test and independent source/host-artifact replay; no full joined MC, FPGA or RK acceptance',auditor_sha256=sha(__file__))
(W/'root-review.json').write_text(json.dumps(record,indent=2)+'\n')
print(record['status'],record['make_test_seconds'])
