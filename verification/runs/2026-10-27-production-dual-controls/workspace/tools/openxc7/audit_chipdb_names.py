#!/usr/bin/env python3
"""Find independent chipdb name failures without changing a live tool build."""
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
base = ROOT / 'build/openxc7'
build = base / 'nextpnr-build'
checkout = ROOT / 'build/reference/nextpnr-xilinx'
out = base / f'name-audit-{time.time_ns()}'
out.mkdir(exist_ok=False)
source = Path(__file__).with_name('name_audit.cc')
flags_file = build / 'CMakeFiles/nextpnr-xilinx.dir/flags.make'
link_file = build / 'CMakeFiles/nextpnr-xilinx.dir/link.txt'
flags = {}
for line in flags_file.read_text().splitlines():
    if ' = ' in line:
        key, value = line.split(' = ', 1)
        flags[key] = shlex.split(value)
link = shlex.split(link_file.read_text())
objects = [(build / arg).resolve() for arg in link if arg.endswith('.o')]
original, chipdb = build / 'nextpnr-xilinx', base / 'xc7k480tffg1156-2.bin'
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
revision = subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip()
assert revision == 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
assert not subprocess.check_output(['git', '-C', checkout, 'status', '--porcelain'], text=True).strip()
original_sha, chipdb_sha = digest(original), digest(chipdb)
assert original_sha == '369df036b39a4a37af40a6047d1f6608e1966a3521ce107b7ebf9dde8132f7e8'
assert chipdb_sha == '98f43994365b465b70f33b17ba9a9e2489f17f3eee4c2be332bea0cbbbe17bf2'
tracked = [Path(__file__).resolve(), source, flags_file, link_file] + objects
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              nextpnr_revision=revision, original_binary_sha256=original_sha, chipdb_sha256=chipdb_sha,
              commands=[], scope='Partial independent name/location diagnostic on original objects. Always exits failure; not an accepted archcheck, routing tool, timing/DRC or FPGA result.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
def run(argv, name, expected=0):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=build, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == expected, text[-5000:]
        step['status'] = 'PASS' if expected == 0 else 'DIAGNOSTIC_FAILURE_EXPECTED'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-started, 3); save()
save()
try:
    report['compiler_version'] = run([link[0], '--version'], 'compiler_version').splitlines()[0]
    obj, binary = out / 'name_audit.o', out / 'nextpnr-name-audit'
    run([link[0], *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'], '-O0', '-g', '-c', source, '-o', obj], 'compile')
    replaced = 0
    for i, value in enumerate(link):
        if value == 'CMakeFiles/nextpnr-xilinx.dir/common/archcheck.cc.o':
            link[i] = str(obj); replaced += 1
        elif value.startswith('-Wl,--dependency-file='):
            link[i] = '-Wl,--dependency-file=' + str(out / 'link.d')
    assert replaced == 1 and link.count('-o') == 1
    link[link.index('-o')+1] = str(binary)
    run(link, 'link')
    text = run([binary, '--chipdb', chipdb, '--test'], 'audit', expected=255)
    assert 'PARTIAL_NAME_AUDIT_COMPLETE' in text, text
    for category in ('BEL', 'WIRE', 'PIP', 'LOCATION'):
        assert f'AUDIT_{category}_EXAMINED=' in text, text
    report['findings'] = [line for line in text.splitlines() if 'AUDIT_' in line]
    assert fingerprint(tracked) == report['source']
    assert digest(original) == original_sha and digest(chipdb) == chipdb_sha
    assert not subprocess.check_output(['git', '-C', checkout, 'status', '--porcelain'], text=True).strip()
    report.update(status='COMPLETED_PARTIAL_NAME_DIAGNOSTIC_NOT_INTEGRITY_PASS',
                  artifacts=fingerprint([obj, binary]+[ROOT / step['log'] for step in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
print('\n'.join(report['findings']))
