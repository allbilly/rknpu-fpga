"""Source/log contract controls only; not synthesis, numerical or FPGA results."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/cmac')]
import admit_dsp_prefix_board_diagnostics as admission


class BoardDiagnosticAdmissionControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_path = ROOT / admission.ram.PARENT
        cls.original = json.loads(cls.original_path.read_text())
        cls.memory = json.loads((ROOT / admission.RAM_REPORT).read_text())
        cls.cone = json.loads((ROOT / admission.CONE_REPORT).read_text())
        cls.fanout = json.loads((ROOT / cls.cone['capture_report']).read_text())
        cls.text = (cls.original_path.parent / 'mapping.log').read_text()
        cls.drivers = admission.cones.capture.driver_notices(cls.text)
        cls.resizes = admission.ram.resize_notices(cls.text, 'ypcb_cmac_array_top')

    def check_log(self, text):
        return admission.audit_log(text, 'ypcb_cmac_array_top', self.original['preserved_kernel'], self.drivers, self.resizes)

    def test_exact_original_log_contract(self):
        self.assertEqual(self.check_log(self.text)['original_check_counts'], [288, 0, 0, 0])

    def test_missing_or_repeated_proved_warning_fails(self):
        line = next(iter(self.drivers))
        for bad in (self.text.replace(line + '\n', '', 1), self.text + line + '\n'):
            with self.assertRaises(AssertionError):
                self.check_log(bad)

    def test_extra_unknown_warning_fails(self):
        with self.assertRaises(AssertionError):
            self.check_log(self.text + '\nWarning: unmodeled live input\n')

    def test_changed_ram_width_or_location_fails(self):
        cell, pin = next(iter(self.resizes))
        old, new = self.resizes[cell, pin]
        line = f'Warning: Resizing cell port ypcb_cmac_array_top.{cell}.{pin} from {old} bits to {new} bits.'
        for bad in (line.replace(f'to {new} bits', f'to {new + 1} bits'), line.replace(cell, 'wrong_cell')):
            with self.assertRaises(AssertionError):
                self.check_log(self.text.replace(line, bad))

    def test_late_check_problem_or_missing_check_fails(self):
        for bad in (self.text.replace('Found and reported 0 problems.', 'Found and reported 1 problems.', 1),
                    self.text.replace('Found and reported 0 problems.', '', 1)):
            with self.assertRaises(AssertionError):
                self.check_log(bad)

    def test_original_abc_and_source_notices_still_required(self):
        for bad in (self.text.replace(admission.mapper.array.ABC_NOTICE, 'Warning: unrelated ABC behavior'),
                    self.text.replace('Extracted 0 gates and 0 wires', 'Extracted 1 gates and 1 wires', 1)):
            with self.assertRaises(AssertionError):
                self.check_log(bad)

    def test_current_completed_reports_and_profile_required(self):
        admission.validate_reports(self.original, self.memory, self.cone, self.fanout, self.original_path)
        for index, field, value in ((1, 'status', 'RUNNING'), (1, 'actual_ram_port_resizes', 53),
                                    (2, 'verified_warning_bits', 287), (3, 'parallel_products', 32),
                                    (3, 'tool_version', 'different'), (2, 'physical_fit_verified', True)):
            reports = deepcopy([self.original, self.memory, self.cone, self.fanout])
            reports[index][field] = value
            with self.assertRaises(AssertionError):
                admission.validate_reports(*reports, self.original_path)

    def test_cross_parent_report_rejected(self):
        memory = deepcopy(self.memory)
        memory['original_report'] = 'build/wrong/report.json'
        with self.assertRaises(AssertionError):
            admission.validate_reports(self.original, memory, self.cone, self.fanout, self.original_path)


if __name__ == '__main__':
    unittest.main()
