#!/usr/bin/env python3
"""Compile an authorized local Ivy results CSV without any network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Permit direct execution from a source checkout; no package install or network needed.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engierun.ivy_csv import (
    AuthorizationRequiredError,
    IdentityConflictError,
    QualityGateError,
    write_authorized_csv_dataset,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        type=Path,
        help="local canonical CSV path (repeat for multiple files)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/generated/ivy_athletes.json"),
    )
    parser.add_argument(
        "--quality-output",
        type=Path,
        default=Path("data/generated/quality_report.json"),
    )
    parser.add_argument(
        "--confirm-authorized-source",
        action="store_true",
        required=True,
        help="attest that inputs are licensed exports or covered by written permission",
    )
    parser.add_argument(
        "--allow-rejected",
        action="store_true",
        help="publish accepted rows after reviewing missing/invalid rows",
    )
    parser.add_argument(
        "--allow-partial-ivy",
        action="store_true",
        help="publish a partial dataset after reviewing missing school/gender programs",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _, report = write_authorized_csv_dataset(
            args.input,
            args.output,
            args.quality_output,
            authorized=args.confirm_authorized_source,
            allow_rejected=args.allow_rejected,
            allow_partial_ivy=args.allow_partial_ivy,
        )
    except (
        AuthorizationRequiredError,
        FileNotFoundError,
        IdentityConflictError,
        QualityGateError,
        UnicodeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
