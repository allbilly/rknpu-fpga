#!/usr/bin/env python3
"""Prepared full-frame packet roundtrip, explicitly NOT a test-ready bitstream.

Admit only the completed full corrected-mux route/frame chain. Revalidate raw
FASM requests, all8240 DSP/actual-clock frame bits, exact-part geometry and
corruption negatives before the already-qualified native assembler/decoder.
Keep all46336-frame/4679936-word/ECC and actual decoded-data/ECC negatives.
The full packet artifact is unreviewed/NOT_FOR_PROGRAMMING: numerical, timing,
electrical/DRC/configuration-CRC/test-ready gates remain false. No circuit or
physical waiver, old evidence edit, checksum manifest or FPGA/flash access.
"""
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_native_heap_bit_encoding as previous
import convert_recursive_mux_shared_frames as frames
from audit_empty_output_pairs import source_shaped

ROOT = previous.ROOT
CONTROL = ROOT / 'tests/cmac/test_recursive_mux_full_bit_control.py'
PASS = 'PASS_FULL_C32K16_RECURSIVE_MUX_PACKET_FRAME_DATA_AND_ECC_UNREVIEWED_NOT_TEST_READY_OR_SIGNOFF'
FLAGS = tuple(k for k in previous.FLAGS if k != 'full_target_bitstream_emitted') + ('reviewed_full_target_bitstream_emitted',)


def verify_full_frame_metadata(saved):
    assert saved['status'] == frames.PASS and saved['stage'] == 'complete' and saved['finished_utc']
    assert (saved['channels'], saved['kernels'], saved['parallel_products'], saved['part'],
            saved['intended_clock_period_ns'], saved['seed']) == (32, 16, 512, 'xc7k480tffg1156-2', 20, 3588)
    assert saved['full_board_FASM_conversion_executed'] is True
    assert all(saved[k] is False for k in frames.FLAGS)
    assert saved['production_source_before'] == saved['production_source_after']
    assert saved['source_defined_DSP_features'] == 8240
    assert saved['source_defined_native_statements'] == saved['converter_requests']['input_lines'] >= 8240
    assert saved['converter_requests']['injected_lines'] > 0
    clocks = saved['clock_contracts']
    assert clocks
    for field, count in (('DSP_frame_readback', 8240), ('clock_frame_readback', len(clocks))):
        result = saved[field]
        assert result['features_compared'] == result['physical_DB_bits_compared'] == len(result['locations']) == count
        assert result['actual_frame_bit_corruption_rejected_in_comparison_only'] is True
        assert result['all_set_and_clear_requirements_matched'] is True
        assert result['database_consistency_only_not_silicon_or_independent_specification'] is True
    assert set(saved['clock_frame_readback']['locations']) == set(clocks)
    geometry = saved['frame_geometry']
    assert (geometry['legal_target_frames'], geometry['supplied_frames'], geometry['tilegrid_frames'],
            geometry['missing_frames_zero_filled_by_assembler']) == (46336, 45892, 45892, 444)
    labels = ['software_controls', 'generated_check', 'parser_runtime_version', 'strict_full_native_FASM_conversion',
              'exact_part_frame_geometry', 'DSP_frame_readback', 'clock_frame_readback']
    assert [c['label'] for c in saved['commands']] == labels
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == c['expected_returncode'] == 0
               for c in saved['commands'])


def verify_full_frame_chain(path, saved, out):
    path = Path(path).resolve(strict=True)
    assert path.is_relative_to(ROOT / 'build/openxc7') and path.name == 'report.json'
    assert path.parent.name.startswith('full-recursive-mux-shared-native-heap-frames-')
    verify_full_frame_metadata(saved)
    route_path = Path(saved['full_route_report']).resolve(strict=True)
    assert route_path.parent.name.startswith('full-prefix-shared-recursive-mux-heap-literal-empty-v2-scan-route-')
    routed, before, fasm, placements, contracts = frames.admission.verify_route(route_path)
    assert saved['production_source_after'] == routed['production_source_after'] == previous.source_revision()
    assert saved['native_executable'] == routed['executable'] and saved['conversion_input'] == str(fasm)
    assert saved['clock_contracts'] == contracts
    previous.bind_report(path, saved, before)
    previous.verify_bindings(before)
    namespace = frames.NAMESPACE
    placed_path = (ROOT / routed['placed_report']).resolve(strict=True)
    assert placed_path.is_relative_to(ROOT / 'build/openxc7')
    placed = json.loads(placed_path.read_text())
    selected = frames.admission.route.NAMESPACE['selected_inputs'](placed, before)
    required, statements = namespace['required_features'](fasm, placements, selected, contracts)
    assert saved['source_defined_native_statements'] == statements
    expected = path.parent / 'comparison-only-8240-DSP-features.json'
    clocks = path.parent / 'comparison-only-clock-features.json'
    assert json.loads(expected.read_text()) == required
    assert json.loads(clocks.read_text()) == dict.fromkeys(contracts, '1')
    frame = previous.parent.small.original.frame
    destination = path.parent / 'native-conversion'
    converted = json.loads((destination / 'result.json').read_text())
    payload = frame.validate_conversion(converted, destination)
    assert str(payload) in before and previous.digest(payload) == before[str(payload)]
    requests = destination / 'feature-requests.jsonl'
    assert namespace['small'].original.verify_requests(namespace['converter_requests'](requests), required) == converted['counts'] == saved['converter_requests']
    assert namespace['small'].verify_clock_requests(namespace['converter_requests'](requests), contracts) == saved['clock_converter_requests']
    geometry = json.loads((path.parent / 'frame-validation.json').read_text())
    assert geometry['status'] == 'FRAME_INPUT_VALIDATION_PASS_ASSEMBLY_PENDING'
    assert geometry['inputs_unchanged'] is True and geometry['physical_verified'] is False
    assert geometry['validation'] == saved['frame_geometry']
    # Fresh readback/actual-bit negatives in this attempt's comparison outputs.
    # Neither expected features nor these outputs become assembler inputs.
    for label, target, method in (
        ('DSP_frame_readback', expected, namespace['dsp_readback']),
        ('clock_frame_readback', clocks, namespace['small'].clock_readback)):
        output = Path(out) / ('revalidated-' + label + '.json')
        method(payload, target, output)
        assert json.loads(output.read_text()) == saved[label]
        before[str(output)] = previous.digest(output)
    previous.verify_bindings(before)
    return before


OLD_ARGS = '    argparse.ArgumentParser(description=__doc__).parse_args()\n'
NEW_ARGS = '''    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames-report', type=Path, required=True)
    SMALL = parser.parse_args().frames_report.resolve(strict=True)
    assert SMALL.is_relative_to(ROOT / 'build/openxc7') and SMALL.name == 'report.json'
    assert SMALL.parent.name.startswith('full-recursive-mux-shared-native-heap-frames-')
'''
REPLACEMENTS = (
    (OLD_ARGS, NEW_ARGS),
    ('parent.verify_small_metadata(saved)', 'verify_full_frame_metadata(saved)'),
    ('resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3)', 'resource.RLIMIT_AS, (12 * 1024**3, 12 * 1024**3)'),
    ('small-native-heap-bit-encoding-', 'full-recursive-mux-shared-unreviewed-bit-encoding-'),
    ('full_target_parallel_products=512, native_control_dsps=4, native_control_brams=6,',
     'full_target_parallel_products=512, channels=32, kernels=16, native_target_dsps=515, native_target_brams=6,\n                  full_target_bitstream_emitted=False,'),
    ('before = {}; bind_report(SMALL, saved, before)', 'before = verify_full_frame_chain(SMALL, saved, out)'),
    ("saved['saved_native_evidence_report']", "saved['full_route_report']"),
    ("c['label'] == 'small_native_PNR_FASM'", "c['label'] == 'native_scan_and_route'"),
    ('saved_native_PNR_report=str(native_path)', 'saved_full_native_route_report=str(native_path)'),
    ('native_small_packet_assembly', 'native_full_unreviewed_packet_assembly'),
    ('small-control.NOT_FOR_PROGRAMMING.unverified.bit', 'full-C32K16.NOT_FOR_PROGRAMMING.unverified.bit'),
    ("        metadata = ypcb_bitstream.inspect(bit)\n", "        report['full_target_bitstream_emitted'] = True\n        metadata = ypcb_bitstream.inspect(bit)\n"),
    ('small_unreviewed_packet_artifact=metadata', 'full_unreviewed_packet_artifact=metadata'),
    ('FAIL_SMALL_NATIVE_HEAP_BIT_ENCODING', 'FAIL_FULL_RECURSIVE_MUX_UNREVIEWED_BIT_ENCODING'),
)
MAIN_SOURCE = source_shaped(inspect.getsource(previous.main), REPLACEMENTS)
NAMESPACE = dict(previous.__dict__, __file__=__file__, __doc__=__doc__, CONTROL=CONTROL,
                 FLAGS=FLAGS, PASS=PASS, verify_full_frame_metadata=verify_full_frame_metadata,
                 verify_full_frame_chain=verify_full_frame_chain)
exec(compile(MAIN_SOURCE, __file__ + ':same-qualified-native-packet-and-corruption-gates-full-bound-frame-input', 'exec'), NAMESPACE)


def main():
    NAMESPACE['main']()


if __name__ == '__main__':
    main()
