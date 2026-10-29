#!/usr/bin/env python3
"""Fixed build-profile controls and unchanged physical gates, all MOCKED."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

tracked = [ROOT / name for name in ('tools/cmac/vivado_fixed_array.py', 'tools/cmac/vivado_array.py',
                                   'tools/cmac/test_fixed_array_board.py', 'tools/evidence.py',
                                   'tests/cmac/test_fixed_array_build.py', 'tests/cmac/test_array_build.py',
                                   'tests/cmac/test_fixed_array_board_control.py', 'tests/test_fpga_build.py',
                                   'fpga/cmac/array_sources.json', 'fpga/cmac/build_array.tcl.in',
                                   'rtl/cmac/rk_cmac_cacc_fp16_array.sv')]
tracked.append(Path(__file__).resolve())
out = ROOT / f'build/rknpu-fixed-array-build-control/{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), commands=[],
              scope='Eighteen fixed-profile Python/Tcl control methods per interpreter with synthetic evidence and all Vivado calls MOCKED. No HDL/Vivado implementation, routed checkpoint, bitstream, electrical fact, FPGA or RK acceptance.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


save()
try:
    xilinx = Path('/home/fedora/vivado/2026.1.1/Vivado_Lab')
    for name, candidate in (('system', shutil.which('tclsh')), ('xilinx86', xilinx / 'bin/unwrapped/lnx64.o/tclsh8.6')):
        if candidate is None or not Path(candidate).is_file():
            report[name] = 'UNAVAILABLE, not a pass'
            if name == 'system': raise RuntimeError('UNAVAILABLE: system Tcl')
            continue
        interpreter = Path(candidate).resolve()
        env = {key: value for key, value in os.environ.items() if not key.startswith(('RK_', 'MOCK_'))}
        env['RK_TEST_TCLSH'] = str(interpreter)
        if name == 'xilinx86':
            env['LD_LIBRARY_PATH'] = str(xilinx / 'lib/lnx64.o'); env['TCL_LIBRARY'] = str(xilinx / 'tps/tcl/tcl8.6')
        argv = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', 'test_fixed_array_build.py', '-v']
        log = out / (name + '.log')
        step = dict(argv=argv, log=str(log.relative_to(ROOT)), interpreter=str(interpreter),
                    interpreter_sha256=hashlib.sha256(interpreter.read_bytes()).hexdigest(), status='RUNNING',
                    runtime_environment={key: env[key] for key in ('RK_TEST_TCLSH', 'LD_LIBRARY_PATH', 'TCL_LIBRARY') if key in env})
        report['commands'].append(step); save(); started = time.monotonic()
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=360)
        text = log.read_text(); step.update(returncode=result.returncode, seconds=round(time.monotonic() - started, 3))
        assert result.returncode == 0 and re.search(r'Ran 18 tests in .*\n\nOK\n', text), text[-6000:]
        step.update(status='PASS', methods=18); save()
    assert fingerprint(tracked) == report['source'], 'Build controls changed during tests'
    report.update(status='PASS_FIXED_ARRAY_BUILD_CONTROL_MOCKS_ONLY', artifacts=fingerprint([ROOT / step['log'] for step in report['commands']]))
except Exception as exc:
    if report['commands'] and report['commands'][-1]['status'] == 'RUNNING': report['commands'][-1]['status'] = 'FAIL'
    report.update(status='FAIL', reason=str(exc)); raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
