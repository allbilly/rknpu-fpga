"""Revalidate completed clean reused-top mapped evidence for checkpoint admission.

This preserves the original full frame/hold/reset/negative gates. It does not
accept the earlier numerical PASS with masked ar errors or authorize emission.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint
import dsp_prefix_top_compile_admission as admission
import dsp_prefix_protected_library_contract as protected
import dsp_prefix_build_contract as build_contract

original = admission.kernel.runner
STATUS = 'PASS_FULL_C32K16_DSP_PREFIX_ARRAY_MAPPED_BINARY_CLEAN_REUSED_TOP_FIXTURES_ONLY'
LABELS = ('verilator_version', 'cxx_version', 'make_version', 'ar_version', 'verilator_root',
    'top_compile', 'kernel_archive_members', 'merged_archive_members', 'negative_test', 'actual_test')


def validate_metadata(report):
    assert report['status'] == STATUS, 'Completed clean full mapped replay required'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert (report['channels'], report['kernels'], report['parallel_products'], report['frames'],
        report['expected_outputs'], report['seed']) == (32, 16, 512, 208, 3328, '0x35883216')
    for name in ('complete_build_diagnostics_accepted', 'full_mapped_gate_accepted',
            'numerical_netlist_binary_fixture_acceptance', 'reused_compiled_kernel',
            'reused_actual_generated_top', 'original_failures_preserved'):
        assert report[name] is True, name
    for name in ('four_state_x_acceptance', 'raw_board_numerical_acceptance',
            'physical_fit_verified', 'bitstream_emitted', 'hardware_programmed'):
        assert report[name] is False, name
    assert report['result'] == original.EXPECTED
    assert report['library_operations'] == ['combo_update', 'create', 'seq_update']
    path = report['operational_library_path_contract']
    assert path['changed_generated_variable'] == 'VM_HIER_LIBS'
    assert path['make_dependency_resolves_to_same_library'] is True
    assert path['stock_archive_extraction_resolves_to_same_library'] is True
    assert path['rtl_or_generated_cpp_changed'] is False
    members = report['archive_member_contract']
    assert members['exact_member_multiset_verified'] is True
    assert members['kernel_object_count'] > 0 and members['top_object_count'] > 0
    assert members['merged_object_count'] == members['kernel_object_count'] + members['top_object_count']
    assert [Path(step['log']).stem for step in report['commands']] == list(LABELS)
    for label, step in zip(LABELS, report['commands'], strict=True):
        assert step['status'] == 'PASS' and type(step['returncode']) is int
        assert (step['returncode'] != 0 if label == 'negative_test' else step['returncode'] == 0), label


def verify(path, area_path, native_path, area, native):
    report = json.loads(path.read_text())
    validate_metadata(report)
    for manifest in (report['source'], report['artifacts'], report['initial_admission_inputs'],
            report['copied_generated_inputs'], report['execution_inputs']):
        assert fingerprint([ROOT / name for name in manifest['files']]) == manifest
    for name in ('tools/cmac/resume_dsp_prefix_generated_top.py',
            'tools/cmac/dsp_prefix_build_contract.py', 'tools/cmac/dsp_prefix_protected_library_contract.py'):
        assert name in report['source']['files']
    paths = {name: ROOT / value for name, value in report['parent_reports'].items()}
    assert set(paths) == {'top', 'fdce_verilator', 'fdce_iverilog', 'top_archive'}
    parent, kernel, top, admitted = admission.admit(*(paths[name] for name in
        ('top', 'fdce_verilator', 'fdce_iverilog', 'top_archive')))
    assert kernel == report['compiler_admission'] and top == report['top_admission']
    assert report['tool_version'] == parent['tool_version'] and report['cxx_version'] == parent['cxx_version']
    compiled_path = ROOT / parent['parent_reports']['compile']
    compiled = admission.kernel.verify_report(compiled_path, 'FAIL')
    assert compiled['parent_reports'] == {'area': str(area_path.relative_to(ROOT)),
        'native': str(native_path.relative_to(ROOT))}
    assert original.mapping.verify_area(area_path)[0] == area
    assert original.replay.verify_native(native_path) == native
    original.mapping.validate_shared_leaf(area, native)
    assert compiled['kernel_cells']['DSP48E1'] == 32
    assert not any(count for kind, count in compiled['kernel_cells'].items() if kind.startswith('FD'))
    assert compiled['export_circuit_identity'] == 'PASS_ALL_PORT_BITS_CELL_TYPES_PARAMETERS_AND_WIRE_INCIDENCE'
    old = compiled_path.parent
    library = old / 'cell' / ('lib' + original.BLOCK + '.a')
    obj = path.parent / 'top'
    hierarchy = obj / ('V' + original.BENCH + '_hier.mk')
    generated = paths['top'].parent / 'top'
    changed, contract = build_contract.relative_hierarchy_library(
        (generated / hierarchy.name).read_text(), obj, library)
    assert hierarchy.read_text() == changed and contract == report['operational_library_path_contract']
    for name in report['copied_generated_inputs']['files']:
        copied = ROOT / name
        assert copied.is_relative_to(obj)
        source = generated / copied.relative_to(obj)
        assert str(source.relative_to(ROOT)) in parent['artifacts']['files']
        if copied != hierarchy:
            assert copied.read_bytes() == source.read_bytes(), 'Modified generated C++ or make input'
    wrapper, bridge = [old / 'cell' / (original.BLOCK + suffix) for suffix in ('.sv', '.cpp')]
    cpp = sorted(obj.glob('V' + original.BENCH + '*.cpp'))
    assert protected.validate(wrapper.read_text(), bridge.read_text(), [file.read_text() for file in cpp]) == report['source_bound_protected_library_interface']
    assert not any('LUT' in file.name or original.SIM_KERNEL in file.name for file in cpp)
    assert fingerprint([obj / 'sim', library]) == report['execution_inputs']
    steps = {Path(step['log']).stem: step for step in report['commands']}
    for label in LABELS[:-2]:
        text = (ROOT / steps[label]['log']).read_text()
        build_contract.require_clean_build(text)
        assert len(admission.kernel.validate_followup(text, admitted)) == steps[label]['exact_admitted_diagnostic_count']
    member_contract = build_contract.validate_archive_members(
        (ROOT / steps['kernel_archive_members']['log']).read_text(),
        (ROOT / steps['merged_archive_members']['log']).read_text(),
        [file.name for file in obj.glob('V' + original.BENCH + '*.o')])
    assert member_contract == report['archive_member_contract']
    vectors = (ROOT / native['vector_report']).parent / 'vectors.hex'
    negative = old / 'negative_vectors.hex'
    assert len(vectors.read_text().splitlines()) == 208
    assert negative.read_text() == original.negative_vectors(vectors.read_text())
    for label, stimulus, is_negative in (('negative_test', negative, True), ('actual_test', vectors, False)):
        step = steps[label]
        assert step['argv'] == [str(obj / 'sim'), f'+VECTORS={stimulus}', '+COUNT=208']
        assert fingerprint([stimulus]) == report['stimulus_inputs'][label]
        result = original.validate_result((ROOT / step['log']).read_text(), step['returncode'], is_negative)
        if result:
            assert result == report['result']
    errors = ROOT / report['preserved_build_errors']
    preserved = json.loads(errors.read_text())
    assert preserved['archive_sha256'] == report['preserved_build_error_archive_sha256']
    assert preserved['complete_build_diagnostics_accepted'] is preserved['full_mapped_gate_accepted'] is False
    assert str(errors.relative_to(ROOT)) in report['source']['files']
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapped', 'area', 'native'):
        parser.add_argument('--' + name + '-report', type=Path, required=True)
    args = parser.parse_args()
    paths = [getattr(args, name + '_report').resolve() for name in ('mapped', 'area', 'native')]
    assert all(file.is_relative_to(ROOT) and file.is_file() for file in paths)
    validate_metadata(json.loads(paths[0].read_text()))
    area = original.mapping.verify_area(paths[1])[0]
    native = original.replay.verify_native(paths[2])
    result = verify(*paths, area, native)
    print(json.dumps(dict(status='PASS_FULL_CLEAN_PREFIX_MAPPED_REPLAY_REVALIDATION_ONLY',
        report=str(paths[0].relative_to(ROOT)), source_sha256=result['source']['sha256'],
        frames=208, checked_outputs=3328, parallel_products=512,
        physical_fit_verified=False, bitstream_emitted=False), sort_keys=True))
