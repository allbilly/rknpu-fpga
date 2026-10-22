#!/usr/bin/env python3
"""Check raw-core C32 group goldens against the executed original MAC class."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence import ROOT, fingerprint, timestamp

def verify(manifest):
    for name, sha in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name

base = ROOT / 'build/rknpu-array-core-vectors'
vr_path = base / 'vectors_report.json'
vr = json.loads(vr_path.read_text())
verify(vr['source']); verify(vr['artifacts'])
donor_report = ROOT / 'build/rknpu-cmac-array/c32k16/nvdla-mac-cell-1789989595701148341/report.json'
donor = json.loads(donor_report.read_text())
assert donor['status'] == 'PASS_ORIGINAL_NVDLA_MAC_CELL_ARITHMETIC'
verify(donor['source']); verify(donor['artifacts'])
assert hashlib.sha256(Path(donor['donor_header']).read_bytes()).hexdigest() == donor['donor_header_sha256']
binary = donor_report.parent / 'model'
assert str(binary.relative_to(ROOT)) in donor['artifacts']['files']
out = ROOT / f'build/rknpu-array-core/model-{time.time_ns()}'
out.mkdir(parents=True, exist_ok=False)
tracked = [Path(__file__).resolve(), vr_path, donor_report]
report = dict(status='RUNNING', started_utc=timestamp(), source=fingerprint(tracked), vectors=vr,
              donor_reference=donor, commands=[],
              scope='Original complete NvdlaMacCell arithmetic class, reusing the source-pinned SystemC executable. Verifies C32 raw-core CMAC goldens only, not CACC/output integration, RTL, upstream UTB or RK silicon.')
def save():
    (out / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
save()
try:
    requests, expected, coordinates = [], [], []
    for case in vr['cases']:
        directory = base / case['name']
        inputs = [int(line, 16) for line in (directory / 'input.hex').read_text().splitlines()]
        weights = [int(line, 16) for line in (directory / 'weight.hex').read_text().splitlines()]
        goldens = [int(line, 16) for line in (directory / 'groups.hex').read_text().splitlines()]
        expected += goldens
        for row in range(case['rows']):
            for oc in range(0, case['ao'], 16):
                for ic in range(0, case['ai'], 32):
                    for kernel in range(16):
                        index = oc*case['ai'] + ic*16 + kernel*32
                        values = [32, 0xffffffff, 0xffffffff] + inputs[row*case['ai']+ic:row*case['ai']+ic+32] + weights[index:index+32]
                        assert len(values) == 67
                        requests.append(' '.join(map(str, values))+'\n')
                        coordinates.append(dict(case=case['name'], row=row, oc=oc+kernel, ic=ic))
    started = time.monotonic()
    result = subprocess.run([binary], input=''.join(requests), capture_output=True, text=True, timeout=300)
    (out / 'run.log').write_text(result.stdout+result.stderr)
    report['commands'].append(dict(argv=[str(binary)], status='PASS' if result.returncode == 0 else 'FAIL',
                                   returncode=result.returncode, seconds=round(time.monotonic()-started, 3),
                                   log=str((out / 'run.log').relative_to(ROOT))))
    assert result.returncode == 0, result.stderr
    actual = list(map(int, result.stdout.split()))
    assert len(actual) == len(expected) == sum(case['frames']*16 for case in vr['cases'])
    mismatches = [dict(**coordinates[i], nvdla=f'{got:011x}', expected=f'{want:011x}')
                  for i, (got, want) in enumerate(zip(actual, expected)) if got != want]
    report.update(compared_outputs=len(actual), mismatches=mismatches[:32], mismatch_count=len(mismatches))
    assert not mismatches, mismatches[:8]
    assert fingerprint(tracked) == report['source']
    verify(vr['source']); verify(vr['artifacts']); verify(donor['source']); verify(donor['artifacts'])
    report.update(status='PASS_RAW_CORE_CMAC_REFERENCE_ONLY', artifacts=fingerprint([out / 'run.log']))
except Exception as exc:
    report.update(status='FAIL', reason=str(exc))
    raise
finally:
    report['finished_utc'] = timestamp(); save(); print(out / 'report.json')
print(report['status'], report['compared_outputs'])
