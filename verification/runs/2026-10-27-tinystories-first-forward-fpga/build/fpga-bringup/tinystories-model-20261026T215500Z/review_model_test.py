from pathlib import Path
import datetime,hashlib,json,sys
R=Path('/home/fedora/rknpu-fpga');W=Path(__file__).resolve().parent
sys.path.insert(0,str(R))
from tools.tinystories.prepare import verify,require
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
T=R/'build/fpga-bringup/tinystories-dual-20261026T221500Z'
audit=json.loads((T/'independent-physical-audit.json').read_text())
require(audit['status']=='PASS_INDEPENDENT_PHYSICAL_TRAINED_TILE_RAW_SCAN_AND_WHOLE_BO_REPLAY' and audit['positive_raw_jobs']==4 and audit['complete_bytes_checked']==360448,'Trained tile physical audit required before model')
base=json.loads((T/'image-review.json').read_text());bound=dict(base['bound_files'])
for p in (T/'image-review.json',T/'independent-physical-audit.json',T/'physical-tests/report.json',Path(__file__).resolve(),W/'run_sram_tests.py',W/'program-template.tcl.in',W/'audit_model.py'):
 bound[str(p)]=sha(p)
package=R/'build/tinystories-preparation/260k-first-v2';prepared=verify(package)
require(len(prepared['projections'])==36 and len(prepared['tiles'])==116,'Model extent changed')
for p in package.rglob('*'):
 if p.is_file():bound[str(p)]=sha(p)
for name in ('build/tinystories-programs/all-v1/report.json','build/tinystories-full-oracle/v1/report.json','build/tinystories-full-oracle/v1/donor-result.json','build/tinystories-full-oracle/v1/donor-logits.bin','build/tinystories-full-oracle/v1/donor-dense-calls.json','build/tinystories-standalone-worker/bos-one-v1/report.json','build/tinystories-standalone-worker/bos-one-v1/logits.bin'):
 bound[str(R/name)]=sha(R/name)
catalog=R/'build/tinystories-programs/all-v1/report.json'
require(sha(catalog)=='eaf4555a59a4e98770f93f773a39487df3d180c28d59d3b51f9bc589ae3948c1','Sealed catalog changed')
for p,h in bound.items():require(sha(p)==h,'Changed reviewed model test input '+p)
require(sha(base['bitstream']['path'])==base['bitstream']['sha256']==audit['bitstream_sha256'],'Wrong tested image')
record=dict(base,bound_files=bound,catalog_sha256=sha(catalog),reviewed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
 reviewer='Root audited image and actual trained-tile raw-wire/BO evidence, bounded BOS/32-position model test design',
 physical_tile_audit_sha256=sha(T/'independent-physical-audit.json'),physical_acceptance=False,
 scope='Authorized volatile SRAM reconfiguration, one BOS forward across36 learned projections, then32positions only after exact dense/logit comparison; CPU explicit host operators, no dense fallback/layout repair; no DDR/PCIe/flash')
path=W/'image-review.json';require(not path.exists(),'Fresh model review required');path.write_text(json.dumps(record,indent=2)+'\n')
print(record['status'],len(bound),path)
