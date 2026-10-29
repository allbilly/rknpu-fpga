import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_run_io_query',BASE/'run_io_query.py')
query=importlib.util.module_from_spec(spec);spec.loader.exec_module(query)

class IOQueryFinalizationControls(unittest.TestCase):
    def test_input_mutation_after_native_success_forces_terminal_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'facts.tsv';path.write_text('before')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            record={'status':'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT',
                    'input_hashes_expected':{str(path):digest},'input_hashes_before':{str(path):digest}}
            path.write_text('changed after simulated successful query')
            self.assertFalse(query.finalize_input_hashes(record))
            self.assertEqual(record['status'],'FAIL_INPUT_MUTATION_AFTER_QUERY')
            self.assertFalse(record['all_inputs_unchanged'])

    def test_final_rehash_error_forces_terminal_failure(self):
        record={'status':'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT',
                'input_hashes_expected':{'missing':'0'*64},'input_hashes_before':{'missing':'0'*64}}
        def raising_hash(_):raise FileNotFoundError('synthetic final rehash control')
        self.assertFalse(query.finalize_input_hashes(record,raising_hash))
        self.assertEqual(record['status'],'FAIL_INPUT_REHASH_AFTER_QUERY')
        self.assertIn('input_rehash_error',record)

    def test_live_owned_descendant_prevents_pass_and_is_killed_with_owned_group(self):
        code="import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])"
        leader=subprocess.Popen([sys.executable,'-c',code],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        leader.wait(timeout=5)
        query.CHILD=leader
        before=query.group_pids(leader.pid)
        self.assertTrue(before)
        record={'status':'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT'}
        self.assertTrue(query.enforce_stopped_group(record,leader.pid))
        self.assertEqual(query.group_pids(leader.pid),[])
        self.assertTrue(record['owned_process_group_stopped'])
        self.assertIn('owned_pids_before_cleanup',record)

if __name__=='__main__':unittest.main()
