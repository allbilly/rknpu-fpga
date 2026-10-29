#!/usr/bin/env python3
"""Build a diagnostic-only archcheck object without modifying pinned nextpnr.

Links unchanged existing nextpnr objects with extra failure logging. All
original archcheck assertions remain active. Never produces FASM/bitstreams.
"""
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
out = base / f'name-diagnostic-{time.time_ns()}'
out.mkdir(exist_ok=False)
source = Path(__file__).with_name('archcheck_diagnostic.cc')
flags_file = build / 'CMakeFiles/nextpnr-xilinx.dir/flags.make'
link_file = build / 'CMakeFiles/nextpnr-xilinx.dir/link.txt'
flags = {}
for line in flags_file.read_text().splitlines():
    if ' = ' in line:
        key, value = line.split(' = ', 1)
        flags[key] = shlex.split(value)
link = shlex.split(link_file.read_text())
objects = [(build / arg).resolve() for arg in link if arg.endswith('.o')]
original = build / 'nextpnr-xilinx'
chipdb = base / 'xc7k480tffg1156-2.bin'
revision = subprocess.check_output(['git', '-C', checkout, 'rev-parse', 'HEAD'], text=True).strip()
assert revision == 'd486d8ef6a1c756ca72b2ba495e7e18e4c24815d'
assert not subprocess.check_output(['git', '-C', checkout, 'status', '--porcelain'], text=True).strip()
def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
original_sha, chipdb_sha = digest(original), digest(chipdb)
assert chipdb_sha == '98f43994365b465b70f33b17ba9a9e2489f17f3eee4c2be332bea0cbbbe17bf2'
assert original_sha == '369df036b39a4a37af40a6047d1f6608e1966a3521ce107b7ebf9dde8132f7e8'
tracked = [Path(__file__).resolve(), source, flags_file, link_file, checkout / 'common/archcheck.cc'] + objects
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              nextpnr_revision=revision, original_binary_sha256=original_sha, chipdb_sha256=chipdb_sha,
              commands=[], scope='Extra BEL mismatch logging, original assertions intact. Not a corrected or accepted FPGA toolchain.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name, expected=0):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=build, stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == expected, text[-5000:]
        step['status'] = 'PASS' if expected == 0 else 'EXPECTED_FAILURE_REPRODUCED'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-start, 3)
        save()
save()
try:
    report['compiler_version'] = run([link[0], '--version'], 'compiler_version').splitlines()[0]
    obj, binary = out / 'archcheck.o', out / 'nextpnr-diagnostic'
    run([link[0], *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], *flags['CXX_FLAGS'],
         '-O0', '-g', '-c', source, '-o', obj], 'compile')
    replaced = 0
    for i, value in enumerate(link):
        if value == 'CMakeFiles/nextpnr-xilinx.dir/common/archcheck.cc.o':
            link[i] = str(obj)
            replaced += 1
        elif value.startswith('-Wl,--dependency-file='):
            link[i] = '-Wl,--dependency-file=' + str(out / 'link.d')
    assert replaced == 1 and link.count('-o') == 1
    link[link.index('-o')+1] = str(binary)
    run(link, 'link')
    text = run([binary, '--chipdb', chipdb, '--test'], 'integrity', expected=255)
    assert 'BEL_NAME_MISMATCH' in text and 'bel == bel2' in text, text
    assert fingerprint(tracked) == report['source']
    assert digest(original) == original_sha and digest(chipdb) == chipdb_sha
    assert not subprocess.check_output(['git', '-C', checkout, 'status', '--porcelain'], text=True).strip()
    report.update(status='REPRODUCED_BEL_NAME_FAILURE', diagnostic=text,
                  artifacts=fingerprint([obj, binary] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['diagnostic'])
