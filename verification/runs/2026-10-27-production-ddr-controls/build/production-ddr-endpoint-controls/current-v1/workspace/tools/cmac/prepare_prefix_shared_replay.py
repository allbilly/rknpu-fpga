#!/usr/bin/env python3
"""Prepare this full shared-prefix graph's own unchanged nine-mode replay.

Reuse only its completed byte-identical literal structural export, not another
candidate's executable or numerical result. Keep the original raw QWORD/BO
bench, all numeric/address/fault/reset assertions and unmodified pinned UNISIM
models/default GSR. Testbench edits are exact live-wire references only. This
preparation neither compiles/simulates the full board nor authorizes bits.
No runtime CPU arithmetic/layout fixup or standalone SHA256SUMS is created.
"""
from collections import Counter
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
from prepare_prefix_shared_pack_input import PARENT, TOP, validate_export, digest
from prefix_shared_cones import PRIVATE, SHARED, COMBINATIONAL
from prepare_shared_board import physical_counts
from pair_board_luts import implementation_module_aliases
from test_fixed_mapped_array import hardware_instance_aliases
from export_dsp_prefix_board_netlist import structural_board_verilog
from bind_mapped_board_bench import BENCH, bind, WIDTHS
from test_observed_mapped_board import verify_bound_bench, negative_golden, WRITES, READS, MODES
import test_dsp_prefix_observed_mapped_board as original
import dsp_prefix_unisim_board_models as models
from prepare_prefix_pack_input import verify_stream_manifest

CONTROL = ROOT / 'tests/cmac/test_prefix_shared_replay_input_control.py'
PREPARED = 'PREPARED_FULL_C32K16_SHARED_PREFIX_UNCHANGED_NINE_MODE_UNISIM_REPLAY_INPUTS_NOT_NUMERICAL_OR_PHYSICAL_ACCEPTANCE'


def configuration(implementation):
    """Three actual hardware modules; unchanged two-module DSP checker view."""
    assert set(implementation['modules']) == {TOP, PRIVATE, SHARED}
    shared = implementation['modules'][SHARED]
    assert shared['cells'] and all(COMBINATIONAL.fullmatch(c['type']) for c in shared['cells'].values())
    callers = [c for c in implementation['modules'][TOP]['cells'].values() if c['type'] == SHARED]
    assert len(callers) == 1 and not callers[0].get('parameters'), 'Changed shared combinational instance'
    # Comparison-only module selection, never an export/compile execution input.
    compared = models.verify_configurations(dict(modules={n: implementation['modules'][n]
                                                         for n in (TOP, PRIVATE)}), TOP, PRIVATE)
    kinds = {c['type'] for body in implementation['modules'].values() for c in body['cells'].values()
             if c['type'] not in (PRIVATE, SHARED, '$scopeinfo')}
    models.selected_models(kinds)  # Unknown simulation primitives remain failures.
    return dict(**compared, shared_combinational_cells=len(shared['cells']),
                shared_module_omitted_from_execution=False, DSP_configuration_view_only=True), kinds


def exact_export(exported, actual_text):
    assert structural_board_verilog(exported) == actual_text, 'Changed actual literal simulation export'


def merge(before, bindings):
    for name, sha in bindings.items():
        path = Path(name).resolve(strict=True)
        assert re.fullmatch('[0-9a-f]{64}', sha)
        assert str(path) not in before or before[str(path)] == sha, 'Conflicting replay source binding'
        before[str(path)] = sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export-report', type=Path, default=PARENT)
    parser.add_argument('--carry-report', type=Path, default=Path(original.CARRY_PARENT))
    args = parser.parse_args()
    parent_path = args.export_report.resolve(strict=True)
    carry_path = (ROOT / args.carry_report).resolve(strict=True)
    assert parent_path == PARENT.resolve(strict=True)
    assert carry_path.is_relative_to(ROOT / 'build') and carry_path.name == 'report.json'
    parent, carry = (json.loads(p.read_text()) for p in (parent_path, carry_path))
    validate_export(parent)
    original.verify_carry_report(carry)  # Reject incomplete/different evidence before output/tools.
    resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    out = ROOT / f'build/rknpu-dsp-prefix-shared-replay-input/{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='source_admission', started_utc=timestamp(), supervisor_pid=os.getpid(),
        source={}, commands=[], scope=__doc__, export_report=str(parent_path), carry_report=str(carry_path),
        channels=32, kernels=16, parallel_products=512, intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20,
        seed=3588, modes=list(MODES), production_source_before=source_revision(),
        reused_completed_literal_export_without_tool_execution=True, old_numerical_result_inherited=False,
        full_board_compilation_executed=False, numerical_netlist_acceptance=False, native_packing_executed=False,
        physical_fit_verified=False, timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, runtime_CPU_arithmetic_or_layout_fixup=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, timeout=120):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), status='RUNNING', timeout_seconds=timeout)
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream, subprocess.Popen(step['argv'], cwd=ROOT,
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
            assert code == 0 and not re.search(r'(?im)\b(?:WARNING|ERROR|FATAL):|sorry:', text), text[-3000:]
            step['status'] = 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY'
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
        before = {}
        for manifest in (parent['source'], parent['artifacts']):
            merge(before, manifest)
        for manifest in (carry['source'], carry['artifacts']):
            merge(before, verify_stream_manifest(manifest))
        paths = {parent_path, carry_path, BENCH, WRITES, READS, CONTROL, Path(sys.executable).resolve()}
        paths.update(Path(shutil.which(n)).resolve() for n in ('git', 'yosys', 'iverilog', 'vvp'))
        paths.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        merge(before, {str(p): digest(p) for p in paths})
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed shared replay source/input'
        assert parent['production_source_after'] == report['production_source_before']
        assert original.carry_truth.validate_result((ROOT / carry['commands'][-1]['log']).read_text(), 0) == carry['result']
        original.carry_truth.validate_result((ROOT / carry['commands'][-2]['log']).read_text(), 1, negative=True)
        report.update(source=before, stage='software_controls')
        save()
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        report['yosys_version'] = run('yosys_version', ['yosys', '-V']).strip()
        assert report['yosys_version'] == parent['yosys_version']
        report['iverilog_version'] = run('iverilog_version', ['iverilog', '-V']).splitlines()[0]
        report['vvp_version'] = run('vvp_version', ['vvp', '-V']).splitlines()[0]
        assert run('model_commit', ['git', '-C', models.CACHE, 'rev-parse', 'HEAD']).strip() == models.COMMIT
        assert run('model_clean', ['git', '-C', models.CACHE, 'status', '--porcelain', '--untracked-files=all']) == ''
        candidate_path = Path(parent['candidate']).resolve(strict=True)
        assert str(candidate_path) in before
        report['stage'] = 'actual_full_hierarchy_and_wire_binding'
        save()
        candidate = json.loads(candidate_path.read_text())
        counts = physical_counts(candidate['modules'], TOP, {TOP, PRIVATE, SHARED})
        assert dict(counts) == parent['cells'] and sum(counts.values()) == 488407
        implementation = dict(modules={n: candidate['modules'][n] for n in (TOP, PRIVATE, SHARED)})
        del candidate
        configuration_checks, kinds = configuration(implementation)
        assert configuration_checks['shared_combinational_cells'] == 981
        bound, edits = bind(implementation['modules'][TOP], BENCH.read_text())
        verify_bound_bench(implementation['modules'][TOP], BENCH.read_text(), bound, edits)
        assert set(original.WIDTHS) == set(WIDTHS) and len(WIDTHS) == 22
        exported, modules = implementation_module_aliases(implementation)
        assert modules == {}
        exported, instances = hardware_instance_aliases(exported)
        assert json.loads((candidate_path.parent / 'hardware_aliases.json').read_text()) == dict(modules=modules, instances=instances)
        literal = Path(parent['literal_export']).resolve(strict=True)
        assert str(literal) in before
        exact_export(exported, literal.read_text())
        del exported, implementation
        sv = out / 'shared_board.v'
        shutil.copyfile(literal, sv)
        assert digest(sv) == before[str(literal)]
        bench = out / BENCH.name
        bench.write_text(bound)
        (out / 'bench_reference_edits.json').write_text(json.dumps(edits, indent=2) + '\n')
        pins, frozen = models.freeze_models(out / 'models', kinds)
        merge(before, {str(p): sha for p, sha in pins.items()})
        negative_data = out / 'negative-golden-cwd/tests/cmac/array_data'
        negative_data.mkdir(parents=True, exist_ok=False)
        (negative_data / WRITES.name).write_text(negative_golden(WRITES.read_text()))
        (negative_data / READS.name).write_bytes(READS.read_bytes())
        assert bound.count('$readmemh(') == 2 and all('"tests/cmac/array_data/' + p.name + '"' in bound for p in (WRITES, READS))
        report['source'] = before
        assert all(digest(p) == sha for p, sha in before.items()), 'Changed full replay preparation input'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status=PREPARED, stage='complete', literal_hardware_export=str(sv), bound_bench=str(bench),
            vendor_models=[str(p) for p in frozen if p.suffix == '.v'], upstream_model_commit=models.COMMIT,
            default_global_startup_preserved=True, all_three_hardware_modules_preserved=True,
            actual_full_literal_export_byte_identity=True, actual_full_wire_only_bench_binding=True,
            observation_signal_count=22, physical_primitive_counts=dict(counts), configurations=configuration_checks,
            unchanged_writes=str(WRITES), unchanged_reads=str(READS), negative_cwd=str(out / 'negative-golden-cwd'))
    except BaseException as error:
        report.update(status='FAIL_PREFIX_SHARED_REPLAY_PREPARATION', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
