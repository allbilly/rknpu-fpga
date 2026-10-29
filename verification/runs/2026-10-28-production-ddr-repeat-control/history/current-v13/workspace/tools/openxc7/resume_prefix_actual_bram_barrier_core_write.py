#!/usr/bin/env python3
"""Continue actual BRAM barrier verification with a stronger core-write property.

Preserve and reproduce the previous missing-show-wire frontend failure. Its
actual cone, library qualification and initialization miter already completed;
revalidate those exact native results, without copying them as fresh evidence.
In a new test-only clocked model, additionally require effective physical port
B writes to equal actual core-fire AND actual request-write. This makes the
previously unused B-write alias a real property dependency, not a kept dummy.
All actual fifty register folds, producer cuts and ghost updates stay identical.
Run fresh temporal negative/positive proofs with the original strict validators,
scripts, assumptions and limits. Never count a frontend error as a negative.
No original model, source, archive, input, live build, gate or SHA256SUMS is edited.
Scope is binary sampled-reset safety, not full startup or physical signoff.
"""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prove_prefix_actual_bram_barrier as previous
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings
from pack_prefix_board import ROOT, digest, timestamp
from evidence import source_revision

FAILED = ROOT / 'build/openxc7/prefix-actual-bram-barrier-1791452093147189951/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_actual_bram_core_write_control.py'
PASS = 'PROVED_ACTUAL_WORKING_BRAM_BINARY_SAMPLED_RESET_PHYSICAL_PIN_OWNERSHIP_READ_BARRIER_AND_CORE_WRITE_GATING_NOT_FULL_STARTUP_OR_FPGA_SIGNOFF'
FRONTEND_ERROR = "ERROR: Failed to parse show expression `bram_core_we'."


def strengthened_model(cone):
    old = previous.clock_model(cone)
    q = {r['original_primitive']['connections']['Q'][0]: i for i, r in enumerate(cone['controller_registers'])}
    other = {w: i for i, w in enumerate(sorted(set(map(int, cone['producer_cuts'])) - set(q)))}
    w, = cone['signals']['demo.memory.req_write']
    assert type(w) is int and w >= 2
    alias = 'storage_state[' + str(q[w]) + ']' if w in q else (
        'producer_input[' + str(other[w]) + ']' if w in other else 't0_' + str(w))
    anchor = 'wire physical_ports_exclusive=!(bram_host_enable&&bram_core_enable);\n'
    addition = 'wire core_request_write=' + alias + ';\n'
    addition += 'wire physical_core_write_equivalence=((bram_core_enable&&bram_core_we)==(core_fire&&core_request_write));\n'
    text = source_shaped(old, ((anchor, addition + anchor),
                               ('&&physical_read_barrier;', '&&physical_read_barrier&&physical_core_write_equivalence;')))
    assert text.replace(addition, '').replace('&&physical_read_barrier&&physical_core_write_equivalence;', '&&physical_read_barrier;') == old
    assert text.count('reg [49:0] storage_state;') == 1 and 'storage_state=' not in text
    assert not re.search(r'\b(?:assume|anyseq|anyconst|force|keep)\b', text)
    return text


def initialization_script(root, negative):
    library = root / 'unchanged_selected_controller_cells.v'
    paired = root / 'actual-BRAM-pin-initialization-miter.v'
    label = 'initialization_' + ('negative' if negative else 'positive')
    witness = root / (label + '-counterexample.json')
    return ('read_verilog ' + str(library) + '\nread_verilog ' + str(paired) + '\nchparam -set NEGATIVE ' + str(int(negative)) +
            ' prefix_actual_bram_miter\nhierarchy -check -top prefix_actual_bram_miter\nflatten\nproc\nopt -full\nwreduce\nopt -full\ncheck -assert\n'
            'sat -verify -prove ok 1 -show state -show compared_0 -show compared_1 -show init_phase -show ok -timeout 120 -dump_json ' + str(witness) + '\n')


def admit(before):
    original, certificate, _, _, _, _, _ = previous.admit(before)
    report = json.loads(FAILED.read_text())
    assert report['status'] == 'FAIL' and report['stage'] == 'native_temporal_negative' and report['finished_utc']
    assert report['error'] == 'AssertionError()'
    assert report['physical_pin_read_barrier_proved_binary'] is False and report['physical_pin_port_ownership_proved_binary'] is False
    bind_report(FAILED, report, before)
    verify_bindings(before)
    verify_bindings(report['execution_inputs'])
    root = FAILED.parent
    cone = json.loads((root / 'actual-BRAM-pin-controller-cone.json').read_text())
    assert cone['controller_registers'] == original['controller_registers']
    assert cone['producer_cuts'] == original['producer_cuts']
    assert all(cone['cells'].get(n) == c for n, c in original['cells'].items())
    assert sorted(set(cone['cells']) - set(original['cells'])) == report['added_actual_cells'] == ['rk_mapped_cell_49970', 'rk_mapped_cell_50664', 'rk_mapped_cell_50665']
    assert len(cone['cells']) == report['actual_cone_cells'] == 1328
    assert len(cone['producer_cuts']) == report['actual_producer_bits'] == 1019
    assert cone['full_primitive_counts'] == original['full_primitive_counts']
    assert previous.completed.previous.qualified.clear_certificate(cone) == certificate
    assert (root / 'actual-BRAM-pin-clocked-model.v').read_text() == previous.clock_model(cone)
    assert (root / 'actual-BRAM-pin-initialization-miter.v').read_text() == previous.miter(cone)
    library, definitions = previous.temporal.base.selected_definitions(previous.temporal.base.LIBRARY.read_bytes(), set(report['actual_cone_primitive_counts']))
    assert library == (root / 'unchanged_selected_controller_cells.v').read_bytes()
    assert definitions == report['selected_unchanged_library_definitions']
    text, width = previous.temporal.proof.prior.declared.qualify_bench(cone['cells'])
    bench = root / 'binary_library_control.sv'
    assert text == bench.read_text() and width == 1538
    footer = previous.temporal.proof.prior.results.expected_finish(bench, text)
    commands = {c['label']: c for c in report['commands']}
    assert len(commands) == len(report['commands']) == 13
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0
               for n, c in commands.items() if n not in ('initialization_negative', 'temporal_negative'))
    vendor = Path(commands['vendor_test']['log']).read_text()
    synthesis = Path(commands['synthesis_test']['log']).read_text()
    assert previous.compare_corpora(vendor, synthesis, width, footer, len(cone['cells'])) == report['binary_library_qualification']
    wrong = Path(commands['synthesis_wrong_golden_test']['log']).read_text()
    a = previous.temporal.proof.prior.results.vectors(vendor, width, footer)
    b = previous.temporal.proof.prior.results.vectors(wrong, width, footer)
    assert a[0] ^ b[0] == 1 and a[1:] == b[1:]
    assert report['binary_library_real_negative'] == 'REJECTED_EXECUTED_FIRST_VECTOR_ONE_BIT_MUTATION'
    for label, negative in (('initialization_negative', True), ('initialization_positive', False)):
        c = commands[label]
        previous.temporal.base.prior.state.raw.validate_result(Path(c['log']).read_text(), c['returncode'], negative)
        assert (root / (label + '.ys')).read_text() == initialization_script(root, negative)
        if negative:
            assert c['status'] == 'PASS_EXPECTED_REAL_FORMAL_NEGATIVE'
            wave = json.loads((root / (label + '-counterexample.json')).read_text())
            values = {s['name']: s for s in wave['signal']}
            assert values['init_phase']['wave'] == '14' and values['ok']['wave'] == '04'
            assert values['compared_0']['data'] == values['compared_1']['data']
            assert re.fullmatch('[01]+', values['compared_0']['data'][0]) and int(values['state']['data'][0], 2) <= 2
        else:
            assert not (root / (label + '-counterexample.json')).exists()
    failed = commands['temporal_negative']
    assert failed['status'] == 'FAIL' and failed['returncode'] == 1
    log = Path(failed['log']).read_text()
    assert re.findall(r'(?m)^ERROR:.*$', log) == [FRONTEND_ERROR]
    assert previous.completed.previous.FAILURE not in log and previous.completed.previous.SUCCESS not in log
    assert not (root / 'temporal_negative-counterexample.json').exists()
    assert (root / 'temporal_negative.ys').read_text() == previous.script(root / 'unchanged_selected_controller_cells.v', root / 'actual-BRAM-pin-clocked-model.v', True, root / 'temporal_negative-counterexample.json')
    try:
        previous.completed.previous.validate(log, 1, True)
    except AssertionError:
        pass
    else:
        raise AssertionError('Original strict validator accepted a frontend error as its negative')
    verify_bindings(before)
    return cone, library


def main():
    out = ROOT / f'build/openxc7/prefix-actual-bram-core-write-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='admission', scope=__doc__, started_utc=timestamp(),
                  supervisor_pid=os.getpid(), source={}, commands=[], seed=None, python_version=sys.version,
                  production_source_before=source_revision(), full_target_parallel_products=512,
                  actual_controller_state_bits=50, preserved_frontend_failure_report=str(FAILED),
                  physical_pin_read_barrier_proved_binary=False, physical_pin_port_ownership_proved_binary=False,
                  physical_core_write_gating_proved_binary=False, initialization_host_data_independence_proved_binary=False,
                  full_board_startup_independence_proved=False, temporal_port_ownership_proved=False,
                  write_before_read_proved=False, four_state_library_equivalence=False,
                  between_edge_reset_pulses_modeled=False, initialization_liveness_proved=False,
                  RAM_data_value_independence_proved=False, full_board_numerical_acceptance=False,
                  physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
                  bitstream_emitted=False, hardware_programmed=False, hardware_input_modified=False, native_PNR_executed=False)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    def run(label, argv, negative=None):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(ROOT), log=str(out / (label + '.log')),
                    timeout_seconds=180, status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as process:
                step['pid'] = process.pid
                save()
                try:
                    code = process.wait(timeout=180)
                except BaseException:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    step['returncode'] = process.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            if negative is not None:
                previous.completed.previous.validate(text, code, negative)
            else:
                assert code == 0 and not re.search(r'(?im)warning:|error:|sorry:|^FAILED|^FATAL|timeout', text), text[-4000:]
            step['status'] = 'PASS_EXPECTED_REAL_FORMAL_NEGATIVE' if negative else 'PASS_TOOL_EXECUTION_ONLY'
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
        shutil.copyfile(__file__, out / 'executed_source.py')
        shutil.copyfile(CONTROL, out / 'executed_control_source.py')
        before = {}
        cone, library_data = admit(before)
        files = {Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve(), Path(shutil.which('yosys')).resolve()}
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for p in files:
            sha = digest(p)
            assert str(p) not in before or before[str(p)] == sha
            before[str(p)] = sha
        report['source'] = before
        verify_bindings(before)
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        report['yosys_version'] = run('yosys_version', ['yosys', '-V']).strip()
        model = out / 'actual-BRAM-core-write-clocked-model.v'
        model.write_text(strengthened_model(cone))
        library = out / 'unchanged_selected_controller_cells.v'
        library.write_bytes(library_data)
        execution = {str(p): digest(p) for p in (model, library)}
        report.update(execution_inputs=execution, actual_cone_cells=len(cone['cells']), actual_producer_bits=len(cone['producer_cuts']),
                      actual_register_folds_and_ghost_updates_unchanged=True, core_write_property_strengthened=True,
                      initialization_host_data_independence_parent_report=str(FAILED))
        for label, negative in (('negative', True), ('positive', False)):
            report['stage'] = 'native_temporal_' + label
            save()
            witness = out / (label + '-counterexample.json')
            target = out / (label + '.ys')
            target.write_text(previous.script(library, model, negative, witness))
            execution[str(target)] = digest(target)
            text = run(label, ['yosys', '-Q', '-T', '-s', target], negative)
            if negative:
                execution[str(witness)] = digest(witness)
                report['real_temporal_negative'] = previous.negative_trace(text, json.loads(witness.read_text()))
            else:
                report['native_induction_length'] = previous.completed.previous.validate(text, 0, False)
                assert not witness.exists()
            verify_bindings(before)
            verify_bindings(execution)
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASS, stage='complete', physical_pin_read_barrier_proved_binary=True,
                      physical_pin_port_ownership_proved_binary=True, physical_core_write_gating_proved_binary=True,
                      initialization_host_data_independence_proved_binary=True,
                      consumed_working_RAM_bits_covered_by_prefix=65536, actual_working_RAMs=2)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
