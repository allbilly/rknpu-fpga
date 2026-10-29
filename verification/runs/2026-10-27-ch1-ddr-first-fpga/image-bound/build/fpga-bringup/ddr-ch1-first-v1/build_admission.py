"""Bind the already-reviewed offline DAG and exact controlled trial sources."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import sys

ROOT = Path('/home/fedora/rknpu-fpga')
HW = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def read(path):
    return json.loads(path.read_text())


def main():
    output = HW/'image-review.json'
    need(not output.exists(), 'Fresh admission path required')
    emitted = ROOT/'build/ypcb-ddr-shell/ch1-image-v2'
    facts_dir = ROOT/'build/ypcb-ddr-shell/ch1-image-bitfile-review-v1'
    report = read(emitted/'report.json')
    prep = read(emitted/'preparation.json')
    facts = read(facts_dir/'root-review-facts.json')
    packets = read(facts_dir/'packet_inventory.json')
    route_review = ROOT/'build/ypcb-ddr-shell/ch1-routed-root-review-v1.json'
    route = read(route_review)
    need(report['status'] == 'PASS_NATIVE_CH1_IMAGE_EMISSION_REQUIRES_INDEPENDENT_BITSTREAM_REVIEW' and report['returncode'] == 0, 'Emission failed')
    need(facts['status'] == 'PASS_READONLY_BITFILE_STRUCTURE_REVIEW_ONLY', 'Independent file review absent')
    need(route['status'] == 'REVIEWED_CH1_INTERNAL_TIMING_CDC_AND_FACTORY_IO_FOR_CONTROLLED_BRINGUP', 'Routed source review absent')
    need(prep['selected_physical_channel'] == 1 and prep['fpga_part'] == 'xc7k480tffg1156-2', 'Wrong source profile')
    need([p['value'] for p in packets['reg13_axss_writes']] == [int(report['usr_access'], 16)], 'Wrong AXSS')
    need(not packets['cmd15_iprog_seen'] and facts['crc_software_validation'] == 'NOT_PERFORMED', 'Wrong file policy')
    need(report['bitstream']['sha256'] == facts['bit_sha256'] == '45bd540cfaf7327ad8db5ba4e3a7548a209db1aeba4423f37159a72287296339', 'Wrong bitfile')
    bound = {}

    def bind(path, expected=None):
        path = Path(path)
        if not path.is_absolute():
            path = ROOT/path
        digest = sha(path)
        need(expected is None or digest == expected, 'Changed evidence/input: ' + str(path))
        need(str(path) not in bound or bound[str(path)] == digest, 'Conflicting binding')
        bound[str(path)] = digest

    for source in (prep['inputs'], report['inputs']):
        for name, digest in source.items():
            bind(name, digest)
    for name, digest in report['artifacts'].items():
        bind(emitted/name, digest)
    for path in [emitted/'report.json', emitted/'preparation.json', route_review,
                 facts_dir/'root-review-facts.json', facts_dir/'packet_inventory.json',
                 facts_dir/'bitstream_check.json', Path(facts['checker_path']),
                 ROOT/'build/ddr-physical-preflight-controls-v1/report.json']:
        bind(path)
    fixture_dir = ROOT/'build/ddr-read-snapshot-candidate/v2/workspace/build/ddr-endpoint-async/native-read-snapshot-v3/vectors/capture_sub_9'
    for name, expected in [('upload.txt', '68cf7b0689343f22c979db0312eb718906a34d51c54e893699039f7630c885fb'),
                           ('expected.txt', 'aca0f96badf878e82a9358eb2e5405f1ff97db706220e25e712555c38f10efec')]:
        bind(fixture_dir/name, expected)
    source_template = ROOT/'build/fpga-bringup/tinystories-model-wait-20261027T035254Z/program-template.tcl.in'
    template = source_template.read_text()
    template = template.replace('set expected_access @USR_ACCESS@', 'set expected_access @USR_ACCESS@\nset expected_bit_sha @BITSTREAM_SHA@')
    guard = '''proc verify_program_file {path expected} {
    if {![file isfile $path]} {error "Reviewed bitstream is missing"}
    set actual [lindex [exec sha256sum -- $path] 0]
    if {![string equal $actual $expected]} {error "Reviewed bitstream SHA256 mismatch"}
}
'''
    template = template.replace('set failed [catch {\n    open_hw_manager', guard+'set failed [catch {\n    verify_program_file $bitstream $expected_bit_sha\n    puts $out "BITSTREAM_SHA256\\t$expected_bit_sha"\n    open_hw_manager')
    template = template.replace('    set_property PROGRAM.FILE $bitstream $dev', '    verify_program_file $bitstream $expected_bit_sha\n    set_property PROGRAM.FILE $bitstream $dev')
    need(template.count('verify_program_file $bitstream $expected_bit_sha') == 2, 'Missing pre-hardware/pre-load SHA guards')
    template_path = HW/'program-template.tcl.in'
    need(not template_path.exists(), 'Fresh program template required')
    template_path.write_text(template)
    bind(source_template)
    for path in [template_path, Path(__file__), HW/'run_sram_test.py']:
        bind(path)
    spec = importlib.util.spec_from_file_location('ch1_trial_preflight', HW/'run_sram_test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for module in list(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name and Path(name).is_relative_to(ROOT) and Path(name).is_file():
            bind(name)
    bind('/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/vivado_lab')
    bind('/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/hw_server')
    review = dict(status='REVIEWED_EXPERIMENTAL_CH1_EW_DDR_IMAGE_FOR_VOLATILE_TRIAL',
        part=prep['fpga_part'], selected_physical_channel=1, source_sha256=report['source_sha256'],
        usr_access=report['usr_access'], bitstream=report['bitstream'],
        target='localhost:3125/xilinx_tcf/Xilinx/80802026a77a01', expected_dna_port='004E544714C705C',
        expected_raw_idcode='23751093', transport_id=prep['transport_id'], abi=prep['abi'],
        programming_scope='volatile-sram', flash_authorized=False, hardware_accessed=False,
        physical_ddr_qualified=False, electrical_signoff=False, software_crc_validation='NOT_PERFORMED',
        setup_ns=route['setup_ns'], hold_ns=route['hold_ns'], pulse_ns=route['pulse_ns'],
        raw_fixture=dict(name='capture_sub_9', upload=str(fixture_dir/'upload.txt'), expected=str(fixture_dir/'expected.txt'),
                         command_address=0x100e0000, initial_amount=35, expected_tasks=2, complete_bo_bytes=102400),
        permitted_trial='Six 64B scratch addresses, two orders, then fixed raw SUB9 with full BO readback before ACK; stop at first failure; no retry/reset/fallback',
        excludes=['full-capacity qualification', 'ECC fault-injection qualification', 'full512 DDR', 'PCIe execution', 'RK silicon equivalence', 'production electrical signoff'],
        bound_files=bound, created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    output.write_text(json.dumps(review, indent=2)+'\n')
    print(json.dumps(dict(status=review['status'], bound_files=len(bound), path=str(output))))


if __name__ == '__main__':
    main()
