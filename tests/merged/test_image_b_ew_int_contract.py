"""Contract tests for the Image-B ew-int page wrapper (task-23).

Pins the page ABI, the raw-stream capture/issue contract, the frozen
`rk_job_control` status layout, and (when a fresh receipt exists) the page-level
RTL replay results. Purely offline; no simulator, no Vivado, no hardware.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PAGE_RTL = ROOT / 'rtl/rk_ew_int_page_axi.sv'
JOB_RTL = ROOT / 'rtl/rk_job_control.sv'
TB = ROOT / 'tests/tb_ew_int_page.sv'
RUNNER = ROOT / 'tools/merged/run_ew_int_page_replay.py'
RECEIPTS = ROOT / 'build/ew-int-page'


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PageAbiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rtl = PAGE_RTL.read_text()
        cls.job = JOB_RTL.read_text()

    def test_page_identity_and_abi_constants(self):
        self.assertIn('module rk_ew_int_page_axi', self.rtl)
        self.assertIn("DEVICE_ID = 32'h524b4549", self.rtl)   # "RKEI"
        self.assertIn("ABI_VERSION = 32'h0001_0000", self.rtl)
        self.assertIn("COMMAND_BANK_BASE = 32'h1100_4000", self.rtl)
        self.assertIn("COMMAND_BANK_BYTES = 32'd4096", self.rtl)
        self.assertIn('MAX_COMMAND_QWORDS = 44', self.rtl)
        # The page reuses the frozen transport register block and the already
        # replayed integer decoder/engine unchanged.
        self.assertIn('rk_job_control', self.rtl)
        self.assertIn('rk_ew_int_regs', self.rtl)
        self.assertIn('rk_ew_int_engine', self.rtl)
        # Additive: it must not instantiate the frozen FP16 EW core.
        self.assertNotIn('rk_ew_dma', self.rtl)
        self.assertNotIn('rk_fp16_alu', self.rtl)

    def test_fail_closed_start_amount_is_the_three_captured_shapes(self):
        for amount in (18, 31, 44):
            self.assertIn(f"32'd{amount}", self.rtl)
        # No other captured-shape literal is admitted by the page.
        shapes = set(re.findall(r"core_start_amount == 32'd(\d+)", self.rtl))
        self.assertEqual(shapes, {'18', '31', '44'})

    def test_frozen_pc_tail_framing_is_enforced(self):
        for key in ('32\'h0101_0010', '32\'h0101_0014', '32\'h0041_0000',
                    '32\'h0081_0008'):
            self.assertIn(key, self.rtl)

    def test_raw_stream_capture_is_little_endian_and_unmodified(self):
        # Four halfword reads per QWORD, low halfword first, assembled into the
        # 64-bit word and fed unchanged to the decoder.
        self.assertIn('fetch_half_q', self.rtl)
        self.assertIn("fetch_half_q == 2'd3", self.rtl)
        self.assertIn('{mem_rsp_rdata, fetch_acc_q}', self.rtl)
        self.assertIn('fetch_acc_q <= {mem_rsp_rdata, fetch_acc_q[47:16]}', self.rtl)
        self.assertIn('cmd_data <= capture[stream_idx_q[5:0]]', self.rtl)
        # The page only ever reads on the capture path; writes exist only while
        # the integer engine owns the bus.
        self.assertIn('assign mem_req_write = run_phase && engine_req_write;',
                      self.rtl)

    def test_engine_and_decoder_are_reset_per_job(self):
        self.assertRegex(
            self.rtl,
            r'wire eng_rst_n = rst_n && \(\(st_q == CHECK\) \|\| '
            r'\(st_q == STREAM\) \|\|')

    def test_decoder_error_is_not_mistaken_for_a_started_engine(self):
        # The last command QWORD can itself be rejected (unsupported op/dtype),
        # so the page waits for decoder-error OR engine-start before running.
        self.assertIn('ISSUE', self.rtl)
        self.assertIn('if (reg_error)', self.rtl)
        self.assertIn('else if (engine_busy || cfg_valid)', self.rtl)

    def test_result_codes_are_documented(self):
        text = self.rtl.replace('\n', ' ')
        for phrase in ('1 unknown register/target', '2 unsupported value/op/dtype',
                       '3 incomplete/framing', '4 invalid address',
                       '5 memory bus error', '6 invalid page command',
                       '7 unsupported PC chain', '8 timeout',
                       'sticky until fabric reset'):
            self.assertIn(phrase, text)
        # Page-originated codes are literals; decoder/engine codes propagate.
        for code in (3, 5, 6, 8):
            self.assertIn(f"8'd{code}", self.rtl)


class FrozenJobControlStatusTest(unittest.TestCase):
    def test_status_word_layout_matches_the_page_replay(self):
        """The page and its bench must use the actual frozen bit positions.

        rk_job_control.sv (frozen) defines:
          status_word = {21'b0, fields_valid, 1'b0, core_busy, core_error,
                         memory_ready, result_error, result_valid, active,
                         can_submit};
        i.e. LSB-anchored: can_submit[0], active[1], result_valid[2],
        result_error[3], memory_ready[4], core_error[5], core_busy[6],
        fields_valid[10:8].
        """
        job = JOB_RTL.read_text()
        self.assertIn(
            'status_word = {21\'b0, fields_valid, 1\'b0, core_busy, core_error,',
            job)
        self.assertIn('memory_ready, result_error, result_valid, active, can_submit};',
                      job)
        tb = TB.read_text()
        # The bench polls the frozen layout, not a documentation sketch.
        self.assertIn('status[0]', tb)   # can_submit
        self.assertIn('status[2]', tb)   # result_valid
        self.assertIn('status[3]', tb)   # result_error
        runner = RUNNER.read_text()
        self.assertIn('frozen rk_job_control', runner)


class PageBenchWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tb = TB.read_text()
        cls.runner = RUNNER.read_text()

    def test_bench_instantiates_the_real_page_and_aperture(self):
        self.assertIn('rk_ew_int_page_axi page', self.tb)
        self.assertIn('rk_ew_int_aperture aperture', self.tb)
        self.assertIn('.memory_ready(ap_memory_ready)', self.tb)
        self.assertIn('.page_busy(page_busy)', self.tb)
        self.assertIn('.engine_req_valid(page_mem_req_valid)', self.tb)

    def test_bench_stages_through_axi_only(self):
        # Operand and command banks are written through the aperture AXI port;
        # there is no back-door memory write task.
        self.assertIn('stage_words(A_BANK', self.tb)
        self.assertIn('stage_words(B_BANK', self.tb)
        self.assertIn('stage_words(C_BANK', self.tb)
        self.assertNotIn('memory[', self.tb)

    def test_bench_checks_readback_and_command_preservation(self):
        self.assertIn('input_a_bytes_exact', self.runner)
        self.assertIn('command_bo_untouched', self.runner)
        self.assertIn('reset-per-job', self.runner)

    def test_runner_covers_fifteen_cases_eight_negatives_and_reset_per_job(self):
        self.assertIn('len(ready) != 15', self.runner)
        for control in ('nc_unsupported_op_div', 'nc_fp16_dtype',
                        'nc_hole_operand', 'nc_unknown_register',
                        'nc_wrong_amount', 'nc_unaligned_start',
                        'nc_missing_tag', 'nc_bad_strobe'):
            self.assertIn(control, self.runner)
        self.assertIn('b2b', self.runner.replace('back_to_back', 'b2b'))

    def test_runner_uses_the_pinned_aperture_map(self):
        for constant in ('A_BANK = 0x1100_1000', 'B_BANK = 0x1100_2000',
                         'D_BANK = 0x1100_3000', 'C_BANK = 0x1100_4000'):
            self.assertIn(constant, self.runner)
        self.assertIn('aperture audit is not PASS', self.runner)


class PageReplayReceiptTest(unittest.TestCase):
    def test_latest_receipt_is_fresh_and_green(self):
        receipts = sorted(RECEIPTS.glob('*/report.json'),
                          key=lambda path: path.stat().st_mtime)
        if not receipts:
            self.skipTest('no page replay receipt yet; run '
                          'tools/merged/run_ew_int_page_replay.py')
        report = json.loads(receipts[-1].read_text())
        for name, digest in report['source_hashes'].items():
            if (ROOT / name).is_file() and sha(ROOT / name) != digest:
                self.skipTest(f'stale page replay receipt ({name} changed); '
                              'regenerate with tools/merged/run_ew_int_page_replay.py')
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['aperture_audit']['verdict'], 'PASS')
        self.assertEqual(len(report['cases']), 15)
        self.assertEqual(set(report['simulators']), {'verilator', 'iverilog'})
        for simulator, record in report['simulators'].items():
            self.assertEqual(record['status'], 'PASS', simulator)
            self.assertEqual(len(record['cases']), 15)
            for case, entry in record['cases'].items():
                self.assertEqual(entry['status'], 'PASS', f'{simulator}/{case}')
                self.assertTrue(entry['input_a_bytes_exact'], f'{simulator}/{case}')
                self.assertTrue(entry['input_b_bytes_exact'], f'{simulator}/{case}')
                self.assertTrue(entry['command_bo_untouched'], f'{simulator}/{case}')
            self.assertEqual(record['back_to_back']['status'], 'PASS', simulator)
            self.assertEqual(record['back_to_back']['first_mismatch_count'], 0)
            self.assertEqual(record['back_to_back']['second_mismatch_count'], 0)
            self.assertEqual(len(record['negative_controls']), 8)
            for control, entry in record['negative_controls'].items():
                self.assertEqual(entry['status'], 'PASS', f'{simulator}/{control}')
        blocked = {entry['case'] for entry in report['blocked_cases']}
        self.assertEqual(blocked, {'int32_div_c8_w2',
                                   'fp16_four_input_sum_c8_w1',
                                   'fp16_bs_bn_relu_prelu_c8_w1'})


if __name__ == '__main__':
    unittest.main()
