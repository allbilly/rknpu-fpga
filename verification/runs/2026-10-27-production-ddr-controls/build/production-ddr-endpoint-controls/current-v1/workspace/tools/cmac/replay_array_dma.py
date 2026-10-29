#!/usr/bin/env python3
"""Replay unchanged C32/K16 DMA tests using a verified existing Icarus build.

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
assert 'rtl/cmac/rk_cmac_array_dma.sv' in parent['source']['files']
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
protocol = [(cases['m2_n17_k31'], mode) for mode in (1, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15)]
if a.suite == 'protocol':
    selected = protocol
elif a.suite == 'finite':
    selected = [(cases['m2_n17_k65_finite'], 0)]
else:
    selected = [(case, 0) for case in vr['cases']] + protocol + [(cases['m2_n17_k31'], mode) for mode in (2, 6, 14)]
out = ROOT / f'build/rknpu-array-dma/replay-{a.suite}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
snapshot = out / 'original_report_snapshot.json'
snapshot.write_text(json.dumps(parent, indent=2)+'\n')
tracked = [ROOT / name for name in parent['source']['files']] + [binary, snapshot, Path(__file__).resolve(), ROOT / compile_step['log']]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), vectors=vr,
              suite=a.suite, reused_compile=compile_step, commands=[], tests=[], seed='0x3588ad16',
              scope='Fresh runs of the unchanged compiled C32/K16 DMA bench. Protocol covers descriptor/framing/profile/early memory faults; finite covers only K65 finite; full covers the complete listed synthetic corpus. No FPGA/RK or upstream UTB claim.')
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
        match = re.fullmatch(r'PASS DMA C32 K16 core mode=(\d+) command_reads=(\d+) command_words=(\d+) reads=(\d+) writes=(\d+) acknowledgments=(\d+) jobs=(\d+) seed=3588ad16', lines[0])
        assert match, text
        actual_mode, command_reads, command_words, reads, writes, acks, jobs = map(int, match.groups())
        assert actual_mode == mode
        if mode in (0, 6, 14):
            assert (command_reads, command_words) == (196, 49), text
            assert (reads, writes, acks, jobs) == (case['reads'], case['writes'], case['writes'], 1), text
        elif mode == 2:
            assert (command_reads, command_words) == (196, 49), text
            assert (reads, writes, acks, jobs) == (case['reads'], case['writes'], case['writes']-1, 0), text
        else:
            assert jobs == writes == acks == 0, text
            expected = {1: (196,49,1), 3: (0,0,0), 4: (1,0,0), 5: (1,0,0),
                        7: (4,1,0), 8: (4,0,0), 9: (1,0,0), 10: (0,0,0),
                        11: (0,0,0), 12: (0,0,0), 13: (184,45,0), 15: (1,0,0)}
            assert (command_reads, command_words, reads) == expected[mode], text
        report['tests'].append(dict(name=name, status='PASS', result=lines[0])); save()
    assert fingerprint(tracked) == report['source']
    verify(parent['source']); verify(vr['source']); verify(vr['artifacts'])
    report.update(status='PASS_RAW_ARRAY_DMA_REPLAY_'+a.suite.upper()+'_ONLY',
                  artifacts=fingerprint([ROOT / step['log'] for step in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'], len(report['tests']))
