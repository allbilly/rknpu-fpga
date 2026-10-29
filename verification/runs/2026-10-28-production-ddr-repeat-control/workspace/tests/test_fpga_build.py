"""Test the real build Tcl's control flow with mocked Vivado commands.

No HDL elaboration, physical constraints, DRC, timing or bitstream is evaluated.
Only explicit mock values and command ordering are checked. Full Vivado is still
required for implementation, even when every test in this file passes.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
proc event {name args} { puts [list EVENT $name {*}$args] }
foreach command {create_project read_verilog read_xdc synth_design write_checkpoint
                 report_utilization opt_design place_design phys_opt_design route_design
                 report_timing_summary write_bitstream} {
    interp alias {} $command {} event $command
}
proc current_design {} { return ypcb_top }
proc set_property {name value object} {
    dict set ::properties $name $value
    event set_property $name $value $object
}
proc mock {name default} {
    if {[info exists ::env($name)]} { return $::env($name) }
    return $default
}
proc check_timing {args} {
    event check_timing {*}$args
    if {[lsearch -exact $args -return_string] < 0} { return }
    if {[lsearch -exact $args -file] >= 0} { error "-return_string and -file cannot be combined" }
    set check [lindex $args [expr {[lsearch -exact $args -override_defaults] + 1}]]
    if {$check ni {no_clock unconstrained_internal_endpoints}} { error "Unexpected timing check $check" }
    if {[info exists ::env(MOCK_TIMING_REPORT)]} { return $::env(MOCK_TIMING_REPORT) }
    set count [mock MOCK_[string toupper $check] 0]
    set subject "register/latch pins with no clock."
    if {$check eq "unconstrained_internal_endpoints"} {
        set subject "pins that are not constrained for maximum delay."
    }
    return "1. checking $check\n-----------------------------------\nThere are $count $subject\n"
}
proc get_cells {args} {
    event get_cells {*}$args
    if {[mock MOCK_NO_BRAM 0]} { return {} }
    return ram
}
proc get_timing_paths {args} {
    set kind [lindex $args [expr {[lsearch -exact $args -delay_type] + 1}]]
    event get_timing_paths {*}$args
    if {[mock MOCK_EMPTY_[string toupper $kind] 0]} { return {} }
    return path_$kind
}
proc get_property {name object} {
    if {$name eq "SLACK" && $object in {path_max path_min}} {
        set kind [string toupper [string range $object 5 end]]
        return [mock MOCK_SLACK_$kind 0.100]
    }
    if {$name eq "SEVERITY" && $object eq "violation"} {
        return [mock MOCK_DRC_SEVERITY Error]
    }
    error "Unexpected property query: $name $object"
}
proc report_drc {args} {
    event report_drc {*}$args
    # Empty if no electrical values were supplied; never invent board facts.
    event drc_properties $::properties
}
proc get_drc_violations {args} {
    if {![info exists ::env(MOCK_DRC_SEVERITY)]} { return {} }
    if {[llength $args] == 0} { return violation }
    # Model the original Error-only filter too, so regressions that restore it
    # cannot silently claim Critical Warning coverage with this mock.
    if {$args eq {-filter {SEVERITY == Error}}} {
        if {$::env(MOCK_DRC_SEVERITY) eq "Error"} { return violation }
        return {}
    }
    error "Unexpected DRC query arguments: $args"
}
set ::properties {}
if {[catch {source $::env(RK_TEST_BUILD_SCRIPT)} detail]} {
    puts stderr $detail
    exit 1
}
puts "PASS mocked build control flow; NOT Vivado implementation"
exit 0
'''


class BuildControlFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tclsh = shutil.which(os.environ.get('RK_TEST_TCLSH', 'tclsh'))
        if cls.tclsh is None:
            raise RuntimeError('UNAVAILABLE: tclsh is required for build-script control-flow tests')
        version = subprocess.run([cls.tclsh], input='puts [info patchlevel]\n',
                                 text=True, capture_output=True, check=True).stdout.strip()
        print(f'Tcl control-flow tests: Tcl {version}; Vivado commands are mocked', flush=True)

    def run_build(self, settings=None, *, confirm=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('RK_', 'MOCK_'))}
        if confirm:
            env['RK_CONFIRM_BOARD'] = 'YPCB_00338_1P1'
        env.update(settings or {})
        with tempfile.TemporaryDirectory(prefix='rk-build-control-') as directory:
            # The actual script computes its output relative to its own path.
            # Copy it to a private tree so even its mkdir cannot touch a real run.
            script = Path(directory) / 'fpga/build.tcl'
            script.parent.mkdir()
            shutil.copyfile(ROOT / 'fpga/build.tcl', script)
            env['RK_TEST_BUILD_SCRIPT'] = str(script)
            result = subprocess.run([self.tclsh], input=HARNESS, env=env, cwd=directory,
                                    text=True, capture_output=True, timeout=10, check=False)
            self.assertFalse(list(Path(directory).rglob('*.bit')), 'Mocks must not write a bitstream')
        return result

    def assert_blocked(self, settings, message, *, before_project=False, confirm=True):
        result = self.run_build(settings, confirm=confirm)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertNotIn('EVENT write_bitstream', result.stdout)
        if before_project:
            self.assertNotIn('EVENT create_project', result.stdout)

    def test_board_confirmation_required(self):
        self.assert_blocked({}, 'RK_CONFIRM_BOARD', before_project=True, confirm=False)
        self.assert_blocked({'RK_CONFIRM_BOARD': 'another_board'}, 'RK_CONFIRM_BOARD', before_project=True)

    def test_default_stops_without_bitstream_or_guessed_voltage(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('EVENT route_design', result.stdout)
        self.assertIn('EVENT report_drc', result.stdout)
        self.assertIn('EVENT drc_properties {}', result.stdout)
        self.assertNotIn('EVENT write_bitstream', result.stdout)
        self.assertNotIn('EVENT set_property', result.stdout)

    def test_boolean_settings_are_strict(self):
        for key in ('RK_LED_ACTIVE_LOW', 'RK_EMIT_BITSTREAM'):
            for value in ('', 'yes', '2', '-1'):
                with self.subTest(key=key, value=value):
                    self.assert_blocked({key: value}, key + ' must be 0 or 1', before_project=True)
        result = self.run_build({'RK_LED_ACTIVE_LOW': '1', 'RK_EMIT_BITSTREAM': '0'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('LED_ACTIVE_LOW=1', result.stdout)
        self.assertNotIn('EVENT write_bitstream', result.stdout)

    def test_electrical_settings_must_be_complete_even_without_emission(self):
        for settings in ({'RK_EMIT_BITSTREAM': '1'}, {'RK_CONFIG_VOLTAGE': '1.8'}, {'RK_CFGBVS': 'GND'}):
            with self.subTest(settings=settings):
                self.assert_blocked(settings, 'Supply both board-verified', before_project=True)

    def test_invalid_and_incompatible_electrical_settings(self):
        for voltage, strap, message in (
                ('0', 'GND', 'Invalid RK_CONFIG_VOLTAGE'),
                ('1.8', 'AUTO', 'RK_CFGBVS must be'),
                ('1.5', 'VCCO', 'Incompatible'), ('1.8', 'VCCO', 'Incompatible'),
                ('2.5', 'GND', 'Incompatible'), ('3.3', 'GND', 'Incompatible')):
            with self.subTest(voltage=voltage, strap=strap):
                self.assert_blocked({'RK_CONFIG_VOLTAGE': voltage, 'RK_CFGBVS': strap},
                                    message, before_project=True)

    def test_all_legal_pairs_apply_before_checkpoint_and_drc(self):
        for voltage, strap in (('1.5', 'GND'), ('1.8', 'GND'), ('2.5', 'VCCO'), ('3.3', 'VCCO')):
            with self.subTest(voltage=voltage, strap=strap):
                result = self.run_build({'RK_EMIT_BITSTREAM': '1', 'RK_CONFIG_VOLTAGE': voltage,
                                         'RK_CFGBVS': strap})
                self.assertEqual(result.returncode, 0, result.stderr)
                events = result.stdout
                for assignment in (f'EVENT set_property CONFIG_VOLTAGE {voltage}',
                                   f'EVENT set_property CFGBVS {strap}'):
                    self.assertLess(events.index(assignment), events.index('EVENT write_checkpoint'))
                    self.assertLess(events.index(assignment), events.index('EVENT report_drc'))
                self.assertIn(f'EVENT drc_properties {{CONFIG_VOLTAGE {voltage} CFGBVS {strap}}}', events)
                self.assertLess(events.index('EVENT report_drc'), events.index('EVENT write_bitstream'))
                self.assertEqual(events.count('EVENT write_bitstream'), 1)

    def test_configured_non_emitting_build_still_uses_electrical_settings(self):
        result = self.run_build({'RK_CONFIG_VOLTAGE': '1.8', 'RK_CFGBVS': 'GND'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('EVENT drc_properties {CONFIG_VOLTAGE 1.8 CFGBVS GND}', result.stdout)
        self.assertNotIn('EVENT write_bitstream', result.stdout)

    def test_block_ram_is_required(self):
        self.assert_blocked({'MOCK_NO_BRAM': '1'}, 'No block RAM inferred')

    def test_timing_paths_must_exist_and_slack_must_be_finite_nonnegative(self):
        for kind in ('MAX', 'MIN'):
            with self.subTest(kind=kind, check='missing'):
                self.assert_blocked({f'MOCK_EMPTY_{kind}': '1'}, f'No {kind.lower()} timing paths')
            for value in ('-0.001', '-2'):
                with self.subTest(kind=kind, value=value):
                    self.assert_blocked({f'MOCK_SLACK_{kind}': value}, f'Negative {kind.lower()} slack')
            for value in ('', 'N/A', 'NaN', 'Inf', '-Inf', '1e9999', 'garbage'):
                with self.subTest(kind=kind, value=value):
                    self.assert_blocked({f'MOCK_SLACK_{kind}': value}, f'Invalid {kind.lower()} slack')
            for value in ('0', '0.001', '1e-3'):
                with self.subTest(kind=kind, value=value):
                    result = self.run_build({f'MOCK_SLACK_{kind}': value})
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocking_or_unknown_drc_severity_never_emits(self):
        for severity in ('Error', 'Critical Warning', 'Fatal', '', 'unrecognized'):
            with self.subTest(severity=severity):
                self.assert_blocked({'RK_EMIT_BITSTREAM': '1', 'RK_CONFIG_VOLTAGE': '1.8',
                                     'RK_CFGBVS': 'GND', 'MOCK_DRC_SEVERITY': severity},
                                    'Blocking DRC violation')
        for severity in ('Warning', 'Advisory', 'Info'):
            with self.subTest(severity=severity):
                result = self.run_build({'MOCK_DRC_SEVERITY': severity})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_internal_timing_gaps_block_emission_with_positive_slack(self):
        settings = {'RK_EMIT_BITSTREAM': '1', 'RK_CONFIG_VOLTAGE': '1.8', 'RK_CFGBVS': 'GND'}
        for check in ('no_clock', 'unconstrained_internal_endpoints'):
            with self.subTest(check=check):
                self.assert_blocked(settings | {'MOCK_' + check.upper(): '17'},
                                    f'Unresolved {check} timing findings')
        result = self.run_build(settings)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('EVENT write_bitstream', result.stdout)
        self.assertNotIn('-override_defaults no_input_delay', result.stdout)
        self.assertNotIn('-override_defaults no_output_delay', result.stdout)

    def test_missing_or_unknown_internal_timing_reports_fail_closed(self):
        for report in ('', 'unknown tool report', 'Checking no_clock.\n',
                       'Checking no_clock.\nThere are N/A pins with no clock.',
                       'Checking no_clock.\nThere are -1 pins with no clock.'):
            with self.subTest(report=report):
                result = self.run_build({'MOCK_TIMING_REPORT': report})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('no_clock timing', result.stderr)
                self.assertNotIn('EVENT write_bitstream', result.stdout)


if __name__ == '__main__':
    unittest.main()
