#!/usr/bin/env python3
"""Prove the actual zero-register DSP model's signed 25x18/bias binary contract.

No primitive rewrite, warning waiver, full-array or physical acceptance.
"""
import argparse
from collections import Counter
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
import audit_dsp_prefix_pin_cone as cone

MITER = ROOT / 'tests/cmac/dsp_prefix_actual_model_miter.sv'
TOP = MITER.stem
SUCCESS = 'SAT proof finished - no model found: SUCCESS!'
FAILURE = 'SAT proof finished - model found: FAIL!'


def validate_miter(text):
    assert text == MITER.read_text()
    assert text.count('dsp_prefix_omitted_input_cone_control actual_model(') == 1
    assert text.count('$signed(A[24:0]) * $signed(B)') == 1
    assert text.count("{{5{mathematical_product[42]}}, mathematical_product} + 48'h000055550000") == 1
    assert text.count("mathematical_sum ^ (NEGATIVE ? 48'h1 : 48'h0)") == 1
    assert 'assign ok = actual == expected;' in text
    assert not re.search(r'\b(?:assume|anyconst|anyseq|force)\b', text)


def validate_result(text, code, negative=False):
    assert not re.search(r'(?im)warning:|\bWarning\b|timed out|timeout reached|unknown cell', text)
    if negative:
        assert code != 0 and FAILURE in text and SUCCESS not in text
        errors = re.findall(r'(?m)^ERROR: (.*)$', text)
        assert errors == ['Called with -verify and proof did fail!']
    else:
        assert code == 0 and text.count(SUCCESS) == 1 and FAILURE not in text
        assert not re.search(r'ERROR:|\berror:', text, re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cone-report', type=Path, required=True)
    args = parser.parse_args()
    parent_path = args.cone_report.resolve()
    assert parent_path.is_relative_to(ROOT) and parent_path.is_file()
    parent = json.loads(parent_path.read_text())
    assert parent['status'] == 'PASS_ISOLATED_ACTUAL_DSP_OMITTED_INPUT_CONE_ONLY'
    assert parent['stage'] == 'complete' and parent['structural_cone_acceptance'] is True
    assert parent['compiler_diagnostics_accepted'] is parent['numerical_acceptance'] is False
    for manifest in (parent['source'], parent['artifacts']):
        assert fingerprint([ROOT / name for name in manifest['files']]) == manifest
    actual_model = parent_path.parent / 'positive.json'
    raw = json.loads(actual_model.read_text())
    cone.validate_positive(cone.output_cone(raw))
    assert parent['matched_actual_dsp_instances'] == 32
    assert parent['actual_parameters'] == cone.primitive.PARAMETERS
    validate_miter(MITER.read_text())
    out = ROOT / f'build/rknpu-dsp-prefix-actual-model-proof/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    frozen_model, miter = out / 'actual_unchanged_model.json', out / MITER.name
    frozen_model.write_bytes(actual_model.read_bytes())
    miter.write_bytes(MITER.read_bytes())
    scripts = {}
    for kind, negative in (('negative', 1), ('positive', 0)):
        script = out / (kind + '.ys')
        script.write_text(f'read_json {frozen_model}\nread_verilog {miter}\n'
            f'chparam -set NEGATIVE {negative} {TOP}\nhierarchy -check -top {TOP}\n'
            f'flatten\nwreduce\nopt -full\ncheck -assert\nwrite_json {out / (kind + ".json")}\n'
            f'sat -verify -prove ok 1 -show-inputs -show-outputs -timeout 120 '
            f'-dump_json {out / (kind + "_counterexample.json")}\n')
        scripts[kind] = script
    tracked = [Path(__file__).resolve(), ROOT / 'tools/evidence.py', Path(cone.__file__).resolve(),
        Path(cone.primitive.__file__).resolve(), MITER, parent_path, actual_model, frozen_model, miter,
        *scripts.values()]
    before = fingerprint(tracked)
    for path in tracked:
        target = out / 'snapshot' / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    report = dict(status='RUNNING', stage='formal', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source=before, commands=[], cone_report=str(parent_path.relative_to(ROOT)),
        actual_model_sha256=hashlib.sha256(actual_model.read_bytes()).hexdigest(),
        actual_parameters=parent['actual_parameters'], actual_constant_pins=parent['actual_constant_pins'],
        symbolic_input_bits=74, relevant_operand_bits=43, checked_output_bits=48,
        input_assumptions=[], seed=None, simulation_only_checks_removed=True, binary_only=True,
        actual_model_binary_proof_acceptance=False, compiler_diagnostics_accepted=False,
        full_array_numerical_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False, scope='Actual unchanged model elaboration from completed source-bound '
        '26-omitted-input cone control, under all 32 actual-kernel parameters and constants. '
        'All A[29:0], B[17:0] and omitted[25:0] are unconstrained binary inputs; independently compare '
        'all 48 P bits with sign-extended signed A[24:0]*B plus exact bias modulo 2^48. '
        'A real one-bit wrong-golden negative must fail the same SAT gate. No main warning admission, '
        'all-X/DSP timing, full-array numerical, physical FPGA or RK compatibility claim.')

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(argv, label, negative=None):
        log = out / (label + '.log')
        step = dict(argv=list(map(str, argv)), status='RUNNING', log=str(log.relative_to(ROOT)))
        report['commands'].append(step)
        save()
        started = time.monotonic()
        try:
            with log.open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid
                    save()
                    try:
                        code = proc.wait(timeout=180)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait()
                        raise
            step['returncode'] = code
            text = log.read_text()
            if negative is not None:
                validate_result(text, code, negative)
            else:
                assert code == 0 and not re.search(r'ERROR:|\berror:', text, re.I)
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').splitlines()[0]
        for kind in ('negative', 'positive'):
            run(['yosys', '-Q', '-T', '-s', scripts[kind]], kind, kind == 'negative')
            assert fingerprint(tracked) == before
            graph = json.loads((out / (kind + '.json')).read_text())
            assert set(graph['modules']) == {TOP}
            module = graph['modules'][TOP]
            assert set(module['ports']) == {'A', 'B', 'omitted', 'actual', 'expected', 'ok'}
            kinds = Counter(cell['type'] for cell in module['cells'].values())
            assert set(kinds) <= cone.COMBINATIONAL | {'$scopeinfo'}
            # Exactly matching signed multiplication operators may be merged by
            # ordinary opt_merge; no arithmetic graph or proof input is replaced.
            assert kinds['$mul'] == 1, 'Actual and independent multiplier structures must agree'
            report[kind + '_cell_types'] = dict(sorted(kinds.items()))
        assert frozen_model.read_bytes() == actual_model.read_bytes() and miter.read_bytes() == MITER.read_bytes()
        report.update(status='PASS_ISOLATED_ACTUAL_DSP_MODEL_ALL_BINARY_OPERANDS_ONLY', stage='complete',
            actual_model_binary_proof_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path != out / 'report.json'])
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
