"""Independent streaming decoder for complete, successful native USER2 traces.

No transport implementation or device is imported. Consuming the iterator to
EOF is required: an incomplete request, scan error or missing target witness
fails the audit. This helper alone does not qualify model execution or an image.
"""
from pathlib import Path
import json

from tools.ddr.interface import require

MAGIC=0x4f54504a
PAYLOAD_MASK=(1<<512)-1


def commands(path,stats):
    require(not stats,'Fresh scan statistics required')
    stats.update(scans=0,commands=0,idcodes=0,tap_resets=0)
    selected=None;pending=None;retained=None;last_request=None
    with Path(path).open() as stream:
        for line in stream:
            require(line.endswith('\n'),'Incomplete native scan record')
            event=json.loads(line)
            if event.get('event')=='TAP_RESET_NOT_FABRIC_RESET':
                require(stats['scans']==0 and stats['tap_resets']==0 and pending is None,
                        'Unexpected TAP reset or reset with an owned command')
                stats['tap_resets']+=1;continue
            require(stats['tap_resets']==1 and type(event['index']) is int and
                    event['index']==stats['scans'],'Missing reset/nonsequential scan')
            stats['scans']+=1
            require('error' not in event,'Failed native scan cannot qualify a complete run')
            bits=event['bits'];ir=event['ir']
            require(type(bits) is int and bits in (6,32,640) and type(ir) is bool,'Invalid scan shape')
            value=int(event['tdi'],16);response=int(event['tdo'],16)
            require(0<=value<1<<bits and 0<=response<1<<bits,'Raw scan overflow')
            if ir:
                require(bits==6 and value in (3,9,63) and pending is None,'Unsafe/mid-request IR')
                selected=value;continue
            if bits==32:
                require(selected==9 and value==0 and response==0x23751093 and retained is None,
                        'Wrong or late target IDCODE')
                stats['idcodes']+=1;continue
            require(bits==640 and selected==3 and stats['idcodes']==1,'Unexpected DR/instruction/target')
            require(response>>568==0 and (response>>536)&0xffffffff==MAGIC,'Malformed USER2 response')
            seq=(response>>520)&65535;status=(response>>512)&255;payload=response&PAYLOAD_MASK
            current=(seq,status,payload)
            if retained is None:
                require(value==0 and pending is None and status==0,'Missing successful retained response')
                retained=current;last_request=seq;stats['initial_retained_sequence']=seq
            if pending is not None and seq==pending['seq']:
                require(status==0,'Native mailbox command failed')
                op=pending['op']
                require((op==3 or payload<1<<32) and (op not in (2,4) or payload==0),
                        'Unexpected response payload')
                pending['response']=payload;complete=pending;pending=None;retained=current
                stats['commands']+=1
                yield complete
            else:
                require(current==retained,'Unowned or changed retained response')
            if value:
                require(pending is None and value>>604==0 and (value>>572)&0xffffffff==MAGIC,
                        'Overlapping/malformed request')
                op=(value>>548)&255;request_seq=(value>>556)&65535
                address=(value>>512)&0xffffffff;data=value&PAYLOAD_MASK
                require(op in (1,2,3,4) and (value>>544)&15==15 and
                        request_seq==last_request%65535+1,'Request opcode/strobe/sequence changed')
                require((op not in (1,3) or data==0) and (op!=2 or data<1<<32),
                        'Unmodeled request payload')
                last_request=request_seq;pending=dict(op=op,seq=request_seq,address=address,data=data)
    require(pending is None and stats['idcodes']==1 and stats['tap_resets']==1 and retained is not None,
            'Incomplete native request/target history')
