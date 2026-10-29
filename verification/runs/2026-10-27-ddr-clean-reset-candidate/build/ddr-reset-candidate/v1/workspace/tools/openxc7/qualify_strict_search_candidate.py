#!/usr/bin/env python3
"""Fresh small native qualification of bounded strict search; not full fit.

Run the unchanged illegal pair and three original positive placements with
normal refinement/Werror, then the original four-DSP/six-BRAM P&R input and
literal feature checks. Require actual native strict-search completion logs.
No original fixture, gate, old report or global tool pointer is changed.
No SHA256SUMS file is written.
"""
from collections import Counter
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
from build_strict_search_candidate import verify_build_metadata, PRECISION_BUILD
from strict_search_candidate import PRECISION_SOURCE, PRECISION_OBJECT, verify_source_transition, compile_argv
from build_dsp_constant_candidate import link_argv
from verify_corrected_native_evidence import verify_corrected_evidence, NATIVE
from probe_corrected_dsp_checkpoint import ROOT, digest, timestamp, source_revision
from qualify_static_exp_candidate import LABELS, probe_argv, check_log, validate_placed
from qualify_dsp_constant_candidate import check_native_log
from probe_prefix_native_config import SELECTED, parse_native_features
from check_corrected_dsp_features import compare_corrected_dsp
from check_prefix_native_features import compare_bram
from place_prefix_board import bind_report, verify_bindings

QUALIFIED = 'QUALIFIED_SMALL_NATIVE_BOUNDED_STRICT_SEARCH_AND_DSP_BRAM_PNR_NOT_FULL_FIT_OR_SIGNOFF'
CONTROL = ROOT / 'tests/cmac/test_strict_search_qualification.py'
COMMANDS = ['software_controls', 'generated_check', 'version', *LABELS, 'small_native_PNR_FASM']
FLAGS = ('full_native_placement_executed', 'full_native_routing_executed', 'full_board_numerical_acceptance',
         'physical_fit_verified', 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted',
         'hardware_programmed', 'default_engine_pointer_changed', 'original_fixtures_changed')


def verify_metadata(report):
    assert report['status'] == QUALIFIED and report['stage'] == 'complete' and report['finished_utc']
    assert report['part'] == 'xc7k480tffg1156-2' and report['full_parallel_products'] == 512
    assert (report['native_positive_placements'], report['lut_output_comparisons']) == (3, 1024)
    assert report['illegal_pair_rejected_before_postPlace'] is True
    assert report['small_native_PNR_FASM_executed'] is True
    assert report['native_control_cell_counts']['DSP48E1_DSP48E1'] == 4
    assert report['native_control_cell_counts']['RAMB36E1_RAMB36E1'] == 6
    assert len(report['DSP_feature_comparison']) == 4 and len(report['BRAM_feature_comparison']) == 6
    assert [c['label'] for c in report['commands']] == COMMANDS
    for c in report['commands']:
        expected = 125 if c['label'] == 'invalid-forced' else 0
        assert c['returncode'] == c['expected_returncode'] == expected
        assert c['status'] == ('PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY')
    assert report['production_source_before'] == report['production_source_after']
    assert all(report[key] is False for key in FLAGS), 'Small qualification cannot grant full/physical acceptance'


def check_strict_log(text):
    begin = re.findall(r'(?m)^Info: RKNPU strict search: begin .*$', text)
    complete = re.findall(r'(?m)^Info: RKNPU strict search: complete .*$', text)
    assert len(begin) == len(complete) == 1, 'Missing actual strict-search begin/completion'
    assert text.index(begin[0]) < text.index(complete[0])
    assert re.search(r'\bqueue=0\b', complete[0]), 'Nonempty legalizer queue'
    for line in begin + complete:
        assert re.search(r'\bvalidity=1$', line), 'Native validity check disabled'
        for counter in ('pops', 'committed', 'samples', 'outside', 'empty', 'plain_checks', 'plain_rejects', 'cluster_checks', 'cluster_rejects'):
            assert re.search(r'\b' + counter + r'=\d+\b', line), 'Missing native search counter'
    assert re.search(r'\boutside=0\b', complete[0]), 'Unexpected out-of-grid sample'
    return dict(begin=begin[0], complete=complete[0])


def small_argv(executable, q, out):
    original = next(c for c in q['commands'] if c['label'] == 'small_native_PNR_FASM')['argv']
    changes = {original[0]: str(executable)}
    for name in ('routed.json', 'control.fasm', 'placement.json'):
        old = str(NATIVE.parent / name)
        changes[old] = str(out / name)
        if name != 'routed.json':
            key = 'fasm=' if name.endswith('.fasm') else 'placement='
            changes[key + old] = key + str(out / name)
    result = [changes.get(value, value) for value in original]
    assert result[result.index('--freq') + 1] == '50' and result[result.index('--seed') + 1] == '3588'
    assert result[result.index('--device') + 1] == 'xc7k480tffg1156-2'
    assert '--Werror' in result and '--no-pack' not in result and '--no-place' not in result
    for key in ('--force', '--timing-allow-fail', '--placer-static-refine-max-iterations'): assert key not in result
    return result


def compare_features(out, q):
    selected = json.loads(SELECTED.read_text())
    features, repeated = parse_native_features((out / 'control.fasm').read_text())
    placed = json.loads((out / 'placement.json').read_text())
    native = next(iter(json.loads((out / 'routed.json').read_text())['modules'].values()))
    counts = dict(Counter(c['type'] for c in native['cells'].values()))
    assert counts == q['native_control_cell_counts'], 'Changed actual primitive membership'
    assert set(native['cells']) == set(placed) and len({v['nextpnr_bel'] for v in placed.values()}) == len(placed)
    origins = q['control_origins']
    dsps = {n: compare_corrected_dsp(features, placed[n], selected[s], native['cells'][n])
            for n, s in origins.items() if selected[s]['type'] == 'DSP48E1'}
    brams = {n: compare_bram(features, placed[n], selected[s]) for n, s in origins.items() if selected[s]['type'] == 'RAMB36E1'}
    return dict(native_control_cell_counts=counts, DSP_feature_comparison=dsps, BRAM_feature_comparison=brams,
                native_FASM_features=len(features), native_FASM_repeated_idempotent_STEPDOWN_lines=repeated)


def verify_candidate_build(path, built, before):
    verify_build_metadata(built); bind_report(path, built, before); verify_bindings(before)
    source = path.parent / 'common/place/placer_static.cc'
    verify_source_transition(PRECISION_SOURCE.read_text(), source.read_text())
    precision = json.loads(PRECISION_BUILD.read_text())
    parent = json.loads(Path(built['parent_build_report']).read_text())
    old_link = next(c['argv'] for c in parent['commands'] if c['label'] == 'link_DSP_constant_candidate')
    commands = {c['label']: c for c in built['commands']}
    assert commands['relink_corrected_parent_identity']['argv'] == link_argv(old_link, path.parent / 'corrected-parent-relinked', {})
    assert digest(path.parent / 'corrected-parent-relinked') == built['parent_executable']['sha256']
    obj = path.parent / 'placer_static.cc.o'
    old_compile = next(c for c in precision['commands'] if c['label'] == 'compile_static_precision')
    assert commands['compile_strict_search_candidate']['argv'] == compile_argv(old_compile['argv'], source, obj)
    assert commands['compile_strict_search_candidate']['cwd'] == old_compile['cwd']
    assert commands['link_strict_search_candidate']['argv'] == link_argv(old_link, Path(built['executable']['path']), {PRECISION_OBJECT: obj})
    assert digest(built['executable']['path']) == built['executable']['sha256']
    for c in built['commands']:
        assert not re.search(r'(?im)\b(?:warning|error|fatal):', Path(c['log']).read_text()), 'Changed native build diagnostic'


def verify_qualification(path):
    path = Path(path).resolve(strict=True); report = json.loads(path.read_text()); verify_metadata(report)
    before = {}; bind_report(path, report, before)
    built_path = Path(report['candidate_build_report']); built = json.loads(built_path.read_text())
    verify_candidate_build(built_path, built, before)
    assert built['executable'] == report['executable'] and built['native_version'] == report['native_version']
    q = json.loads(NATIVE.read_text())
    for step in report['commands']:
        label, text = step['label'], Path(step['log']).read_text()
        if label in LABELS:
            old = next(c for c in q['commands'] if c['label'] == label)
            xdc = Path(next(v[4:] for v in old['argv'] if v.startswith('xdc=')))
            output = path.parent / (label + '-placed.json')
            assert step['argv'] == probe_argv(report['executable']['path'], old['fixture'], xdc, output)
            check_log(step['returncode'], text, step['expected_returncode']); check_strict_log(text)
            if label == 'invalid-forced': assert not output.exists()
            else: assert validate_placed(output, 47 if label == 'counter' else 49,
                    None if label == 'counter' else old['fixture']) == step['placement_checks']
        elif label == 'small_native_PNR_FASM':
            assert step['argv'] == small_argv(report['executable']['path'], q, path.parent)
            check_native_log(text); check_strict_log(text)
            assert all(report[key] == value for key, value in compare_features(path.parent, q).items())
        else: assert not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text)
    verify_bindings(before)
    return report, before


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--build', type=Path, required=True)
    args = parser.parse_args(); build_path = args.build.resolve(strict=True)
    assert build_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/strict-search-qualification-{time.time_ns()}'; out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'executed_source.py'); shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        scope=__doc__, commands=[], source={}, candidate_build_report=str(build_path), part='xc7k480tffg1156-2',
        full_parallel_products=512, production_source_before=source_revision(), **{key: False for key in FLAGS})
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, expected=0, timeout=600):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), cwd=str(ROOT),
            expected_returncode=expected, timeout_seconds=timeout, status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_CORE, (0, 0))) as process:
                step['pid'] = process.pid; save()
                try: code = process.wait(timeout=timeout)
                except BaseException:
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait(); step['returncode'] = process.returncode; raise
            step['returncode'] = code; text = Path(step['log']).read_text()
            if label in LABELS: check_log(code, text, expected); step['search_progress'] = check_strict_log(text)
            else: assert code == expected and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):', text), text[-4000:]
            if label == 'small_native_PNR_FASM': check_native_log(text); step['search_progress'] = check_strict_log(text)
            step['status'] = 'PASS_EXPECTED_REJECTION_ONLY' if expected else 'PASS_TOOL_EXECUTION_ONLY'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3); save()
    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        q, before = verify_corrected_evidence()
        built = json.loads(build_path.read_text()); verify_candidate_build(build_path, built, before)
        files = {Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for path in files:
            sha = digest(path); assert str(path) not in before or before[str(path)] == sha
            before[str(path)] = sha
        verify_bindings(before)
        assert report['production_source_before'] == q['production_source_after'] == built['production_source_after']
        report.update(source=before, executable=built['executable'], native_version=built['native_version'], stage='native_legality_controls',
            software_runtime=dict(executable=str(Path(sys.executable).resolve()), version=sys.version))
        run('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'], timeout=120)
        run('generated_check', ['make', 'generated-check'], timeout=120)
        executable = built['executable']['path']; assert run('version', [executable, '--version'], timeout=60).strip() == built['native_version']
        positives = []
        for label in LABELS:
            old = next(c for c in q['commands'] if c['label'] == label)
            fixture = Path(old['fixture']); xdc = Path(next(v[4:] for v in old['argv'] if v.startswith('xdc=')))
            output = out / (label + '-placed.json')
            run(label, probe_argv(executable, fixture, xdc, output), expected=125 if label == 'invalid-forced' else 0)
            if label == 'invalid-forced': assert not output.exists()
            else:
                result = validate_placed(output, 47 if label == 'counter' else 49, None if label == 'counter' else fixture)
                report['commands'][-1]['placement_checks'] = result; positives.append(result); save()
        assert sum(v['lut_output_comparisons'] for v in positives) == 1024
        report.update(native_positive_placements=3, lut_output_comparisons=1024,
                      illegal_pair_rejected_before_postPlace=True, stage='small_native_PNR_FASM', small_native_PNR_FASM_executed=True)
        run('small_native_PNR_FASM', small_argv(executable, q, out), timeout=3600)
        report.update(compare_features(out, q)); verify_bindings(before)
        report['production_source_after'] = source_revision()
        report.update(status=QUALIFIED, stage='complete', finished_utc=timestamp()); verify_metadata(report)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
