#!/usr/bin/env python3
"""Decoder-only unit driver for the runtime conv decoder prototype.

Compiles `tb_runtime_decode_unit.sv` (one small compile) and feeds every
captured command stream to the RTL decoder, comparing the decoded configuration
against the golden model `conv_runtime_model.py`. This is the fast debugging
loop for the decoder; the full old-vs-new equivalence replay is
`run_runtime_equiv.py`.

Launch through the host guard (required):

    BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=60 \
      build/verif/host_guard/safe_run.sh \
      python3 tests/conv/runtime/run_decode_unit.py
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
TB = HERE / 'tb_runtime_decode_unit.sv'
MODEL = HERE / 'conv_runtime_model.py'
OUT_ROOT = ROOT / 'build/runtime-conv-lab/decode-unit'
GUARD = ROOT / 'build/verif/host_guard/safe_run.sh'
DONOR_RTL = ROOT / 'rtl/vendor/nvdla'

sys.path.insert(0, str(HERE))
import conv_runtime_model as model  # noqa: E402

SOURCES = [
    'rtl/cmac/experimental/runtime/rk_conv_runtime_decode.sv',
    'tests/conv/runtime/tb_runtime_decode_unit.sv',
]
DONOR_SOURCES = [
    'compat/nv_assert_never.v',
    'compat/nv_assert_no_x.v',
]

# cfg field names in the DECODE_OK line and their golden-model keys.
FIELDS = {
    'ih': 'input_height', 'iw': 'input_width',
    'oh': 'output_height', 'ow': 'output_width',
    'kh': 'kernel_h', 'kw': 'kernel_w', 'stride': 'stride',
    'dw': 'depthwise', 'ic': 'input_channels',
    'ical': 'input_channel_align', 'pack': 'pack_c2',
    'planes': 'planes', 'oc': 'output_channels',
    'kernels': 'kernels', 'blocks': 'c1_blocks',
    'wmode': 'weight_mode_id', 'align': 'align_c',
    'fp16': 'output_fp16', 'in_base': 'input_base',
    'w_base': 'weight_base', 'out_base': 'output_base',
    'in_bytes': 'input_bytes', 'w_bytes': 'weight_bytes',
    'out_bytes': 'output_bytes', 'taps': 'taps',
    'frame_w': 'frame_weight_halfwords',
    'w_hw': 'weight_halfwords', 'w_lanes': 'weight_lanes',
    'block_stride': 'block_stride', 'total_atoms': 'total_atoms',
    'plane_words': 'plane_words', 'pixel_bytes': 'pixel_bytes',
    'plane_bytes': 'plane_bytes', 'block_bytes': 'block_bytes',
    'chunk_bytes': 'chunk_stride_bytes',
    'block_plane_bytes': 'block_plane_bytes',
    'real_mask': 'real_mask',
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def golden(loaded: dict) -> dict:
    config = loaded['config']
    config = dict(config)
    config['weight_mode_id'] = {'kh_major': 0, 'depthwise_spatial': 1,
                                'chunked': 2}[config['weight_mode']]
    config['planes'] = -(-config['input_channels'] // config['pack_c2'])
    config['block_stride'] = config['output_height'] * config['output_width']
    config['plane_words'] = (config['input_height'] * config['input_width'] *
                             config['pack_c2'])
    config['pixel_bytes'] = config['pack_c2'] * 2
    config['plane_bytes'] = config['plane_words'] * 2
    config['block_bytes'] = config['block_stride'] * 16
    config['chunk_stride_bytes'] = config['weight_lanes'] * config['taps'] * 2
    config['block_plane_bytes'] = ((config['kernels'] // 4) *
                                   (config['block_stride'] * 16))
    config['real_mask'] = ((1 << config['input_channels']) - 1
                           if config['input_channels'] < 32 else 0xffffffff)
    return config


def fixture_hex(directory: Path, loaded: dict) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    commands = loaded['commands']
    (directory / 'commands.hex').write_text(
        ''.join(f'{word:016x}\n' for word in __import__('struct').unpack(
            f'<{len(commands) // 8}Q', commands)))
    return len(commands) // 8


def guarded(command: list[str]) -> list[str]:
    if 'BENCH_MIN_BATTERY' not in os.environ:
        raise RuntimeError(
            'heavy work refused: launch through '
            f'`BENCH_MIN_BATTERY=30 BENCH_CPUS=0-1 BENCH_CPU_QUOTA=60 '
            f'{GUARD} python3 {Path(__file__).relative_to(ROOT)} ...`')
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', default=None)
    args = parser.parse_args(argv)
    cases = args.case or (list(model.CASES) + list(model.BUNDLE_CASES))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outdir = OUT_ROOT / f'iverilog-{stamp}'
    outdir.mkdir(parents=True, exist_ok=True)
    donor = [str(DONOR_RTL / name) for name in DONOR_SOURCES]
    rtl = [str(ROOT / name) for name in SOURCES]
    build = outdir / 'dec_unit.vvp'
    iverilog = shutil.which('iverilog')
    compile_cmd = guarded([
        iverilog, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
        '-Irtl', f'-I{DONOR_RTL}', '-s', 'tb_runtime_decode_unit',
        '-o', str(build), *donor, *rtl])
    result = subprocess.run(compile_cmd, cwd=ROOT, text=True,
                            capture_output=True, check=False, timeout=600)
    compile_text = result.stdout + result.stderr
    (outdir / 'compile.log').write_text(compile_text)
    failures = 0
    report = {'status': 'RUNNING', 'tool': 'iverilog',
              'tool_version': subprocess.run(
                  [iverilog, '-V'], text=True, capture_output=True,
                  check=True).stdout.splitlines()[0],
              'cases': {}, 'hardware_accessed': False}
    if result.returncode or re.search(r'warning:|sorry:', compile_text, re.I):
        report['status'] = 'FAIL'
        report['failure'] = f'compile: {compile_text[-4000:]}'
        failures = len(cases)
    else:
        vvp = shutil.which('vvp')
        for case in cases:
            loaded = (model.load_bundle(case) if case in model.BUNDLE_CASES
                      else model.load_case(case))
            fdir = outdir / 'fixtures' / case
            num_cmd = fixture_hex(fdir, loaded)
            run = subprocess.run(guarded([
                vvp, str(build), f'+FIXTURE={fdir}',
                f'+NUM_CMD={num_cmd}']),
                cwd=ROOT, text=True, capture_output=True, check=False,
                timeout=600)
            text = run.stdout + run.stderr
            (outdir / f'{case}.log').write_text(text)
            ok_match = re.search(r'^DECODE_OK (.*)$', text, re.M)
            err_match = re.search(r'^DECODE_ERROR (.*)$', text, re.M)
            entry = {'status': 'FAIL', 'log': f'{case}.log'}
            if err_match:
                entry['failure'] = err_match.group(1)
            elif not ok_match:
                entry['failure'] = 'no DECODE line'
            else:
                got = {part.split('=')[0]: int(part.split('=')[1])
                       for part in ok_match.group(1).split()}
                want = golden(loaded)
                bad = []
                for key, model_key in FIELDS.items():
                    expected = int(want[model_key])
                    if got.get(key) != expected:
                        bad.append(f'{key}: rtl={got.get(key)} model={expected}')
                if bad:
                    entry['failure'] = '; '.join(bad)
                else:
                    entry['status'] = 'PASS'
            report['cases'][case] = entry
            if entry['status'] != 'PASS':
                failures += 1
                print(f'FAIL {case}: {entry.get("failure", "")}', file=sys.stderr)
            else:
                print(f'PASS {case}: decoder config equals the golden model')
    report['status'] = 'PASS' if failures == 0 else 'FAIL'
    report['source_hashes'] = {name: sha(ROOT / name) for name in SOURCES}
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    (outdir / 'report.json').write_text(
        json.dumps(report, indent=2, sort_keys=True) + '\n')
    if not args.case:
        for name in ('dec_unit.vvp',):
            target = outdir / name
            if target.exists():
                target.unlink()
    print(f'{"PASS" if failures == 0 else "FAIL"} decoder unit: '
          f'{len(cases) - failures}/{len(cases)} cases -> '
          f'{outdir / "report.json"}')
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
