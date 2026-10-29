#!/usr/bin/env python3
"""Fresh native HeAP qualification of the isolated one-expression limit fix.

Admit only a completed byte-parent-reproduced build. Keep the original illegal
pair, three positive placements, full normal refinement, LUT truth, compiled
beta inspection and actual four-DSP/six-BRAM P&R/FASM guards. Use the existing
source-bound clock-multiplicity decoder for this fresh FASM only. No old native
log is copied into the new attempt or claimed as new execution. This is small
native qualification, not full fit, numerical/physical signoff or FPGA bits.
"""
import argparse
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_heap_attempt_limit_candidate as build
import qualify_native_heap_placement as first
import qualify_native_heap_typed_inspection as typed
import resume_native_heap_early_constraints as early
import clock_bound_native_features as clock
from audit_empty_output_pairs import source_shaped
from place_prefix_board import bind_report, verify_bindings

ROOT = first.ROOT
CONTROL = ROOT / 'tests/cmac/test_prefix_shared_heap_qualification_control.py'
QUALIFIED = 'QUALIFIED_SMALL_COUNTER_SAFE_HEAP_NORMAL_REFINEMENT_LUT_DSP_BRAM_CLOCK_FEATURES_NOT_FULL_FIT_OR_SIGNOFF'
COMMANDS = typed.COMMANDS
FLAGS = first.FLAGS


def admit_build(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('counter-safe-heap-engine-')
    completed = json.loads(path.read_text())
    build.verify_metadata(completed)  # No output/native tool on RUNNING/failed/incomplete builds.
    old, before = first.admit()
    assert old['executable'] == completed['parent_executable']
    assert old['native_version'] == completed['native_version']
    build.merge(before, completed['source'])
    build.merge(before, completed['artifacts'])
    before[str(path)] = build.digest(path)
    source = path.parent / 'common/place/placer_heap.cc'
    build.candidate.verify_source_transition(build.candidate.SOURCE.read_text(), source.read_text())
    assert build.digest(source) == completed['generated_source_sha256'] == before[str(source)]
    assert completed['source'][completed['parent_executable']['path']] == completed['parent_executable']['sha256']
    assert before[completed['executable']['path']] == completed['executable']['sha256']
    verify_bindings(before)
    assert completed['production_source_after'] == build.source_revision()
    # Command construction metadata only: keep frozen original small fixtures,
    # select this newly built executable. Never written as a circuit input.
    selected = dict(old, executable=completed['executable'], native_version=completed['native_version'],
                    own_build_report=str(path), parent_executable=completed['parent_executable'])
    return selected, before


def compare_features(out, original):
    module = next(iter(json.loads((out / 'routed.json').read_text())['modules'].values()))
    assert module['settings']['placer'] == 'heap' and float(module['settings']['target_freq']) == 50_000_000
    assert all(int(module['settings'][key], 2) == 1 for key in ('pack', 'place', 'route'))
    contracts = clock.clock_contracts(module)
    text = (out / 'control.fasm').read_text()
    features, io, clocks = clock.parse_clock_bound_features(text, contracts)
    namespace = dict(first.parent.first.__dict__,
                     parse_native_features=lambda value: clock.parse_clock_bound_features(value, contracts)[:2])
    # Unchanged original DSP/BRAM comparison body and every numerical/feature guard.
    exec(compile(inspect.getsource(first.parent.first.compare_features), __file__ + ':unchanged-feature-comparator', 'exec'), namespace)
    compared = namespace['compare_features'](out, original)
    assert compared['native_FASM_features'] == len(features) and compared['native_FASM_repeated_idempotent_STEPDOWN_lines'] == io
    return dict(**compared, clock_source_contract=clock.source_contract(), clock_fanout_contracts=contracts,
                native_FASM_repeated_clock_enable_lines=clocks, consumer_merge_contract=clock.consumer_merge_check())


METADATA_NAMESPACE = dict(early.VERIFY_NAMESPACE, QUALIFIED=QUALIFIED, COMMANDS=COMMANDS)
exec(compile(inspect.getsource(first.verify_metadata), __file__ + ':unchanged-native-metadata-gates', 'exec'), METADATA_NAMESPACE)


def verify_metadata(report):
    METADATA_NAMESPACE['verify_metadata'](report)
    assert report['native_source_or_executable_changed'] is True
    assert report['only_HeAP_limit_expression_changed'] is True and report['old_native_result_inherited'] is False
    assert report['clock_fanout_contracts'] and report['consumer_merge_contract']['conflicting_assignment_rejected']
    assert report['build_report'] and report['executable'] != report['qualified_parent_executable']
    commands = {s['label']: s for s in report['commands']}
    symbols = Path(commands['compiled_heap_symbol_census']['log']).read_text()
    typed.check_symbol_census(symbols)
    address, size = early.getter_symbol(symbols)
    assert report['compiled_heap_beta_store_certificate'] == early.validate_getter(
        Path(commands['compiled_heap_getter']['log']).read_text(), address, size, early.HEAD.read_text())
    exe = report['executable']['path']
    assert commands['compiled_heap_symbol_census']['argv'] == ['nm', '-S', '-C', exe]
    assert commands['compiled_heap_getter']['argv'] == ['objdump', '-d', '-C', '--start-address=' + hex(address),
                                                     '--stop-address=' + hex(address + size), exe]


OLD_ADMIT = '        q,before=admit()\n'
NEW_ADMIT = '''        q,before=admit_build(build_path)
        r.update(build_report=str(build_path),qualified_parent_executable=q['parent_executable'],
                 only_HeAP_limit_expression_changed=True,old_native_result_inherited=False)
'''
REPLACEMENTS = (
    ('def main():\n', '''def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-report',type=Path,required=True)
    build_path=parser.parse_args().build_report.resolve(strict=True)
    admit_build(build_path)  # Fail closed before creating any attempt.
'''),
    ('native-heap-typed-inspection-', 'counter-safe-heap-qualification-'),
    ('native_source_or_executable_changed=False', 'native_source_or_executable_changed=True'),
    (OLD_ADMIT, NEW_ADMIT),
    ('r.update(parent.first.compare_features(out,original))', 'r.update(compare_features(out,original))'),
    ("r.update(status='FAIL',error=repr(error))", "r.update(status='FAIL_COUNTER_SAFE_HEAP_QUALIFICATION',error=repr(error))"),
)
MAIN_SOURCE = source_shaped(typed.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(typed.NAMESPACE, __file__=__file__, __doc__=__doc__, argparse=argparse, CONTROL=CONTROL,
                 QUALIFIED=QUALIFIED, COMMANDS=COMMANDS, admit_build=admit_build,
                 compare_features=compare_features, verify_metadata=verify_metadata)
exec(compile(MAIN_SOURCE, __file__ + ':fresh-native-procedure-gates-unchanged', 'exec'), NAMESPACE)


def verify_qualification(path):
    report = json.loads(Path(path).read_text())
    verify_metadata(report)
    namespace = dict(NAMESPACE, admit=lambda: admit_build(Path(report['build_report'])))
    verify_source = source_shaped(typed.VERIFY_SOURCE,
        (('parent.first.compare_features(path.parent,original)', 'compare_features(path.parent,original)'),))
    exec(compile(verify_source, __file__ + ':unchanged-fresh-native-revalidation', 'exec'), namespace)
    return namespace['verify_qualification'](path)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
