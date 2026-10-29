"""Complete-stage/parent controls; not full mapped-board numerical proof."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/cmac'))
import map_observed_board as runner


class ObservedBoardMappingControls(unittest.TestCase):
    def test_exact_existing_mapping_stages_and_only_output_paths_changed(self):
        old, new = Path('/tmp/original-rk-mapping'), Path('/tmp/new-rk-mapping')
        suffix = runner.STAGES + ['write_json ' + json.dumps(str(old / 'mapped_hierarchy.json')) + ';',
            'write_verilog -noattr ' + json.dumps(str(old / 'mapped.v'))]
        original = 'read_verilog original.sv;\n' + '\n'.join(suffix) + '\n'
        result = runner.mapping_script(original, Path('/tmp/premap.json'), old, new)
        self.assertTrue(result.startswith('read_verilog -lib +/xilinx/cells_sim.v;\nread_json "/tmp/premap.json";'))
        self.assertNotIn('read_verilog original.sv', result)
        self.assertIn('\n'.join(runner.STAGES), result)
        self.assertIn('write_json "/tmp/new-rk-mapping/mapped_hierarchy.json";', result)
        for forbidden in ('setundef', '-undriven', '-noassert', 'blackbox ', 'delete ', 'share;'):
            self.assertNotIn(forbidden, result)
        for changed in (original.replace('alumacc;', 'share;'), original.replace('check -assert;', 'check;'),
                        original.replace('-family xc7', '-family xcu'), original + 'write_json "extra.json";\n'):
            with self.subTest(script=changed), self.assertRaises(AssertionError):
                runner.mapping_script(changed, Path('/tmp/premap.json'), old, new)

    def test_rejects_incomplete_mismatched_or_claim_promoting_preparation(self):
        report = dict(status='PREPARED_ORIGINAL_RAW_BOARD_OBSERVABILITY_ONLY', stage='complete',
            channels=32, kernels=16, parallel_products=512, bindings={str(i): {} for i in range(22)},
            imported_kernel_circuit_identity='PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE',
            commands=[dict(status='PASS', returncode=0) for _ in range(2)],
            numerical_netlist_acceptance=False, physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False)
        runner.verify_prepared_report(report)
        for key, value in [('status','RUNNING'), ('stage','prepare'), ('channels',8), ('kernels',8),
                           ('parallel_products',64), ('bindings',{}), ('imported_kernel_circuit_identity','COUNTS_ONLY'),
                           ('numerical_netlist_acceptance',True), ('physical_fit_verified',True),
                           ('bitstream_emitted',True), ('hardware_programmed',True)]:
            changed = deepcopy(report); changed[key] = value
            with self.subTest(field=key), self.assertRaises(AssertionError): runner.verify_prepared_report(changed)
        changed = deepcopy(report); changed['commands'][0]['returncode'] = 1
        with self.assertRaises(AssertionError): runner.verify_prepared_report(changed)


if __name__ == '__main__': unittest.main()
