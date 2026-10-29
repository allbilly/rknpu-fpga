"""Offline source-bound CH1 image-template controls; no Vivado or hardware."""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.ddr import image_template as renderer
from tools.hardware.sample_ew import tcl_literal

ROOT=Path(__file__).resolve().parents[3]
HELPER_SOURCES={
    'reset_status':ROOT/'fpga/ddr/reset_status_cdc.tcl',
    'board_reset':ROOT/'fpga/ddr/reset_bridge_board_cdc.tcl',
    'job_crossing':ROOT/'fpga/ddr/async_job_cdc.tcl',
    'memory_crossing':ROOT/'fpga/ddr/async_mem_cdc.tcl',
    'mailbox_ui':ROOT/'fpga/ddr/mailbox_ui_cdc.tcl',
}
PROPERTIES=set(renderer.PORT_PROPERTIES)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def synthetic_ports():
    names=['SYS_CLK','led_3bits_tri_o[0]','port with spaces','port[7]','$literal_port']
    names.extend(f'board_io_{i}' for i in range(242-len(names)))
    assert len(names)==242 and len(set(names))==242
    return {name:{'PACKAGE_PIN':f'PIN{i%10}', 'IOSTANDARD':'LVCMOS18', 'SLEW':'SLOW',
                  'DRIVE':'12', 'PULLTYPE':'NONE', 'DIFF_TERM':'FALSE', 'IN_TERM':'NONE',
                  'DIRECTION':'IN' if i%2==0 else 'OUT'} for i,name in enumerate(names)}


class ImageTemplateTests(unittest.TestCase):
    def make_bound_inputs(self, directory):
        directory=Path(directory)
        # Non-vendor fixture DCP bytes: only the renderer/hash guard is under
        # test. The five helper files are byte copies of the selected live helpers.
        dcp=directory/'qualified checkpoint [C1] $literal.dcp'
        dcp.write_bytes(b'mock source-bound DCP bytes, not opened or qualified')
        helper_dir=directory/'helper files [with space] $literal'
        helper_dir.mkdir(parents=True)
        helpers={}
        for name,source in HELPER_SOURCES.items():
            target=helper_dir/f'{name} [{name}] $helper.tcl'
            shutil.copyfile(source,target)
            assert sha(target)==sha(source)
            helpers[name]=target
        inputs={str(dcp.resolve()):sha(dcp)}
        inputs.update({str(path.resolve()):sha(path) for path in helpers.values()})
        output=directory/'output directory [literal] $out'
        return dcp,helpers,inputs,output

    def render_valid(self,directory,*,ports=None,source_tag='c1a2b3d4'):
        dcp,helpers,inputs,output=self.make_bound_inputs(directory)
        text=renderer.render(dcp,output,inputs,helpers,synthetic_ports() if ports is None else ports,source_tag)
        return text,dcp,helpers,inputs,output

    def test_positive_render_binds_five_helpers_checkpoint_exact242_ports_and_safe_tcl_literals(self):
        with tempfile.TemporaryDirectory(prefix='ddr image [template] $positive ') as tmp:
            text,dcp,helpers,inputs,output=self.render_valid(tmp)
            self.assertIn('set dcp '+tcl_literal(dcp.resolve()),text)
            self.assertIn('set out '+tcl_literal(output.resolve()),text)
            self.assertIn(tcl_literal('port with spaces'),text)
            self.assertIn(tcl_literal('port[7]'),text)
            self.assertIn(tcl_literal('$literal_port'),text)
            source_lines=[x for x in text.splitlines() if x.startswith('source ')]
            self.assertEqual(source_lines,['source '+tcl_literal(helpers[n].resolve()) for n in renderer.HELPERS])
            self.assertEqual(set(inputs),{str(dcp.resolve()),*(str(x.resolve()) for x in helpers.values())})
            self.assertTrue(all(re.fullmatch(r'[0-9a-f]{64}',v) for v in inputs.values()))
            self.assertIn('set expected_inputs [dict create ',text)
            self.assertEqual(len(re.findall(r'^write_bitstream\b',text,re.M)),1)
            self.assertEqual(len(re.findall(r'^set_property BITSTREAM\.CONFIG\.USR_ACCESS 0xc1a2b3d4 \[current_design\]$',text,re.M)),1)
            self.assertEqual(len(re.findall(r'^set_property BITSTREAM\.CONFIG\.',text,re.M)),1)
            for forbidden in (r'\bcreate_clock\b',r'\bset_false_path\b',r'\bset_clock_groups\b',
                              r'\bset_msg_config\b',r'\bprogram_hw\w*\b',r'\bopen_hw\w*\b',r'\bwrite_cfgmem\b'):
                self.assertIsNone(re.search(forbidden,text,re.I),forbidden)
            self.assertEqual(text.count('@'),0,'Template markers remain')

    def test_rejects_bad_missing_or_unbound_hash_inputs_and_helper_sets(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,helpers,inputs,output=self.make_bound_inputs(tmp)
            ports=synthetic_ports();tag='c1a2b3d4'
            with self.assertRaisesRegex(ValueError,'Nonempty exact qualified input hashes'):
                renderer.render('checkpoint',output,{},helpers,ports,tag)
            for bad in ('0'*63,'g'*64,'A'*64):
                with self.subTest(bad_hash=bad),self.assertRaisesRegex(ValueError,'Nonempty exact qualified input hashes'):
                    renderer.render('checkpoint',output,{'checkpoint':bad},helpers,ports,tag)
            missing_dcp=dict(inputs);missing_dcp.pop(str(next(Path(tmp).glob('*.dcp')).resolve()))
            with self.assertRaisesRegex(ValueError,'Checkpoint and all helpers must be hash-bound'):
                renderer.render('checkpoint',output,missing_dcp,helpers,ports,tag)
            missing_helper=dict(inputs);missing_helper.pop(str(helpers['board_reset'].resolve()))
            with self.assertRaisesRegex(ValueError,'Checkpoint and all helpers must be hash-bound'):
                renderer.render('checkpoint',output,missing_helper,helpers,ports,tag)
            fewer=dict(helpers);fewer.pop('mailbox_ui')
            with self.assertRaisesRegex(ValueError,'All five reviewed constraint helpers required'):
                renderer.render('checkpoint',output,inputs,fewer,ports,tag)
            more=dict(helpers);more['unreviewed']=helpers['mailbox_ui']
            with self.assertRaisesRegex(ValueError,'All five reviewed constraint helpers required'):
                renderer.render('checkpoint',output,inputs,more,ports,tag)

    def test_rejects_bad_source_tag_and_incomplete_or_changed_io_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dcp,helpers,inputs,output=self.make_bound_inputs(tmp);ports=synthetic_ports()
            for tag in ('00000000','0000000','zzzzzzzz','C1A2B3D4'):
                with self.subTest(tag=tag),self.assertRaisesRegex(ValueError,'Nonzero source-derived image tag required'):
                    renderer.render(dcp,output,inputs,helpers,ports,tag)
            fewer=dict(ports);fewer.pop(next(iter(fewer)))
            with self.assertRaisesRegex(ValueError,'Exact242-port property snapshot required'):
                renderer.render(dcp,output,inputs,helpers,fewer,'c1a2b3d4')
            missing_prop={k:dict(v) for k,v in ports.items()};missing_prop['SYS_CLK'].pop('PACKAGE_PIN')
            with self.assertRaisesRegex(ValueError,'Exact242-port property snapshot required'):
                renderer.render(dcp,output,inputs,helpers,missing_prop,'c1a2b3d4')
            extra_prop={k:dict(v) for k,v in ports.items()};extra_prop['SYS_CLK']['INIT']='0'
            with self.assertRaisesRegex(ValueError,'Exact242-port property snapshot required'):
                renderer.render(dcp,output,inputs,helpers,extra_prop,'c1a2b3d4')

    @unittest.skipUnless(shutil.which('tclsh') and shutil.which('sha256sum'),'Tcl/SHA256 utilities required')
    def run_hash_guard(self,mode):
        with tempfile.TemporaryDirectory(prefix='ddr hash [guard] $case ') as tmp:
            text,dcp,helpers,inputs,output=self.render_valid(tmp)
            script=Path(tmp)/'rendered emission [safe] $literal.tcl';script.write_text(text)
            if mode=='tamper':
                helper=helpers['board_reset'];helper.write_bytes(helper.read_bytes()+b'\n# changed after render\n')
                expected_error='Changed qualified DDR image input'
            else:
                dcp.unlink();expected_error='Missing qualified DDR image input'
            runner=Path(tmp)/'guard.tcl'
            runner.write_text('''set opened 0
set written 0
proc open_checkpoint {args} {incr ::opened; puts "OPEN_CHECKPOINT $args"}
proc write_bitstream {args} {incr ::written; puts "WRITE_BITSTREAM $args"}
if {[catch {source '''+tcl_literal(script)+'''} message]} {
  puts "EXPECTED_REJECTION $message"
} else {puts UNEXPECTED_SOURCE_SUCCESS}
puts "OPENED=$opened WRITTEN=$written"
''')
            result=subprocess.run([shutil.which('tclsh'),str(runner)],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('EXPECTED_REJECTION '+expected_error,result.stdout)
            self.assertIn('OPENED=0 WRITTEN=0',result.stdout)
            self.assertNotIn('OPEN_CHECKPOINT',result.stdout)
            self.assertNotIn('WRITE_BITSTREAM',result.stdout)
            self.assertNotIn('UNEXPECTED_SOURCE_SUCCESS',result.stdout)

    def test_tcl_hash_guard_rejects_tampered_bound_helper_before_design_or_bitstream(self):
        self.run_hash_guard('tamper')

    def test_tcl_hash_guard_rejects_missing_bound_checkpoint_before_design_or_bitstream(self):
        self.run_hash_guard('missing')

    @unittest.skipUnless(shutil.which('tclsh') and shutil.which('sha256sum'),'Tcl/SHA256 utilities required')
    def test_relative_hash_bound_inputs_resolve_when_sourced_from_another_working_directory(self):
        with tempfile.TemporaryDirectory(prefix='ddr relative [render] $caller ') as tmp:
            root=Path(tmp);caller=root/'caller';caller.mkdir()
            other=root/'different cwd';other.mkdir()
            dcp,helpers,_,output=self.make_bound_inputs(caller)
            relative_dcp=dcp.relative_to(caller)
            relative_helpers={name:path.relative_to(caller) for name,path in helpers.items()}
            relative_inputs={str(path.relative_to(caller)):sha(path) for path in [dcp,*helpers.values()]}
            old_cwd=Path.cwd()
            try:
                os.chdir(caller)
                text=renderer.render(relative_dcp,output.relative_to(caller),relative_inputs,
                                     relative_helpers,synthetic_ports(),'c1a2b3d4')
            finally:
                os.chdir(old_cwd)
            script=root/'rendered from relative inputs.tcl';script.write_text(text)
            runner=root/'stub open checkpoint.tcl'
            runner.write_text('''set opened 0
set written 0
proc open_checkpoint {args} {incr ::opened; error SENTINEL}
proc write_bitstream {args} {incr ::written}
if {[catch {source '''+tcl_literal(script)+'''} message]} {puts "STOP=$message"}
puts "OPENED=$opened WRITTEN=$written"
''')
            result=subprocess.run([shutil.which('tclsh'),str(runner)],cwd=other,
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('STOP=SENTINEL',result.stdout)
            self.assertIn('OPENED=1 WRITTEN=0',result.stdout)

    @unittest.skipUnless(shutil.which('tclsh') and shutil.which('sha256sum'),'Tcl/SHA256 utilities required')
    def test_relative_input_tamper_still_fails_before_design_access_and_conflicting_alias_hashes_reject(self):
        with tempfile.TemporaryDirectory(prefix='ddr relative [tamper] $cwd ') as tmp:
            root=Path(tmp);caller=root/'caller';caller.mkdir()
            other=root/'another cwd';other.mkdir()
            dcp,helpers,_,output=self.make_bound_inputs(caller)
            relative_dcp=dcp.relative_to(caller)
            relative_helpers={name:path.relative_to(caller) for name,path in helpers.items()}
            relative_inputs={str(path.relative_to(caller)):sha(path) for path in [dcp,*helpers.values()]}
            old_cwd=Path.cwd()
            try:
                os.chdir(caller)
                with self.assertRaisesRegex(ValueError,'Conflicting qualified hashes for one image input'):
                    aliased=dict(relative_inputs)
                    first=relative_dcp
                    aliased[str(first.resolve())]='0'*64
                    renderer.render(relative_dcp,output.relative_to(caller),aliased,
                                    relative_helpers,synthetic_ports(),'c1a2b3d4')
                text=renderer.render(relative_dcp,output.relative_to(caller),relative_inputs,
                                     relative_helpers,synthetic_ports(),'c1a2b3d4')
            finally:
                os.chdir(old_cwd)
            script=root/'relative tamper guard.tcl';script.write_text(text)
            helpers['board_reset'].write_bytes(helpers['board_reset'].read_bytes()+b'\n# tampered\n')
            runner=root/'tamper runner.tcl'
            runner.write_text('''set opened 0
set written 0
proc open_checkpoint {args} {incr ::opened; puts OPEN_CHECKPOINT}
proc write_bitstream {args} {incr ::written; puts WRITE_BITSTREAM}
if {[catch {source '''+tcl_literal(script)+'''} message]} {puts "REJECTED=$message"}
puts "OPENED=$opened WRITTEN=$written"
''')
            result=subprocess.run([shutil.which('tclsh'),str(runner)],cwd=other,
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('REJECTED=Changed qualified DDR image input',result.stdout)
            self.assertIn('OPENED=0 WRITTEN=0',result.stdout)
            self.assertNotIn('OPEN_CHECKPOINT',result.stdout)
            self.assertNotIn('WRITE_BITSTREAM',result.stdout)


if __name__=='__main__':
    unittest.main()
