#!/usr/bin/env python3
"""Map the complete C32/K16 array with a shared C32 synthesis hierarchy.

All sixteen parallel hardware instances remain. The combinational C32 cell
is mapped once as a module, then the mapped instances are flattened. This is
not resource sharing, time multiplexing, or functional/physical signoff.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--native-report', type=Path, required=True)
a = p.parse_args()
parent = json.loads(a.native_report.read_text())
assert parent['status'] == 'PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY'
assert (parent['channels'], parent['kernels']) == (32, 16)
def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
verify(parent['source']); verify(parent['artifacts'])
top = 'rk_cmac_fp16_array'
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / 'NV_DW02_tree.v', donor / 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
           ROOT / 'rtl/cmac/rk_cmac_fp16_cell.sv', ROOT / 'rtl/cmac/rk_cmac_fp16_array.sv']
assert all(str(path.relative_to(ROOT)) in parent['source']['files'] for path in sources)
out = ROOT / f'build/rknpu-cmac-array/c32k16/yosys-hierarchical-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
snapshot = out / 'native_report_snapshot.json'
snapshot.write_text(json.dumps(parent, indent=2) + '\n')
tracked = sources + [Path(__file__).resolve(), snapshot]
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              channels=32, kernels=16, target_family='xc7', intended_part='xc7k480tffg1156-2',
              mapping_mode='Preserve C32 module through mapping, retain sixteen physical instances, flatten mapped primitives afterwards; omit only optional SAT share pass.',
              scope='Full 512-product CMAC primitive mapping and structural checks only. Requires subsequent numerical netlist replay, full-device fit and physical timing/DRC verification. No programming.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def primitive_counts(modules, name):
    counts = Counter()
    for cell in modules[name].get('cells', {}).values():
        kind = cell['type']
        if kind == '$scopeinfo': continue
        if kind in modules and modules[kind].get('cells'):
            counts.update(primitive_counts(modules, kind))
        else:
            assert re.fullmatch(r'LUT[1-6]|LUT6_2|FD[A-Z0-9]+|CARRY4|MUXF[78]|DSP48E1|INV|VCC|GND', kind), kind
            counts[kind] += 1
    return counts
save(); started = time.monotonic()
try:
    report['tool_version'] = subprocess.check_output(['yosys', '-V'], text=True).strip()
    help_text = subprocess.check_output(['yosys', '-Q', '-T', '-p', 'help flatten; help synth_xilinx'], text=True)
    (out / 'tool_help.log').write_text(help_text)
    assert "'keep_hierarchy' attribute set will not be" in help_text
    coarse = re.search(r'\n    coarse:\n(.*?)\n    map_memory:', help_text, re.S)
    assert coarse, 'Unknown installed synth_xilinx stage layout'
    commands = [line.strip() for line in coarse.group(1).splitlines() if line.strip()]
    assert commands == ['techmap -map +/cmp2lut.v -map +/cmp2lcu.v -D LUT_WIDTH=[46]',
                        'alumacc', 'share', 'opt', 'memory -nomap', 'opt_clean'], commands
    unshared = [line.replace('LUT_WIDTH=[46]', 'LUT_WIDTH=6') for line in commands if line != 'share']
    report.update(original_coarse_stage=commands, executed_coarse_stage=unshared)
    hierarchy, partitioned, design, netlist = [out / name for name in ('hierarchy.json', 'mapped_hierarchy.json', 'mapped.json', 'mapped.v')]
    script = 'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' + ' '.join(json.dumps(str(s)) for s in sources)
    script += f'; chparam -set ATOMIC_C 32 -set ATOMIC_K 16 {top}'
    script += f'; hierarchy -check -top {top}'
    # Parameter elaboration recreates modules, so annotate the derived module,
    # not the pre-elaboration template. Fail before synthesis if selection drifts.
    script += '; select -assert-mod-count 1 A:hdlname=rk_cmac_fp16_cell'
    script += '; setattr -mod -set keep_hierarchy 1 A:hdlname=rk_cmac_fp16_cell'
    script += '; select -assert-mod-count 1 A:keep_hierarchy=1'
    script += '; select -assert-count 16 */t:*rk_cmac_fp16_cell*'
    script += f'; proc; opt_clean; check -assert; write_json {json.dumps(str(hierarchy))}'
    flags = f'-family xc7 -top {top} -flatten -noiopad -noclkbuf'
    script += f'; synth_xilinx {flags} -run begin:map_dsp; ' + '; '.join(unshared)
    script += f'; synth_xilinx {flags} -run map_memory:; check -assert; write_json {json.dumps(str(partitioned))}'
    script += '; setattr -mod -unset keep_hierarchy; setattr -unset keep_hierarchy; flatten; check -assert'
    script += f'; write_json {json.dumps(str(design))}; write_verilog -noattr {json.dumps(str(netlist))}'
    (out / 'mapping.ys').write_text(script.replace('; ', ';\n') + '\n')
    argv = ['yosys', '-Q', '-T', '-s', str(out / 'mapping.ys')]
    report['argv'] = argv; save()
    with (out / 'mapping.log').open('w') as log:
        with subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as proc:
            try: code = proc.wait(timeout=14400)
            except BaseException:
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait(); raise
    report['returncode'] = code
    log = (out / 'mapping.log').read_text()
    assert code == 0 and not re.search(r'Executing SHARE pass', log), log[-6000:]
    modules = json.loads(hierarchy.read_text())['modules']
    retained = [m for m in modules.values() if m.get('attributes', {}).get('hdlname') == 'rk_cmac_fp16_cell']
    assert len(retained) == 1 and int(retained[0]['attributes']['keep_hierarchy'], 2) == 1
    def multipliers(name):
        if name == 'NV_NVDLA_CMAC_CORE_MAC_mul': return 1
        return sum(multipliers(c['type']) for c in modules[name].get('cells', {}).values() if c['type'] in modules)
    assert multipliers(top) == 512
    parts = json.loads(partitioned.read_text())['modules']
    kernel_types = [c['type'] for c in parts[top]['cells'].values() if 'rk_cmac_fp16_cell' in c['type']]
    assert len(kernel_types) == 16 and len(set(kernel_types)) == 1, kernel_types
    kernel = parts[kernel_types[0]]
    assert int(kernel['attributes']['keep_hierarchy'], 2) == 1
    expected = primitive_counts(parts, top)
    mapped_modules = json.loads(design.read_text())['modules']; mapped = mapped_modules[top]
    cells = Counter(c['type'] for c in mapped['cells'].values() if c['type'] != '$scopeinfo')
    assert cells == expected == primitive_counts(mapped_modules, top), 'Primitive counts changed during final flatten'
    assert sum(n for t, n in cells.items() if t.startswith('FD')) >= 16*32+35
    assert sum(n for t, n in cells.items() if t.startswith('LUT')) > 0
    for name, width in [('in_ready', 1), ('out_valid', 1), ('out_groups', 16*44), ('out_tag', 35)]:
        bits = mapped['ports'][name]['bits']
        assert len(bits) == width and all(isinstance(bit, int) for bit in bits), (name, bits)
    assert fingerprint(tracked) == report['source']
    verify(parent['source']); verify(parent['artifacts'])
    report.update(status='PASS_PARALLEL_CMAC_XC7_MAPPING_ONLY', instantiated_multipliers=512,
                  mapped_kernel_instances=16, mapped_kernel_types=sorted(set(kernel_types)), cells=dict(cells),
                  lut_count=sum(n for t, n in cells.items() if t.startswith('LUT')),
                  ff_count=sum(n for t, n in cells.items() if t.startswith('FD')), dsp_count=cells['DSP48E1'],
                  artifacts=fingerprint([hierarchy, partitioned, design, netlist, out / 'mapping.log', out / 'mapping.ys', out / 'tool_help.log']))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc)); raise
finally:
    report.update(finished_utc=timestamp(), seconds=round(time.monotonic()-started, 3)); save(); print(out / 'report.json')
print(report['status'], report['cells'])
