"""Packing-preparation controls; no full-board simulation or FPGA signoff."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/openxc7'))
from prepare_prefix_pack_input import (
    TOP, assert_circuit_identity, literal_flatten, remove_physical_buffers,
    restore_export_direction_metadata)
from test_fixed_mapped_array import circuit_signature


def primitive(kind, connections, parameters=None):
    outputs = {'INV': {'O'}, 'FDCE': {'Q'}, 'IBUF': {'O'},
               'OBUF': {'O'}, 'BUFG': {'O'}}[kind]
    return dict(hide_name=0, type=kind, attributes={}, parameters=parameters or {},
                port_directions={p: 'output' if p in outputs else 'input' for p in connections},
                connections=connections)


def fixture():
    ports = {'SYS_CLK': dict(direction='input', bits=[2]),
             'SYS_RSTN': dict(direction='input', bits=[3]),
             'led_3bits_tri_o': dict(direction='output', bits=[4, 5, 6])}
    body = dict(ports={'I': dict(direction='input', bits=[2]),
                       'O': dict(direction='output', bits=[3])},
                cells={'a': primitive('INV', {'I': [2], 'O': [100000]}),
                       'b': primitive('INV', {'I': [100000], 'O': [3]})}, netnames={})
    cells = {name: dict(type='kernel', parameters={},
                        port_directions={'I': 'input', 'O': 'output'},
                        connections={'I': [pin], 'O': [out]})
             for name, pin, out in (('k0', 2, 10), ('k1', 3, 11))}
    cells.update(q=primitive('FDCE', {'C': [2], 'CE': ['1'], 'CLR': [3], 'D': [10], 'Q': [4]}, {'INIT': '0'}),
                 a=primitive('INV', {'I': [11], 'O': [5]}),
                 b=primitive('INV', {'I': [10], 'O': [6]}))
    return dict(modules={TOP: dict(ports=ports, cells=cells, netnames={}), 'kernel': body})


def buffered(flat):
    design = deepcopy(flat)
    cells = design['modules'][TOP]['cells']
    mapping = {2: 20, 3: 21, 4: 24, 5: 25, 6: 26}
    for cell in cells.values():
        cell['connections'] = {p: [mapping.get(bit, bit) for bit in bits]
                               for p, bits in cell['connections'].items()}
    cells['q']['connections']['C'] = [22]
    cells.update(ib_clock=primitive('IBUF', {'I': [2], 'O': [20]}),
                 ib_reset=primitive('IBUF', {'I': [3], 'O': [21]}),
                 gb_clock=primitive('BUFG', {'I': [20], 'O': [22]}))
    for bit in (4, 5, 6):
        cells['ob' + str(bit)] = primitive('OBUF', {'I': [mapping[bit]], 'O': [bit]})
    return design


def output_alias_fixture():
    design = fixture()
    design['modules']['kernel']['ports']['O']['bits'] = [3, 3]
    top = design['modules'][TOP]
    top['cells']['k0']['connections']['O'] = [10, 12]
    top['cells']['k1']['connections']['O'] = [11, 13]
    top['cells']['q']['connections']['D'] = [12]
    top['cells']['a']['connections']['I'] = [13]
    top['netnames']['alias_fanout'] = dict(hide_name=0, bits=[12, 13], attributes={})
    return design


def constant_output_fixture():
    design = output_alias_fixture()
    design['modules']['kernel']['ports']['invalid'] = dict(direction='output', bits=['0'])
    top = design['modules'][TOP]
    for name, bit in (('k0', 14), ('k1', 15)):
        top['cells'][name]['connections']['invalid'] = [bit]
        top['cells'][name]['port_directions']['invalid'] = 'output'
    top['cells']['q']['connections']['CLR'] = [14]
    top['cells']['b']['connections']['I'] = [15]
    top['netnames']['constant_fanout'] = dict(hide_name=0, bits=[14, 15], attributes={})
    return design


class PrefixPackInputControl(unittest.TestCase):
    def test_literal_full_instance_expansion_without_internal_aliasing(self):
        original = fixture()
        saved = deepcopy(original)
        flat, instances = literal_flatten(original, TOP, 'kernel')
        self.assertEqual(original, saved)
        self.assertEqual(instances, ['k0', 'k1'])
        cells = flat['modules'][TOP]['cells']
        self.assertEqual(len(cells), 7)
        for name in instances:
            self.assertEqual(cells[name + '.a']['connections']['O'], cells[name + '.b']['connections']['I'])
            self.assertGreater(cells[name + '.a']['connections']['O'][0], 100000)
        self.assertNotEqual(cells['k0.a']['connections']['O'], cells['k1.a']['connections']['O'])

    def test_repeated_output_formal_joins_only_its_own_fanout(self):
        reference, _ = literal_flatten(fixture(), TOP, 'kernel')
        for reverse in (False, True):
            original = output_alias_fixture()
            if reverse:
                original['modules'][TOP]['cells'] = dict(reversed(list(original['modules'][TOP]['cells'].items())))
            saved = deepcopy(original)
            aliases = []
            flat, instances = literal_flatten(original, TOP, 'kernel', aliases)
            self.assertEqual(original, saved)
            self.assertEqual(set(instances), {'k0', 'k1'})
            self.assertEqual(len(aliases), 2)
            self.assertEqual({tuple(a['joined_parent_wires']) for a in aliases}, {(10, 12), (11, 13)})
            self.assertTrue(all(a['formal_output_endpoints'] == [['O', 0], ['O', 1]] for a in aliases))
            self.assertEqual(flat['modules'][TOP]['netnames']['alias_fanout']['bits'], [10, 11])
            assert_circuit_identity(reference, flat)
            self.assertEqual(circuit_signature(reference), circuit_signature(flat))

    def test_conflicting_aliases_and_constant_outputs_remain_failures(self):
        for change in ('independent_driver', 'primary_input_driver', 'constant', 'same_constant', 'mixed_roles', 'input_alias'):
            design = output_alias_fixture()
            top, body = design['modules'][TOP], design['modules']['kernel']
            if change == 'independent_driver':
                top['cells']['extra'] = primitive('INV', {'I': [2], 'O': [12]})
            elif change == 'primary_input_driver':
                top['cells']['k0']['connections']['O'] = [10, 3]
            elif change == 'constant':
                top['cells']['k0']['connections']['O'] = [10, '0']
            elif change == 'same_constant':
                top['cells']['k0']['connections']['O'] = ['0', '0']
            elif change == 'mixed_roles':
                body['ports']['I']['bits'] = [3]
            else:
                body['ports']['I']['bits'] = [2, 2]
                top['cells']['k0']['connections']['I'] = [2, 3]
                top['cells']['k1']['connections']['I'] = [3, 3]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                literal_flatten(design, TOP, 'kernel')

    def test_source_constant_formal_output_is_preserved_without_pruning(self):
        reference, _ = literal_flatten(fixture(), TOP, 'kernel')
        reference['modules'][TOP]['cells']['q']['connections']['CLR'] = ['0']
        reference['modules'][TOP]['cells']['b']['connections']['I'] = ['0']
        original = constant_output_fixture()
        saved = deepcopy(original)
        constants = []
        flat, _ = literal_flatten(original, TOP, 'kernel', constant_audit=constants)
        self.assertEqual(original, saved)
        self.assertEqual(constants, [dict(instance='k0', port='invalid', index=0, value='0', parent_wire=14),
                                     dict(instance='k1', port='invalid', index=0, value='0', parent_wire=15)])
        self.assertEqual(flat['modules'][TOP]['netnames']['constant_fanout']['bits'], ['0', '0'])
        assert_circuit_identity(reference, flat)
        self.assertEqual(circuit_signature(reference), circuit_signature(flat))

    def test_constant_formal_outputs_reject_unknowns_inputs_and_other_drivers(self):
        for change in ('unknown', 'high_impedance', 'input_formal', 'independent_driver', 'primary_input_driver', 'conflict'):
            design = constant_output_fixture()
            top, body = design['modules'][TOP], design['modules']['kernel']
            if change in ('unknown', 'high_impedance'):
                body['ports']['invalid']['bits'] = ['x' if change == 'unknown' else 'z']
            elif change == 'input_formal':
                body['ports']['I']['bits'] = ['0']
            elif change == 'independent_driver':
                top['cells']['extra'] = primitive('INV', {'I': [2], 'O': [14]})
            elif change == 'primary_input_driver':
                top['cells']['k0']['connections']['invalid'] = [2]
            else:
                body['ports']['other'] = dict(direction='output', bits=['1'])
                for name in ('k0', 'k1'):
                    top['cells'][name]['connections']['other'] = list(top['cells'][name]['connections']['invalid'])
                    top['cells'][name]['port_directions']['other'] = 'output'
            with self.subTest(change=change), self.assertRaises(AssertionError):
                literal_flatten(design, TOP, 'kernel')

    def test_flatten_rejects_name_collisions_in_both_orders(self):
        for first in (True, False):
            original = fixture()
            cells = original['modules'][TOP]['cells']
            collision = primitive('INV', {'I': [2], 'O': [4]})
            original['modules'][TOP]['cells'] = ({'k0.a': collision, **cells} if first else {**cells, 'k0.a': collision})
            with self.subTest(first=first), self.assertRaises(AssertionError):
                literal_flatten(original, TOP, 'kernel')

    def test_flatten_rejects_hierarchical_changes(self):
        for change in ('parameters', 'width', 'direction', 'recursive'):
            original = fixture()
            cell = original['modules'][TOP]['cells']['k0']
            if change == 'parameters': cell['parameters'] = {'ATOMIC_C': '1'}
            elif change == 'width': cell['connections']['I'].append(3)
            elif change == 'direction': cell['port_directions']['I'] = 'output'
            else: original['modules']['kernel']['cells']['a']['type'] = TOP
            with self.subTest(change=change), self.assertRaises(AssertionError):
                literal_flatten(original, TOP, 'kernel')

    def test_wire_bijection_agrees_with_existing_endpoint_signature(self):
        flat, _ = literal_flatten(fixture(), TOP, 'kernel')
        other = deepcopy(flat)
        body = other['modules'][TOP]
        for value in body['ports'].values():
            value['bits'] = [bit + 123 for bit in value['bits']]
        for cell in body['cells'].values():
            cell['connections'] = {p: [b + 123 if type(b) is int else b for b in bits]
                                   for p, bits in cell['connections'].items()}
        self.assertEqual(circuit_signature(flat), circuit_signature(other))
        result = assert_circuit_identity(flat, other)
        self.assertEqual(result[TOP]['cells'], 7)

    def test_only_unconnected_debug_scope_metadata_is_nonhardware(self):
        flat, _ = literal_flatten(fixture(), TOP, 'kernel')
        original = deepcopy(flat)
        original['modules'][TOP]['cells']['debug'] = dict(type='$scopeinfo', connections={}, port_directions={})
        result = assert_circuit_identity(original, flat)
        self.assertEqual(result[TOP]['original_debug_scope_cells'], 1)
        self.assertEqual(circuit_signature(original), circuit_signature(flat))
        original['modules'][TOP]['cells']['debug']['connections'] = {'C': [2]}
        with self.assertRaises(AssertionError):
            assert_circuit_identity(original, flat)

    def test_missing_export_annotations_restored_without_hardware_edits(self):
        flat, _ = literal_flatten(fixture(), TOP, 'kernel')
        exported = deepcopy(flat)
        for cell in exported['modules'][TOP]['cells'].values():
            del cell['port_directions']
        before = circuit_signature(exported)
        counts = restore_export_direction_metadata(exported, flat)
        self.assertEqual(counts, {TOP: 7})
        self.assertEqual(circuit_signature(exported), before)
        assert_circuit_identity(flat, exported)
        exported['modules'][TOP]['cells']['a']['port_directions']['O'] = 'input'
        with self.assertRaises(AssertionError):
            restore_export_direction_metadata(exported, flat)

    def test_identity_rejects_split_merge_constants_parameters_and_cells(self):
        flat, _ = literal_flatten(fixture(), TOP, 'kernel')
        for change in ('split', 'merge', 'constant', 'parameters', 'type', 'direction', 'delete', 'pin'):
            other = deepcopy(flat)
            cells = other['modules'][TOP]['cells']
            if change == 'split': cells['k0.b']['connections']['I'] = [999999]
            elif change == 'merge': cells['k1.a']['connections']['O'] = list(cells['k0.a']['connections']['O'])
            elif change == 'constant': cells['q']['connections']['CE'] = ['0']
            elif change == 'parameters': cells['q']['parameters']['INIT'] = '1'
            elif change == 'type': cells['a']['type'] = 'LUT1'
            elif change == 'direction': cells['a']['port_directions']['O'] = 'input'
            elif change == 'delete': del cells['k0.a']
            else: cells['a']['connections']['extra'] = [2]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                assert_circuit_identity(flat, other)

    def test_only_exact_pad_and_global_clock_topology_is_collapsed(self):
        flat, _ = literal_flatten(fixture(), TOP, 'kernel')
        physical = buffered(flat)
        for reverse in (False, True):
            if reverse:
                body = physical['modules'][TOP]
                body['cells'] = dict(reversed(list(body['cells'].items())))
            collapsed = remove_physical_buffers(physical, TOP)
            assert_circuit_identity(flat, collapsed)
            self.assertEqual(circuit_signature(flat), circuit_signature(collapsed))

    def test_bad_buffer_topologies_are_explicit_failures(self):
        flat, _ = literal_flatten(fixture(), TOP, 'kernel')
        for change in ('clock', 'extra', 'parameters', 'short', 'bypass', 'port', 'loop'):
            other = buffered(flat)
            body = other['modules'][TOP]
            cells = body['cells']
            if change == 'clock': cells['gb_clock']['connections']['I'] = [21]
            elif change == 'extra': cells['extra'] = primitive('OBUF', {'I': [200], 'O': [201]})
            elif change == 'parameters': cells['ib_clock']['parameters']['CAPACITANCE'] = '1'
            elif change == 'short': cells['ob4']['connections']['O'] = [5]
            elif change == 'bypass': cells['q']['connections']['C'] = [2]
            elif change == 'port': body['ports']['SYS_CLK']['direction'] = 'output'
            else: cells['gb_clock']['connections']['O'] = [2]
            with self.subTest(change=change), self.assertRaises(AssertionError):
                remove_physical_buffers(other, TOP)

    def test_actual_yosys_buffer_only_roundtrip(self):
        self.assertIsNotNone(shutil.which('yosys'), 'Yosys is required, not an inferred PASS')
        out = ROOT / f'build/openxc7/prefix-pack-small-control-{time.time_ns()}'
        out.mkdir(parents=True, exist_ok=False)
        print('Actual small Yosys artifacts: ' + str(out), flush=True)
        original = fixture()['modules'][TOP]
        original['cells'] = {'reset_inv': primitive('INV', {'I': [3], 'O': [7]})}
        for bit in (4, 5, 6):
            original['cells']['q' + str(bit)] = primitive('FDCE', {
                'C': [2], 'CE': ['1'], 'CLR': [7], 'D': ['1'], 'Q': [bit]}, {'INIT': '0'})
        design = dict(modules={TOP: original})
        (out / 'input.json').write_text(json.dumps(design))
        commands = []
        for label, argv in (('version', ['yosys', '-V']), ('datadir', ['yosys-config', '--datdir'])):
            result = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
            (out / (label + '.log')).write_text(result.stdout + result.stderr)
            commands.append(dict(argv=argv, returncode=result.returncode, log=str(out / (label + '.log'))))
            self.assertEqual(result.returncode, 0)
        library = Path((out / 'datadir.log').read_text().strip()) / 'xilinx/cells_sim.v'
        script = '; '.join(['read_verilog -lib ' + json.dumps(str(library)),
                            'read_json ' + json.dumps(str(out / 'input.json')),
                            'hierarchy -check -top ' + TOP,
                            'clkbufmap -buf BUFG O:I',
                            'iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O',
                            'check -assert', 'select ' + TOP,
                            'write_json -selected ' + json.dumps(str(out / 'output.json'))])
        (out / 'physical_io.ys').write_text(script + '\n')
        argv = ['yosys', '-Q', '-T', '-s', str(out / 'physical_io.ys')]
        result = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
        text = result.stdout + result.stderr
        (out / 'physical_io.log').write_text(text)
        commands.append(dict(argv=argv, returncode=result.returncode, log=str(out / 'physical_io.log')))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        self.assertEqual(result.returncode, 0, text[-1500:])
        self.assertIsNone(re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:', text))
        collapsed = remove_physical_buffers(json.loads((out / 'output.json').read_text()), TOP)
        assert_circuit_identity(design, collapsed)
        self.assertEqual(circuit_signature(design), circuit_signature(collapsed))

    def test_actual_yosys_flatten_matches_literal_output_aliases(self):
        self.assertIsNotNone(shutil.which('yosys'), 'Yosys is required, not an inferred PASS')
        out = ROOT / f'build/openxc7/prefix-pack-alias-control-{time.time_ns()}'
        out.mkdir(parents=True, exist_ok=False)
        print('Actual Yosys alias control artifacts: ' + str(out), flush=True)
        design = constant_output_fixture()
        aliases = []
        constants = []
        expected, _ = literal_flatten(design, TOP, 'kernel', aliases, constants)
        (out / 'input.json').write_text(json.dumps(design))
        (out / 'literal_aliases.json').write_text(json.dumps(aliases, indent=2) + '\n')
        (out / 'literal_constants.json').write_text(json.dumps(constants, indent=2) + '\n')
        commands = []
        for label, argv in (('version', ['yosys', '-V']), ('datadir', ['yosys-config', '--datdir'])):
            result = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
            (out / (label + '.log')).write_text(result.stdout + result.stderr)
            commands.append(dict(argv=argv, returncode=result.returncode, log=str(out / (label + '.log'))))
            self.assertEqual(result.returncode, 0)
        library = Path((out / 'datadir.log').read_text().strip()) / 'xilinx/cells_sim.v'
        script = '; '.join(['read_verilog -lib ' + json.dumps(str(library)),
                            'read_json ' + json.dumps(str(out / 'input.json')),
                            'hierarchy -check -top ' + TOP,
                            'flatten -noscopeinfo', 'check -assert', 'select ' + TOP,
                            'write_json -selected ' + json.dumps(str(out / 'output.json'))])
        (out / 'flatten.ys').write_text(script + '\n')
        argv = ['yosys', '-Q', '-T', '-s', str(out / 'flatten.ys')]
        result = subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)
        text = result.stdout + result.stderr
        (out / 'flatten.log').write_text(text)
        commands.append(dict(argv=argv, returncode=result.returncode, log=str(out / 'flatten.log')))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        self.assertEqual(result.returncode, 0, text[-1500:])
        self.assertIsNone(re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:', text))
        actual = json.loads((out / 'output.json').read_text())
        assert_circuit_identity(expected, actual)
        self.assertEqual(circuit_signature(expected), circuit_signature(actual))


if __name__ == '__main__':
    unittest.main()
