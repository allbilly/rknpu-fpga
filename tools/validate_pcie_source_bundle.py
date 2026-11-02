#!/usr/bin/env python3
"""Validate an exact portable copy of the selected 201-record RTL/source set."""
import argparse, hashlib, json, pathlib, sys
EXPECTED={"hdl":195,"header":3,"xdc":2,"component_checkpoint":1}
def sha(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()
def validate(root):
    root=pathlib.Path(root).resolve(); mp=root/"source-manifest.json"
    data=json.loads(mp.read_text())
    if data.get("schema")!="snapshot-publication-portable-selected-source-manifest-v1": raise ValueError("manifest schema mismatch")
    rows=data.get("records",[])
    if len(rows)!=201 or data.get("source_count")!=201: raise ValueError("source row count mismatch")
    counts={k:sum(r.get("kind")==k for r in rows) for k in EXPECTED}
    if counts!=EXPECTED or data.get("record_kind_counts")!=EXPECTED: raise ValueError("record-kind census mismatch")
    if [r.get("order") for r in rows if r.get("kind")=="hdl"]!=list(range(195)): raise ValueError("HDL ordering mismatch")
    rels=[r.get("relative_path") for r in rows]
    if len(set(rels))!=201: raise ValueError("duplicate relative path")
    for rel in rels:
        p=pathlib.PurePosixPath(rel)
        if p.is_absolute() or ".." in p.parts: raise ValueError("unsafe relative path: "+str(rel))
    for row in rows:
        p=root.joinpath(*pathlib.PurePosixPath(row["relative_path"]).parts)
        if p.is_symlink() or not p.is_file(): raise ValueError("missing/nonregular source: "+row["relative_path"])
        if sha(p)!=row.get("sha256"): raise ValueError("source hash mismatch: "+row["relative_path"])
        if p.stat().st_size!=row.get("size_bytes"): raise ValueError("source size mismatch: "+row["relative_path"])
    expected=set(rels)
    actual=set()
    for prefix in (root/"sources",root/"components"):
        for p in prefix.rglob("*"):
            if p.is_symlink(): raise ValueError("symlink under source tree")
            if p.is_file(): actual.add(p.relative_to(root).as_posix())
    if actual!=expected: raise ValueError("source file set mismatch")
    component=[r for r in rows if r.get("kind")=="component_checkpoint"]
    if len(component)!=1 or component[0].get("relative_path")!="components/xdma_ooc.dcp": raise ValueError("component checkpoint inventory mismatch")
    if data.get("synth_tcl_sha256")!=sha(root/"synth.tcl"): raise ValueError("synthesis recipe hash mismatch")
    return {"status":"PASS_SOURCE_BUNDLE_HASHES_ONLY","source_count":len(rows),"record_kind_counts":counts,"source_manifest_sha256":sha(mp)}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",default=str(pathlib.Path(__file__).resolve().parent));args=ap.parse_args()
    try: print(json.dumps(validate(args.root),sort_keys=True));return 0
    except Exception as e: print("FAIL_SOURCE_BUNDLE: "+str(e),file=sys.stderr);return 1
if __name__=="__main__": raise SystemExit(main())
