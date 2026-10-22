#!/usr/bin/env python3
"""Replay sized-CMAC unit vectors through an XC7 netlist, preserving vendor GSR."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--mapping-report', type=Path, required=True)
p.add_argument('--native-report', type=Path, required=True)
p.add_argument('--suite', choices=('smoke', 'full'), default='smoke')
a = p.parse_args()
mp, np = a.mapping_report.resolve(), a.native_report.resolve()
mr, nr = json.loads(mp.read_text()), json.loads(np.read_text())
assert mr['status'] == 'PASS_PARALLEL_CMAC_XC7_MAPPING_ONLY', mr['status']
assert nr['status'] == 'PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY', nr['status']
C, K = mr['channels'], mr['kernels']
assert (C, K) == (nr['channels'], nr['kernels'])
def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
for report in (mr, nr):
    verify(report['source'])
    verify(report['artifacts'])
vr = nr['vectors']
verify(vr['source'])
verify(vr['artifacts'])
base = ROOT / 'build/rknpu-cmac-array' / f'c{C}k{K}'
out = base / f'mapped-{a.suite}-{time.time_ns()}'
out.mkdir(exist_ok=False)
source_bench = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
text = source_bench.read_text()
def replace(old, new):
    global text
    assert text.count(old) == 1, old
    text = text.replace(old, new)
replace('module tb_cmac_fp16_array #(', 'module tb_cmac_fp16_mapped #(')
replace('rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);',
        'rk_cmac_fp16_array dut(.*); // Actual source-bound mapped dimensions.')
replace('        if(!$value$plusargs("VECTORS=%s",path)',
        '        #200; // Preserve default vendor GSR through 100 ns.\n'
        '        if(!$value$plusargs("VECTORS=%s",path)')
# Only the native X-injection test is excluded: synthesized logic is not an
# electrical X detector. Numeric, hold, tag, reset and drain assertions remain.
replace('`ifndef VERILATOR', '`ifndef MAPPED_NETLIST')
replace('$display("PASS sized FP16 CMAC', '$display("PASS mapped FP16 CMAC')
for declaration in ('in_data', 'in_weight', 'in_data_mask', 'in_weight_mask'):
    replace(declaration + '=0;', declaration + ';')
replace('in_tag=0,out_tag;', 'in_tag,out_tag;')
replace('    initial clk=0;',
        '    initial clk=0;\n'
        '    initial begin #1;in_data=0;in_weight=0;in_data_mask=0;in_weight_mask=0;in_tag=0;end')
bench = out / 'tb_cmac_fp16_mapped.sv'
bench.write_text(text)
rows = (base / 'vectors.hex').read_text().splitlines()
assert len(rows) == vr['frames']
indices = list(range(len(rows)))
if a.suite == 'smoke':
    random_start, masked_start = 16+C, 16+C+128
    indices = list(range(16)) + [16, 16+C//3, 16+C//2, 16+C-1]
    indices += [random_start+i for i in (0, 1, 34, 35, 62, 63, 126, 127)]
    indices += [masked_start+i for i in (0, 7, 23, 31)]
    assert len(indices) == len(set(indices)) == 32
vectors = out / 'vectors.hex'
vectors.write_text(''.join(rows[i] + '\n' for i in indices))
vendor = ROOT / 'tests/vendor/xilinx-unisim'
models = list(vendor.rglob('*.v')) + [vendor / 'LICENSE']
netlist = mp.parent / 'mapped.v'
tracked = [Path(__file__).resolve(), source_bench, bench, vectors, mp, np, netlist]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              mapping=mr, native=nr, primitive_models=fingerprint(models), channels=C, kernels=K,
              suite=a.suite, selected_frame_indices=indices, commands=[],
              exclusions='Only simulation-X injection. All selected arithmetic, held-output, tag, retirement and reset-cancellation assertions retained.',
              scope='Functional XC7 primitive netlist simulation with default vendor GSR and typical model values. No SDF, routed timing, electrical/DRC, FPGA or RK evidence.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
        log = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'warning' not in log.lower() and 'ERROR :' not in log, log[-5000:]
        step['status'] = 'PASS'
        return log
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-start, 3)
        save()
save()
try:
    report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    binary = out / 'sim.vvp'
    run(['iverilog', '-g2012', '-Ttyp', '-DMAPPED_NETLIST', '-s', bench.stem, '-s', 'glbl',
         f'-P{bench.stem}.ATOMIC_C={C}', f'-P{bench.stem}.ATOMIC_K={K}',
         '-y', vendor / 'verilog/src/unisims', '-o', binary,
         vendor / 'verilog/src/glbl.v', netlist, bench], 'compile')
    log = run(['vvp', binary, f'+VECTORS={vectors}', f'+COUNT={len(indices)}'], 'test')
    lines = [line for line in log.splitlines() if line.startswith('PASS ')]
    assert len(lines) == 1 and f'C={C} K={K} frames={len(indices)} checked_outputs={len(indices)*K}' in lines[0], log
    assert f'retired_outputs={(len(indices)-1)*K} reset_canceled={K}' in lines[0] and 'faults=0' in lines[0], lines
    assert fingerprint(tracked) == report['source']
    verify(report['primitive_models'])
    for earlier in (mr, nr):
        verify(earlier['source'])
        verify(earlier['artifacts'])
    verify(vr['source'])
    verify(vr['artifacts'])
    report.update(status='PASS_CMAC_MAPPED_'+a.suite.upper()+'_ONLY', result=lines[0],
                  artifacts=fingerprint([binary] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'], report['result'])
