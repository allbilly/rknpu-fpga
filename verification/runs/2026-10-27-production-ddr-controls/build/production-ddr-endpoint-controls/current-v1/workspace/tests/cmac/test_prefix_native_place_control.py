"""Placement admission/binding controls; small native runs are not full-board fit."""
from collections import Counter
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
from place_prefix_board import (PACKED, ABSENT_ACCEPTANCE, QUALIFICATION, DATABASE,
    TOP, digest, audit, CONSTIDS, packing_xdc, native_export_module,
    verify_packed_metadata, placement_argv, verify_placed_module)


def packed():
    return dict(status=PACKED, stage='complete', finished_utc='synthetic control only',
        channels=32, kernels=16, parallel_products=512, retained_cmac_dsps=512,
        retained_shell_dsps=3, intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
        seed=3588, native_packing_executed=True, native_placement_executed=False,
        retained_kernel_dsps={'k' + str(i): 32 for i in range(16)},
        native_packed_cell_counts={'DSP48E1_DSP48E1': 515, 'RAMB36E1_RAMB36E1': 6},
        commands=[dict(log=label + '.log', status='PASS_TOOL_EXECUTION_ONLY', returncode=0)
                  for label in ('version', 'help', 'native_pack')],
        constraint_translation=dict(target_period_ns=20.0, signoff_constraint_profile=False),
        native_export_top_translation=dict(graph_data_changed=False),
        **{key: False for key in ABSENT_ACCEPTANCE})


def placed_fixture():
    cells = {}
    for group in packed()['retained_kernel_dsps']:
        for i in range(32):
            name = f'{group}.dsp{i}'
            cells[name] = dict(type='DSP48E1_DSP48E1', attributes={'NEXTPNR_BEL': name + '/DSP'})
    for kind, count in (('DSP48E1_DSP48E1', 3), ('RAMB36E1_RAMB36E1', 6)):
        for i in range(count):
            name = kind + str(i)
            cells[name] = dict(type=kind, attributes={'NEXTPNR_BEL': name + '/SLOT'})
    return dict(settings=dict(pack=f'{1:032b}', place=f'{1:032b}',
                              placer='static', target_freq='50000000.000000'), cells=cells)


class PrefixNativePlaceControl(unittest.TestCase):
    def test_full_geometry_admission_preserves_absent_acceptance(self):
        report = packed()
        verify_packed_metadata(report)
        self.assertTrue(all(report[key] is False for key in ABSENT_ACCEPTANCE))

    def test_failed_live_wrong_size_part_clock_seed_and_waivers_rejected(self):
        for key, value in [('status', 'RUNNING'), ('status', 'FAIL'), ('stage', 'native_pack'),
                           ('channels', 16), ('kernels', 8), ('parallel_products', 256),
                           ('retained_cmac_dsps', 511), ('retained_shell_dsps', 2),
                           ('intended_part', 'xc7k480tffg1156-1'), ('intended_clock_period_ns', 40),
                           ('seed', 1), ('native_packing_executed', False), ('native_placement_executed', True)
                           ] + [(key, True) for key in ABSENT_ACCEPTANCE]:
            report = packed()
            report[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                verify_packed_metadata(report)
        report = packed()
        report['retained_kernel_dsps']['k0'] = 31
        with self.assertRaises(AssertionError): verify_packed_metadata(report)
        report = packed()
        report['commands'][-1]['returncode'] = 1
        with self.assertRaises(AssertionError): verify_packed_metadata(report)

    def test_full_bindings_and_each_kernel_checked_without_numeric_claim(self):
        result = verify_placed_module(placed_fixture(), packed()['native_packed_cell_counts'],
                                     packed()['retained_kernel_dsps'])
        self.assertEqual(result['bound_cells'], 521)
        self.assertEqual(result['unique_bel_slots'], 521)
        self.assertEqual(result['retained_kernel_dsps'], packed()['retained_kernel_dsps'])
        self.assertFalse(result['full_placed_numerical_acceptance'])

    def test_missing_duplicate_changed_cell_and_wrong_kernel_bindings_fail(self):
        for change in ('missing', 'empty', 'malformed', 'duplicate', 'delete', 'type', 'kernel'):
            module = placed_fixture()
            cell = module['cells']['k0.dsp0']
            if change == 'missing': cell['attributes'].pop('NEXTPNR_BEL')
            elif change == 'empty': cell['attributes']['NEXTPNR_BEL'] = ''
            elif change == 'malformed': cell['attributes']['NEXTPNR_BEL'] = 'not-a-bel'
            elif change == 'duplicate': cell['attributes']['NEXTPNR_BEL'] = module['cells']['k0.dsp1']['attributes']['NEXTPNR_BEL']
            elif change == 'delete': module['cells'].pop('k0.dsp0')
            elif change == 'type': cell['type'] = 'SLICE_LUTX'
            else: module['cells']['shell.extra'] = module['cells'].pop('k0.dsp0')
            with self.subTest(change=change), self.assertRaises(AssertionError):
                verify_placed_module(module, packed()['native_packed_cell_counts'], packed()['retained_kernel_dsps'])

    def test_missing_stage_route_execution_and_clock_changes_fail(self):
        for key, value in [('pack', f'{0:032b}'), ('place', f'{0:032b}'), ('route', f'{1:032b}'),
                           ('placer', 'heap'), ('target_freq', '25000000'), ('target_freq', 'nan')]:
            module = placed_fixture()
            module['settings'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                verify_placed_module(module, packed()['native_packed_cell_counts'])

    def test_argv_repackages_original_input_with_no_waivers_or_bit_action(self):
        argv = placement_argv('qualified-native', 'original-physical.json', 'literal.xdc', 'placed.json')
        for flag, value in (('--device', 'xc7k480tffg1156-2'), ('--freq', '50'),
                            ('--seed', '3588'), ('--placer', 'static'), ('--json', 'original-physical.json')):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn('--no-route', argv)
        self.assertIn('--Werror', argv)
        for forbidden in ('--force', '--timing-allow-fail', '--ignore-loops', '--no-pack',
                          '--pack-only', '--no-place', '--fasm', '--placer-static-refine-max-iterations'):
            self.assertNotIn(forbidden, argv)

    def test_actual_small_native_placement_and_complete_binding_contract(self):
        from test_prefix_pack_input_control import fixture, primitive
        self.assertIsNotNone(shutil.which('yosys'), 'Actual Yosys required')
        out = ROOT / f'build/openxc7/prefix-native-place-small-control-{time.time_ns()}'
        out.mkdir(parents=True, exist_ok=False)
        print('Actual small native placement control: ' + str(out), flush=True)
        candidate = json.loads(QUALIFICATION.read_text())
        inventory = audit(QUALIFICATION, DATABASE, CONSTIDS)
        before = dict(candidate['inputs'])
        executable = Path(candidate['executable']['path'])
        commands = []
        report = dict(status='RUNNING', source=before, commands=commands,
            full_board_native_placement_executed=False, small_native_placement_executed=False,
            physical_fit_verified=False, timing_signoff=False, bitstream_emitted=False, hardware_programmed=False)

        def run(label, argv):
            step = dict(label=label, argv=list(map(str, argv)), status='RUNNING')
            commands.append(step)
            start = time.monotonic()
            result = subprocess.run(step['argv'], cwd=ROOT, text=True, capture_output=True, timeout=180, check=False)
            text = result.stdout + result.stderr
            log = out / (label + '.log')
            log.write_text(text)
            step.update(returncode=result.returncode, log=str(log), seconds=round(time.monotonic() - start, 3))
            self.assertEqual(result.returncode, 0, text[-2500:])
            self.assertIsNone(re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:|target is ignored|matched nothing', text))
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text.strip()

        try:
            body = fixture()['modules'][TOP]
            body['cells'] = {'reset_inv': primitive('INV', {'I': [3], 'O': [7]}),
                             'toggle_inv': primitive('INV', {'I': [4], 'O': [8]})}
            for bit, data in ((4, 8), (5, 4), (6, 5)):
                body['cells']['q' + str(bit)] = primitive('FDCE', {
                    'C': [2], 'CE': ['1'], 'CLR': [7], 'D': [data], 'Q': [bit]}, {'INIT': '0'})
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
            xdc = out / 'literal.xdc'
            xdc.write_text(text)
            argv = placement_argv(executable, out / 'physical.json', xdc, out / 'packed.json')
            argv[argv.index('--no-route')] = '--pack-only'
            run('native_pack', argv)
            packed_module, _ = native_export_module(json.loads((out / 'packed.json').read_text()), version)
            expected = dict(Counter(cell['type'] for cell in packed_module['cells'].values()))
            report['small_native_placement_executed'] = True
            log = run('native_place', placement_argv(executable, out / 'physical.json', xdc, out / 'placed.json'))
            for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                           'Running post-placement legalisation...', 'Program finished normally.'):
                self.assertIn(marker, log)
            module, labels = native_export_module(json.loads((out / 'placed.json').read_text()), version)
            checks = verify_placed_module(module, expected)
            self.assertTrue(all(digest(path) == sha for path, sha in before.items()))
            report.update(status='PASS_SMALL_REAL_NATIVE_PLACEMENT_BINDING_CONTROL_NOT_FULL_BOARD_OR_SIGNOFF',
                placement_checks=checks, label_translation=labels, constraint_translation=translation,
                timing_inventory=inventory)
        except BaseException as error:
            report.update(status='FAIL', error=repr(error))
            raise
        finally:
            report['artifacts'] = {str(p): digest(p) for p in out.iterdir() if p.is_file()}
            (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    unittest.main()
