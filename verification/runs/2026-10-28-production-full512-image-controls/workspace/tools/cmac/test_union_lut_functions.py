#!/usr/bin/env python3
"""Four-state proof of actual proposed union-LUT classes, not a mapped board.

Every proposal must belong to the exact completed read-only analysis domain.
No netlist is changed; the production array/board and physical gates remain.
"""
from collections import Counter
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
from analyze_union_lut_pairs import verify_proposals
from pair_board_luts import BENCH, four_state_bench
from test_fixed_array_board import verify_manifest
from test_lut_pair_unisim import COMMIT, pinned_models, unisim_bench, validate_result
from test_paired_mapped_array import validate_pair_metadata


def validate_analysis(report):
    assert report['status'] == 'ANALYZED_UNION_FANIN_LUT_OPPORTUNITIES_ONLY'
    assert report['stage'] == 'complete'
    assert (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    for name in ('netlist_changed', 'function_classes_hdl_acceptance', 'numerical_netlist_acceptance',
            'packed_resource_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[name] is False, 'Misrepresented analysis acceptance'
    copies = report['implementation_copies']
    assert copies['ypcb_cmac_array_top'] == 1 and sorted(copies.values()) == [1, 16]
    assert set(copies) == set(report['module_statistics'])
    total = sum(copies[name] * report['module_statistics'][name]['proposed_pairs'] for name in copies)
    assert total > 0 and report['weighted_opportunities']['additional_disjoint_pairs'] == total
    assert report['projected_lut_primitives'] == report['candidate_lut_primitives'] - total
    assert report['unique_proposed_function_classes'] > 0


def validate_domain(report, modules, records, classes):
    validate_analysis(report)
    assert set(records) == set(report['implementation_copies'])
    keys = [json.dumps(c, sort_keys=True, separators=(',', ':')) for c in classes]
    assert len(keys) == len(set(keys)) == report['unique_proposed_function_classes']
    assert all(type(c['fanins']) is int and 1 <= c['fanins'] <= 5 for c in classes)
    domain, actual = dict(zip(keys, classes)), {}
    for name, proposed in records.items():
        assert len(proposed) == report['module_statistics'][name]['proposed_pairs']
        local = {r['function_key']: domain[r['function_key']] for r in proposed}
        verify_proposals(modules[name], proposed, local)
        actual.update(local)
    assert actual == domain, 'Unlisted or missing actual proposal functions'
    return 2 * sum(4 ** c['fanins'] for c in classes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-report', required=True, type=Path)
    args = parser.parse_args()
    analysis_path = args.analysis_report.resolve()
    assert analysis_path.is_relative_to(ROOT)
    analysis = json.loads(analysis_path.read_text())
    validate_analysis(analysis)
    verify_manifest(analysis['source']); verify_manifest(analysis['artifacts'])
    parent_path = ROOT / analysis['parent_report']
    parent = json.loads(parent_path.read_text()); validate_pair_metadata(parent)
    candidate_path = parent_path.parent / 'paired_hierarchy.json'
    assert str(candidate_path.relative_to(ROOT)) in analysis['source']['files']
    records_path, classes_path = [analysis_path.parent / name for name in ('proposals.json', 'function_classes.json')]
    assert all(str(p.relative_to(ROOT)) in analysis['artifacts']['files'] for p in (records_path, classes_path))
    modules = json.loads(candidate_path.read_text())['modules']
    classes = json.loads(classes_path.read_text())
    comparisons = validate_domain(analysis, modules, json.loads(records_path.read_text()), classes)
    models, license_path = pinned_models(ROOT / 'build/reference/xilinx-unisim')
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [Path(__file__).resolve(), analysis_path, parent_path, candidate_path, records_path, classes_path,
        *models, license_path, *imported]
    out = ROOT / f'build/rknpu-union-lut-functions/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='model_preparation', started_utc=timestamp(), source=fingerprint(tracked),
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[],
        analysis_report=str(analysis_path.relative_to(ROOT)), parent_report=str(parent_path.relative_to(ROOT)),
        channels=32, kernels=16, parallel_products=512,
        proposed_pairs=analysis['weighted_opportunities']['additional_disjoint_pairs'],
        function_classes=len(classes), comparisons_per_model=comparisons,
        seed='none; exhaustive union-input 0/1/X/Z enumeration for every actual proposed class',
        model_commit=COMMIT, defines=[], netlist_changed=False, full_circuit_export_acceptance=False,
        full_array_numerical_acceptance=False, full_board_numerical_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Every actual proposed disjoint residual union-fanin LUT function class under frozen Yosys and pinned unmodified Xilinx models, with real INIT-bit negatives and compile/execution hashes. Not a transformed/exported netlist, repair of existing pair output roles, full array/raw-board numeric/hold/reset/fault proof, packed utilization, routing/timing/DRC, bitstream, FPGA or RK acceptance.')
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
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            if simulation is not None:
                marker = validate_result(text, code, len(classes), comparisons, simulation == 'negative')
                if marker: report.setdefault('function_results', {})[label] = marker
            else:
                assert code == 0 and 'ERROR:' not in text, text[-3000:]
                if label.endswith('_compile'):
                    assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    try:
        for command in ('iverilog', 'vvp'):
            report[command + '_version'] = run([command, '-V'], command + '_version').splitlines()[0]
        data = run(['yosys-config', '--datdir'], 'datadir').strip()
        yosys = Path(data) / 'xilinx/cells_sim.v'
        assert hashlib.sha256(yosys.read_bytes()).hexdigest() == parent['primitive_model_original']['sha256']
        report['model_repository_commit'] = run(['git', '-C', ROOT / 'build/reference/xilinx-unisim',
            'rev-parse', 'HEAD'], 'model_commit').strip()
        assert report['model_repository_commit'] == COMMIT
        assert run(['git', '-C', ROOT / 'build/reference/xilinx-unisim', 'status', '--porcelain'], 'model_clean').strip() == ''
        frozen = out / 'models'; frozen.mkdir()
        generated = []
        for path in [yosys, *models, license_path]:
            target = frozen / path.name; target.write_bytes(path.read_bytes())
            assert target.read_bytes() == path.read_bytes(); generated.append(target)
        report['frozen_models'] = fingerprint(generated)
        for path in tracked:
            if path == candidate_path: continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        for model, model_paths, builder in [('yosys', [frozen / yosys.name], four_state_bench),
                ('unisim', [frozen / p.name for p in models], unisim_bench)]:
            for negative in (True, False):
                label = model + ('_negative' if negative else '_actual')
                report['stage'] = label; save()
                bench = out / (label + '.sv'); bench.write_text(builder(classes, negative))
                binary = out / (label + '.vvp'); generated += [bench, binary]
                inputs = [bench, *model_paths, classes_path, records_path, candidate_path]
                before = fingerprint(inputs)
                report.setdefault('compile_inputs', {})[label] = before; save()
                run(['iverilog', '-g2012', '-s', BENCH, '-o', binary, *model_paths, bench], label + '_compile')
                assert fingerprint(inputs) == before, 'Changed compile inputs'
                executable = fingerprint([binary])
                report.setdefault('execution_inputs', {})[label] = executable; save()
                run(['vvp', binary], label + '_test', 'negative' if negative else 'actual')
                assert fingerprint(inputs) == before and fingerprint([binary]) == executable, 'Changed simulation inputs'
        assert fingerprint(tracked) == report['source'], 'Changed proof dependency'
        report.update(status='PASS_ACTUAL_UNION_LUT_FUNCTION_CLASSES_ONLY', stage='complete', finished_utc=timestamp(),
            artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException:
        report.update(status='FAIL', finished_utc=timestamp()); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
