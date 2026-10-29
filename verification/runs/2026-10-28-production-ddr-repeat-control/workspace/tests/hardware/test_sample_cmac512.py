"""Synthetic full512 observer controls only; no hardware or numerical proof."""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.hardware import sample_cmac512 as observer
from tools.hardware import sample_ew


class SampleCMAC512Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='cmac observer control ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bsdl = self.root/'device.bsd'
        text = ('entity XC7K480T_FFG1156 is\n'
                'attribute INSTRUCTION_LENGTH of XC7K480T_FFG1156 : entity is 6;\n'
                'attribute BOUNDARY_LENGTH of XC7K480T_FFG1156 : entity is 1395;\n'
                'attribute INSTRUCTION_CAPTURE of XC7K480T_FFG1156 : entity is "XXXX01";\n'
                '"IDCODE (001001),"\n"SAMPLE (000001),"\n"BYPASS (111111)"\n')
        for pin in observer.PINS.values():
            text += '"IO_'+pin['pin']+':'+pin['pin']+',"\n'
            text += f'"{pin["disable_cell"]} (BC_2, *, controlr, 1),"\n'
            text += f'"{pin["output_cell"]} (BC_2, IO_{pin["pin"]}, output3, X, {pin["disable_cell"]}, 1, Z),"\n'
            text += f'"{pin["input_cell"]} (BC_2, IO_{pin["pin"]}, input, X),"\n'
        self.bsdl.write_text(text)
        self.bit = self.root/'fixture.bit'
        self.bit.write_bytes(b'SYNTHETIC_NOT_A_PROGRAMMABLE_BITSTREAM')
        self.source = self.root/'prepared/report.json'
        self.source.parent.mkdir()
        selected, files = {}, {}
        for name in [f'rtl/fixture_{i}.sv' for i in range(31)]+['tests/cmac/array_data/board_rom.hex']:
            path = self.source.parent/'source'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic source-binding fixture '+name+'\n')
            files[name] = observer.digest(path)
            if name.startswith('rtl/'):
                selected[name] = files[name]
        manifest = ''.join(h+'  '+n+'\n' for n, h in sorted(files.items()))
        # Only this in-memory expected identity is replaced for a small portable
        # fixture. Production code and the real full512 source constant remain
        # unchanged; these tests cannot supply an admitted FPGA image.
        source_sha = hashlib.sha256(manifest.encode()).hexdigest()
        expected = patch.object(observer, 'SOURCE_SHA', source_sha)
        expected.start()
        self.addCleanup(expected.stop)
        self.source.write_text(json.dumps(dict(status='PREPARED_REGISTERED_BRAM_FULL512_PIPELINE_SOURCE_ONLY',
            top='ypcb_cmac_array_regmem_top', part=observer.PART, channels=32, kernels=16,
            parallel_products=512, pipeline_stages=2, clock_period_ns=20,
            source=dict(files=files, sha256=source_sha), hardware_inputs=selected,
            synthesis_sources=list(selected))))
        self.target = 'localhost:3125/xilinx_tcf/Xilinx/SYNTHETIC'
        self.out = self.root/'capture output'
        self.plan = observer.prepare(self.bit, self.source, self.bsdl, self.out, self.target, 'localhost:3125')
        self.plan_path = self.out/'plan.json'
        self.epoch = 1800000000000000
        self.load = self.root/'synthetic-load.json'
        self.load.write_text(json.dumps(dict(status='PASS', action='program-sram', hardware_programmed=True,
            flash_written=False, bitstream_sha256=observer.digest(self.bit), idcode='0x23751093', target=self.target,
            source_report_sha256=observer.digest(self.source), source_sha256=observer.SOURCE_SHA,
            profile=observer.PROFILE, compiled_led_active_low=0,
            finished_utc=datetime.fromtimestamp((self.epoch-1000000)/1e6, timezone.utc).isoformat())))

    def capture(self,healthy=True,heartbeat=True):
        rows=[]
        for index in range(101):
            value=0
            if healthy:value|=1<<852;value|=1<<853
            else:value|=1<<851;value|=1<<845;value|=1<<848
            if heartbeat and (index//10)%2:value|=1<<849;value|=1<<850
            rows.append(f'CMACSAMPLE1|ROW|{index}|{self.epoch+index*50000}|{index*50000}|'+
                        ('31' if healthy else '01')+f'|{value:0349x}')
        text='\n'.join(['CMACSAMPLE1|BINDING|'+self.plan['binding_sha256'],
            'CMACSAMPLE1|TOOL|'+b'2026.1-SYNTHETIC'.hex(),
            'CMACSAMPLE1|TARGET|'+self.target.encode().hex(),'CMACSAMPLE1|TCK|3000000',
            'CMACSAMPLE1|IDCODE|23751093',*rows,
            *['CMACSAMPLE1|CLEANUP|'+name+'|1' for name in ['BYPASS','TARGET','SERVER','MANAGER']],
            'CMACSAMPLE1|END|101|1'])+'\n'
        path=self.out/'synthetic.tsv';path.write_text(text);return path

    def test_prepare_binds_rom_and_remains_preparation_only(self):
        self.assertFalse(self.plan['hardware_accessed'])
        self.assertFalse(self.plan['image_admission'])
        self.assertIn('tests/cmac/array_data/board_rom.hex',
                      self.plan['binding']['source_report']['binding']['hardware_inputs']['files'])
        text = (self.out/'capture.tcl').read_text()
        self.assertNotIn('program_hw_devices', text)
        self.assertNotIn('EXTEST', text)
        self.assertIn('CMACSAMPLE1', text)
        with self.assertRaises(ValueError):
            observer.prepare(self.bit, self.source, self.bsdl, self.out, self.target, 'localhost:3125')

    def test_positive_has_exact_profile_and_no_direct_memory_claim(self):
        result = observer.decode(self.plan_path, self.capture(), 'post-load', self.load)
        self.assertEqual(result['status'], 'PASS_OBSERVED_FULL512_STARTUP_SCOREBOARD_OUTPUTS')
        self.assertEqual(result['profile'], observer.PROFILE)
        self.assertEqual(result['heartbeat_transitions'], 10)
        self.assertTrue(result['application_outputs_observed'])
        self.assertFalse(result['direct_memory_readback'])
        self.assertFalse(result['optical_led_polarity_verified'])
        self.assertFalse(result['programming_performed'])

    def test_baseline_excluded_and_cross_profile_decoders_reject(self):
        result = observer.decode(self.plan_path, self.capture(False, False), 'baseline')
        self.assertEqual(result['status'], 'CAPTURED_BASELINE_APPLICATION_UNKNOWN')
        self.assertFalse(result['application_outputs_observed'])
        with self.assertRaises(ValueError):
            sample_ew.decode(self.plan_path, self.capture(), 'post-load', self.load)
        changed = copy.deepcopy(self.plan)
        changed['status'] = 'PREPARED_SAMPLE_OBSERVER_ONLY'
        self.plan_path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            observer.decode(self.plan_path, self.capture(), 'post-load', self.load)

    def test_load_receipt_profile_source_and_exact_identity_reject(self):
        original = observer.load_json(self.load)
        for field, value in [('profile', 'EW'), ('profile', None), ('source_sha256', '0'*64),
                             ('source_report_sha256', None), ('bitstream_sha256', '0'*64),
                             ('idcode', '0x03751093'), ('target', self.target+'other'),
                             ('status', 'FAIL'), ('action', 'program-flash'), ('flash_written', True)]:
            changed = dict(original)
            if value is None:
                del changed[field]
            else:
                changed[field] = value
            self.load.write_text(json.dumps(changed))
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                observer.decode(self.plan_path, self.capture(), 'post-load', self.load)

    def test_compiled_generic_and_stale_or_naive_load_times_reject(self):
        original = observer.load_json(self.load)
        for value in [1, False, True, 0.0, '0', None]:
            changed = dict(original)
            if value is None:
                del changed['compiled_led_active_low']
            else:
                changed['compiled_led_active_low'] = value
            self.load.write_text(json.dumps(changed))
            with self.subTest(value=value), self.assertRaises(ValueError):
                observer.decode(self.plan_path, self.capture(), 'post-load', self.load)
        for value in ['2027-01-15T08:00:00', datetime.fromtimestamp((self.epoch+1000000)/1e6, timezone.utc).isoformat()]:
            changed = dict(original, finished_utc=value)
            self.load.write_text(json.dumps(changed))
            with self.subTest(value=value), self.assertRaises(ValueError):
                observer.decode(self.plan_path, self.capture(), 'post-load', self.load)

    def test_rom_helper_tcl_and_source_tampering_reject(self):
        paths = [self.out/'source/hardware/tests/cmac/array_data/board_rom.hex',
                 self.out/'source/hardware/rtl/fixture_0.sv', self.out/'source/sample_ew.py',
                 self.out/'source/sample_cmac512.py', self.out/'capture.tcl', self.out/'source/source-report.json']
        for path in paths:
            original = path.read_bytes()
            path.write_bytes(original+b'\n')
            try:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    observer.decode(self.plan_path, self.capture(), 'post-load', self.load)
            finally:
                path.write_bytes(original)

    def test_reduced_target_wrong_top_clock_and_manifest_reject(self):
        original = observer.load_json(self.source)
        for field, value in [('channels', 8), ('kernels', 1), ('parallel_products', 32),
                             ('pipeline_stages', 1), ('clock_period_ns', 40),
                             ('top', 'ypcb_ew_startup_top'), ('status', 'PREPARED_EW_CHECKPOINT_ONLY')]:
            self.source.write_text(json.dumps(dict(original, **{field: value})))
            with self.subTest(field=field), self.assertRaises(ValueError):
                observer.source_contract(self.source)
        self.source.write_text(json.dumps(original))
        path = self.source.parent/'source/tests/cmac/array_data/board_rom.hex'
        path.write_bytes(path.read_bytes()+b'\n')
        with self.assertRaises(ValueError):
            observer.source_contract(self.source)

    def test_capture_failure_unknown_prefix_padding_and_heartbeat_reject(self):
        with self.assertRaises(ValueError):
            observer.decode(self.plan_path, self.capture(True, False), 'post-load', self.load)
        original = self.capture().read_text()
        mutations = [('CMACSAMPLE1|END|101|1', 'CMACSAMPLE1|END|100|1'),
                     ('CMACSAMPLE1|CLEANUP|BYPASS|1', 'CMACSAMPLE1|CLEANUP|BYPASS|0'),
                     ('CMACSAMPLE1|IDCODE|23751093', 'CMACSAMPLE1|IDCODE|03751093'),
                     ('CMACSAMPLE1|', 'EWSAMPLE1|')]
        for old, new in mutations:
            path = self.out/'bad.tsv'
            path.write_text(original.replace(old, new))
            with self.subTest(old=old), self.assertRaises(ValueError):
                observer.decode(self.plan_path, path, 'post-load', self.load)
        lines = original.splitlines()
        index = next(i for i, row in enumerate(lines) if '|ROW|' in row)
        for bit in [851, 846, 1395]:
            changed = list(lines)
            fields = changed[index].split('|')
            fields[-1] = f'{int(fields[-1],16)|(1<<bit):0349x}'
            changed[index] = '|'.join(fields)
            path = self.out/'bad.tsv'
            path.write_text('\n'.join(changed)+'\n')
            with self.subTest(bit=bit), self.assertRaises(ValueError):
                observer.decode(self.plan_path, path, 'post-load', self.load)

    def test_prepare_target_tck_generic_and_duration_reject(self):
        for keyword, value in [('target', self.target+'\n'), ('tck_hz', 6000000),
                               ('led_active_low', True), ('samples', 10), ('interval_ms', 1)]:
            options = dict(target=self.target, server='localhost:3125')
            options[keyword] = value
            with self.subTest(keyword=keyword), self.assertRaises(ValueError):
                observer.prepare(self.bit, self.source, self.bsdl, self.root/'invalid output', **options)

    @unittest.skipUnless(shutil.which('tclsh'),'Plain Tcl is needed for mocked Tcl control')
    def test_candidate_tcl_only_uses_whitelisted_ir_and_safe_cleanup(self):
        raw_values=[]
        for row in observer.parse_capture(self.capture(),self.plan)['samples']:raw_values.append(row['boundary_hex'])
        script=self.root/'mock.tcl'
        prefix='''set ::now 0
set ::row 0
set ::selected 0
rename clock real_clock
proc clock {kind args} {if {$kind eq "clicks"} {return $::now}; if {$kind eq "microseconds"} {return [expr {1800000000000000+$::now}]}; return [real_clock $kind {*}$args]}
proc after {milliseconds} {incr ::now [expr {$milliseconds*1000}]}
proc open_hw_manager {} {}
proc connect_hw_server {args} {}
proc get_hw_targets {} {return [list $::target]}
proc current_hw_target {args} {return $::target}
proc set_property {args} {}
proc open_hw_target {args} {}
proc get_hw_devices {} {return xc7k480t_0}
proc get_property {name object} {if {$name eq "PART"} {return xc7k480t}; return 3000000}
proc close_hw_target {} {}
proc disconnect_hw_server {} {}
proc close_hw_manager {} {}
proc run_state_hw_jtag {state} {if {$state ni {RESET IDLE}} {error "Unsafe TAP state"}}
proc version {args} {return 2026.1-MOCK}
proc scan_ir_hw_jtag {bits args} {set value [lindex $args 1]; if {$bits!=6 || $value ni {09 01 3f}} {error "Unsafe IR"};set ::selected $value;return 31}
proc scan_dr_hw_jtag {bits args} {if {[lindex $args 1] ne "0"} {error "Unexpected TDI"}; if {$bits==32 && $::selected eq "09"} {return 23751093}; if {$bits!=1395 || $::selected ne "01"} {error "Unsafe DR"};set value [lindex $::values $::row];incr ::row;return $value}
'''
        prefix+='set ::target '+observer.tcl_literal(self.target)+'\n'
        prefix+='set ::values [list '+' '.join(raw_values)+']\n'
        prefix+='source '+observer.tcl_literal(self.out/'capture.tcl')+'\n'
        script.write_text(prefix)
        result=subprocess.run([shutil.which('tclsh'),str(script)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stderr,'','Tcl startup/control diagnostics are not a passing test')
        self.assertEqual(len(observer.parse_capture(self.out/'capture.tsv',self.plan)['samples']),101)


if __name__ == '__main__':
    unittest.main()
