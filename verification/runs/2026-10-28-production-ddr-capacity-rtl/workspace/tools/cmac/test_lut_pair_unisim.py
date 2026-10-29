#!/usr/bin/env python3
"""Test every actual paired-board LUT function with pinned, unmodified UNISIM.

This is a local combinational 0/1/X/Z gate, not full-board simulation, GSR,
mapped-array numerical acceptance, routed timing, or hardware validation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from pair_board_luts import BENCH, four_state_bench, verify as verify_pairs
from test_fixed_array_board import verify_manifest
from test_paired_mapped_array import validate_pair_metadata, validate_pair_proof_metadata

COMMIT = '1c8e05fd1e9a79ceb8b996a0996674122eed086f'
MODEL_HASHES = {
    'LUT1.v': '23be0311d281a612284fb355fb0778ac83e4d3a484c93e6a5a9d27dc471cbfc2',
    'LUT2.v': '7d148945093cd956ad3e924290b8fc778f5ea4b323397ebf5a6f78a3f0bbde06',
    'LUT3.v': '86711b745e4b5a71bf71eb6ab2747a2467da354949b45c7c5e4851dab5f6ed96',
    'LUT4.v': 'e1785d5dc015e002bef5b249a536144bbf2c2b6932192701cb6c828e817a8b75',
    'LUT5.v': '5eb071b18bcc3d48cefccd19c42dc1f7db6087272480c3e6015921f4bfec9ead',
    'LUT6_2.v': 'd4927b9fa9299db1332257c215c48fad31954dbab189d2bd2aa098571d65f945',
}
LICENSE_HASH = 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pinned_models(directory):
    paths = [directory / 'verilog/src/unisims' / name for name in MODEL_HASHES]
    for path in paths:
        assert digest(path) == MODEL_HASHES[path.name], ('Changed pinned UNISIM model', path)
    license_path = directory / 'LICENSE'
    assert digest(license_path) == LICENSE_HASH, 'Changed UNISIM license'
    return paths, license_path


def validate_classes(report, classes):
    assert len(classes) == report['unique_function_classes'] and classes
    keys = [json.dumps(c, sort_keys=True, separators=(',', ':')) for c in classes]
    assert len(set(keys)) == len(keys), 'Duplicated function classes'
    assert all(type(c['fanins']) is int and 0 <= c['fanins'] <= 5 for c in classes)
    assert 2 * sum(4 ** c['fanins'] for c in classes) == report['expected_four_state_comparisons']
    return dict(zip(keys, classes))


def unisim_bench(classes, negative=False):
    # UNISIM LUT4/5/O5 are procedural models sensitive only to input events.
    # An already-zero reg produces no first-pattern event in Icarus. Start
    # unknown, then apply the SAME pattern zero and check it normally at #1.
    # This changes no pin binding, truth table, delay, assertion or count.
    # Constant-only functions have no driven input to wake that model; do not
    # silently discard them or claim this harness validates their startup.
    assert all(c['fanins'] > 0 for c in classes), 'UNISIM startup harness requires a driven input in every class'
    original = four_state_bench(classes, negative)
    result = original
    substitutions = []
    for i in range(len(classes)):
        before, after = f'reg [4:0] c{i}_inputs=0;', f"reg [4:0] c{i}_inputs=5'bx;"
        assert result.count(before) == 1
        result = result.replace(before, after)
        substitutions.append((before, after))
    restored = result
    for before, after in substitutions: restored = restored.replace(after, before)
    assert restored == original, 'Changed test beyond input startup initialization'
    return result


def validate_result(text, code, classes, comparisons, negative=False):
    assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
    if negative:
        assert code == 1, ('Expected actual assertion exit, not a tool crash', code)
        assert re.search(r'LUT_PAIR_MISMATCH class=0 pattern=0(?:\s|$)', text)
        assert 'PASS ' not in text
    else:
        expected = f'PASS LUT_PAIR_FOUR_STATE classes={classes} comparisons={comparisons}'
        assert code == 0 and 'FATAL:' not in text, text[-3000:]
        assert [line for line in text.splitlines() if line.startswith('PASS ')] == [expected]
        return expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paired-report', required=True, type=Path)
    parser.add_argument('--model-repository', type=Path, default=ROOT / 'build/reference/xilinx-unisim')
    args = parser.parse_args()
    pair_path, model_root = args.paired_report.resolve(), args.model_repository.resolve()
    assert pair_path.is_relative_to(ROOT) and model_root.is_relative_to(ROOT)
    pair_report = json.loads(pair_path.read_text())
    validate_pair_metadata(pair_report)
    models, license_path = pinned_models(model_root)
    parent_path = ROOT / pair_report['parent_report']
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY'
    assert (parent['channels'], parent['kernels'], parent['parallel_products']) == (32, 16, 512)
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in parent['commands'])
    assert pair_report['parent_source_sha256'] == parent['source']['sha256']
    original_path = parent_path.parent / 'mapped_hierarchy.json'
    pair_out = pair_path.parent
    class_path, certificate_path, candidate_path = [pair_out / name for name in
        ('function_classes.json', 'pair_certificate.json', 'paired_hierarchy.json')]
    tracked = [Path(__file__).resolve(), pair_path, parent_path, original_path,
               class_path, certificate_path, candidate_path, *models, license_path]
    tracked.extend(Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    out = ROOT / f'build/rknpu-lut-pair-unisim/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='parent_validation', started_utc=timestamp(),
        supervisor_pid=os.getpid(), source=fingerprint(tracked), commands=[],
        parent_report=str(pair_path.relative_to(ROOT)), parent_source_sha256=pair_report['source']['sha256'],
        model_repository=str(model_root.relative_to(ROOT)), model_repository_url='https://github.com/Xilinx/XilinxUnisimLibrary',
        model_commit=COMMIT, model_hashes=MODEL_HASHES, license_sha256=LICENSE_HASH,
        startup_contract='Only driven input reg initialization is X instead of already zero, to wake vendor procedural models. Pattern zero and every later pattern are checked with the original delays/counts/assertions/pin ties; constant-only classes explicitly fail.',
        defines=[], python_version=sys.version, seed='none; exhaustive 0/1/X/Z function-class enumeration',
        channels=32, kernels=16, parallel_products=512, physical_lut_pairs=pair_report['physical_lut_pairs'],
        unique_function_classes=pair_report['unique_function_classes'],
        expected_four_state_comparisons=pair_report['expected_four_state_comparisons'],
        full_board_numerical_acceptance=False, mapped_array_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Every literal-restored actual board LUT-pair function class, under six unmodified pinned Xilinx UNISIM LUT models and Icarus four-state simulation. Not full-array/raw-board protocol/numerical/fault/reset simulation, GSR/sequential/BRAM models, XIL_TIMING, SDF, physical fit/timing/DRC, bitstream, FPGA or RK silicon.')

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, label, simulation=None):
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str((out / (label + '.log')).relative_to(ROOT)))
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream,
                        stderr=subprocess.STDOUT, start_new_session=True) as proc:
                    step['pid'] = proc.pid
                    save()
                    try:
                        code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait()
                        raise
            step['returncode'] = code
            result = (ROOT / step['log']).read_text()
            if simulation is not None:
                marker = validate_result(result, code, report['unique_function_classes'],
                    report['expected_four_state_comparisons'], simulation == 'negative')
                if marker: report['four_state_function_class_result'] = marker
            else:
                assert code == 0 and 'ERROR:' not in result, result[-3000:]
                if label.endswith('_compile'):
                    assert not re.search(r'(?im)\b(?:warning|error):', result), result[-3000:]
            step['status'] = 'PASS'
            return result
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    save()
    try:
        verify_manifest(pair_report['source'])
        verify_manifest(pair_report['artifacts'])
        validate_pair_proof_metadata(pair_report, pair_out)
        verify_manifest(parent['source'])
        assert digest(original_path) == parent['artifacts']['files'][str(original_path.relative_to(ROOT))]
        classes = json.loads(class_path.read_text())
        class_map = validate_classes(pair_report, classes)
        verify_pairs(json.loads(original_path.read_text()), json.loads(candidate_path.read_text()),
                     json.loads(certificate_path.read_text()), class_map)
        report['actual_pair_function_domain_verified'] = True
        assert (pair_out / 'actual.sv').read_text() == four_state_bench(classes)
        assert (pair_out / 'negative.sv').read_text() == four_state_bench(classes, True)
        assert run(['git', '-C', model_root, 'rev-parse', 'HEAD'], 'model_commit').strip() == COMMIT
        assert run(['git', '-C', model_root, 'status', '--porcelain'], 'model_clean').strip() == ''
        report['iverilog_version'] = run(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
        report['vvp_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
        frozen_dir = out / 'models'
        frozen_dir.mkdir()
        frozen_models = []
        for path in [*models, license_path]:
            frozen = frozen_dir / path.name
            frozen.write_bytes(path.read_bytes())
            assert digest(frozen) == digest(path)
            if path != license_path: frozen_models.append(frozen)
        generated = [*frozen_models, frozen_dir / 'LICENSE']
        report['frozen_models'] = fingerprint(generated)
        snapshot = out / 'paired_report_snapshot.json'
        snapshot.write_bytes(pair_path.read_bytes())
        generated.append(snapshot)
        for path in tracked:
            if path in (original_path, candidate_path, certificate_path): continue
            dest = out / 'snapshot' / path.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(path.read_bytes())
        for label, negative in (('negative', True), ('actual', False)):
            report['stage'] = label
            bench, executable = out / (label + '.sv'), out / (label + '.vvp')
            bench.write_text(unisim_bench(classes, negative))
            inputs = [class_path, certificate_path, candidate_path, original_path, *generated, bench]
            report.setdefault('function_class_inputs', {})[label] = fingerprint(inputs)
            save()
            run(['iverilog', '-g2012', '-s', BENCH, '-o', executable, *frozen_models, bench], label + '_compile')
            assert fingerprint(inputs) == report['function_class_inputs'][label], 'Inputs changed during compile'
            report.setdefault('function_class_executables', {})[label] = fingerprint([executable])
            save()
            run(['vvp', executable], label + '_test', simulation=label)
            assert fingerprint(inputs) == report['function_class_inputs'][label], 'Inputs changed during simulation'
            assert fingerprint([executable]) == report['function_class_executables'][label], 'Changed simulator executable'
            generated.extend((bench, executable))
        assert fingerprint(tracked) == report['source'], 'Source changed during verification'
        for manifests in (report['function_class_inputs'], report['function_class_executables']):
            for manifest in manifests.values(): verify_manifest(manifest)
        pinned_models(model_root)
        report.update(status='PASS_LUT_PAIR_UNISIM_FUNCTION_CLASSES_ONLY', stage='complete',
            artifacts=fingerprint(generated + [ROOT / c['log'] for c in report['commands']]))
    except BaseException as exc:
        report.update(status='FAIL', reason=str(exc) or repr(exc))
        raise
    finally:
        report['finished_utc'] = timestamp()
        save()
        print(out / 'report.json')
    print(report['status'], report['four_state_function_class_result'])


if __name__ == '__main__': main()
