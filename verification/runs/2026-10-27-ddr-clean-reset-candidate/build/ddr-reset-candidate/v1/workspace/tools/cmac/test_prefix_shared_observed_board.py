#!/usr/bin/env python3
"""Compile and replay this shared graph's own full unchanged nine-mode board.

Requires completed source-bound input preparation before creating an attempt.
Compiles all three literal hardware modules and the unchanged pinned vendor
models/default glbl. Runs the real first-output golden-bit negative followed
by every original numerical/address/fault/reset mode. Old binaries and mode
results are never reused. This is mapped simulation, not FPGA/RK validation,
physical signoff, bitstream emission or runtime CPU arithmetic/layout repair.
"""
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

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / 'openxc7')]
from evidence import ROOT, source_revision, timestamp
import prepare_prefix_shared_replay as preparation
import test_dsp_prefix_observed_mapped_board as original
import dsp_prefix_unisim_board_models as models
from prepare_prefix_shared_pack_input import validate_export, digest

PARENT = ROOT / 'build/rknpu-dsp-prefix-shared-replay-qualified-input/1791478332907270075/report.json'
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_observed_board_control.py'
COUNTS = dict(LUT1=798, LUT2=147030, LUT3=143590, LUT4=16586, LUT5=65410,
              LUT6=57792, FDCE=13981, FDRE=3408, FDSE=128, FDPE=2,
              DSP48E1=515, RAMB36E1=6, CARRY4=8566, INV=22060, MUXF7=7138, MUXF8=1397)
PHYSICAL_FLAGS = ('native_packing_executed', 'physical_fit_verified', 'timing_signoff',
                  'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed')
SUCCESS = 'PASS_FULL_C32K16_SHARED_PREFIX_OWN_NINE_MODE_UNISIM_MAPPED_ONLY'


def verify_prepared(report):
    assert report['status'] == preparation.PREPARED and report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed'], report['modes']) == (
                32, 16, 512, 'xc7k480tffg1156-2', 20, 3588, list(original.MODES))
    assert report['physical_primitive_counts'] == COUNTS and sum(COUNTS.values()) == 488407
    assert report['configurations'] == dict(kernel_dsp_configurations=32, shell_dsp_configurations=3,
        physical_cmac_dsps=512, total_physical_dsps=515, shared_combinational_cells=981,
        shared_module_omitted_from_execution=False, DSP_configuration_view_only=True)
    assert report['observation_signal_count'] == len(original.WIDTHS) == 22
    assert report['upstream_model_commit'] == models.COMMIT
    for flag in ('default_global_startup_preserved', 'all_three_hardware_modules_preserved',
                 'actual_full_literal_export_byte_identity', 'actual_full_wire_only_bench_binding'):
        assert report[flag] is True
    for flag in (*PHYSICAL_FLAGS, 'old_numerical_result_inherited', 'full_board_compilation_executed',
                 'numerical_netlist_acceptance', 'runtime_CPU_arithmetic_or_layout_fixup',
                 'counter_view_used_for_export_or_simulation', 'original_failure_relabelled'):
        assert report[flag] is False
    assert report['production_source_before'] == report['production_source_after']
    assert len(report['counter_timing_qualifiers']) == 4
    labels = ['software_controls', 'generated_check', 'yosys_version', 'iverilog_version',
              'vvp_version', 'model_commit', 'model_clean']
    assert [s['label'] for s in report['commands']] == labels
    assert all(s['status'] == 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY' and s['returncode'] == 0
               for s in report['commands'])
    assert Path(report['unchanged_writes']) == original.WRITES
    assert Path(report['unchanged_reads']) == original.READS


def checked_file(name, folder, manifest):
    path = Path(name).resolve(strict=True)
    assert path.is_file() and path.is_relative_to(folder) and str(path) in manifest
    assert digest(path) == manifest[str(path)], 'Changed prepared execution file'
    return path


def execution_files(report, folder):
    """Only this preparation's exact hardware, bench and complete vendor files."""
    manifest = report['artifacts']
    sv = checked_file(report['literal_hardware_export'], folder, manifest)
    bench = checked_file(report['bound_bench'], folder, manifest)
    assert sv.name == 'shared_board.v' and bench.name == original.BENCH.name
    pins = models.selected_models(set(COUNTS))
    expected = {p.name: sha for p, sha in pins.items()}
    vendor = [checked_file(p, folder / 'models', manifest) for p in report['vendor_models']]
    assert [p.name for p in vendor] == [p.name for p in pins if p.suffix == '.v']
    for name, sha in expected.items():
        assert digest(checked_file(folder / 'models' / name, folder, manifest)) == sha
    negative_cwd = Path(report['negative_cwd']).resolve(strict=True)
    assert negative_cwd == folder / 'negative-golden-cwd'
    data = negative_cwd / 'tests/cmac/array_data'
    wrong = checked_file(data / original.WRITES.name, folder, manifest)
    reads = checked_file(data / original.READS.name, folder, manifest)
    assert wrong.read_text() == original.negative_golden(original.WRITES.read_text())
    assert reads.read_bytes() == original.READS.read_bytes()
    return sv, bench, vendor, negative_cwd, [wrong, reads]


def full_result(commands, tests):
    """No compile-only, partial/old-mode, warning or missing negative PASS."""
    modes = list(original.MODES)
    compilation = [s for s in commands if s['label'] == 'compile']
    assert len(compilation) == 1 and compilation[0]['status'] == 'PASS' and compilation[0]['returncode'] == 0
    executed = [s for s in commands if s['label'] == 'negative' or s['label'].startswith('mode')]
    assert [s['label'] for s in executed] == ['negative', *('mode' + str(m) for m in modes)]
    assert all(s['status'] == 'PASS' and s['returncode'] == int(s['label'] == 'negative') for s in executed)
    assert executed[0]['result'] == 'REJECTED_EXACT_FIRST_OUTPUT_GOLDEN_BIT'
    assert [t['mode'] for t in tests] == modes and all(t['status'] == 'PASS' for t in tests)
    assert all(t['result'] == s['result'] for t, s in zip(tests, executed[1:]))
    for mode, step in zip(modes, executed[1:]):
        assert original.simulation_result(step['result'] + '\n', step['returncode'], mode) == step['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation-report', type=Path, default=PARENT)
    args = parser.parse_args()
    parent_path = args.preparation_report.resolve(strict=True)
    assert parent_path == PARENT.resolve(strict=True)
    parent = json.loads(parent_path.read_text())
    verify_prepared(parent)  # RUNNING/failed/other candidates cannot create an attempt.
    before = {}
    for manifest in (parent['source'], parent['artifacts']):
        preparation.merge(before, manifest)
    export_path = Path(parent['export_report']).resolve(strict=True)
    assert export_path == preparation.PARENT.resolve(strict=True) and str(export_path) in before
    export = json.loads(export_path.read_text())
    validate_export(export)
    assert parent['counter_timing_qualifiers'] == export['counter_timing_qualifiers']
    assert parent['physical_primitive_counts'] == export['cells']
    sv, bench, vendor, negative_cwd, negative_files = execution_files(parent, parent_path.parent)
    paths = {parent_path, CONTROL, Path(sys.executable).resolve(), original.WRITES, original.READS}
    paths.update(Path(shutil.which(n)).resolve() for n in ('git', 'iverilog', 'vvp'))
    paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                 if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
    preparation.merge(before, {str(p): digest(p) for p in paths})
    assert all(digest(p) == sha for p, sha in before.items()), 'Changed shared numerical inputs or provenance'
    assert source_revision() == parent['production_source_after']
    resource.setrlimit(resource.RLIMIT_AS, (24 * 1024**3, 24 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/rknpu-dsp-prefix-shared-observed-board/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='software_controls', started_utc=timestamp(), finished_utc=None,
        supervisor_pid=os.getpid(), preparation_report=str(parent_path), source=before, commands=[], tests=[],
        production_source_before=source_revision(), channels=32, kernels=16, parallel_products=512,
        intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588, modes=list(original.MODES),
        configurations=parent['configurations'], upstream_model_commit=models.COMMIT,
        default_global_startup_preserved=True, old_executable_or_numerical_result_inherited=False,
        full_board_compilation_executed=False, numerical_netlist_acceptance=False, model_four_state_yosys_equivalence=False,
        runtime_CPU_arithmetic_or_layout_fixup=False, scope=__doc__,
        compile_timeout_seconds=21600, each_mode_timeout_seconds=86400,
        **{flag: False for flag in PHYSICAL_FLAGS})

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=120, cwd=ROOT, mode=None, negative=False):
        step = dict(label=label, argv=list(map(str, argv)), cwd=str(cwd), log=str(out / (label + '.log')),
                    status='RUNNING', timeout_seconds=timeout)
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=cwd,
                    stdout=stream, stderr=subprocess.STDOUT, start_new_session=True) as proc:
                step['pid'] = proc.pid
                save()
                try:
                    code = proc.wait(timeout=timeout)
                except BaseException:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    step['returncode'] = proc.returncode
                    raise
            step['returncode'] = code
            text = Path(step['log']).read_text()
            if mode is None:
                assert code == 0 and not re.search(r'(?im)\b(?:warning|error|fatal)\s*:|\bsorry:', text), text[-3000:]
            else:
                step['result'] = original.simulation_result(text, code, mode, negative)
            step['status'] = 'PASS'
            return text
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    save()
    print(out / 'report.json', flush=True)
    try:
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        report['iverilog_version'] = run('iverilog_version', ['iverilog', '-V']).splitlines()[0]
        report['vvp_version'] = run('vvp_version', ['vvp', '-V']).splitlines()[0]
        assert all(report[n] == parent[n] for n in ('iverilog_version', 'vvp_version'))
        assert run('model_commit', ['git', '-C', models.CACHE, 'rev-parse', 'HEAD']).strip() == models.COMMIT
        assert run('model_clean', ['git', '-C', models.CACHE, 'status', '--porcelain', '--untracked-files=all']) == ''
        inputs = [sv, bench, *vendor, *negative_files, original.WRITES, original.READS]
        frozen_inputs = {str(p): digest(p) for p in inputs}
        assert all(before[name] == sha for name, sha in frozen_inputs.items())
        report.update(stage='compile', compile_inputs=frozen_inputs)
        save()
        executable = out / 'board.vvp'
        report['full_board_compilation_executed'] = True
        run('compile', ['iverilog', '-g2012', '-Ttyp', '-s', 'tb_cmac_array_bram_demo', '-s', 'glbl',
                        '-o', executable, *vendor, sv, bench], report['compile_timeout_seconds'])
        report['compiled_executable'] = {str(executable): digest(executable)}
        for label, mode, cwd in [('negative', 0, negative_cwd),
                                 *(('mode' + str(m), m, ROOT) for m in original.MODES)]:
            bound = dict(frozen_inputs, **report['compiled_executable'])
            assert all(digest(p) == sha for p, sha in bound.items()), 'Changed actual simulation input'
            report.update(stage=label)
            report.setdefault('execution_inputs', {})[label] = bound
            save()
            run(label, ['vvp', executable, '+MODE=' + str(mode)], report['each_mode_timeout_seconds'],
                cwd, mode, label == 'negative')
            if label != 'negative':
                report['tests'].append(dict(mode=mode, status='PASS', result=report['commands'][-1]['result']))
            assert all(digest(p) == sha for p, sha in bound.items()), 'Changed simulation input during execution'
            save()
        full_result(report['commands'], report['tests'])
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed source/provenance during numerical replay'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=SUCCESS, stage='complete', numerical_netlist_acceptance=True)
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_OWN_NUMERICAL_REPLAY', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
