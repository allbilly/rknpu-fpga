#!/usr/bin/env python3
"""Independent byte reconciliation and mapped cell recount, not equivalence."""
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
report_path = BASE / 'report.json'
report = json.loads(report_path.read_text())
assert report['status'] == 'PASS_YOSYS_XC7_MAPPING_SUBSYSTEM_ONLY' and report['returncode'] == 0
assert report['owned_process_group_stopped'] and not report['owned_process_group_live_pids_after']
assert report['all_frozen_inputs_unchanged'] and report['input_hashes_before'] == report['input_hashes_after']
for path, expected in report['input_hashes_before'].items():
    assert sha(path) == expected, path
for name, expected in report['output_hashes'].items():
    assert sha(BASE / name) == expected, name
assert sha(report['source_manifest_path']) == report['source_manifest_sha256']
manifest = json.loads(Path(report['source_manifest_path']).read_text())
assert manifest['copy_count'] == len(manifest['sources']) == 6
for row in manifest['sources']:
    assert sha(row['original_path']) == row['original_sha256'] == sha(row['copied_path']) == row['copied_sha256']
    assert Path(row['original_path']).stat().st_size == row['bytes'] == Path(row['copied_path']).stat().st_size
assert sha(report['mapping_script_path']) == report['mapping_script_sha256']
for stream in ('stdout', 'stderr'):
    path = BASE / ('yosys.' + stream + '.log')
    # The launcher records its actual stdout/stderr paths in the directory.
    if not path.exists():
        candidates = [p for p in BASE.glob('*' + stream + '*') if p.is_file()]
        assert len(candidates) == 1, (stream, candidates)
        path = candidates[0]
    assert sha(path) == report[stream + '_sha256']
netlist = json.loads((BASE / 'mapped.json').read_text())['modules']['rk_ddr_capacity_bist']
counts = Counter(cell['type'] for cell in netlist['cells'].values())
assert dict(sorted(counts.items())) == report['cell_type_counts']
allowed = {'$scopeinfo','BUFG','CARRY4','FDRE','FDSE','IBUF','OBUF','INV','MUXF7','MUXF8'} | {
    'LUT' + str(n) for n in range(1,7)}
assert not (counts.keys() - allowed), counts.keys() - allowed
lut = sum(counts['LUT' + str(n)] for n in range(1,7))
ff = counts['FDRE'] + counts['FDSE']
io = counts['IBUF'] + counts['OBUF']
metadata = counts['$scopeinfo']
physical = sum(counts.values()) - metadata
assert (lut, ff, io, metadata, physical) == (1642,1958,2692,5,7860)
result = {
    'status': 'PASS_ROOT_CAPACITY_SUBSYSTEM_MAPPED_INVENTORY_ONLY',
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'reviewer_sha256': sha(__file__), 'report_sha256': sha(report_path),
    'source_original_and_copy_pairs_verified': 6,
    'mapped_netlist_sha256': sha(BASE / 'mapped.json'),
    'core_lut': lut, 'core_ff': ff, 'core_dsp': 0, 'core_ram': 0,
    'io_cells': io, 'metadata_cells_excluded': metadata,
    'core_other_physical_cells': physical-lut-ff-io,
    'physical_cells': physical,
    'scope': 'Diagnostic subsystem mapping only; not functional equivalence or whole-design fit/timing',
    'physical_capacity_qualified': False, 'hardware_accessed': False,
}
with (BASE / 'root-review.json').open('x') as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write('\n')
print(json.dumps(result, sort_keys=True))
