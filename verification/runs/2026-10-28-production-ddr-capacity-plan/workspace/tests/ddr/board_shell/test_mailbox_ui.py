"""Portable mock controls for the DDR USER2 mailbox C0-UI CDC constraints.

These Tcl mocks test command scope and rejection behavior only. They do not
model Vivado timing, a board, or mailbox behavior.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.hardware.sample_ew import tcl_literal

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / 'fpga/ddr/mailbox_ui_cdc.tcl'

MOCK = r'''
set scenario __SCENARIO__
set changes {}
set report_args {}
set ::created_tck 0
proc parse_clock_arg {args} { return [lindex $args end] }
proc get_clocks {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        set obj [lindex $args end]
        set rq_clock_pin [format {PIN:u_mailbox/rq_sync_reg[%d]/C} 0]
        if {$obj eq $rq_clock_pin} {
            return [list [expr {$::scenario eq "wrong_rq_clock" ? "CLOCK:sys_clock" : "CLOCK:c0_ui_clk"}]]
        }
        if {$obj eq "PIN:bscan_user2/TCK"} {
            if {$::scenario eq "existing_jtag_tck" || $::created_tck} {return [list CLOCK:jtag_tck]}
            return {}
        }
        return {}
    }
    set name [parse_clock_arg {*}$args]
    if {[llength $name] != 1} {error "clock names must be singleton"}
    if {$name eq "c0_ui_clk"} {
        if {$::scenario eq "missing_ui_clock"} {return {}}
        if {$::scenario eq "multiple_ui_clock"} {return {CLOCK:c0_ui_clk CLOCK:duplicate_ui}}
        return [list CLOCK:c0_ui_clk]
    }
    if {$name eq "sys_clock"} {return [list CLOCK:sys_clock]}
    if {$name eq "jtag_tck"} {
        if {$::scenario eq "existing_jtag_tck" || $::created_tck} {return [list CLOCK:jtag_tck]}
        return {}
    }
    return {}
}
proc get_property {key object} {
    if {$key eq "PERIOD"} {
        if {![string match "CLOCK:*" $object]} {error "PERIOD requires typed clock object, got $object"}
        set name [string range $object 6 end]
        if {$name eq "c0_ui_clk"} {return 7.5}
        if {$name eq "sys_clock"} {return 20.0}
        if {$name eq "jtag_tck"} {return 166.666}
        if {$name eq "duplicate_ui"} {return 7.5}
        error "Unknown clock token $object"
    }
    if {$key eq "JTAG_CHAIN"} {return [expr {$::scenario eq "wrong_chain" ? 1 : 2}]}
    if {$key eq "IS_PRIMITIVE"} {return [expr {$::scenario eq "primitive_mailbox"}]}
    error "Unexpected property $key on $object"
}
proc get_cells {args} {
    set joined [join $args " "]
    if {[string match {*REF_NAME == BSCANE2*} $joined]} {
        if {$::scenario eq "missing_bscan"} {return {}}
        if {$::scenario eq "multiple_bscan"} {return {bscan_user2 bscan_extra}}
        return {bscan_user2}
    }
    if {[string match {*NAME =~ u_mailbox/*} $joined]} {
        set filter [lindex $args end]
        if {![regexp {NAME =~ u_mailbox/([^*]+)\*} $filter -> stem]} {error "Bad cell filter $filter"}
        if {$stem eq "held_reg"} {
            if {$::scenario eq "missing_held_payload"} {return {}}
            return {u_mailbox/held_reg[0] u_mailbox/held_reg[1]}
        }
        if {$stem eq "req_reg"} {return {u_mailbox/req_reg[0] u_mailbox/req_reg[1]}}
        if {$stem eq "response_reg"} {
            if {$::scenario eq "missing_response_payload"} {return {}}
            return {u_mailbox/response_reg[0] u_mailbox/response_reg[1]}
        }
        if {$stem eq "response_tck_reg"} {
            if {$::scenario eq "missing_response_payload"} {return {}}
            return {u_mailbox/response_tck_reg[0] u_mailbox/response_tck_reg[1]}
        }
        if {$stem in {rq_sync_reg rs_sync_reg}} {
            set n [expr {$::scenario eq "sync_depth" && $stem eq "rq_sync_reg" ? 2 : 3}]
            set cells {}
            for {set i 0} {$i<$n} {incr i} {lappend cells [format {u_mailbox/%s[%d]} $stem $i]}
            return $cells
        }
    }
    set namearg [lindex $args end]
    set name [lindex $namearg 0]
    if {[llength $namearg] != 1} {return {}}
    if {$name eq "u_mailbox"} {
        if {$::scenario eq "missing_mailbox"} {return {}}
        if {$::scenario eq "duplicate_mailbox"} {return {u_mailbox u_mailbox_duplicate}}
        return {u_mailbox}
    }
    set rq0 [format {u_mailbox/rq_sync_reg[%d]} 0]
    if {$name eq $rq0} {
        if {$::scenario eq "missing_rq_first"} {return {}}
        return [list $rq0]
    }
    return $name
}
proc get_pins {name} {
    regsub {^\{(.*)\}/(.*)$} $name {\1/\2} name
    return "PIN:$name"
}
proc create_clock {args} {
    if {$::scenario eq "clock_creation_error"} {error "clock creation rejected"}
    lappend ::changes [linsert $args 0 CREATE_CLOCK]
    set ::created_tck 1
}
proc set_max_delay {args} {lappend ::changes [linsert $args 0 MAX]}
proc set_bus_skew {args} {lappend ::changes [linsert $args 0 SKEW]}
proc set_false_path {args} {lappend ::changes [linsert $args 0 FALSE]}
proc set_property {key value cells} {
    if {$key ni {ASYNC_REG DONT_TOUCH} || $value ne "TRUE" || [llength $cells]!=3} {error "Unreviewed property change"}
    lappend ::changes [list PROPERTY $key $value $cells]
}
proc report_bus_skew {args} {set ::report_args $args;lappend ::changes [linsert $args 0 REPORT_BUS_SKEW]}
'''


@unittest.skipUnless(shutil.which('tclsh'), 'Tcl interpreter required')
class MailboxUiConstraintTests(unittest.TestCase):
    def invoke(self, scenario, body):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mailbox-ui-mock.tcl'
            mock = MOCK.replace('__SCENARIO__', tcl_literal(scenario))
            script = mock + '\nsource ' + tcl_literal(HELPER) + '\n' + body + '\n'
            path.write_text(script)
            return subprocess.run([shutil.which('tclsh'), str(path)], capture_output=True,
                                  text=True, timeout=15)

    @staticmethod
    def exact_false_path_scope(rows):
        """Accept only two payload hold cuts and two synchronizer first-D cuts."""
        false = [line for line in rows if line.startswith('FALSE ')]
        hold = [line for line in false if line.startswith('FALSE -hold ')]
        first_d = [line for line in false if line.startswith('FALSE -to ')]
        if len(false) != 4 or len(hold) != 2 or len(first_d) != 2:
            return False
        if not all(' -from ' in line and ' -to ' in line for line in hold):
            return False
        if not any('held_reg' in line and 'req_reg' in line for line in hold):
            return False
        if not any('response_reg' in line and 'response_tck_reg' in line for line in hold):
            return False
        return {line for line in first_d} == {
            'FALSE -to {PIN:u_mailbox/rq_sync_reg[0]/D}',
            'FALSE -to {PIN:u_mailbox/rs_sync_reg[0]/D}',
        }

    def test_c0_ui_constraints_use_typed_clocks_exact_budgets_and_first_stage_cuts(self):
        body = r'''
rk_ddr_host_cdc_constrain c0_ui_clk
foreach item $changes {puts $item}
puts PASS_MOCK_MAILBOX_UI_CONSTRAINTS
'''
        result = self.invoke('good', body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = result.stdout.splitlines()
        self.assertIn('PASS_MOCK_MAILBOX_UI_CONSTRAINTS', rows)
        creates = [line for line in rows if line.startswith('CREATE_CLOCK ')]
        self.assertEqual(len(creates), 1)
        self.assertIn('-name jtag_tck -period 166.666 PIN:bscan_user2/TCK', creates[0])
        max_rows = [line for line in rows if line.startswith('MAX ')]
        skew_rows = [line for line in rows if line.startswith('SKEW ')]
        self.assertEqual(len(max_rows), 2)
        self.assertEqual(len(skew_rows), 2)
        self.assertTrue(any('-datapath_only 15.000' in line and 'held_reg' in line and 'req_reg' in line for line in max_rows))
        self.assertTrue(any('-datapath_only 333.332' in line and 'response_reg' in line and 'response_tck_reg' in line for line in max_rows))
        self.assertTrue(any(line.startswith('SKEW 15.000 ') and 'held_reg' in line and 'req_reg' in line for line in skew_rows))
        self.assertTrue(any(line.startswith('SKEW 333.332 ') and 'response_reg' in line and 'response_tck_reg' in line for line in skew_rows))
        hold = [line for line in rows if line.startswith('FALSE -hold ')]
        first_d = [line for line in rows if line.startswith('FALSE -to ')]
        self.assertEqual(len(hold), 2)
        self.assertEqual(len(first_d), 2)
        self.assertEqual(len([line for line in rows if line.startswith('FALSE ')]), 4)
        self.assertTrue(any('rq_sync_reg[0]/D' in line for line in first_d))
        self.assertTrue(any('rs_sync_reg[0]/D' in line for line in first_d))
        self.assertFalse(any('rq_sync_reg[1]/D' in line or 'rq_sync_reg[2]/D' in line or
                             'rs_sync_reg[1]/D' in line or 'rs_sync_reg[2]/D' in line for line in rows if line.startswith('FALSE')))
        self.assertTrue(self.exact_false_path_scope(rows), rows)
        props = [line for line in rows if line.startswith('PROPERTY ')]
        self.assertEqual(len(props), 4)
        for prefix in ('rq_sync_reg', 'rs_sync_reg'):
            for prop in ('ASYNC_REG', 'DONT_TOUCH'):
                self.assertTrue(any(line.startswith(f'PROPERTY {prop} TRUE') and prefix in line for line in props))
        self.assertTrue(all('CLOCK:' not in line for line in rows if line.startswith(('MAX ', 'SKEW ', 'FALSE '))))

    def test_mock_mutation_with_extra_from_only_cut_is_rejected(self):
        result = self.invoke('extra_from_only', r'''
rk_ddr_host_cdc_constrain c0_ui_clk
if {$scenario eq "extra_from_only"} {set_false_path -from [get_pins u_mailbox/unreviewed_source_reg/C]}
foreach item $changes {puts $item}
puts PASS_MOCK_MAILBOX_UI_CONSTRAINTS
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = result.stdout.splitlines()
        self.assertIn('FALSE -from PIN:u_mailbox/unreviewed_source_reg/C', rows)
        self.assertFalse(self.exact_false_path_scope(rows))
        self.assertIn('PASS_MOCK_MAILBOX_UI_CONSTRAINTS', rows)

    def test_sys20_missing_multiple_nonuser2_wrong_ui_and_existing_tck_rejected(self):
        cases = (
            ('good', 'sys_clock', 'Wrong sys_clock clock period'),
            ('missing_ui_clock', 'c0_ui_clk', 'Expected exactly one c0_ui_clk.'),
            ('multiple_ui_clock', 'c0_ui_clk', 'Expected exactly one c0_ui_clk.'),
            ('missing_bscan', 'c0_ui_clk', 'Expected exactly one USER2.'),
            ('multiple_bscan', 'c0_ui_clk', 'Expected exactly one USER2.'),
            ('wrong_chain', 'c0_ui_clk', 'Expected USER2 JTAG_CHAIN=2.'),
            ('wrong_rq_clock', 'c0_ui_clk', 'Mailbox is not in selected C0 UI domain.'),
            ('existing_jtag_tck', 'c0_ui_clk', 'Fresh JTAG clock constraint required.'),
            ('missing_held_payload', 'c0_ui_clk', 'Missing held mailbox payload: held/req'),
            ('missing_response_payload', 'c0_ui_clk', 'Missing held mailbox payload: response/response_tck'),
            ('sync_depth', 'c0_ui_clk', 'Missing mailbox toggle synchronizer.'),
            ('missing_rq_first', 'c0_ui_clk', 'Expected exactly one first UI mailbox stage.'),
        )
        for scenario, clock, message in cases:
            with self.subTest(scenario=scenario):
                result = self.invoke(scenario,
                    'rk_ddr_host_cdc_constrain '+tcl_literal(clock)+'\nputs PASS_MOCK_MAILBOX_UI_CONSTRAINTS')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stderr)
                self.assertNotIn('PASS_MOCK_MAILBOX_UI_CONSTRAINTS', result.stdout)
                self.assertNotIn('CREATE_CLOCK -name jtag_tck', result.stdout)

    def test_skew_report_is_scoped_to_hierarchical_mailbox_and_rejects_bad_scope(self):
        result = self.invoke('good', r'''
rk_ddr_host_report_skew reports
puts $report_args
puts PASS_MOCK_MAILBOX_UI_SKEW_SCOPE
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('-cells u_mailbox', result.stdout)
        self.assertIn('-warn_on_violation', result.stdout)
        self.assertIn('reports/mailbox_bus_skew.rpt', result.stdout)
        self.assertIn('PASS_MOCK_MAILBOX_UI_SKEW_SCOPE', result.stdout)
        for scenario, message in (
            ('missing_mailbox', 'Expected exactly one UI mailbox hierarchy.'),
            ('duplicate_mailbox', 'Expected exactly one UI mailbox hierarchy.'),
            ('primitive_mailbox', 'Expected hierarchical UI mailbox.'),
        ):
            with self.subTest(scenario=scenario):
                result = self.invoke(scenario, 'rk_ddr_host_report_skew reports\nputs PASS_MOCK_MAILBOX_UI_SKEW_SCOPE')
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(message, result.stderr)
                self.assertNotIn('PASS_MOCK_MAILBOX_UI_SKEW_SCOPE', result.stdout)
                self.assertNotIn('REPORT_BUS_SKEW', result.stdout)


if __name__ == '__main__':
    unittest.main()
