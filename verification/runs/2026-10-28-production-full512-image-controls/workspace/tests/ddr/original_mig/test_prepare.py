"""Mock generation guards and original-profile checks; no Vivado/hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tools.ddr import prepare_original_mig as p
from tools.hardware.sample_ew import tcl_literal


def project():
    root = ET.Element('Project', NoOfControllers='2')
    for name, value in dict(ModuleName='top_mig_7series_0_0', TargetFPGA='xc7k480t-ffg1156/-2',
        SystemClock='Differential', ReferenceClock='Use System Clock', SysResetPolarity='ACTIVE LOW').items():
        ET.SubElement(root, name).text = value
    for channel in (0, 1):
        c = ET.SubElement(root, 'Controller', number=str(channel))
        for name, value in dict(PortInterface='AXI', ECC='Enabled', PHYRatio='4:1', DataWidth='72',
            InputClkFreq='200', TimePeriod='1875', emrOutputDriveStrength='RZQ/7',
            **{f'C{channel}_MEM_SIZE': '2147483648'}).items():
            ET.SubElement(c, name).text = value
        axi = ET.SubElement(c, 'AXIParameters')
        for name, value in dict(ADDR_WIDTH='31', DATA_WIDTH='512', ID_WIDTH='4', SUPPORTS_NARROW_BURST='0').items():
            ET.SubElement(axi, f'C{channel}_S_AXI_{name}').text = value
        pair, bank = ('AH27/AH28(CC_P/N)', '12') if channel == 0 else ('G25/G26(CC_P/N)', '17')
        ET.SubElement(c, 'Pin', Bank=bank, PADName=pair, name=f'c{channel}_sys_clk_p/n')
    return root


MOCK = r'''
proc version {args} {if {$::scenario eq "version"} {return 2026.2};return 2026.1}
proc current_project {} {return synthetic_project}
proc create_project {args} {
    if {[lrange $args 0 0] ne "rknpu_original_mig" || [lrange $args end-1 end] ne {-part xc7k480tffg1156-2}} {error "Changed project command"}
}
proc get_property {key object} {
    if {$key ne "PART"} {error property}
    return [expr {$::scenario eq "part" ? "xc7k325tffg900-2" : "xc7k480tffg1156-2"}]
}
proc set_property {key value object} {
    if {$key eq "target_language" && $value eq "Verilog"} {return}
    if {$key eq "CONFIG.XML_INPUT_FILE" && $value eq $::qualified} {return}
    error "Unreviewed property mutation"
}
proc create_ip {args} {
    if {[lrange $args 0 9] ne {-name mig_7series -vendor xilinx.com -library ip -version 4.2 -module_name top_mig_7series_0_0}} {error "Changed IP command"}
    if {[lindex $args 10] ne "-dir" || ![file isdirectory [lindex $args 11]]} {error "IP directory does not exist"}
}
proc get_ips {name} {if {$::scenario eq "count"} {return {a b}};return $name}
proc generate_target {args} {
    set root [file join $::out ip top_mig_7series_0_0 top_mig_7series_0_0 user_design rtl]
    foreach name {top_mig_7series_0_0.v top_mig_7series_0_0_mig.v axi/mig_7series_v4_2_axi_mc.v axi/mig_7series_v4_2_axi_ctrl_top.v controller/mig_7series_v4_2_mc.v} {
        if {$::scenario eq "missing" && [string match controller/* $name]} {continue}
        set path [file join $root $name];file mkdir [file dirname $path]
        set f [open $path w];puts $f "SYNTHETIC_MOCK_FILE_NOT_VENDOR_HDL";close $f
    }
    if {$::scenario eq "during"} {set f [open $::qualified a];puts $f changed;close $f}
}
proc report_ip_status {args} {}
proc close_project {} {}
'''


class OriginalProfileTests(unittest.TestCase):
    def test_original_dual_ecc_clock_and_drive_contract(self):
        facts = p.profile(ET.tostring(project()))
        self.assertEqual(facts['values']['controllers'], 2)
        self.assertEqual([c['output_drive'] for c in facts['channels']], ['RZQ/7', 'RZQ/7'])
        self.assertFalse(facts['board_clock_delivery_verified'])
        self.assertFalse(facts['electrical_admission'])

    def test_changed_electrical_clock_reset_and_either_channel_profile_reject(self):
        paths = ['SystemClock', 'ReferenceClock', 'SysResetPolarity', 'TargetFPGA',
                 'ModuleName']
        for channel in range(2):
            prefix = f"Controller[@number='{channel}']/"
            paths += [prefix+n for n in ('ECC', 'PHYRatio', 'DataWidth', 'InputClkFreq', 'TimePeriod',
                       'emrOutputDriveStrength', f'C{channel}_MEM_SIZE',
                       f'AXIParameters/C{channel}_S_AXI_ADDR_WIDTH', f'AXIParameters/C{channel}_S_AXI_DATA_WIDTH')]
        for path in paths:
            root = project()
            root.find(path).text = 'changed'
            with self.subTest(path=path), self.assertRaises(ValueError):
                p.profile(ET.tostring(root))
        for attr in ('Bank', 'PADName'):
            root = project();root.find('Controller/Pin').set(attr, 'changed')
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                p.profile(ET.tostring(root))

    def test_renderer_has_no_implementation_or_hardware_commands(self):
        text = p.render('in.prj', 'out', {'fixture': 'a'*64})
        for command in ('synth_design', 'launch_runs', 'place_design', 'route_design', 'write_bitstream',
                        'open_hw_manager', 'program_hw', 'write_cfgmem', 'set_false_path', 'set_property SEVERITY'):
            self.assertNotIn(command, text)
        for inputs in ({}, {'fixture': 'bad'}):
            with self.assertRaises(ValueError):
                p.render('in.prj', 'out', inputs)


@unittest.skipUnless(shutil.which('tclsh') and shutil.which('sha256sum'), 'Tcl/SHA utility required')
class GenerationTemplateTests(unittest.TestCase):
    def invoke(self, scenario):
        with tempfile.TemporaryDirectory(prefix='original MIG {;} ') as directory:
            root = Path(directory);item = root/'project newline\n\\.prj'
            item.write_bytes(b'synthetic frozen XML fixture')
            out = root/'generation'
            body = p.render(item, out, {str(item): p.sha(item)})
            if scenario == 'old_no_ip_dir':
                self.assertEqual(body.count('file mkdir [file join $out ip]\n'), 1)
                body = body.replace('file mkdir [file join $out ip]\n', '')
            if scenario == 'changed':
                item.write_bytes(b'changed')
            if scenario == 'exists':
                out.mkdir()
            script = root/'mock.tcl'
            script.write_text('set ::scenario '+tcl_literal(scenario)+'\nset ::qualified '+tcl_literal(item)+'\n'+MOCK+'\n'+body)
            result = subprocess.run([shutil.which('tclsh'), str(script)], capture_output=True, text=True, timeout=15)
            return result, (out/'generation.tsv').exists()

    def test_exact_mock_generation_is_source_only(self):
        result, receipt = self.invoke('good')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue(receipt)
        self.assertIn('PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY', result.stdout)

    def test_failed_input_target_tool_or_output_checks_block_success(self):
        for scenario in ('changed', 'during', 'exists', 'version', 'part', 'count', 'missing', 'old_no_ip_dir'):
            with self.subTest(scenario=scenario):
                result, receipt = self.invoke(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(receipt)
                self.assertNotIn('PASS_GENERATED_ORIGINAL_MIG_SOURCES_ONLY', result.stdout)


if __name__ == '__main__':
    unittest.main()
