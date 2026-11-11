#!/usr/bin/env python3
"""Strictly read-only readiness preflight for a real ypcb_jtag_dual_top run.

One command an operator can run with the cable absent, uninitialized or ready.
It reports, without changing anything:

* the DLC10 USB stage (`03fd:0013` needs firmware, `03fd:0008` ready,
  absent/ambiguous reported explicitly), from ``lsusb`` only;
* whether ``~/ypcb/dlc10-init.sh`` prerequisites are present, deriving the
  expected firmware/helper paths and SHA-256 values *from that script itself*;
* running `hw_server`/cable-controller processes and whether the debug/bridge
  ports (3121/3122/3125/3721/3741) are listening, from ``/proc`` and ``ss``;
* the shared YPCB JTAG lease state, read from ``/proc/locks`` against the
  lease file's device/inode;
* offline tool versions (Python, fxload, openFPGALoader, Vivado);
* the emitted-image catalog: which real emitted PASS bitstream is preferred,
  its page map and therefore which harness modes it supports;
* dated prior board identity evidence (DNA/IDCODE/serial), clearly marked as
  prior evidence, not a current reading;
* the exact next commands for the session, with the authorization wording
  placeholder left for the user.

It NEVER loads cable firmware, opens /dev/bus/usb, starts hw_server, launches a
Vivado hardware manager, opens or flocks the shared lease, opens a socket
connection, programs/resets the fabric or writes flash. Every subprocess it
launches is a read-only query (`lsusb`, `ss`, and fixed `--version` commands)
and is listed verbatim in the receipt.

Exit codes: 0 = ready for an authorized session; 2 = not ready (reported, with
reasons); 1 = internal/usage error.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.host import run_jtag_dual_hardware as hw  # noqa: E402

TOOL = 'tools/host/jtag_preflight.py'
DEFAULT_YPCB_ROOT = str(Path.home() / 'ypcb')
DEFAULT_OPENTPU_ROOT = str(Path.home() / 'openTPU')
WATCH_PORTS = (3121, 3122, 3125, 3721, 3741)
# Read-only image catalogs: different example families are deployed as separate
# volatile images. Every directory is only stat'ed/JSON-read; no bitstream is
# loaded and no Vivado/hw_server contact happens.
INVENTORY_CATALOGS = ('build/jtag-dual-image', 'build/host-jtag-preparation',
                      'build/pooling-image', 'build/ppu-image')
INVENTORY_RECEIPTS = ('inputs.json', 'report.json')
CONTROLLER_COMMS = ('openFPGALoader', 'xsdb', 'openocd', 'fxload', 'xvcserver',
                    'xvc-server', 'xvc_server')
PRIOR_EVIDENCE = (
    'build/fpga-bringup/ew-startup-1792988881763089417/target-audit/device-properties.rpt',
    'build/fpga-bringup/ew-startup-1792988881763089417/target-audit/report.json',
    'verification/runs/2026-10-27-host-user2-fpga/hardware/physical-tests/report.json',
)
LSUSB_03FD_RE = re.compile(r'^Bus (\d{3}) Device (\d{3}): ID 03fd:([0-9a-f]{4}) (.*)$')


class PreflightError(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def read_only_command(argv, timeout=60):
    """Run one read-only query; never a server, manager, loader or writer."""
    record = {'argv': list(argv), 'started_utc': utc_now()}
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True,
                                timeout=timeout, check=False)
        record.update(returncode=result.returncode,
                      stdout=(result.stdout or '')[:20000],
                      stderr=(result.stderr or '')[:4000])
    except (OSError, subprocess.SubprocessError) as error:
        record.update(error=f'{type(error).__name__}: {error}')
    record['finished_utc'] = utc_now()
    return record


def proc_processes():
    """Read-only /proc scan: PIDs/comm/cmdline, no signals and no execl."""
    processes = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            comm = (proc / 'comm').read_text().strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if comm not in CONTROLLER_COMMS and comm != 'hw_server':
            continue
        item = {'pid': int(proc.name), 'comm': comm}
        try:
            raw = (proc / 'cmdline').read_bytes()
            item['cmdline'] = [part.decode('utf-8', 'replace')
                               for part in raw.split(b'\0') if part]
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            item['cmdline'] = 'unavailable'
        processes.append(item)
    return processes


def lsusb_lines(identifier):
    result = read_only_command(['lsusb', '-d', identifier], timeout=15)
    if 'error' in result:
        result['lines'] = []
        return result
    result['lines'] = [line for line in result['stdout'].splitlines() if line.strip()]
    return result


def classify_cable(usb_0013, usb_0008, other_03fd=None):
    """Classify the DLC10 stage from already-read lsusb lines only."""
    lines_0013 = list(usb_0013.get('lines') or [])
    lines_0008 = list(usb_0008.get('lines') or [])
    other = list(other_03fd or [])
    stage, reason = 'absent', 'no 03fd:0013 or 03fd:0008 device on USB'
    node = None
    if other:
        stage = 'ambiguous'
        reason = ('unrecognized Xilinx 03fd USB device(s) present: '
                  f'{other}; expected 03fd:0013 or 03fd:0008')
    elif len(lines_0008) == 1 and not lines_0013:
        stage, reason = 'initialized', 'exactly one 03fd:0008 operational DLC10'
        match = LSUSB_03FD_RE.match(lines_0008[0])
        if match is not None:
            node = f'/dev/bus/usb/{match[1]}/{match[2]}'
    elif len(lines_0013) == 1 and not lines_0008:
        stage, reason = 'pre_firmware', 'exactly one 03fd:0013 cable; firmware init required'
    elif lines_0013 or lines_0008:
        stage = 'ambiguous'
        reason = (f'unexpected cable count: 03fd:0013={len(lines_0013)}, '
                  f'03fd:0008={len(lines_0008)}; connect exactly one DLC10 and stop other tools')
    return {'stage': stage, 'reason': reason, 'usb_node': node,
            'lines_03fd_0013': lines_0013, 'lines_03fd_0008': lines_0008}


def parse_ss_listening(text, ports=WATCH_PORTS):
    """Ports listening on loopback/wildcard, from `ss -H -ltn` output only."""
    listening = set()
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        local = fields[3]
        if ':' not in local:
            continue
        try:
            port = int(local.rsplit(':', 1)[1])
        except ValueError:
            continue
        listening.add(port)
    return {port: port in listening for port in ports}


def port_states(ports=WATCH_PORTS):
    result = read_only_command(['ss', '-H', '-ltn'], timeout=15)
    result['ports'] = ({port: False for port in ports} if 'error' in result
                       else parse_ss_listening(result.get('stdout', ''), ports))
    result['listening'] = sorted(port for port, state in result['ports'].items() if state)
    return result


def lease_lock_holders(lease_path, proc_locks_text=None):
    """Read-only lease state: stat plus /proc/locks; never open/flock the lease."""
    lease = Path(lease_path)
    record = {'path': str(lease), 'exists': lease.is_file(),
              'size': None, 'ino': None, 'dev_major': None, 'dev_minor': None,
              'lock_entries': [], 'held': None,
              'source': 'stat + /proc/locks (the lease is never opened or flocked)'}
    if not record['exists']:
        record.update(held=False, note='lease file does not exist yet')
        return record
    info = lease.stat()
    record.update(size=info.st_size, ino=info.st_ino,
                  dev_major=os.major(info.st_dev), dev_minor=os.minor(info.st_dev))
    try:
        text = proc_locks_text if proc_locks_text is not None else Path('/proc/locks').read_text()
    except OSError as error:
        record.update(held=None, error=f'cannot read /proc/locks: {error}')
        return record
    pattern = re.compile(
        r'^\s*(?P<id>\d+):\s+(?P<type>\S+)\s+(?P<mode>\S+)\s+(?P<kind>\S+)\s+'
        r'(?P<pid>\d+)\s+(?P<major>[0-9a-fA-F]+):(?P<minor>[0-9a-fA-F]+):(?P<ino>\d+)\s')
    for line in text.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        if (int(match['major'], 16) == record['dev_major'] and
                int(match['minor'], 16) == record['dev_minor'] and
                int(match['ino']) == record['ino']):
            record['lock_entries'].append(line.strip())
    record['held'] = bool(record['lock_entries'])
    return record


def dlc10_prerequisites(ypcb_root, commands=('lsusb', 'sha256sum', 'awk', 'pgrep', 'python3')):
    """Derive expected firmware files/hashes from dlc10-init.sh and verify them.

    Reads only: the script and the referenced files are stat'ed/hashed; nothing
    is executed and no USB node is opened.
    """
    root = Path(ypcb_root)
    script = root / 'dlc10-init.sh'
    record = {'ypcb_root': str(root), 'script': str(script), 'script_sha256': None,
              'ok': False, 'command_paths': {}, 'checks': [], 'error': None}
    for name in commands:
        found = None
        for directory in os.environ.get('PATH', '').split(os.pathsep):
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                found = str(candidate)
                break
        record['command_paths'][name] = found
    if not script.is_file():
        record['error'] = f'missing cable-init script: {script}'
        return record
    record['script_sha256'] = sha_file(script)
    try:
        text = script.read_text()
    except OSError as error:
        record['error'] = f'cannot read {script}: {error}'
        return record
    variables = {}
    for name, pattern in (('boot', r'^boot="\$root/([^"]+)"'),
                          ('overlay', r'^overlay="\$root/([^"]+)"'),
                          ('helper', r'^helper="\$root/([^"]+)"')):
        match = re.search(pattern, text, re.M)
        variables[name] = root / match[1] if match is not None else None
    hashes = {}
    for name in ('boot', 'overlay', 'helper'):
        match = re.search(r'check_hash "\$' + name + r'" ([0-9a-f]{64})', text)
        hashes[name] = match[1] if match is not None else None
    if any(path is None for path in variables.values()) or any(h is None for h in hashes.values()):
        record['error'] = ('cannot derive firmware paths/hashes from dlc10-init.sh; '
                           'the audited script changed shape')
        return record
    for name in ('boot', 'overlay', 'helper'):
        path = variables[name]
        item = {'name': name, 'path': str(path), 'expected_sha256': hashes[name],
                'exists': path.is_file()}
        if item['exists']:
            item['actual_sha256'] = sha_file(path)
            item['matches'] = item['actual_sha256'] == item['expected_sha256']
        else:
            item['matches'] = False
        record['checks'].append(item)
    extras = {
        'openFPGALoader_debug': root / 'openFPGALoader/build-xpcu-debug/openFPGALoader',
        'stage2_helper': root / 'local-overrides/ref-inspur-adventures/files/scripts/xpcu_stage2.py',
    }
    for name, path in extras.items():
        record['checks'].append({'name': name, 'path': str(path),
                                 'exists': path.is_file(),
                                 'matches': path.is_file()})
    record['ok'] = (all(item['matches'] for item in record['checks']) and
                    all(record['command_paths'].values()))
    return record


def tool_versions(probe=True):
    record = {
        'python': platform.python_version(),
        'paths': {name: shutil_which(name) for name in
                  ('fxload', 'openFPGALoader', 'vivado', 'hw_server', 'lsusb', 'ss', 'flock')},
        'probes': [],
    }
    if not probe:
        return record
    probes = []
    if record['paths'].get('fxload'):
        probes.append(('fxload', [record['paths']['fxload'], '-V']))
    if record['paths'].get('openFPGALoader'):
        probes.append(('openFPGALoader', [record['paths']['openFPGALoader'], '-V']))
    if record['paths'].get('vivado'):
        probes.append(('vivado', [record['paths']['vivado'], '-version']))
    for name, argv in probes:
        result = read_only_command(argv, timeout=90)
        record['probes'].append(result)
        first = (result.get('stdout') or result.get('stderr') or '').strip().splitlines()
        record[name] = first[0] if result.get('returncode') == 0 and first else 'unavailable'
    return record


def shutil_which(name):
    for directory in os.environ.get('PATH', '').split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def catalog_entry(directory):
    """Read-only description of one build receipt directory."""
    directory = Path(directory)
    entry = {'directory': str(directory), 'name': directory.name,
             'receipts': [], 'bitstreams': [], 'page_gate': None}
    for name in INVENTORY_RECEIPTS:
        path = directory / name
        if not path.is_file():
            continue
        record = {'receipt': name, 'sha256': sha_file(path)}
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            record['parse_error'] = f'{type(error).__name__}: {error}'
            data = {}
        for key in ('profile', 'status', 'bitstream_emitted', 'hardware_accessed',
                    'top', 'part', 'source_match'):
            if key in data:
                record[key] = data[key]
        entry['receipts'].append(record)
        if name == 'inputs.json' and isinstance(data.get('bitstream'), str):
            candidate = directory / 'implementation' / data['bitstream']
            if candidate.is_file() and candidate not in entry['bitstreams']:
                entry['bitstreams'].append(candidate)
    # Build receipts put the bitstream under implementation/; the EW emission
    # flow writes it under bitstream/ next to REBUILD_RECEIPT.md. Scan one
    # level of subdirectories so every emitted image is listed regardless of
    # the producing flow.
    for candidate in sorted(directory.glob('*/*.bit')):
        if candidate not in entry['bitstreams']:
            entry['bitstreams'].append(candidate)
    rebuild = directory / 'REBUILD_RECEIPT.md'
    if rebuild.is_file():
        entry['receipts'].append({
            'receipt': 'REBUILD_RECEIPT.md', 'sha256': sha_file(rebuild),
            'note': 'emission receipt (not a prepare-package JSON)',
        })
    entry['bitstreams'] = [
        {'file': str(path), 'bytes': path.stat().st_size, 'sha256': sha_file(path)}
        for path in entry['bitstreams']
    ]
    gate = directory / 'build.tcl'
    if gate.is_file():
        try:
            entry['page_gate'] = hw.parse_page_gate(gate)
        except (OSError, ValueError) as error:
            entry['page_gate_error'] = str(error)
    return entry


def catalog_inventory(roots=None):
    """List every cataloged build receipt/bitstream across image families.

    Strictly read-only: directory listing, receipt JSON reads and SHA-256 file
    reads only. A missing catalog is reported, not an error, so the command
    works before task-9/task-10 images exist.
    """
    catalogs = []
    for root in (roots or INVENTORY_CATALOGS):
        base = Path(root)
        if not base.is_absolute():
            base = ROOT / base
        catalog = {'root': str(base), 'exists': base.is_dir(), 'entries': []}
        if base.is_dir():
            catalog['entries'] = [catalog_entry(directory) for directory in
                                  sorted(base.iterdir()) if directory.is_dir()]
        catalogs.append(catalog)
    return catalogs


def select_preferred_image(emitted):
    """Prefer the richest page map (six pages over four), then the newest stamp."""
    if not emitted:
        return None
    return sorted(emitted, key=lambda entry: (len(entry.get('pages') or []), entry['stamp']))[-1]


def modes_for_image(image):
    if image is None:
        return []
    page_names = {page['name'] for page in image.get('pages') or []}
    modes = [0]
    for mode, spec in sorted(hw.MODE_SPECS.items()):
        if spec['kind'] == 'job' and spec['page'] in page_names:
            modes.append(mode)
    return modes


def prior_board_identity():
    """Dated prior physical evidence, read-only; never a current reading."""
    identity = {'note': ('prior 2026-10-26/27 evidence, not a current card reading; '
                         'the preflight itself cannot read the board'),
                'sources': [], 'dna_port': None, 'idcode': None,
                'cable_serial': None, 'usr_access': None, 'cfgbvs_pin': None}
    properties = ROOT / PRIOR_EVIDENCE[0]
    if properties.is_file():
        identity['sources'].append({'path': str(properties), 'sha256': sha_file(properties)})
        text = properties.read_text(errors='replace')
        for key, pattern in (
                ('dna_port', r'REGISTER\.EFUSE\.DNA_PORT\s+string\s+\w+\s+([0-9A-Fa-f]+)'),
                ('usr_access', r'REGISTER\.USR_ACCESS\s+string\s+\w+\s+([0-9A-Fa-f]+)'),
                ('cfgbvs_pin', r'REGISTER\.CONFIG_STATUS\.BIT30_CFGBVS_PIN\s+string\s+\w+\s+(\d)'),
                ('idcode', r'IDCODE_HEX\s+string\s+\w+\s+([0-9a-fA-F]+)')):
            match = re.search(pattern, text)
            if match is not None:
                identity[key] = match[1]
    target = ROOT / PRIOR_EVIDENCE[1]
    if target.is_file():
        identity['sources'].append({'path': str(target), 'sha256': sha_file(target)})
    physical = ROOT / PRIOR_EVIDENCE[2]
    if physical.is_file():
        identity['sources'].append({'path': str(physical), 'sha256': sha_file(physical)})
        try:
            record = json.loads(physical.read_text())
            identity['cable_serial'] = None
            identity['prior_target_uri'] = record.get('target')
            identity['prior_lsusb'] = record.get('lsusb')
            identity['prior_flash_written'] = record.get('flash_written')
            identity['prior_hardware_programmed'] = record.get('hardware_programmed')
        except (OSError, ValueError):
            pass
    return identity


def _authorization_placeholder(note):
    return note or '<copy the user authorization wording here>'


def next_commands(cable, prereqs, ports, processes, lease, image, args):
    """Exact next commands for the current state; none of them are executed."""
    modes = modes_for_image(image)
    mode_args = ' '.join(f'--mode {mode}' for mode in modes) if modes else '--mode 0'
    image_sha = image['bitstream_sha256'] if image else '<EMITTED-IMAGE-SHA256>'
    target = args.target
    lease_path = args.lease
    common = (f'--image {image_sha} --target {target} --lease {lease_path}')
    commands = []
    commands.append({
        'step': 0, 'requires_authorization': False,
        'command': "lsusb -d 03fd:0013; lsusb -d 03fd:0008; lsusb -d 03fd:",
        'expected': 'exactly one 03fd:0013 (needs init) or one 03fd:0008 (ready)',
    })
    stage = cable['stage']
    if stage == 'absent':
        commands.append({
            'step': 1, 'requires_authorization': False,
            'command': '# Plug the Xilinx Platform Cable USB II into this host, then rerun: '
                       f'python3 {TOOL}',
            'expected': 'lsusb shows exactly one 03fd:0013 (pre-firmware) or 03fd:0008',
        })
        commands.append({'step': 2, 'requires_authorization': False,
                         'command': f'python3 {TOOL}',
                         'expected': 'cable stage is reported (pre_firmware or initialized)'})
        return commands
    if stage == 'pre_firmware':
        commands.append({
            'step': 1, 'requires_authorization': False,
            'command': f'(cd {args.ypcb_root} && bash dlc10-init.sh)',
            'expected': ('PASS: DLC10 initialized and YPCB XC7K480T detected; '
                         'idcode 0x23751093; node becomes 03fd:0008. '
                         'Never start hw_server before this finishes.'),
        })
        commands.append({'step': 2, 'requires_authorization': False,
                         'command': f'python3 {TOOL}',
                         'expected': 'cable stage initialized, ready=true'})
        return commands
    if stage != 'initialized':
        commands.append({
            'step': 1, 'requires_authorization': False,
            'command': '# Resolve the ambiguous cable state: unplug other DLC10s/stop other '
                       'cable tools, leaving exactly one cable, then rerun the preflight',
            'expected': 'cable stage initialized',
        })
        return commands
    commands.append({
        'step': 1, 'requires_authorization': True,
        'command': ('# Read-only target audit (doc §5): owned hw_server under the shared '
                    'lease; expect DNA 004E544714C705C, IDCODE 23751093, INIT/DONE, '
                    'USR_ACCESS, CFGBVS_PIN=0; then stop the server'),
        'expected': 'PASS_READ_ONLY_TARGET_AUDIT with one exact target URI',
        'doc': 'docs/BOARD_RUN_PREP.md §5',
    })
    commands.append({
        'step': 2, 'requires_authorization': True,
        'command': ('# Volatile JTAG load of the exact image only (doc §6A audited Vivado '
                    'route; §6B openFPGALoader). FLASH IS FORBIDDEN. Expect INIT=1, DONE=1, '
                    'IDCODE before/after, USR_ACCESS==source-tag expectation, DNA unchanged; '
                    'then stop hw_server'),
        'expected': f"bitstream {image_sha} loaded, INIT=1 DONE=1, flash_written=false",
        'doc': 'docs/BOARD_RUN_PREP.md §6',
        'image_sha256': image_sha,
    })
    check_command = (f'python3 tools/host/run_jtag_dual_hardware.py --check {common} '
                     f'{mode_args} --out build/board-prep/<UTC-stamp>-check')
    commands.append({
        'step': 3, 'requires_authorization': False, 'command': check_command,
        'expected': 'PASS_CHECK (no hardware opened); use the printed mode list',
        'image_modes': modes,
    })
    harness_command = (f"python3 tools/host/run_jtag_dual_hardware.py --authorized "
                       f"--authorization-note '{_authorization_placeholder(args.authorization_note)}' "
                       f"--source-tag none {common} {mode_args} "
                       f'--out build/board-prep/<UTC-stamp>-hardware')
    commands.append({
        'step': 4, 'requires_authorization': True, 'command': harness_command,
        'expected': ('per-mode PASS with complete 4096-byte BO compare; mode 0 last '
                     '(quarantines the bridge); keep the receipt directory'),
        'image_sha256': image_sha, 'modes': modes,
        'note': ('--source-tag none for the current untagged image; if the build gains a '
                 'BITSTREAM.CONFIG.USR_ACCESS tag, pass that 8-hex tag instead.'),
    })
    commands.append({
        'step': 5, 'requires_authorization': False,
        'command': f'python3 {TOOL}',
        'expected': 'post-run read-only state: no hw_server, lease free, cable 03fd:0008',
    })
    return commands


def collect(args):
    """Run every read-only check. No lease, USB node, socket or server is opened."""
    usb_0013 = lsusb_lines('03fd:0013')
    usb_0008 = lsusb_lines('03fd:0008')
    usb_all = lsusb_lines('03fd:')
    other_03fd = [line for line in (usb_all.get('lines') or [])
                  if 'ID 03fd:0013' not in line and 'ID 03fd:0008' not in line]
    cable = classify_cable(usb_0013, usb_0008, other_03fd)
    cable['lsusb_03fd_all'] = {key: usb_all.get(key) for key in
                               ('returncode', 'error', 'lines')}
    cable['lsusb_03fd_0013'] = {key: usb_0013.get(key) for key in
                                ('returncode', 'error', 'lines')}
    cable['lsusb_03fd_0008'] = {key: usb_0008.get(key) for key in
                                ('returncode', 'error', 'lines')}
    processes = proc_processes()
    hw_servers = [item for item in processes if item['comm'] == 'hw_server']
    controllers = [item for item in processes if item['comm'] in CONTROLLER_COMMS]
    ss = port_states(WATCH_PORTS)
    lease = lease_lock_holders(args.lease)
    prereqs = dlc10_prerequisites(args.ypcb_root)
    versions = tool_versions(probe=not args.skip_version_probes)
    inventory = catalog_inventory(getattr(args, 'image_catalog', None))
    emitted, rejected = hw.scan_image_catalog(Path(args.catalog_root))
    preferred = select_preferred_image(emitted)
    if preferred is not None:
        preferred['source_freshness'] = hw.source_freshness(preferred)
    image = None
    if preferred is not None:
        image = {key: preferred.get(key) for key in
                 ('stamp', 'receipt', 'receipt_sha256', 'bitstream', 'bitstream_sha256',
                  'bitstream_bytes', 'top', 'part', 'page_names', 'pages',
                  'page_gate_source', 'page_gate_sha256', 'reports', 'source_freshness')}
    blockers = []
    for label, result in (('lsusb 03fd:0013', usb_0013), ('lsusb 03fd:0008', usb_0008),
                          ('lsusb 03fd:', usb_all)):
        if 'error' in result:
            blockers.append(f'cannot enumerate USB: {label}: {result["error"]}')
    try:
        hw.parse_target(args.target)
    except ValueError as error:
        blockers.append(f'invalid --target: {error}')
    if not Path(args.lease).is_absolute():
        blockers.append('--lease must be an absolute path')
    if 'error' in ss:
        blockers.append(f'cannot inspect debug/bridge ports with ss: {ss["error"]}')
    if cable['stage'] == 'absent':
        blockers.append('no DLC10 cable on USB (plug it in, expect 03fd:0013)')
    elif cable['stage'] == 'pre_firmware':
        blockers.append('cable is pre-firmware 03fd:0013: run ~/ypcb/dlc10-init.sh')
    elif cable['stage'] == 'ambiguous':
        blockers.append(f"ambiguous cable state: {cable['reason']}")
    if not prereqs['ok']:
        blockers.append('~/ypcb/dlc10-init.sh prerequisites are incomplete or changed')
    if hw_servers:
        blockers.append(f"hw_server already running (PIDs {[item['pid'] for item in hw_servers]}); "
                        'stop it before a harness session')
    if controllers:
        blockers.append(f"other cable controller processes: {[(i['pid'], i['comm']) for i in controllers]}")
    if ss['listening']:
        blockers.append(f"debug/bridge ports already listening: {ss['listening']}")
    if lease['held']:
        blockers.append('shared JTAG lease is held (see /proc/locks entries)')
    if image is None:
        blockers.append(f'no emitted PASS bitstream in {args.catalog_root}; nothing to load')
    ready = not blockers
    return {
        'schema': 1, 'tool': TOOL, 'status': 'PASS_PREFLIGHT_READY' if ready else 'PASS_PREFLIGHT_NOT_READY',
        'started_utc': None, 'finished_utc': None,
        'ready_for_authorized_session': ready,
        'hardware_accessed': False, 'usb_node_opened': False, 'lease_opened': False,
        'network_accessed': False, 'socket_connection_opened': False,
        'firmware_loaded': False, 'hw_server_started': False,
        'vivado_hardware_manager_started': False, 'fabric_programmed': False,
        'fabric_reset': False, 'configuration_written': False, 'flash_written': False,
        'read_only_guarantees': ('only /proc, lsusb, ss, stat/SHA-256 reads, fixed '
                                 '--version probes and build-receipt reads; the lease, '
                                 'USB nodes, sockets and hardware managers are untouched'),
        'target': args.target, 'lease': lease,
        'cable': cable,
        'prerequisites': prereqs,
        'processes': {'hw_server': hw_servers, 'controllers': controllers,
                      'all_matching': processes},
        'ports': ss,
        'tools': versions,
        'catalog': {'root': str(Path(args.catalog_root)),
                    'emitted': [{'stamp': entry['stamp'],
                                 'bitstream_sha256': entry.get('bitstream_sha256'),
                                 'page_names': entry.get('page_names')}
                                for entry in emitted],
                    'rejected_count': len(rejected),
                    'preferred': image,
                    'preferred_modes': modes_for_image(image)},
        'image_inventory': inventory,
        'prior_board_identity': prior_board_identity(),
        'blockers': blockers,
        'next_commands': next_commands(cable, prereqs, ss, processes, lease, image, args),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=None,
                        help='fresh output directory (default build/board-prep/<UTC>-preflight)')
    parser.add_argument('--catalog-root', type=Path, default=hw.IMAGE_CATALOG,
                        help='emitted-image receipt catalog (read-only)')
    parser.add_argument('--image-catalog', action='append', default=None,
                        help='extra/only build catalogs to inventory read-only (repeatable; '
                             'default: ' + ', '.join(INVENTORY_CATALOGS) + ')')
    parser.add_argument('--ypcb-root', default=DEFAULT_YPCB_ROOT,
                        help='~/ypcb tooling root (read-only; hashes and paths only)')
    parser.add_argument('--opentpu-root', default=DEFAULT_OPENTPU_ROOT,
                        help='~/openTPU root (recorded for reference; not executed)')
    parser.add_argument('--lease', default=hw.DEFAULT_LEASE,
                        help='shared YPCB JTAG lease path (read-only /proc/locks view)')
    parser.add_argument('--target', default=hw.DEFAULT_TARGET,
                        help='exact audited cable URI used in the generated next commands')
    parser.add_argument('--authorization-note', default='',
                        help='optional user authorization wording embedded in the generated '
                             'harness command; the preflight never uses it itself')
    parser.add_argument('--skip-version-probes', action='store_true',
                        help='do not launch the read-only version commands '
                             '(fxload -V, openFPGALoader -V, vivado -version)')
    return parser


def print_summary(record):
    cable = record['cable']
    print(f"PREFLIGHT {record['started_utc']} target={record['target']}")
    print(f"cable_stage: {cable['stage']}  ({cable['reason']})")
    for label, key in (('lsusb 03fd:0013', 'lines_03fd_0013'),
                       ('lsusb 03fd:0008', 'lines_03fd_0008'),
                       ('lsusb -d 03fd', 'lsusb_03fd_all')):
        if key == 'lsusb_03fd_all':
            lines = (cable.get(key) or {}).get('lines') or []
        else:
            lines = cable.get(key) or []
        print(f"  {label}: {lines if lines else '(none)'}")
    prereqs = record['prerequisites']
    print(f"dlc10_prerequisites: {'OK' if prereqs['ok'] else 'NOT OK'}"
          f" (script sha256={prereqs.get('script_sha256')})")
    if prereqs.get('error'):
        print(f"  error: {prereqs['error']}")
    for item in prereqs.get('checks', []):
        print(f"  {item['name']}: exists={item['exists']} matches={item['matches']} "
              f"({item.get('path')})")
    print(f"hw_server_processes: {[item['pid'] for item in record['processes']['hw_server']]}")
    print(f"controller_processes: {[(i['pid'], i['comm']) for i in record['processes']['controllers']]}")
    print('ports: ' + ', '.join(f"{port}={'LISTEN' if state else 'closed'}"
                                for port, state in record['ports']['ports'].items()))
    lease = record['lease']
    print(f"lease: {'HELD' if lease['held'] else ('free' if lease['held'] is False else 'unknown')}"
          f" path={lease['path']} size={lease.get('size')}")
    tools = record['tools']
    print('versions: ' + ', '.join(f"{name}={tools.get(name)}" for name in
                                   ('python', 'fxload', 'openFPGALoader', 'vivado')))
    catalog = record['catalog']
    preferred = catalog['preferred']
    print(f"catalog: emitted={len(catalog['emitted'])} rejected={catalog['rejected_count']}")
    if preferred is None:
        print('  preferred_image: none')
    else:
        print(f"  preferred_image: {preferred['stamp']} sha256={preferred['bitstream_sha256']} "
              f"pages={preferred['page_names']} modes={catalog['preferred_modes']}")
    inventory = record.get('image_inventory') or []
    if inventory:
        print('image_inventory (read-only catalogs):')
        for catalog in inventory:
            if not catalog['exists']:
                print(f"  {catalog['root']}: (missing; no image yet)")
                continue
            print(f"  {catalog['root']}: {len(catalog['entries'])} receipt dir(s)")
            for entry in catalog['entries']:
                bits = ', '.join(f"{bit['sha256'][:12]}… {Path(bit['file']).name}"
                                 for bit in entry['bitstreams']) or 'no bitstream'
                profiles = ', '.join(
                    f"{r.get('profile') or 'profile?'}:{r.get('status') or 'status?'}"
                    for r in entry['receipts']) or 'no receipt'
                gate = f" pages={entry['page_gate']}" if entry.get('page_gate') else ''
                print(f"    {entry['name']}: {profiles} | {bits}{gate}")
    identity = record['prior_board_identity']
    if identity.get('dna_port'):
        print(f"prior_board_identity (dated, not current): DNA={identity['dna_port']} "
              f"IDCODE={identity.get('idcode')} CFGBVS_PIN={identity.get('cfgbvs_pin')}")
    print(f"ready_for_authorized_session: {record['ready_for_authorized_session']}")
    if record['blockers']:
        print('blockers:')
        for blocker in record['blockers']:
            print(f'  - {blocker}')
    print('next_commands (none executed):')
    for item in record['next_commands']:
        print(f"  {item['step']}. {item['command']}")
        if 'expected' in item:
            print(f"     expected: {item['expected']}")


def main(argv=None):
    args = build_parser().parse_args(argv)
    out = Path(args.out) if args.out else (
        ROOT / 'build/board-prep' /
        (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-preflight'))
    if out.exists():
        print(f'FAIL: --out must name a fresh directory; it exists: {out}', file=sys.stderr)
        return 1
    out.mkdir(parents=True)
    receipt_path = out / 'receipt.json'
    started = utc_now()
    record = {'schema': 1, 'tool': TOOL, 'status': 'RUNNING', 'started_utc': started}
    write_json(receipt_path, record)
    try:
        record = collect(args)
        record['started_utc'] = started
        record['command'] = [sys.executable, str(Path(__file__).resolve()), *(argv or sys.argv[1:])]
        record['environment'] = {'python': platform.python_version(),
                                 'host': platform.node(), 'cwd': str(Path.cwd())}
        record['receipt'] = str(receipt_path)
        record['source_hashes'] = {}
        for name in (TOOL, 'tools/host/run_jtag_dual_hardware.py',
                     'tools/host/transport.py', 'tools/host/native_link.py',
                     'tests/host/test_jtag_preflight.py'):
            if (ROOT / name).is_file():
                record['source_hashes'][name] = hashlib.sha256(
                    (ROOT / name).read_bytes()).hexdigest()
        record['finished_utc'] = utc_now()
        write_json(receipt_path, record)
        print_summary(record)
        print(f"{record['status']} exit={0 if record['ready_for_authorized_session'] else 2} "
              f"receipt={receipt_path}")
        return 0 if record['ready_for_authorized_session'] else 2
    except Exception as error:  # read-only tool must report, not crash mid-receipt
        record.update(status='PREFLIGHT_INTERNAL_ERROR', finished_utc=utc_now(),
                      error=f'{type(error).__name__}: {error}')
        write_json(receipt_path, record)
        print(f'PREFLIGHT_INTERNAL_ERROR: {type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
