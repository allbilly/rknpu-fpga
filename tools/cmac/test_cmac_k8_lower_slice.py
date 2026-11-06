#!/usr/bin/env python3
"""Prove C32/K8 arithmetic lower-slice equality against the C32/K16 corpus.

Two independent checks use the unchanged 208-frame C32/K16 goldens:

1. The parallel CMAC array is instantiated with ATOMIC_K=8 and compared
   against the lower eight kernel groups of every K16 CMAC frame.
2. The selected framework CMAC/CACC pipeline is instantiated with ATOMIC_K=8
   and compared against the lower eight final FP32 values of every K16 stream.

K16 remains the reference profile; this script does not exercise the raw
command front-end, the OC16/OC8 frame writer, DMA framing, layout packing,
FPGA, board or RK silicon.
"""
import argparse
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

cmac16 = ROOT / 'build/rknpu-cmac-array/c32k16'
cmac8 = ROOT / 'build/rknpu-cmac-array/c32k8-lower-slice'
cacc16 = ROOT / 'build/rknpu-cacc-array/c32k16'
reports = [json.loads((base / 'vectors_report.json').read_text())
           for base in (cmac16, cmac8, cacc16)]


def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name


for manifest in reports:
    verify(manifest['source'])
    verify(manifest['artifacts'])
assert (reports[0]['channels'], reports[0]['kernels'], reports[0]['frames']) == (32, 16, 208)
assert (reports[1]['channels'], reports[1]['kernels'], reports[1]['frames'],
        reports[1]['outputs'], reports[1]['source_kernels']) == (32, 8, 208, 1664, 16)
assert (reports[2]['channels'], reports[2]['kernels'], reports[2]['frames']) == (32, 16, 208)

donor = ROOT / 'rtl/vendor/nvdla'
compat = [donor / n for n in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v')]
donor_array = compat + [donor / n for n in ('NV_DW_lsd.v', 'NV_DW02_tree.v',
                                            'NV_NVDLA_CMAC_CORE_MAC_mul.v')]
cmac_sources = donor_array + [ROOT / 'rtl/cmac' / n for n in
                              ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv')]
cacc_sources = donor_array + [donor / 'NV_NVDLA_CACC_CALC_fp_48b.v']
cacc_sources += [ROOT / 'rtl/ddr/framework' / n for n in
                 ('rk_cmac_cacc_fp16_array.sv', 'rk_cmac_fp16_array_dsp_prefix_pipe.sv',
                  'rk_cmac_fp16_shared_data.sv', 'rk_cmac_fp16_cell_dsp_prefix_pipe.sv')]
cacc_sources += [ROOT / 'rtl/cmac/experimental' / n for n in
                 ('rk_cmac_fp16_rows.sv', 'rk_cmac_fp16_discarded_carry.sv',
                  'rk_cmac_fp16_lane_dsp_prefix.sv')]
cacc_sources += [ROOT / 'rtl/cmac' / n for n in ('rk_nvdla_cacc.sv', 'rk_cacc_fp16_array.sv')]
cmac_bench = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
cacc_bench = ROOT / 'tests/cmac/tb_cmac_cacc_fp16_array.sv'
tracked = (cmac_sources + cacc_sources + [cmac_bench, cacc_bench, Path(__file__).resolve(),
           ROOT / 'tools/cmac/gen_cmac_array_vectors_k8.py'])
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib',
                                'assertion_header.h', 'assertion_task.h')]
tracked += [base / name for base in (cmac16, cmac8, cacc16)
            for name in ('vectors.hex', 'vectors_report.json')]
out = ROOT / f'build/rknpu-cmac-k8-lower-slice/{a.tool}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), tool=a.tool, source=fingerprint(tracked),
              commands=[], results=[], frames=208, kernels=8, parallel_products=256,
              lower_slice_bits=8 * 32, seed='0x3588cc16',
              scope='Test-only arithmetic lower-slice equality against the unchanged C32/K16 208-frame CMAC/CACC corpus. No raw command, frame writer, DMA, backend packing, FPGA, board or RK claim.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


def run(argv, name, lint=False):
    step = dict(argv=list(map(str, argv)), status='RUNNING',
                log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=14400)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0, text[-6000:]
        assert '%Error' not in text and 'ERROR :' not in text, text[-6000:]
        if lint:
            warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
            step['warning_count'] = len(warnings)
            step['warning_locations'] = sorted(set(path for _, path, _ in warnings))
        else:
            assert not re.search(r'warning:|sorry:', text, re.I), text[-6000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic() - started, 3)
        save()


def compile_and_run(label, sources, bench, params, execute_args, expected):
    binary = out / f'{label}.sim'
    if a.tool == 'iverilog':
        run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
             '-s', bench.stem, *[f'-P{bench.stem}.{name}={value}' for name, value in params.items()],
             '-o', binary, *sources, bench], f'{label}_compile')
        text = run(['vvp', str(binary), *execute_args], f'{label}_test')
        runtime = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    else:
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal',
                 '--timescale-override', '1ns/1ps', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                 f'-I{donor}', *[f'-G{name}={value}' for name, value in params.items()]]
        run(['verilator', '--binary', *flags, '-j', '2', '--top-module', bench.stem,
             '--Mdir', out / f'{label}_obj', '-o', 'sim', *sources, bench],
            f'{label}_compile', lint=True)
        text = run([str(out / f'{label}_obj' / 'sim'), *execute_args], f'{label}_test')
        runtime = 'n/a'
    lines = [line for line in text.splitlines() if line.startswith('PASS ')]
    assert lines == [expected], text[-6000:]
    report['results'].append(dict(test=label, status='PASS', result=lines[0]))
    save()
    return runtime


save()
try:
    version = run([a.tool, '--version' if a.tool == 'verilator' else '-V'], 'version')
    report['tool_version'] = version.splitlines()[0]
    runtime_version = compile_and_run(
        'cmac_k8', cmac_sources, cmac_bench, {'ATOMIC_C': 32, 'ATOMIC_K': 8},
        [f'+VECTORS={cmac8 / "vectors.hex"}', '+COUNT=208'],
        'PASS sized FP16 CMAC C=32 K=8 frames=208 checked_outputs=1664 '
        f'retired_outputs=1656 reset_canceled=8 held_cycles=520 faults={int(a.tool == "iverilog")}')
    report['runtime_version'] = runtime_version
    runtime_version = compile_and_run(
        'cacc_k8', cacc_sources, cacc_bench, {'ATOMIC_K': 8},
        [f'+CMAC={cmac16 / "vectors.hex"}', f'+CACC={cacc16 / "vectors.hex"}', '+COUNT=208'],
        'PASS CMAC CACC FP16 pipeline C=32 K=8 frames=208 outputs=200 resets=10 '
        'cancels=3 held=110 seed=3588cc16')
    assert runtime_version == report['runtime_version'], 'simulator runtime changed during run'
    assert fingerprint(tracked) == report['source']
    for manifest in reports:
        verify(manifest['source'])
        verify(manifest['artifacts'])
    report.update(status='PASS_K8_ARITHMETIC_LOWER_SLICE_ONLY',
                  exact_lower_slice_equality=True,
                  artifacts=fingerprint([ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'])
for result in report['results']:
    print(result['result'])
