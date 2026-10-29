#!/usr/bin/env python3
"""Freeze TinyStories260K inputs and static C32/K16 weight tiles. No execution.

Only trained constant weights are packed here. Runtime activations/results must
use the documented device buffers and hardware movement, never CPU gathers.
The software C engine is a separate reference target, not a hardware fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

MODEL_SHA = 'b0a507e7ad0f626624f17112325e66691f9076d622e1d3274d103d00299f2696'
TOKENIZER_SHA = '037cb335abb25d1fa9e8ecae30ed2a3a8ace9302862ebcdc05d51a6bbb10c312'
RUN_C_SHA = '9c4f2d5c6ae01b71726d1cc37530d71e60bff0ec7cc012565f16a43c1ca658bd'
MODEL_REVISION = '0bd21da7698eaf29a0d7de3992de8a46ef624add'
C_REVISION = '350e04fe35433e6d2941dce5a1f53308f87058eb'
HEADER = (64, 172, 5, 8, 4, 512, 512)
BASE, CAPACITY, WEIGHTS = 0x10000000, 1048576, 0x10010000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tensor_layout():
    """Classic llama2.c FP32 file layout, including its stored RoPE tables."""
    shapes = [('token_embedding_table', (512, 64)), ('rms_att_weight', (5, 64)),
              ('wq', (5, 64, 64)), ('wk', (5, 32, 64)), ('wv', (5, 32, 64)),
              ('wo', (5, 64, 64)), ('rms_ffn_weight', (5, 64)),
              ('w1', (5, 172, 64)), ('w2', (5, 64, 172)), ('w3', (5, 172, 64)),
              ('rms_final_weight', (64,)), ('freq_cis_real', (512, 4)),
              ('freq_cis_imag', (512, 4))]
    offset, tensors = 28, {}
    for name, shape in shapes:
        count = math.prod(shape)
        tensors[name] = dict(shape=list(shape), offset=offset, count=count, bytes=count*4)
        offset += count*4
    require(offset == 1056540, 'Internal checkpoint layout disagreement')
    return tensors


def check_model(raw):
    require(len(raw) == 1056540, 'Unsupported/truncated TinyStories260K checkpoint size')
    require(struct.unpack_from('<7i', raw) == HEADER, 'Unsupported TinyStories shape/classifier layout')
    require(sha(raw) == MODEL_SHA, 'Unreviewed TinyStories checkpoint bytes')
    require(all(math.isfinite(v) for (v,) in struct.iter_unpack('<f', raw[28:])),
            'Nonfinite checkpoint tensor')
    return tensor_layout()


def check_tokenizer(raw):
    require(sha(raw) == TOKENIZER_SHA, 'Unreviewed TinyStories tokenizer bytes')
    require(len(raw) >= 4, 'Truncated tokenizer')
    maximum, = struct.unpack_from('<i', raw)
    require(maximum > 0, 'Invalid tokenizer maximum length')
    offset = 4
    for index in range(512):
        require(offset+8 <= len(raw), 'Truncated token header')
        score, length = struct.unpack_from('<fi', raw, offset)
        offset += 8
        require(math.isfinite(score) and 0 < length <= maximum and offset+length <= len(raw),
                'Invalid token record')
        token = raw[offset:offset+length]
        if 3 <= index < 259:
            require(token == f'<0x{index-3:02X}>'.encode(), 'Unexpected byte-token mapping')
        offset += length
    require(offset == len(raw), 'Tokenizer trailing data')


def projection_layout(tensors=None):
    tensors = tensors or tensor_layout()
    result = []
    for layer in range(5):
        for kind in ('wq', 'wk', 'wv', 'wo', 'w1', 'w2', 'w3'):
            item = tensors[kind]
            _, outputs, inputs = item['shape']
            result.append(dict(name=f'layers.{layer}.{kind}', outputs=outputs, inputs=inputs,
                               source_offset=item['offset']+layer*outputs*inputs*4))
    embedding = tensors['token_embedding_table']
    result.append(dict(name='output', outputs=512, inputs=64, source_offset=embedding['offset']))
    return result


def pack_tile(model, projection, first):
    """Offline constant OC16/IC32 packing; zero padding belongs to this file."""
    outputs, inputs = projection['outputs'], projection['inputs']
    require(type(first) is int and 0 <= first < outputs and first % 32 == 0, 'Invalid output tile')
    ai = (inputs+31)//32*32
    packed = bytearray()
    # Same physical order as the source-evidenced CMAC address contract:
    # output block16, input block32, kernel16, input lane32.
    for oc in (0, 16):
        for ic in range(0, ai, 32):
            for kernel in range(16):
                row = first+oc+kernel
                for lane in range(32):
                    column = ic+lane
                    value = 0.0
                    if row < outputs and column < inputs:
                        value, = struct.unpack_from('<f', model,
                            projection['source_offset']+4*(row*inputs+column))
                    try:
                        encoded = struct.pack('<e', value)
                    except OverflowError as error:
                        raise ValueError('Constant weight overflows FP16; no saturation repair') from error
                    require(int.from_bytes(encoded, 'little') & 0x7c00 != 0x7c00,
                            'Constant weight becomes nonfinite FP16')
                    packed.extend(encoded)
    require(len(packed) == 32*ai*2, 'Incorrect C32/K16 packed extent')
    return bytes(packed)


def prepare(model_path, tokenizer_path, c_root, out):
    model, tokenizer = Path(model_path).read_bytes(), Path(tokenizer_path).read_bytes()
    tensors = check_model(model)
    check_tokenizer(tokenizer)
    c_root, out = Path(c_root), Path(out)
    run_c, license_text = (c_root/'run.c').read_bytes(), (c_root/'LICENSE').read_bytes()
    require(sha(run_c) == RUN_C_SHA, 'Unreviewed llama2.c reference source')
    require(b'MIT License' in license_text and b'Andrej' in license_text, 'Missing reference license')
    require(not out.exists(), 'Use a fresh preparation directory')
    out.mkdir(parents=True)
    files = {}
    def save(name, raw):
        target = out/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        files[name] = dict(sha256=sha(raw), bytes=len(raw))
    save('assets/stories260K.bin', model)
    save('assets/tok512.bin', tokenizer)
    save('reference/run.c', run_c)
    save('reference/LICENSE', license_text)
    save('source/prepare.py', Path(__file__).read_bytes())
    projections, address, tiles = projection_layout(tensors), WEIGHTS, []
    for projection in projections:
        for first in range(0, projection['outputs'], 32):
            raw = pack_tile(model, projection, first)
            name = f'weights/{projection["name"]}-{first:04d}.bin'
            save(name, raw)
            ai = (projection['inputs']+31)//32*32
            tiles.append(dict(projection=projection['name'], first_output=first,
                logical_outputs=min(32, projection['outputs']-first), logical_inputs=projection['inputs'],
                rows=1, ai=ai, ao=32, address=address, bytes=len(raw), file=name,
                cmac_frames=2*(ai//32), native_output_bytes=128,
                required_hardware_compaction=[dict(source_halfword=0, destination_halfword=first, count=16),
                                              dict(source_halfword=32, destination_halfword=first+16, count=16)]))
            address += len(raw)
    require(len(projections) == 36 and len(tiles) == 116, 'Projection/tile inventory disagreement')
    require(address-WEIGHTS == 557056 and address <= BASE+CAPACITY, 'Static weights exceed BRAM contract')
    report = dict(status='PREPARED_TINYSTORIES260K_STATIC_DENSE_LAYOUT_ONLY', schema=1,
        scope='Static model/reference/weight layout only; no RTL, image, FPGA inference or RK equivalence claim',
        model_sha256=MODEL_SHA, tokenizer_sha256=TOKENIZER_SHA, model_revision=MODEL_REVISION,
        model_url=f'https://huggingface.co/karpathy/tinyllamas/tree/{MODEL_REVISION}/stories260K',
        reference_revision=C_REVISION,
        reference_url=f'https://github.com/karpathy/llama2.c/tree/{C_REVISION}',
        config=dict(dim=64, hidden_dim=172, layers=5, heads=8, kv_heads=4, vocab=512, context=512),
        learned_parameters=260032, learned_fp16_bytes=520064,
        host_kv_cache_fp32_bytes=655360, projections=projections, tiles=tiles,
        packed_weights_bytes=address-WEIGHTS,
        candidate_buffers=dict(input=dict(address=BASE, bytes=4096), native_output=dict(address=BASE+4096, bytes=4096),
            linear_output=dict(address=BASE+8192, bytes=4096), unity=dict(address=BASE+12288, bytes=4096),
            weights=dict(address=WEIGHTS, bytes=address-WEIGHTS), command=dict(address=0x100e0000, bytes=65536),
            tasks=dict(address=0x100f0000, bytes=16384)),
        execution_contract=dict(dense='Full512 C32/K16 raw CMAC, finite FP16 inputs/weights/output, donor accumulator candidate policy',
            host='Embedding/RMSNorm/RoPE/attention/SwiGLU/residuals/sampling; explicit model operators, no dense fallback',
            layout='Offline constant weight packing. Runtime result compaction must execute in hardware before host byte readback.',
            compaction_candidate='Two source-evidenced raw EW MUL-by-unity16 tasks per32-output tile; requires exhaustive finite bit-preservation proof before admission',
            raw_boundary='Unchanged production final writer must produce both CMAC and EW commands; no tensor-operation transport'),
        remaining_gates=['Fresh official CPU reference', 'Finite EW unity-copy RTL/numerical proof',
            'Actual TinyStories projection commands via original final writer', 'Native full512 projection numerical replay',
            'Explicit host/full512/EW ownership and command selection', 'Routed timing/CDC/startup/image review',
            'Physical first projection, then all five layers and generated tokens with independent logits audit'],
        hardware_accessed=False, cpu_dense_fallback=False, files=files)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    verify(out)
    return report


def verify(directory):
    directory = Path(directory)
    report = json.loads((directory/'report.json').read_text())
    require(report['status'] == 'PREPARED_TINYSTORIES260K_STATIC_DENSE_LAYOUT_ONLY', 'Wrong preparation status')
    require(not report['hardware_accessed'] and not report['cpu_dense_fallback'], 'Invalid execution claims')
    require(report['model_sha256'] == MODEL_SHA and report['tokenizer_sha256'] == TOKENIZER_SHA and
            report['model_revision'] == MODEL_REVISION and report['reference_revision'] == C_REVISION,
            'Changed model/reference identity')
    require(report['config'] == dict(dim=64, hidden_dim=172, layers=5, heads=8, kv_heads=4, vocab=512, context=512)
            and report['learned_parameters'] == 260032 and report['learned_fp16_bytes'] == 520064
            and report['host_kv_cache_fp32_bytes'] == 655360, 'Changed model/memory contract')
    for name, item in report['files'].items():
        relative = Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts, 'Escaping prepared file')
        raw = (directory/relative).read_bytes()
        require(len(raw) == item['bytes'] and sha(raw) == item['sha256'], 'Changed prepared file: '+name)
    model = (directory/'assets/stories260K.bin').read_bytes()
    require(sha((directory/'reference/run.c').read_bytes()) == RUN_C_SHA, 'Changed official C reference')
    check_model(model)
    check_tokenizer((directory/'assets/tok512.bin').read_bytes())
    projections = projection_layout()
    require(report['projections'] == projections, 'Changed source projection layout')
    expected = {(p['name'], first) for p in projections for first in range(0, p['outputs'], 32)}
    actual = {(t['projection'], t['first_output']) for t in report['tiles']}
    require(actual == expected and len(report['tiles']) == 116, 'Missing/duplicate projection tiles')
    address = WEIGHTS
    by_name = {p['name']: p for p in projections}
    expected_files = {'assets/stories260K.bin', 'assets/tok512.bin', 'reference/run.c',
                      'reference/LICENSE', 'source/prepare.py'}
    for tile in report['tiles']:
        projection = by_name[tile['projection']]
        first = tile['first_output']
        raw = pack_tile(model, projection, first)
        ai = (projection['inputs']+31)//32*32
        filename = f'weights/{projection["name"]}-{first:04d}.bin'
        expected_files.add(filename)
        expected_tile = dict(projection=projection['name'], first_output=first,
            logical_outputs=min(32, projection['outputs']-first), logical_inputs=projection['inputs'],
            rows=1, ai=ai, ao=32, address=address, bytes=len(raw), file=filename,
            cmac_frames=2*(ai//32), native_output_bytes=128,
            required_hardware_compaction=[dict(source_halfword=0, destination_halfword=first, count=16),
                                          dict(source_halfword=32, destination_halfword=first+16, count=16)])
        require(tile == expected_tile, 'Changed physical tile/compaction contract')
        require((directory/tile['file']).read_bytes() == raw and tile['address'] == address and tile['bytes'] == len(raw),
                'Changed packed weight bytes/address')
        address += len(raw)
    require(set(report['files']) == expected_files, 'Changed prepared-file inventory')
    require(address-WEIGHTS == report['packed_weights_bytes'] == 557056, 'Changed weight allocation')
    buffers = report['candidate_buffers']
    require(buffers == dict(input=dict(address=BASE, bytes=4096), native_output=dict(address=BASE+4096, bytes=4096),
        linear_output=dict(address=BASE+8192, bytes=4096), unity=dict(address=BASE+12288, bytes=4096),
        weights=dict(address=WEIGHTS, bytes=557056), command=dict(address=0x100e0000, bytes=65536),
        tasks=dict(address=0x100f0000, bytes=16384)), 'Changed candidate device allocation')
    ranges = sorted((v['address'], v['address']+v['bytes']) for v in buffers.values())
    require(all(BASE <= start < end <= BASE+CAPACITY for start, end in ranges)
            and all(a[1] <= b[0] for a, b in zip(ranges, ranges[1:])), 'Overlapping/escaping candidate BOs')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--tokenizer', type=Path, required=True)
    parser.add_argument('--llama2c', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.model, args.tokenizer, args.llama2c, args.out)
    print(result['status'], 'projections=36 tiles=116 packed_weights=557056')


if __name__ == '__main__':
    main()
