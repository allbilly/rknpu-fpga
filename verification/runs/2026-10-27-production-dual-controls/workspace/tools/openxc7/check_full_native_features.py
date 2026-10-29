"""Full routed DSP/BRAM source-defined FASM gate, not physical signoff.

The full caller must retain all 515 DSPs, including 16 C32 kernels, and six
BRAMs. Saved small native outputs validate the reader/comparator separately;
they cannot satisfy the full inventory. No comparison artifact is executed.
"""
from collections import Counter
import json
import mmap
from pathlib import Path
import re

from probe_prefix_native_config import parse_native_features
from check_prefix_native_features import compare_dsp, compare_bram
from pack_prefix_board import DATABASE, CONSTIDS
from himbaechel_site_bels import SiteBELMap

FEATURE_CONTROL = Path('/home/fedora/rknpu-fpga/build/openxc7/prefix-native-config-control-1791407940428316242/report.json')


def verify_feature_control_metadata(report, transition):
    assert report['status'] == 'PASS_SMALL_NATIVE_DSP_BRAM_SOURCE_DEFINED_FEATURE_CONTROL_WITH_EXPLICIT_GAPS_NOT_FULL_BOARD_OR_SIGNOFF'
    assert report['stage'] == 'complete' and report['finished_utc']
    assert report['native_control_primitive_counts'] == {'DSP48E1': 4, 'RAMB36E1': 6}
    assert report['full_target_parallel_products'] == 512
    assert report['native_control_PNR_FASM_executed'] is True
    assert report['native_tool_transition'] == transition, 'Feature control used a different native engine'
    assert report['clock_admission'] == dict(literal_SYS_CLK_alias_preserved=True, target_period_ns=20.0,
        native_parser_applied_constraint=True, clock_metadata_serialized=False, timing_signoff=False)
    assert len(report['DSP_feature_comparison']) == 4 and len(report['BRAM_feature_comparison']) == 6
    assert report['DSP_feature_comparison_pending'] is False
    for key in ('full_board_native_FASM_executed', 'full_board_numerical_acceptance', 'physical_fit_verified',
                'timing_signoff', 'electrical_verified', 'drc_signoff', 'bitstream_emitted', 'hardware_programmed',
                'expected_vectors_used_for_execution', 'full_circuit_identity_claimed', 'USE_MULT_physical_default_verified'):
        assert report[key] is False, 'Unsupported feature-control acceptance: ' + key
    labels = ['software_controls', 'feature_corruption_controls', 'generated_check', 'version',
              'native_clock_admission', 'native_PNR_FASM']
    assert [c['label'] for c in report['commands']] == labels
    assert all(c['status'] == 'PASS_TOOL_EXECUTION_ONLY' and c['returncode'] == 0 for c in report['commands'])
    for command in report['commands'][-2:]:
        argv = command['argv']
        assert argv[0] == transition['selected_executable']['path']
        for flag, value in (('--device', 'xc7k480tffg1156-2'), ('--freq', '50'), ('--seed', '3588')):
            assert argv.count(flag) == 1 and argv[argv.index(flag) + 1] == value
        assert '--Werror' in argv and '--timing-allow-fail' not in argv


def full_inventory(selected, packed):
    assert Counter(c['type'] for c in selected.values()) == {'DSP48E1': 515, 'RAMB36E1': 6}
    assert set(packed) == set(selected), 'Incomplete/extra routed DSP/BRAM membership'
    expected = {'DSP48E1': 'DSP48E1_DSP48E1', 'RAMB36E1': 'RAMB36E1_RAMB36E1'}
    assert all(packed[n]['type'] == expected[c['type']] for n, c in selected.items())
    groups = Counter(n.split('.')[0] for n, c in selected.items() if c['type'] == 'DSP48E1' and '.' in n)
    shell = [n for n, c in selected.items() if c['type'] == 'DSP48E1' and '.' not in n]
    assert len(groups) == 16 and set(groups.values()) == {32} and len(shell) == 3, 'Not the full C32/K16 target'
    return dict(groups)


def routed_primitives(path, names):
    """Read complete selected records without loading the full routed graph.

    This is pinned jsonwrite.cc syntax, not a general JSON parser. The caller
    separately proves the full module's resource/physical/circuit identity.
    """
    result = {}
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        pattern = rb'^          "type": "(?:DSP48E1_DSP48E1|RAMB36E1_RAMB36E1)",$'
        for match in re.finditer(pattern, data, re.MULTILINE):
            start = data.rfind(b'\n        "', 0, match.start())
            end = data.find(b'\n        }', match.end())
            assert start >= 0 and end > match.end(), 'Incomplete native primitive record'
            record = json.loads(b'{' + data[start + 1:end + len(b'\n        }')] + b'}')
            assert len(record) == 1
            name, cell = next(iter(record.items()))
            assert name in names and name not in result, 'Unexpected/duplicate routed DSP/BRAM'
            result[name] = cell
    assert set(result) == set(names), 'Missing routed DSP/BRAM record'
    return result


def placed_primitives(path, names):
    """Pinned write_placement one-record-per-line format; exact name set."""
    result, seen = {}, set()
    with Path(path).open() as stream:
        assert next(stream) == '{\n'
        for line in stream:
            if line == '}\n':
                assert not stream.read(), 'Extra native placement data'
                break
            assert line.startswith('  "'), 'Unsupported native placement format'
            record = json.loads('{' + line.rstrip().removesuffix(',') + '}')
            assert len(record) == 1
            name, placement = next(iter(record.items()))
            assert name not in seen, 'Duplicate native placement name'
            seen.add(name)
            if name in names:
                assert set(placement) == {'tile', 'site', 'bel', 'nextpnr_bel', 'type'}
                result[name] = placement
        else: raise AssertionError('Incomplete native placement object')
    assert set(result) == set(names), 'Missing native DSP/BRAM placement'
    return result


def compare_selected(features, placements, selected, packed, global_label):
    """Generic selected-record comparison; not the full-target census gate."""
    assert set(placements) == set(selected) == set(packed)
    bels = [placements[n]['nextpnr_bel'] for n in selected]
    assert len(set(bels)) == len(bels), 'Aliased selected DSP/BRAM BEL'
    checks = {}
    for name, original in selected.items():
        placement, native = placements[name], packed[name]
        # write_placement uses generic tile/BEL names; postRouteArchInfo
        # exports global site/BEL names. Use the exact bound v6 database,
        # never an inferred coordinate or permissive string normalization.
        assert global_label(placement['nextpnr_bel']) == native['attributes']['NEXTPNR_BEL'], 'Native placement differs from routed BEL'
        if original['type'] == 'DSP48E1': checks[name] = compare_dsp(features, placement, original, native)
        else:
            assert original['type'] == 'RAMB36E1' and native['type'] == 'RAMB36E1_RAMB36E1'
            checks[name] = compare_bram(features, placement, original)
    return checks


def verify_full_features(fasm_path, placement_path, routed_path, selected, expected_groups):
    packed = routed_primitives(routed_path, selected)
    groups = full_inventory(selected, packed)
    assert groups == expected_groups, 'Changed full kernel DSP grouping'
    placed = placed_primitives(placement_path, selected)
    features, repeated = parse_native_features(Path(fasm_path).read_text())
    with SiteBELMap(DATABASE, CONSTIDS) as database:
        checks = compare_selected(features, placed, selected, packed, database.global_label)
    return dict(status='COMPARED_ALL_515_DSP_AND_6_BRAM_SOURCE_DEFINED_FEATURES_WITH_EXPLICIT_GAPS_NOT_SIGNOFF',
        kernel_dsps=groups, selected_primitives_compared=len(checks), primitive_checks=checks,
        native_FASM_features=len(features), repeated_idempotent_STEPDOWN_lines=repeated,
        USE_MULT_physical_default_verified=False, ordinary_constant_net_routing_verified=False,
        observable_BRAM_startup_reset_independence_proved=False, numerical_acceptance=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False, hardware_programmed=False)
