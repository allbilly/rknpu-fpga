#!/usr/bin/env python3
"""Verify portable saved evidence bytes; never program or execute a model."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import tarfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, default=Path(__file__).with_name('index.json'))
    args = parser.parse_args()
    index = json.loads(args.index.read_text())
    require(index['schema'] == 1, 'Unsupported evidence index')
    name = index['archive']['file']
    require(Path(name).name == name, 'Archive must be adjacent to the index')
    archive = args.index.parent / name
    require(archive.stat().st_size == index['archive']['bytes'], 'Archive size mismatch')
    with archive.open('rb') as stream:
        require(digest(stream) == index['archive']['sha256'], 'Archive SHA256 mismatch')
    review = index['independent_byte_review']
    require(Path(review['file']).name == review['file'], 'Review must be adjacent to index')
    with (args.index.parent / review['file']).open('rb') as stream:
        require(digest(stream) == review['sha256'], 'Independent review SHA256 mismatch')

    # Metadata is bound by the index before it supplies the member inventory.
    metadata = {}
    with tarfile.open(archive, 'r:gz') as tar:
        for name, expected in index['metadata'].items():
            member = tar.getmember(name)
            require(member.isfile(), 'Metadata must be a regular member')
            stream = tar.extractfile(member)
            require(stream is not None, 'Missing metadata stream')
            raw = stream.read()
            require(hashlib.sha256(raw).hexdigest() == expected, 'Metadata SHA256 mismatch')
            metadata[name] = json.loads(raw)
    selection = metadata['provenance/artifact-list.json']
    expected = {row['archive_path']: row for row in selection['payload_files']}
    require(len(expected) == len(selection['payload_files']) == index['payload_files'],
            'Duplicate or missing inventory entries')
    require(sum(row['source_bytes'] for row in expected.values()) == index['payload_bytes'],
            'Inventory byte total mismatch')
    require(len(selection['hash_only_exclusions']) == index['hash_only_exclusions'],
            'Hash-only exclusion count mismatch')
    require(selection['qualification_limits'] == index['qualification_limits'] and
            selection['credentials_or_lease_contents_included'] is False,
            'Evidence qualification/exclusion policy mismatch')
    allowed_metadata = set(index['metadata']) | {'provenance/archive-manifest.json'}
    seen = set()
    payload_count = payload_bytes = 0
    root_receipt = None
    with tarfile.open(archive, 'r|gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and
                    str(path) == member.name, 'Unsafe or noncanonical archive member')
            require(member.isfile() and member.name not in seen, 'Nonfile or duplicate member')
            seen.add(member.name)
            require(member.name in expected or member.name in allowed_metadata,
                    'Unselected archive member')
            if member.name in allowed_metadata:
                continue
            row = expected[member.name]
            require(member.size == row['source_bytes'], 'Payload size mismatch')
            stream = tar.extractfile(member)
            require(stream is not None, 'Missing payload stream')
            if member.name == index['root_receipt']['member']:
                raw = stream.read()
                actual = hashlib.sha256(raw).hexdigest()
                root_receipt = json.loads(raw)
                require(actual == index['root_receipt']['sha256'], 'Root receipt identity mismatch')
            else:
                actual = digest(stream)
            require(actual == row['source_sha256'], 'Payload SHA256 mismatch: ' + member.name)
            payload_count += 1
            payload_bytes += member.size
    require(seen == set(expected) | allowed_metadata, 'Missing selected archive members')
    require((payload_count, payload_bytes) == (index['payload_files'], index['payload_bytes']),
            'Payload count or byte total mismatch')
    require(root_receipt is not None and root_receipt['accepted'] is True and
            root_receipt['status'] == index['root_receipt']['status'] and
            root_receipt['bitstream_sha256'] == index['bitstream_sha256'],
            'Saved acceptance/image identity mismatch')
    require(root_receipt['forward_positions'] == index['full32']['positions'] and
            root_receipt['learned_fpga_projections'] == index['full32']['learned_fpga_projections'] and
            root_receipt['logit_values'] == index['full32']['logit_values'] and
            len(root_receipt['generated_token_ids']) == index['full32']['generated_token_count'] and
            root_receipt['jtag_scans'] == index['full32']['jtag_scans'] and
            root_receipt['complete_bo_bytes_before_ack'] == index['full32']['bo_bytes_before_ack'] and
            root_receipt['all_three_phase_totals'] == index['all_three_phases'] and
            root_receipt['cpu_host_operators'] == index['cpu_host_operators'] and
            root_receipt['flash_written'] is False,
            'Saved full32 scope mismatch')
    print(json.dumps({'status': 'PASS_PORTABLE_SAVED_EVIDENCE_BYTES',
                      'payload_files': payload_count, 'payload_bytes': payload_bytes,
                      'hardware_accessed': False, 'model_executed': False}, sort_keys=True))


if __name__ == '__main__':
    main()
