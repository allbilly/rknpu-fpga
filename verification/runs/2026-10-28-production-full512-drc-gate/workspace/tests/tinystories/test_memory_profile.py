"""Explicit BRAM/DDR TinyStories transport selection; wire mocks only."""
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

from tools.host.transport import ProtocolError
from tools.tinystories import run_model, run_projection
from tools.tinystories.transport import DualRawTransport
from tools.ddr.dual_transport import DualDdrRawTransport
from tests.ddr.dual_transport.test_transport import WireLink as DdrWireLink
from tests.tinystories.test_transport import Link as BramWireLink


class TinyStoriesMemoryProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='tinystories-memory-profile-')
        self.addCleanup(self.tmp.cleanup)
        env=patch.dict(os.environ,{'OTPU_RUN_DIR':self.tmp.name})
        env.start();self.addCleanup(env.stop)

    def test_default_is_bram_and_factories_select_only_the_requested_class(self):
        model=run_model.build_parser().parse_args([
            '--package','unused-package','--backend','oracle','--out','unused-output'])
        projection=run_projection.build_parser().parse_args([
            '--vectors','unused-vectors','--vectors-sha256','0'*64,'--out','unused-output'])
        self.assertEqual(model.memory_profile,'bram')
        self.assertEqual(projection.memory_profile,'bram')
        self.assertIs(run_model.transport_class('bram'),DualRawTransport)
        self.assertIs(run_model.transport_class('ddr'),DualDdrRawTransport)
        self.assertIs(run_projection.transport_class('bram'),DualRawTransport)
        self.assertIs(run_projection.transport_class('ddr'),DualDdrRawTransport)
        self.assertEqual(run_model.effective_port('bram',None),3741)
        self.assertEqual(run_model.effective_port('ddr',None),3721)
        self.assertEqual(run_model.effective_port('ddr',4555),4555)
        self.assertEqual(run_projection.effective_port('bram',None),3741)
        self.assertEqual(run_projection.effective_port('ddr',None),3721)
        self.assertEqual(run_projection.effective_port('bram',4666),4666)

    def test_transport_identity_metadata_is_the_constructor_verified_namespace_set(self):
        bram=run_model.namespace_identity_metadata('bram')
        ddr=run_model.namespace_identity_metadata('ddr')
        self.assertEqual({k:v['id'] for k,v in bram.items()},
                         {'ew':'0x524b4557','cmac':'0x524b434d'})
        self.assertEqual({k:v['id'] for k,v in ddr.items()},
                         {'ew':'0x524b4144','cmac':'0x524b4344'})
        for profile in ('ew','cmac'):
            self.assertEqual(bram[profile]['abi_version'],0x00010000)
            self.assertEqual(ddr[profile]['abi_version'],0x00010000)
            self.assertTrue(bram[profile]['constructor_readback_verified'])
            self.assertTrue(ddr[profile]['constructor_readback_verified'])

    def test_ddr_model_preflight_requires_both_banks_initialized_before_bo_writes(self):
        link=DdrWireLink()
        transport=DualDdrRawTransport(link.host,link.port,timeout=1,link=link)
        self.addCleanup(transport.close)
        checks=run_model.preflight_memory_transport(transport,'ddr')
        self.assertEqual({k:v['status'] for k,v in checks.items()},{'ew':'0x010','cmac':'0x010'})
        self.assertEqual(checks['ew']['id'],'0x524b4144')
        self.assertEqual(checks['cmac']['id'],'0x524b4344')
        self.assertEqual(transport.profile,'ew')
        self.assertFalse(any(command[0] in (2,3,4) for command in link.commands))
        transport.close()

        link=DdrWireLink();link.registers[0x108]=0
        transport=DualDdrRawTransport(link.host,link.port,timeout=1,link=link)
        self.addCleanup(transport.close)
        with self.assertRaises(ProtocolError):
            run_model.preflight_memory_transport(transport,'ddr')
        self.assertFalse(any(command[0] in (2,3,4) for command in link.commands))
        self.assertTrue(transport._failed)

    def test_bram_preflight_keeps_its_existing_no_extra_wire_checks(self):
        link=BramWireLink()
        transport=DualRawTransport(link.host,link.port,link=link)
        self.addCleanup(transport.close)
        before=len(link.commands)
        self.assertEqual(run_model.preflight_memory_transport(transport,'bram'),{})
        self.assertEqual(len(link.commands),before)

    def test_bram_transport_rejects_ddr_ids_and_ddr_transport_rejects_bram_ids(self):
        # A mismatched board image is rejected by the explicit selected class;
        # there is no retry using the other profile and no write before identity.
        with patch.object(socket,'create_connection',side_effect=AssertionError('TCP must not open')):
            ddr_link=DdrWireLink()
            with self.assertRaises(ProtocolError):
                DualRawTransport(ddr_link.host,ddr_link.port,timeout=1,link=ddr_link)
            self.assertTrue(ddr_link.closed)
            self.assertTrue(ddr_link.commands)
            self.assertTrue(all(command[0]==1 for command in ddr_link.commands))

            bram_link=BramWireLink()
            with self.assertRaises(ProtocolError):
                DualDdrRawTransport(bram_link.host,bram_link.port,timeout=1,link=bram_link)
            self.assertTrue(bram_link.closed)
            self.assertTrue(bram_link.commands)
            self.assertTrue(all(command[0]==1 for command in bram_link.commands))

    def test_cpu_backend_rejects_ddr_before_package_output_or_connection(self):
        for backend in ('fp32-reference','oracle'):
            output=os.path.join(self.tmp.name,'must-not-exist-'+backend)
            with self.subTest(backend=backend), patch.object(
                    socket,'create_connection',side_effect=AssertionError('network must not open')):
                with self.assertRaisesRegex(ValueError,'DDR memory profile requires the explicit jtag backend'):
                    run_model.main(['--package',os.path.join(self.tmp.name,'missing-package'),
                        '--backend',backend,'--memory-profile','ddr','--out',output])
                self.assertFalse(os.path.exists(output))


if __name__=='__main__':unittest.main()
