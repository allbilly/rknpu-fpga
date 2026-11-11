#!/usr/bin/env python3
"""Static contract checks for the strict 54-QWORD 3x3 C4 DMA wrapper."""
from pathlib import Path
import sys
import unittest

from tools.conv import run_3x3_valid_c4 as raw

ROOT = Path(__file__).resolve().parents[2]


class Conv3x3C4DmaContractTests(unittest.TestCase):
    def test_fetch_geometry_and_descriptor_fields_are_bounded(self) -> None:
        rtl = (ROOT / 'rtl/cmac/rk_conv_3x3_c4_dma.sv').read_text()
        self.assertIn("parameter int unsigned PROFILE = 0", rtl)
        self.assertIn("PROFILE_VALID = 0", rtl)
        self.assertIn("PROFILE_STRIDE2 = 1", rtl)
        self.assertIn("PROFILE_PAD1_ZERO_FRAME = 2", rtl)
        self.assertIn("command_amount != 32'd54", rtl)
        self.assertIn("command_amount <= start_amount", rtl)
        self.assertIn("command_base[2:0] != 3'b000", rtl)
        self.assertIn("command_base} + 33'd432", rtl)
        self.assertIn("command_base + {23'd0, word_index, 3'b000}", rtl)
        self.assertIn("word_index == 6'd53", rtl)
        self.assertIn("cmd_data(command_word)", rtl)
        self.assertIn("cmd_last(word_index == 6'd53)", rtl)
        self.assertIn("21: input_base <= command_word[47:16]", rtl)
        self.assertIn("27: weight_base <= command_word[47:16]", rtl)
        self.assertIn("35: output_base <= command_word[47:16]", rtl)
        self.assertIn("tail_is_exact && !ranges_disjoint", rtl)

    def test_wrapper_rearms_with_owned_core_reset(self) -> None:
        rtl = (ROOT / 'rtl/cmac/rk_conv_3x3_c4_dma.sv').read_text()
        bench = (ROOT / 'tests/conv/tb_conv_3x3_c4_dma.sv').read_text()
        self.assertIn("IDLE, CHECK, FETCH_REQ, FETCH_WAIT, SEND, RUN, REARM, FAILED", rtl)
        self.assertIn(".STRIDE2(PROFILE == PROFILE_STRIDE2)", rtl)
        self.assertIn(".PAD1_ZERO_FRAME(PROFILE == PROFILE_PAD1_ZERO_FRAME)", rtl)
        self.assertIn("RUN: if (core_done) begin", rtl)
        self.assertIn("state <= REARM", rtl)
        self.assertIn("assign core_rst_n = rst_n && state != REARM", rtl)
        self.assertIn("rearm_done", rtl)
        self.assertIn("second DMA convolution failed", bench)
        self.assertIn("second output BO tail modified", bench)

    def test_replay_checks_all_three_exact_profiles_and_failures(self) -> None:
        runner_source = (ROOT / 'tools/conv/run_3x3_c4_dma.py').read_text()
        bench = (ROOT / 'tests/conv/tb_conv_3x3_c4_dma.sv').read_text()
        sys.path.insert(0, str(ROOT))
        from tools.conv import run_3x3_c4_dma as dma
        cases = dma.profile_ids()
        # The DMA wrapper deliberately supports only these three exact
        # profiles; grouped-C2 raw replays use the raw core without DMA.
        self.assertEqual(set(cases), {
            'conv_3x3_valid_c4_h9_w9_oc4',
            'conv_3x3_stride2_c4_h11_w11_oc4',
            'conv_3x3_pad1_zero_frame_c4_h9_w9_oc4',
        })
        for case in cases:
            _manifest, _job, command, _patched, _fixture = raw.load_contract(case)
            self.assertEqual(len(command), 54 * 8)
        self.assertNotIn('conv_grouped_3x3_c4_h5_w5_oc8_g2_task0', cases)
        self.assertIn("for mode in range(7)", runner_source)
        self.assertIn("mode != 5", bench)
        self.assertIn("if (mode == 6)", bench)
        self.assertIn("TOTAL_READS = 216 + 576 + INPUT_READS", bench)
        self.assertIn("device output mismatch", bench)
        self.assertIn("output BO tail modified", bench)


if __name__ == '__main__':
    unittest.main()
