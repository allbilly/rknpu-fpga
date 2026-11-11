#!/usr/bin/env python3
"""Self-contained mainline Rocket UAPI runner for prepared capture bundles.

This program is the board-side half of the RK3588 capture queue.  It does not
contain a numerical model, does not use NumPy, and does not reset or reprogram
the NPU.  For every case directory it:

  * loads job.json, regcmd.bin and all declared input files;
  * validates the bundle against the CAPTURE_FORMAT.md schema;
  * creates one DRM Rocket BO per named buffer plus one BO for regcmd.bin;
  * copies inputs, patches command QWORDs from the actual DMA addresses, and
    builds the Rocket task descriptor array;
  * preps/finis BOs for CPU ownership, submits exactly one job and waits by
    prepping the output BOs;
  * reads back every out/inout BO and writes the requested output files;
  * writes capture.json with addresses, sizes, durations, hashes, submit_ret,
    device identity, tool version and every error.

A failure is recorded for that case and the next case is attempted.  Output
files are never synthesized: only bytes read back from the device are written.

The pure parsing, validation, patching and descriptor-building functions in
this module are importable on a host without a device.  Importing the module
does not open a file descriptor.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as _datetime
import errno
import fcntl
import hashlib
import json
import mmap
import os
import platform
import socket
import stat
import struct
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

__version__ = "1.0.0"

CAPTURE_SCHEMA = "rk3588-rocket-capture-v1"
JOB_SCHEMA_FIELDS = frozenset(
    {"case", "source_example", "description", "timeout_ns", "tasks", "buffers", "patches"}
)
TASK_FIELDS = frozenset({"regcmd_offset_words", "regcmd_words"})
BUFFER_FIELDS = frozenset({"name", "size", "input", "direction", "output"})
PATCH_FIELDS = frozenset({"regcmd_index", "buffer", "kind"})
DIRECTIONS = frozenset({"in", "out", "inout"})
PATCH_MASKS = {
    # value32 replaces command bits [47:16] with the 32-bit DMA address.
    "value32": 0x0000FFFFFFFF0000,
    # all32 replaces command bits [31:0].
    "all32": 0x00000000FFFFFFFF,
    # low32 replaces only the low 32 bits of the QWORD.
    "low32": 0x00000000FFFFFFFF,
    # high32 replaces only the high 32 bits of the QWORD.
    "high32": 0xFFFFFFFF00000000,
}
PATCH_KINDS = frozenset(PATCH_MASKS)
RESERVED_OUTPUT_NAMES = frozenset({"capture.json"})

# Mainline drivers/accel/rocket/rocket_job.c:
# ROCKET_MAX_REGCMDS = (PC_REGISTER_AMOUNTS_PC_DATA_AMOUNT__MASK + 1) * 2
# with a 16-bit PC_DATA_AMOUNT field.
MAX_REGCMDS = 131072
TASK_ALIGNMENT = 16
U32_MAX = 0xFFFFFFFF
U64_MAX = 0xFFFFFFFFFFFFFFFF
S64_MAX = 0x7FFFFFFFFFFFFFFF

# DRM UAPI.  struct sizes are asserted below.
DRM_IOCTL_BASE = ord("d")
DRM_COMMAND_BASE = 0x40
DRM_ROCKET_CREATE_BO = 0x00
DRM_ROCKET_SUBMIT = 0x01
DRM_ROCKET_PREP_BO = 0x02
DRM_ROCKET_FINI_BO = 0x03
DRM_GEM_CLOSE = 0x09
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, type_: int, nr: int, size: int) -> int:
    return (
        (direction << 30)
        | (size << 16)
        | (type_ << 8)
        | nr
    )


def _iow(type_: int, nr: int, size: int) -> int:
    return _ioc(_IOC_WRITE, type_, nr, size)


def _iowr(type_: int, nr: int, size: int) -> int:
    return _ioc(_IOC_WRITE | _IOC_READ, type_, nr, size)


# Packed layouts are given explicitly so the host tests can assert them.
CREATE_BO_SIZE = 24
PREP_BO_SIZE = 16
FINI_BO_SIZE = 8
TASK_SIZE = 8
JOB_SIZE = 40
SUBMIT_SIZE = 24
GEM_CLOSE_SIZE = 8

DRM_IOCTL_ROCKET_CREATE_BO = _iowr(
    DRM_IOCTL_BASE, DRM_COMMAND_BASE + DRM_ROCKET_CREATE_BO, CREATE_BO_SIZE
)
DRM_IOCTL_ROCKET_SUBMIT = _iow(
    DRM_IOCTL_BASE, DRM_COMMAND_BASE + DRM_ROCKET_SUBMIT, SUBMIT_SIZE
)
DRM_IOCTL_ROCKET_PREP_BO = _iow(
    DRM_IOCTL_BASE, DRM_COMMAND_BASE + DRM_ROCKET_PREP_BO, PREP_BO_SIZE
)
DRM_IOCTL_ROCKET_FINI_BO = _iow(
    DRM_IOCTL_BASE, DRM_COMMAND_BASE + DRM_ROCKET_FINI_BO, FINI_BO_SIZE
)
DRM_IOCTL_GEM_CLOSE = _iow(DRM_IOCTL_BASE, DRM_GEM_CLOSE, GEM_CLOSE_SIZE)

assert struct.calcsize("<IIQQ") == CREATE_BO_SIZE
assert struct.calcsize("<IIq") == PREP_BO_SIZE
assert struct.calcsize("<II") == FINI_BO_SIZE
assert struct.calcsize("<II") == TASK_SIZE
assert struct.calcsize("<QQQIIII") == JOB_SIZE
assert struct.calcsize("<QIIQ") == SUBMIT_SIZE
assert struct.calcsize("<II") == GEM_CLOSE_SIZE


class CaseError(ValueError):
    """A prepared bundle or a runtime contract was rejected."""


class PatchError(CaseError):
    """A patch cannot be applied without truncating or corrupting an address."""


class DescriptorError(CaseError):
    """A Rocket task descriptor is out of range or misaligned."""


# ---------------------------------------------------------------------------
# Strict JSON and small value helpers


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CaseError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise CaseError(f"non-standard JSON constant {value!r} is not allowed")


def read_json_strict(path: Path) -> Any:
    """Read JSON, rejecting duplicate object keys and malformed UTF-8/JSON."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CaseError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except CaseError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise CaseError(f"invalid JSON in {path}: {exc}") from exc


def _is_int(value: Any) -> bool:
    # bool is a subclass of int but is not a valid JSON integer here.
    return type(value) is int


def _brief(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _check_keys(
    obj: Any,
    allowed: frozenset[str],
    required: frozenset[str],
    where: str,
    errors: list[str],
) -> bool:
    if not isinstance(obj, dict):
        errors.append(f"{where}: expected a JSON object, got {_brief(obj)}")
        return False
    unknown = sorted(set(obj) - allowed)
    missing = sorted(required - set(obj))
    if unknown:
        errors.append(f"{where}: unknown field(s): {', '.join(unknown)}")
    if missing:
        errors.append(f"{where}: missing field(s): {', '.join(missing)}")
    return not unknown and not missing


def _string(value: Any, where: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{where}: expected a non-empty string, got {_brief(value)}")
        return None
    if "\x00" in value:
        errors.append(f"{where}: NUL is not allowed")
        return None
    return value


def _integer(
    value: Any,
    where: str,
    errors: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if not _is_int(value):
        errors.append(f"{where}: expected an integer, got {_brief(value)}")
        return None
    if minimum is not None and value < minimum:
        errors.append(f"{where}: {value} is below the minimum {minimum}")
        return None
    if maximum is not None and value > maximum:
        errors.append(f"{where}: {value} is above the maximum {maximum}")
        return None
    return value


def _case_component(value: Any, where: str, errors: list[str]) -> str | None:
    name = _string(value, where, errors)
    if name is None:
        return None
    if "/" in name or "\\" in name or name in (".", ".."):
        errors.append(f"{where}: {name!r} is not a safe case directory component")
        return None
    if any(ord(ch) < 0x20 for ch in name):
        errors.append(f"{where}: control characters are not allowed")
        return None
    return name


def _relative_file(value: Any, where: str, errors: list[str]) -> str | None:
    name = _string(value, where, errors)
    if name is None:
        return None
    if name.startswith("/"):
        errors.append(f"{where}: {name!r} must be relative to the case directory")
        return None
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        errors.append(f"{where}: {name!r} must not contain empty, '.' or '..' components")
        return None
    return name


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Parsed bundle and pure validation


@dataclass(frozen=True)
class TaskSpec:
    regcmd_offset_words: int
    regcmd_words: int


@dataclass(frozen=True)
class BufferSpec:
    name: str
    size: int
    direction: str
    input_name: str | None = None
    output_name: str | None = None
    input_path: Path | None = None
    input_data: bytes | None = None
    input_sha256: str | None = None


@dataclass(frozen=True)
class PatchSpec:
    regcmd_index: int
    buffer: str
    kind: str


@dataclass(frozen=True)
class TaskDescriptor:
    regcmd: int
    regcmd_count: int
    regcmd_offset_words: int


@dataclass(frozen=True)
class CaseBundle:
    case_dir: Path
    job_path: Path
    job_sha256: str
    job: dict[str, Any]
    case: str
    source_example: str
    description: str
    timeout_ns: int
    tasks: tuple[TaskSpec, ...]
    buffers: tuple[BufferSpec, ...]
    patches: tuple[PatchSpec, ...]
    regcmd: bytes
    regcmd_sha256: str

    @property
    def regcmd_words(self) -> int:
        return len(self.regcmd) // 8


def _validate_tasks(
    raw: Any, regcmd_words: int | None, errors: list[str]
) -> tuple[TaskSpec, ...]:
    if not isinstance(raw, list):
        errors.append("job.json tasks: expected a non-empty array")
        return ()
    if not raw:
        errors.append("job.json tasks: at least one task is required")
        return ()

    tasks: list[TaskSpec] = []
    intervals: list[tuple[int, int, int, int]] = []
    for index, item in enumerate(raw):
        where = f"job.json tasks[{index}]"
        if not _check_keys(item, TASK_FIELDS, TASK_FIELDS, where, errors):
            continue
        offset = _integer(
            item.get("regcmd_offset_words"), f"{where}.regcmd_offset_words", errors, minimum=0
        )
        words = _integer(
            item.get("regcmd_words"),
            f"{where}.regcmd_words",
            errors,
            minimum=1,
            maximum=MAX_REGCMDS,
        )
        if offset is None or words is None:
            continue
        if offset % (TASK_ALIGNMENT // 8) != 0:
            errors.append(
                f"{where}.regcmd_offset_words: {offset} would put the task at a "
                f"{8 * offset:#x}-byte offset, not {TASK_ALIGNMENT}-byte aligned"
            )
            continue
        fetched_words = regcmd_fetch_words(words)
        if regcmd_words is not None:
            end = offset + fetched_words
            if end > regcmd_words:
                errors.append(
                    f"{where}: declared words [{offset}, {offset + words}) fetch as "
                    f"QWORD pairs [{offset}, {end}), which exceed regcmd.bin's "
                    f"{regcmd_words} QWORDs"
                )
                continue
            intervals.append((offset, end, index, words))
        tasks.append(TaskSpec(offset, words))

    ordered = sorted(intervals)
    for (start_a, end_a, index_a, words_a), (start_b, end_b, index_b, words_b) in zip(
        ordered, ordered[1:]
    ):
        if start_b < end_a:
            errors.append(
                f"job.json tasks[{index_a}] and tasks[{index_b}] overlap in the "
                f"QWORD-pair fetch range ([{start_a}, {end_a}) from {words_a} words and "
                f"[{start_b}, {end_b}) from {words_b} words)"
            )
    return tuple(tasks)


def regcmd_fetch_words(regcmd_words: int) -> int:
    """Number of QWORDs the Rocket PC fetches for a declared count.

    The register field is expressed as pairs: ``(count + 1) / 2`` units, so an
    odd count fetches one extra QWORD.  The source count stays odd in the UAPI
    descriptor; this helper is used to validate the real fetch extent.
    """
    if not _is_int(regcmd_words) or regcmd_words < 1:
        raise CaseError(f"invalid regcmd word count {regcmd_words!r}")
    return regcmd_words + (regcmd_words & 1)


def _validate_buffers(
    case_dir: Path, raw: Any, errors: list[str]
) -> tuple[BufferSpec, ...]:
    if not isinstance(raw, list):
        errors.append("job.json buffers: expected a non-empty array")
        return ()
    if not raw:
        errors.append("job.json buffers: at least one buffer is required")
        return ()

    buffers: list[BufferSpec] = []
    names: set[str] = set()
    output_files: dict[str, int] = {}
    has_output_direction = False

    for index, item in enumerate(raw):
        where = f"job.json buffers[{index}]"
        if not _check_keys(
            item, BUFFER_FIELDS, frozenset({"name", "size", "direction"}), where, errors
        ):
            continue

        name = _string(item.get("name"), f"{where}.name", errors)
        if name is not None:
            if name in names:
                errors.append(f"{where}.name: duplicate buffer name {name!r}")
                name = None
            else:
                names.add(name)

        size = _integer(
            item.get("size"), f"{where}.size", errors, minimum=1, maximum=U32_MAX
        )
        direction = item.get("direction")
        if not isinstance(direction, str) or direction not in DIRECTIONS:
            errors.append(
                f"{where}.direction: expected one of {sorted(DIRECTIONS)}, "
                f"got {_brief(direction)}"
            )
            direction = None
        if direction in ("out", "inout"):
            has_output_direction = True

        input_name = item.get("input")
        output_name = item.get("output")
        if direction in ("in", "inout"):
            if "input" not in item:
                errors.append(f"{where}: direction {direction!r} requires an input file")
                input_name = None
        elif direction is not None and "input" in item:
            errors.append(f"{where}: direction {direction!r} must not have an input file")
            input_name = None
        if direction in ("out", "inout"):
            if "output" not in item:
                errors.append(f"{where}: direction {direction!r} requires an output file")
                output_name = None
        elif direction is not None and "output" in item:
            errors.append(f"{where}: direction {direction!r} must not have an output file")
            output_name = None

        input_rel = None
        input_path = None
        input_data = None
        input_hash = None
        if input_name is not None:
            input_rel = _relative_file(input_name, f"{where}.input", errors)
            if input_rel is not None and size is not None:
                input_path = case_dir / input_rel
                try:
                    info = input_path.stat()
                except OSError as exc:
                    errors.append(f"{where}.input: cannot stat {input_path}: {exc}")
                else:
                    if not stat.S_ISREG(info.st_mode):
                        errors.append(f"{where}.input: {input_path} is not a regular file")
                    else:
                        try:
                            resolved_input = input_path.resolve(strict=True)
                            resolved_case = case_dir.resolve(strict=True)
                        except OSError as exc:
                            errors.append(f"{where}.input: cannot resolve {input_path}: {exc}")
                        else:
                            if resolved_case not in resolved_input.parents:
                                errors.append(
                                    f"{where}.input: {input_path} resolves outside the "
                                    f"case directory to {resolved_input}"
                                )
                            elif info.st_size != size:
                                errors.append(
                                    f"{where}.input: {input_path} is {info.st_size} bytes, "
                                    f"but buffers[{index}].size is {size}"
                                )
                            else:
                                try:
                                    data = input_path.read_bytes()
                                except OSError as exc:
                                    errors.append(f"{where}.input: cannot read {input_path}: {exc}")
                                else:
                                    if len(data) != size:
                                        errors.append(
                                            f"{where}.input: {input_path} changed size while reading "
                                            f"({len(data)} != {size})"
                                        )
                                    else:
                                        input_data = data
                                        input_hash = _sha256(data)

        output_rel = None
        if output_name is not None:
            output_rel = _relative_file(output_name, f"{where}.output", errors)
            if output_rel is not None:
                first = output_rel.split("/", 1)[0]
                if output_rel in RESERVED_OUTPUT_NAMES or first in RESERVED_OUTPUT_NAMES:
                    errors.append(
                        f"{where}.output: {output_rel!r} is reserved for capture.json "
                        "or is a parent path of it"
                    )
                elif output_rel in output_files:
                    errors.append(
                        f"{where}.output: duplicate output filename {output_rel!r} "
                        f"(also buffers[{output_files[output_rel]}])"
                    )
                else:
                    output_files[output_rel] = index

        if name is not None and size is not None and direction is not None:
            buffers.append(
                BufferSpec(
                    name=name,
                    size=size,
                    direction=direction,
                    input_name=input_rel,
                    output_name=output_rel,
                    input_path=input_path,
                    input_data=input_data,
                    input_sha256=input_hash,
                )
            )

    if not has_output_direction:
        errors.append(
            "job.json buffers: at least one buffer must have direction 'out' or 'inout' "
            "so the runner can wait for completion and read a device result"
        )

    # An output file cannot also be a directory used by another output path.
    output_names = sorted(output_files)
    for pos, left in enumerate(output_names):
        left_parts = left.split("/")
        for right in output_names[pos + 1 :]:
            right_parts = right.split("/")
            if left_parts == right_parts[: len(left_parts)]:
                errors.append(
                    f"job.json buffers[{output_files[left]}].output: {left!r} is a "
                    f"parent path of buffers[{output_files[right]}].output {right!r}"
                )
    return tuple(buffers)


def _validate_patches(
    raw: Any,
    regcmd_words: int | None,
    buffer_names: set[str],
    errors: list[str],
) -> tuple[PatchSpec, ...]:
    if not isinstance(raw, list):
        errors.append("job.json patches: expected an array")
        return ()

    patches: list[PatchSpec] = []
    masks_by_index: dict[int, int] = {}
    for index, item in enumerate(raw):
        where = f"job.json patches[{index}]"
        if not _check_keys(item, PATCH_FIELDS, PATCH_FIELDS, where, errors):
            continue
        regcmd_index = _integer(
            item.get("regcmd_index"), f"{where}.regcmd_index", errors, minimum=0
        )
        if regcmd_index is not None and regcmd_words is not None:
            if regcmd_index >= regcmd_words:
                errors.append(
                    f"{where}.regcmd_index: {regcmd_index} is outside regcmd.bin's "
                    f"{regcmd_words} QWORDs"
                )
                regcmd_index = None
        buffer_name = _string(item.get("buffer"), f"{where}.buffer", errors)
        if buffer_name is not None and buffer_name not in buffer_names:
            errors.append(f"{where}.buffer: unknown buffer {buffer_name!r}")
            buffer_name = None
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in PATCH_KINDS:
            errors.append(
                f"{where}.kind: expected one of {sorted(PATCH_KINDS)}, got {_brief(kind)}"
            )
            kind = None
        if regcmd_index is None or buffer_name is None or kind is None:
            continue
        mask = PATCH_MASKS[kind]
        previous = masks_by_index.get(regcmd_index, 0)
        if previous & mask:
            errors.append(
                f"{where}: patch {kind!r} overlaps an earlier patch on "
                f"regcmd_index {regcmd_index}"
            )
            continue
        masks_by_index[regcmd_index] = previous | mask
        patches.append(PatchSpec(regcmd_index, buffer_name, kind))
    return tuple(patches)


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def check_output_paths(bundle: CaseBundle, output_root: Path | str) -> list[str]:
    """Check that a runner output tree would not overwrite anything."""
    errors: list[str] = []
    root = Path(output_root)
    case_out = root / bundle.case
    if _lexists(root) and not root.is_dir():
        errors.append(f"output root exists but is not a directory: {root}")
    try:
        root_resolved = root.resolve(strict=False)
        case_resolved = bundle.case_dir.resolve(strict=False)
    except OSError:
        root_resolved = root.absolute()
        case_resolved = bundle.case_dir.absolute()
    if root_resolved == case_resolved or case_resolved in root_resolved.parents:
        errors.append(
            f"output directory {root} must not be the case directory or inside it"
        )
    if _lexists(case_out):
        errors.append(f"output directory already exists (refusing to overwrite): {case_out}")
    capture_path = case_out / "capture.json"
    if _lexists(capture_path):
        errors.append(f"output already exists (refusing to overwrite): {capture_path}")
    for buffer in bundle.buffers:
        if buffer.output_name is None:
            continue
        output_path = case_out / buffer.output_name
        if _lexists(output_path):
            errors.append(f"output already exists (refusing to overwrite): {output_path}")
    return errors


def load_and_validate_case(
    case_dir: Path | str, output_root: Path | str | None = None
) -> tuple[CaseBundle | None, list[str]]:
    """Parse and fully validate one case directory.

    Returns ``(bundle, errors)``.  ``bundle`` is only returned when ``errors``
    is empty.  This function only reads host files; it never opens a device.
    """
    case_dir = Path(case_dir)
    errors: list[str] = []

    if not case_dir.is_dir():
        return None, [f"case directory does not exist or is not a directory: {case_dir}"]

    job_path = case_dir / "job.json"
    regcmd_path = case_dir / "regcmd.bin"
    if not job_path.is_file():
        return None, [f"missing job.json: {job_path}"]

    try:
        job_sha256 = _sha256_file(job_path)
    except OSError as exc:
        return None, [f"cannot hash {job_path}: {exc}"]

    try:
        job = read_json_strict(job_path)
    except CaseError as exc:
        return None, [str(exc)]

    if not isinstance(job, dict):
        return None, [f"{job_path}: top level must be a JSON object"]

    _check_keys(job, JOB_SCHEMA_FIELDS, JOB_SCHEMA_FIELDS, "job.json", errors)

    case_name = _case_component(job.get("case"), "job.json case", errors)
    source_example = _string(job.get("source_example"), "job.json source_example", errors)
    description = _string(job.get("description"), "job.json description", errors)
    timeout_ns = _integer(
        job.get("timeout_ns"),
        "job.json timeout_ns",
        errors,
        minimum=1,
        maximum=S64_MAX,
    )

    regcmd: bytes | None = None
    regcmd_hash: str | None = None
    regcmd_words: int | None = None
    if not regcmd_path.is_file():
        errors.append(f"missing regcmd.bin: {regcmd_path}")
    else:
        try:
            resolved_regcmd = regcmd_path.resolve(strict=True)
            resolved_case = case_dir.resolve(strict=True)
        except OSError as exc:
            errors.append(f"cannot resolve {regcmd_path}: {exc}")
        else:
            if resolved_case not in resolved_regcmd.parents:
                errors.append(
                    f"{regcmd_path}: resolves outside the case directory to {resolved_regcmd}"
                )
            else:
                try:
                    data = regcmd_path.read_bytes()
                except OSError as exc:
                    errors.append(f"cannot read {regcmd_path}: {exc}")
                else:
                    if not data:
                        errors.append(f"{regcmd_path}: regcmd.bin is empty")
                    elif len(data) % 8 != 0:
                        errors.append(
                            f"{regcmd_path}: regcmd.bin is {len(data)} bytes, not a multiple of 8"
                        )
                    elif len(data) > U32_MAX:
                        errors.append(f"{regcmd_path}: regcmd.bin exceeds the 32-bit BO size limit")
                    else:
                        regcmd = data
                        regcmd_hash = _sha256(data)
                        regcmd_words = len(data) // 8

    tasks = _validate_tasks(job.get("tasks"), regcmd_words, errors)
    buffers = _validate_buffers(case_dir, job.get("buffers"), errors)
    patches = _validate_patches(
        job.get("patches"), regcmd_words, {b.name for b in buffers}, errors
    )

    if errors:
        return None, errors

    assert case_name is not None
    assert source_example is not None
    assert description is not None
    assert timeout_ns is not None
    assert regcmd is not None
    assert regcmd_hash is not None
    bundle = CaseBundle(
        case_dir=case_dir,
        job_path=job_path,
        job_sha256=job_sha256,
        job=job,
        case=case_name,
        source_example=source_example,
        description=description,
        timeout_ns=timeout_ns,
        tasks=tasks,
        buffers=buffers,
        patches=patches,
        regcmd=regcmd,
        regcmd_sha256=regcmd_hash,
    )
    if output_root is not None:
        errors.extend(check_output_paths(bundle, output_root))
    if errors:
        return None, errors
    return bundle, []


# ---------------------------------------------------------------------------
# Pure patch, descriptor and handle logic


def patch_qword(qword: int, kind: str, dma_address: int) -> tuple[int, int]:
    """Apply one patch and return ``(patched_qword, mask)``.

    Address fields this bundle format represents as 32-bit values are rejected
    rather than silently truncated.  ``low32``/``high32`` select a half of the
    64-bit DMA address; ``all32`` is the low-32 operation defined by the format.
    """
    if not _is_int(qword) or qword < 0 or qword > U64_MAX:
        raise PatchError(f"command QWORD is not an unsigned 64-bit integer: {qword!r}")
    if not isinstance(kind, str) or kind not in PATCH_KINDS:
        raise PatchError(f"unsupported patch kind {kind!r}")
    if not _is_int(dma_address) or dma_address < 0 or dma_address > U64_MAX:
        raise PatchError(f"DMA address is not an unsigned 64-bit integer: {dma_address!r}")
    if kind in ("value32", "all32") and dma_address > U32_MAX:
        raise PatchError(
            f"patch kind {kind!r} needs a 32-bit DMA address, got {dma_address:#x}"
        )
    mask = PATCH_MASKS[kind]
    if kind == "value32":
        value = (dma_address & U32_MAX) << 16
    elif kind in ("all32", "low32"):
        value = dma_address & U32_MAX
    elif kind == "high32":
        value = (dma_address >> 32) & U32_MAX
        value <<= 32
    else:  # pragma: no cover - guarded by PATCH_KINDS
        raise PatchError(f"unsupported patch kind {kind!r}")
    patched = (qword & (~mask & U64_MAX)) | (value & mask)
    return patched, mask


def _patch_attribute(patch: PatchSpec | Mapping[str, Any], field: str) -> Any:
    if isinstance(patch, PatchSpec):
        return getattr(patch, field)
    try:
        return patch[field]
    except (KeyError, TypeError) as exc:
        raise PatchError(f"patch is missing {field!r}") from exc


def apply_patches(
    regcmd: bytes,
    patches: Sequence[PatchSpec | Mapping[str, Any]],
    buffer_addresses: Mapping[str, int],
) -> tuple[bytes, list[dict[str, Any]]]:
    """Patch QWORDs in a copy of ``regcmd`` and describe every change."""
    if len(regcmd) % 8 != 0:
        raise PatchError(f"regcmd length {len(regcmd)} is not a multiple of 8")
    data = bytearray(regcmd)
    qword_count = len(regcmd) // 8
    used_masks: dict[int, int] = {}
    applied: list[dict[str, Any]] = []

    for index, patch in enumerate(patches):
        regcmd_index = _patch_attribute(patch, "regcmd_index")
        buffer_name = _patch_attribute(patch, "buffer")
        kind = _patch_attribute(patch, "kind")
        if not _is_int(regcmd_index) or not 0 <= regcmd_index < qword_count:
            raise PatchError(
                f"patch[{index}] regcmd_index {regcmd_index!r} is outside "
                f"0..{qword_count - 1}"
            )
        if not isinstance(buffer_name, str) or buffer_name not in buffer_addresses:
            raise PatchError(f"patch[{index}] refers to unknown buffer {buffer_name!r}")
        if not isinstance(kind, str) or kind not in PATCH_KINDS:
            raise PatchError(f"patch[{index}] has unsupported kind {kind!r}")
        dma_address = buffer_addresses[buffer_name]
        offset = regcmd_index * 8
        before = struct.unpack_from("<Q", data, offset)[0]
        after, mask = patch_qword(before, kind, dma_address)
        if used_masks.get(regcmd_index, 0) & mask:
            raise PatchError(
                f"patch[{index}] {kind!r} overlaps another patch on "
                f"regcmd_index {regcmd_index}"
            )
        used_masks[regcmd_index] = used_masks.get(regcmd_index, 0) | mask
        struct.pack_into("<Q", data, offset, after)
        applied.append(
            {
                "regcmd_index": regcmd_index,
                "kind": kind,
                "buffer": buffer_name,
                "dma_address": dma_address,
                "before": before,
                "after": after,
                "mask": mask,
            }
        )
    return bytes(data), applied


def build_task_descriptors(
    tasks: Sequence[TaskSpec | Mapping[str, Any]], regcmd_dma: int
) -> tuple[TaskDescriptor, ...]:
    """Build descriptors whose ``regcmd`` fields fit the UAPI's 32-bit field."""
    if not _is_int(regcmd_dma) or not 0 <= regcmd_dma <= U32_MAX:
        raise DescriptorError(
            f"regcmd DMA address {regcmd_dma!r} does not fit drm_rocket_task.regcmd (u32)"
        )
    if regcmd_dma % TASK_ALIGNMENT:
        raise DescriptorError(
            f"regcmd DMA address {regcmd_dma:#x} is not {TASK_ALIGNMENT}-byte aligned"
        )
    if not tasks:
        raise DescriptorError("at least one Rocket task is required")

    descriptors: list[TaskDescriptor] = []
    for index, task in enumerate(tasks):
        if isinstance(task, TaskSpec):
            offset = task.regcmd_offset_words
            words = task.regcmd_words
        else:
            try:
                offset = task["regcmd_offset_words"]
                words = task["regcmd_words"]
            except (KeyError, TypeError) as exc:
                raise DescriptorError(f"task[{index}] is missing a required field") from exc
        if not _is_int(offset) or offset < 0:
            raise DescriptorError(f"task[{index}] offset {offset!r} is not a non-negative int")
        if not _is_int(words) or not 1 <= words <= MAX_REGCMDS:
            raise DescriptorError(
                f"task[{index}] regcmd_words {words!r} is outside 1..{MAX_REGCMDS}"
            )
        address = regcmd_dma + 8 * offset
        if address > U32_MAX:
            raise DescriptorError(
                f"task[{index}] regcmd address {address:#x} does not fit the u32 UAPI field"
            )
        if address % TASK_ALIGNMENT:
            raise DescriptorError(
                f"task[{index}] regcmd address {address:#x} is not "
                f"{TASK_ALIGNMENT}-byte aligned"
            )
        descriptors.append(TaskDescriptor(address, words, offset))
    return tuple(descriptors)


def pack_task_descriptors(descriptors: Sequence[TaskDescriptor]) -> bytes:
    return b"".join(struct.pack("<II", d.regcmd, d.regcmd_count) for d in descriptors)


def partition_handles(
    buffers: Sequence[BufferSpec], handles: Mapping[str, int], regcmd_handle: int
) -> tuple[list[int], list[int]]:
    """Partition handles into Rocket in/out arrays without duplicate objects.

    ``inout`` is passed only in the out array.  The kernel locks every object's
    reservation and duplicate entries would be a self-deadlock; the output
    write fence is the stronger of the two dependencies and covers readback.
    """
    if not _is_int(regcmd_handle) or regcmd_handle <= 0:
        raise CaseError(f"invalid regcmd BO handle {regcmd_handle!r}")
    in_handles = [regcmd_handle]
    out_handles: list[int] = []
    seen = {regcmd_handle}
    for buffer in buffers:
        handle = handles.get(buffer.name)
        if not _is_int(handle) or handle <= 0:
            raise CaseError(f"missing or invalid handle for buffer {buffer.name!r}")
        if handle in seen:
            raise CaseError(f"duplicate GEM handle {handle} in one submission")
        seen.add(handle)
        if buffer.direction == "in":
            in_handles.append(handle)
        elif buffer.direction in ("out", "inout"):
            out_handles.append(handle)
        else:  # pragma: no cover - validation guarantees this
            raise CaseError(f"unsupported buffer direction {buffer.direction!r}")
    if not out_handles:
        raise CaseError("submission has no output BO to wait on")
    return in_handles, out_handles


def pack_job(
    tasks_pointer: int,
    in_handles_pointer: int,
    out_handles_pointer: int,
    task_count: int,
    in_handle_count: int,
    out_handle_count: int,
) -> bytes:
    return struct.pack(
        "<QQQIIII",
        tasks_pointer,
        in_handles_pointer,
        out_handles_pointer,
        task_count,
        TASK_SIZE,
        in_handle_count,
        out_handle_count,
    )


def pack_submit(jobs_pointer: int, job_count: int = 1) -> bytes:
    return struct.pack("<QIIQ", jobs_pointer, job_count, JOB_SIZE, 0)


# ---------------------------------------------------------------------------
# Device-side UAPI (never executed at import time)


def _ioctl(fd: int, request: int, payload: bytes) -> bytes:
    buffer = bytearray(payload)
    fcntl.ioctl(fd, request, buffer, True)
    return bytes(buffer)


def _deadline(timeout_ns: int) -> int:
    value = time.monotonic_ns() + timeout_ns
    return min(value, S64_MAX)


def _page_size() -> int:
    return int(os.sysconf("SC_PAGE_SIZE"))


def _page_align(value: int) -> int:
    page = _page_size()
    return (value + page - 1) // page * page


def audit_device(path: Path | str) -> dict[str, Any]:
    """Read-only identity of the DRM target; no reset or control ioctl."""
    target = Path(path)
    try:
        info = target.stat()
    except OSError as exc:
        raise CaseError(f"cannot stat device {target}: {exc}") from exc
    if not stat.S_ISCHR(info.st_mode):
        raise CaseError(f"device {target} is not a character device")
    audit: dict[str, Any] = {
        "path": str(target),
        "major": os.major(info.st_rdev),
        "minor": os.minor(info.st_rdev),
        "kernel": os.uname().release,
    }
    sysdev = Path(f"/sys/dev/char/{audit['major']}:{audit['minor']}/device")
    try:
        resolved = sysdev.resolve(strict=True)
    except OSError:
        resolved = None
    if resolved is not None:
        audit["sysfs_device"] = str(resolved)
        driver_link = resolved / "driver"
        try:
            driver = driver_link.resolve(strict=True).name
        except OSError:
            driver = None
        if driver is not None:
            audit["driver"] = driver
            if driver != "rocket":
                raise CaseError(
                    f"device {target} is bound to driver {driver!r}, not the Rocket driver"
                )
    compatible_path = Path("/proc/device-tree/compatible")
    if compatible_path.is_file():
        try:
            raw = compatible_path.read_bytes().split(b"\x00")
            audit["board_compatible"] = [
                item.decode("ascii", errors="strict") for item in raw if item
            ]
        except (OSError, UnicodeDecodeError):
            audit["board_compatible"] = None
    return audit


@dataclass
class RocketBO:
    role: str
    name: str
    size: int
    handle: int
    dma_address: int
    mmap_offset: int
    mapping_size: int
    mapping: mmap.mmap | None = None

    def close(self) -> None:
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None


class RocketFD:
    """One open Rocket DRM fd and its BO lifetime helpers."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        self.audit = audit_device(self.path)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CLOEXEC)
        self.closed = False

    def create_bo(self, role: str, name: str, size: int) -> RocketBO:
        if not _is_int(size) or not 1 <= size <= U32_MAX:
            raise CaseError(f"invalid BO size {size!r} for {name!r}")
        payload = struct.pack("<IIQQ", size, 0, 0, 0)
        result = _ioctl(self.fd, DRM_IOCTL_ROCKET_CREATE_BO, payload)
        returned_size, handle, dma_address, offset = struct.unpack("<IIQQ", result)
        if returned_size != size:
            raise CaseError(
                f"create BO {name!r} returned size {returned_size}, requested {size}"
            )
        if handle == 0:
            raise CaseError(f"create BO {name!r} returned handle 0")
        if offset % _page_size() != 0:
            try:
                self.gem_close(handle)
            except OSError:
                pass
            raise CaseError(f"create BO {name!r} returned unaligned mmap offset {offset:#x}")
        mapping_size = _page_align(size)
        try:
            mapping = mmap.mmap(
                self.fd,
                mapping_size,
                mmap.MAP_SHARED,
                mmap.PROT_READ | mmap.PROT_WRITE,
                offset=offset,
            )
        except Exception:
            try:
                self.gem_close(handle)
            except OSError:
                pass
            raise
        return RocketBO(
            role=role,
            name=name,
            size=size,
            handle=handle,
            dma_address=dma_address,
            mmap_offset=offset,
            mapping_size=mapping_size,
            mapping=mapping,
        )

    def prep_bo(self, handle: int, timeout_ns: int) -> None:
        deadline = _deadline(timeout_ns)
        payload = struct.pack("<IIq", handle, 0, deadline)
        _ioctl(self.fd, DRM_IOCTL_ROCKET_PREP_BO, payload)

    def fini_bo(self, handle: int) -> None:
        _ioctl(self.fd, DRM_IOCTL_ROCKET_FINI_BO, struct.pack("<II", handle, 0))

    def submit(self, payload: bytes) -> int:
        if len(payload) != SUBMIT_SIZE:
            raise CaseError("internal submit payload size mismatch")
        _ioctl(self.fd, DRM_IOCTL_ROCKET_SUBMIT, payload)
        return 0

    def gem_close(self, handle: int) -> None:
        _ioctl(self.fd, DRM_IOCTL_GEM_CLOSE, struct.pack("<II", handle, 0))

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self.fd)


# ---------------------------------------------------------------------------
# Execution and capture


def _utc_now() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def tool_identity() -> dict[str, Any]:
    script = Path(__file__).resolve()
    try:
        sha = _sha256_file(script)
    except OSError:
        sha = None
    return {
        "name": "rocket_run.py",
        "version": __version__,
        "sha256": sha,
        "python": platform.python_version(),
        "hostname": socket.gethostname(),
        "kernel": os.uname().release,
    }


def _base_capture(
    *,
    case: str | None,
    case_dir: Path | str | None,
    device_path: str,
    tool: Mapping[str, Any],
    timeout_ns: int | None = None,
    job_sha256: str | None = None,
    source_example: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": CAPTURE_SCHEMA,
        "case": case,
        "case_dir": str(case_dir) if case_dir is not None else None,
        "source_example": source_example,
        "description": description,
        "status": "RUNNING",
        "device_path": device_path,
        "tool_version": __version__,
        "tool": dict(tool),
        "started_utc": _utc_now(),
        "timeout_ns": timeout_ns,
        "submit_ret": None,
        "submit_errno": None,
        "submit_error": None,
        "addresses": {},
        "sizes": {},
        "durations": {},
        "hashes": {"job_json": job_sha256},
        "buffers": [],
        "regcmd": None,
        "tasks": [],
        "patches": [],
        "outputs": [],
        "errors": [],
        "cleanup_errors": [],
    }


def _bo_capture(bo: RocketBO, buffer: BufferSpec | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "role": bo.role,
        "name": bo.name,
        "size": bo.size,
        "handle": bo.handle,
        "dma_address": bo.dma_address,
        "mmap_offset": bo.mmap_offset,
        "mapping_size": bo.mapping_size,
    }
    if buffer is not None:
        row.update(
            {
                "direction": buffer.direction,
                "input": buffer.input_name,
                "output": buffer.output_name,
                "input_sha256": buffer.input_sha256,
            }
        )
    return row


def _write_exclusive(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError(errno.EIO, "short write")
            view = view[written:]
    finally:
        os.close(fd)


def _write_capture(case_out: Path, capture: dict[str, Any]) -> Path:
    path = case_out / "capture.json"
    text = json.dumps(capture, indent=2, sort_keys=True) + "\n"
    _write_exclusive(path, text.encode("utf-8"))
    return path


def _record_error(capture: dict[str, Any], message: str) -> None:
    capture["errors"].append(message)


def run_case(
    bundle: CaseBundle,
    output_root: Path | str,
    device_path: Path | str,
    tool: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one validated case and return its capture record.

    All failures are converted into a FAIL capture record.  Output files are
    written only after every output BO has been waited on and read back.
    """
    tool = tool or tool_identity()
    started = time.monotonic_ns()
    capture = _base_capture(
        case=bundle.case,
        case_dir=bundle.case_dir,
        device_path=str(device_path),
        tool=tool,
        timeout_ns=bundle.timeout_ns,
        job_sha256=bundle.job_sha256,
        source_example=bundle.source_example,
        description=bundle.description,
    )
    capture["sizes"]["regcmd"] = len(bundle.regcmd)
    capture["sizes"]["buffers"] = {b.name: b.size for b in bundle.buffers}
    capture["hashes"]["regcmd_source"] = bundle.regcmd_sha256
    capture["tasks"] = [
        {
            "index": index,
            "regcmd_offset_words": task.regcmd_offset_words,
            "regcmd_words": task.regcmd_words,
            "fetched_regcmd_words": regcmd_fetch_words(task.regcmd_words),
        }
        for index, task in enumerate(bundle.tasks)
    ]
    case_out = Path(output_root) / bundle.case
    device: RocketFD | None = None
    command_bo: RocketBO | None = None
    buffers_bo: dict[str, RocketBO] = {}
    output_data: dict[str, bytes] = {}
    durations: dict[str, int] = {}
    status_ok = False
    case_out_created = False

    def mark(label: str, started_ns: int) -> None:
        durations[label] = durations.get(label, 0) + (time.monotonic_ns() - started_ns)

    try:
        output_errors = check_output_paths(bundle, output_root)
        if output_errors:
            raise CaseError("; ".join(output_errors))

        t = time.monotonic_ns()
        case_out.mkdir(parents=True, exist_ok=False)
        case_out_created = True
        mark("prepare_output_dir_ns", t)

        t = time.monotonic_ns()
        device = RocketFD(device_path)
        capture["device"] = device.audit
        mark("open_device_ns", t)

        t = time.monotonic_ns()
        command_bo = device.create_bo("regcmd", "regcmd", len(bundle.regcmd))
        capture["regcmd"] = _bo_capture(command_bo)
        capture["regcmd"]["sha256_source"] = bundle.regcmd_sha256
        capture["addresses"] = {"regcmd": command_bo.dma_address, "buffers": {}}
        for buffer in bundle.buffers:
            bo = device.create_bo("buffer", buffer.name, buffer.size)
            buffers_bo[buffer.name] = bo
            capture["buffers"].append(_bo_capture(bo, buffer))
            capture["addresses"]["buffers"][buffer.name] = bo.dma_address
        mark("allocate_ns", t)

        t = time.monotonic_ns()
        patched, applied = apply_patches(
            bundle.regcmd,
            bundle.patches,
            {b.name: buffers_bo[b.name].dma_address for b in bundle.buffers},
        )
        mark("patch_ns", t)
        capture["patches"] = applied
        capture["hashes"]["regcmd_patched"] = _sha256(patched)
        capture["sizes"]["regcmd"] = len(patched)
        if capture["regcmd"] is not None:
            capture["regcmd"]["sha256_patched"] = capture["hashes"]["regcmd_patched"]

        t = time.monotonic_ns()
        try:
            descriptors = build_task_descriptors(bundle.tasks, command_bo.dma_address)
        except DescriptorError:
            raise
        mark("descriptor_ns", t)
        for index, descriptor in enumerate(descriptors):
            capture["tasks"][index].update(
                {
                    "regcmd_dma": descriptor.regcmd,
                    "regcmd_bytes": descriptor.regcmd_count * 8,
                    "fetched_regcmd_bytes": regcmd_fetch_words(descriptor.regcmd_count) * 8,
                }
            )
        capture["addresses"]["tasks"] = [d.regcmd for d in descriptors]

        # The kernel expects CPU cache ownership to be handed over with
        # PREP_BO and returned with FINI_BO.  Prep every BO, copy inputs and the
        # patched command stream, then hand every BO back before the submit.
        t = time.monotonic_ns()
        for bo in [command_bo, *buffers_bo.values()]:
            start = time.monotonic_ns()
            device.prep_bo(bo.handle, bundle.timeout_ns)
            mark("prep_ns", start)
        mark("prep_all_ns", t)

        t = time.monotonic_ns()
        copies: dict[str, dict[str, Any]] = {}
        for buffer in bundle.buffers:
            if buffer.direction not in ("in", "inout"):
                continue
            if buffer.input_data is None:
                raise CaseError(f"buffer {buffer.name!r} has no loaded input data")
            bo = buffers_bo[buffer.name]
            assert bo.mapping is not None
            bo.mapping[: buffer.size] = buffer.input_data
            copies[buffer.name] = {
                "file": buffer.input_name,
                "size": buffer.size,
                "sha256": buffer.input_sha256,
            }
        assert command_bo.mapping is not None
        command_bo.mapping[: len(patched)] = patched
        capture["hashes"]["command_stream"] = {
            "file": "regcmd.bin",
            "size": len(patched),
            "sha256": capture["hashes"]["regcmd_patched"],
        }
        capture["hashes"]["inputs"] = copies
        mark("copy_inputs_ns", t)

        t = time.monotonic_ns()
        for bo in [command_bo, *buffers_bo.values()]:
            start = time.monotonic_ns()
            device.fini_bo(bo.handle)
            mark("fini_ns", start)
        mark("fini_all_ns", t)

        in_handles, out_handles = partition_handles(
            bundle.buffers,
            {name: bo.handle for name, bo in buffers_bo.items()},
            command_bo.handle,
        )
        task_bytes = pack_task_descriptors(descriptors)
        task_array = ctypes.create_string_buffer(task_bytes, len(task_bytes))
        in_array = (ctypes.c_uint32 * len(in_handles))(*in_handles)
        out_array = (ctypes.c_uint32 * len(out_handles))(*out_handles)
        job_bytes = pack_job(
            ctypes.addressof(task_array),
            ctypes.addressof(in_array),
            ctypes.addressof(out_array),
            len(descriptors),
            len(in_handles),
            len(out_handles),
        )
        jobs_array = ctypes.create_string_buffer(job_bytes, len(job_bytes))
        submit_bytes = pack_submit(ctypes.addressof(jobs_array))
        submit_array = ctypes.create_string_buffer(submit_bytes, len(submit_bytes))

        t = time.monotonic_ns()
        try:
            submit_ret = device.submit(bytes(submit_array))
        except OSError as exc:
            capture["submit_errno"] = exc.errno
            capture["submit_error"] = str(exc)
            mark("submit_ns", t)
            raise
        else:
            capture["submit_ret"] = submit_ret
            mark("submit_ns", t)

        # PREP on an output BO waits for the job's write fence.  Do the wait
        # before reading any output.  A timeout is an explicit failure and is
        # never retried or reset.
        t = time.monotonic_ns()
        for buffer in bundle.buffers:
            if buffer.direction not in ("out", "inout"):
                continue
            bo = buffers_bo[buffer.name]
            start = time.monotonic_ns()
            device.prep_bo(bo.handle, bundle.timeout_ns)
            mark("output_prep_ns", start)
            if bo.mapping is None:
                raise CaseError(f"buffer {buffer.name!r} has no mmap")
            output_data[buffer.name] = bytes(bo.mapping[: buffer.size])
        mark("wait_read_ns", t)

        t = time.monotonic_ns()
        outputs: list[dict[str, Any]] = []
        for buffer in bundle.buffers:
            if buffer.output_name is None:
                continue
            data = output_data.get(buffer.name)
            if data is None:
                raise CaseError(f"no readback data for output buffer {buffer.name!r}")
            output_path = case_out / buffer.output_name
            _write_exclusive(output_path, data)
            outputs.append(
                {
                    "buffer": buffer.name,
                    "file": buffer.output_name,
                    "size": len(data),
                    "sha256": _sha256(data),
                }
            )
        capture["outputs"] = outputs
        capture["hashes"]["outputs"] = {
            row["buffer"]: {
                "file": row["file"],
                "size": row["size"],
                "sha256": row["sha256"],
            }
            for row in outputs
        }
        # Attach the real readback hashes to the buffer records too.
        by_name = {row["buffer"]: row for row in outputs}
        for row in capture["buffers"]:
            out = by_name.get(row["name"])
            if out is not None:
                row["output_sha256"] = out["sha256"]
                row["output_size"] = out["size"]
        mark("write_outputs_ns", t)
        status_ok = True
    except Exception as exc:  # noqa: BLE001 - per-case failure is intentional
        _record_error(capture, f"{type(exc).__name__}: {exc}")
        if not isinstance(exc, (CaseError, OSError)):
            capture["traceback"] = traceback.format_exc()
    finally:
        # Close mappings and handles even after a failure.  Closing the fd is
        # sufficient to release all remaining handles, but explicit GEM close
        # leaves a clean failure record.
        for bo in [command_bo, *buffers_bo.values()]:
            if bo is None:
                continue
            try:
                bo.close()
            except Exception as exc:  # noqa: BLE001
                capture["cleanup_errors"].append(f"munmap {bo.name}: {exc}")
            if device is not None and not device.closed:
                try:
                    device.gem_close(bo.handle)
                except OSError as exc:
                    capture["cleanup_errors"].append(
                        f"GEM_CLOSE {bo.name} handle {bo.handle}: {exc}"
                    )
        if device is not None:
            try:
                device.close()
            except OSError as exc:
                capture["cleanup_errors"].append(f"close device: {exc}")
        durations["total_ns"] = time.monotonic_ns() - started
        capture["durations"] = durations
        if capture["cleanup_errors"]:
            _record_error(capture, "cleanup errors: " + "; ".join(capture["cleanup_errors"]))
            status_ok = False
        capture["finished_utc"] = _utc_now()
        capture["status"] = "OK" if status_ok and not capture["errors"] else "FAIL"
        if case_out_created and case_out.is_dir():
            capture["capture_file"] = str(case_out / "capture.json")
            try:
                _write_capture(case_out, capture)
            except Exception as exc:  # noqa: BLE001
                _record_error(capture, f"cannot write capture.json: {exc}")
                capture["status"] = "FAIL"
                print(f"rocket_run: {bundle.case}: cannot write capture.json: {exc}", file=sys.stderr)
        elif not case_out_created:
            _record_error(capture, f"case output directory was not created: {case_out}")
    return capture


def failure_capture(
    *,
    case_dir: Path | str,
    case_name: str | None,
    errors: Sequence[str],
    output_root: Path | str | None,
    device_path: Path | str,
    tool: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a pre-execution validation failure without touching the device."""
    tool = tool or tool_identity()
    capture = _base_capture(
        case=case_name,
        case_dir=case_dir,
        device_path=str(device_path),
        tool=tool,
    )
    capture["status"] = "FAIL"
    capture["finished_utc"] = _utc_now()
    capture["errors"] = list(errors)
    capture["durations"] = {"total_ns": 0}
    capture["capture_file"] = None
    if output_root is None or case_name is None:
        return capture
    try:
        root_resolved = Path(output_root).resolve(strict=False)
        case_resolved = Path(case_dir).resolve(strict=False)
    except OSError:
        root_resolved = Path(output_root).absolute()
        case_resolved = Path(case_dir).absolute()
    if root_resolved == case_resolved or case_resolved in root_resolved.parents:
        capture["errors"].append(
            f"not writing failure capture: output root {output_root} is inside the case directory"
        )
        return capture
    case_out = Path(output_root) / case_name
    if _lexists(case_out):
        return capture
    try:
        case_out.mkdir(parents=True, exist_ok=False)
        capture["capture_file"] = str(case_out / "capture.json")
        _write_capture(case_out, capture)
    except Exception as exc:  # noqa: BLE001
        capture["errors"].append(f"cannot write failure capture.json: {exc}")
    return capture


# ---------------------------------------------------------------------------
# Queue expansion and CLI


def expand_case_arguments(paths: Iterable[Path | str]) -> tuple[list[Path], list[str]]:
    """Expand case directories or family directories containing ``cases/``."""
    cases: list[Path] = []
    errors: list[str] = []
    for raw in paths:
        path = Path(raw)
        if (path / "job.json").is_file():
            cases.append(path)
        elif (path / "cases").is_dir():
            children = sorted(child for child in (path / "cases").iterdir() if child.is_dir())
            if not children:
                errors.append(f"queue directory has no case subdirectories: {path / 'cases'}")
            cases.extend(children)
        elif (path / "regcmd.bin").is_file():
            # A case whose job.json is missing still needs a recorded failure.
            cases.append(path)
        elif path.is_dir():
            errors.append(
                f"{path}: no job.json, regcmd.bin or cases/ directory; "
                "not a case or queue directory"
            )
        else:
            errors.append(f"not a directory: {path}")
    return cases, errors


def _case_name_hint(case_dir: Path) -> str | None:
    """Best-effort case name for a failure capture, without trusting the job."""

    def safe(value: str | None) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        if "/" in value or "\\" in value or value in (".", ".."):
            return None
        if any(ord(ch) < 0x20 for ch in value):
            return None
        return value

    fallback = safe(case_dir.name)
    try:
        job = read_json_strict(case_dir / "job.json")
    except CaseError:
        return fallback
    if not isinstance(job, dict):
        return fallback
    return safe(job.get("case")) or fallback


def _print_capture_result(capture: Mapping[str, Any]) -> None:
    case = capture.get("case") or "<unknown>"
    status = capture.get("status")
    errors = capture.get("errors") or []
    if status == "OK":
        print(f"OK   {case}  submit_ret={capture.get('submit_ret')}")
    else:
        print(f"FAIL {case}")
        for error in errors:
            print(f"     {error}")


def validate_only(paths: Iterable[Path | str], output_root: Path | str | None) -> int:
    cases, expand_errors = expand_case_arguments(paths)
    bad = False
    for error in expand_errors:
        print(f"FAIL {error}", file=sys.stderr)
        bad = True
    seen_cases: dict[str, Path] = {}
    for case_dir in cases:
        try:
            bundle, errors = load_and_validate_case(case_dir, output_root)
        except Exception as exc:  # noqa: BLE001 - report instead of aborting the queue
            bundle, errors = None, [f"{type(exc).__name__}: {exc}"]
        if bundle is not None and bundle.case in seen_cases:
            errors = list(errors)
            errors.append(
                f"duplicate case name {bundle.case!r}; also used by {seen_cases[bundle.case]}"
            )
            bundle = None
        if errors:
            bad = True
            print(f"FAIL {case_dir}")
            for error in errors:
                print(f"     {error}")
        else:
            assert bundle is not None
            seen_cases[bundle.case] = case_dir
            print(
                f"OK   {case_dir}  case={bundle.case!r} "
                f"tasks={len(bundle.tasks)} buffers={len(bundle.buffers)} "
                f"patches={len(bundle.patches)}"
            )
    if not cases and not expand_errors:
        print("FAIL no cases found", file=sys.stderr)
        bad = True
    return 1 if bad else 0


def run_queue(
    paths: Iterable[Path | str], output_root: Path | str, device_path: Path | str
) -> int:
    cases, expand_errors = expand_case_arguments(paths)
    tool = tool_identity()
    bad = bool(expand_errors)
    for error in expand_errors:
        print(f"FAIL {error}", file=sys.stderr)
    if not cases and not expand_errors:
        print("FAIL no cases found", file=sys.stderr)
        return 1

    output_root = Path(output_root)
    if _lexists(output_root) and not output_root.is_dir():
        print(f"rocket_run: output root is not a directory: {output_root}", file=sys.stderr)
        return 1
    try:
        root_resolved = output_root.resolve(strict=False)
    except OSError:
        root_resolved = output_root.absolute()
    for case_dir in cases:
        try:
            case_resolved = case_dir.resolve(strict=True)
        except OSError:
            continue
        if root_resolved == case_resolved or case_resolved in root_resolved.parents:
            print(
                f"rocket_run: output root {output_root} must not be a case directory "
                f"or inside one ({case_dir})",
                file=sys.stderr,
            )
            return 1
    try:
        output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"rocket_run: cannot create output root {output_root}: {exc}", file=sys.stderr)
        return 1

    prepared: list[tuple[Path, CaseBundle | None, list[str]]] = []
    for case_dir in cases:
        try:
            bundle, errors = load_and_validate_case(case_dir, output_root)
        except Exception as exc:  # noqa: BLE001 - keep the rest of the queue going
            bundle, errors = None, [f"{type(exc).__name__}: {exc}"]
        prepared.append((case_dir, bundle, errors))

    # Duplicate case names would share an output directory.  Reject all of the
    # colliding entries before running anything.
    by_name: dict[str, list[int]] = {}
    for index, (_, bundle, _) in enumerate(prepared):
        if bundle is not None:
            by_name.setdefault(bundle.case, []).append(index)
    for name, indexes in by_name.items():
        if len(indexes) > 1:
            bad = True
            for index in indexes:
                case_dir, bundle, errors = prepared[index]
                errors = list(errors)
                errors.append(f"duplicate case name {name!r} in this queue")
                prepared[index] = (case_dir, None, errors)

    for case_dir, bundle, errors in prepared:
        if bundle is None:
            continue
        capture = run_case(bundle, output_root, device_path, tool)
        _print_capture_result(capture)
        if capture.get("status") != "OK":
            bad = True

    # Record validation failures after real cases so an invalid bundle cannot
    # occupy the output directory of a valid bundle with the same case name.
    for case_dir, bundle, errors in prepared:
        if bundle is not None:
            continue
        bad = True
        hint = _case_name_hint(case_dir)
        try:
            capture = failure_capture(
                case_dir=case_dir,
                case_name=hint,
                errors=errors,
                output_root=output_root,
                device_path=device_path,
                tool=tool,
            )
        except Exception as exc:  # noqa: BLE001 - keep the rest of the queue going
            print(f"FAIL {hint or case_dir}")
            print(f"     cannot record failure capture: {type(exc).__name__}: {exc}")
            continue
        _print_capture_result(capture)
    return 1 if bad else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one prepared Rocket capture case or a queue of cases. "
            "The caller must hold /home/opencode-agent/rk3588-npu.lock."
        )
    )
    parser.add_argument(
        "--device",
        default="/dev/accel/accel0",
        help="Rocket DRM character device (default: /dev/accel/accel0)",
    )
    parser.add_argument(
        "--out",
        help="fresh output root; each case writes OUT_ROOT/<case>/",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate bundles and exit without opening a device or writing outputs",
    )
    parser.add_argument(
        "cases",
        nargs="+",
        metavar="CASE_OR_QUEUE",
        help=(
            "case directories containing job.json, or family directories "
            "containing cases/<name>/job.json"
        ),
    )
    args = parser.parse_args(argv)

    if args.validate_only:
        return validate_only(args.cases, args.out)
    if not args.out:
        parser.error("--out is required unless --validate-only is used")
    return run_queue(args.cases, args.out, args.device)


if __name__ == "__main__":
    sys.exit(main())
