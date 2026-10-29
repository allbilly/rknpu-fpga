#!/usr/bin/env python3
"""Reproduce host placer float-exp overflow on the actual device grid only.

Does not run placement, alter the qualified backend, change FPGA arithmetic
or remove assertions. The exact failing net was not captured; this control
demonstrates the inspected overload's failure for valid grid-spanning nets.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pack_prefix_board import ROOT, QUALIFICATION, DATABASE, CONSTIDS, digest, timestamp
from himbaechel_site_bels import SiteBELMap
from evidence import source_revision

FAILED_PLACE = ROOT / 'build/openxc7/full-prefix-native-place-1791396866085235676/report.json'
SOURCE = QUALIFICATION.parent / 'common/place/placer_static.cc'
CONTROL = Path(__file__).with_name('test_static_exp_precision.cpp')


def main():
    out = ROOT / f'build/openxc7/static-exp-precision-probe-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', started_utc=timestamp(), supervisor_pid=os.getpid(), commands=[],
        scope=__doc__, original_failure_preserved=True, exact_failed_net_captured=False,
        native_placement_executed=False, backend_modified=False, RTL_modified=False,
        physical_fit_verified=False, timing_signoff=False, bitstream_emitted=False,
        hardware_programmed=False, production_source_before=source_revision())

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    save()
    print(out / 'report.json', flush=True)
    try:
        failed = json.loads(FAILED_PLACE.read_text())
        assert failed['status'] == 'FAIL' and failed['finished_utc']
        step = failed['commands'][-1]
        assert Path(step['log']).stem == 'native_place' and step['status'] == 'FAIL' and step['returncode'] == -6
        log = ROOT / step['log']
        actual_failure = log.read_text()
        assert 'Assertion failure: std::isfinite(port.max_exp.at(axis)) (' in actual_failure
        assert '/common/place/placer_static.cc:916)' in actual_failure
        candidate = json.loads(QUALIFICATION.read_text())
        assert digest(SOURCE) == candidate['inputs'][str(SOURCE)]
        text = SOURCE.read_text()
        assert text.count('port.min_exp.at(axis) = std::exp(emin);') == 1
        assert text.count('port.max_exp.at(axis) = std::exp(emax);') == 1
        assert 'DoublePair max_exp{invalid, invalid};' in text and 'float emax = ' in text
        assert 'RealPair wl_coeff{0.5f, 0.5f};' in text
        with SiteBELMap(DATABASE, CONSTIDS) as db:
            width, height = db.width, db.height
        assert (width, height) == (327, 417)
        before = {str(path.resolve()): digest(path) for path in
                  (FAILED_PLACE, log, QUALIFICATION, SOURCE, DATABASE, CONSTIDS, CONTROL, Path(__file__))}
        report.update(source=before, grid_width=width, grid_height=height, failed_native_report=str(FAILED_PLACE.relative_to(ROOT)),
            old_expression='double_field = std::exp(float_exponent)',
            proposed_expression='double_field = std::exp(static_cast<double>(float_exponent))',
            preserves_weighted_average_objective=True, assertion_removal_proposed=False,
            coordinate_clipping_proposed=False, seed='0x3588e001')
        for path in (Path(__file__), CONTROL, SOURCE):
            shutil.copyfile(path, out / path.name)
        save()
        executable = out / 'precision-control'
        argv_list = (
            ('compiler_version', ['/usr/bin/c++', '--version'], 0),
            ('compile', ['/usr/bin/c++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                '-fno-fast-math', '-ffp-contract=off', str(out / CONTROL.name), '-o', str(executable)], 0),
            ('old_overload_negative', [str(executable), 'negative', str(width), str(height)], 1),
            ('widened_overload_positive', [str(executable), 'positive', str(width), str(height)], 0),
            ('generated_check', ['make', 'generated-check'], 0))
        for label, argv, expected in argv_list:
            started = time.monotonic()
            result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=180, check=False)
            output = result.stdout + result.stderr
            log_path = out / (label + '.log')
            log_path.write_text(output)
            command = dict(label=label, argv=argv, cwd=str(ROOT), returncode=result.returncode,
                expected_returncode=expected, seconds=round(time.monotonic() - started, 3),
                log=str(log_path.relative_to(ROOT)), status='PASS_EXPECTED_RESULT' if result.returncode == expected else 'FAIL')
            report['commands'].append(command)
            save()
            assert result.returncode == expected, output[-3000:]
            if label == 'old_overload_negative':
                assert output == 'EXPECTED_REJECT old_float_exp_overflow valid_grid_y=0..416 exponent=104\n'
            if label == 'widened_overload_positive':
                assert output == 'PASS_STATIC_EXP_PRECISION_ONLY extreme_random_cases=1028 finite_range_cases=1024 seed=3588e001\n'
            assert not re.search(r'(?im)warning:|error:', output), output[-2000:]
        assert all(digest(path) == sha for path, sha in before.items()), 'Changed precision-control source'
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='PASS_HOST_STATIC_EXP_OVERFLOW_REPRODUCER_AND_WIDENED_NUMERIC_CONTROLS_NOT_NATIVE_PLACEMENT',
            actual_old_overload_overflow_reproduced=True, widened_numeric_control_passed=True,
            complete_full_placement_recovery_proved=False)
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
