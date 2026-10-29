"""Independent replay of the fixed CH1 scratch and captured SUB9 trial.

This module imports no transport or hardware API. Complete scan decoding and
exact image/load/provenance checks are the caller's responsibility. Reference
BO bytes are test expectations, never a hardware execution fallback.
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.tinystories.audit_scans import commands


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fixture(path):
    """Independently parse the original address + big-endian display format."""
    result = []
    for line in Path(path).read_text().splitlines():
        require(re.fullmatch(r'[0-9a-f]{8} [0-9a-f]{128}', line) is not None,
                'Malformed original raw fixture')
        address, data = line.split(' ')
        address = int(address, 16)
        require(address % 64 == 0 and address + 64 <= 1 << 31 and
                (not result or result[-1][0] < address), 'Invalid fixture address')
        result.append((address, int(data, 16)))
    require(len(result) == 1600, 'Incomplete fixed SUB9 fixture')
    return result


def replay(wire, upload, expected):
    """Consume the complete independently decoded wire iterator through EOF."""
    before, after = fixture(upload), fixture(expected)
    require([a for a, _ in before] == [a for a, _ in after] and before != after,
            'Wrong complete original BO pair')
    addresses = (0x40, 0x1000, 0x1800, 0x200040, 0x1000040, 0x7fffffc0)
    scratch = []
    for trial in range(2):
        values = {address: int.from_bytes(bytes((i*37 + index*19 + trial*83) % 256
                  for i in range(64)), 'little') for index, address in enumerate(addresses)}
        order = addresses if trial == 0 else addresses[::-1]
        scratch.extend((4, address, values[address]) for address in order)
        scratch.extend((3, address, values[address]) for address in addresses)
    scratch_index = uploaded = readbacks = acknowledgments = submits = 0
    staged = []
    identities = set()
    last_status = None
    result = {}
    complete = active = False
    raw_readbacks = []
    for command in wire:
        op, address, data, response = (command[k] for k in ('op', 'address', 'data', 'response'))
        require(op in (1, 2, 3, 4), 'Unmodeled actual opcode')
        if op in (2, 4):
            require(response == 0, 'Actual write response failed')
        if op == 1:
            require(address in (0, 4, 8, 28, 32, 36), 'Unmodeled actual CSR read')
            if address == 0:
                require(response == 0x524b4144, 'Wrong actual RKAD identity')
                identities.add('id')
            elif address == 4:
                require('id' in identities and response == 0x10000, 'Wrong actual ABI')
                identities.add('abi')
            elif address == 8:
                require(response & ~0x77f == 0 and response & (8 | 32) == 0,
                        'Actual endpoint fault or unknown status')
                last_status = response
                if active and response & 4:
                    require(response & (2 | 64) == 0, 'Successful result still busy')
                    complete = True
            else:
                require(active and complete, 'Result CSR read before successful completion')
                result[address] = response
                require(response == {28: 0x44445201, 32: 2, 36: 0}[address],
                        'Actual completion tag/task/error differs')
        elif op in (3, 4):
            require(identities == {'id', 'abi'} and last_status is not None,
                    'Memory accessed before identity/status admission')
            if scratch_index < len(scratch):
                wanted_op, wanted_address, wanted_value = scratch[scratch_index]
                require(not active and last_status & 16 and not staged and uploaded == 0,
                        'Scratch occurred outside idle initialized memory')
                actual = data if op == 4 else response
                require((op, address, actual) == (wanted_op, wanted_address, wanted_value),
                        'Actual scratch order/address/bytes differ')
                scratch_index += 1
            elif not active:
                require(acknowledgments == 0 and op == 4 and uploaded < len(before) and
                        not staged and last_status & 16 and (address, data) == before[uploaded],
                        'Actual raw upload changed or outside idle ownership')
                uploaded += 1
            else:
                require(complete and result == {28: 0x44445201, 32: 2, 36: 0} and
                        op == 3 and readbacks < len(after) and
                        (address, response) == after[readbacks],
                        'Actual complete output differs or was read before completion')
                raw_readbacks.append((address, response))
                readbacks += 1
        else:
            require(identities == {'id', 'abi'} and scratch_index == len(scratch) and
                    uploaded == len(before), 'CSR write before original upload completed')
            if address in (16, 20, 24):
                require(not active and acknowledgments == 0 and len(staged) < 3 and
                        (address, data) == [(16, 0x100e0000), (20, 35), (24, 0x44445201)][len(staged)],
                        'Actual original descriptor/order differs')
                staged.append((address, data))
            elif address == 12 and data == 1:
                require(not active and submits == 0 and len(staged) == 3 and
                        last_status is not None and last_status & 17 == 17 and
                        last_status & (2 | 4 | 8 | 32 | 64) == 0,
                        'Actual SUBMIT violates idle descriptor admission')
                active = True
                submits += 1
            elif address == 12 and data == 2:
                require(active and complete and readbacks == len(after) and
                        result == {28: 0x44445201, 32: 2, 36: 0} and acknowledgments == 0,
                        'ACK precedes complete output validation')
                active = False
                acknowledgments += 1
            else:
                raise ValueError('Unmodeled CSR write or reset attempt')
    require(scratch_index == len(scratch) and uploaded == readbacks == 1600 and
            submits == acknowledgments == 1 and not active and
            last_status is not None and last_status & 16 and last_status & 0x76f == 0,
            'Incomplete actual trial, ACK or final healthy state')
    return dict(status='PASS_FIXED_CH1_SCRATCH_SUB9_WIRE_REPLAY_ONLY',
                scratch_bytes=768, complete_bo_bytes=102400, tasks=2, raw_jobs=1,
                submits=submits, acknowledgments=acknowledgments,
                complete_readback_before_ack=True, full_capacity_qualified=False,
                ecc_injection_qualified=False, full512_integrated=False,
                pcie_tested=False, raw_readbacks=raw_readbacks)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit(run):
    """Qualify this exact fixed trial, not arbitrary DDR/hardware execution."""
    run = Path(run).resolve()
    physical = run/'physical-test'
    review_path = run/'image-review.json'
    producer_path = physical/'report.json'
    review = json.loads(review_path.read_text())
    producer = json.loads(producer_path.read_text())
    require(review['status'] == 'REVIEWED_EXPERIMENTAL_CH1_EW_DDR_IMAGE_FOR_VOLATILE_TRIAL' and
            producer['status'] == 'PASS_PHYSICAL_CH1_SCRATCH_AND_RAW_EW_REQUIRES_INDEPENDENT_WIRE_AUDIT',
            'Full physical producer or source admission incomplete')
    target = 'localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'
    bit_hash = '45bd540cfaf7327ad8db5ba4e3a7548a209db1aeba4423f37159a72287296339'
    require(review['part'] == 'xc7k480tffg1156-2' and review['selected_physical_channel'] ==
            producer['selected_physical_channel'] == 1 and review['usr_access'] == 'a2dfec21' and
            review['target'] == producer['target'] == target and
            review['bitstream']['sha256'] == producer['bitstream_sha256'] == bit_hash and
            producer['image_review_sha256'] == sha(review_path), 'Changed target/image/source binding')
    require(review['flash_authorized'] is False and review['programming_scope'] == 'volatile-sram' and
            producer['flash_written'] is False and producer['hardware_programmed'] is True and
            producer['lease_acquired'] is True and producer['bridge_quit_ack'] is True and
            producer['owned_program_exit'] == producer['owned_bridge_exit'] == 0 and
            producer['owned_hw_server_exit'] in (0, -15), 'Wrong authorization or failed cleanup')
    for name, digest in review['bound_files'].items():
        require(sha(name) == digest, 'Changed admitted input: ' + name)
    require(sha(review['bitstream']['path']) == bit_hash, 'Changed exact physical image')
    for name, digest in producer['artifacts'].items():
        path = (physical/name).resolve()
        require(path.is_relative_to(physical) and sha(path) == digest, 'Changed physical artifact: ' + name)
    load = physical/'load-1'
    receipt_path = load/'program.tsv'
    require(producer['load_receipt_sha256'] == sha(receipt_path), 'Changed load receipt')
    pairs = [line.split('\t', 1) for line in receipt_path.read_text().splitlines()]
    require(all(len(pair) == 2 for pair in pairs), 'Malformed native load receipt')
    receipt = dict(pairs)
    require(len(receipt) == len(pairs), 'Duplicate native load receipt keys')
    wanted = dict(BITSTREAM_SHA256=bit_hash, TARGET=target, DNA_PORT='004E544714C705C',
                  TCK_HZ='3000000', IDCODE_BEFORE='23751093', IDCODE_AFTER='23751093',
                  PROGRAM_FILE=review['bitstream']['path'], PROGRAM_RETURNED='1',
                  INIT_COMPLETE='1', DONE='1', USR_ACCESS='a2dfec21', PROGRAMMED='1', CLEANUP='1', PASS='1')
    require(receipt == wanted, 'Wrong exact native load/target receipt')
    command = json.loads((load/'command.json').read_text())
    require(command['returncode'] == 0 and command['flash_written'] is False and
            command['script_sha256'] == sha(load/'program.tcl'), 'Failed native load command')
    template = (run/'program-template.tcl.in').read_text()
    for name, value in dict(TARGET=target, BITSTREAM=review['bitstream']['path'],
                            RECEIPT=str(receipt_path), USR_ACCESS='a2dfec21', BITSTREAM_SHA=bit_hash).items():
        marker = '@'+name+'@'
        require(template.count(marker) == 1, 'Changed program template marker')
        template = template.replace(marker, '{'+value+'}')
    require((load/'program.tcl').read_text() == template, 'Actual program script differs from admitted guarded template')
    require('Vivado Lab Edition v2026.1.1' in (load/'stdout.log').read_text(), 'Missing actual programming tool version')
    jobs = physical/'raw-jobs'
    bridge = (ROOT/'fpga/host/native_rpc.tcl.in').read_text()
    def bridge_literal(value):
        return '[encoding convertfrom utf-8 [binary format H* {'+str(value).encode('utf-8').hex()+'}]]'
    for name, value in dict(TARGET=bridge_literal(target), SERVER=bridge_literal('localhost:3125'),
                            USR_ACCESS=bridge_literal('a2dfec21'),
                            READY=bridge_literal(jobs/'ready.txt'), PORT='3741').items():
        marker = '@'+name+'@'
        require(bridge.count(marker) == 1, 'Changed bridge template marker')
        bridge = bridge.replace(marker, value)
    require((jobs/'bridge.tcl').read_text() == bridge and
            producer['bridge_script_sha256'] == sha(jobs/'bridge.tcl') and
            (jobs/'ready.txt').read_text().strip() == 'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY',
            'Actual bridge differs from admitted no-programming scan bridge')
    fixture_info = review['raw_fixture']
    require((fixture_info['name'], fixture_info['command_address'], fixture_info['initial_amount'],
             fixture_info['expected_tasks'], fixture_info['complete_bo_bytes']) ==
            ('capture_sub_9', 0x100e0000, 35, 2, 102400), 'Changed fixed physical workload')
    stats = {}
    result = replay(commands(jobs/'native-scans.jsonl', stats), fixture_info['upload'], fixture_info['expected'])
    require(fixture(jobs/'actual-bo.txt') == result.pop('raw_readbacks'), 'Actual saved full BO differs from wire')
    require(stats['scans'] == producer['scans'], 'Producer scan count differs from complete decoder')
    result.update(status='PASS_INDEPENDENT_PHYSICAL_CH1_SCRATCH_AND_RAW_SUB9_AUDIT',
        source_sha256=review['source_sha256'], usr_access=review['usr_access'], bitstream_sha256=bit_hash,
        target=target, dna_port='004E544714C705C', selected_physical_channel=1,
        setup_ns=review['setup_ns'], hold_ns=review['hold_ns'], pulse_ns=review['pulse_ns'],
        raw_scan_stats=stats, admitted_input_count=len(review['bound_files']),
        image_review_sha256=sha(review_path), physical_producer_sha256=sha(producer_path),
        wire_trace_sha256=sha(jobs/'native-scans.jsonl'), auditor_sha256=sha(__file__),
        decoder_sha256=sha(ROOT/'tools/tinystories/audit_scans.py'),
        electrical_signoff=False, software_crc_validation='NOT_PERFORMED', flash_written=False,
        rk_silicon_equivalence=False, audited_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists() and args.out.parent.is_dir(), 'Fresh audit output path required')
    try:
        report = audit(args.run)
    except BaseException as error:
        args.out.write_text(json.dumps(dict(status='FAIL_INDEPENDENT_CH1_PHYSICAL_AUDIT', error=repr(error)), indent=2)+'\n')
        raise
    args.out.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
