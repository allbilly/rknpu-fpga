"""Model-control source/shape/result guards, not HDL or FPGA acceptance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_dsp_prefix_primitive_models as runner


def fixture():
    params = {k: f'{v:032b}' if type(v) is int else v for k, v in runner.PARAMETERS.items()}
    connections = {k: list(reversed(f'{value:0{width}b}')) for k, (width, value) in runner.CONSTANTS.items()}
    connections.update(A=list(range(100, 130)), B=list(range(200, 218)), P=list(range(300, 348)))
    cell = dict(type='DSP48E1', parameters=params, connections=connections,
        port_directions={k: 'output' if k == 'P' else 'input' for k in connections})
    return dict(modules={runner.KERNEL: dict(cells={f'dsp{i}': deepcopy(cell) for i in range(32)})})


class PrimitiveModelControls(unittest.TestCase):
    def test_exact_actual_dsp_configuration_constants_and_full_32_instance_source_required(self):
        good = fixture(); self.assertEqual(runner.validate_configuration(good, runner.BENCH.read_text()), 32)
        for change in ('count', 'pipeline', 'string', 'extra_parameter', 'bias', 'mode', 'pin', 'direction', 'width'):
            bad = deepcopy(good); cells = bad['modules'][runner.KERNEL]['cells']; cell = cells['dsp0']
            if change == 'count': cells.pop('dsp31')
            elif change == 'pipeline': cell['parameters']['MREG'] = f'{1:032b}'
            elif change == 'string': cell['parameters']['USE_MULT'] = 'NONE'
            elif change == 'extra_parameter': cell['parameters']['UNKNOWN'] = f'{0:032b}'
            elif change == 'bias': cell['connections']['C'][0] = '1'
            elif change == 'mode': cell['connections']['OPMODE'][0] = '0'
            elif change == 'pin': cell['connections']['CLK'] = ['0']
            elif change == 'direction': cell['port_directions']['P'] = 'input'
            else: cell['connections']['A'].pop()
            with self.subTest(change=change), self.assertRaises(AssertionError):
                runner.validate_configuration(bad, runner.BENCH.read_text())

    def test_source_parameter_bias_mode_and_single_primitive_body_are_required(self):
        text = runner.BENCH.read_text()
        for before, after in (('.AREG(0)', '.AREG(1)'), ('"MULTIPLY"', '"NONE"'),
            ("BIAS = 48'h000055550000", "BIAS = 48'h000055550001"),
            (".OPMODE(7'b0110101)", ".OPMODE(7'b0000101)"),
            ('CARRY4 actual_carry(', 'CARRY4 wrong_carry(')):
            with self.subTest(before=before), self.assertRaises(AssertionError):
                runner.validate_configuration(fixture(), text.replace(before, after))
        with self.assertRaises(AssertionError): runner.validate_configuration(fixture(), text + text)

    def test_full_corpus_markers_and_two_state_four_state_claims_cannot_be_interchanged(self):
        for simulator in ('iverilog', 'verilator'):
            good = runner.expected(simulator); runner.validate_result(good, 0, simulator)
            other = 'verilator' if simulator == 'iverilog' else 'iverilog'
            for text, code in ((good, 1), (runner.expected(other), 0),
                (good.replace('dsp=4259904', 'dsp=1'), 0), (good.replace('carry_binary=1024', 'carry_binary=1'), 0),
                (good.replace('seed=35883216', 'seed=0'), 0), (good + '\nPASS other', 0),
                (good + '\n%Warning-WIDTH: unsupported', 0), (good + '\n%Error: unrelated', 0)):
                with self.subTest(simulator=simulator, text=text), self.assertRaises(AssertionError):
                    runner.validate_result(text, code, simulator)

    def test_each_real_negative_requires_its_own_case_zero_failure_and_no_positive_marker(self):
        for kind in ('DSP', 'CARRY'):
            text = 'FATAL: control.sv:1: primitive ' + kind + ' mismatch case=0 got=0 expected=1'
            runner.validate_result(text, 1, 'iverilog', kind)
            for bad, code in ((text, 0), (text.replace('case=0', 'case=1'), 1),
                ('FATAL: missing input', 1), (text + '\nPASS other', 1),
                (text + '\n%Error: unrelated', 1), (text + '\nwarning: unsupported', 1)):
                with self.subTest(kind=kind, text=bad), self.assertRaises(AssertionError):
                    runner.validate_result(bad, code, 'iverilog', kind)


if __name__ == '__main__': unittest.main()
