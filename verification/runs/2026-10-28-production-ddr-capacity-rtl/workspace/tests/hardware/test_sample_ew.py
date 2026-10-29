"""Synthetic SAMPLE/BSDL/Tcl controls. No hardware access or physical result."""
import copy
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.hardware import sample_ew as observer


class SampleEWTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='sample ew ')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.bsdl=self.root/'device.bsd'
        text='entity XC7K480T_FFG1156 is\n'
        text+='attribute INSTRUCTION_LENGTH of XC7K480T_FFG1156 : entity is 6;\n'
        text+='attribute BOUNDARY_LENGTH of XC7K480T_FFG1156 : entity is 1395;\n'
        text+='attribute INSTRUCTION_CAPTURE of XC7K480T_FFG1156 : entity is "XXXX01";\n'
        text+='"IDCODE (001001),"\n"SAMPLE (000001),"\n"BYPASS (111111)"\n'
        for pin in observer.PINS.values():
            text+='"IO_'+pin['pin']+':'+pin['pin']+',"\n'
            text+=f'"{pin["disable_cell"]} (BC_2, *, controlr, 1),"\n'
            text+=f'"{pin["output_cell"]} (BC_2, IO_{pin["pin"]}, output3, X, {pin["disable_cell"]}, 1, Z),"\n'
            text+=f'"{pin["input_cell"]} (BC_2, IO_{pin["pin"]}, input, X),"\n'
        self.bsdl.write_text(text)
        self.bit=self.root/'fixture.bit';self.bit.write_bytes(b'SYNTHETIC_NOT_A_PROGRAMMABLE_BITSTREAM')
        self.source=self.root/'prepared/report.json';self.source.parent.mkdir()
        files={}
        for name in ['fpga/ypcb_ew_startup_top.sv','fpga/ypcb_ew_startup.xdc','rtl/rk_ew_dma_demo.sv',
                     'rtl/rk_dma_demo_rom.sv','rtl/rk_demo_memory.sv','rtl/rk_startup_reset.sv','rtl/rk_ew_dma.sv',
                     'rtl/rk_ew_engine.sv','rtl/rk_ew_regs.sv','rtl/rk_fp16_alu.sv','rtl/rk_bram.sv']:
            path=self.source.parent/'source'/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('// synthetic source-binding fixture '+name+'\n');files[name]=observer.digest(path)
        self.source.write_text(json.dumps(dict(schema=1,profile='startup',status='PREPARED_EW_CHECKPOINT_ONLY',
            part=observer.PART,clock_hz=50000000,hardware_inputs=dict(files=files,sha256='1'*64),
            production_revision=dict(sha256='2'*64))))
        self.target='localhost:3125/xilinx_tcf/Xilinx/fixture'
        self.out=self.root/'capture output'
        self.plan=observer.prepare(self.bit,self.source,self.bsdl,self.out,self.target,'localhost:3125')
        self.plan_path=self.out/'plan.json'
        self.load=self.root/'load.json'
        self.epoch=1800000000000000
        self.load.write_text(json.dumps(dict(status='PASS',action='program-sram',hardware_programmed=True,
            flash_written=False,bitstream_sha256=observer.digest(self.bit),idcode='0x23751093',target=self.target,
            source_report_sha256=observer.digest(self.source),compiled_led_active_low=0,
            finished_utc=datetime.fromtimestamp((self.epoch-1000000)/1e6,timezone.utc).isoformat())))

    def capture(self,healthy=True,heartbeat=True):
        rows=[]
        for index in range(101):
            value=0
            if healthy:value|=1<<852;value|=1<<853
            else:value|=1<<851;value|=1<<845;value|=1<<848
            if heartbeat and (index//10)%2:value|=1<<849;value|=1<<850
            rows.append(f'EWSAMPLE1|ROW|{index}|{self.epoch+index*50000}|{index*50000}|'+
                        ('31' if healthy else '01')+f'|{value:0349x}')
        text='\n'.join(['EWSAMPLE1|BINDING|'+self.plan['binding_sha256'],
            'EWSAMPLE1|TOOL|'+b'2026.1-SYNTHETIC'.hex(),
            'EWSAMPLE1|TARGET|'+self.target.encode().hex(),'EWSAMPLE1|TCK|3000000',
            'EWSAMPLE1|IDCODE|23751093',*rows,
            *['EWSAMPLE1|CLEANUP|'+name+'|1' for name in ['BYPASS','TARGET','SERVER','MANAGER']],
            'EWSAMPLE1|END|101|1'])+'\n'
        path=self.out/'synthetic.tsv';path.write_text(text);return path

    def test_exact_bsdl_semantics_and_our_different_pin_roles(self):
        self.assertEqual(observer.bsdl_contract(self.bsdl)['pins']['pass_flag']['output_cell'],852)
        original=self.bsdl.read_text()
        for old,new in [('1395','1396'),('SAMPLE (000001)','SAMPLE (100110)'),('852 (BC_2','851 (BC_2'),('XXXX01','XXXX11')]:
            self.bsdl.write_text(original.replace(old,new))
            with self.subTest(old=old),self.assertRaises(ValueError):observer.bsdl_contract(self.bsdl)
        self.bsdl.write_text(original)

    def test_prepare_has_no_hardware_execution_and_binds_real_inputs(self):
        self.assertFalse(self.plan['hardware_accessed']);self.assertFalse(self.plan['programming_performed'])
        self.assertEqual(self.plan['binding']['bitstream']['sha256'],observer.digest(self.bit))
        text=(self.out/'capture.tcl').read_text()
        self.assertNotIn('program_hw_devices',text);self.assertNotIn('-tdi 26',text)
        self.assertIn('scan_dr_hw_jtag 1395 -tdi 0',text)
        with self.assertRaises(ValueError):observer.prepare(self.bit,self.source,self.bsdl,self.out,self.target,'localhost:3125')

    def test_baseline_makes_no_candidate_application_claim(self):
        result=observer.decode(self.plan_path,self.capture(False,False),'baseline')
        self.assertEqual(result['status'],'CAPTURED_BASELINE_APPLICATION_UNKNOWN')
        self.assertFalse(result['application_outputs_observed'])
        with self.assertRaises(ValueError):observer.decode(self.plan_path,self.capture(False,False),'post-load',self.load)

    def test_good_synthetic_receipt_matches_pins_load_and_heartbeat(self):
        result=observer.decode(self.plan_path,self.capture(),'post-load',self.load)
        self.assertTrue(result['application_outputs_observed']);self.assertFalse(result['decoder_hardware_accessed'])
        self.assertEqual(result['heartbeat_transitions'],10)
        self.assertEqual(result['samples'][0]['outputs'],dict(pass_flag=1,fail_flag=0,heartbeat=0))
        self.assertFalse(result['optical_led_polarity_verified']);self.assertFalse(result['direct_memory_readback'])

    def test_bad_count_padding_cleanup_and_stale_load_reject(self):
        original=self.capture().read_text()
        for old,new in [('EWSAMPLE1|END|101|1','EWSAMPLE1|END|100|1'),('EWSAMPLE1|CLEANUP|BYPASS|1','EWSAMPLE1|CLEANUP|BYPASS|0'),
                        ('EWSAMPLE1|IDCODE|23751093','EWSAMPLE1|IDCODE|03751093')]:
            path=self.out/'bad.tsv';path.write_text(original.replace(old,new))
            with self.subTest(old=old),self.assertRaises(ValueError):observer.decode(self.plan_path,path,'post-load',self.load)
        path=self.out/'padding.tsv';lines=original.splitlines();index=next(i for i,s in enumerate(lines) if '|ROW|' in s)
        fields=lines[index].split('|');fields[-1]='8'+fields[-1][1:];lines[index]='|'.join(fields);path.write_text('\n'.join(lines)+'\n')
        with self.assertRaises(ValueError):observer.decode(self.plan_path,path,'post-load',self.load)
        receipt=observer.load_json(self.load);receipt['finished_utc']=datetime.fromtimestamp((self.epoch+1000000)/1e6,timezone.utc).isoformat();self.load.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):observer.decode(self.plan_path,self.capture(),'post-load',self.load)

    def test_disabled_output_fail_signal_and_no_heartbeat_reject(self):
        with self.assertRaises(ValueError):observer.decode(self.plan_path,self.capture(True,False),'post-load',self.load)
        original=self.capture().read_text();lines=original.splitlines();index=next(i for i,s in enumerate(lines) if '|ROW|' in s)
        for bit in [851,846]:
            changed=list(lines);fields=changed[index].split('|');fields[-1]=f'{int(fields[-1],16)|(1<<bit):0349x}';changed[index]='|'.join(fields)
            path=self.out/'pin-bad.tsv';path.write_text('\n'.join(changed)+'\n')
            with self.subTest(bit=bit),self.assertRaises(ValueError):observer.decode(self.plan_path,path,'post-load',self.load)

    def test_source_and_load_bindings_are_not_silently_replaced(self):
        receipt=observer.load_json(self.load);receipt['bitstream_sha256']='0'*64;self.load.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):observer.decode(self.plan_path,self.capture(),'post-load',self.load)
        source=self.out/'source/hardware/rtl/rk_ew_dma_demo.sv';source.write_text(source.read_text()+'\n')
        with self.assertRaises(ValueError):observer.decode(self.plan_path,self.capture(),'baseline')

    def test_load_receipt_requires_matching_preparation_report(self):
        original=observer.load_json(self.load)
        for value in ['0'*64,None]:
            receipt=copy.deepcopy(original)
            if value is None:del receipt['source_report_sha256']
            else:receipt['source_report_sha256']=value
            self.load.write_text(json.dumps(receipt))
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Load receipt source report differs'):
                observer.decode(self.plan_path,self.capture(),'post-load',self.load)

    def test_load_receipt_requires_exact_compiled_polarity_and_rejects_inverted_failure(self):
        original=observer.load_json(self.load)
        for value in [1,False,True,0.0,'0',None]:
            receipt=copy.deepcopy(original)
            if value is None:del receipt['compiled_led_active_low']
            else:receipt['compiled_led_active_low']=value
            self.load.write_text(json.dumps(receipt))
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'Load receipt compiled LED polarity differs'):
                observer.decode(self.plan_path,self.capture(),'post-load',self.load)
        self.load.write_text(json.dumps(original))
        self.plan['binding']['led_active_low']=1
        self.plan['binding_sha256']=hashlib.sha256(observer.canonical(self.plan['binding'])).hexdigest()
        self.plan_path.write_text(json.dumps(self.plan))
        capture=self.capture();lines=capture.read_text().splitlines()
        for index,line in enumerate(lines):
            fields=line.split('|')
            if fields[1]=='ROW':
                # Compiled noninverted failure: PASS=0, FAIL=1. A false LOW=1
                # declaration would interpret these outputs as success.
                value=int(fields[-1],16)^(1<<852)^(1<<846)
                fields[-1]=f'{value:0349x}';lines[index]='|'.join(fields)
        capture.write_text('\n'.join(lines)+'\n')
        with self.assertRaisesRegex(ValueError,'Load receipt compiled LED polarity differs'):
            observer.decode(self.plan_path,capture,'post-load',self.load)

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


if __name__=='__main__':unittest.main()
