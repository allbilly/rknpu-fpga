"""Twenty-five unchanged guards plus exact native finish result controls."""
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
from test_declared_binary_prefix_bram_address_control import DeclaredBinaryAddressControl
import resume_binary_result_prefix_bram_address as new


class BinaryResultAddressControl(unittest.TestCase):
    def test_exact_footer_preserves_strict_vector_and_real_wrong_golden_checks(self):
        body=BinaryLibraryAddressControl().corpus();footer='/exact/source.sv:1128: $finish called at 1125000 (1ps)'
        good=body+footer+'\n'
        self.assertEqual(new.corpus(good,footer),body)
        new.compare_vectors(good,good,8,footer)
        for bad in (body,good+'extra\n',good.replace('1125000','1125001'),good.replace('1ps','1ns'),
                    good.replace('/exact/source','/wrong/source'),good.replace('1128','1127')):
            with self.assertRaises(AssertionError):new.vectors(bad,8,footer)
        for bad in (good.replace('0000 00','0000 0x'),good.replace('0001 00','0000 00'),good.replace('0000 00','warning: bad')):
            with self.assertRaises(AssertionError):new.vectors(bad,8,footer)
        with self.assertRaisesRegex(AssertionError,'Binary model mismatch vector=0'):
            new.compare_vectors(good,good.replace('0000 00','0000 01'),8,footer)

    def test_unchanged_native_small_bench_actually_completes_at_bound_footer(self):
        text,width=new.previous.qualify_bench({'actual':PrefixBramAddressControl().cell()})
        glbl=new.raw.models.CACHE/'verilog/src/glbl.v'
        with tempfile.TemporaryDirectory(prefix='rknpu-native-finish-control-') as directory:
            bench=Path(directory)/'control.sv';bench.write_text(text)
            binary=Path(directory)/'control.vvp'
            compile=subprocess.run(['iverilog','-g2012','-Ttyp','-s','binary_library_control','-s','glbl',
                '-o',str(binary),str(new.raw.LIBRARY),str(glbl),str(bench)],capture_output=True,text=True,timeout=30)
            self.assertEqual(compile.returncode,0,compile.stdout+compile.stderr)
            self.assertEqual(compile.stdout+compile.stderr,'')
            result=subprocess.run(['vvp',str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0);self.assertEqual(result.stderr,'')
            footer=new.expected_finish(bench,text)
            self.assertEqual(result.stdout.splitlines()[-1],footer)
            # Unsized XOR prints 32 bits for a one-output compile fixture.
            self.assertEqual(len(new.raw.vectors(new.corpus(result.stdout,footer),32)),1024)


if __name__=='__main__':unittest.main()
