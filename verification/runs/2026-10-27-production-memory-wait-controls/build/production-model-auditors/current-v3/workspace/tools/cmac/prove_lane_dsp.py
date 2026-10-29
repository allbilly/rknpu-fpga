#!/usr/bin/env python3
"""Fresh binary proof of the isolated lane sum/tag; no native or FPGA claim."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp
from check_lane_dsp import SOURCES, TOP, sanity_miter, validate_graph


def main():
    out = ROOT / f'build/rknpu-lane-dsp-formal/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    negative = out / 'negative_miter.sv'
    negative.write_text(sanity_miter(SOURCES[-1].read_text()))
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    tracked = [*SOURCES, negative, ROOT / 'rtl/vendor/nvdla/LICENSE', Path(__file__).resolve(), *imported]
    report = dict(status='RUNNING', stage='binary_formal', started_utc=timestamp(),
        supervisor_pid=os.getpid(), python_version=sys.version, source=fingerprint(tracked), commands=[],
        seed='none; unconstrained 37-bit binary input domain',
        relevant_binary_input_bits=37, compared_binary_output_bits=40,
        binary_lane_sum_equivalence=False, native_numerical_acceptance=False,
        mapped_numerical_acceptance=False, full_array_numerical_acceptance=False,
        raw_board_numerical_acceptance=False, physical_fit_verified=False,
        bitstream_emitted=False, hardware_programmed=False,
        scope='Fresh isolated compensated donor lane-sum/tag binary SAT comparison, with actual one-bit negative. Sign/pre-shifted magnitude inputs, not IEEE bits. Not identical carry-save rows, X/reset/configuration, native fixtures, mapped numerics, full array/raw board, placed fit, timing/electrical/DRC, FPGA or RK acceptance.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative_proof=False, timeout=1000):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)),
            status='RUNNING', expected='actual SAT countermodel' if negative_proof else 'zero')
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            assert fingerprint(tracked) == report['source'], 'Changed proof dependency'
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=timeout)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            assert fingerprint(tracked) == report['source'], 'Changed proof dependency'
            if negative_proof:
                assert code == 1 and 'SAT proof finished - model found: FAIL!' in text, text[-3000:]
                assert 'Called with -verify and proof did fail!' in text, text[-3000:]
            else:
                assert code == 0 and 'ERROR:' not in text, text[-3000:]
            step['status'] = 'PASS'; return text
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - started, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save()
    generated = [negative]
    try:
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes()); generated.append(target)
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        for label, miter in [('negative', negative), ('actual', SOURCES[-1])]:
            graph, script = out / (label + '.json'), out / (label + '_lower.ys')
            script.write_text('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
                ' '.join(json.dumps(str(p)) for p in [*SOURCES[:-1], miter]) + '\n' +
                'hierarchy -check -top ' + TOP + '\nproc\nflatten -noscopeinfo\n' +
                'opt -full\ncheck -assert\nwrite_json ' + json.dumps(str(graph)) + '\n')
            generated += [graph, script]
            run(['yosys', '-Q', '-T', '-s', script], label + '_lowering')
            report[label + '_cells'] = validate_graph(json.loads(graph.read_text()))
            binding = fingerprint([graph]); report[label + '_proof_inputs'] = binding; save()
            proof = out / (label + '_sat.ys'); generated.append(proof)
            proof.write_text('read_json ' + json.dumps(str(graph)) + '\n' +
                'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
            text = run(['yosys', '-Q', '-T', '-s', proof], label + '_sat', label == 'negative')
            assert fingerprint([graph]) == binding, 'Changed SAT graph'
            if label == 'actual':
                assert 'SAT proof finished - no model found: SUCCESS!' in text, text[-3000:]
                report['binary_lane_sum_equivalence'] = True
        assert fingerprint(tracked) == report['source'], 'Changed proof dependency'
        report.update(status='PASS_ISOLATED_CORRECTED_DSP_LANE_BINARY_SAT_ONLY', stage='complete',
            finished_utc=timestamp(), artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()]))
        raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
