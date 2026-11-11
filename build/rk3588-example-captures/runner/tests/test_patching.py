"""Host-only tests for pure Rocket parsing, patching and descriptor logic."""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RUNNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER))

import rocket_run as rr  # noqa: E402
from bundle_factory import make_case, write_job  # noqa: E402


class FakeMapping:
    """Small mmap-like object used to exercise the runner without a device."""

    def __init__(self, size: int):
        self.data = bytearray(size)
        self.closed = False

    def __getitem__(self, key):
        if isinstance(key, slice):
            return bytes(self.data[key])
        return self.data[key]

    def __setitem__(self, key, value) -> None:
        self.data[key] = value

    def close(self) -> None:
        self.closed = True


class FakeRocketFD:
    """Deterministic in-process stand-in for RocketFD."""

    def __init__(self, path):
        self.path = str(path)
        self.audit = {"path": self.path, "driver": "rocket", "fake": True}
        self.closed = False
        self.handles = 1
        self.next_dma = 0x10000
        self.bos = {}

    def create_bo(self, role, name, size):
        bo = rr.RocketBO(
            role=role,
            name=name,
            size=size,
            handle=self.handles,
            dma_address=self.next_dma,
            mmap_offset=0x1000 * self.handles,
            mapping_size=size,
            mapping=FakeMapping(size),
        )
        self.handles += 1
        self.next_dma += (size + 0xFFF) & ~0xFFF
        self.bos[name] = bo
        return bo

    def prep_bo(self, handle, timeout_ns):
        if timeout_ns <= 0:
            raise AssertionError("prep timeout must be positive")

    def fini_bo(self, handle):
        pass

    def submit(self, payload):
        self.bos["out"].mapping[0:4] = b"NPU!"
        return 0

    def gem_close(self, handle):
        pass

    def close(self):
        self.closed = True


class UapiLayoutTests(unittest.TestCase):
    def test_ioctl_numbers_and_struct_sizes(self) -> None:
        self.assertEqual(rr.DRM_IOCTL_ROCKET_CREATE_BO, 0xC0186440)
        self.assertEqual(rr.DRM_IOCTL_ROCKET_SUBMIT, 0x40186441)
        self.assertEqual(rr.DRM_IOCTL_ROCKET_PREP_BO, 0x40106442)
        self.assertEqual(rr.DRM_IOCTL_ROCKET_FINI_BO, 0x40086443)
        self.assertEqual(rr.DRM_IOCTL_GEM_CLOSE, 0x40086409)

    def test_packed_job_and_submit_offsets(self) -> None:
        job = rr.pack_job(0x1111, 0x2222, 0x3333, 2, 3, 4)
        self.assertEqual(
            struct.unpack("<QQQIIII", job),
            (0x1111, 0x2222, 0x3333, 2, 8, 3, 4),
        )
        self.assertEqual(
            struct.unpack("<QIIQ", rr.pack_submit(0x4444)),
            (0x4444, 1, 40, 0),
        )
        self.assertEqual(
            struct.unpack("<IIq", struct.pack("<IIq", 7, 0, 123)),
            (7, 0, 123),
        )


class PatchingTests(unittest.TestCase):
    def test_value32(self) -> None:
        qword = 0x0201_0000_0000_1234
        patched, mask = rr.patch_qword(qword, "value32", 0x89ABCDEF)
        self.assertEqual(mask, 0x0000FFFFFFFF0000)
        self.assertEqual(patched & 0xFFFF000000000000, qword & 0xFFFF000000000000)
        self.assertEqual(patched & 0x000000000000FFFF, 0x1234)
        self.assertEqual((patched >> 16) & 0xFFFFFFFF, 0x89ABCDEF)

    def test_all32_and_low32_are_identical_per_spec(self) -> None:
        qword = 0xFFFF_FFFF_0000_0000
        all32, _ = rr.patch_qword(qword, "all32", 0x12345678)
        low32, _ = rr.patch_qword(qword, "low32", 0x12345678)
        self.assertEqual(all32, 0xFFFFFFFF12345678)
        self.assertEqual(all32, low32)

    def test_high32(self) -> None:
        qword = 0x0000_0000_DEAD_BEEF
        patched, mask = rr.patch_qword(qword, "high32", 0x123456789ABCDEF0)
        self.assertEqual(mask, 0xFFFFFFFF00000000)
        self.assertEqual(patched, 0x12345678DEADBEEF)

    def test_32bit_kinds_reject_truncation(self) -> None:
        with self.assertRaises(rr.PatchError):
            rr.patch_qword(0, "value32", 0x1_0000_0000)
        with self.assertRaises(rr.PatchError):
            rr.patch_qword(0, "all32", 0x1_0000_0000)

    def test_apply_patches_sequential_non_overlapping(self) -> None:
        regcmd = struct.pack("<Q", 0xAAAAAAAAAAAAAAAA) + struct.pack("<Q", 0)
        patches = [
            rr.PatchSpec(0, "a", "high32"),
            rr.PatchSpec(0, "b", "low32"),
        ]
        data, applied = rr.apply_patches(
            regcmd, patches, {"a": 0x123456789ABCDEF0, "b": 0xCAFEBABE}
        )
        self.assertEqual(
            struct.unpack_from("<Q", data, 0)[0], 0x12345678CAFEBABE
        )
        self.assertEqual(len(applied), 2)
        self.assertEqual(applied[0]["before"], 0xAAAAAAAAAAAAAAAA)

    def test_apply_patches_rejects_overlap_and_range(self) -> None:
        regcmd = struct.pack("<Q", 0) * 2
        with self.assertRaises(rr.PatchError):
            rr.apply_patches(
                regcmd,
                [
                    rr.PatchSpec(0, "a", "low32"),
                    rr.PatchSpec(0, "b", "low32"),
                ],
                {"a": 1, "b": 2},
            )
        with self.assertRaises(rr.PatchError):
            rr.apply_patches(
                regcmd, [rr.PatchSpec(2, "a", "low32")], {"a": 1}
            )
        with self.assertRaises(rr.PatchError):
            rr.apply_patches(
                regcmd, [rr.PatchSpec(0, "missing", "low32")], {"a": 1}
            )

    def test_apply_patches_bad_regcmd_length(self) -> None:
        with self.assertRaises(rr.PatchError):
            rr.apply_patches(b"\x00", [], {})


class DescriptorTests(unittest.TestCase):
    def test_task_addresses_follow_offset(self) -> None:
        descriptors = rr.build_task_descriptors(
            [rr.TaskSpec(0, 22), rr.TaskSpec(24, 8)], 0x1000
        )
        self.assertEqual(descriptors[0].regcmd, 0x1000)
        self.assertEqual(descriptors[1].regcmd, 0x1000 + 24 * 8)
        packed = rr.pack_task_descriptors(descriptors)
        self.assertEqual(
            struct.unpack("<IIII", packed),
            (0x1000, 22, 0x10C0, 8),
        )
        odd = rr.build_task_descriptors([rr.TaskSpec(0, 7)], 0x1000)
        self.assertEqual(odd[0].regcmd_count, 7)
        self.assertEqual(rr.regcmd_fetch_words(7), 8)

    def test_descriptor_alignment_and_u32_limits(self) -> None:
        with self.assertRaises(rr.DescriptorError):
            rr.build_task_descriptors([rr.TaskSpec(1, 8)], 0x1000)
        with self.assertRaises(rr.DescriptorError):
            rr.build_task_descriptors([rr.TaskSpec(0, 8)], 0x1008)
        with self.assertRaises(rr.DescriptorError):
            rr.build_task_descriptors([rr.TaskSpec(0, 8)], 0x1_0000_0000)
        with self.assertRaises(rr.DescriptorError):
            rr.build_task_descriptors([rr.TaskSpec(2, 8)], 0xFFFF_FFF0)

    def test_handle_partitioning(self) -> None:
        in_buf = rr.BufferSpec("a", 1, "in")
        out_buf = rr.BufferSpec("b", 1, "out")
        inout_buf = rr.BufferSpec("c", 1, "inout")
        ins, outs = rr.partition_handles(
            [in_buf, out_buf, inout_buf], {"a": 11, "b": 12, "c": 13}, 10
        )
        self.assertEqual(ins, [10, 11])
        self.assertEqual(outs, [12, 13])

    def test_handle_duplicate_rejected(self) -> None:
        with self.assertRaises(rr.CaseError):
            rr.partition_handles(
                [rr.BufferSpec("a", 1, "in")], {"a": 10}, 10
            )


class QueueAndFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_expand_family_queue_sorted(self) -> None:
        family = self.root / "family"
        (family / "cases").mkdir(parents=True)
        make_case(family / "cases", case_name="z_case")
        make_case(family / "cases", case_name="a_case")
        cases, errors = rr.expand_case_arguments([family])
        self.assertEqual(errors, [])
        self.assertEqual([p.name for p in cases], ["a_case", "z_case"])

    def test_expand_rejects_non_case_directory(self) -> None:
        path = self.root / "empty"
        path.mkdir()
        cases, errors = rr.expand_case_arguments([path])
        self.assertEqual(cases, [])
        self.assertTrue(errors)

    def test_validate_only_never_opens_device(self) -> None:
        case = make_case(self.root)
        with mock.patch.object(rr, "RocketFD", side_effect=AssertionError("device opened")):
            rc = rr.main(["--validate-only", str(case)])
        self.assertEqual(rc, 0)

    def test_device_open_failure_records_fail_and_writes_no_output(self) -> None:
        case = make_case(self.root)
        out = self.root / "out"
        bundle, errors = rr.load_and_validate_case(case, out)
        self.assertEqual(errors, [])
        assert bundle is not None
        with mock.patch.object(
            rr, "RocketFD", side_effect=OSError(19, "No such device")
        ):
            capture = rr.run_case(bundle, out, "/dev/accel/accel0")
        self.assertEqual(capture["status"], "FAIL")
        self.assertIsNone(capture["submit_ret"])
        self.assertTrue(capture["errors"])
        self.assertFalse((out / "tiny_case" / "out.bin").exists())
        self.assertTrue((out / "tiny_case" / "capture.json").is_file())

    def test_run_case_refuses_existing_output_before_device(self) -> None:
        case = make_case(self.root)
        out = self.root / "out"
        bundle, errors = rr.load_and_validate_case(case)
        self.assertEqual(errors, [])
        assert bundle is not None
        (out / "tiny_case").mkdir(parents=True)
        with mock.patch.object(rr, "RocketFD") as rocket_fd:
            capture = rr.run_case(bundle, out, "/dev/accel/accel0")
        rocket_fd.assert_not_called()
        self.assertEqual(capture["status"], "FAIL")
        self.assertTrue(any("already exists" in e for e in capture["errors"]))

    def test_successful_case_with_fake_uapi(self) -> None:
        case = make_case(self.root)
        out = self.root / "out"
        bundle, errors = rr.load_and_validate_case(case, out)
        self.assertEqual(errors, [])
        assert bundle is not None
        with mock.patch.object(rr, "RocketFD", FakeRocketFD):
            capture = rr.run_case(bundle, out, "/dev/accel/accel0")
        self.assertEqual(capture["status"], "OK", capture["errors"])
        self.assertEqual(capture["submit_ret"], 0)
        self.assertEqual(capture["errors"], [])
        output = (out / "tiny_case" / "out.bin").read_bytes()
        self.assertEqual(output[:4], b"NPU!")
        self.assertEqual(capture["outputs"][0]["size"], 32)
        capture_json = out / "tiny_case" / "capture.json"
        self.assertTrue(capture_json.is_file())
        embedded = rr.read_json_strict(capture_json)
        self.assertEqual(embedded["status"], "OK")
        self.assertEqual(embedded["submit_ret"], 0)
        self.assertEqual(embedded["device_path"], "/dev/accel/accel0")
        self.assertIn("durations", embedded)
        self.assertIn("hashes", embedded)
        self.assertIn("addresses", embedded)

    def test_queue_continues_after_invalid_case(self) -> None:
        family = self.root / "family"
        (family / "cases").mkdir(parents=True)
        invalid = make_case(family / "cases", case_name="bad_case")
        job = rr.read_json_strict(invalid / "job.json")
        del job["description"]
        write_job(invalid, job)
        make_case(family / "cases", case_name="good_case")
        out = self.root / "out"
        with mock.patch.object(rr, "RocketFD", FakeRocketFD):
            rc = rr.run_queue([family], out, "/dev/accel/accel0")
        self.assertEqual(rc, 1)
        bad_capture = rr.read_json_strict(out / "bad_case" / "capture.json")
        good_capture = rr.read_json_strict(out / "good_case" / "capture.json")
        self.assertEqual(bad_capture["status"], "FAIL")
        self.assertEqual(good_capture["status"], "OK")
        self.assertTrue((out / "good_case" / "out.bin").is_file())

    def test_missing_job_failure_uses_directory_name(self) -> None:
        family = self.root / "family"
        broken = family / "cases" / "broken_case"
        broken.mkdir(parents=True)
        out = self.root / "out"
        rc = rr.run_queue([family], out, "/dev/accel/accel0")
        self.assertEqual(rc, 1)
        capture = rr.read_json_strict(out / "broken_case" / "capture.json")
        self.assertEqual(capture["status"], "FAIL")
        self.assertTrue(any("missing job.json" in e for e in capture["errors"]))


if __name__ == "__main__":
    unittest.main()
