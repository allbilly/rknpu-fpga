from __future__ import annotations
import ast,contextlib,hashlib,importlib.util,io,json,os,pathlib,subprocess,sys,tempfile,unittest
from unittest import mock

PKG=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('full512_ddr_model_runner',PKG/'run_full_model.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class OfflineModelPreparationTests(unittest.TestCase):
    def test_default_preflight_is_offline_and_fail_closed(self):
        output=io.StringIO()
        with mock.patch.object(runner.socket,'socket',side_effect=AssertionError('socket used')), \
             mock.patch.object(runner.subprocess,'Popen',side_effect=AssertionError('process started')), \
             mock.patch.object(runner.fcntl,'flock',side_effect=AssertionError('lease acquired')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(runner.main([]),0)
        self.assertIn('READY_REQUIRES_EXPLICIT_EXECUTION',output.getvalue())
        self.assertIn('"hardware_accessed": false',output.getvalue())

    def test_explicit_execution_control_does_not_start_any_hardware_action(self):
        with tempfile.TemporaryDirectory() as td:
            original=runner.PKG;runner.PKG=pathlib.Path(td)
            try:
                with mock.patch.object(runner,'hardware_admission',side_effect=AssertionError('offline test blocked before hardware admission')), \
                     mock.patch.object(runner,'check_frozen_inputs'), \
                     mock.patch.object(runner.socket,'socket',side_effect=AssertionError('socket used')), \
                     mock.patch.object(runner.subprocess,'Popen',side_effect=AssertionError('process started')), \
                     mock.patch.object(runner.fcntl,'flock',side_effect=AssertionError('lease acquired')):
                    with self.assertRaisesRegex(AssertionError,'offline test blocked'):
                        runner.main(['--execute-volatile-sram'])
            finally:runner.PKG=original

    def test_root_image_prerequisite_and_execution_approval_are_hash_bound(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        review=json.loads((PKG/'image-review.json').read_text())
        trained=json.loads((PKG/'trained-tile-prerequisite.json').read_text())
        approval=json.loads((PKG/'execution-approval.json').read_text())
        self.assertEqual(prep['image_review_sha256'],runner.sha(PKG/'image-review.json'))
        self.assertEqual(prep['trained_tile_prerequisite_sha256'],runner.sha(PKG/'trained-tile-prerequisite.json'))
        self.assertEqual(prep['execution_approval_sha256'],runner.sha(PKG/'execution-approval.json'))
        self.assertTrue(trained['accepted']);self.assertTrue(approval['approved'])
        self.assertEqual(review['bitstream']['sha256'],prep['bitstream_sha256'])
        self.assertFalse(approval['flash_authorized'])
        self.assertEqual(runner.pending_gates(prep),[])

    def test_populated_root_admission_validates_without_running_hardware(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        result=runner.validate_admission(prep)
        self.assertEqual(result[0]['status'],runner.IMAGE_STATUS)
        self.assertEqual(result[1]['status'],runner.PREREQ_STATUS)
        self.assertTrue(result[2]['approved'])
        self.assertEqual(result[5],prep['bitstream_sha256'])

    def test_v12_image_emission_and_canonical_review_bindings_are_frozen_without_model_approval(self):
        p=json.loads((PKG/'preparation.json').read_text())
        self.assertEqual(p['source_tag'],'5e99f881')
        self.assertEqual(p['source_manifest_sha256'],'5e99f881eea21ff01bdf02f02435c7722a5ef78b820308727ac84f39edf0981f')
        self.assertEqual(p['full512_image_preparation_path'],'build/full512-ddr-preparation/full512-image-prep-v12/image-preparation.json')
        self.assertEqual(p['full512_image_preparation_sha256'],'c52e8e9d8d91a0cc703520d6b021c546ba5280d3bf511b8346b8d27aef01a80d')
        self.assertEqual(p['full512_root_emission_review_path'],'build/full512-ddr-preparation/full512-image-prep-v12/root-emission-review.json')
        self.assertEqual(p['full512_root_bindings_path'],'build/full512-ddr-preparation/full512-image-prep-v12/root-bindings.json')
        self.assertEqual(p['canonical_v12_image_review_path'],'build/full512-ddr-preparation/full512-bitfile-audit-v2/v12-image-review.json')
        self.assertEqual(p['canonical_v12_bitfile_audit_path'],'build/full512-ddr-preparation/full512-bitfile-audit-v2/v12-image-audit.json')
        self.assertEqual(p['candidate_emitted_bitstream_sha256'],'d627b7155c4a4ad6b948424fbd28240a666ea6071bfe8c5d5b19f7da051b0031')
        self.assertEqual(p['candidate_software_crc_validation'],'NOT_CHECKED')
        self.assertEqual(p['expected_profile']['memory_profile'],'ddr')
        self.assertEqual(p['expected_profile']['selected_physical_channel'],1)
        self.assertEqual(p['expected_profile']['product_dsps'],512)
        self.assertEqual(p['expected_profile']['total_dsps'],516)
        self.assertEqual(p['expected_profile']['bram_blocks'],0)

    def test_actual_v6_trained_tile_candidate_is_bound_but_model_prerequisite_stays_pending(self):
        p=json.loads((PKG/'preparation.json').read_text());candidate=p['trained_tile_candidate']
        self.assertEqual(candidate['status'],'ROOT_REVIEWED_FULL512_CH1_DDR_TRAINED_TILE')
        self.assertTrue(candidate['accepted'])
        self.assertEqual(candidate['run_report_sha256'],'b5bfb029b8fb423adb34374fa70e0b2e5498bba71af1ba917e52591ae6fbef95')
        self.assertEqual(candidate['worker_report_sha256'],'d4426973f4cde54f83fa4a1beba9f753f065de5071d7c52a4a50629f9912bc3e')
        self.assertEqual(candidate['independent_audit_sha256'],'a4ac850f02f8b543b8e99c9309792aba22ec253bbe88dc95d088d1886e3cb1b3')
        self.assertTrue(candidate['physical_artifacts'])
        self.assertIsNotNone(p['trained_tile_prerequisite_sha256'])
        self.assertTrue(json.loads((PKG/'trained-tile-prerequisite.json').read_text())['accepted'])

    def test_model_specific_review_requires_canonical_hardware_review_and_full_source_hash(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        canonical_path=runner.ROOT/prep['canonical_v12_image_review_path']
        canonical=json.loads(canonical_path.read_text())
        review=dict(canonical)
        review.update({'catalog_sha256':prep['catalog_report_sha256'],
            'canonical_hardware_review_path':prep['canonical_v12_image_review_path'],
            'canonical_hardware_review_sha256':runner.sha(canonical_path),
            'bound_files':{str(canonical_path):runner.sha(canonical_path)}})
        review_sha='f'*64;prep['image_review_sha256']=review_sha
        bit,bit_sha=runner.validate_model_image_review(prep,review,canonical,canonical_path,review_sha)
        self.assertEqual(bit_sha,canonical['bitstream']['sha256'])
        self.assertEqual(bit, pathlib.Path(canonical['bitstream']['path']))
        bad=dict(review);bad['canonical_hardware_review_sha256']='0'*64
        with self.assertRaisesRegex(RuntimeError,'canonical image binding changed'):
            runner.validate_model_image_review(prep,bad,canonical,canonical_path,review_sha)
        bad=dict(review);bad['bitstream']=dict(review['bitstream'],sha256='0'*64)
        with self.assertRaisesRegex(RuntimeError,'differs from canonical image'):
            runner.validate_model_image_review(prep,bad,canonical,canonical_path,review_sha)
        bad=dict(review);bad['source_sha256']=runner.SOURCE_TAG
        with self.assertRaisesRegex(RuntimeError,'differs from canonical hardware review: source_sha256'):
            runner.validate_model_image_review(prep,bad,canonical,canonical_path,review_sha)
        bad=dict(review);bad['source_manifest_sha256']=runner.SOURCE_TAG
        with self.assertRaisesRegex(RuntimeError,'differs from canonical hardware review: source_manifest_sha256'):
            runner.validate_model_image_review(prep,bad,canonical,canonical_path,review_sha)

    def test_runner_bootstraps_repo_imports_from_unrelated_cwd_without_pythonpath(self):
        code=("import importlib.util,pathlib; p=pathlib.Path("+repr(str(PKG/'run_full_model.py'))+
              "); s=importlib.util.spec_from_file_location('fresh_runner',p); m=importlib.util.module_from_spec(s); "
              "s.loader.exec_module(m); import tools.tinystories.progress; print('IMPORT_OK')")
        env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'}
        with tempfile.TemporaryDirectory() as td:
            result=subprocess.run([sys.executable,'-c',code],cwd=td,env=env,text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('IMPORT_OK',result.stdout)

    def test_original_package_catalog_and_oracle_ids_are_bound(self):
        p=json.loads((PKG/'preparation.json').read_text())
        self.assertEqual(p['model_package_path'],'build/tinystories-preparation/260k-first-v2')
        self.assertEqual(p['model_package_report_sha256'],'5229ead1933dc9fd4f7c364f1bfa42f2f43a5e2621900e37e072c78993c161d0')
        self.assertEqual(p['catalog_report_path'],'build/tinystories-programs/all-v1/report.json')
        self.assertEqual(p['oracle_reference_path'],'build/tinystories-full-oracle/v1')
        self.assertEqual(p['oracle_reference_report_sha256'],runner.sha(runner.ROOT/p['oracle_reference_path']/'report.json'))
        self.assertEqual(len(p['model_package_files']),121)
        self.assertEqual(len(p['oracle_reference_artifacts']),26)

    def test_three_original_phases_have_exact_order_and_prompts(self):
        self.assertEqual(runner.phase_specs(),[
            {'name':'one-complete-forward-position','steps':1,'prompt':''},
            {'name':'repeated-complete-forward-position','steps':1,'prompt':''},
            {'name':'greedy32','steps':32,'prompt':'Once upon a time'}])

    def test_exact_public_worker_command_keeps_profile_wait_budget_and_deadline(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        phase=runner.phase_specs()[1];argv=runner.worker_argv(prep,phase,PKG/'physical-test/physical-tests'/phase['name']/'jobs')
        self.assertEqual(argv[0],runner.sys.executable)
        self.assertIn('tools/tinystories/run_model.py',argv[1])
        self.assertEqual(argv[argv.index('--backend')+1],'jtag')
        self.assertEqual(argv[argv.index('--memory-profile')+1],'ddr')
        self.assertEqual(argv[argv.index('--port')+1],'3721')
        self.assertEqual(argv[argv.index('--min-mem-available-mib')+1],'2048')
        self.assertEqual(argv[argv.index('--memory-wait-budget-seconds')+1],'900')
        self.assertEqual(argv[argv.index('--steps')+1],'1')
        self.assertEqual(argv[argv.index('--prompt')+1],'')
        self.assertIn('--quit-bridge',argv)
        self.assertEqual(prep['worker_contract']['per_worker_timeout_seconds'],14400)

    def test_public_audit_model_is_called_for_every_phase_in_ddr_mode(self):
        prep=json.loads((PKG/'preparation.json').read_text())
        for phase in runner.phase_specs():
            physical=PKG/'physical-test/physical-tests'
            audit_output=PKG/'phase-audits'/phase['name']/'audit.json'
            argv=runner.audit_argv(phase,physical,audit_output,prep)
            self.assertIn('tools/tinystories/audit_model.py',argv[1])
            self.assertEqual(argv[argv.index('--run')+1],str(physical.parent))
            self.assertEqual(argv[argv.index('--phase')+1],phase['name'])
            self.assertEqual(argv[argv.index('--memory-profile')+1],'ddr')
            self.assertFalse(audit_output.is_relative_to(physical))

    def test_parent_image_review_and_physical_report_use_public_audit_layout(self):
        source=(PKG/'run_full_model.py').read_text()
        self.assertIn("run=PKG/'physical-test'",source)
        self.assertIn("physical=run/'physical-tests'",source)
        self.assertIn("run/'image-review.json').write_bytes(REVIEW.read_bytes())",source)
        self.assertIn("write(physical/'report.json',record)",source)

    def test_one_program_then_fresh_bridge_each_phase_without_fabric_reset(self):
        tree=ast.parse((PKG/'run_full_model.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        loop=next(n for n in ast.walk(main) if isinstance(n,ast.For) and 'phase_specs()' in ast.unparse(n.iter))
        program_calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and ast.unparse(n.func)=='start_owned' and
                       n.args and 'native_argv' in ast.unparse(n.args[0])]
        self.assertEqual(len(program_calls),1)
        self.assertLess(program_calls[0].lineno,loop.lineno)
        loop_calls=[n for n in ast.walk(loop) if isinstance(n,ast.Call)]
        self.assertTrue(any(ast.unparse(n.func)=='launch_phase_bridge' for n in loop_calls))
        self.assertFalse(any('program_hw_devices' in ast.unparse(n) or 'fabric_reset' in ast.unparse(n).lower()
                             for n in ast.walk(loop)))
        prep=json.loads((PKG/'preparation.json').read_text())
        self.assertEqual(prep['worker_contract']['volatile_load_count'],1)
        self.assertFalse(prep['worker_contract']['fabric_reset_between_phases'])

    def test_model_math_is_not_host_dense_fallback_and_fixtures_are_not_regenerated(self):
        source=(PKG/'run_full_model.py').read_text()
        self.assertIn('tools/tinystories/run_model.py',source)
        self.assertIn('tools/tinystories/audit_model.py',source)
        self.assertNotIn('tools.tinystories.oracle import',source)
        self.assertNotIn('generate_vectors',source)
        p=json.loads((PKG/'preparation.json').read_text())
        self.assertFalse(p['hardware_accessed']);self.assertFalse(p['model_run_executed'])

    def trained_prerequisite_fixture(self,base,audit_hardware_accessed='absent'):
        image_sha='a'*64;bit_sha='b'*64;prep=json.loads((PKG/'preparation.json').read_text())
        def save(name,obj):
            p=base/name;p.write_text(json.dumps(obj,sort_keys=True)+'\n');return p
        worker=save('trained-worker.json',{'status':'PASS_PHYSICAL_TRAINED_TILE_COMPACTION_AND_REARM_REQUIRES_AUDIT',
            'memory_profile':'ddr','hardware_accessed':True,'flash_written':False,'cpu_dense_fallback':False,
            'vectors_report_sha256':prep['trained_vectors_report_sha256']})
        run=save('trained-run.json',{'status':'PASS_FULL512_CH1_SCRATCH_AND_TRAINED_TILE_REQUIRES_ROOT_AUDIT',
            'hardware_programmed':True,'flash_written':False,'bitstream_sha256':bit_sha,'image_review_sha256':image_sha,
            'source_manifest_sha256':runner.SOURCE_SHA256,'trained_worker_report_sha256':runner.sha(worker)})
        audit_fields={'status':'PASS_INDEPENDENT_DDR_TRAINED_TILE_RAW_WIRE_AUDIT_ONLY',
            'image_target_route_qualified_by_this_audit':False,
            'worker_report_sha256':runner.sha(worker),'vector_report_sha256':prep['trained_vectors_report_sha256']}
        if audit_hardware_accessed!='absent':audit_fields['hardware_accessed']=audit_hardware_accessed
        audit=save('trained-audit.json',audit_fields)
        root=save('trained-root-review.json',{'status':'ROOT_REVIEWED_FULL512_CH1_DDR_TRAINED_TILE','accepted':True,
            'trained_tile_run_report_sha256':runner.sha(run),'trained_tile_worker_report_sha256':runner.sha(worker),
            'trained_tile_independent_audit_sha256':runner.sha(audit),'image_review_sha256':image_sha,
            'bitstream_sha256':bit_sha,'source_sha256':runner.SOURCE_SHA256})
        prereq={'status':runner.PREREQ_STATUS,'accepted':True,'trained_tile_run_report_path':str(run),
            'trained_tile_run_report_sha256':runner.sha(run),'trained_tile_worker_report_path':str(worker),
            'trained_tile_worker_report_sha256':runner.sha(worker),'trained_tile_independent_audit_path':str(audit),
            'trained_tile_independent_audit_sha256':runner.sha(audit),'root_prerequisite_review_path':str(root),
            'root_prerequisite_review_sha256':runner.sha(root),'image_review_sha256':image_sha,
            'bitstream_sha256':bit_sha,'source_sha256':runner.SOURCE_SHA256}
        prereq_path=save('prerequisite.json',prereq);prereq_sha=runner.sha(prereq_path)
        prep['trained_tile_prerequisite_sha256']=prereq_sha
        return prep,prereq,image_sha,bit_sha,prereq_sha,worker,run,audit,root

    def test_accepted_wrapper_still_requires_all_real_underlying_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);prep,prereq,image_sha,bit_sha,p_sha,worker,run,audit,root=self.trained_prerequisite_fixture(base)
            result=runner.validate_trained_tile_prerequisite(prep,prereq,image_sha,bit_sha,p_sha)
            self.assertIn('trained_tile_run_report_path',result)

    def test_actual_trained_v6_audit_without_hardware_accessed_is_accepted_by_wrapper(self):
        prep=json.loads((PKG/'preparation.json').read_text());prereq=json.loads((PKG/'trained-tile-prerequisite.json').read_text())
        actual=pathlib.Path(prereq['trained_tile_independent_audit_path']);audit=json.loads(actual.read_text())
        self.assertNotIn('hardware_accessed',audit)
        result=runner.validate_trained_tile_prerequisite(prep,prereq,runner.sha(runner.ROOT/prep['canonical_v12_image_review_path']),
            prereq['bitstream_sha256'],runner.sha(PKG/'trained-tile-prerequisite.json'))
        self.assertEqual(result['trained_tile_independent_audit_path'],audit)

    def test_trained_tile_audit_explicit_true_or_null_hardware_access_is_rejected(self):
        for explicit in (True,None):
            with self.subTest(explicit=explicit),tempfile.TemporaryDirectory() as temp:
                base=pathlib.Path(temp);prep,prereq,image_sha,bit_sha,p_sha,*_=self.trained_prerequisite_fixture(base,explicit)
                with self.assertRaisesRegex(RuntimeError,'underlying trained-tile raw-wire audit'):
                    runner.validate_trained_tile_prerequisite(prep,prereq,image_sha,bit_sha,p_sha)

    def test_accepted_wrapper_with_missing_underlying_receipt_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);prep,prereq,image_sha,bit_sha,p_sha,worker,run,audit,root=self.trained_prerequisite_fixture(base)
            missing=base/'deleted-trained-worker.json';prereq['trained_tile_worker_report_path']=str(missing)
            prep['trained_tile_prerequisite_sha256']='c'*64
            with self.assertRaisesRegex(RuntimeError,'required trained-tile prerequisite receipt missing'):
                runner.validate_trained_tile_prerequisite(prep,prereq,image_sha,bit_sha,'c'*64)

    def test_accepted_wrapper_with_tampered_underlying_worker_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            base=pathlib.Path(temp);prep,prereq,image_sha,bit_sha,p_sha,worker,run,audit,root=self.trained_prerequisite_fixture(base)
            worker.write_text('{"status":"PASS_BUT_TAMPERED"}\n')
            with self.assertRaisesRegex(RuntimeError,'trained-tile prerequisite hash mismatch'):
                runner.validate_trained_tile_prerequisite(prep,prereq,image_sha,bit_sha,p_sha)

    def test_local_runtime_python_import_closure_is_hash_bound(self):
        p=json.loads((PKG/'preparation.json').read_text());bound=set(p['runtime_source_hashes'])
        sources=set(bound)|{'run_full_model.py'};modules=set()
        for name in sources:
            if not name.endswith('.py'):continue
            q=(PKG/name) if name=='run_full_model.py' else runner.ROOT/name
            tree=ast.parse(q.read_text(),filename=name)
            for n in ast.walk(tree):
                if isinstance(n,ast.Import):modules.update(a.name for a in n.names if a.name.startswith('tools.'))
                elif isinstance(n,ast.ImportFrom) and n.module and n.module.startswith('tools.'):modules.add(n.module)
        required=set()
        for module in modules:
            base=module.replace('.','/');a=runner.ROOT/(base+'.py');b=runner.ROOT/base/'__init__.py'
            if a.is_file():required.add(a.relative_to(runner.ROOT).as_posix())
            elif b.is_file():required.add(b.relative_to(runner.ROOT).as_posix())
        self.assertFalse(required-bound,sorted(required-bound))

if __name__=='__main__':unittest.main()
