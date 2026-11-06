#!/usr/bin/env python3
"""Replay one unchanged K16-format raw command BO through the C32/K8 DMA.

The host command stream remains the 49-QWORD m2_n17_k65_finite case with
0x10014024=16. The DMA and AXI geometry parameters are propagated into the
core; the memory model returns the unchanged K16 input image and the original
K16/OC16 (N/16, K/32, 16, 32) weight BO, not a repacked K8 image. The bench
captures every write, compares the exact address/data sequence against the K8
core expectation, and checks that every output gap halfword remains the
sentinel.
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
p.add_argument('--suite', choices=('smoke', 'protocol'), default='protocol')
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
# Re-chunk each 16-halfword K16 block into two 8-halfword OC8 frames. The
# numerical values and the 64-byte OC16 block stride are unchanged.
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
             'rk_cmac_array_front.sv', 'rk_cmac_rw_arbiter.sv', 'rk_cmac_array_core.sv',
             'rk_cmac_array_dma.sv', 'rk_cmac_job_control.sv', 'rk_cmac_axi_mem.sv',
             'rk_cmac_array_axi.sv')]
sources.append(ROOT / 'rtl/rk_cmac_profile.sv')
bench = ROOT / 'tests/cmac/tb_cmac_array_dma.sv'
axi_bench = ROOT / 'tests/cmac/tb_cmac_array_axi.sv'
tracked = sources + [bench, axi_bench, ROOT / 'tests/axil_host.svh', ROOT / 'tests/memory_check.svh',
                     Path(__file__).resolve(), Path(__file__).with_name('gen_array_core_vectors_k8.py')]
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib',
                                'assertion_header.h', 'assertion_task.h')]
tracked += [k16 / 'vectors_report.json', k8 / 'vectors_report.json']
tracked += [k16 / case_name / n for n in ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex')]
tracked += [k8 / case_name / n for n in ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex')]
tracked += [k8 / case_name / 'derivation.json']

out = ROOT / f'build/rknpu-array-dma-k8/iverilog-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
report = dict(status='RUNNING', started_utc=timestamp(), suite=a.suite,
              case=case_name, atomic_c=32, atomic_k=8, rows=2, ai=96, ao=32,
              operand_frames=24, output_frames=8, reads=6912, writes=64,
              commands_sha256=commands_sha, source=fingerprint(tracked), commands=[], results=[],
              seed='0x3588ad16',
              scope='One unchanged K16-format raw command BO and original K16/OC16 weight BO through the C32/K8 DMA and core. Synthetic operands and K16-derived goldens, not RK captures, AXI host replay, DDR, FPGA or RK validation.')
for path in tracked:
    dest = out / 'snapshot' / path.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


def run(argv, name, allow_warnings=False):
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
        assert result.returncode == 0 and 'ERROR :' not in text, text[-6000:]
        if not allow_warnings:
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
    report['tool_version'] = run(['iverilog', '-V'], 'version').splitlines()[0]
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    binary = out / 'sim.vvp'
    params = {'ATOMIC_C': 32, 'ATOMIC_K': 8}
    run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
         '-s', bench.stem, *[f'-P{bench.stem}.{name}={value}' for name, value in params.items()],
         '-o', binary, *sources, bench], 'compile')
    # Elaborate the AXI endpoint with the same K8 override. This checks the
    # parameter propagation through the host bench; the K16 AXI suite remains
    # the transaction-level regression.
    run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-I.',
         '-s', axi_bench.stem,
         *[f'-P{axi_bench.stem}.{name}={value}' for name, value in params.items()],
         '-o', out / 'axi-elab.vvp', *sources, axi_bench], 'axi_k8_elaboration')
    report['axi_k8_elaboration'] = 'PASS'
    modes = (0,) if a.suite == 'smoke' else (0, 2)
    for mode in modes:
        text = run(['vvp', binary, f'+DIRECTORY={k8 / case_name}', f'+MODE={mode}', '+ROWS=2',
                    '+AI=96', '+AO=32', '+READS=6912', '+WRITES=64'], f'mode{mode}')
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        expected = (f'PASS DMA C32 K8 core mode={mode} command_reads=196 command_words=49 '
                    f'reads=6912 writes=64 acknowledgments={64 if mode == 0 else 63} '
                    f'jobs={1 if mode == 0 else 0} seed=3588ad16')
        assert lines == [expected], text[-6000:]
        report['results'].append(dict(mode=mode, status='PASS', result=lines[0]))
        save()
    assert fingerprint(tracked) == report['source']
    verify(k16_report['source'])
    verify(k16_report['artifacts'])
    verify(k8_report['source'])
    verify(k8_report['artifacts'])
    report.update(status='PASS_C32_K8_RAW_DMA_ONLY',
                  lower_slice_writes_exact=True,
                  gap_sentinels_checked=True,
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
