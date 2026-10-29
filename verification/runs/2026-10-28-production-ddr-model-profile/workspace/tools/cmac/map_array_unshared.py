#!/usr/bin/env python3
"""XC7 mapping of the parallel CMAC without the optional SAT share pass.

Preserves all other synth_xilinx stages and structural gates. This separate
flow does not modify or terminate the ongoing default synthesis experiment.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
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
out = ROOT / f'build/rknpu-cmac-array/c{C}k{K}/yosys-unshared-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / 'NV_DW02_tree.v', donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
           ROOT / 'rtl/cmac/rk_cmac_fp16_cell.sv', ROOT / 'rtl/cmac/rk_cmac_fp16_array.sv']
tracked = sources + [Path(__file__).resolve()]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), channels=C, kernels=K,
              target_family='xc7', intended_part='xc7k480tffg1156-2',
              omitted_optimization='SAT-based share only; no check, constraint, arithmetic or verification removed',
              scope='Full parallel CMAC XC7 mapping/structure characterization, without SAT resource sharing. Not netlist numerical equivalence, full-device fit, P&R, timing, electrical/DRC, FPGA or RK proof.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
save()
started = time.monotonic()
try:
    report['tool_version'] = subprocess.check_output(['yosys', '-V'], text=True).strip()
    help_text = subprocess.check_output(['yosys', '-Q', '-T', '-p', 'help synth_xilinx'], text=True)
    (out / 'synth_xilinx_help.log').write_text(help_text)
    coarse = re.search(r'\n    coarse:\n(.*?)\n    map_memory:', help_text, re.S)
    assert coarse, 'Installed synth_xilinx stage layout is unknown'
    commands = [line.strip() for line in coarse.group(1).splitlines() if line.strip()]
    assert commands == ['techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=[46]',
                        'alumacc', 'share', 'opt', 'memory -nomap', 'opt_clean'], commands
    # Explicitly preserve the installed XC7 coarse stage except its optional
    # resource-sharing optimization. XC7 uses native six-input LUTs.
    unshared = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in commands if line != 'share']
    report['original_coarse_stage'] = commands
    report['executed_coarse_stage'] = unshared
    hierarchy, design, netlist = (out / name for name in ('hierarchy.json', 'mapped.json', 'mapped.v'))
    script = 'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' + ' '.join(json.dumps(str(s)) for s in sources)
    script += f'; chparam -set ATOMIC_C {C} -set ATOMIC_K {K} {top}'
    script += f'; hierarchy -check -top {top}; proc; opt_clean; check -assert; write_json {json.dumps(str(hierarchy))}'
    flags = f'-family xc7 -top {top} -flatten -noiopad -noclkbuf'
    script += f'; synth_xilinx {flags} -run begin:map_dsp; ' + '; '.join(unshared)
    script += f'; synth_xilinx {flags} -run map_memory:; check -assert'
    script += f'; write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}'
    (out / 'mapping.ys').write_text(script.replace('; ', ';\n')+'\n')
    argv = ['yosys', '-Q', '-T', '-s', str(out / 'mapping.ys')]
    report['argv'] = argv; save()
    with (out / 'mapping.log').open('w') as log:
        result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
    report['returncode'] = result.returncode
    assert result.returncode == 0, (out / 'mapping.log').read_text()[-6000:]
    log = (out / 'mapping.log').read_text()
    assert not re.search(r'Executing SHARE pass', log), 'Unexpected SAT share stage executed'
    modules = json.loads(hierarchy.read_text())['modules']
    def multipliers(name):
        if name == 'NV_NVDLA_CMAC_CORE_MAC_mul':
            return 1
        return sum(multipliers(cell['type']) for cell in modules[name].get('cells', {}).values() if cell['type'] in modules)
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
        assert len(bits) == width and all(isinstance(bit, int) for bit in bits), (name, bits)
    assert fingerprint(tracked) == report['source']
    report.update(status='PASS_PARALLEL_CMAC_XC7_MAPPING_ONLY', instantiated_multipliers=count, cells=dict(cells),
                  lut_count=sum(n for t, n in cells.items() if t.startswith('LUT')),
                  ff_count=sum(n for t, n in cells.items() if t.startswith('FD')), dsp_count=cells['DSP48E1'],
                  artifacts=fingerprint([hierarchy, design, netlist, out / 'mapping.log', out / 'mapping.ys', out / 'synth_xilinx_help.log']))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report.update(finished_utc=timestamp(), seconds=round(time.monotonic()-started, 3)); save(); print(out / 'report.json')
print(report['status'], report['cells'])
