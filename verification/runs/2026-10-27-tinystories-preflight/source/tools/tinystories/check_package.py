#!/usr/bin/env python3
"""Read-only producer check plus isolated corruption controls on a copied package."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

from tools.tinystories.prepare import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    package = args.package.resolve()
    report = verify(package)
    tests = []
    mutations = {
        'ai': lambda d: d['tiles'][0].update(ai=32),
        'compaction': lambda d: d['tiles'][0]['required_hardware_compaction'][1].update(source_halfword=16),
        'address': lambda d: d['tiles'][1].update(address=d['tiles'][0]['address']),
        'missing_tile': lambda d: d['tiles'].pop(),
        'duplicate_tile': lambda d: d['tiles'].append(d['tiles'][0]),
        'classifier_alias': lambda d: d['projections'][-1].update(source_offset=32),
        'host_cache': lambda d: d.update(host_kv_cache_fp32_bytes=327680),
        'overlap_buffer': lambda d: d['candidate_buffers']['linear_output'].update(address=0x10001000),
        'execution_claim': lambda d: d.update(hardware_accessed=True),
    }
    with tempfile.TemporaryDirectory(prefix='tinystories-copied-inputs-') as temporary:
        copy = Path(temporary)/'package'
        shutil.copytree(package, copy)
        spec = importlib.util.spec_from_file_location('copied_tinystories_preparer', copy/'source/prepare.py')
        isolated = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(isolated)
        isolated.verify(copy)
        tests.append(dict(name='isolated_copied_source', status='PASS'))
        original = (copy/'report.json').read_bytes()
        for name, mutate in mutations.items():
            changed = json.loads(original)
            mutate(changed)
            (copy/'report.json').write_text(json.dumps(changed))
            for verifier in (verify, isolated.verify):
                try:
                    verifier(copy)
                except (ValueError, FileNotFoundError):
                    pass
                else:
                    raise RuntimeError('Corrupted package accepted: '+name)
            tests.append(dict(name=name, status='PASS_REJECTED'))
            (copy/'report.json').write_bytes(original)
        weight = copy/report['tiles'][0]['file']
        raw = weight.read_bytes()
        weight.write_bytes(bytes([raw[0]^1])+raw[1:])
        try:
            verify(copy)
        except ValueError:
            tests.append(dict(name='weight_data', status='PASS_REJECTED'))
        else:
            raise RuntimeError('Corrupted constant weight accepted')
    verify(package)
    result = dict(status='PASS_TINYSTORIES_STATIC_PACKAGE_CONTROLS', tests=tests,
                  source_package=str(package), source_report_sha256=hashlib.sha256((package/'report.json').read_bytes()).hexdigest(),
                  scope='Static integrity/shape/packing admission only; no model execution, RTL or hardware', hardware_accessed=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    print(result['status'], len(tests))


if __name__ == '__main__':
    main()
