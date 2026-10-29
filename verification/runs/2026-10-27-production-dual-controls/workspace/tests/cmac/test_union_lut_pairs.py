"""Greedy proposal controls and real tiny primitive proofs, not board/fit proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import analyze_union_lut_pairs as runner
from test_board_lut_pair import lut
from pair_board_luts import BENCH, four_state_bench
from test_lut_pair_unisim import pinned_models, unisim_bench, validate_result
from evidence import fingerprint, timestamp


def fixture():
    return dict(ports={'inputs': dict(direction='input', bits=list(range(2, 10))),
        'outputs': dict(direction='output', bits=[20, 21])}, cells={
        'a': lut('LUT3', [2, 3, 4], 20, '01101001'),
        'b': lut('LUT2', [5, 6], 21, '1000')})


def carry(bits):
    return dict(type='CARRY4', connections={'S': bits, 'DI': ['0'] * 4},
        port_directions={'S': 'input', 'DI': 'input'})


class UnionLutPairControls(unittest.TestCase):
    def test_disjoint_three_plus_two_inputs_exact_binary_tables(self):
        module = fixture(); before = deepcopy(module)
        records, classes, skipped = runner.proposals(module)
        self.assertEqual(module, before)
        self.assertEqual(len(records), 1); self.assertEqual(skipped['unmatched_eligible_luts'], 0)
        runner.verify_proposals(module, records, classes)
        item, = records; function = classes[item['function_key']]
        self.assertEqual(item['fanins'], [2, 3, 4, 5, 6])
        self.assertEqual(function['first']['pins'], [0, 1, 2])
        self.assertEqual(function['second']['pins'], [3, 4])
        for index in range(32):
            self.assertEqual((int(function['init'], 2) >> index) & 1,
                (int('01101001', 2) >> (index & 7)) & 1)
            self.assertEqual((int(function['init'], 2) >> (index + 32)) & 1,
                (int('1000', 2) >> ((index >> 3) & 3)) & 1)

    def test_overlapping_three_plus_three_and_actual_constants_pin_order(self):
        module = fixture(); module['cells']['b'] = lut('LUT3', [6, 2, 5], 21, '10010110')
        records, classes, _ = runner.proposals(module)
        self.assertEqual(len(records), 1); runner.verify_proposals(module, records, classes)
        module['cells']['a'] = lut('LUT3', ['1', 3, 2], 20, '01101001')
        module['cells']['b'] = lut('LUT3', [5, '0', 3], 21, '10010110')
        records, classes, _ = runner.proposals(module)
        self.assertEqual(len(records), 1); runner.verify_proposals(module, records, classes)
        self.assertEqual(classes[records[0]['function_key']]['first']['pins'], ['1', 1, 0])

    def test_orientation_preserves_o6_role_and_two_required_outputs_are_not_paired(self):
        module = fixture(); module['cells']['carry'] = carry([20, '0', '0', '0'])
        records, classes, _ = runner.proposals(module)
        self.assertEqual(records[0]['second'], 'a'); self.assertEqual(records[0]['first'], 'b')
        runner.verify_proposals(module, records, classes)
        module['cells']['carry']['connections']['S'][1] = 21
        records, classes, _ = runner.proposals(module)
        self.assertEqual(records, []); self.assertEqual(classes, {})

    def test_mux_roles_and_multiple_consumers_not_erased(self):
        module = fixture(); module['cells']['mux'] = dict(type='MUXF7',
            connections={'I0': [20], 'I1': ['0']}, port_directions={'I0': 'input', 'I1': 'input'})
        module['cells']['carry'] = carry([20, '0', '0', '0'])
        records, classes, _ = runner.proposals(module)
        self.assertEqual(len(records[0]['dedicated_o6_sinks']['O6']), 2)
        runner.verify_proposals(module, records, classes)

    def test_oversized_causal_and_repeated_correlated_pairs_not_suggested(self):
        for case in ('six_inputs', 'causal', 'repeated'):
            module = fixture()
            if case == 'six_inputs': module['cells']['b'] = lut('LUT3', [5, 6, 7], 21, '00110011')
            elif case == 'causal': module['cells']['b']['connections']['I0'] = [20]
            else: module['cells']['b']['connections']['I1'] = [5]
            with self.subTest(case=case):
                self.assertEqual(runner.proposals(module)[0], [])
                with self.assertRaises(AssertionError): runner.union_function(module['cells']['a'], module['cells']['b'])

    def test_constant_only_functions_remain_explicitly_unmatched(self):
        module = fixture(); module['cells']['a'] = lut('LUT1', ['0'], 20, '10')
        module['cells']['b'] = lut('LUT1', ['1'], 21, '10')
        records, _, skipped = runner.proposals(module)
        self.assertEqual(records, []); self.assertEqual(skipped['retained_constant_only_luts'], 2)

    def test_deterministic_disjoint_selection_and_existing_pairs_are_not_modified(self):
        module = fixture(); module['cells']['c'] = lut('LUT2', [7, 8], 22, '0110')
        module['cells']['d'] = lut('LUT3', [2, 7, 9], 23, '01010101')
        module['cells']['existing'] = dict(type='LUT6_2', parameters={'INIT': '0' * 64})
        before = deepcopy(module); first = runner.proposals(module); second = runner.proposals(module)
        self.assertEqual(first, second); self.assertEqual(module, before)
        records, classes, _ = first; self.assertEqual(len(records), 2)
        runner.verify_proposals(module, records, classes)
        used = [n for r in records for n in (r['first'], r['second'])]
        self.assertEqual(len(used), len(set(used)))

    def test_mutated_proposals_classes_or_roles_are_rejected(self):
        module = fixture(); records, classes, _ = runner.proposals(module)
        for case in ('reuse', 'fanins', 'key', 'roles', 'classes', 'truth'):
            changed, domain = deepcopy(records), deepcopy(classes)
            if case == 'reuse': changed.append(deepcopy(changed[0]))
            elif case == 'fanins': changed[0]['fanins'] = [2, 3, 4]
            elif case == 'key': changed[0]['function_key'] = 'wrong'
            elif case == 'roles': changed[0]['dedicated_o6_sinks']['O5'] = [dict(cell='made_up')]
            elif case == 'classes': domain = {}
            else: domain[changed[0]['function_key']]['init'] = '0' * 64
            with self.subTest(case=case), self.assertRaises(AssertionError):
                runner.verify_proposals(module, changed, domain)

    def test_bad_lut_and_dedicated_sink_fields_fail_explicitly(self):
        for case in ('init', 'unknown', 'direction', 'primary', 'carry_width', 'mux_direction'):
            module = fixture()
            if case == 'init': module['cells']['a']['parameters']['INIT'] = '01'
            elif case == 'unknown': module['cells']['a']['connections']['I0'] = ['x']
            elif case == 'direction': module['cells']['a']['port_directions']['I0'] = 'output'
            elif case == 'primary': module['cells']['a']['connections']['O'] = [9]
            elif case == 'carry_width': module['cells']['carry'] = carry([20])
            else: module['cells']['mux'] = dict(type='MUXF7', connections={'I0': [20], 'I1': [21]},
                port_directions={'I0': 'output', 'I1': 'input'})
            with self.subTest(case=case), self.assertRaises(AssertionError): runner.proposals(module)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp') and shutil.which('yosys-config'),
        'Real Icarus/Yosys tools unavailable; no primitive HDL proof claimed')
    def test_real_yosys_and_pinned_unisim_four_state_with_actual_negative(self):
        pairs = [
            (lut('LUT3', [2, 3, 4], 20, '01101001'), lut('LUT2', [5, 6], 21, '1000')),
            (lut('LUT3', [2, 3, 4], 20, '01101001'), lut('LUT3', [6, 2, 5], 21, '10010110')),
            (lut('LUT3', ['1', 3, 2], 20, '01101001'), lut('LUT3', [5, '0', 3], 21, '10010110')),
            (lut('LUT4', [2, 3, 4, 5], 20, '0001001000110100'), lut('LUT2', [6, 2], 21, '1000')),
            (lut('LUT5', [6, 5, 4, 3, 2], 20, '01' * 16), lut('LUT1', [2], 21, '10')),
            (lut('LUT1', ['1'], 20, '10'), lut('LUT2', [2, 3], 21, '0110')),
        ]
        classes = [runner.union_function(a, b)[1] for a, b in pairs]
        count = 2 * sum(4 ** c['fanins'] for c in classes)
        directory = ROOT / f'build/rknpu-union-lut-model-controls/{time.time_ns()}'
        directory.mkdir(parents=True, exist_ok=False)
        tracked = [Path(__file__).resolve()]
        tracked.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and (Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')
                or Path(m.__file__).resolve().is_relative_to(ROOT / 'tests/cmac')))
        before = fingerprint(tracked)
        report = dict(status='RUNNING', started_utc=timestamp(), source=before, python_version=sys.version,
            seed='none; six explicit fixtures with exhaustive union-input 0/1/X/Z enumeration',
            fixture_classes=len(classes), expected_comparisons_per_model=count, commands=[],
            actual_board_candidate=False, physical_fit_verified=False, bitstream_emitted=False,
            scope='Six tiny primitive fixtures only; not the actual board proposal domain or full board/array.')
        def save(): (directory / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        def run(argv, label):
            started = time.monotonic()
            result = subprocess.run(list(map(str, argv)), cwd=ROOT, text=True, capture_output=True, timeout=120)
            path = directory / (label + '.log'); path.write_text(result.stdout + result.stderr)
            expected = 1 if label.endswith('_negative_test') else 0
            report['commands'].append(dict(argv=list(map(str, argv)), log=str(path.relative_to(ROOT)),
                status='PASS' if result.returncode == expected else 'FAIL', expected_returncode=expected,
                returncode=result.returncode, seconds=round(time.monotonic() - started, 3)))
            save()
            return result, path.read_text()
        save()
        try:
            data, text = run(['yosys-config', '--datdir'], 'datadir')
            self.assertEqual(data.returncode, 0, text)
            yosys_model = Path(data.stdout.strip()) / 'xilinx/cells_sim.v'
            unisim_models, license_path = pinned_models(ROOT / 'build/reference/xilinx-unisim')
            report['models'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [yosys_model, *unisim_models, license_path]}
            frozen = directory / 'models'; frozen.mkdir()
            frozen_paths = []
            for path in [yosys_model, *unisim_models, license_path]:
                copy = frozen / path.name; copy.write_bytes(path.read_bytes())
                self.assertEqual(copy.read_bytes(), path.read_bytes()); frozen_paths.append(copy)
            report['frozen_models'] = fingerprint(frozen_paths)
            yosys_model = frozen / yosys_model.name
            unisim_models = [frozen / path.name for path in unisim_models]
            for command in ('iverilog', 'vvp'):
                result, text = run([command, '-V'], command + '_version')
                self.assertEqual(result.returncode, 0, text); report[command + '_version'] = text.splitlines()[0]
            generated = []
            for model, paths, builder in [('yosys', [yosys_model], four_state_bench),
                    ('unisim', unisim_models, unisim_bench)]:
                for negative in (True, False):
                    label = model + ('_negative' if negative else '_actual')
                    bench = directory / (label + '.sv'); bench.write_text(builder(classes, negative))
                    binary = directory / (label + '.vvp'); generated += [bench, binary]
                    result, text = run(['iverilog', '-g2012', '-s', BENCH, '-o', binary, *paths, bench], label + '_compile')
                    self.assertEqual(result.returncode, 0, text)
                    self.assertNotRegex(text, r'(?im)\b(?:warning|error):')
                    result, text = run(['vvp', binary], label + '_test')
                    validate_result(text, result.returncode, len(classes), count, negative)
            self.assertEqual(fingerprint(tracked), before)
            report.update(status='PASS_SMALL_UNION_LUT_FOUR_STATE_FIXTURES_ONLY', finished_utc=timestamp(),
                artifacts=fingerprint([*generated, *(directory.glob('*.log'))]))
        except BaseException:
            report.update(status='FAIL', finished_utc=timestamp()); raise
        finally:
            save()
            print('Retained union-LUT model control:', directory / 'report.json', flush=True)


if __name__ == '__main__': unittest.main()
