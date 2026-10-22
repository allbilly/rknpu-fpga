#!/usr/bin/env python3
"""XC7 synthesis/inference and mapped-netlist smoke test; not place and route."""
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from evidence import ROOT, fingerprint, source_revision, timestamp

OUT = ROOT / 'build/yosys'
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / 'report.json'
report = {'status': 'RUNNING', 'started_utc': timestamp(), 'source_revision': source_revision(),
          'scope': 'Yosys XC7 mapping and functional Xilinx primitive simulation; no placement, routed timing or timing closure',
          'target_family': 'xc7', 'board_part': 'xc7k480tffg1156-2', 'commands': []}


def save():
    REPORT.write_text(json.dumps(report, indent=2) + '\n')


def execute(args, name, timeout=600):
    log = OUT / f'{name}.log'
    step = {'argv': args, 'log': str(log.relative_to(ROOT)), 'status': 'RUNNING'}
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with log.open('w') as stream:
            result = subprocess.run(args, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, check=False)
        step.update(returncode=result.returncode, status='PASS' if result.returncode == 0 else 'FAIL')
    except subprocess.TimeoutExpired:
        step['status'] = 'TIMEOUT'
        raise
    finally:
        step['seconds'] = round(time.monotonic() - start, 3)
        save()
    output = log.read_text()
    step['warnings'] = [line for line in output.splitlines() if 'warning:' in line.lower()]
    if result.returncode:
        print(output[-10000:], file=sys.stderr)
        raise RuntimeError(f'{name} failed; full log: {log}')
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
    sources = [ROOT / 'rtl' / f'{name}.sv' for name in
               ('rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma',
                'rk_bram', 'rk_demo_memory', 'rk_dma_demo_rom', 'rk_ew_dma_demo')] + [ROOT / 'fpga/ypcb_top.sv']
    design = OUT / 'ypcb.json'
    netlist = OUT / 'ypcb_netlist.v'
    # Quoting is for the Yosys command parser, never a shell.
    # Remove dead function-local temporaries before synth_xilinx's early check.
    # Check both here and after mapping; no undriven functional net is waived.
    script = ('read_verilog -sv ' + ' '.join(json.dumps(str(p)) for p in sources) +
              '; hierarchy -check -top ypcb_top; proc; opt_clean; check -assert; ' +
              'synth_xilinx -family xc7 -top ypcb_top -flatten; check -assert; ' +
              f'write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}')
    execute(['yosys', '-Q', '-T', '-p', script], 'synthesis', timeout=1200)
    cells = json.loads(design.read_text())['modules']['ypcb_top']['cells']
    counts = Counter(cell['type'] for cell in cells.values())
    report['cells'] = dict(sorted(counts.items()))
    if counts['RAMB36E1'] + counts['RAMB18E1'] == 0:
        raise RuntimeError('No block RAM inferred for the BRAM demo')
    # $scopeinfo stores source hierarchy metadata after flattening. It is not
    # logic and write_verilog omits it. Every other internal cell must map.
    if any(name.startswith('$') and name != '$scopeinfo' for name in counts):
        raise RuntimeError('Unmapped internal cells remain in the XC7 netlist')
    # Yosys cells_sim.v has a port-only RAMB36E1 declaration. Use the real
    # functional models, including global startup, for every mapped primitive.
    vendor = ROOT / 'tests/vendor/xilinx-unisim'
    primitives = vendor / 'verilog/src/unisims'
    report['primitive_models'] = fingerprint(list(vendor.rglob('*.v')) + [vendor / 'LICENSE'])
    report['primitive_models']['upstream_commit'] = '1c8e05fd1e9a79ceb8b996a0996674122eed086f'
    binary = OUT / 'ypcb_netlist.vvp'
    execute(['iverilog', '-g2012', '-s', 'tb_ypcb_netlist', '-s', 'glbl',
             '-y', str(primitives), '-o', str(binary), str(vendor / 'verilog/src/glbl.v'),
             str(netlist), str(ROOT / 'tests/tb_ypcb_netlist.sv')], 'netlist_build')
    # The captured-DMA demo loads/checks 336 halfwords and executes two linked
    # tasks per reset, versus the legacy demo's 24 input and 24 output words.
    # Only the host simulator wall-clock budget changes, not any timing gate.
    output = execute(['vvp', str(binary)], 'netlist_simulation', timeout=1800)
    if 'PASS mapped YPCB' not in output:
        raise RuntimeError('Mapped-netlist simulation exited without passing')
    dma_design = OUT / 'dma.json'
    dma_sources = [ROOT/'rtl'/f'{name}.sv' for name in
                   ('rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_dma')]
    dma_script = ('read_verilog -sv ' + ' '.join(json.dumps(str(p)) for p in dma_sources) +
                  '; hierarchy -check -top rk_ew_dma; proc; opt_clean; check -assert; ' +
                  'synth_xilinx -family xc7 -top rk_ew_dma -flatten; check -assert; ' +
                  f'write_json {json.dumps(str(dma_design))}')
    execute(['yosys', '-Q', '-T', '-p', dma_script], 'dma_synthesis', timeout=1200)
    dma_counts = Counter(cell['type'] for cell in json.loads(dma_design.read_text())['modules']['rk_ew_dma']['cells'].values())
    if any(name.startswith('$') and name != '$scopeinfo' for name in dma_counts):
        raise RuntimeError('Unmapped internal cells remain in standalone DMA XC7 mapping')
    report['dma_cells'] = dict(sorted(dma_counts.items()))
    report['dma_scope'] = 'Standalone rk_ew_dma XC7 mapping plus captured-DMA board functional netlist test; no P&R or physical FPGA test'
    axi_design = OUT / 'axi.json'
    axi_script = (f'read_verilog -sv {json.dumps(str(ROOT / "rtl/rk_axi_mem.sv"))}; ' +
                  'hierarchy -check -top rk_axi_mem; proc; opt_clean; check -assert; ' +
                  'synth_xilinx -family xc7 -top rk_axi_mem -flatten; check -assert; ' +
                  f'write_json {json.dumps(str(axi_design))}')
    execute(['yosys', '-Q', '-T', '-p', axi_script], 'axi_synthesis', timeout=1200)
    axi_counts = Counter(cell['type'] for cell in json.loads(axi_design.read_text())['modules']['rk_axi_mem']['cells'].values())
    if any(name.startswith('$') and name != '$scopeinfo' for name in axi_counts):
        raise RuntimeError('Unmapped internal cells remain in AXI adapter XC7 mapping')
    report['axi_cells'] = dict(sorted(axi_counts.items()))
    report['axi_scope'] = 'Standalone rk_axi_mem XC7 mapping; not integrated MIG/DDR or mapped AXI simulation'
    report['artifacts'] = fingerprint([design, netlist, dma_design, axi_design])
    if source_revision()['sha256'] != report['source_revision']['sha256']:
        raise RuntimeError('Sources changed during synthesis; rerun before accepting results')
    report.update(status='PASS', finished_utc=timestamp())
    save()
    print(output.strip())
    print('PASS XC7 mapping:', json.dumps(report['cells'], sort_keys=True))
    print('PASS standalone DMA XC7 mapping:', json.dumps(report['dma_cells'], sort_keys=True))
    print('PASS standalone AXI adapter XC7 mapping:', json.dumps(report['axi_cells'], sort_keys=True))
except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError) as exc:
    report.update(status='FAIL', finished_utc=timestamp(), reason=str(exc))
    save()
    print(str(exc), file=sys.stderr)
    sys.exit(1)
