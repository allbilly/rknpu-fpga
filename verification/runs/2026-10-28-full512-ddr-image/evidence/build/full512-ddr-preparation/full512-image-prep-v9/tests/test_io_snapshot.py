import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from argparse import Namespace

PACKAGE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('full512_io_snapshot',PACKAGE/'io_snapshot.py')
io_snapshot=importlib.util.module_from_spec(spec);spec.loader.exec_module(io_snapshot)

class SnapshotFixture:
    def __init__(self,root):
        self.root=Path(root)
        self.dcp=self.write('route.dcp',b'fake-dcp-object')
        self.review=self.write_json('route-review.json',{'status':'PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY',
                    'post_route_dcp_sha256':self.sha(self.dcp)})
        self.board=self.write('board.xdc',b'board-spec')
        self.mig=self.write('mig.xdc',b'mig-spec')
        self.oldfacts=self.write('old-facts.tsv',self.old_facts().encode())
        self.oldcomp=self.write_json('old-comparison.json',{'status':'PASS_READONLY_ROUTED_IO_FACTS_COLLECTED','port_count':242,
            'mismatches':[],'unknown_actual_properties':[],'source_inputs':{
                'board_xdc':{'sha256':self.sha(self.board)},'original_mig_xdc':{'sha256':self.sha(self.mig)}}})
        self.facts=self.write('new-facts.tsv',self.new_facts().encode())
        self.properties=self.write('properties.txt',b'report_property snapshot\n')
        self.ports_tcl=self.write('ports.tcl',b'set full512_ports [dict create]\n')
        self.report_io=self.write('report_io.rpt',b'report_io\n')
        self.query=self.write_json('query-report.json',self.query_data())
        self.args=Namespace(facts=str(self.facts),properties=str(self.properties),ports_tcl=str(self.ports_tcl),report_io=str(self.report_io),
            query_report=str(self.query),query_report_sha256=self.sha(self.query),route_review=str(self.review),expected_dcp=str(self.dcp),
            expected_dcp_sha256=self.sha(self.dcp),old_facts=str(self.oldfacts),old_facts_sha256=self.sha(self.oldfacts),
            old_comparison=str(self.oldcomp),old_comparison_sha256=self.sha(self.oldcomp),current_board_xdc=str(self.board),current_mig_xdc=str(self.mig),
            out=str(self.root/'snapshot.json'))
    def sha(self,p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    def write(self,name,data):
        p=self.root/name;p.write_bytes(data);return p
    def write_json(self,name,value):
        p=self.root/name;p.write_text(json.dumps(value,indent=2)+'\n');return p
    def props(self,i):
        direction='INOUT' if i<120 else ('OUT' if i<200 else 'IN')
        return {'PACKAGE_PIN':f'PIN{i:03d}','IOSTANDARD':'SSTL15','SLEW':'FAST','DRIVE':'12',
                'PULLTYPE':'NONE','DIFF_TERM':'0','IN_TERM':'UNTUNED_SPLIT_50' if direction in {'IN','INOUT'} else 'NONE',
                'DIRECTION':direction}
    def old_facts(self):
        rows=[]
        for i in range(242):
            p=self.props(i);name=f'port_{i:03d}'
            rows.append('\t'.join(['PORT',str(i),name,p['DIRECTION'],p['PACKAGE_PIN'],'11',p['IOSTANDARD'],p['SLEW'],p['DRIVE'],p['PULLTYPE'],p['DIFF_TERM'],p['IN_TERM']]))
        return '\n'.join(rows)+'\n'
    def new_facts(self):
        dcp=self.sha(self.dcp);rows=['\t'.join(['DESIGN','ypcb_ddr_dual_top','ypcb_ddr_dual_top','xc7k480tffg1156-2','1.8','GND']),
            '\t'.join(['DCP',str(self.dcp),dcp]),'PORT_COUNT\t242']
        for i in range(242):
            name=f'port_{i:03d}'
            for key,value in self.props(i).items():rows.append('\t'.join(['PORT',str(i),name,key,value]))
        rows.append('SNAPSHOT_COMPLETE\t242')
        return '\n'.join(rows)+'\n'
    def query_data(self):
        return {'status':io_snapshot.QUERY_STATUS,'returncode':0,'stdout_marker_count':1,'dcp_path':str(self.dcp),'dcp_sha256':self.sha(self.dcp),
            'route_review_sha256':self.sha(self.review),'facts_sha256':self.sha(self.facts),'properties_sha256':self.sha(self.properties),
            'ports_tcl_sha256':self.sha(self.ports_tcl),'report_io_sha256':self.sha(self.report_io)}
    def refresh_query(self):self.query=self.write_json('query-report.json',self.query_data());self.args.query_report=str(self.query);self.args.query_report_sha256=self.sha(self.query)

class Full512SnapshotTests(unittest.TestCase):
    def with_fixture(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);return SnapshotFixture(Path(tmp.name))

    def test_complete_snapshot_and_all_eight_properties_match_old_pin_spec(self):
        f=self.with_fixture();result=io_snapshot.build_snapshot(f.args)
        self.assertEqual(result['port_count'],242);self.assertEqual(result['property_count'],1936)
        self.assertEqual(result['old_pin_spec']['compared_properties'],1936);self.assertEqual(result['old_pin_spec']['mismatch_count'],0)
        self.assertEqual(result['ports']['port_000']['PACKAGE_PIN'],'PIN000')

    def test_wrong_design_identity_rejected(self):
        f=self.with_fixture();text=f.facts.read_text().replace('ypcb_ddr_dual_top','ypcb_ddr_ew_top',1);f.facts.write_text(text);f.refresh_query()
        with self.assertRaisesRegex(ValueError,'wrong routed design/top/part/config properties'):
            io_snapshot.build_snapshot(f.args)

    def test_duplicate_header_rejected(self):
        f=self.with_fixture();f.facts.write_text(f.facts.read_text()+'PORT_COUNT\t242\n');f.refresh_query()
        with self.assertRaisesRegex(ValueError,'exactly one PORT_COUNT'):
            io_snapshot.build_snapshot(f.args)

    def test_unknown_or_duplicate_property_rows_rejected(self):
        f=self.with_fixture();f.facts.write_text(f.facts.read_text()+'UNKNOWN\trow\n');f.refresh_query()
        with self.assertRaisesRegex(ValueError,'unknown facts row'):
            io_snapshot.build_snapshot(f.args)
        f=self.with_fixture();first=next(line for line in f.facts.read_text().splitlines() if line.startswith('PORT\t0\tport_000\tPACKAGE_PIN'))
        f.facts.write_text(f.facts.read_text()+first+'\n');f.refresh_query()
        with self.assertRaisesRegex(ValueError,'duplicate property'):
            io_snapshot.build_snapshot(f.args)

    def test_missing_property_and_wrong_route_dcp_binding_rejected(self):
        f=self.with_fixture();lines=f.facts.read_text().splitlines();lines.remove(next(x for x in lines if x.startswith('PORT\t0\tport_000\tDRIVE')));f.facts.write_text('\n'.join(lines)+'\n');f.refresh_query()
        with self.assertRaisesRegex(ValueError,'1936 properties'):
            io_snapshot.build_snapshot(f.args)
        f=self.with_fixture();f.args.expected_dcp_sha256='0'*64
        with self.assertRaisesRegex(ValueError,'native query report bound to wrong DCP'):
            io_snapshot.build_snapshot(f.args)

    def test_native_query_must_exit_zero_and_emit_standalone_marker(self):
        f=self.with_fixture();q=json.loads(f.query.read_text());q['returncode']=1;f.query=f.write_json('query-report.json',q);f.args.query_report=str(f.query);f.args.query_report_sha256=f.sha(f.query)
        with self.assertRaisesRegex(ValueError,'rc0 and one standalone PASS marker'):
            io_snapshot.build_snapshot(f.args)


    def test_wrong_part_and_configuration_rejected(self):
        for old,new in [('xc7k480tffg1156-2','xc7k480tffg1156-1'),('1.8','3.3')]:
            with self.subTest(change=(old,new)):
                f=self.with_fixture();f.facts.write_text(f.facts.read_text().replace(old,new,1));f.refresh_query()
                with self.assertRaisesRegex(ValueError,'wrong routed design/top/part/config properties'):
                    io_snapshot.build_snapshot(f.args)

    def test_wrong_route_review_status_rejected(self):
        f=self.with_fixture();review=json.loads(f.review.read_text());review['status']='RUNNING';f.review=f.write_json('route-review.json',review)
        query=json.loads(f.query.read_text());query['route_review_sha256']=f.sha(f.review);f.query=f.write_json('query-report.json',query)
        f.args.route_review=str(f.review);f.args.query_report=str(f.query);f.args.query_report_sha256=f.sha(f.query)
        with self.assertRaisesRegex(ValueError,'independent route review does not pass/bind'):
            io_snapshot.build_snapshot(f.args)

    def test_old_physical_pin_spec_mismatch_rejected(self):
        f=self.with_fixture();text=f.facts.read_text().replace('port_000\tPACKAGE_PIN\tPIN000','port_000\tPACKAGE_PIN\tPIN999');f.facts.write_text(text);f.refresh_query()
        with self.assertRaisesRegex(ValueError,'port properties differ'):
            io_snapshot.build_snapshot(f.args)

if __name__=='__main__':unittest.main()
