#!/usr/bin/env python3
"""Continue unchanged shared replay preparation with a qualified counter view.

Preserve the first census FAIL and its original helper/guards. The existing
DSP declaration qualifier recognizes exactly four CEP timing-enable gates;
only the read-only resource-counter view receives it. All three actual
hardware modules, literal export, vendor models, raw bench and numerical/error
expectations remain unchanged. This is input preparation, not simulation,
physical signoff or a bitstream. No standalone SHA256SUMS file is created.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1] / 'openxc7')]
import prepare_prefix_shared_replay as previous
from lane_dsp_library import timing_only_view
from audit_empty_output_pairs import source_shaped

FAILED = previous.ROOT / 'build/rknpu-dsp-prefix-shared-replay-input/1791477912941138574/report.json'
CONTROL = previous.ROOT / 'tests/cmac/test_prefix_shared_replay_counter_control.py'


def verify_failure(report):
    assert report['status'] == 'FAIL_PREFIX_SHARED_REPLAY_PREPARATION' and report['finished_utc']
    assert report['stage'] == 'actual_full_hierarchy_and_wire_binding' and report['error'] == 'AssertionError()'
    assert (report['channels'], report['kernels'], report['parallel_products'], report['intended_part'],
            report['intended_clock_period_ns'], report['seed']) == (32, 16, 512, 'xc7k480tffg1156-2', 20, 3588)
    labels = ['software_controls', 'generated_check', 'yosys_version', 'iverilog_version', 'vvp_version', 'model_commit', 'model_clean']
    assert [s['label'] for s in report['commands']] == labels
    assert all(s['returncode'] == 0 and s['status'] == 'PASS_TOOL_OR_SOFTWARE_CONTROL_ONLY' for s in report['commands'])
    assert report['old_numerical_result_inherited'] is report['full_board_compilation_executed'] is report['numerical_netlist_acceptance'] is False
    assert Path(previous.__file__).resolve().as_posix() in report['source']


def admit_failure():
    report = json.loads(FAILED.read_text())
    verify_failure(report)
    before = {}
    previous.merge(before, report['source'])
    previous.merge(before, report['artifacts'])
    assert all(previous.digest(p) == sha for p, sha in before.items()), 'Changed original failed preparation evidence'
    assert report['production_source_before'] == previous.source_revision()
    before[str(FAILED)] = previous.digest(FAILED)
    return before


OLD_SOURCE = "    try:\n        before = {}\n"
NEW_SOURCE = "    try:\n        before = admit_failure()\n        report['original_failure_report'] = str(FAILED)\n        report['original_failure_relabelled'] = False\n"
OLD_COUNTS = "        counts = physical_counts(candidate['modules'], TOP, {TOP, PRIVATE, SHARED})\n"
NEW_COUNTS = """        counter_view, qualifiers = timing_only_view(candidate['modules'])
        assert qualifiers == parent['counter_timing_qualifiers'], 'Changed qualified DSP timing declaration'
        counts = physical_counts(counter_view, TOP, {TOP, PRIVATE, SHARED})
        del counter_view
        report['counter_timing_qualifiers'] = qualifiers
        report['counter_view_used_for_export_or_simulation'] = False
"""
REPLACEMENTS = (
    ('build/rknpu-dsp-prefix-shared-replay-input/', 'build/rknpu-dsp-prefix-shared-replay-qualified-input/'),
    (OLD_SOURCE, NEW_SOURCE), (OLD_COUNTS, NEW_COUNTS),
    ('FAIL_PREFIX_SHARED_REPLAY_PREPARATION', 'FAIL_PREFIX_SHARED_REPLAY_COUNTER_CONTINUATION'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 FAILED=FAILED, admit_failure=admit_failure, timing_only_view=timing_only_view)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-replay-input-counter-qualification-only', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
