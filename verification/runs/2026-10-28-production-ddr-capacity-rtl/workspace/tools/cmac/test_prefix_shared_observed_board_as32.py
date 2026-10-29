#!/usr/bin/env python3
"""Fresh full nine-mode mapped replay with only a wider host address-space cap.

Preserve the failed24 GiB attempt and all literal hardware, unmodified vendor
models/default glbl, raw inputs/goldens, warning checks, actual wrong-output
negative, nine modes and21600/86400-second deadlines. Derive the frozen runner
reversibly; change only its private virtual-address ceiling24→32 GiB and own
output/status/control metadata. This does not raise cgroup RAM/swap caps or
prove the earlier allocation failure's cause. Native/physical/RK/bitstream
acceptance remains false. No old result, CPU fallback or checksum manifest.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / 'openxc7')]
import test_prefix_shared_observed_board as previous
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_observed_board_as32_control.py'
FAILED = ROOT / 'build/rknpu-dsp-prefix-shared-observed-board/1791493285871405865/report.json'
ADDRESS_BYTES = 32 * 1024**3
SUCCESS = 'PASS_FULL_C32K16_SHARED_PREFIX_OWN_NINE_MODE_UNISIM_HOST_AS32_MAPPED_ONLY'


def verify_failed_metadata(report, log):
    assert report['status'] == 'FAIL_PREFIX_SHARED_OWN_NUMERICAL_REPLAY'
    assert report['stage'] == 'compile' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed'], report['modes']) == (
                32, 16, 512, 'xc7k480tffg1156-2', 20, 3588, list(range(9)))
    assert report['compile_timeout_seconds'] == 21600 and report['each_mode_timeout_seconds'] == 86400
    assert report['tests'] == [] and report['full_board_compilation_executed'] is True
    assert report['numerical_netlist_acceptance'] is False
    assert report['old_executable_or_numerical_result_inherited'] is False
    assert report['default_global_startup_preserved'] is True
    assert report['runtime_CPU_arithmetic_or_layout_fixup'] is False
    assert all(report[k] is False for k in previous.PHYSICAL_FLAGS)
    assert report['preparation_report'] == str(previous.PARENT)
    expected = ['software_controls', 'generated_check', 'iverilog_version', 'vvp_version',
                'model_commit', 'model_clean', 'compile']
    assert [c['label'] for c in report['commands']] == expected
    assert all(c['status'] == 'PASS' and c['returncode'] == 0 for c in report['commands'][:-1])
    compile_step = report['commands'][-1]
    assert compile_step['status'] == 'FAIL' and compile_step['returncode'] == 1
    assert compile_step['timeout_seconds'] == 21600 and compile_step['seconds'] < 21600
    assert 't-dll-expr.cc:624: Error: calloc() ran out of memory.' in log
    assert 'compiled_executable' not in report and 'execution_inputs' not in report


def verify_failed_parent():
    path = FAILED.resolve(strict=True)
    report = json.loads(path.read_text())
    log = Path(report['commands'][-1]['log']).resolve(strict=True)
    assert log == path.parent / 'compile.log'
    verify_failed_metadata(report, log.read_text())
    assert report['production_source_before'] == previous.source_revision()
    before = {}
    previous.preparation.merge(before, report['source'])
    for name in report['artifacts']:
        artifact = Path(name).resolve(strict=True)
        assert artifact.is_relative_to(path.parent)
    previous.preparation.merge(before, report['artifacts'])
    before[str(path)] = previous.digest(path)
    assert all(previous.digest(p) == sha for p, sha in before.items()), 'Changed preserved allocation-failure evidence'
    return before


OLD_LIMIT = '    resource.setrlimit(resource.RLIMIT_AS, (24 * 1024**3, 24 * 1024**3))\n'
NEW_LIMIT = '    resource.setrlimit(resource.RLIMIT_AS, (32 * 1024**3, 32 * 1024**3))\n'
REPLACEMENTS = (
    ('    before = {}\n', '    before = verify_failed_parent()\n'),
    (OLD_LIMIT, NEW_LIMIT),
    ('build/rknpu-dsp-prefix-shared-observed-board/', 'build/rknpu-dsp-prefix-shared-observed-board-as32/'),
    ('runtime_CPU_arithmetic_or_layout_fixup=False, scope=__doc__,',
     '''runtime_CPU_arithmetic_or_layout_fixup=False, scope=__doc__,
        allocator_retry_parent=str(FAILED), host_address_space_limit_bytes=ADDRESS_BYTES,
        only_host_virtual_address_limit_changed=True,
        original_inputs_tests_models_and_deadlines_preserved=True,'''),
    ('FAIL_PREFIX_SHARED_OWN_NUMERICAL_REPLAY', 'FAIL_PREFIX_SHARED_OWN_NUMERICAL_REPLAY_AS32'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 FAILED=FAILED, ADDRESS_BYTES=ADDRESS_BYTES, SUCCESS=SUCCESS,
                 verify_failed_parent=verify_failed_parent)
exec(compile(MAIN_SOURCE, __file__ + ':identical-full-replay-only-host-AS-ceiling-and-own-evidence', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
