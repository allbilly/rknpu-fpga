"""Harness controls plus a small real exporter check, not numerical/FPGA acceptance."""
from copy import deepcopy
from pathlib import Path
import re
import json
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_dsp_mapped_array as runner
from test_dsp_board_area_control import fixture


def mapped_fixture():
    design, _, _, kernel, _ = fixture()
    ports = {}; bit = 10000
    for name, direction, width in (('data', 'input', 512), ('weight', 'input', 512),
        ('data_mask', 'input', 32), ('weight_mask', 'input', 32),
        ('result', 'output', 44), ('invalid', 'output', 1)):
        ports[name] = dict(direction=direction, bits=list(range(bit, bit + width))); bit += width
    body = design['modules'][kernel]; body['ports'] = ports
    body['parameter_default_values'] = {'ATOMIC_C': f'{32:032b}'}
    for cell in body['cells'].values():
        cell['parameters']['USE_MULT'] = 'MULTIPLY'
        cell['connections'] = {'A': ports['data']['bits'][:30], 'B': ports['weight']['bits'][:18],
            'P': ports['result']['bits'] + [ports['invalid']['bits'][0]] * 4}
    return design, kernel


class DspMappedArrayControls(unittest.TestCase):
    def test_full_partition_aliasing_is_reversible_and_keeps_actual_bodies(self):
        design, kernel = mapped_fixture(); before = deepcopy(design)
        renamed, counts = runner.simulation_partition(design)
        self.assertEqual(design, before)
        self.assertEqual(counts['DSP48E1'], 32)
        self.assertEqual(set(renamed['modules']), {runner.CMAC, runner.SIM_KERNEL})
        self.assertEqual(renamed['modules'][runner.SIM_KERNEL], design['modules'][kernel])
        cells = renamed['modules'][runner.CMAC]['cells']
        self.assertEqual(len(cells), 16)
        self.assertEqual([c['type'] for c in cells.values()], [runner.SIM_KERNEL] * 16)
        aliased, names = runner.hardware_instance_aliases(renamed)
        self.assertEqual(len(names[runner.SIM_KERNEL]), 32)
        self.assertEqual(len(names[runner.CMAC]), 16)
        self.assertEqual([c['parameters'] for c in aliased['modules'][runner.SIM_KERNEL]['cells'].values()],
            [c['parameters'] for c in renamed['modules'][runner.SIM_KERNEL]['cells'].values()])

    def test_export_default_declarations_separate_reversibly_without_primitive_parameter_waiver(self):
        design, _ = mapped_fixture(); partition, _ = runner.simulation_partition(design)
        original = deepcopy(partition); exported, interfaces = runner.export_interface(partition)
        self.assertEqual(partition, original)
        restored = deepcopy(exported)
        for name, values in interfaces.items(): restored['modules'][name]['parameter_default_values'] = values
        self.assertEqual(restored, original)
        self.assertTrue(all('parameter_default_values' not in m for m in exported['modules'].values()))
        self.assertEqual(exported['modules'][runner.SIM_KERNEL]['cells'], original['modules'][runner.SIM_KERNEL]['cells'])
        signature = runner.circuit_signature(exported)
        changed = deepcopy(exported); changed['modules'][runner.SIM_KERNEL]['cells']['dsp0']['parameters']['USE_MULT'] = 'NONE'
        self.assertNotEqual(runner.circuit_signature(changed), signature)
        for change in ('default', 'missing', 'override'):
            bad = deepcopy(original)
            if change == 'default': bad['modules'][runner.SIM_KERNEL]['parameter_default_values']['ATOMIC_C'] = f'{31:032b}'
            elif change == 'missing': bad['modules'][runner.SIM_KERNEL].pop('parameter_default_values')
            else: bad['modules'][runner.CMAC]['cells']['kernel0']['parameters']['ATOMIC_C'] = f'{31:032b}'
            with self.subTest(change=change), self.assertRaises(AssertionError): runner.export_interface(bad)

    def test_real_yosys_export_keeps_dsp_string_parameters_and_all_actual_pin_incidence(self):
        executable = shutil.which('yosys')
        if not executable: self.skipTest('yosys unavailable; real exporter control not executed')
        fixture = ROOT / 'tests/cmac/dsp_export_parameter_control.sv'
        with TemporaryDirectory(prefix='rknpu-dsp-export-control-') as name:
            out = Path(name); original, imported, partition, exported, roundtrip = [out / n for n in
                ('original.json', 'imported.json', 'actual_partition.json', 'exported.v', 'roundtrip.json')]
            def run(script):
                argv = [executable, '-Q', '-T', '-p', script]
                print('REAL_EXPORT_CONTROL_ONLY argv=' + json.dumps(argv), flush=True)
                proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertNotRegex(proc.stdout + proc.stderr, r'(?im)warning:|ERROR:')
            run('read_verilog -sv ' + json.dumps(str(fixture)) + '; write_json ' + json.dumps(str(original)))
            raw = json.loads(original.read_text()); separated, _ = runner.export_interface(raw)
            self.assertTrue(all(c['type'] in {*raw['modules'], 'DSP48E1'}
                for m in raw['modules'].values() for c in m['cells'].values()))
            aliased, aliases = runner.hardware_instance_aliases(separated)
            self.assertTrue(all(len(m) == len(set(m.values())) for m in aliases.values()))
            partition.write_text(json.dumps(aliased) + '\n')
            run('read_json ' + json.dumps(str(original)) + '; write_json ' + json.dumps(str(imported)))
            run('read_json ' + json.dumps(str(partition)) +
                '; write_verilog -noattr -noexpr -norename -nodec -nohex ' + json.dumps(str(exported)))
            loaded = json.loads(imported.read_text())
            run('read_verilog -sv ' + json.dumps(str(exported)) + '; write_json ' + json.dumps(str(roundtrip)))
            result = json.loads(roundtrip.read_text())
            print('REAL_EXPORT_CONTROL_ONLY interfaces=' + json.dumps({label: {n: m.get('parameter_default_values')
                for n, m in value['modules'].items()} for label, value in
                (('original', raw), ('imported', loaded), ('roundtrip', result))}), flush=True)
            self.assertEqual(runner.circuit_signature(loaded), runner.circuit_signature(raw))
            self.assertTrue(all('parameter_default_values' not in m for m in result['modules'].values()))
            self.assertEqual(runner.circuit_signature(result), runner.circuit_signature(aliased))
            self.assertIn('MULTIPLY', exported.read_text())
            print('REAL_EXPORT_CONTROL_ONLY tool=' + subprocess.check_output([executable, '-V'], text=True).strip(), flush=True)

    def test_wrong_geometry_missing_products_ports_and_sequential_kernel_rejected(self):
        for change in ('geometry', 'kernel', 'dsp', 'port', 'mask', 'sequential'):
            design, kernel = mapped_fixture()
            if change == 'geometry': design['modules'][runner.CMAC]['parameter_default_values']['TAG_WIDTH'] = f'{34:032b}'
            elif change == 'kernel': design['modules'][runner.CMAC]['cells'].pop('kernel15')
            elif change == 'dsp': design['modules'][kernel]['cells'].pop('dsp31')
            elif change == 'port': design['modules'][kernel]['ports']['result']['bits'].pop()
            elif change == 'mask': design['modules'][kernel]['ports']['data_mask']['direction'] = 'output'
            else:
                design['modules'][kernel]['cells']['ff'] = dict(type='FDCE', parameters={}, connections={})
                design['modules']['FDCE'] = dict(attributes={'blackbox': '1'}, cells={})
            with self.subTest(change=change), self.assertRaises(AssertionError): runner.simulation_partition(design)

    def test_original_bench_only_four_literal_edits_preserve_every_assertion_and_x_guard(self):
        original = runner.SOURCE_BENCH.read_text(); mapped = runner.mapped_bench(original)
        changes = [
            ('module tb_cmac_fp16_array #(', 'module ' + runner.BENCH + ' #('),
            ('rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);',
                runner.CMAC + ' dut(.*); // Actual mapped C32/K16/TAG35 ports, no parameter override.'),
            ('        if(!$value$plusargs("VECTORS=%s",path)',
                '        #200; // Functional-model startup, not UNISIM GSR or routed timing.\n'
                '        if(!$value$plusargs("VECTORS=%s",path)'),
            ('$display("PASS sized FP16 CMAC', '$display("PASS binary mapped DSP FP16 CMAC')]
        restored = mapped
        for before, after in changes:
            self.assertEqual(restored.count(after), 1); restored = restored.replace(after, before)
        self.assertEqual(restored, original)
        self.assertEqual(re.findall(r'\$fatal\([^\n]+', mapped), re.findall(r'\$fatal\([^\n]+', original))
        self.assertIn('`ifndef VERILATOR', mapped)
        self.assertIn('if(!error||out_valid||in_ready) $fatal(1,"unknown input accepted");', mapped)
        for bad in (original + original, original.replace('module tb_cmac_fp16_array #(', 'module broken #(')):
            with self.assertRaises(AssertionError): runner.mapped_bench(bad)

    def test_exact_full_binary_marker_keeps_hold_reset_retirement_and_zero_x_fault_count(self):
        self.assertEqual(runner.validate_result(runner.EXPECTED, 0), runner.EXPECTED)
        for text, code in [(runner.EXPECTED, 1), (runner.EXPECTED.replace('frames=208', 'frames=1'), 0),
            (runner.EXPECTED.replace('checked_outputs=3328', 'checked_outputs=16'), 0),
            (runner.EXPECTED.replace('retired_outputs=3312', 'retired_outputs=3328'), 0),
            (runner.EXPECTED.replace('reset_canceled=16', 'reset_canceled=0'), 0),
            (runner.EXPECTED.replace('held_cycles=520', 'held_cycles=0'), 0),
            (runner.EXPECTED.replace('faults=0', 'faults=1'), 0),
            (runner.EXPECTED + '\nPASS other', 0), (runner.EXPECTED + '\n%Error: unknown', 0)]:
            with self.subTest(text=text, code=code), self.assertRaises(AssertionError): runner.validate_result(text, code)
        self.assertIn('faults=1', runner.replay.native.EXPECTED)

    def test_verilator_expected_first_frame_fatal_not_warning_or_unrelated_error(self):
        text = ('[216000] %Error: control.sv:42: Assertion failed in bench: sized array mismatch frame=0 got=0 expected=1\n'
            '%Error: control.sv:42: Verilog $stop\nAborting...\n')
        runner.validate_result(text, 134, True)
        for bad, code in [(text, 0), (text.replace('frame=0', 'frame=1'), 134),
            ('%Error: missing vectors', 134), (text + '\nPASS other', 134),
            (text + '\n%Error: another failure', 134), (text + '\n%Warning-WIDTH: unrelated', 134),
            (text + '\nwarning: unsupported', 134)]:
            with self.subTest(text=bad, code=code), self.assertRaises(AssertionError): runner.validate_result(bad, code, True)

    def test_negative_changes_only_lowest_first_expected_output_bit_not_operands(self):
        original = '\n'.join(['0123456789abcdef'] * 208) + '\n'
        changed = runner.negative_vectors(original)
        before, after = original.splitlines(), changed.splitlines()
        self.assertEqual(after[1:], before[1:]); self.assertEqual(after[0][:-1], before[0][:-1])
        self.assertEqual(int(after[0], 16) ^ int(before[0], 16), 1)
        for bad in (original[:-17], original.replace('0123', 'x123', 1)):
            with self.assertRaises(AssertionError): runner.negative_vectors(bad)

    def test_only_export_model_metadata_and_exact_generated_timestamp_warnings_allowed(self):
        with TemporaryDirectory(prefix='rknpu-dsp-mapped-control-') as name:
            out = Path(name); (out / 'cell').mkdir()
            wrapper = out / 'cell' / (runner.BLOCK + '.sv')
            wrapper.write_text('time last_combo_seqnum__V;\nlogic arithmetic_result;\n')
            allowed = [
                f'%Warning-DECLFILENAME: {out}/mapped_partition.v:1:1: exported module name',
                f'%Warning-UNUSEDSIGNAL: {out}/mapped_partition.v:2:1: unused net alias',
                f'%Warning-UNUSEDPARAM: {out}/xilinx_functional_models.v:3:1: unused model parameter',
                f'%Warning-SPECIFYIGN: {out}/xilinx_functional_models.v:4:1: timing metadata',
                f'%Warning-GENUNNAMED: {out}/xilinx_functional_models.v:5:1: generator metadata',
                f'%Warning-UNUSEDSIGNAL: {wrapper}:1:1: protectlib timestamp']
            self.assertEqual(len(runner.validate_diagnostics('\n'.join(allowed), out)), len(allowed))
            rejected = [
                f'%Warning-INITIALDLY: {out}/xilinx_functional_models.v:1:1: changed delay',
                f'%Warning-UNOPTFLAT: {out}/mapped_partition.v:1:1: feedback',
                f'%Warning-UNUSEDSIGNAL: {wrapper}:2:1: arithmetic state',
                f'%Warning-UNUSEDSIGNAL: {out}/unrelated.sv:1:1: other source',
                '%Warning-WIDTH: unparsed diagnostic', '%Error: failed', 'warning: failed', 'sorry: failed']
            for text in rejected:
                with self.subTest(text=text), self.assertRaises(AssertionError): runner.validate_diagnostics(text, out)


if __name__ == '__main__': unittest.main()
