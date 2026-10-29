#!/usr/bin/env python3
"""Read-only logical-to-physical ROM/RAM address and data wiring audit.

Uses literal n_<mapped-wire-id> aliases, not signal guessing or execution
fixups. Reuses the completed all-cell consumer/INIT audit with explicit
bindings. This does not prove ownership, write-before-read, reset/startup,
native FASM, full circuit equivalence, timing or physical-board acceptance.
"""
import json
import mmap
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_prefix_bram_outputs import ROOT, TOP, PREPARED, INVENTORY, SELECTED, MODEL, ROM
from audit_prefix_config_contract import bram_contract
from pack_prefix_board import digest, timestamp, verify_prepared_metadata
from evidence import source_revision

CONSUMER = ROOT / 'build/openxc7/prefix-bram-output-audit-1791406793437962391/report.json'
HIERARCHY = ROOT / 'build/rknpu-dsp-prefix-observed-board-mapping/1791308955335106261/mapped_hierarchy.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_memory_wiring_control.py'
WIDTHS = {'demo.rom.value': 32, 'demo.rom.index': 12, 'demo.index': 12,
          'demo.initial_value': 16, 'demo.expected_value': 16,
          'demo.memory.host_index': 12, 'demo.memory.host_wdata': 16,
          'demo.memory.host_rdata': 16, 'demo.memory.translated': 12,
          'demo.mem_req_wdata': 16, 'demo.mem_rsp_rdata': 16, 'demo.memory.clk': 1}


def netname_region(data):
    start = data.find(b'\n    ' + json.dumps(TOP).encode() + b': {')
    assert start >= 0, 'Missing literal top module'
    end = data.find(b'\n    }', start)
    nets = data.find(b'      "netnames": {', start, end)
    assert end > start and nets > start, 'Unsupported top module/netname format'
    return nets, end


def named_net(data, name, region):
    start, limit = region
    needle = b'        ' + json.dumps(name).encode() + b': {'
    pos = data.find(needle, start, limit)
    assert pos >= 0 and data.find(needle, pos + len(needle), limit) < 0, 'Missing/duplicate literal net alias: ' + name
    end = data.find(b'\n        }', pos, limit)
    assert end > pos, 'Incomplete literal net alias'
    result = json.loads(b'{' + data[pos:end + len(b'\n        }')] + b'}')[name]
    assert not set(result) - {'hide_name', 'bits', 'attributes'}, 'Unmodeled net offset/direction'
    assert result['bits'] and all(type(b) is int and b >= 2 for b in result['bits']), 'Non-wire semantic net alias'
    return result


def translated_signals(original, physical):
    source_region, physical_region = netname_region(original), netname_region(physical)
    mappings, signals = {}, {}
    for name, width in WIDTHS.items():
        record = named_net(original, name, source_region)
        assert record['hide_name'] == 0 and len(record['bits']) == width, 'Changed semantic signal width'
        assert len(set(record['bits'])) == width, 'Aliased semantic bus bits'
        signals[name] = []
        for bit in record['bits']:
            if bit not in mappings:
                alias = named_net(physical, 'n_' + str(bit), physical_region)
                assert len(alias['bits']) == 1, 'Non-scalar physical wire alias'
                mappings[bit] = alias['bits'][0]
            signals[name].append(mappings[bit])
    assert len(set(mappings.values())) == len(mappings), 'Non-bijective selected wire translation'
    return signals, mappings


def lanes(connections, port, direction):
    data, parity = {('A', 'out'): ('DOADO', 'DOPADOP'), ('B', 'out'): ('DOBDO', 'DOPBDOP'),
                    ('A', 'in'): ('DIADI', 'DIPADIP'), ('B', 'in'): ('DIBDI', 'DIPBDIP')}[port, direction]
    return connections[data][:8] + connections[parity][:1]


def verify_wiring(brams, classification, signals):
    assert len(brams) == 6 and set(brams) == set(classification)
    assert set(signals) == set(WIDTHS)
    for name, width in WIDTHS.items():
        assert len(signals[name]) == width and len(set(signals[name])) == width
        assert all(type(b) is int and b >= 2 for b in signals[name])
    assert signals['demo.rom.value'] == signals['demo.initial_value'] + signals['demo.expected_value']
    assert signals['demo.rom.index'] == signals['demo.index'] == signals['demo.memory.host_index']
    assert signals['demo.memory.host_wdata'] == signals['demo.initial_value']
    roms, rams = {}, {}
    for name, cell in brams.items():
        bram_contract(cell)
        c, p, info = cell['connections'], cell['parameters'], classification[name]
        assert c['ADDRARDADDR'] == ['0'] * 3 + signals['demo.index'] + ['1'], 'Changed ROM/host address mapping'
        assert c['CLKARDCLK'] == signals['demo.memory.clk'], 'Changed BRAM A clock wiring'
        if info['readonly']:
            offset = info['source_ROM_slice_match_offset']
            assert offset in (0, 9, 18, 27) and offset not in roms, 'Missing/duplicate source-ROM slice'
            width = min(9, 32 - offset)
            assert info['directly_consumed_memory_lanes'] == list(range(width))
            assert all(int(p[k], 2) == 0 for k in ('WRITE_WIDTH_A', 'WRITE_WIDTH_B', 'READ_WIDTH_B'))
            assert c['ENARDEN'] == ['1'] and c['ENBWREN'] == ['0']
            assert c['WEA'] == ['0'] * 4 and c['WEBWE'] == ['0'] * 8, 'Writable source-ROM primitive'
            assert lanes(c, 'A', 'out')[:width] == signals['demo.rom.value'][offset:offset + width], 'Reordered ROM data/parity bits'
            roms[offset] = name
        else:
            width = len(info['directly_consumed_memory_lanes'])
            assert width in (9, 7) and width not in rams
            assert info['directly_consumed_memory_lanes'] == list(range(width))
            assert all(int(p[k], 2) == 9 for k in ('READ_WIDTH_A', 'READ_WIDTH_B', 'WRITE_WIDTH_A', 'WRITE_WIDTH_B'))
            offset = 0 if width == 9 else 9
            assert c['ADDRBWRADDR'] == ['0'] * 3 + signals['demo.memory.translated'] + ['1'], 'Changed core address mapping'
            assert c['CLKBWRCLK'] == signals['demo.memory.clk'], 'Changed BRAM B clock wiring'
            for port, direction, signal in (
                ('A', 'in', 'demo.memory.host_wdata'), ('A', 'out', 'demo.memory.host_rdata'),
                ('B', 'in', 'demo.mem_req_wdata'), ('B', 'out', 'demo.mem_rsp_rdata')):
                assert lanes(c, port, direction)[:width] == signals[signal][offset:offset + width], 'Changed working-RAM data/parity wiring: ' + signal
            rams[width] = name
    assert set(roms) == {0, 9, 18, 27} and set(rams) == {9, 7}
    return dict(ROM_by_logical_bit_offset=roms, working_RAM_by_consumed_width=rams,
                all_32_ROM_data_bits_wired=True, all_16_working_RAM_data_bits_wired=True,
                all_12_address_bits_wired=True, clock_pin_wiring_matched=True,
                enables_and_write_ownership_proved=False, write_before_read_proved=False,
                observable_startup_reset_independence_proved=False)


def main():
    out = ROOT / f'build/openxc7/prefix-memory-wiring-audit-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), scope=__doc__, commands=[],
                  python_version=platform.python_version(), entire_upstream_chain_revalidated=False,
                  expected_vectors_used_for_execution=False, numerical_acceptance=False,
                  native_PNR_FASM_executed=False, physical_fit_verified=False, timing_signoff=False,
                  electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    save(); print(out / 'report.json', flush=True)
    try:
        prepared, inventory, consumer = (json.loads(p.read_text()) for p in (PREPARED, INVENTORY, CONSUMER))
        verify_prepared_metadata(prepared)
        assert consumer['status'] == 'AUDITED_FULL_BRAM_OUTPUT_CONSUMERS_AND_INIT_WITH_STARTUP_GAP_NOT_FASM_OR_SIGNOFF'
        assert inventory['status'] == 'AUDITED_ACTUAL_FULL_PREFIX_DSP_BRAM_CONFIGURATION_WITH_EXPLICIT_GAPS_NOT_FASM_OR_SIGNOFF'
        physical = ROOT / prepared['pack_input']
        bound = CONSUMER.parent / 'actual-BRAM-output-consumers.json'
        for p in (physical, SELECTED, MODEL, ROM):
            assert digest(p) == consumer['source'][str(p.resolve())], 'Changed completed consumer-audit input'
        assert digest(HIERARCHY) == prepared['source'][str(HIERARCHY.resolve())]
        assert digest(bound) == consumer['artifacts'][str(bound.relative_to(ROOT))]
        paths = {Path(__file__).resolve(), CONTROL, PREPARED, INVENTORY, CONSUMER, bound, HIERARCHY, physical,
                 SELECTED, MODEL, ROM, ROOT / 'tools/cmac/export_dsp_prefix_board_netlist.py',
                 ROOT / 'tools/cmac/gen_array_board.py'}
        paths.update(ROOT / 'rtl/cmac' / n for n in ('rk_cmac_array_bram_demo.sv', 'rk_cmac_demo_memory.sv', 'rk_cmac_array_demo_rom.sv'))
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        before = {str(p): digest(p) for p in sorted(paths)}
        report.update(source=before, production_source_before=source_revision(), completed_consumer_audit=str(CONSUMER.relative_to(ROOT)))
        for p in paths:
            if p.is_relative_to(ROOT) and p.suffix == '.py':
                frozen = out / 'sources' / p.relative_to(ROOT)
                frozen.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, frozen)
        for label, argv in (('controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
                            ('generated_check', ['make', 'generated-check']),
                            ('ROM_consistency_readonly', [sys.executable, 'tools/cmac/gen_array_board.py', '--check'])):
            step = dict(label=label, argv=argv, log=str(out / (label + '.log')), status='RUNNING')
            report['commands'].append(step); save(); start = time.monotonic()
            try:
                with Path(step['log']).open('w') as stream:
                    result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300, check=False)
                step['returncode'] = result.returncode
                assert result.returncode == 0, Path(step['log']).read_text()[-3000:]
                step['status'] = 'PASS_SOFTWARE_ONLY'
            except BaseException:
                step['status'] = 'FAIL'; raise
            finally: step['seconds'] = round(time.monotonic() - start, 3); save()
        report['stage'] = 'actual_alias_and_wiring_audit'; save()
        with HIERARCHY.open('rb') as a, mmap.mmap(a.fileno(), 0, access=mmap.ACCESS_READ) as original, \
             physical.open('rb') as b, mmap.mmap(b.fileno(), 0, access=mmap.ACCESS_READ) as flattened:
            signals, mappings = translated_signals(original, flattened)
        selected = json.loads(SELECTED.read_text())
        brams = {n: c for n, c in selected.items() if c['type'] == 'RAMB36E1'}
        checks = verify_wiring(brams, consumer['BRAM_memory_classification'], signals)
        output = dict(logical_signal_physical_wires=signals, original_wire_to_physical_wire=mappings, wiring_checks=checks)
        (out / 'actual-memory-wire-bindings.json').write_text(json.dumps(output, indent=2, sort_keys=True) + '\n')
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed memory wiring audit input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(wiring_checks=checks, literal_wire_aliases_compared=len(mappings), stage='complete',
                      status='AUDITED_FULL_ROM_AND_WORKING_RAM_ADDRESS_DATA_WIRING_NOT_STARTUP_OR_FASM_SIGNOFF')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
