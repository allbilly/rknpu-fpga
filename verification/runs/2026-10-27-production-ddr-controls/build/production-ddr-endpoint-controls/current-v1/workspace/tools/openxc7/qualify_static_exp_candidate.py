#!/usr/bin/env python3
"""Fresh small native qualification of the isolated double-exp placer.

No global engine pointer, full placement, routing, timing signoff or bitstream
is changed. Original fixtures are executed unchanged with normal refinement
and fatal warnings. The forced illegal pair must still fail before postPlace.
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
from pack_prefix_board import ROOT, QUALIFICATION, DATABASE, CONSTIDS, digest, timestamp, audit
from audit_himbaechel_timing import QUALIFIED
from evidence import source_revision

BUILD = Path('/home/fedora/soDLA/build/ypcb/static-exp-engine-1791401936054675202/report.json')
BUILT = 'BUILT_ISOLATED_STATIC_DOUBLE_EXP_CANDIDATE_NOT_NATIVE_REQUALIFIED_OR_PNR'
DONOR_TOOLS = Path('/home/fedora/soDLA/tools')
CONTROL = ROOT / 'tests/cmac/test_static_exp_qualification_control.py'
LABELS = ('invalid-forced', 'valid-forced', 'invalid-free', 'counter')


def verify_build_metadata(report):
    assert report['status'] == BUILT and report['stage'] == 'complete' and report['finished_utc']
    assert report['part'] == 'xc7k480tffg1156-2'
    assert report['parent_relink_byte_identical'] is True and report['exact_changed_calls'] == 2
    for key in ('assertion_removal', 'objective_or_coefficient_changed', 'FPGA_clock_or_geometry_changed',
                'native_requalification_executed', 'native_placement_executed', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed'):
        assert report[key] is False, 'Invalid build acceptance: ' + key
    assert [c['label'] for c in report['commands']] == [
        'compiler_version', 'relink_parent_identity', 'compile_static_precision',
        'link_precision_candidate', 'native_version']
    assert all(c['returncode'] == 0 and c['status'] == 'PASS_TOOL_EXECUTION_ONLY' for c in report['commands'])


def probe_argv(executable, fixture, xdc, output):
    return list(map(str, [executable, '--chipdb', DATABASE, '--device', 'xc7k480tffg1156-2',
        '--json', fixture, '-o', 'xdc=' + str(xdc), '--placer', 'static', '--no-route',
        '--freq', '50', '--seed', '12350', '--Werror', '--write', output]))


def check_log(code, text, expected):
    assert code == expected, text[-3000:]
    assert not re.search(r'(?im)\bWARNING:|sorry:|target is ignored|matched nothing', text), text[-3000:]
    if expected == 0:
        assert not re.search(r'(?im)\b(?:ERROR|FATAL):', text), text[-3000:]
        for marker in ('Running Static placer...', 'Running simulated annealing placer for refinement.',
                       'Running post-placement legalisation...', 'Program finished normally.'):
            assert marker in text, 'Missing completion marker: ' + marker
        assert 'Static refinement iteration limit:' not in text
    else:
        assert expected == 125
        for marker in ('post-placement validity check failed',
                       'Static refinement failed; aborting placement before postPlace.'):
            assert marker in text, 'Wrong negative diagnostic: ' + marker
        for marker in ('Assertion failure', 'Running post-placement legalisation...', 'Program finished normally.'):
            assert marker not in text, 'Unexpected failed-placement continuation: ' + marker


def validate_placed(path, count, fixture=None):
    # Pure, source-bound donor checker; do not invoke its main/global publisher.
    sys.path.insert(0, str(DONOR_TOOLS))
    from ypcb_lut_pair_engine import validate_placed as checked
    return checked(path, count, fixture)


def verify_precision_qualification(path):
    """Revalidate fresh evidence, not just a qualification's PASS label."""
    path = Path(path).resolve(strict=True)
    q = json.loads(path.read_text())
    assert q['status'] == QUALIFIED and q['static_double_exp_native_requalification'] is True
    assert q['normal_refinement_and_fatal_warnings'] is True
    assert (q['native_positive_placements'], q['lut_output_comparisons']) == (3, 1024)
    rpath = Path(q['build_report']).resolve(strict=True)
    assert rpath.parent == path.parent and str(rpath) in q['inputs']
    for name, sha in q['inputs'].items():
        assert digest(name) == sha, 'Changed qualified input: ' + name
    r = json.loads(rpath.read_text())
    assert r['status'] == QUALIFIED and r['stage'] == 'complete'
    assert r['executable'] == q['executable'] and digest(q['executable']['path']) == q['executable']['sha256']
    build_path = Path(r['candidate_build_report']).resolve(strict=True)
    assert str(build_path) in q['inputs']
    built = json.loads(build_path.read_text())
    verify_build_metadata(built)
    assert built['executable'] == q['executable']
    for name, sha in {**built['inputs'], **built['artifacts']}.items():
        assert digest(name) == sha, 'Changed candidate build input/artifact: ' + name
    assert [c['label'] for c in r['commands']] == ['software_controls', 'generated_check', 'version'] + list(LABELS)
    assert all(c['status'].startswith('PASS_') and c['returncode'] == c['expected_returncode'] for c in r['commands'])
    positives = []
    for c in r['commands'][3:]:
        check_log(c['returncode'], Path(c['log']).read_text(), c['expected_returncode'])
        assert c['argv'] == probe_argv(q['executable']['path'], c['fixture'], r['constraints'], c['output'])
        if c['label'] == 'invalid-forced':
            assert not Path(c['output']).exists()
        else:
            fixture = None if c['label'] == 'counter' else c['fixture']
            result = validate_placed(c['output'], 47 if fixture is None else 49, fixture)
            assert result == c['placement_checks']
            positives.append(result)
    assert len(positives) == 3 and sum(p['lut_output_comparisons'] for p in positives) == 1024
    # Unmodified generic audit enforces the exact native dependency scope/DB.
    return audit(path, DATABASE, CONSTIDS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=BUILD)
    args = parser.parse_args()
    build_path = args.build.resolve(strict=True)
    assert build_path.is_relative_to(Path('/home/fedora/soDLA/build/ypcb'))
    out = Path('/home/fedora/soDLA/build/ypcb') / f'static-exp-qualification-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        commands=[], candidate_build_report=str(build_path), scope=__doc__,
        full_board_native_placement_executed=False, native_routing_executed=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False,
        drc_signoff=False, bitstream_emitted=False, hardware_programmed=False,
        production_source_before=source_revision())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, expected=0, native=False, **detail):
        step = dict(label=label, argv=list(map(str, argv)), expected_returncode=expected,
            cwd=str(ROOT), log=str(out / (label + '.log')), timeout_seconds=600, status='RUNNING', **detail)
        report['commands'].append(step)
        start = time.monotonic()
        save()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as proc:
                step['pid'] = proc.pid
                save()
                try: code = proc.wait(timeout=600)
                except BaseException:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            if native: check_log(code, text, expected)
            else: assert code == expected and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text), text[-3000:]
            step['status'] = 'PASS_TOOL_EXECUTION_ONLY' if expected == 0 else 'PASS_EXPECTED_REJECTION_ONLY'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        audit(QUALIFICATION, DATABASE, CONSTIDS)
        built = json.loads(build_path.read_text())
        verify_build_metadata(built)
        before = {**built['inputs'], **built['artifacts']}
        before[str(build_path)] = digest(build_path)
        before[str(Path(__file__).resolve())] = digest(__file__)
        before[str(CONTROL)] = digest(CONTROL)
        for name, sha in before.items(): assert digest(name) == sha, 'Changed admitted build: ' + name
        # Preserve ROOT orchestration bindings in this report and bind their
        # frozen copies in the native qualification. Do not broaden the generic
        # native dependency whitelist or discard native compilation inputs.
        native_inputs = {}
        orchestration = {}
        for name, sha in before.items():
            p = Path(name)
            if p.is_relative_to(ROOT):
                orchestration[name] = sha
                snapshot = out / 'orchestration-at-launch' / p.relative_to(ROOT)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, snapshot)
                assert digest(snapshot) == sha
                native_inputs[str(snapshot)] = sha
            else:
                native_inputs[name] = sha
        report.update(source=before, orchestration_inputs=orchestration, executable=built['executable'],
                      source_revision=built['source_revision'], part=built['part'])
        parent = json.loads(Path(built['parent_build_report']).read_text())
        old = {Path(c['log']).stem.removeprefix('probe-'): c for c in parent['commands'] if Path(c['log']).stem.startswith('probe-')}
        constraints = Path(old['counter']['argv'][old['counter']['argv'].index('-o') + 1].removeprefix('xdc='))
        assert str(constraints) in native_inputs
        report['constraints'] = str(constraints)
        executable = built['executable']['path']
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        version = run('version', [executable, '--version']).strip()
        assert version == built['native_version']
        report.update(stage='native_probes', native_version=version)
        for label in LABELS:
            fixture = Path(old[label]['argv'][old[label]['argv'].index('--json') + 1])
            assert str(fixture) in native_inputs, 'Unbound original probe fixture'
            output = out / (label + '-placed.json')
            run(label, probe_argv(executable, fixture, constraints, output), 125 if label == 'invalid-forced' else 0,
                native=True, fixture=str(fixture), output=str(output))
            if label == 'invalid-forced': assert not output.exists()
            else:
                report['commands'][-1]['placement_checks'] = validate_placed(output, 47 if label == 'counter' else 49,
                    None if label == 'counter' else fixture)
                save()
        for name, sha in before.items(): assert digest(name) == sha, 'Changed qualification input: ' + name
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=QUALIFIED, stage='complete', finished_utc=timestamp())
        save()
        native_inputs.update({str(p): digest(p) for p in out.rglob('*') if p.is_file()})
        q = dict(status=QUALIFIED, part=built['part'], source_revision=built['source_revision'],
            build_report=str(out / 'report.json'), executable=built['executable'], inputs=native_inputs,
            static_double_exp_native_requalification=True, normal_refinement_and_fatal_warnings=True,
            native_positive_placements=3, lut_output_comparisons=1024,
            scope='Fresh three small native placements and one illegal-pair rejection, normal refinement and Werror; '
                  'two host exponential overloads widened. Not full-core PNR, DSP/-2 timing, electrical/DRC or numerical signoff.')
        qpath = out / 'qualification.json'
        qpath.write_text(json.dumps(q, indent=2, sort_keys=True) + '\n')
        verify_precision_qualification(qpath)
        print(qpath, flush=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error), finished_utc=timestamp())
        save()
        raise


if __name__ == '__main__':
    main()
