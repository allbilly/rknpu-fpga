#!/usr/bin/env python3
"""Replay unchanged raw-core tests using a verified existing Icarus build.

Only the compile step is reused; every selected simulation is freshly run.
Protocol-only results never imply numerical replay or a complete core pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--compiled-report', type=Path, required=True)
p.add_argument('--suite', choices=('protocol', 'finite', 'full'), default='full')
a = p.parse_args()
parent_path = a.compiled_report.resolve()
parent = json.loads(parent_path.read_text())
def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
verify(parent['source'])
vr = parent['vectors']; verify(vr['source']); verify(vr['artifacts'])
compile_steps = [step for step in parent['commands'] if Path(step['log']).name == 'compile.log']
assert len(compile_steps) == 1 and compile_steps[0]['status'] == 'PASS' and compile_steps[0]['returncode'] == 0
compile_step = compile_steps[0]
assert compile_step['argv'][0] == 'iverilog' and '-o' in compile_step['argv']
binary = Path(compile_step['argv'][compile_step['argv'].index('-o')+1])
assert binary.resolve() == parent_path.parent / 'sim.vvp' and binary.is_file()
base = ROOT / 'build/rknpu-array-core-vectors'
cases = {case['name']: case for case in vr['cases']}
protocol = [(cases['m2_n17_k31'], mode) for mode in (1, 3, 4, 5, 7, 9)]
if a.suite == 'protocol':
    selected = protocol
elif a.suite == 'finite':
    selected = [(cases['m2_n17_k65_finite'], 0)]
else:
    selected = [(case, 0) for case in vr['cases']] + protocol + [(cases['m2_n17_k31'], mode) for mode in (2, 6)]
out = ROOT / f'build/rknpu-array-core/replay-{a.suite}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
snapshot = out / 'original_report_snapshot.json'
snapshot.write_text(json.dumps(parent, indent=2)+'\n')
tracked = [ROOT / name for name in parent['source']['files']] + [binary, snapshot, Path(__file__).resolve(), ROOT / compile_step['log']]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), vectors=vr,
              suite=a.suite, reused_compile=compile_step, commands=[], tests=[], seed='0x3588ac16',
              scope='Fresh runs of the unchanged compiled raw-core bench. Protocol suite covers only early errors/cancel; finite covers only the K65 finite replay; full covers the complete listed synthetic corpus. No FPGA/RK or upstream UTB claim.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'ERROR :' not in text, text[-5000:]
        assert not re.search(r'warning:|sorry:', text, re.I), text[-5000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-started, 3); save()
save()
try:
    report['tool_version'] = parent['tool_version']
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    assert report['runtime_version'] == parent['runtime_version']
    for case, mode in selected:
        name = f'{case["name"]}-mode{mode}'
        text = run(['vvp', binary, f'+DIRECTORY={base / case["name"]}', f'+MODE={mode}', f'+ROWS={case["rows"]}',
                    f'+AI={case["ai"]}', f'+AO={case["ao"]}', f'+READS={case["reads"]}', f'+WRITES={case["writes"]}'], name)
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert len(lines) == 1, text
        match = re.fullmatch(r'PASS raw C32 K16 core mode=(\d+) reads=(\d+) writes=(\d+) acknowledgments=(\d+) jobs=(\d+) seed=3588ac16', lines[0])
        assert match, text
        actual_mode, reads, writes, acks, jobs = map(int, match.groups())
        assert actual_mode == mode
        if mode in (0, 6):
            assert (reads, writes, acks, jobs) == (case['reads'], case['writes'], case['writes'], 1), text
        elif mode == 2:
            assert (reads, writes, acks, jobs) == (case['reads'], case['writes'], case['writes']-1, 0), text
        else:
            assert jobs == writes == acks == 0, text
        report['tests'].append(dict(name=name, status='PASS', result=lines[0])); save()
    assert fingerprint(tracked) == report['source']
    verify(parent['source']); verify(vr['source']); verify(vr['artifacts'])
    report.update(status='PASS_RAW_ARRAY_CORE_REPLAY_'+a.suite.upper()+'_ONLY',
                  artifacts=fingerprint([ROOT / step['log'] for step in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'], len(report['tests']))
