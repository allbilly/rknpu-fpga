"""Full prefix raw-board compile admission controls, not board simulation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import prepare_dsp_prefix_board as runner
from test_dsp_prefix_array_control import leaf


class PrefixBoardPreparationControls(unittest.TestCase):
    def test_one_exact_join_rebind_keeps_raw_transport_and_downstream_arithmetic(self):
        original=(ROOT/runner.JOIN).read_text();actual=runner.dsp_join(original)
        self.assertEqual(actual.replace('rk_cmac_fp16_array_dsp_prefix #','rk_cmac_fp16_array #'),original)
        self.assertEqual(actual.count('rk_cmac_fp16_array_dsp_prefix #'),1)
        for bad in ('',original+original,original.replace('TAG_WIDTH(TAG_WIDTH+2)','TAG_WIDTH(TAG_WIDTH+1)')):
            with self.subTest(),self.assertRaises(AssertionError):runner.dsp_join(bad)

    def test_only_cell_array_and_join_sources_change_and_helper_is_present_once(self):
        spec=json.loads(runner.SPEC.read_text());join=ROOT/'build/CONTROL_ONLY_PREFIX_JOIN_NOT_EXECUTED.sv'
        sources=runner.simulation_sources(spec,join)
        original=[ROOT/n for n in spec['simulation_helpers']+spec['synthesis']]
        expected=[p for p in original if p not in {ROOT/runner.ORIGINAL_CELL,ROOT/runner.ORIGINAL_ARRAY,ROOT/runner.JOIN}]
        self.assertEqual(set(sources)-set(expected),{runner.ROWS,runner.HELPER,runner.LANE,runner.DSP_CELL,runner.DSP_ARRAY,join})
        self.assertEqual(len(sources),len(original)+3)
        self.assertEqual(sources.count(runner.HELPER),1)
        for mutation in ('duplicate','part','clock','missing','helper_duplicate'):
            changed=deepcopy(spec)
            if mutation=='duplicate':changed['synthesis'].append(changed['synthesis'][0])
            elif mutation=='part':changed['part']='xc7k325tffg900-2'
            elif mutation=='clock':changed['clock_period_ns']=40
            elif mutation=='helper_duplicate':changed['synthesis'].append(str(runner.HELPER.relative_to(ROOT)))
            else:changed['synthesis'].remove(runner.ORIGINAL_ARRAY)
            with self.subTest(mutation=mutation),self.assertRaises(AssertionError):runner.simulation_sources(changed,join)

    def test_all_512_lanes_and_helpers_16_cells_one_array_and_no_fallback_required(self):
        counts={'rk_cmac_fp16_array_dsp_prefix':1,'rk_cmac_fp16_cell_dsp_prefix':16,
            'rk_cmac_fp16_lane_dsp_prefix':512,'rk_cmac_fp16_discarded_carry':512}
        def scopes(values):return ''.join(f'.scope module, "fixture" "{name}"\n'*count for name,count in values.items())
        good=scopes(counts);self.assertEqual(runner.validate_compiled_hierarchy(good),counts)
        for name in counts:
            for delta in (-1,1):
                changed=dict(counts);changed[name]+=delta
                with self.subTest(name=name,delta=delta),self.assertRaises(AssertionError):runner.validate_compiled_hierarchy(scopes(changed))
        for name in ('rk_cmac_fp16_cell','rk_cmac_fp16_cell_fixed','rk_cmac_fp16_array','rk_cmac_fp16_array_fixed',
            'rk_cmac_fp16_cell_dsp','rk_cmac_fp16_lane_dsp','rk_cmac_fp16_array_dsp'):
            with self.subTest(name=name),self.assertRaises(AssertionError):runner.validate_compiled_hierarchy(good+scopes({name:1}))

    def test_incomplete_or_wrong_variant_or_overstated_mapped_leaf_rejected(self):
        good=leaf();runner.validate_leaf_metadata(good)
        for field,value in (('status','RUNNING'),('status','PASS_ISOLATED_ACTUAL_DSP_MAPPED_BINARY_FIXTURES_ONLY'),
            ('stage','mapped'),('isolated_mapped_binary_fixture_acceptance',False),
            ('source_bound_native_binary_lane_equivalence',False),('four_state_leaf_acceptance',True),
            ('expected_comparisons_per_phase',1),('physical_fit_verified',True),('hardware_programmed',True)):
            changed=deepcopy(good);changed[field]=value
            with self.subTest(field=field),self.assertRaises(AssertionError):runner.validate_leaf_metadata(changed)


if __name__=='__main__':unittest.main()
