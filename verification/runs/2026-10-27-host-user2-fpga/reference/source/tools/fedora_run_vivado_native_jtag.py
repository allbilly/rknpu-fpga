#!/usr/bin/env python3
"""Run the unchanged MIG tests through Vivado's native cable driver.

Numeric localhost JTAG RPC; no programming, counter clearing or FPGA clock
changes. Full physical memory and model gates remain required.
"""

try:
    from .workspace_paths import expand_paths
except ImportError:
    from workspace_paths import expand_paths
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import os

ROOT = Path(__file__).resolve().parents[1]
CAND = ROOT/'build/fedora-vivado/mig-jtag-controller-20261010T235833Z'
VIVADO = Path(expand_paths('@VIVADO_BIN@'))
sys.path.insert(0, str(ROOT))

TCL = r'''
open_hw_manager
connect_hw_server -url localhost:3122
set targets [get_hw_targets]
if {[llength $targets] != 1} {error "Expected exactly one hardware target"}
current_hw_target [lindex $targets 0]
set_property PARAM.FREQUENCY 3000000 [current_hw_target]
open_hw_target
set devices [get_hw_devices]
if {[llength $devices] != 1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {
    error "Expected single YPCB XC7K480T"
}
close_hw_target
open_hw_target -jtag_mode 1
run_state_hw_jtag RESET
run_state_hw_jtag IDLE
scan_ir_hw_jtag 6 -tdi 09
set ident [scan_dr_hw_jtag 32 -tdi 0]
if {[expr "0x$ident"] != 0x23751093} {error "Unexpected raw IDCODE"}
if {[info exists ::env(OTPU_NATIVE_BIT)]} {
    close_hw_target
    open_hw_target
    set devices [get_hw_devices]
    if {[llength $devices] != 1 || [get_property PART [lindex $devices 0]] ne "xc7k480t"} {
        error "Programming target changed"
    }
    set device [lindex $devices 0]
    set_property PROGRAM.FILE $::env(OTPU_NATIVE_BIT) $device
    program_hw_devices $device
    refresh_hw_device $device
    set init [get_property REGISTER.IR.BIT4_INIT_COMPLETE $device]
    set configured [get_property REGISTER.IR.BIT5_DONE $device]
    if {![string is boolean -strict $init] || ![string is boolean -strict $configured] ||
        !$init || !$configured} {error "Native programming INIT/DONE failed"}
    set f [open $::env(OTPU_NATIVE_PROGRAM_STATUS) w]
    puts $f "INIT=1 DONE=1"
    close $f
    close_hw_target
    open_hw_target -jtag_mode 1
    run_state_hw_jtag RESET
    run_state_hw_jtag IDLE
    scan_ir_hw_jtag 6 -tdi 09
    set ident [scan_dr_hw_jtag 32 -tdi 0]
    if {[expr "0x$ident"] != 0x23751093} {error "Post-load IDCODE changed"}
}
scan_ir_hw_jtag 6 -tdi 03
set reply [scan_dr_hw_jtag 640 -tdi 0]
set word [expr "0x$reply"]
if {(($word >> 536) & 0xffffffff) != 0x4f54504a} {error "OpenTPU mailbox absent"}
set owner ""
set done 0
proc drop {channel} {
    global owner
    catch {close $channel}
    if {$owner eq $channel} {set owner ""}
}
proc request {channel} {
    if {[eof $channel]} {drop $channel; return}
    if {[gets $channel line] < 0} {
        if {[eof $channel]} {drop $channel}
        return
    }
    if {[string length $line] > 1024} {drop $channel; return}
    if {[catch {
        set fields [split $line]
        set result 0
        switch -- [lindex $fields 0] {
            RESET {
                if {[llength $fields] != 1} {error "Bad reset"}
                run_state_hw_jtag RESET
                run_state_hw_jtag IDLE
            }
            IDLE {
                set cycles [lindex $fields 1]
                if {[llength $fields] != 2 || ![string is integer -strict $cycles] ||
                    $cycles < 1 || $cycles > 4096} {error "Bad idle count"}
                runtest_hw_jtag -wait_state IDLE -end_state IDLE -tck $cycles
            }
            SCAN {
                lassign $fields unused kind bits value
                if {[llength $fields] != 4 || ![string is integer -strict $bits] ||
                    $bits < 1 || $bits > 640 || ![regexp {^[0-9a-fA-F]{1,160}$} $value]} {
                    error "Bad scan fields"
                }
                if {$kind eq "IR" && $bits == 6} {
                    set result [scan_ir_hw_jtag $bits -tdi $value]
                } elseif {$kind eq "DR"} {
                    set result [scan_dr_hw_jtag $bits -tdi $value]
                } else {error "Bad scan kind"}
            }
            QUIT {
                if {[llength $fields] != 1} {error "Bad quit"}
                after 0 {set ::done 1}
            }
            default {error "Unknown command"}
        }
    } failure]} {
        puts $channel "ERR [string map {\n { } \r { }} $failure]"
    } else {puts $channel "OK $result"}
    flush $channel
}
proc accept {channel address port} {
    global owner
    fconfigure $channel -blocking 0 -buffering line -translation lf
    if {$owner ne ""} {puts $channel BUSY; flush $channel; close $channel; return}
    set owner $channel
    puts $channel READY
    flush $channel
    fileevent $channel readable [list request $channel]
}
set listener [socket -server accept -myaddr 127.0.0.1 3741]
set f [open $::env(OTPU_NATIVE_READY) w]
puts $f PASS_NATIVE_CHAIN_AND_OPENTPU_MAILBOX
close $f
vwait done
if {$owner ne ""} {drop $owner}
close $listener
close_hw_target
disconnect_hw_server
close_hw_manager
exit
'''


class NativeLink:
    """The scan/reset interface consumed by the existing JtagTransport."""
    def __init__(self, host='127.0.0.1', port=3741, timeout=30):
        self.failed = False
        deadline = time.monotonic()+timeout
        while True:
            self.sock = socket.create_connection((host, port), timeout)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.reader = self.sock.makefile('rb')
            try:
                response = self.reader.readline(1025)
                if response == b'READY\n':
                    break
                if response != b'BUSY\n' or time.monotonic() >= deadline:
                    raise IOError('Native JTAG bridge is not ready or already owned')
                self.close()
                time.sleep(.05)
            except BaseException:
                self.close()
                raise

    def command(self, text):
        if self.failed:
            raise IOError('Native JTAG connection needs recovery')
        try:
            self.sock.sendall((text+'\n').encode('ascii'))
            line = self.reader.readline(1025)
            if not re.fullmatch(rb'OK [0-9a-fA-F]+\n', line):
                raise IOError(f'Native JTAG command failed: {line[:512]!r}')
            return int(line[3:-1], 16)
        except BaseException:
            self.failed = True
            raise

    def scan(self, value, bits=640, ir=False):
        if not isinstance(bits, int) or not 1 <= bits <= 640 or (ir and bits != 6):
            raise ValueError('Invalid native scan length')
        if not isinstance(value, int) or not 0 <= value < 1 << bits:
            raise ValueError('Native scan value exceeds its length')
        result = self.command(f'SCAN {"IR" if ir else "DR"} {bits} {value:x}')
        if result >= 1 << bits:
            self.failed = True
            raise IOError('Native scan response exceeds its length')
        return result

    def reset(self):
        self.command('RESET')

    def shift(self, n, tms, tdi):
        if tms or tdi or not 1 <= n <= 4096:
            raise ValueError('Native raw shift supports idle clocks only')
        self.command(f'IDLE {n}')
        return 0

    def close(self):
        self.reader.close()
        self.sock.close()


def wait_for_calibration(transport, timeout=120, observe=None):
    from opentpu.host import regs as R
    deadline = time.monotonic()+timeout
    required = R.ST_CALIB0 | R.ST_CALIB1
    while True:
        state = transport.reg_read(R.R_STATUS)
        if observe:
            observe(state)
        if state & (R.ST_RUN | R.ST_LOADING):
            raise IOError('Calibration check requires idle compute')
        if state & required == required:
            return state
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Both DDR channels did not calibrate; status={state:#x}')
        time.sleep(.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--reload', action='store_true', help='Guarded native Vivado load of the frozen SRAM image')
    ap.add_argument('--wait-usb', type=int, default=0)
    args = ap.parse_args()
    if args.wait_usb < 0:
        ap.error('--wait-usb must be nonnegative')
    out = args.out.resolve()
    if out.exists():
        ap.error('Choose a new receipt directory')
    out.mkdir(parents=True)
    receipt = dict(status='STARTING', physical=True, transport='Vivado native JTAG',
                   flash_written=False, programming='NOT_RUN', counter_clear=False,
                   fpga_clocks_changed=False, tck_hz=3000000,
                   started_utc=datetime.now(timezone.utc).isoformat(), full_memory_passes=[])
    hw = bridge = None
    opened = []

    def save():
        p = out/'manifest.json.tmp'
        p.write_text(json.dumps(receipt, indent=2)+'\n')
        p.replace(out/'manifest.json')

    def require(ok, message):
        if not ok:
            raise RuntimeError(message)

    try:
        for owner in ('hw_server', 'openFPGALoader', 'xsdb', 'fxload'):
            require(subprocess.run(['pgrep', '-x', owner], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode != 0, f'Active cable owner: {owner}')
        for port in (3122, 3741):
            with socket.socket() as s:
                require(s.connect_ex(('127.0.0.1', port)) != 0, f'Port already owned: {port}')
        for path in (Path(__file__), CAND/'mig_host.py', ROOT/'opentpu/host/jtag.py'):
            receipt.setdefault('inputs', []).append(dict(path=str(path),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if args.reload:
            receipt['status'] = 'FROZEN_IMAGE_OFFLINE_AUDIT_RUNNING'
            save()
            command = [sys.executable, str(CAND/'check_candidate.py'),
                       '--out', str(out/'offline-audit.json')]
            (out/'offline-audit.command.json').write_text(json.dumps(command, indent=2)+'\n')
            with (out/'offline-audit.log').open('w') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=240)
            receipt['offline_audit_exit'] = result.returncode
            require(result.returncode == 0 and json.loads((out/'offline-audit.json').read_text())
                    ['status'] == 'PASS_MIG_NATIVE_IMAGE_OFFLINE_AUDIT', 'Frozen image audit failed')
        deadline = time.monotonic()+args.wait_usb
        previous_usb = None
        while True:
            usb = subprocess.run(['lsusb'], capture_output=True, text=True, check=True).stdout
            cables = [line for line in usb.splitlines() if 'ID 03fd:' in line]
            require(len(cables) <= 1, 'Multiple cables detected; target is ambiguous')
            receipt.update(status='WAITING_FOR_STABLE_USB',
                           observed_utc=datetime.now(timezone.utc).isoformat(), usb_cables=cables)
            save()
            if cables and (not args.wait_usb or cables == previous_usb):
                receipt['usb_at_start'] = usb
                break
            require(time.monotonic() < deadline, 'USB wait expired; no stable cable')
            previous_usb = cables
            time.sleep(min(5, max(0, deadline-time.monotonic())))
        # Recheck ownership after a potentially long USB wait.
        for owner in ('hw_server', 'openFPGALoader', 'xsdb', 'fxload'):
            require(subprocess.run(['pgrep', '-x', owner], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL).returncode != 0, f'Cable owner appeared: {owner}')
        (out/'bridge.tcl').write_text(TCL)
        with (out/'hw-server.log').open('w') as log:
            hw = subprocess.Popen([str(VIVADO/'hw_server'), '-s', 'tcp::3122'],
                                  stdout=log, stderr=subprocess.STDOUT)
        env = dict(os.environ, OTPU_NATIVE_READY=str(out/'native-ready.txt'))
        if args.reload:
            bit = CAND/'implementation/otpu_mig_jtag.runs/impl_1/otpu_fpga_top_vivado_mig_jtag.bit'
            require(hashlib.sha256(bit.read_bytes()).hexdigest() ==
                    '0863b3e2a7f45b1c75e8229e4d18247baaa73b3bc8746240f14d6199424d4e4f',
                    'Qualified image hash changed')
            env.update(OTPU_NATIVE_BIT=str(bit),
                       OTPU_NATIVE_PROGRAM_STATUS=str(out/'native-program-status.txt'))
        with (out/'vivado.log').open('w') as log:
            bridge = subprocess.Popen([str(VIVADO/'vivado'), '-mode', 'batch', '-nojournal',
                '-nolog', '-source', str(out/'bridge.tcl')], cwd=out, env=env,
                stdout=log, stderr=subprocess.STDOUT)
        receipt.update(status='NATIVE_DRIVER_STARTING', hw_server_pid=hw.pid, vivado_pid=bridge.pid)
        save()
        deadline = time.monotonic()+300
        while not (out/'native-ready.txt').exists():
            require(hw.poll() is None and bridge.poll() is None, 'Native driver startup failed')
            require(time.monotonic() < deadline, 'Native driver startup timeout')
            time.sleep(.5)
        if args.reload:
            require((out/'native-program-status.txt').read_text().strip() == 'INIT=1 DONE=1',
                    'Fresh native programming receipt absent')
            receipt['programming'] = 'PASS_NATIVE_SRAM_INIT_DONE_AND_EXPECTED_MAILBOX'
        spec = importlib.util.spec_from_file_location('qualified_mig_host', CAND/'mig_host.py')
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)

        def factory(*unused):
            link = NativeLink()
            try:
                t = host.MigJtagTransport('localhost', 3741, link=link)
            except BaseException:
                link.close()
                raise
            opened.append(t)
            return t

        from opentpu.host import regs as R, selftest
        t = factory()
        actual = {key: t.reg_read(off) for key, off in
                  [('id', R.R_ID), ('regmap', R.R_REGMAP), ('core_khz', R.R_CORE_KHZ),
                   ('build', R.R_BUILD_ID), ('ddr_mts', R.R_DDR_MTS)]}
        require(actual == dict(id=0x4f545055, regmap=3, core_khz=100000,
                               build=0x5b1e646c, ddr_mts=1066), 'Unexpected loaded image')
        receipt.update(identity=actual, status='WAITING_FOR_DDR_CALIBRATION', calibration_samples=[])
        save()

        def record_calibration(state):
            receipt['calibration_samples'].append(dict(
                observed_utc=datetime.now(timezone.utc).isoformat(), status=state))
            save()

        receipt['calibrated_status'] = wait_for_calibration(t, observe=record_calibration)
        receipt.update(initial_ecc=t.ecc_health(), temperature_c=t.read_die_temperature(),
                       status='FULL_MEMORY_TEST_RUNNING')
        save()
        with (out/'memory.log').open('w') as log, contextlib.redirect_stdout(log):
            for ch in (0, 1):
                for pattern in (1, 2, 3, 0):
                    for read in (False, True):
                        receipt['full_memory_passes'].append(t.bist(ch, pattern, read))
                        save()
        receipt['memory_ecc'] = t.ecc_health()
        t.close()
        opened.clear()
        receipt['status'] = 'FULL_PHYSICAL_SELFTEST_RUNNING'
        save()
        with (out/'selftest.log').open('w') as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            code = selftest.main(['--dev', 'jtag://localhost:3741', '--bw-mib', '1',
                                 '--model', 'lfm2', '--tokens', '8', '--wformat', 'int8'],
                                open_transport=factory)
        receipt['selftest_exit'] = code
        (out/'selftest.exit').write_text(f'{code}\n')
        require(code == 0, 'Physical selftest failed; see selftest.log')
        receipt['final_ecc'] = [t.ecc_health() for t in opened]
        rows = [row for t in opened for row in t.model_checks]
        require(rows and all(row.get('exact_match') and row.get('actual_token_ids') for row in rows),
                'Physical model comparison absent or failed')
        receipt.update(status='PASS_FULL_PHYSICAL_SELFTEST_AND_LFM2', model_checks=rows)
        return 0
    except Exception as error:
        receipt.update(status='FAIL', error=repr(error))
        print(receipt['error'], flush=True)
        return 1
    finally:
        receipt['io_stats'] = [t.io_stats for t in opened]
        receipt.setdefault('model_checks', [row for t in opened for row in t.model_checks])
        for t in opened:
            try:
                offsets = [8, 0x1c, 0x20, 0x24, 0x28, 0x2c, 0x38, 0x3c, 0x40]
                names = ['status', 'issued', 'completed', 'corrected_beats',
                         'uncorrectable_beats', 'bad_beats', 'first_bad_beat',
                         'bad_bits_low', 'bad_bits_high']
                receipt.setdefault('final_channels', []).extend(dict(channel=ch,
                    **dict(zip(names, t.reg_read_many([t.base(ch)+off for off in offsets]))))
                    for ch in (0, 1))
            except Exception as error:
                receipt['final_snapshot_error'] = repr(error)
        for t in opened:
            t.close()
        if bridge is not None:
            if bridge.poll() is None:
                try:
                    link = NativeLink(timeout=5)
                    link.command('QUIT')
                    link.close()
                    bridge.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    bridge.terminate()
                    try:
                        bridge.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        bridge.kill()
                        bridge.wait()
            receipt['vivado_exit'] = bridge.returncode
        if hw is not None:
            hw.terminate()
            try:
                hw.wait(timeout=10)
            except subprocess.TimeoutExpired:
                hw.kill()
                hw.wait()
            receipt['hw_server_exit'] = hw.returncode
        receipt['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    raise SystemExit(main())

