#!/usr/bin/env python3
"""Archive an actual read-only revalidation of completed small native v2 evidence.

Run the original controls, rehash/recompute real source-bound native evidence,
and check the new pair/carry auditors against actual qualification inputs.
Do not execute placement/routing, modify old inputs, emit SHA256SUMS files,
admit full placement/route or claim numerical/physical/FPGA acceptance.
"""
import argparse
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
import verify_empty_output_evidence as evidence
import route_empty_output_board as handoff
from audit_empty_output_pairs import audit_pairs, local_carry_roles
from place_prefix_board import verify_bindings
from pack_prefix_board import ROOT, digest, timestamp
from evidence import source_revision

CONTROLS = ('test_fixed_empty_output_fixture.py', 'test_empty_output_pair_audit.py',
            'test_empty_output_evidence.py', 'test_empty_output_full_route.py')
PASS = 'REVALIDATED_COMPLETED_SMALL_NATIVE_V2_EVIDENCE_AND_PREPARED_FULL_ROUTE_NOT_FULL_ACCEPTANCE'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qualification', type=Path, default=evidence.QUALIFIED)
    args = parser.parse_args()
    qualified_path = args.qualification.resolve(strict=True)
    assert qualified_path.is_relative_to(ROOT / 'build/openxc7')
    out = ROOT / f'build/openxc7/empty-output-evidence-revalidation-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    (out / 'prepared_full_route_source.py').write_text(handoff.MAIN_SOURCE)
    report = dict(status='RUNNING', stage='completed_metadata_admission', started_utc=timestamp(),
        supervisor_pid=os.getpid(), scope=__doc__, source={}, commands=[],
        qualification_report=str(qualified_path), production_source_before=source_revision(),
        native_execution_performed_by_this_revalidation=False,
        full_placement_admitted=False, full_route_handoff_executed=False,
        **{key: False for key in evidence.probe.FLAGS})

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv):
        step = dict(label=label, argv=argv, cwd=str(ROOT), log=str(out / (label + '.log')),
                    status='RUNNING', expected_returncode=0, timeout_seconds=120)
        report['commands'].append(step); save(); start = time.monotonic()
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
            step['seconds'] = round(time.monotonic() - start, 3); save()

    print(out / 'report.json', flush=True); save()
    signal.signal(signal.SIGTERM, lambda s, f: (_ for _ in ()).throw(SystemExit(128 + s)))
    try:
        # Reject a nonterminal native report before treating its hashes as stable.
        evidence.verify_metadata(json.loads(qualified_path.read_text()))
        files = {Path(__file__).resolve(), Path(sys.executable).resolve()}
        files.update(ROOT / 'tests/cmac' / name for name in CONTROLS)
        # The control modules import older tests in their subprocesses. Bind
        # those source files too, not merely the four discover entrypoints.
        files.update((ROOT / 'tests/cmac').glob('*.py'))
        files.update(Path(m.__file__).resolve() for m in list(sys.modules.values())
            if getattr(m, '__file__', None) and Path(m.__file__).resolve().is_relative_to(ROOT / 'tools'))
        report['source'] = {str(path): digest(path) for path in files}
        report['stage'] = 'software_controls'; save()
        for name in CONTROLS:
            run(Path(name).stem, [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        report['stage'] = 'actual_source_bound_evidence_revalidation'; save()
        qualification, carry_build = evidence.verify_qualification(report['source'], qualified_path)
        report.update(qualified_executable=qualification['executable'], native_version=qualification['native_version'],
            corrected_DSP_parent_build=carry_build['parent_build_report'],
            original_failed_fixture_report=str(evidence.continuation.FAILED),
            original_failure_relabelled=False,
            revalidated_native_command_count=len(qualification['commands']),
            revalidated_native_rejections=len(evidence.REASONS),
            revalidated_native_routes=qualification['valid_routes'])
        designs = {'49': evidence.BASE, '50': qualified_path.parent / 'test-only-50.json',
                   '286': evidence.base.checker.TRANSFER.parent / 'corrected-transfer-input.json'}
        report['actual_input_pair_and_carry_audits'] = {}
        for name, path in designs.items():
            module = next(iter(json.loads(path.read_text())['modules'].values()))
            pairs = audit_pairs(module); roles = local_carry_roles(module)
            expected = {'49': (9, 8), '50': (10, 8), '286': (98, 0)}[name]
            assert (pairs['logic_pairs_compared'], len(roles)) == expected
            report['actual_input_pair_and_carry_audits'][name] = dict(pairs=pairs, local_carry_DI_roles=len(roles))
        verify_bindings(report['source'])
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status=PASS, stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error)); raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p.relative_to(ROOT)): digest(p) for p in out.rglob('*')
                               if p.is_file() and p.name != 'report.json'}
        save(); print(out / 'report.json', flush=True)


if __name__ == '__main__': main()
