"""Seal the already reviewed emission recipe once all actual gates pass."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASE = Path(__file__).resolve().parent
PATHS = {
    'synthesis': ROOT / 'build/full512-capacity-retire-vivado-run-v1/root-synth-review.json',
    'fast_parent': ROOT / 'build/full512-capacity-retire-fast-model-v1/root-result-review.json',
    'paired_adapter_monitor': ROOT / 'build/full512-capacity-retire-snapshot-controls-v1/root-paired-v3-review.json',
    'public_regression': ROOT / 'build/production-model-auditors/current-v19/root-review.json',
    'controller_capacity': ROOT / 'build/full512-capacity-retire-controller-v1/root-result-review.json',
    'route': ROOT / 'build/full512-capacity-retire-route-run-v1/root-route-review.json',
}
IO = ROOT / 'build/full512-capacity-retire-image-prep-v1/io-query-v1/io-snapshot/full512-io-snapshot.json'
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
    spec = importlib.util.spec_from_file_location('capacity_image_preparer', BASE / 'prepare_image.py')
    preparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparer)
    pending = [name for name, path in PATHS.items() if not path.is_file()]
    if not IO.is_file():
        pending.append('routed_io_snapshot')
    if pending:
        print(json.dumps(dict(status='PENDING_RETIRE_IMAGE_BINDINGS', pending=pending,
                              vivado_executed=False, hardware_accessed=False)))
        return 0
    gates = {}
    for name, path in PATHS.items():
        need(load(path)['status'] == preparer.REQUIRED_GATES[name], 'Required gate has not passed: ' + name)
        gates[name] = dict(path=str(path), sha256=sha(path))
    route = load(PATHS['route'])
    dcp = ROOT / 'build/full512-capacity-retire-route-run-v1/output/post_route.dcp'
    need(sha(dcp) == route['post_route_dcp_sha256'], 'Reviewed route checkpoint changed')
    io = load(IO)
    need(io['status'] == 'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT' and
         io['dcp']['sha256'] == sha(dcp) and (io['port_count'], io['property_count']) == (242, 1936),
         'Missing or changed actual routed IO snapshot')
    hardware = load(BASE / 'hardware-source-manifest.json')
    need(hardware.get('profile') == 'full512-ch1-ddr-capacity-retire-snapshot-ecc-test-off' and
         len(hardware.get('files', {})) == 171, 'Wrong retirement hardware profile/source count')
    digest = hashlib.sha256(json.dumps(hardware, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    bindings = dict(source_manifest_sha256=digest, render_approved=True, gates=gates,
                    post_route_dcp_sha256=sha(dcp), io_snapshot=dict(path=str(IO), sha256=sha(IO)))
    with (BASE / 'bindings.json').open('x') as stream:
        stream.write(json.dumps(bindings, indent=2, sort_keys=True) + '\n')
    need(preparer.main() == 0, 'Reviewed emission recipe did not render')
    prep = load(BASE / 'image-preparation.json')
    need(prep['status'] == 'PREPARED_ROOT_BOUND_FULL512_RETIRE_EMISSION_ONLY' and
         prep['source_manifest_sha256'] == digest and prep['source_tag'] == digest[:8],
         'Rendered source identity changed')
    approval = dict(status='ROOT_APPROVED_RETIRE_IMAGE_EMISSION', launch_approved=True,
                    image_preparation_sha256=sha(BASE / 'image-preparation.json'),
                    run_image_sha256=sha(BASE / 'run_image.py'), vivado_launcher_sha256=sha(VIVADO),
                    source_manifest_sha256=digest, source_tag=digest[:8], route_dcp_sha256=sha(dcp),
                    tcl_sha256=prep['tcl_sha256'], binder_sha256=sha(__file__),
                    scope='Previously reviewed strict image recipe; 2400s/8GiB/2CPU, no implementation/programming/flash')
    with (BASE / 'root-bindings.json').open('x') as stream:
        stream.write(json.dumps(approval, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(status=approval['status'], source_tag=digest[:8],
                          vivado_executed=False, hardware_accessed=False)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
