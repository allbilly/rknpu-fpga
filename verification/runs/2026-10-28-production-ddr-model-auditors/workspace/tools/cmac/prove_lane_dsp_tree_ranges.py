#!/usr/bin/env python3
"""Real conditional tree integer-sum lemmas; not concrete donor bounds.

The unchanged donor Booth recoder and both actual carry-save tree shapes
are compared independently. Digit reconstruction and the conditional
discarded-carry identity have all free binary inputs. Composition, concrete
range bounds and multiply distributivity remain unproved by this harness.
"""
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
from check_lane_dsp import COMBINATIONAL, SOURCES

MITERS = ROOT / 'tests/cmac/cmac_dsp_tree_range_miters.sv'
DOMAINS = {
    'cmac_tree_5x24_integer_lemma': ({'words': 120}, 25, True),
    'cmac_tree_4x32_integer_lemma': ({'words': 128}, 33, True)}


def validate_graph(design, top):
    assert set(design['modules']) == {top}, 'Unflattened component or retained library'
    module = design['modules'][top]; inputs, width, conditional = DOMAINS[top]
    assert conditional is True
    expected = {**{n: ('input', w) for n, w in inputs.items()},
        'difference': ('output', width), 'mismatch': ('output', 1), 'sum_overflow': ('output', 1)}
    ports, cells = module['ports'], module['cells']
    assert {n: (p['direction'], len(p['bits'])) for n, p in ports.items()} == expected
    bits = [b for n in inputs for b in ports[n]['bits']]
    assert all(type(b) is int for b in bits) and len(set(bits)) == sum(inputs.values()), 'Reduced or coupled inputs'
    types = {c['type'] for c in cells.values()}
    assert types <= COMBINATIONAL | {'$logic_and'} and '$mul' not in types, ('State, assumptions or unknown arithmetic', types)
    guards = [c for c in cells.values() if c['type'] == '$logic_and']
    assert len(guards) == 1
    guard = guards[0]
    assert {n: int(v, 2) for n, v in guard['parameters'].items()} == {
        'A_SIGNED': 0, 'B_SIGNED': 0, 'A_WIDTH': 1, 'B_WIDTH': 1, 'Y_WIDTH': 1}
    assert guard['port_directions'] == {'A': 'input', 'B': 'input', 'Y': 'output'}
    pins = guard['connections']
    assert set(pins) == {'A', 'B', 'Y'} and pins['Y'] == ports['mismatch']['bits']
    for pin, kind, source, size in [('A', '$logic_not', 'sum_overflow', 1),
            ('B', '$reduce_or', 'difference', width)]:
        assert len(pins[pin]) == 1 and type(pins[pin][0]) is int
        drivers = [c for c in cells.values() if c.get('connections', {}).get('Y') == pins[pin]]
        assert len(drivers) == 1 and drivers[0]['type'] == kind
        driver = drivers[0]
        assert driver['connections'] == {'A': ports[source]['bits'], 'Y': pins[pin]}
        assert driver['port_directions'] == {'A': 'input', 'Y': 'output'}
        assert {n: int(v, 2) for n, v in driver['parameters'].items()} == {
            'A_SIGNED': 0, 'A_WIDTH': size, 'Y_WIDTH': 1}


def validate_sat(text, code, negative):
    assert not re.search(r'(?im)^Warning:', text), text[-3000:]
    if negative:
        assert code == 1 and 'SAT proof finished - model found: FAIL!' in text
        assert 'Called with -verify and proof did fail!' in text
    else:
        assert code == 0 and 'ERROR:' not in text and 'SAT proof finished - no model found: SUCCESS!' in text


def main():
    imported = [Path(m.__file__).resolve() for m in list(sys.modules.values())
        if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools')]
    sources = [*SOURCES[:2], MITERS]
    tracked = [*sources, ROOT / 'rtl/vendor/nvdla/LICENSE', Path(__file__).resolve(), *imported]
    before = fingerprint(tracked)
    out = ROOT / f'build/rknpu-dsp-tree-range-proofs/{time.time_ns()}'; out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='preparation', started_utc=timestamp(), source=before,
        supervisor_pid=os.getpid(), python_version=sys.version, commands=[], lemmas={},
        binary_lane_sum_equivalence=False, composed_lane_proof=False, donor_range_bound_proved=False,
        multiply_distributivity_proved=False, full_array_numerical_acceptance=False,
        raw_board_numerical_acceptance=False, physical_fit_verified=False, bitstream_emitted=False,
        hardware_programmed=False,
        scope='Actual donor 5x24 and 4x32 carry-save full-integer sum identities conditional on the complete unsigned input sum fitting the respective width. All 120/128 inputs free, visible overflow predicate and compared 25/33 row-sum bits, no assume cells/cutpoint axioms. Concrete FP16 donor input ranges, multiply distributivity, exact lane composition and full-array/raw-board/physical acceptance remain unproved.')
    def save(): (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(argv, label, negative=None):
        step = dict(argv=list(map(str, argv)), log=str((out / (label + '.log')).relative_to(ROOT)), status='RUNNING')
        report['commands'].append(step); save(); start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                        start_new_session=True) as proc:
                    step['pid'] = proc.pid; save()
                    try: code = proc.wait(timeout=1000)
                    except BaseException:
                        try: os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                        proc.wait(); raise
            step['returncode'] = code; text = (ROOT / step['log']).read_text()
            if negative is not None: validate_sat(text, code, negative)
            else: assert code == 0 and 'ERROR:' not in text, text[-4000:]
            step['status'] = 'PASS'; return text
        except BaseException: step['status'] = 'FAIL'; raise
        finally: step['seconds'] = round(time.monotonic() - start, 3); save()
    def terminate(signum, _frame): raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate); save(); generated = []
    try:
        report['tool_version'] = run(['yosys', '-V'], 'version').strip()
        for path in sorted(set(tracked)):
            target = out / 'snapshot' / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(path.read_bytes()); generated.append(target)
        for top, (inputs, width, conditional) in DOMAINS.items():
            report['stage'] = top
            report['lemmas'][top] = dict(status='RUNNING', free_input_bits=sum(inputs.values()),
                compared_output_bits=width, conditional_on_no_unsigned_row_sum_overflow=conditional)
            save()
            for label, negative in [('negative', True), ('actual', False)]:
                stem = top + '_' + label; graph, script = out / (stem + '.json'), out / (stem + '.ys')
                script.write_text('read_verilog -sv -DSYNTHESIS -DDESIGNWARE_NOEXIST ' +
                    ('-DRK_COMPONENT_NEGATIVE ' if negative else '') +
                    ' '.join(json.dumps(str(p)) for p in sources) + '\n' +
                    'hierarchy -check -top ' + top + '\nproc\nflatten -noscopeinfo\nopt -full\ncheck -assert\n' +
                    'write_json ' + json.dumps(str(graph)) + '\n')
                generated += [script, graph]
                binding = fingerprint([*sources, script]); report.setdefault('lowering_inputs', {})[stem] = binding; save()
                run(['yosys', '-Q', '-T', '-s', script], stem + '_lowering')
                assert fingerprint([*sources, script]) == binding
                validate_graph(json.loads(graph.read_text()), top)
                proof = out / (stem + '_sat.ys'); generated.append(proof)
                proof.write_text('read_json ' + json.dumps(str(graph)) + '\n' +
                    'sat -verify -prove mismatch 0 -show-inputs -show-outputs -timeout 900\n')
                proof_binding = fingerprint([graph, proof]); report.setdefault('proof_inputs', {})[stem] = proof_binding; save()
                run(['yosys', '-Q', '-T', '-s', proof], stem + '_sat', negative)
                assert fingerprint([graph, proof]) == proof_binding and fingerprint([*sources, script]) == binding
            report['lemmas'][top]['status'] = 'PASS_COMPONENT_ONLY'; save()
        assert fingerprint(tracked) == before
        report.update(status='PASS_CONDITIONAL_DONOR_TREE_INTEGER_LEMMAS_ONLY', stage='complete', finished_utc=timestamp(),
            artifacts=fingerprint([*generated, *(out.glob('*.log'))]))
    except BaseException as error:
        report.update(status='FAIL', finished_utc=timestamp(), error=repr(error),
            artifacts=fingerprint([p for p in [*generated, *(out.glob('*.log'))] if p.is_file()])); raise
    finally: save()
    print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
