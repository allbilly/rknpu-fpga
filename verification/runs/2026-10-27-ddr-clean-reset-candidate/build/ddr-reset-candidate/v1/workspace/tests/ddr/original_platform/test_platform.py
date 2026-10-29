"""Offline interface/rendering and Icarus stub-elaboration controls."""
import copy
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.ddr.interface import load_json
from tools.ddr.original_binding import ports
from tools.ddr.original_platform import TOP,render

ROOT=Path(__file__).resolve().parents[3]
PACKAGE=ROOT/'build/original-ddr-platform/v5'
SELECTION=ROOT/'build/original-mig-rtl-selection/v4'
ENDPOINT=ROOT/'rtl/ddr/rk_jtag_ew_ddr_async.sv'
MIG_HEADER=SELECTION/'source/generated/rtl/top_mig_7series_0_0.v'
REPORT=load_json(PACKAGE/'report.json')
PORT_MAP=load_json(SELECTION/'evidence/port-map.json')
ENDPOINT_PORTS=ports(ENDPOINT.read_text(),'rk_jtag_ew_ddr_async')
PORTS=PORT_MAP['ports']
SOURCES=[Path(p) for p in REPORT['interface_check_sources']]


def port_declaration(text,module,port):
    header=re.search(r'\bmodule\s+'+re.escape(module)+r'\s*\((.*?)\n\s*\);',text,re.S)
    if header is None:raise AssertionError('Missing actual module header '+module)
    body=re.sub(r'/\*.*?\*/|//[^\n]*','',header.group(1),flags=re.S)
    result=[]
    for line in body.splitlines():
        line=line.strip().rstrip(',').strip()
        if not line or line.startswith('`'):continue
        found=re.fullmatch(r'(input|output|inout)\s+(?:(?:wire|logic)\s+)?(\[[^]]+\]\s*)?([A-Za-z_]\w*)',line)
        if found and found.group(3)==port:
            direction,extent,_=found.groups()
            result.append({'direction':{'input':'in','output':'out','inout':'inout'}[direction],
                           'range':extent.strip() if extent else None})
    if len(result)!=1:raise AssertionError(f'Expected one declaration for {module}.{port}; found {len(result)}')
    return result[0]


class PlatformRenderTests(unittest.TestCase):
    def setUp(self):
        self.endpoint=copy.deepcopy(ENDPOINT_PORTS)
        self.mapping=copy.deepcopy(PORTS)

    def test_all_169_connections_and_widths_match_source_derived_fixture(self):
        source,stub,top=render(self.endpoint,self.mapping)
        self.assertEqual(len(self.mapping),169)
        instance=re.search(r'top_mig_7series_0_0\s+mig\s*\((.*?)\n\s*\);',source,re.S)
        self.assertIsNotNone(instance)
        self.assertEqual(len(re.findall(r'^\s*\.[A-Za-z_][A-Za-z0-9_]*\(',instance.group(1),re.M)),169)
        for name,port in self.mapping.items():
            binding=port['binding']
            expected=(f"{port['width']}'h{binding['value']:x}" if binding['kind'] in
                      ('inactive_channel_constant','inactive_request_constant') else binding['net'])
            self.assertRegex(source,re.escape(f'.{name}({expected})')+r'(?=,|\n)')
        self.assertIn('module '+TOP+' (',source)
        self.assertIn('module top_mig_7series_0_0 (',stub)

    def test_c1_literal_values_and_exported_physical_pads_and_clocks(self):
        source,_,top=render(self.endpoint,self.mapping)
        constants=[(name,p) for name,p in self.mapping.items()
                   if name.startswith('c1_') and p['binding']['kind'] in
                   ('inactive_channel_constant','inactive_request_constant')]
        self.assertTrue(constants)
        for name,port in constants:
            self.assertEqual(port['direction'],'in')
            value=port['binding']['value']
            self.assertGreaterEqual(value,0)
            self.assertLess(value,1<<port['width'])
            literal=f".{name}({port['width']}'h{value:x})"
            self.assertIn(literal,source)
        physical=REPORT['physical_ports']
        self.assertTrue(physical)
        for name,decl in physical.items():
            self.assertEqual({k:decl[k] for k in ('direction','width')},
                             {k:top[name][k] for k in ('direction','width')})
        self.assertEqual({k:top['c0_ddr3_dq'][k] for k in ('direction','width')},dict(direction='inout',width=72))
        self.assertEqual({k:top['c1_ddr3_dq'][k] for k in ('direction','width')},dict(direction='inout',width=72))
        for name in ('c0_sys_clk_p','c0_sys_clk_n','c1_sys_clk_p','c1_sys_clk_n'):
            self.assertEqual({k:top[name][k] for k in ('direction','width')},dict(direction='in',width=1))
        for name in ('c0_ddr3_ck_p','c0_ddr3_ck_n','c1_ddr3_ck_p','c1_ddr3_ck_n'):
            self.assertEqual({k:top[name][k] for k in ('direction','width')},dict(direction='out',width=1))

    def test_frame_clock_and_reset_aliases_are_explicit(self):
        source,_,top=render(self.endpoint,self.mapping)
        self.assertEqual(top['frame_clk'],dict(direction='out',width=1))
        self.assertEqual(top['frame_rst_n'],dict(direction='out',width=1))
        self.assertRegex(source,r'assign\s+frame_clk\s*=\s*c0_ui_clk\s*;')
        self.assertRegex(source,r'assign\s+frame_rst_n\s*=\s*c0_clients_rst_n\s*;')

    def test_singleton_bus_dimensions_match_actual_generated_mig_header(self):
        actual_text=MIG_HEADER.read_text();platform_text=(PACKAGE/'platform.sv').read_text()
        for channel in (0,1):
            for signal in ('ck_p','ck_n','cke','cs_n','odt'):
                name=f'c{channel}_ddr3_{signal}'
                expected={'direction':'out','range':'[0:0]'}
                self.assertEqual(port_declaration(actual_text,'top_mig_7series_0_0',name),expected,name)
                self.assertEqual(port_declaration(platform_text,'rk_original_mig_ew_platform',name),expected,name)
            for signal in ('reset_n','ras_n','cas_n','we_n'):
                name=f'c{channel}_ddr3_{signal}'
                expected={'direction':'out','range':None}
                self.assertEqual(port_declaration(actual_text,'top_mig_7series_0_0',name),expected,name)
                self.assertEqual(port_declaration(platform_text,'rk_original_mig_ew_platform',name),expected,name)

    def test_invalid_mapping_endpoint_width_direction_constant_kind_and_alias_fail(self):
        cases=[]
        mapping=copy.deepcopy(self.mapping);mapping.pop(next(iter(mapping)));cases.append(('missing_mapping',self.endpoint,mapping))
        mapping=copy.deepcopy(self.mapping);name=next(n for n,p in mapping.items() if p['binding']['kind']=='endpoint');mapping[name]['binding']['net']='missing_endpoint_signal';cases.append(('missing_endpoint',self.endpoint,mapping))
        mapping=copy.deepcopy(self.mapping);name=next(n for n,p in mapping.items() if p['binding']['kind']=='endpoint');mapping[name]['width']+=1;cases.append(('width',self.endpoint,mapping))
        mapping=copy.deepcopy(self.mapping);name=next(n for n,p in mapping.items() if p['binding']['kind']=='endpoint');mapping[name]['direction']=self.endpoint[mapping[name]['binding']['net']]['direction'];cases.append(('direction',self.endpoint,mapping))
        mapping=copy.deepcopy(self.mapping);name=next(n for n,p in mapping.items() if p['binding']['kind']=='inactive_channel_constant');mapping[name]['binding']['value']=1<<mapping[name]['width'];cases.append(('bad_constant',self.endpoint,mapping))
        mapping=copy.deepcopy(self.mapping);name=next(iter(mapping));mapping[name]['binding']['kind']='unmodeled';cases.append(('unmodeled_kind',self.endpoint,mapping))
        endpoint=copy.deepcopy(self.endpoint);endpoint['frame_clk']=dict(direction='out',width=1);cases.append(('reserved_alias',endpoint,self.mapping))
        for label,endpoint,mapping in cases:
            with self.subTest(label=label):
                with self.assertRaises(ValueError):render(endpoint,mapping)


@unittest.skipUnless(shutil.which('iverilog'),'Icarus Verilog required for negative elaboration controls')
class InterfaceElaborationTests(unittest.TestCase):
    def compile(self,sources,output):
        return subprocess.run([shutil.which('iverilog'),'-g2012','-Wall','-s',TOP,'-o',str(output),
                               *[str(p) for p in sources]],capture_output=True,text=True,timeout=180)

    def test_prepared_declaration_only_interface_elaborates_without_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'interface.vvp'
            result=self.compile(SOURCES,output)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout,'')
            self.assertEqual(result.stderr,'')
            self.assertTrue(output.is_file())
            # The image is declaration-only lint output and is never executed.

    def test_bad_mig_port_name_and_width_mismatch_are_rejected_or_warned(self):
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory)
            platform=PACKAGE/'platform.sv';stub=PACKAGE/'mig_interface_only.sv'
            base=[Path(p) for p in REPORT['interface_check_sources']
                  if Path(p) not in (platform,stub)]
            original_platform=platform.read_text();original_stub=stub.read_text()
            bad_platform=work/'bad_port.sv'
            bad_name='unmodeled_mig_port'
            changed=re.sub(r'\.c0_ddr3_dq\(','.'+bad_name+'(',original_platform,count=1)
            self.assertNotEqual(changed,original_platform)
            bad_platform.write_text(changed)
            bad= self.compile([*base,stub,bad_platform],work/'bad_port.vvp')
            self.assertTrue(bad.returncode!=0 or re.search(r'(?i)warning',bad.stderr),bad.stdout+bad.stderr)
            self.assertRegex(bad.stderr+r'\n'+bad.stdout,r'(?i)port|unknown|not.*port|error|warning')

            # Alter only the temporary declaration stub, leaving the prepared
            # source package and its original 169-port fixture untouched.
            bad_width_stub=work/'bad_width_stub.sv'
            changed_stub=re.sub(r'(?m)^(\s*inout\s+wire\s+)\[71:0\](\s+c0_ddr3_dq\s*,?\s*)$',
                                r'\g<1>[70:0]\g<2>',original_stub,count=1)
            self.assertNotEqual(changed_stub,original_stub)
            bad_width_stub.write_text(changed_stub)
            wrong=self.compile([*base,bad_width_stub,platform],work/'bad_width.vvp')
            self.assertTrue(wrong.returncode!=0 or re.search(r'(?i)warning',wrong.stderr),wrong.stdout+wrong.stderr)
            self.assertRegex(wrong.stderr+r'\n'+wrong.stdout,r'(?i)width|prun|pad|warning|error')
            self.assertEqual(platform.read_text(),original_platform)
            self.assertEqual(stub.read_text(),original_stub)


if __name__=='__main__':unittest.main()
