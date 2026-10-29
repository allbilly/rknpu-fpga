#!/usr/bin/env python3
"""Run the full-width C32/K16 YPCB wrapper against the packaged K65 ROM."""
import argparse
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
p.add_argument('--suite', choices=('smoke', 'full'), default='smoke')
a = p.parse_args()
spec_path = ROOT / 'fpga/cmac/array_sources.json'
spec = json.loads(spec_path.read_text())
sources = [ROOT / name for name in spec['simulation_helpers']+spec['synthesis']]
bench = ROOT / spec['bench']
tracked = sources + [bench, spec_path, Path(__file__).resolve(), ROOT / 'tools/cmac/gen_array_board.py', ROOT / spec['constraints']]
tracked += sorted((ROOT / 'tests/cmac/array_data').iterdir())
donor = ROOT / 'rtl/vendor/nvdla'
tracked += [donor / name for name in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h')]
out = ROOT / f'build/rknpu-array-board/{a.suite}-iverilog-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), suite=a.suite, source=fingerprint(tracked),
              commands=[], tests=[], seed='directed board/reset scenarios; fixed source-pinned K65 finite operands',
              scope='Native RTL board-wrapper simulation: C32/K16 CMAC, raw command DMA, trace BRAM, reset/LED controller and complete ROM/readback. Not physical FPGA, RK captures, DDR/PCIe or timing/electrical validation.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')

def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            with subprocess.Popen(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                try:
                    code = proc.wait(timeout=14400)
                except BaseException:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    raise
        text = (ROOT / step['log']).read_text()
        step['returncode'] = code
        assert code == 0 and 'ERROR :' not in text, text[-5000:]
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
    run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
    report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    binary = out / 'sim.vvp'
    run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
         '-s', bench.stem, '-o', binary, *sources, bench], 'compile')
    for mode in ((1, 8, 0) if a.suite == 'smoke' else range(9)):
        text = run(['vvp', binary, f'+MODE={mode}'], f'mode{mode}')
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert len(lines) == 1, text
        match = re.fullmatch(r'PASS C32 K16 BRAM board RTL mode=(\d+) success=(\d+) resets=(\d+) faults=(\d+) init=(\d+) check=(\d+) cmd_reads=(\d+) operand_reads=(\d+) writes=(\d+) acks=(\d+) cycles=(\d+); no physical FPGA test', lines[0])
        assert match, text
        got_mode, successes, resets, faults, init, checked, commands, reads, writes, acks, cycles = map(int, match.groups())
        good = mode in (0, 3, 4, 5, 6)
        assert (got_mode, successes, resets, faults) == (mode, 2 if mode==6 else int(good), int(mode in (3,4,5,6)), int(not good))
        assert init == 4096 and 0 < cycles < 1048576
        if good:
            assert (checked, commands, reads, writes, acks) == (4096, 196, 6528, 64, 64), text
        elif mode == 1:
            assert (checked, commands, reads, writes, acks) == (0, 1, 0, 0, 0), text
        elif mode == 8:
            assert checked == writes == acks == 0 and commands == 196 and 20 <= reads <= 21, text
        else:
            assert (checked, commands, reads, writes, acks) == (1, 196, 6528, 64, 64), text
        report['tests'].append(dict(mode=mode, status='PASS', result=lines[0])); save()
    assert fingerprint(tracked) == report['source']
    report.update(status='PASS_RAW_ARRAY_BOARD_'+a.suite.upper()+'_RTL_ONLY',
                  artifacts=fingerprint([binary]+[ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
