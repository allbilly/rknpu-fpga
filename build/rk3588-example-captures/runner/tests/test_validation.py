"""Host-only tests for bundle validation. No device access."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER))

import rocket_run as rr  # noqa: E402
from bundle_factory import make_case, write_job  # noqa: E402


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.case = make_case(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_bundle_and_fields(self) -> None:
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertEqual(errors, [])
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertEqual(bundle.case, "tiny_case")
        self.assertEqual(bundle.regcmd_words, 22)
        self.assertEqual(len(bundle.tasks), 1)
        self.assertEqual(len(bundle.buffers), 2)
        self.assertEqual(len(bundle.patches), 1)
        self.assertEqual(bundle.buffers[0].input_data, bytes(range(32)))

    def test_output_root_checks(self) -> None:
        out = self.root / "out"
        bundle, errors = rr.load_and_validate_case(self.case, out)
        self.assertEqual(errors, [])
        self.assertIsNotNone(bundle)
        (out / "tiny_case").mkdir(parents=True)
        bundle, errors = rr.load_and_validate_case(self.case, out)
        self.assertIsNone(bundle)
        self.assertTrue(any("already exists" in e for e in errors), errors)

    def test_missing_job(self) -> None:
        (self.case / "job.json").unlink()
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("missing job.json" in e for e in errors), errors)

    def test_missing_field(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        del job["description"]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("missing field(s): description" in e for e in errors), errors)

    def test_unknown_top_level_field(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["surprise"] = 1
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("unknown field(s): surprise" in e for e in errors), errors)

    def test_duplicate_json_key(self) -> None:
        (self.case / "job.json").write_text(
            '{"case": "a", "case": "b"}\n', encoding="utf-8"
        )
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("duplicate JSON key" in e for e in errors), errors)

    def test_nonstandard_json_constant(self) -> None:
        (self.case / "job.json").write_text('{"case": NaN}\n', encoding="utf-8")
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("non-standard JSON constant" in e for e in errors), errors)

    def test_duplicate_buffer_name(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"][1]["name"] = "a"
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("duplicate buffer name" in e for e in errors), errors)

    def test_missing_input_file(self) -> None:
        (self.case / "a.bin").unlink()
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("cannot stat" in e and "a.bin" in e for e in errors), errors)

    def test_input_size_mismatch(self) -> None:
        (self.case / "a.bin").write_bytes(b"\x00" * 31)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("but buffers[0].size is 32" in e for e in errors), errors)

    def test_regcmd_length_not_multiple_of_eight(self) -> None:
        with (self.case / "regcmd.bin").open("ab") as stream:
            stream.write(b"\x00")
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("not a multiple of 8" in e for e in errors), errors)

    def test_missing_or_empty_regcmd(self) -> None:
        (self.case / "regcmd.bin").unlink()
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("missing regcmd.bin" in e for e in errors), errors)

        (self.case / "regcmd.bin").write_bytes(b"")
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("regcmd.bin is empty" in e for e in errors), errors)

    def test_patch_out_of_range(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["patches"][0]["regcmd_index"] = 22
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("outside regcmd.bin" in e for e in errors), errors)

    def test_patch_bad_kind_and_unknown_buffer(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["patches"][0]["kind"] = "nope"
        job["patches"][0]["buffer"] = "ghost"
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("unknown buffer 'ghost'" in e for e in errors), errors)
        self.assertTrue(any("expected one of" in e for e in errors), errors)

    def test_patch_overlap_on_same_qword(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["patches"] = [
            {"regcmd_index": 3, "buffer": "a", "kind": "value32"},
            {"regcmd_index": 3, "buffer": "out", "kind": "low32"},
        ]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("overlaps an earlier patch" in e for e in errors), errors)

    def test_patch_high_and_low_on_same_qword_is_allowed(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["patches"] = [
            {"regcmd_index": 3, "buffer": "a", "kind": "high32"},
            {"regcmd_index": 3, "buffer": "out", "kind": "low32"},
        ]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertEqual(errors, [])
        self.assertIsNotNone(bundle)

    def test_task_odd_offset(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["tasks"] = [{"regcmd_offset_words": 1, "regcmd_words": 8}]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("16-byte aligned" in e for e in errors), errors)

    def test_task_odd_word_count_fetches_one_extra(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["tasks"] = [{"regcmd_offset_words": 0, "regcmd_words": 7}]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertEqual(errors, [])
        self.assertIsNotNone(bundle)
        self.assertEqual(rr.regcmd_fetch_words(7), 8)

        job["tasks"] = [{"regcmd_offset_words": 20, "regcmd_words": 3}]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("fetch as QWORD pairs" in e for e in errors), errors)

    def test_odd_fetch_ranges_detect_overlap(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["tasks"] = [
            {"regcmd_offset_words": 0, "regcmd_words": 7},
            {"regcmd_offset_words": 2, "regcmd_words": 4},
        ]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("QWORD-pair fetch range" in e for e in errors), errors)

    def test_task_range_beyond_regcmd(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["tasks"] = [{"regcmd_offset_words": 20, "regcmd_words": 8}]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("exceed regcmd.bin" in e for e in errors), errors)

    def test_task_overlap(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["tasks"] = [
            {"regcmd_offset_words": 0, "regcmd_words": 12},
            {"regcmd_offset_words": 8, "regcmd_words": 10},
        ]
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("overlap in the QWORD-pair fetch range" in e for e in errors), errors)

    def test_duplicate_output_name(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"].append(
            {"name": "out2", "size": 16, "direction": "out", "output": "out.bin"}
        )
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("duplicate output filename" in e for e in errors), errors)

    def test_reserved_capture_output_name(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"][1]["output"] = "capture.json"
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("reserved for capture.json" in e for e in errors), errors)

    def test_capture_json_parent_path_is_rejected(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"][1]["output"] = "capture.json/nested.bin"
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("reserved for capture.json" in e for e in errors), errors)

    def test_output_parent_path_conflict_is_rejected(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"][1]["output"] = "nested"
        job["buffers"].append(
            {"name": "out2", "size": 16, "direction": "out", "output": "nested/out.bin"}
        )
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("is a parent path" in e for e in errors), errors)

    def test_absolute_and_traversal_outputs(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"][1]["output"] = "/tmp/out.bin"
        write_job(self.case, job)
        _, errors = rr.load_and_validate_case(self.case)
        self.assertTrue(any("must be relative" in e for e in errors), errors)

        job["buffers"][1]["output"] = "../out.bin"
        write_job(self.case, job)
        _, errors = rr.load_and_validate_case(self.case)
        self.assertTrue(any("must not contain" in e for e in errors), errors)

    def test_no_output_buffer_is_rejected(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"] = [{"name": "a", "size": 32, "input": "a.bin", "direction": "in"}]
        job["patches"] = []
        write_job(self.case, job)
        bundle, errors = rr.load_and_validate_case(self.case)
        self.assertIsNone(bundle)
        self.assertTrue(any("at least one buffer" in e for e in errors), errors)

    def test_unknown_nested_fields(self) -> None:
        job = rr.read_json_strict(self.case / "job.json")
        job["buffers"][0]["extra"] = True
        write_job(self.case, job)
        _, errors = rr.load_and_validate_case(self.case)
        self.assertTrue(any("buffers[0]: unknown field(s): extra" in e for e in errors), errors)

    def test_output_root_inside_case_is_rejected(self) -> None:
        bundle, errors = rr.load_and_validate_case(self.case, self.case / "captures")
        self.assertIsNone(bundle)
        self.assertTrue(any("inside it" in e for e in errors), errors)

    def test_validator_cli_exit_codes_and_overwrite(self) -> None:
        validator = RUNNER / "validate_bundle.py"
        result = subprocess.run(
            [sys.executable, str(validator), str(self.case)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)

        out = self.root / "cli-out"
        (out / "tiny_case").mkdir(parents=True)
        result = subprocess.run(
            [sys.executable, str(validator), "--output-dir", str(out), str(self.case)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("already exists", result.stdout)

    def test_validator_cli_family_queue(self) -> None:
        family = self.root / "family"
        (family / "cases").mkdir(parents=True)
        (family / "cases" / "one").symlink_to(self.case, target_is_directory=True)
        result = subprocess.run(
            [sys.executable, str(RUNNER / "validate_bundle.py"), str(family)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validator_rejects_duplicate_case_names_in_queue(self) -> None:
        family = self.root / "family"
        (family / "cases").mkdir(parents=True)
        make_case(
            family / "cases",
            case_name="dup_case",
            directory_name="first",
        )
        make_case(
            family / "cases",
            case_name="dup_case",
            directory_name="second",
        )
        result = subprocess.run(
            [sys.executable, str(RUNNER / "validate_bundle.py"), str(family)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate case name", result.stdout)


if __name__ == "__main__":
    unittest.main()
