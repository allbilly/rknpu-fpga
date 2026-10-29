"""Synthetic execution-record controls; these fixtures are not MC simulations."""
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

from tools.ddr import qualify_fence_order as q

WORKSPACE=Path(__file__).resolve().parents[3]


def trace(mode):
    full=mode>=6;negative=mode in (1,7)
    addresses={4:(2,0,8),1:(1 if mode in (2,3) else 0,0,0),
               2:(1,1 if mode==2 else 0,0 if mode==3 else 8),
               3:(2 if negative else 1,1 if mode==2 else 0,0 if mode==3 else 8)}
    lines=[]
    for tag,cycle in ((4,10),(1,40),(2,50),(3,60)):
        b,r,c=addresses[tag];lines.append(f'TRACE ACCEPT cycle={cycle} tag={tag} bank={b} row={r} col={c} op={1 if tag in (3,4) else 0 if full else 3}')
    columns=[(20,4,1,0),(110,1,0,0),(120,2,0,0),(85 if negative else 130,3,1,0)]
    if not full:columns += [(70,1,1,1),(80,2,1,1)]
    for cycle,tag,read,rmw in sorted(columns):
        b,r,c=addresses[tag];lines.append(f'TRACE COLUMN cycle={cycle} tag={tag} bank={b} row={r} col={c} read={read} rmw={rmw}')
    returns=[(30,4,0),(101 if negative else 140,3,0)]
    if not full:returns += [(90,1,1),(100,2,1)]
    for cycle,tag,rmw in sorted(returns):
        lines.append(f'TRACE PHY cycle={cycle} tag={tag} rmw={rmw} periodic=0')
    if full:lines += ['TRACE FULL_WRITE_DATA cycle=111 data=0 mask=0','TRACE FULL_WRITE_DATA cycle=121 data=0 mask=0']
    fence=102 if negative else 141
    lines+=['TRACE RESPONSE cycle=31 tag=4',f'TRACE RESPONSE cycle={fence} tag=3',
            f'PASS mig_fence_order mode={mode} accepted=4 read_columns={2 if full else 4} write_columns=2 phy_returns={2 if full else 4} native_returns=2 w1=110 w2=120 rmw2={0 if full else 100} fence={fence} ue={1 if mode==5 else 0} scope=actual_MC_modeled_PHY_only']
    return '\n'.join(lines)+'\n'


def arbiter_trace(name):
    if name=='arbiter-original-one':return 'FATAL: synthetic fixture WIDTH1_UNDRIVEN_INHIBIT_GROUP\n'
    widths=[2,3,4] if name=='arbiter-original-multi' else [1,2,3,4];lines=[]
    for width in widths:
        last=width-1
        for step in range(128):
            req=((step*13)^(step>>2))&((1<<width)-1);rst=int(step%31==0);disable=int(step%7==3);update=int(step%3!=0)
            current=1<<(step%width);basis=width-1 if rst else step%width if update else last;grant=0
            for offset in range(1,width+1):
                index=(basis+offset)%width
                if not disable and not grant and req&(1<<index):grant=1<<index
            last=basis
            lines.append(f'TRACE ARBITER width={width} step={step} req={req:x} reset={rst} disable={disable} update={update} current={current:x} grant={grant:x} registered={grant:x}')
    return '\n'.join(lines)+f'\nPASS round_robin_width widths={len(widths)} cases_per_width=128 scope=actual_arbiter_only\n'


class QualifierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in q.LOCAL:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WORKSPACE/name,p)
        p=patch.object(q,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.output='build/fixture';self.producer=Path('/original/producer')
        models={name:('// synthetic '+name).encode() for name in q.PRIMITIVES}
        p=patch.object(q,'PRIMITIVES',{k:hashlib.sha256(v).hexdigest() for k,v in models.items()});p.start();self.addCleanup(p.stop)
        self.models=models
        derived={'BM_CNT_WIDTH','DATA_BUF_OFFSET_WIDTH','ECC_WIDTH','MC_ERR_ADDR_WIDTH','PAYLOAD_WIDTH',
                 'RANK_WIDTH','nSLOTS','SLOT_0_CONFIG','SLOT_1_CONFIG'}
        defaults={'MAINT_PRESCALER_PERIOD','nREFRESH_BANK','DRAM_TYPE'}
        core='\n'.join('parameter '+('' if k=='STARVE_LIMIT' else 'C0_')+k+' = '+json.dumps(v)+';'
                       for k,v in q.PARAMETERS.items() if k not in derived|defaults)
        core+='\nparameter C0_SLOT_1_CONFIG=0;\nlocalparam C0_DATA_BUF_OFFSET_WIDTH = 1;\n'
        core+='localparam C0_MC_ERR_ADDR_WIDTH = ((C0_CS_WIDTH == 1) ? 0 : C0_RANK_WIDTH);\n'
        mc='\n'.join('parameter '+k+' = '+json.dumps(q.PARAMETERS[k])+';' for k in defaults)
        interface="localparam SLOT_0_CONFIG_MC = (nSLOTS == 2)? 8'b0000_0101 : 8'b0000_1111;\n"
        prefix='fixture/';base='top_mig_7series_0_0/user_design/rtl/'
        self.bodies={prefix+base+'top_mig_7series_0_0_mig.v':core.encode(),
                     prefix+base+'controller/mig_7series_v4_2_mc.v':mc.encode(),
                     prefix+base+'ip_top/mig_7series_v4_2_mem_intfc.v':interface.encode()}
        variant=q.load_json(self.root/'fpga/ddr/patches/round_robin_width_one.json')
        variant['member']=prefix+base+'controller/mig_7series_v4_2_round_robin_arb.v'
        original=('// synthetic verifier fixture\n'+variant['replace_once']['old']).encode()
        patched=original.replace(variant['replace_once']['old'].encode(),variant['replace_once']['new'].encode())
        self.bodies[variant['member']]=original;variant['archive_sha256']='a'*64
        variant['original_sha256']=hashlib.sha256(original).hexdigest();variant['patched_sha256']=hashlib.sha256(patched).hexdigest()
        self.write('fpga/ddr/patches/round_robin_width_one.json',json.dumps(variant))
        catalog=dict(member_prefix=prefix,archive={'sha256':'a'*64},members={
            name:dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)) for name,data in self.bodies.items()})
        self.write('fpga/ddr/xdma_archive_reference.json',json.dumps(catalog))
        contract=dict(catalog=dict(sha256=q.sha(self.root/'fpga/ddr/xdma_archive_reference.json'),archive_sha256='a'*64))
        self.write('fpga/ddr/xdma_retirement_contract.json',json.dumps(contract))
        plan=q.expected_inputs(self.output)
        files={Path(name).name:sha for name,sha in plan['files'].items() if name in plan['compiled']}
        self.policy=dict(review_status='REVIEWED_FOR_BOUNDED_MC_MODEL',compiled_source_sha256=files,
            bench_sha256=q.sha(self.root/'tests/ddr/tb_mig_fence_order.sv'),
            arbiter_bench_sha256=q.sha(self.root/'tests/ddr/fence_mc/tb_round_robin_width.sv'),
            arbiter_helper_sha256=q.sha(self.root/'tests/ddr/fence_mc/check_round_robin.sv'),
            original_arbiter_sha256=variant['original_sha256'],
            iverilog_version='synthetic Icarus version',verilator_version='synthetic Verilator version',
            iverilog=[],verilator=[],arbiter={s:{n:[] for n in ('arbiter-original-multi','arbiter-variant','arbiter-original-one')}
                                            for s in ('iverilog','verilator')})
        self.write('tests/ddr/fence_mc/warnings.json',json.dumps(self.policy))

    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p

    def fixture(self,simulator='iverilog'):
        plan=q.expected_inputs(self.output)
        for member,name in plan['members'].items():self.write(name,self.bodies[member].decode())
        for name,data in self.models.items():self.write(str(Path(self.output)/'primitives'/name),data.decode())
        variant=q.load_json(self.root/'fpga/ddr/patches/round_robin_width_one.json')
        self.write(plan['variant']['derived'],q.apply_variant(self.bodies[variant['member']],variant).decode())
        self.write(plan['header_name'],plan['header'])
        tools={role:dict(path='/synthetic/bin/'+name,sha256=hashlib.sha256(name.encode()).hexdigest())
               for role,name in [('simulator',simulator),('runtime','vvp')]}
        if simulator=='verilator':tools.pop('runtime');tools['cxx']=dict(path='/synthetic/bin/c++',sha256='c'*64)
        source=q.source_revision();inputs=q.manifest(source['files']|plan['files'])
        report=dict(schema_version=3,status='PASS_ACTUAL_MC_MODELED_PHY_ORDERING_CASES',complete_matrix=True,
            source=source,scope=q.SCOPE,parameters=q.PARAMETERS,actual_mc_source_variant_simulated=True,
            original_controller_qualified=False,
            controller_phy_simulated=False,axi_ui_bridge_simulated=False,hardware_accessed=False,
            vivado_executed=False,vendor_ip_generated=False,physical_integration_ready=False,
            joint_reset_drain_verified=False,seed=None,stimuli='Directed; no PRNG',simulator=simulator,
            output_directory=self.output,execution_root=str(self.producer),tools=tools,commands=[],tests=[],arbiter_controls=[],
            source_variant=plan['variant'],
            archive_sha256=plan['archive_sha256'],archive_members=plan['members'],execution_inputs=inputs)
        artifacts=set(plan['files'])
        def command(name,argv,executable,text,expected=0):
            log=str(Path(self.output)/(name+'.log'));self.write(log,text);artifacts.add(log)
            item=dict(name=name,argv=argv,environment_overrides=q.ENVIRONMENT,returncode=expected,expected_returncode=expected,
                status='PASS' if expected==0 else 'EXPECTED_FAILURE',
                executable_before=executable,executable_after=executable,log=log,log_sha256=q.sha(self.root/log))
            report['commands'].append(item);return item
        for name,argv,role in q.version_plan(simulator,tools):
            field={'simulator':'simulator_version','runtime':'runtime_version','cxx':'cxx_version'}[role]
            report[field]=self.policy[simulator+'_version'] if role=='simulator' else 'synthetic '+role
            command(name,argv,tools[role],report[field]+'\n')
        for name,arb in q.arbiter_plans(simulator,self.producer,self.output,tools,plan['variant']).items():
            self.write(arb['image'],'synthetic arbiter image');artifacts.add(arb['image'])
            image=dict(path=arb['image'],sha256=q.sha(self.root/arb['image']))
            item=command(name+'-build',arb['build'],tools['simulator'],'')
            item.update(inputs_before=inputs,inputs_after=inputs,output_image=image,admitted_diagnostics=[])
            executable=tools['runtime'] if simulator=='iverilog' else dict(path=str(self.producer/arb['image']),sha256=image['sha256'])
            text=arbiter_trace(name);item=command(name+'-run',arb['run'],executable,text,arb['expected_returncode'])
            item.update(inputs_before=inputs,inputs_after=inputs,image=image['path'],image_before=image['sha256'],image_after=image['sha256'])
            report['arbiter_controls'].append(q.validate_arbiter(text,name)[0])
        build=q.compile_plan(simulator,self.producer,self.output,tools,plan['compiled'])
        self.write(build['image'],'synthetic image');artifacts.add(build['image'])
        image=dict(path=build['image'],sha256=q.sha(self.root/build['image']));report['binary_sha256']=image['sha256']
        item=command('build',build['build'],tools['simulator'],'')
        item.update(inputs_before=inputs,inputs_after=inputs,output_image=image,admitted_diagnostics=[])
        for mode in q.MODES:
            executable=tools['runtime'] if simulator=='iverilog' else dict(path=str(self.producer/image['path']),sha256=image['sha256'])
            text=trace(mode);item=command('mode'+str(mode),build['run']+['+MODE='+str(mode)],executable,text)
            item.update(inputs_before=inputs,inputs_after=inputs,image=image['path'],image_before=image['sha256'],image_after=image['sha256'])
            report['tests'].append(q.validate_result(text,mode))
        report['artifacts']=q.fingerprints([self.root/n for n in artifacts]);return report

    def test_copied_records_need_no_original_archive_or_tools(self):
        for simulator in ('iverilog','verilator'):
            with self.subTest(simulator=simulator),patch('subprocess.run',side_effect=AssertionError('No execution')):
                self.assertEqual(q.verify_record(self.fixture(simulator))['modes'],list(q.MODES))

    def test_command_version_compile_and_image_binding(self):
        for simulator in ('iverilog','verilator'):
            report=self.fixture(simulator)
            for kind in ('missing_version','compiler','output','header','relative_header','runtime','cxx','image'):
                if kind=='cxx' and simulator=='iverilog':continue
                mutant=copy.deepcopy(report);built=next(c for c in mutant['commands'] if c['name']=='build');ran=next(c for c in mutant['commands'] if c['name']=='mode0')
                if kind=='missing_version':mutant['commands'].pop(0)
                elif kind=='compiler':built['argv'][0]='/bin/true'
                elif kind=='output':built['argv'][built['argv'].index('-o')+1]='other'
                elif kind in ('header','relative_header'):
                    i=next(i for i,a in enumerate(built['argv']) if a.startswith('-DRK_MIG_MC_PARAMS_HEADER='))
                    if kind=='header':built['argv'].pop(i)
                    else:built['argv'][i]='-DRK_MIG_MC_PARAMS_HEADER="mc_parameters.svh"'
                elif kind=='runtime':ran['argv'].insert(0,'/bin/echo')
                elif kind=='cxx':built['argv'][built['argv'].index('-MAKEFLAGS')+1]='CXX=/other/c++'
                else:ran['image_after']='0'*64
                with self.subTest(simulator=simulator,kind=kind),self.assertRaises(ValueError):q.verify_record(mutant)
            mutant=copy.deepcopy(report);mutant['execution_root']='relative-producer'
            for c in mutant['commands']:c['argv']=[a.replace(str(self.producer),'relative-producer') for a in c['argv']]
            with self.assertRaisesRegex(ValueError,'Producer root'):q.verify_record(mutant)
            mutant=copy.deepcopy(report);old=mutant['tools']['simulator'];new=dict(path='/bin/true',sha256='0'*64)
            mutant['tools']['simulator']=new
            for c in mutant['commands']:
                if c['argv'][0]==old['path']:
                    c['argv'][0]=new['path'];c['executable_before']=new;c['executable_after']=new
            with self.assertRaisesRegex(ValueError,'Tool executable'):q.verify_record(mutant)

    def test_header_sources_and_boundary_manifests(self):
        report=self.fixture();mutant=copy.deepcopy(report);next(c for c in mutant['commands'] if c['name']=='build')['inputs_after']=q.manifest({})
        with self.assertRaises(ValueError):q.verify_record(mutant)
        plan=q.expected_inputs(self.output);self.write(plan['header_name'],plan['header'].replace('.nCK_PER_CLK(4)','.nCK_PER_CLK(2)'))
        with self.assertRaises(ValueError):q.verify_record(report)
        report=self.fixture();self.write(plan['compiled'][0],'changed source')
        with self.assertRaises(ValueError):q.verify_record(report)

    def test_partial_modes_or_expanded_claims_are_rejected(self):
        report=self.fixture()
        for key,value in [('complete_matrix',False),('schema_version',1),('schema_version',2),('physical_integration_ready',True),
                          ('axi_ui_bridge_simulated',True),('joint_reset_drain_verified',True),('original_controller_qualified',True)]:
            mutant=copy.deepcopy(report);mutant[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):q.verify_record(mutant)
        mutant=copy.deepcopy(report);mutant['tests'].pop()
        with self.assertRaises(ValueError):q.verify_record(mutant)
        mutant=copy.deepcopy(report);mutant['arbiter_controls'].pop()
        with self.assertRaises(ValueError):q.verify_record(mutant)
        mutant=copy.deepcopy(report);mutant['source_variant']['patched_sha256']='0'*64
        with self.assertRaises(ValueError):q.verify_record(mutant)

    def test_actual_trace_must_support_summary(self):
        original=trace(0)
        for changed in (original.replace('TRACE COLUMN cycle=130 tag=3','TRACE COLUMN cycle=100 tag=3'),
                        original.replace('TRACE PHY cycle=100 tag=2','TRACE PHY cycle=50 tag=2'),
                        original.replace('TRACE ACCEPT cycle=60 tag=3 bank=1','TRACE ACCEPT cycle=60 tag=3 bank=2'),
                        original.replace('w2=120','w2=119'),original.replace('accepted=4','accepted=0')):
            with self.subTest(changed=changed[-90:]),self.assertRaises(ValueError):q.validate_result(changed,0)
        with self.assertRaises(ValueError):q.validate_result(trace(5).replace('ue=1','ue=2'),5)
        for changed in (trace(6).replace('op=0','op=3'),trace(6).replace(' data=0 mask=0',' data=0 mask=1'),
                        trace(6).replace('TRACE FULL_WRITE_DATA cycle=121 data=0 mask=0\n',''),
                        trace(6).replace('FULL_WRITE_DATA cycle=111','FULL_WRITE_DATA cycle=150').replace('FULL_WRITE_DATA cycle=121','FULL_WRITE_DATA cycle=151'),
                        trace(6).replace('FULL_WRITE_DATA cycle=111','FULL_WRITE_DATA cycle=100'),
                        trace(6).replace('rmw2=0','rmw2=100')):
            with self.subTest(full_write_mutation=changed[-100:]),self.assertRaises(ValueError):q.validate_result(changed,6)
        with self.assertRaises(ValueError):q.validate_arbiter(arbiter_trace('arbiter-original-one')+'FATAL: unrelated failure\n','arbiter-original-one')

    def test_artifact_log_and_warning_replacement(self):
        report=self.fixture('verilator');mutant=copy.deepcopy(report)
        del mutant['artifacts']['files'][mutant['commands'][0]['log']]
        mutant['artifacts']=q.manifest(mutant['artifacts']['files'])
        with self.assertRaises(ValueError):q.verify_record(mutant)
        built=next(c for c in report['commands'] if c['name']=='build');self.write(built['log'],'%Warning-NEW: /source/tb_mig_fence_order.sv:1:1: unexpected\n')
        built['log_sha256']=q.sha(self.root/built['log']);report['artifacts']['files'][built['log']]=built['log_sha256']
        report['artifacts']=q.manifest(report['artifacts']['files'])
        with self.assertRaisesRegex(ValueError,'Warning'):q.verify_record(report)

    def test_parameter_source_defaults_cannot_replace_c0(self):
        original=self.bodies['fixture/top_mig_7series_0_0/user_design/rtl/top_mig_7series_0_0_mig.v'].decode()
        mc=self.bodies['fixture/top_mig_7series_0_0/user_design/rtl/controller/mig_7series_v4_2_mc.v'].decode()
        interface=self.bodies['fixture/top_mig_7series_0_0/user_design/rtl/ip_top/mig_7series_v4_2_mem_intfc.v'].decode()
        q.check_parameters(original,mc,interface)
        for old,new in [('C0_nCK_PER_CLK = 4','C0_nCK_PER_CLK = 2'),('C0_ROW_WIDTH = 15','C0_ROW_WIDTH = 14')]:
            with self.subTest(field=old),self.assertRaises(ValueError):q.check_parameters(original.replace(old,new),mc,interface)

    def test_required_absolute_macro_beats_native_header_shadows(self):
        compiler=shutil.which('iverilog');runtime=shutil.which('vvp')
        if not compiler or not runtime:self.skipTest('Icarus/vvp unavailable')
        output='build/owned headers';directory=self.root/output;directory.mkdir(parents=True)
        cwd=self.root/'other';cwd.mkdir();self.write(str(Path(output)/'mc_parameters.svh'),'.VALUE(1)\n')
        self.write('other/mc_parameters.svh','.VALUE(2)\n')
        include=next(l for l in (WORKSPACE/'tests/ddr/tb_mig_fence_order.sv').read_text().splitlines() if l.startswith('`include'))
        self.assertEqual(include,'`include `RK_MIG_MC_PARAMS_HEADER')
        source=self.write('other/probe.sv','module leaf #(parameter VALUE=0)(); initial begin if(VALUE!=1)$fatal; $display("BOUND");$finish;end endmodule\nmodule probe; leaf #(\n'+include+'\n) x(); endmodule\n')
        image=directory/'sim';base=[compiler,'-g2012','-s','probe','-o',str(image)]
        built=subprocess.run(base+[q.parameter_include(self.root,output),str(source)],cwd=cwd,capture_output=True,text=True)
        self.assertEqual(built.returncode,0,built.stderr)
        ran=subprocess.run([runtime,str(image)],cwd=cwd,capture_output=True,text=True);self.assertEqual(ran.returncode,0,ran.stdout)
        self.assertIn('BOUND',ran.stdout)
        missing=subprocess.run(base+[str(source)],cwd=cwd,capture_output=True,text=True);self.assertNotEqual(missing.returncode,0)

    def test_producer_rejects_header_mutation_before_running_image(self):
        archive=self.root/'fixture.zip'
        with zipfile.ZipFile(archive,'w') as bundle:
            for name,data in self.bodies.items():bundle.writestr(name,data)
        catalog=q.load_json(self.root/'fpga/ddr/xdma_archive_reference.json');catalog['archive']['sha256']=q.sha(archive)
        self.write('fpga/ddr/xdma_archive_reference.json',json.dumps(catalog))
        contract=dict(catalog=dict(sha256=q.sha(self.root/'fpga/ddr/xdma_archive_reference.json'),archive_sha256=q.sha(archive)))
        self.write('fpga/ddr/xdma_retirement_contract.json',json.dumps(contract))
        variant=q.load_json(self.root/'fpga/ddr/patches/round_robin_width_one.json');variant['archive_sha256']=q.sha(archive)
        self.write('fpga/ddr/patches/round_robin_width_one.json',json.dumps(variant))
        library=self.root/'primitive-library';library.mkdir()
        for name,data in self.models.items():(library/name).write_bytes(data)
        binaries=self.root/'bin';binaries.mkdir()
        for name in ('iverilog','vvp'):(binaries/name).write_text('synthetic executable identity')
        output=self.root/'build/producer-mutation'
        def execute(argv,**kwargs):
            if argv[-1]=='-V':kwargs['stdout'].write(self.policy['iverilog_version']+'\n')
            else:
                Path(argv[argv.index('-o')+1]).write_text('synthetic image')
                header=output/'mc_parameters.svh';header.write_text(header.read_text()+'// changed during build\n')
            return SimpleNamespace(returncode=0)
        argv=['qualify_fence_order.py','--simulator','iverilog','--archive',str(archive),
              '--primitive-library',str(library),'--out',str(output)]
        with patch('sys.argv',argv),patch('shutil.which',side_effect=lambda name:str(binaries/name)), \
             patch('subprocess.run',side_effect=execute),self.assertRaisesRegex(ValueError,'input changed'):
            q.main()
        report=q.load_json(output/'report.json');self.assertEqual(report['status'],'FAIL')
        self.assertFalse(any(c['name'].startswith('mode') for c in report['commands']))


if __name__=='__main__':unittest.main()
