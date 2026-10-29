"""Independent mailbox audit controls; synthetic records only, no FPGA access."""
from pathlib import Path
import json
import tempfile
import unittest

from tools.tinystories.audit_scans import commands


def request(sequence,op,address=0,data=0):
    return (0x4f54504a<<572)|(sequence<<556)|(op<<548)|(15<<544)|(address<<512)|data


def response(sequence,payload=0,status=0):
    return (0x4f54504a<<536)|(sequence<<520)|(status<<512)|payload


def trace(initial=65534):
    rows=[dict(event='TAP_RESET_NOT_FABRIC_RESET')]
    def scan(bits,ir,tdi,tdo):rows.append(dict(index=len(rows)-1,bits=bits,ir=ir,tdi=f'{tdi:x}',tdo=f'{tdo:x}'))
    scan(6,True,9,0);scan(32,False,0,0x23751093);scan(6,True,3,0)
    retained=response(initial,0x10);scan(640,False,0,retained)
    for op,address,data,result in [(1,0,0,0x524b4557),(4,0x10000000,0x1234567890,0),(3,0x10000000,0,0x1234567890)]:
        sequence=initial%65535+1
        scan(640,False,request(sequence,op,address,data),retained)
        scan(640,False,0,retained)
        retained=response(sequence,result);scan(640,False,0,retained);initial=sequence
    return rows


class ScanAuditTests(unittest.TestCase):
    def decode(self,rows,tail=''):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'scans.jsonl'
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows)+tail)
            stats={};decoded=list(commands(path,stats))
            return decoded,stats

    def test_nonzero_retained_sequence_and_wrap_preserve_actual_bytes(self):
        decoded,stats=self.decode(trace())
        self.assertEqual([c['seq'] for c in decoded],[65535,1,2])
        self.assertEqual([c['op'] for c in decoded],[1,4,3])
        self.assertEqual(decoded[-1]['response'],0x1234567890)
        self.assertEqual(stats['initial_retained_sequence'],65534)
        self.assertEqual((stats['commands'],stats['idcodes'],stats['tap_resets']),(3,1,1))

    def test_request_ownership_shape_and_sequence_are_strict(self):
        corruptions={
            'sequence':request(4,1),'strobe':request(65535,1)^(1<<544),
            'opcode':request(65535,5),'read_payload':request(65535,1,data=7),
            'upper_bits':request(65535,1)|(1<<620),
        }
        for name,value in corruptions.items():
            with self.subTest(name=name):
                rows=trace();rows[5]['tdi']=f'{value:x}'
                with self.assertRaises(ValueError):self.decode(rows)
        rows=trace();rows[6]['tdi']=f'{request(1,1):x}'
        with self.assertRaisesRegex(ValueError,'Overlapping'):self.decode(rows)

    def test_response_framing_status_and_retained_bytes_are_strict(self):
        for name,value,index in [
            ('error',response(65535,status=0x80),7),
            ('unowned',response(99),6),('retained_changed',response(65534,0x11),6),
            ('magic',response(65535)^(1<<536),7),
            ('write_payload',response(1,1),10),
        ]:
            with self.subTest(name=name):
                rows=trace();rows[index]['tdo']=f'{value:x}'
                with self.assertRaises(ValueError):self.decode(rows)

    def test_missing_or_failed_terminal_scan_cannot_qualify(self):
        for mode in ('pending','error','partial_row','reset_mid_request','wrong_target','nonsequential'):
            with self.subTest(mode=mode):
                rows=trace();tail=''
                if mode=='pending':rows=rows[:-1]
                elif mode=='error':rows[-1].pop('tdo');rows[-1]['error']="TimeoutError('timed out')"
                elif mode=='partial_row':tail='{"index":'
                elif mode=='reset_mid_request':rows.insert(6,dict(event='TAP_RESET_NOT_FABRIC_RESET'))
                elif mode=='wrong_target':rows[2]['tdo']='12345678'
                else:rows[-1]['index']+=1
                with self.assertRaises((ValueError,json.JSONDecodeError)):self.decode(rows,tail)


if __name__=='__main__':unittest.main()
