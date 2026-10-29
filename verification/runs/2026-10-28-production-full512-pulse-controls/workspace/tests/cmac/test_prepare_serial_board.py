"""Serialized board evidence/admission controls; all local fixtures are mocks."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/cmac'))
import prepare_serial_board as prep


class SerialPreparationTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'build').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='serial-prepare-controls-',dir=ROOT/'build')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.source=prep.native.inputs()[1]

    def mock_report(self,sim):
        out=self.base/sim;out.mkdir(exist_ok=True)
        binary=out/('obj/sim' if sim=='verilator' else 'sim.vvp')
        binary.parent.mkdir(exist_ok=True);binary.write_text('mock native binary, never execute\n')
        files=[binary];commands=[];tests=[]
        tool_version='Verilator 5.048 MOCK_ONLY' if sim=='verilator' else 'Icarus Verilog 13.0 MOCK_ONLY'
        versions=dict(version=tool_version,cxx_version='c++ MOCK_ONLY',vvp_version='Icarus Verilog runtime 13.0 MOCK_ONLY')
        for label,argv in prep.producer_prelude(sim,str(binary.relative_to(ROOT)),'2').items():
            log=out/(label+'.log');log.write_text(versions.get(label,'MOCK ONLY: command not executed')+'\n')
            files.append(log);commands.append(dict(argv=argv,log=str(log.relative_to(ROOT)),status='PASS',returncode=0))
        modes=set(range(7 if sim=='verilator' else 8))|{8}
        for mode in sorted(modes):
            good=mode in (0,3,4,5,6)
            line=(f'PASS CMAC BRAM board RTL mode={mode} success={2 if mode==6 else int(good)} '
                  f'resets={int(mode in (3,4,5,6))} faults={int(not good)} init=4096 '
                  f'check={4096 if good else 0} cmd_reads={196 if good else 0} '
                  f'operand_reads={12288 if good else 0} writes={64 if good else 0} '
                  f'acks={64 if good else 0} cycles=1; no physical FPGA test')
            log=out/f'mode{mode}.log';log.write_text(line+'\n');files.append(log)
            argv=([str(binary)] if sim=='verilator' else ['vvp',str(binary)])+[f'+MODE={mode}']
            commands.append(dict(argv=argv,log=str(log.relative_to(ROOT)),status='PASS',returncode=0))
            tests.append(dict(name=f'mode{mode}',status='PASS',result=line))
        return dict(status='PASS_CONSOLIDATED_CMAC_NATIVE_BOARD',action='test',suite='board',
            finished_utc='MOCK_ONLY',source=self.source,
            tool_version=tool_version,cxx_version=versions['cxx_version'],vvp_version=versions['vvp_version'],
            bitstream_emitted=False,hardware_programmed=False,commands=commands,tests=tests,
            artifacts=prep.fingerprint(files),runtime_binary=prep.fingerprint([binary]))

    def package(self,bound=False):
        reports={}
        if bound:
            for sim in ['iverilog','verilator']:
                path=self.base/(sim+'.json');prep.write_json(path,self.mock_report(sim));reports[sim]=path
        return prep.prepare(self.base/'package',reports)

    def test_prepare_does_not_execute_tools_or_claim_hardware(self):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('No external tool')):
            directory=self.package();result=prep.verify(directory)
        self.assertEqual(result['status'],'SOURCE_INTACT_REVIEW_PENDING')
        self.assertEqual(len(result['blockers']),2)
        text=(directory/'build.tcl').read_text()
        self.assertIn('synth_design -top ypcb_cmac_top ',text)
        self.assertNotIn('ypcb_cmac_array_top',text)
        self.assertNotIn('write_bitstream',text)
        self.assertIn('RK_SERIAL_SOURCE_SHA',text)
        self.assertIn('DESIGNWARE_NOEXIST',text)
        self.assertIn('No block RAM inferred',text)
        self.assertFalse(list(directory.rglob('*.bit')))

    def test_full_mode_and_binary_evidence_required(self):
        original=self.mock_report('iverilog')
        prep.validate_report(original,'iverilog',self.source)
        mutations=[lambda r:r.update(status='RUNNING'),lambda r:r.update(suite='core'),
                   lambda r:r.update(source={}),lambda r:r.update(tool_version='Verilator'),
                   lambda r:r.update(tests=r['tests'][:-1]),lambda r:r.update(runtime_binary={}),
                   lambda r:r['commands'][0].update(returncode=True),
                   lambda r:r['commands'][0].update(argv=['not-the-tested-binary','+MODE=0']),
                   lambda r:r['tests'][0].update(result='PASS wrong'),
                   lambda r:r.update(hardware_programmed=True)]
        for mutation in mutations:
            record=deepcopy(original);mutation(record)
            with self.assertRaises(ValueError):prep.validate_report(record,'iverilog',self.source)
        binary=ROOT/next(iter(original['runtime_binary']['files']));binary.write_text('changed\n')
        with self.assertRaisesRegex(ValueError,'Changed native artifact'):
            prep.validate_report(original,'iverilog',self.source)

    def test_complete_bound_package_still_requires_board_review(self):
        directory=self.package(True);result=prep.verify(directory)
        self.assertEqual(result['blockers'],['Missing board reviewer'])
        with self.assertRaisesRegex(ValueError,'reviewer'):prep.command(directory)
        review=prep.read_json(directory/'board-review.json')
        review.update(reviewer='MOCK ONLY',checks={k:True for k in prep.BOARD_CHECKS},
            evidence={k:'MOCK NOT BOARD EVIDENCE' for k in prep.BOARD_CHECKS},
            config_voltage='1.8',cfgbvs='GND',led_active_low=0)
        prep.write_json(directory/'board-review.json',review)
        with patch.object(subprocess,'Popen',side_effect=AssertionError('Do not run Vivado')):
            command=prep.command(directory)
        self.assertEqual(command['argv'][0],'vivado')
        self.assertEqual(command['environment']['RK_EMIT_BITSTREAM'],'0')
        self.assertIs(command['vivado_executed'],False)

    def test_snapshot_inventory_and_copied_evidence_tampering_fail(self):
        directory=self.package(True)
        path=directory/'source/rtl/cmac/rk_cmac_bram_demo.sv'
        original=path.read_bytes();path.write_bytes(original+b'// tampered\n')
        with self.assertRaisesRegex(ValueError,'Changed snapshot'):prep.verify(directory)
        path.write_bytes(original)
        report=prep.read_json(directory/'report.json')
        del report['source']['files']['rtl/cmac/rk_cmac_bram_demo.sv']
        prep.write_json(directory/'report.json',report)
        with self.assertRaisesRegex(ValueError,'Invalid package manifest'):prep.verify(directory)

    def test_wrong_memory_counts_fail_even_with_consistent_artifact_hashes(self):
        report=self.mock_report('verilator')
        test=next(t for t in report['tests'] if t['name']=='mode0')
        test['result']=test['result'].replace('check=4096','check=4095')
        log=ROOT/next(c['log'] for c in report['commands'] if Path(c['log']).stem=='mode0')
        log.write_text(test['result']+'\n')
        report['artifacts']=prep.fingerprint([ROOT/n for n in report['artifacts']['files']])
        with self.assertRaisesRegex(ValueError,'Wrong serialized board result counts'):
            prep.validate_report(report,'verilator',self.source)

    def test_compile_source_output_and_prelude_logs_are_bound(self):
        for sim in ('iverilog','verilator'):
            original=self.mock_report(sim)
            for mutation in ('only_modes','missing_compile','missing_version','extra_step',
                             'compile_output','compile_top','compile_source','unbound_log','wrong_version'):
                with self.subTest(simulator=sim,mutation=mutation):
                    record=deepcopy(original)
                    step=next(c for c in record['commands'] if Path(c['log']).stem=='compile')
                    if mutation=='only_modes':
                        record['commands']=[c for c in record['commands'] if Path(c['log']).stem.startswith('mode')]
                    elif mutation in ('missing_compile','missing_version'):
                        label=mutation.removeprefix('missing_')
                        record['commands']=[c for c in record['commands'] if Path(c['log']).stem!=label]
                    elif mutation=='extra_step':record['commands'].append(deepcopy(step))
                    elif mutation=='compile_output':step['argv'][step['argv'].index('-o')+1]='other_binary'
                    elif mutation=='compile_top':
                        flag='-s' if sim=='iverilog' else '--top-module'
                        step['argv'][step['argv'].index(flag)+1]='wrong_top'
                    elif mutation=='compile_source':step['argv'].pop()
                    elif mutation=='unbound_log':del record['artifacts']['files'][step['log']]
                    elif mutation=='wrong_version':record['tool_version']+=' changed'
                    with self.assertRaises(ValueError):prep.validate_report(record,sim,self.source)

    def test_board_result_fields_have_exact_boundaries(self):
        report=self.mock_report('verilator')
        valid=next(t['result'] for t in report['tests'] if t['name']=='mode0')
        bad=next(t['result'] for t in report['tests'] if t['name']=='mode1')
        prep.validate_board_result(valid,0);prep.validate_board_result(bad,1)
        for line,mode in [(valid.replace('acks=64','acks=640'),0),
                          (valid.replace('writes=64','writes=640'),0),
                          (valid.replace('success=1','success=10'),0),
                          (bad.replace('faults=1','faults=10'),1),
                          (valid+' trailing',0),(valid.replace('cycles=1','cycles=0'),0),
                          (valid.replace('no physical FPGA test','physical FPGA passed'),0)]:
            with self.subTest(line=line),self.assertRaises(ValueError):prep.validate_board_result(line,mode)
        self.assertIn('tools/cmac/board_contract.py',self.source['files'])

    def test_optimized_python_is_refused_by_native_producer(self):
        result=subprocess.run([sys.executable,'-O',str(ROOT/'tools/cmac/run.py'),'check'],
                              text=True,capture_output=True,timeout=30)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('do not use -O',result.stderr)


if __name__=='__main__':unittest.main()
