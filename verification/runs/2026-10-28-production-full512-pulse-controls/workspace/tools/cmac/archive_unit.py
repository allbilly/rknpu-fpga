#!/usr/bin/env python3
"""Freeze completed sized-CMAC unit reports and their exact dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, timestamp

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--name', required=True)
p.add_argument('reports', nargs='+', type=Path)
a = p.parse_args()
assert re.fullmatch(r'[a-zA-Z0-9_-]+', a.name)
members, visited, statuses = {}, set(), {}
def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
def add(path):
    path = path.resolve()
    if path.is_relative_to(ROOT):
        name = str(path.relative_to(ROOT))
    else:
        assert path.is_relative_to('/home/fedora/hw'), path
        name = 'donor/hw/' + str(path.relative_to('/home/fedora/hw'))
    members[name] = path
def check(name, sha):
    path = (ROOT / name).resolve()
    assert path.is_file() and digest(path) == sha, name
    add(path)
    if path.suffix == '.json' and path not in visited:
        visited.add(path)
        verify(json.loads(path.read_text()))
def verify(value):
    if isinstance(value, dict):
        files = value.get('files')
        if isinstance(files, dict) and all(isinstance(v, str) and re.fullmatch('[0-9a-f]{64}', v) for v in files.values()):
            for name, sha in files.items():
                check(name, sha)
        if 'external_source' in value:
            for name, sha in value['external_source'].items():
                check(name, sha)
        if 'donor_header' in value:
            check(value['donor_header'], value['donor_header_sha256'])
        for v in value.values():
            verify(v)
    elif isinstance(value, list):
        for v in value:
            verify(v)
allowed = {'PASS_PARALLEL_SIZED_CMAC_NATIVE_ONLY', 'PASS_CMAC_STREAM_NATIVE_ONLY',
           'PASS_ORIGINAL_NVDLA_MAC_CELL_ARITHMETIC', 'PASS_ORIGINAL_NVDLA_MAC_RTL_ONLY',
           'PASS_PARALLEL_CACC_NATIVE_ONLY', 'PASS_CMAC_CACC_NATIVE_ONLY',
           'PASS_OC16_FRAME_OUTPUT_NATIVE_ONLY', 'PASS_RAW_ARRAY_FRONT_NATIVE_ONLY',
           'PASS_ARRAY_DATAPATH_SMOKE_ONLY', 'PASS_ARRAY_DATAPATH_FULL_ONLY',
           'PASS_CMAC_RW_ARBITER_NATIVE_ONLY', 'PASS_RAW_CORE_CMAC_REFERENCE_ONLY',
           'PASS_RAW_ARRAY_CORE_SMOKE_ONLY', 'PASS_RAW_ARRAY_CORE_FULL_ONLY',
           'PASS_RAW_ARRAY_CORE_REPLAY_PROTOCOL_ONLY', 'PASS_RAW_ARRAY_CORE_REPLAY_FINITE_ONLY',
           'PASS_RAW_ARRAY_CORE_REPLAY_FULL_ONLY', 'PASS_PARALLEL_CMAC_XC7_MAPPING_ONLY',
           'PASS_RAW_ARRAY_DMA_PROTOCOL_ONLY', 'PASS_RAW_ARRAY_DMA_SMOKE_ONLY', 'PASS_RAW_ARRAY_DMA_FULL_ONLY',
           'PASS_RAW_ARRAY_DMA_REPLAY_PROTOCOL_ONLY', 'PASS_RAW_ARRAY_DMA_REPLAY_FINITE_ONLY', 'PASS_RAW_ARRAY_DMA_REPLAY_FULL_ONLY',
           'PASS_RAW_ARRAY_AXI_PROTOCOL_ONLY', 'PASS_RAW_ARRAY_AXI_SMOKE_ONLY', 'PASS_RAW_ARRAY_AXI_FULL_ONLY',
           'PASS_RAW_ARRAY_BOARD_SMOKE_RTL_ONLY', 'PASS_RAW_ARRAY_BOARD_FULL_RTL_ONLY',
           'PASS_ARRAY_BUILD_CONTROL_MOCKS_ONLY', 'PASS_HIERARCHY_TOOL_PROBE_ONLY',
           'PASS_EXPLICIT_HIERARCHICAL_CMAC_NATIVE_ONLY',
           'PASS_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_ONLY', 'PASS_FIXED_FP16_ROW_AREA_ONLY'}
allowed.add('PASS_RAW_ARRAY_AXI_FULL_HIERARCHICAL_ONLY')
allowed.update({'PASS_FIXED_FP16_ROWS_EXPERIMENT_ONLY',
                'PASS_FIXED_MODE_CMAC_NATIVE_EXPERIMENT_ONLY',
                'PASS_FIXED_CMAC_XC7_AREA_EXPERIMENT_ONLY',
                'PASS_FIXED_RAW_ARRAY_BOARD_TWO_STATE_HIERARCHICAL_EXPERIMENT_ONLY',
                'PASS_FIXED_RAW_ARRAY_BOARD_FOUR_STATE_RTL_EXPERIMENT_ONLY',
                'PASS_FIXED_BOARD_CONTRACT_CONTROLS_ONLY',
                'PASS_FIXED_ARRAY_BUILD_CONTROL_MOCKS_ONLY',
                'PASS_BITSTREAM_EMITTER_CONTROL_MOCKS_ONLY',
                'PASS_MAPPED_FIXED_FP16_ROWS_BINARY_FORMAL_ONLY',
                'PASS_FIXED_RAW_BOARD_PARTITIONED_XC7_AREA_ONLY',
                'PASS_ACTUAL_FIXED_PARTITION_IMPORT_BOUNDARY_ONLY'})
allowed.add('PREPARED_SHARED_CONE_BOARD_NETLIST_ONLY')
allowed.update({'PREPARED_LUT6_2_BOARD_CANDIDATE_ONLY',
                'PASS_LUT_PAIR_UNISIM_FUNCTION_CLASSES_ONLY'})
for path in a.reports:
    path = path.resolve()
    report = json.loads(path.read_text())
    assert report['status'] in allowed, (path, report['status'])
    assert all(c['status'] == 'PASS' for c in report.get('commands', [])), path
    statuses[str(path.relative_to(ROOT))] = report['status']
    add(path)
    visited.add(path)
    verify(report)
license_paths = [Path(__file__), ROOT / 'LICENSE', ROOT / 'rtl/vendor/nvdla/LICENSE']
# Bundled donor RTL carries its own pinned license. An external checkout is
# needed only when this report actually depends on source from that checkout;
# required external source hashes above still fail if anything is missing.
if any(name.startswith('donor/hw/') for name in members):
    license_paths.append(Path('/home/fedora/hw/LICENSE'))
for path in license_paths:
    add(path)
before = {name: digest(path) for name, path in members.items()}
dest = ROOT / 'verification/runs' / a.name
dest.mkdir(exist_ok=False)
archive = dest / 'evidence.tar.gz'
with tarfile.open(archive, 'x:gz') as tar:
    for name, path in sorted(members.items()):
        tar.add(path, arcname=name, recursive=False)
with tarfile.open(archive) as tar:
    assert len(tar.getmembers()) == len(members)
    for member in tar.getmembers():
        assert member.isfile() and hashlib.sha256(tar.extractfile(member).read()).hexdigest() == before[member.name]
assert all(digest(path) == before[name] for name, path in members.items())
sha = digest(archive)
index = dict(status='PASS_SOURCE_BOUND_UNIT_ARCHIVE', archived_utc=timestamp(), reports=statuses,
             archive=str(archive.relative_to(ROOT)), archive_sha256=sha, archive_bytes=archive.stat().st_size,
             verified_members=len(members), member_sha256=before,
             scope='Only the listed completed reports and configurations. Not upstream UTB, unlisted configurations, physical FPGA, or RK silicon.')
(dest / 'index.json').write_text(json.dumps(index, indent=2) + '\n')
(dest / 'archive_SHA256SUMS').write_text(f'{sha}  evidence.tar.gz\n')
print(json.dumps({k: index[k] for k in ('status', 'archive_sha256', 'archive_bytes', 'verified_members')}))
