#!/usr/bin/env python3
"""Build isolated literal-empty-output checker v2 from qualified carry engine.

Require/recheck the actual old-checker rejection and small native qualification.
Byte-relink the qualified parent, replace only json_frontend.cc.o and xilinx.cc.o,
and retain all default/v1 behavior, native guards and connected graph. No live
tool/donor/RTL/default executable edits, SHA256SUMS manifest, or FPGA access.
Build completion is not native qualification, full route or physical signoff.
"""
import difflib
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_strict_search_board as support
import empty_output_candidate as candidate
import build_imported_placement_checker as builder
from probe_imported_empty_lut import fixture, actual_empty_lut, BASE, check_rejection
from place_prefix_board import bind_report, verify_bindings
from build_dsp_constant_candidate import dependencies, link_argv, compile_argv
from evidence import source_revision

ROOT = support.ROOT
DIAGNOSTIC = ROOT / 'build/openxc7/imported-empty-lut-diagnostic-1791432126438912643/report.json'
CONTROL = ROOT / 'tests/cmac/test_empty_output_candidate.py'
BUILT = 'BUILT_ISOLATED_LITERAL_EMPTY_OUTPUT_V2_CHECKER_NOT_NATIVE_QUALIFIED_OR_FULL_ROUTE_SIGNOFF'


def verify_diagnostic(report):
    assert report['status'] == 'REPRODUCED_NATIVE_CHECKER_UNSUPPORTED_DISCONNECTED_PAIRED_LUT_OUTPUT_NOT_QUALIFIED_OR_FULL_ROUTE'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert [c['label'] for c in report['commands']] == ['software_controls', 'generated_check', 'version', 'native_empty_output_diagnostic']
    step = report['commands'][-1]
    assert step['status'] == 'PASS_EXPECTED_UNSUPPORTED_REJECTION_ONLY' and step['returncode'] == 125
    check_rejection(step['returncode'], Path(step['log']).read_text())
    for key in ('full_input_modified', 'full_native_placement_executed', 'full_native_route_executed',
                'positive_checker_qualification', 'numerical_acceptance', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False
    original = json.loads(BASE.read_text()); expected, details = fixture(original, actual_empty_lut())
    assert json.loads(Path(report['execution_input']).read_text()) == expected and report['test_only_fixture'] == details


def frontend_compile_recipe(source, obj, flags, recipe):
    variables = {}
    for key in ('DEFINES', 'INCLUDES', 'FLAGS'):
        matches = re.findall(r'^CXX_' + key + r' = (.*)$', flags, re.M)
        assert len(matches) == 1
        variables[key] = shlex.split(matches[0])
    relative = 'CMakeFiles/nextpnr-himbaechel.dir/__/frontend/json_frontend.cc.o'
    expected = ('/usr/bin/c++ $(CXX_DEFINES) $(CXX_INCLUDES) $(CXX_FLAGS) -MD -MT himbaechel/' + relative +
                ' -MF ' + relative + '.d -o ' + relative + ' -c ' + str(candidate.FRONTEND))
    assert recipe.count(expected) == 1, 'Unpinned original frontend compile invocation'
    return ['/usr/bin/c++', *variables['DEFINES'], *variables['INCLUDES'], *variables['FLAGS'],
            '-iquote', str(candidate.FRONTEND.parent), '-MD', '-MT', str(obj), '-MF', str(obj) + '.d',
            '-o', str(obj), '-c', str(source)]


def main():
    out = ROOT / f'build/openxc7/empty-output-checker-engine-{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=support.timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], profile=candidate.PROFILE, diagnostic_report=str(DIAGNOSTIC),
        changed_objects_relative_to_qualified_carry_engine=2, native_requalification_executed=False,
        full_placement_transfer_admitted=False, connected_graph_changed=False, old_v1_behavior_changed=False,
        numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False, production_source_before=source_revision())
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, cwd=ROOT, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), log=str(out / (label + '.log')),
                    status='RUNNING', expected_returncode=0, timeout_seconds=timeout)
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=cwd,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:warning|error|fatal):', text), text[-4000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'; return text.strip()
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        before = {}; small, parent = support.verify_small_evidence(before)
        diagnostic = json.loads(DIAGNOSTIC.read_text()); verify_diagnostic(diagnostic)
        assert diagnostic['executable'] == small['executable']
        bind_report(DIAGNOSTIC, diagnostic, before)
        parent_path = Path(json.loads(support.small.PARENT.read_text())['candidate_build_report'])
        assert json.loads(parent_path.read_text()) == parent
        parent_link = next(c for c in parent['commands'] if c['label'] == 'link_imported_placement_probe')
        parent_obj = parent_path.parent / 'xilinx.cc.o'
        assert parent_link['argv'].count(str(parent_obj)) == parent_link['argv'].count(str(candidate.FRONTEND_OBJECT)) == 1
        files = {Path(__file__).resolve(), Path(candidate.__file__).resolve(), CONTROL, Path(sys.executable).resolve(),
                 parent_path, candidate.FRONTEND, candidate.FRONTEND_OBJECT, Path(str(candidate.FRONTEND_OBJECT) + '.d'),
                 parent_obj, builder.TAG_SOURCE, builder.CMAKE / 'flags.make', builder.CMAKE / 'build.make'}
        files.update(dependencies(Path(str(candidate.FRONTEND_OBJECT) + '.d')))
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            sha = support.digest(path); assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
        verify_bindings(before); report.update(source=before, parent_build_report=str(parent_path),
            parent_executable=parent['executable'], parent_small_native_report=str(support.SMALL), stage='build')
        old_template = (parent_path.parent / 'check_imported_placement.inc').read_text()
        block = candidate.checker_template(old_template)
        template = out / 'check_imported_placement.inc'; template.write_text(block)
        sources = [(builder.TAG_SOURCE, out / 'himbaechel/uarch/xilinx/xilinx.cc',
                    builder.checked_source(builder.TAG_SOURCE.read_text(), block), out / 'xilinx.cc.o'),
                   (candidate.FRONTEND, out / 'frontend/json_frontend.cc',
                    candidate.frontend_source(candidate.FRONTEND.read_text()), out / 'json_frontend.cc.o')]
        report['generated_source'] = {}
        for old, path, text, obj in sources:
            path.parent.mkdir(parents=True, exist_ok=False); path.write_text(text)
            shutil.copyfile(old, out / ('original-' + old.name))
            (out / (old.name + '.patch')).write_text(''.join(difflib.unified_diff(old.read_text().splitlines(True), text.splitlines(True),
                fromfile='a/' + old.name, tofile='b/' + old.name)))
            report['generated_source'][str(path)] = support.digest(path)
        report.update(default_and_v1_import_unchanged=True, original_native_validity_guards_preserved=True,
            source_declared_empty_PORT_OUT_preserved=True, warning_checks_suppressed=False, second_JSON_parse_added=False,
            software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        identity = out / 'qualified-carry-parent-relinked'
        run('relink_qualified_parent_identity', link_argv(parent_link['argv'], identity, {}), Path(parent_link['cwd']))
        assert support.digest(identity) == parent['executable']['sha256'], 'Qualified parent relink differs'
        report['qualified_parent_relink_byte_identical'] = True
        flags = (builder.CMAKE / 'flags.make').read_text(); recipe = (builder.CMAKE / 'build.make').read_text()
        for old, path, text, obj in sources:
            argv = (compile_argv('xilinx.cc', path, obj, flags, recipe) if old == builder.TAG_SOURCE else
                    frontend_compile_recipe(path, obj, flags, recipe))
            run('compile_' + old.stem, argv, builder.CMAKE.parent.parent)
            for dependency in dependencies(Path(str(obj) + '.d')):
                expected = report['generated_source'].get(str(dependency), before.get(str(dependency)))
                assert expected is not None and support.digest(dependency) == expected, 'Unbound compile dependency'
        executable = out / 'nextpnr-himbaechel'
        replacements = {parent_obj: sources[0][3], candidate.FRONTEND_OBJECT: sources[1][3]}
        run('link_empty_output_checker', link_argv(parent_link['argv'], executable, replacements), Path(parent_link['cwd']))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == small['native_version']
        report['executable'] = dict(path=str(executable), sha256=support.digest(executable))
        verify_bindings(before); report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=BUILT, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = support.timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): support.digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
