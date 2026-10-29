"""EW package admission and mocked Tcl controls; no Vivado process is started."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_ew_fpga as prep
from tools.evidence import source_revision
from test_fpga_build import HARNESS

ROOT = Path(__file__).resolve().parents[1]


def mock_simulator(simulator, revision, artifact_root, profile='startup'):
    """Faithful record structure with explicitly fake executable/log contents."""
    names = {'alu', 'dma_demo', 'demo_memory', prep.PROFILES[profile]['board_test']}
    if profile == 'startup':
        names.add('startup_reset')
    root = Path(artifact_root).resolve()
    prefix = 'build/' + ('rtl' if simulator == 'verilator' else 'iverilog') + '/'
    artifacts, commands, tests = {}, [], []
    def write(name, text):
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        artifacts[name] = prep.digest(path)
    def manifest(files):
        text = ''.join(f'{sha}  {name}\n' for name, sha in sorted(files.items()))
        return dict(sha256=hashlib.sha256(text.encode()).hexdigest(), files=dict(files))
    def command(name, argv, text):
        log = prefix + name + '.log'
        write(log, text + '\nMOCK UNIT CONTROL ONLY; NO HDL WAS EXECUTED\n')
        result = dict(name=name, argv=argv, log=log, log_sha256=artifacts[log], status='PASS', returncode=0)
        commands.append(result)
        return result
    compiler = '/mock/bin/' + simulator
    version = 'Verilator 0 MOCK_UNIT_CONTROL_ONLY' if simulator == 'verilator' else 'Icarus Verilog version 0 MOCK_UNIT_CONTROL_ONLY'
    command('version', [compiler, '--version' if simulator == 'verilator' else '-V'], version)
    runtime = dict(path='/mock/bin/vvp', sha256='0'*64)
    runtime_version = 'Icarus Verilog runtime version 0 MOCK_UNIT_CONTROL_ONLY'
    if simulator == 'iverilog':
        command('runtime_version', [runtime['path'], '-V'], runtime_version)
    write('build/vectors/alu.hex', 'MOCK INPUT; NOT NUMERICAL EVIDENCE\n')
    stimuli = manifest({'build/vectors/alu.hex': artifacts['build/vectors/alu.hex']})
    results = {
        'alu': ['PASS ALU: 12963 vectors, 17262 cycles'],
        'dma_demo': ['PASS DMA board workload: verbatim SUB(9), two tasks, 324 requests, 336 memory checks',
                     'PASS DMA demo reset during command fetch and restart',
                     'PASS DMA demo reset during data execution and restart',
                     'PASS DMA demo initialization bus error', 'PASS DMA demo command bus error',
                     'PASS DMA demo completion-count mismatch', 'PASS DMA demo known readback corruption',
                     'PASS DMA demo watchdog and fault recovery'],
        'demo_memory': ['PASS sparse demo BRAM: 80 checked transfers, adjacent requests, dual-port reset'],
        'ypcb': ['PASS YPCB top: startup, asynchronous reset, synchronized release, both LED polarities'],
        'startup_reset': ['PASS startup reset: initial hold, exact release, synchronous restart, held and repeated requests'],
        'ypcb_ew_startup': ['PASS YPCB startup profile: no external reset, 64-cycle hold, raw SUB(9), both LED polarities'],
    }
    if simulator == 'iverilog':
        results['dma_demo'].insert(-1, 'PASS DMA demo unknown readback corruption')
    for name in sorted(names):
        top = prep.BOARD_TOPS[name]
        image = prefix + ('obj_' + top + '/sim' if simulator == 'verilator' else top + '.vvp')
        write(image, 'MOCK EXECUTABLE; NEVER EXECUTE THIS FIXTURE: ' + top + '\n')
        binding = dict(path=image, sha256=artifacts[image], build_command=top + '_build')
        if simulator == 'verilator':
            argv = [compiler, '--binary', '--timing', '--assert', '-Wall', '-j', '2',
                    '--top-module', top, '--Mdir', str(root / prefix / ('obj_' + top)), '-o', 'sim']
            execute = [str(root / image)]
        else:
            argv = [compiler, '-g2012', '-Wall', '-s', top, '-o', str(root / image)]
            execute = [runtime['path'], str(root / image)]
        argv += [str(root / source) for source in prep.board_test_sources(name)]
        command(top + '_build', argv, 'MOCK compiler output')['output'] = binding
        if name == 'alu':
            execute += [f'+VECTORS={root}/build/vectors/alu.hex', '+COUNT=12963']
        command(name, execute, '\n'.join(results[name]))
        tests.append(dict(name=name, status='PASS', results=results[name], execution=binding | {'command': name}))
    record = dict(status='PASS', finished_utc='MOCK_UNIT_CONTROL_ONLY', simulator=simulator,
                  execution_schema=1, execution_root=str(root), source_revision=revision,
                  tool_version=version, commands=commands, tests=tests,
                  artifacts=manifest(artifacts), stimuli=stimuli)
    if simulator == 'iverilog':
        record.update(runtime=runtime, runtime_version=runtime_version)
    return record


def complete_mock_review(directory):
    review = prep.read_json(directory / 'board-review.json')
    review.update(reviewer='MOCK UNIT TEST, NOT BOARD SIGNOFF', config_voltage='1.8',
                  cfgbvs='GND', led_active_low=0,
                  checks={key: True for key in prep.BOARD_CHECKS},
                  evidence={key: 'MOCK CONTROL ONLY' for key in prep.BOARD_CHECKS})
    prep.write_json(directory / 'board-review.json', review)
    return review


class EwPreparationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'build').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='ew-prepare-control-', dir=ROOT / 'build')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def prepare(self, profile='startup', evidence=False):
        reports = {}
        if evidence:
            revision = source_revision()
            for simulator in ('verilator', 'iverilog'):
                path = self.directory / (simulator + '.json')
                prep.write_json(path, mock_simulator(simulator, revision, self.directory / 'producer', profile))
                reports[simulator] = path
        return prep.prepare(profile, self.directory / profile, reports)

    def test_prepare_is_file_only_and_review_starts_incomplete(self):
        # source_revision reads Git; all implementation/tool launches stay forbidden.
        revision = source_revision()
        with patch.object(prep, 'source_revision', return_value=revision), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('No tool launch allowed')):
            directory = self.prepare()
            result = prep.verify(directory)
        self.assertEqual(result['status'], 'SOURCE_INTACT_REVIEW_PENDING')
        self.assertEqual(len(result['blockers']), 2)
        report = prep.read_json(directory / 'report.json')
        self.assertFalse(report['simulation_bound'])
        for flag in ('vivado_executed', 'implementation_completed', 'bitstream_emitted', 'hardware_programmed'):
            self.assertIs(report[flag], False)
        review = prep.read_json(directory / 'board-review.json')
        self.assertTrue(all(value is False for value in review['checks'].values()))
        self.assertIsNone(review['config_voltage'])
        with self.assertRaisesRegex(ValueError, 'Both matching simulator'):
            prep.command(directory)

    def test_both_profiles_keep_exact_top_pins_and_clock(self):
        for profile, top in [('external-r28', 'ypcb_top'), ('startup', 'ypcb_ew_startup_top')]:
            directory = self.prepare(profile)
            script = (directory / 'build.tcl').read_text()
            self.assertIn('synth_design -top ' + top, script)
            self.assertIn('double($period) == 20.0', script)
            xdc = (directory / 'source' / prep.PROFILES[profile]['constraints']).read_text()
            self.assertIn('AA28', xdc)
            self.assertEqual('get_ports SYS_RSTN' in xdc, profile == 'external-r28')
            self.assertIn('unconstrained_internal_endpoints', script)
            self.assertNotIn('write_bitstream', script)
            self.assertFalse(list(directory.rglob('*.bit')))

    def test_command_only_prints_future_invocation_after_bound_review(self):
        directory = self.prepare(evidence=True)
        with self.assertRaisesRegex(ValueError, 'reviewer'):
            prep.command(directory)
        complete_mock_review(directory)
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('Must not execute Vivado')):
            result = prep.command(directory)
        self.assertEqual(result['argv'][0], 'vivado')
        self.assertEqual(result['environment']['RK_EMIT_BITSTREAM'], '0')
        self.assertIs(result['vivado_executed'], False)
        (directory / 'implementation').mkdir()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            prep.command(directory)

    def test_stale_incomplete_and_wrong_simulation_evidence_rejected(self):
        revision = source_revision()
        original = mock_simulator('iverilog', revision, self.directory / 'producer')
        mutations = [lambda r: r.update(status='RUNNING'),
                     lambda r: r.update(finished_utc=None),
                     lambda r: r.update(simulator='verilator'),
                     lambda r: r['source_revision'].update(sha256='0'*64),
                     lambda r: r.update(tests=[t for t in r['tests'] if t['name'] != 'startup_reset']),
                     lambda r: r['commands'][0].update(returncode=True),
                     lambda r: r['commands'][0].update(status='TIMEOUT'),
                     lambda r: r['tests'][0].update(status='FAIL')]
        for mutation in mutations:
            record = deepcopy(original); mutation(record)
            with self.assertRaises(ValueError):
                prep.simulation_evidence(record, 'iverilog', revision, 'startup')
        path = self.directory / 'only-one.json'; prep.write_json(path, original)
        with self.assertRaisesRegex(ValueError, 'both simulator'):
            prep.prepare('startup', self.directory / 'bad', {'iverilog': path})
        self.assertFalse((self.directory / 'bad').exists())

    def test_snapshot_tcl_and_report_tampering_fail(self):
        directory = self.prepare()
        source = directory / 'source/rtl/rk_startup_reset.sv'
        old = source.read_bytes(); source.write_bytes(old + b'// changed\n')
        with self.assertRaisesRegex(ValueError, 'Changed snapshot'):
            prep.verify(directory)

        source.write_bytes(old)
        script = directory / 'build.tcl'; old_tcl = script.read_bytes(); script.write_bytes(old_tcl+b'puts altered\n')
        with self.assertRaisesRegex(ValueError, 'Changed generated Tcl'):
            prep.verify(directory)
        script.write_bytes(old_tcl)
        report = prep.read_json(directory / 'report.json')
        del report['production_revision']['files']['rtl/rk_startup_reset.sv']
        prep.write_json(directory / 'report.json', report)
        with self.assertRaisesRegex(ValueError, 'source manifest'):
            prep.verify(directory)


    def test_summary_only_and_wrong_execution_metadata_are_rejected(self):
        revision = source_revision()
        original = mock_simulator('verilator', revision, self.directory / 'producer')
        def test(record, name):
            return next(t for t in record['tests'] if t['name'] == name)
        def cmd(record, name):
            return next(c for c in record['commands'] if c['name'] == name)
        mutations = [lambda r: r.pop('execution_schema'),
                     lambda r: r.pop('artifacts'),
                     lambda r: r.pop('tool_version'),
                     lambda r: test(r, 'startup_reset').update(results=[]),
                     lambda r: test(r, 'ypcb_ew_startup')['execution'].update(command='startup_reset'),
                     lambda r: cmd(r, 'startup_reset').update(argv=['true']),
                     lambda r: cmd(r, 'tb_ypcb_ew_startup_build')['argv'].remove('--assert'),
                     lambda r: cmd(r, 'alu')['argv'].__setitem__(-1, '+COUNT=1'),
                     lambda r: r['tests'].append(deepcopy(r['tests'][0]))]
        for mutation in mutations:
            record = deepcopy(original); mutation(record)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                prep.simulation_evidence(record, 'verilator', revision, 'startup')

    def test_missing_or_corrupt_original_binary_log_and_stimulus_fail(self):
        revision = source_revision()
        for simulator in ('verilator', 'iverilog'):
            record = mock_simulator(simulator, revision, self.directory / 'producer')
            test = next(t for t in record['tests'] if t['name'] == 'ypcb_ew_startup')
            cmd = next(c for c in record['commands'] if c['name'] == 'ypcb_ew_startup')
            for name in (test['execution']['path'], cmd['log'], 'build/vectors/alu.hex'):
                path = Path(record['execution_root']) / name
                original = path.read_bytes()
                for mutation in ('missing', 'corrupt'):
                    with self.subTest(simulator=simulator, artifact=name, mutation=mutation):
                        if mutation == 'missing': path.unlink()
                        else: path.write_bytes(original + b'changed\n')
                        with self.assertRaisesRegex(ValueError, 'RTL artifact'):
                            prep.simulation_evidence(record, simulator, revision, 'startup')
                        path.write_bytes(original)

    def test_known_pass_marker_and_version_are_checked_against_bound_logs(self):
        revision = source_revision()
        original = mock_simulator('iverilog', revision, self.directory / 'producer')
        def update_log(record, command_name, text):
            command = next(c for c in record['commands'] if c['name'] == command_name)
            path = Path(record['execution_root']) / command['log']
            path.write_text(text)
            command['log_sha256'] = prep.digest(path)
            record['artifacts']['files'][command['log']] = command['log_sha256']
            manifest = ''.join(f'{sha}  {name}\n' for name, sha in sorted(record['artifacts']['files'].items()))
            record['artifacts']['sha256'] = hashlib.sha256(manifest.encode()).hexdigest()
        record = deepcopy(original)
        board = next(t for t in record['tests'] if t['name'] == 'ypcb_ew_startup')
        board['results'] = ['PASS unrelated test']
        update_log(record, 'ypcb_ew_startup', 'PASS unrelated test\n')
        with self.assertRaisesRegex(ValueError, 'selected board/reset results'):
            prep.simulation_evidence(record, 'iverilog', revision, 'startup')
        record = mock_simulator('iverilog', revision, self.directory / 'producer')
        update_log(record, 'version', 'Different tool\n')
        with self.assertRaisesRegex(ValueError, 'version does not match'):
            prep.simulation_evidence(record, 'iverilog', revision, 'startup')

    def test_package_preserves_evidence_independent_of_producer_workspace(self):
        directory = self.prepare(evidence=True); complete_mock_review(directory)
        shutil.rmtree(self.directory / 'producer')
        self.assertEqual(prep.command(directory)['status'], 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD')
        record = prep.read_json(directory / 'evidence/verilator.json')
        test = next(t for t in record['tests'] if t['name'] == 'ypcb_ew_startup')
        command = next(c for c in record['commands'] if c['name'] == 'ypcb_ew_startup')
        for name in (test['execution']['path'], command['log'], 'build/vectors/alu.hex'):
            path = directory / 'evidence/verilator/artifacts' / name
            original = path.read_bytes()
            path.write_bytes(original + b'corrupt\n')
            with self.subTest(artifact=name), self.assertRaisesRegex(ValueError, 'RTL artifact'):
                prep.verify(directory)
            path.write_bytes(original)

    def test_symlink_and_parent_path_snapshots_rejected(self):
        directory = self.prepare()
        source = directory / 'source/rtl/rk_startup_reset.sv'
        source.unlink(); source.symlink_to(ROOT / 'rtl/rk_startup_reset.sv')
        with self.assertRaisesRegex(ValueError, 'Changed snapshot'):
            prep.verify(directory)
        source.unlink(); shutil.copyfile(ROOT / 'rtl/rk_startup_reset.sv', source)
        report = prep.read_json(directory / 'report.json')
        report['snapshot_files']['../outside'] = '0'*64
        prep.write_json(directory / 'report.json', report)
        with self.assertRaisesRegex(ValueError, 'Unsafe snapshot path'):
            prep.verify(directory)

    def test_electrical_identity_and_explicit_review_required(self):
        directory = self.prepare(evidence=True)
        good = complete_mock_review(directory); record = prep.read_json(directory / 'report.json')
        for voltage, cfgbvs in [('1.5','GND'), ('1.8','GND'), ('2.5','VCCO'), ('3.3','VCCO')]:
            review = dict(good, config_voltage=voltage, cfgbvs=cfgbvs)
            prep.validate_board_review(review, record)
        for key, value in [('profile','external-r28'),('board','unknown'),('part','wrong'),
                           ('source_sha256','0'*64),('reviewer',''),('config_voltage','NaN'),
                           ('cfgbvs','VCCO'),('led_active_low',True)]:
            review = dict(good); review[key] = value
            with self.assertRaises(ValueError):
                prep.validate_board_review(review, record)
        for value in (False, 'true', 1):
            review = deepcopy(good); review['checks']['reset_contract'] = value
            with self.assertRaises(ValueError): prep.validate_board_review(review, record)
        review = deepcopy(good); review['evidence']['configuration_bank']=''
        with self.assertRaises(ValueError): prep.validate_board_review(review, record)

    def test_existing_output_is_preserved_and_invalid_profile_fails(self):
        directory = self.prepare(); before = (directory / 'report.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            prep.prepare('startup', directory)
        self.assertEqual((directory / 'report.json').read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'Unknown EW profile'):
            prep.prepare('unknown', self.directory / 'unknown')

    def test_frozen_old_hardware_cannot_authorize_current_build(self):
        directory = self.prepare(evidence=True); complete_mock_review(directory)
        original_digest = prep.digest
        def changed_live_file(path):
            return '0'*64 if Path(path) == ROOT/'rtl/rk_startup_reset.sv' else original_digest(path)
        with patch.object(prep, 'digest', side_effect=changed_live_file):
            result = prep.verify(directory)
            self.assertEqual(result['status'], 'SOURCE_INTACT_REVIEW_PENDING')
            self.assertIn('Selected hardware source changed', result['blockers'][0])
            with self.assertRaisesRegex(ValueError, 'hardware source changed'):
                prep.command(directory)

    def test_python_optimization_cannot_remove_integrity_checks(self):
        directory = self.prepare()
        (directory / 'source/rtl/rk_startup_reset.sv').write_text('changed\n')
        result = subprocess.run([os.sys.executable, '-O', str(ROOT / 'tools/prepare_ew_fpga.py'),
                                 'verify', str(directory)], text=True, capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Changed snapshot', result.stderr)

    def test_checkpoint_tcl_retains_physical_gates(self):
        tclsh = shutil.which('tclsh')
        if tclsh is None:
            self.fail('UNAVAILABLE: tclsh is required for checkpoint controls')
        directory = self.prepare(evidence=True); complete_mock_review(directory)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        env.update(prep.command(directory)['environment'])
        env['RK_TEST_BUILD_SCRIPT'] = str(directory / 'build.tcl')
        additions = r'''
proc get_parts {args} {return xc7k480tffg1156-2}
proc get_clocks {args} {return sys_clk}
rename get_property original_get_property
proc get_property {name object} {
    if {$name eq "PERIOD"} {return [mock MOCK_PERIOD 20.0]}
    return [original_get_property $name $object]
}
proc report_route_status {args} {event report_route_status {*}$args}
proc report_pulse_width {args} {event report_pulse_width {*}$args}
'''
        harness = HARNESS.replace('set ::properties {}', additions + '\nset ::properties {}')
        for settings, passes in [({},True),({'MOCK_NO_CLOCK':'1'},False),
                                 ({'MOCK_UNCONSTRAINED_INTERNAL_ENDPOINTS':'1'},False),
                                 ({'MOCK_SLACK_MIN':'-0.1'},False),({'MOCK_SLACK_MAX':'NaN'},False),
                                 ({'MOCK_DRC_SEVERITY':'Critical Warning'},False),
                                 ({'MOCK_NO_BRAM':'1'},False),({'MOCK_PERIOD':'25'},False),
                                 ({'RK_CONFIG_VOLTAGE':'1.8','RK_CFGBVS':'VCCO'},False),
                                 ({'RK_EMIT_BITSTREAM':'1'},False)]:
            result = subprocess.run([tclsh],input=harness,env=env|settings,text=True,
                                    capture_output=True,cwd=self.directory,timeout=10)
            self.assertEqual(result.returncode==0,passes,result.stdout+result.stderr)
            self.assertNotIn('EVENT write_bitstream',result.stdout)
        self.assertFalse(list(directory.rglob('*.dcp')))

    def test_invalid_reset_parameters_fail_in_real_simulation(self):
        if not shutil.which('iverilog') or not shutil.which('vvp'):
            self.fail('UNAVAILABLE: Icarus is required for reset parameter controls')
        for hold in (0, 2, 65536):
            bench = self.directory / f'invalid_{hold}.sv'
            bench.write_text('`timescale 1ns/1ps\nmodule bad_reset;\n'
                'reg clk=0; wire rst_n; always #5 clk=~clk;\n'
                f'rk_startup_reset #(.HOLD_CYCLES({hold})) dut(.clk(clk),.request_reset(1\'b0),.rst_n(rst_n));\n'
                'initial begin #100; $display("UNEXPECTED parameter acceptance"); $finish; end\nendmodule\n')
            binary = self.directory / f'invalid_{hold}.vvp'
            compile_result = subprocess.run(['iverilog', '-g2012', '-s', 'bad_reset', '-o', str(binary),
                str(ROOT/'rtl/rk_startup_reset.sv'),str(bench)],text=True,capture_output=True,timeout=30)
            self.assertEqual(compile_result.returncode,0,compile_result.stderr)
            result = subprocess.run(['vvp',str(binary)],text=True,capture_output=True,timeout=10)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertIn('HOLD_CYCLES must be between 3 and 65535',result.stdout)
            self.assertNotIn('UNEXPECTED parameter acceptance',result.stdout)


if __name__ == '__main__':
    unittest.main()
