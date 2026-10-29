#!/usr/bin/env python3
"""Root-owned, exact-image CH1 cold/idle volatile trial. Never writes flash."""
from pathlib import Path
import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time

ROOT = Path('/home/fedora/rknpu-fpga')
HW = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tools.ddr.transport import DdrJtagTransport
from tools.ddr.raw_test import run_case, scratch
from tools.host.native_link import render_bridge
from tools.tinystories.native_trace import RecordedNativeLink
from tools.tinystories.progress import require_memory

VIVADO = Path('/home/fedora/vivado/2026.1.1/Vivado_Lab/bin/vivado_lab')
HWSERVER = VIVADO.with_name('hw_server')
LEASE = Path('/home/fedora/ypcb/build/hardware-locks/ypcb-jtag.lock')
TARGET = 'localhost:3125/xilinx_tcf/Xilinx/80802026a77a01'
QUIESCING = False


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def literal(value):
    value = str(value)
    need(not any(c in value for c in '{}\\\r\n'), 'Unsafe Tcl literal')
    return '{' + value + '}'


def interrupted(signum, frame):
    if not QUIESCING:
        raise InterruptedError('Physical trial interrupted: ' + str(signum))


def start_owned(argv, logfile, cwd):
    signals = {signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM}
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        return subprocess.Popen(argv, stdout=logfile, stderr=subprocess.STDOUT,
            cwd=cwd, start_new_session=True,
            preexec_fn=lambda: signal.pthread_sigmask(signal.SIG_SETMASK, previous))
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def stop_owned(child):
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def main():
    global QUIESCING
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute-volatile-sram', action='store_true')
    args = parser.parse_args()
    review_path = HW / 'image-review.json'
    review = json.loads(review_path.read_text())
    need(review['status'] == 'REVIEWED_EXPERIMENTAL_CH1_EW_DDR_IMAGE_FOR_VOLATILE_TRIAL', 'Missing image admission')
    need(review['part'] == 'xc7k480tffg1156-2' and review['selected_physical_channel'] == 1, 'Wrong physical profile')
    need(review['programming_scope'] == 'volatile-sram' and review['flash_authorized'] is False, 'Wrong authorization')
    need(review['usr_access'] == 'a2dfec21' and review['target'] == TARGET, 'Wrong source tag/target')
    bit = Path(review['bitstream']['path'])

    def check_review():
        for name, digest in review['bound_files'].items():
            need(sha(name) == digest, 'Changed reviewed file: ' + name)
        need(sha(bit) == review['bitstream']['sha256'], 'Changed reviewed bitstream')

    check_review()
    require_memory(4096)
    if not args.execute_volatile_sram:
        print(json.dumps(dict(status='PASS_OFFLINE_BOUND_INPUT_PREFLIGHT', files=len(review['bound_files']), hardware_accessed=False)))
        return
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(sig, interrupted)
    signal.alarm(1200)
    run = HW / 'physical-test'
    run.mkdir(exist_ok=False)
    record = dict(status='ADMITTED_AUTHORIZED_VOLATILE_CH1_TRIAL', started_utc=now(),
        authorization='User: u can start fpga test if needed', image_review_sha256=sha(review_path),
        bitstream_sha256=sha(bit), target=TARGET, lease=str(LEASE), hardware_programmed=False,
        flash_written=False, selected_physical_channel=1, tests=[], full_capacity_qualified=False,
        ecc_injection_qualified=False, full512_integrated=False, pcie_tested=False)
    write(run / 'report.json', record)
    lease = LEASE.open('a+b')
    server = bridge = program = None
    link = device = None
    logs = []
    try:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record['lease_acquired'] = True
        record['lease_inode'] = os.fstat(lease.fileno()).st_ino
        controllers = []
        names = {'hw_server', 'openocd', 'xsdb', 'openFPGALoader', 'fxload', 'xvcserver', 'xvc-server', 'xvc_server', 'vivado_lab'}
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit():
                continue
            try:
                comm = (proc / 'comm').read_text().strip()
                if comm in names:
                    controllers.append(dict(pid=int(proc.name), name=comm))
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                pass
        need(not controllers, 'Other hardware controller present: ' + repr(controllers))
        for port in (3121, 3125, 3721, 3741, 2542):
            with socket.socket() as sock:
                sock.settimeout(.2)
                need(sock.connect_ex(('127.0.0.1', port)) != 0, 'Hardware debug port already listening: ' + str(port))
        usb = subprocess.run(['lsusb', '-d', '03fd:0008'], capture_output=True, text=True, timeout=10)
        need(usb.returncode == 0 and len(usb.stdout.strip().splitlines()) == 1, 'Expected exactly one initialized DLC10')
        record['lsusb'] = usb.stdout.strip()
        match = re.fullmatch(r'Bus (\d{3}) Device (\d{3}):.*', usb.stdout.strip())
        need(match, 'Cannot identify USB node')
        node = '/dev/bus/usb/' + match[1] + '/' + match[2]
        owners = subprocess.run(['fuser', node], capture_output=True, text=True, timeout=10)
        need(owners.returncode == 1 and not owners.stdout.strip(), 'USB cable owned or check failed')
        record['usb_node'] = node
        check_review()
        serverlog = (run / 'hw-server.log').open('x'); logs.append(serverlog)
        server = start_owned([str(HWSERVER), '-s', 'tcp::3125'], serverlog, run)
        record.update(status='RUNNING_AUTHORIZED_VOLATILE_CH1_TRIAL', hw_server_pid=server.pid)
        write(run / 'report.json', record)
        limit = time.monotonic() + 20
        while True:
            need(server.poll() is None, 'Owned hw_server exited')
            with socket.socket() as sock:
                sock.settimeout(.2)
                if sock.connect_ex(('127.0.0.1', 3125)) == 0:
                    break
            need(time.monotonic() < limit, 'Owned hw_server startup timeout')
            time.sleep(.1)
        load = run / 'load-1'; load.mkdir()
        text = (HW / 'program-template.tcl.in').read_text()
        for name, value in dict(TARGET=TARGET, BITSTREAM=bit, RECEIPT=load/'program.tsv',
                                USR_ACCESS=review['usr_access'], BITSTREAM_SHA=review['bitstream']['sha256']).items():
            marker = '@' + name + '@'
            need(text.count(marker) == 1, 'Unexpected program template marker')
            text = text.replace(marker, literal(value))
        script = load / 'program.tcl'; script.write_text(text)
        argv = [str(VIVADO), '-mode', 'batch', '-source', str(script), '-log', str(load/'vivado.log'), '-journal', str(load/'vivado.jou')]
        command = dict(argv=argv, started_utc=now(), script_sha256=sha(script), flash_written=False)
        write(load / 'command.json', command)
        logfile = (load / 'stdout.log').open('x'); logs.append(logfile)
        record['hardware_programming_may_have_occurred'] = True
        write(run / 'report.json', record)
        program = start_owned(argv, logfile, load)
        command['pid'] = program.pid
        write(load / 'command.json', command)
        code = program.wait(timeout=180)
        command.update(returncode=code, finished_utc=now())
        write(load / 'command.json', command)
        need(code == 0, 'Native SRAM programming Tcl failed')
        pairs = [line.split('\t', 1) for line in (load/'program.tsv').read_text().splitlines()]
        need(all(len(pair) == 2 for pair in pairs), 'Malformed programming receipt')
        actual = dict(pairs)
        need(len(actual) == len(pairs), 'Duplicate programming receipt keys')
        expected = dict(TARGET=TARGET, DNA_PORT='004E544714C705C', TCK_HZ='3000000',
            IDCODE_BEFORE='23751093', IDCODE_AFTER='23751093', INIT_COMPLETE='1', DONE='1',
            PROGRAM_RETURNED='1', PROGRAMMED='1', CLEANUP='1', PASS='1', PROGRAM_FILE=str(bit), BITSTREAM_SHA256=review['bitstream']['sha256'])
        need(all(actual.get(key) == value for key, value in expected.items()), 'Bad load receipt: ' + repr(actual))
        need(actual.get('USR_ACCESS', '').lower() == review['usr_access'], 'Wrong loaded source tag')
        record.update(hardware_programmed=True, load_receipt_sha256=sha(load/'program.tsv'))
        write(run / 'report.json', record)
        print(json.dumps(dict(status='PASS_AUDITED_VOLATILE_LOAD', usr_access=review['usr_access'])), flush=True)
        check_review()
        trial = run / 'raw-jobs'; trial.mkdir()
        bridge_script = trial/'bridge.tcl'
        bridge_script.write_text(render_bridge(TARGET, 'localhost:3125', review['usr_access'], trial/'ready.txt', 3741))
        argv = [str(VIVADO), '-mode', 'batch', '-source', str(bridge_script), '-log', str(trial/'vivado.log'), '-journal', str(trial/'vivado.jou')]
        bridgelog = (trial/'bridge-stdout.log').open('x'); logs.append(bridgelog)
        bridge = start_owned(argv, bridgelog, trial)
        record.update(bridge_pid=bridge.pid, bridge_argv=argv, bridge_script_sha256=sha(bridge_script))
        write(run / 'report.json', record)
        limit = time.monotonic() + 90
        while not (trial/'ready.txt').exists():
            need(bridge.poll() is None, 'Owned bridge exited before READY')
            need(time.monotonic() < limit, 'Owned bridge startup timeout')
            time.sleep(.1)
        need((trial/'ready.txt').read_text().strip() == 'PASS_AUDITED_NATIVE_USER2_BRIDGE_READY', 'Wrong bridge READY')
        with (trial/'native-scans.jsonl').open('x') as trace:
            link = RecordedNativeLink(trace, '127.0.0.1', 3741)
            device = DdrJtagTransport(host=link.host, port=link.port, link=link)
            record['initial_status'] = device.wait_memory_ready(timeout=30.0)
            record['tests'].append(scratch(device))
            write(run/'report.json', record)
            print(json.dumps(record['tests'][-1]), flush=True)
            fixture = review['raw_fixture']
            result = run_case(device, fixture['upload'], fixture['expected'], trial/'actual-bo.txt',
                command_address=fixture['command_address'], initial_amount=fixture['initial_amount'],
                expected_tasks=fixture['expected_tasks'], tag=0x44445201)
            record['tests'].append(result)
            record['final_status'] = device.reg_read(8)
            record['scans'] = link.scans
            link.shutdown_bridge()
            record['bridge_quit_ack'] = True
            device.close(); device = None
            print(json.dumps(result), flush=True)
        need(bridge.wait(timeout=20) == 0, 'Owned bridge cleanup failed')
        check_review()
        record['status'] = 'PASS_PHYSICAL_CH1_SCRATCH_AND_RAW_EW_REQUIRES_INDEPENDENT_WIRE_AUDIT'
    except BaseException as error:
        record.update(status='FAIL_PHYSICAL_CH1_TRIAL', error=repr(error))
        raise
    finally:
        QUIESCING = True
        signal.alarm(0)
        if device is not None:
            device.close()
        elif link is not None:
            link.close()
        for name, child in [('program', program), ('bridge', bridge), ('hw_server', server)]:
            if child is not None:
                stop_owned(child)
                record['owned_' + name + '_exit'] = child.returncode
        for logfile in logs:
            logfile.close()
        record['finished_utc'] = now()
        record['artifacts'] = {str(p.relative_to(run)): sha(p) for p in sorted(run.rglob('*')) if p.is_file() and p != run/'report.json'}
        write(run/'report.json', record)
        fcntl.flock(lease, fcntl.LOCK_UN)
        lease.close()
    print(json.dumps(dict(status=record['status'], report=str(run/'report.json'), flash_written=False)), flush=True)


if __name__ == '__main__':
    main()
