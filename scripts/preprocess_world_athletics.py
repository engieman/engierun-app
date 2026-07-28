#!/usr/bin/env python3
"""Preprocess the MIT World Athletics CSV into pseudonymous JSON Lines.

The generated file is intentionally ignored by git. It remains top-list data and
must not be described as a complete race-history export.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engierun.world_athletics_data import load_world_athletics_results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = load_world_athletics_results(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps({**row, "date": row["date"].isoformat()}, separators=(",", ":")) + "\n")
    print(f"wrote {len(rows)} pseudonymous timed top-list records to {args.output}")


if __name__ == "__main__":
    main()
