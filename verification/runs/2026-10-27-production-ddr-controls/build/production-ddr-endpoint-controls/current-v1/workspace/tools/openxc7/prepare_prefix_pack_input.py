#!/usr/bin/env python3
"""Prepare the full admitted mapped board for native packing, not signoff.

Expand all sixteen literal C32 kernels without logic optimization. Add only
two input pads, three output pads and one global clock buffer using Yosys.
Independently undo those physical buffers and require exact primitive,
parameter and pin/wire-incidence identity. No runtime CPU fixups or bits.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[1] / 'cmac')]
from evidence import ROOT, timestamp
from test_fixed_mapped_array import hardware_instance_aliases
from pair_board_luts import implementation_module_aliases
from test_dsp_prefix_observed_mapped_board import verify_mapping_report

TOP = 'ypcb_cmac_array_top'
PARENT = ROOT / 'build/rknpu-dsp-prefix-observed-mapped-board/1791355721215888508/report.json'
EXPECTED_PORTS = {'SYS_CLK': ('input', 1), 'SYS_RSTN': ('input', 1),
                  'led_3bits_tri_o': ('output', 3)}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_stream_manifest(manifest, external=False):
    """Revalidate an existing manifest without loading giant executables."""
    files = manifest['files']
    assert files, 'Empty evidence manifest'
    checked = {}
    for name, sha in files.items():
        path = (ROOT / name).resolve()
        if not external:
            assert not Path(name).is_absolute() and path.is_relative_to(ROOT)
        assert re.fullmatch('[0-9a-f]{64}', sha), 'Invalid evidence digest'
        assert digest(path) == sha, 'Stale evidence: ' + name
        checked[str(path)] = sha
    encoded = ''.join(f'{files[name]}  {name}\n' for name in sorted(files, key=Path))
    assert hashlib.sha256(encoded.encode()).hexdigest() == manifest['sha256']
    return checked


def assert_circuit_identity(before, after):
    """Exact endpoint-preserving wire bijection, using bounded linear storage.

    Unlike materializing sorted tuples for millions of endpoints, retain only
    forward/inverse wire IDs. Each named port bit and cell pin bit must agree;
    both maps forbid wire splitting or merging. Constants cannot be renamed.
    Cell names, types, parameters and pin directions are checked literally.
    Debug net aliases are not electrical endpoints, as in circuit_signature.
    """
    assert set(before['modules']) == set(after['modules'])
    result = {}
    for name, original in before['modules'].items():
        changed = after['modules'][name]
        assert original.get('parameter_default_values', {}) == changed.get('parameter_default_values', {})
        assert set(original['ports']) == set(changed['ports'])
        def hardware(module):
            cells = {}
            metadata = 0
            for cell_name, cell in module['cells'].items():
                if cell['type'] == '$scopeinfo':
                    # The existing literal exporter and circuit_signature
                    # exclude this Yosys debug-only pseudo-cell. Do not allow
                    # a connected primitive to disappear under that label.
                    assert not cell.get('connections'), 'Connected scope metadata'
                    assert not cell.get('port_directions'), 'Scope metadata has pin directions'
                    metadata += 1
                else:
                    cells[cell_name] = cell
            return cells, metadata

        original_cells, original_metadata = hardware(original)
        changed_cells, changed_metadata = hardware(changed)
        assert set(original_cells) == set(changed_cells), 'Changed hardware instance membership'
        forward, inverse = {}, {}
        endpoints = 0

        def compare_bits(left, right):
            nonlocal endpoints
            assert len(left) == len(right), 'Changed pin/port width'
            for a, b in zip(left, right):
                assert type(a) is int or a in ('0', '1', 'x', 'z')
                assert type(b) is int or b in ('0', '1', 'x', 'z')
                endpoints += 1
                if type(a) is not int or type(b) is not int:
                    assert type(a) is type(b) and a == b, 'Changed constant endpoint'
                    continue
                assert forward.setdefault(a, b) == b, 'Split original wire'
                assert inverse.setdefault(b, a) == a, 'Merged original wires'

        for port, value in original['ports'].items():
            assert value['direction'] == changed['ports'][port]['direction']
            compare_bits(value['bits'], changed['ports'][port]['bits'])
        for cell_name, value in original_cells.items():
            other = changed_cells[cell_name]
            assert value['type'] == other['type'], 'Changed primitive type'
            assert value.get('parameters', {}) == other.get('parameters', {}), 'Changed primitive parameters'
            assert value.get('port_directions', {}) == other.get('port_directions', {}), 'Changed pin direction'
            assert set(value['connections']) == set(other['connections']), 'Changed primitive pins'
            for pin, bits in value['connections'].items():
                compare_bits(bits, other['connections'][pin])
        result[name] = dict(cells=len(original_cells), endpoint_bits=endpoints,
                            bijective_wires=len(forward),
                            original_debug_scope_cells=original_metadata,
                            changed_debug_scope_cells=changed_metadata)
    return result


def restore_export_direction_metadata(exported, original):
    """Restore only absent JSON pin annotations from admitted mapped hardware.

    The existing read_verilog export has no primitive definitions and omits
    their port_directions. Connections, types and parameters are not edited.
    Present annotations must match exactly. Actual Yosys library export later
    repeats the independent strict direction check with definitions loaded.
    """
    assert set(exported['modules']) == set(original['modules'])
    restored = {}
    for name, body in exported['modules'].items():
        source = {n: c for n, c in original['modules'][name]['cells'].items()
                  if c['type'] != '$scopeinfo'}
        assert set(body['cells']) == set(source), 'Changed hardware instance membership'
        count = 0
        for cell_name, cell in body['cells'].items():
            previous = source[cell_name]
            assert cell['type'] == previous['type']
            assert cell.get('parameters', {}) == previous.get('parameters', {})
            assert set(cell['connections']) == set(previous['connections'])
            directions = previous['port_directions']
            assert set(directions) == set(previous['connections'])
            assert set(directions.values()) <= {'input', 'output', 'inout'}
            if cell.get('port_directions'):
                assert cell['port_directions'] == directions, 'Explicit export direction mismatch'
            else:
                cell['port_directions'] = dict(directions)
                count += 1
        restored[name] = count
    return restored


def literal_flatten(design, top, kernel, alias_audit=None, constant_audit=None):
    """One explicit hierarchy expansion; no sharing/pruning/defaulting."""
    assert set(design['modules']) == {top, kernel}
    original, body = design['modules'][top], design['modules'][kernel]
    maximum = max(bit for mod in (original, body)
        for bits in [*(v['bits'] for v in mod['ports'].values()),
                     *(v['bits'] for v in mod.get('netnames', {}).values()),
                     *(bits for c in mod['cells'].values() for bits in c['connections'].values())]
        for bit in bits if type(bit) is int)
    next_bit = maximum + 1
    flat = dict(original, cells={}, netnames=dict(original.get('netnames', {})))
    instances = []
    # A repeated formal output bit is one physical driver with multiple
    # boundary endpoints. Its distinct parent fanout nets must be joined,
    # exactly as the HDL assignments do. Never join independent drivers.
    drivers = {}
    for port, spec in original['ports'].items():
        if spec['direction'] == 'input':
            for index, bit in enumerate(spec['bits']):
                drivers.setdefault(bit, set()).add(('port', port, index))
    for name, cell in original['cells'].items():
        for pin, bits in cell['connections'].items():
            if cell['port_directions'][pin] == 'output':
                for index, bit in enumerate(bits):
                    if type(bit) is int:
                        drivers.setdefault(bit, set()).add((name, pin, index))
    roles = {}
    for port, spec in body['ports'].items():
        for index, bit in enumerate(spec['bits']):
            assert type(bit) is int or (spec['direction'] == 'output' and bit in ('0', '1')), 'Unsupported constant formal port'
            roles.setdefault(bit, []).append((port, index, spec['direction']))
    aliases = {}

    def canonical(bit):
        while bit in aliases:
            bit = aliases[bit]
        return bit

    for name, cell in original['cells'].items():
        assert cell['type'] not in (top, '$scopeinfo'), 'Recursive or nonhardware cell'
        if cell['type'] != kernel:
            assert name not in flat['cells'], 'Flattened instance collision'
            flat['cells'][name] = cell
            continue
        instances.append(name)
        assert not cell.get('parameters'), 'Unexpected hierarchical parameter override'
        assert set(cell['connections']) == set(body['ports'])
        assert cell['port_directions'] == {p: s['direction'] for p, s in body['ports'].items()}
        mapping = {}
        for port, spec in body['ports'].items():
            actual = cell['connections'][port]
            assert len(actual) == len(spec['bits'])
            assert spec['direction'] in ('input', 'output'), 'Unsupported hierarchical port direction'
            if spec['direction'] == 'output':
                assert all(type(bit) is int for bit in actual), 'Constant output connection'
            for index, (internal, external) in enumerate(zip(spec['bits'], actual)):
                assert type(external) is int or external in ('0', '1', 'x', 'z')
                if type(internal) is not int:
                    # This source output is a literal constant, not a wire
                    # to allocate or a runtime fault signal to synthesize.
                    assert spec['direction'] == 'output' and internal in ('0', '1')
                    left = canonical(external)
                    allowed = {(name, p, i) for p, i, _ in roles[internal]}
                    actual_drivers = drivers.get(left if type(left) is int else external, set())
                    assert actual_drivers and actual_drivers <= allowed, 'Constant output has an independent driver'
                    assert type(left) is int or left == internal, 'Conflicting constant output'
                    aliases[external] = internal
                    if constant_audit is not None:
                        constant_audit.append(dict(instance=name, port=port, index=index,
                            value=internal, parent_wire=external))
                    continue
                if internal in mapping:
                    left, right = canonical(mapping[internal]), canonical(external)
                    if left != right:
                        assert {direction for _, _, direction in roles[internal]} == {'output'}, 'Input port alias conflict'
                        assert type(left) is int and type(right) is int, 'Constant output alias conflict'
                        allowed = {(name, p, i) for p, i, _ in roles[internal]}
                        actual_drivers = drivers.get(left, set()) | drivers.get(right, set())
                        assert actual_drivers and actual_drivers <= allowed, 'Output alias has an independent driver'
                        target, removed = sorted((left, right))
                        aliases[removed] = target
                        drivers[target] = actual_drivers
                        drivers.pop(removed, None)
                        if alias_audit is not None:
                            alias_audit.append(dict(instance=name, formal_bit=internal,
                                formal_output_endpoints=[[p, i] for p, i, _ in roles[internal]],
                                joined_parent_wires=[left, right], canonical_parent_wire=target))
                mapping[internal] = canonical(external)

        def mapped(bit):
            nonlocal next_bit
            if type(bit) is not int:
                assert bit in ('0', '1', 'x', 'z')
                return bit
            if bit not in mapping:
                mapping[bit] = next_bit
                next_bit += 1
            return mapping[bit]

        for child_name, child in body['cells'].items():
            assert child['type'] not in (top, kernel, '$scopeinfo')
            new_name = name + '.' + child_name
            assert new_name not in flat['cells'], 'Flattened instance collision'
            flat['cells'][new_name] = dict(child, connections={
                pin: [mapped(bit) for bit in bits] for pin, bits in child['connections'].items()})
        for net_name, net in body.get('netnames', {}).items():
            new_name = name + '.' + net_name
            assert new_name not in flat['netnames'], 'Flattened net collision'
            flat['netnames'][new_name] = dict(net, bits=[mapped(bit) for bit in net['bits']])
    # Resolve all joins after expanding every instance, including parent
    # consumers and previously expanded children. Do not mutate the input.
    flat['ports'] = {p: dict(spec, bits=[canonical(b) for b in spec['bits']])
                     for p, spec in original['ports'].items()}
    for name, cell in flat['cells'].items():
        flat['cells'][name] = dict(cell, connections={
            pin: [canonical(b) for b in bits] for pin, bits in cell['connections'].items()})
    for name, net in flat['netnames'].items():
        flat['netnames'][name] = dict(net, bits=[canonical(b) for b in net['bits']])
    return dict(modules={top: flat}), instances


def remove_physical_buffers(design, top):
    """Require the exact external pad/clock topology before collapsing identities."""
    module = design['modules'][top]
    assert {n: (p['direction'], len(p['bits'])) for n, p in module['ports'].items()} == EXPECTED_PORTS
    buffers = {name: c for name, c in module['cells'].items()
               if c['type'] in ('IBUF', 'OBUF', 'BUFG')}
    assert Counter(c['type'] for c in buffers.values()) == {'IBUF': 2, 'OBUF': 3, 'BUFG': 1}
    for c in buffers.values():
        assert set(c['connections']) == {'I', 'O'} and not c.get('parameters')
        assert c['port_directions'] == {'I': 'input', 'O': 'output'}
        assert all(len(bits) == 1 and type(bits[0]) is int for bits in c['connections'].values())
    inputs = {}
    for name in ('SYS_CLK', 'SYS_RSTN'):
        pin = module['ports'][name]['bits']
        match = [c for c in buffers.values() if c['type'] == 'IBUF' and c['connections']['I'] == pin]
        assert len(match) == 1
        inputs[name] = match[0]
    for bit in module['ports']['led_3bits_tri_o']['bits']:
        assert sum(c['type'] == 'OBUF' and c['connections']['O'] == [bit]
                   for c in buffers.values()) == 1
    clock = next(c for c in buffers.values() if c['type'] == 'BUFG')
    assert clock['connections']['I'] == inputs['SYS_CLK']['connections']['O'], 'Wrong clock source'
    external = {bit for spec in module['ports'].values() for bit in spec['bits']}
    assert len(external) == 5 and all(type(bit) is int for bit in external)
    assert len({c['connections']['O'][0] for c in buffers.values()}) == 6, 'Shared buffer drivers'
    for name, cell in module['cells'].items():
        if name not in buffers:
            assert not external.intersection(bit for bits in cell['connections'].values() for bit in bits), 'Unbuffered external endpoint'
    aliases = {}

    def canonical(bit):
        seen = set()
        while bit in aliases:
            assert bit not in seen, 'Buffer identity loop'
            seen.add(bit)
            bit = aliases[bit]
        return bit

    for cell in buffers.values():
        lhs, rhs = map(canonical, (cell['connections']['O'][0], cell['connections']['I'][0]))
        assert lhs != rhs
        aliases[lhs] = rhs
    collapsed = dict(module, cells={}, ports={})
    for name, spec in module['ports'].items():
        collapsed['ports'][name] = dict(spec, bits=[canonical(bit) for bit in spec['bits']])
    for name, cell in module['cells'].items():
        if name not in buffers:
            collapsed['cells'][name] = dict(cell, connections={
                pin: [canonical(bit) for bit in bits] for pin, bits in cell['connections'].items()})
    return dict(modules={top: collapsed})


def main():
    out = ROOT / f'build/openxc7/full-prefix-pack-input-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(),
        supervisor_pid=os.getpid(), commands=[], channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
        native_packing_executed=False, numerical_netlist_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        bitstream_emitted=False, hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label, timeout=3600):
        log = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), cwd=str(ROOT), log=str(log.relative_to(ROOT)),
                    status='RUNNING', timeout_seconds=timeout)
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with log.open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = log.read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:', text), text[-2000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        parent = json.loads(PARENT.read_text())
        assert parent['status'] == 'FAIL' and parent['finished_utc']
        assert parent['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE'
        assert (parent['channels'], parent['kernels'], parent['parallel_products'],
                parent['intended_part'], parent['intended_clock_period_ns']) == (
                    32, 16, 512, 'xc7k480tffg1156-2', 20)
        step = parent['commands'][5]
        assert Path(step['log']).stem == 'export' and step['status'] == 'PASS' and step['returncode'] == 0
        assert step['argv'] == ['yosys', '-Q', '-T', '-s', str(PARENT.parent / 'export.ys')]
        assert parent['numerical_netlist_acceptance'] is False
        exported = PARENT.parent / 'export_roundtrip.json'
        assert digest(exported) == parent['artifacts']['files'][str(exported.relative_to(ROOT))]
        mapping_path = ROOT / parent['mapping_report']
        mapping = json.loads(mapping_path.read_text())
        verify_mapping_report(mapping)
        assert parent['parent_source_sha256'] == mapping['source']['sha256']
        before = {}
        for value in (parent, mapping):
            for key in ('source', 'artifacts'):
                before.update(verify_stream_manifest(value[key]))
        before.update(verify_stream_manifest(mapping['external_mapping_inputs'], external=True))
        yosys = Path(shutil.which('yosys')).resolve()
        config = Path(shutil.which('yosys-config')).resolve()
        before.update({str(p.resolve()): digest(p) for p in (Path(__file__), PARENT, mapping_path, yosys, config)})
        report.update(source=before, source_report=str(PARENT.relative_to(ROOT)),
            original_parent_status='FAIL', full_board_numerical_acceptance_inherited=False)
        save()
        library = Path(run([config, '--datdir'], 'datadir').strip()) / 'xilinx/cells_sim.v'
        assert digest(library) == mapping['external_mapping_inputs']['files'][str(library.resolve())]
        sources = [Path(__file__), PARENT, exported, mapping_path, library,
                   yosys, config]
        sources += [Path(m.__file__).resolve() for m in list(sys.modules.values())
                    if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
        before.update({str(p.resolve()): digest(p) for p in set(sources)})
        report.update(source=before, source_report=str(PARENT.relative_to(ROOT)),
            original_parent_status='FAIL', full_board_numerical_acceptance_inherited=False)
        graph = mapping_path.parent / 'mapped_hierarchy.json'
        assert str(graph) in before
        original = json.loads(graph.read_text())
        original = dict(modules={name: original['modules'][name] for name in (TOP, mapping['preserved_kernel'])})
        aliased, modules = implementation_module_aliases(original)
        del original
        aliased, instances = hardware_instance_aliases(aliased)
        assert json.loads((PARENT.parent / 'hardware_name_aliases.json').read_text()) == dict(modules=modules, instances=instances)
        design = json.loads(exported.read_text())
        report['export_pin_direction_annotations_restored'] = restore_export_direction_metadata(design, aliased)
        report['mapping_to_export_identity'] = assert_circuit_identity(aliased, design)
        del aliased
        assert set(design['modules']) == {TOP, 'rk_lut_pair_module_0'}
        assert {n: (p['direction'], len(p['bits'])) for n, p in design['modules'][TOP]['ports'].items()} == EXPECTED_PORTS
        output_aliases = []
        constant_outputs = []
        flat, instances = literal_flatten(design, TOP, 'rk_lut_pair_module_0', output_aliases, constant_outputs)
        assert len(instances) == 16
        assert len(output_aliases) == 16
        assert all(record['formal_output_endpoints'] == [['result', 38], ['result', 39]]
                   for record in output_aliases), 'Unexpected full-profile output alias'
        assert len(constant_outputs) == 16
        assert all((record['port'], record['index'], record['value']) == ('invalid', 0, '0')
                   for record in constant_outputs), 'Unexpected full-profile constant output'
        counts = Counter(c['type'] for c in flat['modules'][TOP]['cells'].values())
        assert dict(counts) == mapping['cells'] and counts['DSP48E1'] == 515
        assert all(sum(c['type'] == 'DSP48E1' for n, c in flat['modules'][TOP]['cells'].items()
                       if n.startswith(instance + '.')) == 32 for instance in instances)
        report.update(stage='physical_io_export', primitive_counts=dict(counts),
                      retained_kernel_instances=instances, retained_cmac_dsps=512,
                      literal_output_aliases=output_aliases, literal_constant_outputs=constant_outputs)
        logical = out / 'literal_flat.json'
        with logical.open('w') as stream:
            json.dump(flat, stream, separators=(',', ':'))
            stream.write('\n')
        del design, flat
        packed = out / 'pack_input.json'
        script = out / 'physical_io.ys'
        script.write_text(';\n'.join([
            'read_verilog -lib ' + json.dumps(str(library)),
            'read_json ' + json.dumps(str(logical)),
            'hierarchy -check -top ' + TOP,
            'clkbufmap -buf BUFG O:I',
            'iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O',
            'check -assert', 'select ' + TOP,
            'write_json -selected ' + json.dumps(str(packed))]) + '\n')
        report['yosys_version'] = run([yosys, '-V'], 'version').strip()
        assert report['yosys_version'] == mapping['tool_version']
        run([yosys, '-Q', '-T', '-s', script], 'physical_io')
        physical = json.loads(packed.read_text())
        collapsed = remove_physical_buffers(physical, TOP)
        del physical
        with logical.open() as stream:
            flat = json.load(stream)
        report['physical_buffer_roundtrip_identity'] = assert_circuit_identity(flat, collapsed)
        del flat, collapsed
        assert all(digest(path) == sha for path, sha in before.items()), 'Changed preparation input'
        report.update(status='PREPARED_FULL_C32K16_LITERAL_PACK_INPUT_NOT_NATIVE_PACKING_OR_SIGNOFF',
            stage='complete', physical_buffer_counts={'IBUF': 2, 'OBUF': 3, 'BUFG': 1},
            circuit_identity='ALL_PRIMITIVE_PARAMETERS_PORT_BITS_AND_PIN_WIRE_INCIDENCE_AFTER_BUFFER_REMOVAL',
            pack_input=str(packed.relative_to(ROOT)))
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.iterdir()
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
