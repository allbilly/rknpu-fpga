#!/usr/bin/env python3
"""Prepared complete-output review of a narrowly identified host-counter error.

Admit ONLY a stopped, zero-code, normally completed full C32/K16 native run
whose frozen wrapper rejects the source-proven analytic-subset/full-census
comparison. Preserve that failed report and every execution artifact. Reuse
the complete original post-native cell/unique-BEL/DSP/tie/clock/source guards;
prove the full census from actual packed/placed membership, never the subset
log marker. No native P&R rerun, input repair, smaller target, numerical or
physical signoff, bits, FPGA/flash access or SHA256SUMS manifest follows.
A prepared reviewer is NOT an accepted placement or permission to route.
"""
import argparse
import inspect
import json
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import place_recursive_mux_prefix_shared_board as placement
import audit_typed_recursive_mux_analytic_scope as scope_audit
from audit_empty_output_pairs import source_shaped
from evidence import ROOT, source_revision, timestamp

CONTROL = ROOT / 'tests/cmac/test_recursive_mux_completed_placement_review_control.py'
REVIEWED = 'REVIEWED_COMPLETED_FULL_C32K16_RECURSIVE_MUX_ALL_CELL_BEL_DSP_CLOCK_NOT_ROUTED_OR_SIGNOFF'
PARENT_FAILED = 'FAIL_PREFIX_SHARED_RECURSIVE_MUX_HEAP_PLACE'
PARENT_ERROR = "AssertionError('Changed complete full analytic cell census')"
LABELS = ['software_controls', 'native_heap_guard_controls', 'generated_check', 'version', 'native_place']


METADATA_REPLACEMENTS = (
    ("    assert report['status'] == 'RUNNING' and report['stage'] == 'native_place'\n",
     """    assert report['status'] == PARENT_FAILED and report['stage'] == 'native_place'
    assert report['error'] == PARENT_ERROR and report['finished_utc']
    assert [c['label'] for c in report['commands']] == LABELS
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])
    assert report['native_source_or_executable_changed'] is True
    assert report['only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent'] is True
    assert report['counter_safe_HeAP_parent_retained'] is True and report['old_native_result_inherited'] is False
"""),
    ("command['label'] == 'native_place' and command['status'] == 'RUNNING'",
     "command['label'] == 'native_place' and command['status'] == 'PASS_TOOL_EXECUTION_ONLY'"),
    ("command.get('returncode') is None", "command['returncode'] == 0"),
)
METADATA_SOURCE = source_shaped(inspect.getsource(scope_audit.previous.live_metadata), METADATA_REPLACEMENTS)
METADATA_NAMESPACE = dict(scope_audit.previous.__dict__, PARENT_FAILED=PARENT_FAILED, PARENT_ERROR=PARENT_ERROR, LABELS=LABELS)
exec(compile(METADATA_SOURCE, __file__ + ':cause-specific-terminal-zero-code-full-profile', 'exec'), METADATA_NAMESPACE)
verify_parent_metadata = METADATA_NAMESPACE['live_metadata']


def verify_scope_metadata(scope, native, path):
    assert scope['status'] == scope_audit.STATUS and scope['finished_utc']
    assert Path(scope['native_report']).resolve(strict=True) == Path(path).resolve(strict=True)
    assert scope['current_native_pid'] == native['commands'][-1]['pid']
    assert scope['native_version'] == native['native_version']
    assert scope['packed_report'] == native['packed_report']
    assert scope['production_source'] == native['production_source_before']
    assert scope['native_source_scope_contract']['marker_expression'] == 'place_cells.size()'
    assert scope['native_source_scope_contract']['native_final_all_nonpseudo_cell_binding_guard_present'] is True
    assert scope['actual_log_observation']['full_unique_BEL_and_cell_membership_still_required'] is True
    for flag in ('frozen_runner_or_error_expectation_changed', 'replacement_placement_acceptance_prepared',
                 'full_cell_membership_verified', 'numerical_netlist_acceptance', 'physical_fit_verified',
                 'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed',
                 'processes_signalled'):
        assert scope[flag] is False


def fresh_log_checks(log, pack, scope):
    placement.packer.validate_pack(pack)
    placement.check_heap_log(0, log)  # All original normal-refinement/legality/warning guards.
    checksum = scope['actual_log_observation']['actual_native_packed_checksum']
    expected = re.findall(r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$', Path(pack['commands'][-1]['log']).read_text())
    assert expected == [checksum], 'Changed actual bound full-pack checksum'
    observation = scope_audit.previous.log_observation(log, pack['native_census']['cells'], checksum)
    assert observation == scope['actual_log_observation'], 'Changed observed analytic prefix or packed population'
    limits = re.findall(r'(?m)^Info: Running main analytical placer, max placement attempts per cell = (\d+)\.$', log)
    limit = placement.previous.qualification.build.candidate.limit(pack['native_census']['cells'], 8)
    assert limit == 2147483646 and limits == [str(limit)], 'Changed source-bound finite counter limit'
    return dict(actual_packed_checksum=checksum, actual_full_packed_cells=pack['native_census']['cells'],
                actual_logged_analytic_active_roots=observation['actual_logged_analytic_active_roots'],
                actual_logged_maximum_attempts_per_cell=limit, finite_counter_rejection_preserved=True,
                analytic_marker_used_as_full_census=False, complete_output_membership_required=True,
                physical_fit_verified=False)


# Lift the complete existing post-native block, keeping every full-output,
# DSP/tie, clock and after-source guard literally unchanged. Replace only the
# incorrect subset-log/full-census check and the independent review status.
START = '        verify_clock_admission(log, constraints)\n'
END = '    except BaseException as error:\n'
assert placement.MAIN_SOURCE.count(START) == placement.MAIN_SOURCE.count(END) == 1
ORIGINAL_POST = placement.MAIN_SOURCE.split(START, 1)[1].split(END, 1)[0]
ORIGINAL_POST = START + ORIGINAL_POST
POST_REPLACEMENTS = (
    ("report['recursive_mux_attempt_limit_and_packed_checksum'] = full_log_checks(log, pack)",
     "report['reviewed_native_log_characterization'] = fresh_log_checks(log, pack, scope)"),
    ("status='" + placement.PLACED + "'", "status='" + REVIEWED + "'"),
)
POST_BODY = source_shaped(ORIGINAL_POST, POST_REPLACEMENTS)
POST_SOURCE = ('def verify_complete_output(report, log, constraints, pack, scope, output, pp, candidate, names, before, save):\n'
               '    if True:\n' + POST_BODY + '    return report\n')
POST_NAMESPACE = dict(placement.NAMESPACE, fresh_log_checks=fresh_log_checks)
exec(compile(POST_SOURCE, __file__ + ':all-original-complete-output-and-after-source-guards', 'exec'), POST_NAMESPACE)
verify_complete_output = POST_NAMESPACE['verify_complete_output']


def bind_report(path, report, before):
    """Bind actual producer bytes/artifacts, without rewriting any report."""
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    for manifest, own in ((report['source'], False), (report['artifacts'], True)):
        for name, sha in manifest.items():
            artifact = (ROOT / name).resolve(strict=True)
            if own:
                assert artifact.is_relative_to(path.parent), 'Artifact outside its actual producer'
            key = str(artifact)
            assert key not in before or before[key] == sha, 'Conflicting admitted source/artifact'
            before[key] = sha
    before[str(path)] = scope_audit.previous.digest(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--scope-report', type=Path, required=True)
    args = parser.parse_args()
    path = args.native_report.resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-prefix-shared-recursive-mux-heap-place-')
    native = json.loads(path.read_text())
    command = verify_parent_metadata(native)  # No output/tools for RUNNING, native failure or wrong error.
    assert not Path(f'/proc/{command["pid"]}').exists(), 'Native worker is still live'
    assert not Path(f'/proc/{native["supervisor_pid"]}').exists(), 'Original producer is still live'
    sp = args.scope_report.resolve(strict=True)
    assert sp.is_relative_to(ROOT / 'build/openxc7') and sp.name == 'report.json'
    assert sp.parent.name.startswith('recursive-mux-analytic-scope-typed-')
    scope = json.loads(sp.read_text())
    verify_scope_metadata(scope, native, path)
    resource.setrlimit(resource.RLIMIT_AS, (12 * 1024**3, 12 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    production = source_revision()
    assert production == native['production_source_before']
    out = ROOT / f'build/openxc7/full-recursive-mux-completed-placement-review-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    (out / 'executed_source.py').write_bytes(Path(__file__).read_bytes())
    (out / 'executed_post_native_checks.py').write_text(POST_SOURCE)
    report = dict(status='RUNNING', stage='closed_actual_native_source_admission', started_utc=timestamp(),
        supervisor_pid=os.getpid(), scope=__doc__, commands=[], source={}, native_execution_report=str(path),
        source_scope_report=str(sp), production_source_before=production,
        fresh_native_placement_executed=False, original_failed_report_relabelled=False,
        original_native_output_modified=False, hardware_execution_input_changed=False,
        original_full_output_guards_retained=True, full_placed_cell_membership_verified=False,
        native_routing_executed=False, numerical_netlist_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv):
        step = dict(label=label, argv=argv, cwd=str(ROOT), log=str(out / (label + '.log')), status='RUNNING', timeout_seconds=120)
        report['commands'].append(step); save(); started = time.monotonic()
        try:
            with Path(step['log']).open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            step['returncode'] = result.returncode
            text = Path(step['log']).read_text()
            assert result.returncode == 0 and not re.search(r'(?im)^(?:FAILED|ERROR|WARNING|FATAL)\b', text), text[-4000:]
            step['status'] = 'PASS_SOFTWARE_CONTROL_ONLY'
        except BaseException:
            step['status'] = 'FAIL'; raise
        finally:
            step['seconds'] = round(time.monotonic() - started, 3); save()

    save(); print(out / 'report.json', flush=True)
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        before = {}
        bind_report(path, native, before); bind_report(sp, scope, before)
        pp = Path(native['packed_report']).resolve(strict=True)
        assert str(pp) in before
        pack = json.loads(pp.read_text()); placement.packer.validate_pack(pack)
        bind_report(pp, pack, before)
        candidate, admitted = placement.admit_qualification(native['qualification'])
        for name, sha in admitted.items():
            assert name not in before or before[name] == sha
            before[name] = sha
        assert candidate['executable'] == pack['executable'] == native['executable']
        assert candidate['native_version'] == native['native_version']
        assert candidate['production_source_after'] == pack['production_source_after'] == production
        assert native['qualified_parent_executable'] == candidate['qualified_parent_executable']
        assert native['recursive_mux_engine_build_report'] == candidate['build_report']
        assert native['execution_input'] == pack['execution_input']
        assert native['prepared_report'] == pack['prepared_report']
        constraints = native['constraint_translation']
        assert constraints == pack['constraint_translation'] and constraints['target_period_ns'] == 20.0
        source = Path(scope['compiled_HeAP_source']).resolve(strict=True)
        assert str(source) in before and scope['source'][str(source)] == before[str(source)]
        assert scope_audit.previous.source_contract(source.read_text()) == scope['native_source_scope_contract']
        output = Path(command['argv'][command['argv'].index('--write') + 1]).resolve(strict=True)
        assert output == path.parent / 'placed.json' and str(output) in before
        log_path = Path(command['log']).resolve(strict=True)
        assert log_path.is_relative_to(path.parent) and str(log_path) in before
        assert command['argv'][command['argv'].index('--json') + 1] == pack['execution_input']
        files = {Path(__file__).resolve(), CONTROL, Path(sys.executable).resolve()}
        files.update((ROOT / 'tests/cmac').glob('*.py'))
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
                     if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        for item in files:
            key, sha = str(item), scope_audit.previous.digest(item)
            assert key not in before or before[key] == sha
            before[key] = sha
        assert all(scope_audit.previous.digest(p) == sha for p, sha in before.items()), 'Changed complete original/source evidence'
        report.update(source=before, stage='software_controls', executable=native['executable'],
            native_version=native['native_version'], packed_report=str(pp), prepared_report=pack['prepared_report'],
            execution_input=pack['execution_input'], constraint_translation=constraints,
            original_native_commands=native['commands'], channels=32, kernels=16, parallel_products=512,
            intended_part='xc7k480tffg1156-2', intended_clock_period_ns=20, seed=3588)
        save()
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        names = placement.NAMESPACE['packed_names'](pack['packed_design'])
        assert len(names) == pack['native_census']['cells']
        log = log_path.read_text()
        verify_complete_output(report, log, constraints, pack, scope, output, pp, candidate, names, before, save)
        report['full_placed_cell_membership_verified'] = True
        report['source_proven_analytic_subset_contract_used'] = True
    except BaseException as error:
        report.update(status='FAIL_COMPLETED_RECURSIVE_MUX_FULL_PLACEMENT_REVIEW', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): scope_audit.previous.digest(p) for p in out.iterdir() if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
