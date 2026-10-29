"""Observability script safety controls, not mapped or physical-board proof."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import prepare_observed_board as runner


def source_script():
    return '\n'.join(['read_verilog -lib +/xilinx/cells_sim.v;', 'read_json "partition.json";',
        'read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST "source.sv";',
        'hierarchy -check -top ' + runner.TOP + ';',
        'select -assert-mod-count 1 A:hdlname=' + runner.KERNEL + ';',
        'select -assert-mod-count 1 A:keep_hierarchy=1;', runner.MARKER, 'write_json "old_output.json";']) + '\n'


class ObservedBoardPrepareControls(unittest.TestCase):
    def test_every_exact_bench_signal_is_retained_before_optimization(self):
        text = runner.premap_script(source_script(), Path('new_output.json'))
        self.assertEqual(text.count('select -assert-count 1 '), 22)
        self.assertEqual(text.count('setattr -set keep 1 '), 22)
        for name in runner.WIDTHS: self.assertIn(runner.TOP + '/w:' + name + ';', text)
        self.assertIn('setattr -set fsm_encoding "none" ' + runner.TOP + '/w:demo.state;', text)
        self.assertLess(text.index('proc;'), text.index('flatten;'))
        self.assertLess(text.index('flatten;'), text.index('setattr -set keep'))
        self.assertLess(text.index('setattr -set fsm_encoding'), text.index('opt_expr -keepdc'))
        self.assertIn('opt_expr -keepdc ' + runner.TOP + ';', text)
        self.assertIn('opt_clean ' + runner.TOP + ';', text)
        self.assertIn('check -assert;', text)
        for forbidden in ('setundef', '-undriven', '-mux_undef', '-noassert'):
            self.assertNotIn(forbidden, text)
        self.assertNotIn('synth_xilinx ', text)
        self.assertNotIn('old_output.json', text)
        self.assertEqual(text.count('write_json '), 1)
        self.assertIn('select ' + runner.TOP + ' A:hdlname=' + runner.KERNEL + ';', text)
        self.assertIn('select -assert-mod-count 2 %;', text)
        self.assertIn('write_json -selected "new_output.json";', text)
        for forbidden in ('blackbox ', 'delete ', 'proc =FDCE'):
            self.assertNotIn(forbidden, text)

    @unittest.skipUnless(shutil.which('yosys'), 'Real Yosys unavailable; export fixture not executed')
    def test_real_library_processes_excluded_without_removing_primitive_instances(self):
        # This is a real tool/export control, not a full board or numerical test.
        # FDCE is the exact library type that caused the complete preparation
        # export to fail. The full implementation, including its FDCE cell,
        # must survive the selected-module export.
        with tempfile.TemporaryDirectory(prefix='rk-observed-export-') as directory:
            directory = Path(directory)
            source = directory / 'fixture.v'
            source.write_text('(* keep_hierarchy=1, hdlname="' + runner.KERNEL + '" *)\n'
                'module kernel(input C,CE,CLR,D, output Q);\n'
                'FDCE #(.INIT(1\'b0)) ff(.C(C),.CE(CE),.CLR(CLR),.D(D),.Q(Q)); endmodule\n'
                'module ' + runner.TOP + '(input C,CE,CLR,D, output Q);\n'
                'kernel actual(.C(C),.CE(CE),.CLR(CLR),.D(D),.Q(Q)); endmodule\n')
            prefix = ('read_verilog -lib +/xilinx/cells_sim.v;\n'
                'read_verilog ' + json.dumps(str(source)) + ';\n'
                'hierarchy -check -top ' + runner.TOP + ';\nproc;\nflatten;\ncheck -assert;\n')
            negative = subprocess.run(['yosys', '-Q', '-T', '-p', prefix + 'write_json ' + json.dumps(str(directory / 'all.json')) + ';'],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            self.assertNotEqual(negative.returncode, 0)
            self.assertIn('Module FDCE contains processes', negative.stdout)
            output = directory / 'selected.json'
            positive = subprocess.run(['yosys', '-Q', '-T', '-p', prefix + runner.implementation_export(output)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
            self.assertEqual(positive.returncode, 0, positive.stdout)
            self.assertNotIn('Warning:', positive.stdout)
            self.assertIn('Found and reported 0 problems.', positive.stdout)
            design = json.loads(output.read_text())
            self.assertEqual(set(design['modules']), {runner.TOP, 'kernel'})
            self.assertEqual(design['modules'][runner.TOP]['cells']['actual']['type'], 'kernel')
            primitive = design['modules']['kernel']['cells']['ff']
            self.assertEqual(primitive['type'], 'FDCE')
            self.assertEqual(set(primitive['connections']), {'C','CE','CLR','D','Q'})
            self.assertEqual(primitive['parameters']['INIT'], '0')

    def test_changed_import_stage_shape_and_added_side_effects_rejected(self):
        original = source_script()
        for text in [original.replace(runner.MARKER, ''), original + runner.MARKER,
                     original.replace('hierarchy -check', 'hierarchy'),
                     original.replace('keep_hierarchy=1', 'keep_hierarchy=0'),
                     original.replace('read_json "partition.json";', 'delete *;'),
                     'write_json "unexpected.json";\n' + original]:
            with self.subTest(text=text), self.assertRaises(AssertionError):
                runner.premap_script(text, Path('new.json'))

    def test_only_three_exact_source_lowering_messages_are_classified(self):
        text = '\n'.join(runner.LOWERING_WARNINGS)
        self.assertEqual(runner.classify_warnings(text), runner.LOWERING_WARNINGS)
        for bad in [text + '\nWarning: Wire top.bad is used but has no driver.',
                    text.replace('tree.v:41', 'tree.v:42'), text.replace('temp_array', 'unknown_array'),
                    text + '\n' + next(iter(runner.LOWERING_WARNINGS))]:
            with self.subTest(log=bad), self.assertRaises(AssertionError): runner.classify_warnings(bad)

    def test_export_boundary_rejects_missing_instances_modules_or_changed_kernel(self):
        kernel = dict(ports={'D': {'direction': 'input', 'bits': [2]},
                             'Q': {'direction': 'output', 'bits': [3]}},
            cells={'primitive': {'type': 'FDCE', 'parameters': {'INIT': '0'},
                'connections': {'D': [2], 'Q': [3]}}})
        original = {'modules': {'kernel': kernel}}
        design = {'modules': {'kernel': deepcopy(kernel), runner.TOP: {
            'cells': {str(i): {'type': 'kernel'} for i in range(16)}}}}
        runner.verify_implementation_boundary(design, original, 'kernel')
        for label in ('missing_instance', 'missing_module', 'extra_module', 'changed_primitive', 'changed_pin'):
            changed = deepcopy(design)
            if label == 'missing_instance': del changed['modules'][runner.TOP]['cells']['0']
            elif label == 'missing_module': del changed['modules']['kernel']
            elif label == 'extra_module': changed['modules']['FDCE'] = {}
            elif label == 'changed_primitive': changed['modules']['kernel']['cells']['primitive']['type'] = 'FDRE'
            else: changed['modules']['kernel']['cells']['primitive']['connections']['D'] = ['0']
            with self.subTest(case=label), self.assertRaises(AssertionError):
                runner.verify_implementation_boundary(changed, original, 'kernel')

    def test_recoded_missing_dead_and_unretained_observations_still_rejected(self):
        # Every force bit is distinct and live in the fixture. It checks only
        # audit logic; it is not presented as actual hardware preparation.
        bit = 2; nets = {}; ports = {}
        for name, width in runner.WIDTHS.items():
            bits = list(range(bit, bit + width)); bit += width
            nets[name] = dict(bits=bits, attributes={'keep': '1'})
            # Separate lists: mutating a debug net must not also mutate the
            # exported port and accidentally make the new bit live.
            ports[name] = dict(direction='output', bits=bits.copy())
        nets['demo.state']['attributes']['fsm_encoding'] = 'none'
        module = dict(netnames=nets, ports=ports, cells={})
        bench = runner.BENCH.read_text()
        self.assertEqual(len(runner.verify_observations(module, bench)), 22)
        for label in ('recoded', 'missing', 'dead', 'keep', 'encoding'):
            changed = deepcopy(module)
            if label == 'recoded': changed['netnames']['demo.state']['bits'] *= 2
            elif label == 'missing': del changed['netnames']['demo.error_code']
            elif label == 'dead': changed['netnames']['demo.mem_req_addr']['bits'][0] = bit + 10
            elif label == 'keep': changed['netnames']['demo.error_code']['attributes']['keep'] = '0'
            else: changed['netnames']['demo.state']['attributes']['fsm_encoding'] = 'auto'
            with self.subTest(label=label), self.assertRaises(AssertionError): runner.verify_observations(changed, bench)


if __name__ == '__main__': unittest.main()
