"""Portable synthetic parser controls, never qualification of actual MIG RTL."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tools.ddr import interface as api

ROOT = Path(__file__).resolve().parents[2]


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference = api.load_json(ROOT/'fpga/ddr/mig_c0_reference.json')
        self.ports = api.expected_ports() | {
            'c0_app_ecc_multiple_err':dict(direction='out',width=8),
            'c0_app_ecc_single_err':dict(direction='out',width=8)}
        project = '''<Project NoOfControllers="2"><ModuleName>top_mig_7series_0_0</ModuleName>
<TargetFPGA>xc7k480t-ffg1156/-2</TargetFPGA><SystemClock>Differential</SystemClock>
<ReferenceClock>Use System Clock</ReferenceClock><SysResetPolarity>ACTIVE LOW</SysResetPolarity>
<Controller number="0"><PortInterface>AXI</PortInterface><ECC>Enabled</ECC><PHYRatio>4:1</PHYRatio>
<DataWidth>72</DataWidth><C0_MEM_SIZE>2147483648</C0_MEM_SIZE><InputClkFreq>200</InputClkFreq>
<TimePeriod>1875</TimePeriod><AXIParameters><C0_S_AXI_ADDR_WIDTH>31</C0_S_AXI_ADDR_WIDTH>
<C0_S_AXI_DATA_WIDTH>512</C0_S_AXI_DATA_WIDTH><C0_S_AXI_ID_WIDTH>4</C0_S_AXI_ID_WIDTH>
<C0_S_AXI_SUPPORTS_NARROW_BURST>0</C0_S_AXI_SUPPORTS_NARROW_BURST></AXIParameters>
</Controller><Controller number="1"/></Project>'''
        template = '\n'.join(f'.{name}({name}), // '+{'in':'input','out':'output','inout':'inout'}[port['direction']]+
                            (f" [{port['width']-1}:0]" if port['width'] != 1 else '')+' '+name
                            for name,port in self.ports.items())
        template='top_mig_7series_0_0 instance (\n'+template+'\n);'
        example = 'parameter C0_nCK_PER_CLK = 4;\n'+'\n'.join(
            f'wire [(2*C0_nCK_PER_CLK)-1:0] {n};\n.{n}({n})' for n in
            ('c0_app_ecc_single_err','c0_app_ecc_multiple_err'))
        file_list = '\n'.join(v['path'] for v in self.reference['missing_generated_sources']['referenced_by_file_list'])
        for role,text in dict(project=project,template=template,component=self.component_xml(),
                              example=example,file_list=file_list,block_design='synthetic fixture; no RTL').items():
            self.write(role,text)

    def component_xml(self):
        tag = lambda n:'{'+api.SPIRIT+'}'+n
        x = lambda n:'{'+api.XILINX+'}'+n
        root = ET.Element(tag('component')); model = ET.SubElement(root,tag('model'))
        params = ET.SubElement(model,tag('modelParameters'))
        values = dict(NoOfControllers=2,C0_USE_AXI=1,C0_ECC='ON',C0_MEM_TYPE='DDR3',
                      C0_DDRX_nCK_PER_CLK=4,C0_C_S_AXI_ADDR_WIDTH=31,
                      C0_C_S_AXI_DATA_WIDTH=512,C0_C_S_AXI_ID_WIDTH=4)
        for key,val in values.items():
            p=ET.SubElement(params,tag('modelParameter'))
            ET.SubElement(p,tag('name')).text=key; ET.SubElement(p,tag('value')).text=str(val)
        ports = ET.SubElement(model,tag('ports'))
        for name,info in self.ports.items():
            port=ET.SubElement(ports,tag('port')); ET.SubElement(port,tag('name')).text=name
            wire=ET.SubElement(port,tag('wire')); ET.SubElement(wire,tag('direction')).text=info['direction']
            if info['width']>1:
                vector=ET.SubElement(wire,tag('vector')); left=ET.SubElement(vector,tag('left'))
                left.text=str(info['width']-1); ET.SubElement(vector,tag('right')).text='0'
                if name == 'c0_s_axi_awaddr':
                    left.set(tag('resolve'),'dependent')
                    left.set(tag('dependency'),"spirit:decode(id('MODELPARAM_VALUE.C0_C_S_AXI_ADDR_WIDTH')) - 1")
            vendor=ET.SubElement(port,tag('vendorExtensions')); info=ET.SubElement(vendor,x('portInfo'))
            enabled=ET.SubElement(ET.SubElement(info,x('enablement')),x('isEnabled'))
            enabled.text='true'; enabled.set(x('resolve'),'dependent')
            enabled.set(x('dependency'),"spirit:decode(id('MODELPARAM_VALUE.NoOfControllers')) > 1 and spirit:decode(id('MODELPARAM_VALUE.C0_USE_AXI')) = 1")
        buses=ET.SubElement(root,tag('busInterfaces'))
        for name,physical,logical,fields in [
            ('C0_CLOCK','c0_ui_clk','CLK',dict(FREQ_HZ=133333333,ASSOCIATED_BUSIF='S0_AXI:S0_AXI_CTRL',
                ASSOCIATED_RESET='c0_aresetn:c0_ui_clk_sync_rst',CLK_DOMAIN='top_mig_7series_0_0_c0_ui_clk')),
            ('C0_RESET','c0_ui_clk_sync_rst','RST',dict(POLARITY='ACTIVE_HIGH')),
            ('C0_ARESETN','c0_aresetn','ARESETN',dict(POLARITY='ACTIVE_LOW')),
            ('SYSTEM_RESET','sys_rst','RST',dict(POLARITY='ACTIVE_LOW'))]:
            bus=ET.SubElement(buses,tag('busInterface'));ET.SubElement(bus,tag('name')).text=name
            mapping=ET.SubElement(ET.SubElement(bus,tag('portMaps')),tag('portMap'))
            ET.SubElement(ET.SubElement(mapping,tag('physicalPort')),tag('name')).text=physical
            ET.SubElement(ET.SubElement(mapping,tag('logicalPort')),tag('name')).text=logical
            params=ET.SubElement(bus,tag('parameters'))
            for key,val in fields.items():
                p=ET.SubElement(params,tag('parameter'));ET.SubElement(p,tag('name')).text=key
                ET.SubElement(p,tag('value')).text=str(val)
        return ET.tostring(root,encoding='unicode')

    def write(self,role,text):
        entry=self.reference['sources'][role]; path=self.root/entry['path']
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text)
        entry['sha256']=api.digest(path.read_bytes())

    def text(self,role):
        return (self.root/self.reference['sources'][role]['path']).read_text()

    def component(self):
        return ET.fromstring(self.text('component'))

    def port(self,root,name):
        return next(p for p in root.findall('s:model/s:ports/s:port',api.NS)
                    if p.findtext('s:name',namespaces=api.NS)==name)

    def write_component(self,root):
        self.write('component',ET.tostring(root,encoding='unicode'))

    def audit(self):
        return api.audit(self.root,self.reference)

    def test_consistent_synthetic_metadata_is_never_controller_admission(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No tool invocation')), \
             patch('socket.create_connection',side_effect=AssertionError('No network')):
            report=self.audit()
            self.assertEqual(api.verify(report,self.root,self.reference),report)
        self.assertEqual(report['interface_status'],'CONSISTENT_SOURCE_INTERFACE_ONLY')
        self.assertEqual(report['status'],'BLOCKED_DDR_INTEGRATION')
        self.assertEqual(report['controller_source_status'],'MISSING_GENERATED_CONTROLLER')
        self.assertFalse(report['controller_implementation_verified'])
        self.assertFalse(report['physical_integration_ready'])
        self.assertFalse(report['external_references_revalidated'])
        self.assertEqual(len(report['inputs']['files']),6)
        self.assertEqual(report['blockers'][1:],api.BLOCKERS)

    def test_original_ecc_conflict_shape_is_blocked(self):
        self.write('template','\n'.join(l for l in self.text('template').splitlines()
                                       if 'c0_app_ecc_single_err' not in l))
        root=self.component(); ports=root.find('s:model/s:ports',api.NS)
        ports.remove(self.port(root,'c0_app_ecc_single_err'))
        p=self.port(root,'c0_app_ecc_multiple_err')
        p.find('s:wire/s:vector/s:left',api.NS).text='3'
        enabled=p.find('s:vendorExtensions/x:portInfo/x:enablement/x:isEnabled',api.NS)
        enabled.text='false'; enabled.set('{'+api.XILINX+'}dependency',
            "spirit:decode(id('MODELPARAM_VALUE.C0_USE_AXI')) = 0")
        self.write_component(root); report=self.audit()
        self.assertIn('PORT_MISSING:c0_app_ecc_single_err',report['conflicts'])
        self.assertIn('PORT_DECLARATION_CONFLICT:c0_app_ecc_multiple_err',report['conflicts'])
        self.assertIn('COMPONENT_DISABLED_PORT:c0_app_ecc_multiple_err',report['conflicts'])
        self.assertIn('EXAMPLE_TEMPLATE_CONFLICT:c0_app_ecc_single_err',report['conflicts'])
        self.assertIn('ECC_PORT_METADATA_CONFLICT',report['blockers'])

    def test_missing_duplicate_and_misdeclared_ports(self):
        source=self.text('template'); line=source.splitlines()[1]
        for mutated in (source+'\n'+line,source.replace('// input','// mystery',1)):
            with self.subTest(mutated=mutated[-80:]):
                with self.assertRaises(ValueError): api.parse_template(mutated)
        self.write('template','\n'.join(l for l in source.splitlines() if not l.startswith('.c0_s_axi_awid(')))
        self.assertIn('TEMPLATE_REQUIRED_PORT:c0_s_axi_awid',self.audit()['conflicts'])
        root=self.component(); root.find('s:model/s:ports',api.NS).append(copy.deepcopy(self.port(root,'sys_rst')))
        with self.assertRaisesRegex(ValueError,'Duplicate component port'):
            api.parse_component(ET.tostring(root,encoding='unicode'))

    def test_width_direction_and_enable_cache_conflicts(self):
        root=self.component(); p=self.port(root,'c0_s_axi_awaddr')
        p.find('s:wire/s:vector/s:left',api.NS).text='31'
        p=self.port(root,'c0_ui_clk'); p.find('s:wire/s:direction',api.NS).text='in'
        p.find('s:vendorExtensions/x:portInfo/x:enablement/x:isEnabled',api.NS).text='false'
        self.write_component(root); report=self.audit()
        self.assertIn('COMPONENT_WIDTH_CACHE:c0_s_axi_awaddr',report['conflicts'])
        self.assertIn('PORT_DECLARATION_CONFLICT:c0_ui_clk',report['conflicts'])
        self.assertIn('COMPONENT_ENABLE_CACHE:c0_ui_clk',report['conflicts'])

    def test_unknown_expressions_fail_closed_without_evaluation(self):
        expressions=["__import__('os').system('false')",'0',
                     "spirit:decode(id('MODELPARAM_VALUE.MISSING')) = 1",
                     "1 = 0 and unrecognized(1)","1 = 1 or unrecognized(1)"]
        for expression in expressions:
            with self.subTest(expression=expression):
                root=self.component(); p=self.port(root,'c0_ui_clk')
                p.find('s:vendorExtensions/x:portInfo/x:enablement/x:isEnabled',api.NS).set(
                    '{'+api.XILINX+'}dependency',expression)
                with self.assertRaises(ValueError): api.parse_component(ET.tostring(root,encoding='unicode'))
        self.assertEqual(api.expression("(2 * spirit:decode(id('MODELPARAM_VALUE.R'))) - 1",{'R':4}),7)
        with self.assertRaises(ValueError): api.expression('3 / 2',{})

    def test_project_address_clock_reset_and_ecc_changes_are_blocked(self):
        original=self.text('project')
        for before,after,key in [('>31<','>32<','address_width'),('ACTIVE LOW','ACTIVE HIGH','sys_reset'),
                                 ('>Enabled<','>Disabled<','ecc'),('>200<','>50<','input_clock_mhz'),
                                 ('>4:1<','>2:1<','phy_ratio')]:
            with self.subTest(key=key):
                self.write('project',original.replace(before,after))
                self.assertIn('PROJECT_CONFIGURATION:'+key,self.audit()['conflicts'])
        with self.assertRaises(ValueError): api.parse_project(original.replace('number="1"','number="0"'))

    def test_reference_cannot_override_readiness_or_unsafe_contract(self):
        mutations=[('schema_version',True),('physical_integration_ready',True),('status','READY')]
        for key,value in mutations:
            candidate=copy.deepcopy(self.reference); candidate[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): api.audit(self.root,candidate)
        for section,key,val in [('profile','address_width',32),('profile','channel',False),
                                ('profile','supports_narrow_bursts',0),
                                ('reset_observations','joint_reset_ack_generated_port','c0_init_calib_complete'),
                                ('initialization','init_calib_complete_proves_allocated_memory_initialized',True),
                                ('ecc_observations','installed_templates_resolve_original_binding',True)]:
            candidate=copy.deepcopy(self.reference);candidate[section][key]=val
            with self.subTest(key=key),self.assertRaises(ValueError): api.audit(self.root,candidate)
        candidate=copy.deepcopy(self.reference);candidate['ports']['c0_ui_clk']['width']=True
        with self.assertRaises(ValueError):api.audit(self.root,candidate)

    def test_absent_placeholder_or_template_is_never_implementation(self):
        prior=self.audit(); ip=Path(self.reference['sources']['template']['path']).parent
        for entry in self.reference['missing_generated_sources']['referenced_by_file_list']:
            path=self.root/ip/entry['path'];path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('module placeholder; endmodule\n'+self.text('template'))
        report=self.audit()
        self.assertEqual(report['controller_source_status'],'PRESENT_UNQUALIFIED')
        self.assertFalse(report['controller_implementation_verified'])
        self.assertEqual(report['status'],'BLOCKED_DDR_INTEGRATION')
        with self.assertRaises(ValueError):api.verify(prior,self.root,self.reference)

    def test_source_and_report_tampering_are_rejected(self):
        report=self.audit()
        for key,value in [('status','READY'),('physical_integration_ready',True),('blockers',[])]:
            changed=copy.deepcopy(report);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):api.verify(changed,self.root,self.reference)
        path=self.root/self.reference['sources']['template']['path'];path.write_text(path.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Changed reference source'):self.audit()

    def test_duplicate_json_keys_entities_and_escaping_paths_rejected(self):
        for text in ('{"a":1,"a":2}','{"x":NaN}','{"x":{"a":1,"a":2}}'):
            path=self.root/'bad.json';path.write_text(text)
            with self.subTest(text=text),self.assertRaises(ValueError):api.load_json(path)
        with self.assertRaises(ValueError):api.xml('<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
        for name in ('../outside','/absolute','a/../b','.','a\\b'):
            with self.subTest(name=name),self.assertRaises(ValueError):api.safe_relative(name)
        path=self.root/self.reference['sources']['template']['path']; data=path.read_bytes();path.unlink()
        target=self.root/'outside.veo';target.write_bytes(data);path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'symlinked'):self.audit()

    def test_foreign_vector_and_unknown_resolve_are_rejected(self):
        root=self.component();wire=self.port(root,'c0_ui_clk').find('s:wire',api.NS)
        vector=ET.SubElement(wire,'{urn:bad}vector')
        ET.SubElement(vector,'{urn:bad}left').text='31';ET.SubElement(vector,'{urn:bad}right').text='0'
        with self.assertRaisesRegex(ValueError,'namespace/location'):
            api.parse_component(ET.tostring(root,encoding='unicode'))
        for mode in ('unexpected','user'):
            root=self.component();field=self.port(root,'c0_s_axi_awaddr').find('s:wire/s:vector/s:left',api.NS)
            field.set('{'+api.SPIRIT+'}resolve',mode)
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'resolve mode'):
                api.parse_component(ET.tostring(root,encoding='unicode'))
        root=self.component();field=self.port(root,'c0_ui_clk').find('s:vendorExtensions/x:portInfo/x:enablement/x:isEnabled',api.NS)
        field.set('{'+api.XILINX+'}resolve','unexpected')
        with self.assertRaisesRegex(ValueError,'resolve mode'):api.parse_component(ET.tostring(root,encoding='unicode'))

    def test_actual_clock_reset_bus_metadata_is_checked(self):
        original=self.text('component')
        for busname,key,new in [('C0_CLOCK','FREQ_HZ','50000000'),
            ('C0_CLOCK','ASSOCIATED_RESET','c0_init_calib_complete'),
            ('C0_CLOCK','ASSOCIATED_BUSIF','S1_AXI'),('C0_RESET','POLARITY','ACTIVE_LOW'),
            ('C0_ARESETN','POLARITY','ACTIVE_HIGH'),('SYSTEM_RESET','POLARITY','ACTIVE_HIGH')]:
            root=ET.fromstring(original)
            bus=next(n for n in root.findall('s:busInterfaces/s:busInterface',api.NS)
                     if n.findtext('s:name',namespaces=api.NS)==busname)
            p=next(n for n in bus.findall('s:parameters/s:parameter',api.NS)
                   if n.findtext('s:name',namespaces=api.NS)==key)
            p.find('s:value',api.NS).text=new;self.write_component(root)
            with self.subTest(bus=busname,key=key):
                self.assertIn('CLOCK_RESET_BINDING:'+busname,self.audit()['conflicts'])

    def test_wrong_module_and_additional_enabled_port_cannot_hide(self):
        original=self.text('template');self.write('template',original.replace('top_mig_7series_0_0','other_controller'))
        self.assertIn('TEMPLATE_MODULE',self.audit()['conflicts'])
        self.write('template',original)
        root=self.component();extra=copy.deepcopy(self.port(root,'c0_aresetn'))
        extra.find('s:name',api.NS).text='c0_unmodeled_reset'
        root.find('s:model/s:ports',api.NS).append(extra);self.write_component(root)
        self.assertIn('PORT_MISSING:c0_unmodeled_reset',self.audit()['conflicts'])
        enabled=extra.find('s:vendorExtensions/x:portInfo/x:enablement/x:isEnabled',api.NS)
        enabled.text='false';enabled.set('{'+api.XILINX+'}dependency',"spirit:decode(id('MODELPARAM_VALUE.C0_USE_AXI')) = 0")
        self.write_component(root)
        self.assertNotIn('PORT_MISSING:c0_unmodeled_reset',self.audit()['conflicts'])


if __name__ == '__main__':
    unittest.main()
