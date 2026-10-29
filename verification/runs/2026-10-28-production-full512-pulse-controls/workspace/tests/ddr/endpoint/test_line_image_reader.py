"""Actual Icarus/Verilator controls for the shared complete-BO image reader."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
DATA0='0123456789abcdef'*8
DATA1='fedcba9876543210'*8
ROWS=[f'10000000 {DATA0}',f'10000040 {DATA1}']


class StrictLineImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='ddr-line-reader-')
        cls.directory=Path(cls.temp.name);cls.programs={}
        header=ROOT/'tests/ddr/endpoint/strict_line_image.svh'
        bench=ROOT/'tests/ddr/endpoint/tb_strict_line_image.sv'
        define='-DRK_DDR_LINE_IMAGE_HEADER='+json.dumps(str(header))
        for simulator in ('iverilog','verilator'):
            tool=shutil.which(simulator)
            if tool is None:continue
            if simulator=='iverilog':
                runtime=shutil.which('vvp')
                if runtime is None:continue
                image=cls.directory/'reader.vvp'
                argv=[tool,'-g2012','-Wall','-s','tb_strict_line_image',define,'-o',str(image),str(bench)]
                run=[runtime,str(image)]
            else:
                image=cls.directory/'obj/reader'
                argv=[tool,'--binary','--timing','--assert','-Wall','--top-module','tb_strict_line_image',
                      '-j','2','--Mdir',str(cls.directory/'obj'),'-o','reader',define,str(bench)]
                run=[str(image)]
            result=subprocess.run(argv,cwd=ROOT,text=True,capture_output=True,timeout=180)
            if result.returncode:raise AssertionError(simulator+' reader compile failed:\n'+result.stdout+result.stderr)
            cls.programs[simulator]=run
        if not cls.programs:raise unittest.SkipTest('Neither Icarus nor Verilator is available')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_image(self,simulator,data,rows=2):
        path=self.directory/'image.txt';path.write_bytes(data if isinstance(data,bytes) else data.encode())
        return subprocess.run(self.programs[simulator]+['+IMAGE='+str(path),'+NROWS='+str(rows)],
                              cwd=self.directory,text=True,capture_output=True,timeout=15)

    def test_valid_full_width_values_and_whitespace(self):
        forms=['\n'.join(ROWS)+'\n','\r\n'.join(r.upper() for r in ROWS)+'\r\n',
               '\n'.join(' \t'+r.replace(' ','\t\t')+'  ' for r in ROWS)+'\n','\n'.join(ROWS)]
        for simulator in self.programs:
            for data in forms:
                with self.subTest(simulator=simulator,data=data[:20]):
                    result=self.run_image(simulator,data)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertEqual([l for l in result.stdout.splitlines() if l.startswith('ROW ')],['ROW '+r for r in ROWS])
                    self.assertIn('PASS strict_ddr_image rows=2',result.stdout)

    def test_malformed_or_truncated_oracle_rejected(self):
        good='\n'.join(ROWS)+'\n'
        invalid={
            'empty':'','short':ROWS[0]+'\n','extra_row':good+f'10000080 {DATA0}\n',
            'trailing_bad':good+'garbage\n','trailing_half_row':good+'10000080\n',
            'trailing_blank':good+'\n','extra_token':good.replace(DATA0,DATA0+' dead'),
            'wide_address':good.replace('10000000','110000000'),
            'short_address':good.replace('10000000','1000000'),
            'wide_data':good.replace(DATA0,'1'+DATA0),'short_data':good.replace(DATA0,DATA0[:-1]),
            'unknown_x':good.replace(DATA0,'x'+DATA0[1:]),'unknown_z':good.replace(DATA0,'z'+DATA0[1:]),
            'hex_prefix':good.replace('10000000','0x10000000'),
            'embedded_nul':good.replace(DATA0,DATA0+'\x00ignored'),
            'misaligned':good.replace('10000040','10000042'),
            'outside':good.replace('10000040','10001000'),
            'below_base':good.replace('10000000','0fffffc0'),
            'duplicate':ROWS[0]+'\n'+ROWS[0]+'\n','descending':'\n'.join(reversed(ROWS))+'\n',
            'oversized':ROWS[0]+' '*600+'\n'+ROWS[1]+'\n',
        }
        for simulator in self.programs:
            for name,data in invalid.items():
                with self.subTest(simulator=simulator,control=name):
                    result=self.run_image(simulator,data)
                    self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertNotIn('PASS strict_ddr_image',result.stdout)

    def test_independent_count_must_be_positive_exact_and_bounded(self):
        for simulator in self.programs:
            for rows in (0,-1,1,3,65):
                with self.subTest(simulator=simulator,rows=rows):
                    result=self.run_image(simulator,'\n'.join(ROWS)+'\n',rows)
                    self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertNotIn('PASS strict_ddr_image',result.stdout)


if __name__=='__main__':unittest.main()
