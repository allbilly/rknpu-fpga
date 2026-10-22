"""Content-addressed provenance for local checks, including unpacked source trees."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(paths: list[Path]) -> dict:
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(set(paths))}
    manifest = ''.join(f'{digest}  {name}\n' for name, digest in files.items())
    return {'sha256': hashlib.sha256(manifest.encode()).hexdigest(), 'files': files}


def source_revision() -> dict:
    paths = [ROOT / 'Makefile']
    for directory, patterns in {'rtl': ['*.sv'], 'fpga': ['*.sv', '*.xdc', '*.tcl'],
                                'model': ['*.py', '*.cpp'], 'tools': ['*.py'],
                                'tests': ['*.py', '*.sv', '*.svh', '*.json']}.items():
        for pattern in patterns:
            paths.extend((ROOT / directory).glob(pattern))
    paths.extend(p for p in (ROOT / 'tests/vendor').rglob('*') if p.is_file())
    result = fingerprint(paths)
    git = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                         text=True, capture_output=True, check=False)
    result['git_commit'] = git.stdout.strip() if git.returncode == 0 else None
    result['identity'] = 'SHA256 of the listed source manifest; includes uncommitted edits'
    return result
