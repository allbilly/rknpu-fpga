#!/usr/bin/env python3
"""Execute unchanged nvdlav1 MAC RTL on the sized-array reference vectors."""
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
p.add_argument('--channels', type=int, choices=(8, 32, 64), default=32)
p.add_argument('--kernels', type=int, choices=(1, 8, 16, 32), default=16)
a = p.parse_args()
C, K = a.channels, a.kernels
base = ROOT / 'build/rknpu-cmac-array' / f'c{C}k{K}'
vr = json.loads((base / 'vectors_report.json').read_text())
assert (vr['channels'], vr['kernels']) == (C, K)
def verify(m):
    for name, digest in m['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
verify(vr['source'])
verify(vr['artifacts'])
hw = Path('/home/fedora/hw')
revision = subprocess.check_output(['git', '-C', hw, 'rev-parse', 'HEAD'], text=True).strip()
assert revision == '8e06b1b9d85aab65b40d43d08eec5ea4681ff715'
names = ['NV_NVDLA_CMAC_CORE_mac.v', 'NV_NVDLA_CMAC_CORE_MAC_exp.v', 'NV_NVDLA_CMAC_CORE_MAC_nan.v']
external = [hw / 'vmod/nvdla/cmac' / n for n in names]
external.append(hw / 'vmod/vlibs/NV_DW_minmax.v')
for path in external:
    committed = subprocess.check_output(['git', '-C', hw, 'show', f'{revision}:{path.relative_to(hw)}'])
    assert path.read_bytes() == committed, path
external_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in external}
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / n for n in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v',
                              'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v')]
bench = ROOT / 'tests/cmac/tb_nvdla_fp16_mac.sv'
tracked = sources + [bench, Path(__file__).resolve(), base / 'vectors_report.json', base / 'vectors.hex']
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h')]
out = base / f'nvdla-rtl-{time.time_ns()}'
out.mkdir(exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              donor_revision=revision, external_source=external_hashes, vectors=vr, commands=[],
              scope='Unmodified native C64 NVDLA MAC RTL, zero-padded sized operands. Not original UTB, RK silicon or FPGA timing.')
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
         f'-P{bench.stem}.ATOMIC_C={C}', f'-P{bench.stem}.ATOMIC_K={K}',
         '-o', binary, *sources, *external, bench], 'compile')
    text = run(['vvp', binary, f'+VECTORS={base / "vectors.hex"}', f'+COUNT={vr["frames"]}'], 'test')
    passes = [line for line in text.splitlines() if line.startswith('PASS ')]
    assert len(passes) == 1 and f'C={C} K={K} frames={vr["frames"]} outputs={vr["outputs"]}' in passes[0], text
    assert fingerprint(tracked) == report['source']
    assert external_hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in external}
    verify(vr['source'])
    verify(vr['artifacts'])
    report.update(status='PASS_ORIGINAL_NVDLA_MAC_RTL_ONLY', result=passes[0],
                  artifacts=fingerprint([binary] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['result'])
