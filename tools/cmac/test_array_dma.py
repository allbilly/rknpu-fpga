#!/usr/bin/env python3
"""Fetch unchanged final command BO words through the C32/K16 DMA core."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--suite', choices=('protocol', 'smoke', 'full'), default='smoke')
a = p.parse_args()
base = ROOT / 'build/rknpu-array-core-vectors'
vr = json.loads((base / 'vectors_report.json').read_text())
def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
verify(vr['source']); verify(vr['artifacts'])
donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / name for name in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v', 'compat/NV_DW_lsd.v',
                                    'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v', 'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v')]
sources += [ROOT / 'rtl/cmac' / name for name in ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv', 'rk_nvdla_cacc.sv',
             'rk_cacc_fp16_array.sv', 'rk_cmac_cacc_fp16_array.sv', 'rk_nvdla_fp32_to_fp16.sv', 'rk_cmac_writer.sv',
             'rk_cmac_output_nvdla.sv', 'rk_cmac_frame_output.sv', 'rk_cmac_array_datapath.sv',
             'rk_cmac_array_front.sv', 'rk_cmac_rw_arbiter.sv', 'rk_cmac_array_core.sv', 'rk_cmac_array_dma.sv')]
sources.append(ROOT / 'rtl/rk_cmac_profile.sv')
bench = ROOT / 'tests/cmac/tb_cmac_array_dma.sv'
tracked = sources + [bench, Path(__file__).resolve(), base / 'vectors_report.json']
tracked += [donor / name for name in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib', 'assertion_header.h', 'assertion_task.h')]
out = ROOT / f'build/rknpu-array-dma/{a.suite}-iverilog-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
fault_modes = (1, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 15)
if a.suite == 'protocol':
    tests = [(vr['cases'][3], mode) for mode in fault_modes]
elif a.suite == 'smoke':
    tests = [(vr['cases'][3], mode) for mode in (10, 7, 0, 2)]
else:
    tests = [(case, 0) for case in vr['cases']]
    tests += [(vr['cases'][3], mode) for mode in (*fault_modes, 2, 6, 14)]
report = dict(status='RUNNING', started_utc=timestamp(), suite=a.suite, source=fingerprint(tracked), vectors=vr,
              commands=[], tests=[], seed='0x3588ad16',
              scope='Physical command BO fetch through strict terminal RK words, C32/K16 CMAC/CACC/conversion and acknowledged writes. Synthetic operands and donor-policy goldens, not RK captures, upstream UTB, PCIe/DDR or FPGA validation.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
def run(argv, name):
    step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (name+'.log')).relative_to(ROOT)))
    report['commands'].append(step); save()
    started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=14400)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and 'ERROR :' not in text, text[-6000:]
        assert not re.search(r'warning:|sorry:', text, re.I), text[-6000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic()-started, 3); save()
save()
try:
    report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    binary = out / 'sim.vvp'
    run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-s', bench.stem, '-o', binary, *sources, bench], 'compile')
    for case, mode in tests:
        name = f'{case["name"]}-mode{mode}'
        text = run(['vvp', binary, f'+DIRECTORY={base / case["name"]}', f'+MODE={mode}', f'+ROWS={case["rows"]}',
                    f'+AI={case["ai"]}', f'+AO={case["ao"]}', f'+READS={case["reads"]}', f'+WRITES={case["writes"]}'], name)
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert len(lines) == 1, text
        match = re.fullmatch(r'PASS DMA C32 K16 core mode=(\d+) command_reads=(\d+) command_words=(\d+) reads=(\d+) writes=(\d+) acknowledgments=(\d+) jobs=(\d+) seed=3588ad16', lines[0])
        assert match, text
        actual_mode, command_reads, command_words, reads, writes, acks, jobs = map(int, match.groups())
        assert actual_mode == mode
        if mode in (0, 6, 14):
            assert (command_reads, command_words) == (196, 49), text
            assert (reads, writes, acks, jobs) == (case['reads'], case['writes'], case['writes'], 1), text
        elif mode == 2:
            assert (command_reads, command_words) == (196, 49), text
            assert (reads, writes, acks, jobs) == (case['reads'], case['writes'], case['writes']-1, 0), text
        else:
            assert jobs == writes == acks == 0, text
            expected = {1: (196,49,1), 3: (0,0,0), 4: (1,0,0), 5: (1,0,0),
                        7: (4,1,0), 8: (4,0,0), 9: (1,0,0), 10: (0,0,0),
                        11: (0,0,0), 12: (0,0,0), 13: (184,45,0), 15: (1,0,0)}
            assert (command_reads, command_words, reads) == expected[mode], text
        report['tests'].append(dict(name=name, status='PASS', result=lines[0]))
        save()
    assert fingerprint(tracked) == report['source']; verify(vr['source']); verify(vr['artifacts'])
    report.update(status='PASS_RAW_ARRAY_DMA_'+a.suite.upper()+'_ONLY',
                  artifacts=fingerprint([binary]+[ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'])
