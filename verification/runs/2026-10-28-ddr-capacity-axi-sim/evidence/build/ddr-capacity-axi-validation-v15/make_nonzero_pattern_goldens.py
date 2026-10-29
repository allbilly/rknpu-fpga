#!/usr/bin/env python3
"""Generate explicit nonzero-base goldens from the public software pattern oracle."""
from __future__ import annotations
import hashlib,json,pathlib,struct,sys
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.ddr.capacity_pattern import CapacityPlan

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 base=0x1000;span=256;addresses=[base,base+64,base+192];seeds=[0,0x3588c350,0xffffffff];rows=[]
 with (PKG/'nonzero-public-goldens.txt').open('x') as f:
  for seed in seeds:
   plan=CapacityPlan(base=base,size=span,seed=seed)
   for address in addresses:
    for trial in (0,1):
     data=plan.pattern(address,trial);row={'address':address,'seed':seed,'trial':trial,'data_hex':data.hex()}
     rows.append(row);f.write(f'{address:08x} {seed:08x} {trial:d} {int.from_bytes(data,"little"):0128x}\n')
 out=PKG/'nonzero-golden-manifest.json';report={'schema':'ddr-capacity-axi-nonzero-public-pattern-goldens-v1',
  'status':'PREPARED_PUBLIC_SOFTWARE_PATTERN_ORACLE_GOLDENS','base':base,'span_bytes':span,
  'addresses':[f'0x{x:08x}' for x in addresses],'seeds':[f'0x{x:08x}' for x in seeds],'trials':[0,1],
  'line_count':len(rows),'oracle_path':'tools/ddr/capacity_pattern.py',
  'oracle_sha256':sha(ROOT/'tools/ddr/capacity_pattern.py'),'fixture_path':str(PKG/'nonzero-public-goldens.txt'),
  'fixture_sha256':sha(PKG/'nonzero-public-goldens.txt'),'fixture_bytes':(PKG/'nonzero-public-goldens.txt').stat().st_size,
  'rows':rows,'hardware_executed':False,'physical_capacity_qualified':False}
 out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':report['status'],'rows':len(rows),'fixture_sha256':report['fixture_sha256'],'manifest':str(out)},sort_keys=True))
if __name__=='__main__':main()
