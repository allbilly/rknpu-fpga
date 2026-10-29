#!/usr/bin/env python3
"""Independent streaming regression; does not replace arithmetic/reset/X tests."""
import argparse
from collections import Counter
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
p.add_argument('--tool', choices=('iverilog', 'verilator'), default='iverilog')
p.add_argument('--channels', type=int, choices=(8, 32, 64), default=32)
p.add_argument('--kernels', type=int, choices=(1, 8, 16, 32), default=16)
a = p.parse_args()
C, K = a.channels, a.kernels
base = ROOT / 'build/rknpu-cmac-array' / f'c{C}k{K}'
vr = json.loads((base / 'vectors_report.json').read_text())

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

verify(vr['source'])
verify(vr['artifacts'])
assert (vr['channels'], vr['kernels']) == (C, K)
out = base / f'stream-{a.tool}-{time.time_ns()}'
out.mkdir(exist_ok=False)
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / n for n in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v',
                              'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v')]
sources += [ROOT / 'rtl/cmac' / n for n in ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv')]
bench = ROOT / 'tests/cmac/tb_cmac_fp16_stream.sv'
tracked = sources + [bench, Path(__file__).resolve(), base / 'vectors_report.json']
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h')]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), vectors=vr,
              seed='0x35883216', commands=[], channels=C, kernels=K,
              scope='Native RTL stream ownership and arithmetic. Not upstream UTB, FPGA timing, or RK silicon.')

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

def run(argv, name, lint=False):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as f:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=7200)
        log = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'ERROR :' not in log, log[-5000:]
        if lint:
            locations = Counter(re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', log, re.M))
            allowed = {('DECLFILENAME', str(donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v'), '680'),
                       ('WIDTHTRUNC', str(donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v'), '137'),
                       ('WIDTHTRUNC', str(donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v'), '198')}
            assert set(locations) <= allowed, locations
            report['donor_warnings'] = [list(k) + [v] for k, v in sorted(locations.items())]
        elif name == 'compile':
            assert 'warning:' not in log.lower() and 'sorry:' not in log.lower(), log[-3000:]
        step['status'] = 'PASS'
        return log
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic() - start, 3)
        save()

save()
try:
    report['tool_version'] = run([a.tool, '-V' if a.tool == 'iverilog' else '--version'], 'version').splitlines()[0]
    flags = ['-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}']
    if a.tool == 'iverilog':
        binary = out / 'sim.vvp'
        run(['iverilog', '-g2012', *flags, '-s', bench.stem, f'-P{bench.stem}.ATOMIC_C={C}',
             f'-P{bench.stem}.ATOMIC_K={K}', '-o', binary, *sources, bench], 'compile')
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        execute = ['vvp', binary]
    else:
        binary = out / 'obj/sim'
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
        run(['verilator', '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps',
             *flags, f'-GATOMIC_C={C}', f'-GATOMIC_K={K}', '--top-module', bench.stem,
             '--Mdir', out / 'obj', '-o', 'sim', '-j', '2', *sources, bench], 'compile', lint=True)
        execute = [binary]
    log = run([*execute, f'+VECTORS={base / "vectors.hex"}', f'+COUNT={vr["frames"]}'], 'test')
    passes = [line for line in log.splitlines() if line.startswith('PASS ')]
    assert len(passes) == 1 and f'C={C} K={K} frames={vr["frames"]} outputs={vr["outputs"]}' in passes[0], log
    assert fingerprint(tracked) == report['source']
    verify(vr['source'])
    verify(vr['artifacts'])
    report.update(status='PASS_CMAC_STREAM_NATIVE_ONLY', result=passes[0],
                  artifacts=fingerprint([binary] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['result'])
