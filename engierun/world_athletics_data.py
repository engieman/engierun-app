"""Reader for the MIT-licensed World Athletics top-list dataset.

Source: https://github.com/thomascamminady/world-athletics-database
The raw CSV remains outside the repository; names are replaced with stable IDs.
"""

from __future__ import annotations

import csv
import hashlib
import math
from datetime import date
from pathlib import Path
from typing import Any

TIMED_RUNNING_EVENTS = frozenset(
    {
        "600 Metres",
        "800 Metres",
        "1000 Metres",
        "1500 Metres",
        "One Mile",
        "2000 Metres",
        "Two Miles",
        "3000 Metres",
        "2000 Metres Steeplechase",
        "3000 Metres Steeplechase",
        "5000 Metres",
        "10000 Metres",
        "5 Kilometres",
        "10 Kilometres",
        "10 Miles Road",
        "15 Kilometres",
        "20 Kilometres",
        "Half Marathon",
        "Marathon",
    }
)


def _athlete_id(row: dict[str, str]) -> str:
    identity = "|".join(
        row.get(field, "").strip()
        for field in ("Competitor", "DOB", "Nat", "Sex")
    )
    return "wa_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def load_world_athletics_results(path: str | Path) -> list[dict[str, Any]]:
    """Load valid timed top-list marks, dropping exact duplicate source rows."""
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, float]] = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source, delimiter=";"):
            event = row.get("Event", "").strip()
            if event not in TIMED_RUNNING_EVENTS:
                continue
            try:
                day = date.fromisoformat(row["Date"].strip())
                seconds = float(row["Mark [meters or seconds]"])
            except (KeyError, TypeError, ValueError):
                continue
            if not math.isfinite(seconds) or seconds <= 0:
                continue
            athlete_id = _athlete_id(row)
            key = (athlete_id, event, day.isoformat(), seconds)
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "athlete_id": athlete_id,
                    "event": event,
                    "date": day,
                    "seconds": seconds,
                }
            )
    results.sort(key=lambda item: (item["event"], item["athlete_id"], item["date"], item["seconds"]))
    return results
