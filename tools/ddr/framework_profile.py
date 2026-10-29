"""Explicit, hashed source selection for the full512 layout/reset parent.

The framework variants retain historical module names. Use this ordered source
set rather than combining them with the original variants in a recursive glob.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

ROOT=Path(__file__).resolve().parents[2]
MANIFEST='rtl/ddr/framework/sources.json'


class ProfileError(ValueError):
    pass


def source_paths(root=ROOT, *, manifest=None):
    """Return the 68 checked HDL paths, failing before compiler invocation."""
    root=Path(root).resolve()
    if manifest is None:
        manifest=json.loads((root/MANIFEST).read_text())
    def require(condition,message):
        if not condition:raise ProfileError(message)
    require(type(manifest) is dict and set(manifest)==
            {'schema','top','precision','atomic_c','atomic_k','defines','sources'},'Unsupported framework manifest schema')
    require(type(manifest['schema']) is int and manifest['schema']==1 and
            manifest['top']=='rk_jtag_dual_ddr_async' and manifest['precision']=='FP16' and
            manifest['atomic_c']==32 and manifest['atomic_k']==16 and
            manifest['defines']==['DESIGNWARE_NOEXIST','ASSERT_ON'],'Unsupported framework compute profile')
    rows=manifest['sources']
    require(type(rows) is list and len(rows)==68,'Expected 68 ordered framework HDL inputs')
    selected=[]
    for row in rows:
        require(type(row) is dict and set(row)=={'path','sha256'},'Unsupported source binding')
        name,digest=row['path'],row['sha256']
        require(type(name) is str and '\\' not in name and '\x00' not in name,'Invalid HDL path')
        relative=PurePosixPath(name)
        require(bool(relative.parts) and not relative.is_absolute() and relative.as_posix()==name and
                not any(part in ('.','..') for part in relative.parts) and
                relative.parts[0] in ('rtl','fpga') and relative.suffix in ('.sv','.v'),'Escaping or unsupported HDL path')
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}',digest) is not None,'Malformed HDL digest')
        selected.append((root/name,digest))
    require(len({p for p,_ in selected})==68,'Duplicate HDL input')
    for path,digest in selected:
        require(path.resolve()==path and path.is_file(),'Missing or linked HDL input: '+str(path))
        require(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Changed HDL input: '+str(path))
    return [path for path,_ in selected]
