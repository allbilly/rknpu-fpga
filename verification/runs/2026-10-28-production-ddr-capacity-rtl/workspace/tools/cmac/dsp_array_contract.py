"""Exact offline candidate derivation; never an arithmetic/layout fallback."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT

FIXED_CELL = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_cell_fixed.sv'
FIXED_ARRAY = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_array_fixed.sv'
DSP_CELL = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_cell_dsp.sv'
DSP_ARRAY = ROOT / 'rtl/cmac/experimental/rk_cmac_fp16_array_dsp.sv'
BENCH = ROOT / 'tests/cmac/tb_cmac_fp16_array.sv'
PREFIX = '// EXPERIMENTAL: compensated DSP lanes; no promotion or FPGA acceptance.\n'


def replace_once(text, before, after):
    assert text.count(before) == 1, 'Changed original contract fragment: ' + before
    return text.replace(before, after)


def expected_cell(original):
    changes = [('module rk_cmac_fp16_cell_fixed #', 'module rk_cmac_fp16_cell_dsp #'),
        ('    wire [31:0] row_a[ATOMIC_C],row_b[ATOMIC_C];', '    wire [31:0] lane_total[ATOMIC_C];'),
        ('    logic [31:0] compensation,lane_sum;', '    logic [31:0] lane_sum;'),
        ('        rk_cmac_fp16_rows donor(', '        rk_cmac_fp16_lane_dsp donor('),
        ('            .res_a(row_a[i]),.res_b(row_b[i]),.res_tag(row_tag[i]));',
         '            .lane_sum(lane_total[i]),.res_tag(row_tag[i]));'),
        ('        sum=0;invalid=0;compensation=0;lane_sum=0;nan_found=0;nan_payload=0;',
         '        sum=0;invalid=0;lane_sum=0;nan_found=0;nan_payload=0;'),
        ('''            case(row_tag[i])
                8'hf0:compensation=32'haaab0000;
                8'h78:compensation=32'hfaaab000;
                8'h3c:compensation=32'hffaaab00;
                8'h1e:compensation=32'hfffaaab0;
                8'h0f:compensation=32'hffffaaab;
                8'h07:compensation=32'hfffffaab;
                8'h03:compensation=32'hffffffab;
                8'h01:compensation=32'hfffffffb;
                8'h00:compensation=0;
                default:begin compensation=0;invalid=1;end
            endcase''', '''            case(row_tag[i])
                8'hf0,8'h78,8'h3c,8'h1e,8'h0f,8'h07,8'h03,8'h01,8'h00:begin end
                default:invalid=1;
            endcase'''),
        ('            lane_sum=row_a[i]+row_b[i]+compensation;', '            lane_sum=lane_total[i];')]
    result = original
    for before, after in changes: result = replace_once(result, before, after)
    return PREFIX + result


def expected_array(original):
    result = replace_once(original, 'module rk_cmac_fp16_array_fixed #', 'module rk_cmac_fp16_array_dsp #')
    result = replace_once(result, 'rk_cmac_fp16_cell_fixed #', 'rk_cmac_fp16_cell_dsp #')
    return PREFIX + result


def array_bench(original):
    return replace_once(original, 'rk_cmac_fp16_array #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);',
        'rk_cmac_fp16_array_dsp #(.ATOMIC_C(ATOMIC_C),.ATOMIC_K(ATOMIC_K)) dut(.*);')


def validate_sources():
    assert DSP_CELL.read_text() == expected_cell(FIXED_CELL.read_text()), 'Extra cell arithmetic, priority or boundary change'
    assert DSP_ARRAY.read_text() == expected_array(FIXED_ARRAY.read_text()), 'Changed array warmup, hold/reset, fault or tag contract'
