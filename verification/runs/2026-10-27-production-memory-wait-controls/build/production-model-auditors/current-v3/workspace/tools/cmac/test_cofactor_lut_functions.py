#!/usr/bin/env python3
"""Exhaustive live-I5 cofactor classes with unmodified Yosys and UNISIM.

Small fixture and completed actual residual-analysis domains are distinct.
No transformed board, packed savings, circuit/export or physical acceptance.
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
from analyze_cofactor_lut_pairs import (IMPLEMENTATIONS, key, load_parent, proposals,
    truth_table, verify_proposals_cofactor)
from test_fixed_array_board import verify_manifest
from test_lut_pair_unisim import COMMIT, pinned_models
from test_cofactor_lut_pair_control import fixture

BENCH = 'rk_lut_cofactor_four_state'
LUT6_HASH = '0b6aff98f29cb3cd2745269519d84efc04b6b1a4f1244906558b5b37d67f7d87'


def validate_function(function):
    assert set(function) == {'mode', 'fanins', 'first', 'second', 'init'}
    assert function['mode'] == 'live_selector_zero_cofactor' and function['fanins'] == 6
    assert re.fullmatch('[01]{64}', function['init'])
    for field, kinds in [('first', 'LUT[1-5]'), ('second', 'LUT6')]:
        spec = function[field]; assert set(spec) == {'kind', 'init', 'pins'}
        assert re.fullmatch(kinds, spec['kind'])
        size = int(spec['kind'][-1]); assert len(spec['pins']) == size
        assert re.fullmatch('[01]+', spec['init']) and len(spec['init']) == 2 ** size
        limit = 5 if field == 'first' else 6
        wires = [p for p in spec['pins'] if type(p) is int]
        assert len(set(wires)) == len(wires) and all(0 <= p < limit for p in wires)
        assert all(type(p) is int or p in ('0', '1') for p in spec['pins'])
        if field == 'second': assert sorted(spec['pins']) == list(range(6))
        table = truth_table(spec['init'], tuple(spec['pins']), limit)
        actual = int(function['init'], 2) & ((1 << (2 ** limit)) - 1)
        assert table == actual, 'Cofactor class binary truth changed'


def four_state_bench(classes, negative=False):
    assert classes and len({key(c) for c in classes}) == len(classes)
    for function in classes: validate_function(function)
    lines = ['`timescale 1ns/1ps', f'module {BENCH};',
        f'  reg [{len(classes)-1}:0] done=0;', '  integer comparisons=0;']
    for i, function in enumerate(classes):
        base = f'c{i}'
        # Both models receive an actual transition from X to pattern zero;
        # all 4096 patterns, including zero, keep the same check and delay.
        lines += [f"  reg [5:0] {base}_inputs=6'bx;",
            f'  wire {base}_a, {base}_b, {base}_o5, {base}_o6;']
        for label, field in [('a', 'first'), ('b', 'second')]:
            spec = function[field]
            pins = [f'.I{j}({base}_inputs[{p}])' if type(p) is int else f".I{j}(1'b{p})"
                for j, p in enumerate(spec['pins'])]
            lines.append(f"  {spec['kind']} #(.INIT({len(spec['init'])}'b{spec['init']})) " +
                f'{base}_{label}_ref(' + ', '.join(pins + [f'.O({base}_{label})']) + ');')
        init = format(int(function['init'], 2) ^ (1 if negative and i == 0 else 0), '064b')
        pins = [f'.I{j}({base}_inputs[{j}])' for j in range(6)]
        lines += [f"  LUT6_2 #(.INIT(64'b{init})) {base}_dut(" +
            ', '.join(pins + [f'.O5({base}_o5)', f'.O6({base}_o6)']) + ');',
            f'  initial begin: {base}_test', '    integer pattern, pin;',
            '    for(pattern=0;pattern<4096;pattern=pattern+1) begin',
            '      for(pin=0;pin<6;pin=pin+1)', '        case((pattern>>(2*pin))&3)',
            f"          0: {base}_inputs[pin]=1'b0;", f"          1: {base}_inputs[pin]=1'b1;",
            f"          2: {base}_inputs[pin]=1'bx;", f"          3: {base}_inputs[pin]=1'bz;",
            '        endcase', '      #1;',
            f'      if({base}_o5 !== {base}_a || {base}_o6 !== {base}_b)',
            f'        $fatal(1,"LUT_COFACTOR_MISMATCH class={i} pattern=%0d",pattern);',
            '      comparisons=comparisons+2;', '    end', f'    done[{i}]=1;', '  end']
    expected = 8192 * len(classes)
    lines += ['  initial begin', '    wait(&done);',
        f'    if(comparisons!={expected}) $fatal(1,"comparison count");',
        f'    $display("PASS LUT_COFACTOR_FOUR_STATE classes={len(classes)} comparisons=%0d",comparisons);',
        '    $finish;', '  end',
        '  initial begin #8192; $fatal(1,"LUT_COFACTOR_WATCHDOG"); end', 'endmodule']
    return '\n'.join(lines) + '\n'


def validate_result(text, code, count, negative=False):
    assert not re.search(r'(?im)\b(?:warning|error):', text), text[-3000:]
    if negative:
        assert code == 1 and re.search(r'LUT_COFACTOR_MISMATCH class=0 pattern=0(?:\s|$)', text)
        assert 'PASS ' not in text
    else:
        expected = f'PASS LUT_COFACTOR_FOUR_STATE classes={count} comparisons={8192 * count}'
        assert code == 0 and 'FATAL:' not in text
        assert [line for line in text.splitlines() if line.startswith('PASS ')] == [expected]
        return expected


def load_actual(path):
    assert path.is_relative_to(ROOT)
    report = json.loads(path.read_text())
    assert report['status'] == 'ANALYZED_RESIDUAL_ZERO_COFACTOR_LUT_OPPORTUNITIES_ONLY'
    assert report['stage'] == 'complete' and (report['channels'], report['kernels'], report['parallel_products']) == (32, 16, 512)
    for field in ('netlist_changed', 'function_classes_hdl_acceptance', 'numerical_netlist_acceptance',
            'packed_resource_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[field] is False
    verify_manifest(report['source']); verify_manifest(report['artifacts'])
    analysis_path = ROOT / report['analysis_report']; analysis = json.loads(analysis_path.read_text())
    parent_path = (ROOT / analysis['parent_report']).resolve()
    _, modules, copies, dependencies = load_parent(parent_path)
    assert dict(copies) == report['implementation_copies']
    paths = [path.parent / n for n in ('proposals.json', 'function_classes.json', 'excluded_union_cells.json')]
    assert all(str(p.relative_to(ROOT)) in report['artifacts']['files'] for p in paths)
    records, listed, exclusions = [json.loads(p.read_text()) for p in paths]
    prior_path = analysis_path.parent / 'proposals.json'; prior = json.loads(prior_path.read_text())
    assert set(records) == set(exclusions) == IMPLEMENTATIONS
    classes = {key(c): c for c in listed}
    assert classes and len(classes) == len(listed) == report['unique_function_classes']
    actual = {}
    for name in IMPLEMENTATIONS:
        omitted = {r[f] for r in prior[name] for f in ('first', 'second')}
        assert exclusions[name] == sorted(omitted)
        local = {r['function_key']: classes[r['function_key']] for r in records[name]}
        verify_proposals_cofactor(modules[name], omitted, records[name], local); actual.update(local)
        assert len(records[name]) == report['module_statistics'][name]['proposed_pairs']
    assert actual == classes
    assert sum(copies[n] * len(records[n]) for n in copies) == report['weighted_additional_disjoint_pairs']
    return listed, [path, analysis_path, prior_path, *paths, *dependencies]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--fixture', action='store_true'); group.add_argument('--analysis-report', type=Path)
    args = parser.parse_args()
    if args.fixture:
        _, functions, _ = proposals(fixture(), set()); classes = [functions[k] for k in sorted(functions)]
        dependencies = []
    else: classes, dependencies = load_actual(args.analysis_report.resolve())
    for function in classes: validate_function(function)
    model_root = ROOT / 'build/reference/xilinx-unisim'
    models, license_path = pinned_models(model_root)
    lut6 = model_root / 'verilog/src/unisims/LUT6.v'
    assert hashlib.sha256(lut6.read_bytes()).hexdigest() == LUT6_HASH; models.append(lut6)
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT) and
        Path(m.__file__).resolve().relative_to(ROOT).parts[0] in ('tools', 'tests')]
    tracked = [Path(__file__).resolve(), *dependencies, *models, license_path, *imported]
    before = fingerprint(tracked); out = ROOT / f'build/rknpu-cofactor-lut-functions/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='models', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source=before, commands=[], fixture=args.fixture, python_version=sys.version,
        model_commit=COMMIT, function_classes=len(classes), comparisons_per_model=8192 * len(classes),
        seed='none; exhaustive 0/1/X/Z on all six actual live inputs', defines=[],
        full_circuit_export_acceptance=False, full_array_numerical_acceptance=False,
        full_board_numerical_acceptance=False, packed_resource_acceptance=False,
        physical_fit_verified=False, bitstream_emitted=False, hardware_programmed=False,
        scope='Small cofactor fixture only' if args.fixture else 'Actual completed residual cofactor function classes only')
    if not args.fixture: report['analysis_report'] = str(args.analysis_report.resolve().relative_to(ROOT))
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=None):
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
            if negative is not None:
                result = validate_result(text, code, len(classes), negative)
                if result: report.setdefault('function_results', {})[label] = result
            else:
                assert code == 0 and 'ERROR:' not in text
                if label.endswith('_compile'): assert not re.search(r'(?im)\b(?:warning|error):', text)
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save(); generated = []
    try:
        for name in ('iverilog', 'vvp'): report[name + '_version'] = run([name, '-V'], name + '_version').splitlines()[0]
        assert run(['git', '-C', model_root, 'rev-parse', 'HEAD'], 'model_commit').strip() == COMMIT
        assert run(['git', '-C', model_root, 'status', '--porcelain'], 'model_clean').strip() == ''
        yosys = Path(run(['yosys-config', '--datdir'], 'datadir').strip()) / 'xilinx/cells_sim.v'
        frozen = out / 'models'; frozen.mkdir()
        for path in [yosys, *models, license_path]:
            target = frozen / path.name; target.write_bytes(path.read_bytes())
            assert target.read_bytes() == path.read_bytes(); generated.append(target)
        report['frozen_models'] = fingerprint(generated)
        for path in sorted(set(tracked)):
            if path.name == 'paired_hierarchy.json': continue
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        # The installed model may be outside the workspace manifest. Bind it
        # separately, freeze it byte-for-byte, and check it again at the end.
        snapshot = out / 'snapshot/installed_yosys/cells_sim.v'
        snapshot.parent.mkdir(parents=True, exist_ok=True); snapshot.write_bytes(yosys.read_bytes()); generated.append(snapshot)
        report['installed_yosys_model'] = dict(path=str(yosys), sha256=hashlib.sha256(yosys.read_bytes()).hexdigest())
        domain_path = out / 'function_classes.json'; domain_path.write_text(json.dumps(classes, indent=2) + '\n'); generated.append(domain_path)
        for model, files in [('yosys', [frozen / yosys.name]), ('unisim', [frozen / p.name for p in models])]:
            for negative in (True, False):
                label = model + ('_negative' if negative else '_actual'); report['stage'] = label; save()
                bench, binary = out / (label + '.sv'), out / (label + '.vvp')
                bench.write_text(four_state_bench(classes, negative)); generated += [bench, binary]
                inputs = [bench, domain_path, *files]; binding = fingerprint(inputs)
                report.setdefault('compile_inputs', {})[label] = binding; save()
                run(['iverilog', '-g2012', '-s', BENCH, '-o', binary, *files, bench], label + '_compile')
                assert fingerprint(inputs) == binding
                executable = fingerprint([binary]); report.setdefault('execution_inputs', {})[label] = executable; save()
                run(['vvp', binary], label + '_test', negative)
                assert fingerprint(inputs) == binding and fingerprint([binary]) == executable
        assert fingerprint(tracked) == before
        assert yosys.read_bytes() == (frozen / yosys.name).read_bytes()
        assert hashlib.sha256(yosys.read_bytes()).hexdigest() == report['installed_yosys_model']['sha256']
        assert json.loads(domain_path.read_text()) == classes
        report.update(status='PASS_SMALL_COFACTOR_FUNCTION_FIXTURE_ONLY' if args.fixture else
            'PASS_ACTUAL_RESIDUAL_COFACTOR_FUNCTION_CLASSES_ONLY', stage='complete', finished_utc=timestamp(),
            artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
