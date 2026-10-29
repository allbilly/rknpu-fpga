#!/usr/bin/env python3
"""Run the unchanged HeAP arithmetic fixture with explicit Clang C++ driver.

Both earlier linker failures and helpers remain frozen. Only the compiler's
C++ driver selection changes; source expression, UBSan and all positive and
overflow expectations are unchanged. This is a host-expression reproduction,
not a repaired nextpnr, new placement, proof of fit or physical signoff.
"""
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import audit_shared_heap_attempt_limit as audit
import continue_shared_heap_attempt_limit as continuation
from evidence import source_revision, timestamp

PARENT = audit.ROOT / 'build/openxc7/shared-heap-attempt-limit-clang-audit-1791479949964695628/report.json'
CONTROL = audit.ROOT / 'tests/cmac/test_prefix_shared_heap_driver_control.py'


def compile_argv(old, output):
    argv = list(old)
    assert argv.count('-o') == 1 and '--driver-mode=g++' not in argv
    assert all(argv.count(flag) == 1 for flag in ('-Werror', '-fsanitize=signed-integer-overflow', '-fno-sanitize-recover=all'))
    assert Path(argv[0]).name == 'clang-22' and argv.count('-std=c++17') == 1
    argv.insert(1, '--driver-mode=g++')
    argv[argv.index('-o') + 1] = str(output)
    return argv


def main():
    parent = json.loads(PARENT.read_text())
    assert parent['status'] == 'FAIL_SHARED_HEAP_ATTEMPT_LIMIT_CLANG_AUDIT' and parent['finished_utc']
    assert parent['commands'][-1]['label'] == 'compile_exact_expression'
    assert parent['commands'][-1]['returncode'] == 1 and parent['commands'][-1]['status'] == 'FAIL'
    assert "undefined reference to `std::cout'" in Path(parent['commands'][-1]['log']).read_text()
    assert parent['original_GCC_failure_relabelled'] is parent['native_placement_reexecuted'] is False
    before = continuation.admit_failure()
    for manifest in (parent['source'], parent['artifacts']):
        for name, sha in manifest.items():
            assert name not in before or before[name] == sha
            before[name] = sha
    cpp = Path(parent['commands'][-1]['argv'][-3]).resolve(strict=True)
    assert cpp.name == 'actual_expression.cc' and cpp.read_text() == audit.fixture(audit.SOURCE.read_text())
    before.update({str(p): audit.digest(p) for p in (PARENT, CONTROL, Path(__file__).resolve(), Path(sys.executable).resolve())})
    assert all(audit.digest(p) == sha for p, sha in before.items())
    assert source_revision() == parent['production_source_before']
    out = audit.ROOT / f'build/openxc7/shared-heap-arithmetic-cxx-driver-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', stage='host_expression_replay', started_utc=timestamp(), source=before,
        parent_report=str(PARENT), production_source_before=source_revision(), commands=[], scope=__doc__,
        actual_packed_cells=parent['actual_packed_cells'], mathematical_default_attempt_limit=parent['mathematical_default_attempt_limit'],
        actual_native_logged_attempt_limit=10000, original_failures_relabelled=False,
        actual_fixture_source=str(cpp), exact_fixture_bytes_preserved=True, native_placement_reexecuted=False,
        correction_proves_fit=False, numerical_netlist_acceptance=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, bitstream_emitted=False, hardware_programmed=False)

    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    def run(label, argv, count=None):
        step = dict(label=label, argv=list(map(str, argv)), log=str(out / (label + '.log')), status='RUNNING')
        report['commands'].append(step)
        save()
        start = time.monotonic()
        try:
            result = subprocess.run(step['argv'], cwd=audit.ROOT, capture_output=True, text=True, timeout=120)
            text = result.stdout + result.stderr
            Path(step['log']).write_text(text)
            step['returncode'] = result.returncode
            if count is None:
                assert result.returncode == 0 and not re.search(r'(?im)\b(?:warning|error)\s*:', text)
                step['status'] = 'PASS_HOST_TOOL_OR_CONTROL_ONLY'
            else:
                step['status'] = audit.validate_arithmetic(text, result.returncode, count)
        except BaseException:
            step['status'] = 'FAIL'
            raise
        finally:
            step['seconds'] = round(time.monotonic() - start, 3)
            save()

    save()
    print(out / 'report.json', flush=True)
    try:
        run('software_controls', [sys.executable, '-B', '-W', 'error', '-m', 'unittest', 'discover',
                                 '-s', 'tests/cmac', '-p', CONTROL.name, '-v'])
        run('generated_check', ['make', 'generated-check'])
        argv = compile_argv(parent['commands'][-1]['argv'], out / 'actual_expression')
        run('compiler_version', [argv[0], '--driver-mode=g++', '--version'])
        run('compile_exact_expression_cxx_driver', argv)
        exe = out / 'actual_expression'
        report['execution_inputs'] = {str(p): audit.digest(p) for p in (cpp, exe)}
        for n in (7, 46340, 46341, parent['actual_packed_cells']):
            run('count_' + str(n), [exe, str(n)], n)
        assert all(audit.digest(p) == sha for p, sha in report['execution_inputs'].items())
        assert all(audit.digest(p) == sha for p, sha in before.items())
        report['production_source_after'] = source_revision()
        assert report['production_source_after'] == report['production_source_before']
        report.update(status='CONFIRMED_SOURCE_BOUND_HEAP_DEFAULT_ATTEMPT_ARITHMETIC_OVERFLOW_NOT_FIT_OR_SIGNOFF', stage='complete')
    except BaseException as error:
        report.update(status='FAIL_SHARED_HEAP_CXX_DRIVER_REPLAY', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(p): audit.digest(p) for p in out.rglob('*') if p.is_file() and p.name != 'report.json'}
        save()


if __name__ == '__main__':
    main()
