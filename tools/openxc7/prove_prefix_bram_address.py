#!/usr/bin/env python3
"""Prove the actual full physical-input BRAM address/accepted-request cone.

Trace only exact mapped wire aliases and complete primitive drivers. Compare
all twelve translated bits, ready and mapped core-fire against the fixed raw
device-address apertures over every binary address/control assignment. Use
unchanged pinned UNISIM combinational models and a real wrong-golden negative.
The cut is combinational: no temporal ownership, write-before-read, startup,
full-board numerical, P&R/timing/DRC/electrical or bitstream acceptance follows.
No hardware input, RTL, live job, old gate or SHA256SUMS file is modified.
"""
from collections import Counter
import json
import mmap
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_prefix_memory_wiring import HIERARCHY, netname_region, named_net
from audit_prefix_bram_control_wiring import binary_control_contract
from audit_prefix_bram_outputs import PREPARED, INVENTORY
from pack_prefix_board import ROOT, digest, timestamp
from place_prefix_board import bind_report, verify_bindings
from evidence import source_revision

PARENT = ROOT / 'build/openxc7/prefix-bram-control-wiring-1791422081130315089/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_bram_address_control.py'
MODEL_DIR = ROOT / 'tests/vendor/xilinx-unisim/verilog/src/unisims'
MODEL_NAMES = [*(f'LUT{i}' for i in range(1, 7)), 'CARRY4', 'MUXF7', 'MUXF8', 'INV']
WIDTHS = dict(req_addr=32, translated=12, core_fire=1, req_ready=1, req_valid=1, rsp_valid=1, rst_n=1)
INPUTS = ('req_addr', 'req_valid', 'rsp_valid', 'rst_n')
SUCCESS = 'SAT proof finished - no model found: SUCCESS!'
FAILURE = 'SAT proof finished - model found: FAIL!'
PASS = 'PROVED_ACTUAL_FULL_PREFIX_BINARY_BRAM_ADDRESS_AND_ACCEPTED_REQUEST_CONE_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'


def aliases(original, physical):
    a, b = netname_region(original), netname_region(physical)
    result, translated = {}, {}
    for name, width in WIDTHS.items():
        record = named_net(original, 'demo.memory.' + name, a)
        assert record['hide_name'] == 0 and len(record['bits']) == width
        assert len(set(record['bits'])) == width, 'Aliased semantic bus bits'
        result[name] = []
        for wire in record['bits']:
            if wire not in translated:
                target = named_net(physical, 'n_' + str(wire), b)
                assert len(target['bits']) == 1, 'Non-scalar physical alias'
                translated[wire] = target['bits'][0]
            result[name].append(translated[wire])
    assert len(set(translated.values())) == len(translated), 'Non-bijective selected aliases'
    return result


def indexed_cells(data):
    # Same complete pretty-format records as primitive_cells; offsets avoid
    # retaining the half-million-cell design just to find a small driver cone.
    seen = set()
    for match in re.finditer(rb'^          "type": "([^"\n]+)",$', data, re.MULTILINE):
        start = data.rfind(b'\n        "', 0, match.start())
        end = data.find(b'\n        }', match.end()) + len(b'\n        }')
        assert start >= 0 and end > match.end(), 'Incomplete cell record'
        record = json.loads(b'{' + data[start + 1:end] + b'}')
        assert len(record) == 1
        name, cell = next(iter(record.items()))
        assert name not in seen and cell['type'] == match.group(1).decode('ascii')
        assert set(cell['port_directions']) == set(cell['connections'])
        seen.add(name)
        yield name, cell, start, end


def driver_index(data, expected_counts):
    drivers, counts = {}, Counter()
    for name, cell, start, end in indexed_cells(data):
        counts[cell['type']] += 1
        for pin, bits in cell['connections'].items():
            direction = cell['port_directions'][pin]
            assert direction in ('input', 'output', 'inout')
            if direction == 'input': continue
            for bit, wire in enumerate(bits):
                assert type(wire) is int and wire >= 2, 'Constant/unknown primitive output'
                assert wire not in drivers, 'Multiple primitive output drivers'
                drivers[wire] = (start, end, name, pin, bit, direction)
    assert dict(counts) == expected_counts, 'Incomplete/changed full primitive census'
    return drivers, dict(counts)


def validate_cell(cell):
    kind, c, d, p = cell['type'], cell['connections'], cell['port_directions'], cell['parameters']
    if re.fullmatch(r'LUT[1-6]', kind):
        width = int(kind[-1]); inputs = {f'I{i}': 1 for i in range(width)}; outputs = {'O': 1}
        assert set(p) == {'INIT'} and re.fullmatch('[01]+', p['INIT'])
        assert len(p['INIT']) >= 1 << width and len(p['INIT']) <= 64, 'Invalid LUT truth table'
    elif kind == 'CARRY4':
        inputs = dict(CI=1, CYINIT=1, DI=4, S=4); outputs = dict(CO=4, O=4); assert p == {}
    elif kind in ('MUXF7', 'MUXF8'):
        inputs = dict(I0=1, I1=1, S=1); outputs = dict(O=1); assert p == {}
    elif kind == 'INV':
        inputs = dict(I=1); outputs = dict(O=1); assert p == {}
    else: raise AssertionError('Unsupported/sequential address-cone primitive: ' + kind)
    assert set(c) == set(d) == set(inputs) | set(outputs), 'Unmodeled primitive pin'
    assert d == {**{pin: 'input' for pin in inputs}, **{pin: 'output' for pin in outputs}}
    for pin, width in {**inputs, **outputs}.items():
        assert len(c[pin]) == width, 'Changed primitive pin width'
        assert all(w in ('0', '1') or type(w) is int and w >= 2 for w in c[pin]), 'Unknown/high-impedance cone wire'
    return inputs, outputs


def trace_cone(signals, get_driver):
    assert set(signals) == set(WIDTHS)
    assert all(len(signals[k]) == WIDTHS[k] for k in WIDTHS)
    cuts = {w for k in INPUTS for w in signals[k]}
    assert len(cuts) == 35 and all(type(w) is int and w >= 2 for w in cuts), 'Changed independent semantic cut'
    nodes, visited = {}, set()
    def visit(wire, stack):
        if wire in ('0', '1') or wire in cuts or wire in visited: return
        assert type(wire) is int and wire >= 2 and wire not in stack, 'Unknown/cyclic address-cone wire'
        name, cell, pin, bit = get_driver(wire)
        ins, outs = validate_cell(cell)
        assert pin in outs and cell['connections'][pin][bit] == wire
        assert name not in nodes or nodes[name] == cell, 'Changed selected driver'
        nodes[name] = cell
        for port in ins:
            for upstream in cell['connections'][port]: visit(upstream, stack | {wire})
        visited.add(wire)
    for name in ('translated', 'core_fire', 'req_ready'):
        for wire in signals[name]: visit(wire, set())
    assert nodes, 'Empty address cone'
    return nodes


def miter(signals, nodes):
    cuts = {w: f'{k}[{i}]' if WIDTHS[k] > 1 else k for k in INPUTS for i, w in enumerate(signals[k])}
    def bit(w): return "1'b" + w if w in ('0', '1') else cuts.get(w, 'w_' + str(w))
    def bus(bits): return '{' + ','.join(bit(w) for w in reversed(bits)) + '}'
    wires = {w for cell in nodes.values() for bits in cell['connections'].values() for w in bits
             if type(w) is int and w not in cuts}
    lines = ['module prefix_bram_address_miter #(parameter NEGATIVE=0) (',
             'input [31:0] req_addr, input req_valid,rsp_valid,rst_n, output ok);']
    lines.extend('wire w_' + str(w) + ';' for w in sorted(wires))
    for i, (name, cell) in enumerate(sorted(nodes.items())):
        ins, outs = validate_cell(cell)
        assert not any(w in cuts for pin in outs for w in cell['connections'][pin]), 'Cut wire also driven by retained cone cell'
        parameter = ''
        if cell['type'].startswith('LUT'):
            init = cell['parameters']['INIT']; parameter = ' #(.INIT(' + str(len(init)) + "'b" + init + '))'
        lines.append(cell['type'] + parameter + ' mapped_' + str(i) + '(' + ','.join(
            '.' + pin + '(' + bus(bits) + ')' for pin, bits in sorted(cell['connections'].items())) + ');')
    lines += ['wire aligned = !req_addr[0];',
        "wire aperture0 = req_addr >= 32'h10010000 && req_addr < 32'h100101c0;",
        "wire aperture1 = req_addr >= 32'h10020000 && req_addr < 32'h10021840;",
        "wire aperture2 = req_addr >= 32'h10040000 && req_addr < 32'h10040140;",
        "wire aperture3 = req_addr >= 32'h100e0000 && req_addr < 32'h100e01c0;",
        'wire expected_mapped = aligned && (aperture0 || aperture1 || aperture2 || aperture3);',
        'wire [31:0] byte_offset = !aligned ? 0 :',
        "aperture0 ? req_addr - 32'h10010000 :",
        "aperture1 ? req_addr - 32'h10020000 + 32'd448 :",
        "aperture2 ? req_addr - 32'h10040000 + 32'd6656 :",
        "aperture3 ? req_addr - 32'h100e0000 + 32'd6976 : 0;",
        'wire [11:0] expected_translated = byte_offset[12:1];',
        'wire expected_ready = rst_n && !rsp_valid;',
        'wire expected_fire = req_valid && expected_ready && expected_mapped;',
        'wire [13:0] actual = {' + bit(signals['core_fire'][0]) + ',' + bit(signals['req_ready'][0]) + ',' + bus(signals['translated']) + '};',
        "wire [13:0] expected = {expected_fire,expected_ready,expected_translated} ^ (NEGATIVE ? 14'h1 : 14'h0);",
        'assign ok = actual == expected;', 'endmodule']
    text = '\n'.join(lines) + '\n'
    assert not re.search(r'\b(?:assume|anyseq|anyconst|force)\b', text)
    return text


def validate_result(text, code, negative):
    assert not re.search(r'(?im)warning:|timed out|timeout reached|unknown cell', text)
    if negative:
        assert code != 0 and FAILURE in text and SUCCESS not in text
        assert re.findall(r'(?m)^ERROR: (.*)$', text) == ['Called with -verify and proof did fail!']
    else:
        assert code == 0 and text.count(SUCCESS) == 1 and FAILURE not in text and not re.search('ERROR:', text)


def main():
    out = ROOT / f'build/openxc7/prefix-bram-address-proof-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], python_version=sys.version, seed=None,
        symbolic_binary_input_bits=35, compared_output_bits=14, input_assumptions=[],
        production_source_before=source_revision(), full_target_parallel_products=512,
        entire_upstream_chain_revalidated=False, native_PNR_executed=False,
        temporal_port_ownership_proved=False, write_before_read_proved=False,
        observable_startup_reset_independence_proved=False, full_board_numerical_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, comparison_view_used_for_execution=False)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, negative=None):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(ROOT),
                    status='RUNNING', timeout_seconds=180)
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=180)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            if negative is not None: validate_result(text, code, negative)
            else: assert code == 0 and not re.search(r'(?im)^(?:WARNING|ERROR|FAILED|FATAL)\b', text), text[-4000:]
            step['status'] = 'PASS_EXPECTED_FORMAL_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    save(); print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        parent = json.loads(PARENT.read_text()); inventory = json.loads(INVENTORY.read_text()); prepared = json.loads(PREPARED.read_text())
        assert parent['status'] == 'AUDITED_FULL_BRAM_ENABLE_AND_LOCAL_BINARY_WRITE_GATING_NOT_TEMPORAL_STARTUP_OR_SIGNOFF'
        assert parent['stage'] == 'complete' and parent['finished_utc']
        before = {}; bind_report(PARENT, parent, before)
        physical = (ROOT / prepared['pack_input']).resolve(strict=True)
        assert before[str(physical)] == prepared['artifacts'][str(physical.relative_to(ROOT))]
        files = {Path(__file__).resolve(), CONTROL, PARENT, INVENTORY, PREPARED, HIERARCHY, physical,
                 Path(sys.executable).resolve(), Path(shutil.which('yosys')).resolve(),
                 *(MODEL_DIR / (name + '.v') for name in MODEL_NAMES)}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            sha = digest(path); assert str(path) not in before or before[str(path)] == sha; before[str(path)] = sha
        verify_bindings(before); report['source'] = before
        shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
        report['stage'] = 'software_controls'; save()
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        report['tool_version'] = run('yosys_version', ['yosys', '-V']).strip()
        report['stage'] = 'actual_full_driver_census_and_address_cone'; save()
        with HIERARCHY.open('rb') as a, mmap.mmap(a.fileno(), 0, access=mmap.ACCESS_READ) as logical, \
             physical.open('rb') as b, mmap.mmap(b.fileno(), 0, access=mmap.ACCESS_READ) as actual:
            signals = aliases(logical, actual)
            drivers, counts = driver_index(actual, inventory['actual_primitive_counts'])
            def get_driver(wire):
                assert wire in drivers, 'Missing actual primitive driver'
                start, end, name, pin, bit, direction = drivers[wire]
                assert direction == 'output', 'Bidirectional address-cone driver'
                cell = json.loads(b'{' + actual[start + 1:end] + b'}')[name]
                return name, cell, pin, bit
            nodes = trace_cone(signals, get_driver)
        del drivers
        (out / 'actual-address-cone.json').write_text(json.dumps(dict(signals=signals, cells=nodes, full_primitive_counts=counts), indent=2) + '\n')
        source = out / 'actual-address-miter.v'; source.write_text(miter(signals, nodes))
        report.update(actual_cone_cells=len(nodes), actual_cone_primitive_counts=dict(Counter(c['type'] for c in nodes.values())),
                      actual_full_primitive_counts=counts, hardware_input_modified=False)
        report['stage'] = 'actual_binary_SAT'; save()
        for kind, negative in (('negative', 1), ('positive', 0)):
            script = out / (kind + '.ys')
            script.write_text('read_verilog -D XIL_XECLIB ' + ' '.join(str(MODEL_DIR / (name + '.v')) for name in MODEL_NAMES) + '\n'
                'read_verilog ' + str(source) + '\nchparam -set NEGATIVE ' + str(negative) + ' prefix_bram_address_miter\n'
                'hierarchy -check -top prefix_bram_address_miter\nflatten\nproc\nopt -full\nwreduce\nopt -full\ncheck -assert\n'
                'sat -verify -prove ok 1 -show-inputs -show-outputs -timeout 120 -dump_json ' + str(out / (kind + '-counterexample.json')) + '\n')
            run(kind, ['yosys', '-Q', '-T', '-s', script], bool(negative))
        verify_bindings(before); report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASS, stage='complete', address_decoder_binary_cut_proved=True,
                      mapped_core_fire_binary_cut_proved=True, normal_error_on_invalid_address_gate_preserved=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
