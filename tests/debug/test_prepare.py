"""Both optional debug preparation profiles; mock evidence, no Vivado launch."""
from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from tools.debug import prepare as prep


def load_fixture(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EW = load_fixture('debug_ew_parent_controls', ROOT/'tests/test_prepare_ew_fpga.py')
HOST = load_fixture('debug_host_parent_controls', ROOT/'tests/host/test_prepare.py')


class DebugPreparationTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'build').mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='debug-preparation-control-', dir=ROOT/'build')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.serial = 0

    def parent(self, kind, evidence=True):
        self.serial += 1
        if kind == 'host':
            fixture = HOST.HostPreparationTests()
            fixture.setUp(); self.addCleanup(fixture.doCleanups)
            # Current validator byte identity belongs to the parent snapshot,
            # even though this fixture mocks native qualification itself.
            fixture.protocol_names.append('tools/host/qualification.py')
            return fixture.package(evidence)
        root = self.directory/f'ew-parent-{self.serial}'
        reports = {}
        if evidence:
            revision = prep.base.source_revision()
            for simulator in ('verilator','iverilog'):
                path = self.directory/f'ew-{self.serial}-{simulator}.json'
                prep.write_json(path, EW.mock_simulator(simulator,revision,self.directory/f'producer-{self.serial}'))
                reports[simulator] = path
        return prep.base.prepare('startup',root,reports)

    def package(self, kind):
        parent = self.parent(kind)
        profile = 'ew-startup-ila' if kind == 'ew' else 'host-jtag-ew-ila'
        return parent, self.prepare(parent,self.directory/f'debug-{self.serial}',profile)

    def prepare(self, parent, out, profile):
        with patch.object(subprocess,'Popen',side_effect=AssertionError('Debug preparation must not launch a tool')):
            return prep.prepare(parent,out,profile)

    def review(self, directory):
        value = prep.read_json(directory/'board-review.json')
        value.update(reviewer='MOCK CONTROL ONLY',config_voltage='1.8',cfgbvs='GND',led_active_low=0,
                     checks={name:True for name in prep.base.BOARD_CHECKS},
                     evidence={name:'MOCK; NOT PHYSICAL EVIDENCE' for name in prep.base.BOARD_CHECKS})
        prep.write_json(directory/'board-review.json',value)

    def test_both_profiles_copy_only_qualified_evidence_and_start_unreviewed(self):
        for kind in ('ew','host'):
            with self.subTest(kind=kind):
                parent,directory = self.package(kind)
                with patch.object(subprocess,'Popen',side_effect=AssertionError('No build or hardware command')):
                    result = prep.verify(directory)
                    self.assertEqual(result['status'],'SOURCE_INTACT_REVIEW_PENDING')
                    with self.assertRaisesRegex(ValueError,'reviewer'): prep.command(directory)
                record = prep.read_json(directory/'report.json')
                actual = {str(p.relative_to(directory)) for section in ('evidence','artifacts')
                          for p in (directory/section).rglob('*') if p.is_file()}
                self.assertEqual(actual,set(record['evidence_manifest']['files']))
                self.assertEqual((directory/'parent-report.json').read_bytes(),(parent/'report.json').read_bytes())
                self.assertFalse(record['vivado_executed']); self.assertFalse(record['hardware_programmed'])
                review = prep.read_json(directory/'board-review.json')
                self.assertTrue(all(value is False for value in review['checks'].values()))

    def test_unmanifested_parent_file_or_symlink_is_rejected_without_following(self):
        for kind in ('ew','host'):
            parent = self.parent(kind)
            profile = 'ew-startup-ila' if kind=='ew' else 'host-jtag-ew-ila'
            extra = parent/'evidence/unqualified.txt'
            extra.write_text('not part of the verified evidence')
            with self.subTest(kind=kind,entry='file'), self.assertRaisesRegex(ValueError,'Unmanifested'):
                self.prepare(parent,self.directory/f'extra-{kind}',profile)
            self.assertFalse((self.directory/f'extra-{kind}'/'evidence/unqualified.txt').exists())
            extra.unlink()
            outside = self.directory/f'outside-{kind}.txt'; outside.write_text('MUST NOT BE READ')
            extra.symlink_to(outside)
            original_open = Path.open
            def guarded_open(path,*args,**kwargs):
                if path.resolve()==outside: raise AssertionError('Unqualified symlink target was read')
                return original_open(path,*args,**kwargs)
            with self.subTest(kind=kind,entry='symlink'), patch.object(Path,'open',guarded_open), \
                 self.assertRaisesRegex(ValueError,'Symlinked'):
                self.prepare(parent,self.directory/f'symlink-{kind}',profile)
            extra.unlink()

    def test_copied_evidence_is_independent_and_tampering_or_extras_fail(self):
        for kind in ('ew','host'):
            parent,directory = self.package(kind)
            self.review(directory)
            shutil.rmtree(parent)
            with patch.object(subprocess,'Popen',side_effect=AssertionError('No build or hardware command')):
                result = prep.command(directory)
            self.assertEqual(result['status'],'READY_FOR_SEPARATELY_AUTHORIZED_DEBUG_BUILD')
            self.assertEqual(result['environment']['RK_EMIT_BITSTREAM'],'0')
            record = prep.read_json(directory/'report.json')
            name = next(n for n in record['evidence_manifest']['files'] if not n.endswith('.json'))
            path = directory/name; saved = path.read_bytes()
            try:
                path.write_bytes(saved+b'changed')
                with self.subTest(kind=kind,change='bytes'), self.assertRaises(ValueError): prep.verify(directory)
            finally: path.write_bytes(saved)
            extra = directory/'evidence/unqualified.log'; extra.write_text('extra')
            with self.subTest(kind=kind,change='inventory'), self.assertRaisesRegex(ValueError,'Unmanifested'): prep.verify(directory)
            extra.unlink()
            self.assertEqual(prep.verify(directory)['status'],'READY_FOR_SEPARATELY_AUTHORIZED_DEBUG_BUILD')

    def test_state_bits_and_clock_anchor_are_source_bound(self):
        for kind in ('ew','host'):
            _,directory = self.package(kind)
            profile = 'ew-startup-ila' if kind=='ew' else 'host-jtag-ew-ila'
            path = directory/'source'/prep.PROFILES[profile]['plan']
            original = prep.read_json(path)
            for mutation in ('wide','boolean','anchor'):
                value = deepcopy(original)
                book = value['state_codebooks'][0]
                if mutation=='anchor': value['clock']['anchor_pin']='wrong/state_reg[0]/C'
                else:
                    if mutation=='wide': book['selected_bits']=list(range(book['declared_width']+1))
                    else: book['selected_bits'][0]=False
                    probe = next(p for p in value['probes'] if p['name']==book['name'])
                    probe['width']=len(book['selected_bits'])
                    probe['nets']=[f'{book["signal"]}[{int(bit)}]' for bit in book['selected_bits']]
                prep.write_json(path,value)
                with self.subTest(kind=kind,mutation=mutation), self.assertRaises(ValueError):
                    prep.plan(directory/'source',profile)
            prep.write_json(path,original)

    def test_debug_render_preserves_default_sources_and_physical_checks(self):
        originals = ['fpga/ew_checkpoint.tcl.in','fpga/ypcb_ew_startup_top.sv',
                     'fpga/host/ypcb_jtag_ew_top.sv','fpga/host/mailbox_cdc.tcl']
        before = {name:prep.digest(ROOT/name) for name in originals}
        for kind in ('ew','host'):
            _,directory = self.package(kind)
            text = (directory/'build.tcl').read_text()
            self.assertIn('Rendered by tools/debug/prepare.py.',text)
            self.assertIn('-flatten_hierarchy none -fsm_extraction off',text)
            self.assertIn('rk_ew_debug_insert $out $rk_ew_debug_plan',text)
            self.assertIn('rk_ew_debug_audit $out $rk_ew_debug_plan',text)
            for gate in ('RK_CONFIG_VOLTAGE','RK_CFGBVS','No block RAM inferred','unconstrained_internal_endpoints',
                         'Invalid or negative $delay_type slack','Blocking DRC'):
                self.assertIn(gate,text)
            self.assertNotIn('write_bitstream',text)
            if kind=='host':
                cdc = (directory/'debug-mailbox-cdc.tcl').read_text()
                self.assertEqual(cdc.count('REF_NAME == BSCANE2 && NAME == u_bscan'),2)
                self.assertIn('rk_host_cdc_audit $out',text)
        self.assertEqual(before,{name:prep.digest(ROOT/name) for name in originals})

    def test_exact_state_codebook_roles_sources_and_signals_are_required(self):
        for kind in ('ew','host'):
            _,directory = self.package(kind)
            profile = 'ew-startup-ila' if kind=='ew' else 'host-jtag-ew-ila'
            path = directory/'source'/prep.PROFILES[profile]['plan']
            original_bytes = path.read_bytes()
            original = prep.read_json(path)
            for mutation in ('duplicate','omitted','wrong_source','wrong_signal','wrong_type','wrong_bits'):
                value = deepcopy(original)
                first = value['state_codebooks'][0]
                if mutation=='duplicate': value['state_codebooks']=[deepcopy(first) for _ in range(3)]
                elif mutation=='omitted': value['state_codebooks'].pop()
                elif mutation=='wrong_source':
                    # This remains a self-consistent source enum/codebook and
                    # passed the old parser, but describes the wrong controller.
                    other = value['state_codebooks'][1]
                    for key in ('source','type','declared_width','selected_bits','values'):
                        first[key]=deepcopy(other[key])
                elif mutation=='wrong_signal': first['signal']=value['state_codebooks'][1]['signal']
                elif mutation=='wrong_type': first['type']='other_state_t'
                else: first['selected_bits']=list(reversed(first['selected_bits']))
                if mutation in ('wrong_source','wrong_signal','wrong_bits'):
                    probe = next(p for p in value['probes'] if p['name']==first['name'])
                    probe['width']=len(first['selected_bits'])
                    probe['nets']=[f'{first["signal"]}[{bit}]' for bit in first['selected_bits']]
                prep.write_json(path,value)
                with self.subTest(kind=kind,mutation=mutation), self.assertRaisesRegex(ValueError,'state codebooks|codebook source/signal'):
                    prep.plan(directory/'source',profile)
            path.write_bytes(original_bytes)
            self.assertEqual(prep.plan(directory/'source',profile),original)

    def test_parent_type_simulation_and_current_host_validator_are_required(self):
        for kind in ('ew','host'):
            parent = self.parent(kind,evidence=False)
            profile = 'ew-startup-ila' if kind=='ew' else 'host-jtag-ew-ila'
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError,'simulation-bound'):
                self.prepare(parent,self.directory/f'no-evidence-{kind}',profile)
        _,directory = self.package('host')
        original_digest = prep.digest
        for name in ('tools/host/prepare.py','tools/host/qualification.py'):
            def changed(path,name=name):
                return '0'*64 if Path(path)==ROOT/name else original_digest(path)
            with self.subTest(name=name), patch.object(prep,'digest',side_effect=changed), \
                 self.assertRaisesRegex(ValueError,'validator/input changed'):
                prep.verify(directory)

    def test_copied_validators_have_standalone_import_closure(self):
        for kind in ('ew','host'):
            _,directory = self.package(kind)
            source = directory/'source'
            before = {str(p.relative_to(directory)):prep.digest(p) for p in directory.rglob('*') if p.is_file()}
            self.assertIn('tools/host/prepare.py',prep.read_json(directory/'report.json')['source']['files'])
            with tempfile.TemporaryDirectory(prefix='debug-validator-outside-') as cwd:
                if kind=='ew':
                    command = [sys.executable,'-I','-B',str(source/'tools/debug/prepare.py'),'verify',str(directory)]
                else:
                    # HOST parent evidence is deliberately mocked in these unit
                    # controls, so test import closure rather than relabel it as
                    # genuine native qualification in the isolated interpreter.
                    code = ('import pathlib,sys\n'
                            'root=pathlib.Path(sys.argv[1]).resolve();sys.path.insert(0,str(root))\n'
                            'from tools.debug import prepare\n'
                            'for module in (prepare,prepare.base,prepare.host):\n'
                            ' assert pathlib.Path(module.__file__).resolve().is_relative_to(root)\n'
                            'print("PASS copied HOST validator import closure; mock evidence is not replayed")\n')
                    command = [sys.executable,'-I','-B','-c',code,str(source)]
                result = subprocess.run(command,cwd=cwd,text=True,capture_output=True,timeout=30)
            with self.subTest(kind=kind):
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                if kind=='ew': self.assertIn('SOURCE_INTACT_REVIEW_PENDING',result.stdout)
                else: self.assertIn('PASS copied HOST validator import closure',result.stdout)
                after = {str(p.relative_to(directory)):prep.digest(p) for p in directory.rglob('*') if p.is_file()}
                self.assertEqual(after,before,'Isolated validation must not create bytecode or alter copied evidence')

    def test_shared_import_dependency_cannot_overwrite_changed_parent_source(self):
        parent = self.parent('host')
        original_digest = prep.digest
        dependency = 'tools/host/prepare.py'
        parent_hash = prep.read_json(parent/'report.json')['source']['files'][dependency]
        def changed(path):
            return '0'*64 if Path(path)==ROOT/dependency else original_digest(path)
        destination = self.directory/'changed-parent-import'
        with patch.object(prep,'digest',side_effect=changed), self.assertRaisesRegex(ValueError,'parent import dependency'):
            self.prepare(parent,destination,'host-jtag-ew-ila')
        self.assertFalse(destination.exists())
        self.assertEqual(original_digest(parent/'source'/dependency),parent_hash)


if __name__=='__main__': unittest.main()
