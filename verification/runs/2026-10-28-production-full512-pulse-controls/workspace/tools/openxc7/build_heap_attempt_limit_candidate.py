#!/usr/bin/env python3
"""Build one isolated counter-safe HeAP object on the qualified parent engine.

Reproduce the parent's executable byte-for-byte, execute sanitizer-clean limit
and counter-boundary fixtures, then replace only the actual linked HeAP object.
All donor sources/objects, live jobs, native legality/refinement/clock/part,
raw hardware/commands and default tool pointers remain unchanged. Fresh native
qualification is required before full placement. No SHA256SUMS is written.
"""
import difflib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import heap_attempt_limit_candidate as candidate
import build_strict_search_candidate as parent_build
from qualify_native_heap_clock_features import verify_qualification
from build_dsp_constant_candidate import dependencies, link_argv
from prepare_prefix_shared_pack_input import digest
from evidence import ROOT, source_revision, timestamp

PARENT = ROOT / 'build/openxc7/strict-search-engine-1791427828339461924/report.json'
QUALIFICATION = ROOT / 'build/openxc7/native-heap-clock-features-1791461172554993544/report.json'
ARITHMETIC = ROOT / 'build/openxc7/shared-heap-arithmetic-cxx-driver-1791480180109061866/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_heap_build_control.py'
CASES = ((7, 8), (46340, 8), (46341, 8), (523410, 8), (538118, 8),
         (2**31-1, 8), (2**64-1, 8), (2**64-1, 2**31-1), (523410, 0))
BUILT = 'BUILT_ISOLATED_COUNTER_SAFE_HEAP_LIMIT_NOT_NATIVE_QUALIFIED_OR_FULL_PNR'
COMMANDS = ['software_controls', 'generated_check', 'compiler_version', 'relink_qualified_parent_identity',
            'compile_sanitized_limit_fixture', *('limit_' + str(i) for i in range(len(CASES))),
            'compile_counter_safe_heap', 'link_counter_safe_heap', 'native_version']
FLAGS = ('native_requalification_executed', 'full_native_placement_executed', 'full_native_routing_executed',
         'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted',
         'hardware_programmed', 'default_engine_pointer_changed', 'native_legality_guards_changed',
         'objective_or_coefficient_changed', 'refinement_or_RNG_changed', 'warning_checks_suppressed',
         'FPGA_clock_or_geometry_changed', 'runtime_CPU_arithmetic_or_layout_fixup')


def merge(before, bindings):
    for name, sha in bindings.items():
        path = Path(name)
        path = (path if path.is_absolute() else ROOT / path).resolve(strict=True)
        assert re.fullmatch('[0-9a-f]{64}', sha)
        assert str(path) not in before or before[str(path)] == sha, 'Conflicting engine input binding'
        before[str(path)] = sha


def verify_metadata(report):
    assert report['status'] == BUILT and report['stage'] == 'complete' and report['finished_utc']
    assert report['part'] == 'xc7k480tffg1156-2' and report['full_parallel_products'] == 512
    assert report['qualified_parent_relinked_byte_identical'] is True
    assert report['changed_objects_relative_to_qualified_HeAP_parent'] == 1
    assert report['actual_original_source'] == str(candidate.SOURCE) and report['actual_original_object'] == str(candidate.OBJECT)
    assert report['default_actual_full_graph_attempt_limit'] == candidate.MAXIMUM == 2147483646
    assert report['source_change'] == 'ONE_EXPRESSION_WIDE_SQUARE_AND_COUNTER_SAFE_FINITE_SATURATION'
    assert report['limit_fixture_cases'] == [list(c) for c in CASES]
    assert report['production_source_before'] == report['production_source_after']
    assert [s['label'] for s in report['commands']] == COMMANDS
    assert all(s['status'] == 'PASS_TOOL_EXECUTION_ONLY' and s['returncode'] == 0 for s in report['commands'])
    assert all(report[flag] is False for flag in FLAGS)


def main():
    parent = json.loads(PARENT.read_text())
    parent_build.verify_build_metadata(parent)
    q, before = verify_qualification(QUALIFICATION)
    assert q['executable'] == parent['executable'] and q['native_version'] == parent['native_version']
    arithmetic = json.loads(ARITHMETIC.read_text())
    assert arithmetic['status'] == 'CONFIRMED_SOURCE_BOUND_HEAP_DEFAULT_ATTEMPT_ARITHMETIC_OVERFLOW_NOT_FIT_OR_SIGNOFF'
    assert arithmetic['stage'] == 'complete' and arithmetic['finished_utc']
    assert (arithmetic['actual_packed_cells'], arithmetic['actual_native_logged_attempt_limit']) == (523410, 10000)
    for report in (parent, arithmetic):
        merge(before, report['source'])
        merge(before, report['artifacts'])
    links = [s for s in parent['commands'] if s['label'] == 'link_strict_search_candidate']
    assert len(links) == 1 and links[0]['status'] == 'PASS_TOOL_EXECUTION_ONLY'
    link = links[0]
    assert link['argv'].count(str(candidate.OBJECT)) == 1
    assert link['argv'][link['argv'].index('-o')+1] == parent['executable']['path']
    deps = dependencies(Path(str(candidate.OBJECT) + '.d'))
    assert candidate.SOURCE in deps
    assert all(str(p) in before and before[str(p)] == digest(p) for p in (candidate.SOURCE, candidate.OBJECT))
    paths = {PARENT, QUALIFICATION, ARITHMETIC, candidate.CMAKE / 'flags.make', candidate.CMAKE / 'build.make',
             Path(str(candidate.OBJECT) + '.d'), CONTROL, Path(__file__).resolve(), Path(sys.executable).resolve(),
             Path('/usr/bin/c++').resolve(), *deps}
    paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    merge(before, {str(p): digest(p) for p in paths})
    assert all(digest(p) == sha for p, sha in before.items()), 'Changed actual engine build input'
    assert source_revision() == parent['production_source_after'] == arithmetic['production_source_after']
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (5 * 1024**3, 5 * 1024**3))
    out = ROOT / f'build/openxc7/counter-safe-heap-engine-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='build', started_utc=timestamp(), finished_utc=None, supervisor_pid=os.getpid(),
        source=before, commands=[], scope=__doc__, parent_build_report=str(PARENT), parent_qualification=str(QUALIFICATION),
        arithmetic_defect_report=str(ARITHMETIC), parent_executable=parent['executable'], production_source_before=source_revision(),
        part='xc7k480tffg1156-2', full_parallel_products=512, changed_objects_relative_to_qualified_HeAP_parent=1,
        actual_original_source=str(candidate.SOURCE), actual_original_object=str(candidate.OBJECT),
        source_change='ONE_EXPRESSION_WIDE_SQUARE_AND_COUNTER_SAFE_FINITE_SATURATION',
        default_actual_full_graph_attempt_limit=candidate.limit(523410, 8), limit_fixture_cases=[list(c) for c in CASES],
        **{flag: False for flag in FLAGS})

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, cwd=ROOT, timeout=1800, case=None):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), log=str(out / (label + '.log')),
                    status='RUNNING', timeout_seconds=timeout)
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=cwd,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0 and not re.search(r'(?im)\b(?:warning|error|fatal)\s*:', text), text[-3500:]
            if case is not None:
                step['result'] = candidate.validate_result(text, code, *case)
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text.strip()
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128+s)))
    save()
    print(out / 'report.json', flush=True)
    try:
        original = candidate.SOURCE.read_text()
        source = out / 'common/place/placer_heap.cc'
        source.parent.mkdir(parents=True, exist_ok=False)
        source.write_text(candidate.candidate_source(original))
        candidate.verify_source_transition(original, source.read_text())
        report['generated_source_sha256'] = digest(source)
        shutil.copyfile(candidate.SOURCE, out / 'original-placer_heap.cc')
        (out / 'counter-safe-heap-limit.patch').write_text(''.join(difflib.unified_diff(original.splitlines(True),
            source.read_text().splitlines(True), fromfile='a/common/place/placer_heap.cc', tofile='b/common/place/placer_heap.cc')))
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        relinked = out / 'qualified-parent-relinked'
        run('relink_qualified_parent_identity', link_argv(link['argv'], relinked, {}), cwd=Path(link['cwd']))
        assert digest(relinked) == parent['executable']['sha256'], 'Qualified parent relink differs'
        report['qualified_parent_relinked_byte_identical'] = True
        old_compile = next(s for s in arithmetic['commands'] if s['label'] == 'compile_exact_expression_cxx_driver')
        fixture, fixture_exe = out / 'counter_safe_limit_fixture.cc', out / 'counter_safe_limit_fixture'
        fixture.write_text(candidate.fixture())
        assert digest(old_compile['argv'][0]) == before[old_compile['argv'][0]]
        run('compile_sanitized_limit_fixture', [old_compile['argv'][0], '--driver-mode=g++', '-std=c++17', '-O0',
            '-Wall', '-Wextra', '-Werror', '-fsanitize=signed-integer-overflow,unsigned-integer-overflow',
            '-fno-sanitize-recover=all', fixture, '-o', fixture_exe], timeout=120)
        report['fixture_execution_inputs'] = {str(p): digest(p) for p in (fixture, fixture_exe)}
        for i, case in enumerate(CASES):
            run('limit_' + str(i), [fixture_exe, *map(str, case)], timeout=120, case=case)
        assert all(digest(p) == sha for p, sha in report['fixture_execution_inputs'].items())
        obj = out / 'placer_heap.cc.o'
        run('compile_counter_safe_heap', candidate.compile_argv(source, obj, (candidate.CMAKE / 'flags.make').read_text(),
            (candidate.CMAKE / 'build.make').read_text()), cwd=candidate.CMAKE.parent.parent)
        for dependency in dependencies(Path(str(obj) + '.d')):
            expected = report['generated_source_sha256'] if dependency == source else before[str(dependency)]
            assert digest(dependency) == expected, 'Unbound/changed new compile dependency'
        assert digest(source) == report['generated_source_sha256']
        executable = out / 'nextpnr-himbaechel'
        run('link_counter_safe_heap', link_argv(link['argv'], executable, {candidate.OBJECT: obj}), cwd=Path(link['cwd']))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == q['native_version']
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        assert all(digest(p) == sha for p, sha in before.items())
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=BUILT, stage='complete', finished_utc=timestamp())
        verify_metadata(report)
    except BaseException as error:
        report.update(status='FAIL_COUNTER_SAFE_HEAP_BUILD', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
