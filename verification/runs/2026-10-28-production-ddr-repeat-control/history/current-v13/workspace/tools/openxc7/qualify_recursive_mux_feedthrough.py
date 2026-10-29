#!/usr/bin/env python3
"""Fresh native qualification of the isolated recursive mux legalization engine.

Keep all original exact illegal-pair rejection, three positive placements,
normal refinement, 1024 LUT comparisons, compiled beta certificate, four-DSP/
six-BRAM route and clock/FASM guards. Add a real native placement of the same
shared-root mux fixture used by the completed build. All prior inputs, sources,
error expectations and result logs remain untouched. No full placement/route,
timing/electrical/DRC signoff, bitstream, checksum manifest or card access.
"""
from collections import Counter
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_native_io_mux_feedthrough_candidate as build
import qualify_counter_safe_heap as base
from audit_empty_output_pairs import source_shaped
from place_prefix_board import verify_bindings
from route_prefix_board import logical_lut

candidate = build.previous.original
ROOT = candidate.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_qualification_control.py'
QUALIFIED = 'QUALIFIED_SMALL_RECURSIVE_MUX_HEAP_LUT_DSP_BRAM_CLOCK_FEATURES_NOT_FULL_FIT_OR_SIGNOFF'
MUX_LABEL = 'mux_feedthrough_native_place'
COMMANDS = [*base.COMMANDS, MUX_LABEL]
FLAGS = base.FLAGS


def admit_build(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-native-io-engine-')
    completed = json.loads(path.read_text())
    candidate.verify_metadata(completed)  # No output or native execution for incomplete/failed builds.
    counter, before = base.verify_qualification(candidate.QUALIFICATION)
    assert counter['executable'] == completed['parent_executable']
    assert counter['native_version'] == completed['native_version']
    # The already revalidated static record supplies unchanged original fixtures,
    # never an inherited native result for this newly compiled executable.
    static_path = base.first.PARENT.resolve(strict=True)
    assert before[str(static_path)] == candidate.digest(static_path)
    old = json.loads(static_path.read_text())
    assert old['executable'] == counter['qualified_parent_executable']
    assert old['native_version'] == completed['native_version']
    candidate.heap.merge(before, completed['source'])
    for name in completed['artifacts']:
        assert Path(name).is_absolute() and Path(name).resolve(strict=True).is_relative_to(path.parent)
    candidate.heap.merge(before, completed['artifacts'])
    before[str(path)] = candidate.digest(path)
    source = path.parent / 'himbaechel/uarch/xilinx/pack.cc'
    candidate.verify_source_transition(candidate.SOURCE.read_text(), source.read_text())
    assert candidate.digest(source) == completed['generated_source_sha256'] == before[str(source)]
    assert before[completed['executable']['path']] == completed['executable']['sha256']
    assert before[completed['parent_executable']['path']] == completed['parent_executable']['sha256']
    assert completed['production_source_after'] == candidate.source_revision()
    # Revalidate actual probe artifacts, not just stored PASS metadata.
    for filename, corrected, key in (('parent-packed.json', False, 'parent_probe'),
                                      ('candidate-packed.json', True, 'candidate_probe')):
        packed = json.loads((path.parent / filename).read_text())
        assert build.probe.packed_probe(packed, corrected) == completed[key]
    build.probe.validate_source_contract()
    steps = {step['label']: step for step in completed['commands']}
    for label, filename, exe in (('native_parent_pack_probe', 'parent-packed.json', completed['parent_executable']['path']),
                                  ('native_candidate_pack_probe', 'candidate-packed.json', completed['executable']['path'])):
        assert steps[label]['argv'] == candidate.pack_argv(exe, path.parent / 'mux_probe.json',
                                                         path.parent / 'mux_probe.xdc', path.parent / filename)
    assert 'PASS_MUX_FEEDTHROUGH_FOUR_STATE vectors=16384 comparisons=32768' in Path(steps['four_state_equivalence']['log']).read_text()
    assert 'MUX_EQ_MISMATCH vector=0 inactive=0' in Path(steps['wrong_output_negative']['log']).read_text()
    verify_bindings(before)
    return dict(old, executable=completed['executable'], native_version=completed['native_version'],
                own_build_report=str(path), parent_executable=completed['parent_executable']), before


def mux_place_argv(build_path, out):
    build_path = Path(build_path)
    completed = json.loads(build_path.read_text())
    argv = candidate.pack_argv(completed['executable']['path'], build_path.parent / 'mux_probe.json',
                              build_path.parent / 'mux_probe.xdc', Path(out) / 'mux-feedthrough-placed.json')
    assert argv.count('--pack-only') == 1
    i = argv.index('--pack-only')
    return argv[:i] + ['--placer', 'heap', '--no-route'] + argv[i + 1:]


def validate_mux_module(module, built):
    settings, cells = module['settings'], module['cells']
    assert settings['placer'] == 'heap' and float(settings['target_freq']) == 50_000_000
    assert int(settings['pack'], 2) == int(settings['place'], 2) == 1
    assert int(settings.get('route', '0'), 2) == 0
    counts = dict(Counter(cell['type'] for cell in cells.values()))
    assert counts == built['candidate_probe']['cell_counts'], 'Changed native mux fixture primitive census'
    bels = [cell['attributes'].get('NEXTPNR_BEL') for cell in cells.values()]
    assert all(isinstance(bel, str) and bel for bel in bels) and len(set(bels)) == len(bels)
    root = cells['root']
    assert root['type'] == 'SELMUX2_1' and root['attributes']['X_ORIG_TYPE'] == 'MUXF8'
    ground = [cell['connections']['Y'] for cell in cells.values() if cell['type'] == 'PSEUDO_GND']
    assert len(ground) == 1 and len(ground[0]) == 1
    comparisons = 0
    for expected in built['candidate_probe']['paths']:
        wrapper = cells[expected['wrapper']]
        identity = cells[expected['immediate_driver']]
        original = cells[expected['original_shared_mux']]
        assert wrapper['type'] == 'SELMUX2_1' and wrapper['attributes']['X_ORIG_TYPE'] == 'MUXF7'
        assert original['type'] == 'SELMUX2_1' and original['attributes']['X_ORIG_TYPE'] == 'MUXF7'
        assert root['connections'][expected['root_port']] == wrapper['connections']['OUT']
        assert wrapper['connections']['S0'] == ground[0], 'Nonconstant wrapper select'
        assert identity['attributes']['X_ORIG_TYPE'] == 'LUT1'
        logical = logical_lut(identity)  # Source-defined original-pin view; never rewrites a circuit input.
        assert wrapper['connections']['0'] == logical['connections']['O']
        assert logical['connections']['I0'] == original['connections']['OUT']
        assert int(logical['parameters']['INIT'], 2) == 2, 'Changed feed-through truth table'
        for bit in (0, 1):
            assert ((int(logical['parameters']['INIT'], 2) >> bit) & 1) == bit
            comparisons += 1
    assert comparisons == 4
    for i, name in enumerate(('left', 'right', 'root')):
        pad = cells['output_pad' + str(i) + '$intcell$OBUF']
        assert pad['attributes']['X_ORIG_TYPE'] == 'OBUF'
        assert pad['connections']['IN'] == cells[name]['connections']['OUT']
    return dict(placed_cells=len(cells), unique_bels=len(bels), native_fixture_counts=counts,
                shared_original_mux_exports_preserved=True, inserted_identity_luts=2,
                identity_truth_comparisons=comparisons, clock_period_ns=20,
                native_routing_executed=False, full_target_fit_or_timing_signoff=False)


def validate_mux_placed(path, build_path):
    data = json.loads(Path(path).read_text())
    assert len(data['modules']) == 1
    return validate_mux_module(next(iter(data['modules'].values())), json.loads(Path(build_path).read_text()))


METADATA_NAMESPACE = dict(base.METADATA_NAMESPACE, QUALIFIED=QUALIFIED, COMMANDS=COMMANDS)
exec(compile(inspect.getsource(base.first.verify_metadata), __file__ + ':unchanged-original-native-gates', 'exec'), METADATA_NAMESPACE)


def verify_metadata(report):
    METADATA_NAMESPACE['verify_metadata'](report)
    assert report['native_source_or_executable_changed'] is True and report['old_native_result_inherited'] is False
    assert report['only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent'] is True
    assert report['counter_safe_HeAP_parent_retained'] is True
    assert report['executable'] != report['qualified_parent_executable']
    assert report['clock_fanout_contracts'] and report['consumer_merge_contract']['conflicting_assignment_rejected']
    steps = {step['label']: step for step in report['commands']}
    symbols = Path(steps['compiled_heap_symbol_census']['log']).read_text()
    base.typed.check_symbol_census(symbols)
    address, size = base.early.getter_symbol(symbols)
    assert report['compiled_heap_beta_store_certificate'] == base.early.validate_getter(
        Path(steps['compiled_heap_getter']['log']).read_text(), address, size, base.early.HEAD.read_text())
    exe = report['executable']['path']
    assert steps['compiled_heap_symbol_census']['argv'] == ['nm', '-S', '-C', exe]
    assert steps['compiled_heap_getter']['argv'] == ['objdump', '-d', '-C', '--start-address=' + hex(address),
                                                  '--stop-address=' + hex(address + size), exe]
    assert report['mux_native_positive_placements'] == 1
    assert report['mux_placement_checks']['inserted_identity_luts'] == 2
    assert report['mux_placement_checks']['identity_truth_comparisons'] == 4
    assert report['mux_placement_checks']['shared_original_mux_exports_preserved'] is True


OLD_ADMIT = base.NEW_ADMIT
NEW_ADMIT = '''        q,before=admit_build(build_path)
        r.update(build_report=str(build_path),qualified_parent_executable=q['parent_executable'],
                 only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
                 counter_safe_HeAP_parent_retained=True,old_native_result_inherited=False)
'''
OLD_FEATURE = 'r.update(compare_features(out,original));verify_bindings(before)'
NEW_FEATURE = '''r.update(compare_features(out,original))
        run('mux_feedthrough_native_place',mux_place_argv(build_path,out),timeout=3600)
        check_heap_log(0,Path(r['commands'][-1]['log']).read_text())
        r.update(mux_native_positive_placements=1,
                 mux_placement_checks=validate_mux_placed(out/'mux-feedthrough-placed.json',build_path))
        verify_bindings(before)'''
REPLACEMENTS = (('counter-safe-heap-qualification-', 'recursive-mux-feedthrough-qualification-'),
                (OLD_ADMIT, NEW_ADMIT), (OLD_FEATURE, NEW_FEATURE),
                ('FAIL_COUNTER_SAFE_HEAP_QUALIFICATION', 'FAIL_RECURSIVE_MUX_FEEDTHROUGH_QUALIFICATION'))
MAIN_SOURCE = source_shaped(base.MAIN_SOURCE, REPLACEMENTS)
NAMESPACE = dict(base.NAMESPACE, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 QUALIFIED=QUALIFIED, COMMANDS=COMMANDS, admit_build=admit_build,
                 verify_metadata=verify_metadata, mux_place_argv=mux_place_argv,
                 validate_mux_placed=validate_mux_placed)
exec(compile(MAIN_SOURCE, __file__ + ':all-original-native-procedure-plus-mux-placement', 'exec'), NAMESPACE)


def verify_qualification(path):
    path = Path(path).resolve(strict=True)
    report = json.loads(path.read_text())
    verify_metadata(report)
    namespace = dict(NAMESPACE, admit=lambda: admit_build(Path(report['build_report'])))
    extra = '''        elif label=='mux_feedthrough_native_place':
            assert c['argv']==mux_place_argv(Path(r['build_report']),path.parent)
            check_heap_log(c['returncode'],text)
            assert r['mux_placement_checks']==validate_mux_placed(path.parent/'mux-feedthrough-placed.json',Path(r['build_report']))
'''
    verify_source = source_shaped(base.typed.VERIFY_SOURCE,
        (('parent.first.compare_features(path.parent,original)', 'compare_features(path.parent,original)'),
         ('        elif label==\'compiled_heap_symbol_census\':check_symbol_census(text)',
          extra + '        elif label==\'compiled_heap_symbol_census\':check_symbol_census(text)')))
    exec(compile(verify_source, __file__ + ':fresh-native-plus-mux-artifact-revalidation', 'exec'), namespace)
    return namespace['verify_qualification'](path)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
