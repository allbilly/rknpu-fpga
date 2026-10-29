"""Twenty-three old guards plus reversible bench order/native compile controls."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'tools/openxc7'),str(Path(__file__).resolve().parent)]
from test_prefix_bram_address_control import PrefixBramAddressControl
from test_sparse_prefix_bram_address_control import SparseCarryOutputControl
from test_coherent_prefix_bram_address_control import CoherentAddressControl
from test_full_budget_prefix_bram_address_control import FullBudgetAddressControl
from test_resumed_prefix_bram_address_control import ResumedAddressControl
from test_binary_library_prefix_bram_address_control import BinaryLibraryAddressControl
import resume_declared_binary_prefix_bram_address as new


class DeclaredBinaryAddressControl(unittest.TestCase):
    def test_only_initial_block_order_changes_with_exact_inverse(self):
        nodes={'actual':PrefixBramAddressControl().cell()}
        old,width=new.previous.qualify_bench(nodes);fixed,fixed_width=new.qualify_bench(nodes)
        self.assertEqual(width,fixed_width)
        self.assertLess(fixed.index(' observed = '),fixed.index('initial begin'))
        self.assertGreater(old.index(' observed = '),old.index('initial begin'))
        a,b=old.splitlines(),fixed.splitlines()
        self.assertCountEqual(a,b)
        self.assertEqual(new.MAIN_SOURCE.replace('prefix-bram-address-declared-binary-resume-',
            'prefix-bram-address-binary-library-resume-'),__import__('inspect').getsource(new.previous.main))
        self.assertIs(new.NAMESPACE['base'].validate_result,new.previous.base.validate_result)

    def test_actual_Icarus_compiles_same_small_bench_against_each_unchanged_library(self):
        nodes={'actual':PrefixBramAddressControl().cell()}
        text,_=new.qualify_bench(nodes)
        vendor=[path for path in new.previous.models.selected_models({'LUT2'}) if path.suffix=='.v']
        glbl=next(path for path in vendor if path.name=='glbl.v')
        with tempfile.TemporaryDirectory(prefix='rknpu-binary-declaration-control-') as directory:
            bench=Path(directory)/'control.sv';bench.write_text(text)
            for kind,files in (('vendor',vendor),('synthesis',[new.previous.LIBRARY,glbl])):
                result=subprocess.run(['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl',
                    '-o',str(Path(directory)/(kind+'.vvp')),*map(str,files),str(bench)],
                    capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(result.stdout+result.stderr,'')


if __name__=='__main__':unittest.main()
