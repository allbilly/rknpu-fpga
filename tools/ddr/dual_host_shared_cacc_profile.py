"""Explicit 72-source C32/K16 dual-host profile with shared FP48 pipelines."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.ddr.dual_host_factored_profile import core_source_paths as base_sources

MANIFEST = "rtl/ddr/dual_host_shared_cacc/sources.json"
REPLACEMENTS = {
    "rtl/cmac/rk_cacc_fp16_array.sv": "rtl/cmac/shared_cacc/rk_cacc_fp16_array.sv",
    "rtl/cmac/rk_cmac_array_front.sv": "rtl/cmac/shared_cacc/rk_cmac_array_front.sv",
}


def core_source_paths(root=ROOT):
    """Return exact checked sources, without selecting another default profile."""
    root = Path(root).resolve()
    manifest_path = root / MANIFEST
    if manifest_path.resolve() != manifest_path:
        raise ValueError("Linked shared-CACC manifest")
    manifest = json.loads(manifest_path.read_text())
    if (type(manifest) is not dict or set(manifest) !=
            {"schema", "top", "precision", "atomic_c", "atomic_k", "defines", "sources"} or
            type(manifest["schema"]) is not int or manifest["schema"] != 1 or
            manifest["top"] != "rk_dual_host_ddr" or manifest["precision"] != "FP16" or
            type(manifest["atomic_c"]) is not int or manifest["atomic_c"] != 32 or
            type(manifest["atomic_k"]) is not int or manifest["atomic_k"] != 16 or
            manifest["defines"] != ["DESIGNWARE_NOEXIST", "ASSERT_ON"]):
        raise ValueError("Unsupported shared-CACC source profile")
    # Validate the predecessor source hashes too; only these two explicit
    # substitutions may differ, and every other source must retain its order.
    original = base_sources(root)
    names = [str(path.relative_to(root)) for path in original]
    if sum(name in REPLACEMENTS for name in names) != 2:
        raise ValueError("Changed predecessor source selection")
    expected = [REPLACEMENTS.get(name, name) for name in names]
    rows = manifest["sources"]
    if type(rows) is not list or len(rows) != 72 or len(set(expected)) != 72:
        raise ValueError("Missing or duplicate shared-CACC source")
    paths = []
    for row, name in zip(rows, expected):
        if (type(row) is not dict or set(row) != {"path", "sha256"} or
                row["path"] != name or type(row["sha256"]) is not str or
                re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None):
            raise ValueError("Changed shared-CACC source order or binding")
        path = root / name
        if (path.resolve() != path or not path.is_file() or
                hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]):
            raise ValueError("Missing, linked or changed shared-CACC source: " + name)
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    paths = core_source_paths()
    print(json.dumps({"status": "PASS_SHARED_CACC_DUAL_HOST_PROFILE",
        "source_count": len(paths), "top": "rk_dual_host_ddr", "precision": "FP16",
        "atomic_c": 32, "atomic_k": 16,
        "manifest_sha256": hashlib.sha256((ROOT / MANIFEST).read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
