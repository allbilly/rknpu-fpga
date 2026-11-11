#!/usr/bin/env python3
"""Pinned physical replay wrapper for the emitted EW image (`ypcb_jtag_ew_top`).

This is the reviewed entry point approved by the Lead for the EW image
`b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a`
(`USR_ACCESS=ec9ecd41`). It is the archived audited raw-command pattern from
`verification/runs/2026-10-27-host-user2-fpga/hardware/{run_sram_tests.py,run_jobs.py}`
pinned into the repo:

  USER2 640-bit mailbox -> RKEW BRAM ABI (1 MiB at 0x10000000)
  `tools/host/transport.py` (JtagTransport) + `tools/host/native_link.py`
  raw captured BOs from `tools/dma_fixtures.py` production EW captures.

What this tool does, exactly:

* opens the shared board lease, starts an **owned** hw_server and the audited
  native scan bridge (`fpga/host/native_rpc.tcl.in`), verifies the loaded EW
  image (exact target URI, DNA, INIT/DONE, `USR_ACCESS=ec9ecd41`), verifies the
  RKEW endpoint identity (`0x524b4557` / ABI `0x00010000`), uploads every
  captured BO byte-verbatim, submits the captured raw descriptor, reads every
  owned BO back **completely**, compares it against the frozen capture
  expectation, and only then ACKs. It finishes with the archived synthetic
  unknown-register E1 negative control and the poisoned-owner checks.
* never programs, resets or flashes the fabric/configuration flash. The EW
  image must already be loaded by the separately authorized volatile-load step
  (`docs/BOARD_RUN_PREP.md` §6A with expected `USR_ACCESS=ec9ecd41`; the
  operator runbook is `docs/BOARD_SESSION_RUNBOOK.md` §5).
* fails closed when any of these is missing or wrong: `--authorized`, the exact
  EW image SHA-256, the exact `--source-tag ec9ecd41`, the exact audited target,
  the shared lease, the human board-review admission
  (`tools/host/prepare.py verify` -> READY), or the cable/tooling preconditions.
* has an offline `--check` that validates the image package/admission, target,
  lease path, the nine captured BO replays and the E1 negative plan without
  touching USB, the lease, a socket, Vivado or hw_server.

The human board-review admission and the per-family user authorization remain
**separate gates**: admission is a review fact, authorization is the user's
explicit instruction; this tool refuses hardware unless both are satisfied.

Exit codes: `0` PASS / PASS_CHECK; `1` FAIL / CHECK_FAILED; `2` REFUSED.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import dma_fixtures  # noqa: E402
from tools.host import native_link, run_jtag_dual_hardware as dual, transport  # noqa: E402

TOOL = 'tools/host/run_jtag_ew_hardware.py'
EW_IMAGE_SHA = 'b373ee7000cf23b727a06743b0025760610b6eba6a441af14725a1bfcf75f59a'
EW_USR_ACCESS = 'ec9ecd41'
EW_TOP = 'ypcb_jtag_ew_top'
EW_BITSTREAM = ROOT / 'build/host-jtag-preparation/20261109T210015Z-emission/bitstream/host-user2-ew.bit'
EW_PACKAGE = ROOT / 'build/host-jtag-preparation/20261109T210015Z'
DEFAULT_TARGET = dual.DEFAULT_TARGET
DEFAULT_LEASE = dual.DEFAULT_LEASE
BRIDGE_PORT = 3741
BRIDGE_TIMEOUT = 180.0
JOB_TIMEOUT = 120.0
POLL_TIMEOUT = 60.0
BRIDGE_READY = 'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY'
CASE_TAG_BASE = 0x35880001
NEGATIVE_TAG = 0x3588BAD1
NEGATIVE_CASE = 'capture_sub_9'
TRACKED_INPUTS = (
    TOOL,
    'tools/host/transport.py',
    'tools/host/native_link.py',
    'tools/host/run_jtag_dual_hardware.py',
    'tools/dma_fixtures.py',
    'tests/backend_ew_captures.json',
    'tests/host/test_run_jtag_ew_hardware.py',
    'verification/runs/2026-10-27-host-user2-fpga/hardware/run_jobs.py',
)

Refusal = dual.Refusal


class ModeFailure(RuntimeError):
    """A replay ran but its evidence did not match the frozen expectation."""


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def need(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def _blob(data):
    return {'bytes': len(data), 'sha256': sha_bytes(data)}


# ---------------------------------------------------------------------------
# Admission (human board-review gate) and image/plan validation
# ---------------------------------------------------------------------------

def admission_record(package=EW_PACKAGE):
    """Read-only `tools/host/prepare.py verify` view of the EW package.

    This is the human board-review gate: it stays `SOURCE_INTACT_REVIEW_PENDING`
    until a reviewer fills `board-review.json`. It is a separate gate from the
    user's per-family authorization.
    """
    package = Path(package)
    record = {'package': str(package), 'status': None, 'blockers': [],
              'ready': False, 'profile': None, 'vivado_executed': None,
              'package_exists': package.is_dir()}
    if not record['package_exists']:
        record['blockers'] = [f'missing EW package: {package}']
        record['status'] = 'UNAVAILABLE'
        return record
    try:
        from tools.host import prepare as image_prepare  # lazy: file work only
        result = image_prepare.verify(package)
    except Exception as error:  # noqa: BLE001 - report the exact reason, fail closed
        record['status'] = 'UNAVAILABLE'
        record['blockers'] = [f'{type(error).__name__}: {error}']
        return record
    record['status'] = result.get('status')
    record['blockers'] = list(result.get('blockers') or [])
    record['profile'] = result.get('profile')
    record['vivado_executed'] = result.get('vivado_executed')
    record['ready'] = (record['status'] == 'READY_FOR_SEPARATELY_AUTHORIZED_BUILD'
                       and not record['blockers'])
    return record


def validate_image(args):
    """Exact image/tag binding + on-disk emitted bitstream check."""
    if args.image != EW_IMAGE_SHA:
        raise Refusal(f'--image must be the exact EW image SHA-256 {EW_IMAGE_SHA}; '
                      f'got {args.image}')
    if args.source_tag != EW_USR_ACCESS:
        raise Refusal(f'--source-tag must be {EW_USR_ACCESS} for the EW image; '
                      f'got {args.source_tag}')
    bitstream = Path(args.ew_bitstream)
    if not bitstream.is_file():
        raise Refusal(f'EW bitstream not found: {bitstream}')
    actual = sha_file(bitstream)
    if actual != EW_IMAGE_SHA:
        raise Refusal(f'EW bitstream SHA-256 mismatch: {bitstream} is {actual}, '
                      f'expected {EW_IMAGE_SHA}')
    return {'path': str(bitstream), 'sha256': actual, 'bytes': bitstream.stat().st_size,
            'top': EW_TOP, 'usr_access': EW_USR_ACCESS}


def build_plan(cases=None):
    """Build the complete-BO replay plan from the frozen production captures.

    Every byte of every owned region is compared: the command BO (64 KiB), the
    task BO (16 KiB), the input/weight/output BOs (4-8 KiB each). There is no
    prefix comparison and no tolerance - the captures are exact device output.
    """
    cases = list(cases if cases is not None else dma_fixtures.production_cases())
    if not cases:
        raise ValueError('EW production fixture set is empty')
    plan_cases = []
    total_bytes = 0
    for index, case in enumerate(cases):
        expected, oracle = dma_fixtures.replay(case)
        regions = []
        for address, data in sorted(case['regions'].items()):
            golden = bytes(expected.regions[address])
            need(len(golden) == len(data), f"{case['name']}: expectation size changed")
            regions.append({'address': address, 'bytes': len(golden),
                            'input': bytes(data), 'expected': golden,
                            'input_sha256': sha_bytes(data),
                            'expected_sha256': sha_bytes(golden)})
            total_bytes += len(golden)
        plan_cases.append({
            'name': case['name'], 'address': case['address'],
            'amount': case['amount'], 'tasks': case['tasks'],
            'tag': CASE_TAG_BASE + index, 'regions': regions,
            'bytes': sum(region['bytes'] for region in regions),
            'oracle': {'command_reads': oracle.command_reads,
                       'memory_transactions': oracle.memory_transactions},
        })
    return {'cases': plan_cases, 'bytes': total_bytes, 'case_count': len(plan_cases)}


def build_negative_plan(cases=None, case_name=NEGATIVE_CASE):
    """Archived synthetic unknown-register control: patch the first raw QWORD.

    The rest of the captured command BO is byte-identical; the expected fault is
    E1 with zero completed tasks, and the owner must be poisoned afterwards.
    """
    cases = list(cases if cases is not None else dma_fixtures.production_cases())
    case = next((item for item in cases if item['name'] == case_name), None)
    if case is None:
        raise ValueError(f'negative-control case {case_name!r} is not in the EW fixture set')
    base = case['address']
    raw = bytearray(case['regions'][base])
    original = bytes(raw[:8])
    old = struct.unpack_from('<Q', raw, 0)[0]
    bad = (0x1001 << 48) | (old & 0x0000FFFF_FFFF0000) | 0x4074
    struct.pack_into('<Q', raw, 0, bad)
    patched = bytes(raw)
    regions = {address: (patched if address == base else bytes(data))
               for address, data in case['regions'].items()}
    return {'name': 'synthetic_unknown_register', 'case': case_name,
            'address': base, 'amount': case['amount'], 'tag': NEGATIVE_TAG,
            'expected_error_code': 1, 'expected_completed_tasks': 0,
            'changed_bytes': {'address': base, 'original_sha256': sha_bytes(original),
                              'replacement_sha256': sha_bytes(patched[:8]),
                              'original_hex': original.hex(),
                              'replacement_hex': patched[:8].hex()},
            'regions': regions}


def plan_summary(plan):
    """JSON-safe plan (no raw BO bytes)."""
    return {
        'case_count': plan['case_count'],
        'bytes': plan['bytes'],
        'cases': [{
            'name': case['name'], 'address': f"{case['address']:#010x}",
            'amount': case['amount'], 'tasks': case['tasks'], 'tag': f"{case['tag']:#010x}",
            'bytes': case['bytes'], 'oracle': case['oracle'],
            'regions': [{key: region[key] for key in
                         ('address', 'bytes', 'input_sha256', 'expected_sha256')}
                        for region in case['regions']],
        } for case in plan['cases']],
    }


# ---------------------------------------------------------------------------
# Replay engine (pure transport operations; unit-tested with a fake transport)
# ---------------------------------------------------------------------------

def replay_positive(transport_owner, plan, outdir, timeout=JOB_TIMEOUT):
    """Upload captured BOs, submit, read every owned byte back, compare, ACK.

    The ACK is written only after the complete readback matches. A mismatch
    leaves the result un-ACKed and the per-case receipt in place.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    results = []
    checked_total = 0
    for case in plan['cases']:
        record = {'name': case['name'], 'status': 'RUNNING',
                  'started_utc': utc_now(),
                  'descriptor': {'address': f"{case['address']:#010x}",
                                 'amount': case['amount'], 'tag': f"{case['tag']:#010x}",
                                 'tasks': case['tasks']},
                  'bytes_expected': case['bytes'], 'regions': []}
        path = outdir / f"{case['name']}.json"
        write_json(path, record)
        try:
            for region in case['regions']:
                transport_owner.mem_write(region['address'], region['input'])
                record['regions'].append({'address': f"{region['address']:#010x}",
                                          'bytes': region['bytes'],
                                          'input_sha256': region['input_sha256'],
                                          'expected_sha256': region['expected_sha256']})
            write_json(path, record)
            transport_owner.submit(case['address'], case['amount'], case['tag'])
            result = transport_owner.poll_result(timeout)
            record['completion'] = {'tag': f"{result.tag:#010x}",
                                    'completed_tasks': result.completed_tasks,
                                    'error_code': result.error_code,
                                    'status': result.status}
            write_json(path, record)
            need(result.tag == case['tag'], f"{case['name']}: completion tag mismatch")
            need(result.completed_tasks == case['tasks'],
                 f"{case['name']}: completed_tasks {result.completed_tasks} != {case['tasks']}")
            need(result.error_code == 0, f"{case['name']}: engine error {result.error_code}")
            checked = 0
            for entry, region in zip(record['regions'], case['regions']):
                observed = transport_owner.mem_read(region['address'], region['bytes'])
                entry['observed_sha256'] = sha_bytes(observed)
                entry['matches'] = observed == region['expected']
                write_json(path, record)
                if not entry['matches']:
                    raise ModeFailure(
                        f"{case['name']}: complete BO mismatch at {region['address']:#x} "
                        f"({region['bytes']} bytes); result left un-ACKed")
                checked += len(observed)
            transport_owner.ack_success()
            record.update(status='PASS', bytes_checked=checked, finished_utc=utc_now(),
                          ack_after_complete_readback=True)
            checked_total += checked
        except BaseException as error:
            record.update(status='FAIL', failure=str(error), finished_utc=utc_now())
            write_json(path, record)
            raise
        finally:
            write_json(path, record)
        results.append({'name': case['name'], 'status': record['status'],
                        'bytes_checked': record.get('bytes_checked', 0),
                        'receipt': path.name,
                        'receipt_sha256': sha_file(path)})
        print(f"PASS EW_CASE {case['name']} bytes={record['bytes_checked']}", flush=True)
    return {'status': 'PASS', 'cases': results, 'bytes_checked': checked_total}


def replay_negative(transport_owner, negative, outdir, timeout=JOB_TIMEOUT):
    """Archived synthetic unknown-register E1 negative + poisoned-owner checks."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / 'synthetic_unknown_register.json'
    record = {'status': 'RUNNING', 'name': negative['name'],
              'started_utc': utc_now(), 'case': negative['case'],
              'expected_error_code': negative['expected_error_code'],
              'expected_completed_tasks': negative['expected_completed_tasks'],
              'tag': f"{negative['tag']:#010x}",
              'changed_bytes': negative['changed_bytes'],
              'ack_sent': False,
              'regions': [{'address': f'{address:#010x}', 'bytes': len(data),
                           'sha256': sha_bytes(data)}
                          for address, data in sorted(negative['regions'].items())]}
    write_json(path, record)
    try:
        for address, data in sorted(negative['regions'].items()):
            transport_owner.mem_write(address, data)
        transport_owner.submit(negative['address'], negative['amount'], negative['tag'])
        try:
            transport_owner.poll_result(timeout)
        except transport.JobError as error:
            result = error.result
            record['completion'] = {'tag': f'{result.tag:#010x}',
                                    'completed_tasks': result.completed_tasks,
                                    'error_code': result.error_code,
                                    'status': result.status}
            need(result.tag == negative['tag'],
                 'unknown register: completion tag mismatch')
            need(result.error_code == negative['expected_error_code'],
                 f"unknown register: error {result.error_code} != E1")
            need(result.completed_tasks == negative['expected_completed_tasks'],
                 'unknown register: tasks executed before E1')
        else:
            raise ModeFailure('unknown register was silently accepted (no E1)')
        link = getattr(transport_owner, 'link', None)
        scans_before = getattr(link, 'scans', None)
        for action in (lambda: transport_owner.mem_read(negative['address'], 64),
                       transport_owner.ack_success):
            try:
                action()
            except transport.ProtocolError:
                pass
            else:
                raise ModeFailure('poisoned owner remained usable after E1')
        if scans_before is not None:
            need(getattr(link, 'scans', None) == scans_before,
                 'poisoned owner issued another scan after E1')
        record.update(status='PASS_EXPECTED_E1_AND_POISONED_OWNER',
                      finished_utc=utc_now())
        print('PASS EW_NEGATIVE synthetic_unknown_register E1', flush=True)
    except BaseException as error:
        record.update(status='FAIL', failure=str(error), finished_utc=utc_now())
        write_json(path, record)
        raise
    finally:
        write_json(path, record)
    return {'status': record['status'], 'receipt': path.name,
            'receipt_sha256': sha_file(path), 'completion': record.get('completion')}


# ---------------------------------------------------------------------------
# Hardware session (owned hw_server + audited bridge; never programs)
# ---------------------------------------------------------------------------

class TraceLink(native_link.NativeLink):
    """NativeLink that records scans and mailbox requests for the receipt."""

    def __init__(self, trace, host='127.0.0.1', port=BRIDGE_PORT, timeout=30.0):
        self.trace = trace
        self.scans = 0
        self.requests = []
        super().__init__(host=host, port=port, timeout=timeout)

    def scan(self, value, bits=640, *, ir=False, deadline=None):
        if not ir and bits == 640 and value:
            self.requests.append(((value >> 548) & 0xFF, (value >> 512) & 0xFFFFFFFF))
        item = {'index': self.scans, 'utc': utc_now(), 'bits': bits, 'ir': ir,
                'tdi': f'{value:x}'}
        try:
            result = super().scan(value, bits, ir=ir, deadline=deadline)
            item['tdo'] = f'{result:x}'
            return result
        except BaseException as error:
            item['error'] = str(error)
            raise
        finally:
            self.scans += 1
            self.trace.write(json.dumps(item, separators=(',', ':')) + '\n')
            self.trace.flush()

    def reset(self, *, deadline=None):
        self.trace.write(json.dumps({'event': 'TAP_RESET_NOT_FABRIC_RESET',
                                     'utc': utc_now()}) + '\n')
        self.trace.flush()
        return super().reset(deadline=deadline)


def _fresh_directory(path):
    path = Path(path)
    need(not path.exists(), f'--out must name a fresh directory; it exists: {path}')
    path.mkdir(parents=True)
    return path


def _receipt_base(args, kind):
    return {
        'schema': 1, 'tool': TOOL, 'kind': kind, 'started_utc': utc_now(),
        'finished_utc': None, 'status': 'RUNNING',
        'hardware_accessed': False, 'network_accessed': False,
        'vivado_executed': False, 'hw_server_started': False,
        'fabric_programmed': False, 'fabric_reset': False,
        'configuration_written': False, 'flash_written': False,
        'image_loaded_by_this_tool': False, 'lease_acquired': False,
        'authorized': bool(getattr(args, 'authorized', False)),
        'authorization_note': getattr(args, 'authorization_note', ''),
        'command': getattr(args, 'command', sys.argv),
    }


def run_hardware(args, plan, negative, admission, out):
    """Owned hw_server + audited bridge + raw captured BO replay (no programming)."""
    receipt = _receipt_base(args, 'hardware')
    receipt.update({
        'image': {'path': str(Path(args.ew_bitstream)), 'sha256': EW_IMAGE_SHA,
                  'top': EW_TOP, 'usr_access': EW_USR_ACCESS},
        'package': admission['package'], 'admission': admission,
        'plan': plan_summary(plan),
        'negative_plan': {'name': negative['name'], 'case': negative['case'],
                          'tag': f"{negative['tag']:#010x}",
                          'changed_bytes': negative['changed_bytes']},
        'source_hashes_before': dual.manifest(TRACKED_INPUTS),
        'tools': dual.tool_versions(probe=False),
    })
    receipt_path = out / 'receipt.json'
    write_json(receipt_path, receipt)
    lease_fd = None
    server = bridge = link = owner = None
    try:
        target = dual.parse_target(args.target)
        lease_fd = dual.acquire_lease(args.lease)
        receipt['lease_acquired'] = True
        receipt['target'] = target
        receipt['lease'] = {'path': args.lease, 'acquired': True}
        write_json(receipt_path, receipt)
        receipt['controllers'] = dual.check_controllers()
        receipt['ports'] = dual.check_ports(target['port'], args.bridge_port)
        receipt['cable'] = dual.check_cable()
        receipt['tools'] = dual.tool_versions(probe=True)
        write_json(receipt_path, receipt)

        tools = receipt['tools']
        vivado = tools['paths'].get('vivado') or str(Path('/home/fedora/vivado/2026.1/Vivado/bin/vivado'))
        hw_server = tools['paths'].get('hw_server') or str(Path(vivado).with_name('hw_server'))
        need(Path(vivado).is_file(), f'Vivado executable not found: {vivado}')
        need(Path(hw_server).is_file(), f'hw_server executable not found: {hw_server}')
        bridge_dir = out / 'bridge'
        bridge_dir.mkdir(parents=True, exist_ok=True)
        receipt['status'] = 'RUNNING_BRIDGE'
        write_json(receipt_path, receipt)

        server = dual.start_owned([hw_server, '-s', f"tcp::{target['port']}"],
                                  bridge_dir / 'hw-server.log', bridge_dir)
        if not dual.wait_port(target['port'], time.monotonic() + 30, server):
            raise RuntimeError('owned hw_server did not start listening within 30 s')
        ready_path = bridge_dir / 'ready.txt'
        if ready_path.exists():
            ready_path.unlink()
        script = bridge_dir / 'bridge.tcl'
        script.write_text(native_link.render_bridge(
            target['uri'], target['server'], EW_USR_ACCESS, str(ready_path), args.bridge_port))
        bridge_record = {'tcl_sha256': sha_file(script),
                         'template': 'fpga/host/native_rpc.tcl.in',
                         'template_sha256': sha_file(ROOT / 'fpga/host/native_rpc.tcl.in'),
                         'source_tag': EW_USR_ACCESS,
                         'ready_marker': None}
        argv = [vivado, '-mode', 'batch', '-nojournal', '-nolog', '-notrace',
                '-source', str(script)]
        bridge = dual.start_owned(argv, bridge_dir / 'bridge-stdout.log', bridge_dir)
        deadline = time.monotonic() + args.bridge_timeout
        while not ready_path.exists():
            if bridge.poll() is not None:
                tail = (bridge_dir / 'bridge-stdout.log').read_text()[-4000:]
                raise RuntimeError(f'native bridge exited before READY '
                                   f'(rc={bridge.returncode}): {tail}')
            if time.monotonic() >= deadline:
                raise RuntimeError(f'native bridge READY timeout after {args.bridge_timeout} s')
            time.sleep(0.1)
        marker = ready_path.read_text().strip()
        bridge_record['ready_marker'] = marker
        need(marker == BRIDGE_READY, f'unexpected native bridge READY marker: {marker!r}')
        bridge_record['ready_file_sha256'] = sha_file(ready_path)
        receipt['hardware_accessed'] = True
        receipt['network_accessed'] = True
        receipt['vivado_executed'] = True
        receipt['hw_server_started'] = True
        receipt['bridge'] = bridge_record
        write_json(receipt_path, receipt)

        trace_path = out / 'scans.jsonl'
        with trace_path.open('w') as trace:
            link = TraceLink(trace, host='127.0.0.1', port=args.bridge_port, timeout=30.0)
            bridge_record['native_link'] = {
                'host': link.host, 'port': link.port,
                'actual_tck_frequency_hz': link.actual_frequency_hz,
                'actual_period_ns': {'numerator': link.actual_period_ns.numerator,
                                     'denominator': link.actual_period_ns.denominator}}
            owner = transport.JtagTransport(host=link.host, port=link.port,
                                            frequency_hz=6_000_000, link=link)
            receipt['identity'] = {
                'rke_id': f'{owner.reg_read(0):08x}',
                'rke_abi': f'{owner.reg_read(4):08x}',
                'rke_status': f'{owner.reg_read(8):08x}',
                'expected_rke_id': f'{transport.RKEW_ID:08x}',
                'expected_rke_abi': f'{transport.ABI_VERSION:08x}',
                'actual_tck_frequency_hz': link.actual_frequency_hz,
                'actual_tck_period_ns': {'numerator': link.actual_period_ns.numerator,
                                         'denominator': link.actual_period_ns.denominator},
            }
            write_json(receipt_path, receipt)
            receipt['status'] = 'RUNNING_REPLAY'
            write_json(receipt_path, receipt)
            receipt['positive'] = replay_positive(owner, plan, out / 'cases',
                                                  timeout=args.job_timeout)
            write_json(receipt_path, receipt)
            if not args.skip_negative:
                receipt['negative'] = replay_negative(owner, negative, out / 'negative',
                                                      timeout=args.job_timeout)
                write_json(receipt_path, receipt)
        receipt['status'] = 'PASS'
        receipt['bytes_checked'] = receipt['positive']['bytes_checked']
        receipt['finished_utc'] = utc_now()
        receipt['source_hashes_after'] = dual.manifest(TRACKED_INPUTS)
        need(receipt['source_hashes_after'] == receipt['source_hashes_before'],
             'tracked inputs changed during the run')
        write_json(receipt_path, receipt)
        print(f"PASS EW_HARDWARE cases={plan['case_count']} bytes={receipt['bytes_checked']} "
              f"e1={'skipped' if args.skip_negative else 'PASS'} receipt={receipt_path}")
        return 0
    except Refusal as error:
        receipt['status'] = 'REFUSED'
        receipt['failure'] = str(error)
        receipt['finished_utc'] = utc_now()
        write_json(receipt_path, receipt)
        print(f'REFUSED: {error}', file=sys.stderr)
        return 2
    except BaseException as error:
        receipt['status'] = 'FAIL'
        receipt['failure'] = str(error)
        receipt['finished_utc'] = utc_now()
        write_json(receipt_path, receipt)
        print(f'FAIL EW_HARDWARE: {error}', file=sys.stderr)
        return 1
    finally:
        cleanup = {}
        try:
            if link is not None:
                try:
                    link.shutdown_bridge()
                    cleanup['bridge_quit_ack'] = True
                except BaseException as error:
                    cleanup['bridge_quit_error'] = str(error)
            if owner is not None:
                try:
                    owner.close()
                except BaseException as error:
                    cleanup['owner_close_error'] = str(error)
            elif link is not None:
                try:
                    link.close()
                except BaseException:
                    pass
            if bridge is not None:
                try:
                    cleanup['bridge_returncode'] = bridge.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    rc, forced = dual.stop_owned(bridge)
                    cleanup['bridge_returncode'] = rc
                    cleanup['bridge_forced_termination'] = forced
                log_path = out / 'bridge' / 'bridge-stdout.log'
                if log_path.is_file():
                    text = log_path.read_text()
                    cleanup['bridge_log_sha256'] = sha_file(log_path)
                    cleanup['bridge_clean_exit_marker'] = (
                        'PASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT' in text)
                    cleanup['bridge_log_tail'] = text[-1500:]
            if server is not None:
                rc, forced = dual.stop_owned(server)
                cleanup['owned_hw_server_exit'] = rc
                cleanup['owned_hw_server_forced_termination'] = forced
                hw_log = out / 'bridge' / 'hw-server.log'
                if hw_log.is_file():
                    cleanup['hw_server_log_sha256'] = sha_file(hw_log)
        finally:
            if lease_fd is not None:
                try:
                    dual.release_lease(lease_fd, args.lease)
                    cleanup['lease_released'] = True
                except BaseException as error:
                    cleanup['lease_release_error'] = str(error)
            receipt['cleanup'] = cleanup
            receipt['bridge_clean_quit'] = bool(cleanup.get('bridge_quit_ack')) and \
                bool(cleanup.get('bridge_clean_exit_marker', False))
            receipt['owned_hw_server_stopped'] = cleanup.get('owned_hw_server_exit') in (0, -15, -9, None)
            receipt['fabric_programmed'] = False
            receipt['fabric_reset'] = False
            receipt['configuration_written'] = False
            receipt['flash_written'] = False
            receipt['finished_utc'] = receipt.get('finished_utc') or utc_now()
            write_json(receipt_path, receipt)


# ---------------------------------------------------------------------------
# Offline check
# ---------------------------------------------------------------------------

def check_main(args):
    out = _fresh_directory(args.out or dual._default_out('ew-check'))
    receipt = _receipt_base(args, 'check')
    receipt.update({'check_only': True, 'stage_dir': str(out / 'staged')})
    receipt_path = out / 'receipt.json'
    write_json(receipt_path, receipt)
    try:
        image = validate_image(args)
        target = dual.parse_target(args.target)
        lease = dual.validate_lease(args.lease)
        plan = build_plan()
        negative = build_negative_plan()
        admission = admission_record(args.ew_package)
        receipt.update({
            'image': image, 'target': target, 'lease': lease,
            'admission': admission, 'plan': plan_summary(plan),
            'negative_plan': {'name': negative['name'], 'case': negative['case'],
                              'tag': f"{negative['tag']:#010x}",
                              'changed_bytes': negative['changed_bytes']},
            'tools': dual.tool_versions(probe=False),
            'source_hashes_before': dual.manifest(TRACKED_INPUTS),
            'offline_guarantees': {
                'lease_opened': False, 'usb_enumerated': False,
                'socket_opened': False, 'subprocess_launched': False,
                'vivado_or_hw_server_started': False,
            },
        })
        receipt['source_hashes_after'] = receipt['source_hashes_before']
        receipt['status'] = ('PASS_CHECK' if admission['ready']
                             else 'PASS_CHECK_PENDING_ADMISSION')
        for case in plan['cases']:
            print(f"EW_CASE {case['name']} bytes={case['bytes']} "
                  f"descriptor={case['address']:#x}/{case['amount']} tasks={case['tasks']}")
        print(f"EW_NEGATIVE {negative['name']} case={negative['case']} expected=E1")
        if admission['ready']:
            print(f"ADMISSION READY {admission['package']} ({admission['status']})")
        else:
            print(f"ADMISSION NOT READY {admission['package']} "
                  f"({admission['status']}): {'; '.join(admission['blockers'])}")
            print('NOTE hardware runs will refuse until the human board-review admission clears')
        print(f"{receipt['status']} image={EW_IMAGE_SHA[:12]}… cases={plan['case_count']} "
              f"bytes={plan['bytes']} hardware_accessed=false receipt={receipt_path}")
        return 0
    except (Refusal, ValueError) as error:
        receipt['status'] = 'CHECK_FAILED'
        receipt['failure'] = str(error)
        print(f'CHECK_FAILED: {error}', file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 - fail closed with the exact reason
        receipt['status'] = 'CHECK_FAILED'
        receipt['failure'] = f'{type(error).__name__}: {error}'
        print(f'CHECK_FAILED: {type(error).__name__}: {error}', file=sys.stderr)
        return 1
    finally:
        receipt['finished_utc'] = utc_now()
        write_json(receipt_path, receipt)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--image', required=True,
                        help=f'exact EW image SHA-256 (must be {EW_IMAGE_SHA})')
    parser.add_argument('--source-tag', required=True,
                        help=f'exact EW USR_ACCESS tag (must be {EW_USR_ACCESS})')
    parser.add_argument('--target', required=True, default=None,
                        help='exact audited cable URI, e.g. ' + DEFAULT_TARGET)
    parser.add_argument('--lease', required=True, default=None,
                        help='shared YPCB JTAG lease path')
    parser.add_argument('--authorized', action='store_true',
                        help='explicit per-family authorization for the hardware '
                             'replay; hardware runs refuse without it')
    parser.add_argument('--authorization-note', default='',
                        help='who authorized this EW replay (recorded verbatim)')
    parser.add_argument('--ew-bitstream', type=Path, default=EW_BITSTREAM,
                        help='emitted EW bitstream whose SHA-256 must equal --image')
    parser.add_argument('--ew-package', type=Path, default=EW_PACKAGE,
                        help='prepared EW package used for the human board-review admission')
    parser.add_argument('--check', action='store_true',
                        help='offline validation of image/admission/fixtures/plan; '
                             'no lease, USB, socket, Vivado or hw_server is touched')
    parser.add_argument('--skip-negative', action='store_true',
                        help='skip the synthetic unknown-register E1 negative (the E1 '
                             'control poisons the owner, so it is normally last)')
    parser.add_argument('--out', type=Path, default=None,
                        help='fresh output directory (default build/board-prep/<UTC>-<kind>)')
    parser.add_argument('--bridge-port', type=int, default=BRIDGE_PORT)
    parser.add_argument('--bridge-timeout', type=float, default=BRIDGE_TIMEOUT)
    parser.add_argument('--job-timeout', type=float, default=JOB_TIMEOUT)
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    args.command = [sys.executable, str(Path(__file__).resolve()), *argv]
    if args.check:
        return check_main(args)
    # Hardware path: fail closed before any hardware work.
    try:
        if not args.authorized:
            raise Refusal('Hardware access refused: pass --authorized only after the '
                          'user explicitly authorized this EW replay (separate from the '
                          'board-review admission). Nothing was opened.')
        validate_image(args)
        dual.parse_target(args.target)
        dual.validate_lease(args.lease)
        plan = build_plan()
        negative = build_negative_plan()
        admission = admission_record(args.ew_package)
        if not admission['ready']:
            raise Refusal('EW image admission is not ready: '
                          f"{admission['status']}: {'; '.join(admission['blockers'])}. "
                          'A human board reviewer must clear board-review.json; nothing was opened.')
    except (Refusal, ValueError) as error:
        out = _fresh_directory(args.out or dual._default_out('ew-refused'))
        receipt = _receipt_base(args, 'hardware')
        receipt.update({'status': 'REFUSED', 'failure': str(error),
                        'image_attempted': args.image, 'source_tag_attempted': args.source_tag,
                        'finished_utc': utc_now()})
        write_json(out / 'receipt.json', receipt)
        print(f'REFUSED: {error}', file=sys.stderr)
        return 2
    out = _fresh_directory(args.out or dual._default_out('ew-hardware'))
    return run_hardware(args, plan, negative, admission, out)


if __name__ == '__main__':
    raise SystemExit(main())
