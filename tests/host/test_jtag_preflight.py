"""Offline controls for tools/host/jtag_preflight.py (strictly read-only).

No board, cable, USB node, lease, socket or hw_server/Vivado manager is touched:
leaf readers are replaced with canned values and any real subprocess/socket
attempt fails the test. These are software controls, not hardware evidence.
"""
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
from tools.host import jtag_preflight as pf
from tools.host import run_jtag_dual_hardware as hw

DLC10_0013 = 'Bus 001 Device 010: ID 03fd:0013 Xilinx, Inc. Platform Cable USB II'
DLC10_0008 = 'Bus 001 Device 011: ID 03fd:0008 Xilinx, Inc. Platform Cable USB II'
UNKNOWN_03FD = 'Bus 001 Device 012: ID 03fd:0007 Xilinx, Inc. Platform Cable USB'
FAIL_NO_NETWORK = 'offline test opened a network connection'
FAIL_NO_PROCESS = 'offline test launched a real subprocess'
ALL_PAGES = ['conv_page', 'pool_page', 'gemm_page', 'conv_fp32_page',
             'conv_k5_page', 'conv_c16_page']


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def lsusb_result(lines):
    return {'lines': list(lines), 'returncode': 0 if lines else 1,
            'stdout': '\n'.join(lines)}


def write_catalog_image(root, stamp='20261110T000000Z', pages=None, *,
                        bit_bytes=b'\x04' * (2 * 1024 * 1024)):
    directory = Path(root) / stamp
    (directory / 'implementation').mkdir(parents=True)
    bit = b'\x04' * (2 * 1024 * 1024) if bit_bytes is None else bit_bytes
    if bit_bytes is not None:
        (directory / 'implementation/rk_jtag_dual.bit').write_bytes(bit)
    (directory / 'inputs.json').write_text(json.dumps({
        'profile': 'ypcb_jtag_dual', 'status': 'PASS', 'bitstream_emitted': True,
        'hardware_accessed': False, 'top': 'ypcb_jtag_dual_top',
        'part': 'xc7k480tffg1156-2', 'bitstream': 'rk_jtag_dual.bit',
        'source_hashes': {},
    }))
    (directory / 'build.tcl').write_text(
        'foreach page {' + ' '.join(pages or ALL_PAGES) + '} {\n}\n')
    return hashlib.sha256(bit).hexdigest()


def write_fake_ypcb(root):
    """A synthetic dlc10-init.sh whose expected hashes match dummy firmware files."""
    root = Path(root)
    (root / 'firmware').mkdir(parents=True)
    (root / 'ref/fxload').mkdir(parents=True)
    (root / 'openFPGALoader/build-xpcu-debug').mkdir(parents=True)
    (root / 'local-overrides/ref-inspur-adventures/files/scripts').mkdir(parents=True)
    payloads = {
        'firmware/xusb_xp2-boot.hex': b'boot-firmware-fixture\n',
        'firmware/xusb_xp2-overlay.hex': b'overlay-firmware-fixture\n',
        'ref/fxload/a3load.hex': b'a3load-fixture\n',
        'openFPGALoader/build-xpcu-debug/openFPGALoader': b'#! /bin/sh\nexit 0\n',
        'local-overrides/ref-inspur-adventures/files/scripts/xpcu_stage2.py': b'# fixture\n',
    }
    hashes = {}
    for name, data in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[name] = sha_bytes(data)
        if 'openFPGALoader' in name:
            path.chmod(0o755)
    (root / 'dlc10-init.sh').write_text(
        '#!/usr/bin/env bash\n'
        'set -euo pipefail\n'
        'root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)\n'
        'boot="$root/firmware/xusb_xp2-boot.hex"\n'
        'overlay="$root/firmware/xusb_xp2-overlay.hex"\n'
        'helper="$root/ref/fxload/a3load.hex"\n'
        f'check_hash "$boot" {hashes["firmware/xusb_xp2-boot.hex"]}\n'
        f'check_hash "$overlay" {hashes["firmware/xusb_xp2-overlay.hex"]}\n'
        f'check_hash "$helper" {hashes["ref/fxload/a3load.hex"]}\n'
    )
    return root


class CableClassificationTests(unittest.TestCase):
    def test_stages(self):
        self.assertEqual(pf.classify_cable(lsusb_result([]), lsusb_result([]))['stage'], 'absent')
        pre = pf.classify_cable(lsusb_result([DLC10_0013]), lsusb_result([]))
        self.assertEqual(pre['stage'], 'pre_firmware')
        ready = pf.classify_cable(lsusb_result([]), lsusb_result([DLC10_0008]))
        self.assertEqual(ready['stage'], 'initialized')
        self.assertEqual(ready['usb_node'], '/dev/bus/usb/001/011')
        both = pf.classify_cable(lsusb_result([DLC10_0013]), lsusb_result([DLC10_0008]))
        self.assertEqual(both['stage'], 'ambiguous')
        unknown = pf.classify_cable(lsusb_result([]), lsusb_result([]), [UNKNOWN_03FD])
        self.assertEqual(unknown['stage'], 'ambiguous')
        self.assertIn('unrecognized', unknown['reason'])


class ParsingTests(unittest.TestCase):
    def test_ss_listening(self):
        text = (
            'LISTEN 0      4096   127.0.0.1:3125       0.0.0.0:*\n'
            'LISTEN 0      4096       [::1]:3721          [::]:*\n'
            'LISTEN 0      4096   192.168.1.5:3741       0.0.0.0:*\n'
            'ESTAB  0      0        127.0.0.1:22       127.0.0.1:5000\n'
        )
        states = pf.parse_ss_listening(text, (3121, 3122, 3125, 3721, 3741))
        self.assertEqual(states, {3121: False, 3122: False, 3125: True,
                                  3721: True, 3741: True})

    def test_lease_state_reads_proc_locks_without_opening(self):
        with tempfile.TemporaryDirectory(prefix='preflight-lease-') as directory:
            lease = Path(directory) / 'ypcb-jtag.lock'
            lease.write_bytes(b'')
            free = pf.lease_lock_holders(lease)
            self.assertFalse(free['held'])
            fd = os.open(lease, os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                held = pf.lease_lock_holders(lease)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            self.assertTrue(held['held'])
            self.assertTrue(held['lock_entries'])

    def test_lease_state_synthetic_proc_locks(self):
        with tempfile.TemporaryDirectory(prefix='preflight-lease-synth-') as directory:
            lease = Path(directory) / 'ypcb-jtag.lock'
            lease.write_bytes(b'')
            info = lease.stat()
            line = (f"7: FLOCK  ADVISORY  WRITE 4242 "
                    f"{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino} 0 EOF")
            state = pf.lease_lock_holders(lease, proc_locks_text=line + '\n')
            self.assertTrue(state['held'])
            other = ('7: FLOCK  ADVISORY  WRITE 4242 00:99:1 0 EOF\n')
            self.assertFalse(pf.lease_lock_holders(lease, proc_locks_text=other)['held'])


class PrerequisiteTests(unittest.TestCase):
    def test_derives_and_verifies_from_script(self):
        with tempfile.TemporaryDirectory(prefix='preflight-ypcb-') as directory:
            root = write_fake_ypcb(directory)
            record = pf.dlc10_prerequisites(root, commands=())
            self.assertTrue(record['ok'], record)
            self.assertTrue(all(item['matches'] for item in record['checks']))
            self.assertEqual(len(record['checks']), 5)
            reference = next(item for item in record['checks'] if item['name'] == 'boot')
            self.assertEqual(reference['actual_sha256'], reference['expected_sha256'])

    def test_changed_firmware_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix='preflight-ypcb-bad-') as directory:
            root = write_fake_ypcb(directory)
            (root / 'firmware/xusb_xp2-overlay.hex').write_bytes(b'tampered\n')
            record = pf.dlc10_prerequisites(root, commands=())
            self.assertFalse(record['ok'])
            overlay = next(item for item in record['checks'] if item['name'] == 'overlay')
            self.assertFalse(overlay['matches'])

    def test_missing_script_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix='preflight-ypcb-missing-') as directory:
            record = pf.dlc10_prerequisites(directory, commands=())
            self.assertFalse(record['ok'])
            self.assertIn('missing cable-init script', record['error'])


class PreferredImageTests(unittest.TestCase):
    def test_six_page_image_is_preferred_and_enables_all_modes(self):
        with tempfile.TemporaryDirectory(prefix='preflight-catalog-') as directory:
            four = Path(directory) / 'four'
            six = Path(directory) / 'six'
            write_catalog_image(four, '20261109T073000Z',
                                ['conv_page', 'pool_page', 'gemm_page', 'conv_fp32_page'])
            six_sha = write_catalog_image(six, '20261110T000000Z', ALL_PAGES)
            emitted_four, _ = hw.scan_image_catalog(four)
            emitted_six, _ = hw.scan_image_catalog(six)
            preferred_four = pf.select_preferred_image(emitted_four)
            preferred_six = pf.select_preferred_image(emitted_six)
            self.assertEqual(pf.modes_for_image(preferred_four), [0, 1, 2, 3, 4])
            self.assertEqual(pf.modes_for_image(preferred_six), [0, 1, 2, 3, 4, 5, 6])
            self.assertEqual(preferred_six['bitstream_sha256'], six_sha)
            # page count outranks a newer timestamp: six pages always wins.
            self.assertGreater(len(preferred_six['pages']), len(preferred_four['pages']))


class CatalogInventoryTests(unittest.TestCase):
    """Read-only multi-family catalog listing (no image is loaded or opened)."""

    def test_lists_receipts_bitstreams_and_gates_across_families(self):
        with tempfile.TemporaryDirectory(prefix='preflight-inventory-') as directory:
            root = Path(directory)
            jtag = root / 'jtag-dual-image' / '20261109T160627Z'
            (jtag / 'implementation').mkdir(parents=True)
            jtag_bit = b'\x05' * (2 * 1024 * 1024)
            (jtag / 'implementation/rk_jtag_dual.bit').write_bytes(jtag_bit)
            (jtag / 'inputs.json').write_text(json.dumps({
                'profile': 'ypcb_jtag_dual', 'status': 'PASS',
                'bitstream_emitted': True, 'hardware_accessed': False,
                'top': 'ypcb_jtag_dual_top', 'part': 'xc7k480tffg1156-2',
                'bitstream': 'rk_jtag_dual.bit', 'source_match': True}))
            (jtag / 'build.tcl').write_text(
                'foreach page {' + ' '.join(ALL_PAGES) + '} {\n}\n')
            ew = root / 'host-jtag-preparation' / '1793029573705453757'
            ew.mkdir(parents=True)
            (ew / 'report.json').write_text(json.dumps({
                'profile': 'host-jtag-ew-bram', 'status': 'PREPARED_HOST_JTAG_EW_ONLY',
                'bitstream_emitted': False, 'hardware_programmed': False}))
            # The EW emission flow writes the bitstream under bitstream/ with a
            # REBUILD_RECEIPT.md instead of a prepare-package JSON.
            emission = root / 'host-jtag-preparation' / '1793029573705453757-emission'
            (emission / 'bitstream').mkdir(parents=True)
            ew_bit = b'\x07' * (4 * 1024 * 1024)
            (emission / 'bitstream/host-user2-ew.bit').write_bytes(ew_bit)
            (emission / 'REBUILD_RECEIPT.md').write_text('# emission fixture\n')
            (root / 'pooling-image').mkdir()
            inventory = pf.catalog_inventory([str(root / 'jtag-dual-image'),
                                              str(root / 'host-jtag-preparation'),
                                              str(root / 'pooling-image'),
                                              str(root / 'missing-catalog')])
            self.assertEqual(len(inventory), 4)
            self.assertTrue(inventory[0]['exists'])
            entry = inventory[0]['entries'][0]
            self.assertEqual(entry['name'], '20261109T160627Z')
            self.assertEqual(entry['receipts'][0]['profile'], 'ypcb_jtag_dual')
            self.assertEqual(entry['receipts'][0]['status'], 'PASS')
            self.assertEqual(entry['bitstreams'][0]['sha256'], sha_bytes(jtag_bit))
            self.assertEqual(entry['bitstreams'][0]['bytes'], len(jtag_bit))
            self.assertEqual(entry['page_gate'], ALL_PAGES)
            self.assertEqual(inventory[1]['entries'][0]['receipts'][0]['profile'],
                             'host-jtag-ew-bram')
            self.assertEqual(inventory[1]['entries'][0]['bitstreams'], [])
            emission_entry = inventory[1]['entries'][1]
            self.assertEqual(emission_entry['name'], '1793029573705453757-emission')
            self.assertEqual(emission_entry['bitstreams'][0]['sha256'],
                             sha_bytes(ew_bit))
            self.assertEqual(emission_entry['bitstreams'][0]['bytes'], len(ew_bit))
            self.assertEqual(emission_entry['receipts'][0]['receipt'],
                             'REBUILD_RECEIPT.md')
            self.assertEqual(inventory[2]['entries'], [])
            self.assertFalse(inventory[3]['exists'])
            self.assertEqual(inventory[3]['entries'], [])

    def test_missing_catalog_root_is_reported_not_fatal(self):
        inventory = pf.catalog_inventory(['definitely/not/a/catalog/root'])
        self.assertFalse(inventory[0]['exists'])
        self.assertEqual(inventory[0]['entries'], [])


class PreflightCliTests(unittest.TestCase):
    """End-to-end preflight CLI with leaf readers replaced (no real queries)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='jtag-preflight-cli-')
        self.root = Path(self._tmp.name)
        self.catalog = self.root / 'catalog'
        self.four_sha = write_catalog_image(
            self.catalog, '20261109T073000Z',
            ['conv_page', 'pool_page', 'gemm_page', 'conv_fp32_page'])
        self.ypcb_root = write_fake_ypcb(self.root / 'ypcb')
        self.lease = self.root / 'ypcb-jtag.lock'

    def tearDown(self):
        self._tmp.cleanup()

    def run_preflight(self, name, *, stage='absent', six_page=False,
                      hw_servers=(), controllers=(), listening=(),
                      lease_held=False, target=None, catalog=None):
        out = self.root / f'out-{name}'
        lines_0013 = [DLC10_0013] if stage == 'pre_firmware' else []
        lines_0008 = [DLC10_0008] if stage == 'initialized' else []
        if stage == 'absent':
            lines_0013 = lines_0008 = []
        all_lines = lines_0013 + lines_0008
        states = {port: port in listening for port in pf.WATCH_PORTS}

        def fake_lsusb(identifier):
            if identifier == '03fd:0013':
                return lsusb_result(lines_0013)
            if identifier == '03fd:0008':
                return lsusb_result(lines_0008)
            if identifier == '03fd:':
                return lsusb_result(all_lines)
            raise AssertionError(f'unexpected lsusb identifier {identifier}')

        def fake_ports(ports=pf.WATCH_PORTS):
            return {'ports': states, 'listening': sorted(listening),
                    'returncode': 0, 'stdout': ''}

        processes = ([{'pid': 900, 'comm': 'hw_server', 'cmdline': []}] if hw_servers else []) + \
                    [{'pid': 901, 'comm': name, 'cmdline': []} for name in controllers]
        args = ['--out', str(out), '--catalog-root', str(catalog or self.catalog),
                '--ypcb-root', str(self.ypcb_root), '--lease', str(self.lease),
                '--target', target or hw.DEFAULT_TARGET, '--skip-version-probes']
        with mock.patch.object(pf, 'lsusb_lines', side_effect=fake_lsusb), \
                mock.patch.object(pf, 'port_states', side_effect=fake_ports), \
                mock.patch.object(pf, 'proc_processes', return_value=processes), \
                mock.patch.object(pf, 'lease_lock_holders',
                                  return_value={'path': str(self.lease), 'held': lease_held,
                                                'lock_entries': ['synthetic'] if lease_held else []}), \
                mock.patch.object(pf, 'tool_versions',
                                  return_value={'python': '3.14.5', 'paths': {},
                                                'probes': [], 'fxload': 'fixture',
                                                'openFPGALoader': 'fixture', 'vivado': 'fixture'}), \
                mock.patch.object(pf, 'catalog_inventory',
                                  return_value=[{'root': 'fixture-catalog', 'exists': True,
                                                 'entries': []}]), \
                mock.patch.object(pf, 'read_only_command',
                                  side_effect=AssertionError(FAIL_NO_PROCESS)), \
                mock.patch('socket.create_connection', side_effect=AssertionError(FAIL_NO_NETWORK)), \
                mock.patch('subprocess.run', side_effect=AssertionError(FAIL_NO_PROCESS)), \
                mock.patch('subprocess.Popen', side_effect=AssertionError(FAIL_NO_PROCESS)):
            code = pf.main(args)
        receipt = json.loads((out / 'receipt.json').read_text())
        self.assertFalse(self.lease.exists(), 'preflight created/opened the lease file')
        return code, receipt, out

    def test_absent_cable_is_not_ready_exit_2(self):
        code, receipt, _ = self.run_preflight('absent')
        self.assertEqual(code, 2)
        self.assertEqual(receipt['status'], 'PASS_PREFLIGHT_NOT_READY')
        self.assertEqual(receipt['cable']['stage'], 'absent')
        self.assertFalse(receipt['ready_for_authorized_session'])
        self.assertFalse(receipt['hardware_accessed'])
        self.assertFalse(receipt['lease_opened'])
        self.assertFalse(receipt['network_accessed'])
        self.assertFalse(receipt['usb_node_opened'])
        self.assertFalse(receipt['firmware_loaded'])
        self.assertFalse(receipt['hw_server_started'])
        self.assertFalse(receipt['vivado_hardware_manager_started'])
        self.assertFalse(receipt['fabric_programmed'])
        self.assertFalse(receipt['flash_written'])
        self.assertEqual(receipt['image_inventory'][0]['root'], 'fixture-catalog')
        self.assertTrue(any('no DLC10 cable' in item for item in receipt['blockers']))
        steps = [item['command'] for item in receipt['next_commands']]
        self.assertTrue(any('Plug the Xilinx Platform Cable' in step for step in steps))
        self.assertFalse(any('--authorized' in step for step in steps))

    def test_pre_firmware_cable_reports_dlc10_init(self):
        code, receipt, _ = self.run_preflight('pre-firmware', stage='pre_firmware')
        self.assertEqual(code, 2)
        self.assertEqual(receipt['cable']['stage'], 'pre_firmware')
        steps = [item['command'] for item in receipt['next_commands']]
        self.assertTrue(any('dlc10-init.sh' in step for step in steps))
        self.assertFalse(any('--authorized' in step for step in steps))

    def test_initialized_four_page_catalog_is_ready_modes_0_to_4(self):
        code, receipt, _ = self.run_preflight('ready-four', stage='initialized')
        self.assertEqual(code, 0)
        self.assertEqual(receipt['status'], 'PASS_PREFLIGHT_READY')
        self.assertTrue(receipt['ready_for_authorized_session'])
        self.assertEqual(receipt['catalog']['preferred']['page_names'],
                         ['conv_page', 'pool_page', 'gemm_page', 'conv_fp32_page'])
        self.assertEqual(receipt['catalog']['preferred_modes'], [0, 1, 2, 3, 4])
        steps = [item['command'] for item in receipt['next_commands']]
        self.assertTrue(any('--authorized' in step for step in steps))
        self.assertTrue(any('--mode 4' in step for step in steps))
        self.assertFalse(any('--mode 5' in step for step in steps))
        self.assertTrue(any(receipt['catalog']['preferred']['bitstream_sha256'] in step
                            for step in steps))
        self.assertTrue(receipt['prior_board_identity']['dna_port'])

    def test_initialized_six_page_catalog_is_ready_modes_0_to_6(self):
        six_catalog = self.root / 'catalog-six'
        six_sha = write_catalog_image(six_catalog, '20261110T000000Z', ALL_PAGES)
        code, receipt, _ = self.run_preflight('ready-six', stage='initialized',
                                              catalog=six_catalog)
        self.assertEqual(code, 0)
        self.assertEqual(receipt['catalog']['preferred']['bitstream_sha256'], six_sha)
        self.assertEqual(receipt['catalog']['preferred_modes'], [0, 1, 2, 3, 4, 5, 6])
        steps = [item['command'] for item in receipt['next_commands']]
        self.assertTrue(any('--mode 5' in step and '--mode 6' in step for step in steps),
                        'six-page harness command must include modes 5 and 6')
        self.assertTrue(any('[0, 1, 2, 3, 4, 5, 6]' in json.dumps(item)
                            for item in receipt['next_commands']))

    def test_held_lease_is_not_ready(self):
        code, receipt, _ = self.run_preflight('lease-held', stage='initialized',
                                              lease_held=True)
        self.assertEqual(code, 2)
        self.assertFalse(receipt['ready_for_authorized_session'])
        self.assertTrue(any('lease is held' in item for item in receipt['blockers']))

    def test_running_hw_server_is_not_ready(self):
        code, receipt, _ = self.run_preflight('hw-server', stage='initialized',
                                              hw_servers=(900,))
        self.assertEqual(code, 2)
        self.assertTrue(any('hw_server already running' in item
                            for item in receipt['blockers']))

    def test_listening_port_is_not_ready(self):
        code, receipt, _ = self.run_preflight('port', stage='initialized',
                                              listening=(3125,))
        self.assertEqual(code, 2)
        self.assertTrue(any('ports already listening' in item
                            for item in receipt['blockers']))

    def test_invalid_target_is_not_ready(self):
        code, receipt, _ = self.run_preflight(
            'bad-target', stage='initialized',
            target='10.0.0.9:3125/xilinx_tcf/Xilinx/80802026a77a01')
        self.assertEqual(code, 2)
        self.assertTrue(any('invalid --target' in item for item in receipt['blockers']))

    def test_no_emitted_image_is_not_ready(self):
        empty = self.root / 'catalog-empty'
        empty.mkdir()
        code, receipt, _ = self.run_preflight('no-image', stage='initialized',
                                              catalog=empty)
        self.assertEqual(code, 2)
        self.assertTrue(any('no emitted PASS bitstream' in item
                            for item in receipt['blockers']))


if __name__ == '__main__':
    unittest.main()
