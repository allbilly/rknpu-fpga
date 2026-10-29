#!/usr/bin/env python3
"""Source-bound XC7 primitive mapping of the parallel CMAC internal leaf.

This is area/structure characterization, not functional or physical signoff.
The wide CSC/CACC ports are internal: no fictitious package pins are assigned.
"""
import argparse
from collections import Counter
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
top = 'rk_cmac_fp16_array'
base = ROOT / 'build/rknpu-cmac-array' / f'c{C}k{K}'
base.mkdir(parents=True, exist_ok=True)
out = base / f'yosys-{time.time_ns()}'
out.mkdir(exist_ok=False)
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / 'NV_DW02_tree.v', donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
           ROOT / 'rtl/cmac/rk_cmac_fp16_cell.sv', ROOT / 'rtl/cmac/rk_cmac_fp16_array.sv']
tracked = sources + [Path(__file__).resolve()]
hierarchy = out / 'hierarchy.json'
design = out / 'mapped.json'
netlist = out / 'mapped.v'
script = 'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' + ' '.join(json.dumps(str(s)) for s in sources)
script += f'; chparam -set ATOMIC_C {C} -set ATOMIC_K {K} {top}'
script += f'; hierarchy -check -top {top}; proc; opt_clean; check -assert; write_json {json.dumps(str(hierarchy))}'
script += f'; synth_xilinx -family xc7 -top {top} -flatten -noiopad -noclkbuf; check -assert'
script += f'; write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}'
argv = ['yosys', '-Q', '-T', '-p', script]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), channels=C, kernels=K,
              target_family='xc7', intended_part='xc7k480tffg1156-2', argv=argv,
              scope='Internal parallel CMAC leaf XC7 mapping only. No numerical netlist replay, full-device fit, I/O assignment, P&R, timing, electrical/DRC or RK claim.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
save()
start = time.monotonic()
try:
    report['tool_version'] = subprocess.check_output(['yosys', '-V'], text=True).strip()
    save()
    with (out / 'mapping.log').open('w') as log:
        run = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
    report['returncode'] = run.returncode
    assert run.returncode == 0, (out / 'mapping.log').read_text()[-5000:]
    modules = json.loads(hierarchy.read_text())['modules']
    def multipliers(name):
        if name == 'NV_NVDLA_CMAC_CORE_MAC_mul':
            return 1
        return sum(multipliers(cell['type']) for cell in modules[name].get('cells', {}).values()
                   if cell['type'] in modules)
    count = multipliers(top)
    assert count == C*K, (count, C*K)
    mapped = json.loads(design.read_text())['modules'][top]
    cells = Counter(cell['type'] for cell in mapped['cells'].values())
    assert not any(t.startswith('$') and t != '$scopeinfo' for t in cells), cells
    assert not cells['IBUF'] and not cells['OBUF'] and not cells['BUFG'], cells
    assert sum(n for t, n in cells.items() if t.startswith('FD')) >= K*32+35, cells
    assert sum(n for t, n in cells.items() if t.startswith('LUT')) > 0, cells
    for name, width in [('in_ready', 1), ('out_valid', 1), ('out_groups', K*44), ('out_tag', 35)]:
        bits = mapped['ports'][name]['bits']
        assert len(bits) == width and all(isinstance(b, int) for b in bits), (name, bits)
    assert fingerprint(tracked) == report['source']
    report.update(status='PASS_PARALLEL_CMAC_XC7_MAPPING_ONLY', instantiated_multipliers=count,
                  cells=dict(cells), lut_count=sum(n for t, n in cells.items() if t.startswith('LUT')),
                  ff_count=sum(n for t, n in cells.items() if t.startswith('FD')),
                  dsp_count=cells['DSP48E1'],
                  artifacts=fingerprint([hierarchy, design, netlist, out / 'mapping.log']))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report.update(finished_utc=timestamp(), seconds=round(time.monotonic()-start, 3))
    save()
    print(out / 'report.json')
print(report['status'], report['cells'])
