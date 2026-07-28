"""Pure head-to-head personal-best comparison logic."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from numbers import Real
from typing import Any

CANONICAL_EVENT_ORDER = (
    "800m",
    "1000m",
    "1500m",
    "Mile",
    "3000m",
    "5000m",
    "10000m",
)

_TIME_COMPONENT = re.compile(r"\d+(?:\.\d+)?\Z")


def _parse_race_time(mark: Any) -> float | None:
    """Return a positive finite race time in seconds, or ``None`` if invalid."""
    if isinstance(mark, bool):
        return None
    if isinstance(mark, Real):
        seconds = float(mark)
        return seconds if math.isfinite(seconds) and seconds > 0 else None
    if not isinstance(mark, str):
        return None

    text = mark.strip()
    parts = text.split(":")
    if not 1 <= len(parts) <= 3 or any(not _TIME_COMPONENT.fullmatch(part) for part in parts):
        return None

    values = [float(part) for part in parts]
    if len(values) > 1 and values[-1] >= 60:
        return None
    if len(values) == 3 and values[-2] >= 60:
        return None

    seconds = sum(value * (60 ** power) for power, value in enumerate(reversed(values)))
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _ordered_shared_events(a_marks: Mapping[str, Any], b_marks: Mapping[str, Any]) -> list[str]:
    shared = set(a_marks) & set(b_marks)
    canonical = [event for event in CANONICAL_EVENT_ORDER if event in shared]
    canonical_set = set(CANONICAL_EVENT_ORDER)
    return canonical + sorted(shared - canonical_set)


def compare_personal_bests(
    a_marks: Mapping[str, Any], b_marks: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare valid personal bests shared by two athletes.

    Lower times win an event; exact ties award half a point to each athlete.
    Invalid or one-sided marks are excluded from the comparison.
    """
    events: list[dict[str, Any]] = []
    a_points = 0.0
    b_points = 0.0

    for event in _ordered_shared_events(a_marks, b_marks):
        a_seconds = _parse_race_time(a_marks[event])
        b_seconds = _parse_race_time(b_marks[event])
        if a_seconds is None or b_seconds is None:
            continue

        difference_seconds = abs(a_seconds - b_seconds)
        if a_seconds < b_seconds:
            winner = "a"
            a_points += 1
        elif b_seconds < a_seconds:
            winner = "b"
            b_points += 1
        else:
            winner = "tie"
            a_points += 0.5
            b_points += 0.5

        slower_seconds = max(a_seconds, b_seconds)
        events.append(
            {
                "event": event,
                "a_mark": a_marks[event],
                "b_mark": b_marks[event],
                "a_seconds": a_seconds,
                "b_seconds": b_seconds,
                "winner": winner,
                "difference_seconds": difference_seconds,
                "faster_seconds": min(a_seconds, b_seconds),
                "slower_seconds": slower_seconds,
                "percent_faster": difference_seconds / slower_seconds * 100,
            }
        )

    shared_event_count = len(events)
    if shared_event_count:
        a_win_share_percent = a_points / shared_event_count * 100
        b_win_share_percent = b_points / shared_event_count * 100
        a_geometric_time = math.exp(
            sum(math.log(row["a_seconds"]) for row in events) / shared_event_count
        )
        b_geometric_time = math.exp(
            sum(math.log(row["b_seconds"]) for row in events) / shared_event_count
        )
        if math.isclose(a_geometric_time, b_geometric_time, rel_tol=1e-12, abs_tol=1e-12):
            overall_time_edge_winner = "tie"
            overall_time_edge_percent = 0.0
        elif a_geometric_time < b_geometric_time:
            overall_time_edge_winner = "a"
            overall_time_edge_percent = (
                (b_geometric_time - a_geometric_time) / b_geometric_time * 100
            )
        else:
            overall_time_edge_winner = "b"
            overall_time_edge_percent = (
                (a_geometric_time - b_geometric_time) / a_geometric_time * 100
            )
    else:
        a_win_share_percent = b_win_share_percent = 0.0
        overall_time_edge_winner = "tie"
        overall_time_edge_percent = 0.0

    return {
        "events": events,
        "shared_event_count": shared_event_count,
        "a_points": a_points,
        "b_points": b_points,
        "a_win_share_percent": a_win_share_percent,
        "b_win_share_percent": b_win_share_percent,
        "overall_time_edge_winner": overall_time_edge_winner,
        "overall_time_edge_percent": overall_time_edge_percent,
    }
