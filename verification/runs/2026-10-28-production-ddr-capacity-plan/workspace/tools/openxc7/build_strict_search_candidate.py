#!/usr/bin/env python3
"""Build an isolated physical-grid-bounded strict search with progress logs.

Start with the revalidated corrected-DSP engine and reproduce its executable
byte-identically. Change only its static-placer object. This changes search
sampling, not the objective, native legality guards, clock, circuit or target.
Native requalification is required before full-size placement. All donor
files/default pointers and completed attempts remain untouched. No
SHA256SUMS file is written.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_corrected_native_evidence import verify_corrected_evidence, NATIVE
from build_dsp_constant_candidate import dependencies, link_argv
from strict_search_candidate import (PRECISION_SOURCE, PRECISION_OBJECT, candidate_source,
                                     verify_source_transition, compile_argv)
from probe_corrected_dsp_checkpoint import ROOT, digest, timestamp, source_revision
from place_prefix_board import verify_bindings

PRECISION_BUILD = PRECISION_SOURCE.parents[2] / 'report.json'
CONTROL = ROOT / 'tests/cmac/test_strict_search_candidate.py'
BUILT = 'BUILT_ISOLATED_BOUNDED_STRICT_SEARCH_NOT_NATIVE_QUALIFIED_OR_FULL_PNR'
FLAGS = ('native_requalification_executed', 'full_native_placement_executed', 'full_native_routing_executed',
         'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted',
         'hardware_programmed', 'default_engine_pointer_changed', 'assertion_removal', 'warning_checks_suppressed',
         'native_legality_guards_changed', 'objective_or_coefficient_changed', 'FPGA_clock_or_geometry_changed')
COMMANDS = ('software_controls', 'generated_check', 'compiler_version', 'relink_corrected_parent_identity',
            'compile_strict_search_candidate', 'link_strict_search_candidate', 'native_version')


def verify_build_metadata(report):
    assert report['status'] == BUILT and report['stage'] == 'complete' and report['finished_utc']
    assert report['part'] == 'xc7k480tffg1156-2' and report['full_parallel_products'] == 512
    assert report['corrected_parent_relink_byte_identical'] is True
    assert report['changed_objects_relative_to_corrected_DSP_encoder'] == 1
    assert report['changed_search_upper_bounds'] == 2 and report['search_rng_trajectory_changed'] is True
    assert report['actual_original_source'] == str(PRECISION_SOURCE) and report['actual_original_object'] == str(PRECISION_OBJECT)
    assert report['production_source_before'] == report['production_source_after']
    assert [c['label'] for c in report['commands']] == list(COMMANDS)
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'])
    assert all(report[key] is False for key in FLAGS), 'Unsupported candidate build acceptance'


def main():
    out = ROOT / f'build/openxc7/strict-search-engine-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, source={}, commands=[], part='xc7k480tffg1156-2', full_parallel_products=512,
        corrected_parent_qualification=str(NATIVE), precision_build_report=str(PRECISION_BUILD),
        actual_original_source=str(PRECISION_SOURCE), actual_original_object=str(PRECISION_OBJECT),
        production_source_before=source_revision(), **{key: False for key in FLAGS})
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, cwd=ROOT, timeout=1800):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(cwd),
                    expected_returncode=0, timeout_seconds=timeout, status='RUNNING')
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
        q, before = verify_corrected_evidence()
        parent_path = Path(q['candidate_build_report']); parent = json.loads(parent_path.read_text())
        precision = json.loads(PRECISION_BUILD.read_text())
        assert str(PRECISION_SOURCE) in before and str(PRECISION_OBJECT) in before
        old_link = next(c for c in parent['commands'] if c['label'] == 'link_DSP_constant_candidate')
        old_compile = next(c for c in precision['commands'] if c['label'] == 'compile_static_precision')
        assert old_link['argv'].count(str(PRECISION_OBJECT)) == 1
        assert old_link['argv'][old_link['argv'].index('-o') + 1] == q['executable']['path']
        copied = out / 'common/place/placer_static.cc'; copied.parent.mkdir(parents=True)
        original = PRECISION_SOURCE.read_text(); changed = candidate_source(original)
        verify_source_transition(original, changed); copied.write_text(changed)
        shutil.copyfile(PRECISION_SOURCE, out / 'original-placer_static.cc')
        (out / 'bounded-strict-search.patch').write_text(''.join(difflib.unified_diff(
            original.splitlines(True), changed.splitlines(True), fromfile='a/common/place/placer_static.cc',
            tofile='b/common/place/placer_static.cc')))
        files = {PRECISION_BUILD, parent_path, Path(__file__).resolve(), CONTROL, copied,
                 Path(sys.executable).resolve(), Path('/usr/bin/c++').resolve(), Path(str(PRECISION_OBJECT) + '.d')}
        files.update(dependencies(Path(str(PRECISION_OBJECT) + '.d')))
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            path = path.resolve(strict=True); sha = digest(path)
            assert str(path) not in before or before[str(path)] == sha, 'Changed candidate build input'
            before[str(path)] = sha
        verify_bindings(before)
        report.update(source=before, parent_build_report=str(parent_path), parent_executable=q['executable'],
            changed_objects_relative_to_corrected_DSP_encoder=1, changed_search_upper_bounds=2,
            search_rng_trajectory_changed=True, progress_counters_consume_rng=False, stage='build',
            software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        report['compiler_version'] = run('compiler_version', ['/usr/bin/c++', '--version'], timeout=60)
        relinked = out / 'corrected-parent-relinked'
        run('relink_corrected_parent_identity', link_argv(old_link['argv'], relinked, {}), cwd=Path(old_link['cwd']))
        assert digest(relinked) == q['executable']['sha256'], 'Corrected parent relink differs'
        report['corrected_parent_relink_byte_identical'] = True
        obj = out / 'placer_static.cc.o'
        run('compile_strict_search_candidate', compile_argv(old_compile['argv'], copied, obj), cwd=Path(old_compile['cwd']))
        for dependency in dependencies(Path(str(obj) + '.d')):
            assert str(dependency) in before and digest(dependency) == before[str(dependency)], 'Unbound new compile dependency'
        executable = out / 'nextpnr-himbaechel'
        run('link_strict_search_candidate', link_argv(old_link['argv'], executable, {PRECISION_OBJECT: obj}), cwd=Path(old_link['cwd']))
        report['native_version'] = run('native_version', [executable, '--version'], timeout=60)
        assert report['native_version'] == q['native_version']
        report['executable'] = dict(path=str(executable), sha256=digest(executable))
        verify_bindings(before)
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=BUILT, stage='complete', finished_utc=timestamp())
        verify_build_metadata(report)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
