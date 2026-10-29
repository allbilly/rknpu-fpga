"""Pure capacity-image preparation; does not launch Vivado or access hardware."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.ddr import full512_image_template as renderer

BASE = Path(__file__).resolve().parent
BINDINGS = BASE / 'bindings.json'
MANIFEST = BASE / 'hardware-source-manifest.json'
TEMPLATE = BASE / 'emit_capacity.tcl.in'
ROUTE = ROOT / 'build/full512-capacity-retire-route-run-v1/output/post_route.dcp'
ANCHORS = ROOT / 'build/full512-capacity-retire-route-run-v1/expected-anchors.txt'
REQUIRED_GATES = {
    'synthesis': 'PASS_ROOT_FRESH_FULL512_RETIRE_SYNTHESIS_ONLY',
    'fast_parent': 'PASS_ROOT_RETIRE_SNAPSHOT_FAST_PARENT_MODEL_ONLY',
    'paired_adapter_monitor': 'PASS_ROOT_PAIRED_RETIRE_ADAPTER_AND_MONITOR_CONTRACT_ONLY',
    'public_regression': 'PASS_ROOT_CURRENT_V19_SOURCE_NATIVE_HOST_ONLY',
    'controller_capacity': 'PASS_ROOT_FULL512_RETIRE_CAPACITY_CONTROLLER_MODEL_ONLY',
    'route': 'PASS_ROOT_FULL512_RETIRE_ROUTE_TIMING',
}


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    hardware = load(MANIFEST)
    need(len(hardware['files']) == 171 and hardware['top'] == 'ypcb_ddr_dual_top' and
         hardware['part'] == 'xc7k480tffg1156-2' and
         hardware['profile'] == 'full512-ch1-ddr-capacity-retire-snapshot-ecc-test-off', 'Wrong retirement-profile hardware manifest')
    source_hash = hashlib.sha256(json.dumps(hardware, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    controller_files = [Path(path).name for path in hardware['files']]
    need(controller_files.count('rk_job_control_admission.sv') == 1 and
         controller_files.count('rk_dual_job_control_admission.sv') == 1,
         'Capacity admission-controller source files must be present exactly once')
    inputs = dict(hardware['files'])
    for path, digest in inputs.items():
        need(sha(path) == digest, 'Changed retirement hardware source: ' + path)
    if not BINDINGS.is_file():
        print(json.dumps(dict(status='PREPARED_PENDING_RETIRE_QUALIFICATION_BINDINGS',
                              required_gates=REQUIRED_GATES, required_post_route_dcp=str(ROUTE),
                              source_tag=source_hash[:8], vivado_executed=False, hardware_accessed=False)))
        return 0
    bindings = load(BINDINGS)
    need(bindings['source_manifest_sha256'] == source_hash and bindings['render_approved'] is True,
         'Root render approval/source binding absent')
    need(set(bindings['gates']) == set(REQUIRED_GATES), 'Missing or extra qualification gate')
    for name, expected in REQUIRED_GATES.items():
        gate = bindings['gates'][name]
        path = Path(gate['path'])
        need(sha(path) == gate['sha256'] and load(path)['status'] == expected,
             'Qualification gate missing, changed or incomplete: ' + name)
        inputs[str(path.resolve())] = gate['sha256']
    need(sha(ROUTE) == bindings['post_route_dcp_sha256'], 'Wrong new retirement route DCP')
    route_review = load(bindings['gates']['route']['path'])
    need(route_review['post_route_dcp_sha256'] == sha(ROUTE), 'Route review binds another DCP')
    io_path = Path(bindings['io_snapshot']['path'])
    need(sha(io_path) == bindings['io_snapshot']['sha256'], 'IO snapshot changed')
    io = load(io_path)
    need(io['status'] == 'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT' and
         io['dcp']['sha256'] == sha(ROUTE), 'IO snapshot binds another route image')
    helper_dir = ROOT / 'build/full512-capacity-retire-vivado-prep-v1/source/constraint-helpers'
    helpers = {name: helper_dir / file for name, file in dict(reset_status='status_cdc.tcl',
                board_reset='board_reset.tcl', job_crossing='job_cdc.tcl',
                memory_crossing='memory_crossing.tcl', mailbox_ui='mailbox_ui.tcl',
                cmac_permit='permit_cdc.tcl').items()}
    for path in (MANIFEST, TEMPLATE, BINDINGS, Path(__file__), renderer.TEMPLATE,
                 ROOT / 'tools/ddr/full512_image_template.py',
                 ROOT / 'tools/hardware/sample_ew.py', ANCHORS, ROUTE, io_path, *helpers.values()):
        inputs[str(path.resolve())] = sha(path)
    renderer.TEMPLATE = TEMPLATE
    text = renderer.render(ROUTE, BASE / 'emission', inputs, helpers, io['ports'], source_hash[:8])
    need(not (BASE / 'emission').exists(), 'Fresh image output required')
    for path, digest in inputs.items():
        need(sha(path) == digest, 'Image input changed during render: ' + path)
    with (BASE / 'emit_capacity.tcl').open('x') as stream:
        stream.write(text)
    result = dict(status='PREPARED_ROOT_BOUND_FULL512_RETIRE_EMISSION_ONLY',
                  source_manifest_sha256=source_hash, source_tag=source_hash[:8],
                  hardware_source_manifest=hardware, input_hashes=inputs,
                  tcl_path=str(BASE / 'emit_capacity.tcl'), tcl_sha256=sha(BASE / 'emit_capacity.tcl'),
                  route_dcp_path=str(ROUTE), route_dcp_sha256=sha(ROUTE),
                  output_directory=str(BASE / 'emission'), vivado_executed=False, hardware_accessed=False)
    with (BASE / 'image-preparation.json').open('x') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(dict(status=result['status'], source_tag=result['source_tag'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
