#!/usr/bin/env python3
"""Read-only BRAM enable/write-control cone audit, not startup acceptance.

All six primitives and the complete physical-input census are checked. Small
binary LUT cones are evaluated exhaustively at explicit opaque cut wires.
This proves local effective write gating, not cut-wire reachability, the
address decoder, temporal ownership or write-before-read. No execution input,
RTL, netlist, native tool or prior acceptance gate is changed. No SHA256SUMS
manifest is written.
"""
from collections import Counter
from itertools import product
import json
import mmap
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_prefix_memory_wiring import HIERARCHY, netname_region, named_net
from audit_prefix_bram_outputs import ROOT, PREPARED, INVENTORY, SELECTED, primitive_cells
from audit_prefix_config_contract import bram_contract
from pack_prefix_board import digest, timestamp
from place_prefix_board import verify_bindings
from evidence import source_revision

PARENT = ROOT / 'build/openxc7/prefix-memory-wiring-audit-1791408308815007879/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_bram_control_wiring.py'
SIGNALS = ('rst_n', 'req_valid', 'req_ready', 'req_write', 'rsp_valid',
           'host_ready', 'host_write', 'host_rsp_valid', 'core_fire', 'host_fire')
ZERO_PORTS = ('REGCEAREGCE', 'REGCEB', 'RSTRAMARSTRAM', 'RSTRAMB', 'RSTREGARSTREG', 'RSTREGB')


def translate_controls(original, physical):
    a, b = netname_region(original), netname_region(physical)
    result, aliases = {}, {}
    for signal in SIGNALS:
        record = named_net(original, 'demo.memory.' + signal, a)
        assert record['hide_name'] == 0 and len(record['bits']) == 1, 'Changed scalar control alias'
        source = record['bits'][0]
        alias = named_net(physical, 'n_' + str(source), b)
        assert len(alias['bits']) == 1, 'Non-scalar physical control alias'
        result[signal] = alias['bits'][0]
        aliases[source] = alias['bits'][0]
    assert len(set(result.values())) == len(SIGNALS), 'Aliased distinct control signals'
    return result, aliases


def control_roots(brams, classification, signals):
    assert set(signals) == set(SIGNALS)
    assert all(type(w) is int and w >= 2 for w in signals.values())
    assert len(set(signals.values())) == len(signals)
    assert len(brams) == 6 and set(brams) == set(classification), 'Changed BRAM membership'
    roots = {signals[k] for k in ('req_ready', 'host_ready', 'core_fire', 'host_fire')}
    ram_names = []
    for name, cell in brams.items():
        bram_contract(cell)
        c = cell['connections']
        assert all(c[p] == ['0'] for p in ZERO_PORTS), 'Changed reset/register-enable policy'
        if classification[name]['readonly']:
            assert c['ENARDEN'] == ['1'] and c['ENBWREN'] == ['0']
            assert c['WEA'] == ['0'] * 4 and c['WEBWE'] == ['0'] * 8, 'Writable source ROM'
            assert all(int(cell['parameters'][p], 2) == 0 for p in ('WRITE_WIDTH_A', 'WRITE_WIDTH_B'))
            continue
        ram_names.append(name)
        assert c['ENARDEN'] == [signals['host_fire']], 'Changed host enable alias'
        assert c['ENBWREN'] == [signals['core_fire']], 'Changed core enable alias'
        assert len(c['WEA']) == 4 and c['WEA'] == [c['WEA'][0]] * 4
        assert len(c['WEBWE']) == 8 and c['WEBWE'][:4] == [c['WEBWE'][0]] * 4
        assert c['WEBWE'][4:] == ['0'] * 4, 'Active unused core write lanes'
        for w in (c['WEA'][0], c['WEBWE'][0]):
            assert type(w) is int and w >= 2, 'Constant/missing working-RAM write control'
            roots.add(w)
        assert all(int(cell['parameters'][p], 2) == 9 for p in ('READ_WIDTH_A', 'READ_WIDTH_B', 'WRITE_WIDTH_A', 'WRITE_WIDTH_B'))
    assert len(ram_names) == 2, 'Wrong working-RAM census'
    return roots, ram_names


def selected_drivers(data, roots, brams, expected_counts):
    counts, drivers, seen_brams = Counter(), {}, set()
    for name, cell in primitive_cells(data):
        counts[cell['type']] += 1
        if name in brams:
            assert cell == brams[name], 'Changed selected BRAM record'
            seen_brams.add(name)
        for pin, bits in cell['connections'].items():
            direction = cell['port_directions'][pin]
            assert direction in ('input', 'output', 'inout')
            if direction == 'input':
                continue
            for wire in bits:
                if type(wire) is not int or wire not in roots:
                    continue
                assert direction == 'output' and wire not in drivers, 'Multiple/bidirectional control driver'
                drivers[wire] = dict(cell=name, output_pin=pin, primitive=cell)
    assert dict(counts) == expected_counts, 'Incomplete/changed full primitive census'
    assert seen_brams == set(brams) and set(drivers) == roots, 'Missing BRAM/control driver'
    return drivers, dict(counts)


def binary_control_contract(brams, classification, signals, drivers):
    roots, rams = control_roots(brams, classification, signals)
    assert set(drivers) == roots, 'Missing/extra control-cone driver'
    nodes = {}
    for wire, record in drivers.items():
        cell = record['primitive']
        c, p, d = cell['connections'], cell['parameters'], cell['port_directions']
        match = re.fullmatch('LUT([1-6])', cell['type'])
        assert match and record['output_pin'] == 'O', 'Unsupported control-cone primitive'
        width = int(match.group(1))
        inputs = ['I' + str(i) for i in range(width)]
        assert set(c) == set(d) == set(inputs + ['O']), 'Unmodeled LUT pin'
        assert d == dict(O='output', **{p: 'input' for p in inputs})
        assert all(len(c[p]) == 1 for p in c) and c['O'] == [wire]
        assert set(p) == {'INIT'} and re.fullmatch('[01]+', p['INIT'])
        assert len(p['INIT']) >= 1 << width, 'Short literal LUT truth table'
        nodes[wire] = (tuple(c[p][0] for p in inputs), int(p['INIT'], 2))
    leaves = {w for inputs, _ in nodes.values() for w in inputs if type(w) is int and w not in nodes}
    leaves.update(signals[k] for k in ('rst_n', 'rsp_valid', 'host_rsp_valid', 'host_write', 'req_valid', 'req_write'))
    assert not leaves & set(nodes), 'Semantic input driven by a selected control output'
    assert all(type(w) is int and w >= 2 for w in leaves)
    assert len(leaves) <= 16, 'Unbounded exhaustive control cut'
    leaves = sorted(leaves)
    evaluated = set()
    def evaluate(wire, values, stack):
        if wire in ('0', '1'):
            return int(wire)
        assert type(wire) is int and wire >= 2, 'Unknown/high-impedance control input'
        if wire in values:
            return values[wire]
        assert wire in nodes and wire not in stack, 'Missing/cyclic control-cone driver'
        inputs, init = nodes[wire]
        index = sum(evaluate(w, values, stack | {wire}) << i for i, w in enumerate(inputs))
        values[wire] = (init >> index) & 1
        evaluated.add(wire)
        return values[wire]
    comparisons = 0
    for bits in product((0, 1), repeat=len(leaves)):
        values = dict(zip(leaves, bits))
        v = {k: evaluate(w, values, set()) for k, w in signals.items()}
        assert v['host_ready'] == (v['rst_n'] and not v['host_rsp_valid']), 'Host ready mismatch'
        assert v['req_ready'] == (v['rst_n'] and not v['rsp_valid']), 'Core ready mismatch'
        assert not v['host_fire'] or v['host_ready'], 'Host fire without ready'
        assert not v['core_fire'] or (v['req_ready'] and v['req_valid']), 'Core fire without accepted request'
        comparisons += 4
        for name in rams:
            c = brams[name]['connections']
            for enable, write, golden in (('ENARDEN', 'WEA', v['host_fire'] and v['host_write']),
                                           ('ENBWREN', 'WEBWE', v['core_fire'] and v['req_write'])):
                effective = evaluate(c[enable][0], values, set()) and evaluate(c[write][0], values, set())
                assert effective == golden, 'Effective BRAM write mismatch: ' + name + '/' + write
                comparisons += 1
    assert evaluated == roots, 'Unused control driver in proof'
    return dict(binary_cut_assignments=1 << len(leaves), binary_assertions_compared=comparisons,
                control_driver_cells=len(drivers), opaque_cut_wires=leaves,
                write_enables_match_declared_fire_and_write=True, ready_reset_response_gating_verified=True,
                fire_requires_ready_verified=True, all_six_BRAM_reset_and_enable_pins_checked=True,
                address_decoder_proved=False, temporal_port_ownership_proved=False,
                write_before_read_proved=False, observable_startup_reset_independence_proved=False)


def main():
    out = ROOT / f'build/openxc7/prefix-bram-control-wiring-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), scope=__doc__, commands=[],
                  software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version),
                  production_source_before=source_revision(), fresh_native_execution=False,
                  full_board_numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
                  electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
                  entire_upstream_chain_revalidated=False)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    save(); print(out / 'report.json', flush=True)
    try:
        parent, prepared, inventory = (json.loads(p.read_text()) for p in (PARENT, PREPARED, INVENTORY))
        assert parent['status'] == 'AUDITED_FULL_ROM_AND_WORKING_RAM_ADDRESS_DATA_WIRING_NOT_STARTUP_OR_FASM_SIGNOFF'
        assert parent['stage'] == 'complete' and parent['finished_utc']
        physical = (ROOT / prepared['pack_input']).resolve(strict=True)
        bound = PARENT.parent / 'actual-memory-wire-bindings.json'
        assert digest(bound) == parent['artifacts'][str(bound.relative_to(ROOT))]
        for path in (physical, HIERARCHY, SELECTED, ROOT / 'rtl/cmac/rk_cmac_demo_memory.sv', ROOT / 'rtl/cmac/rk_cmac_array_bram_demo.sv'):
            assert digest(path) == parent['source'][str(path.resolve())], 'Changed admitted wiring input'
        consumer_path = ROOT / parent['completed_consumer_audit']
        assert digest(consumer_path) == parent['source'][str(consumer_path.resolve())], 'Changed consumer classification report'
        consumer = json.loads(consumer_path.read_text())
        selected = json.loads(SELECTED.read_text())
        brams = {n: c for n, c in selected.items() if c['type'] == 'RAMB36E1'}
        files = {Path(__file__).resolve(), CONTROL, PARENT, PREPARED, INVENTORY, physical, HIERARCHY, SELECTED,
                 bound, consumer_path, Path(sys.executable).resolve(),
                 ROOT / 'rtl/cmac/rk_cmac_demo_memory.sv', ROOT / 'rtl/cmac/rk_cmac_array_bram_demo.sv'}
        files.update(ROOT / f'tests/vendor/xilinx-unisim/verilog/src/unisims/LUT{i}.v' for i in range(1, 7))
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        report['source'] = {str(p): digest(p) for p in sorted(files)}
        verify_bindings(report['source'])
        for path in files:
            if path.is_relative_to(ROOT) and path.suffix == '.py':
                target = out / 'sources' / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target)
        report['stage'] = 'software_controls'
        for label, argv in (('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
                            ('generated_check', ['make', 'generated-check'])):
            log = out / (label + '.log')
            step = dict(label=label, argv=argv, log=str(log), status='RUNNING', timeout_seconds=120)
            report['commands'].append(step); save(); start = time.monotonic()
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            step.update(returncode=result.returncode, seconds=round(time.monotonic() - start, 3), status='PASS_SOFTWARE_ONLY' if result.returncode == 0 else 'FAIL')
            save(); assert result.returncode == 0, log.read_text()[-4000:]
        report['stage'] = 'actual_full_control_wiring_audit'; save(); start = time.monotonic()
        with HIERARCHY.open('rb') as a, mmap.mmap(a.fileno(), 0, access=mmap.ACCESS_READ) as original, \
             physical.open('rb') as b, mmap.mmap(b.fileno(), 0, access=mmap.ACCESS_READ) as flattened:
            signals, aliases = translate_controls(original, flattened)
            roots, _ = control_roots(brams, consumer['BRAM_memory_classification'], signals)
            drivers, counts = selected_drivers(flattened, roots, brams, inventory['actual_primitive_counts'])
        result = binary_control_contract(brams, consumer['BRAM_memory_classification'], signals, drivers)
        output = dict(logical_signal_physical_wires=signals, original_to_physical_wire_aliases=aliases,
                      actual_control_drivers={str(w): c for w, c in drivers.items()}, actual_primitive_counts=counts, checks=result)
        (out / 'actual-BRAM-control-cones.json').write_text(json.dumps(output, indent=2, sort_keys=True) + '\n')
        report.update(checks=result, actual_audit_seconds=round(time.monotonic() - start, 3))
        verify_bindings(report['source'])
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='AUDITED_FULL_BRAM_ENABLE_AND_LOCAL_BINARY_WRITE_GATING_NOT_TEMPORAL_STARTUP_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
