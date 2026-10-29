#!/usr/bin/env python3
"""Compile a pinned Verilator C++ model at -O0 in a separate directory.

The original generated C++, RTL, full corpus and test assertions are unchanged.
This avoids expensive host optimization; it is not a smaller HDL test.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--generated-report', type=Path, required=True)
a = p.parse_args()
parent_path = a.generated_report.resolve()
parent = json.loads(parent_path.read_text())
def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
verify(parent['source'])
vr = parent['vectors']; verify(vr['source']); verify(vr['artifacts'])
C, K = parent['channels'], parent['kernels']
assert (C, K) == (vr['channels'], vr['kernels'])
lint_steps = [step for step in parent['commands'] if Path(step['log']).name in ('baseline_lint.log', 'bench_lint.log')]
assert len(lint_steps) == 2 and all(step['status'] == 'PASS' and step['returncode'] == 0 for step in lint_steps)
original_obj = parent_path.parent / 'obj'
prefix = 'Vtb_cmac_fp16_array'
generated = sorted(path for path in original_obj.iterdir() if path.suffix in ('.cpp', '.h', '.mk'))
assert len(generated) > 10 and all(path.name.startswith(prefix) for path in generated)
assert (original_obj / (prefix+'.mk')) in generated
generated_source = fingerprint(generated)
out = parent_path.parent.parent / f'verilator-o0-{time.time_ns()}'
obj = out / 'obj'
obj.mkdir(parents=True, exist_ok=False)
snapshot = out / 'original_report_snapshot.json'
snapshot.write_text(json.dumps(parent, indent=2)+'\n')
for path in generated:
    shutil.copy2(path, obj / path.name)
copied = [obj / path.name for path in generated]
for original, copy in zip(generated, copied):
    assert original.read_bytes() == copy.read_bytes(), original
source_paths = [ROOT / name for name in parent['source']['files']]
source_paths += [Path(__file__).resolve(), snapshot]
tracked = fingerprint(source_paths)
report = dict(status='RUNNING', started_utc=timestamp(), source=tracked, generated_source=generated_source,
              copied_cpp=fingerprint(copied), original_lint_steps=lint_steps, donor_warnings=parent['donor_warnings'],
              vectors=vr, channels=C, kernels=K, parallel_products=C*K, commands=[],
              host_optimization='OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
              scope='Full unchanged native Verilator arithmetic/hold/tag/reset test, with separately compiled -O0 host C++. Original build left running. No Icarus X-injection, netlist, FPGA or RK claim.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
def run(argv, name, cwd=ROOT):
    step = dict(argv=list(map(str, argv)), cwd=str(cwd), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=cwd, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'ERROR :' not in text, text[-5000:]
        assert not re.search(r'warning:|%Warning|sorry:', text, re.I), text[-5000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-started, 3); save()
save()
try:
    report['tool_version'] = run(['verilator', '--version'], 'version').splitlines()[0]
    assert report['tool_version'] == parent['tool_version'], (report['tool_version'], parent['tool_version'])
    report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
    report['make_version'] = run(['make', '--version'], 'make_version').splitlines()[0]
    run(['make', '-f', prefix+'.mk', '-j', '2', 'OPT_FAST=-O0', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O0'], 'compile', obj)
    binary = obj / 'sim'
    base = ROOT / f'build/rknpu-cmac-array/c{C}k{K}'
    text = run([binary, f'+VECTORS={base / "vectors.hex"}', f'+COUNT={vr["frames"]}'], 'test')
    lines = [line for line in text.splitlines() if line.startswith('PASS ')]
    assert len(lines) == 1 and f'C={C} K={K} frames={vr["frames"]} checked_outputs={vr["outputs"]}' in lines[0], text
    assert f'retired_outputs={vr["outputs"]-K} reset_canceled={K}' in lines[0] and 'faults=0' in lines[0], lines
    assert fingerprint(source_paths) == tracked
    verify(parent['source']); verify(vr['source']); verify(vr['artifacts'])
    verify(generated_source); verify(report['copied_cpp'])
    report.update(status='PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY', result=lines[0],
                  artifacts=fingerprint([binary]+[ROOT / step['log'] for step in report['commands']]+[ROOT / step['log'] for step in lint_steps]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'], report['result'])
