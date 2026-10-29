#!/usr/bin/env python3
"""Audit the old full pack/small FASM for upstream DSP tile-constant gaps.

This reads all 515 actual DSP records and the saved four-DSP native encoder
control. Upstream source snapshots are comparison evidence only, never
executed. Findings do not rewrite the old source-consistency PASS or admit a
bitstream. No packing, placement, routing, RTL, fixture or donor edits.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from place_prefix_board import ROOT, digest, timestamp, verify_packed_metadata
from check_full_native_features import FEATURE_CONTROL, full_inventory, placed_primitives, routed_primitives, verify_feature_control_metadata
from probe_prefix_native_config import SELECTED, FASM_SOURCE, parse_native_features
from audit_prefix_config_contract import dsp_contract

PACK_REPORT = ROOT / 'build/openxc7/full-prefix-native-pack-1791394643587130253/report.json'
UPSTREAM = 'a662c08d25d7d2524ab341a387f120521c8a5d08'
UPSTREAM_INVERSION = '915d376e35f37b1b8c6e959dbe46999a1eaa321b'
PINS = tuple([('INMODE', i) for i in range(5)] + [('ALUMODE', 2), ('ALUMODE', 3), ('OPMODE', 6)])
DB = Path('/home/fedora/tiny-gpu/build/ypcb/prjxray-db/kintex7')


def requirements(original):
    dsp_contract(original)
    required = {}
    for bus, bit in PINS:
        value = original['connections'][bus][bit]
        assert value == '0', 'This audit admits only the actual zero-constant pin profile'
        required[bus + str(bit)] = dict(bus=bus, bit=bit, logical_value=0)
    return required


def declared_ties(packed):
    assert packed['type'] == 'DSP48E1_DSP48E1'
    result = {}
    for level in ('GND', 'VCC'):
        names = packed['attributes']['DSP_' + level + '_PINS'].split()
        assert len(names) == len(set(names)) and not set(names) & set(result), 'Aliased/conflicting DSP ties'
        result.update(dict.fromkeys(names, level))
    return result


def packed_gap(original, packed):
    required = requirements(original)
    ties = declared_ties(packed)
    result = {}
    for pin, spec in required.items():
        # Preserve the original logical constant, not the packer's VCC net
        # alone. Its per-bit inversion is what turns VCC into logical zero.
        param = f"IS_{spec['bus']}[{spec['bit']}]_INVERTED"
        value = packed['parameters'][param]
        assert re.fullmatch('[01]+', value) and int(value, 2) == 1
        if pin not in ties:
            result[pin] = dict(required_logical_tile_tie='GND', declared_tile_tie=None,
                old_packer_per_bit_inversion=1,
                upstream_requires_tile_tie_with_physical_inverter_disabled=True)
    return result


def sample_gap(features, placement, original):
    match = re.fullmatch(r'DSP48_X\d+Y(\d+)', placement['site'])
    assert match and placement['type'] == 'DSP48E1_DSP48E1'
    tile = placement['tile']
    assert re.fullmatch(r'DSP_[LR]_X\d+Y\d+', tile)
    side, slot = tile[4], int(match.group(1)) % 2
    required = {}
    for pin, spec in requirements(original).items():
        required[f'{tile}.DSP_{slot}_{pin}.DSP_GND_{side}'] = '1'
        required[f"{tile}.DSP48.DSP_{slot}.ZIS_{spec['bus']}_INVERTED[{spec['bit']}]"] = '1'
    missing = {name: value for name, value in required.items() if features.get(name) != value}
    return dict(required_features=required, absent_or_different_features=missing)


def finding_status(full_count, small_count):
    assert type(full_count) is int and full_count >= 0 and type(small_count) is int and small_count >= 0
    if full_count and small_count:
        return 'CONFIRMED_FULL_PACKED_AND_SAVED_SMALL_NATIVE_DSP_CONSTANT_ENCODING_GAP_NOT_FIXED_NOT_SILICON_TEST'
    if full_count or small_count:
        return 'PARTIAL_DSP_CONSTANT_ENCODING_GAP_IN_INSPECTED_ARTIFACTS_NOT_FIXED_NOT_SILICON_TEST'
    return 'NO_GAP_FOUND_BY_THIS_AUDIT_NOT_ENCODER_OR_PHYSICAL_ACCEPTANCE'


def main():
    out = ROOT / f'build/openxc7/upstream-dsp-constant-gap-audit-{time.time_ns()}'
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), out / 'executed_source.py')
    report = dict(status='RUNNING', started_utc=timestamp(), python=sys.version,
        old_native_source_revision='c68c13582e972292c86a5025140d52e713384cbc',
        upstream_tie_commit=UPSTREAM, upstream_inversion_commit=UPSTREAM_INVERSION,
        source={}, upstream_sources={}, scope=__doc__, full_parallel_products=512,
        full_native_FASM_executed=False, new_native_tool_executed=False,
        corrected_encoder_qualified=False, physical_fit_verified=False,
        timing_signoff=False, electrical_verified=False, drc_signoff=False,
        bitstream_emitted=False, hardware_programmed=False, source_consistency_parent_relabelled=False)
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(out / 'report.json', flush=True)
    save()
    try:
        pack = json.loads(PACK_REPORT.read_text())
        verify_packed_metadata(pack)
        small = json.loads(FEATURE_CONTROL.read_text())
        verify_feature_control_metadata(small, small['native_tool_transition'])
        packed_path = ROOT / pack['packed_design']
        small_paths = [FEATURE_CONTROL.parent / name for name in ('control.fasm', 'placement.json', 'routed.json')]
        control_path = ROOT / 'tests/cmac/test_upstream_dsp_constant_audit_control.py'
        paths = [Path(__file__), control_path, Path(sys.executable).resolve(strict=True),
                 PACK_REPORT, FEATURE_CONTROL, SELECTED, packed_path, *small_paths,
                 FASM_SOURCE, FASM_SOURCE.parent / 'pack_dsp_xc7.cc', DB / 'segbits_dsp_l.db', DB / 'segbits_dsp_r.db']
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and Path(filename).resolve().is_relative_to(ROOT / 'tools'):
                paths.append(Path(filename).resolve())
        report['source'] = {str(path.resolve(strict=True)): digest(path) for path in paths}
        assert report['source'][str(SELECTED)] == small['source'][str(SELECTED)], 'Changed original DSP/BRAM inventory'
        assert report['source'][str(packed_path)] == pack['artifacts'][str(packed_path.relative_to(ROOT))]
        for path in small_paths:
            assert report['source'][str(path)] == small['artifacts'][str(path.relative_to(ROOT))]
        report['software_control_argv'] = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/cmac',
                                           '-p', control_path.name, '-v']
        started = time.monotonic()
        with (out / 'software_controls.log').open('w') as log:
            subprocess.run(report['software_control_argv'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        report['software_controls_seconds'] = round(time.monotonic() - started, 3)
        report['software_controls_status'] = 'PASS_SOFTWARE_CONTROLS_ONLY'
        for filename in ('fasm.cc', 'pack_dsp_xc7.cc'):
            url = f'https://raw.githubusercontent.com/openXC7/nextpnr/{UPSTREAM}/himbaechel/uarch/xilinx/{filename}'
            with urllib.request.urlopen(url, timeout=30) as response:
                source = response.read()
            assert source.startswith(b'/*') and b'Permission to use, copy, modify' in source
            path = out / ('upstream-' + filename)
            path.write_bytes(source)
            report['upstream_sources'][url] = dict(path=str(path.relative_to(ROOT)), sha256=digest(path), executed=False)
        selected = json.loads(SELECTED.read_text())
        packed = routed_primitives(packed_path, selected)
        report['kernel_dsps'] = full_inventory(selected, packed)
        dsps = {name: cell for name, cell in selected.items() if cell['type'] == 'DSP48E1'}
        report['full_packed_gap'] = {name: packed_gap(cell, packed[name]) for name, cell in dsps.items()}
        report['affected_full_dsps'] = sum(bool(gap) for gap in report['full_packed_gap'].values())
        report['missing_full_declared_tile_ties'] = sum(map(len, report['full_packed_gap'].values()))
        # The exact local segbits recognize both physical levels in both slots.
        db_keys = {side: {line.split()[0] for line in (DB / f'segbits_dsp_{side.lower()}.db').read_text().splitlines() if line}
                   for side in ('L', 'R')}
        for side in ('L', 'R'):
            for slot in (0, 1):
                for bus, bit in PINS:
                    for level in ('GND', 'VCC'):
                        key = f'DSP_{side}.DSP_{slot}_{bus}{bit}.DSP_{level}_{side}'
                        assert key in db_keys[side], 'Missing local dedicated-tie DB feature: ' + key
        report['local_dedicated_tile_features_checked'] = 64
        origins = small['control_origins']
        placements = placed_primitives(small_paths[1], origins)
        features, repeated = parse_native_features(small_paths[0].read_text())
        report['saved_native_small_gap'] = {name: sample_gap(features, placements[name], selected[origin])
                                           for name, origin in origins.items() if selected[origin]['type'] == 'DSP48E1'}
        assert len(report['saved_native_small_gap']) == 4
        report['absent_or_different_small_native_features'] = sum(len(item['absent_or_different_features'])
                                                                 for item in report['saved_native_small_gap'].values())
        report['repeated_idempotent_STEPDOWN_lines'] = repeated
        assert all(digest(Path(path)) == sha for path, sha in report['source'].items()), 'Changed audit input'
        report['status'] = finding_status(report['missing_full_declared_tile_ties'], report['absent_or_different_small_native_features'])
    except BaseException as error:
        report.update(status='FAIL', error=repr(error))
        raise
    finally:
        report['finished_utc'] = timestamp()
        report['artifacts'] = {str(path.relative_to(ROOT)): digest(path) for path in out.iterdir()
                               if path.is_file() and path.name != 'report.json'}
        save()
        print(out / 'report.json', flush=True)


if __name__ == '__main__':
    main()
