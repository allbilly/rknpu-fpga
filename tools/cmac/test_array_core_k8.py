#!/usr/bin/env python3
"""Replay one unchanged K16-format raw command stream through the K8 core.

The host command BO is the existing 49-QWORD m2_n17_k65_finite stream with
0x10014024=16. The core is instantiated with ATOMIC_K=8, so the front splits
the logical OC16 job into two OC8 frames. The memory model returns the
original K16/OC16 (N/16, K/32, 16, 32) weight BO, not a repacked K8 image; the
bench checks every read, every write, the 16-halfword gap and the lower/upper
OC8 numerical equality against the K16 reference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--tool', choices=('iverilog', 'verilator'), default='iverilog')
p.add_argument('--suite', choices=('normal', 'protocol'), default='protocol')
a = p.parse_args()

k16 = ROOT / 'build/rknpu-array-core-vectors'
k8 = ROOT / 'build/rknpu-array-core-vectors-k8'
case_name = 'm2_n17_k65_finite'
k16_report = json.loads((k16 / 'vectors_report.json').read_text())
k8_report = json.loads((k8 / 'vectors_report.json').read_text())


def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name


verify(k16_report['source'])
verify(k16_report['artifacts'])
verify(k8_report['source'])
verify(k8_report['artifacts'])
case16 = next(c for c in k16_report['cases'] if c['name'] == case_name)
case8 = k8_report['case']
assert case8['name'] == case_name
assert (case8['rows'], case8['ai'], case8['ao']) == (2, 96, 32)
assert (case8['atomic_c'], case8['atomic_k']) == (32, 8)
assert (case8['operand_frames'], case8['output_frames'], case8['reads'],
        case8['writes']) == (24, 8, 6912, 64)
assert case8['repacked_weight_required'] is False
assert 'original K16/OC16' in case8['weight_layout']
assert (k8 / case_name / 'weight.hex').read_bytes() == \
       (k16 / case_name / 'weight.hex').read_bytes(), 'K8 path must use the original weight BO'
commands = [int(line, 16) for line in (k16 / case_name / 'commands.hex').read_text().splitlines()]
assert len(commands) == 49
assert commands[32] == 0x1001000000104024, 'host kernel_group field must remain 16'
assert [((word >> 48) << 16) | (word & 0xffff) for word in commands[45:49]] == [
    0x00010000, 0x01010014, 0x00410000, 0x00810008]
commands_sha = hashlib.sha256(struct.pack('<49Q', *commands)).hexdigest()
assert commands_sha == case16['commands_sha256'] == case8['commands_sha256']
writes16 = [int(line, 16) for line in (k16 / case_name / 'writes.hex').read_text().splitlines()]
writes8 = [int(line, 16) for line in (k8 / case_name / 'writes.hex').read_text().splitlines()]
assert writes8 == writes16
# Re-chunk the 16-halfword K16 block into two 8-halfword OC8 frames and check
# the physical OC16 base/+16-byte placement independently of the RTL.
for block in range(len(writes16) // 16):
    block_base = writes16[block * 16] >> 16
    for frame in range(2):
        for lane in range(8):
            record = writes8[block * 16 + frame * 8 + lane]
            assert record >> 16 == block_base + frame * 16 + lane * 2
            assert record == writes16[block * 16 + frame * 8 + lane]

donor = ROOT / 'rtl/vendor/nvdla'
sources = [donor / n for n in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v',
                               'NV_DW_lsd.v', 'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
                               'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v')]
sources += [ROOT / 'rtl/cmac' / n for n in
            ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv', 'rk_nvdla_cacc.sv',
             'rk_cacc_fp16_array.sv', 'rk_cmac_cacc_fp16_array.sv',
             'rk_nvdla_fp32_to_fp16.sv', 'rk_cmac_writer.sv', 'rk_cmac_output_nvdla.sv',
             'rk_cmac_frame_output.sv', 'rk_cmac_array_datapath.sv',
             'rk_cmac_array_front.sv', 'rk_cmac_rw_arbiter.sv', 'rk_cmac_array_core.sv')]
sources.append(ROOT / 'rtl/rk_cmac_profile.sv')
bench = ROOT / 'tests/cmac/tb_cmac_array_core.sv'
tracked = sources + [bench, Path(__file__).resolve(), Path(__file__).with_name('gen_array_core_vectors_k8.py')]
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib',
                                'assertion_header.h', 'assertion_task.h')]
tracked += [k16 / 'vectors_report.json', k8 / 'vectors_report.json']
tracked += [k16 / case_name / n for n in ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex')]
tracked += [k8 / case_name / n for n in ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex')]
tracked += [k8 / case_name / 'derivation.json']

out = ROOT / f'build/rknpu-array-core-k8/{a.tool}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), tool=a.tool, suite=a.suite,
              case=case_name, atomic_c=32, atomic_k=8, rows=2, ai=96, ao=32,
              operand_frames=24, output_frames=8, reads=6912, writes=64,
              commands_sha256=commands_sha, source=fingerprint(tracked), commands=[], results=[],
              seed='0x3588ac16',
              scope='One unchanged K16-format raw command stream and original K16/OC16 weight BO through the C32/K8 core. Synthetic operands and K16-derived goldens, not RK captures, DMA/AXI/DDR, FPGA or RK validation.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


def run(argv, name, lint=False):
    step = dict(argv=list(map(str, argv)), status='RUNNING',
                log=str((out / (name + '.log')).relative_to(ROOT)))
    report['commands'].append(step)
    save()
    started = time.monotonic()
    try:
        with (ROOT / step['log']).open('w') as log:
            result = subprocess.run(step['argv'], cwd=ROOT, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=14400)
        text = (ROOT / step['log']).read_text()
        step['returncode'] = result.returncode
        assert result.returncode == 0 and '%Error' not in text and 'ERROR :' not in text, text[-6000:]
        if lint:
            warnings = re.findall(r'^%Warning-([^:]+): ([^:]+):(\d+):\d+:', text, re.M)
            step['warning_count'] = len(warnings)
            step['warning_locations'] = sorted(set(path for _, path, _ in warnings))
        else:
            assert not re.search(r'warning:|sorry:', text, re.I), text[-6000:]
        step['status'] = 'PASS'
        return text
    except Exception:
        step['status'] = 'FAIL'
        raise
    finally:
        step['seconds'] = round(time.monotonic() - started, 3)
        save()


save()
try:
    report['tool_version'] = run([a.tool, '--version' if a.tool == 'verilator' else '-V'],
                                 'version').splitlines()[0]
    binary = out / 'sim'
    params = {'ATOMIC_K': 8}
    if a.tool == 'iverilog':
        run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
             '-s', bench.stem, *[f'-P{bench.stem}.{name}={value}' for name, value in params.items()],
             '-o', binary, *sources, bench], 'compile')
        execute = ['vvp', str(binary)]
    else:
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps',
                 '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
                 *[f'-G{name}={value}' for name, value in params.items()]]
        run(['verilator', '--binary', *flags, '-j', '2', '--top-module', bench.stem,
             '--Mdir', out / 'obj', '-o', 'sim', *sources, bench], 'compile', lint=True)
        execute = [str(out / 'obj' / 'sim')]
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]
    if a.tool == 'iverilog':
        report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    modes = (0, 2) if a.suite == 'protocol' else (0,)
    for mode in modes:
        text = run(execute + [f'+DIRECTORY={k8 / case_name}', f'+MODE={mode}', '+ROWS=2',
                              '+AI=96', '+AO=32', '+READS=6912', '+WRITES=64'], f'mode{mode}')
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        expected = (f'PASS raw C32 K8 core mode={mode} reads=6912 writes=64 '
                    f'acknowledgments={64 if mode == 0 else 63} jobs={1 if mode == 0 else 0} seed=3588ac16')
        assert lines == [expected], text[-6000:]
        report['results'].append(dict(mode=mode, status='PASS', result=lines[0]))
        save()
    assert fingerprint(tracked) == report['source']
    verify(k16_report['source'])
    verify(k16_report['artifacts'])
    verify(k8_report['source'])
    verify(k8_report['artifacts'])
    report.update(status='PASS_C32_K8_RAW_COMMAND_CORE_ONLY',
                  lower_slice_writes_exact=True,
                  artifacts=fingerprint([ROOT / c['log'] for c in report['commands']]))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp()
    save()
    print(out / 'report.json')
print(report['status'])
for result in report['results']:
    print(result['result'])
