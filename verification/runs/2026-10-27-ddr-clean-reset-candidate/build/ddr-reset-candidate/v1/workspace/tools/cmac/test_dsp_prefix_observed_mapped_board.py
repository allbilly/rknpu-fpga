#!/usr/bin/env python3
"""Replay all nine unchanged raw-board modes on full C32/K16 DSP XC7 hardware.

Own source-bound prefix mapping/native parents; exact circuit export and
wire-only bench binding; unmodified pinned UNISIM models/default startup.
Includes the unknown-readback case and a real first-output-bit negative.
Never an all-X model-equivalence, physical fit/timing/DRC or RK silicon claim.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from evidence import ROOT, fingerprint, timestamp
import map_dsp_prefix_observed_board as mapping
import dsp_prefix_unisim_board_models as models
import check_dsp_prefix_unisim_carry_truth as carry_truth
from export_dsp_prefix_board_netlist import structural_board_verilog
from pair_board_luts import implementation_module_aliases
from test_fixed_mapped_array import circuit_signature, hardware_instance_aliases
from test_fixed_array_board import verify_manifest, validate_result
from test_observed_mapped_board import negative_golden, verify_bound_bench, WRITES, READS, MODES
from bind_mapped_board_bench import bind, WIDTHS

PARENT = 'build/rknpu-dsp-prefix-observed-board-mapping/1791308955335106261/report.json'
CARRY_PARENT = 'build/rknpu-dsp-prefix-unisim-carry-truth/1791309718773637131/report.json'
TOP, BENCH = mapping.TOP, mapping.BENCH


def verify_mapping_report(report):
    assert report['status'] == mapping.STATUS and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['mapped_kernel_instances'],
            report['retained_cmac_dsps'], report['dsp_count'], report['shell_cells']['DSP48E1'],
            report['reused_kernel_cells']['DSP48E1'], report['cells']['RAMB36E1'],
            report['intended_part'], report['intended_clock_period_ns']) == (
                32, 16, 512, 16, 512, 515, 3, 32, 6, 'xc7k480tffg1156-2', 20)
    assert set(report['bindings']) == set(WIDTHS)
    assert report['imported_kernel_circuit_identity'] == 'PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE'
    assert all(report[name] is True for name in ('original_four_bit_state_preserved',
               'original_bench_unchanged', 'mapping_diagnostics_accepted'))
    assert report['actual_ram_port_resizes'] == len(report['normalization_audit']) == 54
    assert report['logged_ram_port_resizes'] == 32
    assert [Path(step['log']).stem for step in report['commands']] == ['version', 'help', 'datadir', 'mapping']
    assert all(step['status'] == 'PASS_TOOL_EXECUTION_ONLY' and step['returncode'] == 0
               for step in report['commands'])
    for name in ('numerical_netlist_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[name] is False


def verify_carry_report(report):
    assert report['status'] == 'PASS_PINNED_UNISIM_CARRY_TRUTH_WITH_EXPLICIT_YOSYS_FOUR_STATE_DIFFERENCES_ONLY'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert report['upstream_model_commit'] == models.COMMIT
    assert report['primitive_fixture_acceptance'] is True and report['default_global_startup_preserved'] is True
    assert report['result'] == dict(binary_comparisons=1024, four_state_comparisons=1048576,
                                  yosys_four_state_differences=415001, first_difference=3,
                                  binary_yosys_vendor_equivalence=True, four_state_yosys_vendor_equivalence=False)
    labels = ('model_commit', 'model_clean', 'version', 'runtime_version', 'compile', 'negative_test', 'positive_test')
    assert [Path(step['log']).stem for step in report['commands']] == list(labels)
    assert all(step['status'] == 'PASS' and step['returncode'] == (1 if label == 'negative_test' else 0)
               for label, step in zip(labels, report['commands']))
    for name in ('numerical_netlist_acceptance', 'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[name] is False


def simulation_result(text, code, mode, negative=False):
    assert not re.search(r'(?im)\b(?:warning|error)\s*:|\bsorry:', text), 'Unaccepted simulation diagnostic'
    if negative:
        assert mode == 0 and code == 1 and 'board demo numerical/address mismatch output=0' in text
        assert not re.search(r'^PASS ', text, re.M)
        return 'REJECTED_EXACT_FIRST_OUTPUT_GOLDEN_BIT'
    assert code == 0 and not re.search(r'FATAL:', text)
    return validate_result(text, mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapping-report', type=Path, default=Path(PARENT))
    parser.add_argument('--carry-report', type=Path, default=Path(CARRY_PARENT))
    args = parser.parse_args()
    parent_path = mapping.mapper.replay.workspace_path(args.mapping_report)
    carry_path = mapping.mapper.replay.workspace_path(args.carry_report)
    parent, carry = (json.loads(path.read_text()) for path in (parent_path, carry_path))
    verify_mapping_report(parent)
    verify_carry_report(carry)
    for report in (parent, carry):
        verify_manifest(report['source'])
        verify_manifest(report['artifacts'])
    assert carry_truth.validate_result((ROOT / carry['commands'][-1]['log']).read_text(), 0) == carry['result']
    carry_truth.validate_result((ROOT / carry['commands'][-2]['log']).read_text(), 1, negative=True)
    prepared_path = ROOT / parent['preparation_report']
    prepared = json.loads(prepared_path.read_text())
    mapping.verify_prepared_metadata(prepared)
    assert prepared['source']['sha256'] == parent['parent_source_sha256']
    verify_manifest(prepared['source'])
    verify_manifest(prepared['artifacts'])
    original_path = ROOT / prepared['original_mapping_report']
    original = json.loads(original_path.read_text())
    # The old attempt remains FAIL; only its immutable partition is reused.
    assert original['status'] == 'FAIL'
    spec, _ = mapping.mapper.inputs()
    area, raw, _ = mapping.mapper.verify_area(ROOT / original['parent_reports']['area'])
    board, numerical_paths, _ = mapping.mapper.verify_board(ROOT / original['parent_reports']['board'], spec)
    mapping.mapper.validate_shared_prerequisites(area, numerical_paths)
    partition, kernel, kernel_counts = mapping.mapper.partition(raw)
    assert kernel == parent['preserved_kernel'] == prepared['preserved_kernel']
    mapped = parent_path.parent / 'mapped_hierarchy.json'
    before = parent_path.parent / 'before.json'
    assert all(str(path.relative_to(ROOT)) in parent['artifacts']['files'] for path in (mapped, before))
    design = json.loads(mapped.read_text())
    implementation = dict(modules={name: design['modules'][name] for name in (TOP, kernel)})
    mapping.preparation.observations.verify_implementation_boundary(implementation, partition, kernel)
    assert mapping.preparation.observations.verify_observations(implementation['modules'][TOP], BENCH.read_text()) == parent['bindings']
    counts, shell, qualifiers = mapping.mapper.validate_mapped(design, TOP, kernel, partition['modules'][kernel], kernel_counts)
    assert dict(counts) == parent['cells'] and dict(shell) == parent['shell_cells']
    assert qualifiers == parent['timing_qualifier_counter_audit']
    log = ROOT / parent['commands'][-1]['log']
    text = log.read_text()
    resizes = mapping.ram.resize_notices(text, TOP)
    assert mapping.audit_mapping_log(text, kernel, resizes) == parent['mapping_diagnostics']
    assert mapping.ram.audit_normalization(json.loads(before.read_text()), design, TOP, resizes) == parent['normalization_audit']
    configuration = models.verify_configurations(implementation, TOP, kernel)
    kinds = {cell['type'] for body in implementation['modules'].values() for cell in body['cells'].values()
             if cell['type'] not in (kernel, '$scopeinfo')}
    pins = models.selected_models(kinds)
    del design, partition, raw
    out = ROOT / f'build/rknpu-dsp-prefix-observed-mapped-board/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    module_export, module_aliases = implementation_module_aliases(implementation)
    exported, instance_aliases = hardware_instance_aliases(module_export)
    assert module_aliases.get(TOP, TOP) == TOP
    sv, bench = out / 'mapped_board.v', out / BENCH.name
    sv.write_text(structural_board_verilog(exported))
    bound, edits = bind(implementation['modules'][TOP], BENCH.read_text())
    verify_bound_bench(implementation['modules'][TOP], BENCH.read_text(), bound, edits)
    bench.write_text(bound)
    edits_path, aliases = out / 'bench_reference_edits.json', out / 'hardware_name_aliases.json'
    edits_path.write_text(json.dumps(edits, indent=2) + '\n')
    aliases.write_text(json.dumps(dict(modules=module_aliases, instances=instance_aliases), indent=2) + '\n')
    _, frozen = models.freeze_models(out / 'models', kinds)
    negative_cwd = out / 'negative-golden-cwd'
    negative_data = negative_cwd / 'tests/cmac/array_data'
    negative_data.mkdir(parents=True)
    negative_writes, negative_reads = negative_data / WRITES.name, negative_data / READS.name
    negative_writes.write_text(negative_golden(WRITES.read_text()))
    negative_reads.write_bytes(READS.read_bytes())
    assert bound.count('$readmemh(') == 2 and '"tests/cmac/array_data/writes.hex"' in bound
    assert '"tests/cmac/array_data/reads.hex"' in bound
    roundtrip, script = out / 'export_roundtrip.json', out / 'export.ys'
    script.write_text('read_verilog -sv ' + json.dumps(str(sv)) + ';\nwrite_json ' + json.dumps(str(roundtrip)) + ';\n')
    generated = [sv, bench, edits_path, aliases, script, *frozen, negative_writes, negative_reads]
    tracked = {parent_path, carry_path, prepared_path, original_path, mapped, before, BENCH, WRITES, READS,
               Path(__file__).resolve(), *pins, *generated, *(ROOT / name for name in parent['source']['files'])}
    tracked.update(Path(module.__file__).resolve() for module in list(sys.modules.values())
                   if getattr(module, '__file__', None) and Path(module.__file__).resolve().is_relative_to(ROOT / 'tools'))
    report = dict(status='RUNNING', stage='export', started_utc=timestamp(), supervisor_pid=os.getpid(),
                  source=fingerprint(tracked), mapping_report=str(parent_path.relative_to(ROOT)),
                  carry_truth_report=str(carry_path.relative_to(ROOT)), parent_source_sha256=parent['source']['sha256'],
                  commands=[], tests=[], channels=32, kernels=16, parallel_products=512, modes=list(MODES),
                  intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, upstream_model_commit=models.COMMIT,
                  configurations=configuration, model_four_state_yosys_equivalence=False,
                  numerical_netlist_acceptance=False, physical_fit_verified=False,
                  bitstream_emitted=False, hardware_programmed=False, scope=__doc__)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(argv, label, cwd=ROOT, mode=None, negative=False):
        step = dict(argv=list(map(str, argv)), cwd=str(cwd.relative_to(ROOT)) or '.',
                    status='RUNNING', log=str((out / (label + '.log')).relative_to(ROOT)))
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with (ROOT / step['log']).open('w') as stream:
                with subprocess.Popen(step['argv'], cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                      start_new_session=True) as process:
                    step['pid'] = process.pid
                    save()
                    try:
                        code = process.wait(timeout=14400)
                    except BaseException:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                        raise
            step['returncode'] = code
            text = (ROOT / step['log']).read_text()
            if mode is not None:
                step['result'] = simulation_result(text, code, mode, negative)
            else:
                assert code == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:|\bsorry:|FATAL:', text), text[-4000:]
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit(128 + signum)))
    save()
    print(out / 'report.json', flush=True)
    try:
        for path in sorted(tracked):
            if path.suffix in ('.py', '.sv', '.v', '.vlib', '.ys', '.hex'):
                target = out / 'snapshot' / path.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        report['yosys_version'] = run(['yosys', '-V'], 'yosys_version').strip()
        assert report['yosys_version'] == parent['tool_version']
        report['iverilog_version'] = run(['iverilog', '-V'], 'iverilog_version').splitlines()[0]
        report['vvp_version'] = run(['vvp', '-V'], 'vvp_version').splitlines()[0]
        assert run(['git', '-C', models.CACHE, 'rev-parse', 'HEAD'], 'model_commit').strip() == models.COMMIT
        assert run(['git', '-C', models.CACHE, 'status', '--porcelain', '--untracked-files=all'], 'model_clean') == ''
        run(['yosys', '-Q', '-T', '-s', script], 'export')
        assert circuit_signature(json.loads(roundtrip.read_text())) == circuit_signature(exported), 'Export changed hardware circuit'
        report['export_circuit_identity'] = 'PASS_ALL_PORT_BITS_PRIMITIVE_TYPES_PARAMETERS_AND_PIN_WIRE_INCIDENCE'
        executable = out / 'board.vvp'
        compile_inputs = [*generated, roundtrip, WRITES, READS]
        report['compile_inputs'] = fingerprint(compile_inputs)
        report['stage'] = 'compile'
        save()
        run(['iverilog', '-g2012', '-Ttyp', '-s', 'tb_cmac_array_bram_demo', '-s', 'glbl', '-o', executable,
             *[path for path in frozen if path.suffix == '.v'], sv, bench], 'compile')
        assert fingerprint(compile_inputs) == report['compile_inputs']
        report['compiled_executable'] = fingerprint([executable])
        for label, mode, cwd in [('negative', 0, negative_cwd), *(('mode' + str(mode), mode, ROOT) for mode in MODES)]:
            assert fingerprint(compile_inputs) == report['compile_inputs']
            assert fingerprint([executable]) == report['compiled_executable']
            report['stage'] = label
            report.setdefault('execution_inputs', {})[label] = fingerprint([*compile_inputs, executable])
            save()
            run(['vvp', executable, '+MODE=' + str(mode)], label, cwd, mode, label == 'negative')
            if label != 'negative':
                report['tests'].append(dict(mode=mode, status='PASS', result=report['commands'][-1]['result']))
            assert fingerprint([*compile_inputs, executable]) == report['execution_inputs'][label]
            save()
        assert [test['mode'] for test in report['tests']] == list(MODES)
        assert fingerprint(tracked) == report['source']
        for parent_report in (parent, carry, prepared):
            verify_manifest(parent_report['source'])
            verify_manifest(parent_report['artifacts'])
        verify_bound_bench(implementation['modules'][TOP], BENCH.read_text(), bench.read_text(), edits)
        report.update(status='PASS_FULL_C32K16_PREFIX_OBSERVABLE_RAW_BOARD_NINE_MODE_UNISIM_MAPPED_ONLY',
                      stage='complete', numerical_netlist_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = fingerprint([path for path in out.rglob('*') if path.is_file() and path.name != 'report.json'])
        save()


if __name__ == '__main__':
    main()
