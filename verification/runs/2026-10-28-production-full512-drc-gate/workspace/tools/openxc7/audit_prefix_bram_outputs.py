#!/usr/bin/env python3
"""Read-only full physical-input BRAM consumer/INIT classification.

This checks every primitive's pins and every top-level port for consumers of
the six BRAMs' actual output wires. It distinguishes unconnected memory lanes
from potentially observable unknown INIT bits. It does not prove write-before-
read ownership, startup/reset independence, full ROM wiring or physical FASM.
No comparison data is supplied to the execution path.
"""
from collections import Counter, defaultdict
import json
import mmap
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, TOP, digest, timestamp, verify_prepared_metadata
from audit_prefix_config_contract import PARENT as PREPARED, bram_contract
from evidence import source_revision

INVENTORY = ROOT / 'build/openxc7/prefix-config-contract-1791401020849392343/report.json'
SELECTED = INVENTORY.parent / 'actual-selected-primitives.json'
MODEL = ROOT / 'tests/vendor/xilinx-unisim/verilog/src/unisims/RAMB36E1.v'
ROM = ROOT / 'tests/cmac/array_data/board_rom.hex'
CONTROL = ROOT / 'tests/cmac/test_prefix_bram_output_control.py'


def primitive_cells(data):
    """Parse complete individual cells from the bound Yosys pretty format."""
    seen = set()
    for match in re.finditer(rb'^          "type": "([^"\n]+)",$', data, re.MULTILINE):
        start = data.rfind(b'\n        "', 0, match.start())
        end = data.find(b'\n        }', match.end())
        assert start >= 0 and end > match.end(), 'Incomplete/unsupported cell format'
        record = json.loads(b'{' + data[start + 1:end + len(b'\n        }')] + b'}')
        assert len(record) == 1
        name, cell = next(iter(record.items()))
        assert name not in seen and cell['type'] == match.group(1).decode('ascii')
        assert set(cell['port_directions']) == set(cell['connections'])
        seen.add(name)
        yield name, cell


def module_ports(data):
    start = data.find(b'      "ports": {')
    end = data.find(b'\n      },\n      "cells": {', start)
    assert start >= 0 and end > start, 'Unsupported physical module header'
    return json.loads(b'{' + data[start:end + len(b'\n      }')] + b'}')['ports']


def output_bindings(data, brams, expected_counts=None):
    outputs = {}
    for name, cell in brams.items():
        bram_contract(cell)
        assert {p for p, d in cell['port_directions'].items() if d != 'input'} == {'DOADO', 'DOBDO', 'DOPADOP', 'DOPBDOP'}
        for pin, width in (('DOADO', 32), ('DOBDO', 32), ('DOPADOP', 4), ('DOPBDOP', 4)):
            bits = cell['connections'][pin]
            assert len(bits) == width
            for i, bit in enumerate(bits):
                assert type(bit) is int and bit >= 2 and bit not in outputs, 'Aliased/constant BRAM output'
                outputs[bit] = (name, pin, i)
    consumers, drivers, counts, selected_seen = defaultdict(list), defaultdict(list), Counter(), set()
    for name, cell in primitive_cells(data):
        counts[cell['type']] += 1
        if name in brams:
            assert cell == brams[name], 'Changed selected BRAM record'
            selected_seen.add(name)
        for pin, bits in cell['connections'].items():
            direction = cell['port_directions'][pin]
            assert direction in ('input', 'output', 'inout')
            for i, bit in enumerate(bits):
                if type(bit) is not int or bit not in outputs: continue
                endpoint = dict(cell=name, type=cell['type'], pin=pin, bit=i)
                assert direction != 'inout', 'Unsupported bidirectional BRAM-output consumer'
                (consumers if direction == 'input' else drivers)[bit].append(endpoint)
    assert selected_seen == set(brams), 'Incomplete selected BRAM census'
    if expected_counts is not None: assert dict(counts) == expected_counts, 'Incomplete/changed full primitive census'
    for pin, port in module_ports(data).items():
        for i, bit in enumerate(port['bits']):
            if type(bit) is int and bit in outputs:
                assert port['direction'] == 'output', 'BRAM output aliases a top-level input/inout'
                consumers[bit].append(dict(top_port=pin, bit=i))
    result = {}
    for wire, (name, pin, i) in outputs.items():
        assert drivers[wire] == [dict(cell=name, type='RAMB36E1', pin=pin, bit=i)], 'Missing/multiple BRAM output driver'
        result.setdefault(name, {}).setdefault(pin, []).append(dict(bit=i, wire=wire, consumers=consumers[wire]))
    return dict(counts), result


def memory_words(params):
    required = {f'INIT_{i:02X}' for i in range(128)} | {f'INITP_{i:02X}' for i in range(16)}
    keys = {k for k in params if re.fullmatch(r'INITP?_[0-9A-F]{2}', k)}
    assert keys == required, 'Complete literal 36-kbit INIT required'
    assert all(re.fullmatch('[01x]{256}', params[k]) for k in required)
    data = ''.join(params[f'INIT_{i:02X}'][::-1] for i in range(128))
    parity = ''.join(params[f'INITP_{i:02X}'][::-1] for i in range(16))
    # The pinned UNISIM widest-width=9 path has width=8, widthp=1,
    # mem_depth=4096 and initializes each successive INIT slice LSB-first.
    return [data[8 * i:8 * (i + 1)] + parity[i] for i in range(4096)]


def classify_memory(original, bindings, reference_rom=None):
    bram_contract(original)
    params = original['parameters']
    words = memory_words(params)
    live_lanes = set()
    for port, pins in (('A', ('DOADO', 'DOPADOP')), ('B', ('DOBDO', 'DOPBDOP'))):
        width = int(params['READ_WIDTH_' + port], 2)
        assert width in (0, 9)
        for pin in pins:
            active_width = (8 if pin in ('DOADO', 'DOBDO') else 1) if width else 0
            for entry in bindings[pin]:
                if not entry['consumers']: continue
                assert entry['bit'] < active_width, 'Consumer on an inactive BRAM data lane'
                live_lanes.add(entry['bit'] if pin in ('DOADO', 'DOBDO') else 8)
    stats = Counter()
    for word in words:
        for lane, symbol in enumerate(word):
            stats[('unknown' if symbol == 'x' else 'known') + ('_with_direct_consumer' if lane in live_lanes else '_without_consumer')] += 1
    readonly = all(int(params[k], 2) == 0 for k in ('WRITE_WIDTH_A', 'WRITE_WIDTH_B'))
    result = dict(readonly=readonly, directly_consumed_memory_lanes=sorted(live_lanes),
                  memory_bit_classification=dict(stats), write_before_read_proved=False,
                  observable_startup_reset_independence_proved=False,
                  full_ROM_logical_bit_wiring_verified=False)
    if readonly and reference_rom is not None:
        assert len(reference_rom) == 4096 and live_lanes
        assert not stats['unknown_with_direct_consumer'], 'Unknown ROM bit has a direct consumer'
        offsets = [offset for offset in range(32 - max(live_lanes)) if all(
            word[lane] == str((reference_rom[address] >> (offset + lane)) & 1)
            for address, word in enumerate(words) for lane in live_lanes)]
        assert len(offsets) == 1, 'No unique complete source-ROM slice match'
        result.update(source_ROM_slice_match_offset=offsets[0], source_ROM_words_compared=4096,
                      source_ROM_consumed_bits_compared=4096 * len(live_lanes))
    return result


def main():
    out = ROOT / f'build/openxc7/prefix-bram-output-audit-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), scope=__doc__, commands=[],
        python_version=platform.python_version(), native_PNR_FASM_executed=False,
        expected_vectors_used_for_execution=False, entire_upstream_chain_revalidated=False,
        numerical_acceptance=False, observable_startup_reset_independence_proved=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    save()
    print(out / 'report.json', flush=True)
    try:
        parent, inventory = (json.loads(p.read_text()) for p in (PREPARED, INVENTORY))
        verify_prepared_metadata(parent)
        assert inventory['status'] == 'AUDITED_ACTUAL_FULL_PREFIX_DSP_BRAM_CONFIGURATION_WITH_EXPLICIT_GAPS_NOT_FASM_OR_SIGNOFF'
        physical = ROOT / parent['pack_input']
        assert digest(physical) == parent['artifacts'][str(physical.relative_to(ROOT))]
        assert digest(SELECTED) == inventory['artifacts'][str(SELECTED.relative_to(ROOT))]
        paths = {Path(__file__).resolve(), CONTROL, PREPARED, INVENTORY, physical, SELECTED, MODEL, ROM,
                 ROOT / 'tools/cmac/gen_array_board.py'}
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        before = {str(p): digest(p) for p in sorted(paths)}
        report.update(source=before, physical_input=str(physical.relative_to(ROOT)),
                      production_source_before=source_revision())
        for p in paths:
            if p.is_relative_to(ROOT) and p.suffix == '.py':
                frozen = out / 'sources' / p.relative_to(ROOT)
                frozen.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, frozen)
        save()
        for label, argv in (
            ('controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
            ('generated_check', ['make', 'generated-check']),
            ('ROM_consistency_readonly', [sys.executable, 'tools/cmac/gen_array_board.py', '--check'])):
            step = dict(label=label, argv=argv, status='RUNNING', log=str(out / (label + '.log')))
            report['commands'].append(step); save()
            start = time.monotonic()
            try:
                with Path(step['log']).open('w') as stream:
                    proc = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300, check=False)
                step['returncode'] = proc.returncode
                assert proc.returncode == 0, Path(step['log']).read_text()[-3000:]
                step['status'] = 'PASS_SOFTWARE_ONLY'
            except BaseException:
                step['status'] = 'FAIL'; raise
            finally:
                step['seconds'] = round(time.monotonic() - start, 3); save()
        selected = json.loads(SELECTED.read_text())
        brams = {n: c for n, c in selected.items() if c['type'] == 'RAMB36E1'}
        assert len(brams) == 6
        expected = dict(Counter(parent['primitive_counts']) + Counter(parent['physical_buffer_counts']))
        report['stage'] = 'actual_full_graph_scan'; save()
        start = time.monotonic()
        with physical.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            counts, bindings = output_bindings(data, brams, expected)
        report['graph_scan_seconds'] = round(time.monotonic() - start, 3)
        (out / 'actual-BRAM-output-consumers.json').write_text(json.dumps(bindings, indent=2, sort_keys=True) + '\n')
        reference_rom = [int(line, 16) for line in ROM.read_text().splitlines()]
        assert len(reference_rom) == 4096 and all(0 <= v < 2**32 for v in reference_rom)
        classified = {n: classify_memory(c, bindings[n], reference_rom) for n, c in brams.items()}
        totals = Counter()
        for c in classified.values(): totals.update(c['memory_bit_classification'])
        assert totals['unknown_with_direct_consumer'] + totals['unknown_without_consumer'] == inventory['BRAM_memory_unknown_bits']
        report.update(actual_primitive_counts=counts, BRAM_memory_classification=classified,
                      memory_bit_totals=dict(totals), checked_output_pin_bits=sum(len(entries) for pins in bindings.values() for entries in pins.values()))
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed BRAM-output audit input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='AUDITED_FULL_BRAM_OUTPUT_CONSUMERS_AND_INIT_WITH_STARTUP_GAP_NOT_FASM_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
