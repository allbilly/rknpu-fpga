#!/usr/bin/env python3
"""Bounded native placement of the completed engine's unchanged mux fixture.

Revalidate the completed isolated build and its actual old/new pack probes.
Run the same corrected mux fixture with normal HeAP refinement, exact part,
50 MHz, seed3588 and fatal warnings. This is a small mux placement probe, NOT
the all-original-gates backend qualification, full C32/K16 placement/route,
numerical/timing/electrical/DRC/CRC signoff, bitstream or FPGA/RK test. No donor,
old source/result, execution input, default tool or SHA256SUMS is changed.
"""
import argparse
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
import qualify_recursive_mux_feedthrough as qualification

candidate = qualification.candidate
ROOT = candidate.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_placement_probe_control.py'
PASSED = 'PASS_SMALL_RECURSIVE_MUX_NATIVE_PLACEMENT_NOT_FULL_BACKEND_QUALIFICATION_OR_FIT'


def admit_completed_build(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-native-io-engine-')
    report = json.loads(path.read_text())
    candidate.verify_metadata(report)  # Fail before any tool/output for RUNNING/failed/incomplete builds.
    before = {}
    candidate.heap.merge(before, report['source'])
    for name in report['artifacts']:
        assert Path(name).is_absolute() and Path(name).resolve(strict=True).is_relative_to(path.parent)
    candidate.heap.merge(before, report['artifacts'])
    before[str(path)] = candidate.digest(path)
    qualification.verify_bindings(before)
    candidate.verify_source_transition(candidate.SOURCE.read_text(),
                                       (path.parent / 'himbaechel/uarch/xilinx/pack.cc').read_text())
    assert report['production_source_after'] == candidate.source_revision()
    assert before[report['executable']['path']] == report['executable']['sha256']
    for filename, fixed, key in (('parent-packed.json', False, 'parent_probe'),
                                  ('candidate-packed.json', True, 'candidate_probe')):
        assert qualification.build.probe.packed_probe(json.loads((path.parent / filename).read_text()), fixed) == report[key]
    return report, before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report', type=Path, required=True)
    args = parser.parse_args()
    built, before = admit_completed_build(args.build_report)
    paths = {Path(__file__).resolve(), CONTROL, qualification.CONTROL, Path(sys.executable).resolve()}
    paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    candidate.heap.merge(before, {str(p): candidate.digest(p) for p in paths})
    qualification.verify_bindings(before)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (5 * 1024**3, 5 * 1024**3))
    out = ROOT / f'build/openxc7/recursive-mux-native-placement-probe-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='small_mux_placement', scope=__doc__, started_utc=candidate.timestamp(),
        supervisor_pid=os.getpid(), source=before, commands=[], build_report=str(args.build_report.resolve()),
        executable=built['executable'], production_source_before=candidate.source_revision(),
        part='xc7k480tffg1156-2', clock_period_ns=20, seed=3588, full_parallel_products=512,
        full_backend_qualification_executed=False, full_native_placement_executed=False,
        native_routing_executed=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), status='RUNNING',
                    timeout_seconds=timeout, log=str(out / (label + '.log')))
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid; save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait(); step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            assert code == 0, text[-3500:]
            assert not re.search(r'(?im)\b(?:warning|error|fatal):|sorry:|target is ignored|matched nothing', text), text[-3500:]
            if label == qualification.MUX_LABEL: qualification.base.early.check_heap_log(code, text)
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save(); print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        shutil.copyfile(__file__, out / 'executed_source.py')
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], 120)
        run('generated_check', ['make', 'generated-check'], 120)
        assert run('native_version', [built['executable']['path'], '--version'], 60).strip() == built['native_version']
        run(qualification.MUX_LABEL, qualification.mux_place_argv(args.build_report.resolve(), out), 3600)
        report['mux_placement_checks'] = qualification.validate_mux_placed(out / 'mux-feedthrough-placed.json', args.build_report)
        qualification.verify_bindings(before)
        report['production_source_after'] = candidate.source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASSED, stage='complete')
    except BaseException as error:
        report.update(status='FAIL_SMALL_RECURSIVE_MUX_NATIVE_PLACEMENT_PROBE', error=repr(error)); raise
    finally:
        report['finished_utc'] = candidate.timestamp()
        report['artifacts'] = {str(p): candidate.digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
