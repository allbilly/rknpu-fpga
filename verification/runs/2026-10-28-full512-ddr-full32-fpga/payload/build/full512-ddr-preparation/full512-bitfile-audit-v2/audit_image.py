"""Read-only full512 bitfile/emitter review. Never implements or programs.

The independent container checker and packet inventory do not validate CRCs in
software. Image/route source binding is checked separately from physical use.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.util
import json
import re
import struct

CHECKER = Path('/home/fedora/ypcb/local-overrides/projects-bonetto-soc/files/scripts/fedora-check-vivado-bitstream.py')
CHECKER_SHA = '480f6a4bd7ee7e5e7f6c9eee5750a3f1e223f52a4f87cb694afade7d0558f756'
EXPECTED_DRC = {'DPIP-1': 1032, 'DPOP-1': 516, 'DPOP-2': 516, 'REQP-1709': 2}
PART = 'xc7k480tffg1156-2'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_map(expected, base=None):
    actual = {}
    for name, digest in expected.items():
        p = Path(name)
        if base is not None:
            need(not p.is_absolute(), 'Output inventory contains an absolute path')
            p = (base/p).resolve()
            need(p.is_relative_to(base), 'Output inventory escapes emission directory')
        need(p.is_file() and sha(p) == digest, 'Changed bound file: '+str(p))
        actual[str(p)] = digest
    return actual


def load_checker():
    need(sha(CHECKER) == CHECKER_SHA, 'Independent checker source changed')
    spec = importlib.util.spec_from_file_location('reviewed_bitfile_checker', CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    need(module.TARGET_IDCODE == 0x03751093, 'Checker configuration IDCODE changed')
    return module


def packet_inventory(data, structure, source_tag):
    """Inventory actual packet words without expanding multi-million-word FDRI."""
    need(re.fullmatch(r'[0-9a-f]{8}', source_tag) and source_tag != '00000000',
         'Malformed source tag')
    payload_offset = structure['payload_offset']
    payload = memoryview(data)[payload_offset:]
    cursor = structure['sync_offset']+4
    fdri_context = False
    packets = []
    registers = {0: [], 4: [], 12: [], 13: []}
    fdri_words = 0
    while cursor < len(payload):
        need(cursor+4 <= len(payload), 'Truncated packet header')
        position = cursor
        word = struct.unpack_from('>I', payload, cursor)[0]
        cursor += 4
        if word in (0, 0xffffffff):
            continue
        kind, opcode = (word >> 29) & 7, (word >> 27) & 3
        need(kind in (1, 2) and opcode in (0, 2),
             'Unknown or READ packet in reviewed write-only configuration')
        if kind == 1:
            register, count = (word >> 13) & 0x3fff, word & 0x7ff
            if opcode == 0:
                need(word == 0x20000000, 'Malformed NOP packet/count')
                fdri_context = False
            else:
                need(word & 0x1800 == 0, 'Reserved Type-1 packet bits')
                fdri_context = register == 2 and count == 0
        else:
            need(fdri_context and opcode == 2, 'Type-2 packet lacks immediate FDRI write context')
            register, count = 2, word & 0x7ffffff
            fdri_context = False
        need(cursor+4*count <= len(payload), 'Packet data overruns payload')
        packets.append(dict(offset=payload_offset+position, register=register,
                            opcode=opcode, type=kind, word_count=count))
        if opcode == 2 and register == 2:
            fdri_words += count
        if opcode == 2 and register in registers:
            # These are configuration control words, never frame data.
            need(count <= 64, 'Unexpected control-register packet size')
            for index in range(count):
                value = struct.unpack_from('>I', payload, cursor+4*index)[0]
                registers[register].append(dict(offset=payload_offset+cursor+4*index,
                                                value=value))
        cursor += 4*count
    need([r['value'] for r in registers[12]] == [0x03751093],
         'Wrong configuration IDCODE words')
    tags = [r['value'] for r in registers[13]]
    need(tags and all(value == int(source_tag, 16) for value in tags),
         'USR_ACCESS/AXSS differs from source manifest')
    commands = [r['value'] for r in registers[4]]
    need(15 not in commands, 'IPROG command is forbidden in this volatile image')
    need(5 in commands and 13 in commands, 'Missing START/DESYNC')
    need(registers[0] and fdri_words == structure['fdri_words'] > 100000,
         'Missing encoded CRC words or substantial frame data')
    return dict(packet_count=len(packets), packets=packets, fdri_words=fdri_words,
                idcode_words=registers[12], usr_access_words=registers[13],
                command_words=registers[4], encoded_crc_words=registers[0],
                iprog_seen=False, crc_software_validation='NOT_CHECKED')


def drc_inventory(path):
    text = Path(path).read_text()
    totals = re.findall(r'Checks found:\s*(\d+)', text)
    need(len(totals) == 1 and int(totals[0]) == sum(EXPECTED_DRC.values()),
         'Missing or changed DRC total')
    actual = {}
    for line in text.splitlines():
        columns = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(columns) != 4 or not re.fullmatch(r'[A-Z][A-Z0-9_-]*-[0-9]+', columns[0]):
            continue
        rule, severity, _, count = columns
        need(rule not in actual and severity == 'Warning' and count.isdigit(),
             'Duplicate or unreviewed DRC severity/count')
        actual[rule] = int(count)
    need(actual == EXPECTED_DRC, 'Default/bitstream DRC inventory changed')
    return actual


def audit(package, preparation_sha, emission_sha, route_review_sha):
    package = Path(package).resolve()
    prep_path, report_path = package/'image-preparation.json', package/'emission-report.json'
    need(sha(prep_path) == preparation_sha and sha(report_path) == emission_sha,
         'External preparation/emitter hashes differ')
    prep, report = json.loads(prep_path.read_text()), json.loads(report_path.read_text())
    need(prep['status'] == 'READY_FOR_ROOT_REVIEWED_FULL512_IMAGE_EMISSION'
         and prep['image_emission_approved'] is True, 'Image preparation was not admitted')
    need(report['status'] == 'PASS_FULL512_IMAGE_EMISSION_REQUIRES_INDEPENDENT_BITSTREAM_REVIEW'
         and report['returncode'] == 0 and report['bitstream_emitted'] is True,
         'Emitter has not completed successfully')
    need(report['all_inputs_unchanged'] is True and report['owned_process_group_stopped'] is True,
         'Emitter inputs or process ownership are not qualified')
    need(all(report[k] is False for k in ('hardware_accessed', 'hardware_programmed', 'flash_written')),
         'Emitter crossed the offline boundary')
    need(report['input_hashes_expected'] == report['input_hashes_before'] == report['input_hashes_after'],
         'Emitter input hash maps differ')
    before = verify_map(report['input_hashes_expected'])
    source_inputs = verify_map(prep['source_inputs'])
    rendered_inputs = verify_map(prep['rendered_inputs'])
    binding_path = package/'root-bindings.json'
    binding_sha = sha(binding_path)
    binding = json.loads(binding_path.read_text())
    need(binding['status'] == 'ROOT_REVIEWED_FULL512_IMAGE_EMISSION'
         and binding['launch_approved'] is True
         and binding['image_preparation_sha256'] == preparation_sha,
         'Exact root image-emission approval is missing')
    need(report['input_hashes_expected'].get(str(binding_path)) == binding_sha,
         'Emitter input map does not bind root emission approval')
    need(binding['emission_tcl_path'] == prep['emission_tcl_path']
         and binding['emission_tcl_sha256'] == prep['emission_tcl_sha256']
         == sha(prep['emission_tcl_path']), 'Rendered emission Tcl differs from root approval')
    emitted = package/'emission'
    outputs = verify_map(report['output_hashes'], emitted)
    run_artifacts = verify_map(report['run_artifact_hashes'], package)
    manifest = prep['hardware_source_manifest']
    manifest_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    need(manifest_sha == prep['hardware_source_sha256'] and prep['source_tag'] == manifest_sha[:8],
         'Hardware manifest/source-tag mismatch')
    need(manifest['top'] == 'ypcb_ddr_dual_top' and manifest['part'] == PART
         and manifest['verilog_defines'] == ['DESIGNWARE_NOEXIST']
         and len(manifest['files']) == 163, 'Wrong hardware source profile/defines')
    root = Path('/home/fedora/rknpu-fpga')
    verify_map({str(root/n): h for n, h in manifest['files'].items()})
    route = prep['route_gate']
    route_path = Path(route['review_path'])
    need(sha(route_path) == route_review_sha == route['review_sha256'],
         'External route-review binding differs')
    reviewed = json.loads(route_path.read_text())
    route_report_path = Path(route['route_report_path'])
    need(sha(route_report_path) == route['report_sha256'], 'Route producer receipt changed')
    route_report = json.loads(route_report_path.read_text())
    need(route_report['status'] == route['required_report_status']
         and route_report['returncode'] == 0
         and route_report['all_inputs_unchanged'] is True
         and route_report['owned_process_group_stopped'] is True
         and route_report['output_hashes']['post_route.dcp'] == route['post_route_dcp_sha256'],
         'Route producer is incomplete or binds another checkpoint')
    need(reviewed['status'] == 'PASS_INDEPENDENT_FULL512_DDR_ROUTE_AND_TIMING_ONLY'
         and reviewed['post_route_dcp_sha256'] == route['post_route_dcp_sha256'] == report['route_dcp_sha256']
         and (reviewed['product_dsps'], reviewed['total_dsps'], reviewed['ports']) == (512, 516, 242),
         'Route review does not qualify this full512 checkpoint')
    need(sha(route['post_route_dcp_path']) == report['route_dcp_sha256'], 'Route DCP changed')
    io_path = Path(prep['io_snapshot_gate']['future_snapshot_json_path'])
    need(report['input_hashes_expected'].get(str(io_path)) == sha(io_path),
         'Emitter did not bind routed I/O snapshot')
    io = json.loads(io_path.read_text())
    need(io['status'] == 'PASS_READ_ONLY_FULL512_ROUTED_242_PORT_PROPERTY_SNAPSHOT'
         and io['dcp']['sha256'] == report['route_dcp_sha256']
         and io['port_count'] == 242 and io['property_count'] == 1936,
         'Wrong routed I/O source/profile/coverage')
    for gate in prep['qualification_gates'].values():
        need(sha(gate['path']) == gate['sha256'], 'Logical gate changed')
        value = json.loads(Path(gate['path']).read_text())
        need(value[gate['status_field']] == gate['required_status'], 'Logical gate is incomplete')
        if gate.get('expected_case_count') is not None:
            need(value[gate['count_field']] == gate['expected_case_count'], 'Controller union count differs')
    bit = emitted/'full512-ddr-ch1-user2.bit'
    need(report['bitstream_path'] == str(bit) and sha(bit) == report['bitstream_sha256']
         and bit.stat().st_size == report['bitstream_bytes'], 'Emitted bitfile identity differs')
    need(sha(emitted/'image.dcp') == report['image_dcp_sha256'], 'Emitted checkpoint identity differs')
    stdout = (package/'stdout.log').read_text()
    need(stdout.splitlines().count('PASS_REVIEWED_FULL512_CH1_DDR_BITSTREAM_EMISSION_ONLY') == 1,
         'Missing exact native image marker')
    need(not (package/'stderr.log').read_bytes(), 'Emitter has unexpected stderr')
    for name in ('stdout.log', 'vivado.log'):
        need(not re.search(r'^\s*(?:ERROR|CRITICAL WARNING)\s*:', (package/name).read_text(), re.M | re.I),
             'Unreviewed native emitter error/critical warning')
    drcs = {name: drc_inventory(emitted/name) for name in ('default_drc.rpt', 'bitstream_drc.rpt')}
    checker = load_checker()
    checked = checker.check(bit, report['bitstream_sha256'])
    need(checked['status'] == 'PASS' and checked['crc'] == 'NOT_CHECKED'
         and checked['programming'] == checked['physical_hardware'] == 'NOT_RUN',
         'Independent checker crossed its scope')
    packets = packet_inventory(bit.read_bytes(), checked['structure'], prep['source_tag'])
    need(verify_map(report['input_hashes_expected']) == before
         and verify_map(report['output_hashes'], emitted) == outputs
         and verify_map(report['run_artifact_hashes'], package) == run_artifacts
         and verify_map(prep['source_inputs']) == source_inputs
         and verify_map(prep['rendered_inputs']) == rendered_inputs
         and sha(binding_path) == binding_sha
         and sha(prep_path) == preparation_sha and sha(report_path) == emission_sha
         and sha(CHECKER) == CHECKER_SHA,
         'Image review input/output changed during audit')
    return dict(status='PASS_FULL512_DDR_BITFILE_AND_EMISSION_AUDIT_ONLY',
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scope='Source-bound native image emission, exact DRC counts, bitfile container/IDCODE/AXSS and packet bounds; no FPGA execution or software CRC proof',
        preparation_sha256=preparation_sha, emission_report_sha256=emission_sha,
        route_review_sha256=route_review_sha, source_sha256=manifest_sha,
        source_tag=prep['source_tag'], bitstream_sha256=sha(bit),
        bitstream_bytes=bit.stat().st_size, image_dcp_sha256=sha(emitted/'image.dcp'),
        bound_inputs_rehashed=len(before), output_files_rehashed=len(outputs),
        checker_source_sha256=CHECKER_SHA, auditor_source_sha256=sha(__file__),
        checker=checked, packets=packets, drc=drcs,
        hardware_accessed=False, flash_written=False, image_programming_admitted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--preparation-sha256', required=True)
    parser.add_argument('--emission-sha256', required=True)
    parser.add_argument('--route-review-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    need(not args.out.exists(), 'Fresh independent audit receipt required')
    result = audit(args.package, args.preparation_sha256, args.emission_sha256, args.route_review_sha256)
    with args.out.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(result['status'])


if __name__ == '__main__':
    main()
