#!/usr/bin/env python3
"""Verify a source/input tar handoff without extracting or importing it."""
import hashlib,json,tarfile
from pathlib import Path,PurePosixPath
BASE=Path(__file__).resolve().parent
def fail(msg): raise SystemExit('VERIFY_FAIL: '+msg)
def sha(b): return hashlib.sha256(b).hexdigest()
data=json.loads((BASE/'index.json').read_text())
archive=BASE/data['archive_path']
if sha(archive.read_bytes())!=data['archive_sha256']: fail('archive SHA256 mismatch')
if archive.stat().st_size!=data['archive_size']: fail('archive size mismatch')
expected={row['path']:row for row in data['members']}
if len(expected)!=data['member_count']: fail('duplicate paths in index')
seen=set()
try:
 with tarfile.open(archive,'r:gz') as tf:
  for member in tf.getmembers():
   name=member.name; path=PurePosixPath(name)
   if path.is_absolute() or any(part in ('','..','.') for part in name.split('/')) or '\\' in name: fail('unsafe archive path '+repr(name))
   if name in seen: fail('duplicate archive member '+name)
   seen.add(name)
   if name not in expected: fail('unindexed archive member '+name)
   if not member.isfile(): fail('non-regular archive member '+name)
   if member.size!=expected[name]['size']: fail('member size mismatch '+name)
   stream=tf.extractfile(member)
   if stream is None: fail('unreadable archive member '+name)
   payload=stream.read()
   if len(payload)!=member.size or sha(payload)!=expected[name]['sha256']: fail('member SHA256 mismatch '+name)
   if name.endswith(('.pyc','.o','.a','.gch','.so','.elf','.dcp','.bit')): fail('forbidden generated/binary artifact '+name)
   if name.endswith('.bin') and Path(name).name not in ('program.bin','a.bin','b.bin','output-before.bin'): fail('unexpected binary payload '+name)
except (tarfile.TarError,OSError,EOFError) as exc: fail('archive parse error '+repr(exc))
if seen!=set(expected): fail('archive member census mismatch')
if len(seen)!=data['member_count']: fail('member count mismatch')
print('PASS_PORTABLE_ARCHIVE_HASHES_AND_SAFE_MEMBERS',len(seen))
