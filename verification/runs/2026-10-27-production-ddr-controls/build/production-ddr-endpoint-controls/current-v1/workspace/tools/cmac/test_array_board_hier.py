#!/usr/bin/env python3
"""Replay unchanged board/reset benches with the verified CMAC RTL library.

This is additional two-state evidence. Mode 7 requires four-state simulation;
the full Icarus board gate in vivado_array.py is deliberately unchanged.
"""
import argparse
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
p.add_argument('--board-report', type=Path, required=True)
p.add_argument('--cmac-report', type=Path, required=True)
p.add_argument('--donor-report', type=Path, action='append', required=True)
a = p.parse_args()
board = json.loads(a.board_report.read_text())
cmac = json.loads(a.cmac_report.read_text())
baselines = [json.loads(path.read_text()) for path in a.donor_report]
assert board['status'] == 'PASS_RAW_ARRAY_BOARD_SMOKE_RTL_ONLY'
assert {t['mode'] for t in board['tests']} == {0, 1, 8}
assert cmac['status'] == 'PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY'
assert (cmac['channels'], cmac['kernels'], cmac['parallel_products']) == (32, 16, 512)
assert {r['status'] for r in baselines} == {'PASS_PARALLEL_CACC_NATIVE_ONLY', 'PASS_OC16_FRAME_OUTPUT_NATIVE_ONLY'}

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

for parent in (board, cmac, *baselines):
    assert all(c['status'] == 'PASS' for c in parent['commands'])
    verify(parent['source']); verify(parent['artifacts'])
donor = ROOT / 'rtl/vendor/nvdla'
allowed = set()
for step in cmac['commands']:
    for code, name, line in step.get('warning_locations', []):
        if Path(name).parent == donor:
            allowed.add((code, name, line))
for parent in baselines:
    assert parent['tool_version'] == cmac['tool_version']
    for code, name, line, *count in parent['donor_warnings']:
        assert Path(name).parent == donor
        allowed.add((code, name, line))
spec = json.loads((ROOT / 'fpga/cmac/array_sources.json').read_text())
sources = [ROOT / name for name in spec['simulation_helpers'] + spec['synthesis']]
bench = ROOT / spec['bench']
# Same intentional reset arrangement documented for the earlier board top:
# asynchronous ownership/scoreboard reset, synchronous BRAM transaction enables.
# Never suppress this warning class globally or reset the RAM data to silence it.
reset_warning = ('SYNCASYNCNET', str(ROOT / 'fpga/cmac/ypcb_cmac_array_top.sv'), '9')
assert (ROOT / 'fpga/cmac/ypcb_cmac_array_top.sv').read_text().splitlines()[8].strip() == '(* ASYNC_REG="TRUE" *) reg reset_n;'
libdir = a.cmac_report.resolve().parent / 'cell'
block = 'rk_cmac_fp16_cell_b'
wrapper = libdir / (block + '.sv')
library = libdir / ('lib' + block + '.a')
params = ROOT / 'tools/cmac/empty_hier_parameters.v'
for path in (wrapper, library):
    assert str(path.relative_to(ROOT)) in cmac['artifacts']['files']
assert str(params.relative_to(ROOT)) in cmac['source']['files']
for path in sources + [bench]:
    assert str(path.relative_to(ROOT)) in board['source']['files']
out = ROOT / f'build/rknpu-array-board/two-state-hierarchical-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
snapshots = []
for name, parent in [('board', board), ('cmac', cmac)] + [(f'donor{i}', r) for i, r in enumerate(baselines)]:
    path = out / (name + '_report_snapshot.json')
    path.write_text(json.dumps(parent, indent=2) + '\n'); snapshots.append(path)
tracked = [ROOT / name for name in board['source']['files']] + [wrapper, library, params, Path(__file__).resolve()] + snapshots
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(path.read_bytes())
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked),
              commands=[], tests=[], seed=board['seed'], suite='two-state-eight-modes',
              four_state_mode_not_run=7, approved_donor_warnings=[list(x) for x in sorted(allowed)],
              reviewed_reset_warning=list(reset_warning),
              reset_warning_reason='Synchronized reset clears transaction state asynchronously and gates clocked BRAM enables; RAM data is not reset. Off-edge assertion and three-edge release checks remain unchanged.',
              scope='Unchanged K65 board bench, modes 0..6 and 8, verified RTL CMAC library. Mode 7 remains Icarus-only. Not physical FPGA, RK silicon or a substitute for the full Icarus Vivado prerequisite.')

def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

def run(argv, name, lint=False):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step); save(); start = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            with subprocess.Popen(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                try:
                    code = proc.wait(timeout=14400)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait(); raise
        text = (ROOT / step['log']).read_text(); step['returncode'] = code
        assert code == 0 and 'ERROR :' not in text, text[-6000:]
        warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
        assert len(warnings) == len(re.findall(r'^%Warning-', text, re.M)), 'Unparsed warning'
        unexpected = [w for w in warnings if not (lint and (w in allowed or w == reset_warning))]
        assert not unexpected, unexpected
        if lint: assert warnings.count(reset_warning) == 1, 'Reset diagnostic changed'
        assert not re.search(r'%Error|warning:|sorry:', text, re.I), text[-6000:]
        step.update(status='PASS', warning_locations=[list(w) for w in warnings]); return text
    except Exception:
        step['status'] = 'FAIL'; raise
    finally:
        step['seconds'] = round(time.monotonic() - start, 3); save()

save()
try:
    run([sys.executable, ROOT / 'tools/cmac/gen_array_board.py', '--check'], 'rom_check')
    report['tool_version'] = run(['verilator', '--version'], 'version').splitlines()[0]
    report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
    assert report['tool_version'] == cmac['tool_version'] and report['cxx_version'] == cmac['cxx_version']
    obj = out / 'obj'; obj.mkdir()
    (obj / f'V{bench.stem}_hier.mk').write_text('# Verified library linked by VM_USER_LDLIBS.\nVM_HIER_LIBS := ' + str(library) + '\n')
    run(['verilator', '--cc', '--main', '--exe', '--timing', '--assert', '-Wall', '-Wno-fatal',
         '--timescale-override', '1ns/1ps', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
         '--Mdir', obj, '--top-module', bench.stem, '-o', 'sim',
         '--hierarchical-block', 'rk_cmac_fp16_cell,' + block, '--hierarchical-params-file', params,
         '-LDFLAGS', library, wrapper, *sources, bench], 'generate', True)
    top_cpp = list(obj.glob(f'V{bench.stem}*.cpp')); called = set()
    for path in top_cpp:
        text = path.read_text()
        for operation in ('create', 'combo_update', 'seq_update'):
            if re.search(r'\b' + block + '_protectlib_' + operation + r'\s*\(', text): called.add(operation)
    assert called == {'create', 'combo_update', 'seq_update'}, 'Missing actual library calls'
    assert not any('NV_NVDLA_CMAC_CORE_MAC_mul' in path.name for path in top_cpp)
    report['library_operations'] = sorted(called); save()
    run(['make', '-C', obj, '-f', f'V{bench.stem}.mk', '-j', '2', 'OPT_FAST=-O0', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O0'], 'compile')
    for mode in (0, 1, 2, 3, 4, 5, 6, 8):
        text = run([obj / 'sim', f'+MODE={mode}'], f'mode{mode}')
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert len(lines) == 1, text
        match = re.fullmatch(r'PASS C32 K16 BRAM board RTL mode=(\d+) success=(\d+) resets=(\d+) faults=(\d+) init=(\d+) check=(\d+) cmd_reads=(\d+) operand_reads=(\d+) writes=(\d+) acks=(\d+) cycles=(\d+); no physical FPGA test', lines[0])
        assert match, text
        got_mode, successes, resets, faults, init, checked, commands, reads, writes, acks, cycles = map(int, match.groups())
        good = mode in (0, 3, 4, 5, 6)
        assert (got_mode, successes, resets, faults) == (mode, 2 if mode == 6 else int(good), int(mode in (3, 4, 5, 6)), int(not good))
        assert init == 4096 and 0 < cycles < 1048576
        if good: assert (checked, commands, reads, writes, acks) == (4096, 196, 6528, 64, 64), text
        elif mode == 1: assert (checked, commands, reads, writes, acks) == (0, 1, 0, 0, 0), text
        elif mode == 8: assert checked == writes == acks == 0 and commands == 196 and 20 <= reads <= 21, text
        else: assert (checked, commands, reads, writes, acks) == (1, 196, 6528, 64, 64), text
        report['tests'].append(dict(mode=mode, status='PASS', result=lines[0])); save()
    assert len(report['tests']) == 8 and fingerprint(tracked) == report['source']
    for parent in (board, cmac, *baselines): verify(parent['source']); verify(parent['artifacts'])
    report.update(status='PASS_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_ONLY',
                  artifacts=fingerprint([p for p in obj.rglob('*') if p.is_file()] + [ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc)); raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
