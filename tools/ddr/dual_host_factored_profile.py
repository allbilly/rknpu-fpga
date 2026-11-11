"""Explicit factored full512 source selection with retained dual-host ownership."""
import argparse
import sys
import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from tools.ddr.framework_profile import source_paths as checked_sources

MANIFEST='rtl/ddr/dual_host_factored/sources.json'
FRONTEND_MANIFEST='rtl/ddr/dual_host_factored/frontend-sources.json'


def source_paths(root=ROOT):
    root=Path(root).resolve()
    manifest=json.loads((root/MANIFEST).read_text())
    bound=checked_sources(root,manifest=manifest,expected_count=68)
    # The framework top instantiates the three-bank layout controller. The
    # predecessor dual-bank admission controller is uninstantiated and has the
    # earlier leaf signature; do not compile that unrelated predecessor here.
    return [path for path in bound if path.name!='rk_dual_job_control_admission.sv']


def core_source_paths(root=ROOT):
    """Return the full same-clock NPU + two-transport frontend source closure."""
    root=Path(root).resolve();paths=source_paths(root)
    manifest=json.loads((root/FRONTEND_MANIFEST).read_text())
    if (type(manifest) is not dict or set(manifest)!=
            {'schema','top','backend_manifest_sha256','sources'} or
            type(manifest['schema']) is not int or manifest['schema']!=1 or
            manifest['top']!='rk_dual_host_ddr' or
            manifest['backend_manifest_sha256']!=hashlib.sha256((root/MANIFEST).read_bytes()).hexdigest()):
        raise ValueError('Unsupported or changed dual-host frontend manifest')
    expected=['rtl/host/rk_axil_frame_mailbox.sv','rtl/host/rk_raw_frame_owner_mux.sv',
              'rtl/host/rk_transport_epoch_guard.sv','rtl/host/rk_pcie_jtag_frame_frontend.sv',
              'rtl/ddr/dual_host/rk_dual_host_ddr.sv']
    if [r.get('path') for r in manifest['sources']]!=expected:
        raise ValueError('Wrong dual-host frontend source order')
    for row in manifest['sources']:
        path=root/row['path']
        if (set(row)!= {'path','sha256'} or path.resolve()!=path or not path.is_file() or
                hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']):
            raise ValueError('Changed or linked dual-host frontend source')
        paths.append(path)
    if len(paths)!=72 or len(set(paths))!=72:
        raise ValueError('Duplicate or missing dual-host core input')
    return paths


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true',required=True)
    parser.parse_args()
    selected=core_source_paths()
    print('PASS factored dual-host source profile:',len(selected),'ordered sources')
