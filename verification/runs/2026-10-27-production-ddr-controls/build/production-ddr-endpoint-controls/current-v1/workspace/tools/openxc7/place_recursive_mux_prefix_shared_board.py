#!/usr/bin/env python3
"""Full shared C32/K16 placement after fresh recursive-mux qualification/packing.

Keep every original full-scope input, placement, normal-refinement, complete
cell/BEL, DSP/tie, clock and finite-counter guard. Require the newly qualified
engine and its actual newly characterized full packed graph, not the old fixed
523410-cell/checksum expectation. Compare actual repacking against that new
graph's logged checksum/census and source-defined finite wide limit. No old
graph/checksum/error expectation is overwritten, no small-probe shortcut,
serialization, tensor/CPU fixup, physical waiver, routing, bits or FPGA access.
"""
import inspect
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import place_counter_safe_prefix_shared_board as previous
import pack_recursive_mux_prefix_shared_board as packer
import qualify_recursive_mux_feedthrough as qualification
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_full_place_control.py'
PLACED = 'PLACED_FULL_C32K16_SHARED_PREFIX_RECURSIVE_MUX_HEAP_NORMAL_REFINEMENT_NOT_ROUTED_FIT_OR_SIGNOFF'
NATIVE_TIMEOUT = previous.NATIVE_TIMEOUT


def admit_qualification(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-qualification-')
    report = json.loads(path.read_text())
    qualification.verify_metadata(report)  # No output/native tool for incomplete or small-probe-only records.
    admitted, before = qualification.verify_qualification(path)
    assert admitted == report and report['executable'] != report['qualified_parent_executable']
    assert report['only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent'] is True
    assert report['counter_safe_HeAP_parent_retained'] is True and report['old_native_result_inherited'] is False
    return admitted, before


def full_log_checks(text, packed):
    """Actual newly packed graph identity/finite counter, not a fit certificate."""
    packer.validate_pack(packed)
    marker = 'Creating initial analytic placement for '
    assert text.count(marker) == 1, 'Missing/ambiguous full analytic placement'
    section = text.split(marker, 1)[0]
    log = Path(packed['commands'][-1]['log']).read_text()
    pattern = r'(?m)^Info: Checksum: (0x[0-9a-f]{8})$'
    expected, observed = re.findall(pattern, log), re.findall(pattern, section)
    assert len(expected) == 1 and observed == expected, 'Repacking differs from new qualified full packed graph'
    count = packed['native_census']['cells']
    actual = re.findall(r'Creating initial analytic placement for (\d+) cells,', text)
    assert actual == [str(count)], 'Changed complete full analytic cell census'
    limits = re.findall(r'(?m)^Info: Running main analytical placer, max placement attempts per cell = (\d+)\.$', text)
    limit = previous.qualification.build.candidate.limit(count, 8)
    assert limit == 2147483646 and limits == [str(limit)], 'Wrong source-bound counter-safe finite limit'
    return dict(actual_packed_checksum=observed[0], actual_full_packed_cells=count,
                actual_logged_maximum_attempts_per_cell=limit, finite_counter_rejection_preserved=True,
                old_fixed_packed_census_or_checksum_inherited=False, physical_fit_verified=False)


def check_heap_log(code, text):
    # The original complete native normal-refinement/legality/warning checker.
    # Full new graph checksum/census is checked separately with its bound report.
    previous.previous.check_heap_log(code, text)


REPLACEMENTS = (
    ('admit_qualification(qp)  # Fail closed before any output/native tool launch.',
     'preflight, _ = admit_qualification(qp)  # Fail closed before any output/native tool launch.'),
    ('    validate_pack(pack)  # No tools/output on RUNNING, reduced target or capacity conflict.\n',
     '''    validate_pack(pack)  # No tools/output on RUNNING, reduced target or capacity conflict.
    assert pack['executable'] == preflight['executable'], 'Packed graph uses a different qualified engine'
'''),
    ('full-prefix-shared-counter-safe-heap-place-', 'full-prefix-shared-recursive-mux-heap-place-'),
    ('native_source_or_executable_changed=True, only_HeAP_limit_expression_changed=True,',
     '''native_source_or_executable_changed=True,
        only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
        counter_safe_HeAP_parent_retained=True,'''),
    ('counter_safe_engine_build_report=', 'recursive_mux_engine_build_report='),
    ("report['counter_safe_attempt_limit_and_packed_checksum'] = full_log_checks(log)",
     "report['recursive_mux_attempt_limit_and_packed_checksum'] = full_log_checks(log, pack)"),
    (previous.PLACED, PLACED),
    ('FAIL_PREFIX_SHARED_COUNTER_SAFE_HEAP_PLACE', 'FAIL_PREFIX_SHARED_RECURSIVE_MUX_HEAP_PLACE'),
)
MAIN_SOURCE = source_shaped(previous.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(previous.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 validate_pack=packer.validate_pack, admit_qualification=admit_qualification,
                 check_heap_log=check_heap_log, full_log_checks=full_log_checks)
exec(compile(MAIN_SOURCE, __file__ + ':all-original-full-placement-gates-new-source-bound-pack-profile', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
