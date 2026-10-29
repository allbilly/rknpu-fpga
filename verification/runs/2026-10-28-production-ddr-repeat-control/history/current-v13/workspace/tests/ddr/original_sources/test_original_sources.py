"""Offline controls for the original MIG generated-source selector."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.ddr import original_sources as selector


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ModuleSelectionTests(unittest.TestCase):
    def fixture(self,directory):
        raw=directory/'raw.v';derived=directory/'derived.v';other=directory/'other.v'
        raw.write_text('module mig_7series_v4_2_round_robin_arb; endmodule\n')
        derived.write_text('module mig_7series_v4_2_round_robin_arb; endmodule\n')
        other.write_text('module mig_7series_v4_2_mc; endmodule\n')
        return raw,derived,other

    def test_exactly_one_corrected_arbiter_is_selected_and_raw_copy_is_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            raw,derived,other=self.fixture(Path(name))
            with patch.object(selector,'RAW_ARBITER_SHA',digest(raw)),patch.object(
                    selector,'DERIVED_ARBITER_SHA',digest(derived)):
                selected,counts=selector.select([raw,other],raw,derived)
            self.assertEqual(selected,[other,derived])
            self.assertNotIn(raw,selected)
            self.assertEqual(counts['mig_7series_v4_2_round_robin_arb'],1)
            self.assertEqual(counts['mig_7series_v4_2_mc'],1)

    def test_wrong_hash_missing_raw_and_duplicate_definition_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            raw,derived,other=self.fixture(Path(name))
            with patch.object(selector,'RAW_ARBITER_SHA','0'*64),patch.object(
                    selector,'DERIVED_ARBITER_SHA',digest(derived)):
                with self.assertRaisesRegex(ValueError,'Changed arbiter source identity'):
                    selector.select([raw,other],raw,derived)
            with patch.object(selector,'RAW_ARBITER_SHA',digest(raw)),patch.object(
                    selector,'DERIVED_ARBITER_SHA',digest(derived)):
                with self.assertRaisesRegex(ValueError,'Missing/duplicate raw RTL selection'):
                    selector.select([other],raw,derived)
                duplicate=Path(name)/'duplicate.v'
                duplicate.write_text('module mig_7series_v4_2_round_robin_arb; endmodule\n')
                with self.assertRaisesRegex(ValueError,'Original and corrected arbiter cannot both be selected'):
                    selector.select([raw,other,duplicate],raw,derived)

    def test_legacy_codepage_comments_are_ignored_without_decoding_source(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'legacy.v'
            path.write_bytes(b'/* \x80 module commented_block; endmodule */\n// \x96 module commented_line; endmodule\nmodule actual_source; endmodule\n')
            self.assertEqual(selector.module_names(path),['actual_source'])


class SynthesisFilesetTests(unittest.TestCase):
    COMMON='xilinx_anylanguagesynthesis_view_fileset'
    WRAPPER='xilinx_verilogsynthesiswrapper_view_fileset'

    def write_component(self,path,common_count=100,wrapper_count=1,*,missing_wrapper=False,
                        duplicate_common=False,escape=False,simulation=False,asset=False):
        common=['common_%03d.v'%i for i in range(common_count)]
        wrapper=['wrapper_%03d.v'%i for i in range(wrapper_count)]
        if asset:common.append('metadata.txt')
        if escape and common:common[0]='../escape.v'
        if simulation and wrapper:wrapper[-1]='top_mig_7series_0_0_mig_sim.v'
        def group(name,files):
            return '<fileSet><name>'+name+'</name>'+''.join('<file><name>'+f+'</name></file>' for f in files)+'</fileSet>'
        text='<component>'+group(self.COMMON,common)
        if duplicate_common:text+=group(self.COMMON,['duplicate.v'])
        if not missing_wrapper:text+=group(self.WRAPPER,wrapper)
        text+='</component>'
        path.write_text(text)

    def test_actual_two_synthesis_filesets_select_101_hdl_and_separate_assets(self):
        with tempfile.TemporaryDirectory() as name:
            component=Path(name)/'top_mig_7series_0_0.xml'
            self.write_component(component,asset=True)
            selected,assets,groups=selector.synthesis_files(component)
            self.assertEqual(len(selected),101)
            self.assertEqual(len(set(selected)),101)
            self.assertEqual(groups,(self.COMMON,self.WRAPPER))
            self.assertEqual([p.name for p in assets],['metadata.txt'])
            self.assertFalse(any(p.name.endswith('_mig_sim.v') for p in selected))

    def test_missing_duplicate_escaping_count_and_sim_wrapper_are_rejected(self):
        cases=(
            ('missing',dict(missing_wrapper=True),'Missing actual MIG synthesis view'),
            ('duplicate',dict(duplicate_common=True),'Duplicate component file set'),
            ('escaping',dict(escape=True),'Escaping synthesis source'),
            ('wrong_count',dict(common_count=99),'Changed original synthesis HDL inventory'),
            ('simulation',dict(simulation=True),'Simulation wrapper cannot enter synthesis'),
        )
        for label,kwargs,message in cases:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as name:
                component=Path(name)/'top_mig_7series_0_0.xml'
                self.write_component(component,**kwargs)
                with self.assertRaisesRegex(ValueError,message):
                    selector.synthesis_files(component)


if __name__=='__main__':unittest.main()
