#!/usr/bin/env python3
"""Static whole-BO fixtures for CMAC/EW ownership tests, never runtime repair."""
from pathlib import Path
import argparse
import hashlib
import json
import struct


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def generate(first, output):
    first, output = Path(first).resolve(), Path(output).resolve()
    source = json.loads((first/'report.json').read_text())
    require(source['status'] == 'PREPARED_FIRST_TINYSTORIES_RAW_PROJECTION_AND_COMPACTION_COMMANDS', 'Wrong trained fixture')
    require(source['backend_final_writer_unchanged'] and not source['hardware_accessed'], 'Wrong fixture boundary')
    require(source['model_input'] == dict(token_id=1,layer=0,operator='wq',selected_outputs=[0,32],
            input_precision='FP32 RMSNorm then binary16 RNE'), 'Changed trained input identity')
    for name, record in source['files'].items():
        require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Escaping source fixture')
        require(sha(first/name) == record['sha256'] and (first/name).stat().st_size == record['bytes'], 'Changed source fixture')
    require(not output.exists(), 'Fresh joined-vector directory required')
    output.mkdir(parents=True)
    def words(name):
        return [int(row,16) for row in (first/'fixture'/name).read_text().splitlines()]
    def clone(regions):
        return {a:bytearray(data) for a,data in regions.items()}
    def dump(name, regions):
        (output/name).write_text(''.join(f'{a+i:08x} {int.from_bytes(data[i:i+64],"little"):0128x}\n'
            for a,data in sorted(regions.items()) for i in range(0,len(data),64)))
    def delta(name, old, new):
        changed = {a+i:new[a][i:i+64] for a in new for i in range(0,len(new[a]),64)
                   if old[a][i:i+64] != new[a][i:i+64]}
        (output/name).write_text(''.join(f'{a:08x} {int.from_bytes(data,"little"):0128x}\n' for a,data in sorted(changed.items())))
        return len(changed)
    regions = {
        0x10010000:bytearray(b'\x5a\xa5'*2048),
        0x10020000:bytearray(struct.pack('<2048H',*words('weight.hex'))),
        0x10040000:bytearray(b'\x5a\xa5'*2048),
        0x10050000:bytearray(b'\x5a\xa5'*2048),
        0x10060000:bytearray(struct.pack('<16H',*[0x3c00]*16)+bytes(4064)),
        0x100e0000:bytearray((first/'cmac/command_bo.bin').read_bytes()),
        0x100f0000:bytearray((first/'cmac/task_bo.bin').read_bytes())}
    regions[0x10010000][:128] = struct.pack('<64H',*words('input.hex'))
    require(len(regions[0x100e0000]) == 65536 and len(regions[0x100f0000]) == 4096, 'Changed final-writer BO allocation')
    dump('initial.txt', regions)
    cmac = clone(regions)
    for value in words('writes.hex'):
        address = value>>16
        require(0x10040000 <= address < 0x10040080 and address%2 == 0, 'Escaping numerical write')
        struct.pack_into('<H',cmac[0x10040000],address-0x10040000,value&65535)
    dump('cmac_expected.txt', cmac)
    ew_initial = clone(cmac)
    for address,name in ((0x100e0000,'command_bo.bin'),(0x100f0000,'task_bo.bin')):
        ew_initial[address][:] = (first/'compaction'/name).read_bytes()
    ew_lines = delta('ew_delta.txt', cmac, ew_initial)
    ew = clone(ew_initial)
    ew[0x10050000][:64] = struct.pack('<32H',*[int(v,16) for v in source['expected_fp16']])
    dump('ew_expected.txt', ew)
    repeated = clone(ew)
    for address,name in ((0x100e0000,'command_bo.bin'),(0x100f0000,'task_bo.bin')):
        repeated[address][:] = (first/'cmac'/name).read_bytes()
    repeated[0x10040000][:] = regions[0x10040000]
    repeat_lines = delta('repeat_delta.txt', ew, repeated)
    for value in words('writes.hex'):
        struct.pack_into('<H',repeated[0x10040000],(value>>16)-0x10040000,value&65535)
    dump('repeat_expected.txt', repeated)
    report = dict(status='STATIC_TRAINED_TILE_JOINED_TEST_VECTORS',
        scope='Original complete command/task BOs, exact byte deltas and static test expectations only; no runtime CPU movement',
        lines=sum(len(data)//64 for data in regions.values()), ew_delta_lines=ew_lines, repeat_delta_lines=repeat_lines,
        cmac_amount=45, ew_amount=source['compaction_descriptors'][0]['regcfg_amount'],
        source_report_path=str(first/'report.json'), source_report_sha256=sha(first/'report.json'),
        generator_sha256=sha(__file__),
        files={p.name:sha(p) for p in output.iterdir()})
    require((report['lines'],ew_lines,repeat_lines) == (1408,9,11), 'Changed trained BO/delta inventory')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    result = generate(args.first,args.out)
    print(result['status'],result['lines'],result['ew_delta_lines'],result['repeat_delta_lines'])


if __name__ == '__main__':
    main()
