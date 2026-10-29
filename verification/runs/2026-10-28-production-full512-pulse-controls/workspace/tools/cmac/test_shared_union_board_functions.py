#!/usr/bin/env python3
"""Independent actual/fixture union and O6-repair function-class HDL gate.

The complete shared-board analysis and reversible transform define the
actual domain. Exhaustive 0/1/X/Z tests run under frozen Yosys and pinned
unmodified UNISIM, with real one-bit negatives. No whole-board, export,
packed resource, timing or FPGA acceptance follows from a class proof.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests/cmac'))
from evidence import ROOT, fingerprint, timestamp
from prepare_shared_union_board import (IMPLEMENTATIONS, key, load_parent,
    transform, validate_analysis, verify_transform)
from test_fixed_array_board import verify_manifest
from pair_board_luts import BENCH, four_state_bench
from test_lut_pair_unisim import COMMIT, pinned_models, unisim_bench, validate_result
from test_shared_union_board_control import fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--analysis-report', type=Path)
    group.add_argument('--fixture', action='store_true')
    args = parser.parse_args()
    dependencies = []
    if args.fixture:
        original, proposals, domain, implementations = fixture()
        parent = None
    else:
        analysis_path = args.analysis_report.resolve(); assert analysis_path.is_relative_to(ROOT)
        analysis = json.loads(analysis_path.read_text()); validate_analysis(analysis)
        verify_manifest(analysis['source']); verify_manifest(analysis['artifacts'])
        parent_path = (ROOT / analysis['parent_report']).resolve()
        parent, modules, copies, dependencies = load_parent(parent_path)
        assert dict(copies) == analysis['implementation_copies']
        assert parent['lut_count'] == analysis['candidate_lut_primitives']
        candidate_path = parent_path.parent / 'paired_hierarchy.json'
        original = json.loads(candidate_path.read_text())
        record_path, class_path = [analysis_path.parent / n for n in ('proposals.json', 'function_classes.json')]
        assert all(str(p.relative_to(ROOT)) in analysis['artifacts']['files'] for p in (record_path, class_path))
        proposals, listed = [json.loads(p.read_text()) for p in (record_path, class_path)]
        domain = {key(f): f for f in listed}
        assert len(domain) == len(listed) == analysis['unique_proposed_function_classes']
        for name in IMPLEMENTATIONS:
            assert len(proposals[name]) == analysis['module_statistics'][name]['proposed_pairs']
        implementations = IMPLEMENTATIONS
        dependencies += [analysis_path, record_path, class_path]
    candidate, certificate, functions = transform(original, proposals, domain, implementations)
    classes = [functions[k] for k in sorted(functions)]
    assert classes and all(1 <= c['fanins'] <= 5 for c in classes)
    comparisons = 2 * sum(4 ** c['fanins'] for c in classes)
    models, license_path = pinned_models(ROOT / 'build/reference/xilinx-unisim')
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT) and
        Path(m.__file__).resolve().relative_to(ROOT).parts[0] in ('tools', 'tests')]
    tracked = [Path(__file__).resolve(), *dependencies, *models, license_path, *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-shared-union-board-functions/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='model_preparation', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], fixture=args.fixture,
        model_commit=COMMIT, function_classes=len(classes), comparisons_per_model=comparisons,
        seed='none; exhaustive 0/1/X/Z for every actual transformed union/O6-role function', defines=[],
        full_circuit_export_acceptance=False, full_array_numerical_acceptance=False,
        full_board_numerical_acceptance=False, packed_resource_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Small fixture' if args.fixture else 'Actual complete shared-board union plus split/swapped O6-role function domain',
        acceptance_limit='Combinational primitive function classes only. No circuit export, full array/raw board numerical/reset/fault suite, placed fit, timing/electrical/DRC, FPGA or RK acceptance.')
    if not args.fixture:
        report.update(analysis_report=str(analysis_path.relative_to(ROOT)),
            channels=32, kernels=16, parallel_products=512)
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, simulation=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=14400)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if simulation is not None:
                marker = validate_result(text, code, len(classes), comparisons, simulation == 'negative')
                if marker: report.setdefault('function_results', {})[label] = marker
            else:
                assert code == 0 and 'ERROR:' not in text, text[-3000:]
                if label.endswith('_compile'): assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    generated = []
    try:
        for command in ('iverilog', 'vvp'):
            report[command + '_version'] = run([command, '-V'], command + '_version').splitlines()[0]
        yosys = Path(run(['yosys-config', '--datdir'], 'datadir').strip()) / 'xilinx/cells_sim.v'
        if parent is not None:
            assert hashlib.sha256(yosys.read_bytes()).hexdigest() == parent['primitive_model_original']['sha256']
        assert run(['git', '-C', ROOT / 'build/reference/xilinx-unisim', 'rev-parse', 'HEAD'], 'model_commit').strip() == COMMIT
        assert run(['git', '-C', ROOT / 'build/reference/xilinx-unisim', 'status', '--porcelain'], 'model_clean').strip() == ''
        frozen = out / 'models'; frozen.mkdir()
        for path in [yosys, *models, license_path]:
            target = frozen / path.name; target.write_bytes(path.read_bytes())
            assert target.read_bytes() == path.read_bytes(); generated.append(target)
        report['frozen_models'] = fingerprint(generated)
        for path in sorted(set(tracked)):
            if not args.fixture and path == candidate_path: continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        graph_path, cert_path, classes_path = [out / n for n in
            ('transformed_hierarchy.json', 'transform_certificate.json', 'function_classes.json')]
        graph_path.write_text(json.dumps(candidate) + '\n'); cert_path.write_text(json.dumps(certificate, indent=2) + '\n')
        classes_path.write_text(json.dumps(classes, indent=2) + '\n'); generated += [graph_path, cert_path, classes_path]
        for model, model_paths, builder in [('yosys', [frozen / yosys.name], four_state_bench),
                ('unisim', [frozen / p.name for p in models], unisim_bench)]:
            for negative in (True, False):
                label = model + ('_negative' if negative else '_actual'); report['stage'] = label; save()
                bench = out / (label + '.sv'); bench.write_text(builder(classes, negative))
                binary = out / (label + '.vvp'); generated += [bench, binary]
                inputs = [bench, *model_paths, classes_path, cert_path, graph_path]
                binding = fingerprint(inputs); report.setdefault('compile_inputs', {})[label] = binding; save()
                run(['iverilog', '-g2012', '-s', BENCH, '-o', binary, *model_paths, bench], label + '_compile')
                assert fingerprint(inputs) == binding
                executable = fingerprint([binary]); report.setdefault('execution_inputs', {})[label] = executable; save()
                run(['vvp', binary], label + '_test', 'negative' if negative else 'actual')
                assert fingerprint(inputs) == binding and fingerprint([binary]) == executable
        verify_transform(original, json.loads(graph_path.read_text()), json.loads(cert_path.read_text()),
            {key(f): f for f in json.loads(classes_path.read_text())}, implementations)
        assert fingerprint(tracked) == before, 'Changed class-proof dependency'
        assert hashlib.sha256(yosys.read_bytes()).hexdigest() == hashlib.sha256((frozen / yosys.name).read_bytes()).hexdigest()
        report.update(status='PASS_SMALL_SHARED_UNION_ROLE_FUNCTION_FIXTURE_ONLY' if args.fixture else
            'PASS_ACTUAL_SHARED_UNION_ROLE_FUNCTION_CLASSES_ONLY', stage='complete', finished_utc=timestamp(),
            artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()]))
        raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
