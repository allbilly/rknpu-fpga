from __future__ import annotations
import ast, copy, importlib.util, json, pathlib, unittest
from unittest import mock

PKG=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('full512_ddr_trained_runner',PKG/'run_sram_test.py')
runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)

class PreparationOnlyTests(unittest.TestCase):
    def test_offline_preflight_reports_pending_without_hardware_calls(self):
        with mock.patch.object(runner.socket,'socket',side_effect=AssertionError('socket used')), \
             mock.patch.object(runner.subprocess,'Popen',side_effect=AssertionError('process started')), \
             mock.patch.object(runner.fcntl,'flock',side_effect=AssertionError('lease acquired')):
            self.assertEqual(runner.offline_preflight(),0)

    def test_execute_flag_cannot_cross_pending_image_or_approval_gate(self):
        with mock.patch.object(runner.socket,'socket',side_effect=AssertionError('socket used')), \
             mock.patch.object(runner.subprocess,'Popen',side_effect=AssertionError('process started')), \
             mock.patch.object(runner.fcntl,'flock',side_effect=AssertionError('lease acquired')):
            with self.assertRaisesRegex(RuntimeError,'Hardware gates remain pending'):
                runner.main(['--execute-volatile-sram'])

    def test_image_and_execution_approval_are_explicitly_pending(self):
        image=json.loads((PKG/'image-review.json').read_text())
        approval=json.loads((PKG/'execution-approval.json').read_text())
        prep=json.loads((PKG/'preparation.json').read_text())
        self.assertIsNone(image['image_review_sha256'])
        self.assertIsNone(image['bitstream_path']); self.assertIsNone(image['bitstream_sha256'])
        self.assertFalse(image['final_execution_approval'])
        self.assertFalse(approval['approved'])
        self.assertIsNone(approval['image_review_sha256']); self.assertIsNone(approval['bitstream_sha256'])
        self.assertIsNone(prep['image_review_sha256']); self.assertIsNone(prep['execution_approval_sha256'])
        self.assertIn('review', ' '.join(runner.pending_gates(prep)))

    def test_required_device_and_resource_contract_is_bound(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        self.assertEqual(prep['source_tag'],'5e99f881')
        self.assertEqual(prep['source_manifest_sha256'],'5e99f881eea21ff01bdf02f02435c7722a5ef78b820308727ac84f39edf0981f')
        resources=prep['expected_resource_contract']
        self.assertEqual((prep['top'],resources['memory_profile'],resources['selected_physical_channel'],
                          resources['product_dsps'],resources['total_dsps'],resources['bram_blocks']),
                         ('ypcb_ddr_dual_top','ddr',1,512,516,0))
        self.assertEqual((prep['expected_target'],prep['expected_dna_port'],prep['expected_raw_idcode']),
                         (runner.TARGET,runner.DNA,runner.IDCODE))

    def test_current_board_lease_is_existing_expected_inode(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        stat=runner.LEASE.stat()
        self.assertEqual(stat.st_ino,9121364); self.assertEqual(prep['lease_inode'],9121364)
        self.assertEqual(stat.st_size,0)

    def test_original_trained_vector_binding_is_static_and_complete(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        vectors=pathlib.Path(prep['trained_vectors_path'])
        report=json.loads((vectors/'report.json').read_text())
        self.assertEqual(runner.sha(vectors/'report.json'),prep['trained_vectors_report_sha256'])
        self.assertEqual(report['status'],'STATIC_TRAINED_TILE_JOINED_TEST_VECTORS')
        self.assertEqual((report['lines'],report['cmac_amount'],report['ew_amount']),(1408,45,22))
        self.assertEqual(len(report['files']),6)

    def test_scratch_uses_fixed_helper_then_independent_trace_audit(self):
        source=(PKG/'run_sram_test.py').read_text()
        self.assertIn('result=scratch(device)',source)
        self.assertIn("'--trace',str(trace_path),'--out',str(scratch_audit)",source)
        self.assertIn('PASS_FIXED_DUAL_DDR_SCRATCH_WIRE_REPLAY_ONLY',source)
        self.assertIn("open('r+b')",source)
        self.assertNotIn("open('a+b')",source)

    def test_existing_projection_worker_command_keeps_raw_ddr_contract(self):
        source=(PKG/'run_sram_test.py').read_text()
        for value in ("tools/tinystories/run_projection.py", "'--memory-profile','ddr'",
                      "'--port','3721'", "'--quit-bridge'", "'--vectors-sha256'"):
            self.assertIn(value,source)
        self.assertIn("tools/ddr/audit_trained_tile.py",source)

    def test_complete_local_python_import_closure_is_hash_bound(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        bound=set(prep['runtime_source_hashes'])
        modules=set()
        for name in bound:
            if not name.endswith('.py'): continue
            tree=ast.parse((runner.ROOT/name).read_text(),filename=name)
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    modules.update(alias.name for alias in node.names if alias.name.startswith('tools.'))
                elif isinstance(node,ast.ImportFrom) and node.module and node.module.startswith('tools.'):
                    modules.add(node.module)
        required=set()
        for module in modules:
            base=module.replace('.','/')
            module_file=runner.ROOT/(base+'.py')
            package_file=runner.ROOT/base/'__init__.py'
            if module_file.is_file(): required.add(module_file.relative_to(runner.ROOT).as_posix())
            elif package_file.is_file(): required.add(package_file.relative_to(runner.ROOT).as_posix())
        self.assertFalse(required-bound,sorted(required-bound))

    def test_program_file_is_set_only_after_hash_and_target_checks(self):
        tcl=(PKG/'program-template.tcl.in').read_text()
        self.assertLess(tcl.index('verify_program_file $bitstream $expected_bit_sha'),
                        tcl.index('set_property PROGRAM.FILE $bitstream $dev'))
        self.assertLess(tcl.index('host_idcode'),tcl.index('set_property PROGRAM.FILE $bitstream $dev'))
        self.assertIn('flash',tcl.lower())
        self.assertNotIn('write_cfgmem',tcl.lower())

if __name__=='__main__': unittest.main()
