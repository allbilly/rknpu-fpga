#!/usr/bin/env python3
"""Run a completed hierarchical compile after reviewing its generated-name warning.

The initial strict compile report remains unchanged. This permits only the
exact Verilator-generated C32 cell rename, with its generated wrapper checked;
it does not suppress arithmetic warnings, change RTL or edit expected results.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--compiled-report', type=Path, required=True)
a = p.parse_args()
parent_path = a.compiled_report.resolve()
parent = json.loads(parent_path.read_text())
assert parent['status'] == 'FAIL', 'Wait for the original strict runner to finish; do not race its compiler'
assert parent['tool_version'].startswith('Verilator 5.048 ')
assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32,16,512)
steps = [step for step in parent['commands'] if Path(step['log']).name == 'compile.log']
assert len(steps) == 1 and steps[0]['returncode'] == 0 and steps[0]['status'] == 'FAIL'
assert all(step['status'] == 'PASS' for step in parent['commands'] if step is not steps[0])

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

verify(parent['source'])
vr = parent['vectors']; verify(vr['source']); verify(vr['artifacts'])
assert (vr['channels'],vr['kernels'],vr['frames'],vr['outputs']) == (32,16,208,3328)
log = ROOT / steps[0]['log']
text = log.read_text()
locations = set(re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:',text,re.M))
donor = {tuple(item[:3]) for item in parent['donor_warnings']}
cell = ROOT / 'rtl/cmac/rk_cmac_fp16_cell.sv'
rename = ('DECLFILENAME',str(cell),'5')
assert locations == donor | {rename}, locations
assert parent['reason'] == str({rename}), parent['reason']
assert not re.search(r'%Error|warning:|sorry:',text,re.I)
rename_lines = [line for line in text.splitlines() if line.startswith('%Warning-DECLFILENAME: '+str(cell)+':')]
assert rename_lines and all(line == f"%Warning-DECLFILENAME: {cell}:5:8: Filename 'rk_cmac_fp16_cell' does not match MODULE name: 'rk_cmac_fp16_cell_b'" for line in rename_lines)
obj = parent_path.parent / 'obj'
wrapper = obj / 'Vrk_cmac_fp16_cell_b/rk_cmac_fp16_cell_b.sv'
args = obj / 'Vrk_cmac_fp16_cell_b__hierMkArgs.f'
assert '--hierarchical-block rk_cmac_fp16_cell,rk_cmac_fp16_cell_b' in args.read_text()
wrapper_text = wrapper.read_text()
for pattern in (r'module rk_cmac_fp16_cell_b\s*\(', r'input logic \[511:0\]\s+data',
                r'input logic \[511:0\]\s+weight', r'input logic \[31:0\]\s+data_mask',
                r'input logic \[31:0\]\s+weight_mask', r'output logic \[43:0\]\s+result'):
    assert re.search(pattern,wrapper_text), pattern
assert cell.read_text().splitlines()[4].startswith('module rk_cmac_fp16_cell #(')
binary = obj / 'sim'
assert binary.is_file()
# A generated wrapper/library alone does not prove that the top uses it.
# Check the completed emitted top, not merely its planned hierarchy arguments.
top_cpp = sorted(obj.glob('Vtb_cmac_fp16_array*.cpp'))
top_headers = sorted(obj.glob('Vtb_cmac_fp16_array*.h'))
assert top_cpp and top_headers, 'Missing generated top-level C++ model'
called = set()
for path in top_cpp:
    text = path.read_text()
    for operation in ('create', 'combo_update', 'seq_update'):
        symbol = 'rk_cmac_fp16_cell_b_protectlib_'+operation
        if symbol in text and re.search(r'\b'+symbol+r'\s*\(', text):
            called.add(operation)
for operation in ('create', 'combo_update', 'seq_update'):
    assert operation in called, \
        'Top-level model does not call the partition library: '+operation
assert not any('NV_NVDLA_CMAC_CORE_MAC_mul' in path.name for path in top_cpp+top_headers), \
    'Top-level model still contains donor multiplier internals; partitioning is unproven'
out = ROOT / f'build/rknpu-cmac-array/c32k16/hierarchical-replay-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
snapshot = out / 'original_report_snapshot.json'
snapshot.write_text(json.dumps(parent,indent=2)+'\n')
generated = sorted(path for path in obj.rglob('*') if path.suffix in ('.cpp','.h','.mk','.sv','.v','.vlt','.f','.dat'))
tracked = [ROOT / name for name in parent['source']['files']] + [snapshot,binary,log,wrapper,args,Path(__file__).resolve()]
report = dict(status='RUNNING',started_utc=timestamp(),source=fingerprint(tracked),generated_source=fingerprint(generated),
              vectors=vr,channels=32,kernels=16,parallel_products=512,commands=[],reused_compile=steps[0],
              reviewed_warning=dict(location=list(rename),occurrences=len(rename_lines),
                                    reason='Verilator hierarchical deparameterization renames the unmodified module to cell_b while retaining the source filename. Exact generated block mapping and C32 port widths checked.'),
              scope='Fresh unchanged full CMAC bench execution after one generated-name diagnostic review. Same RTL, 208 vectors, all assertions and flat-result comparison. No original failure relabeling, X verification, FPGA or RK claim.')

def save():
    (out / 'report.json').write_text(json.dumps(report,indent=2)+'\n')

def run(argv,name):
    step = dict(argv=list(map(str,argv)),status='RUNNING',log=str((out/(name+'.log')).relative_to(ROOT)))
    report['commands'].append(step);save();started=time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as stream:
            with subprocess.Popen(step['argv'],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True) as proc:
                try:
                    code=proc.wait(timeout=14400)
                except BaseException:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    proc.wait();raise
        output=(ROOT / step['log']).read_text();step['returncode']=code
        assert code==0 and not re.search(r'ERROR :|%Warning|warning:|sorry:',output,re.I),output[-5000:]
        step['status']='PASS';return output
    except Exception:
        step['status']='FAIL';raise
    finally:
        step['seconds']=round(time.monotonic()-started,3);save()

save()
try:
    report['tool_version']=run(['verilator','--version'],'version').splitlines()[0]
    assert report['tool_version']==parent['tool_version']
    result=run([binary,f'+VECTORS={ROOT / "build/rknpu-cmac-array/c32k16/vectors.hex"}','+COUNT=208'],'test')
    lines=[line for line in result.splitlines() if line.startswith('PASS ')]
    assert lines==[parent['flat_result']],result
    assert fingerprint(tracked)==report['source']
    verify(parent['source']);verify(vr['source']);verify(vr['artifacts']);verify(report['generated_source'])
    report.update(status='PASS_HIERARCHICAL_CMAC_NATIVE_ONLY',result=lines[0],
                  artifacts=fingerprint([ROOT / step['log'] for step in report['commands']]))
except Exception as exc:
    report.update(status='FAIL',reason=str(exc));raise
finally:
    report['finished_utc']=timestamp();save();print(out / 'report.json')
print(report['status'],report['result'])
