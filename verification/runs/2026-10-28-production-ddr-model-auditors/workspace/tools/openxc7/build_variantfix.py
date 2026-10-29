#!/usr/bin/env python3
"""Build and test an isolated nextpnr BEL-name fix; never place or program."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

base = ROOT / 'build/openxc7'
checkout = ROOT / 'build/reference/nextpnr-xilinx-variantfix'
original = ROOT / 'build/reference/nextpnr-xilinx'
revision = 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
assert subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip() == revision
assert not subprocess.check_output(['git', '-C', original, 'status', '--porcelain'], text=True).strip()
out = base / f'variantfix-{time.time_ns()}'
out.mkdir(exist_ok=False)
chipdb = base / 'xc7k480tffg1156-2.bin'
def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
assert digest(chipdb) == '98f43994365b465b70f33b17ba9a9e2489f17f3eee4c2be332bea0cbbbe17bf2'
tracked = [checkout / n for n in ('common/archcheck.cc', 'xilinx/arch.cc', 'xilinx/arch.h', 'xilinx/bel_variant_name.h')]
tracked += [Path(__file__).resolve(), Path(__file__).with_name('test_bel_variant_name.cpp')]
report = dict(status='RUNNING', started_utc=timestamp(), base_revision=revision,
              source=fingerprint(tracked), chipdb_sha256=digest(chipdb), commands=[],
              scope='Experimental isolated BEL-name fix and original archcheck. No physical implementation, timing signoff or bitstream.')
(out / 'tracked.patch').write_bytes(subprocess.check_output(['git', '-C', checkout, 'diff', '--binary']))
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
env = dict(os.environ)
env['PKG_CONFIG_PATH'] = str(base / 'prefix/share/pkgconfig') + (':' + env['PKG_CONFIG_PATH'] if env.get('PKG_CONFIG_PATH') else '')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=7200)
        step['returncode'] = result.returncode
        text = (ROOT / step['log']).read_text()
        assert result.returncode == 0, text[-5000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic() - start, 3)
        save()
save()
try:
    report['compiler_version'] = run(['c++', '--version'], 'compiler_version').splitlines()[0]
    report['cmake_version'] = run(['cmake', '--version'], 'cmake_version').splitlines()[0]
    report['eigen_version'] = run(['pkg-config', '--modversion', 'eigen3'], 'eigen_version').strip()
    run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I' + str(checkout / 'xilinx'), tracked[-1], '-o', out / 'parser_test'], 'parser_compile')
    report['parser_result'] = run([out / 'parser_test'], 'parser_test').strip()
    build = out / 'build'
    run(['cmake', '-S', checkout, '-B', build, '-DARCH=xilinx', '-DBUILD_PYTHON=OFF', '-DBUILD_GUI=OFF', '-DBUILD_HEAP=ON', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5'], 'configure')
    run(['cmake', '--build', build, '-j2'], 'build')
    binary = build / 'nextpnr-xilinx'
    report['binary_sha256'] = digest(binary)
    report['tool_version'] = run([binary, '--version'], 'tool_version').strip()
    run([binary, '--chipdb', chipdb, '--test'], 'integrity')
    assert fingerprint(tracked) == report['source']
    assert digest(chipdb) == report['chipdb_sha256']
    assert not subprocess.check_output(['git', '-C', original, 'status', '--porcelain'], text=True).strip()
    report.update(status='PASS_EXPERIMENTAL_ARCHCHECK_ONLY', artifacts=fingerprint([ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'])
