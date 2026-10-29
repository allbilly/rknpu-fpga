"""Synthetic receipt controls only; these fixtures are not native RTL results."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tools.ddr import run_lifecycle as runner
from tools.ddr import run_monitor as shared

WORKSPACE = Path(__file__).resolve().parents[3]


class LifecycleRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in runner.sources(['reset', 'fence']):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(WORKSPACE/name, path)
        for module in (runner, shared):
            change = patch.object(module, 'ROOT', self.root)
            change.start()
            self.addCleanup(change.stop)
        self.producer = Path('/original/producer')
        self.output = 'build/synthetic-lifecycle'

    def write(self, name, data):
        path = self.root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def fixture(self, simulator='iverilog', profiles=None):
        profiles = ['reset', 'fence'] if profiles is None else profiles
        names = {'simulator':simulator, **({'runtime':'vvp'} if simulator == 'iverilog' else {'cxx':'c++'})}
        tools = {role:dict(path='/synthetic/bin/'+name,
                          sha256=hashlib.sha256(name.encode()).hexdigest()) for role, name in names.items()}
        source = runner.fingerprint([self.root/p for p in runner.sources(profiles)])
        report = dict(status='PASS_DDR_LIFECYCLE_PROTOCOLS_ONLY', execution_schema=1,
            scope=runner.SCOPE, execution_root=str(self.producer), output_directory=self.output,
            profiles=profiles, simulator=simulator, source=source, execution_inputs=source,
            tools=tools, commands=[], tests=[], **{name:False for name in runner.FLAGS})
        artifacts = set()

        def command(name, argv, role, text, returncode=0):
            log = str(Path(self.output)/(name+'.log'))
            self.write(log, text)
            artifacts.add(log)
            executable = tools[role] if role else dict(path=argv[0], sha256=runner.digest(self.root/argv[0].removeprefix(str(self.producer)+'/')))
            entry = dict(name=name, argv=argv, environment=copy.deepcopy(runner.ENVIRONMENT),
                executable_before=copy.deepcopy(executable), executable_after=copy.deepcopy(executable),
                tools_before=copy.deepcopy(tools), tools_after=copy.deepcopy(tools),
                inputs_before=source, inputs_after=source, log=log,
                log_sha256=runner.digest(self.root/log), returncode=returncode)
            report['commands'].append(entry)
            return entry

        for name, argv, role in runner.version_plan(simulator, tools):
            field = {'simulator':'tool_version', 'runtime':'runtime_version', 'cxx':'cxx_version'}[role]
            report[field] = 'synthetic '+role+' version'
            command(name, argv, role, report[field]+'\n')
        for plan in runner.plans(simulator, profiles, self.producer, self.output, tools):
            self.write(plan['image'], 'synthetic compiled image '+plan['name'])
            artifacts.add(plan['image'])
            image_hash = runner.digest(self.root/plan['image'])
            built = command(plan['name']+'-build', plan['build'], 'simulator', '')
            built['output_image'] = dict(path=plan['image'], sha256=image_hash)
            if plan['rejected']:
                text = ('FATAL: fixture.sv:1: '+plan['expected']+'\n Time: 0 Scope: fixture\n'
                        if simulator == 'iverilog' else '[0] %Error: fixture.sv:1: '+plan['expected']+'\n')
            else:
                text = plan['expected']+'\n'
            executed = command(plan['name']+'-run', plan['run'], 'runtime' if simulator == 'iverilog' else None,
                               text, 1 if plan['rejected'] else 0)
            executed.update(image=plan['image'], image_before=image_hash, image_after=image_hash)
            report['tests'].append(dict(name=plan['name'], outcome='EXPECTED_REJECTION' if plan['rejected'] else 'PASS',
                result=plan['expected'], image=plan['image'], image_sha256=image_hash))
        report['artifacts'] = runner.fingerprint([self.root/n for n in artifacts])
        return report

    def verify(self, report):
        path = self.write('receipt.json', json.dumps(report))
        return runner.verify_report(path)

    def rebind_commands(self, report):
        """Rebuild self-consistent metadata to expose missing producer invariants."""
        versions = runner.version_plan(report['simulator'], report['tools'])
        plans = runner.plans(report['simulator'], report['profiles'], report['execution_root'],
                             report['output_directory'], report['tools'])
        commands = [(name, argv, role) for name, argv, role in versions]
        commands += [(plan['name']+'-'+stage, plan[stage], 'simulator' if stage == 'build' else
                      ('runtime' if report['simulator'] == 'iverilog' else None))
                     for plan in plans for stage in ('build', 'run')]
        for entry, (name, argv, role) in zip(report['commands'], commands):
            self.assertEqual(entry['name'], name)
            entry['argv'] = argv
            identity = report['tools'][role] if role else dict(path=argv[0],
                sha256=report['artifacts']['files'][entry['image']])
            entry['executable_before'] = copy.deepcopy(identity)
            entry['executable_after'] = copy.deepcopy(identity)
            entry['tools_before'] = copy.deepcopy(report['tools'])
            entry['tools_after'] = copy.deepcopy(report['tools'])

    def replace_log(self, report, command, text):
        self.write(command['log'], text)
        command['log_sha256'] = runner.digest(self.root/command['log'])
        report['artifacts']['files'][command['log']] = command['log_sha256']
        report['artifacts'] = runner.manifest(report['artifacts']['files'])

    def test_copied_verification_runs_no_tools_or_original_inputs(self):
        for simulator in ('iverilog', 'verilator'):
            for profiles in (['reset'], ['fence'], ['reset', 'fence']):
                with self.subTest(simulator=simulator, profiles=profiles):
                    report = self.fixture(simulator, profiles)
                    with patch('subprocess.Popen', side_effect=AssertionError('Verification may not execute tools')):
                        result = self.verify(report)
                    self.assertEqual(result['status'], 'VERIFIED_DDR_LIFECYCLE_PROTOCOLS_ONLY')
                    self.assertFalse(result['memory_retirement_verified'])

    def test_rebound_tool_role_must_still_name_the_producer_tool(self):
        for simulator, roles in [('iverilog', ('simulator', 'runtime')), ('verilator', ('simulator', 'cxx'))]:
            report = self.fixture(simulator)
            for role in roles:
                changed = copy.deepcopy(report)
                changed['tools'][role]['path'] = '/synthetic/bin/true'
                changed['tools'][role]['sha256'] = hashlib.sha256(b'other-tool').hexdigest()
                self.rebind_commands(changed)
                with self.subTest(simulator=simulator, role=role), self.assertRaises(ValueError):
                    self.verify(changed)

    def test_rebound_producer_root_must_be_absolute(self):
        for simulator in ('iverilog', 'verilator'):
            changed = self.fixture(simulator)
            changed['execution_root'] = 'relative-producer'
            self.rebind_commands(changed)
            with self.subTest(simulator=simulator), self.assertRaises(ValueError):
                self.verify(changed)

    def test_command_inventory_flags_outputs_and_executed_image_are_exact(self):
        for simulator in ('iverilog', 'verilator'):
            report = self.fixture(simulator)
            for kind in ('missing-version', 'duplicate', 'flag', 'output', 'runtime', 'override'):
                changed = copy.deepcopy(report)
                build = next(c for c in changed['commands'] if c['name'] == 'reset-build')
                run = next(c for c in changed['commands'] if c['name'] == 'reset-run')
                if kind == 'missing-version':
                    changed['commands'] = changed['commands'][1:]
                elif kind == 'duplicate':
                    changed['commands'].insert(0, copy.deepcopy(changed['commands'][0]))
                elif kind == 'flag':
                    build['argv'].insert(1, '-DFAKE_PASS')
                elif kind == 'output':
                    build['argv'][build['argv'].index('-o')+1] = '/unrelated/image'
                elif kind == 'runtime':
                    run['argv'].insert(0, '/bin/echo')
                else:
                    invalid = next(c for c in changed['commands'] if c['name'] == 'fence-DUT_TIMEOUT_CYCLES-zero-build')
                    prefix = '-P' if simulator == 'iverilog' else '-G'
                    index = next(i for i, arg in enumerate(invalid['argv']) if arg.startswith(prefix))
                    invalid['argv'][index] = invalid['argv'][index].removesuffix('=0')+'=1'
                with self.subTest(simulator=simulator, kind=kind), self.assertRaises(ValueError):
                    self.verify(changed)

    def test_versions_executables_and_input_boundaries_are_bound(self):
        report = self.fixture()
        for kind in ('version', 'executable', 'tools', 'inputs', 'image'):
            changed = copy.deepcopy(report)
            command = next(c for c in changed['commands'] if c['name'] == 'fence-run')
            if kind == 'version':changed['runtime_version'] = 'unbound version'
            elif kind == 'executable':command['executable_after']['sha256'] = '0'*64
            elif kind == 'tools':command['tools_after'] = {}
            elif kind == 'inputs':command['inputs_after'] = runner.manifest({})
            else:command['image_after'] = '0'*64
            with self.subTest(kind=kind), self.assertRaises(ValueError):self.verify(changed)

    def test_closed_artifacts_and_actual_image_bytes_are_required(self):
        report = self.fixture()
        extra = 'build/extra.txt'
        self.write(extra, 'unbound artifact')
        changed = copy.deepcopy(report)
        changed['artifacts']['files'][extra] = runner.digest(self.root/extra)
        changed['artifacts'] = runner.manifest(changed['artifacts']['files'])
        with self.assertRaises(ValueError):self.verify(changed)
        self.write(report['tests'][0]['image'], 'replacement image')
        with self.assertRaises(ValueError):self.verify(report)

    def test_parameter_rejections_need_specific_reason_time_zero_and_failure(self):
        for simulator in ('iverilog', 'verilator'):
            report = self.fixture(simulator)
            for kind in ('reason', 'time', 'exit'):
                changed = copy.deepcopy(report)
                command = next(c for c in changed['commands'] if c['name'] == 'fence-DUT_TIMEOUT_CYCLES-zero-run')
                text = (self.root/command['log']).read_text()
                if kind == 'reason':text = text.replace(runner.SPEC['fence']['fatal'], 'Other failure')
                elif kind == 'time':text = text.replace('Time: 0', 'Time: 10').replace('[0]', '[10]')
                else:command['returncode'] = 0
                self.replace_log(changed, command, text)
                with self.subTest(simulator=simulator, kind=kind), self.assertRaises(ValueError):self.verify(changed)
                # Restore the original result before the next independent mutation.
                original = ('FATAL: fixture.sv:1: '+runner.SPEC['fence']['fatal']+'\n Time: 0 Scope: fixture\n'
                            if simulator == 'iverilog' else '[0] %Error: fixture.sv:1: '+runner.SPEC['fence']['fatal']+'\n')
                self.write(command['log'], original)

    def test_hardware_claims_scope_and_unexpected_warnings_are_rejected(self):
        report = self.fixture()
        for flag in runner.FLAGS:
            changed = copy.deepcopy(report);changed[flag] = True
            with self.subTest(flag=flag), self.assertRaises(ValueError):self.verify(changed)
        changed = copy.deepcopy(report);changed['scope'] = 'Full DDR verified'
        with self.assertRaises(ValueError):self.verify(changed)
        command = next(c for c in report['commands'] if c['name'] == 'fence-build')
        self.replace_log(report, command, '/source/fence.sv:1: warning: new diagnostic\n')
        with self.assertRaises(ValueError):self.verify(report)

    def test_source_drift_is_not_a_verified_protocol_run(self):
        report = self.fixture()
        path = self.root/'rtl/ddr/rk_mig_write_fence.sv'
        path.write_text(path.read_text()+'\n')
        with self.assertRaises(ValueError):self.verify(report)


if __name__ == '__main__':
    unittest.main()
