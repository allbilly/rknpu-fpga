#!/usr/bin/env python3
"""Record source-bound mock build-control tests; does not invoke Vivado."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from vivado_array import inputs

spec, tracked = inputs()
tracked += [ROOT / 'tests/cmac/test_array_build.py', ROOT / 'tests/test_fpga_build.py', Path(__file__).resolve()]
out = ROOT / f'build/rknpu-array-build-control/{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
              seed='directed control-flow cases', scope='Tcl and Python build-control MOCKS only. No HDL elaboration, Vivado, physical timing, DRC, checkpoint or bitstream created.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
save()
try:
    xilinx = Path('/home/fedora/vivado/2026.1.1/Vivado_Lab')
    for name, interpreter in (('system', None), ('xilinx86', xilinx / 'bin/unwrapped/lnx64.o/tclsh8.6')):
        if interpreter is not None:
            if not interpreter.is_file():
                report['optional_xilinx_tcl'] = 'UNAVAILABLE; not counted as tested'
                continue
        env = dict(os.environ)
        if interpreter is not None:
            env['RK_TEST_TCLSH'] = str(interpreter)
            env['LD_LIBRARY_PATH'] = str(xilinx / 'lib/lnx64.o')
            env['TCL_LIBRARY'] = str(xilinx / 'tps/tcl/tcl8.6')
        else:
            env.pop('RK_TEST_TCLSH', None)
        argv = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', 'test_array_build.py', '-v']
        log = out / (name+'.log')
        step = dict(argv=argv, log=str(log.relative_to(ROOT)), interpreter=str(interpreter or 'PATH tclsh'), status='RUNNING')
        if interpreter is not None:
            step['runtime_environment'] = {key:env[key] for key in ('LD_LIBRARY_PATH', 'TCL_LIBRARY')}
            step['interpreter_sha256'] = hashlib.sha256(interpreter.read_bytes()).hexdigest()
        report['commands'].append(step); save()
        started = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        text = log.read_text()
        step.update(returncode=result.returncode, seconds=round(time.monotonic()-started, 3))
        assert result.returncode == 0 and re.search(r'Ran 9 tests in .*\n\nOK\n', text), text[-6000:]
        step.update(status='PASS', methods=9, version=next(line for line in text.splitlines() if 'Tcl ' in line))
        save()
    assert fingerprint(tracked) == report['source']
    report.update(status='PASS_ARRAY_BUILD_CONTROL_MOCKS_ONLY', artifacts=fingerprint([ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    if report['commands'] and report['commands'][-1]['status'] == 'RUNNING':
        report['commands'][-1]['status'] = 'FAIL'
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
