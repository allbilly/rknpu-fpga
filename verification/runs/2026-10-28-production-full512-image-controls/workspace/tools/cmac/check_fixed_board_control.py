#!/usr/bin/env python3
"""Source-bound fixed-board runner controls, not HDL or physical acceptance."""
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

tracked = [ROOT / name for name in ('tools/cmac/test_fixed_array_board.py', 'tools/cmac/vivado_array.py',
                                   'tools/evidence.py', 'tests/cmac/test_fixed_array_board_control.py',
                                   'fpga/cmac/array_sources.json', 'rtl/cmac/rk_cmac_cacc_fp16_array.sv')]
tracked.append(Path(__file__).resolve())
out = ROOT / f'build/rknpu-fixed-board-control/{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
              scope='Nine Python contract-control methods with synthetic fixtures. Not HDL simulation, numerical acceptance, raw integration, Vivado, bitstream or FPGA/RK evidence.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


save()
try:
    argv = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', 'test_fixed_array_board_control.py', '-v']
    log = out / 'controls.log'
    step = dict(argv=argv, status='RUNNING', log=str(log.relative_to(ROOT)))
    report['commands'].append(step); save(); started = time.monotonic()
    report['python_version'] = sys.version
    with log.open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=360)
    step.update(returncode=result.returncode, seconds=round(time.monotonic() - started, 3))
    text = log.read_text()
    assert result.returncode == 0 and re.search(r'Ran 9 tests in .*\n\nOK\n', text), text[-6000:]
    step.update(status='PASS', methods=9)
    assert fingerprint(tracked) == report['source'], 'Control sources changed during tests'
    report.update(status='PASS_FIXED_BOARD_CONTRACT_CONTROLS_ONLY', artifacts=fingerprint([log]))
except Exception as exc:
    if report['commands']:
        report['commands'][-1]['status'] = 'FAIL'
    report.update(status='FAIL', reason=str(exc)); raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
