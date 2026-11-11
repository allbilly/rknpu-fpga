#!/usr/bin/env python3
"""Run prepared RK3588 integer elementwise Rocket capture bundles.

Pure Python 3, no NumPy.  This is the board side of the ew-int queue: it
allocates Rocket BOs, patches real DMA addresses into the prepared command
QWORD stream, submits exactly one job per case, waits on the output BO and
writes the bytes that were actually read back.

The caller must hold /home/opencode-agent/rk3588-npu.lock for the entire
invocation.  Cases are processed strictly sequentially.  A per-case failure is
recorded in that case's capture.json and the runner moves on; it never retries
a submit and it never substitutes expected data for device output.

Usage:
    python3 ew_int_run.py --queue QUEUE_DIR --out OUTPUT_ROOT
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import fcntl
import hashlib
import json
import mmap
import os
import platform
import socket
import struct
import sys
import time
import traceback
from pathlib import Path

VERSION = "1.0.0"
SCHEMA = "rk3588-ew-int-capture-v1"
DEVICE = "/dev/accel/accel0"
BUFFER_SIZE = 4096
PAGE_SIZE = int(os.sysconf("SC_PAGE_SIZE"))
U32_MAX = 0xFFFFFFFF
U64_MAX = 0xFFFFFFFFFFFFFFFF
S64_MAX = 0x7FFFFFFFFFFFFFFF

# Mainline Rocket DRM UAPI (drivers/accel/rocket).
DRM_COMMAND_BASE = 0x40
CREATE_BO = (3 << 30) | (ord("d") << 8) | (DRM_COMMAND_BASE + 0) | (24 << 16)
SUBMIT = (1 << 30) | (ord("d") << 8) | (DRM_COMMAND_BASE + 1) | (24 << 16)
PREP_BO = (1 << 30) | (ord("d") << 8) | (DRM_COMMAND_BASE + 2) | (16 << 16)
FINI_BO = (1 << 30) | (ord("d") << 8) | (DRM_COMMAND_BASE + 3) | (8 << 16)
GEM_CLOSE = (1 << 30) | (ord("d") << 8) | 0x09 | (8 << 16)

assert struct.calcsize("<IIQQ") == 24
assert struct.calcsize("<QIIQ") == 24
assert struct.calcsize("<IIq") == 16
assert struct.calcsize("<II") == 8


def utc_now() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_align(value: int) -> int:
    return (value + PAGE_SIZE - 1) // PAGE_SIZE * PAGE_SIZE


def ioctl(fd: int, request: int, payload: bytes) -> bytes:
    buffer = bytearray(payload)
    fcntl.ioctl(fd, request, buffer, True)
    return bytes(buffer)


class RunnerError(RuntimeError):
    pass


class BO:
    def __init__(self, name: str, size: int, handle: int, dma_address: int,
                 mmap_offset: int, mapping: mmap.mmap):
        self.name = name
        self.size = size
        self.handle = handle
        self.dma_address = dma_address
        self.mmap_offset = mmap_offset
        self.mapping = mapping

    def close(self) -> None:
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None


def open_device(path: str) -> int:
    try:
        return os.open(path, os.O_RDWR | os.O_CLOEXEC)
    except OSError as exc:
        raise RunnerError(f"cannot open Rocket device {path}: {exc}") from exc


def create_bo(fd: int, name: str, size: int) -> BO:
    if not 1 <= size <= U32_MAX:
        raise RunnerError(f"invalid BO size {size} for {name}")
    result = ioctl(fd, CREATE_BO, struct.pack("<IIQQ", size, 0, 0, 0))
    returned_size, handle, dma_address, offset = struct.unpack("<IIQQ", result)
    if returned_size not in (size, page_align(size)):
        raise RunnerError(
            f"create BO {name}: driver returned size {returned_size}, requested {size}"
        )
    if handle == 0:
        raise RunnerError(f"create BO {name}: handle 0")
    if offset % PAGE_SIZE:
        raise RunnerError(f"create BO {name}: unaligned mmap offset {offset:#x}")
    mapping_size = max(page_align(size), page_align(returned_size))
    try:
        mapping = mmap.mmap(
            fd, mapping_size, mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE, offset=offset,
        )
    except Exception:
        try:
            ioctl(fd, GEM_CLOSE, struct.pack("<II", handle, 0))
        except OSError:
            pass
        raise
    return BO(name, size, handle, dma_address, offset, mapping)


def prep_bo(fd: int, bo: BO, timeout_ns: int) -> None:
    deadline = min(time.monotonic_ns() + timeout_ns, S64_MAX)
    ioctl(fd, PREP_BO, struct.pack("<IIq", bo.handle, 0, deadline))


def fini_bo(fd: int, bo: BO) -> None:
    ioctl(fd, FINI_BO, struct.pack("<II", bo.handle, 0))


def close_bo(fd: int, bo: BO, cleanup_errors: list[str]) -> None:
    try:
        bo.close()
    except Exception as exc:  # noqa: BLE001
        cleanup_errors.append(f"munmap {bo.name}: {exc}")
    try:
        ioctl(fd, GEM_CLOSE, struct.pack("<II", bo.handle, 0))
    except OSError as exc:
        cleanup_errors.append(f"GEM_CLOSE {bo.name} handle {bo.handle}: {exc}")


def load_case(case_dir: Path) -> dict:
    job_path = case_dir / "job.json"
    if not job_path.is_file():
        raise RunnerError(f"missing {job_path}")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    if job.get("case") != case_dir.name:
        raise RunnerError(
            f"job case {job.get('case')!r} != directory {case_dir.name!r}"
        )
    timeout_ns = job.get("timeout_ns")
    if type(timeout_ns) is not int or timeout_ns <= 0:
        raise RunnerError(f"bad timeout_ns {timeout_ns!r}")

    regcmd_path = case_dir / "regcmd.bin"
    regcmd = regcmd_path.read_bytes()
    if not regcmd or len(regcmd) % 8:
        raise RunnerError(f"regcmd.bin is {len(regcmd)} bytes, not a non-empty multiple of 8")

    tasks = job.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise RunnerError("exactly one task is required")
    task = tasks[0]
    if task.get("regcmd_offset_words") != 0:
        raise RunnerError("task regcmd_offset_words must be 0")
    if task.get("regcmd_words") != len(regcmd) // 8:
        raise RunnerError("task regcmd_words does not match regcmd.bin")

    by_name = {}
    for buffer in job.get("buffers", []):
        name = buffer.get("name")
        if name in by_name:
            raise RunnerError(f"duplicate buffer {name!r}")
        by_name[name] = buffer
    if set(by_name) != {"a", "b", "out"}:
        raise RunnerError(f"buffer set is {sorted(by_name)}, expected a,b,out")
    for name in ("a", "b"):
        buffer = by_name[name]
        if buffer.get("direction") != "in":
            raise RunnerError(f"buffer {name} direction is not 'in'")
        if buffer.get("size") != BUFFER_SIZE:
            raise RunnerError(f"buffer {name} size is not {BUFFER_SIZE}")
        if not (case_dir / buffer.get("input", "")).is_file():
            raise RunnerError(f"buffer {name} input file missing")
    out_buffer = by_name["out"]
    if out_buffer.get("direction") != "out":
        raise RunnerError("buffer out direction is not 'out'")
    if out_buffer.get("size") != BUFFER_SIZE:
        raise RunnerError(f"buffer out size is not {BUFFER_SIZE}")
    if out_buffer.get("output") != "out.bin":
        raise RunnerError("buffer out filename is not out.bin")

    patches = job.get("patches")
    if not isinstance(patches, list) or len(patches) != 3:
        raise RunnerError("exactly three patches are required")
    seen = set()
    for patch in patches:
        if patch.get("kind") != "value32":
            raise RunnerError(f"unsupported patch kind {patch.get('kind')!r}")
        if patch.get("buffer") not in ("a", "b", "out"):
            raise RunnerError(f"unknown patch buffer {patch.get('buffer')!r}")
        index = patch.get("regcmd_index")
        if type(index) is not int or not 0 <= index < len(regcmd) // 8:
            raise RunnerError(f"patch index {index!r} out of range")
        if index in seen:
            raise RunnerError(f"duplicate patch index {index}")
        seen.add(index)
    if {patch["buffer"] for patch in patches} != {"a", "b", "out"}:
        raise RunnerError("patches must cover a, b and out exactly once")

    a_data = (case_dir / by_name["a"]["input"]).read_bytes()
    b_data = (case_dir / by_name["b"]["input"]).read_bytes()
    if len(a_data) != BUFFER_SIZE or len(b_data) != BUFFER_SIZE:
        raise RunnerError("input files are not 4096 bytes")
    return {
        "job": job,
        "job_sha256": sha256_file(job_path),
        "regcmd": regcmd,
        "regcmd_sha256": sha256_bytes(regcmd),
        "timeout_ns": timeout_ns,
        "inputs": {"a": a_data, "b": b_data},
        "input_sha256": {"a": sha256_bytes(a_data), "b": sha256_bytes(b_data)},
        "patches": patches,
    }


def patch_regcmd(regcmd: bytes, patches: list[dict], addresses: dict[str, int]) -> tuple[bytes, list[dict]]:
    data = bytearray(regcmd)
    applied = []
    for patch in patches:
        index = patch["regcmd_index"]
        buffer_name = patch["buffer"]
        address = addresses[buffer_name]
        if not 0 <= address <= U32_MAX:
            raise RunnerError(
                f"DMA address {address:#x} for {buffer_name} does not fit value32"
            )
        offset = index * 8
        before = struct.unpack_from("<Q", data, offset)[0]
        after = (before & ~0x0000FFFFFFFF0000) | ((address & U32_MAX) << 16)
        struct.pack_into("<Q", data, offset, after)
        applied.append({
            "regcmd_index": index,
            "buffer": buffer_name,
            "kind": "value32",
            "dma_address": address,
            "before": before,
            "after": after,
        })
    return bytes(data), applied


def submit_job(fd: int, cmd: BO, regcmd_words: int, inputs: list[BO], output: BO) -> int:
    if cmd.dma_address > U32_MAX:
        raise RunnerError(f"regcmd DMA address {cmd.dma_address:#x} does not fit u32")
    task_bytes = struct.pack("<II", cmd.dma_address & U32_MAX, regcmd_words)
    task_array = ctypes.create_string_buffer(task_bytes, len(task_bytes))
    in_handles = [cmd.handle, *[bo.handle for bo in inputs]]
    out_handles = [output.handle]
    in_array = (ctypes.c_uint32 * len(in_handles))(*in_handles)
    out_array = (ctypes.c_uint32 * len(out_handles))(*out_handles)
    job_bytes = struct.pack(
        "<QQQIIII",
        ctypes.addressof(task_array),
        ctypes.addressof(in_array),
        ctypes.addressof(out_array),
        1,
        8,
        len(in_handles),
        len(out_handles),
    )
    jobs_array = ctypes.create_string_buffer(job_bytes, len(job_bytes))
    submit_bytes = struct.pack("<QIIQ", ctypes.addressof(jobs_array), 1, 40, 0)
    submit_array = ctypes.create_string_buffer(submit_bytes, len(submit_bytes))
    ioctl(fd, SUBMIT, bytes(submit_array))
    return 0


def base_capture(case_dir: Path, device_path: str) -> dict:
    return {
        "schema": SCHEMA,
        "runner_version": VERSION,
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "case": case_dir.name,
        "case_dir": str(case_dir),
        "status": "RUNNING",
        "device_path": device_path,
        "hostname": socket.gethostname(),
        "kernel": os.uname().release,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "started_utc": utc_now(),
        "duration_ns": None,
        "durations": {},
        "submit_ret": None,
        "submit_errno": None,
        "submit_error": None,
        "addresses": {},
        "sizes": {},
        "bo_handles": {},
        "hashes": {},
        "patches": [],
        "outputs": [],
        "bytes_read": 0,
        "errors": [],
        "cleanup_errors": [],
    }


def run_case(case_dir: Path, output_root: Path, device_path: str) -> dict:
    capture = base_capture(case_dir, device_path)
    started = time.monotonic_ns()
    case_out = output_root / case_dir.name
    fd = None
    bos: dict[str, BO] = {}
    status_ok = False
    try:
        case_out.mkdir(parents=True, exist_ok=False)
        case = load_case(case_dir)
        capture["hashes"].update({
            "job_json": case["job_sha256"],
            "regcmd_source": case["regcmd_sha256"],
            "inputs": dict(case["input_sha256"]),
        })
        capture["sizes"].update({
            "regcmd_bytes": len(case["regcmd"]),
            "regcmd_words": len(case["regcmd"]) // 8,
            "a": BUFFER_SIZE,
            "b": BUFFER_SIZE,
            "out": BUFFER_SIZE,
        })
        fd = open_device(device_path)
        capture["device_stat"] = {
            "mode": oct(os.stat(device_path).st_mode),
            "rdev": list(os.stat(device_path).st_rdev.to_bytes(8, "little")),
        }

        bos["cmd"] = create_bo(fd, "cmd", len(case["regcmd"]))
        bos["a"] = create_bo(fd, "a", BUFFER_SIZE)
        bos["b"] = create_bo(fd, "b", BUFFER_SIZE)
        bos["out"] = create_bo(fd, "out", BUFFER_SIZE)
        for name, bo in bos.items():
            capture["addresses"][name] = bo.dma_address
            capture["bo_handles"][name] = bo.handle
            capture["sizes"][f"{name}_bo_request"] = bo.size
            capture["sizes"][f"{name}_mmap"] = len(bo.mapping)

        patched, applied = patch_regcmd(
            case["regcmd"],
            case["patches"],
            {name: bo.dma_address for name, bo in bos.items() if name != "cmd"},
        )
        capture["patches"] = applied
        capture["hashes"]["regcmd_patched"] = sha256_bytes(patched)

        t = time.monotonic_ns()
        for bo in (bos["cmd"], bos["a"], bos["b"], bos["out"]):
            prep_bo(fd, bo, case["timeout_ns"])
        capture["durations"]["prep_all_ns"] = time.monotonic_ns() - t

        t = time.monotonic_ns()
        bos["a"].mapping[:BUFFER_SIZE] = case["inputs"]["a"]
        bos["b"].mapping[:BUFFER_SIZE] = case["inputs"]["b"]
        bos["cmd"].mapping[: len(patched)] = patched
        capture["durations"]["copy_inputs_ns"] = time.monotonic_ns() - t

        t = time.monotonic_ns()
        for bo in (bos["cmd"], bos["a"], bos["b"], bos["out"]):
            fini_bo(fd, bo)
        capture["durations"]["fini_all_ns"] = time.monotonic_ns() - t

        t = time.monotonic_ns()
        try:
            submit_ret = submit_job(
                fd, bos["cmd"], len(case["regcmd"]) // 8,
                [bos["a"], bos["b"]], bos["out"],
            )
        except OSError as exc:
            capture["submit_errno"] = exc.errno
            capture["submit_error"] = str(exc)
            raise
        capture["submit_ret"] = submit_ret
        capture["durations"]["submit_ns"] = time.monotonic_ns() - t
        if submit_ret != 0:
            raise RunnerError(f"submit returned {submit_ret}")
        t = time.monotonic_ns()
        prep_bo(fd, bos["out"], case["timeout_ns"])
        raw = bytes(bos["out"].mapping[:BUFFER_SIZE])
        capture["durations"]["wait_read_ns"] = time.monotonic_ns() - t
        if len(raw) != BUFFER_SIZE:
            raise RunnerError(f"read back {len(raw)} bytes, expected {BUFFER_SIZE}")

        out_path = case_out / "out.bin"
        fd_out = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd_out, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
        finally:
            os.close(fd_out)
        capture["hashes"]["out"] = sha256_bytes(raw)
        capture["outputs"].append({
            "file": "out.bin",
            "size": len(raw),
            "sha256": sha256_bytes(raw),
        })
        capture["bytes_read"] = len(raw)
        status_ok = True
    except Exception as exc:  # noqa: BLE001 - per-case failure is intentional
        capture["errors"].append(f"{type(exc).__name__}: {exc}")
        if not isinstance(exc, (RunnerError, OSError, json.JSONDecodeError)):
            capture["traceback"] = traceback.format_exc()
    finally:
        if fd is not None:
            for bo in bos.values():
                close_bo(fd, bo, capture["cleanup_errors"])
            try:
                os.close(fd)
            except OSError as exc:
                capture["cleanup_errors"].append(f"close device: {exc}")
        if capture["cleanup_errors"]:
            capture["errors"].append("cleanup errors: " + "; ".join(capture["cleanup_errors"]))
            status_ok = False
        capture["duration_ns"] = time.monotonic_ns() - started
        capture["status"] = "OK" if status_ok and not capture["errors"] else "FAIL"
        if case_out.is_dir():
            try:
                with open(case_out / "capture.json", "x", encoding="utf-8") as stream:
                    stream.write(json.dumps(capture, indent=2, sort_keys=True) + "\n")
            except Exception as exc:  # noqa: BLE001
                capture["errors"].append(f"cannot write capture.json: {exc}")
                print(f"FAIL {case_dir.name}: cannot write capture.json: {exc}", file=sys.stderr)
        else:
            capture["errors"].append("case output directory was not created")
    return capture


def main(argv: list[str] | None = None) -> int:
    run_started = time.monotonic_ns()
    run_started_utc = utc_now()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", required=True, help="directory of case directories")
    parser.add_argument("--out", required=True, help="fresh output root")
    parser.add_argument("--device", default=DEVICE)
    args = parser.parse_args(argv)

    queue = Path(args.queue)
    output_root = Path(args.out)
    if not queue.is_dir():
        print(f"runner: queue directory missing: {queue}", file=sys.stderr)
        return 1
    output_root.mkdir(parents=True, exist_ok=True)
    cases = sorted(path for path in queue.iterdir() if path.is_dir())
    if not cases:
        print(f"runner: no case directories in {queue}", file=sys.stderr)
        return 1

    results = []
    for case_dir in cases:
        capture = run_case(case_dir, output_root, args.device)
        results.append(capture)
        if capture["status"] == "OK":
            print(
                f"OK   {case_dir.name} submit_ret={capture['submit_ret']} "
                f"out_sha256={capture['hashes'].get('out')} "
                f"duration_ns={capture['duration_ns']}"
            )
        else:
            print(f"FAIL {case_dir.name}: {'; '.join(capture['errors'])}")

    summary = {
        "schema": SCHEMA,
        "runner_version": VERSION,
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "hostname": socket.gethostname(),
        "kernel": os.uname().release,
        "python_version": platform.python_version(),
        "device_path": args.device,
        "queue": str(queue),
        "output_root": str(output_root),
        "started_utc": run_started_utc,
        "finished_utc": utc_now(),
        "duration_ns": time.monotonic_ns() - run_started,
        "case_count": len(results),
        "ok_count": sum(1 for item in results if item["status"] == "OK"),
        "fail_count": sum(1 for item in results if item["status"] != "OK"),
        "submit_ret_zero_count": sum(1 for item in results if item["submit_ret"] == 0),
        "bytes_read_total": sum(item["bytes_read"] for item in results),
        "cases": [
            {
                "case": item["case"],
                "status": item["status"],
                "submit_ret": item["submit_ret"],
                "submit_errno": item["submit_errno"],
                "submit_error": item["submit_error"],
                "addresses": item["addresses"],
                "bytes_read": item["bytes_read"],
                "duration_ns": item["duration_ns"],
                "out_sha256": item["hashes"].get("out"),
                "errors": item["errors"],
            }
            for item in results
        ],
    }
    with open(output_root / "summary.json", "x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        f"SUMMARY cases={summary['case_count']} ok={summary['ok_count']} "
        f"fail={summary['fail_count']} submit0={summary['submit_ret_zero_count']} "
        f"bytes_read={summary['bytes_read_total']}"
    )
    return 0 if summary["fail_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
