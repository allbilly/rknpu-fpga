#!/usr/bin/env python3
"""Execute the same RTL tests with Verilator or four-state Icarus Verilog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from evidence import ROOT, fingerprint, source_revision, timestamp

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--simulator', choices=('verilator', 'iverilog'), default='verilator')
args = parser.parse_args()
OUT = ROOT / 'build' / ('rtl' if args.simulator == 'verilator' else 'iverilog')
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / 'report.json'
report = {'status': 'RUNNING', 'started_utc': timestamp(), 'simulator': args.simulator,
          'scope': 'RTL simulation only; not timing closure, FPGA or RK3588 validation',
          'source_revision': source_revision(), 'tests': [], 'commands': [],
          'seeds': {'vectors': '0x3588', 'alu_backpressure': '0x12345678',
                    'memory_backpressure': '0x35881234', 'axi_backpressure': '0x3588a512',
                    'host_axi_backpressure': '0x3588c510', 'cmac_address_backpressure': '0x3588ca01'},
          'python_version': platform.python_version(),
          'warnings_policy': 'Verilator -Wall warnings are fatal. All tool output is logged.'}


def save():
    REPORT.write_text(json.dumps(report, indent=2) + '\n')


def execute(command: list[str], name: str, timeout: int = 180) -> str:
    log = OUT / f'{name}.log'
    record = {'argv': command, 'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(record)
    save()
    start = time.monotonic()
    try:
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout, check=False)
        record.update(returncode=result.returncode,
                      status='PASS' if result.returncode == 0 else 'FAIL')
    except subprocess.TimeoutExpired:
        record['status'] = 'TIMEOUT'
        raise
    finally:
        record['seconds'] = round(time.monotonic() - start, 3)
        save()
    output = log.read_text()
    record['warnings'] = [line for line in output.splitlines()
                          if line.startswith('%Warning') or 'warning:' in line.lower()]
    if result.returncode:
        print(output[-12000:], file=sys.stderr)
        raise RuntimeError(f'{name}: command failed ({result.returncode}); see {log}')
    return output


def build(top: str, files: list[str]) -> list[str]:
    sources = [str(ROOT / f) for f in files] + [str(ROOT / 'tests' / f'{top}.sv')]
    if args.simulator == 'verilator':
        obj = OUT / ('obj_' + top)
        obj.mkdir(exist_ok=True)
        command = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                   '--top-module', top, '--Mdir', str(obj), '-o', 'sim'] + sources
        executable = [str(obj / 'sim')]
    else:
        binary = OUT / f'{top}.vvp'
        command = [compiler, '-g2012', '-Wall', '-s', top, '-o', str(binary)] + sources
        executable = [shutil.which('vvp'), str(binary)]
    execute(command, f'{top}_build', timeout=600)
    return executable


def run(name: str, command: list[str], timeout: int = 180):
    output = execute(command, name, timeout=timeout)
    passes = [line for line in output.splitlines() if line.startswith('PASS ')]
    if not passes:
        raise RuntimeError(f'{name}: exited without a PASS marker')
    report['tests'].append({'name': name, 'status': 'PASS', 'results': passes})
    print('\n'.join(passes), flush=True)
    save()


save()
compiler = shutil.which(args.simulator)
if not compiler or (args.simulator == 'iverilog' and not shutil.which('vvp')):
    report.update(status='UNAVAILABLE', finished_utc=timestamp(), reason=f'{args.simulator} toolchain is not installed')
    save()
    print(report['reason'], file=sys.stderr)
    sys.exit(2)

try:
    version_args = ['--version'] if args.simulator == 'verilator' else ['-V']
    report['tool_version'] = execute([compiler] + version_args, 'version').splitlines()[0]
    report['cxx_version'] = subprocess.check_output(['c++', '--version'], text=True).splitlines()[0]
    def stimuli():
        return fingerprint([p for d in ('vectors', 'dma_vectors')
                            for p in (ROOT / 'build' / d).rglob('*') if p.is_file()])
    report['stimuli'] = stimuli()
    core = [f'rtl/{name}.sv' for name in ('rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_core')]
    demo = core + ['rtl/rk_bram.sv', 'rtl/rk_demo_rom.sv', 'rtl/rk_ew_demo.sv']
    dma_demo = core[:-1] + ['rtl/rk_ew_dma.sv', 'rtl/rk_bram.sv', 'rtl/rk_demo_memory.sv',
                            'rtl/rk_dma_demo_rom.sv', 'rtl/rk_ew_dma_demo.sv']
    alu = build('tb_fp16', ['rtl/rk_fp16_alu.sv'])
    count = int((ROOT / 'build/vectors/alu_count.txt').read_text())
    run('alu', alu + [f'+VECTORS={ROOT}/build/vectors/alu.hex', f'+COUNT={count}'])
    report['alu_vectors'] = count
    # This address-only unit is not connected to the raw-command execution path.
    # Its measured Icarus run exceeds the default 180-second process allowance;
    # the HDL's 10 ms timeout and every existing test's timeout are unchanged.
    run('cmac_address', build('tb_cmac_address', ['rtl/rk_cmac_address.sv']), timeout=600)
    cmac_rejections = 22 if args.simulator == 'verilator' else 24
    expected_cmac = f'PASS CMAC address-only leaf: 375895 transfers, 11 complete walks, {cmac_rejections} rejected configs; seed=3588ca01'
    if report['tests'][-1]['results'] != [expected_cmac]:
        raise RuntimeError('CMAC address coverage totals do not match the declared contract')
    report['cmac_address_scope'] = {'transfers': 375895, 'complete_walks': 11,
                                    'rejected_configs': cmac_rejections,
                                    'connected_to_execution_path': False,
                                    'scope': 'Packed address/tag sequencing only, no raw-command acceptance, arithmetic or hardware execution'}
    ew = build('tb_ew', core)
    cases = json.loads((ROOT / 'build/vectors/cases.json').read_text())
    for case in cases:
        run(case['name'], ew + [f"+CASE={ROOT}/build/vectors/{case['name']}",
            f"+NCMD={case['ncmd']}", f"+ECODE={case['error']}", f"+NDONE={case['done']}",
            f"+BUS_ERROR_AT={case['bus_error_at']}", f"+DROP={case['drop']}",
            f"+STALL_REQUEST={case['stall_request']}", f"+NTRANS={case['transactions']}", f"+NCHECKS={case['checks']}"])
    report['engine_scenarios'] = len(cases)
    dma = build('tb_dma', core[:-1] + ['rtl/rk_ew_dma.sv'])
    dma_cases = json.loads((ROOT / 'build/dma_vectors/cases.json').read_text())
    for case in dma_cases:
        run(case['name'], dma + [f"+CASE={ROOT}/build/dma_vectors/{case['name']}",
            f"+OUTPUT={OUT}/{case['name']}_observed.hex",
            f"+START={case['address']:08x}", f"+AMOUNT={case['amount']}", f"+ECODE={case['error']}",
            f"+NJOBS={case['jobs']}", f"+NTASKS={case['tasks']}", f"+REPEATS={case['repeats']}",
            f"+BUS_ERROR_AT={case.get('bus_error_at', 0)}", f"+DROP_AT={case.get('drop_at', 0)}",
            f"+RESET_AT={case.get('reset_at', 0)}", f"+FAULT_BEFORE_RESTART={case.get('fault_before_restart', 0)}",
            f"+STALL_AT={case.get('stall_at', 0)}", f"+NTRANS={case['transactions']}", f"+NCHECKS={case['checks']}"])
    report['dma_scenarios'] = len(dma_cases)
    report['production_dma_captures'] = sum(c['production_capture'] for c in dma_cases)
    report['dma_test_parameters'] = {'TIMEOUT_CYCLES': 128, 'MAX_TASKS': 4}
    report['dma_observed_memory'] = fingerprint([OUT/f"{c['name']}_observed.hex" for c in dma_cases])
    axi = build('tb_axi_mem', core[:-1] + ['rtl/rk_ew_dma.sv', 'rtl/rk_axi_mem.sv'])
    run('axi_protocol', axi)
    axi_cases = [c for c in dma_cases if c['production_capture']]
    for case in axi_cases:
        run('axi_' + case['name'], axi + [f"+CASE={ROOT}/build/dma_vectors/{case['name']}",
            f"+OUTPUT={OUT}/axi_{case['name']}_observed.hex",
            f"+START={case['address']:08x}", f"+AMOUNT={case['amount']}",
            f"+NTASKS={case['tasks']}", f"+NTRANS={case['transactions']}", f"+NCHECKS={case['checks']}"])
    sub = next(c for c in axi_cases if c['name'] == 'capture_sub_9')
    for fault in range(1, 7):
        run(f'axi_dma_fault_{fault}', axi + [f"+CASE={ROOT}/build/dma_vectors/{sub['name']}",
            f"+OUTPUT={OUT}/axi_fault_unused.hex", f"+START={sub['address']:08x}",
            f"+AMOUNT={sub['amount']}", f"+NTASKS={sub['tasks']}",
            f"+NTRANS={sub['transactions']}", f"+NCHECKS={sub['checks']}", f'+FAULT={fault}'])
    report['axi_observed_memory'] = fingerprint([OUT/f"axi_{c['name']}_observed.hex" for c in axi_cases])
    report['axi_scope'] = {'data_bits': 512, 'address_bits': 31, 'id_bits': 4,
                           'production_captures': len(axi_cases), 'dma_fault_cases': 6,
                           'slave': 'Independent behavioral RAM, not Xilinx MIG or physical DDR'}
    run('job_control', build('tb_job_control', ['rtl/rk_job_control.sv']))
    host = build('tb_host_axi', core[:-1] + ['rtl/rk_ew_dma.sv', 'rtl/rk_axi_mem.sv',
                                           'rtl/rk_job_control.sv', 'rtl/rk_ew_axi.sv'])
    host_outputs = []

    def host_case(case, name, fault=0, repeats=1):
        observed = OUT / f'{name}_observed.hex'
        run(name, host + [f"+CASE={ROOT}/build/dma_vectors/{case['name']}", f'+OUTPUT={observed}',
            f"+START={case['address']:08x}", f"+AMOUNT={case['amount']}",
            f"+NTASKS={case['tasks']}", f"+NTRANS={case['transactions']}", f"+NCHECKS={case['checks']}", f'+FAULT={fault}', f'+REPEATS={repeats}'])
        if fault in (0, 9):
            host_outputs.append(observed)

    for case in axi_cases:
        host_case(case, 'host_' + case['name'])
    for fault in (*range(1, 9), 10):
        host_case(sub, f'host_fault_{fault}', fault=fault)
    host_case(sub, 'host_reset_partial_write', fault=9)
    host_case(sub, 'host_repeat_sub_9', repeats=2)
    report['host_observed_memory'] = fingerprint(host_outputs)
    report['host_scope'] = {'control': 'Original FPGA AXI-Lite transport ABI v1.0, not Rockchip MMIO or a PCIe BAR',
                            'production_captures': len(axi_cases), 'negative_cases': 9,
                            'reset_after_partial_second_task': True, 'repeated_jobs_without_memory_reload': 2,
                            'slave': 'Behavioral AXI RAM; no MIG, PCIe, CDC or physical FPGA'}
    for name, top, sources in [('demo', 'tb_demo', demo), ('bram', 'tb_bram', ['rtl/rk_bram.sv']),
                               ('demo_fault', 'tb_demo_fault', demo),
                               ('dma_demo', 'tb_dma_demo', dma_demo),
                               ('demo_memory', 'tb_demo_memory', ['rtl/rk_bram.sv', 'rtl/rk_demo_memory.sv']),
                               ('ypcb', 'tb_ypcb', dma_demo + ['fpga/ypcb_top.sv'])]:
        run(name, build(top, sources))
    if source_revision()['sha256'] != report['source_revision']['sha256']:
        raise RuntimeError('Source files changed during the run; rerun before accepting results')
    if stimuli() != report['stimuli']:
        raise RuntimeError('Stimulus files changed during the run; rerun before accepting results')
    report.update(status='PASS', finished_utc=timestamp())
    save()
except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
    report.update(status='FAIL', finished_utc=timestamp(), reason=str(exc))
    save()
    print(str(exc), file=sys.stderr)
    sys.exit(1)
