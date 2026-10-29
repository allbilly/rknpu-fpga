#!/usr/bin/env python3
"""Recheck a completed synthesis whose old counter rejected timing metadata.

Preserve the failed report. No synthesis is rerun or source/netlist changed.
All original hardware/geometry/source gates remain; known blackbox primitive
declarations may contain only Yosys timing metadata, never extra hardware.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from xc7_primitive_counts import primitive_counts

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--failed-report', type=Path, required=True)
a=p.parse_args();old_path=a.failed_report.resolve();old=json.loads(old_path.read_text());base=old_path.parent
assert old['status']=='FAIL' and old['reason']=='$specify2' and old['returncode']==0
assert (old['channels'],old['kernels'])==(32,16)
def verify(manifest):
    for name,sha in manifest['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha,name
verify(old['source'])
native_path=base/'native_report_snapshot.json';native=json.loads(native_path.read_text())
assert native['status']=='PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY'
assert (native['channels'],native['kernels'])==(32,16)
verify(native['source']);verify(native['artifacts'])
inputs=[base/n for n in ('hierarchy.json','mapped_hierarchy.json','mapped.json','mapped.v','mapping.log','mapping.ys','tool_help.log')]
out=base.parent/f'yosys-hierarchical-recheck-{time.time_ns()}';out.mkdir(exist_ok=False)
tracked=[Path(__file__).resolve(),ROOT/'tools/cmac/xc7_primitive_counts.py',ROOT/'tests/cmac/test_xc7_primitive_counts.py',old_path,native_path]+inputs
report=dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),
            original_mapping=old,native=native,channels=32,kernels=16,
            target_family='xc7',intended_part='xc7k480tffg1156-2',tool_version=old['tool_version'],commands=[],
            scope='Revalidation of saved completed synthesis with primitive-aware counting. No new synthesis or changed RTL. Not numerical netlist, device fit, P&R, timing/DRC, FPGA or RK evidence.')
def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
save();start=time.monotonic()
try:
    testlog=out/'counter_tests.log'
    argv=[sys.executable,'-m','unittest','discover','-s','tests/cmac','-p','test_xc7_primitive_counts.py','-v']
    with testlog.open('w') as f: result=subprocess.run(argv,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=60)
    report['commands'].append(dict(argv=argv,status='PASS' if result.returncode==0 else 'FAIL',returncode=result.returncode,log=str(testlog.relative_to(ROOT))))
    assert result.returncode==0,testlog.read_text()
    log=(base/'mapping.log').read_text()
    assert "Dumping module `\\rk_cmac_fp16_array'." in log
    assert 'Executing SHARE pass' not in log and 'ERROR:' not in log
    assert log.count('Found and reported 0 problems.')>=3
    original=json.loads((base/'hierarchy.json').read_text())['modules']
    def multipliers(name):
        if name=='NV_NVDLA_CMAC_CORE_MAC_mul': return 1
        return sum(multipliers(c['type']) for c in original[name].get('cells',{}).values() if c['type'] in original)
    assert multipliers('rk_cmac_fp16_array')==512
    del original
    partitioned=json.loads((base/'mapped_hierarchy.json').read_text())['modules']
    kernels=[c['type'] for c in partitioned['rk_cmac_fp16_array']['cells'].values() if 'rk_cmac_fp16_cell' in c['type']]
    assert len(kernels)==16 and len(set(kernels))==1
    assert int(partitioned[kernels[0]]['attributes']['keep_hierarchy'],2)==1
    expected=primitive_counts(partitioned,'rk_cmac_fp16_array')
    del partitioned
    flat=json.loads((base/'mapped.json').read_text())['modules'];top=flat['rk_cmac_fp16_array']
    cells=Counter(c['type'] for c in top['cells'].values() if c['type']!='$scopeinfo')
    assert cells==expected==primitive_counts(flat,'rk_cmac_fp16_array')
    assert sum(n for t,n in cells.items() if t.startswith('FD'))>=547
    assert sum(n for t,n in cells.items() if t.startswith('LUT'))>0
    for name,width in [('in_ready',1),('out_valid',1),('out_groups',704),('out_tag',35)]:
        bits=top['ports'][name]['bits'];assert len(bits)==width and all(isinstance(b,int) for b in bits),(name,bits)
    del flat,top
    netlist=out/'mapped.v';shutil.copyfile(base/'mapped.v',netlist)
    assert hashlib.sha256(netlist.read_bytes()).hexdigest()==report['source']['files'][str((base/'mapped.v').relative_to(ROOT))]
    assert fingerprint(tracked)==report['source']
    verify(old['source']);verify(native['source']);verify(native['artifacts'])
    report.update(status='PASS_PARALLEL_CMAC_XC7_MAPPING_ONLY',instantiated_multipliers=512,mapped_kernel_instances=16,
                  mapped_kernel_types=sorted(set(kernels)),cells=dict(cells),
                  lut_count=sum(n for t,n in cells.items() if t.startswith('LUT')),
                  ff_count=sum(n for t,n in cells.items() if t.startswith('FD')),dsp_count=cells['DSP48E1'],
                  artifacts=fingerprint([netlist,testlog]))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report.update(finished_utc=timestamp(),seconds=round(time.monotonic()-start,3));save();print(out/'report.json')
print(report['status'],report['cells'])
