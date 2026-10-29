#!/usr/bin/env python3
"""Execute raw layout QWORDs in both simulators, without a backend/device."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.backend.layout import ABI, StaticGather, encode

BASE, SIZE = 0x10000000, 65536
SOURCE, DESTINATION, TABLE, COMMAND = (BASE + x for x in (0x1000, 0x3000, 0x6000, 0xF000))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def case_vectors(case, position):
    """Test-only byte oracle, independent of the encoder's affine expansion."""
    fields = case['rkgather_plans'][position]['fields']
    d = case['logical_dimensions']
    if position == 2:
        elements = case['scratch_bytes'][2] // 2
    else:
        slot = fields['src']['fields']['index']
        elements = d['m'] * d['k'] if slot == 1 else d['k'] * d['n']
    indices = case['expected_indices'][('input_a', 'weight', 'output')[position]]
    plan = StaticGather(fields['count'], fields['base'],
                        tuple(tuple(axis['items']) for axis in fields['axes']['items']), tuple(fields['offsets']['items']))
    return plan, elements, indices


def fixture(directory, plan, elements, indices, *, salt=0, mutate=None, raw_start=None):
    program = encode(plan, source_address=SOURCE, destination_address=DESTINATION,
                     source_bytes=elements * 2, destination_bytes=plan.count * 2,
                     table_address=TABLE, command_address=COMMAND, aperture_base=BASE, aperture_bytes=SIZE)
    memory = bytearray(b'\xa5\x5a' * (SIZE // 2))
    source = tuple(((lane * 40503 + salt) & 65535) for lane in range(elements)) if raw_start is None else tuple(
        raw_start + lane for lane in range(elements))
    memory[SOURCE - BASE:SOURCE - BASE + elements * 2] = struct.pack('<' + 'H' * elements, *source)
    memory[TABLE - BASE:TABLE - BASE + len(program.index_bytes)] = program.index_bytes
    memory[COMMAND - BASE:COMMAND - BASE + 72] = program.command_bytes
    if mutate is not None:
        mutate(memory)
    expected = bytearray(memory)
    output = [0 if lane < 0 else source[lane] for lane in indices]
    expected[DESTINATION - BASE:DESTINATION - BASE + len(output) * 2] = struct.pack('<' + 'H' * len(output), *output)
    directory.mkdir()
    for name, data in (('memory', memory), ('expected', expected)):
        (directory / (name + '.hex')).write_text(''.join(f'{word:04x}\n' for word in struct.unpack('<32768H', data)))
    (directory / 'commands.bin').write_bytes(memory[COMMAND - BASE:COMMAND - BASE + 72])
    return {'count': plan.count, 'source_elements': elements, 'zero_fills': sum(x == -1 for x in indices),
            'source_raw_bits_sha256': hashlib.sha256(struct.pack('<' + 'H' * elements, *source)).hexdigest(),
            'files': {p.name: sha(p) for p in directory.iterdir()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulator', choices=('iverilog', 'verilator'), required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    output = (args.out or ROOT / 'build/backend-layout' / f'{args.simulator}-{time.time_ns()}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / 'rtl/layout/rk_layout_dma.sv', ROOT / 'tests/backend_layout/tb_layout_dma.sv']
    inputs = sources + [ROOT / 'tools/backend/layout.py', ROOT / 'tests/backend_layout/fixtures.json', Path(__file__).resolve()]
    before = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    report = dict(status='RUNNING', simulator=args.simulator, source_hashes_before=before, commands=[], cases=[],
                  seed='0x3588', hardware_accessed=False, vivado_executed=False,
                  scope='Standalone raw-QWORD layout DMA source/native only; no parent, framework runtime, reset or FPGA qualification')
    def interrupted(signum, frame):
        raise InterruptedError('Raw layout native run interrupted by signal ' + str(signum))
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    binary = None
    binary_sha256 = None
    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(name, argv, timeout=180):
        check(all(sha(ROOT / p) == h for p, h in before.items()), 'Inputs changed during native run')
        if binary is not None:
            check(sha(binary) == binary_sha256, 'Compiled simulator image changed')
        log = output / (name + '.log')
        started = time.monotonic()
        with log.open('xb') as stream:
            process = subprocess.Popen(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                rc = process.wait(timeout=timeout)
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                except ProcessLookupError:
                    process.wait()
                raise
        text = log.read_text()
        report['commands'].append(dict(name=name, argv=list(map(str, argv)), returncode=rc,
                                       wall_seconds=time.monotonic()-started, timeout_seconds=timeout,
                                       log=str(log.relative_to(ROOT)), log_sha256=sha(log)))
        save()
        check(rc == 0, f'{name} failed: {text[-5000:]}')
        return text
    save()
    try:
        tools = {}
        for name in (('iverilog', 'vvp') if args.simulator == 'iverilog' else ('verilator',)):
            executable = shutil.which(name)
            check(executable is not None, 'UNAVAILABLE: ' + name)
            tools[name] = executable
            text = run(name + '_version', [executable, '--version' if name == 'verilator' else '-V'])
            report.setdefault('tool_versions', {})[name] = dict(path=executable, sha256=sha(executable), text=text)
        if args.simulator == 'iverilog':
            text = run('compile', [tools['iverilog'], '-g2012', '-Wall', '-s', 'tb_layout_dma', '-o', str(output / 'sim.vvp'),
                                   *map(str, sources)])
            command = [tools['vvp'], str(output / 'sim.vvp')]
        else:
            text = run('compile', [tools['verilator'], '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                                   '--top-module', 'tb_layout_dma', '--Mdir', str(output / 'obj'), '-o', 'sim', *map(str, sources)])
            command = [str(output / 'obj/sim')]
        check(not re.search(r'(?im)%Warning|warning:|sorry:', text), 'Unreviewed native diagnostics')
        binary = output / ('sim.vvp' if args.simulator == 'iverilog' else 'obj/sim')
        binary_sha256 = sha(binary)
        report['simulator_image'] = dict(path=str(binary.relative_to(ROOT)), sha256=binary_sha256)
        cases = json.loads((ROOT / 'tests/backend_layout/fixtures.json').read_text())['cases']
        jobs = []
        total_indices = 0
        for case in cases:
            for position, label in enumerate(('input_a', 'weight', 'output')):
                plan, elements, indices = case_vectors(case, position)
                total_indices += len(indices)
                jobs.append((case['name'] + '_' + label, plan, elements, indices, {}))
        check(len(jobs) == 18 and total_indices == 16897, 'Incomplete captured layout census')
        # Across 16 independent permutations every raw halfword, including all
        # NaN payloads, signed zero, subnormals and infinities, is transported.
        for bank in range(16):
            jobs.append((f'raw_bits_{bank}', StaticGather(4096, axes=((1, 4096, 1),)), 4096,
                         list(range(4096)), dict(raw_start=bank * 4096)))
        small = StaticGather(1, offsets=(0,))
        def change_word(index, value=None, key=None):
            def apply(memory):
                offset = COMMAND - BASE + index * 8
                old, = struct.unpack_from('<Q', memory, offset)
                new = old if value is None else (old & 0xFFFF00000000FFFF) | (value << 16)
                if key is not None:
                    new = (new & 0x0000FFFFFFFF0000) | ((key >> 16) << 48) | (key & 65535)
                struct.pack_into('<Q', memory, offset, new)
            return apply
        negative = []
        for word in range(9):
            negative.append((f'bad_key_{word}', 2, 0, dict(mutate=change_word(word, key=0xFF020000 | word * 4)), []))
            negative.append((f'bad_register_{word}', 2, 0,
                             dict(mutate=change_word(word, key=0xFF010000 | (word * 4 + 2))), []))
        for word, value in ((0, ABI ^ 1), (6, 1), (7, 1), (8, 0)):
            negative.append((f'bad_value_{word}', 2, 0, dict(mutate=change_word(word, value)), []))
        for name, word, value in (('source_alignment', 1, SOURCE + 1), ('destination_alignment', 2, DESTINATION + 1),
                                  ('table_alignment', 3, TABLE + 2), ('source_below', 1, BASE - 2),
                                  ('source_wrap', 1, 0xFFFFFFFE), ('destination_wrap', 2, 0xFFFFFFFE),
                                  ('table_wrap', 3, 0xFFFFFFFC), ('count_zero', 4, 0), ('count_huge', 4, 0xFFFFFFFF),
                                  ('source_zero', 5, 0), ('source_huge', 5, 0xFFFFFFFF),
                                  ('overlap_source_destination', 2, SOURCE), ('overlap_source_table', 3, SOURCE),
                                  ('overlap_source_command', 1, COMMAND), ('overlap_destination_table', 2, TABLE),
                                  ('overlap_destination_command', 2, COMMAND), ('overlap_table_command', 3, COMMAND)):
            negative.append((name, 3, 0, dict(mutate=change_word(word, value)), []))
        def bad_index(memory):
            struct.pack_into('<I', memory, TABLE - BASE, 1)
        negative.append(('index_outside_source', 4, 0, dict(mutate=bad_index), []))
        for name, extra in (('bad_amount', ['+amount=8']), ('extra_word', ['+amount=10']),
                            ('unaligned_command', [f'+address={COMMAND+8:x}']),
                            ('command_wrap', ['+address=fffffff0'])):
            negative.append((name, 1, 0, {}, extra))
        for name, mode, code in (('request_timeout', 1, 8), ('response_timeout', 2, 8), ('command_error', 3, 5),
                                  ('unsolicited_response', 5, 7), ('source_error', 6, 5), ('write_error', 7, 5)):
            negative.append((name, code, mode, {}, []))
        if args.simulator == 'iverilog':
            negative.append(('unknown_read_data', 6, 4, {}, []))
        for name, plan, elements, indices, options in jobs:
            directory = output / name
            detail = fixture(directory, plan, elements, indices, **options)
            text = run(name, command + [f'+directory={directory}', f'+count={plan.count}', '+error=0', '+mode=0'])
            check(f'PASS raw_layout mode=0 error=0 lanes={plan.count} epochs=2 ' in text, 'Missing complete positive marker')
            check(all(sha(directory / p) == h for p, h in detail['files'].items()), 'Positive fixture changed during execution')
            report['cases'].append(dict(name=name, status='PASS', error=0, mode=0, **detail))
        for name, code, mode, options, extra in negative:
            directory = output / name
            detail = fixture(directory, small, 1, [0], **options)
            text = run(name, command + [f'+directory={directory}', '+count=1', f'+error={code}', f'+mode={mode}', *extra])
            check(f'PASS raw_layout mode={mode} error={code} lanes=1 ' in text, 'Missing negative marker')
            check(all(sha(directory / p) == h for p, h in detail['files'].items()), 'Negative fixture changed during execution')
            report['cases'].append(dict(name=name, status='PASS', error=code, mode=mode, **detail))
        report.update(status='PASS_RAW_LAYOUT_DMA_NATIVE_ONLY', captured_gathers=18, captured_indices=total_indices,
                      positive_cases=len(jobs), negative_cases=len(negative), exhaustive_raw_halfwords=65536)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['source_hashes_after'] = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
        if report['source_hashes_after'] != before:
            report.update(status='FAIL', error='Native input mutation')
        report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
    check(report['status'] == 'PASS_RAW_LAYOUT_DMA_NATIVE_ONLY', 'Native run did not pass')
    print(json.dumps(dict(status=report['status'], simulator=args.simulator, positive_cases=len(jobs),
                          negative_cases=len(negative), report=str(output / 'report.json'))))


if __name__ == '__main__':
    main()
