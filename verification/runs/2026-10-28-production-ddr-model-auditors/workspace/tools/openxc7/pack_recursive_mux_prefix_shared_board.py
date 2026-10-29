#!/usr/bin/env python3
"""Fresh full C32/K16 packing with the completely qualified recursive mux engine.

Keep the unchanged literal shared-prefix physical input, all 512 CMAC/three
shell DSPs, six BRAM, exact part, 20ns clock, seed3588 and all original input,
native schema/primitive, DSP-configuration/tie, clock and LUT-capacity guards.
Require all original small native qualification gates plus corrected mux
placement; a small standalone mux probe is insufficient. Preserve/revalidate
the original encoder's full 515-DSP baseline certificate, without presenting
it as full packing by the newly compiled engine. This fresh full pack must
itself compare all 515 DSP configurations/4120 ties and characterize its whole
new graph before any subsequent full placement. No old checksum/census is
rewritten, no old pack log copied, no tensor/CPU fixup, physical waiver,
SHA256SUMS, bitstream or FPGA/flash access.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack_prefix_shared_board as previous
import qualify_recursive_mux_feedthrough as qualification
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_full_pack_control.py'
PACKED = 'PACKED_FULL_C32K16_SHARED_PREFIX_RECURSIVE_MUX_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF'


def admit_qualification(path):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('recursive-mux-feedthrough-qualification-')
    report = json.loads(path.read_text())
    qualification.verify_metadata(report)  # No output/native execution on incomplete/small-probe-only records.
    legacy = json.loads(previous.QUALIFICATION.read_text())
    previous.validate_qualification(legacy)  # Retain original full-DSP encoder certificate and every old gate.
    admitted, before = qualification.verify_qualification(path)
    assert admitted == report and report['executable'] != report['qualified_parent_executable']
    candidate = qualification.candidate
    built = json.loads(Path(report['build_report']).read_text())
    candidate.verify_metadata(built)
    parent = json.loads(candidate.PARENT.read_text())
    link = next(step for step in parent['commands'] if step['label'] == 'link_counter_safe_heap')
    changed = next(step for step in built['commands'] if step['label'] == 'link_recursive_mux_feedthrough')
    assert changed['argv'] == candidate.link_argv(link['argv'], Path(built['executable']['path']),
        {candidate.OBJECT: Path(report['build_report']).parent / 'pack.cc.o'})
    assert changed['cwd'] == link['cwd'], 'Changed qualified native link context'
    # The native DSP packer/writer and all other actual link objects are unchanged.
    candidate.heap.merge(before, legacy['source'])
    candidate.heap.merge(before, legacy['artifacts'])
    before[str(previous.QUALIFICATION)] = previous.digest(previous.QUALIFICATION)
    qualification.verify_bindings(before)
    return admitted, before


def validate_qualification(report):
    qualification.verify_metadata(report)
    assert str(previous.JSON_WRITER) in report['source'] and str(previous.DATABASE) in report['source']
    assert report['source'][report['executable']['path']] == report['executable']['sha256']


def validate_pack(report):
    # Same complete full-pack gate body; only this new profile's status token differs.
    PACK_METADATA_NAMESPACE['validate_pack'](report)
    assert report['only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent'] is True
    assert report['legacy_full_encoder_result_inherited_as_new_pack'] is False
    assert report['encoder_qualification'] and report['legacy_DSP_encoder_qualification']


OLD_NATIVE = '    native = json.loads(QUALIFICATION.read_text())\n'
NEW_NATIVE = '''    qp = args.qualification.resolve(strict=True)
    native, qualified_bindings = admit_qualification(qp)
'''
REPLACEMENTS = (
    ('    args = parser.parse_args()\n', '''    parser.add_argument('--qualification', type=Path, required=True)
    args = parser.parse_args()
'''),
    (OLD_NATIVE, NEW_NATIVE),
    ('full-prefix-shared-native-pack-', 'full-prefix-shared-recursive-mux-native-pack-'),
    ('encoder_qualification=str(QUALIFICATION),', '''encoder_qualification=str(qp),
        legacy_DSP_encoder_qualification=str(previous.QUALIFICATION),
        only_recursive_mux_feedthrough_changed_relative_to_counter_safe_parent=True,
        legacy_full_encoder_result_inherited_as_new_pack=False,'''),
    ('        before = {}\n', '        before = dict(qualified_bindings)\n'),
    ('paths = {pp, QUALIFICATION, CONTROL,', 'paths = {pp, qp, CONTROL, previous.CONTROL, qualification.CONTROL,'),
    ('PACKED_FULL_C32K16_SHARED_PREFIX_NATIVE_RESOURCE_CHARACTERIZATION_NOT_PLACED_FIT_OR_SIGNOFF', PACKED),
    ('FAIL_PREFIX_SHARED_NATIVE_PACK', 'FAIL_RECURSIVE_MUX_SHARED_NATIVE_PACK'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, previous=previous,
                 qualification=qualification, CONTROL=CONTROL, admit_qualification=admit_qualification,
                 validate_qualification=validate_qualification)
exec(compile(MAIN_SOURCE, __file__ + ':unchanged-full-input-census-DSP-clock-and-capacity-gates', 'exec'), NAMESPACE)

# Do not alter the frozen original full-pack validator or its expectations.
import place_prefix_shared_board as old_place
PACK_METADATA_NAMESPACE = dict(old_place.__dict__, PACKED=PACKED)
exec(compile(inspect.getsource(old_place.validate_pack), __file__ + ':unchanged-complete-full-pack-admission', 'exec'), PACK_METADATA_NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
