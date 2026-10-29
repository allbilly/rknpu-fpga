"""Bind the read-only IO query after the live route's independent review."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
QUERY = BASE / 'io-query-v1'
ROUTE = ROOT / 'build/full512-capacity-retire-route-run-v1'
VIVADO = ROOT.parent / 'vivado/2026.1/Vivado/bin/vivado'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    review_path = ROUTE / 'root-route-review.json'
    if not review_path.is_file():
        print(json.dumps(dict(status='PENDING_INDEPENDENT_RETIRE_ROUTE_REVIEW',
                              vivado_executed=False, hardware_accessed=False)))
        return 0
    review = load(review_path)
    report_path = ROUTE / 'report.json'
    report = load(report_path)
    dcp = ROUTE / 'output/post_route.dcp'
    need(review['status'] == 'PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING' and
         review['producer_sha256'] == sha(report_path), 'Wrong or changed route review')
    need(report['status'] == 'PASS_FRESH_FULL512_RETIRE_ROUTE_REQUIRES_ROOT_REVIEW' and
         report['all_inputs_unchanged'] is True and report['all_owned_groups_stopped'] is True,
         'Route is not a complete source/ownership-qualified pass')
    need(sha(dcp) == review['post_route_dcp_sha256'] == report['outputs'][str(dcp)],
         'Wrong route checkpoint')
    hardware_path = BASE / 'hardware-source-manifest.json'
    hardware = load(hardware_path)
    need(hardware.get('profile') == 'full512-ch1-ddr-capacity-retire-snapshot-ecc-test-off',
         'Wrong retirement hardware profile')
    digest = hashlib.sha256(json.dumps(hardware, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    need(len(hardware['files']) == 171, 'Wrong retirement source inventory')
    inputs = dict(hardware['files'])
    for path, expected in inputs.items():
        need(sha(path) == expected, 'Changed hardware source: ' + path)
    for path in (QUERY / 'run_io_query.py', QUERY / 'io_query.tcl', QUERY / 'io_snapshot.py',
                 hardware_path, BASE / 'lineage.json', Path(__file__), VIVADO):
        inputs[str(path.resolve())] = sha(path)
    binding = dict(status='ROOT_BOUND_RETIRE_READ_ONLY_IO_QUERY',
                   source_manifest_sha256=digest, source_tag=digest[:8],
                   source_inputs=inputs, vivado_sha256=sha(VIVADO),
                   route_gate=dict(route_report_path=str(report_path), report_sha256=sha(report_path),
                                   review_path=str(review_path), review_sha256=sha(review_path),
                                   post_route_dcp_path=str(dcp), post_route_dcp_sha256=sha(dcp)),
                   hardware_accessed=False, scope='Read-only checkpoint query; no implementation or programming')
    with (QUERY / 'io-bindings.json').open('x') as stream:
        stream.write(json.dumps(binding, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(status=binding['status'], source_tag=digest[:8])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
