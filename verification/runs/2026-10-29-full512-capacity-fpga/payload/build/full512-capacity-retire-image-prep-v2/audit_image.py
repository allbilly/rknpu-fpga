"""Independent retirement-capacity bitfile audit; no native FPGA tools or hardware."""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json,re

ROOT=Path('/home/fedora/rknpu-fpga');BASE=Path(__file__).resolve().parent
LIBRARY=ROOT/'build/full512-ddr-preparation/full512-bitfile-audit-v1/audit_image.py'
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)
def load(p):return json.loads(Path(p).read_text())
def verify(mapping):
    for p,h in mapping.items():need(Path(p).is_file() and sha(p)==h,'Changed audit input/output '+p)

def audit(expected_preparation_sha,expected_emission_sha,expected_route_sha):
    prep_path=BASE/'image-preparation.json';emission_path=BASE/'emission-report.json'
    route_path=ROOT/'build/full512-capacity-retire-route-run-v1/root-route-review.json'
    need(sha(prep_path)==expected_preparation_sha and sha(emission_path)==expected_emission_sha and
         sha(route_path)==expected_route_sha,'Externally bound image/route receipts differ')
    prep=load(prep_path);r=load(emission_path);route=load(route_path)
    need(prep['status']=='PREPARED_ROOT_BOUND_FULL512_RETIRE_EMISSION_ONLY' and
         r['status']=='PASS_FULL512_RETIRE_IMAGE_EMITTED_REQUIRES_BITFILE_REVIEW','Emitter incomplete/failed')
    need(r['returncode']==0 and r['all_inputs_unchanged'] is True and
         not r['owned_pids_after_cleanup'] and r['bitstream_emitted'] is True,'Emitter ownership/source gate failed')
    need(all(r[k] is False for k in ('hardware_accessed','hardware_programmed','flash_written')),'Emitter exceeded offline scope')
    need(r['input_hashes_before']==r['input_hashes_expected']==r['input_hashes_after'],'Emission before/after input drift')
    verify(r['input_hashes_expected']);verify(r['outputs'])
    hardware=prep['hardware_source_manifest']
    source_sha=hashlib.sha256(json.dumps(hardware,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    need(source_sha==prep['source_manifest_sha256']==r['source_manifest_sha256'] and
         source_sha[:8]==prep['source_tag']==r['source_tag']=='2c8f17dd','Wrong retirement source/tag')
    need(hardware['top']=='ypcb_ddr_dual_top' and hardware['part']=='xc7k480tffg1156-2' and
         hardware['profile']=='full512-ch1-ddr-capacity-retire-snapshot-ecc-test-off' and
         len(hardware['files'])==171,'Wrong 171-file hardware closure')
    verify(hardware['files'])
    need(route['status']=='PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING' and
         route['post_route_dcp_sha256']==prep['route_dcp_sha256']==r['route_dcp_sha256'] and
         (route['product_dsps'],route['total_dsps'],route['ports'])==(512,516,242),'Wrong route/image compute binding')
    need(sha(prep['route_dcp_path'])==r['route_dcp_sha256'],'Actual route checkpoint changed')
    out=BASE/'emission';bit=out/'full512-ddr-ch1-user2.bit';dcp=out/'image.dcp'
    need(r['bitstream_path']==str(bit) and sha(bit)==r['bitstream_sha256'] and
         sha(dcp)==r['image_dcp_sha256'],'Emitted bitfile/image checkpoint changed')
    need(set(r['outputs'])=={str(p) for p in out.rglob('*') if p.is_file()},'Missing or extra emitted artifact')
    stdout=(BASE/'stdout.log').read_text()
    need(stdout.splitlines().count('PASS_REVIEWED_FULL512_RETIRE_BITSTREAM_EMISSION_ONLY')==1 and
         not (BASE/'stderr.log').read_bytes(),'Missing clean native emission marker')
    for p in (BASE/'stdout.log',BASE/'vivado.log'):
        need(not re.search(r'^\s*(?:ERROR|CRITICAL WARNING)\s*:',p.read_text(),re.M|re.I),'Unreviewed native emission error/critical warning')
    spec=importlib.util.spec_from_file_location('retire_bitfile_packet_library',LIBRARY)
    lib=importlib.util.module_from_spec(spec);spec.loader.exec_module(lib)
    library_sha=sha(LIBRARY)
    drc={name:lib.drc_inventory(out/name) for name in ('default_drc.rpt','bitstream_drc.rpt')}
    checker=lib.load_checker();checked=checker.check(bit,r['bitstream_sha256'])
    need(checked['status']=='PASS' and checked['crc']=='NOT_CHECKED' and
         checked['programming']==checked['physical_hardware']=='NOT_RUN','Independent checker failed/exceeded its scope')
    packets=lib.packet_inventory(bit.read_bytes(),checked['structure'],source_sha[:8])
    verify(r['input_hashes_expected']);verify(r['outputs']);verify(hardware['files'])
    need(sha(prep_path)==expected_preparation_sha and sha(emission_path)==expected_emission_sha and
         sha(route_path)==expected_route_sha and sha(LIBRARY)==library_sha,'Audit receipts/library mutated')
    bound={**r['input_hashes_expected'],**r['outputs']}
    for p in (prep_path,emission_path,route_path,LIBRARY,lib.CHECKER,Path(__file__),BASE/'stdout.log',BASE/'stderr.log',BASE/'vivado.log'):
        bound[str(p)]=sha(p)
    return dict(status='PASS_INDEPENDENT_FULL512_RETIRE_BITFILE_AUDIT',
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_tag=source_sha[:8],source_manifest_sha256=source_sha,
        preparation_sha256=expected_preparation_sha,emission_report_sha256=expected_emission_sha,
        route_review_sha256=expected_route_sha,bitstream_sha256=sha(bit),bitstream_bytes=bit.stat().st_size,
        image_dcp_sha256=sha(dcp),post_route_dcp_sha256=r['route_dcp_sha256'],
        bound_files=bound,checker_source_sha256=lib.CHECKER_SHA,packet_library_sha256=library_sha,
        auditor_sha256=sha(__file__),checker=checked,packets=packets,drc=drc,
        hardware_accessed=False,flash_written=False,image_programming_admitted=False,
        scope='Fresh retirement image emission, complete source/output hashes, exact two-ruledeck DRC, bitfile container/IDCODE/USR_ACCESS/packet bounds. No software CRC or physical execution proof.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preparation-sha256',required=True);p.add_argument('--emission-sha256',required=True)
    p.add_argument('--route-review-sha256',required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();need(not args.out.exists(),'Fresh independent bitfile audit receipt required')
    result=audit(args.preparation_sha256,args.emission_sha256,args.route_review_sha256)
    with args.out.open('x') as f:f.write(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ('status','source_tag','bitstream_sha256','bitstream_bytes')}))
if __name__=='__main__':main()
