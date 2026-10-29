"""Frontend-only structural controls; never whole-board mapping or FPGA evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prepare_dsp_prefix_board_mapping as runner
from test_dsp_prefix_board_area_control import fixture


def frontend_fixture():
    design, _, top, kernel, _ = fixture()
    raw, _, _ = runner.mapping.partition(design)
    # Actual imported array metadata, retained during the module-key alias.
    raw['modules'][runner.mapping.CMAC]['attributes'] = {'hdlname': runner.mapping.CMAC}
    part, _ = runner.mapping.parameter_binding(raw, runner.mapping.array.DSP_ARRAY.read_text())
    graph = deepcopy(design)
    graph['modules'].pop(runner.mapping.CMAC)
    graph['modules'].update(deepcopy(part['modules']))
    ports = deepcopy(part['modules'][runner.mapping.MAPPED_CMAC]['ports'])
    wrapper = 'CONTROL_CHECKED_PREFIX_WRAPPER'
    graph['modules'][wrapper] = dict(attributes={'hdlname': runner.mapping.CMAC}, ports=ports,
        cells={'actual_partition': dict(type=runner.mapping.MAPPED_CMAC, parameters={},
            connections={n: p['bits'] for n, p in ports.items()})})
    graph['modules']['CONTROL_NATIVE_SHELL'] = dict(ports={}, cells={'native': dict(type='$dff')})
    graph['modules'][top] = dict(ports={'SYS_CLK': dict(direction='input', bits=[10]),
        'SYS_RSTN': dict(direction='input', bits=[11]), 'led_3bits_tri_o': dict(direction='output', bits=[12, 13, 14])},
        cells={'cmac': dict(type=wrapper), 'shell': dict(type='CONTROL_NATIVE_SHELL')})
    return graph, part, top, kernel, wrapper


class PrefixBoardMappingPreparationControls(unittest.TestCase):
    def test_full_imported_array_and_all_16_kernel_circuits_unchanged_with_unmapped_shell(self):
        graph, part, top, kernel, _ = frontend_fixture()
        original = deepcopy(graph)
        result = runner.validate_frontend(graph, top, kernel, part)
        self.assertEqual(graph, original)
        self.assertEqual(result['mapped_kernel_instances'], 16)
        self.assertEqual(result['retained_cmac_dsps'], 512)
        self.assertTrue(result['native_shell_unmapped'])
        self.assertEqual(result['reachable_instances'][kernel], 16)
        self.assertEqual(result['reachable_instances']['CONTROL_NATIVE_SHELL'], 1)
        self.assertEqual(result['reachable_instances'][runner.mapping.MAPPED_CMAC], 1)

    def test_changed_kernel_array_delegate_and_board_boundary_rejected(self):
        for change in ('kernel_count', 'kernel_pin', 'array_pin', 'delegate', 'override',
            'wrapper_count', 'constant_io', 'narrow_io', 'cycle', 'native_fallback'):
            graph, part, top, kernel, wrapper = frontend_fixture()
            if change == 'kernel_count': graph['modules'][runner.mapping.MAPPED_CMAC]['cells'].pop('kernel15')
            elif change == 'kernel_pin': graph['modules'][kernel]['cells']['dsp0']['connections']['A'][0] = '0'
            elif change == 'array_pin': graph['modules'][runner.mapping.MAPPED_CMAC]['ports']['in_data']['bits'][0] = '0'
            elif change == 'delegate':
                graph['modules'][wrapper]['cells']['actual_partition']['connections']['in_data'][0] = '0'
            elif change == 'override': graph['modules'][wrapper]['cells']['actual_partition']['parameters']['ATOMIC_C'] = '1'
            elif change == 'wrapper_count': graph['modules'][top]['cells']['second_cmac'] = dict(type=wrapper)
            elif change == 'constant_io': graph['modules'][top]['ports']['led_3bits_tri_o']['bits'][0] = '0'
            elif change == 'narrow_io': graph['modules'][top]['ports']['led_3bits_tri_o']['bits'].pop()
            elif change == 'cycle': graph['modules']['CONTROL_NATIVE_SHELL']['cells']['loop'] = dict(type=top)
            else:
                graph['modules']['CONTROL_NATIVE_SHELL']['attributes'] = {'hdlname': 'rk_cmac_fp16_lane_dsp_prefix'}
            with self.subTest(change=change), self.assertRaises(AssertionError):
                runner.validate_frontend(graph, top, kernel, part)

    def test_frontend_stops_before_synthesis_abc_area_route_or_programming(self):
        spec = json.loads(runner.mapping.replay.preparation.SPEC.read_text())
        script = runner.frontend_script(spec, [ROOT / 'CONTROL_ONLY.sv'],
            ROOT / 'CONTROL_ONLY.json', ROOT / 'build/CONTROL_ONLY')
        self.assertIn('select -assert-count 16', script)
        self.assertIn('proc;\nopt_clean;\ncheck -assert;', script)
        self.assertIn('frontend_hierarchy.json', script)
        self.assertIn('write_json -selected ', script)
        self.assertNotIn('blackbox ', script)
        for token in ('synth_xilinx', 'abc', 'flatten', 'write_bitstream', 'program_hw', 'place_design', 'route_design'):
            self.assertNotIn(token, script)
        for field, value in [('part', 'xc7k325tffg900-2'), ('clock_period_ns', 40),
            ('constraints', 'CONTROL_RELAXED.xdc'), ('top', 'CONTROL_SMALL')]:
            bad = dict(spec, **{field: value})
            with self.subTest(field=field), self.assertRaises(AssertionError):
                runner.frontend_script(bad, [], ROOT / 'CONTROL_ONLY.json', ROOT / 'build/CONTROL_ONLY')

    def test_independent_own_area_native_and_compile_verifiers_required_and_leaf_bound(self):
        real = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
        area = dict(parent_report=str(real.relative_to(ROOT)), parent_source_sha256='a' * 64)
        native = dict(lane_report=area['parent_report'], lane_source_sha256='a' * 64)
        compiled = dict(lane_report=area['parent_report'])
        with patch.object(runner.mapping, 'verify_area', return_value=(area, 'CONTROL_RAW', 'CONTROL_GRAPH')) as av, \
            patch.object(runner.mapping.replay, 'verify_native', return_value=native) as nv, \
            patch.object(runner.mapping.replay, 'verify_prepared', return_value=(compiled, None, [])) as pv:
            result = runner.verify_parents(real, real, real, 'CONTROL_SPEC')
            self.assertEqual(result, (area, native, compiled, 'CONTROL_RAW', 'CONTROL_GRAPH'))
            av.assert_called_once_with(real); nv.assert_called_once_with(real); pv.assert_called_once_with(real, 'CONTROL_SPEC')
            for change in ('leaf_hash', 'compile_leaf'):
                changed = dict(native); prep = dict(compiled)
                if change == 'leaf_hash': changed['lane_source_sha256'] = 'b' * 64
                else: prep['lane_report'] = 'CONTROL_DIFFERENT_PREFIX_LEAF'
                nv.return_value = changed; pv.return_value = (prep, None, [])
                with self.subTest(change=change), self.assertRaises(AssertionError):
                    runner.verify_parents(real, real, real, 'CONTROL_SPEC')
            for verifier in (av, nv, pv):
                nv.return_value = native; pv.return_value = (compiled, None, [])
                verifier.side_effect = AssertionError('CONTROL rejected RUNNING/failed evidence')
                with self.assertRaises(AssertionError): runner.verify_parents(real, real, real, 'CONTROL_SPEC')
                verifier.side_effect = None


if __name__ == '__main__': unittest.main()
