#!/usr/bin/env python3
"""Record fresh comparator software controls, not new native P&R evidence.

Saved native artifacts are read-only parser/comparison targets. They cannot
admit full routing, placement transfer, physical signoff or bitstream emission.
No standalone SHA256SUMS manifest is written.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_full_corrected_native_features as features
from pack_prefix_board import ROOT, digest, timestamp
from probe_prefix_native_config import SELECTED
from place_prefix_board import verify_bindings
from evidence import source_revision

CONTROL = ROOT / 'tests/cmac/test_full_corrected_native_feature_control.py'
PARENT = ROOT / 'build/openxc7/corrected-dsp-checkpoint-resume-1791418453459203706/report.json'


def main():
    out = ROOT / f'build/openxc7/corrected-full-feature-controls-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, out / 'executed_source.py')
    shutil.copyfile(CONTROL, out / 'executed_control_source.py')
    report = dict(status='RUNNING', stage='admission', started_utc=timestamp(),
        scope=__doc__, source={}, commands=[], saved_native_control_report=str(PARENT),
        full_target_parallel_products=512, saved_control_dsps=4, saved_control_brams=6,
        fresh_native_execution=False, full_board_features_compared=False,
        full_route_admitted=False, placement_transfer_admitted=False,
        numerical_acceptance=False, physical_fit_verified=False, timing_signoff=False,
        electrical_verified=False, drc_signoff=False, bitstream_emitted=False,
        hardware_programmed=False, production_source_before=source_revision())
    report['software_runtime'] = dict(python_executable=str(Path(sys.executable).resolve(strict=True)), python_version=sys.version)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    save()
    print(out / 'report.json', flush=True)
    try:
        parent = json.loads(PARENT.read_text())
        assert parent['status'] == 'PASS_CORRECTED_DSP_BRAM_PLACED_RELOAD_AND_ROUTE_WITH_EXACT_EMPTY_INPUT_METADATA_VIEW_NOT_FULL_TRANSFER_OR_SIGNOFF'
        assert parent['stage'] == 'complete' and parent['finished_utc']
        files = [PARENT, SELECTED, features.DATABASE, features.CONSTIDS,
                 Path(__file__), CONTROL, Path(sys.executable).resolve(strict=True)]
        for name in ('control.fasm', 'placement.json', 'routed.json'):
            path = PARENT.parent / name
            assert digest(path) == parent['artifacts'][str(path.relative_to(ROOT))]
            files.append(path)
        assert digest(SELECTED) == parent['source'][str(SELECTED.resolve())]
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                files.append(Path(filename))
        report['source'] = {str(path.resolve(strict=True)): digest(path) for path in files}
        verify_bindings(report['source'])
        report['stage'] = 'software_controls'
        for label, argv in [('software_controls', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac', '-p', CONTROL.name, '-v']),
                            ('generated_check', ['make', 'generated-check'])]:
            log = out / (label + '.log')
            step = dict(label=label, argv=argv, cwd=str(ROOT), log=str(log),
                        status='RUNNING', expected_returncode=0, timeout_seconds=120)
            report['commands'].append(step)
            save()
            started = time.monotonic()
            with log.open('w') as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=120)
            step.update(returncode=result.returncode, seconds=round(time.monotonic() - started, 3),
                        status='PASS_SOFTWARE_CONTROL_ONLY' if result.returncode == 0 else 'FAIL')
            save()
            assert result.returncode == 0, log.read_text()[-4000:]
        verify_bindings(report['source'])
        report['production_source_after'] = source_revision()
        assert report['production_source_before'] == report['production_source_after']
        report.update(status='PASS_CORRECTED_FULL_FEATURE_COMPARATOR_SOFTWARE_CONTROLS_NOT_FULL_ROUTE_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.iterdir()
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
