"""Schema-3 READ64 execution adapter source-identity controls only.

No DUT, simulator, PHY model, Vivado, or hardware operation is started here.
"""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tools.ddr import endpoint_vectors
from tools.ddr import read_snapshot_contract as schema3
from tools.ddr import read_snapshot_contract_v4 as contract
from tools.ddr import run_async_endpoint as async_runner
from tools.ddr import run_read_snapshot_execution_v4 as execution


class ReadSnapshotExecutionV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="read-snapshot-execution-v4-")
        cls.root = Path(cls.temp.name)
        cls.vectors = cls.root / "vectors"
        cls.original_specs = endpoint_vectors.generate(cls.vectors)
        cls.specs = execution.expanded_specs(cls.original_specs)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def spec(self, name):
        return next(s for s in self.specs if s["name"] == name)

    @staticmethod
    def marker(spec, metrics, *, phy_user_returns=None, packets=None, ar_reads=None, prefix=None):
        jobs = 0 if spec["negative"] == 9 else spec["jobs"] + int(bool(spec["reset_recovery"]))
        if phy_user_returns is None:
            phy_user_returns = metrics["phy_user_returns"]
            if phy_user_returns is None:
                phy_user_returns = metrics["phy_user_returns_minimum"]
        if packets is None:
            packets = metrics["host_read64_packets"]
        if ar_reads is None:
            ar_reads = metrics["host_read64_axi_reads"]
        prefix = prefix or "PASS jtag_ew_ddr_read_snapshot"
        return (
            f"{prefix} jobs={jobs} negative={spec['negative']} "
            f"recovered={int(bool(spec['reset_recovery']))} lines={metrics['lines']} "
            f"uploaded_nonzero={metrics['uploaded_nonzero']} rawtasks={spec['tasks']} "
            f"phy_user_returns={phy_user_returns} read64_packets={packets} "
            f"read64_axi_reads={ar_reads} scope=actual_AXI_UI_MC_modeled_PHY"
        )

    def check_fake(self, spec, marker, *, code=0, checked_partial=True, readback="auto", extra=()):
        data = contract.metrics(spec, self.vectors)
        expected = self.vectors / spec["case"] / "expected.txt"
        lines = []
        if spec["negative"] == 10 and checked_partial:
            lines.append("CHECKED partial_task_fault completed=1 ui_code=5")
        lines.extend(extra)
        lines.append(marker)
        with tempfile.TemporaryDirectory(prefix="read-snapshot-v4-check-") as temp:
            observed = Path(temp) / "observed.txt"
            should_readback = data["successful_jobs"] > 0 if readback == "auto" else readback
            if should_readback:
                observed.write_bytes(expected.read_bytes())
            return contract.check_result("\n".join(lines) + "\n", code, spec, data, observed, expected)

    def test_frozen_v3_package_passes_read_only_build_verifier(self):
        package = Path("build/ddr-endpoint-async/native-read-snapshot-v3")
        report = execution.verify_build(package)
        self.assertEqual(report["status"], "PASS_READ_SNAPSHOT_DDR_NATIVE_BUILD_ONLY")
        self.assertEqual(report["binary_sha256"], "d3fe23dbf517842b391ba440fb8ff8d02b2f536a2ee1d8cefe2a7c6de84b1eb5")
        self.assertEqual(report["schema"], contract.SCHEMA)
        self.assertFalse(report["hardware_accessed"])

    def test_build_command_is_execution_only_and_leaves_output_absent(self):
        with tempfile.TemporaryDirectory(prefix="snapshot-build-must-not-run-") as temp:
            out = Path(temp) / "must-remain-absent"
            with self.assertRaisesRegex(ValueError, "Execution-only adapter"):
                execution.build(SimpleNamespace(out=out))
            self.assertFalse(out.exists())

    def test_execution_inventory_binds_both_v4_modules_and_this_test(self):
        inventory = execution.execution_input_inventory()
        root = execution.ROOT
        expected = (
            "tools/ddr/run_read_snapshot_execution_v4.py",
            "tools/ddr/read_snapshot_contract_v4.py",
            "tests/ddr/read_snapshot/test_execution_v4.py",
        )
        for relative in expected:
            path = root / relative
            self.assertIn(str(path), inventory)
            self.assertEqual(inventory[str(path)], contract.sha(path))

    def test_execution_v4_rejects_legacy_v3_run_receipt(self):
        legacy_report = execution.ROOT / "build/repeat-read-snapshot-v3/report.json"
        report = __import__("json").loads(legacy_report.read_text())
        self.assertIsNone(report.get("execution_contract_version"))
        with self.assertRaisesRegex(ValueError, "Incomplete async DDR run"):
            execution.verify_run(legacy_report)

    def test_schema3_metrics_other_twenty_cases_are_unchanged(self):
        self.assertEqual(len(self.original_specs), 20)
        self.assertEqual(self.specs[:20], self.original_specs)
        self.assertEqual(len(self.specs), 21)
        self.assertEqual(self.specs[20]["name"], "partial_task_fault")
        for spec in self.original_specs:
            with self.subTest(case=spec["name"]):
                old = schema3.metrics(spec, self.vectors)
                new = contract.metrics(spec, self.vectors)
                if spec["name"] == "unknown_command":
                    # The one intentional traffic delta: READ64 of the command
                    # packet plus one command-ID corruption write.
                    self.assertEqual((old["host_read64_packets"], old["host_read64_axi_reads"]), (2, 2))
                    self.assertEqual((new["host_read64_packets"], new["host_read64_axi_reads"]), (3, 3))
                    self.assertEqual((new["command_corruption_read_packets"],
                                      new["command_corruption_write_packets"]), (1, 1))
                    for key in ("lines", "physical_bytes", "uploaded_nonzero", "successful_jobs",
                                "uncached_phy_user_returns"):
                        self.assertEqual(new[key], old[key], key)
                else:
                    for key, value in old.items():
                        self.assertEqual(new[key], value, f"{spec['name']}:{key}")
                    self.assertEqual(new["command_corruption_read_packets"], 0)
                    self.assertEqual(new["command_corruption_write_packets"], 0)

    def test_unknown_command_e1_path_has_three_packets_and_minimum_5060(self):
        spec = self.spec("unknown_command")
        data = contract.metrics(spec, self.vectors)
        self.assertEqual((data["host_read64_packets"], data["host_read64_axi_reads"]), (3, 3))
        self.assertEqual(data["phy_user_returns_minimum"], 5060)
        # The unchanged testbench performs a pre-job command read/write and
        # checks the explicit E1 register result.
        bench = (execution.ROOT / "tests/ddr/tb_jtag_ew_ddr_async.sv").read_text()
        self.assertIn("if(negative_mode==1)begin", bench)
        self.assertIn("expect_reg(32'h24,negative_mode==1?32'd1:", bench)
        result = self.check_fake(spec, self.marker(spec, data, phy_user_returns=5064))
        self.assertEqual(result["successful_jobs"], 0)
        self.assertEqual(result["read64_packets"], 3)
        self.assertEqual(result["read64_axi_reads"], 3)

    def test_legacy_marker_and_bad_command_packet_counters_are_rejected(self):
        spec = self.spec("unknown_command")
        old = schema3.metrics(spec, self.vectors)
        data = contract.metrics(spec, self.vectors)
        self.assertEqual(old["host_read64_packets"], 2)
        self.assertEqual(old["host_read64_axi_reads"], 2)
        expected = self.vectors / spec["case"] / "expected.txt"
        with tempfile.TemporaryDirectory(prefix="snapshot-marker-revision-") as temp:
            observed = Path(temp) / "observed.txt"
            legacy_marker = (
                "PASS jtag_ew_ddr_read_snapshot jobs=1 negative=1 recovered=0 "
                f"lines={old['lines']} uploaded_nonzero={old['uploaded_nonzero']} rawtasks={spec['tasks']} "
                f"phy_user_returns={data['phy_user_returns_minimum']} read64_packets=2 read64_axi_reads=2 "
                "scope=actual_AXI_UI_MC_modeled_PHY"
            )
            with self.assertRaises(ValueError):
                contract.check_result(legacy_marker, 0, spec, data, observed, expected)
        for name, options in (
            ("packets_2", dict(packets=2)),
            ("packets_4", dict(packets=4)),
            ("ar_2", dict(ar_reads=2)),
            ("ar_4", dict(ar_reads=4)),
            ("phy_below_minimum", dict(phy_user_returns=5059)),
            ("missing_new_marker", dict(prefix="PASS jtag_ew_ddr")),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.check_fake(spec, self.marker(spec, data, **options))

    def test_partial_task_e5_and_all_original_error_modes_are_preserved(self):
        expected_modes = {
            "unknown_command": 1, "rmw_ue": 2, "dropped_return": 3,
            "phy_write_stall": 4, "calibration_loss": 5,
            "queued_fault_after_success": 6, "ecc_control_timeout": 7,
            "late_pending_result_fault": 8, "host_memory_timeout": 9, "joint_reset_recovery": 2,
        }
        self.assertEqual({s["name"]:s["negative"] for s in self.original_specs if s["negative"]},
                         expected_modes)
        partial = self.spec("partial_task_fault");data=contract.metrics(partial,self.vectors)
        valid=self.check_fake(partial,self.marker(partial,data))
        self.assertEqual(valid["successful_jobs"],0)
        for bad_line in (None, "CHECKED partial_task_fault completed=0 ui_code=5",
                         "CHECKED partial_task_fault completed=1 ui_code=8"):
            lines=[] if bad_line is None else [bad_line]
            with self.subTest(bad_line=bad_line),self.assertRaises(ValueError):
                self.check_fake(partial,self.marker(partial,data),checked_partial=False,extra=lines)
        with self.assertRaises(ValueError):
            self.check_fake(partial,self.marker(partial,data),extra=("CHECKED partial_task_fault completed=1 ui_code=5",))

    def test_v4_timeout_policy_stays_300_and_1800(self):
        for name in ("unknown_command", "partial_task_fault"):
            spec=self.spec(name);self.assertEqual(execution.runtime_timeout(spec,contract.metrics(spec,self.vectors)),300)
        for name in ("capture_add_8", "repeat_sub_9", "late_pending_result_fault"):
            spec=self.spec(name);self.assertEqual(execution.runtime_timeout(spec,contract.metrics(spec,self.vectors)),1800)


if __name__ == "__main__":
    unittest.main()
