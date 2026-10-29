"""Pure-Python contract controls for schema-3 packet-scoped READ64 receipts.

These tests fabricate only result-marker text and readback files. They never
launch a simulator, device runner, Vivado, or hardware command.
"""
from pathlib import Path
import tempfile
import unittest

from tools.ddr import async_endpoint_contract as legacy
from tools.ddr import endpoint_vectors, read_snapshot_contract as contract
from tools.ddr import run_async_endpoint as legacy_runner
from tools.ddr import run_read_snapshot_endpoint as snapshot_runner


class ReadSnapshotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="read-snapshot-contract-")
        cls.root = Path(cls.temp.name)
        cls.vector_root = cls.root / "vectors"
        cls.original_specs = endpoint_vectors.generate(cls.vector_root)
        cls.specs = snapshot_runner.expanded_specs(cls.original_specs)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def spec(self, name):
        return next(s for s in self.specs if s["name"] == name)

    def marker(self, spec, metrics):
        jobs = 0 if spec["negative"] == 9 else spec["jobs"] + int(bool(spec["reset_recovery"]))
        returns = metrics["phy_user_returns"]
        if returns is None:
            returns = metrics["phy_user_returns_minimum"]
        return (
            "PASS jtag_ew_ddr_read_snapshot "
            f"jobs={jobs} negative={spec['negative']} recovered={int(bool(spec['reset_recovery']))} "
            f"lines={metrics['lines']} uploaded_nonzero={metrics['uploaded_nonzero']} "
            f"rawtasks={spec['tasks']} phy_user_returns={returns} "
            f"read64_packets={metrics['host_read64_packets']} "
            f"read64_axi_reads={metrics['host_read64_axi_reads']} "
            "scope=actual_AXI_UI_MC_modeled_PHY"
        )

    def evaluate(self, spec_name, *, marker_edit=None, code=0, output="auto", extra_lines=(),
                 checked_line="default"):

        spec = self.spec(spec_name)
        metrics = contract.metrics(spec, self.vector_root)
        marker = self.marker(spec, metrics)
        if marker_edit is not None:
            marker = marker_edit(marker, metrics, spec)
        lines = []
        if spec["negative"] == 10:
            if checked_line == "default":
                lines.append("CHECKED partial_task_fault completed=1 ui_code=5")
            elif checked_line is not None:
                lines.append(checked_line)
        lines.extend(extra_lines)
        lines.append(marker)
        expected = self.vector_root / spec["case"] / "expected.txt"
        with tempfile.TemporaryDirectory(prefix="read-snapshot-result-") as name:
            observed = Path(name) / "observed.txt"
            should_write = metrics["successful_jobs"] > 0 if output == "auto" else output != "missing"
            if should_write:
                observed.write_bytes(expected.read_bytes())
                if output == "changed":
                    data = observed.read_bytes()
                    observed.write_bytes(bytes([data[0] ^ 1]) + data[1:])
                elif output == "truncated":
                    observed.write_bytes(observed.read_bytes()[:-138])
            text = "\n".join(lines) + "\n"
            return contract.check_result(text, code, spec, metrics, observed, expected)

    def assert_rejected(self, *args, **kwargs):
        with self.assertRaises(ValueError):
            self.evaluate(*args, **kwargs)

    def test_original_vectors_and_all_21_scenarios_are_preserved(self):
        self.assertEqual(endpoint_vectors.verify_vectors(self.vector_root), self.original_specs)
        self.assertEqual(len(self.original_specs), 20)
        self.assertEqual(len(self.specs), 21)
        self.assertEqual(self.specs[:20], self.original_specs)
        self.assertEqual(self.specs[20]["name"], "partial_task_fault")
        self.assertEqual(self.specs[20]["case"], "capture_sub_9")
        self.assertEqual(self.specs[20]["negative"], 10)
        self.assertEqual(contract.selection(self.specs, None), self.specs)
        self.assertEqual(len(contract.selection(self.specs, ["capture_add_8", "partial_task_fault"])), 2)
        for bad in (["not_a_case"], ["capture_add_8", "capture_add_8"]):
            with self.assertRaises(ValueError):
                contract.selection(self.specs, bad)
        with self.assertRaises(ValueError):
            contract.selection(self.specs[:-1], None)

    def test_static_repeat_and_reset_packet_metrics_keep_legacy_counts(self):
        repeat = self.spec("repeat_sub_9")
        old_repeat = legacy.metrics(repeat, self.vector_root)
        new_repeat = contract.metrics(repeat, self.vector_root)
        self.assertEqual(old_repeat["phy_user_returns"], 108107)
        self.assertEqual(new_repeat["uncached_phy_user_returns"], 108107)
        self.assertEqual((new_repeat["phy_user_returns"], new_repeat["host_read64_packets"],
                          new_repeat["host_read64_axi_reads"]), (8845, 3202, 3202))

        reset = self.spec("joint_reset_recovery")
        old_reset = legacy.metrics(reset, self.vector_root)
        new_reset = contract.metrics(reset, self.vector_root)
        self.assertEqual(old_reset["phy_user_returns"], 56486)
        self.assertEqual(new_reset["uncached_phy_user_returns"], 56486)
        self.assertEqual((new_reset["phy_user_returns"], new_reset["host_read64_packets"],
                          new_reset["host_read64_axi_reads"]), (6855, 1601, 1601))

    def test_exact_fabricated_snapshot_result_uses_complete_original_bo(self):
        result = self.evaluate("capture_add_8")
        self.assertEqual(result["readback_physical_bytes"], 94208)
        self.assertEqual(result["persisted_final_image_physical_bytes"], 94208)
        self.assertEqual(result["observed_text_bytes"], 203136)
        self.assertEqual(result["read64_packets"], 1474)
        self.assertEqual(result["read64_axi_reads"], 1474)

    def test_schema3_rejects_legacy_marker_and_inexact_packet_or_return_counts(self):
        repeat = self.spec("repeat_sub_9")
        old = legacy.metrics(repeat, self.vector_root)
        self.assertEqual(old["phy_user_returns"], 108107)
        snapshot = contract.metrics(repeat, self.vector_root)
        legacy_marker = (
            "PASS jtag_ew_ddr jobs=2 negative=0 recovered=0 "
            f"lines={old['lines']} uploaded_nonzero={old['uploaded_nonzero']} rawtasks=2 "
            f"phy_user_returns={old['phy_user_returns']} scope=actual_AXI_UI_MC_modeled_PHY"
        )
        expected = self.vector_root / repeat["case"] / "expected.txt"
        with tempfile.TemporaryDirectory(prefix="legacy-marker-") as name:
            observed = Path(name) / "observed.txt"
            observed.write_bytes(expected.read_bytes())
            with self.assertRaises(ValueError):
                contract.check_result(legacy_marker, 0, repeat, snapshot, observed, expected)
            snapshot_marker = self.marker(repeat, snapshot)
            with self.assertRaises(ValueError):
                legacy.check_result(snapshot_marker, 0, repeat, old, observed, expected)

        def wrong_returns(marker, metrics, spec):
            return marker.replace(f"phy_user_returns={metrics['phy_user_returns']}",
                                  f"phy_user_returns={metrics['uncached_phy_user_returns']}")

        def missing_packets(marker, metrics, spec):
            return marker.replace(f" read64_packets={metrics['host_read64_packets']}", "")

        def duplicate_packets(marker, metrics, spec):
            return marker + f" read64_packets={metrics['host_read64_packets']}"

        def ar_more_than_one_per_packet(marker, metrics, spec):
            return marker.replace(f"read64_axi_reads={metrics['host_read64_axi_reads']}",
                                  f"read64_axi_reads={metrics['host_read64_axi_reads'] + 1}")

        def ar_missing(marker, metrics, spec):
            return marker.replace(f" read64_axi_reads={metrics['host_read64_axi_reads']}", "")

        def packet_count_wrong(marker, metrics, spec):
            return marker.replace(f"read64_packets={metrics['host_read64_packets']}",
                                  f"read64_packets={metrics['host_read64_packets'] - 1}")

        for name, edit in (("legacy_phy_returns", wrong_returns), ("missing_packet_count", missing_packets),
                           ("duplicate_packet_count", duplicate_packets),
                           ("more_than_one_ar_per_packet", ar_more_than_one_per_packet),
                           ("missing_ar_count", ar_missing), ("packet_count_mismatch", packet_count_wrong)):
            with self.subTest(name=name):
                self.assert_rejected("repeat_sub_9", marker_edit=edit)

    def test_coverage_exit_and_runtime_diagnostic_failures_are_rejected(self):
        edits = [
            ("jobs", lambda m, d, s: m.replace("jobs=1", "jobs=0", 1)),
            ("error", lambda m, d, s: m.replace("negative=0", "negative=1", 1)),
            ("recovery", lambda m, d, s: m.replace("recovered=0", "recovered=1", 1)),
            ("line_count", lambda m, d, s: m.replace("lines=1472", "lines=1471", 1)),
            ("upload_count", lambda m, d, s: m.replace("uploaded_nonzero=72", "uploaded_nonzero=0", 1)),
            ("task_count", lambda m, d, s: m.replace("rawtasks=1", "rawtasks=0", 1)),
        ]
        for name, edit in edits:
            with self.subTest(name=name):
                self.assert_rejected("capture_add_8", marker_edit=edit)
        with self.assertRaises(ValueError):
            self.evaluate("capture_add_8", code=1)
        with self.assertRaises(ValueError):
            self.evaluate("capture_add_8", extra_lines=("PASS extra unrelated result",))
        with self.assertRaises(ValueError):
            self.evaluate("capture_add_8", extra_lines=("warning: runtime warning",))

    def test_whole_bo_changes_and_fault_readback_are_rejected(self):
        with self.assertRaises(ValueError):
            self.evaluate("capture_add_8", output="changed")
        with self.assertRaises(ValueError):
            self.evaluate("capture_add_8", output="truncated")
        with self.assertRaises(ValueError):
            self.evaluate("unknown_command", output="expected")
        with self.assertRaises(ValueError):
            self.evaluate("capture_add_8", output="missing")

    def test_partial_task_fault_requires_real_task_and_ui_e5_check_marker(self):
        result = self.evaluate("partial_task_fault")
        self.assertEqual(result["successful_jobs"], 0)

        good = "CHECKED partial_task_fault completed=1 ui_code=5"
        for mutation, bad in (("missing", None), ("zero_count", "CHECKED partial_task_fault completed=0 ui_code=5"),
                              ("wrong_code", "CHECKED partial_task_fault completed=1 ui_code=8")):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    self.evaluate("partial_task_fault", checked_line=bad)
        with self.assertRaises(ValueError):
            self.evaluate("partial_task_fault", extra_lines=(good,))

    def test_original_runtime_deadlines_are_unchanged(self):
        for name in ("capture_add_8", "repeat_sub_9", "late_pending_result_fault"):
            spec = self.spec(name)
            self.assertEqual(snapshot_runner.runtime_timeout(spec,
                contract.metrics(spec, self.vector_root)), 1800)
        for name in ("unknown_command", "partial_task_fault"):
            spec = self.spec(name)
            self.assertEqual(snapshot_runner.runtime_timeout(spec,
                contract.metrics(spec, self.vector_root)), 300)


if __name__ == "__main__":
    unittest.main()
