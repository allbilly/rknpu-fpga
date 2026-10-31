"""Passive raw-DRM capture primitives; importing this module never opens a device.

The observer calls the original backend and ioctl unchanged. It adds explicitly
recorded FROM_DEVICE syncs after successful blocking submits to capture entire
physical BOs before their reuse/free. These are capture diagnostics, not an FPGA
runtime or a numerical oracle. A hardware case runner and silicon results remain
separate requirements.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import asdict, dataclass
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from unittest.mock import patch


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


def save_preserving(recorder, primary):
    """A receipt failure must not mask the backend's original timeout/error."""
    try:
        recorder.save()
    except BaseException as error:
        recorder.failed = True
        if primary is None:
            raise
        primary.add_note("Capture receipt also failed: " + repr(error))


@dataclass(frozen=True)
class Buffer:
    allocation: int
    virtual: int
    dma: int
    obj: int
    handle: int
    size: int


class Recorder:
    """Own a fresh artifact directory and record complete live allocation spans.

    ``read`` and ``sync`` operate only on registered, backend-owned mappings.
    Their injection also permits device-free tests; a captured submission alone
    makes no assertion about where the injected ioctl actually executed.
    """

    def __init__(self, out, provenance, read, sync):
        self.lock, self.failed = threading.RLock(), False
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.read, self.sync = read, sync
        self.buffers, self.events, self.submissions = {}, [], []
        self.next_allocation, self.inflight = 0, False
        self.provenance = json.loads(json.dumps(provenance))
        self.save()

    @serialized
    def save(self):
        report = dict(schema="raw-drm-capture-v1", provenance=self.provenance,
                      scope="Raw submission/BO observations only; no numerical or FPGA acceptance",
                      submissions=self.submissions, events=self.events,
                      capture_failed=self.failed,
                      live_allocations=[asdict(b) for b in self.buffers.values()])
        temporary = self.out / "report.json.tmp"
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        temporary.replace(self.out / "report.json")

    @serialized
    def register(self, virtual, dma, obj, handle, size):
        require(not self.failed and not self.inflight, "Allocation changed during a failed/blocking capture")
        require(all(type(x) is int for x in (virtual, dma, obj, handle, size)), "Non-integer BO metadata")
        require(virtual > 0 and dma >= 0 and obj > 0 and handle > 0 and size > 0, "Invalid BO extent")
        require(virtual + size <= 2**64 and dma + size <= 2**64, "BO address overflow")
        for old in self.buffers.values():
            require(obj != old.obj and handle != old.handle, "Duplicate live BO object/handle")
            require(virtual + size <= old.virtual or old.virtual + old.size <= virtual, "Overlapping live mappings")
            require(dma + size <= old.dma or old.dma + old.size <= dma, "Overlapping live device ranges")
        buffer = Buffer(self.next_allocation, virtual, dma, obj, handle, size)
        self.next_allocation += 1
        self.buffers[obj] = buffer
        self.events.append(dict(kind="allocate", buffer=asdict(buffer)))
        try:
            self.save()
        except BaseException as error:
            # The caller still owns cleanup of the newly returned mapping. A
            # failed receipt must not leave it registered after that cleanup,
            # nor remove an older allocation rejected as a duplicate above.
            if self.buffers.get(obj) is buffer:
                self.buffers.pop(obj)
            self.failed = True
            self.events.append(dict(kind="allocation_registration_failed", allocation=buffer.allocation,
                                    error=repr(error)))
            raise
        return buffer

    @serialized
    def unregister(self, obj):
        require(not self.inflight and obj in self.buffers, "Untracked free or free during capture")
        buffer = self.buffers.pop(obj)
        self.events.append(dict(kind="free", allocation=buffer.allocation))
        self.save()

    def write(self, relative, data):
        path = self.out / relative
        with path.open("xb") as stream:
            stream.write(data)
        return dict(file=relative, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())

    def snapshot(self, prefix, buffers):
        rows = []
        for buffer in buffers:
            data = self.read(buffer.virtual, buffer.size)
            require(isinstance(data, bytes) and len(data) == buffer.size, "Incomplete physical BO snapshot")
            rows.append(dict(buffer=asdict(buffer), **self.write(f"{prefix}/bo-{buffer.allocation}.bin", data)))
        return rows

    @serialized
    def submit(self, payload, descriptors, action):
        require(not self.failed and not self.inflight, "Nested submission or failed capture session")
        require(self.buffers, "Submission has no registered BOs")
        buffers = tuple(self.buffers.values())
        name = f"submit-{len(self.submissions):04d}"
        directory = self.out / name
        directory.mkdir()
        (directory / "before").mkdir()
        row = dict(status="CAPTURING_BEFORE_SUBMIT", diagnostic_syncs=[], descriptors=descriptors,
                   original_action_started=False, blocking_completion_confirmed=False)
        self.submissions.append(row)
        self.inflight = True
        primary = None
        try:
            row["payload_before"] = self.write(f"{name}/submit-before.bin", bytes(payload))
            row["before"] = self.snapshot(f"{name}/before", buffers)
            row["status"] = "SUBMITTING"
            self.save()
            row["original_action_started"] = True
            result = action()  # The original blocking ioctl, exactly once; no retry.
            row["blocking_completion_confirmed"] = True
            row["payload_after"] = self.write(f"{name}/submit-after.bin", bytes(payload))
            row["status"] = "CAPTURING_AFTER_BLOCKING_COMPLETION"
            self.save()
            # All syncs must finish before reading any post-submit BO bytes.
            for buffer in buffers:
                event = dict(kind="diagnostic_from_device_sync", allocation=buffer.allocation,
                             obj_addr=buffer.obj, offset=0, size=buffer.size, completed=False)
                row["diagnostic_syncs"].append(event)
                self.save()
                self.sync(buffer)
                event["completed"] = True
            (directory / "after").mkdir()
            row["after"] = self.snapshot(f"{name}/after", buffers)
            row["status"] = "CAPTURED_BLOCKING_SUBMISSION_NOT_NUMERIC_VALIDATED"
            return result
        except BaseException as error:
            primary, self.failed = error, True
            row["status"], row["error"] = "FAIL_CAPTURE", repr(error)
            raise
        finally:
            self.inflight = False
            save_preserving(self, primary)


def audit_device(path):
    """Read sysfs identity only; fail before opening a non-RK3588 DRM node."""
    path = Path(path).resolve(strict=True)
    info = path.stat()
    require(stat.S_ISCHR(info.st_mode), "DRM target is not a character device")
    sysdev = Path(f"/sys/dev/char/{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}/device").resolve(strict=True)
    driver = (sysdev / "driver").resolve(strict=True).name
    compatible = (Path("/proc/device-tree/compatible").read_bytes().split(b"\0"))
    require(driver == "rknpu" and b"rockchip,rk3588" in compatible, "Target is not the required RK3588 rknpu driver")
    return dict(path=str(path), rdev=info.st_rdev, sysfs_device=str(sysdev), driver=driver,
                board_compatible=[x.decode("ascii", errors="strict") for x in compatible if x],
                kernel=os.uname().release)


@contextmanager
def observe_backend(runtime, rk, recorder, identity):
    """Observe one audited device; never instantiate a backend or open a node.

    Install before constructing the device so initial resets and every BO are
    observed. The caller must pin the backend source and supply ``audit_device``
    output. Normal allocation, command encoding, sync, reset, and ioctl functions
    remain authoritative. Hardware case selection is intentionally outside this
    primitive.
    """
    original_alloc = runtime.RockchipDevice._gpu_alloc
    original_free = runtime.RockchipDevice._gpu_free
    original_ioctl = runtime.FileIOInterface.ioctl
    active_device = None
    active_fd = None
    identity = json.loads(json.dumps(identity))

    def check_fd(fd):
        nonlocal active_fd
        info = os.fstat(fd.fd)
        require(stat.S_ISCHR(info.st_mode) and info.st_rdev == identity["rdev"] and
                str(Path(fd.path).resolve()) == identity["path"], "Opened DRM fd differs from audited target")
        require(active_fd is None or active_fd is fd, "Multiple control descriptors in one capture")
        active_fd = fd

    def allocate(device, size, flags=0):
        nonlocal active_device
        with recorder.lock:
            require(not recorder.failed and not recorder.inflight, "Allocation during failed/blocking capture")
            check_fd(device.fd_ctl)
            require(active_device is None or active_device is device, "Multiple devices in one capture")
            active_device = device
            buffer = original_alloc(device, size, flags)
            try:
                # Stock backend maps this exact page-rounded extent. Never read
                # beyond that mapping on a driver ABI mismatch.
                mapped = max(4096, (size + 4095) & -4096)
                require(int(buffer.meta.size) == mapped, "Driver BO extent differs from mapped span")
                recorder.register(int(buffer.base.va_addr), int(buffer.meta.dma_addr), int(buffer.meta.obj_addr),
                                  int(buffer.meta.handle), mapped)
                return buffer
            except BaseException as error:
                cleanup = dict(kind="unregistered_allocation_cleanup", completed=False)
                recorder.events.append(cleanup)
                try:
                    original_free(device, buffer)
                    cleanup["completed"] = True
                except BaseException as cleanup_error:
                    cleanup["error"] = repr(cleanup_error)
                    error.add_note("Allocation cleanup also failed: " + repr(cleanup_error))
                recorder.failed = True
                device._poisoned = True
                save_preserving(recorder, error)
                raise

    def free(device, buffer):
        with recorder.lock:
            check_fd(device.fd_ctl)
            obj = int(buffer.meta.obj_addr)
            require(not recorder.inflight and obj in recorder.buffers, "Untracked free or free during submit")
            registered = recorder.buffers[obj]
            require((int(buffer.base.va_addr), int(buffer.meta.dma_addr), int(buffer.meta.handle), int(buffer.meta.size)) ==
                    (registered.virtual, registered.dma, registered.handle, registered.size),
                    "Free metadata differs from the registered physical mapping")
            try:
                original_free(device, buffer)
                recorder.unregister(obj)
            except BaseException as error:
                # The stock free may already have unmapped its VA before a
                # destroy-ioctl failure. No future snapshot may read that span.
                recorder.failed = True
                device._poisoned = True
                recorder.buffers.pop(obj, None)
                recorder.events.append(dict(kind="free_failed", obj_addr=obj, error=repr(error),
                                            ownership="UNMAP_OR_DESTROY_OUTCOME_UNKNOWN"))
                save_preserving(recorder, error)
                raise

    def ioctl(fd, request, payload):
        with recorder.lock:
            return locked_ioctl(fd, request, payload)

    def locked_ioctl(fd, request, payload):
        check_fd(fd)
        before = bytes(payload)
        event = dict(kind="ioctl", request=request, payload_before_hex=before.hex(), completed=False)
        recorder.events.append(event)
        recorder.save()
        primary = None
        submitting = (request & 0xff) == 0x41
        try:
            if submitting:
                require(isinstance(payload, rk.struct_rknpu_submit), "Unknown submit ABI")
                expected = (3 << 30) | (ctypes.sizeof(payload) << 16) | (ord("d") << 8) | 0x41
                require(request == expected and active_device is not None and fd is active_device.fd_ctl,
                        "Unrecognized submit request/device")
                require(payload.core_mask == 1 and payload.task_start == 0 and payload.task_number > 0 and
                        payload.flags == (rk.RKNPU_JOB_PC | rk.RKNPU_JOB_BLOCK | rk.RKNPU_JOB_PINGPONG),
                        "Capture supports only the pinned core-0 blocking PC submit contract")
                task = recorder.buffers.get(int(payload.task_obj_addr))
                amount = int(payload.task_number) * ctypes.sizeof(rk.struct_rknpu_task)
                require(task is not None and amount <= task.size, "Task descriptors outside owned BO")
                tasks = (rk.struct_rknpu_task * int(payload.task_number)).from_address(task.virtual)
                descriptors = []
                for descriptor in tasks:
                    address, size = int(descriptor.regcmd_addr), int(descriptor.regcfg_amount) * 8
                    require(size > 0 and address % 8 == 0 and any(
                        b.dma <= address and address + size <= b.dma + b.size for b in recorder.buffers.values()),
                        "Command QWORD range outside owned BO")
                    descriptors.append({name: int(getattr(descriptor, name)) for name, _ in descriptor._fields_})
                def action():
                    result = original_ioctl(fd, request, payload)
                    require(result == 0, "Blocking ioctl returned nonzero")
                    return result
                result = recorder.submit(payload, descriptors, action)
            else:
                result = original_ioctl(fd, request, payload)
            event.update(completed=True, return_value=result, payload_after_hex=bytes(payload).hex())
            return result
        except BaseException as error:
            primary = error
            if submitting:
                recorder.failed = True
                if active_device is not None:
                    active_device._poisoned = True
            event["error"] = repr(error)
            raise
        finally:
            try:
                save_preserving(recorder, primary)
            except BaseException:
                if active_device is not None:
                    active_device._poisoned = True
                raise

    # Cache maintenance goes through the unchanged kernel ABI and is recorded as
    # diagnostic traffic in addition to the backend's ordinary sync calls.
    previous_sync = recorder.sync
    def sync(buffer):
        require(active_device is not None, "No active capture device")
        rk.DRM_IOCTL_RKNPU_MEM_SYNC(active_device.fd_ctl, flags=rk.RKNPU_MEM_SYNC_FROM_DEVICE,
                                  obj_addr=buffer.obj, offset=0, size=buffer.size)
    recorder.sync = sync
    try:
        with patch.object(runtime.RockchipDevice, "_gpu_alloc", allocate), \
             patch.object(runtime.RockchipDevice, "_gpu_free", free), \
             patch.object(runtime.FileIOInterface, "ioctl", ioctl):
            yield recorder
    finally:
        recorder.sync = previous_sync
