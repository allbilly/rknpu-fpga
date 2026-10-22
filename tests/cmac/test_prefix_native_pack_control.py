"""Native-pack admission/constraint controls, not native packing or signoff."""
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
from pack_prefix_board import (PREPARED, QUALIFICATION, DATABASE, JSON_WRITER,
    CONSTIDS, TOP, digest, audit, native_export_module, packing_xdc, verify_prepared_metadata)


def prepared():
    return dict(status=PREPARED, stage='complete', finished_utc='synthetic control only',
        channels=32, kernels=16, parallel_products=512, retained_cmac_dsps=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
        retained_kernel_instances=['k' + str(i) for i in range(16)],
        primitive_counts={'DSP48E1': 515, 'RAMB36E1': 6},
        physical_buffer_counts={'IBUF': 2, 'OBUF': 3, 'BUFG': 1},
        mapping_to_export_identity={'synthetic': True}, physical_buffer_roundtrip_identity={'synthetic': True},
        circuit_identity='ALL_PRIMITIVE_PARAMETERS_PORT_BITS_AND_PIN_WIRE_INCIDENCE_AFTER_BUFFER_REMOVAL',
        original_parent_status='FAIL', full_board_numerical_acceptance_inherited=False,
        native_packing_executed=False, numerical_netlist_acceptance=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        commands=[dict(log=label + '.log', status='PASS_TOOL_EXECUTION_ONLY', returncode=0)
                  for label in ('datadir', 'version', 'physical_io')])


class PrefixNativePackControl(unittest.TestCase):
    def test_native_writer_default_and_explicit_labels_are_recorded_not_normalized(self):
        from test_prefix_pack_input_control import fixture
        version = 'control executable -- Next Generation Place and Route (Version control-only)'
        for explicit in (False, True):
            body = fixture()['modules'][TOP]
            body['attributes'] = {'module': TOP} if explicit else {}
            label = TOP if explicit else 'top'
            design = dict(creator='Next Generation Place and Route (Version control-only)', modules={label: body})
            saved = deepcopy(design)
            module, record = native_export_module(design, version)
            self.assertIs(module, body)
            self.assertEqual(design, saved)
            self.assertEqual(record['emitted_context_label'], label)
            self.assertEqual(record['logical_input_top'], TOP)
            self.assertFalse(record['graph_data_changed'])

    def test_native_writer_schema_version_ports_and_unknown_labels_fail(self):
        from test_prefix_pack_input_control import fixture
        version = 'control executable -- Next Generation Place and Route (Version control-only)'
        for change in ('label', 'extra_module', 'explicit_attribute', 'creator', 'direction', 'width', 'extra_port', 'offset', 'constant', 'merged'):
            body = fixture()['modules'][TOP]
            body['attributes'] = {}
            design = dict(creator='Next Generation Place and Route (Version control-only)', modules={'top': body})
            if change == 'label': design['modules'] = {TOP: body}
            elif change == 'extra_module': design['modules']['other'] = deepcopy(body)
            elif change == 'explicit_attribute': body['attributes']['module'] = 'unrecognized_context'
            elif change == 'creator': design['creator'] = 'Next Generation Place and Route (Version other)'
            elif change == 'direction': body['ports']['SYS_CLK']['direction'] = 'output'
            elif change == 'width': body['ports']['led_3bits_tri_o']['bits'].pop()
            elif change == 'extra_port': body['ports']['extra'] = dict(direction='input', bits=[100])
            elif change == 'offset': body['ports']['led_3bits_tri_o']['offset'] = 1
            elif change == 'constant': body['ports']['SYS_CLK']['bits'] = ['0']
            else: body['ports']['SYS_CLK']['bits'] = list(body['ports']['SYS_RSTN']['bits'])
            with self.subTest(change=change), self.assertRaises(AssertionError):
                native_export_module(design, version)

    def test_actual_small_native_pack_writer_contract(self):
        from test_prefix_pack_input_control import fixture, primitive
        self.assertIsNotNone(shutil.which('yosys'), 'Actual Yosys required')
        out = ROOT / f'build/openxc7/prefix-native-export-small-control-{time.time_ns()}'
        out.mkdir(parents=True, exist_ok=False)
        print('Actual small native writer control: ' + str(out), flush=True)
        inventory = audit(QUALIFICATION, DATABASE, CONSTIDS)
        candidate = json.loads(QUALIFICATION.read_text())
        self.assertIn(str(JSON_WRITER), candidate['inputs'])
        executable = Path(candidate['executable']['path'])
        before = dict(candidate['inputs'])
        commands = []

        def run(label, argv):
            result = subprocess.run(list(map(str, argv)), cwd=ROOT, text=True,
                                    capture_output=True, timeout=60, check=False)
            text = result.stdout + result.stderr
            (out / (label + '.log')).write_text(text)
            commands.append(dict(argv=list(map(str, argv)), returncode=result.returncode,
                                 log=str(out / (label + '.log'))))
            (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
            self.assertEqual(result.returncode, 0, text[-1500:])
            self.assertIsNone(re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text))
            return text.strip()

        body = fixture()['modules'][TOP]
        body['cells'] = {'reset_inv': primitive('INV', {'I': [3], 'O': [7]})}
        for bit in (4, 5, 6):
            body['cells']['q' + str(bit)] = primitive('FDCE', {
                'C': [2], 'CE': ['1'], 'CLR': [7], 'D': ['1'], 'Q': [bit]}, {'INIT': '0'})
        (out / 'input.json').write_text(json.dumps(dict(modules={TOP: body})))
        run('yosys_version', ['yosys', '-V'])
        library = Path(run('datadir', ['yosys-config', '--datdir'])) / 'xilinx/cells_sim.v'
        before[str(library)] = digest(library)
        script = '; '.join(['read_verilog -lib ' + json.dumps(str(library)),
            'read_json ' + json.dumps(str(out / 'input.json')), 'hierarchy -check -top ' + TOP,
            'clkbufmap -buf BUFG O:I', 'iopadmap -bits -inpad IBUF O:I -outpad OBUF I:O',
            'check -assert', 'select ' + TOP, 'write_json -selected ' + json.dumps(str(out / 'physical.json'))])
        (out / 'physical.ys').write_text(script + '\n')
        run('physical_io', ['yosys', '-Q', '-T', '-s', out / 'physical.ys'])
        version = run('native_version', [executable, '--version'])
        text, translation = packing_xdc((ROOT / 'fpga/ypcb.xdc').read_text())
        xdc = out / 'pack-only.xdc'
        xdc.write_text(text)
        run('native_pack', [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
            '--top', TOP, '--json', out / 'physical.json', '-o', 'xdc=' + str(xdc),
            '--pack-only', '--freq', '50', '--seed', '3588', '--Werror', '--verbose', '--write', out / 'packed.json'])
        module, labels = native_export_module(json.loads((out / 'packed.json').read_text()), version)
        self.assertEqual(labels['emitted_context_label'], 'top')
        self.assertEqual(len(module['ports']), 3)
        self.assertTrue(all(digest(path) == sha for path, sha in before.items()))
        report = dict(status='PASS_SMALL_REAL_NATIVE_EXPORT_SCHEMA_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF',
            source=before, timing_inventory=inventory, commands=commands,
            label_translation=labels, constraint_translation=translation,
            full_board_numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
            bitstream_emitted=False, hardware_programmed=False,
            artifacts={str(p): digest(p) for p in out.iterdir() if p.is_file()})
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def test_full_geometry_metadata_never_inherits_failed_parent_numerics(self):
        report = prepared()
        verify_prepared_metadata(report)
        self.assertFalse(report['numerical_netlist_acceptance'])
        self.assertFalse(report['physical_fit_verified'])
        self.assertFalse(report['bitstream_emitted'])

    def test_live_failed_wrong_geometry_and_unsupported_acceptance_rejected(self):
        cases = [('status', 'RUNNING'), ('status', 'FAIL'), ('channels', 16),
                 ('kernels', 8), ('parallel_products', 256), ('retained_cmac_dsps', 511),
                 ('intended_part', 'xc7k480tffg1156-1'), ('intended_clock_period_ns', 40),
                 ('native_packing_executed', True), ('timing_signoff', True),
                 ('bitstream_emitted', True), ('full_board_numerical_acceptance_inherited', True)]
        for key, value in cases:
            report = deepcopy(prepared())
            report[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                verify_prepared_metadata(report)
        report = prepared()
        report['retained_kernel_instances'][-1] = report['retained_kernel_instances'][0]
        with self.assertRaises(AssertionError): verify_prepared_metadata(report)

    def test_all_original_constraints_accounted_for_without_clock_relaxation(self):
        original = (ROOT / 'fpga/ypcb.xdc').read_text()
        text, record = packing_xdc(original)
        self.assertIn('create_clock -period 20.000 [get_ports SYS_CLK]', text)
        self.assertEqual(text.count('PACKAGE_PIN'), 5)
        self.assertEqual(text.count('IOSTANDARD LVCMOS18'), 5)
        self.assertEqual(record['metadata_clock_label'], 'sys_clk')
        self.assertEqual(len(record['unapplied_external_timing_exceptions']), 2)
        self.assertFalse(record['signoff_constraint_profile'])
        for changed in (original.replace('20.000', '40.000'),
                        original.replace('AA28', 'AA27'),
                        original.replace('LVCMOS18', 'LVCMOS33'),
                        original + '\nset_false_path -from [get_cells internal_pipeline]\n'):
            with self.assertRaises(ValueError): packing_xdc(changed)


if __name__ == '__main__':
    unittest.main()
