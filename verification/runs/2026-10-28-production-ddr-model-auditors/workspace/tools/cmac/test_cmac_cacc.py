#!/usr/bin/env python3
"""Run the connected FP16 CMAC/CACC array without changing raw-core tests."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--kernels', type=int, choices=(1, 16), default=1)
a = p.parse_args()
cmac = ROOT / 'build/rknpu-cmac-array/c32k16'
cacc = ROOT / 'build/rknpu-cacc-array/c32k16'
manifests = [json.loads((base / 'vectors_report.json').read_text()) for base in (cmac, cacc)]
def verify(m):
    for name, sha in m['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
for vr in manifests:
    verify(vr['source'])
    verify(vr['artifacts'])
assert manifests[0]['frames'] == manifests[1]['frames']
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / n for n in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'compat/NV_DW_lsd.v',
                               'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v', 'NV_NVDLA_CACC_CALC_fp_48b.v')]
sources += [ROOT / 'rtl/cmac' / n for n in ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv', 'rk_nvdla_cacc.sv',
                                         'rk_cacc_fp16_array.sv', 'rk_cmac_cacc_fp16_array.sv')]
bench = ROOT / 'tests/cmac/tb_cmac_cacc_fp16_array.sv'
tracked = sources + [bench, Path(__file__).resolve()]
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h')]
tracked += [base / name for base in (cmac, cacc) for name in ('vectors.hex', 'vectors_report.json')]
out = ROOT / f'build/rknpu-cmac-cacc-array/c32k{a.kernels}/iverilog-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), kernels=a.kernels, source=fingerprint(tracked), commands=[],
              seed='0x3588cc16', scope='Connected CMAC/CACC internal FP16-to-FP32 pipeline only. No raw command, final FP16 writer, FPGA or RK proof.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'ERROR :' not in text, text[-5000:]
        if name == 'compile':
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
    report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    binary = out / 'sim.vvp'
    run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-s', bench.stem,
         f'-P{bench.stem}.ATOMIC_K={a.kernels}', '-o', binary, *sources, bench], 'compile')
    count = manifests[1]['frames']
    result = run(['vvp', binary, f'+CMAC={cmac / "vectors.hex"}', f'+CACC={cacc / "vectors.hex"}', f'+COUNT={count}'], 'test')
    passes = [line for line in result.splitlines() if line.startswith('PASS ')]
    expected = f'C=32 K={a.kernels} frames={count} outputs={(manifests[1]["streams"]+10)*a.kernels} resets=10 cancels=3'
    assert len(passes) == 1 and expected in passes[0], result
    assert fingerprint(tracked) == report['source']
    for vr in manifests:
        verify(vr['source'])
        verify(vr['artifacts'])
    report.update(status='PASS_CMAC_CACC_NATIVE_ONLY', result=passes[0], artifacts=fingerprint([binary]+[ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['result'])
