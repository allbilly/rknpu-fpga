#!/usr/bin/env python3
"""Test-only C32 numerical oracles for unchanged terminal RK command captures."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from cacc_reference import add, final

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

def convert(bits):
    # Independent test policy, not FPGA execution: donor payload truncation,
    # finite RNE and saturation. Checked against the existing output corpus.
    if bits & 0x7f800000 == 0x7f800000 and bits & 0x7fffff:
        return ((bits >> 16) & 0x8000) | 0x7c00 | (bits & 1023)
    value = struct.unpack('<f', struct.pack('<I', bits))[0]
    try:
        result = struct.unpack('<H', struct.pack('<e', value))[0]
        return (result & 0x8000) | 0x7bff if result & 0x7fff == 0x7c00 else result
    except OverflowError:
        return ((bits >> 16) & 0x8000) | 0x7bff

def nan(value):
    return value & 0x7c00 == 0x7c00 and value & 1023 != 0

def mant(value):
    exponent = (value >> 10) & 31
    return ((value & 1023) | (1024 if exponent else 0)) << (exponent & 3 if exponent else 1)

base = ROOT / 'build/rknpu-array-front'
vr = json.loads((base / 'vectors_report.json').read_text())
verify(vr['source']); verify(vr['artifacts'])
output_corpus = ROOT / 'build/rknpu-frame-output/vectors.hex'
conversion_checks = 0
for line in output_corpus.read_text().splitlines():
    row = int(line, 16)
    for lane in range(16):
        assert convert((row >> (256 + 32*lane)) & 0xffffffff) == (row >> (16*lane)) & 65535
        conversion_checks += 1

helper = ROOT / 'build/cmac_group_candidate/donor_booth_helper.cpp'
assert hashlib.sha256(helper.read_bytes()).hexdigest() == 'f7c53e8e4d0d12db0c9d62e2c0b2fac3fe95458b3af85328b6f0b3bf9036d2f0'
out = ROOT / 'build/rknpu-array-core-vectors'
out.mkdir(exist_ok=False)
binary = out / 'donor_helper'
command = ['c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', str(helper), '-o', str(binary)]
compiled = subprocess.run(command, capture_output=True, text=True)
(out / 'compile.log').write_text(compiled.stdout + compiled.stderr)
assert compiled.returncode == 0, compiled.stderr
sources = [Path(__file__).resolve(), Path(__file__).with_name('cacc_reference.py'),
           base / 'vectors_report.json', helper, output_corpus]
artifacts = [binary, out / 'compile.log']
cases = []
for fixture, finite in [(case, False) for case in vr['cases']] + [(vr['cases'][-1], True)]:
    name = fixture['name'] + ('_finite' if finite else '')
    original = ROOT / 'build/cmac_vectors' / fixture['name']
    words = [int(line, 16) for line in (original / 'commands.hex').read_text().splitlines()]
    assert len(words) == 49 and hashlib.sha256(struct.pack('<49Q', *words)).hexdigest() == fixture['commands_sha256']
    inputs = [int(line, 16) for line in (original / 'input.hex').read_text().splitlines()]
    weights = [int(line, 16) for line in (original / 'weight.hex').read_text().splitlines()]
    m, ai, ao = (fixture[key] for key in ('rows', 'ai', 'ao'))
    assert len(inputs) == m*ai and len(weights) == ai*ao
    if finite:
        inputs = [(x & 0x83ff) | ((10 + ((x >> 10) % 8)) << 10) for x in inputs]
        weights = [(x & 0x83ff) | ((11 + ((x >> 10) % 7)) << 10) for x in weights]
    requests, metadata, reads = [], [], []
    for row in range(m):
        for oc in range(0, ao, 16):
            for ic in range(0, ai, 32):
                data = inputs[row*ai+ic:row*ai+ic+32]
                weight_base = oc*ai + ic*16
                reads += [((0x10010000 + 2*(row*ai+ic+c)) << 16) | data[c] for c in range(32)]
                reads += [((0x10020000 + 2*(weight_base+i)) << 16) | weights[weight_base+i] for i in range(512)]
                for kernel in range(16):
                    weight = weights[weight_base+kernel*32:weight_base+(kernel+1)*32]
                    active = [bool(x & 0x7fff) and bool(w & 0x7fff) for x, w in zip(data, weight)]
                    exponents = [((x >> 12) & 7) + ((w >> 12) & 7) if used else 0
                                 for x, w, used in zip(data, weight, active)]
                    maximum = max(exponents)
                    start = len(requests)
                    for x, w, used, exponent in zip(data, weight, active, exponents):
                        if used:
                            requests.append(f'{(x^w)>>15} {mant(w)} {mant(x)} {(maximum-exponent)*4}\n')
                    special = next((w for w in weight if nan(w)), None)
                    if special is None:
                        special = next((x for x in data if nan(x)), None)
                    metadata.append((row, oc, ic, kernel, maximum, start, len(requests), special))
    result = subprocess.run([binary], input=''.join(requests), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    partials = list(map(int, result.stdout.split()))
    assert len(partials) == len(requests)
    accumulators = [0]*16
    writes, groups, finals = [], [], []
    for row, oc, ic, kernel, maximum, start, end, special in metadata:
        group = ((63 << 38) | ((special >> 15) << 37) | ((special & 1023) << 27)) if special is not None else \
                (maximum << 40) | (sum(partials[start:end]) & ((1 << 38)-1))
        groups.append(group)
        accumulators[kernel] = add(group, accumulators[kernel], ic != 0)
        if ic == ai-32:
            bits = final(accumulators[kernel])
            address = 0x10040000 + row*ao*4 + (oc//16)*64 + kernel*2
            writes.append((address << 16) | convert(bits))
            finals.append(bits)
    assert len(reads) == fixture['reads'] and len(writes) == m*ao
    if finite:
        assert all(not nan(x & 65535) and x & 0x7fff != 0x7c00 for x in writes)
        assert len(set(x & 65535 for x in writes)) > 16
    directory = out / name
    directory.mkdir()
    for filename, values, width in [('commands.hex', words, 16), ('input.hex', inputs, 4), ('weight.hex', weights, 4),
                                     ('reads.hex', reads, 12), ('writes.hex', writes, 12), ('groups.hex', groups, 11),
                                     ('fp32.hex', finals, 8)]:
        path = directory / filename
        path.write_text(''.join(f'{value:0{width}x}\n' for value in values))
        artifacts.append(path)
    sources += [original / name for name in ('commands.hex', 'input.hex', 'weight.hex')]
    cases.append(dict(name=name, raw_fixture=fixture['name'], commands_sha256=fixture['commands_sha256'], rows=m, ai=ai, ao=ao,
                      frames=fixture['frames'], reads=len(reads), writes=len(writes), finite_variant=finite,
                      nan_outputs=sum(nan(x & 65535) for x in writes), unique_outputs=len(set(x & 65535 for x in writes))))
report = dict(status='GENERATED_C32_RAW_CORE_REFERENCE_ONLY', created_utc=timestamp(), cases=cases,
              source=fingerprint(sources), artifacts=fingerprint(artifacts), compile_command=command,
              compiler=subprocess.run(['c++', '--version'], capture_output=True, text=True).stdout.splitlines()[0],
              conversion_reference_checks=conversion_checks,
              scope='Unchanged raw command words, static synthetic physical operands, C32 donor Booth grouping and dyadic CACC reference. No runtime CPU fixups, RTL result, RK capture or original UTB pass.')
(out / 'vectors_report.json').write_text(json.dumps(report, indent=2)+'\n')
print(f'Generated {len(cases)} raw-command cases, {sum(c["frames"] for c in cases)} C32/K16 frames, {sum(c["writes"] for c in cases)} output halfwords')
