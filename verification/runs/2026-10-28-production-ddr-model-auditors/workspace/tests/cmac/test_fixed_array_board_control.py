"""Runner contract tests; synthetic control fixtures are not HDL evidence."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import test_fixed_array_board as runner


def manifest(root, names):
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(names, key=Path)}
    text = ''.join(f'{digest}  {name}\n' for name, digest in files.items())
    return {'files': files, 'sha256': hashlib.sha256(text.encode()).hexdigest()}


def result(mode):
    good = mode in (0, 3, 4, 5, 6)
    fields = [mode, 2 if mode == 6 else int(good), int(mode in (3, 4, 5, 6)), int(not good), 4096]
    fields += ([4096, 196, 6528, 64, 64] if good else [0, 1, 0, 0, 0] if mode == 1 else
               [0, 196, 20, 0, 0] if mode == 8 else [1, 196, 6528, 64, 64])
    fields += [50000]
    keys = 'mode success resets faults init check cmd_reads operand_reads writes acks cycles'.split()
    return 'PASS C32 K16 BRAM board RTL ' + ' '.join(f'{key}={value}' for key, value in zip(keys, fields)) + '; no physical FPGA test'


class FixedBoardControl(unittest.TestCase):
    def test_single_internal_substitution(self):
        original = (ROOT / runner.JOIN).read_text()
        expected = original.replace('    rk_cmac_fp16_array #', '    rk_cmac_fp16_array_fixed #')
        self.assertEqual(runner.fixed_join(original), expected)
        for invalid in ('module unrelated; endmodule\n', original + original,
                        original.replace('.TAG_WIDTH(TAG_WIDTH+2)', '.TAG_WIDTH(TAG_WIDTH+1)')):
            with self.assertRaises(AssertionError):
                runner.fixed_join(invalid)

    def test_source_list_preserves_raw_path(self):
        spec = json.loads((ROOT / 'fpga/cmac/array_sources.json').read_text())
        generated = ROOT / 'build/MOCK-fixed-board/rk_cmac_cacc_fp16_array.sv'
        sources = runner.simulation_sources(spec, generated)
        expected = [ROOT / name for name in spec['simulation_helpers'] + spec['synthesis']
                    if name not in (runner.ORIGINAL_CELL, runner.ORIGINAL_ARRAY, runner.JOIN)]
        self.assertEqual(set(sources), set(expected + [ROOT / runner.ROWS, ROOT / runner.CELL, ROOT / runner.ARRAY, generated]))
        for name in (runner.ORIGINAL_CELL, runner.ORIGINAL_ARRAY, runner.JOIN):
            invalid = copy.deepcopy(spec)
            invalid['synthesis'].append(name)
            with self.assertRaises(AssertionError):
                runner.simulation_sources(invalid, generated)

    def test_all_nine_unchanged_contracts(self):
        for mode in range(9):
            text = result(mode)
            self.assertEqual(runner.validate_result(text + '\n', mode), text)
        with self.assertRaises(AssertionError):
            runner.validate_result(result(0), 9)
        for text in (result(0) + '\n' + result(0), result(0).replace('no physical FPGA test', 'physical FPGA PASS'), ''):
            with self.assertRaises(AssertionError):
                runner.validate_result(text, 0)

    def test_partial_readback_or_counts_never_pass(self):
        for mode in range(9):
            for field, value in (('success', 9), ('resets', 9), ('faults', 9), ('init', 4095),
                                 ('check', 17), ('cmd_reads', 7), ('operand_reads', 13),
                                 ('writes', 7), ('acks', 7), ('cycles', 0), ('cycles', 1048576)):
                changed = re.sub(r'\b' + field + r'=\d+', f'{field}={value}', result(mode))
                with self.assertRaises(AssertionError, msg=f'mode={mode} {field}'):
                    runner.validate_result(changed, mode)

    def test_watchdog_read_count_boundary(self):
        for reads in (20, 21):
            runner.validate_result(result(8).replace('operand_reads=20', f'operand_reads={reads}'), 8)
        for reads in (19, 22):
            with self.assertRaises(AssertionError):
                runner.validate_result(result(8).replace('operand_reads=20', f'operand_reads={reads}'), 8)

    def test_manifest_binding_and_path_safety(self):
        with tempfile.TemporaryDirectory(prefix='rk-fixed-board-controls-') as directory, patch.object(runner, 'ROOT', Path(directory)):
            root = Path(directory)
            (root / 'source.sv').write_text('MOCK source, not HDL validation\n')
            source = manifest(root, ['source.sv'])
            runner.verify_manifest(source)
            invalid = copy.deepcopy(source); invalid['sha256'] = '0' * 64
            with self.assertRaisesRegex(AssertionError, 'manifest digest'):
                runner.verify_manifest(invalid)
            for name in ('../outside', '/absolute'):
                with self.assertRaisesRegex(AssertionError, 'escapes workspace'):
                    runner.verify_manifest({'files': {name: '0' * 64}, 'sha256': '0' * 64})
            (root / 'source.sv').write_text('MODIFIED MOCK\n')
            with self.assertRaisesRegex(AssertionError, 'Stale evidence'):
                runner.verify_manifest(source)

    def test_native_parent_cannot_be_running_or_baseline(self):
        with tempfile.TemporaryDirectory(prefix='rk-fixed-native-controls-') as directory:
            path = Path(directory) / 'report.json'
            for status in ('RUNNING', 'FAIL', 'PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY', 'PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY'):
                path.write_text(json.dumps({'status': status}))
                with self.assertRaisesRegex(AssertionError, 'Completed fixed full-array'):
                    runner.verify_fixed_native(path)
        # Mock manifests isolate the metadata gates here. Actual file/manifest
        # binding is tested separately; none of these fixtures are HDL evidence.
        with tempfile.TemporaryDirectory(prefix='rk-fixed-proof-controls-') as directory, \
                patch.object(runner, 'ROOT', Path(directory)), patch.object(runner, 'verify_manifest'):
            root = Path(directory); path = root / 'report.json'
            row_path = root / 'rows_report_snapshot.json'
            rows = dict(status='PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY', formal_result=runner.ROW_FORMAL,
                        simulation_result='PASS fixed FP16 rows comparisons=2097152 resets=4 seed=3588f016; post-configuration only',
                        source={}, artifacts={}, commands=[dict(status='PASS', returncode=0, log=name + '.log')
                        for name in ('compile', 'test', 'formal_control', 'formal_datapath')])
            native = dict(status='PASS_FIXED_MODE_CMAC_NATIVE_EXPERIMENT_ONLY', channels=32, kernels=16, parallel_products=512,
                          row_formal_status_at_start=runner.ROW_FORMAL, result=runner.NATIVE_RESULT,
                          library_operations=['combo_update', 'create'], artifacts={},
                          commands=[dict(status='PASS', returncode=0, log=name + '.log') for name in
                                    ('version', 'cxx_version', 'cell_compile', 'top_generate', 'top_compile', 'test')],
                          vectors=dict(frames=208, outputs=3328, seed='0x35883216', source={}, artifacts={}),
                          source={'files': {name: 'MOCK' for name in (runner.CELL, runner.ARRAY, runner.ROWS,
                                  runner.ORIGINAL_CELL, runner.ORIGINAL_ARRAY, 'tools/cmac/test_fixed_array.py', row_path.name)}})
            row_path.write_text(json.dumps(rows)); path.write_text(json.dumps(native))
            runner.verify_fixed_native(path)
            for key, value in (('channels', 16), ('kernels', 8), ('parallel_products', 256),
                               ('row_formal_status_at_start', 'RUNNING'), ('result', 'PASS smaller corpus'),
                               ('library_operations', ['create'])):
                invalid = dict(native, **{key: value}); path.write_text(json.dumps(invalid))
                with self.assertRaises(AssertionError, msg=key):
                    runner.verify_fixed_native(path)
            path.write_text(json.dumps(native))
            for updates in ({'status': 'RUNNING'}, {'formal_result': 'NOT_COMPLETED'},
                            {'commands': rows['commands'][:-1]}, {'simulation_result': 'PASS fewer comparisons'}):
                row_path.write_text(json.dumps(dict(rows, **updates)))
                with self.assertRaises(AssertionError):
                    runner.verify_fixed_native(path)
        step = dict(status='PASS', returncode=0, log='compile.log')
        runner.completed_commands({'commands': [step]}, ['compile'])
        for steps in ([], [dict(step, status='RUNNING')], [dict(step, returncode=1)]):
            with self.assertRaises(AssertionError):
                runner.completed_commands({'commands': steps})
        with self.assertRaisesRegex(AssertionError, 'Missing required'):
            runner.completed_commands({'commands': [step]}, ['formal_datapath'])

    def test_exact_generated_timestamp_warning_only(self):
        with tempfile.TemporaryDirectory(prefix='rk-fixed-warning-controls-') as directory:
            wrapper = Path(directory) / (runner.BLOCK + '.sv')
            wrapper.write_text('\n' * 51 + '    time last_combo_seqnum__V;\n')
            text = f"%Warning-UNUSEDSIGNAL: {wrapper}:52:10: Signal is not used: 'last_combo_seqnum__V'\n"
            runner.check_warnings(text, (), wrapper=wrapper)
            for changed in (text + text, text.replace(':52:', ':53:'), text.replace('last_combo_seqnum__V', 'operand')):
                with self.assertRaises(AssertionError):
                    runner.check_warnings(changed, (), wrapper=wrapper)
            wrapper.write_text('\n' * 51 + '    wire operand;\n')
            with self.assertRaises(AssertionError):
                runner.check_warnings(text, (), wrapper=wrapper)

    def test_reset_and_donor_warnings_are_location_scoped(self):
        reset = ('SYNCASYNCNET', '/MOCK/board.sv', '9')
        text = '%Warning-SYNCASYNCNET: /MOCK/board.sv:9:31: MOCK intentional reset\n'
        runner.check_warnings(text, (), reset_warning=reset)
        for changed in ('', text + text, text.replace('board.sv', 'unreviewed.sv'), text + 'warning: compiler issue\n',
                        text + '%Warning-WIDTH: /MOCK/new.sv:4:8: changed HDL\n', text + 'ERROR : assertion\n'):
            with self.assertRaises(AssertionError):
                runner.check_warnings(changed, (), reset_warning=reset)
        with self.assertRaises(AssertionError):
            runner.check_warnings('%Warning-unparsed diagnostic\n', ())


if __name__ == '__main__':
    unittest.main()
