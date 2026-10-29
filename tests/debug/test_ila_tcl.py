"""Optional ILA control tests with Tcl-only Vivado mocks, never implementation."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.debug.prepare import literal

TCL_STARTUP_PROBE = ('puts "VERSION=[info patchlevel]"\n'
                     'puts "AUTO_LOAD=[llength [info commands auto_load]]"\n'
                     'puts "SYNTH_DESIGN=[llength [info commands synth_design]]"\n')


def checked_tcl_version(executable):
    """A zero exit/patchlevel alone does not prove Tcl loaded its standard library."""
    try:
        result = subprocess.run([executable], input=TCL_STARTUP_PROBE, text=True,
                                capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('UNAVAILABLE: Tcl initialization probe failed: '+str(error)) from error
    if result.returncode != 0 or result.stderr:
        raise RuntimeError(f'UNAVAILABLE: Tcl startup diagnostics (exit {result.returncode}): {result.stderr}')
    lines = result.stdout.splitlines()
    if len(lines) != 3 or not lines[0].startswith('VERSION=') or not lines[0][8:].strip():
        raise RuntimeError('UNAVAILABLE: Tcl startup version is missing or malformed')
    if lines[1] != 'AUTO_LOAD=1':
        raise RuntimeError('UNAVAILABLE: Tcl standard library is not initialized')
    if lines[2] != 'SYNTH_DESIGN=0':
        raise RuntimeError('UNAVAILABLE: ordinary Tcl without the Vivado engine is required')
    return lines[0][8:].strip()


MOCKS = r'''
set ::cores {}; set ::ports {}; set ::props {}; set ::connections {}
set ::inserted 0; set ::routed 0; set ::mutations 0
proc mock {name default} {
    if {[info exists ::env($name)]} {return $::env($name)}
    return $default
}
proc current_design {} {return D@design}
proc event {name args} {puts [list EVENT $name {*}$args]}
proc get_property {property objects} {
    set property [string toupper $property];set values {}
    foreach object $objects {
        set name [lindex [split $object @] 1]
        if {$property eq "NAME"} {
            set value $name
            if {$object eq "D@design"} {set value [mock MOCK_TOP [dict get $::plan top]]}
        } elseif {$property eq "PART"} {set value [mock MOCK_PART xc7k480tffg1156-2]
        } elseif {$property eq "PERIOD"} {set value [mock MOCK_PERIOD 20.0]
        } elseif {$property eq "JTAG_CHAIN"} {
            set value [expr {$name eq "u_bscan" ? [mock MOCK_MAILBOX_CHAIN 2] : [mock MOCK_IMPL_CHAIN 1]}]
        } else {
            set key [list $object $property]
            if {![dict exists $::props $key]} {error "Unsupported mock property $property of $object"}
            set value [dict get $::props $key]
            if {$::routed} {
                if {$property eq "PORT_WIDTH" && [mock MOCK_CHANGED_WIDTH 0]} {incr value}
                if {$property eq "C_DATA_DEPTH" && [mock MOCK_CHANGED_DEPTH 0]} {set value 2048}
                if {$property eq "C_INPUT_PIPE_STAGES" && [mock MOCK_CHANGED_PIPE 0]} {set value 1}
                if {$property eq "C_USER_SCAN_CHAIN" && [mock MOCK_CHANGED_CHAIN 0]} {set value 2}
                if {$property eq "C_CLK_INPUT_FREQ_HZ" && [mock MOCK_CHANGED_FREQ 0]} {set value 100000000}
                if {$property eq "C_ENABLE_CLK_DIVIDER" && [mock MOCK_CHANGED_DIVIDER 0]} {set value true}
                if {$property eq "MARK_DEBUG" && [mock MOCK_LOST_MARK 0]} {set value false}
            }
        }
        lappend values $value
    }
    if {[llength $values]==1} {return [lindex $values 0]}
    return $values
}
proc get_ports {args} {
    if {[mock MOCK_MISSING_CLOCK_PORT 0]} {return {}}
    return [list P@SYS_CLK]
}
proc get_pins {args} {
    if {[mock MOCK_MISSING_ANCHOR 0]} {return {}}
    set filter [lindex $args end]
    if {![regexp {^NAME == "(.*)"$} $filter -> name] || $name ne [dict get $::plan clock anchor_pin]} {
        error "Unexpected anchor query: $args"
    }
    return [list A@$name]
}
proc get_clocks {args} {
    if {[mock MOCK_MISSING_CLOCK 0]} {return {}}
    if {[lsearch -exact $args -of_objects]>=0 && [mock MOCK_WRONG_CLOCK 0]} {return [list K@other_clock]}
    if {[mock MOCK_MULTIPLE_CLOCKS 0]} {return [list K@sys_clk K@other_clock]}
    return [list K@sys_clk]
}
proc get_nets {args} {
    if {[lsearch -exact $args -of_objects]>=0} {
        if {[lsearch -exact $args -segments]<0 || [lsearch -exact $args -top_net_of_hierarchical_group]<0} {
            error "Clock must resolve from the existing buffered register clock"
        }
        if {[lindex $args end] ne "A@[dict get $::plan clock anchor_pin]"} {error "Unsupported net object relationship"}
        if {[mock MOCK_MULTIPLE_CLOCK_NETS 0]} {return [list N@SYS_CLK_IBUF_BUFG N@other]}
        if {$::routed && [mock MOCK_CLOCK_NET_CHANGED 0]} {return [list N@other]}
        return [list N@SYS_CLK_IBUF_BUFG]
    }
    set filter [lindex $args end]
    if {![regexp {^NAME == "(.*)"$} $filter -> name]} {error "Nonliteral net query: $args"}
    if {$name ni $::known_nets || [mock MOCK_MISSING_NET 0]} {return {}}
    if {[mock MOCK_MULTIPLE_NETS 0]} {return [list N@$name N@alias]}
    if {[mock MOCK_NET_ALIAS 0]} {return [list N@alias]}
    return [list N@$name]
}
proc get_cells {args} {
    if {[lindex $args end] ne "REF_NAME == BSCANE2"} {error "Unexpected cell query"}
    set result {}
    if {[dict get $::plan profile] eq "host-jtag-ew-ila" && ![mock MOCK_MISSING_MAILBOX 0]} {
        lappend result [expr {[mock MOCK_RENAMED_MAILBOX 0] ? "B@foreign_mailbox" : "B@u_bscan"}]
    }
    if {[mock MOCK_PREEXISTING_BSCAN 0]} {lappend result B@foreign_bscan}
    if {$::routed && ![mock MOCK_MISSING_IMPL_BSCAN 0]} {lappend result B@dbg_hub/inst/bscan}
    if {$::routed && [mock MOCK_EXTRA_IMPL_BSCAN 0]} {lappend result B@extra}
    return $result
}
proc get_debug_cores {args} {
    set cores $::cores
    if {!$::inserted && [mock MOCK_PREEXISTING_CORE 0]} {return [list C@old_core]}
    if {$::routed && [mock MOCK_EXTRA_CORE 0]} {lappend cores C@extra}
    if {$args eq "-quiet"} {return $cores}
    set object C@[lindex $args end]
    return [expr {$object in $cores ? [list $object] : {}}]
}
proc get_debug_ports {args} {
    set pattern [lindex $args end];set result {}
    foreach name [dict keys $::ports] {
        if {[string match $pattern $name]} {lappend result Q@$name}
    }
    if {$::routed && [mock MOCK_EXTRA_PORT 0] && [string match *\* $pattern]} {lappend result Q@u_rk_ew_ila/probe99}
    return $result
}
proc set_property {property value objects} {
    incr ::mutations
    foreach object $objects {dict set ::props [list $object [string toupper $property]] $value}
    event set_property $property $value $objects
}
proc create_debug_core {name type} {
    if {$name ne "u_rk_ew_ila" || $type ne "ila"} {error "Unexpected debug core"}
    set ::inserted 1;incr ::mutations
    set ::cores [list C@$name]
    if {![mock MOCK_NO_HUB 0]} {lappend ::cores C@dbg_hub}
    foreach port [list $name/clk $name/probe0 dbg_hub/clk] {
        dict set ::ports $port 1
        dict set ::props [list Q@$port PORT_WIDTH] 1
    }
    event create_debug_core $name $type
}
proc create_debug_port {name type} {
    if {$type ne "probe"} {error "Unexpected debug port type"}
    set index [expr {[dict size $::ports]-2}]
    set port $name/probe$index
    dict set ::ports $port 1;dict set ::props [list Q@$port PORT_WIDTH] 1
    event create_debug_port $name $type
}
proc connect_debug_port {port nets} {
    if {![dict exists $::ports $port]} {error "Connecting nonexistent port"}
    if {[dict get $::props [list Q@$port PORT_WIDTH]] != [llength $nets]} {error "Connection width mismatch"}
    set names {};foreach net $nets {lappend names [get_property NAME $net]}
    dict set ::connections $port $names
    event connect_debug_port $port $names
}
proc report_debug_core {args} {
    if {[mock MOCK_MISSING_REPORT 0]} {return}
    set file [lindex $args [expr {[lsearch -exact $args -file]+1}]]
    set channel [open $file w]
    if {![mock MOCK_EMPTY_REPORT 0]} {puts $channel "MOCK DEBUG REPORT ONLY - NO VIVADO EXECUTED"}
    close $channel
}
proc write_debug_probes {file} {
    if {[mock MOCK_MISSING_LTX 0]} {return}
    set channel [open $file w]
    if {![mock MOCK_EMPTY_LTX 0]} {puts $channel "MOCK LTX ONLY - NOT HARDWARE EVIDENCE"}
    close $channel
}
set ::known_nets {}
foreach probe [dict get $::plan probes] {lappend ::known_nets {*}[dict get $probe nets]}
if {[catch {
    if {[mock MOCK_SKIP_INSERT 0]} {
        set ::routed 1
        rk_ew_debug_audit $::out $::plan
    } else {
        rk_ew_debug_insert $::out $::plan
        set index 0
        foreach probe [dict get $::plan probes] {
            if {[join [dict get $::connections u_rk_ew_ila/probe$index] "\t"] ne [join [dict get $probe nets] "\t"]} {
                error "Probe order changed"
            }
            incr index
        }
        if {[dict get $::connections u_rk_ew_ila/clk] ne "SYS_CLK_IBUF_BUFG" ||
            [dict get $::connections dbg_hub/clk] ne "SYS_CLK_IBUF_BUFG"} {error "Wrong clock connection"}
        set ::routed 1
        if {[mock MOCK_CHANGE_PLAN 0]} {dict set ::plan description changed}
        rk_ew_debug_audit $::out $::plan
    }
} error]} {
    puts stderr $error
    puts "MUTATIONS=$::mutations"
    exit 1
}
puts "PASS mocked optional ILA controls; no Vivado or hardware qualification"
exit 0
'''


class IlaTclTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tclsh = shutil.which(os.environ.get('RK_TEST_TCLSH', 'tclsh'))
        if cls.tclsh is None:raise RuntimeError('UNAVAILABLE: Tcl interpreter')
        version = checked_tcl_version(cls.tclsh)
        print('ILA Tcl controls:', version, '; all Vivado operations mocked', flush=True)
        cls.plans = [json.loads((ROOT/'fpga/debug'/name).read_text()) for name in ('ew_ila.json','host_ila.json')]

    def test_startup_warning_cannot_pass_with_zero_exit_and_patchlevel(self):
        good = 'VERSION=8.6.13\nAUTO_LOAD=1\nSYNTH_DESIGN=0\n'
        result = subprocess.CompletedProcess(['mock-tclsh'], 0, good, '')
        with patch.object(subprocess, 'run', return_value=result) as run:
            self.assertEqual(checked_tcl_version('mock-tclsh'), '8.6.13')
            run.assert_called_once_with(['mock-tclsh'], input=TCL_STARTUP_PROBE, text=True,
                                        capture_output=True, timeout=10, check=False)
        failures = [
            subprocess.CompletedProcess(['mock-tclsh'], 0, good,
                                        'application-specific initialization failed: cannot find init.tcl\n'),
            subprocess.CompletedProcess(['mock-tclsh'], 1, good, ''),
            subprocess.CompletedProcess(['mock-tclsh'], 0, good.replace('AUTO_LOAD=1','AUTO_LOAD=0'), ''),
            subprocess.CompletedProcess(['mock-tclsh'], 0, good.replace('SYNTH_DESIGN=0','SYNTH_DESIGN=1'), ''),
            subprocess.CompletedProcess(['mock-tclsh'], 0, good.replace('8.6.13',''), ''),
        ]
        for result in failures:
            with self.subTest(result=result), patch.object(subprocess, 'run', return_value=result), \
                 self.assertRaisesRegex(RuntimeError, 'UNAVAILABLE'):
                checked_tcl_version('mock-tclsh')
        with patch.object(subprocess, 'run', side_effect=subprocess.TimeoutExpired('mock-tclsh',10)), \
             self.assertRaisesRegex(RuntimeError, 'UNAVAILABLE'):
            checked_tcl_version('mock-tclsh')

    def run_mock(self, plan, settings=None):
        env = {k:v for k,v in os.environ.items() if not k.startswith('MOCK_')}
        env.update(settings or {})
        with tempfile.TemporaryDirectory(prefix='rk-ila-tcl-controls-') as name:
            out = Path(name)
            script = ('set ::plan '+literal(plan)+'\nset ::out '+literal(str(out))+'\nsource '+
                      literal(str(ROOT/'fpga/debug/ew_ila.tcl'))+'\n'+MOCKS)
            result = subprocess.run([self.tclsh], input=script, env=env, text=True,
                                    capture_output=True, timeout=10)
            artifacts = {p.name:p.read_text() for p in out.iterdir() if p.is_file()}
            self.assertFalse(list(out.rglob('*.bit')));self.assertFalse(list(out.rglob('*.dcp')))
        return result, artifacts

    def test_both_profiles_connect_exact_order_and_keep_scope_honest(self):
        for plan in self.plans:
            with self.subTest(profile=plan['profile']):
                result, artifacts = self.run_mock(plan)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertEqual(result.stdout.count('EVENT create_debug_core '), 1)
                self.assertEqual(result.stdout.count('EVENT create_debug_port '), 13)
                lines = artifacts['ila_connections_requested.tsv'].splitlines()
                actual = [line.split('\t')[2:] for line in lines if line.startswith('PROBE\t')]
                expected = [[p['name'],str(i),net] for p in plan['probes'] for i,net in enumerate(p['nets'])]
                self.assertEqual(actual, expected)
                self.assertEqual(len(actual), 204)
                self.assertIn('PHYSICAL_PROBE_REVIEW_REQUIRED', artifacts['ila_objects_audit.tsv'])
                self.assertIn('MOCK', artifacts['ila_debug_core.rpt']);self.assertIn('MOCK', artifacts['ew_ila.ltx'])
                self.assertNotIn('EVENT set_false_path', result.stdout)

    def test_missing_or_ambiguous_inputs_fail_before_design_mutation(self):
        for plan in self.plans:
            for setting in ('MOCK_MISSING_CLOCK','MOCK_MULTIPLE_CLOCKS','MOCK_MISSING_CLOCK_PORT',
                            'MOCK_MISSING_ANCHOR','MOCK_MULTIPLE_CLOCK_NETS','MOCK_WRONG_CLOCK',
                            'MOCK_MISSING_NET','MOCK_MULTIPLE_NETS','MOCK_NET_ALIAS',
                            'MOCK_PREEXISTING_CORE','MOCK_PREEXISTING_BSCAN'):
                with self.subTest(profile=plan['profile'], setting=setting):
                    result, _ = self.run_mock(plan, {setting:'1'})
                    self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertIn('MUTATIONS=0', result.stdout)

    def test_invalid_clocks_shapes_and_targets_are_rejected(self):
        for plan in self.plans:
            for value in ('10','25','NaN','Inf',''):
                result, _ = self.run_mock(plan, {'MOCK_PERIOD':value})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('MUTATIONS=0', result.stdout)
            for mutation in ('depth','width','duplicate_bit','wrong_top','wrong_part','anchor'):
                value = deepcopy(plan)
                if mutation=='depth':value['core']['depth']=2048
                elif mutation=='width':value['probes'][0]['width']+=1
                elif mutation=='duplicate_bit':value['probes'][0]['nets'][1]=value['probes'][0]['nets'][0]
                elif mutation=='wrong_top':value['top']='other'
                elif mutation=='wrong_part':value['part']='other'
                else:value['clock']['anchor_pin']='SYS_CLK'
                with self.subTest(profile=plan['profile'], mutation=mutation):
                    result, _ = self.run_mock(value)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('MUTATIONS=0', result.stdout)

    def test_routed_object_drift_and_missing_artifacts_fail(self):
        for plan in self.plans:
            for setting in ('MOCK_CHANGED_WIDTH','MOCK_CHANGED_DEPTH','MOCK_CHANGED_PIPE','MOCK_CHANGED_CHAIN',
                            'MOCK_CHANGED_FREQ','MOCK_CHANGED_DIVIDER','MOCK_CLOCK_NET_CHANGED','MOCK_LOST_MARK',
                            'MOCK_EXTRA_CORE','MOCK_EXTRA_PORT','MOCK_MISSING_IMPL_BSCAN','MOCK_EXTRA_IMPL_BSCAN',
                            'MOCK_MISSING_REPORT','MOCK_EMPTY_REPORT','MOCK_MISSING_LTX','MOCK_EMPTY_LTX',
                            'MOCK_SKIP_INSERT','MOCK_CHANGE_PLAN','MOCK_NO_HUB'):
                with self.subTest(profile=plan['profile'], setting=setting):
                    result, _ = self.run_mock(plan, {setting:'1'})
                    self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
            result, _ = self.run_mock(plan, {'MOCK_IMPL_CHAIN':'2'})
            self.assertNotEqual(result.returncode, 0)

    def test_host_user2_owner_must_survive_without_collision(self):
        host = self.plans[1]
        for settings in ({'MOCK_MISSING_MAILBOX':'1'}, {'MOCK_RENAMED_MAILBOX':'1'}, {'MOCK_MAILBOX_CHAIN':'1'}):
            result, _ = self.run_mock(host, settings)
            self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('MUTATIONS=0', result.stdout)

    def test_codebooks_and_probe_bit_order_match_unchanged_rtl(self):
        for plan in self.plans:
            self.assertEqual(len(plan['probes']), 14)
            self.assertEqual(sum(p['width'] for p in plan['probes']), 204)
            self.assertFalse(any('unused_task_done' in n for p in plan['probes'] for n in p['nets']))
            probes = {p['name']:p for p in plan['probes']}
            for book in plan['state_codebooks']:
                source = (ROOT/book['source']).read_text()
                match = re.search(r'typedef\s+enum\s+logic\s*\[(\d+):0\]\s*\{([^}]+)\}\s*state_t;', source, re.S)
                self.assertIsNotNone(match)
                self.assertEqual(int(match[1])+1, book['declared_width'])
                self.assertEqual({n.strip():i for i,n in enumerate(match[2].split(','))}, book['values'])
                self.assertEqual(probes[book['name']]['nets'], [f'{book["signal"]}[{i}]' for i in book['selected_bits']])
            for probe in plan['probes']:
                if all('[' in n for n in probe['nets']):
                    self.assertEqual([int(re.search(r'\[([0-9]+)\]$',n)[1]) for n in probe['nets']], list(range(probe['width'])))


if __name__ == '__main__':unittest.main()
