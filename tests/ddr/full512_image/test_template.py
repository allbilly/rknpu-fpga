"""Offline full512 CH1 emission-template controls; no Vivado or hardware."""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.ddr import full512_image_template as renderer
from tools.hardware.sample_ew import tcl_literal


HELPER_BLOCK_STUBS = r'''
proc require {condition message} {if {!$condition} {error $message}}
proc rk_status_inventory {endpoint sys ui0 ui1} {
    require [expr {$endpoint eq "platform/endpoint" && $sys eq "sys_clock" &&
        $ui0 eq "clk_pll_i_1" && $ui1 eq "clk_pll_i"}] "Wrong status inventory arguments"
    return {status0 status1 status2 status3 status4 status5 status6 status7 status8}
}
proc rk_status_cdc_audit {endpoint sys ui0 ui1 output} {
    require [expr {$endpoint eq "platform/endpoint" && $sys eq "sys_clock" &&
        $ui0 eq "clk_pll_i_1" && $ui1 eq "clk_pll_i" && $output eq "reset_status"}] "Wrong status audit arguments"
    lappend ::calls status
}
proc rk_board_reset_inventory {endpoint startup inverter sys ui0 ui1} {
    require [expr {$endpoint eq "platform/endpoint" && $startup eq "startup" &&
        $inverter eq "platform_i_1" && $sys eq "sys_clock" &&
        $ui0 eq "clk_pll_i_1" && $ui1 eq "clk_pll_i"}] "Wrong board reset inventory arguments"
    return {bank0 bank1 bank2 bank3}
}
proc rk_board_reset_audit {endpoint startup inverter sys ui0 ui1 output} {
    require [expr {$output eq "board_reset"}] "Wrong board reset output"
    lappend ::calls board
}
proc rk_cmac_permit_inventory {endpoint ui sys} {
    require [expr {$endpoint eq "platform/endpoint" && $ui eq "clk_pll_i_1" &&
        $sys eq "sys_clock"}] "Wrong CMAC permit inventory arguments"
    set cells {}
    for {set i 0} {$i < $::permit_cell_count} {incr i} {lappend cells permit_sync$i}
    return [list permit_sync "$endpoint/engine/cmac/permit_registered_reg" $ui $sys $cells]
}
proc rk_cmac_permit_audit {endpoint ui sys output} {
    require [expr {$output eq "permit"}] "Wrong CMAC permit audit output"
    lappend ::calls permit
}
proc rk_job_payloads {prefix profile} {
    require [string match "*/" $prefix] "Job payload prefix must end with slash"
    if {$profile eq "ew_engine_e1_e8"} {
        require [expr {$prefix eq "platform/endpoint/engine/ew/job_crossing/"}] "Wrong EW payload prefix"
        set results 37
    } elseif {$profile eq "cmac_terminal_full8"} {
        require [expr {$prefix eq "platform/endpoint/engine/cmac/job_crossing/"}] "Wrong CMAC payload prefix"
        set results 10
    } else {error "Wrong job profile $profile"}
    return [list [list descriptor [lrepeat 64 ds] [lrepeat 64 dt] 40.0] \
        [list result [lrepeat $results rs] [lrepeat $results rt] 15.0]]
}
proc rk_job_cdc_audit {instance source destination output profile} {
    require [expr {![string match "*/" $instance] &&
        $source eq "clk_pll_i_1" && $destination eq "sys_clock"}] "Wrong/bare-instance job audit clocks"
    if {$profile eq "ew_engine_e1_e8"} {
        require [expr {$instance eq "platform/endpoint/engine/ew/job_crossing" && $output eq "ew_job"}] "Wrong EW audit instance/profile"
        lappend ::calls ew_job
    } elseif {$profile eq "cmac_terminal_full8"} {
        require [expr {$instance eq "platform/endpoint/engine/cmac/job_crossing" && $output eq "cmac_job"}] "Wrong CMAC audit instance/profile"
        lappend ::calls cmac_job
    } else {error "Wrong job audit profile $profile"}
}
proc rk_mem_prefix {instance} {
    require [expr {![string match "*/" $instance]}] "Wrong memory instance"
    return "$instance/"
}
proc rk_mem_payloads {prefix} {
    require [string match "*/" $prefix] "Memory payload prefix must end with slash"
    return {{request source target 15.0} {response source target 40.0}}
}
proc rk_mem_cdc_audit {instance source destination output} {
    require [expr {$source eq "sys_clock" && $destination eq "clk_pll_i_1"}] "Wrong memory audit clock direction"
    if {$instance eq "platform/endpoint/engine/ew/memory_crossing" && $output eq "ew_memory"} {
        lappend ::calls ew_memory
    } elseif {$instance eq "platform/endpoint/engine/cmac/memory_crossing" && $output eq "cmac_memory"} {
        lappend ::calls cmac_memory
    } else {error "Wrong memory audit instance"}
}
proc rk_ddr_host_cdc_audit {name ui} {
    require [expr {$name eq "mailbox" && $ui eq "clk_pll_i_1"}] "Wrong mailbox audit arguments"
    lappend ::calls mailbox
}
proc rk_status_cdc_constrain {args} {incr ::constrain_calls; error "constraint helper invoked"}
proc rk_board_reset_constrain {args} {incr ::constrain_calls; error "constraint helper invoked"}
proc rk_cmac_permit_constrain {args} {incr ::constrain_calls; error "constraint helper invoked"}
proc rk_job_cdc_constrain {args} {incr ::constrain_calls; error "constraint helper invoked"}
proc rk_mem_cdc_constrain {args} {incr ::constrain_calls; error "constraint helper invoked"}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def synthetic_ports():
    names = ["SYS_CLK", "port with spaces", "port[7]", "$literal_port", "CFG_USER2"]
    names.extend(f"board_io_{i}" for i in range(242 - len(names)))
    assert len(names) == 242 and len(set(names)) == 242
    return {
        name: {
            "PACKAGE_PIN": f"PIN{i % 20}",
            "IOSTANDARD": "LVCMOS18",
            "SLEW": "SLOW",
            "DRIVE": "12",
            "PULLTYPE": "NONE",
            "DIFF_TERM": "FALSE",
            "IN_TERM": "NONE",
            "DIRECTION": "IN" if i % 2 == 0 else "OUT",
        }
        for i, name in enumerate(names)
    }


class Full512ImageTemplateTests(unittest.TestCase):
    def make_bound_inputs(self, directory):
        directory = Path(directory)
        dcp = directory / "qualified checkpoint [full512] $literal.dcp"
        dcp.write_bytes(b"synthetic input bytes; not opened as a checkpoint")
        helper_dir = directory / "helpers [full512]"
        helper_dir.mkdir()
        helpers = {}
        for name in renderer.HELPERS:
            target = helper_dir / f"{name} [bound].tcl"
            # Synthetic helper bytes keep these renderer controls portable;
            # helper behavior is source-bound and reviewed in the route DAG.
            target.write_text(f"# synthetic hash-bound {name} helper fixture\n")
            helpers[name] = target
        inputs = {str(dcp.resolve()): sha(dcp)}
        inputs.update({str(path.resolve()): sha(path) for path in helpers.values()})
        inputs[str(renderer.TEMPLATE.resolve())] = sha(renderer.TEMPLATE)
        inputs[str(Path(renderer.__file__).resolve())] = sha(renderer.__file__)
        output = directory / "emission output [offline]"
        return dcp, helpers, inputs, output

    def render_valid(self, directory, *, ports=None, source_tag="d4e5f607"):
        dcp, helpers, inputs, output = self.make_bound_inputs(directory)
        text = renderer.render(
            dcp,
            output,
            inputs,
            helpers,
            synthetic_ports() if ports is None else ports,
            source_tag,
        )
        return text, dcp, helpers, inputs, output

    def test_positive_render_binds_all_inputs_helpers_and_exact_full512_profile(self):
        with tempfile.TemporaryDirectory(prefix="full512 image [positive] $") as tmp:
            text, dcp, helpers, inputs, output = self.render_valid(tmp)
            self.assertIn("set dcp " + tcl_literal(dcp.resolve()), text)
            self.assertIn("set out " + tcl_literal(output.resolve()), text)
            self.assertIn(tcl_literal("port with spaces"), text)
            self.assertIn(tcl_literal("port[7]"), text)
            self.assertIn(tcl_literal("$literal_port"), text)
            source_lines = [line for line in text.splitlines() if line.startswith("source ")]
            self.assertEqual(
                source_lines,
                ["source " + tcl_literal(helpers[name].resolve()) for name in renderer.HELPERS],
            )
            self.assertEqual(len(inputs), 9)
            self.assertIn("ypcb_ddr_dual_top", text)
            self.assertIn("cmac_terminal_full8", text)
            self.assertIn("ew_engine_e1_e8", text)
            self.assertIn("DPIP-1 1032 DPOP-1 516 DPOP-2 516 REQP-1709 2", text)
            self.assertIn("products == 512", text)
            self.assertIn("[llength $dsps] == 516", text)
            self.assertIn("PASS_REVIEWED_FULL512_CH1_DDR_BITSTREAM_EMISSION_ONLY", text)
            self.assertEqual(
                len(re.findall(r"^set_property BITSTREAM\.CONFIG\.USR_ACCESS 0xd4e5f607", text, re.M)),
                1,
            )
            self.assertEqual(len(re.findall(r"^set_property\b", text, re.M)), 1)
            for forbidden in (
                r"\bcreate_clock\b",
                r"\bset_false_path\b",
                r"\bset_max_delay\b",
                r"\bset_bus_skew\b",
                r"\bset_clock_groups\b",
                r"\bplace_design\b",
                r"\broute_design\b",
                r"\bsynth_design\b",
                r"\bprogram_hw\w*\b",
                r"\bopen_hw\w*\b",
                r"\bwrite_cfgmem\b",
            ):
                self.assertIsNone(re.search(forbidden, text, re.I), forbidden)
            self.assertEqual(text.count("@"), 0)

    def test_rejects_missing_malformed_and_unbound_inputs_or_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            dcp, helpers, inputs, output = self.make_bound_inputs(tmp)
            ports = synthetic_ports()
            tag = "d4e5f607"
            with self.assertRaisesRegex(ValueError, "Nonempty exact qualified input hashes"):
                renderer.render(dcp, output, {}, helpers, ports, tag)
            for bad in ("0" * 63, "g" * 64, "A" * 64):
                with self.subTest(bad_hash=bad), self.assertRaisesRegex(
                    ValueError, "Nonempty exact qualified input hashes"
                ):
                    renderer.render(dcp, output, {"fixture": bad}, helpers, ports, tag)
            missing_dcp = dict(inputs)
            missing_dcp.pop(str(dcp.resolve()))
            with self.assertRaisesRegex(ValueError, "Checkpoint, renderer, template and all helpers"):
                renderer.render(dcp, output, missing_dcp, helpers, ports, tag)
            for bound_path in (renderer.TEMPLATE, Path(renderer.__file__)):
                missing = dict(inputs)
                missing.pop(str(bound_path.resolve()))
                with self.subTest(unbound=bound_path), self.assertRaisesRegex(
                    ValueError, "Checkpoint, renderer, template and all helpers"
                ):
                    renderer.render(dcp, output, missing, helpers, ports, tag)
            missing_helper_hash = dict(inputs)
            missing_helper_hash.pop(str(helpers["cmac_permit"].resolve()))
            with self.assertRaisesRegex(ValueError, "Checkpoint, renderer, template and all helpers"):
                renderer.render(dcp, output, missing_helper_hash, helpers, ports, tag)
            fewer = dict(helpers)
            fewer.pop("cmac_permit")
            with self.assertRaisesRegex(ValueError, "All six reviewed full512 constraint helpers"):
                renderer.render(dcp, output, inputs, fewer, ports, tag)
            extra = dict(helpers)
            extra["unreviewed"] = helpers["cmac_permit"]
            with self.assertRaisesRegex(ValueError, "All six reviewed full512 constraint helpers"):
                renderer.render(dcp, output, inputs, extra, ports, tag)

    def test_rejects_zero_or_malformed_tag_and_changed_242_port_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dcp, helpers, inputs, output = self.make_bound_inputs(tmp)
            ports = synthetic_ports()
            for tag in ("00000000", "0000000", "zzzzzzzz", "D4E5F607"):
                with self.subTest(tag=tag), self.assertRaisesRegex(
                    ValueError, "Nonzero source-derived image tag required"
                ):
                    renderer.render(dcp, output, inputs, helpers, ports, tag)
            fewer = dict(ports)
            fewer.pop(next(iter(fewer)))
            with self.assertRaisesRegex(ValueError, "Exact242-port property snapshot required"):
                renderer.render(dcp, output, inputs, helpers, fewer, "d4e5f607")
            missing_property = {key: dict(value) for key, value in ports.items()}
            missing_property["SYS_CLK"].pop("PACKAGE_PIN")
            with self.assertRaisesRegex(ValueError, "Exact242-port property snapshot required"):
                renderer.render(dcp, output, inputs, helpers, missing_property, "d4e5f607")
            extra_property = {key: dict(value) for key, value in ports.items()}
            extra_property["SYS_CLK"]["INIT"] = "0"
            with self.assertRaisesRegex(ValueError, "Exact242-port property snapshot required"):
                renderer.render(dcp, output, inputs, helpers, extra_property, "d4e5f607")

    def test_conflicting_relative_and_absolute_alias_hashes_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dcp, helpers, inputs, output = self.make_bound_inputs(root)
            relative_dcp = dcp.relative_to(root)
            relative_helpers = {name: path.relative_to(root) for name, path in helpers.items()}
            aliases = {str(path.relative_to(root)): sha(path) for path in [dcp, *helpers.values()]}
            aliases[str(renderer.TEMPLATE.resolve())] = sha(renderer.TEMPLATE)
            aliases[str(Path(renderer.__file__).resolve())] = sha(renderer.__file__)
            aliases[str(dcp.resolve())] = "0" * 64
            previous = Path.cwd()
            try:
                os.chdir(root)
                with self.assertRaisesRegex(ValueError, "Conflicting qualified hashes for one image input"):
                    renderer.render(relative_dcp, output.relative_to(root), aliases,
                                    relative_helpers, synthetic_ports(), "d4e5f607")
            finally:
                os.chdir(previous)

    @unittest.skipUnless(shutil.which("tclsh") and shutil.which("sha256sum"), "Tcl and SHA utility required")
    def test_tclinfo_accepts_complete_generated_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, *_ = self.render_valid(tmp)
            script = Path(tmp) / "full512 emission.tcl"
            script.write_text(text)
            tcl = "set f [open " + tcl_literal(script) + " r]\nset body [read $f]\nclose $f\nputs [info complete $body]\n"
            result = subprocess.run([shutil.which("tclsh")], input=tcl, text=True,
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(result.stdout.strip(), "1")

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl required")
    def test_helper_audit_block_uses_reviewed_profiles_and_read_only_api_shapes(self):
        template = renderer.TEMPLATE.read_text()
        start_marker = "# BEGIN FULL512 AUDIT-ONLY HELPER INVOCATIONS\n"
        end_marker = "# END FULL512 AUDIT-ONLY HELPER INVOCATIONS"
        self.assertEqual(template.count(start_marker), 1)
        self.assertEqual(template.count(end_marker), 1)
        block = template.split(start_marker, 1)[1].split(end_marker, 1)[0]

        def invoke(permit_cells):
            prefix = HELPER_BLOCK_STUBS + f"""
set endpoint platform/endpoint
set startup_name startup
set inverter_name platform_i_1
set sys sys_clock
set ui0 clk_pll_i_1
set ui1 clk_pll_i
set permit_cell_count {permit_cells}
set calls {{}}
set constrain_calls 0
"""
            suffix = """
require [expr {$constrain_calls == 0}] "A constraint procedure was called"
require [expr {$calls eq {status board permit ew_job cmac_job ew_memory cmac_memory mailbox}}] \
    "Audit invocation set/order changed"
puts AUDIT_HELPERS_PASS
"""
            with tempfile.TemporaryDirectory() as tmp:
                script = Path(tmp) / "audit block.tcl"
                script.write_text(prefix + block + suffix)
                return subprocess.run([shutil.which("tclsh"), str(script)], cwd=tmp,
                                      capture_output=True, text=True, timeout=15)

        accepted = invoke(3)
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(accepted.stderr, "")
        self.assertIn("AUDIT_HELPERS_PASS", accepted.stdout)
        for wrong_count in (2, 4):
            with self.subTest(permit_cells=wrong_count):
                rejected = invoke(wrong_count)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("Expected one three-stage CMAC permit synchronizer", rejected.stderr)
                self.assertNotIn("AUDIT_HELPERS_PASS", rejected.stdout)

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl required")
    def run_pulse_audit(self, report):
        template = renderer.TEMPLATE.read_text()
        start_marker = "# BEGIN ALL-ROW PULSE WIDTH AUDIT\n"
        end_marker = "# END ALL-ROW PULSE WIDTH AUDIT"
        self.assertEqual(template.count(start_marker), 1)
        self.assertEqual(template.count(end_marker), 1)
        body = template.split(start_marker, 1)[1].split(end_marker, 1)[0]
        harness = r'''
proc require {condition message} {if {!$condition} {error $message}}
proc finite {value} {
    return [expr {[string is double -strict $value] &&
        ![catch {expr {abs(double($value)) < Inf}} result] && $result}]
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "pulse audit.tcl"
            script.write_text(
                harness + body + "\nset pulse " + tcl_literal(report) + "\n"
                "if {[catch {audit_pulse_width_report $pulse} result]} {puts \"REJECT=$result\"} "
                "else {puts \"ACCEPT=[dict get $result {Min Period}] [dict get $result {Max Period}] "
                "[dict get $result {Low Pulse Width}] [dict get $result {High Pulse Width}]\"}\n"
            )
            return subprocess.run([shutil.which("tclsh"), str(script)], cwd=tmp,
                                  capture_output=True, text=True, timeout=15)

    @staticmethod
    def pulse_report(negative_kind=None, *, include_max=True, missing_kind=None, malformed=None):
        rows = []
        descriptions = {
            "Min Period": ("n/a", "CLK", "n/a", "1.000", "2.000", "1.000"),
            "Max Period": ("n/a", "CLK", "n/a", "5.000", "2.000", "3.000"),
            "Low Pulse Width": ("Slow", "CLK", "n/a", "0.500", "1.000", "0.500"),
            "High Pulse Width": ("Slow", "CLK", "n/a", "0.500", "1.000", "0.500"),
        }
        for kind in ("Min Period", "Max Period", "Low Pulse Width", "High Pulse Width"):
            if kind == "Max Period" and not include_max:
                continue
            if kind == missing_kind:
                continue
            if kind == malformed:
                rows.append(kind)
                continue
            tokens = descriptions[kind]
            for clock_name in ("CLK_A", "CLK_B"):
                row = list(tokens)
                row[1] = clock_name
                if kind == negative_kind and clock_name == "CLK_B":
                    row[5] = "-0.001"
                rows.append(kind + " " + " ".join(row) + " SITE " + clock_name)
        return "\n".join(rows)

    def test_pulse_audit_checks_all_rows_and_allows_absent_max_period(self):
        good = self.run_pulse_audit(self.pulse_report())
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertEqual(good.stderr, "")
        self.assertIn("ACCEPT=2 2 2 2", good.stdout)
        no_max = self.run_pulse_audit(self.pulse_report(include_max=False))
        self.assertEqual(no_max.returncode, 0, no_max.stdout + no_max.stderr)
        self.assertIn("ACCEPT=2 0 2 2", no_max.stdout)

    def test_pulse_audit_rejects_later_negative_row_for_each_check_kind(self):
        for kind in ("Min Period", "Max Period", "Low Pulse Width", "High Pulse Width"):
            for separator in (" ", "\t"):
                with self.subTest(kind=kind, separator=separator):
                    report = self.pulse_report(negative_kind=kind).replace(" ", separator)
                    result = self.run_pulse_audit(report)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("REJECT=Invalid or failing pulse check row: " + kind, result.stdout)
                    self.assertNotIn("ACCEPT=", result.stdout)

    def test_pulse_audit_rejects_missing_required_and_malformed_rows(self):
        for kind in ("Min Period", "Low Pulse Width", "High Pulse Width"):
            with self.subTest(missing=kind):
                result = self.run_pulse_audit(self.pulse_report(missing_kind=kind))
                self.assertIn("REJECT=Missing pulse check rows for " + kind, result.stdout)
        for row in (
            self.pulse_report(malformed="Min Period"),
            self.pulse_report().replace("High Pulse Width Slow CLK_B n/a 0.500 1.000 0.500", "High Pulse Width Slow CLK_B n/a 0.500 NaN 0.500"),
        ):
            with self.subTest(malformed=True):
                result = self.run_pulse_audit(row)
                self.assertIn("REJECT=", result.stdout)
                self.assertNotIn("ACCEPT=", result.stdout)

    @unittest.skipUnless(shutil.which("tclsh"), "Tcl required")
    def run_bitstream_drc_gate(self, *, counts=None, unknown=False, bad_severity=False):
        template = renderer.TEMPLATE.read_text()
        start_marker = "# BEGIN BITSTREAM CHECK DRC GATE\n"
        end_marker = "# END BITSTREAM CHECK DRC GATE"
        self.assertEqual(template.count(start_marker), 1)
        self.assertEqual(template.count(end_marker), 1)
        body = template.split(start_marker, 1)[1].split(end_marker, 1)[0]
        expected = {"DPIP-1": 1032, "DPOP-1": 516, "DPOP-2": 516, "REQP-1709": 2}
        if counts is not None:
            expected.update(counts)
        rules = []
        for rule, count in expected.items():
            rules.extend([rule] * count)
        if unknown:
            rules.append("UNREVIEWED-1")
        identifiers = [f"v{i}" for i in range(len(rules))]
        rule_map = " ".join(f"{name} {{{rule}#{i + 1}}}" for i, (name, rule) in
                            enumerate(zip(identifiers, rules)))
        severity_map = " ".join(
            f"{name} {{{'ERROR' if bad_severity and i == 0 else 'WARNING'}}}"
            for i, name in enumerate(identifiers)
        )
        prefix = f"""
proc require {{condition message}} {{if {{!$condition}} {{error $message}}}}
proc report_drc {{args}} {{}}
set expected_drc [dict create DPIP-1 1032 DPOP-1 516 DPOP-2 516 REQP-1709 2]
set ::violations {{{' '.join(identifiers)}}}
set ::names {{{rule_map}}}
set ::severities {{{severity_map}}}
proc get_drc_violations {{}} {{return $::violations}}
proc get_property {{property object}} {{
    if {{$property eq "NAME"}} {{return [dict get $::names $object]}}
    if {{$property eq "SEVERITY"}} {{return [dict get $::severities $object]}}
    error "Unexpected property $property"
}}
"""
        suffix = """
puts BITSTREAM_DRC_ACCEPTED
"""
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "bitstream DRC gate.tcl"
            script.write_text(prefix + body + suffix)
            return subprocess.run([shutil.which("tclsh"), str(script)], cwd=tmp,
                                  capture_output=True, text=True, timeout=30)

    def test_bitstream_drc_gate_accepts_exact_reviewed_inventory(self):
        result = self.run_bitstream_drc_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("BITSTREAM_DRC_ACCEPTED", result.stdout)

    def test_bitstream_drc_gate_rejects_missing_or_extra_allowed_rule_counts(self):
        for rule, count in (("DPIP-1", 1031), ("REQP-1709", 3)):
            with self.subTest(rule=rule, count=count):
                result = self.run_bitstream_drc_gate(counts={rule: count})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Changed bitstream-check DRC warning inventory", result.stderr)
                self.assertNotIn("BITSTREAM_DRC_ACCEPTED", result.stdout)

    def test_bitstream_drc_gate_rejects_unknown_rule_or_severity(self):
        for kwargs in ({"unknown": True}, {"bad_severity": True}):
            with self.subTest(kwargs=kwargs):
                result = self.run_bitstream_drc_gate(**kwargs)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("BITSTREAM_DRC_ACCEPTED", result.stdout)

    @unittest.skipUnless(shutil.which("tclsh") and shutil.which("sha256sum"), "Tcl and SHA utility required")
    def run_hash_guard(self, tamper):
        with tempfile.TemporaryDirectory(prefix="full512 input [guard] $") as tmp:
            text, dcp, helpers, _, output = self.render_valid(tmp)
            script = Path(tmp) / "rendered emission.tcl"
            script.write_text(text)
            if tamper:
                helper = helpers["cmac_permit"]
                helper.write_bytes(helper.read_bytes() + b"\n# tampered after render\n")
                expected = "Changed qualified full512 image input"
            else:
                dcp.unlink()
                expected = "Missing qualified full512 image input"
            runner = Path(tmp) / "guard runner.tcl"
            runner_text = """rename source ::real_source
set opened 0
set written 0
proc source {path} {
    if {[file tail $path] eq "rendered emission.tcl"} {return [uplevel #0 [list ::real_source $path]]}
    return
}
proc open_checkpoint {args} {incr ::opened; error CHECKPOINT_REACHED}
proc write_checkpoint {args} {incr ::written}
proc write_bitstream {args} {incr ::written}
if {[catch {source @SCRIPT@} message]} {puts "STOP=$message"}
puts "OPENED=$opened WRITTEN=$written OUTPUT_EXISTS=[file exists @OUTPUT@]"
"""
            runner.write_text(
                runner_text.replace("@SCRIPT@", tcl_literal(script)).replace(
                    "@OUTPUT@", tcl_literal(output)
                )
            )
            result = subprocess.run([shutil.which("tclsh"), str(runner)], text=True,
                                    capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("STOP=" + expected, result.stdout)
            self.assertIn("OPENED=0 WRITTEN=0", result.stdout)
            self.assertIn("OUTPUT_EXISTS=0", result.stdout)
            self.assertNotIn("CHECKPOINT_REACHED", result.stdout)

    def test_tcl_hash_guard_rejects_tampered_bound_helper_before_opening_design(self):
        self.run_hash_guard(True)

    def test_tcl_hash_guard_rejects_missing_checkpoint_before_opening_design(self):
        self.run_hash_guard(False)


if __name__ == "__main__":
    unittest.main()
