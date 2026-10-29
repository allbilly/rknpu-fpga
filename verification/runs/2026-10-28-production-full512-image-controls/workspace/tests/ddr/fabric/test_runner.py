"""Synthetic fabric receipt controls, never native DDR qualification."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.ddr import run_fabric as runner
from tools.ddr import run_monitor as shared

WORKSPACE = Path(__file__).resolve().parents[3]


class FabricRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in runner.LOCAL:
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(WORKSPACE/name, path)
        for module in (runner, shared):
            change = patch.object(module, 'ROOT', self.root)
            change.start();self.addCleanup(change.stop)
        self.producer = Path('/original/producer')
        self.output = 'build/synthetic-fabric'

    def write(self, name, data):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def fixture(self, simulator='iverilog', mode='portable'):
        names = {'simulator':simulator, **({'runtime':'vvp'} if simulator == 'iverilog' else {'cxx':'c++'})}
        tools = {role:dict(path='/synthetic/bin/'+name,
            sha256=hashlib.sha256(name.encode()).hexdigest()) for role, name in names.items()}
        source = runner.source_revision()
        report = dict(status='PASS_DDR_FABRIC_MODEL_ONLY', execution_schema=1, scope=runner.SCOPE,
            execution_root=str(self.producer), output_directory=self.output, simulator=simulator,
            mode=mode, source=source, execution_inputs=source, tools=tools, commands=[], tests=[],
            **{name:False for name in runner.FLAGS})
        artifacts = set()
        def command(name, argv, identity, text, code=0):
            log = str(Path(self.output)/(name+'.log'));self.write(log, text);artifacts.add(log)
            entry = dict(name=name, argv=argv, environment=copy.deepcopy(runner.ENVIRONMENT),
                status='PASS', log=log, log_sha256=runner.digest(self.root/log), returncode=code,
                executable_before=copy.deepcopy(identity), executable_after=copy.deepcopy(identity),
                tools_before=copy.deepcopy(tools), tools_after=copy.deepcopy(tools),
                inputs_before=source, inputs_after=source)
            report['commands'].append(entry)
            return entry
        for name, argv, role in runner.version_plan(simulator, tools):
            field = {'simulator':'tool_version', 'runtime':'runtime_version', 'cxx':'cxx_version'}[role]
            report[field] = 'synthetic '+role+' version'
            command(name, argv, tools[role], report[field]+'\n')
        for plan in runner.plans(simulator, mode, self.producer, self.output, tools):
            self.write(plan['image'], 'synthetic executable '+plan['name']);artifacts.add(plan['image'])
            image_hash = runner.digest(self.root/plan['image'])
            built = command(plan['name']+'-build', plan['build'], tools['simulator'], '')
            built['output_image'] = dict(path=plan['image'], sha256=image_hash)
            if plan['rejected']:
                text = ('FATAL: fixture.sv:1: '+plan['expected'][0]+'\n Time: 0 Scope: fixture\n'
                        if simulator == 'iverilog' else '[0] %Error: fixture.sv:1: '+plan['expected'][0]+'\n')
            else:
                text = plan['expected']+'\n'
                if mode == 'full-span':
                    text = ''.join('PROGRESS default_c0_init_lines='+str(value)+'\n'
                                   for value in range(1048576,33554433,1048576))+text
            identity = tools['runtime'] if simulator == 'iverilog' else dict(
                path=plan['run'][0], sha256=image_hash)
            executed = command(plan['name']+'-run', plan['run'], identity, text, 1 if plan['rejected'] else 0)
            executed.update(image=plan['image'], image_before=image_hash, image_after=image_hash)
            result = runner.check_result(text, plan, executed['returncode'], simulator)
            report['tests'].append(dict(name=plan['name'], outcome='EXPECTED_REJECTION' if plan['rejected'] else 'PASS',
                result=result, image=plan['image'], image_sha256=image_hash))
        report['artifacts'] = runner.fingerprint([self.root/p for p in artifacts])
        return report

    def verify(self, report):
        return runner.verify_report(self.write('receipt.json',json.dumps(report)))

    def change_log(self, report, command, text):
        self.write(command['log'], text)
        command['log_sha256'] = runner.digest(self.root/command['log'])
        report['artifacts']['files'][command['log']] = command['log_sha256']
        report['artifacts'] = runner.manifest(report['artifacts']['files'])

    def test_copied_verification_needs_no_tools_or_original_tree(self):
        for simulator,mode in [('iverilog','portable'),('verilator','portable'),('verilator','full-span')]:
            report = self.fixture(simulator,mode)
            with self.subTest(simulator=simulator,mode=mode), patch('subprocess.Popen',side_effect=AssertionError('No execution')):
                self.assertEqual(self.verify(report)['status'],'VERIFIED_DDR_FABRIC_MODEL_ONLY')

    def test_full_span_plan_uses_actual_default_span(self):
        report = self.fixture('verilator','full-span')
        build = next(c for c in report['commands'] if c['name']=='full-span-build')
        self.assertIn('-GFULL_SPAN=1',build['argv'])
        self.assertFalse(any(a.startswith(('-GDUT_BASE=','-GDUT_BYTES=')) for a in build['argv']))
        changed=copy.deepcopy(report);next(c for c in changed['commands'] if c['name']=='full-span-build')['argv'].insert(1,'-GDUT_BYTES=256')
        with self.assertRaises(ValueError):self.verify(changed)
        with self.assertRaises(ValueError):runner.cases('iverilog','full-span')

    def test_full_span_progress_cannot_skip_repeat_or_forge_lines(self):
        original=self.fixture('verilator','full-span')
        command=next(c for c in original['commands'] if c['name']=='full-span-run')
        text=(self.root/command['log']).read_text()
        for kind in ('skip','repeat','bad','wrong-total'):
            report=copy.deepcopy(original);run=next(c for c in report['commands'] if c['name']=='full-span-run')
            changed=text
            if kind=='skip':changed=changed.replace('PROGRESS default_c0_init_lines=1048576\n','')
            elif kind=='repeat':changed='PROGRESS default_c0_init_lines=1048576\n'+changed
            elif kind=='bad':changed='PROGRESS default_c0_init_lines=unknown\n'+changed
            else:changed=changed.replace('lines=33554432 last=','lines=4 last=')
            self.change_log(report,run,changed)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.verify(report)
            self.write(command['log'],text)

    def test_tool_roles_producer_root_and_version_links_are_bound(self):
        report=self.fixture()
        for kind in ('role','root','version'):
            changed=copy.deepcopy(report)
            if kind=='role':changed['tools']['simulator']['path']='/bin/true'
            elif kind=='root':changed['execution_root']='relative'
            else:changed['runtime_version']='unbound runtime'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.verify(changed)

    def test_exact_command_outputs_inputs_and_images_are_required(self):
        report=self.fixture('verilator')
        for kind in ('missing','output','run','flag','input','image','status'):
            changed=copy.deepcopy(report);build=next(c for c in changed['commands'] if c['name']=='portable-build');run=next(c for c in changed['commands'] if c['name']=='portable-run')
            if kind=='missing':changed['commands']=changed['commands'][1:]
            elif kind=='output':build['argv'][build['argv'].index('-o')+1]='other'
            elif kind=='run':run['argv'].insert(0,'/bin/echo')
            elif kind=='flag':build['argv'].insert(1,'-DFAKE_PASS')
            elif kind=='input':build['inputs_after']=runner.manifest({})
            elif kind=='image':run['image_after']='0'*64
            else:run['status']='RUNNING'
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.verify(changed)

    def test_closed_artifact_set_and_source_bytes_are_required(self):
        report=self.fixture();extra='build/extra.bin';self.write(extra,'unbound')
        changed=copy.deepcopy(report);changed['artifacts']['files'][extra]=runner.digest(self.root/extra);changed['artifacts']=runner.manifest(changed['artifacts']['files'])
        with self.assertRaises(ValueError):self.verify(changed)
        source=self.root/'rtl/ddr/rk_ddr_memory_fabric.sv';source.write_text(source.read_text()+'\n')
        with self.assertRaises(ValueError):self.verify(report)

    def test_parameter_controls_require_specific_time_zero_rejection(self):
        for simulator in ('iverilog','verilator'):
            original=self.fixture(simulator);command=next(c for c in original['commands'] if c['name']=='zero-bytes-run');text=(self.root/command['log']).read_text()
            for kind in ('reason','time','exit'):
                report=copy.deepcopy(original);run=next(c for c in report['commands'] if c['name']=='zero-bytes-run')
                changed=text
                if kind=='reason':changed=changed.replace(runner.FABRIC_ERROR,'Other failure')
                elif kind=='time':changed=changed.replace('Time: 0','Time: 10').replace('[0]','[10]')
                else:run['returncode']=0
                self.change_log(report,run,changed)
                with self.subTest(simulator=simulator,kind=kind),self.assertRaises(ValueError):self.verify(report)
                self.write(command['log'],text)

    def test_unknown_warnings_and_physical_claims_are_rejected(self):
        report=self.fixture()
        for flag in runner.FLAGS:
            changed=copy.deepcopy(report);changed[flag]=True
            with self.subTest(flag=flag),self.assertRaises(ValueError):self.verify(changed)
        build=next(c for c in report['commands'] if c['name']=='portable-build')
        self.change_log(report,build,'/source/fabric.sv:1: warning: extra diagnostic\n')
        with self.assertRaises(ValueError):self.verify(report)


if __name__=='__main__':unittest.main()
