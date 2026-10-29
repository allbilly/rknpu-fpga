#!/usr/bin/env python3
"""Independently compare the frozen fixture with the public software pattern oracle."""
from __future__ import annotations
import argparse,hashlib,json,pathlib,sys
ROOT=pathlib.Path('/home/fedora/rknpu-fpga');PKG=pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.ddr.capacity_pattern import CapacityPlan

def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--out',type=pathlib.Path,required=True);args=parser.parse_args()
 manifest_path=PKG/'nonzero-golden-manifest.json';manifest=json.loads(manifest_path.read_text());fixture=PKG/'nonzero-public-goldens.txt'
 if sha(ROOT/manifest['oracle_path'])!=manifest['oracle_sha256']:raise SystemExit('public software oracle source changed')
 if sha(fixture)!=manifest['fixture_sha256']:raise SystemExit('golden fixture source changed')
 rows=[line.split() for line in fixture.read_text().splitlines()]
 if len(rows)!=manifest['line_count'] or len(rows)!=18:raise SystemExit('wrong nonzero golden row count')
 checked=0
 for address_hex,seed_hex,trial_text,data_hex in rows:
  address=int(address_hex,16);seed=int(seed_hex,16);trial=int(trial_text)
  plan=CapacityPlan(base=manifest['base'],size=manifest['span_bytes'],seed=seed)
  actual=plan.pattern(address,trial).hex()
  expected=int(data_hex,16).to_bytes(64,'little').hex()
  if actual!=expected:raise SystemExit(f'public software pattern mismatch address={address_hex} seed={seed_hex} trial={trial_text}')
  checked+=1
 result={'schema':'ddr-capacity-axi-public-pattern-reference-check-v1','status':'PASS_PUBLIC_SOFTWARE_NONZERO_PATTERN_GOLDENS',
  'oracle_path':manifest['oracle_path'],'oracle_sha256':manifest['oracle_sha256'],'manifest_sha256':sha(manifest_path),
  'fixture_sha256':sha(fixture),'rows_checked':checked,'base':manifest['base'],'span_bytes':manifest['span_bytes'],
  'hardware_executed':False,'physical_capacity_qualified':False}
 args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');print(json.dumps(result,sort_keys=True))
if __name__=='__main__':main()
