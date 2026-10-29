"""Exercise replay scoreboard rejection through actual Icarus DUT benches."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from model.dma import DMAEmulator
from model.sim import Memory
from tools.dma_fixtures import A, B, C, D, BASE, packed, synthetic_words

ROOT = Path(__file__).resolve().parents[1]
BENCHES = ('tb_ew', 'tb_dma', 'tb_axi_mem', 'tb_host_axi')


@unittest.skipUnless(all(shutil.which(tool) for tool in ('iverilog', 'vvp', 'verilator')),
                     'UNAVAILABLE: both HDL simulators are required for parser compatibility controls')
class MemoryCheckParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='rk-parser-compat-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        bench = str(ROOT / 'tests/tb_memory_check.sv')
        cls.executables = {
            'iverilog': ['vvp', str(cls.directory / 'parser.vvp')],
            'verilator': [str(cls.directory / 'obj/parser')],
        }
        commands = {
            'iverilog': ['iverilog', '-g2012', '-s', 'tb_memory_check', '-o',
                         str(cls.directory / 'parser.vvp'), bench],
            'verilator': ['verilator', '--binary', '--assert', '-Wall', '-j', '2',
                          '--top-module', 'tb_memory_check', '--Mdir', str(cls.directory / 'obj'),
                          '-o', 'parser', bench],
        }
        for simulator, command in commands.items():
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            version = subprocess.run([simulator, '-V' if simulator == 'iverilog' else '--version'],
                                     text=True, capture_output=True, check=True)
            print('Shared scoreboard runtime: ' + version.stdout.splitlines()[0], flush=True)

    def check(self, content, count, *, passes=False, allow_empty=False):
        path = self.directory / 'check.txt'
        path.write_text(content)
        for simulator, command in self.executables.items():
            with self.subTest(simulator=simulator, content=content, count=count):
                result = subprocess.run(command + [f'+FILE={path}', f'+NCHECKS={count}',
                                                   f'+ALLOW_EMPTY={int(allow_empty)}'],
                                        cwd=ROOT, text=True, capture_output=True, timeout=10)
                if passes:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('PASS shared memory scoreboard', result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('PASS ', result.stdout)

    def test_valid_records_and_explicit_empty_error_contract(self):
        self.check('10000000 1234\n10000002 abcd\n', 2, passes=True)
        self.check('10000000 1234\n10000002 abcd', 2, passes=True)
        self.check('10000000\t1234\r\n10000002 ABCD\n', 2, passes=True)
        self.check('', 0, passes=True, allow_empty=True)

    def test_all_parser_rejections_execute_in_both_simulators(self):
        valid = '10000000 1234\n10000002 abcd\n'
        for bad in ('', 'bad\n', '10000000 1234\n', valid + 'bad\n',
                    '10000000 1234 extra\n10000002 abcd\n',
                    '10000000 11234\n10000002 abcd\n',
                    '110000000 1234\n10000002 abcd\n',
                    '10000000 xxxx\n10000002 abcd\n',
                    '10000000 1234\n10000000 1234\n',
                    '10000001 1234\n10000002 abcd\n',
                    '10000000 1234\n10000010 0000\n',
                    '10000000 0000\n10000002 abcd\n',
                    valid + '10000004 0000\n'):
            self.check(bad, 2)
        self.check('', 0)
        self.check('', -1, allow_empty=True)


@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),
                     'UNAVAILABLE: Icarus is required for replay scoreboard controls')
class MemoryCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='rk-memory-check-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        version = subprocess.run(['iverilog', '-V'], text=True, capture_output=True, check=True)
        print('Replay scoreboard controls: ' + version.stdout.splitlines()[0], flush=True)
        names = ('rk_fp16_alu', 'rk_ew_regs', 'rk_ew_engine', 'rk_ew_core',
                 'rk_ew_dma', 'rk_axi_mem', 'rk_job_control', 'rk_ew_axi')
        sources = [str(ROOT / 'rtl' / (name + '.sv')) for name in names]
        for top in BENCHES:
            command = ['iverilog', '-g2012', '-s', top, '-o', str(cls.directory / (top + '.vvp'))]
            result = subprocess.run(command + sources + [str(ROOT / 'tests' / (top + '.sv'))],
                                    cwd=ROOT, text=True, capture_output=True, timeout=60)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        regions = {A: struct.pack('<8H', *([0x3c00] * 8)),
                   B: struct.pack('<8H', *([0x4000] * 8)),
                   D: struct.pack('<8H', *([0xdead] * 8)), C: packed(synthetic_words())}
        memory = Memory()
        for address, data in regions.items():
            memory.map(address, data)
        DMAEmulator(memory).submit_dma(C, 22)
        cls.expected = ''.join(f'{address+2*i:08x} {value:04x}\n'
                               for address, data in sorted(memory.regions.items())
                               for i, (value,) in enumerate(struct.iter_unpack('<H', data)))
        cls.checks = sum(len(data) // 2 for data in regions.values())
        cls.directory.joinpath('input.hex').write_text(''.join(
            f'@{(address-BASE)//2:x}\n' + ''.join(f'{value:04x}\n' for value, in struct.iter_unpack('<H', data))
            for address, data in sorted(regions.items())))
        cls.directory.joinpath('mapped.hex').write_text(''.join(
            f'@{(address-BASE)//2:x}\n' + '1\n' * (len(data)//2) for address, data in sorted(regions.items())))
        cls.directory.joinpath('commands.hex').write_text(''.join(f'{word:016x}\n' for word in synthetic_words()))

    def run_case(self, top, oracle, *, include_count=True, checks=None):
        self.directory.joinpath('check.txt').write_text(oracle)
        command = ['vvp', str(self.directory / (top + '.vvp')), f'+CASE={self.directory}',
                   f'+OUTPUT={self.directory}/observed.hex', '+NCMD=22', f'+START={C:08x}',
                   '+AMOUNT=22', '+ECODE=0', '+NDONE=1', '+NJOBS=1', '+NTASKS=1',
                   '+REPEATS=1', f'+NTRANS={24 if top == "tb_ew" else 112}']
        if include_count:
            command.append(f'+NCHECKS={self.checks if checks is None else checks}')
        return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=30)

    def test_complete_oracle_passes_each_actual_replay_bench(self):
        for top in BENCHES:
            with self.subTest(top=top):
                result = self.run_case(top, self.expected)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS ', result.stdout)

    def test_empty_malformed_short_and_overwide_oracles_fail(self):
        lines = self.expected.splitlines(keepends=True)
        malformed = {'empty': '', 'malformed': 'invalid oracle\n',
                     'truncated': ''.join(lines[:-1]), 'partial_row': self.expected + '10000000\n',
                     'extra_row': self.expected + '100ffffe 0000\n',
                     'duplicate': lines[0] + self.expected,
                     'wide_value': self.expected.replace('3c00', '13c00', 1),
                     'wide_address': '1' + self.expected,
                     'unknown_value': self.expected.replace('3c00', 'xxxx', 1),
                     'extra_token': lines[0].rstrip() + ' garbage\n' + ''.join(lines[1:]),
                     'odd_address': self.expected.replace('10001000', '10001001', 1),
                     'wrong_value': self.expected.replace('3c00', '0000', 1)}
        for top in BENCHES:
            for name, oracle in malformed.items():
                with self.subTest(top=top, corruption=name):
                    result = self.run_case(top, oracle)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('PASS ', result.stdout)
                    self.assertRegex(result.stdout, 'memory check|memory mismatch')

    def test_success_requires_explicit_nonzero_count(self):
        for top in BENCHES:
            for include_count, checks in ((False, None), (True, 0)):
                with self.subTest(top=top, include_count=include_count, checks=checks):
                    result = self.run_case(top, '', include_count=include_count, checks=checks)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn('PASS ', result.stdout)

    def test_explicit_error_case_can_have_no_mapped_memory_checks(self):
        with tempfile.TemporaryDirectory(prefix='rk-empty-error-') as directory:
            case = Path(directory)
            case.joinpath('commands.hex').write_text('0000000000000000\n')
            case.joinpath('input.hex').write_text('@0\n0000\n')
            case.joinpath('check.txt').write_text('')
            result = subprocess.run(['vvp', str(self.directory / 'tb_ew.vvp'), f'+CASE={case}',
                                     '+NCHECKS=0', '+NCMD=1', '+ECODE=1', '+NDONE=0', '+NTRANS=0'],
                                    cwd=ROOT, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('expected_error=1', result.stdout)
