#!/usr/bin/env python3
"""Host-side validator for RK3588 capture bundles.

This program never opens the Rocket device and never talks to the board.  It
checks job.json, regcmd.bin, input files, patch indices/kinds, task ranges,
output names, and (when --output-dir is supplied) output overwrite safety.

Usage:
    python3 validate_bundle.py [--output-dir OUT_ROOT] CASE_OR_QUEUE [...]

A CASE_OR_QUEUE may be a case directory containing job.json or a family
directory containing cases/<name>/job.json.  Exit status is 0 only when every
bundle is valid.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from rocket_run import __version__, expand_case_arguments, load_and_validate_case


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate prepared RK3588 Rocket capture bundles without board access."
    )
    parser.add_argument(
        "--output-dir",
        help="optional runner output root; also reject existing capture/output paths",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "cases",
        nargs="+",
        metavar="CASE_OR_QUEUE",
        help=(
            "case directories containing job.json, or family directories "
            "containing cases/<name>/job.json"
        ),
    )
    args = parser.parse_args(argv)

    cases, expand_errors = expand_case_arguments(args.cases)
    bad = False
    for error in expand_errors:
        print(f"FAIL {error}", file=sys.stderr)
        bad = True

    seen_cases: dict[str, Path] = {}
    for case_dir in cases:
        try:
            bundle, errors = load_and_validate_case(case_dir, args.output_dir)
        except Exception as exc:  # noqa: BLE001 - report instead of aborting the queue
            bundle, errors = None, [f"{type(exc).__name__}: {exc}"]
        if bundle is not None and bundle.case in seen_cases:
            errors = list(errors)
            errors.append(
                f"duplicate case name {bundle.case!r}; also used by {seen_cases[bundle.case]}"
            )
            bundle = None
        if errors:
            bad = True
            print(f"FAIL {case_dir}")
            for error in errors:
                print(f"     {error}")
        else:
            assert bundle is not None
            seen_cases[bundle.case] = case_dir
            print(
                f"OK   {case_dir}  case={bundle.case!r} "
                f"tasks={len(bundle.tasks)} buffers={len(bundle.buffers)} "
                f"patches={len(bundle.patches)}"
            )

    if not cases and not expand_errors:
        print("FAIL no cases found", file=sys.stderr)
        bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
