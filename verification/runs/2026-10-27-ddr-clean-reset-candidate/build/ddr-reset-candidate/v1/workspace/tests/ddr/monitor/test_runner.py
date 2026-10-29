"""Synthetic evidence/producer controls; no fixture is a native MIG result."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools.ddr import run_monitor as runner

WORKSPACE = Path(__file__).resolve().parents[3]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in runner.LOCAL:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(WORKSPACE/name,target)
        self.patch=patch.object(runner,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.output='build/fixture';self.producer=Path('/original/producer')
        self.policy=runner.load_json(self.root/'tests/ddr/vendor_warnings.json')
        members={};self.bodies={}
        for name in runner.CONTROL:
            member='synthetic/axi/'+name;data=('// synthetic verifier fixture '+name+'\n').encode()
            self.bodies[member]=data;members[member]=dict(sha256=hashlib.sha256(data).hexdigest())
        self.archive=self.root/'synthetic.zip'
        with zipfile.ZipFile(self.archive,'w') as archive:
            for name,data in self.bodies.items():archive.writestr(name,data)
        archive_sha=runner.digest(self.archive)
        catalog=dict(archive=dict(sha256=archive_sha),members=members)
        self.write('fpga/ddr/xdma_archive_reference.json',json.dumps(catalog))
        contract=dict(catalog=dict(sha256=runner.digest(self.root/'fpga/ddr/xdma_archive_reference.json'),archive_sha256=archive_sha),
            control_leaf_parameters=dict(values=runner.PARAMETERS),physical_integration_ready=False,controller_simulated=False,
            sources={str(i):dict(member=n,sha256=v['sha256']) for i,(n,v) in enumerate(members.items())})
        self.write('fpga/ddr/xdma_lifecycle_contract.json',json.dumps(contract))
        self.policy['vendor_source_sha256']={Path(n).name:v['sha256'] for n,v in members.items()}
        self.write('tests/ddr/vendor_warnings.json',json.dumps(self.policy))

    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        return p

    def diagnostics_text(self,items,simulator):
        lines=[]
        for item in items:
            if simulator=='verilator':
                lines.append(f"%Warning-{item['code']}: /synthetic/{item['file']}:{item['line']}:{item['column']}: {item['message']}")
            else:lines.append(f"/synthetic/{item['file']}:{item['line']}: {item['message']}")
        return '\n'.join(lines)+'\n'

    def fixture(self,simulator='iverilog',vendor=True):
        tools={role:dict(path='/fixture/bin/'+name,sha256=hashlib.sha256(name.encode()).hexdigest())
               for role,name in [('simulator',simulator),('runtime','vvp')] if simulator=='iverilog'}
        if simulator=='verilator':
            tools={role:dict(path='/fixture/bin/'+name,sha256=hashlib.sha256(name.encode()).hexdigest())
                   for role,name in [('simulator','verilator'),('cxx','c++')]}
        profile_names=['portable','vendor'] if vendor else ['portable']
        plan=runner.vendor_plan(self.output,self.policy) if vendor else dict(files={},compiled=[])
        if vendor:
            for name,member in plan['members'].items():self.write(name,self.bodies[member].decode())
            self.write(plan['header_name'],plan['header'])
        source=runner.source_revision();inputs=runner.manifest(source['files']|plan['files'])
        report=dict(status='PASS_ECC_MONITOR_CONTROL_ONLY',execution_schema=2,source=source,scope=runner.SCOPE,
            simulator=simulator,vendor_control_test=vendor,execution_root=str(self.producer),output_directory=self.output,
            tools=tools,commands=[],tests=[],execution_inputs=inputs,
            vivado_executed=False,vendor_ip_executed=False,hardware_accessed=False,controller_simulated=False,
            memory_retirement_verified=False,electrical_profile_adopted=False,
            tool_version=self.policy[simulator+'_version'])
        if vendor:report['archive_sha256']=plan['archive_sha256']
        artifacts=set(plan['files'])
        def command(name,argv,executable,text):
            log=str(Path(self.output)/(name+'.log'));self.write(log,text);artifacts.add(log)
            c=dict(name=name,argv=argv,status='PASS',returncode=0,log=log,log_sha256=runner.digest(self.root/log),
                executable_before=executable,executable_after=executable,environment_overrides=runner.ENVIRONMENT)
            report['commands'].append(c);return c
        for name,argv,role in runner.version_plan(simulator,tools):
            field={'simulator':'tool_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
            version=report['tool_version'] if role=='simulator' else 'synthetic '+role+' version'
            report[field]=version;command(name,argv,tools[role],version+'\n')
        for name in profile_names:
            p=runner.profile_plan(simulator,name,self.producer,self.output,tools,plan['compiled'] if name=='vendor' else ())
            self.write(p['image'],'synthetic compiled image '+simulator+name);artifacts.add(p['image'])
            image=dict(path=p['image'],sha256=runner.digest(self.root/p['image']))
            warnings=self.policy[simulator] if name=='vendor' else (self.policy['portable_iverilog'] if simulator=='iverilog' else [])
            build=command(name+'-build',p['build'],tools['simulator'],self.diagnostics_text(warnings,simulator))
            build.update(admitted_diagnostics=warnings,output_image=image,inputs_before=inputs,inputs_after=inputs)
            executable=tools['runtime'] if simulator=='iverilog' else dict(path=str(self.producer/p['image']),sha256=image['sha256'])
            run=command(name+'-run',p['run'],executable,p['result']+'\n')
            run.update(image=image['path'],image_sha256_before=image['sha256'],image_sha256_after=image['sha256'],
                       inputs_before=inputs,inputs_after=inputs)
            report['tests'].append(dict(name=name,status='PASS',result=p['result'],image=image['path'],image_sha256=image['sha256']))
        report['artifacts']=runner.fingerprint([self.root/n for n in artifacts])
        return report

    def verify(self,report):
        path=self.write('control-report.json',json.dumps(report));return runner.verify_report(path)

    def test_copied_verification_needs_no_tools_or_original_archive(self):
        for simulator in ('iverilog','verilator'):
            for vendor in (False,True):
                with self.subTest(simulator=simulator,vendor=vendor):
                    report=self.fixture(simulator,vendor)
                    with patch('subprocess.run',side_effect=AssertionError('No external execution')):
                        self.assertEqual(self.verify(report)['status'],'VERIFIED_ECC_MONITOR_CONTROL_ONLY')

    def test_version_commands_inventory_and_log_linkage(self):
        report=self.fixture()
        variants=[]
        changed=copy.deepcopy(report);changed['commands']=changed['commands'][2:];variants.append(changed)
        changed=copy.deepcopy(report);changed['commands'].insert(0,copy.deepcopy(changed['commands'][0]));variants.append(changed)
        changed=copy.deepcopy(report);changed['runtime_version']='unbound runtime';variants.append(changed)
        changed=copy.deepcopy(report);changed['commands'][0]['log_sha256']='0'*64;variants.append(changed)
        for changed in variants:
            with self.subTest(index=variants.index(changed)),self.assertRaises(ValueError):self.verify(changed)

    def test_exact_build_output_include_flags_and_run_executable(self):
        for simulator in ('iverilog','verilator'):
            report=self.fixture(simulator)
            for kind in ('build_executable','output','include','run_executable','extra_flag','image_binding',
                         'parameter_macro_path','parameter_macro_missing'):
                changed=copy.deepcopy(report)
                build=next(c for c in changed['commands'] if c['name']=='vendor-build')
                run=next(c for c in changed['commands'] if c['name']=='vendor-run')
                if kind=='build_executable':build['argv'][0]='/bin/true'
                elif kind=='output':build['argv'][build['argv'].index('-o')+1]='/unrelated/image'
                elif kind=='include':
                    i=next(i for i,a in enumerate(build['argv']) if a.startswith('-I'));build['argv'][i]='-I/unrelated'
                elif kind=='run_executable':run['argv'].insert(0,'/bin/echo')
                elif kind=='extra_flag':build['argv'].insert(1,'-DFAKE_PASS')
                elif kind=='image_binding':build['output_image']['sha256']='0'*64
                else:
                    i=next(i for i,a in enumerate(build['argv']) if a.startswith('-DRK_MIG_ECC_PARAMS_HEADER='))
                    if kind=='parameter_macro_missing':del build['argv'][i]
                    else:build['argv'][i]='-DRK_MIG_ECC_PARAMS_HEADER="monitor_vendor_params.svh"'
                with self.subTest(simulator=simulator,kind=kind),self.assertRaises(ValueError):self.verify(changed)

    def test_parameter_header_cannot_be_omitted_or_rewritten(self):
        report=self.fixture();name=str(Path(self.output)/'monitor_vendor_params.svh')
        changed=copy.deepcopy(report);del changed['artifacts']['files'][name]
        changed['artifacts']=runner.manifest(changed['artifacts']['files'])
        with self.assertRaises(ValueError):self.verify(changed)
        self.write(name,(self.root/name).read_text().replace('.C_NCK_PER_CLK(4)','.C_NCK_PER_CLK(2)'))
        report['artifacts']['files'][name]=runner.digest(self.root/name)
        report['artifacts']=runner.manifest(report['artifacts']['files'])
        with self.assertRaisesRegex(ValueError,'input changed'):self.verify(report)

    def test_extracted_source_and_before_after_boundaries(self):
        report=self.fixture();changed=copy.deepcopy(report)
        next(c for c in changed['commands'] if c['name']=='vendor-build')['inputs_after']=runner.manifest({})
        with self.assertRaises(ValueError):self.verify(changed)
        name=next(n for n in report['execution_inputs']['files'] if '/vendor/' in n)
        self.write(name,(self.root/name).read_text()+'// changed during compiler run\n')
        with self.assertRaisesRegex(ValueError,'input changed'):runner.check_inputs(report['execution_inputs'])
        with self.assertRaises(ValueError):self.verify(report)

    def test_image_hashes_and_execution_result_cannot_be_replaced(self):
        report=self.fixture()
        for key in ('image_sha256_before','image_sha256_after'):
            changed=copy.deepcopy(report);next(c for c in changed['commands'] if c['name']=='vendor-run')[key]='0'*64
            with self.subTest(key=key),self.assertRaises(ValueError):self.verify(changed)
        image=report['tests'][0]['image'];self.write(image,'replacement image')
        with self.assertRaises(ValueError):self.verify(report)

    def test_unknown_warning_and_physical_claims_are_rejected(self):
        report=self.fixture('verilator');changed=copy.deepcopy(report);changed['controller_simulated']=True
        with self.assertRaises(ValueError):self.verify(changed)
        build=next(c for c in report['commands'] if c['name']=='vendor-build');path=self.root/build['log']
        path.write_text(path.read_text()+'%Warning-NEW: /source/rk_mig_ecc_monitor.sv:1:1: New warning\n')
        build['log_sha256']=runner.digest(path);report['artifacts']['files'][build['log']]=runner.digest(path)
        report['artifacts']=runner.manifest(report['artifacts']['files'])
        with self.assertRaisesRegex(ValueError,'Warning admission'):self.verify(report)

    def test_producer_rejects_input_mutation_during_compile(self):
        binaries=self.root/'bin';binaries.mkdir()
        for name in ('iverilog','vvp'):(binaries/name).write_text('synthetic executable identity')
        output=self.root/'build/producer-mutation'
        def execute(argv,**kwargs):
            if argv[-1]=='-V':kwargs['stdout'].write(self.policy['iverilog_version']+'\n')
            else:
                Path(argv[argv.index('-o')+1]).write_text('synthetic image')
                header=output/'monitor_vendor_params.svh';header.write_text(header.read_text()+'// mutated\n')
            return SimpleNamespace(returncode=0)
        argv=['run_monitor.py','--simulator','iverilog','--archive',str(self.archive),'--out',str(output)]
        with patch('sys.argv',argv),patch('shutil.which',side_effect=lambda n:str(binaries/n)), \
             patch('subprocess.run',side_effect=execute),self.assertRaisesRegex(ValueError,'input changed'):
            runner.main()
        report=runner.load_json(output/'report.json')
        self.assertEqual(report['status'],'FAIL')
        self.assertNotIn('portable-run',[c['name'] for c in report['commands']])

    def test_absolute_parameter_include_beats_real_iverilog_shadows(self):
        compiler=shutil.which('iverilog');runtime=shutil.which('vvp')
        if compiler is None or runtime is None:self.skipTest('Icarus/vvp unavailable for native include-precedence control')
        output='build/owned headers with spaces';directory=self.root/output;directory.mkdir(parents=True)
        source_dir=self.root/'source shadow';source_dir.mkdir()
        cwd=self.root/'cwd shadow';cwd.mkdir()
        (directory/'monitor_vendor_params.svh').write_text('.SELECTED(1)\n')
        (source_dir/'monitor_vendor_params.svh').write_text('.SELECTED(3)\n')
        (cwd/'monitor_vendor_params.svh').write_text('.SELECTED(2)\n')
        include=next(line for line in (WORKSPACE/'tests/ddr/tb_mig_ecc_vendor.sv').read_text().splitlines()
                     if line.startswith('`include'))
        self.assertEqual(include,'`include `RK_MIG_ECC_PARAMS_HEADER')
        source=source_dir/'probe.sv'
        source.write_text('module leaf #(parameter SELECTED=0)();\n'
            'initial begin if (SELECTED!=1) $fatal(1,"SHADOW_HEADER"); '
            '$display("PASS BOUND_ABSOLUTE_HEADER"); $finish; end endmodule\n'
            'module probe; leaf #(\n'+include+'\n) selected(); endmodule\n')
        binary=directory/'probe.vvp'
        base=[compiler,'-g2012','-s','probe','-I',str(directory),'-o',str(binary)]
        macro=runner.parameter_include(self.root,output)
        built=subprocess.run(base+[macro,str(source)],cwd=cwd,text=True,capture_output=True,timeout=20)
        self.assertEqual(built.returncode,0,built.stdout+built.stderr)
        ran=subprocess.run([runtime,str(binary)],cwd=cwd,text=True,capture_output=True,timeout=20)
        self.assertEqual(ran.returncode,0,ran.stdout+ran.stderr)
        self.assertIn('PASS BOUND_ABSOLUTE_HEADER',ran.stdout)
        missing=subprocess.run(base+[str(source)],cwd=cwd,text=True,capture_output=True,timeout=20)
        self.assertNotEqual(missing.returncode,0,'Missing parameter macro unexpectedly compiled')
        self.assertIn('RK_MIG_ECC_PARAMS_HEADER',missing.stdout+missing.stderr)
        for unsafe in ('build/quoted"path','build/back\\slash','build/new\nline'):
            with self.subTest(path=unsafe),self.assertRaises(ValueError):runner.parameter_include(self.root,unsafe)


if __name__=='__main__':unittest.main()
