"""Device-free tests for passive raw-DRM capture primitives."""
import ctypes
import json
from pathlib import Path
import stat
import threading
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import rk_capture


class FakeTask(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("regcfg_amount", ctypes.c_uint32),
        ("regcmd_addr", ctypes.c_uint64),
    ]


class FakeSubmit(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("task_start", ctypes.c_uint32),
        ("task_number", ctypes.c_uint32),
        ("task_obj_addr", ctypes.c_uint64),
        ("core_mask", ctypes.c_uint32),
    ]


class FakeMemSync(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("obj_addr", ctypes.c_uint64),
        ("offset", ctypes.c_uint64),
        ("size", ctypes.c_uint64),
    ]


def fake_abi():
    def sync_ioctl(fd, *, flags, obj_addr, offset, size):
        payload = FakeMemSync(flags, obj_addr, offset, size)
        return fd.ioctl(0xDEAD0001, payload)

    return SimpleNamespace(
        struct_rknpu_submit=FakeSubmit,
        struct_rknpu_task=FakeTask,
        RKNPU_JOB_PC=1,
        RKNPU_JOB_BLOCK=0,
        RKNPU_JOB_PINGPONG=4,
        RKNPU_MEM_SYNC_FROM_DEVICE=2,
        DRM_IOCTL_RKNPU_MEM_SYNC=sync_ioctl,
    )


class FakeFileIO:
    def __init__(self, trace, on_submit=None, submit_result=0, sync_error=None):
        self.path = "/dev/mock-rknpu"
        self.fd = 17
        self.trace = trace
        self.on_submit = on_submit
        self.submit_result = submit_result
        self.sync_error = sync_error
        self.calls = []

    def ioctl(self, request, payload):
        self.calls.append((request, payload))
        if request == 0xDEAD0001:
            self.trace.append(("sync", int(payload.obj_addr)))
            if self.sync_error is not None:
                raise self.sync_error
            return 0
        self.trace.append(("submit", request))
        if self.on_submit is not None:
            self.on_submit()
        return self.submit_result


class FakeBuffer:
    def __init__(self, size, dma, handle):
        self.storage = ctypes.create_string_buffer(size)
        self.va_addr = ctypes.addressof(self.storage)
        self.base = self
        self.size = size
        self.meta = SimpleNamespace(
            size=size,
            dma_addr=dma,
            obj_addr=self.va_addr,
            handle=handle,
        )


class FakeRockchipDevice:
    def __init__(self, fd, trace, submit_result=0):
        self.fd_ctl = fd
        self.trace = trace
        self.next_dma = 0x10000000
        self.next_handle = 1
        self.freed = []
        self.freed_buffers = []
        self.allocation_calls = []
        self.free_calls = []
        self._poisoned = False
        self.submit_result = submit_result

    def _gpu_alloc(self, size, flags=0):
        self.allocation_calls.append((size, flags))
        mapped = max(4096, (size + 4095) & -4096)
        buf = FakeBuffer(mapped, self.next_dma, self.next_handle)
        self.next_dma += mapped
        self.next_handle += 1
        self.last_allocation = buf
        return buf

    def _gpu_free(self, buf):
        self.free_calls.append(buf.meta.obj_addr)
        self.freed.append(buf.meta.obj_addr)
        self.freed_buffers.append(buf)


class RecorderTests(unittest.TestCase):
    def recorder(self, directory, read, sync=lambda _buffer: None):
        return rk_capture.Recorder(directory, {"test": "device-free"}, read, sync)

    def test_snapshots_cover_padded_physical_span_and_preserve_raw_payload(self):
        with TemporaryDirectory() as tmp:
            memory = bytearray(b"A" * 4096)
            events = []

            def read(address, size):
                events.append(("read", address, size))
                return bytes(memory[address - 0x1000:address - 0x1000 + size])

            recorder = self.recorder(Path(tmp) / "capture", read)
            buffer = recorder.register(0x1000, 0x8000, 0x9000, 1, 4096)
            memory[5:9] = b"PAD!"
            payload = FakeSubmit(5, 0, 1, buffer.obj, 1)
            descriptors = [{"regcmd_addr": 0x8000, "regcfg_amount": 2, "flags": 0}]
            actions = []

            def original_action():
                actions.append(bytes(payload))
                memory[5:9] = b"DONE"
                return 0

            result = recorder.submit(payload, descriptors, original_action)
            row = recorder.submissions[0]
            self.assertEqual(result, 0)
            self.assertEqual(len(actions), 1)
            self.assertEqual(row["descriptors"], descriptors)
            self.assertEqual(row["payload_before"]["bytes"], ctypes.sizeof(FakeSubmit))
            self.assertEqual((recorder.out / row["payload_before"]["file"]).read_bytes(), bytes(payload))
            self.assertEqual((recorder.out / row["payload_after"]["file"]).read_bytes(), bytes(payload))
            before = (recorder.out / row["before"][0]["file"]).read_bytes()
            after = (recorder.out / row["after"][0]["file"]).read_bytes()
            self.assertEqual(len(before), 4096)
            self.assertEqual(len(after), 4096)
            self.assertEqual(before[5:9], b"PAD!")
            self.assertEqual(after[5:9], b"DONE")
            self.assertEqual(row["status"], "CAPTURED_BLOCKING_SUBMISSION_NOT_NUMERIC_VALIDATED")

    def test_all_post_completion_syncs_precede_any_after_read(self):
        with TemporaryDirectory() as tmp:
            trace = []
            memory = {0x1000: b"a" * 16, 0x2000: b"b" * 16}
            recorder = self.recorder(
                Path(tmp) / "capture",
                lambda address, size: (trace.append(("read", address)), memory[address][:size])[1],
                lambda buffer: trace.append(("sync", buffer.obj)),
            )
            recorder.register(0x1000, 0x3000, 0x4000, 1, 16)
            recorder.register(0x2000, 0x5000, 0x6000, 2, 16)
            trace.clear()
            recorder.submit(b"payload", [], lambda: trace.append(("action",)) or 7)
            tail = trace[2:]  # Two complete pre-submit reads precede the action.
            action_index = next(i for i, event in enumerate(tail) if event[0] == "action")
            post = tail[action_index + 1:]
            self.assertEqual([event[0] for event in post], ["sync", "sync", "read", "read"])

    def test_submit_failure_is_not_retried_and_has_no_successful_after_state(self):
        with TemporaryDirectory() as tmp:
            calls = []
            recorder = self.recorder(Path(tmp) / "capture", lambda _a, n: bytes(n))
            recorder.register(0x1000, 0x3000, 0x4000, 1, 16)

            def fail_once():
                calls.append("submit")
                raise OSError("mock submit failure")

            with self.assertRaisesRegex(OSError, "mock submit failure"):
                recorder.submit(b"payload", [], fail_once)
            row = recorder.submissions[0]
            self.assertEqual(calls, ["submit"])
            self.assertEqual(row["status"], "FAIL_CAPTURE")
            self.assertNotIn("after", row)
            self.assertNotIn("payload_after", row)

    def test_sync_failure_has_no_after_snapshot_or_retry(self):
        with TemporaryDirectory() as tmp:
            calls = []

            def fail_sync(_buffer):
                calls.append("sync")
                raise OSError("mock sync failure")

            recorder = self.recorder(Path(tmp) / "capture", lambda _a, n: bytes(n), fail_sync)
            recorder.register(0x1000, 0x3000, 0x4000, 1, 16)
            with self.assertRaisesRegex(OSError, "mock sync failure"):
                recorder.submit(b"payload", [], lambda: calls.append("submit") or 0)
            row = recorder.submissions[0]
            self.assertEqual(calls, ["submit", "sync"])
            self.assertEqual(row["status"], "FAIL_CAPTURE")
            self.assertFalse(row["diagnostic_syncs"][0]["completed"])
            self.assertNotIn("after", row)

    def test_read_failures_before_or_after_submit_preserve_fail_status(self):
        for fail_on in (1, 2):
            with self.subTest(fail_on=fail_on), TemporaryDirectory() as tmp:
                reads, actions = [], []

                def read(_address, size):
                    reads.append(1)
                    if len(reads) == fail_on:
                        raise OSError("mock read failure")
                    return bytes(size)

                recorder = self.recorder(Path(tmp) / "capture", read)
                recorder.register(0x1000, 0x3000, 0x4000, 1, 16)
                with self.assertRaisesRegex(OSError, "mock read failure"):
                    recorder.submit(b"payload", [], lambda: actions.append("submit") or 0)
                row = recorder.submissions[0]
                self.assertEqual(row["status"], "FAIL_CAPTURE")
                self.assertNotIn("after", row)
                self.assertEqual(actions, [] if fail_on == 1 else ["submit"])

    def test_allocation_free_reuse_and_monotonic_allocation_identity(self):
        with TemporaryDirectory() as tmp:
            recorder = self.recorder(Path(tmp) / "capture", lambda _a, n: bytes(n))
            first = recorder.register(0x1000, 0x2000, 0x3000, 7, 64)
            recorder.unregister(first.obj)
            second = recorder.register(0x1000, 0x2000, 0x3000, 7, 64)
            self.assertEqual((first.allocation, second.allocation), (0, 1))
            self.assertEqual([event["kind"] for event in recorder.events], ["allocate", "free", "allocate"])
            self.assertEqual([item["allocation"] for item in json.loads((recorder.out / "report.json").read_text())["live_allocations"]], [1])

    def test_rejects_live_overlap_duplicate_handles_and_address_overflow(self):
        with TemporaryDirectory() as tmp:
            recorder = self.recorder(Path(tmp) / "capture", lambda _a, n: bytes(n))
            recorder.register(0x1000, 0x3000, 0x5000, 1, 64)
            invalid = [
                (0x103F, 0x4000, 0x6000, 2, 64),  # virtual overlap
                (0x2000, 0x303F, 0x6000, 2, 64),  # DMA overlap
                (0x2000, 0x4000, 0x7000, 1, 64),  # reused live handle
                (0x2000, 0x4000, 0x5000, 2, 64),  # reused live object
                (2**64 - 16, 0x5000, 0x7000, 3, 32),  # virtual overflow
                (0x3000, 2**64 - 16, 0x7000, 3, 32),  # DMA overflow
            ]
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(RuntimeError):
                    recorder.register(*args)

    def test_fresh_output_directory_is_required(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "capture"
            target.mkdir()
            (target / "sentinel").write_text("keep")
            with self.assertRaises(FileExistsError):
                self.recorder(target, lambda _a, n: bytes(n))
            self.assertEqual((target / "sentinel").read_text(), "keep")

    def test_original_timeout_survives_secondary_receipt_save_failure(self):
        with TemporaryDirectory() as tmp:
            recorder = self.recorder(Path(tmp) / "capture", lambda _a, n: bytes(n))
            recorder.register(0x1000, 0x3000, 0x4000, 1, 16)
            action_calls = []
            save = recorder.save

            def save_after_timeout():
                if action_calls:
                    raise OSError("secondary receipt failure")
                save()

            recorder.save = save_after_timeout

            def timeout():
                action_calls.append("action")
                raise TimeoutError("original blocking timeout")

            with self.assertRaisesRegex(TimeoutError, "original blocking timeout") as caught:
                recorder.submit(b"payload", [], timeout)
            self.assertEqual(action_calls, ["action"])
            self.assertTrue(recorder.failed)
            self.assertIn("secondary receipt failure", " ".join(getattr(caught.exception, "__notes__", [])))
            self.assertEqual(recorder.submissions[0]["status"], "FAIL_CAPTURE")
            self.assertFalse(recorder.submissions[0]["blocking_completion_confirmed"])


class ObserveBackendTests(unittest.TestCase):
    identity = {"rdev": 0x1234, "path": str(Path("/dev/mock-rknpu").resolve())}

    def build_device(self, trace, on_submit=None, result=0):
        fileio = FakeFileIO(trace, on_submit=on_submit, submit_result=result)
        runtime = SimpleNamespace(
            RockchipDevice=FakeRockchipDevice,
            FileIOInterface=FakeFileIO,
        )
        rk = fake_abi()
        device = FakeRockchipDevice(fileio, trace, submit_result=result)
        return runtime, rk, device, fileio

    def recorder(self, directory, trace, read=None):
        return rk_capture.Recorder(
            directory,
            {"backend": "fake test ABI"},
            read or (lambda address, size: (trace.append(("read", address)), ctypes.string_at(address, size))[1]),
            lambda _buffer: None,
        )

    def open_observer(self, runtime, rk, recorder):
        fake_fstat = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"])
        return patch("tools.rk_capture.os.fstat", return_value=fake_fstat), rk_capture.observe_backend(
            runtime, rk, recorder, self.identity
        )

    @staticmethod
    def valid_submit(rk, cmd, task, task_obj=None, command_address=None):
        descriptor = rk.struct_rknpu_task(0, 2, command_address if command_address is not None else cmd.meta.dma_addr)
        ctypes.memmove(task.va_addr, ctypes.byref(descriptor), ctypes.sizeof(descriptor))
        payload = rk.struct_rknpu_submit(
            rk.RKNPU_JOB_PC | rk.RKNPU_JOB_BLOCK | rk.RKNPU_JOB_PINGPONG,
            0,
            1,
            task.meta.obj_addr if task_obj is None else task_obj,
            1,
        )
        request = (3 << 30) | (ctypes.sizeof(payload) << 16) | (ord("d") << 8) | 0x41
        return request, payload, descriptor

    def test_observer_persists_actual_abi_ranges_and_restores_original_hooks(self):
        with TemporaryDirectory() as tmp:
            trace = []
            cmd_ref = {}

            def complete():
                cmd = cmd_ref["cmd"]
                ctypes.memset(cmd.va_addr + 8, 0xE7, 8)

            runtime, rk, device, fileio = self.build_device(trace, on_submit=complete)
            original_alloc = runtime.RockchipDevice._gpu_alloc
            original_free = runtime.RockchipDevice._gpu_free
            original_ioctl = runtime.FileIOInterface.ioctl
            recorder = rk_capture.Recorder(
                Path(tmp) / "capture",
                {"backend": "fake test ABI"},
                lambda address, size: (trace.append(("read", address)), ctypes.string_at(address, size))[1],
                lambda _buffer: self.fail("observer must replace Recorder.sync with the fake ABI sync"),
            )
            fake_fstat = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"])
            with patch("tools.rk_capture.os.fstat", return_value=fake_fstat):
                with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                    cmd = device._gpu_alloc(12)
                    task = device._gpu_alloc(ctypes.sizeof(rk.struct_rknpu_task))
                    cmd_ref["cmd"] = cmd
                    ctypes.memmove(cmd.va_addr, b"COMMAND!!PAD", 12)
                    request, payload, descriptor = self.valid_submit(rk, cmd, task)
                    self.assertEqual(device.fd_ctl.ioctl(request, payload), 0)

                self.assertIs(runtime.RockchipDevice._gpu_alloc, original_alloc)
                self.assertIs(runtime.RockchipDevice._gpu_free, original_free)
                self.assertIs(runtime.FileIOInterface.ioctl, original_ioctl)

            self.assertEqual(sum(req == request for req, _ in fileio.calls), 1)
            self.assertEqual(sum(req == 0xDEAD0001 for req, _ in fileio.calls), 2)
            row = recorder.submissions[0]
            self.assertEqual(row["status"], "CAPTURED_BLOCKING_SUBMISSION_NOT_NUMERIC_VALIDATED")
            self.assertEqual(row["payload_before"]["bytes"], ctypes.sizeof(payload))
            self.assertEqual((recorder.out / row["payload_before"]["file"]).read_bytes(), bytes(payload))
            self.assertEqual(row["descriptors"][0]["regcfg_amount"], 2)
            self.assertEqual(row["descriptors"][0]["regcmd_addr"], cmd.meta.dma_addr)
            self.assertEqual([x["buffer"]["size"] for x in row["before"]], [4096, 4096])
            self.assertEqual([x["buffer"]["size"] for x in row["after"]], [4096, 4096])
            after_cmd = next(x for x in row["after"] if x["buffer"]["obj"] == cmd.meta.obj_addr)
            captured = (recorder.out / after_cmd["file"]).read_bytes()
            self.assertEqual(captured[8:16], b"\xE7" * 8)
            task_capture = next(x for x in row["before"] if x["buffer"]["obj"] == task.meta.obj_addr)
            task_bytes = (recorder.out / task_capture["file"]).read_bytes()
            self.assertEqual(task_bytes[:ctypes.sizeof(descriptor)], bytes(descriptor))
            # Every diagnostic sync happens before either post-submit memory read.
            kinds = [event[0] for event in trace]
            submit_index = kinds.index("submit")
            post = kinds[submit_index + 1:]
            self.assertEqual(post, ["sync", "sync", "read", "read"])

    def test_observer_rejects_unowned_task_object_and_command_range(self):
        for fault in ("task_obj", "command_range"):
            with self.subTest(fault=fault), TemporaryDirectory() as tmp:
                trace = []
                runtime, rk, device, fileio = self.build_device(trace)
                recorder = rk_capture.Recorder(
                    Path(tmp) / "capture",
                    {"backend": "fake test ABI"},
                    lambda address, size: ctypes.string_at(address, size),
                    lambda _buffer: None,
                )
                fake_fstat = SimpleNamespace(st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"])
                with patch("tools.rk_capture.os.fstat", return_value=fake_fstat):
                    with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                        cmd = device._gpu_alloc(16)
                        task = device._gpu_alloc(ctypes.sizeof(rk.struct_rknpu_task))
                        if fault == "task_obj":
                            request, payload, _ = self.valid_submit(rk, cmd, task, task_obj=0xABCDEF)
                        else:
                            request, payload, _ = self.valid_submit(
                                rk, cmd, task, command_address=cmd.meta.dma_addr + 8192
                            )
                        with self.assertRaises(RuntimeError):
                            device.fd_ctl.ioctl(request, payload)
                self.assertEqual(sum(req == request for req, _ in fileio.calls), 0)
                self.assertEqual(recorder.submissions, [])
                self.assertEqual(runtime.RockchipDevice._gpu_alloc, FakeRockchipDevice._gpu_alloc)

    def test_completion_followed_by_sync_read_or_save_failure_poisons_without_retry(self):
        for failure in ("sync", "postread", "save"):
            with self.subTest(failure=failure), TemporaryDirectory() as tmp:
                trace, action_calls, reads = [], [], []
                runtime, rk, device, fileio = self.build_device(trace, on_submit=lambda: action_calls.append("submit"))
                recorder = self.recorder(
                    Path(tmp) / "capture",
                    trace,
                    read=lambda address, size: (
                        reads.append(address),
                        (_ for _ in ()).throw(OSError("post-completion read failure"))
                        if failure == "postread" and len(reads) == 3
                        else ctypes.string_at(address, size),
                    )[1],
                )
                if failure == "sync":
                    fileio.sync_error = OSError("post-completion sync failure")
                if failure == "save":
                    original_save = recorder.save
                    save_failed = []

                    def fail_once_after_submit():
                        if action_calls and not save_failed:
                            save_failed.append(True)
                            raise OSError("post-completion receipt save failure")
                        original_save()

                    recorder.save = fail_once_after_submit

                with patch("tools.rk_capture.os.fstat", return_value=SimpleNamespace(
                    st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"]
                )):
                    with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                        cmd = device._gpu_alloc(16)
                        task = device._gpu_alloc(ctypes.sizeof(rk.struct_rknpu_task))
                        request, payload, _ = self.valid_submit(rk, cmd, task)
                        with self.assertRaises(OSError):
                            device.fd_ctl.ioctl(request, payload)

                        row = recorder.submissions[0]
                        self.assertTrue(row["blocking_completion_confirmed"])
                        self.assertEqual(row["status"], "FAIL_CAPTURE")
                        self.assertNotIn("after", row)
                        self.assertTrue(recorder.failed)
                        self.assertTrue(device._poisoned)
                        # A subsequent intercepted request is rejected by the failed session;
                        # it must not call the original blocking ioctl again.
                        with self.assertRaises(RuntimeError):
                            device.fd_ctl.ioctl(request, payload)

                self.assertEqual(action_calls, ["submit"])
                self.assertEqual(sum(req == request for req, _ in fileio.calls), 1)
                report = json.loads((recorder.out / "report.json").read_text())
                self.assertTrue(report["capture_failed"])
                self.assertTrue(report["submissions"][0]["blocking_completion_confirmed"])
                self.assertEqual(report["submissions"][0]["status"], "FAIL_CAPTURE")
                self.assertNotIn("after", report["submissions"][0])

    def test_bad_extent_and_registration_failures_cleanup_exact_new_buffer(self):
        class BadExtentDevice(FakeRockchipDevice):
            def _gpu_alloc(self, size, flags=0):
                buffer = super()._gpu_alloc(size, flags)
                buffer.meta.size -= 1
                self.last = buffer
                return buffer

        class DuplicateObjectDevice(FakeRockchipDevice):
            def _gpu_alloc(self, size, flags=0):
                buffer = super()._gpu_alloc(size, flags)
                if len(self.allocation_calls) > 1:
                    buffer.meta.obj_addr = self.first.meta.obj_addr
                else:
                    self.first = buffer
                self.last = buffer
                return buffer

        class CleanupFailureDevice(BadExtentDevice):
            def _gpu_free(self, buf):
                self.free_calls.append(buf.meta.obj_addr)
                self.freed_buffers.append(buf)
                raise OSError("cleanup free failed")

        for device_type, message, expected_cleanup, cleanup_error in (
            (BadExtentDevice, "Driver BO extent differs", True, False),
            (DuplicateObjectDevice, "Duplicate live BO object/handle", True, False),
            (CleanupFailureDevice, "Driver BO extent differs", False, True),
        ):
            with self.subTest(device_type=device_type.__name__, cleanup=expected_cleanup), TemporaryDirectory() as tmp:
                trace = []
                runtime = SimpleNamespace(RockchipDevice=device_type, FileIOInterface=FakeFileIO)
                rk = fake_abi()
                device = device_type(FakeFileIO(trace), trace)
                recorder = self.recorder(Path(tmp) / "capture", trace)
                with patch("tools.rk_capture.os.fstat", return_value=SimpleNamespace(
                    st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"]
                )):
                    with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                        if device_type is DuplicateObjectDevice:
                            original = device._gpu_alloc(8)
                            self.assertIn(original.meta.obj_addr, recorder.buffers)
                        before_frees = len(device.free_calls)
                        with self.assertRaisesRegex(RuntimeError, message) as caught:
                            device._gpu_alloc(8)
                        failed = device.last
                        self.assertEqual(len(device.free_calls) - before_frees, 1)
                        cleanup = [e for e in recorder.events if e["kind"] == "unregistered_allocation_cleanup"][-1]
                        self.assertEqual(cleanup["completed"], expected_cleanup)
                        if cleanup_error:
                            self.assertIn("cleanup free failed", cleanup["error"])
                            self.assertIn("cleanup free failed", " ".join(getattr(caught.exception, "__notes__", [])))
                        if device_type is DuplicateObjectDevice:
                            original_record = recorder.buffers[original.meta.obj_addr]
                            self.assertEqual(failed.meta.obj_addr, original.meta.obj_addr)
                            self.assertIs(recorder.buffers[original.meta.obj_addr], original_record)
                            with self.assertRaisesRegex(RuntimeError, "Free metadata differs"):
                                device._gpu_free(failed)
                            self.assertEqual(len(device.free_calls) - before_frees, 1)
                        self.assertTrue(recorder.failed)
                        self.assertTrue(device._poisoned)

    def test_registration_receipt_failure_rolls_back_and_cleans_once(self):
        with TemporaryDirectory() as tmp:
            trace = []
            runtime, rk, device, _fileio = self.build_device(trace)
            recorder = self.recorder(Path(tmp) / "capture", trace)
            original_save = recorder.save
            failures = []

            def fail_first_register_save():
                if not failures:
                    failures.append(True)
                    raise OSError("allocation receipt save failure")
                original_save()

            recorder.save = fail_first_register_save
            with patch("tools.rk_capture.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"]
            )):
                with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                    with self.assertRaisesRegex(OSError, "allocation receipt save failure"):
                        device._gpu_alloc(8)
                    allocated = device.freed_buffers[0]
                    obj = allocated.meta.obj_addr
                    self.assertNotIn(obj, recorder.buffers)
                    self.assertEqual(device.free_calls.count(obj), 1)
                    cleanup = next(e for e in recorder.events if e["kind"] == "unregistered_allocation_cleanup")
                    self.assertTrue(cleanup["completed"])
                    self.assertTrue(any(e["kind"] == "allocation_registration_failed" for e in recorder.events))
                    with self.assertRaisesRegex(RuntimeError, "Untracked free"):
                        device._gpu_free(allocated)
                    self.assertEqual(device.free_calls.count(obj), 1)
            report = json.loads((recorder.out / "report.json").read_text())
            self.assertEqual(report["live_allocations"], [])
            self.assertTrue(report["capture_failed"])

    def test_failed_free_evicts_unmapped_extent_and_never_retries_destroy(self):
        class FreeDestroyFailureDevice(FakeRockchipDevice):
            def _gpu_free(self, buffer):
                self.free_calls.append(buffer.meta.obj_addr)
                self.freed_buffers.append(buffer)  # Model that VA unmap already happened.
                raise OSError("mock destroy ioctl failure after unmap")

        with TemporaryDirectory() as tmp:
            trace = []
            runtime = SimpleNamespace(RockchipDevice=FreeDestroyFailureDevice, FileIOInterface=FakeFileIO)
            rk = fake_abi()
            device = FreeDestroyFailureDevice(FakeFileIO(trace), trace)
            recorder = self.recorder(Path(tmp) / "capture", trace)
            with patch("tools.rk_capture.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"]
            )):
                with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                    buffer = device._gpu_alloc(16)
                    obj = buffer.meta.obj_addr
                    with self.assertRaisesRegex(OSError, "destroy ioctl failure") as caught:
                        device._gpu_free(buffer)
                    self.assertEqual(device.free_calls, [obj])
                    self.assertNotIn(obj, recorder.buffers)
                    self.assertTrue(recorder.failed)
                    self.assertTrue(device._poisoned)
                    failed = next(e for e in recorder.events if e["kind"] == "free_failed")
                    self.assertEqual(failed["ownership"], "UNMAP_OR_DESTROY_OUTCOME_UNKNOWN")
                    with self.assertRaisesRegex(RuntimeError, "Untracked free"):
                        device._gpu_free(buffer)
                    self.assertEqual(device.free_calls, [obj])
                    self.assertEqual(getattr(caught.exception, "__notes__", []), [])
            report = json.loads((recorder.out / "report.json").read_text())
            self.assertEqual(report["live_allocations"], [])
            self.assertTrue(report["capture_failed"])

    def test_concurrent_allocation_and_free_wait_until_blocking_capture_releases_lock(self):
        with TemporaryDirectory() as tmp:
            trace = []
            entered_read = threading.Event()
            release_read = threading.Event()
            read_calls = []

            def read(address, size):
                read_calls.append(address)
                if len(read_calls) == 1:
                    entered_read.set()
                    if not release_read.wait(timeout=4):
                        raise TimeoutError("test did not release capture read")
                return ctypes.string_at(address, size)

            runtime, rk, device, fileio = self.build_device(trace)
            recorder = self.recorder(Path(tmp) / "capture", trace, read=read)
            failure = []
            alloc_started, alloc_done = threading.Event(), threading.Event()
            free_started, free_done = threading.Event(), threading.Event()
            rendezvous = threading.Barrier(3)
            results = {}

            def allocate_worker():
                try:
                    rendezvous.wait(timeout=2)
                    alloc_started.set()
                    results["allocated"] = device._gpu_alloc(8)
                except BaseException as error:
                    failure.append(error)
                finally:
                    alloc_done.set()

            def free_worker():
                try:
                    rendezvous.wait(timeout=2)
                    free_started.set()
                    device._gpu_free(free_target)
                except BaseException as error:
                    failure.append(error)
                finally:
                    free_done.set()

            alloc_thread = threading.Thread(target=allocate_worker, name="concurrent-allocation")
            free_thread = threading.Thread(target=free_worker, name="concurrent-free")
            with patch("tools.rk_capture.os.fstat", return_value=SimpleNamespace(
                st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"]
            )), rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                cmd = device._gpu_alloc(16)
                task = device._gpu_alloc(ctypes.sizeof(rk.struct_rknpu_task))
                request, payload, _ = self.valid_submit(rk, cmd, task)
                results["request"] = request
                initial_allocations = len(device.allocation_calls)
                initial_frees = len(device.free_calls)
                free_target = cmd
                capture_thread = threading.Thread(
                    target=lambda: self._capture_thread_action(device, request, payload, failure, results),
                    name="capture-submit",
                )
                capture_thread.start()
                self.assertTrue(entered_read.wait(timeout=2), "blocking capture did not reach pre-submit read")
                alloc_thread = threading.Thread(target=allocate_worker, name="concurrent-allocation")
                free_thread = threading.Thread(target=free_worker, name="concurrent-free")
                alloc_thread.start()
                free_thread.start()
                rendezvous.wait(timeout=2)
                self.assertTrue(alloc_started.wait(timeout=1))
                self.assertTrue(free_started.wait(timeout=1))
                self.assertFalse(alloc_done.wait(timeout=0.05))
                self.assertFalse(free_done.wait(timeout=0.05))
                self.assertEqual(len(device.allocation_calls), initial_allocations)
                self.assertEqual(len(device.free_calls), initial_frees)

                release_read.set()
                for thread in (capture_thread, alloc_thread, free_thread):
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive(), f"thread did not finish: {thread.name}")
                self.assertEqual(failure, [])
                self.assertEqual(results.get("submit"), 0)
                self.assertEqual(len(device.allocation_calls), initial_allocations + 1)
                self.assertEqual(len(device.free_calls), initial_frees + 1)
                self.assertEqual(sum(req == request for req, _ in fileio.calls), 1)

    @staticmethod
    def _capture_thread_action(device, request, payload, failures, results):
        try:
            results["submit"] = device.fd_ctl.ioctl(request, payload)
        except BaseException as error:
            failures.append(error)

    def test_same_thread_inflight_allocation_and_free_are_rejected_pre_original(self):
        for operation in ("allocate", "free"):
            with self.subTest(operation=operation), TemporaryDirectory() as tmp:
                trace = []
                runtime, rk, device, _fileio = self.build_device(trace)
                recorder = self.recorder(Path(tmp) / "capture", trace)
                with patch("tools.rk_capture.os.fstat", return_value=SimpleNamespace(
                    st_mode=stat.S_IFCHR | 0o600, st_rdev=self.identity["rdev"]
                )):
                    with rk_capture.observe_backend(runtime, rk, recorder, self.identity):
                        cmd = device._gpu_alloc(16)
                        task = device._gpu_alloc(ctypes.sizeof(rk.struct_rknpu_task))
                        request, payload, _ = self.valid_submit(rk, cmd, task)
                        prior_allocs, prior_frees = len(device.allocation_calls), len(device.free_calls)
                        callback_errors = []

                        def mutate_during_submit():
                            try:
                                if operation == "allocate":
                                    device._gpu_alloc(8)
                                else:
                                    device._gpu_free(cmd)
                            except BaseException as error:
                                callback_errors.append(error)
                                raise

                        device.fd_ctl.on_submit = mutate_during_submit
                        with self.assertRaisesRegex(RuntimeError, "Allocation during failed/blocking capture|Untracked free"):
                            device.fd_ctl.ioctl(request, payload)
                        self.assertEqual(len(device.allocation_calls), prior_allocs)
                        self.assertEqual(len(device.free_calls), prior_frees)
                        self.assertEqual(len(callback_errors), 1)


if __name__ == "__main__":
    unittest.main()
