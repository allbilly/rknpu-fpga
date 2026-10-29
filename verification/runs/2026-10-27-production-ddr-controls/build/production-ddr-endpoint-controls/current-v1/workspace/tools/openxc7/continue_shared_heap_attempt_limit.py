#!/usr/bin/env python3
"""Repeat the exact HeAP arithmetic audit with available Clang UBSan runtime.

Keep the GCC link failure, original helper/controls and every expression and
runtime expectation unchanged. This isolated compiler selection does not
repair/rebuild nextpnr, rerun placement or prove that the mux/design fits.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_shared_heap_attempt_limit as previous
from audit_empty_output_pairs import source_shaped

AUDIT_FAILED = previous.ROOT / 'build/openxc7/shared-heap-attempt-limit-audit-1791479701447349503/report.json'
CONTROL = previous.ROOT / 'tests/cmac/test_prefix_shared_heap_limit_clang_control.py'
RUNTIME = Path('/home/linuxbrew/.linuxbrew/Cellar/llvm/22.1.7_1/lib/clang/22/lib/linux')


def admit_failure():
    report = json.loads(AUDIT_FAILED.read_text())
    assert report['status'] == 'FAIL_SHARED_HEAP_ATTEMPT_LIMIT_AUDIT' and report['finished_utc']
    assert report['stage'] == 'host_arithmetic_reproduction' and report['error'] == 'AssertionError()'
    steps = report['commands']
    assert [s['label'] for s in steps] == ['software_controls', 'compiler_version', 'compile_exact_expression']
    assert all(s['status'] == 'PASS_HOST_TOOL_OR_CONTROL_ONLY' and s['returncode'] == 0 for s in steps[:2])
    assert steps[-1]['status'] == 'FAIL' and steps[-1]['returncode'] == 1
    assert 'cannot find /usr/lib64/libubsan.so.1.0.0' in Path(steps[-1]['log']).read_text()
    assert report['native_placement_reexecuted'] is report['failed_placement_relabelled'] is False
    before = dict(report['source'])
    for name, sha in report['artifacts'].items():
        assert name not in before or before[name] == sha
        before[name] = sha
    assert all(previous.digest(p) == sha for p, sha in before.items()), 'Changed GCC failure/source'
    before[str(AUDIT_FAILED)] = previous.digest(AUDIT_FAILED)
    for name in ('libclang_rt.ubsan_standalone-x86_64.a', 'libclang_rt.ubsan_standalone_cxx-x86_64.a'):
        path = (RUNTIME / name).resolve(strict=True)
        before[str(path)] = previous.digest(path)
    return before


OLD_BIND = '    for path in (SOURCE, COMMAND, Path(failed[\'commands\'][-1][\'argv\'][0])):\n'
NEW_BIND = '''    for path, sha in admit_failure().items():
        assert path not in before or before[path] == sha
        before[path] = sha
''' + OLD_BIND
OLD_SAVE = '    def save():\n'
NEW_SAVE = '''    report['original_GCC_audit_failure'] = str(AUDIT_FAILED)
    report['original_GCC_failure_relabelled'] = False
    report['clang_UBSan_runtime_selection_only'] = True

''' + OLD_SAVE
REPLACEMENTS = (
    ("compiler = Path(shutil.which('g++')).resolve(strict=True)", "compiler = Path(shutil.which('clang++')).resolve(strict=True)"),
    (OLD_BIND, NEW_BIND), (OLD_SAVE, NEW_SAVE),
    ('build/openxc7/shared-heap-attempt-limit-audit-', 'build/openxc7/shared-heap-attempt-limit-clang-audit-'),
    ('FAIL_SHARED_HEAP_ATTEMPT_LIMIT_AUDIT', 'FAIL_SHARED_HEAP_ATTEMPT_LIMIT_CLANG_AUDIT'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 AUDIT_FAILED=AUDIT_FAILED, admit_failure=admit_failure)
exec(compile(MAIN_SOURCE, __file__ + ':compiler-selection-only', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
