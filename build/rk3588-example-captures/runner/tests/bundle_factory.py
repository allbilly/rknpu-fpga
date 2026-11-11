"""Synthetic capture bundles for host-only runner tests."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any


DEFAULT_CASE = "tiny_case"
DEFAULT_QWORDS = 22


def default_regcmd(qwords: int = DEFAULT_QWORDS) -> bytes:
    """Plausible PC command QWORDs with stable, patchable placeholders."""
    rows = []
    for index in range(qwords):
        # Target id in bits 63:48, register offset in bits 15:0, payload between.
        rows.append((0x0201 << 48) | (index << 16) | index)
    return b"".join(struct.pack("<Q", row) for row in rows)


def default_job(case_name: str = DEFAULT_CASE, qwords: int = DEFAULT_QWORDS) -> dict[str, Any]:
    return {
        "case": case_name,
        "source_example": "/home/fedora/rk3588/examples/conv_simple.py",
        "description": "synthetic host-only bundle",
        "timeout_ns": 1_000_000,
        "tasks": [{"regcmd_offset_words": 0, "regcmd_words": qwords}],
        "buffers": [
            {"name": "a", "size": 32, "input": "a.bin", "direction": "in"},
            {"name": "out", "size": 32, "direction": "out", "output": "out.bin"},
        ],
        "patches": [
            {"regcmd_index": 14, "buffer": "out", "kind": "value32"},
        ],
    }


def write_job(case_dir: Path, job: dict[str, Any]) -> None:
    (case_dir / "job.json").write_text(
        json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def make_case(
    parent: Path,
    *,
    case_name: str = DEFAULT_CASE,
    job: dict[str, Any] | None = None,
    qwords: int = DEFAULT_QWORDS,
    regcmd: bytes | None = None,
    inputs: dict[str, bytes] | None = None,
    directory_name: str | None = None,
) -> Path:
    case_dir = parent / (directory_name or case_name)
    case_dir.mkdir(parents=True)
    (case_dir / "regcmd.bin").write_bytes(
        default_regcmd(qwords) if regcmd is None else regcmd
    )
    for name, data in (inputs or {"a.bin": bytes(range(32))}).items():
        path = case_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write_job(case_dir, default_job(case_name, qwords) if job is None else job)
    return case_dir
