#!/usr/bin/env python3
"""Board-image replay for the first conv FPGA profile.

Runs `tb_ypcb_conv_i8_top` (the autonomous self-test that will run at power-up)
in both simulators. This does NOT synthesise, place, route, program or read any
FPGA; it only proves the image's RTL reaches PASS from reset release.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve()
DONOR = ROOT / 'rtl/vendor/nvdla'
TB = ROOT / 'tests/tb_ypcb_conv_simple.sv'
TB_NAME = 'tb_ypcb_conv_i8_top'
DONOR_SOURCES = [
    'compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'NV_DW_lsd.v',
    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
    'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v',
]
RTL = [
    'rtl/cmac/rk_cmac_fp16_cell.sv', 'rtl/cmac/rk_cmac_fp16_array.sv',
    'rtl/cmac/rk_nvdla_cacc.sv', 'rtl/cmac/rk_cacc_fp16_array.sv',
    'rtl/cmac/rk_cmac_cacc_fp16_array.sv', 'rtl/cmac/rk_nvdla_fp32_to_fp16.sv',
    'rtl/cmac/rk_cmac_writer.sv', 'rtl/cmac/rk_cmac_output_nvdla.sv',
    'rtl/cmac/rk_cmac_frame_output.sv', 'rtl/cmac/rk_cmac_rw_arbiter.sv',
    'rtl/cmac/rk_conv_output_atom.sv', 'rtl/cmac/rk_conv_simple_profile.sv',
    'rtl/cmac/rk_conv_3x3_valid_c4_front.sv', 'rtl/cmac/rk_conv_simple_core.sv',
    'rtl/cmac/rk_conv_simple_demo_rom.sv', 'rtl/cmac/rk_conv_simple_self_test.sv',
    'rtl/rk_bram.sv', 'rtl/rk_startup_reset.sv',
    'fpga/ypcb_conv_simple_top.sv',
]
SPEC = ROOT / 'fpga/conv/sources.json'
XDC = ROOT / 'fpga/ypcb_conv_simple.xdc'
GEN = ROOT / 'tools/conv/gen_conv_demo.py'
PASS_LINE = ('PASS YPCB conv image: 64-cycle hold, captured C4 k3x3 OC16 '
             'whole-BO, both LED polarities')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_version(argv: list[str]) -> str:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=30)
    text = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(f'tool version command failed: {argv}: {text}')
    return text.splitlines()[0] if text else 'unknown'


def run(simulator: str, outdir: Path) -> None:
    compiler = shutil.which(simulator)
    runtime = shutil.which('vvp') if simulator == 'iverilog' else None
    if not compiler or (simulator == 'iverilog' and not runtime):
        raise RuntimeError(f'{simulator} and its runtime are required')
    sources = [str(DONOR / name) for name in DONOR_SOURCES] + [str(ROOT / name) for name in RTL]
    if simulator == 'iverilog':
        build = outdir / 'board.vvp'
        argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                '-Irtl', '-Irtl/vendor/nvdla', '-s', TB_NAME, '-o', str(build),
                *sources, str(TB)]
        prefix = [runtime, str(build)]
    else:
        build = outdir / 'obj_dir'
        argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                '-j', '2', '--timescale-override', '1ns/1ps', '-DDESIGNWARE_NOEXIST',
                '-DASSERT_ON', '-Irtl', '-Irtl/vendor/nvdla',
                '--top-module', TB_NAME, '--Mdir', str(build), '-o', 'sim',
                *sources, str(TB)]
        prefix = [str(build / 'sim')]
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=900)
    text = result.stdout + result.stderr
    (outdir / 'compile.log').write_text(text)
    if result.returncode or re.search(r'%Error', text):
        raise RuntimeError(f'{simulator} compile failed: {text[-4000:]}')
    result = subprocess.run(prefix, cwd=ROOT, text=True, capture_output=True,
                            check=False, timeout=900)
    output = result.stdout + result.stderr
    (outdir / 'run.log').write_text(output)
    if result.returncode or PASS_LINE not in output.splitlines():
        raise RuntimeError(f'{simulator} board replay failed: {output[-4000:]}')
    # A negative control must fail with the checker's own code, not a crash.
    for kind, needle, replacement in (
            ('expected', "10'd0: expected_data = 16'hbe93;",
             "10'd0: expected_data = 16'hbe94;"),
            ('input', "8'd16: input_data = 16'h", None)):
        rom = outdir / f'negative-{kind}.sv'
        original = (ROOT / 'rtl/cmac/rk_conv_simple_demo_rom.sv').read_text()
        if needle not in original:
            raise RuntimeError(f'negative control {kind}: ROM pattern changed')
        if kind == 'expected':
            rom.write_text(original.replace(needle, replacement))
        else:
            # Raise lane 0 of pixel 1 above the current maximum contribution.
            import re as _re
            match = _re.search(re.escape(needle) + r'([0-9a-f]{4});', original)
            if match is None:
                raise RuntimeError('negative control input: ROM pattern changed')
            value = f'{int(match.group(1), 16) ^ 0x0001:04x}'
            rom.write_text(original.replace(match.group(0),
                                            needle + value + ';'))
        sources_neg = [s for s in sources if s != str(ROOT / 'rtl/cmac/rk_conv_simple_demo_rom.sv')]
        sources_neg.append(str(rom))
        if simulator == 'iverilog':
            build_neg = outdir / f'negative-{kind}.vvp'
            argv = [compiler, '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON',
                    '-Irtl', '-Irtl/vendor/nvdla', '-s', TB_NAME,
                    '-o', str(build_neg), *sources_neg, str(TB)]
            prefix_neg = [runtime, str(build_neg)]
        else:
            build_neg = outdir / f'obj_dir_{kind}'
            argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-Wno-fatal',
                    '-j', '2', '--timescale-override', '1ns/1ps',
                    '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', '-Irtl',
                    '-Irtl/vendor/nvdla', '--top-module', TB_NAME,
                    '--Mdir', str(build_neg), '-o', 'sim', *sources_neg, str(TB)]
            prefix_neg = [str(build_neg / 'sim')]
        result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                                check=False, timeout=900)
        if result.returncode:
            raise RuntimeError(f'negative {kind} compile failed: {result.stdout[-3000:]}')
        result = subprocess.run(prefix_neg, cwd=ROOT, text=True,
                                capture_output=True, check=False, timeout=900)
        output = result.stdout + result.stderr
        (outdir / f'negative-{kind}.log').write_text(output)
        if 'board conv self-test FAILED code=51' not in output:
            raise RuntimeError(f'negative {kind} did not fail with code 0x51: {output[-3000:]}')
        if PASS_LINE in output.splitlines():
            raise RuntimeError(f'negative {kind} wrongly passed')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator', 'both'),
                        default='both')
    parser.add_argument('--keep-build', action='store_true')
    args = parser.parse_args()
    spec = json.loads(SPEC.read_text())
    if spec['top'] != 'ypcb_conv_simple_top':
        raise SystemExit('conv sources.json top changed')
    result = subprocess.run([sys.executable, str(GEN), '--check'], cwd=ROOT,
                            text=True, capture_output=True, check=False, timeout=120)
    if result.returncode:
        raise SystemExit(f'generated conv ROM is stale: {result.stdout}{result.stderr}')
    paths = ([ROOT / n for n in RTL + [SPEC, XDC, GEN,
              'tests/conv_simple_demo_fixture.json', str(TB.relative_to(ROOT))]] +
             [DONOR / n for n in DONOR_SOURCES])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    simulators = ('iverilog', 'verilator') if args.simulator == 'both' else (args.simulator,)
    try:
        for simulator in simulators:
            outdir = ROOT / 'build/conv-board' / f'{simulator}-{stamp}'
            outdir.mkdir(parents=True, exist_ok=False)
            compiler = shutil.which(simulator)
            report = {
                'status': 'RUNNING',
                'started_utc': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'simulator': simulator, 'python_version': platform.python_version(),
                'source_revision': subprocess.run(
                    ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                    capture_output=True, check=True).stdout.strip(),
                'source_hashes_before': {str(p.relative_to(ROOT)): sha(p) for p in paths},
                'top': spec['top'], 'part': spec['part'],
                'clock_period_ns': spec['clock_period_ns'],
                'scope': ('Autonomous conv board self-test: ROM-loaded frozen '
                          'conv-simple operands and 52-QWORD stream, raw endpoint, '
                          'parameterised spatial front, donor CMAC/CACC arithmetic, '
                          'FP16 output writer, complete output BO check, startup '
                          'reset and LED polarity. Simulation only; no synthesis, '
                          'bitstream or board.'),
                'hardware_accessed': False, 'vivado_executed': False,
                'bitstream_emitted': False, 'negative_controls': [],
            }
            (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                           sort_keys=True) + '\n')
            try:
                report['tool_version'] = tool_version(
                    [compiler, '--version'] if simulator == 'verilator' else [compiler, '-V'])
                run(simulator, outdir)
                report['negative_controls'] = [
                    {'kind': 'expected', 'result': 'REJECTED_WITH_CODE_51'},
                    {'kind': 'input', 'result': 'REJECTED_WITH_CODE_51'}]
                after = {str(p.relative_to(ROOT)): sha(p) for p in paths}
                if after != report['source_hashes_before']:
                    raise RuntimeError('RTL or generated ROM changed during the run')
                report.update(status='PASS', finished_utc=datetime.now(
                    timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    source_hashes_after=after, result=PASS_LINE)
            except Exception as exc:
                report.update(status='FAIL', failure=str(exc),
                              finished_utc=datetime.now(timezone.utc).strftime(
                                  '%Y-%m-%dT%H:%M:%SZ'))
                raise
            finally:
                if not args.keep_build:
                    for leftover in list(outdir.glob('obj_dir*')):
                        if leftover.is_dir():
                            shutil.rmtree(leftover)
                    for leftover in list(outdir.glob('*.vvp')):
                        leftover.unlink(missing_ok=True)
                    report['build_products_pruned'] = True
                (outdir / 'report.json').write_text(json.dumps(report, indent=2,
                                                               sort_keys=True) + '\n')
            print(f'PASS conv board image logic {simulator}: {PASS_LINE}; '
                  f'report={outdir / "report.json"}')
    except Exception as exc:
        print(f'FAIL conv board image logic: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
