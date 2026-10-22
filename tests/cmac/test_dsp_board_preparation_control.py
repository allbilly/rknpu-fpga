"""Literal substitution/admission controls, not compiled board execution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import prepare_dsp_board as runner


class DspBoardPreparationControls(unittest.TestCase):
    def test_exact_one_array_join_substitution_and_no_other_change(self):
        original=(ROOT/runner.JOIN).read_text();actual=runner.dsp_join(original)
        self.assertEqual(actual.replace('rk_cmac_fp16_array_dsp #','rk_cmac_fp16_array #'),original)
        self.assertEqual(actual.count('rk_cmac_fp16_array_dsp #'),1)
        for bad in (original+original,original.replace('TAG_WIDTH(TAG_WIDTH+2)','TAG_WIDTH(TAG_WIDTH+1)')):
            with self.subTest(),self.assertRaises(AssertionError):runner.dsp_join(bad)

    def test_only_sources_changed_are_cell_array_and_join(self):
        spec=json.loads(runner.SPEC.read_text());join=ROOT/'build/CONTROL_ONLY_DSP_JOIN_NOT_EXECUTED.sv'
        sources=runner.simulation_sources(spec,join)
        original=[ROOT/n for n in spec['simulation_helpers']+spec['synthesis']]
        expected=[p for p in original if p not in {ROOT/runner.ORIGINAL_CELL,ROOT/runner.ORIGINAL_ARRAY,ROOT/runner.JOIN}]
        self.assertEqual(set(sources)-set(expected),{runner.ROWS,runner.LANE,runner.DSP_CELL,runner.DSP_ARRAY,join})
        self.assertEqual(len(sources),len(original)+2)
        for mutation in ('duplicate','part','clock','missing'):
            changed=deepcopy(spec)
            if mutation=='duplicate':changed['synthesis'].append(changed['synthesis'][0])
            elif mutation=='part':changed['part']='xc7k325tffg900-2'
            elif mutation=='clock':changed['clock_period_ns']=40
            else:changed['synthesis'].remove(runner.ORIGINAL_ARRAY)
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):runner.simulation_sources(changed,join)

    def test_full_compiled_hierarchy_and_no_baseline_or_fixed_fallback(self):
        cell='.scope module, "cell" "rk_cmac_fp16_cell_dsp"\n'
        lane='.scope module, "donor" "rk_cmac_fp16_lane_dsp"\n'
        text=cell*16+lane*512
        self.assertEqual(runner.validate_compiled_hierarchy(text),{'rk_cmac_fp16_cell_dsp':16,'rk_cmac_fp16_lane_dsp':512})
        for bad in (cell*15+lane*512,cell*16+lane*511,text+'.scope module, "fallback" "rk_cmac_fp16_cell"\n',
                text+'.scope module, "fallback" "rk_cmac_fp16_array_fixed"\n'):
            with self.subTest(),self.assertRaises(AssertionError):runner.validate_compiled_hierarchy(bad)


if __name__=='__main__':unittest.main()
