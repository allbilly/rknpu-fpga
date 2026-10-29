#!/usr/bin/env python3
"""Source-bound native tests of the parallel K16 CACC bank."""
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
a = p.parse_args()
base = ROOT / 'build/rknpu-cacc-array/c32k16'
vr = json.loads((base / 'vectors_report.json').read_text())
def verify(m):
    for name, sha in m['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
verify(vr['source'])
verify(vr['artifacts'])
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / 'compat/nv_assert_never.v', donor / 'compat/NV_DW_lsd.v', donor / 'NV_NVDLA_CACC_CALC_fp_48b.v',
           ROOT / 'rtl/cmac/rk_nvdla_cacc.sv', ROOT / 'rtl/cmac/rk_cacc_fp16_array.sv']
bench = ROOT / 'tests/cmac/tb_cacc_fp16_array.sv'
tracked = sources + [bench, Path(__file__).resolve(), base / 'vectors_report.json', base / 'vectors.hex']
tracked += [donor / n for n in ('nv_assert_never.vlib', 'assertion_header.h', 'assertion_task.h')]
out = base / f'{a.tool}-{time.time_ns()}'
out.mkdir(exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), vectors=vr, commands=[],
              scope='K16 FP44 to FP48/FP32 accumulation bank only; no CMAC/command integration, FPGA or RK evidence.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
baseline = None
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name, lint=False):
    global baseline
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=7200)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'ERROR :' not in text, text[-5000:]
        if lint:
            locations = Counter(re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M))
            assert all(Path(path).parent == donor for _, path, _ in locations), locations
            if baseline is None:
                baseline = locations
                report['donor_warnings'] = [list(k) + [v] for k, v in sorted(locations.items())]
            else:
                assert locations == baseline, locations
        elif name == 'compile':
            assert 'warning:' not in text.lower() and 'sorry:' not in text.lower(), text[-3000:]
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
    report['tool_version'] = run([a.tool, '-V' if a.tool == 'iverilog' else '--version'], 'version').splitlines()[0]
    defines = ['-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}']
    if a.tool == 'iverilog':
        binary = out / 'sim.vvp'
        run(['iverilog', '-g2012', *defines, '-s', bench.stem, '-o', binary, *sources, bench], 'compile')
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
        execute = ['vvp', binary]
    else:
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps', *defines]
        run(['verilator', '--lint-only', *flags, '--top-module', 'rk_cacc_fp16_array', *sources], 'baseline_lint', True)
        run(['verilator', '--lint-only', *flags, '--top-module', bench.stem, *sources, bench], 'bench_lint', True)
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
        binary = out / 'obj/sim'
        run(['verilator', '--binary', *flags, '-j', '2', '--top-module', bench.stem, '--Mdir', out / 'obj', '-o', 'sim', *sources, bench], 'compile', True)
        execute = [binary]
    result = run(execute + [f'+VECTORS={base / "vectors.hex"}', f'+COUNT={vr["frames"]}'], 'test')
    passes = [line for line in result.splitlines() if line.startswith('PASS ')]
    expected = f'K=16 frames={vr["frames"]} outputs={(vr["streams"]+12)*16} faults={24 if a.tool=="iverilog" else 20} resets=9 cancels=5'
    assert len(passes) == 1 and expected in passes[0], result
    assert fingerprint(tracked) == report['source']
    verify(vr['source'])
    verify(vr['artifacts'])
    report.update(status='PASS_PARALLEL_CACC_NATIVE_ONLY', result=passes[0], artifacts=fingerprint([binary] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['result'])
