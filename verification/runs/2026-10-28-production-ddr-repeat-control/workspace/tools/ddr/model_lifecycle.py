"""Read-only raw-command lifecycle checks for positive RKAD/RKCD inference.

No transport, arithmetic, image loader or hardware API is imported.
"""
from tools.ddr.interface import require

IDENTITIES={0:0x524b4144,256:0x524b4344}

def ddr_lifecycle(wire):
    identities=set();ready=set();staged=set();owner=None;done=False;registers=set();release=None;completed=0
    for item in wire:
        op,address,value,response=(item[k] for k in ('op','address','data','response'))
        require(type(op) is int and op in (1,2,3,4),'Unmodeled raw DDR command opcode')
        if op==1 and 0<=address<512:
            base=256 if address>=256 else 0;offset=address-base
            if offset==0:
                require(response==IDENTITIES[base],'Wrong actual DDR namespace identity')
                identities.add(address)
            elif offset==4:
                require(base in identities and response==0x10000,'Wrong DDR namespace ABI/order')
                identities.add(address)
            elif offset==8:
                require(not response & ~0x77f and not response & (8|32),'Faulted/unmodeled DDR status')
                if owner is None:
                    if release is not None:
                        require(base==release and response==16,'ACK did not restore owned DDR readiness')
                        release=None
                    if not staged:
                        require(response==16,'Uninitialized/non-idle DDR inference namespace')
                        ready.add(base)
                    else:
                        require(not response & (2|4|64) and response & 16,'Staged descriptor lost DDR readiness')
                else:
                    require(base==owner,'Peer status read during owned inference')
                    # General memory-ready is deliberately low while the
                    # DDR owner retains a result through readback and ACK.
                    require(not response & 1,'Owned DDR status advertised a new submit')
                    if response & 4:
                        require(not response & (2|64),'Invalid successful DDR completion state')
                        done=True
            elif offset in (28,32,36):
                require(owner==base and done,'Completion snapshot outside successful DDR owner')
                if offset==36:require(response==0,'Nonzero DDR completion error code')
                registers.add(offset)
        elif op==2 and 0<=address<512:
            base=256 if address>=256 else 0;offset=address-base
            if offset in (16,20,24):
                require(owner is None and release is None,'Descriptor writes during retained DDR ownership')
                require(identities=={0,4,256,260} and ready=={0,256},
                        'Descriptor write before both DDR namespaces are admitted')
                staged.add(base)
            elif offset==12 and value==1:
                require(owner is None and release is None and identities=={0,4,256,260} and ready=={0,256},'Submit before both DDR identities/readiness or ACK release')
                require(staged=={base},'Mixed DDR descriptor namespace')
                owner=base;done=False;registers=set();staged=set()
            elif offset==12 and value==2:
                require(owner==base and done and registers=={28,32,36},'ACK before owned validated DDR completion')
                owner=None;release=base;done=False;registers=set();completed+=1
        elif op==4:
            require(owner is None and release is None and not staged and
                    identities=={0,4,256,260} and ready=={0,256},'Upload before healthy DDR admission or during retained ownership')
        elif op==3:
            if owner is not None:
                require(done and registers=={28,32,36},'Owned BO read before validated DDR completion')
            else:require(release is None,'Read before ACK restored initialized DDR memory')
        yield item
    require(owner is None and release is None and not staged and completed>0 and
            identities=={0,4,256,260} and ready=={0,256},
            'Incomplete positive DDR inference lifecycle')
