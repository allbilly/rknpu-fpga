"""Loopback RPC/Tcl controls with mocked cable calls; never accesses hardware."""
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

from tools.host.native_link import NativeLink, render_bridge
from tools.host.transport import DeviceBusy, ProtocolError
from tools.hardware.sample_ew import tcl_literal


MOCK = r'''
proc open_hw_manager {} {}
proc connect_hw_server {args} {}
proc get_hw_targets {} {return [list localhost:3125/fixture]}
proc current_hw_target {args} {return localhost:3125/fixture}
proc set_property {key value object} {if {$key ne "PARAM.FREQUENCY" || $value!=3000000} {error "Unexpected mutation"}}
proc open_hw_target {args} {}
proc close_hw_target {} {}
proc disconnect_hw_server {} {}
proc close_hw_manager {} {}
proc get_hw_devices {} {return xc7k480t_0}
proc refresh_hw_device {args} {}
proc get_property {key object} {
    switch -- $key {
        PARAM.FREQUENCY {return 3000000}
        PART {return xc7k480t}
        REGISTER.EFUSE.DNA_PORT {return 004E544714C705C}
        REGISTER.IR.BIT4_INIT_COMPLETE {return 1}
        REGISTER.IR.BIT5_DONE {return 1}
        REGISTER.USR_ACCESS {return 3a0ef75f}
    }
    error "Unexpected property"
}
proc run_state_hw_jtag {state} {if {$state ni {RESET IDLE}} {error "Unexpected state"}}
proc scan_ir_hw_jtag {bits args} {
    set v [lindex $args 1]
    if {$bits!=6 || [expr "0x$v"] ni {3 9 63}} {error "Unsafe instruction reached hardware mock"}
    return 31
}
proc scan_dr_hw_jtag {bits args} {
    if {$bits==32} {return 23751093}
    if {$bits!=640} {error "Unsafe width"}
    return @MOCK_RESPONSE@
}
'''


@unittest.skipUnless(shutil.which('tclsh'), 'Plain Tcl required for mocked RPC')
class NativeRpcTclTests(unittest.TestCase):
    def run_bridge(self, callback, source_tag='3a0ef75f', expected_good=True):
        with tempfile.TemporaryDirectory(prefix='native rpc {;} ') as directory:
            root = Path(directory)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            ready = root/'ready.txt'
            script = root/'mock.tcl'
            # Build a full-width response without relying on Tcl's integer
            # formatter width. This is a protocol test, not numerical evidence.
            reply = f'{0x4f54504a << 536:0160x}'
            self.assertEqual(MOCK.count('@MOCK_RESPONSE@'), 1)
            mocks = MOCK.replace('@MOCK_RESPONSE@', reply)
            script.write_text(mocks+'\n'+render_bridge('localhost:3125/fixture', 'localhost:3125', source_tag, ready, port))
            with (root/'stdout').open('w') as out, (root/'stderr').open('w') as err:
                child = subprocess.Popen([shutil.which('tclsh'), str(script)], stdout=out, stderr=err)
                try:
                    deadline = time.monotonic()+5
                    while not ready.exists() and child.poll() is None and time.monotonic()<deadline:
                        time.sleep(.01)
                    if expected_good:
                        self.assertTrue(ready.exists(), (root/'stderr').read_text())
                        callback(port)
                    else:
                        self.assertFalse(ready.exists())
                    code = child.wait(timeout=5)
                finally:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=5)
            output, errors = (root/'stdout').read_text(), (root/'stderr').read_text()
            if expected_good:
                self.assertEqual(code, 0, output+errors)
                self.assertEqual(errors, '')
                self.assertIn('PASS_NATIVE_USER2_BRIDGE_CLEAN_EXIT', output)
            else:
                self.assertNotEqual(code, 0)

    def test_raw_native_widths_identity_and_orderly_exit(self):
        def client(port):
            link = NativeLink(port=port)
            try:
                link.reset()
                link.scan(9, 6, ir=True)
                self.assertEqual(link.scan(0, 32), 0x23751093)
                link.scan(3, 6, ir=True)
                self.assertEqual(link.scan(0), 0x4f54504a << 536)
                link.shutdown_bridge()
            finally:
                link.close()
        self.run_bridge(client)

    def test_single_owner_and_server_instruction_whitelist(self):
        def client(port):
            link = NativeLink(port=port)
            with self.assertRaises(DeviceBusy):
                NativeLink(port=port)
            with self.assertRaises(ProtocolError):
                link._command('SCAN IR 6 26')
            # Closing/reconnecting does not recover fabric state. This second
            # control owner only exits the mocked bridge; no FPGA is present.
            time.sleep(.02)
            admin = NativeLink(port=port)
            admin.shutdown_bridge()
        self.run_bridge(client)

    def test_wrong_loaded_image_refuses_before_rpc_ready(self):
        self.run_bridge(lambda _: None, source_tag='ffffffff', expected_good=False)

    def test_renderer_rejects_unbound_target_and_malformed_source(self):
        for target, tag, port in [('other/fixture', '3a0ef75f', 3741),
                                  ('localhost:3125/fixture\n', '3a0ef75f', 3741),
                                  ('localhost:3125/fixture', 'bad', 3741),
                                  ('localhost:3125/fixture', '3a0ef75f', True)]:
            with self.subTest(target=target, tag=tag, port=port), self.assertRaises(ValueError):
                render_bridge(target, 'localhost:3125', tag, 'ready', port)


if __name__ == '__main__':
    unittest.main()
