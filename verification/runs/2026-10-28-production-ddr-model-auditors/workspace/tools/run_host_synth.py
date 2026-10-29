#!/usr/bin/env python3
"""Focused XC7 mapping of the host endpoint and functional mapped-control test."""
from collections import Counter
import json
import shutil
import subprocess
import sys
import time

from evidence import ROOT, fingerprint, source_revision, timestamp

OUT = ROOT / 'build/yosys_host'
OUT.mkdir(parents=True, exist_ok=True)
report = {'status': 'RUNNING', 'started_utc': timestamp(), 'source_revision': source_revision(),
          'scope': 'Host endpoint XC7 mapping and mapped control with a mock engine. No mapped full-endpoint simulation, board reimplementation, MIG, PCIe, routed timing or hardware validation.',
          'target_family': 'xc7', 'commands': []}


def save():
    (OUT / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


def execute(argv, name, timeout=600):
    log = OUT / f'{name}.log'
    record = {'argv': argv, 'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(record)
    save()
    begin = time.monotonic()
    try:
        with log.open('w') as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        record.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
    except subprocess.TimeoutExpired:
        record['status'] = 'TIMEOUT'
        raise
    finally:
        record['seconds'] = round(time.monotonic() - begin, 3)
        save()
    output = log.read_text()
    record['warnings'] = [line for line in output.splitlines() if 'warning:' in line.lower()]
    save()
    if result.returncode:
        raise RuntimeError(f'{name}: see {log}\n{output[-6000:]}')
    return output


save()
missing = [tool for tool in ('yosys', 'iverilog', 'vvp') if not shutil.which(tool)]
if missing:
    report.update(status='UNAVAILABLE', finished_utc=timestamp(), reason=f'Missing tools: {missing}')
    save()
    print(report['reason'], file=sys.stderr)
    sys.exit(2)
try:
    report['yosys_version'] = execute(['yosys', '-V'], 'yosys_version').strip()
    report['iverilog_version'] = execute(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
    artifacts = []
    for top, names in (
        ('rk_job_control', ['rk_job_control']),
        ('rk_ew_axi', ['rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma',
                       'rk_axi_mem', 'rk_job_control', 'rk_ew_axi']),
    ):
        design, netlist = OUT / f'{top}.json', OUT / f'{top}_netlist.v'
        script = ('read_verilog -sv ' + ' '.join(json.dumps(str(ROOT / 'rtl' / f'{n}.sv')) for n in names) +
                  f'; hierarchy -check -top {top}; proc; opt_clean; check -assert; ' +
                  f'synth_xilinx -family xc7 -top {top} -flatten; check -assert; ' +
                  f'write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}')
        execute(['yosys', '-Q', '-T', '-p', script], top + '_mapping', timeout=1200)
        counts = Counter(c['type'] for c in json.loads(design.read_text())['modules'][top]['cells'].values())
        if any(n.startswith('$') and n != '$scopeinfo' for n in counts):
            raise RuntimeError(f'Unmapped internal cell in {top}')
        report[top + '_cells'] = dict(sorted(counts.items()))
        artifacts.extend((design, netlist))
        save()
    vendor = ROOT / 'tests/vendor/xilinx-unisim'
    report['primitive_models'] = fingerprint(list(vendor.rglob('*.v')) + [vendor / 'LICENSE'])
    report['primitive_models']['upstream_commit'] = '1c8e05fd1e9a79ceb8b996a0996674122eed086f'
    binary = OUT / 'control_netlist.vvp'
    execute(['iverilog', '-g2012', '-Wall', '-s', 'tb_job_control_netlist', '-s', 'glbl',
             '-y', str(vendor / 'verilog/src/unisims'), '-o', str(binary),
             str(vendor / 'verilog/src/glbl.v'), str(OUT / 'rk_job_control_netlist.v'),
             str(ROOT / 'tests/tb_job_control.sv'), str(ROOT / 'tests/tb_job_control_netlist.sv')], 'control_netlist_build')
    output = execute(['vvp', str(binary)], 'control_netlist_simulation')
    if 'PASS job_control ' not in output:
        raise RuntimeError('Mapped control simulation exited without a PASS marker')
    report['mapped_control'] = {'status': 'PASS', 'startup_clock_hold_ns': 200,
                                'scope': 'Default Xilinx global startup; mock engine, no arithmetic or DDR simulation'}
    report['artifacts'] = fingerprint(artifacts + [binary])
    if source_revision()['sha256'] != report['source_revision']['sha256']:
        raise RuntimeError('Source files changed during verification; rerun before accepting results')
    report.update(status='PASS', finished_utc=timestamp())
    save()
    print(output.strip())
    print('PASS host endpoint and control XC7 mapping')
except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as exc:
    report.update(status='FAIL', finished_utc=timestamp(), reason=str(exc))
    save()
    print(str(exc), file=sys.stderr)
    sys.exit(1)
