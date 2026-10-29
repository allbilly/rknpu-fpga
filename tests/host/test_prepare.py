"""Host shell preparation/CDC controls. Vivado calls are mocked, never launched."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from tools.host import prepare as prep
from test_fpga_build import HARNESS


CDC_MOCKS = r'''
proc get_parts {args} {return xc7k480tffg1156-2}
proc get_pins {args} {return [lindex $args end]}
proc create_clock {args} {event create_clock {*}$args}
proc get_clocks {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        set pin [lindex $args end]
        if {[string match *u_bscan/TCK $pin] || [string match *rs_sync* $pin]} {return jtag_tck}
        return sys_clk
    }
    return [lindex $args end]
}
rename get_cells base_get_cells
proc get_cells {args} {
    if {[lsearch -exact $args -filter]>=0} {
        set filter [lindex $args end]
        if {$filter eq "REF_NAME == BSCANE2"} {
            if {[mock MOCK_NO_BSCAN 0]} {return {}}
            return u_bscan
        }
        if {[string match *RAMB* $filter]} {return [base_get_cells {*}$args]}
        if {[regexp {NAME =~ u_mailbox/(.*)_reg\*} $filter -> prefix]} {
            if {$prefix in {rq_sync rs_sync}} {
                set count [mock MOCK_SYNC_DEPTH 3];set result {}
                for {set i 0} {$i<$count} {incr i} {lappend result [format {u_mailbox/%s_reg[%d]} $prefix $i]}
                return $result
            }
            if {[mock MOCK_NO_PAYLOAD 0]} {return {}}
            return [list [format {u_mailbox/%s_reg[0]} $prefix] [format {u_mailbox/%s_reg[1]} $prefix]]
        }
        error "Unexpected cell filter $filter"
    }
    return [lindex $args end]
}
rename get_property base_get_property
proc get_property {name object} {
    if {$name eq "JTAG_CHAIN"} {return [mock MOCK_CHAIN 2]}
    if {$name in {ASYNC_REG DONT_TOUCH}} {return [mock MOCK_SYNC_PROPERTY 1]}
    if {$name eq "PERIOD"} {
        if {$object eq "jtag_tck"} {return [mock MOCK_TCK_PERIOD 166.666]}
        return [mock MOCK_SYS_PERIOD 20.000]
    }
    if {$name eq "SLACK" && ![string match path_* $object]} {return [mock MOCK_CDC_SLACK 0.100]}
    if {$name eq "REQUIREMENT"} {
        if {[mock MOCK_WRONG_BOUND 0]} {return 999}
        if {$object eq "payload_held"} {return 40.000}
        if {$object eq "payload_response"} {return [mock MOCK_RESPONSE_BOUND 333.332]}
        if {[string match *rs_sync* $object]} {return [mock MOCK_SYNC_REQUIRED 166.666]}
        return 20.000
    }
    return [base_get_property $name $object]
}
rename get_timing_paths base_get_timing_paths
proc get_timing_paths {args} {
    set index [lsearch -exact $args -from]
    if {$index<0} {return [base_get_timing_paths {*}$args]}
    set source [lindex [lindex $args [expr {$index+1}]] 0]
    if {[string match *held_reg* $source] || [string match *response_reg* $source]} {
        if {[mock MOCK_CUT_PAYLOAD 0]} {return {}}
        if {[string match *held_reg* $source]} {return payload_held}
        return payload_response
    }
    if {[mock MOCK_CUT_LATER_STAGE 0]} {return {}}
    return sync_$source
}
proc all_fanin {args} {
    if {[mock MOCK_BAD_FANIN 0]} {return unexpected/C}
    set pin [lindex $args end]
    if {![regexp {u_mailbox/(rq_sync|rs_sync)_reg\[([0-2])\]/D} $pin -> prefix bit]} {error "Bad sync pin $pin"}
    if {$bit==0} {
        if {$prefix eq "rq_sync"} {return u_mailbox/req_toggle_reg/C}
        return u_mailbox/rsp_toggle_reg/C
    }
    return [format {u_mailbox/%s_reg[%d]/C} $prefix [expr {$bit-1}]]
}
foreach name {set_max_delay set_false_path set_bus_skew report_timing report_cdc
              report_exceptions report_route_status report_pulse_width} {
    interp alias {} $name {} event $name
}
proc report_bus_skew {args} {
    event report_bus_skew {*}$args
    set file [lindex $args [expr {[lsearch -exact $args -file]+1}]]
    set channel [open $file w]
    set count [mock MOCK_SKEW_COUNT 2]
    set status [mock MOCK_SKEW_STATUS MET]
    set slack [mock MOCK_SKEW_SLACK 1.000]
    for {set i 0} {$i<$count} {incr i} {
        set bound [expr {$i==0 ? 40.000 : [mock MOCK_RESPONSE_SKEW_BOUND 333.332]}]
        if {[mock MOCK_SKEW_BOUND 0]} {set bound 1000}
        if {![mock MOCK_SKEW_HEADER_MISSING 0]} {puts $channel "Requirement: ${bound}ns"}
        puts $channel "Slack ($status) : ${slack}ns  (requirement - actual skew)"
        set detail [expr {[mock MOCK_SKEW_DETAIL_CONFLICT 0] ? $bound+1 : $bound}]
        if {![mock MOCK_SKEW_DETAIL_MISSING 0]} {puts $channel "  Requirement: ${detail}ns"}
    }
    close $channel
}
'''


class HostPreparationTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'build').mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='host-preparation-control-', dir=ROOT/'build')
        self.addCleanup(self.temporary.cleanup); self.base = Path(self.temporary.name)
        # Admission is delegated to the native runner. These mock artifacts test
        # package copying/tamper boundaries, never numerical qualification.
        self.protocol_names = ['rtl/host/rk_jtag_backend.sv', 'rtl/host/rk_jtag_ew_bram.sv',
                               'rtl/vendor/opentpu/otpu_jtag_mailbox.sv']
        self.native = SimpleNamespace(source_revision=self.revision, verify_report=self.verify_mock)
        self.patch = patch.object(prep, 'qualification', return_value=self.native)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def revision(self, root=ROOT):
        return prep.manifest({name: prep.digest(root/name) for name in self.protocol_names})

    def verify_mock(self, path, source_root=ROOT, artifact_root=ROOT):
        report = prep.read_json(path)
        prep.require(report['status'] == 'MOCK_HOST_QUALIFIED_ONLY' and
                     report['source_revision'] == self.revision(source_root), 'Wrong mocked qualification')
        for name, sha in report['artifacts']['files'].items():
            prep.require(prep.digest(prep.checked_path(artifact_root, name)) == sha, 'Changed mocked artifact')
        return report

    def package(self, evidence=False):
        reports = {}
        if evidence:
            for simulator in ('verilator', 'iverilog'):
                artifact = self.base/'producer'/simulator/'sim';artifact.parent.mkdir(parents=True)
                artifact.write_text('MOCK BINARY; NEVER EXECUTE\n')
                report = dict(status='MOCK_HOST_QUALIFIED_ONLY', simulator=simulator, execution_root=str(ROOT),
                    source_revision=self.revision(), artifacts=prep.manifest({str(artifact.relative_to(ROOT)):prep.digest(artifact)}))
                path = self.base/(simulator+'.json');prep.write_json(path, report);reports[simulator]=path
        return prep.prepare(self.base/'package', reports)

    def complete_mock_review(self, directory):
        review = prep.read_json(directory/'board-review.json')
        review.update(reviewer='MOCK UNIT CONTROL ONLY', config_voltage='1.8', cfgbvs='GND', led_active_low=0,
            checks={key:True for key in prep.common.BOARD_CHECKS},
            evidence={key:'MOCK NOT BOARD FACTS' for key in prep.common.BOARD_CHECKS})
        prep.write_json(directory/'board-review.json', review)

    def test_preparation_is_file_only_and_unreviewed_command_is_rejected(self):
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('No tool execution')):
            directory = self.package();result = prep.verify(directory)
        self.assertEqual(result['status'], 'SOURCE_INTACT_REVIEW_PENDING')
        self.assertEqual(len(result['blockers']), 2)
        review = prep.read_json(directory/'board-review.json')
        self.assertTrue(all(value is False for value in review['checks'].values()))
        self.assertIsNone(review['config_voltage'])
        with self.assertRaisesRegex(ValueError, 'host endpoint simulator'): prep.command(directory)
        text = (directory/'build.tcl').read_text()
        self.assertIn('synth_design -top ypcb_jtag_ew_top ', text)
        self.assertIn('rk_host_cdc_constrain', text);self.assertIn('rk_host_cdc_audit $out', text)
        self.assertNotIn('write_bitstream', text);self.assertNotIn('set_clock_groups', text)
        self.assertNotRegex((directory/'source/fpga/host/ypcb_jtag_ew.xdc').read_text(), r'set_property\s+PACKAGE_PIN\s+R28')

    def test_bound_copy_survives_original_artifact_removal_but_not_tampering(self):
        directory = self.package(True)
        with self.assertRaisesRegex(ValueError, 'reviewer'): prep.command(directory)
        self.complete_mock_review(directory);shutil.rmtree(self.base/'producer')
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('No Vivado')):
            result = prep.command(directory)
        self.assertEqual(result['argv'][0], 'vivado');self.assertFalse(result['vivado_executed'])
        self.assertEqual(result['environment']['RK_EMIT_BITSTREAM'], '0')
        record = prep.read_json(directory/'evidence/verilator.json')
        path = directory/'artifacts'/next(iter(record['artifacts']['files']))
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'artifact'):prep.verify(directory)

    def test_foreign_workspace_reports_copy_and_verify_without_origin(self):
        with tempfile.TemporaryDirectory(prefix='host-foreign-producer-') as temporary:
            producer = Path(temporary) / 'workspace'
            reports = {}
            for simulator in ('verilator', 'iverilog'):
                name = f'build/host-jtag/{simulator}/sim'
                artifact = producer / name
                artifact.parent.mkdir(parents=True, exist_ok=True)
                artifact.write_text('MOCK FOREIGN EXECUTABLE; NEVER RUN\n')
                record = dict(status='MOCK_HOST_QUALIFIED_ONLY', simulator=simulator,
                    execution_root=str(producer), source_revision=self.revision(),
                    artifacts=prep.manifest({name: prep.digest(artifact)}))
                path = producer / f'{simulator}.json'
                prep.write_json(path, record)
                reports[simulator] = path
            directory = prep.prepare(self.base/'package', reports)
            shutil.rmtree(producer)
            self.complete_mock_review(directory)
            self.assertEqual(prep.command(directory)['status'], 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD')
            artifact = directory/'artifacts/build/host-jtag/verilator/sim'
            artifact.write_text('corrupt copied foreign artifact')
            with self.assertRaisesRegex(ValueError, 'artifact'):
                prep.verify(directory)

    def test_invalid_report_origin_fails_before_package_creation(self):
        for origin in (None, True, 'relative/workspace', '/tmp/../workspace'):
            with self.subTest(origin=origin):
                record = dict(status='MOCK_HOST_QUALIFIED_ONLY', simulator='verilator',
                              execution_root=origin, source_revision=self.revision())
                path = self.base/'invalid-origin.json'; prep.write_json(path, record)
                with self.assertRaisesRegex(ValueError, 'qualification execution_root'):
                    prep.prepare(self.base/'bad', {'verilator':path, 'iverilog':path})
                self.assertFalse((self.base/'bad').exists())

    def test_snapshot_tcl_and_physical_claim_tampering_are_rejected(self):
        directory = self.package();source = directory/'source/fpga/host/mailbox_cdc.tcl'
        saved = source.read_bytes();source.write_bytes(saved+b'\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'snapshot'):prep.verify(directory)
        source.write_bytes(saved)
        script = directory/'build.tcl';original = script.read_bytes();script.write_bytes(original+b'\n# changed\n')
        with self.assertRaisesRegex(ValueError, 'checkpoint Tcl'):prep.verify(directory)
        script.write_bytes(original)
        report = prep.read_json(directory/'report.json');report['vivado_executed']=True
        prep.write_json(directory/'report.json', report)
        with self.assertRaisesRegex(ValueError, 'physical qualification'):prep.verify(directory)

    def test_existing_package_and_stale_qualification_are_rejected(self):
        directory = self.package()
        with self.assertRaisesRegex(ValueError, 'fresh package'):prep.prepare(directory)
        old = self.base/'old.json';prep.write_json(old, {'status':'PASS_OLD_EW_OR_CMAC'})
        with self.assertRaisesRegex(ValueError, 'qualification'):
            prep.prepare(self.base/'bad', {'verilator':old, 'iverilog':old})
        self.assertFalse((self.base/'bad').exists())

    def run_tcl(self, directory, settings=None):
        tclsh = shutil.which('tclsh');self.assertIsNotNone(tclsh, 'UNAVAILABLE: tclsh')
        report = prep.read_json(directory/'report.json')
        env = {k:v for k,v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        env.update(RK_TEST_BUILD_SCRIPT=str(directory/'build.tcl'), RK_HOST_PREPARED_SHA=report['source']['sha256'],
                   RK_CONFIRM_BOARD=prep.BOARD, RK_CONFIG_VOLTAGE='1.8', RK_CFGBVS='GND', RK_LED_ACTIVE_LOW='0', RK_EMIT_BITSTREAM='0')
        env.update(settings or {})
        harness = HARNESS.replace('set ::properties {}', CDC_MOCKS+'\nset ::properties {}')
        return subprocess.run([tclsh], input=harness, env=env, text=True, capture_output=True, timeout=10)

    def test_mocked_checkpoint_preserves_bounded_cdc_and_physical_gates(self):
        directory = self.package();result = self.run_tcl(directory)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(result.stdout.count('EVENT set_max_delay -datapath_only '), 2)
        self.assertIn('EVENT set_max_delay -datapath_only 40.000 ', result.stdout)
        self.assertIn('EVENT set_max_delay -datapath_only 333.332 ', result.stdout)
        self.assertEqual(result.stdout.count('EVENT set_false_path -hold '), 2)
        self.assertEqual(result.stdout.count('EVENT set_false_path -to '), 2)
        self.assertIn('EVENT report_cdc -details', result.stdout)
        self.assertLess(result.stdout.index('EVENT synth_design'), result.stdout.index('EVENT set_max_delay'))
        self.assertLess(result.stdout.index('EVENT route_design'), result.stdout.index('EVENT report_cdc'))
        for settings in ({'MOCK_NO_BSCAN':'1'}, {'MOCK_CHAIN':'1'}, {'MOCK_TCK_PERIOD':'100'},
            {'MOCK_TCK_PERIOD':'166.667'}, {'MOCK_RESPONSE_BOUND':'333.333'},
            {'MOCK_SYNC_REQUIRED':'166.667'}, {'MOCK_RESPONSE_SKEW_BOUND':'333.333'},
            {'MOCK_SKEW_HEADER_MISSING':'1'}, {'MOCK_SKEW_DETAIL_MISSING':'1'},
            {'MOCK_SKEW_DETAIL_CONFLICT':'1'},
            {'MOCK_SYS_PERIOD':'25'}, {'MOCK_NO_PAYLOAD':'1'}, {'MOCK_SYNC_DEPTH':'2'},
            {'MOCK_SYNC_PROPERTY':'0'}, {'MOCK_BAD_FANIN':'1'}, {'MOCK_CUT_PAYLOAD':'1'},
            {'MOCK_CUT_LATER_STAGE':'1'}, {'MOCK_WRONG_BOUND':'1'}, {'MOCK_CDC_SLACK':'NaN'},
            {'MOCK_CDC_SLACK':'-0.1'}, {'MOCK_SKEW_COUNT':'1'}, {'MOCK_SKEW_STATUS':'VIOLATED'},
            {'MOCK_SKEW_SLACK':'NaN'}, {'MOCK_SKEW_BOUND':'1'}, {'MOCK_NO_CLOCK':'1'},
            {'MOCK_UNCONSTRAINED_INTERNAL_ENDPOINTS':'1'}, {'MOCK_SLACK_MIN':'-0.1'},
            {'MOCK_SLACK_MAX':'NaN'}, {'MOCK_DRC_SEVERITY':'Critical Warning'}, {'MOCK_NO_BRAM':'1'},
            {'RK_CFGBVS':'VCCO'}, {'RK_EMIT_BITSTREAM':'1'}):
            with self.subTest(settings=settings):
                result = self.run_tcl(directory, settings)
                self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertNotIn('EVENT write_bitstream', result.stdout)
        self.assertFalse(list(directory.rglob('*.dcp')));self.assertFalse(list(directory.rglob('*.bit')))

    def test_native_picosecond_quantization_strengthens_nominal_budgets(self):
        from fractions import Fraction
        spec = prep.specification()
        period = Fraction(str(spec['tck_period_ns']))
        nominal = Fraction(1000000000, 6000000)
        self.assertLessEqual(period, nominal)
        self.assertEqual((period*1000).denominator, 1)
        self.assertEqual(period, Fraction(166666, 1000))
        self.assertEqual(period*2, Fraction(333332, 1000))
        text = (ROOT/'fpga/host/mailbox_cdc.tcl').read_text()
        self.assertIn('response response_tck 333.332', text)
        self.assertNotIn('166.666667', text)
        self.assertNotIn('set_clock_groups', text)

    def test_physical_wrapper_startup_with_explicit_primitive_stubs(self):
        for tool in ('iverilog', 'vvp'):
            self.assertIsNotNone(shutil.which(tool), 'UNAVAILABLE: '+tool)
        bench = self.base/'shell.sv'
        bench.write_text('''`timescale 1ns/1ps
module IBUF(input wire I, output wire O); assign O=I; endmodule
module BUFG(input wire I, output wire O); assign O=I; endmodule
// Simulation stubs only: no TAP or physical primitive timing is modeled.
module BSCANE2 #(parameter integer JTAG_CHAIN=1) (
 output wire TCK,DRCK,CAPTURE,SHIFT,UPDATE,SEL,TDI,RESET,RUNTEST,TMS, input wire TDO);
 assign {TCK,DRCK,CAPTURE,SHIFT,UPDATE,SEL,TDI,RESET,RUNTEST,TMS}=10'b0;
 initial if(JTAG_CHAIN!=2) $fatal(1,"wrong USER chain");
endmodule
module tb_host_shell;
 reg clk=0; always #10 clk=~clk;
 wire [2:0] normal_led, inverted_led;
 ypcb_jtag_ew_top normal(.SYS_CLK(clk),.led_3bits_tri_o(normal_led));
 ypcb_jtag_ew_top #(.LED_ACTIVE_LOW(1)) inverted(.SYS_CLK(clk),.led_3bits_tri_o(inverted_led));
 initial begin
   for(integer edge_count=1;edge_count<=128;edge_count=edge_count+1) begin
     @(posedge clk); #1;
     if(normal.rst_n !== (edge_count>=65) || inverted.rst_n !== (edge_count>=65))
       $fatal(1,"wrong startup reset timing");
     if(normal_led!==3'b000 || inverted_led!==3'b111) $fatal(1,"wrong idle LEDs/polarity");
     if(normal.endpoint.core_start_valid || normal.endpoint.core_busy || normal.endpoint.mem_req_valid)
       $fatal(1,"host endpoint launched without a host command");
   end
   $display("PASS host shell startup and idle ownership with primitive stubs; no TAP/FPGA proof");
   $finish;
 end
 initial begin #10000; $fatal(1,"shell timeout"); end
endmodule
''')
        binary = self.base/'shell.vvp'
        sources = [str(ROOT/name) for name in prep.specification()['synthesis']]
        compile_result = subprocess.run(['iverilog', '-g2012', '-s', 'tb_host_shell', '-o', str(binary),
                                         *sources, str(bench)], text=True, capture_output=True, timeout=30)
        self.assertEqual(compile_result.returncode, 0, compile_result.stdout+compile_result.stderr)
        result = subprocess.run(['vvp', str(binary)], text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('PASS host shell startup and idle ownership with primitive stubs', result.stdout)


if __name__ == '__main__': unittest.main()
