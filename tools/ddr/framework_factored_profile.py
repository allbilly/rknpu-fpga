#!/usr/bin/env python3
"""Explicit 83-source framework profile with six captures and one emitted PPU candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.ddr.framework_profile import source_paths as checked_source_paths

MANIFEST=Path("rtl/ddr/framework_factored/sources.json")

def source_paths(root=ROOT):
    root=Path(root).resolve()
    manifest=json.loads((root/MANIFEST).read_text())
    return checked_source_paths(root,manifest=manifest,expected_count=83)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",required=True,help="validate all 83 ordered paths and exact hashes")
    args=parser.parse_args()
    root=ROOT.resolve();manifest_path=root/MANIFEST
    manifest=json.loads(manifest_path.read_text())
    paths=source_paths(root)
    order_hash=hashlib.sha256(json.dumps([str(p.relative_to(root)) for p in paths],separators=(",",":")).encode()).hexdigest()
    print(json.dumps({"status":"PASS_FACTORED_FRAMEWORK_PUBLIC_PROFILE","manifest_path":str(manifest_path),
        "manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest(),"source_count":len(paths),
        "source_order_sha256":order_hash,"top":manifest["top"],"precision":manifest["precision"],
        "atomic_c":manifest["atomic_c"],"atomic_k":manifest["atomic_k"]},sort_keys=True))

if __name__=="__main__":main()
