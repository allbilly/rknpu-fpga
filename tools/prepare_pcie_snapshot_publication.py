#!/usr/bin/env python3
"""Validate or materialize the explicit PCIe snapshot/publication source candidate.

This command copies source inputs only. It never runs Vivado or accesses hardware.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "rtl/ddr/pcie_snapshot_publication"
INDEX = PROFILE / "source-index.json"
VALIDATOR = ROOT / "tools/validate_pcie_source_bundle.py"
FULL_SHA = "68cea9679fcb1140e5c1db61027993c0f335fee11386db91921cd4d5a27e322d"
INDEX_SHA = "68463e168f10524f543bf0a823e49239a410b2f1d67358be0d15e4d5b9bfcc6b"
COMPONENT_SHA = "9c9d895d1af9811548a6b534ad40b79c50f6c8eb7a1a7c13f52ffe7e783c9c5a"
COUNTS = {"hdl": 195, "header": 3, "xdc": 2, "component_checkpoint": 1}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def relative(value):
    path = Path(value)
    need(not path.is_absolute() and value and ".." not in path.parts,
         "Unsafe relative source path: " + str(value))
    return path


def bind(inputs, path, expected=None):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "Missing or linked input: " + str(path))
    actual = sha(path)
    need(expected is None or actual == expected, "Input hash mismatch: " + str(path))
    name = str(path.resolve())
    need(name not in inputs or inputs[name] == actual, "Conflicting input: " + name)
    inputs[name] = actual


def collect(component, index_path=None):
    index_path = Path(index_path or INDEX)
    need(index_path.is_file() and not index_path.is_symlink(), "Source index must be a regular file")
    index_digest = sha(index_path)
    need(index_digest == INDEX_SHA, "Source index hash is not the independently reviewed 201-record selection")
    index = json.loads(index_path.read_text())
    need(index.get("schema") == "snapshot-publication-repository-source-index-v1"
         and index.get("source_manifest_sha256") == FULL_SHA, "Wrong source index lineage")
    rows = index["records"]
    need(len(rows) == 201 and index["record_kind_counts"] == COUNTS
         and {kind: sum(row["kind"] == kind for row in rows) for kind in COUNTS} == COUNTS,
         "Source census differs from the selected 201 inputs")
    need([row["order"] for row in rows if row["kind"] == "hdl"] == list(range(195)),
         "HDL compilation order changed")
    need(len({row["relative_path"] for row in rows}) == 201, "Duplicate output source path")
    inputs, selected = {}, []
    for row in rows:
        target = relative(row["relative_path"])
        if row["kind"] == "component_checkpoint":
            need(row["repository_path"] is None and row["sha256"] == COMPONENT_SHA
                 and row["size_bytes"] == 9075034
                 and target.as_posix() == "components/xdma_ooc.dcp",
                 "Only the unchanged selected XDMA component may be supplied externally")
            source = Path(component)
        else:
            source = ROOT / relative(row["repository_path"])
            need(source.resolve().is_relative_to(ROOT), "Source escapes repository")
        bind(inputs, source, row["sha256"])
        need(source.stat().st_size == row["size_bytes"], "Source size changed: " + str(source))
        selected.append((row, source, target))
    recipe = ROOT / relative(index["synth_recipe_path"])
    bind(inputs, recipe, index["synth_recipe_sha256"])
    for path in (index_path, Path(__file__).resolve(), VALIDATOR):
        bind(inputs, path)
    return index, selected, recipe, inputs, index_digest


def prepare(component, output=None, index_path=None):
    index, selected, recipe, inputs, index_digest = collect(component, index_path)
    result = {"status": "PASS_PCIE_CANDIDATE_SOURCE_INPUTS_ONLY", "source_count": 201,
              "record_kind_counts": COUNTS, "source_manifest_sha256": FULL_SHA,
              "source_index_path": str(Path(index_path or INDEX).resolve()),
              "source_index_sha256": index_digest,
              "repository_index_sha256": index_digest, "inputs_before": inputs,
              "vivado_or_model_executed": False, "hardware_accessed": False}
    if output is not None:
        out = Path(output).absolute()
        need(not out.exists() and not out.is_symlink(), "Output directory must be fresh")
        out.mkdir(parents=True)
        for row, source, rel in selected:
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            need(sha(target) == row["sha256"], "Copied source changed: " + str(rel))
        for source, name in ((recipe, "synth.tcl"), (VALIDATOR, "validate_bundle.py")):
            with source.open("rb") as src, (out / name).open("xb") as dst:
                shutil.copyfileobj(src, dst)
        manifest = {"schema": "snapshot-publication-portable-selected-source-manifest-v1",
                    "source_count": 201, "record_kind_counts": COUNTS,
                    "source_manifest_sha256": FULL_SHA,
                    "repository_index_sha256": index_digest,
                    "synth_tcl_sha256": sha(recipe),
                    "records": [{key: row[key] for key in
                                 ("kind", "order", "basename", "relative_path", "sha256", "size_bytes")}
                                for row, _, _ in selected]}
        (out / "source-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        spec = importlib.util.spec_from_file_location("candidate_bundle_validator", VALIDATOR)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        result["bundle_validation"] = validator.validate(out)
        result["status"] = "PASS_PCIE_CANDIDATE_SOURCE_MATERIALIZATION_ONLY"
    result["inputs_after"] = {path: sha(path) for path in inputs}
    need(result["inputs_after"] == inputs, "Source inputs changed during preparation")
    result["inputs_unchanged"] = True
    if output is not None:
        (out / "source-preparation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xdma-component", required=True, type=Path)
    parser.add_argument("--source-index", type=Path, default=INDEX,
                        help="Reviewed source index; only the pinned 201-record index SHA is accepted")
    parser.add_argument("--out", type=Path, help="Fresh source output; omitted for input validation only")
    args = parser.parse_args()
    try:
        result = prepare(args.xdma_component, args.out, args.source_index)
    except (ValueError, OSError, KeyError) as error:
        print("SOURCE_PREPARATION_FAILED: " + str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("inputs_before", "inputs_after")}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
