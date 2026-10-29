#!/usr/bin/env python3
"""Verify raw-command operand/product paths; not accumulated GEMM or hardware."""
import argparse
import json
import platform
import re
import shutil
import subprocess
import time
from evidence import ROOT, fingerprint, source_revision, timestamp

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--simulator', choices=('verilator', 'iverilog'), required=True)
args = parser.parse_args()
OUT = ROOT / 'build' / ('cmac_' + args.simulator)
OUT.mkdir(parents=True, exist_ok=True)
report = dict(status='RUNNING', started_utc=timestamp(), simulator=args.simulator,
              source_revision=source_revision(), python_version=platform.python_version(),
              commands=[], tests=[], seeds=['0x3588ca03', '0x3588ca04', '0x3588ca05'],
              scope='Read-only raw CMAC command to tagged product pipeline plus leaf/operand regressions. No accumulation, output writes, DMA/host/board integration or RK numerical validation.')
def save():
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name, timeout=1200):
    log = OUT / (name + '.log')
    record = dict(argv=[str(a) for a in argv], log=str(log.relative_to(ROOT)), status='RUNNING')
    report['commands'].append(record)
    save()
    start = time.monotonic()
    try:
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        output = log.read_text()
        warnings = [s for s in output.splitlines() if 'warning' in s.lower() or 'sorry:' in s.lower()]
        record.update(returncode=result.returncode, warnings=warnings,
                      status='PASS' if not result.returncode and not warnings else 'FAIL')
        if result.returncode or warnings:
            raise RuntimeError(f'{name}: {output[-3000:]}')
        return output
    except subprocess.TimeoutExpired:
        record['status'] = 'TIMEOUT'
        raise
    finally:
        record['seconds'] = round(time.monotonic() - start, 3)
        save()

save()
try:
    if not shutil.which(args.simulator) or (args.simulator == 'iverilog' and not shutil.which('vvp')):
        raise FileNotFoundError(f'UNAVAILABLE: {args.simulator} toolchain')
    for name, argv in [('simulator', [args.simulator, '--version' if args.simulator == 'verilator' else '-V']),
                       ('cxx', ['c++', '--version'])]:
        report[name + '_version'] = run(argv, name + '_version').splitlines()[0]
    if args.simulator == 'iverilog':
        report['vvp_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
    inputs = [p for directory in ('cmac_vectors', 'fp16_product_vectors')
              for p in (ROOT / 'build' / directory).rglob('*') if p.is_file()]
    assert inputs
    report['stimuli'] = fingerprint(inputs)
    operand_sources = [ROOT / 'rtl' / (name + '.sv') for name in
                       ('rk_cmac_profile', 'rk_cmac_address', 'rk_cmac_reader', 'rk_cmac_operand_front')]
    product = ROOT / 'rtl/rk_fp16_product.sv'
    benches = [
        ('tb_fp16_product', [product], [f'+VECTORS={ROOT}/build/fp16_product_vectors/vectors.hex']),
        ('tb_cmac_operand_front', operand_sources, [f'+ROOT={ROOT}/build/cmac_vectors']),
        ('tb_cmac_product_front', operand_sources + [product, ROOT / 'rtl/rk_cmac_product_front.sv'],
         [f'+ROOT={ROOT}/build/cmac_vectors'])]
    artifacts = []
    for top, sources, plusargs in benches:
        sources = sources + [ROOT / 'tests' / (top + '.sv')]
        if args.simulator == 'verilator':
            obj = OUT / ('obj_' + top)
            command = ['verilator', '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                       '--top-module', top, '--Mdir', str(obj), '-o', 'sim'] + sources
            binary = obj / 'sim'
            execute = [str(binary)]
        else:
            binary = OUT / (top + '.vvp')
            command = ['iverilog', '-g2012', '-Wall', '-s', top, '-o', str(binary)] + sources
            execute = ['vvp', str(binary)]
        run(command, top + '_build', timeout=600)
        output = run(execute + plusargs, top + '_run')
        passes = [line for line in output.splitlines() if line.startswith('PASS ')]
        assert len(passes) == 1, output
        x = 0 if args.simulator == 'verilator' else 2
        if top == 'tb_fp16_product':
            assert passes == ['PASS exact FP16 product vectors=230400 compared=230433 reset_cases=4 stalls=30466 cycles=278375 seed=3588ca04']
        elif top == 'tb_cmac_operand_front':
            assert passes == [f'PASS raw CMAC operand front good_runs=13 fault_runs={7+x} reset_phases=5 x_runs={x} checked_operands=53297 seed=3588ca03; no numerical GEMM']
        else:
            match = re.fullmatch(r'PASS raw CMAC product front good_runs=(\d+) fault_runs=(\d+) reset_cases=(\d+) x_runs=(\d+) checked_products=(\d+) blocked_cycles=(\d+) seed=3588ca05; no accumulated GEMM', passes[0])
            assert match, passes
            good, faults, resets, unknowns, products, blocked = map(int, match.groups())
            assert (good, faults, resets, unknowns, blocked) == (13, 11+x, 3, x, 80)
            assert products >= 53240, products
        report['tests'].append(dict(name=top, status='PASS', results=passes))
        artifacts.append(binary)
        print(passes[0], flush=True)
    assert source_revision() == report['source_revision'], 'source changed during verification'
    assert fingerprint(inputs) == report['stimuli'], 'stimuli changed during verification'
    artifacts += [ROOT / c['log'] for c in report['commands']]
    report.update(status='PASS_RAW_PRODUCT_PATH_ONLY', finished_utc=timestamp(), artifacts=fingerprint(artifacts))
    save()
except Exception as exc:
    report.update(status='UNAVAILABLE' if isinstance(exc, FileNotFoundError) else 'FAIL',
                  reason=str(exc), finished_utc=timestamp())
    save()
    raise
