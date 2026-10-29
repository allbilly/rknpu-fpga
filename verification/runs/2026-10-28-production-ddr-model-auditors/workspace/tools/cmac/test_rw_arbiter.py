#!/usr/bin/env python3
"""Source-bound simulation of the one-outstanding CMAC read/write arbiter."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--tool', choices=('iverilog', 'verilator'), default='iverilog')
a = p.parse_args()
sources = [ROOT / 'rtl/cmac/rk_cmac_rw_arbiter.sv', ROOT / 'tests/cmac/tb_cmac_rw_arbiter.sv']
tracked = sources + [Path(__file__).resolve()]
out = ROOT / f'build/rknpu-rw-arbiter/{a.tool}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
              scope='Native arbitration, ownership and fault protocol only; no numerical, raw-command or FPGA claim.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0, text[-5000:]
        if name in ('compile', 'lint'):
            assert not re.search(r'warning:|sorry:|%Warning', text, re.I), text[-5000:]
        assert 'ERROR :' not in text, text[-5000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic() - started, 3)
        save()

save()
try:
    report['tool_version'] = run([a.tool, '-V' if a.tool == 'iverilog' else '--version'], 'version').splitlines()[0]
    top = 'tb_cmac_rw_arbiter'
    if a.tool == 'iverilog':
        binary = out / 'sim.vvp'
        run(['iverilog', '-g2012', '-s', top, '-o', binary, *sources], 'compile')
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        execute = ['vvp', binary]
    else:
        flags = ['--timing', '--assert', '-Wall', '--timescale-override', '1ns/1ps']
        run(['verilator', '--lint-only', *flags, '--top-module', top, *sources], 'lint')
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
        binary = out / 'obj/sim'
        run(['verilator', '--binary', *flags, '-j', '2', '--top-module', top,
             '--Mdir', out / 'obj', '-o', 'sim', *sources], 'compile')
        execute = [binary]
    text = run(execute, 'test')
    lines = [line for line in text.splitlines() if line.startswith('PASS ')]
    assert lines == ['PASS CMAC read/write arbiter transfers=36 reads=19 writes=17 fair_pairs=16 locked_write=1 cancels=3 unsolicited_faults=1'], text
    assert fingerprint(tracked) == report['source']
    report.update(status='PASS_CMAC_RW_ARBITER_NATIVE_ONLY', result=lines[0],
                  artifacts=fingerprint([binary] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['result'])
