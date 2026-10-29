#!/usr/bin/env python3
"""Verify hierarchical compilation against the completed full flat C32/K16 test.

Same RTL, corpus, bench and assertions; a separate Verilator control file
partitions the repeated cell. No waveform substitution or arithmetic model.
"""
import argparse
import hashlib
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
p.add_argument('--flat-report', type=Path, required=True)
a = p.parse_args()
parent_path = a.flat_report.resolve()
parent = json.loads(parent_path.read_text())
assert parent['status'] == 'PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY'
assert parent['tool_version'].startswith('Verilator ') and (parent['channels'], parent['kernels']) == (32, 16)

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

verify(parent['source']); verify(parent['artifacts'])
vr = parent['vectors']; verify(vr['source']); verify(vr['artifacts'])
assert (vr['channels'], vr['kernels'], vr['frames'], vr['outputs']) == (32, 16, 208, 3328)
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / name for name in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v',
                                    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v')]
sources += [ROOT / 'rtl/cmac/rk_cmac_fp16_cell.sv', ROOT / 'rtl/cmac/rk_cmac_fp16_array.sv']
bench = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
control = ROOT / 'tools/cmac/array_hierarchy.vlt'
for path in sources+[bench]:
    assert str(path.relative_to(ROOT)) in parent['source']['files']
out = ROOT / f'build/rknpu-cmac-array/c32k16/hierarchical-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
snapshot = out / 'flat_report_snapshot.json'
snapshot.write_text(json.dumps(parent, indent=2)+'\n')
tracked = [ROOT / name for name in parent['source']['files']] + [control, Path(__file__).resolve(), snapshot]
allowed = {tuple(item[:3]) for item in parent['donor_warnings']}
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), vectors=vr,
              channels=32, kernels=16, parallel_products=512, commands=[], donor_warnings=parent['donor_warnings'],
              flat_result=parent['result'], host_optimization='OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
              scope='Fresh full native arithmetic/hold/reset simulation using hierarchical Verilation of the unchanged C32 cell. Same 512 multipliers, all 208 vectors and assertions. Not Icarus X verification, mapped timing, upstream UTB or physical FPGA/RK validation.')

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')

def run(argv, name, lint=False):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as stream:
            with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
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
        assert code == 0 and 'ERROR :' not in text, text[-7000:]
        warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
        if lint:
            assert set(warnings) <= allowed, set(warnings)-allowed
            assert len(warnings) == len(re.findall(r'^%Warning-', text, re.M)), 'Unparsed Verilator warning'
            step['warning_locations'] = [list(item) for item in warnings]
        else:
            assert not warnings
        assert not re.search(r'warning:|sorry:', text, re.I), text[-7000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-started, 3); save()

save()
try:
    report['tool_version'] = run(['verilator', '--version'], 'version').splitlines()[0]
    assert report['tool_version'] == parent['tool_version']
    report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
    flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps',
             '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-GATOMIC_C=32', '-GATOMIC_K=16']
    binary = out / 'obj/sim'
    run(['verilator', '--binary', '--hierarchical', *flags, '-j', '2',
         '-MAKEFLAGS', 'OPT_FAST=-O0 OPT_SLOW=-O0 OPT_GLOBAL=-O0',
         '--top-module', bench.stem, '--Mdir', out / 'obj', '-o', 'sim', control, *sources, bench], 'compile', True)
    generated = sorted(path for path in (out / 'obj').rglob('*') if path.suffix in ('.cpp', '.h', '.mk', '.v', '.vlt'))
    assert any('rk_cmac_fp16_cell' in str(path.relative_to(out / 'obj')) for path in generated), 'No separate cell model generated'
    report['generated_source'] = fingerprint(generated); save()
    result = run([binary, f'+VECTORS={ROOT / "build/rknpu-cmac-array/c32k16/vectors.hex"}', '+COUNT=208'], 'test')
    lines = [line for line in result.splitlines() if line.startswith('PASS ')]
    assert lines == [parent['result']], result
    assert fingerprint(tracked) == report['source']
    verify(parent['source']); verify(parent['artifacts']); verify(vr['source']); verify(vr['artifacts'])
    report.update(status='PASS_HIERARCHICAL_CMAC_NATIVE_ONLY', result=lines[0],
                  artifacts=fingerprint([binary]+[ROOT / step['log'] for step in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'], report['result'])
