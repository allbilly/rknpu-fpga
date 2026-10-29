#!/usr/bin/env python3
"""Full shared C32/K16 placement with a freshly qualified counter-safe engine.

Keep the original full literal input, all 512 products, part/clock/seed,
native legality/refinement, complete cell/BEL inventory and DSP comparisons.
Select only a completed new native qualification of the isolated one-expression
HeAP correction. Require the old packing checksum and the corrected finite
default attempt limit in the actual new full native log. No old result, CPU
tensor fixup, relaxed physical gate, changed live helper or SHA256SUMS is used.
This is placement characterization, not routed fit or bitstream readiness.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import place_prefix_shared_board as previous
import qualify_counter_safe_heap as qualification
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_heap_place_control.py'
PLACED = 'PLACED_FULL_C32K16_SHARED_PREFIX_COUNTER_SAFE_HEAP_NORMAL_REFINEMENT_NOT_ROUTED_FIT_OR_SIGNOFF'
PACKED_REPORT = ROOT / 'build/openxc7/full-prefix-shared-native-pack-1791474646490498829/report.json'
NATIVE_TIMEOUT = previous.NATIVE_TIMEOUT


def admit_qualification(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('counter-safe-heap-qualification-')
    report = json.loads(path.read_text())
    qualification.verify_metadata(report)  # No execution output for incomplete qualification.
    admitted, before = qualification.verify_qualification(path)
    assert admitted == report
    assert report['executable'] != report['qualified_parent_executable']
    assert report['only_HeAP_limit_expression_changed'] is True
    assert report['old_native_result_inherited'] is False
    return admitted, before


def full_log_checks(text):
    """Actual logged wide limit and unchanged packing, not a fit certificate."""
    marker = 'Creating initial analytic placement for '
    assert text.count(marker) == 1, 'Missing/ambiguous full analytic placement'
    packed_section = text.split(marker, 1)[0]
    pack = json.loads(PACKED_REPORT.read_text())
    previous.validate_pack(pack)
    command = pack['commands'][-1]
    packed_log = Path(command['log']).read_text()
    pattern = r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$'
    expected = re.findall(pattern, packed_log)
    observed = re.findall(pattern, packed_section)
    assert len(expected) == 1 and observed == expected, 'Changed actual native packed checksum'
    limits = re.findall(r'(?m)^Info: Running main analytical placer, max placement attempts per cell = (\d+)\.$', text)
    count = pack['native_census']['cells']
    assert count == 523410
    limit = qualification.build.candidate.limit(count, 8)
    assert limit == 2147483646 and limits == [str(limit)], 'Wrong/ambiguous actual counter-safe finite native limit'
    return dict(actual_packed_checksum=observed[0], actual_full_packed_cells=count,
                actual_logged_maximum_attempts_per_cell=limit,
                finite_counter_rejection_preserved=True, physical_fit_verified=False)


def check_heap_log(code, text):
    previous.check_heap_log(code, text)
    full_log_checks(text)


OLD_ADMIT = '        candidate, before = verify_qualification(HEAP_QUALIFICATION)\n'
NEW_ADMIT = '''        candidate, before = admit_qualification(qp)
        report.update(qualified_parent_executable=candidate['qualified_parent_executable'],
                      counter_safe_engine_build_report=candidate['build_report'])
'''
REPLACEMENTS = (
    ('    args = parser.parse_args()\n', '''    parser.add_argument('--qualification', type=Path, required=True)
    args = parser.parse_args()
    qp = args.qualification.resolve(strict=True)
    admit_qualification(qp)  # Fail closed before any output/native tool launch.
'''),
    ('full-prefix-shared-native-heap-place-', 'full-prefix-shared-counter-safe-heap-place-'),
    ('qualification=str(HEAP_QUALIFICATION),', 'qualification=str(qp),'),
    ('scope=__doc__, source={}, commands=[],', '''scope=__doc__, source={}, commands=[],
        native_source_or_executable_changed=True, only_HeAP_limit_expression_changed=True,
        old_native_result_inherited=False,'''),
    (OLD_ADMIT, NEW_ADMIT),
    ('        verify_clock_admission(log, constraints)\n', '''        verify_clock_admission(log, constraints)
        report['counter_safe_attempt_limit_and_packed_checksum'] = full_log_checks(log)
'''),
    ('PLACED_FULL_C32K16_SHARED_PREFIX_NATIVE_HEAP_NORMAL_REFINEMENT_NOT_ROUTED_FIT_OR_SIGNOFF', PLACED),
    ('FAIL_PREFIX_SHARED_NATIVE_HEAP_PLACE', 'FAIL_PREFIX_SHARED_COUNTER_SAFE_HEAP_PLACE'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 admit_qualification=admit_qualification, check_heap_log=check_heap_log,
                 full_log_checks=full_log_checks)
exec(compile(MAIN_SOURCE, __file__ + ':full-scope-native-placement-gates-unchanged', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
