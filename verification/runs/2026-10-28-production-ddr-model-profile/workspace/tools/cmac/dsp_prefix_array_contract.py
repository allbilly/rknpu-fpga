"""Exact isolated full C32/K16 prefix derivation, not numerical acceptance."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT
import dsp_array_contract as original
import test_dsp_prefix_carry as leaf

CELL = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp_prefix.sv'
ARRAY = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_array_dsp_prefix.sv'
PREFIX = '// EXPERIMENTAL prefix-carry variant; no array numerical or FPGA acceptance.\n'


def expected_cell(text):
    text = original.replace_once(text, 'module rk_cmac_fp16_cell_dsp #',
        'module rk_cmac_fp16_cell_dsp_prefix #')
    text = original.replace_once(text, '        rk_cmac_fp16_lane_dsp donor(',
        '        rk_cmac_fp16_lane_dsp_prefix donor(')
    return PREFIX + text


def expected_array(text):
    text = original.replace_once(text, 'module rk_cmac_fp16_array_dsp #',
        'module rk_cmac_fp16_array_dsp_prefix #')
    text = original.replace_once(text, '        rk_cmac_fp16_cell_dsp #',
        '        rk_cmac_fp16_cell_dsp_prefix #')
    return PREFIX + text


def array_bench(text):
    dsp = original.array_bench(text)
    return original.replace_once(dsp,
        'rk_cmac_fp16_array_dsp #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);',
        'rk_cmac_fp16_array_dsp_prefix #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);')


def validate_sources():
    original.validate_sources(); leaf.validate_sources()
    assert CELL.read_text() == expected_cell(original.DSP_CELL.read_text()), 'Extra prefix cell arithmetic/priority change'
    assert ARRAY.read_text() == expected_array(original.DSP_ARRAY.read_text()), 'Changed prefix array geometry/hold/reset/fault contract'
