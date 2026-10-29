import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_prepare_image',BASE/'prepare_image.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)

class PreparationGateTests(unittest.TestCase):
    def test_partial_running_route_report_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);report=root/'route.json';review=root/'review.json';dcp=root/'post_route.dcp'
            dcp.write_bytes(b'partial route checkpoint');dcp_hash=prepare.sha(dcp)
            report.write_text(json.dumps({'status':'RUNNING','returncode':None,'output_hashes':{}}))
            review.write_text(json.dumps({'status':'PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY','post_route_dcp_sha256':dcp_hash}))
            manifest={'status':'UNLAUNCHABLE','qualification_gates':{},'route_gate':{
                'report_sha256':prepare.sha(report),'route_report_path':str(report),'required_report_status':'PASS_FULL512_DDR_ROUTED_CHECKPOINT_ONLY_REQUIRES_SOURCE_AUDIT_AND_PHYSICAL_REVIEW',
                'post_route_dcp_path':str(dcp),'post_route_dcp_sha256':dcp_hash,'review_path':str(review),'review_sha256':prepare.sha(review),
                'independent_route_review_status':'PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY'},
                'io_snapshot_gate':{'future_snapshot_json_path':str(root/'io.json')}}
            binding={'render_approved':True}
            old_io=prepare.IO_REPORT;prepare.IO_REPORT=root/'io.json'
            try:missing=prepare.collect_missing(manifest,binding)
            finally:prepare.IO_REPORT=old_io
            self.assertTrue(any('route repair report is not terminal PASS' in x for x in missing))

    def test_pending_case_union_and_render_approval_remain_blockers(self):
        missing=prepare.collect_missing({'status':'UNLAUNCHABLE','qualification_gates':{
            'controller_case_union_33':{'path':None,'sha256':None,'required_status':None,'status_field':'status','expected_case_count':33}},
            'route_gate':{'report_sha256':None,'review_path':None,'review_sha256':None,'post_route_dcp_sha256':None},
            'io_snapshot_gate':{'future_snapshot_json_path':'missing.json'}}, {'render_approved':False})
        self.assertTrue(any('root preparation/render approval is absent' in x for x in missing))
        self.assertTrue(any('controller_case_union_33' in x for x in missing))

if __name__=='__main__':unittest.main()
