#!/usr/bin/env python3
"""Focused C32/K8 replay of the original K16/OC16 weight buffer.

The host command BO and the weight BO are the unchanged K16
`m2_n17_k65_finite` images. No `(N/8, K/32, 8, 32)` repack is supplied: the
K8 front must select the low and high OC8 halves of each original
`(N/16, K/32, 16, 32)` block. The test derives the expected K8 read order from
the original weight BO, re-chunks the K16 write list into two OC8 frames per
OC16 block, and checks every read/write plus the gap sentinels through the K8
core and DMA. The resulting write list is byte-identical to the historical
repacked-weight K8 result (the shared K8 `writes.hex`), so the original-weight
result equals that earlier result record-for-record.
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

CASE = 'm2_n17_k65_finite'
K16 = ROOT / 'build/rknpu-array-core-vectors'
K8 = ROOT / 'build/rknpu-array-core-vectors-k8'
k16_report = json.loads((K16 / 'vectors_report.json').read_text())
k8_report = json.loads((K8 / 'vectors_report.json').read_text())


def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name


verify(k16_report['source'])
verify(k16_report['artifacts'])
verify(k8_report['source'])
verify(k8_report['artifacts'])
case16 = next(c for c in k16_report['cases'] if c['name'] == CASE)
case8 = k8_report['case']
assert case8['name'] == CASE
assert (case8['rows'], case8['ai'], case8['ao']) == (2, 96, 32)
assert (case8['atomic_c'], case8['atomic_k']) == (32, 8)
assert (case8['operand_frames'], case8['output_frames'], case8['reads'],
        case8['writes']) == (24, 8, 6912, 64)
assert case8['repacked_weight_required'] is False
assert 'original K16/OC16' in case8['weight_layout']
assert (K8 / CASE / 'weight.hex').read_bytes() == \
       (K16 / CASE / 'weight.hex').read_bytes(), 'K8 corpus must carry the original weight BO'

rows, ai, ao = case8['rows'], case8['ai'], case8['ao']
commands = [int(line, 16) for line in (K16 / CASE / 'commands.hex').read_text().splitlines()]
inputs = [int(line, 16) for line in (K16 / CASE / 'input.hex').read_text().splitlines()]
weights16 = [int(line, 16) for line in (K16 / CASE / 'weight.hex').read_text().splitlines()]
reads16 = [int(line, 16) for line in (K16 / CASE / 'reads.hex').read_text().splitlines()]
writes16 = [int(line, 16) for line in (K16 / CASE / 'writes.hex').read_text().splitlines()]
writes8 = [int(line, 16) for line in (K8 / CASE / 'writes.hex').read_text().splitlines()]
assert len(commands) == 49
assert commands[32] == 0x1001000000104024, 'host kernel_group field must remain 16'
assert [((word >> 48) << 16) | (word & 0xffff) for word in commands[45:49]] == [
    0x00010000, 0x01010014, 0x00410000, 0x00810008]
commands_sha = hashlib.sha256(struct.pack('<49Q', *commands)).hexdigest()
assert commands_sha == case16['commands_sha256'] == case8['commands_sha256']
assert len(inputs) == rows * ai
assert len(weights16) == ai * ao
assert len(reads16) == case16['reads']
assert len(writes16) == case16['writes'] == rows * ao

# Original K16 weight layout is (N/16, K/32, 16, 32). A K8 OC8 frame reads
# eight consecutive kernels at the original OC16 block base plus the in-block
# kernel offset, and each IC32 group advances by one full 16-kernel group.
reads_original = []
frame_data_original = {}
for row in range(rows):
    for oc in range(0, ao, 8):
        for group in range(ai // 32):
            ic = group * 32
            reads_original += [((0x10010000 + 2 * (row * ai + ic + lane)) << 16) |
                               inputs[row * ai + ic + lane] for lane in range(32)]
            weight_base = (oc // 16) * 16 * ai + (oc % 16) * 32 + group * 16 * 32
            assert weight_base + 8 * 32 <= len(weights16)
            reads_original += [((0x10020000 + 2 * (weight_base + lane)) << 16) |
                               weights16[weight_base + lane] for lane in range(8 * 32)]
            frame_data_original[(row, oc, group)] = weights16[weight_base:weight_base + 8 * 32]
assert len(reads_original) == 6912 == case8['reads']

# Independent logical check: each original-buffer OC8 frame must carry the
# corresponding low/high half of the unchanged K16 OC16 frame.
frame_data16 = {}
for row in range(rows):
    for oc in range(0, ao, 16):
        for group in range(ai // 32):
            index = (row * ((ao // 16) * (ai // 32)) + (oc // 16) * (ai // 32) + group) * (32 + 512)
            frame_data16[(row, oc, group)] = [record & 0xffff for record in reads16[index + 32:index + 544]]
for (row, oc, group), data16 in frame_data16.items():
    for half in range(2):
        assert frame_data_original[(row, oc + half * 8, group)] == \
            data16[half * 256:(half + 1) * 256], (row, oc, group, half)

# K8 output schedule is the unchanged K16 write list re-chunked into two
# eight-halfword frames per OC16 block. Values and the 64-byte block stride
# (including the 16-halfword gap) remain unchanged.
writes_rechunked = []
for block in range(len(writes16) // 16):
    block_base = writes16[block * 16] >> 16
    for frame in range(2):
        for lane in range(8):
            record = writes16[block * 16 + frame * 8 + lane]
            assert record >> 16 == block_base + frame * 16 + lane * 2
            writes_rechunked.append(record)
assert writes_rechunked == writes8 == [int(line, 16) for line in
                                       (K8 / CASE / 'writes.hex').read_text().splitlines()]
assert {record >> 16 for record in reads_original if (record >> 16) >= 0x10020000} <= \
       set(0x10020000 + 2 * index for index in range(ai * ao))
assert {record >> 16 for record in writes_rechunked} <= \
       set(0x10040000 + 2 * index for index in range(rows * ao * 2))

donor = ROOT / 'rtl/vendor/nvdla'
core_sources = [donor / n for n in ('compat/nv_assert_never.v', 'compat/nv_assert_no_x.v',
                                    'NV_DW_lsd.v', 'NV_DW02_tree.v', 'NV_NVDLA_CMAC_CORE_MAC_mul.v',
                                    'NV_NVDLA_CACC_CALC_fp_48b.v', 'HLS_fp32_to_fp16.v')]
core_sources += [ROOT / 'rtl/cmac' / n for n in
                 ('rk_cmac_fp16_cell.sv', 'rk_cmac_fp16_array.sv', 'rk_nvdla_cacc.sv',
                  'rk_cacc_fp16_array.sv', 'rk_cmac_cacc_fp16_array.sv',
                  'rk_nvdla_fp32_to_fp16.sv', 'rk_cmac_writer.sv', 'rk_cmac_output_nvdla.sv',
                  'rk_cmac_frame_output.sv', 'rk_cmac_array_datapath.sv',
                  'rk_cmac_array_front.sv', 'rk_cmac_rw_arbiter.sv', 'rk_cmac_array_core.sv')]
core_sources.append(ROOT / 'rtl/rk_cmac_profile.sv')
dma_sources = core_sources + [ROOT / 'rtl/cmac' / n for n in
                              ('rk_cmac_array_dma.sv', 'rk_cmac_job_control.sv',
                               'rk_cmac_axi_mem.sv', 'rk_cmac_array_axi.sv')]
core_bench = ROOT / 'tests/cmac/tb_cmac_array_core.sv'
dma_bench = ROOT / 'tests/cmac/tb_cmac_array_dma.sv'
tracked = core_sources + [core_bench, dma_bench, Path(__file__).resolve()]
tracked += [donor / n for n in ('nv_assert_never.vlib', 'nv_assert_no_x.vlib',
                                'assertion_header.h', 'assertion_task.h')]
tracked += [K16 / 'vectors_report.json', K8 / 'vectors_report.json']
tracked += [K16 / CASE / n for n in ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex')]
tracked += [K8 / CASE / n for n in ('commands.hex', 'input.hex', 'weight.hex', 'reads.hex', 'writes.hex')]
tracked += [K8 / CASE / 'derivation.json']

out = ROOT / f'build/rknpu-array-core-k8-original/{a.tool}-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
corpus = out / 'corpus' / CASE
corpus.mkdir(parents=True)
# Copy the original K16 operand BOs byte-for-byte. The weight file is the
# original (N/16, K/32, 16, 32) buffer, not a K8 repack.
for name in ('commands.hex', 'input.hex', 'weight.hex'):
    (corpus / name).write_bytes((K16 / CASE / name).read_bytes())
(corpus / 'reads.hex').write_text(''.join(f'{value:012x}\n' for value in reads_original))
(corpus / 'writes.hex').write_text(''.join(f'{value:012x}\n' for value in writes_rechunked))
(corpus / 'derivation.json').write_text(json.dumps({
    'source_case': CASE,
    'source_weight': f'{K16.relative_to(ROOT)}/{CASE}/weight.hex',
    'source_weight_sha256': hashlib.sha256((K16 / CASE / 'weight.hex').read_bytes()).hexdigest(),
    'atomic_c': 32,
    'atomic_k': 8,
    'rows': rows,
    'ai': ai,
    'ao': ao,
    'operand_frames': case8['operand_frames'],
    'output_frames': case8['output_frames'],
    'read_count': len(reads_original),
    'write_count': len(writes_rechunked),
    'weight_layout': '(N/16, K/32, 16, 32), read directly with OC8 halves',
    'write_layout': '8 halfwords at OC16 base+0 and OC16 base+16 bytes; 64-byte block stride preserved',
    'scope': 'Test-only original-weight K8 derivation from the unchanged C32/K16 core case; no repack and no runtime CPU layout fixup.',
}, indent=2) + '\n')
corpus_files = [corpus / n for n in ('commands.hex', 'input.hex', 'weight.hex',
                                     'reads.hex', 'writes.hex', 'derivation.json')]
assert hashlib.sha256((corpus / 'weight.hex').read_bytes()).hexdigest() == \
       hashlib.sha256((K16 / CASE / 'weight.hex').read_bytes()).hexdigest()
assert (corpus / 'commands.hex').read_bytes() == (K16 / CASE / 'commands.hex').read_bytes()
assert (corpus / 'input.hex').read_bytes() == (K16 / CASE / 'input.hex').read_bytes()
assert (corpus / 'writes.hex').read_bytes() == (K8 / CASE / 'writes.hex').read_bytes()

report = dict(status='RUNNING', started_utc=timestamp(), tool=a.tool, suite=a.suite,
              case=CASE, atomic_c=32, atomic_k=8, rows=rows, ai=ai, ao=ao,
              operand_frames=case8['operand_frames'], output_frames=case8['output_frames'],
              reads=len(reads_original), writes=len(writes_rechunked),
              commands_sha256=commands_sha,
              original_weight_sha256=hashlib.sha256((corpus / 'weight.hex').read_bytes()).hexdigest(),
              writes_sha256=hashlib.sha256((corpus / 'writes.hex').read_bytes()).hexdigest(),
              historical_repacked_writes_sha256=hashlib.sha256(
                  (K8 / CASE / 'writes.hex').read_bytes()).hexdigest(),
              source=fingerprint(tracked), corpus=fingerprint(corpus_files),
              commands=[], results=[], seed='0x3588ae16',
              scope='Unchanged K16 raw command and original K16/OC16 weight BO through the C32/K8 core and DMA. Synthetic operands and K16-derived goldens, not RK captures, repacked backend packing, FPGA or RK validation.')
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


def expected_core(mode):
    return (f'PASS raw C32 K8 core mode={mode} reads=6912 writes=64 '
            f'acknowledgments={64 if mode == 0 else 63} jobs={1 if mode == 0 else 0} '
            f'seed=3588ac16')


def expected_dma(mode):
    return (f'PASS DMA C32 K8 core mode={mode} command_reads=196 command_words=49 '
            f'reads=6912 writes=64 acknowledgments={64 if mode == 0 else 63} '
            f'jobs={1 if mode == 0 else 0} seed=3588ad16')


save()
try:
    report['tool_version'] = run([a.tool, '--version' if a.tool == 'verilator' else '-V'],
                                 'version').splitlines()[0]
    report['runtime_version'] = run(['vvp', '-V'], 'runtime_version').splitlines()[0]
    modes = (0,) if a.suite == 'normal' else (0, 2)

    core_binary = out / ('sim_core' if a.tool == 'iverilog' else 'sim_core.vvp')
    if a.tool == 'iverilog':
        run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}',
             '-s', core_bench.stem, f'-P{core_bench.stem}.ATOMIC_K=8',
             '-o', core_binary, *core_sources, core_bench], 'compile_core')
        core_execute = ['vvp', str(core_binary)]
    else:
        flags = ['--timing', '--assert', '-Wall', '-Wno-fatal', '--timescale-override', '1ns/1ps',
                 '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-GATOMIC_K=8']
        run(['verilator', '--binary', *flags, '-j', '2', '--top-module', core_bench.stem,
             '--Mdir', out / 'obj_core', '-o', 'sim_core', *core_sources, core_bench],
            'compile_core', lint=True)
        core_execute = [str(out / 'obj_core' / 'sim_core')]
        report['cxx_version'] = run(['c++', '--version'], 'cxx_version').splitlines()[0]

    dma_binary = out / 'sim_dma.vvp'
    run(['iverilog', '-g2012', '-DDESIGNWARE_NOEXIST', '-DASSERT_ON', f'-I{donor}', '-I.',
         '-s', dma_bench.stem, f'-P{dma_bench.stem}.ATOMIC_C=32',
         f'-P{dma_bench.stem}.ATOMIC_K=8',
         '-o', dma_binary, *dma_sources, dma_bench], 'compile_dma')

    # The new front reads the original OC16 image; the old repacked image is
    # not a second supported layout. Equality with the previously repacked
    # result is the exact write list shared by both derivatives, already
    # checked above, not a second read-order replay.
    for mode in modes:
        text = run(core_execute + [f'+DIRECTORY={corpus}', f'+MODE={mode}', f'+ROWS={rows}',
                                   f'+AI={ai}', f'+AO={ao}', '+READS=6912', '+WRITES=64'],
                   f'core_original_mode{mode}')
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert lines == [expected_core(mode)], text[-6000:]
        report['results'].append(dict(target='core', corpus='original', mode=mode,
                                      status='PASS', result=lines[0]))
        save()
    for mode in modes:
        text = run(['vvp', str(dma_binary), f'+DIRECTORY={corpus}', f'+MODE={mode}',
                    f'+ROWS={rows}', f'+AI={ai}', f'+AO={ao}', '+READS=6912', '+WRITES=64'],
                   f'dma_original_mode{mode}')
        lines = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert lines == [expected_dma(mode)], text[-6000:]
        report['results'].append(dict(target='dma', corpus='original', mode=mode,
                                      status='PASS', result=lines[0]))
        save()

    assert fingerprint(tracked) == report['source']
    assert fingerprint(corpus_files) == report['corpus']
    verify(k16_report['source'])
    verify(k16_report['artifacts'])
    verify(k8_report['source'])
    verify(k8_report['artifacts'])
    report.update(status='PASS_C32_K8_ORIGINAL_WEIGHT_CORE_AND_DMA_ONLY',
                  original_weight_is_k16=True,
                  no_repacked_weight_required=True,
                  original_equals_repacked=True,
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
